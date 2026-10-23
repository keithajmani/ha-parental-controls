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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ctl.entry_id)},
            name=f"{ctl.name} Parental Controls",
            manufacturer="Parental Controls",
            model="Child",
            entry_type=DeviceEntryType.SERVICE,
        )

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
    return DeviceInfo(
        identifiers={(DOMAIN, f"{ctl.entry_id}_{mac}")},
        name=cfg.get("name") or mac,
        manufacturer="Parental Controls",
        model="Picked device",
        serial_number=mac,
        via_device=(DOMAIN, ctl.entry_id),
    )
