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
