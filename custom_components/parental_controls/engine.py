"""Parental Controls rules engine: pure Python, no Home Assistant imports.

One `Kid` per child. The parent's intent (manual block, a running pause or allow-for, bedtime, "allowed
tonight") is stored; whether the router should block the kid right now is *derived* from it with
`Kid.status(now)`. The integration's job is only to persist the Kid, call the actions below, call
`tick(now)` periodically (and at start-up), and make the router match `status(now).router_blocked`.

Rules (in priority order) for whether a kid is blocked at a given moment:
  1. A running override wins: a pause blocks, an allow-for allows.
  2. Otherwise bedtime blocks, unless the kid was allowed for the rest of tonight.
  3. Otherwise the manual setting: blocked or allowed.

What Pause means depends on what the kid is doing when you press it:
  - online                 -> pause: blocked for N minutes, then back to whatever applies (online)
  - blocked (manual/bedtime) -> allow-for: online for N minutes, then back to whatever applies (blocked)
  - a pause or allow-for already running -> restart it with the new length

Devices (optional, router-specific listing) follow `device_blocked()`:
  - a device in the kid's group is blocked when the kid is, or when it is individually blocked;
  - a device outside the group ("extra") is only ever blocked individually.
  A device can never be allowed through its kid's block (individual blocks only add restrictions).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Optional

PAUSE = "pause"
ALLOW_FOR = "allow_for"


class State(str, Enum):
    ONLINE = "online"
    PAUSED = "paused"            # override: blocked for a while, then back to the underlying state
    ALLOWED_FOR = "allowed_for"  # override: online for a while, then back to the underlying state
    BEDTIME = "bedtime"
    BLOCKED = "blocked"


@dataclass
class Bedtime:
    enabled: bool = False
    weeknight_start: time = time(21, 0)   # Sun-Thu nights
    weekend_start: time = time(22, 0)     # Fri and Sat nights
    end: time = time(7, 0)                # next morning when end <= start

    def start_for(self, night: datetime) -> time:
        """Start time for the night that begins on `night`'s date (Fri=4, Sat=5 use the weekend start)."""
        return self.weekend_start if night.weekday() in (4, 5) else self.weeknight_start

    def window(self, day: datetime) -> tuple[datetime, datetime]:
        """The bedtime window that starts on `day`'s evening."""
        d = day.replace(hour=0, minute=0, second=0, microsecond=0)
        s = self.start_for(d)
        start = d.replace(hour=s.hour, minute=s.minute)
        end = d.replace(hour=self.end.hour, minute=self.end.minute)
        if end <= start:
            end += timedelta(days=1)
        return start, end

    def active_window(self, now: datetime) -> Optional[tuple[datetime, datetime]]:
        if not self.enabled:
            return None
        for day in (now - timedelta(days=1), now):
            start, end = self.window(day)
            if start <= now < end:
                return start, end
        return None


@dataclass
class Override:
    kind: str            # PAUSE or ALLOW_FOR
    ends_at: datetime


@dataclass
class Status:
    state: State
    router_blocked: bool
    ends_at: Optional[datetime] = None
    then: Optional[State] = None          # what applies when the override ends


@dataclass
class Kid:
    name: str
    manual_blocked: bool = False
    override: Optional[Override] = None
    bedtime: Bedtime = field(default_factory=Bedtime)
    allowed_tonight: bool = False          # set by Allow during bedtime; cleared when a bedtime window starts or ends
    _in_bedtime: Optional[tuple] = None    # the bedtime window we last saw, to detect starts and ends in tick()

    # ---- derived state -------------------------------------------------------------------------------
    def _underlying(self, now: datetime) -> State:
        if self.bedtime.active_window(now) and not self.allowed_tonight:
            return State.BEDTIME
        return State.BLOCKED if self.manual_blocked else State.ONLINE

    def status(self, now: datetime) -> Status:
        base = self._underlying(now)
        o = self.override
        if o and now < o.ends_at:
            st = State.PAUSED if o.kind == PAUSE else State.ALLOWED_FOR
            return Status(st, router_blocked=(o.kind == PAUSE), ends_at=o.ends_at, then=self._underlying(o.ends_at))
        return Status(base, router_blocked=base in (State.BEDTIME, State.BLOCKED))

    # ---- time ---------------------------------------------------------------------------------------
    def tick(self, now: datetime) -> None:
        """Call every minute or so and once at start-up: ends expired overrides and handles bedtime starts/ends,
        including ones missed while Home Assistant was down."""
        win = self.bedtime.active_window(now)
        if win != self._in_bedtime:
            if win is not None:
                # a bedtime window started: it cancels any running pause or allow-for, and tonight starts fresh
                self.override = None
            self.allowed_tonight = False
            self._in_bedtime = win
        if self.override and now >= self.override.ends_at:
            self.override = None

    # ---- actions ------------------------------------------------------------------------------------
    def block(self, now: datetime) -> None:
        """Block until Allow. Cancels any pause or allow-for. Survives the end of bedtime."""
        self.tick(now)
        self.manual_blocked = True
        self.override = None

    def allow(self, now: datetime) -> None:
        """Online now. Cancels any pause or allow-for; during bedtime, allowed for the rest of tonight."""
        self.tick(now)
        self.manual_blocked = False
        self.override = None
        if self.bedtime.active_window(now):
            self.allowed_tonight = True

    def pause(self, now: datetime, minutes: int) -> None:
        """Pause when online; allow-for when blocked; restart when a pause or allow-for is running."""
        if minutes <= 0:
            raise ValueError("minutes must be positive")
        self.tick(now)
        ends = now + timedelta(minutes=minutes)
        cur = self.status(now).state
        if cur == State.PAUSED:
            kind = PAUSE
        elif cur in (State.ALLOWED_FOR, State.BLOCKED, State.BEDTIME):
            kind = ALLOW_FOR
        else:
            kind = PAUSE
        self.override = Override(kind, ends)

    def external_change(self, now: datetime, router_blocked: bool) -> None:
        """The router's block was changed outside the integration (e.g. in the router's app).
        Turning it off counts as Allow; turning it on counts as Block."""
        if router_blocked == self.status(now).router_blocked:
            return
        if router_blocked:
            self.block(now)
        else:
            self.allow(now)

    # ---- persistence --------------------------------------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        w = d.pop("_in_bedtime", None)
        # the bedtime window we were in, so a restart mid-bedtime doesn't look like bedtime just started
        d["in_bedtime"] = [w[0].isoformat(), w[1].isoformat()] if w else None
        for k in ("weeknight_start", "weekend_start", "end"):
            d["bedtime"][k] = d["bedtime"][k].strftime("%H:%M")
        if self.override:
            d["override"] = {"kind": self.override.kind, "ends_at": self.override.ends_at.isoformat()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Kid":
        b = d.get("bedtime", {})
        bt = Bedtime(enabled=b.get("enabled", False),
                     **{k: time.fromisoformat(b[k]) for k in ("weeknight_start", "weekend_start", "end") if k in b})
        o = d.get("override")
        w = d.get("in_bedtime")
        return cls(name=d["name"], manual_blocked=d.get("manual_blocked", False), bedtime=bt,
                   allowed_tonight=d.get("allowed_tonight", False),
                   override=Override(o["kind"], datetime.fromisoformat(o["ends_at"])) if o else None,
                   _in_bedtime=(datetime.fromisoformat(w[0]), datetime.fromisoformat(w[1])) if w else None)


# ---- devices ------------------------------------------------------------------------------------------
@dataclass
class Device:
    mac: str
    name: str
    kid: str
    in_group: bool            # member of the kid's router group (follows the kid's block)
    controllable: bool = False  # has its own block on the router
    blocked: bool = False     # individual block (only meaningful when controllable)


def device_blocked(device: Device, kid_status: Status) -> bool:
    """Whether the router blocks this device. The kid's block always wins for group members;
    an individual block adds a restriction; nothing can allow a device through its kid's block."""
    own = device.controllable and device.blocked
    return own or (device.in_group and kid_status.router_blocked)
