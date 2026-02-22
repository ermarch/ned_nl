from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import CURRENCY_EURO
from .const import DOMAIN
from datetime import datetime

MAX_HOURS_PER_DAY = 24  # Only create 24 hourly sensors per day

async def async_setup_entry(hass, entry, async_add_entities):
    """Create sensors for each hour across multiple days (limit 24 per day)."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []

    for day_data in coordinator.history:
        day_str = day_data.get("fetched_at", None)
        if day_str:
            try:
                date_obj = datetime.fromisoformat(day_str)
                date_label = date_obj.strftime("%Y-%m-%d")
            except ValueError:
                date_label = day_str
        else:
            date_label = "unknown"

        hours = day_data.get("data", [])[:MAX_HOURS_PER_DAY]  # Limit to 24
        for hour_idx, hour_entry in enumerate(hours):
            entities.append(
                NedHourlyPriceSensor(coordinator, date_label, hour_idx, hour_entry)
            )

    async_add_entities(entities)


class NedHourlyPriceSensor(SensorEntity):
    """Sensor for one hourly electricity price for a specific date."""

    def __init__(self, coordinator, date_label, hour_idx, hour_entry):
        self.coordinator = coordinator
        self.date_label = date_label
        self.hour_idx = hour_idx
        self.hour_entry = hour_entry
        self._attr_unique_id = f"ned_price_{date_label}_hour{hour_idx}"

    @property
    def name(self):
        hour_str = self.hour_entry.get("uur", f"H{self.hour_idx}")
        return f"NED Price {self.date_label} Hour {hour_str}"

    @property
    def native_value(self):
        return self.hour_entry.get("prijs")

    @property
    def native_unit_of_measurement(self):
        return CURRENCY_EURO

    @property
    def device_class(self):
        return "monetary"

    @property
    def state_class(self):
        return "measurement"

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={("ned", f"{self.date_label}_hour{self.hour_idx}")},
            name=f"NED Electricity {self.date_label}",
            manufacturer="ned.nl",
        )

    async def async_update(self):
        await self.coordinator.async_request_refresh()
