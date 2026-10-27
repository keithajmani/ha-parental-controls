"""Setup.

Add integration → Parental Controls offers two kinds of entry:
- "Add a child": name, the router switch that blocks the child's group, and (with a router connected) which router
  group is the child's, so its devices can be listed. One entry per child, any number of children.
- "Connect a router": the router type, then the console and a view-only login, used for device search, the Devices
  list and checking which switch blocks what. Blocking never needs it: blocks go through Home Assistant switches.
  The router entry can be reconfigured (type, address, login) and asks to re-authenticate when the login stops working.

A child's options: the block switch and group (checked against the router's rules where the router can tell), add
devices (wildcard search, then pick under group headings), and the Devices list (untick to remove). After picking,
the Device blocking step shows how each device will be controlled: by the child's group, by its own router rule
(a switch whose rule targets just that device), or status and statistics only.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (CONF_BLOCK_ENTITY, CONF_CHILD_NAME, CONF_DEVICES, CONF_HOST, CONF_KIND, CONF_PASSWORD,
                    CONF_PATTERN, CONF_ROUTER_GROUP, CONF_SITE, CONF_USERNAME, CONF_VENDOR, DOMAIN,
                    KIND_CHILD, KIND_ROUTER)
from .devices import router_client
from .provider import DEFAULT_ROUTER_TYPE, ROUTER_TYPES
from .rules import (alert, check_block_switch, check_children, connected_router, device_switches, help_md,
                    unswitched_device_rules,
                    integration_switches, switch_rules, type_of)
from .unifi import UniFiAuthError, UniFiClient, UniFiError, unifi_session

LEVEL = "Can be blocked"
STATUS = "Status & traffic only"

# any on/off entity works as a block switch: a router integration's switch, or an input_boolean for testing
BLOCK_SELECTOR = selector.EntitySelector(selector.EntitySelectorConfig(domain=["switch", "input_boolean"]))


async def _group_selector(hass) -> selector.SelectSelector | None:
    client = router_client(hass)
    if client is None:
        return None
    try:
        groups = sorted(await client.kid_groups())
    except UniFiError:
        return None
    return selector.SelectSelector(selector.SelectSelectorConfig(options=groups, custom_value=True,
                                                                 mode=selector.SelectSelectorMode.DROPDOWN))


def _type_selector(default: str) -> dict:
    return {vol.Required(CONF_VENDOR, default=default): selector.SelectSelector(selector.SelectSelectorConfig(
        options=[selector.SelectOptionDict(value=k, label=t.label) for k, t in ROUTER_TYPES.items()],
        mode=selector.SelectSelectorMode.LIST))}


def _password_selector() -> selector.TextSelector:
    return selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


async def _test_login(hass, host: str, username: str, password: str) -> tuple[dict[str, str] | None, str | None]:
    """(sites, None) when the login works, else (None, error key)."""
    client = UniFiClient(unifi_session(hass), host, username, password)
    try:
        await client.login()
        return await client.sites(), None
    except UniFiAuthError:
        return None, "invalid_auth"
    except UniFiError:
        return None, "cannot_connect"


class _SwitchCheckMixin:
    """Block switch check shared by Add a child and Block switch and router group: a green note when the router
    confirms the switch blocks the group, a red one when it doesn't. A mismatch is saved only when submitted again
    unchanged (e.g. a test toggle on purpose)."""
    _shown: tuple | None = None

    async def _check(self, entity: str | None, group: str | None) -> tuple[str, bool]:
        chk = await check_block_switch(self.hass, entity, group)
        return ("", True) if chk is None else (chk.html, chk.ok)

    async def _accept(self, entity: str, group: str | None) -> tuple[bool, str]:
        html, ok = await self._check(entity, group)
        accept = ok or self._shown == (entity, group)
        self._shown = (entity, group)
        return accept, html


class ParentalControlsConfigFlow(_SwitchCheckMixin, ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["child", "router"])

    async def async_step_child(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        check = ""
        if user_input is not None:
            name = user_input[CONF_CHILD_NAME].strip()
            await self.async_set_unique_id(slugify(name))
            self._abort_if_unique_id_configured()
            used = {{**e.data, **e.options}.get(CONF_BLOCK_ENTITY) for e in self._async_current_entries()}
            group = user_input.get(CONF_ROUTER_GROUP) or None
            if user_input[CONF_BLOCK_ENTITY] in used:
                errors[CONF_BLOCK_ENTITY] = "switch_in_use"
            else:
                ok, check = await self._accept(user_input[CONF_BLOCK_ENTITY], group)
                if ok:
                    data = {CONF_KIND: KIND_CHILD, CONF_CHILD_NAME: name,
                            CONF_BLOCK_ENTITY: user_input[CONF_BLOCK_ENTITY]}
                    if group:
                        data[CONF_ROUTER_GROUP] = group
                    return self.async_create_entry(title=name, data=data)
                errors["base"] = "switch_mismatch"
        schema = {vol.Required(CONF_CHILD_NAME): str, vol.Required(CONF_BLOCK_ENTITY): BLOCK_SELECTOR}
        if (groups := await _group_selector(self.hass)) is not None:
            schema[vol.Optional(CONF_ROUTER_GROUP)] = groups
        schema = vol.Schema(schema)
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="child", errors=errors, data_schema=schema,
                                    description_placeholders={"check": check})

    # ---- router -----------------------------------------------------------------------------------------
    async def async_step_router(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick the router type. Only UniFi so far; others plug in behind the same provider interface."""
        await self.async_set_unique_id("router")
        self._abort_if_unique_id_configured()
        if user_input is not None:
            self._vendor = user_input[CONF_VENDOR]
            return await self.async_step_unifi()
        return self.async_show_form(step_id="router", data_schema=vol.Schema(_type_selector(DEFAULT_ROUTER_TYPE)))

    async def async_step_unifi(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            sites, err = await _test_login(self.hass, user_input[CONF_HOST], user_input[CONF_USERNAME],
                                           user_input[CONF_PASSWORD])
            if err:
                errors["base"] = err
            else:
                self._login = user_input
                self._sites = sites
                if len(sites) <= 1:   # most homes: one site, picked automatically
                    return await self._async_finish_unifi(next(iter(sites), "default"))
                return await self.async_step_site()
        return self.async_show_form(step_id="unifi", errors=errors, data_schema=vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): _password_selector(),
        }))

    async def async_step_site(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Only shown when the console manages more than one site."""
        if user_input is not None:
            return await self._async_finish_unifi(user_input[CONF_SITE])
        return self.async_show_form(step_id="site", data_schema=vol.Schema({
            vol.Required(CONF_SITE): selector.SelectSelector(selector.SelectSelectorConfig(
                options=[selector.SelectOptionDict(value=k, label=v) for k, v in self._sites.items()]))}))

    async def _async_finish_unifi(self, site: str) -> ConfigFlowResult:
        client = UniFiClient(unifi_session(self.hass), self._login[CONF_HOST],
                             self._login[CONF_USERNAME], self._login[CONF_PASSWORD], site)
        try:
            await client.kid_groups()
        except UniFiError:
            return self.async_abort(reason="cannot_connect")
        return self.async_create_entry(title=f"UniFi ({self._login[CONF_HOST]})",
                                       data={CONF_KIND: KIND_ROUTER, CONF_VENDOR: self._vendor, **self._login,
                                             CONF_SITE: site})

    # ---- router: reconfigure and re-authenticate ---------------------------------------------------------
    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Router type first (the next step asks for the connection details)."""
        entry = self._get_reconfigure_entry()
        if entry.data.get(CONF_KIND) != KIND_ROUTER:
            return self.async_abort(reason="child_use_configure")
        if user_input is not None:
            self._vendor = user_input[CONF_VENDOR]
            return await self.async_step_reconfigure_connection()
        return self.async_show_form(step_id="reconfigure",
                                    data_schema=vol.Schema(_type_selector(type_of(entry).key or DEFAULT_ROUTER_TYPE)))

    async def async_step_reconfigure_connection(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Address, username and password; an empty password keeps the current one. Tested before it's saved."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            login = {CONF_HOST: user_input[CONF_HOST].strip(), CONF_USERNAME: user_input[CONF_USERNAME],
                     CONF_PASSWORD: user_input.get(CONF_PASSWORD) or entry.data[CONF_PASSWORD]}
            sites, err = await _test_login(self.hass, **login)
            if err:
                errors["base"] = err
            else:
                site = entry.data.get(CONF_SITE, "default")
                if site not in sites:
                    site = next(iter(sites), "default")
                type_changed = (entry.data.get(CONF_VENDOR) or DEFAULT_ROUTER_TYPE) != self._vendor
                self.hass.config_entries.async_update_entry(
                    entry, title=f"UniFi ({login[CONF_HOST]})",
                    data={**entry.data, **login, CONF_VENDOR: self._vendor, CONF_SITE: site})
                await self.hass.config_entries.async_reload(entry.entry_id)
                if type_changed and (problems := await check_children(self.hass)):
                    return self.async_abort(reason="reconfigure_mismatch",
                                            description_placeholders={"problems": "\n".join(f"- {p}" for p in problems)})
                return self.async_abort(reason="reconfigure_successful")
        return self.async_show_form(step_id="reconfigure_connection", errors=errors, data_schema=vol.Schema({
            vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST, "")): str,
            vol.Required(CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")): str,
            vol.Optional(CONF_PASSWORD): _password_selector(),
        }))

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            _sites, err = await _test_login(self.hass, entry.data[CONF_HOST], user_input[CONF_USERNAME],
                                            user_input[CONF_PASSWORD])
            if err:
                errors["base"] = err
            else:
                return self.async_update_reload_and_abort(entry, data_updates={
                    CONF_USERNAME: user_input[CONF_USERNAME], CONF_PASSWORD: user_input[CONF_PASSWORD]})
        return self.async_show_form(step_id="reauth_confirm", errors=errors,
                                    description_placeholders={"host": entry.data.get(CONF_HOST, "")},
                                    data_schema=vol.Schema({
                                        vol.Required(CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")): str,
                                        vol.Required(CONF_PASSWORD): _password_selector()}))

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        return config_entry.data.get(CONF_KIND, KIND_CHILD) == KIND_CHILD

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ChildOptionsFlow()


class ChildOptionsFlow(_SwitchCheckMixin, OptionsFlow):
    def __init__(self) -> None:
        self._found: dict[str, Any] = {}        # MAC -> Client from the search
        self._fields: dict[str, list[str]] = {}  # field label -> MACs it offers
        self._block: list[str] = []             # MACs shown on the Device blocking step
        self._names: dict[str, str] = {}
        self._groups: dict[str, list[str]] = {}  # MAC -> router groups it is in
        self._kept: dict[str, dict] | None = None

    def _opts(self) -> dict:
        return {**self.config_entry.data, **self.config_entry.options}

    @property
    def _child(self) -> str:
        return self.config_entry.data[CONF_CHILD_NAME]

    def _save(self, **changes) -> ConfigFlowResult:
        keep = {k: v for k, v in self.config_entry.options.items()}
        return self.async_create_entry(data={**keep, **changes})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        n = len(self._opts().get(CONF_DEVICES) or {})
        return self.async_show_menu(step_id="init", menu_options=["settings", "add_devices", "devices"],
                                    description_placeholders={"devices": str(n) if n else "none"})

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        o = self._opts()
        errors: dict[str, str] = {}
        if user_input is not None:
            group = user_input.get(CONF_ROUTER_GROUP) or None
            ok, check = await self._accept(user_input[CONF_BLOCK_ENTITY], group)
            if ok:
                return self._save(**{CONF_BLOCK_ENTITY: user_input[CONF_BLOCK_ENTITY], CONF_ROUTER_GROUP: group})
            errors["base"] = "switch_mismatch"
            values = user_input
        else:
            values = {CONF_BLOCK_ENTITY: o[CONF_BLOCK_ENTITY], CONF_ROUTER_GROUP: o.get(CONF_ROUTER_GROUP)}
            check, _ok = await self._check(values[CONF_BLOCK_ENTITY], values[CONF_ROUTER_GROUP])
            self._shown = (values[CONF_BLOCK_ENTITY], values[CONF_ROUTER_GROUP])
        schema = {vol.Required(CONF_BLOCK_ENTITY): BLOCK_SELECTOR}
        groups = await _group_selector(self.hass)
        schema[vol.Optional(CONF_ROUTER_GROUP)] = groups if groups is not None else str
        return self.async_show_form(
            step_id="settings", errors=errors, description_placeholders={"check": check},
            data_schema=self.add_suggested_values_to_schema(vol.Schema(schema),
                                                            {k: v for k, v in values.items() if v}))

    # ---- add devices: search, pick, device blocking ------------------------------------------------------
    async def async_step_add_devices(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 1: wildcard search of the router's known devices."""
        client = router_client(self.hass)
        if client is None:
            return self.async_abort(reason="no_router")
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                found = await client.search_clients(user_input[CONF_PATTERN])
            except UniFiError:
                errors["base"] = "cannot_connect"
            else:
                if not found:
                    errors[CONF_PATTERN] = "no_match"
                else:
                    self._pattern = user_input[CONF_PATTERN]
                    self._found = {c.mac: c for c in found[:100]}
                    return await self.async_step_pick()
        return self.async_show_form(step_id="add_devices", errors=errors,
                                    data_schema=vol.Schema({vol.Required(CONF_PATTERN, default="*"): str}))

    def _headings(self, macs: list[str], groups: dict[str, list[str]]) -> dict[str, list[str]]:
        """Group headings, the child's group first, then other groups, then devices in no group."""
        mine = self._opts().get(CONF_ROUTER_GROUP)
        own, other, none = [], {}, []
        for m in macs:
            gs = groups.get(m) or []
            if mine and mine in gs:
                own.append(m)
            elif gs:
                other.setdefault(sorted(gs)[0], []).append(m)
            else:
                none.append(m)
        out = {}
        if own:
            out[f"In {self._child}'s group"] = own
        for g in sorted(other):
            out[f"In the “{g}” group"] = other[g]
        if none:
            out["Not in any group"] = none
        return out

    async def async_step_pick(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 2: tick devices under two headings. Device level blocking: in the child's group, or with its own block
        rule on the router that Home Assistant has a switch for. Status & traffic only: everything else. Nothing is
        ticked to start with. When the router can tell which switch blocks a device, that's saved directly; when it
        can't, the Device blocking step asks."""
        errors: dict[str, str] = {}
        child, mine = self._child, self._opts().get(CONF_ROUTER_GROUP)
        rules = await switch_rules(self.hass)
        own = {m: device_switches(rules, m) for m in self._found} if rules is not None else {}
        no_switch = await unswitched_device_rules(self.hass) if rules is not None else set()
        level, status = {}, []
        for m, c in self._found.items():
            if mine and mine in c.groups:
                level[m] = f"{child}'s group"
            elif own.get(m):
                level[m] = "own block rule"
            else:
                status.append(m)
        self._fields = {}
        if level:
            self._fields[LEVEL] = list(level)
        if status:
            self._fields[STATUS] = status
        if user_input is not None:
            picked = [m for label in self._fields for m in user_input.get(label, [])]
            if picked:
                self._names = {m: self._found[m].name for m in self._found}
                self._groups = {m: self._found[m].groups for m in self._found}
                self._block = picked
                if rules is None:
                    return await self.async_step_block()
                devices = dict(self._opts().get(CONF_DEVICES) or {})
                for m in picked:
                    sw = own.get(m) or []
                    devices[m] = {"name": self._names[m], "block_entity": sw[0] if sw else None, "confirmed": bool(sw)}
                return self._save(**{CONF_DEVICES: devices})
            errors["base"] = "none_picked"

        dupes = _duplicate_names({m: c.name for m, c in self._found.items()})

        def line(m: str) -> str:
            # the router's own name is enough to find it in the router's app; the MAC only tells two same-named apart
            c = self._found[m]
            how = f" \u00b7 {level[m]}" if m in level else (" \u00b7 rule has no switch in HA" if m in no_switch else "")
            mac = f" \u00b7 {m}" if m in dupes else ""
            return f"{c.name} \u00b7 {'online' if c.online else 'offline'}{mac}{how}"

        schema = {}
        for label, macs in self._fields.items():
            schema[vol.Optional(label, default=[])] = selector.SelectSelector(selector.SelectSelectorConfig(
                options=[selector.SelectOptionDict(value=m, label=line(m)) for m in macs],
                multiple=True, mode=selector.SelectSelectorMode.LIST))
        return self.async_show_form(step_id="pick", errors=errors, data_schema=vol.Schema(schema),
                                    description_placeholders={
                                        "count": str(len(self._found)), "pattern": self._pattern, "child": child,
                                        # placeholders of the v0.5.3 text, for a browser still holding it in cache
                                        "notes": "", "router_help": ""})

    def _rtype(self):
        r = connected_router(self.hass)
        return r.type if r else None

    async def async_step_block(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 3, Device blocking: how each device will be controlled. A device whose own router rule was found
        gets a block switch field (limited to the switches whose rule targets just that device); a router type that
        can't tell gets an unconfirmed picker limited to its integration's switches."""
        child, mine = self._child, self._opts().get(CONF_ROUTER_GROUP)
        rules = await switch_rules(self.hass)
        current = self._opts().get(CONF_DEVICES) or {}
        fields: dict[str, str] = {}      # field label -> MAC
        lines, any_stats = [], False
        schema = {}
        for mac in self._block:
            name = self._names.get(mac) or current.get(mac, {}).get("name") or mac
            in_group = bool(mine and mine in (self._groups.get(mac) or []))
            if rules is not None:
                options = device_switches(rules, mac)
                confirmed = True
            else:
                options = integration_switches(self.hass, self._rtype())
                confirmed = False
            if options or (options is None and not confirmed):
                label = f"{name}: block switch" + ("" if confirmed else " (not confirmed)")
                if label in fields:
                    label = f"{name} ({mac}): block switch" + ("" if confirmed else " (not confirmed)")
                fields[label] = mac
                was = current.get(mac, {}).get("block_entity")
                suggested = was if (was and (options is None or was in options)) else (
                    options[0] if (confirmed and options) else None)
                cfg = selector.EntitySelectorConfig(domain=["switch", "input_boolean"]) if options is None else \
                    selector.EntitySelectorConfig(include_entities=options)
                schema[vol.Optional(label, description={"suggested_value": suggested})] = selector.EntitySelector(cfg)
                if confirmed:
                    note = (f"In {child}'s group, and has its own block rule (below)" if in_group
                            else f"Not in {child}'s group: has its own block rule (below)")
                elif in_group:
                    note = f"In {child}'s group: Block, Pause and Bedtime cover it"
                else:
                    note = "Not checked: pick its block switch below if your router has a rule for it"
            elif in_group:
                note = f"In {child}'s group: Block, Pause and Bedtime cover it"
            else:
                note = "Status and statistics only: no block rule for this device on your router"
                any_stats = True
            lines.append(f"**{name}**  \n{note}")
        if user_input is not None:
            devices = dict(self._kept if self._kept is not None else current)
            for mac in self._block:
                devices[mac] = {"name": self._names.get(mac) or current.get(mac, {}).get("name") or mac,
                                "block_entity": None, "confirmed": False}
            for label, mac in fields.items():
                if user_input.get(label):
                    devices[mac]["block_entity"] = user_input[label]
                    devices[mac]["confirmed"] = rules is not None
            return self._save(**{CONF_DEVICES: devices})
        found = ("\n\nFound on your router: this switch's rule turns off internet for this device only. Clear it to "
                 "show the device for status and statistics only.") if fields and rules is not None else ""
        stats = ("\n\nTo make a status-and-statistics-only device blockable, your router needs a rule that turns off "
                 "that device's internet. Home Assistant shows the rule as a switch; open Configure → Devices "
                 "again and it appears here." + help_md(self._rtype(), "device")) if any_stats else ""
        return self.async_show_form(step_id="block", data_schema=vol.Schema(schema), description_placeholders={
            "child": child, "devices": "\n\n".join(lines), "found": found, "stats": stats})

    # ---- the Devices list --------------------------------------------------------------------------------
    async def async_step_devices(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Devices on the child's screen, under Can be blocked and Status & traffic only; untick to remove (the device
        goes from Home Assistant too). Submitting re-reads each kept device's own rule, so router changes are picked
        up."""
        devices = dict(self._opts().get(CONF_DEVICES) or {})
        if user_input is not None:
            kept = {m for label in self._fields for m in user_input.get(label, [])}
            self._kept = {m: d for m, d in devices.items() if m in kept}
            rules = await switch_rules(self.hass)
            if rules is None or not self._kept:     # can't tell: keep each device's switch as it is
                return self._save(**{CONF_DEVICES: self._kept})
            for m, d in self._kept.items():          # a rule added or removed on the router since is picked up here
                sw = device_switches(rules, m)
                self._kept[m] = {**d, "block_entity": sw[0] if sw else None, "confirmed": bool(sw)}
            return self._save(**{CONF_DEVICES: self._kept})
        client = router_client(self.hass)
        self._groups, online = {}, {}
        if client is not None and devices:
            try:
                members = await client.kid_groups()
                self._groups = {m: [g for g, ms in members.items() if m in ms] for m in devices}
                online = {c.mac: c.online for c in await client.live_clients(list(devices))}
            except UniFiError:
                pass
        mine = self._opts().get(CONF_ROUTER_GROUP)
        level = [m for m, d in devices.items() if d.get("block_entity") or (mine and mine in self._groups.get(m, []))]
        status = [m for m in devices if m not in level]
        self._fields = {}
        if level:
            self._fields[LEVEL] = level
        if status:
            self._fields[STATUS] = status
        dupes = _duplicate_names({m: d.get("name") or m for m, d in devices.items()})
        schema = {}
        for label, macs in self._fields.items():
            def line(m: str) -> str:
                status = "" if m not in online else (" · online" if online[m] else " · offline")
                how = (f" · {self._child}'s group" if mine and mine in self._groups.get(m, [])
                       else " · own block rule" if devices[m].get("block_entity") else "")
                mac = f" · {m}" if m in dupes else ""
                return f"{devices[m].get('name') or m}{status}{mac}{how}"
            schema[vol.Optional(label, default=macs)] = selector.SelectSelector(selector.SelectSelectorConfig(
                options=[selector.SelectOptionDict(value=m, label=line(m)) for m in macs],
                multiple=True, mode=selector.SelectSelectorMode.LIST))
        return self.async_show_form(step_id="devices", data_schema=vol.Schema(schema),
                                    description_placeholders={"child": self._child})


def _duplicate_names(names: dict[str, str]) -> set[str]:
    """MACs whose name is shared with another listed device (case-insensitive)."""
    seen: dict[str, list[str]] = {}
    for mac, name in names.items():
        seen.setdefault(name.strip().lower(), []).append(mac)
    return {mac for macs in seen.values() if len(macs) > 1 for mac in macs}
