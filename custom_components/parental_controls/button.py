"""Block, Allow and Pause buttons. Pause uses the pause-length number; the service takes any length."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ChildEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    ctl = entry.runtime_data
    async_add_entities([ActionButton(ctl, "block"), ActionButton(ctl, "allow"), ActionButton(ctl, "pause")])


class ActionButton(ChildEntity, ButtonEntity):
    async def async_press(self) -> None:
        key = self._attr_translation_key
        await {"block": self.ctl.async_block, "allow": self.ctl.async_allow, "pause": self.ctl.async_pause}[key]()
