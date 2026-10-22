"""Bedtime times: weeknight start (Sun-Thu nights), weekend start (Fri and Sat nights) and end."""
from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ChildEntity

KEYS = ("weeknight_start", "weekend_start", "end")


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([BedtimeTime(entry.runtime_data, k) for k in KEYS])


class BedtimeTime(ChildEntity, TimeEntity):
    _attr_icon = "mdi:clock-outline"

    def __init__(self, ctl, key: str) -> None:
        super().__init__(ctl, f"bedtime_{key}")
        self._key = key

    @property
    def native_value(self) -> time:
        return getattr(self.ctl.kid.bedtime, self._key)

    async def async_set_value(self, value: time) -> None:
        await self.ctl.async_set_bedtime(**{self._key: value})
