"""Router provider interface: what the integration needs from a router. Only UniFi will be implemented at
first; another router (Firewalla, OPNsense, ...) can be added by implementing this without touching the rules.

No Home Assistant imports here either; the HA glue lives elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class Client:
    mac: str
    name: str                 # the router's name for it, or its hostname
    hostname: Optional[str]
    online: bool
    last_seen: Optional[float]
    groups: list[str]         # router groups it belongs to (e.g. "Riley")
    ap: Optional[str] = None
    signal: Optional[int] = None
    down_bps: Optional[int] = None
    up_bps: Optional[int] = None


class RouterProvider(Protocol):
    """Everything is async in the real integration; shown synchronous here for the spec."""

    def search_clients(self, pattern: str) -> list[Client]:
        """Known clients (online or not) whose name, hostname or MAC matches a case-insensitive wildcard,
        e.g. '*kobo*'. Used by the 'pick devices' step of the setup."""

    def kid_groups(self) -> list[str]:
        """Groups that can be used as a kid (e.g. UniFi groups)."""

    def set_kid_blocked(self, kid_group: str, blocked: bool) -> None:
        """Block or allow every device in the kid's group."""

    def kid_blocked(self, kid_group: str) -> Optional[bool]:
        """Current router state, to detect changes made outside Home Assistant. None = unknown."""

    def set_device_blocked(self, mac: str, blocked: bool) -> None:
        """Block or allow one device, whether or not it is in a kid's group."""

    def device_blocked(self, mac: str) -> Optional[bool]:
        ...

    def live_clients(self, macs: list[str]) -> list[Client]:
        """Current status and speeds for these devices, fetched on demand only (Devices card Check / Live)."""
