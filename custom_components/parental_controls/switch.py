"""Bedtime on/off, Live device refresh, and a block switch per device that has its own router switch."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_DEVICES
from .entity import ChildEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    ctl = entry.runtime_data
    devices = {**entry.data, **entry.options}.get(CONF_DEVICES, {})
    async_add_entities([BedtimeSwitch(ctl), LiveSwitch(ctl)] + [
        DeviceBlockSwitch(ctl, mac, cfg) for mac, cfg in devices.items() if cfg.get("block_entity")])


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


class DeviceBlockSwitch(ChildEntity, SwitchEntity):
    """On = this one device is blocked. Mirrors the router switch picked for it in the child's options."""
    _attr_icon = "mdi:web-off"

    def __init__(self, ctl, mac: str, cfg: dict) -> None:
        super().__init__(ctl, "device_blocked")
        self._target = cfg["block_entity"]
        self._attr_unique_id = f"{ctl.entry_id}_device_{mac.replace(':', '')}"
        self._attr_translation_placeholders = {"device": cfg.get("name") or mac}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_track_state_change_event(self.hass, [self._target], self._target_changed))

    @callback
    def _target_changed(self, _event: Event) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self.hass.states.get(self._target) is not None

    @property
    def is_on(self) -> bool:
        st = self.hass.states.get(self._target)
        return st is not None and st.state == STATE_ON

    async def _set(self, on: bool) -> None:
        await self.hass.services.async_call(self._target.split(".", 1)[0], "turn_on" if on else "turn_off",
                                            {"entity_id": self._target}, blocking=True, context=self._context)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
