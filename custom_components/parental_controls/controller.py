"""Glue between the rules engine and Home Assistant for one child (one config entry).

- Loads and saves the child's state with HA's Store, so restarts keep pauses, allow-fors and "allowed tonight".
- Makes the router's block switch match what the rules say, and only touches it when it differs.
- Notices when the switch is changed outside the integration (router app, dashboard toggle) and treats it as
  Allow or Block. Our own changes are recognised by the Context we send them with.
- Re-evaluates every TICK_SECONDS (bedtime starts and ends) and exactly when a pause or allow-for ends.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Callable

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import CALLBACK_TYPE, Context, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DEFAULT_PAUSE_MINUTES, DOMAIN, STORAGE_VERSION, SWITCH_GRACE, TICK_SECONDS
from .engine import Kid, Status

_LOGGER = logging.getLogger(__name__)


class ChildController:
    def __init__(self, hass: HomeAssistant, entry_id: str, name: str, block_entity: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.name = name
        self.block_entity = block_entity
        self.kid = Kid(name)
        self.pause_minutes = DEFAULT_PAUSE_MINUTES
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._override_timer: CALLBACK_TYPE | None = None
        self._own_contexts: set[str] = set()
        self._last: tuple | None = None
        self._bad_since: dict[str, datetime] = {}   # switch entity -> when it was first seen missing / unavailable
        self.devices = None   # ChildDevices, set by __init__   # (status, saved state) after the last update, to spot changes on a tick

    # ---- lifecycle ----------------------------------------------------------------------------------
    async def async_start(self) -> None:
        data = await self._store.async_load()
        if data:
            self.kid = Kid.from_dict({**data["kid"], "name": self.name})
            self.pause_minutes = data.get("pause_minutes", DEFAULT_PAUSE_MINUTES)
        else:
            # First start for this child: adopt the switch's current state, so adding a child who is blocked
            # right now doesn't unblock them.
            st = self.hass.states.get(self.block_entity)
            if st is not None and st.state == STATE_ON:
                self.kid.manual_blocked = True
        self._unsubs.append(async_track_state_change_event(self.hass, [self.block_entity], self._on_switch_change))
        self._unsubs.append(async_track_time_interval(self.hass, self._on_tick, timedelta(seconds=TICK_SECONDS)))
        await self._async_update()   # applies anything that ended while HA was down

    async def async_stop(self) -> None:
        for u in self._unsubs:
            u()
        self._unsubs.clear()
        if self._override_timer:
            self._override_timer()
            self._override_timer = None

    # ---- state for entities -------------------------------------------------------------------------
    def status(self) -> Status:
        return self.kid.status(dt_util.now())

    @callback
    def notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    @callback
    def add_listener(self, cb: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    # ---- actions (buttons, services) ----------------------------------------------------------------
    async def async_block(self) -> None:
        self.kid.block(dt_util.now()); await self._async_update()

    async def async_allow(self) -> None:
        self.kid.allow(dt_util.now()); await self._async_update()

    async def async_pause(self, minutes: int | None = None) -> None:
        self.kid.pause(dt_util.now(), int(minutes or self.pause_minutes)); await self._async_update()

    async def async_set_pause_minutes(self, minutes: int) -> None:
        self.pause_minutes = int(minutes); await self._async_update(apply=False)

    async def async_set_bedtime(self, *, enabled: bool | None = None, weeknight_start: time | None = None,
                                weekend_start: time | None = None, end: time | None = None) -> None:
        b = self.kid.bedtime
        if enabled is not None:
            b.enabled = enabled
        if weeknight_start is not None:
            b.weeknight_start = weeknight_start
        if weekend_start is not None:
            b.weekend_start = weekend_start
        if end is not None:
            b.end = end
        await self._async_update()

    # ---- internals ----------------------------------------------------------------------------------
    async def _async_update(self, apply: bool = True) -> None:
        now = dt_util.now()
        self.kid.tick(now)
        if apply:
            await self._async_apply(now)
        self._schedule_override_end()
        saved = {"kid": self.kid.to_dict(), "pause_minutes": self.pause_minutes}
        await self._store.async_save(saved)
        self._last = (self.kid.status(now), saved)
        for cb in list(self._listeners):
            cb()

    async def _async_apply(self, now: datetime) -> None:
        """Make the router switch match the rules. Only acts on a clear on/off state."""
        want = self.kid.status(now).router_blocked
        st = self.hass.states.get(self.block_entity)
        if st is None or st.state not in (STATE_ON, STATE_OFF):
            _LOGGER.warning("%s: block switch %s is %s; not changing it", self.name, self.block_entity,
                            st.state if st else "missing")
            return
        if (st.state == STATE_ON) == want:
            return
        ctx = Context()
        self._own_contexts.add(ctx.id)
        domain = self.block_entity.split(".", 1)[0]
        await self.hass.services.async_call(domain, "turn_on" if want else "turn_off",
                                            {"entity_id": self.block_entity}, blocking=True, context=ctx)

    @callback
    def _schedule_override_end(self) -> None:
        if self._override_timer:
            self._override_timer()
            self._override_timer = None
        o = self.kid.override
        if o:
            self._override_timer = async_track_point_in_time(self.hass, self._on_override_end, o.ends_at)

    async def _on_override_end(self, _now: datetime) -> None:
        self._override_timer = None
        await self._async_update()

    # ---- repairs ------------------------------------------------------------------------------------
    @callback
    def _check_switches(self, now: datetime) -> None:
        """Raise a Repairs issue when the child's block switch, or a device's own block switch, has been missing or
        unavailable for SWITCH_GRACE (e.g. the router integration or rule was removed). Clears it when it's back."""
        targets = [(f"{self.entry_id}_block_switch", "block_switch_missing", self.block_entity, None)]
        for mac, cfg in (self.devices.configured.items() if self.devices else []):
            if cfg.get("block_entity"):
                targets.append((f"{self.entry_id}_device_{mac.replace(':', '')}", "device_block_switch_missing",
                                cfg["block_entity"], cfg.get("name") or mac))
        for issue_id, key, entity, device in targets:
            st = self.hass.states.get(entity)
            reason = "missing" if st is None else ("unavailable" if st.state in ("unavailable", "unknown") else None)
            if reason is None:
                self._bad_since.pop(entity, None)
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                continue
            since = self._bad_since.setdefault(entity, now)
            if now - since >= SWITCH_GRACE:
                ir.async_create_issue(self.hass, DOMAIN, issue_id, is_fixable=False, severity=ir.IssueSeverity.WARNING,
                                      translation_key=key, translation_placeholders={
                                          "child": self.name, "entity": entity, "reason": reason, "device": device or ""})

    async def _on_tick(self, _now: datetime) -> None:
        self._check_switches(dt_util.now())
        # Bedtime starting or ending changes the status without any stored field changing, so compare the
        # derived status as well as the saved state with what we last applied.
        now = dt_util.now()
        self.kid.tick(now)
        if self._last != (self.kid.status(now), {"kid": self.kid.to_dict(), "pause_minutes": self.pause_minutes}):
            await self._async_update()
        else:
            for cb in list(self._listeners):   # keeps "N min left" fresh on the status sensor
                cb()

    async def _on_switch_change(self, event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        if new is None or new.state not in (STATE_ON, STATE_OFF):
            return
        if new.context.id in self._own_contexts:
            self._own_contexts.discard(new.context.id)
            return
        now = dt_util.now()
        if (new.state == STATE_ON) != self.kid.status(now).router_blocked:
            _LOGGER.info("%s: block switch changed outside Parental Controls (%s); treating it as %s",
                         self.name, new.state, "Block" if new.state == STATE_ON else "Allow")
            self.kid.external_change(now, new.state == STATE_ON)
            await self._async_update(apply=False)
