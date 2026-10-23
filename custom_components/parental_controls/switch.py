"""Bedtime on/off and Live device refresh."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ChildEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    ctl = entry.runtime_data
    async_add_entities([BedtimeSwitch(ctl), LiveSwitch(ctl)])


class BedtimeSwitch(ChildEntity, SwitchEntity):
    _attr_icon = "mdi:weather-night"

    def __init__(self, ctl) -> None:
        super().__init__(ctl, "bedtime")

    @property
    def is_on(self) -> bool:
        return self.ctl.kid.bedtime.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.ctl.async_set_bedtime(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.ctl.async_set_bedtime(enabled=False)


class LiveSwitch(ChildEntity, SwitchEntity):
    """Refresh the device list every few seconds; turns itself off after 5 minutes."""
    _attr_icon = "mdi:access-point-network"

    def __init__(self, ctl) -> None:
        super().__init__(ctl, "devices_live")

    @property
    def is_on(self) -> bool:
        return self.ctl.devices.live

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.ctl.devices.async_set_live(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.ctl.devices.async_set_live(False)
