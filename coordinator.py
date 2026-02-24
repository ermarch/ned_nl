from datetime import timedelta
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import NedApi
from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class NedCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, api_key):
        self.api = NedApi(api_key)

        super().__init__(
            hass,
            _LOGGER,
            name="NED coordinator",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self):
        raw = await self.api.fetch()

        normalized = []

        for item in raw:
            normalized.append(
                {
                    "time": item.get("validfrom"),
                    "value": item.get("volume"),
                }
            )

        return normalized
