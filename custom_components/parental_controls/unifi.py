"""UniFi router provider (read-only): device search, kid groups, live status and speeds.

Talks to the UniFi Network application on a UniFi OS console (UCG, UDM, UDR, Cloud Key Gen2+) with a local
view-only admin. Blocking itself is done through Home Assistant switches (e.g. the UniFi Network integration's
per-group or per-device switches), so this login never needs write access.

- One login, reused; logs in again only when the console says the session expired (consoles rate-limit logins).
- Group members, known clients and access-point names are cached for 10 minutes.
- Speeds are averaged from each client's byte counters over the last ~20 s. UniFi's own rate fields under-read
  badly on bursts (a 595 Mbps upload showed as 1.4 Mbps), so they are only used for the first sample.
  Wired clients use the wired-* counters. The access point's or switch's tx is the client's download.
"""
from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass, field

import logging

import aiohttp

from .provider import Client

_LOGGER = logging.getLogger(__name__)
CACHE_TTL = 600
RATE_WINDOW = 20
RATE_MIN_SPAN = 4


def unifi_session(hass) -> aiohttp.ClientSession:
    """A session for the UniFi console. Consoles are usually addressed by IP, and aiohttp's default cookie jar
    refuses cookies from IP addresses, which silently loses the login (every request then gets 401)."""
    from homeassistant.helpers.aiohttp_client import async_create_clientsession
    return async_create_clientsession(hass, verify_ssl=False, cookie_jar=aiohttp.CookieJar(unsafe=True))


class UniFiError(Exception):
    """Login failed, console unreachable, or an unexpected reply."""


class UniFiAuthError(UniFiError):
    """Wrong username or password."""


@dataclass
class _Cache:
    at: float = 0.0
    groups: dict[str, list[str]] = field(default_factory=dict)   # group name -> member MACs
    users: dict[str, dict] = field(default_factory=dict)         # MAC -> known client record
    aps: dict[str, str] = field(default_factory=dict)            # AP MAC -> name


class UniFiClient:
    def __init__(self, session: aiohttp.ClientSession, host: str, username: str, password: str,
                 site: str = "default") -> None:
        self._s = session
        self._base = f"https://{host}"
        self._user, self._pw, self._site = username, password, site
        self._csrf: str | None = None
        self._logged_in = False
        self._cache = _Cache()
        self._hist: dict[str, list[tuple[float, int, int]]] = {}

    # ---- HTTP ---------------------------------------------------------------------------------------
    async def login(self) -> None:
        try:
            async with self._s.post(f"{self._base}/api/auth/login", ssl=False,
                                    json={"username": self._user, "password": self._pw, "rememberMe": True}) as r:
                if r.status in (400, 401, 403):
                    # the console's own reason (never contains the password) helps tell a typo from a lockout
                    body = (await r.text())[:200]
                    _LOGGER.warning("UniFi login to %s refused: HTTP %s %s", self._base, r.status, body)
                    raise UniFiAuthError(f"UniFi rejected the login (HTTP {r.status})")
                if r.status == 429:
                    raise UniFiError("UniFi is rate-limiting logins; try again in a few minutes")
                if r.status != 200:
                    raise UniFiError(f"UniFi login failed (HTTP {r.status})")
                self._csrf = r.headers.get("X-CSRF-Token")
        except aiohttp.ClientError as err:
            raise UniFiError(f"Can't reach UniFi at {self._base}: {err}") from err
        self._logged_in = True

    async def _get(self, path: str, retry: bool = True):
        if not self._logged_in:
            await self.login()
        headers = {"X-CSRF-Token": self._csrf} if self._csrf else {}
        try:
            async with self._s.get(f"{self._base}/proxy/network{path}", ssl=False, headers=headers) as r:
                if r.status == 401 and retry:
                    self._logged_in = False
                    return await self._get(path, retry=False)
                if r.status != 200:
                    raise UniFiError(f"UniFi returned HTTP {r.status} for {path}")
                d = await r.json(content_type=None)
        except aiohttp.ClientError as err:
            raise UniFiError(f"Can't reach UniFi: {err}") from err
        return d.get("data", d) if isinstance(d, dict) else d

    async def _cached(self) -> _Cache:
        c = self._cache
        if time.time() - c.at < CACHE_TTL:
            return c
        groups = await self._get(f"/v2/api/site/{self._site}/network-members-groups")
        users = await self._get(f"/api/s/{self._site}/rest/user")
        devices = await self._get(f"/api/s/{self._site}/stat/device")
        self._cache = _Cache(
            at=time.time(),
            groups={g["name"]: [m.lower() for m in g.get("members", [])] for g in groups},
            users={u["mac"].lower(): u for u in users},
            aps={d["mac"].lower(): d.get("name") or d["mac"] for d in devices if d.get("type") == "uap"},
        )
        return self._cache

    async def sites(self) -> dict[str, str]:
        """Sites on this console: {site id (e.g. "default"): description}. Most homes have one."""
        if not self._logged_in:
            await self.login()
        headers = {"X-CSRF-Token": self._csrf} if self._csrf else {}
        try:
            async with self._s.get(f"{self._base}/proxy/network/api/self/sites", ssl=False, headers=headers) as r:
                if r.status != 200:
                    raise UniFiError(f"UniFi returned HTTP {r.status} for the site list")
                d = await r.json(content_type=None)
        except aiohttp.ClientError as err:
            raise UniFiError(f"Can't reach UniFi: {err}") from err
        return {x["name"]: x.get("desc") or x["name"] for x in d.get("data", [])}

    def use_site(self, site: str) -> None:
        self._site = site

    # ---- provider API -------------------------------------------------------------------------------
    async def kid_groups(self) -> dict[str, list[str]]:
        return dict((await self._cached()).groups)

    async def search_clients(self, pattern: str) -> list[Client]:
        """Known clients (online or not) whose name, hostname or MAC matches the wildcard, case-insensitive.
        A pattern without * or ? matches anywhere ("kobo" = "*kobo*")."""
        c = await self._cached()
        live = {s["mac"].lower(): s for s in await self._get(f"/api/s/{self._site}/stat/sta")}
        pat = pattern.strip().lower() or "*"
        if not any(ch in pat for ch in "*?["):
            pat = f"*{pat}*"
        out = []
        for mac in set(c.users) | set(live):
            u, s = c.users.get(mac, {}), live.get(mac, {})
            name = s.get("name") or u.get("name") or s.get("hostname") or u.get("hostname") or mac
            host = s.get("hostname") or u.get("hostname")
            if not any(fnmatch.fnmatch(str(x).lower(), pat) for x in (name, host, mac) if x):
                continue
            out.append(Client(mac=mac, name=name, hostname=host, online=mac in live,
                              last_seen=s.get("last_seen") or u.get("last_seen"),
                              groups=[g for g, members in c.groups.items() if mac in members]))
        out.sort(key=lambda x: (not x.online, x.name.lower()))
        return out

    async def live_clients(self, macs: list[str]) -> list[Client]:
        """Current status and averaged speeds for these MACs. One request when the cache is warm."""
        c = await self._cached()
        live = {s["mac"].lower(): s for s in await self._get(f"/api/s/{self._site}/stat/sta")}
        now = time.time()
        out = []
        for mac in dict.fromkeys(m.lower() for m in macs):
            u, s = c.users.get(mac, {}), live.get(mac)
            name = (s or {}).get("name") or u.get("name") or (s or {}).get("hostname") or u.get("hostname") or mac
            down = up = None
            if s:
                down, up = self._rates(mac, s, now)
            out.append(Client(mac=mac, name=name, hostname=(s or {}).get("hostname") or u.get("hostname"),
                              online=s is not None, last_seen=(s or {}).get("last_seen") or u.get("last_seen"),
                              groups=[g for g, members in c.groups.items() if mac in members],
                              ap=c.aps.get(((s or {}).get("ap_mac") or "").lower()) if s else None,
                              signal=(s or {}).get("signal"), down_bps=down, up_bps=up,
                              ssid=(s or {}).get("essid") or ("wired" if s and s.get("is_wired") else None)))
        return out

    def _rates(self, mac: str, s: dict, now: float) -> tuple[int | None, int | None]:
        w = "wired-" if s.get("is_wired") else ""
        tx, rx = s.get(w + "tx_bytes"), s.get(w + "rx_bytes")
        if tx is None or rx is None:
            return None, None
        h = [x for x in self._hist.get(mac, []) if 0 < now - x[0] <= RATE_WINDOW and x[1] <= tx and x[2] <= rx]
        self._hist[mac] = (h + [(now, tx, rx)])[-8:]
        if h and now - h[0][0] >= RATE_MIN_SPAN:
            span = now - h[0][0]
            return round((tx - h[0][1]) * 8 / span), round((rx - h[0][2]) * 8 / span)
        return round(s.get(w + "tx_bytes-r", 0) * 8), round(s.get(w + "rx_bytes-r", 0) * 8)
