"""Parental Controls: block, pause and schedule a child's internet on the home router.

One config entry per child. Each child is a device with a status sensor, Block / Allow / Pause buttons,
a pause-length number, and bedtime settings. The rules live in engine.py; controller.py connects them to
the router's block switch.
"""
from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_call_later
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
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER, Platform.SWITCH, Platform.TIME]

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
    _remove_unpicked(hass, entry, ctl.devices.configured)
    _register_devices(hass, entry, ctl)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    entry.async_create_background_task(hass, ctl.devices.async_load_members(), f"{DOMAIN} group members")
    _watch_router_switches(hass, entry)
    return True


SYNC_DELAY = 10   # seconds of quiet after the router integration's switches change before rules are re-read
STARTUP_SYNC_DELAY = 60   # seconds after a child loads before its devices' own rules are checked once


@callback
def _watch_router_switches(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Auto-detect: when the router integration adds, removes, enables or disables a switch, re-read the router's
    rules and attach or detach each picked device's own block switch, so it moves between "Can be blocked" and
    "Status & traffic only" without opening Configure. Bursts (e.g. the router integration reloading) are waited out.
    Only the child's saved options change; no switch is ever turned on or off."""
    pending: list = []

    @callback
    def relevant(data) -> bool:
        if not data["entity_id"].startswith("switch."):
            return False
        if data["action"] == "update" and "disabled_by" not in data.get("changes", {}):
            return False
        return True

    async def sync(_now=None) -> None:
        pending.clear()
        await async_sync_device_switches(hass, entry)

    @callback
    def changed(event) -> None:
        if pending:
            pending.pop()()           # cancel the earlier timer: restart the quiet period
        pending.append(async_call_later(hass, SYNC_DELAY, sync))

    entry.async_on_unload(hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, changed, event_filter=relevant))
    # once after loading too, for rules (and switches) made while Home Assistant was down or on an older version;
    # later than the debounce, so the router entry has logged in by then
    pending.append(async_call_later(hass, STARTUP_SYNC_DELAY, sync))
    entry.async_on_unload(lambda: pending and pending.pop()())


async def async_sync_device_switches(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Match each picked device's own block switch against the router's rules now. Devices whose switch was picked by
    hand for a router that can't tell (confirmed False, with a switch) are left alone. True when something changed."""
    from homeassistant.helpers import issue_registry as ir
    from .rules import device_switches, switch_rules
    rules = await switch_rules(hass, fresh=True)   # a switch just appeared: the rule behind it is new too
    if rules is None or entry.state is not ConfigEntryState.LOADED:
        return False
    devices = dict({**entry.data, **entry.options}.get(CONF_DEVICES) or {})
    changed = False
    for mac, d in devices.items():
        if d.get("block_entity") and not d.get("confirmed"):
            continue
        found = device_switches(rules, mac)
        new = found[0] if found else None
        if new == d.get("block_entity"):
            continue
        name = d.get("name") or mac
        if new:
            _LOGGER.info("Parental Controls: %s on %s now has its own block switch %s", name, entry.title, new)
        else:
            _LOGGER.info("Parental Controls: %s on %s no longer has its own block switch (was %s); status and traffic "
                         "only", name, entry.title, d.get("block_entity"))
            ir.async_delete_issue(hass, DOMAIN, f"{entry.entry_id}_device_{mac.replace(':', '')}")
        devices[mac] = {**d, "block_entity": new, "confirmed": bool(new)}
        changed = True
    if changed:
        hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_DEVICES: devices})
    return changed


def _register_devices(hass: HomeAssistant, entry: ConfigEntry, ctl: ChildController) -> None:
    """The child's device, then each picked device linked to it ("connected via"). Linked by the child device's id
    where Home Assistant supports it (2026.10 deprecates via_device), else by its identifier on older versions."""
    from .entity import child_device_info
    devreg = dr.async_get(hass)
    child = devreg.async_get_or_create(config_entry_id=entry.entry_id, **child_device_info(ctl))
    for mac, cfg in ({**entry.data, **entry.options}.get(CONF_DEVICES) or {}).items():
        devreg.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"{entry.entry_id}_{mac}")},
                                   name=cfg.get("name") or mac, manufacturer="Parental Controls",
                                   model="Picked device", serial_number=mac, **_via(child, entry.entry_id))


def _via(child: dr.DeviceEntry, entry_id: str) -> dict:
    import inspect
    if "via_device_id" in inspect.signature(dr.DeviceRegistry.async_get_or_create).parameters:
        return {"via_device_id": child.id}
    return {"via_device": (DOMAIN, entry_id)}


def _remove_unpicked(hass: HomeAssistant, entry: ConfigEntry, picked: dict) -> None:
    """Devices removed in the child's Devices list go from Home Assistant too. Also drops the "<device> blocked"
    switches of v0.4 and earlier, which the picked devices' own entities replaced."""
    keep = {(DOMAIN, entry.entry_id)} | {(DOMAIN, f"{entry.entry_id}_{m}") for m in picked}
    devreg = dr.async_get(hass)
    for dev in dr.async_entries_for_config_entry(devreg, entry.entry_id):
        if not dev.identifiers & keep:
            devreg.async_update_device(dev.id, remove_config_entry_id=entry.entry_id)
    entreg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(entreg, entry.entry_id):
        if ent.domain == "switch" and ent.unique_id.startswith(f"{entry.entry_id}_device_"):
            entreg.async_remove(ent.entity_id)


async def async_remove_config_entry_device(hass: HomeAssistant, entry: ConfigEntry, device: dr.DeviceEntry) -> bool:
    """Delete on a picked device's page: take it off the child (the child's own device can't be deleted)."""
    if entry.data.get(CONF_KIND) == KIND_ROUTER or (DOMAIN, entry.entry_id) in device.identifiers:
        return False
    prefix = f"{entry.entry_id}_"
    macs = [i[1][len(prefix):] for i in device.identifiers if i[0] == DOMAIN and i[1].startswith(prefix)]
    devices = dict({**entry.data, **entry.options}.get(CONF_DEVICES) or {})
    if not macs or not any(m in devices for m in macs):
        return True
    for m in macs:
        devices.pop(m, None)
    hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_DEVICES: devices})
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
