"""Base entity: one device per child, named "<Child> Parental Controls" by default (see docs/design.md)."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .controller import ChildController


class ChildEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, ctl: ChildController, key: str) -> None:
        self.ctl = ctl
        self._attr_translation_key = key
        self._attr_unique_id = f"{ctl.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(**child_device_info(ctl))

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.ctl.add_listener(self.async_write_ha_state))


class PickedDeviceEntity(Entity):
    """An entity of a picked device: its own HA device, connected via the child's device. The MAC is the device's
    serial number rather than a network connection, so it isn't merged with the router integration's own client
    device."""
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, ctl: ChildController, mac: str, cfg: dict, key: str) -> None:
        self.ctl = ctl
        self.mac = mac
        self.cfg = cfg
        self._attr_translation_key = key
        self._attr_unique_id = f"{ctl.entry_id}_{mac.replace(':', '')}_{key}"
        self._attr_device_info = picked_device_info(ctl, mac, cfg)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.ctl.add_listener(self.async_write_ha_state))


def picked_device_info(ctl: ChildController, mac: str, cfg: dict) -> DeviceInfo:
    # The device itself, and its link to the child's device, are registered by __init__ before the entities load
    # (Home Assistant 2026.10 deprecates linking with via_device from an entity).
    return DeviceInfo(identifiers={(DOMAIN, f"{ctl.entry_id}_{mac}")})


def child_device_info(ctl: ChildController) -> dict:
    return {"identifiers": {(DOMAIN, ctl.entry_id)}, "name": f"{ctl.name} Parental Controls",
            "manufacturer": "Parental Controls", "model": "Child", "entry_type": DeviceEntryType.SERVICE}
