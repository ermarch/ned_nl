from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfEnergy
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, COORDINATOR


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

    async_add_entities(
        [
            NedCurrentLoadSensor(coordinator),
            NedTodayMinSensor(coordinator),
            NedTodayMaxSensor(coordinator),
        ]
    )


class NedBaseSensor(SensorEntity):
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_info = DeviceInfo(
        identifiers={(DOMAIN, "ned_energy")},
        name="NED Energy",
        manufacturer="NED",
    )

    def __init__(self, coordinator):
        self.coordinator = coordinator

    async def async_update(self):
        await self.coordinator.async_request_refresh()

    @property
    def available(self):
        return self.coordinator.last_update_success


class NedCurrentLoadSensor(NedBaseSensor):
    _attr_name = "NED Current Load"
    _attr_unique_id = "ned_current_load"

    @property
    def native_value(self):
        data = self.coordinator.data
        return data[0]["value"] if data else None


class NedTodayMinSensor(NedBaseSensor):
    _attr_name = "NED Today Min Load"
    _attr_unique_id = "ned_today_min"

    @property
    def native_value(self):
        values = [d["value"] for d in self.coordinator.data if d["value"] is not None]
        return min(values) if values else None


class NedTodayMaxSensor(NedBaseSensor):
    _attr_name = "NED Today Max Load"
    _attr_unique_id = "ned_today_max"

    @property
    def native_value(self):
        values = [d["value"] for d in self.coordinator.data if d["value"] is not None]
        return max(values) if values else None
