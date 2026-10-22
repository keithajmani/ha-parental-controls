"""Bedtime on/off for the child."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ChildEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([BedtimeSwitch(entry.runtime_data)])


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
