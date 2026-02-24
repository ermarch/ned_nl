from __future__ import annotations

import httpx
from datetime import datetime, timedelta
from .const import NED_ENDPOINT


class NedApi:
    def __init__(self, api_key: str):
        self._api_key = api_key

    async def fetch(self) -> list[dict]:
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)

        params = {
            "point": 0,
            "type": 27,
            "granularity": 5,
            "granularitytimezone": 1,
            "classification": 2,
            "activity": 1,
            "validfrom[after]": today.isoformat(),
            "validfrom[strictly_before]": tomorrow.isoformat(),
        }

        headers = {
            "X-AUTH-TOKEN": self._api_key,
            "Accept": "application/ld+json",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(NED_ENDPOINT, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return data.get("member", [])
