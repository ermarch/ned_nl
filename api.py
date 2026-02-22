from __future__ import annotations

import httpx

BASE_URL = "https://api.ned.nl/v1"


class NedApi:
    """Async client for NED API."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def async_get_prices(self) -> list[dict]:
        """Fetch electricity prices."""
        url = f"{BASE_URL}/utilizations"

        headers = {
            "X-AUTH-TOKEN": self._api_key,
            "accept": "application/json",
        }

        params = {
            "point": "APX",
            "type": "price",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

        # Extract hourly data
        return data.get("data", [])
