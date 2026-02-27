"""NED.nl API client."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://api.ned.nl/v1"

# ---------------------------------------------------------------------------
# Granularity IDs
# ---------------------------------------------------------------------------
GRANULARITY_10MIN = 3
GRANULARITY_15MIN = 4
GRANULARITY_HOURLY = 5
GRANULARITY_DAILY = 6
GRANULARITY_MONTHLY = 7
GRANULARITY_YEARLY = 8

# ---------------------------------------------------------------------------
# GranularityTimeZone IDs
# NOTE: despite docs labelling tz=1 as "UTC" in the example, 1 = Amsterdam/CET.
# Daily/monthly/yearly aggregations ONLY return data for tz=1 (Amsterdam).
# ---------------------------------------------------------------------------
GRANULARITY_TIMEZONE_UTC = 0
GRANULARITY_TIMEZONE_AMSTERDAM = 1

# ---------------------------------------------------------------------------
# Classification IDs
# ---------------------------------------------------------------------------
CLASSIFICATION_FORECAST = 1
CLASSIFICATION_CURRENT = 2    # near-realtime / "public"
CLASSIFICATION_BACKCAST = 3

# ---------------------------------------------------------------------------
# Activity IDs
# ---------------------------------------------------------------------------
ACTIVITY_PROVIDING = 1
ACTIVITY_CONSUMING = 2
ACTIVITY_IMPORT = 3
ACTIVITY_EXPORT = 4
ACTIVITY_STORAGE_IN = 5
ACTIVITY_STORAGE_OUT = 6
ACTIVITY_STORAGE = 7

# ---------------------------------------------------------------------------
# Point IDs
# ---------------------------------------------------------------------------
POINT_NETHERLANDS = 0
POINT_GRONINGEN = 1
POINT_FRIESLAND = 2
POINT_DRENTHE = 3
POINT_OVERIJSSEL = 4
POINT_FLEVOLAND = 5
POINT_GELDERLAND = 6
POINT_UTRECHT = 7
POINT_NOORD_HOLLAND = 8
POINT_ZUID_HOLLAND = 9
POINT_ZEELAND = 10
POINT_NOORD_BRABANT = 11
POINT_LIMBURG = 12
POINT_OFFSHORE = 14

POINT_NAMES: dict[int, str] = {
    0: "Netherlands",
    1: "Groningen",
    2: "Friesland",
    3: "Drenthe",
    4: "Overijssel",
    5: "Flevoland",
    6: "Gelderland",
    7: "Utrecht",
    8: "Noord-Holland",
    9: "Zuid-Holland",
    10: "Zeeland",
    11: "Noord-Brabant",
    12: "Limburg",
    14: "Offshore",
}

# ---------------------------------------------------------------------------
# Type IDs
# ---------------------------------------------------------------------------
TYPE_ALL = 0
TYPE_WIND = 1
TYPE_SOLAR = 2
TYPE_BIOGAS = 3
TYPE_HEAT_PUMP = 4
TYPE_COFIRING = 8
TYPE_GEOTHERMAL = 9
TYPE_OTHER = 10
TYPE_WASTE = 11
TYPE_BIO_OIL = 12
TYPE_BIOMASS = 13
TYPE_WOOD = 14
TYPE_WIND_OFFSHORE = 17
TYPE_FOSSIL_GAS_POWER = 18
TYPE_FOSSIL_HARD_COAL = 19
TYPE_NUCLEAR = 20
TYPE_WASTE_POWER = 21
TYPE_WIND_OFFSHORE_B = 22
TYPE_NATURAL_GAS = 23
TYPE_BIOMETHANE = 24
TYPE_BIOMASS_POWER = 25
TYPE_OTHER_POWER = 26
TYPE_ELECTRICITY_MIX = 27
TYPE_GAS_MIX = 28
TYPE_GAS_DISTRIBUTION = 31
TYPE_WKK_TOTAL = 35
TYPE_ALL_CONSUMING_GAS = 56    # total gas consumption (all sectors combined)
TYPE_ELECTRICITY_LOAD = 59     # total electricity consumption / load

TYPE_NAMES: dict[int, str] = {
    0: "All",
    1: "Wind",
    2: "Solar",
    3: "Biogas",
    4: "Heat Pump",
    8: "Co-firing",
    9: "Geothermal",
    10: "Other",
    11: "Waste",
    12: "Bio Oil",
    13: "Biomass",
    14: "Wood",
    17: "Wind Offshore",
    18: "Fossil Gas",
    19: "Hard Coal",
    20: "Nuclear",
    21: "Waste Power",
    22: "Wind Offshore B",
    23: "Natural Gas",
    24: "Biomethane",
    25: "Biomass Power",
    26: "Other Power",
    27: "Electricity Mix",
    28: "Gas Mix",
    31: "Gas Distribution",
    35: "WKK Total",
    56: "All Consuming Gas",
    59: "Electricity Load",
}

# ---------------------------------------------------------------------------
# Default queries: (point_id, type_id, activity_id)
# ---------------------------------------------------------------------------
DEFAULT_QUERIES: list[tuple[int, int, int]] = [
    # ── Electricity production (10-min for solar/wind, hourly for thermal) ──
    (POINT_NETHERLANDS, TYPE_SOLAR,           ACTIVITY_PROVIDING),
    (POINT_NETHERLANDS, TYPE_WIND,            ACTIVITY_PROVIDING),
    (POINT_NETHERLANDS, TYPE_WIND_OFFSHORE,   ACTIVITY_PROVIDING),
    (POINT_NETHERLANDS, TYPE_FOSSIL_GAS_POWER,ACTIVITY_PROVIDING),
    (POINT_NETHERLANDS, TYPE_FOSSIL_HARD_COAL,ACTIVITY_PROVIDING),
    (POINT_NETHERLANDS, TYPE_NUCLEAR,         ACTIVITY_PROVIDING),
    (POINT_NETHERLANDS, TYPE_BIOMASS_POWER,   ACTIVITY_PROVIDING),
    (POINT_NETHERLANDS, TYPE_OTHER_POWER,     ACTIVITY_PROVIDING),
    # ── Electricity mix — actual data is empty but forecast works ────────────
    # The NED website uses ElectricityMix (type 27) for its own forecast graph.
    (POINT_NETHERLANDS, TYPE_ELECTRICITY_MIX, ACTIVITY_PROVIDING),
    # ── Electricity consumption ──────────────────────────────────────────────
    (POINT_NETHERLANDS, TYPE_ELECTRICITY_LOAD, ACTIVITY_CONSUMING),
    # ── Gas consumption ──────────────────────────────────────────────────────
    (POINT_NETHERLANDS, TYPE_ALL_CONSUMING_GAS, ACTIVITY_CONSUMING),
]

# Types that only publish data at HOURLY granularity.
# If the client is configured for 10-min, these will fall back to hourly.
HOURLY_ONLY_TYPES: frozenset[int] = frozenset({
    TYPE_FOSSIL_GAS_POWER,
    TYPE_FOSSIL_HARD_COAL,
    TYPE_NUCLEAR,
    TYPE_WASTE_POWER,
    TYPE_BIOMASS_POWER,
    TYPE_OTHER_POWER,
    TYPE_ELECTRICITY_MIX,
    TYPE_COFIRING,
    TYPE_GEOTHERMAL,
    TYPE_NATURAL_GAS,
    TYPE_ALL_CONSUMING_GAS,  # total gas consumption — hourly only
    TYPE_ELECTRICITY_LOAD,   # total electricity load — hourly only
})

# Types for which no forecast data exists in the API.
# Queries with these types + CLASSIFICATION_FORECAST will be skipped.
# Types for which the API returns NO forecast data.
# ElectricityMix (27) is NOT in this set — it does have forecast data.
# Individual solar/wind forecasts (types 1,2,17) also have forecast data.
NO_FORECAST_TYPES: frozenset[int] = frozenset({
    TYPE_ALL_CONSUMING_GAS,
    TYPE_ELECTRICITY_LOAD,
    TYPE_FOSSIL_GAS_POWER,
    TYPE_FOSSIL_HARD_COAL,
    TYPE_NUCLEAR,
    TYPE_BIOMASS_POWER,
    TYPE_OTHER_POWER,
    TYPE_WASTE_POWER,
    TYPE_COFIRING,
    TYPE_GEOTHERMAL,
})

# Types for which actual (non-forecast) data is empty — skip actual fetch.
# ElectricityMix providing actual returns empty; only its forecast is valid.
NO_ACTUAL_TYPES: frozenset[int] = frozenset({
    TYPE_ELECTRICITY_MIX,
})


def _extract_list(data: Any) -> list[dict]:
    """Extract records from plain JSON, JSON-LD (hydra:member), or HAL+JSON."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "hydra:member" in data:
            return data["hydra:member"]
        embedded = data.get("_embedded", {})
        if isinstance(embedded, dict):
            for key in ("item", "utilization", "point", "type", "granularity"):
                if key in embedded:
                    return embedded[key]
    _LOGGER.warning("NED.nl: unexpected response format: %s", type(data).__name__)
    return []


class NedApiClient:
    """Async client for the NED.nl v1 API."""

    def __init__(
        self,
        api_key: str,
        session: aiohttp.ClientSession,
        granularity: int = GRANULARITY_10MIN,
        granularity_timezone: int = GRANULARITY_TIMEZONE_AMSTERDAM,
        classification: int = CLASSIFICATION_CURRENT,
        queries: list[tuple[int, int, int]] | None = None,
    ) -> None:
        self.api_key = api_key
        self.session = session
        self.granularity = granularity
        self.granularity_timezone = granularity_timezone
        self.classification = classification
        self.queries = queries or DEFAULT_QUERIES

    def _headers(self) -> dict[str, str]:
        return {
            "X-AUTH-TOKEN": self.api_key,
            "Accept": "application/json",
        }

    async def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{BASE_URL}{path}"
        _LOGGER.debug("NED.nl GET %s params=%s", url, params)
        try:
            async with self.session.get(
                url,
                headers=self._headers(),
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                _LOGGER.debug("NED.nl response: HTTP %s", resp.status)
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except aiohttp.ClientResponseError:
            raise
        except aiohttp.ClientError as err:
            _LOGGER.error("NED.nl connection error for %s: %s", url, err)
            raise

    async def validate_api_key(self) -> bool:
        """Return True if the API key is accepted, False on 401/403."""
        now = datetime.now(tz=timezone.utc)
        params = {
            "point": POINT_NETHERLANDS,
            "type": TYPE_SOLAR,
            "granularity": GRANULARITY_10MIN,
            "granularitytimezone": GRANULARITY_TIMEZONE_AMSTERDAM,
            "classification": CLASSIFICATION_CURRENT,
            "activity": ACTIVITY_PROVIDING,
            "validfrom[after]": (now - timedelta(days=1)).strftime("%Y-%m-%d"),
            "validfrom[strictly_before]": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
            "itemsPerPage": 1,
        }
        try:
            await self._get("/utilizations", params)
            return True
        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                _LOGGER.warning("NED.nl: invalid API key (HTTP %s)", err.status)
                return False
            raise

    async def get_utilizations_for_query(
        self,
        point_id: int,
        type_id: int,
        activity_id: int,
        start: datetime,
        end: datetime,
        classification: int | None = None,
        granularity_override: int | None = None,
    ) -> list[dict]:
        """
        Fetch utilization records for a single (point, type, activity) + time window.

        Parameters follow the official NED.nl API docs exactly:
          point                       – integer point ID
          type                        – integer type ID
          granularity                 – e.g. 3 (10-min) or 5 (hourly)
          granularitytimezone         – 1 = Amsterdam/CET (required for daily+)
          classification              – 2 = current/public, 1 = forecast
          activity                    – 1 = providing
          validfrom[after]            – inclusive start date YYYY-MM-DD
          validfrom[strictly_before]  – exclusive end date   YYYY-MM-DD

        granularity_override forces a specific granularity regardless of the
        client default — used so hourly-only types still work when the client
        is configured for 10-min granularity.
        """
        effective_granularity = granularity_override if granularity_override is not None else self.granularity
        # The NED.nl API only accepts YYYY-MM-DD date strings (not full ISO datetimes).
        # Use date-only format to avoid 403 Forbidden errors.
        params = {
            "point": point_id,
            "type": type_id,
            "granularity": effective_granularity,
            "granularitytimezone": self.granularity_timezone,
            "classification": classification if classification is not None else self.classification,
            "activity": activity_id,
            "validfrom[after]": start.strftime("%Y-%m-%d"),
            "validfrom[strictly_before]": end.strftime("%Y-%m-%d"),
            "itemsPerPage": 200,
            "order[validfrom]": "desc",
        }

        data = await self._get("/utilizations", params)
        records = _extract_list(data)
        _LOGGER.debug(
            "NED.nl: point=%s type=%s activity=%s classification=%s granularity=%s → %d records",
            point_id, type_id, activity_id,
            classification or self.classification, effective_granularity, len(records),
        )
        return records

    async def get_all_utilizations(self) -> dict[str, list[dict]]:
        """
        Fetch the latest actual + forecast utilization data for every configured query.

        For each (point, type, activity) tuple this fetches:
          - "actual"   key: CLASSIFICATION_CURRENT, last 48 h
          - "forecast" key: CLASSIFICATION_FORECAST, next 24 h

        Solar note: we always fetch with 10-min granularity regardless of the
        configured granularity setting so that the most-recent interval is
        never empty just because the current hour isn't finished yet.

        Returns a dict keyed by  "pt_{p}_ty_{t}_ac_{a}_{classification}"
        """
        now = datetime.now(tz=timezone.utc)

        # Actual: last 48 h — wide enough that solar always has a non-zero slot
        actual_start = now - timedelta(hours=48)
        actual_end   = now + timedelta(hours=1)

        # Forecast window: today through 3 days ahead.
        # The API only accepts YYYY-MM-DD date strings so we work in whole days.
        # The coordinator's _next_future() then picks the correct future slot
        # from the returned records regardless of how many past-today slots are included.
        forecast_start = now
        forecast_end   = now + timedelta(days=3)

        results: dict[str, list[dict]] = {}

        for point_id, type_id, activity_id in self.queries:
            # Power-plant / consumption types only publish at hourly granularity.
            if type_id in HOURLY_ONLY_TYPES and self.granularity == GRANULARITY_10MIN:
                gran_override = GRANULARITY_HOURLY
            else:
                gran_override = None

            for classification, start, end in [
                (CLASSIFICATION_CURRENT,  actual_start,   actual_end),
                (CLASSIFICATION_FORECAST, forecast_start, forecast_end),
            ]:
                # Skip forecast fetch for types that have no forecast data.
                if classification == CLASSIFICATION_FORECAST and type_id in NO_FORECAST_TYPES:
                    _LOGGER.debug("NED.nl: skipping forecast for type=%s", type_id)
                    continue
                # Skip actual fetch for types that only have forecast data.
                if classification == CLASSIFICATION_CURRENT and type_id in NO_ACTUAL_TYPES:
                    _LOGGER.debug("NED.nl: skipping actual for type=%s (forecast-only)", type_id)
                    continue

                key = f"pt_{point_id}_ty_{type_id}_ac_{activity_id}_cl_{classification}"
                try:
                    records = await self.get_utilizations_for_query(
                        point_id=point_id,
                        type_id=type_id,
                        activity_id=activity_id,
                        start=start,
                        end=end,
                        classification=classification,
                        granularity_override=gran_override,
                    )
                    results[key] = records
                except Exception as err:  # pylint: disable=broad-except
                    _LOGGER.warning(
                        "NED.nl: skipping key=%s – %s", key, err
                    )
                    results[key] = []

        return results
