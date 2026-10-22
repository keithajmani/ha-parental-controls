"""Parental Controls: block, pause and schedule a child's internet on the home router.

One config entry per child. Each child is a device with a status sensor, Block / Allow / Pause buttons,
a pause-length number, and bedtime settings. The rules live in engine.py; controller.py connects them to
the router's block switch.
"""
from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import (CONF_BLOCK_ENTITY, CONF_CHILD_NAME, CONF_DEVICES, CONF_HOST, CONF_KIND, CONF_PASSWORD,
                    CONF_ROUTER_GROUP, CONF_SITE, CONF_USERNAME, DOMAIN, KIND_ROUTER, MAX_PAUSE_MINUTES,
                    MIN_PAUSE_MINUTES)
from .controller import ChildController
from .devices import ChildDevices
from .unifi import UniFiAuthError, UniFiClient, UniFiError, unifi_session

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.SENSOR, Platform.BUTTON, Platform.NUMBER, Platform.SWITCH, Platform.TIME]

ParentalControlsConfigEntry = ConfigEntry[ChildController]

ATTR_CHILD = "config_entry_id"
ATTR_MINUTES = "minutes"
CHILD_SCHEMA = vol.Schema({vol.Required(ATTR_CHILD): cv.string})
PAUSE_SCHEMA = CHILD_SCHEMA.extend(
    {vol.Optional(ATTR_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=MIN_PAUSE_MINUTES, max=MAX_PAUSE_MINUTES))})


_LOGGER = logging.getLogger(__name__)
CARD_URL = "/parental_controls/parental-controls-card.js"


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the dashboard card from the integration and add it as a dashboard resource, so nobody has to.

    It is registered as a normal Lovelace resource (like a HACS card) rather than an early-loaded frontend module:
    a module that loads before the dashboard's element registry is ready ends up invisible to the dashboard.
    """
    from homeassistant.components.http import StaticPathConfig
    from homeassistant.loader import async_get_integration

    version = (await async_get_integration(hass, DOMAIN)).version
    path = Path(__file__).parent / "frontend" / "parental-controls-card.js"
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(path), True)])
    url = f"{CARD_URL}?v={version}"

    async def add_resource(_event=None) -> None:
        lovelace = hass.data.get("lovelace")
        resources = getattr(lovelace, "resources", None)
        if resources is None or not hasattr(resources, "async_create_item"):
            # dashboards in YAML mode: the resource has to be added by hand (see docs/install.md)
            _LOGGER.info("Parental Controls: add %s as a dashboard resource (type: module)", url)
            return
        if not resources.loaded:
            await resources.async_load()
            resources.loaded = True
        for item in resources.async_items():
            if item.get("url", "").split("?")[0] == CARD_URL:
                if item["url"] != url:   # new version: bump the URL so browsers fetch the new card
                    await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
                return
        await resources.async_create_item({"res_type": "module", "url": url})

    if hass.data.get("lovelace") is not None:
        await add_resource()
    else:
        from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, add_resource)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the card and the services once: parental_controls.block / allow / pause / refresh_devices."""
    if getattr(hass, "http", None) is not None:
        await _async_register_card(hass)

    def child(call: ServiceCall) -> ChildController:
        entry = hass.config_entries.async_get_entry(call.data[ATTR_CHILD])
        if (entry is None or entry.domain != DOMAIN or entry.data.get(CONF_KIND) == KIND_ROUTER
                or not hasattr(entry, "runtime_data")):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_child")
        return entry.runtime_data

    async def block(call: ServiceCall) -> None:
        await child(call).async_block()

    async def allow(call: ServiceCall) -> None:
        await child(call).async_allow()

    async def pause(call: ServiceCall) -> None:
        await child(call).async_pause(call.data.get(ATTR_MINUTES))

    hass.services.async_register(DOMAIN, "block", block, schema=CHILD_SCHEMA)
    hass.services.async_register(DOMAIN, "allow", allow, schema=CHILD_SCHEMA)
    hass.services.async_register(DOMAIN, "pause", pause, schema=PAUSE_SCHEMA)

    async def refresh_devices(call: ServiceCall) -> None:
        await child(call).devices.async_refresh()

    hass.services.async_register(DOMAIN, "refresh_devices", refresh_devices, schema=CHILD_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ParentalControlsConfigEntry) -> bool:
    if entry.data.get(CONF_KIND) == KIND_ROUTER:
        # the router entry only holds the (view-only) login; children use it for their Devices list
        client = UniFiClient(unifi_session(hass), entry.data[CONF_HOST],
                             entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD], entry.data.get(CONF_SITE, "default"))
        try:
            await client.login()
        except UniFiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except UniFiError as err:
            raise ConfigEntryNotReady(str(err)) from err
        entry.runtime_data = client
        return True
    opts = {**entry.data, **entry.options}
    ctl = ChildController(hass, entry.entry_id, entry.data[CONF_CHILD_NAME], opts[CONF_BLOCK_ENTITY])
    ctl.devices = ChildDevices(hass, opts.get(CONF_ROUTER_GROUP), opts.get(CONF_DEVICES, {}), ctl.notify)
    await ctl.async_start()
    entry.runtime_data = ctl
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ParentalControlsConfigEntry) -> bool:
    if entry.data.get(CONF_KIND) == KIND_ROUTER:
        return True
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.devices.async_stop()
        await entry.runtime_data.async_stop()
    return ok


async def async_remove_entry(hass: HomeAssistant, entry: ParentalControlsConfigEntry) -> None:
    """A child was deleted: remove its Repairs issues."""
    from homeassistant.helpers import issue_registry as ir
    for issue in list(ir.async_get(hass).issues.values()):
        if issue.domain == DOMAIN and issue.issue_id.startswith(entry.entry_id):
            ir.async_delete_issue(hass, DOMAIN, issue.issue_id)


async def _async_reload(hass: HomeAssistant, entry: ParentalControlsConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
