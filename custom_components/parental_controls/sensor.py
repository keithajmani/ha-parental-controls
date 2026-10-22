"""Status sensor: Online / Paused / Allowed for / Bedtime / Blocked, with when it ends and what comes next."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .engine import State
from .entity import ChildEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([InternetSensor(entry.runtime_data)])


class InternetSensor(ChildEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [s.value for s in State]

    def __init__(self, ctl) -> None:
        super().__init__(ctl, "internet")

    @property
    def native_value(self) -> str:
        return self.ctl.status().state.value

    @property
    def icon(self) -> str:
        return {State.ONLINE: "mdi:web", State.PAUSED: "mdi:timer-sand", State.ALLOWED_FOR: "mdi:web-clock",
                State.BEDTIME: "mdi:weather-night", State.BLOCKED: "mdi:web-off"}[self.ctl.status().state]

    @property
    def extra_state_attributes(self) -> dict:
        s = self.ctl.status()
        left = None
        if s.ends_at:
            left = max(0, -(-int((s.ends_at - dt_util.now()).total_seconds()) // 60))   # minutes, rounded up
        b = self.ctl.kid.bedtime
        return {
            "router_blocked": s.router_blocked,
            "ends_at": s.ends_at.isoformat() if s.ends_at else None,
            "minutes_left": left,
            "then": s.then.value if s.then else None,
            "manual_blocked": self.ctl.kid.manual_blocked,
            "allowed_tonight": self.ctl.kid.allowed_tonight,
            "bedtime_enabled": b.enabled,
            "block_entity": self.ctl.block_entity,
        }
