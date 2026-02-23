from __future__ import annotations

from datetime import datetime
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import CURRENCY_EURO

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the NED price sensor."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NedCurrentPriceSensor(coordinator)])


class NedCurrentPriceSensor(SensorEntity):
    """Single sensor with current price and all hourly data as attributes."""

    _attr_name = "NED Electricity Price"
    _attr_native_unit_of_measurement = CURRENCY_EURO
    _attr_device_class = "monetary"
    _attr_state_class = "measurement"

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._attr_unique_id = "ned_current_price"

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, "ned_prices")},
            name="NED Electricity Prices",
            manufacturer="ned.nl",
        )

    @property
    def native_value(self):
        """Return the current hour price."""
        data = self.coordinator.data
        if not data:
            return None

        today = datetime.now().date().isoformat()

        for day in data:
            if day["date"] == today:
                current_hour = datetime.now().hour
                try:
                    return day["data"][current_hour]["prijs"]
                except (IndexError, KeyError):
                    return None

        return None

    @property
    def extra_state_attributes(self):
        """Expose all hourly prices as attributes."""
        data = self.coordinator.data
        if not data:
            return {}

        attrs = {}

        for day in data:
            date = day["date"]

            hourly_prices = {
                f"{hour:02d}:00": entry.get("prijs")
                for hour, entry in enumerate(day["data"][:24])
            }

            attrs[f"prices_{date}"] = hourly_prices

        return attrs

    async def async_update(self):
        await self.coordinator.async_request_refresh()
