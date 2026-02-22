import httpx
from datetime import datetime
from .const import BASE_URL, PRICE_ENDPOINT

class NedAPI:
    """Fetch electricity price data from NED API v1."""

    def __init__(self, api_key: str):
        self.endpoint = PRICE_ENDPOINT
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=30)

    async def fetch_price(self):
        url = f"{BASE_URL}/{self.endpoint}"
        headers = {"X-API-Key": self.api_key}

        r = await self._client.get(url, headers=headers)
        r.raise_for_status()

        payload = r.json()
        return {
            "endpoint": self.endpoint,
            "fetched_at": datetime.utcnow().isoformat(),
            "data": payload,
        }
