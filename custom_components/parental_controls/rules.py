"""Router rules behind Home Assistant switches: which switch blocks which group or device, and the router-specific
help shown on the setup screens.

A router type can tell what a switch's rule blocks only if its provider has block_rules() (UniFi: Policy Engine
objects). Otherwise nothing is confirmed and the screens fall back to a picker limited to the router integration's
switches.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_BLOCK_ENTITY, CONF_DEVICES, CONF_KIND, CONF_ROUTER_GROUP, CONF_VENDOR, DOMAIN, KIND_ROUTER
from .provider import DEFAULT_ROUTER_TYPE, ROUTER_TYPES, BlockRule, RouterType
from .unifi import UniFiError

UNKNOWN_TYPE = RouterType(key="", label="", name="", integration=None)


@dataclass
class Router:
    entry: ConfigEntry
    client: Any            # the provider, e.g. UniFiClient; None while the entry isn't loaded
    type: RouterType


def router_entry(hass: HomeAssistant) -> ConfigEntry | None:
    return next((e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_KIND) == KIND_ROUTER), None)


def type_of(entry: ConfigEntry | None) -> RouterType | None:
    if entry is None:
        return None
    return ROUTER_TYPES.get(entry.data.get(CONF_VENDOR) or DEFAULT_ROUTER_TYPE, UNKNOWN_TYPE)


def connected_router(hass: HomeAssistant) -> Router | None:
    entry = router_entry(hass)
    if entry is None:
        return None
    return Router(entry, getattr(entry, "runtime_data", None), type_of(entry))


# ---- help text ------------------------------------------------------------------------------------------
def _help_line(rtype: RouterType | None, kind: str, group: str | None = None) -> str | None:
    if rtype is None:
        return None
    line = rtype.help_group if kind == "group" else rtype.help_device
    return line.format(group=group) if line else None


def help_md(rtype: RouterType | None, kind: str, group: str | None = None) -> str:
    """'' or, as markdown, a paragraph break, then 'On your <router> router' in bold and the router's instruction
    on the next line."""
    line = _help_line(rtype, kind, group)
    return f"\n\n**On your {rtype.name} router**  \n{line}" if line else ""


def help_html(rtype: RouterType | None, kind: str, group: str | None = None) -> str:
    line = _help_line(rtype, kind, group)
    return f"<br><br><b>On your {escape(rtype.name)} router</b><br>{escape(line)}" if line else ""


def alert(kind: str, html: str, title: str | None = None) -> str:
    """An HA alert box inside a flow description (success = green, error = red, warning = amber)."""
    t = f' title="{escape(title)}"' if title else ""
    return f'\n\n<ha-alert alert-type="{kind}"{t}>{html}</ha-alert>'


# ---- rules ----------------------------------------------------------------------------------------------
async def switch_rules(hass: HomeAssistant, fresh: bool = False) -> dict[str, BlockRule] | None:
    """{switch entity_id: rule} for the router integration's switches that turn off internet. None when it can't be
    told: no router, the router type can't map switches to rules, or the router can't be reached."""
    r = connected_router(hass)
    if r is None or r.client is None or not r.type.integration or not hasattr(r.client, "block_rules"):
        return None
    try:
        rules = await r.client.block_rules(max_age=0) if fresh else await r.client.block_rules()
    except UniFiError:
        return None
    return {e.entity_id: rules[e.unique_id] for e in er.async_get(hass).entities.values()
            if e.platform == r.type.integration and e.domain == "switch" and e.unique_id in rules
            and e.disabled_by is None}


async def unswitched_device_rules(hass: HomeAssistant) -> set[str]:
    """MACs that have their own internet-off rule on the router but no enabled switch for it in Home Assistant."""
    r = connected_router(hass)
    if r is None or r.client is None or not r.type.integration or not hasattr(r.client, "block_rules"):
        return set()
    try:
        rules = await r.client.block_rules()
    except UniFiError:
        return set()
    switched = {e.unique_id for e in er.async_get(hass).entities.values()
                if e.platform == r.type.integration and e.domain == "switch" and e.disabled_by is None}
    return {rule.macs[0].lower() for uid, rule in rules.items() if len(rule.macs) == 1 and uid not in switched}


def device_switches(rules: dict[str, BlockRule], mac: str) -> list[str]:
    """Switches whose rule turns off internet for this one device only."""
    return sorted(e for e, rule in rules.items() if {m.lower() for m in rule.macs} == {mac.lower()})


def integration_switches(hass: HomeAssistant, rtype: RouterType | None) -> list[str] | None:
    """The router integration's switches, for the unconfirmed fallback picker. None = no router integration known
    (any switch or toggle helper may be picked)."""
    if rtype is None or not rtype.integration:
        return None
    return sorted(e.entity_id for e in er.async_get(hass).entities.values()
                  if e.platform == rtype.integration and e.domain == "switch")


@dataclass
class SwitchCheck:
    ok: bool
    html: str     # a ready-to-show alert for a flow description


async def check_block_switch(hass: HomeAssistant, entity: str, group: str | None,
                             rules: dict[str, BlockRule] | None = None) -> SwitchCheck | None:
    """Does this switch block the child's router group? None when it can't be checked (no group, no router, a router
    type that can't tell, or a switch that isn't the router's, e.g. a test toggle)."""
    if not group or not entity:
        return None
    r = connected_router(hass)
    ent = er.async_get(hass).async_get(entity)
    if r is None or ent is None or ent.platform != r.type.integration:
        return None
    if rules is None:
        rules = await switch_rules(hass)
    if rules is None:
        return None
    rule = rules.get(entity)
    g = escape(group)
    if rule is not None and group in rule.groups:
        return SwitchCheck(True, alert("success", f"Checked on your router: this switch blocks the group {g}."))
    if rule is None:
        what = "This switch doesn't turn off internet on your router"
    elif rule.groups:
        what = f"This switch blocks the group {escape(', '.join(rule.groups))}, not {g}"
    else:
        what = f"This switch blocks a single device, not the group {g}"
    return SwitchCheck(False, alert("error", f"{what}. Pick the switch that blocks {g}. If there isn't one, your "
                                             f"router needs a rule that turns off internet for the group {g}."
                                    + help_html(r.type, "group", group)))


async def check_children(hass: HomeAssistant) -> list[str]:
    """After the router changed: every child's block switch and device rules that no longer match, as lines."""
    rules = await switch_rules(hass)
    if rules is None:
        return []
    problems = []
    for e in hass.config_entries.async_entries(DOMAIN):
        if e.data.get(CONF_KIND) == KIND_ROUTER:
            continue
        o = {**e.data, **e.options}
        chk = await check_block_switch(hass, o.get(CONF_BLOCK_ENTITY), o.get(CONF_ROUTER_GROUP), rules)
        if chk is not None and not chk.ok:
            problems.append(f"{e.title}: the block switch doesn't block the group {o.get(CONF_ROUTER_GROUP)}")
        for mac, d in (o.get(CONF_DEVICES) or {}).items():
            if d.get("block_entity") and d["block_entity"] not in device_switches(rules, mac):
                problems.append(f"{e.title}: {d.get('name') or mac} has no matching device rule")
    return problems
