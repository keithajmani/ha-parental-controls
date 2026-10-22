"""Setup.

Add integration → Parental Controls offers two kinds of entry:
- "Add a child": name, the router switch that blocks the child's group, and (with a router connected) which router
  group is the child's, so its devices can be listed. One entry per child, any number of children.
- "Connect a router": the UniFi console and a view-only login, used for device search and the Devices list.
  Blocking never needs it: blocks go through Home Assistant switches.

A child's options: change the block switch or group, add devices (wildcard search, then pick), remove devices.
A picked device is either outside the child's group (listed on the child's screen) or inside it (blocked on its own
while the rest of the group stays online); either kind can get its own block switch.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.util import slugify

from .const import (CONF_BLOCK_ENTITY, CONF_CHILD_NAME, CONF_DEVICES, CONF_HOST, CONF_KIND, CONF_PASSWORD,
                    CONF_PATTERN, CONF_PICKED, CONF_ROUTER_GROUP, CONF_SITE, CONF_USERNAME, DOMAIN, KIND_CHILD,
                    KIND_ROUTER)
from .devices import router_client
from .unifi import UniFiAuthError, UniFiClient, UniFiError

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


class ParentalControlsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["child", "router"])

    async def async_step_child(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_CHILD_NAME].strip()
            await self.async_set_unique_id(slugify(name))
            self._abort_if_unique_id_configured()
            used = {{**e.data, **e.options}.get(CONF_BLOCK_ENTITY) for e in self._async_current_entries()}
            if user_input[CONF_BLOCK_ENTITY] in used:
                errors[CONF_BLOCK_ENTITY] = "switch_in_use"
            else:
                data = {CONF_KIND: KIND_CHILD, CONF_CHILD_NAME: name, CONF_BLOCK_ENTITY: user_input[CONF_BLOCK_ENTITY]}
                if user_input.get(CONF_ROUTER_GROUP):
                    data[CONF_ROUTER_GROUP] = user_input[CONF_ROUTER_GROUP]
                return self.async_create_entry(title=name, data=data)
        schema = {vol.Required(CONF_CHILD_NAME): str, vol.Required(CONF_BLOCK_ENTITY): BLOCK_SELECTOR}
        if (groups := await _group_selector(self.hass)) is not None:
            schema[vol.Optional(CONF_ROUTER_GROUP)] = groups
        return self.async_show_form(step_id="child", errors=errors, data_schema=vol.Schema(schema))

    async def async_step_router(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id("router")
            self._abort_if_unique_id_configured()
            client = UniFiClient(async_create_clientsession(self.hass, verify_ssl=False), user_input[CONF_HOST],
                                 user_input[CONF_USERNAME], user_input[CONF_PASSWORD], user_input[CONF_SITE])
            try:
                await client.login()
                await client.kid_groups()
            except UniFiAuthError:
                errors["base"] = "invalid_auth"
            except UniFiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=f"UniFi ({user_input[CONF_HOST]})",
                                               data={CONF_KIND: KIND_ROUTER, **user_input})
        return self.async_show_form(step_id="router", errors=errors, data_schema=vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
            vol.Required(CONF_SITE, default="default"): str,
        }))

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        return config_entry.data.get(CONF_KIND, KIND_CHILD) == KIND_CHILD

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ChildOptionsFlow()


class ChildOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._found: dict[str, str] = {}

    def _opts(self) -> dict:
        return {**self.config_entry.data, **self.config_entry.options}

    def _save(self, **changes) -> ConfigFlowResult:
        keep = {k: v for k, v in self.config_entry.options.items()}
        return self.async_create_entry(data={**keep, **changes})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["settings", "add_devices"]
        if self._opts().get(CONF_DEVICES):
            menu.append("remove_devices")
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        o = self._opts()
        if user_input is not None:
            return self._save(**{CONF_BLOCK_ENTITY: user_input[CONF_BLOCK_ENTITY],
                                 CONF_ROUTER_GROUP: user_input.get(CONF_ROUTER_GROUP) or None})
        schema = {vol.Required(CONF_BLOCK_ENTITY, default=o[CONF_BLOCK_ENTITY]): BLOCK_SELECTOR}
        groups = await _group_selector(self.hass)
        schema[vol.Optional(CONF_ROUTER_GROUP, description={"suggested_value": o.get(CONF_ROUTER_GROUP)})] = \
            groups if groups is not None else str
        return self.async_show_form(step_id="settings", data_schema=vol.Schema(schema))

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
                    group = self._opts().get(CONF_ROUTER_GROUP)
                    self._found = {c.mac: _label(c, group) for c in found[:100]}
                    self._names = {c.mac: c.name for c in found}
                    return await self.async_step_pick()
        return self.async_show_form(step_id="add_devices", errors=errors,
                                    data_schema=vol.Schema({vol.Required(CONF_PATTERN, default="*"): str}))

    async def async_step_pick(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 2: pick devices from the matches, and optionally a block switch for each."""
        if user_input is not None and CONF_PICKED in user_input:
            self._picked = user_input[CONF_PICKED]
            return await self.async_step_block()
        options = [selector.SelectOptionDict(value=m, label=lbl) for m, lbl in self._found.items()]
        return self.async_show_form(step_id="pick", data_schema=vol.Schema({
            vol.Required(CONF_PICKED): selector.SelectSelector(selector.SelectSelectorConfig(
                options=options, multiple=True, mode=selector.SelectSelectorMode.LIST))}))

    async def async_step_block(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 3: for each picked device, an optional switch that blocks just that device."""
        if user_input is not None:
            devices = dict(self._opts().get(CONF_DEVICES, {}))
            for mac in self._picked:
                devices[mac] = {"name": self._names.get(mac, mac), "block_entity": user_input.get(mac) or None}
            return self._save(**{CONF_DEVICES: devices})
        return self.async_show_form(
            step_id="block",
            description_placeholders={"devices": ", ".join(self._names.get(m, m) for m in self._picked)},
            data_schema=vol.Schema({vol.Optional(m, description={"suggested_value": None}): BLOCK_SELECTOR
                                    for m in self._picked}))

    async def async_step_remove_devices(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        devices = dict(self._opts().get(CONF_DEVICES, {}))
        if user_input is not None:
            for mac in user_input.get(CONF_PICKED, []):
                devices.pop(mac, None)
            return self._save(**{CONF_DEVICES: devices})
        options = [selector.SelectOptionDict(value=m, label=f"{d.get('name') or m} · {m}") for m, d in devices.items()]
        return self.async_show_form(step_id="remove_devices", data_schema=vol.Schema({
            vol.Optional(CONF_PICKED, default=[]): selector.SelectSelector(selector.SelectSelectorConfig(
                options=options, multiple=True, mode=selector.SelectSelectorMode.LIST))}))


def _label(c, group: str | None) -> str:
    where = "in this child's group" if group and group in c.groups else (
        f"group {', '.join(c.groups)}" if c.groups else "no group")
    status = "online" if c.online else "away"
    return f"{c.name} · {c.mac} · {status} · {where}"
