from __future__ import annotations

import logging
from datetime import timedelta, datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NedApi
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

MAX_HISTORY_DAYS = 7


class NedCoordinator(DataUpdateCoordinator):
    """Coordinator to manage NED electricity price data."""

    def __init__(self, hass: HomeAssistant, api_key: str, scan_interval: int):
        self.hass = hass
        self.api = NedApi(api_key)

        # Rolling buffer with last 7 days
        self.history: list[dict] = []

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self):
        """Fetch data from NED API."""
        try:
            data = await self.api.async_get_prices()

            if data is None:
                raise UpdateFailed("No data received from NED API")

            today = datetime.now().date().isoformat()

            # Avoid duplicate day entries
            if not any(day["date"] == today for day in self.history):
                self.history.append(
                    {
                        "date": today,
                        "data": data,
                    }
                )

                # Keep only last 7 days
                self.history = self.history[-MAX_HISTORY_DAYS:]

            return self.history

        except Exception as err:
            raise UpdateFailed(f"Error fetching NED data: {err}") from err
