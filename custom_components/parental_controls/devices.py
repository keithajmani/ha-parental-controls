"""A child's devices: the router group's members plus devices picked in the child's options.

Fetched only on demand (Check) or while Live is on (every LIVE_INTERVAL seconds, off by itself after
LIVE_TIMEOUT). Nothing is polled otherwise, and the device list is kept out of the recorder.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Callable

from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CONF_KIND, DOMAIN, KIND_ROUTER, LIVE_INTERVAL, LIVE_TIMEOUT
from .unifi import UniFiAuthError, UniFiClient, UniFiError

_LOGGER = logging.getLogger(__name__)


def router_client(hass: HomeAssistant) -> UniFiClient | None:
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_KIND) == KIND_ROUTER and getattr(e, "runtime_data", None) is not None:
            return e.runtime_data
    return None


class ChildDevices:
    def __init__(self, hass: HomeAssistant, group: str | None, devices: dict[str, dict],
                 notify: Callable[[], None]) -> None:
        self.hass = hass
        self.group = group
        self.configured = {m.lower(): v for m, v in devices.items()}
        self._notify = notify
        self.rows: list[dict] = []
        self.checked: datetime | None = None
        self.error: str | None = None
        self.members: set[str] | None = None    # the group's MACs, once known
        self._live_task: asyncio.Task | None = None

    @property
    def live(self) -> bool:
        return self._live_task is not None and not self._live_task.done()

    async def async_refresh(self) -> None:
        client = router_client(self.hass)
        if client is None:
            self.error = ("No router connected. Connect one for the whole household: Settings → Devices & services → "
                          "Parental Controls → Add hub → Connect a router.")
            self._notify()
            return
        try:
            members = (await client.kid_groups()).get(self.group, []) if self.group else []
            macs = list(dict.fromkeys(members + list(self.configured)))
            clients = await client.live_clients(macs)
        except UniFiAuthError as err:
            self.error = str(err)
            _reauth(self.hass)
            self._notify()
            return
        except UniFiError as err:
            self.error = str(err)
            _LOGGER.warning("Parental Controls: device check failed: %s", err)
            self._notify()
            return
        member_set = self.members = set(members)
        rows = []
        for c in clients:
            cfg = self.configured.get(c.mac, {})
            rows.append({
                "control": self.control(c.mac),
                "name": cfg.get("name") or c.name, "mac": c.mac, "kind": _kind(cfg.get("name") or c.name),
                "online": c.online, "ssid": c.ssid, "ap": c.ap, "signal": c.signal,
                "down_bps": c.down_bps, "up_bps": c.up_bps, "last_seen": c.last_seen,
                "in_group": c.mac in member_set, "block_entity": cfg.get("block_entity"),
            })
        rows.sort(key=lambda r: (not r["online"], r["name"].lower()))
        self.rows, self.error, self.checked = rows, None, dt_util.now()
        self._notify()

    async def async_load_members(self) -> None:
        """Group membership only (cached by the router client), so each picked device's Blocking is known without a
        device check."""
        client = router_client(self.hass)
        if client is None or not self.group:
            return
        try:
            self.members = set((await client.kid_groups()).get(self.group, []))
        except UniFiError:
            return
        self._notify()

    def control(self, mac: str) -> str | None:
        """How a device is controlled: "own" (its own block switch), "group" (follows the child), "stats" (status and
        statistics only). None while group membership isn't known yet."""
        if (self.configured.get(mac) or {}).get("block_entity"):
            return "own"
        if not self.group:
            return "stats"
        if self.members is None:
            return None
        return "group" if mac in self.members else "stats"

    def row(self, mac: str) -> dict | None:
        return next((r for r in self.rows if r["mac"] == mac), None)

    def blocked(self, row: dict) -> bool | None:
        """Individual block state for a controllable device (None when it has no block switch)."""
        e = row.get("block_entity")
        if not e:
            return None
        st = self.hass.states.get(e)
        return st is not None and st.state == STATE_ON

    async def async_set_live(self, on: bool) -> None:
        if on and not self.live:
            self._live_task = self.hass.async_create_background_task(self._live_loop(), f"{DOMAIN} devices live")
        elif not on and self.live:
            self._live_task.cancel()
            self._live_task = None
        self._notify()

    async def _live_loop(self) -> None:
        end = asyncio.get_running_loop().time() + LIVE_TIMEOUT
        try:
            while asyncio.get_running_loop().time() < end:
                await self.async_refresh()
                await asyncio.sleep(LIVE_INTERVAL)
        finally:
            self._live_task = None
            self._notify()

    async def async_stop(self) -> None:
        if self.live:
            self._live_task.cancel()


def _reauth(hass: HomeAssistant) -> None:
    """The router login stopped working: ask for it again (Settings shows a Re-authenticate prompt)."""
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_KIND) == KIND_ROUTER:
            e.async_start_reauth(hass)


def _kind(name: str) -> str:
    n = name.lower()
    for k, words in (("phone", ("iphone", "phone", "pixel", "galaxy")), ("tablet", ("ipad", "tablet", "kobo", "kindle")),
                     ("laptop", ("macbook", "laptop", "chromebook")), ("desktop", (" pc", "desktop", "imac")),
                     ("console", ("xbox", "playstation", "switch", "ps5")),
                     ("speaker", ("echo", "speaker", "homepod", "sonos"))):
        if any(w in n for w in words) or (k == "desktop" and n.endswith("pc")):
            return k
    return "other"
