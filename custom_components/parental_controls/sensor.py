"""Status sensor: Online / Paused / Allowed for / Bedtime / Blocked, with when it ends and what comes next."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_DEVICES
from .engine import State
from .entity import ChildEntity, PickedDeviceEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    ctl = entry.runtime_data
    devices = {**entry.data, **entry.options}.get(CONF_DEVICES, {})
    async_add_entities([InternetSensor(ctl), DevicesSensor(ctl)]
                       + [DeviceBlocking(ctl, mac, cfg) for mac, cfg in devices.items()])


class InternetSensor(ChildEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _unrecorded_attributes = frozenset({"minutes_left", "config_entry_id", "child", "block_entity"})
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
            "bedtime_weeknight_start": b.weeknight_start.strftime("%H:%M"),
            "bedtime_weekend_start": b.weekend_start.strftime("%H:%M"),
            "bedtime_end": b.end.strftime("%H:%M"),
            "bedtime_now": self.ctl.kid.bedtime.active_window(dt_util.now()) is not None,
            "config_entry_id": self.ctl.entry_id,
            "child": self.ctl.name,
            "block_entity": self.ctl.block_entity,
        }


class DevicesSensor(ChildEntity, SensorEntity):
    """Number of the child's devices online at the last check. The device list is an attribute that is kept
    out of the recorder (it changes every few seconds while Live is on)."""
    _attr_icon = "mdi:devices"
    _attr_native_unit_of_measurement = "online"
    _unrecorded_attributes = frozenset({"devices", "checked", "error", "live"})

    def __init__(self, ctl) -> None:
        super().__init__(ctl, "devices")

    @property
    def native_value(self) -> int | None:
        d = self.ctl.devices
        return sum(1 for r in d.rows if r["online"]) if d.checked else None

    @property
    def extra_state_attributes(self) -> dict:
        d = self.ctl.devices
        # a device that follows the child reads Blocked whenever the child is (Block, Pause or Bedtime)
        rows = [{**r, "blocked": d.blocked(r) if r["block_entity"] else (r["in_group"] and self.ctl.status().router_blocked)}
                for r in d.rows]
        return {"devices": rows, "checked": d.checked.isoformat() if d.checked else None, "error": d.error,
                "live": d.live}


class DeviceBlocking(PickedDeviceEntity, SensorEntity):
    """How a picked device is controlled: follows the child (in the child's group), its own block rule, or status
    and statistics only."""
    _attr_icon = "mdi:shield-account-outline"

    def __init__(self, ctl, mac: str, cfg: dict) -> None:
        super().__init__(ctl, mac, cfg, "blocking")

    @property
    def native_value(self) -> str | None:
        return {"own": "Own block rule", "group": f"Follows {self.ctl.name}",
                "stats": "Status and statistics only"}.get(self.ctl.devices.control(self.mac))
