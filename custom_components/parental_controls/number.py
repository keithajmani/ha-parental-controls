"""Pause length (the Custom slider), in minutes."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import MAX_PAUSE_MINUTES, MIN_PAUSE_MINUTES
from .entity import ChildEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([PauseMinutes(entry.runtime_data)])


class PauseMinutes(ChildEntity, NumberEntity):
    _attr_native_min_value = MIN_PAUSE_MINUTES
    _attr_native_max_value = MAX_PAUSE_MINUTES
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:timer-cog-outline"

    def __init__(self, ctl) -> None:
        super().__init__(ctl, "pause_minutes")

    @property
    def native_value(self) -> float:
        return self.ctl.pause_minutes

    async def async_set_native_value(self, value: float) -> None:
        await self.ctl.async_set_pause_minutes(int(value))
