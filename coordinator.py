from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.core import HomeAssistant
from .api import NedAPI
from .const import DEFAULT_SCAN_INTERVAL, MAX_DAYS

class NedCoordinator(DataUpdateCoordinator):
    """Manages fetching NED electricity price data and 7-day history."""

    def __init__(self, hass: HomeAssistant, api_key: str, scan_interval: int = DEFAULT_SCAN_INTERVAL):
        self.api = NedAPI(api_key)
        self.history = []  # list of daily datasets
        super().__init__(
            hass,
            logger=hass.logger,
            name="NED Electricity Price",
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self):
        data = await self.api.fetch_price()

        self.history.append(data)
        if len(self.history) > MAX_DAYS:
            self.history = self.history[-MAX_DAYS:]

        return data
