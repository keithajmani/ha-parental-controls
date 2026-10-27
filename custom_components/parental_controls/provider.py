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
    ssid: Optional[str] = None


@dataclass
class BlockRule:
    """A router rule that turns off internet, as seen behind one of Home Assistant's switches."""
    name: str
    groups: list[str]         # group names it targets (a group rule)
    macs: list[str]           # device MACs it targets (a device rule)


@dataclass(frozen=True)
class RouterType:
    """What the setup screens need to know about a kind of router. The help lines are optional: a router type
    without them shows only the general sentence."""
    key: str
    label: str                       # in the router type list
    name: str                        # "UniFi", as in "On your UniFi router"
    integration: Optional[str]       # the HA integration whose switches turn this router's rules on and off
    help_device: Optional[str] = None
    help_group: Optional[str] = None  # may use {group}


ROUTER_TYPES = {
    "unifi": RouterType(
        key="unifi", label="UniFi (UniFi OS console)", name="UniFi", integration="unifi",
        help_device="Add a Policy Engine object for that device, set to No Internet.",
        help_group="Add a Policy Engine object for the group {group}, set to No Internet."),
}
DEFAULT_ROUTER_TYPE = "unifi"   # router entries saved before the type was stored are UniFi


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
        """Current status and speeds for these devices, fetched on demand only (Live, or the Check devices button)."""

    def block_rules(self) -> dict[str, BlockRule]:
        """Optional. The router's internet-off rules keyed by the unique_id of the Home Assistant switch that turns
        each one on (in the integration named by RouterType.integration). Lets the setup confirm that a switch
        blocks the child's group, or exactly one device. Providers without it get an unconfirmed switch picker."""
