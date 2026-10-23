"""Each picked device: Online (from the last device check, so it only changes when the device comes or goes), and
Blocked when the device has its own block switch."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_DEVICES
from .entity import PickedDeviceEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    ctl = entry.runtime_data
    devices = {**entry.data, **entry.options}.get(CONF_DEVICES, {})
    entities = []
    for mac, cfg in devices.items():
        entities.append(DeviceOnline(ctl, mac, cfg))
        if cfg.get("block_entity"):
            entities.append(DeviceBlocked(ctl, mac, cfg))
    async_add_entities(entities)


class DeviceOnline(PickedDeviceEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, ctl, mac: str, cfg: dict) -> None:
        super().__init__(ctl, mac, cfg, "online")

    @property
    def is_on(self) -> bool | None:
        row = self.ctl.devices.row(self.mac)
        return None if row is None else row["online"]


class DeviceBlocked(PickedDeviceEntity, BinarySensorEntity):
    """On while the device's own block switch is on."""
    _attr_icon = "mdi:web-off"

    def __init__(self, ctl, mac: str, cfg: dict) -> None:
        super().__init__(ctl, mac, cfg, "blocked")
        self._target = cfg["block_entity"]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_track_state_change_event(self.hass, [self._target], self._target_changed))

    @callback
    def _target_changed(self, _event: Event) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        st = self.hass.states.get(self._target)
        return st is not None and st.state in ("on", "off")

    @property
    def is_on(self) -> bool:
        st = self.hass.states.get(self._target)
        return st is not None and st.state == STATE_ON
