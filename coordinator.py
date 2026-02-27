"""Data coordinator for NED.nl integration."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    NedApiClient,
    POINT_NAMES,
    TYPE_NAMES,
    CLASSIFICATION_CURRENT,
    CLASSIFICATION_FORECAST,
)

_LOGGER = logging.getLogger(__name__)

# Poll every 10 minutes — matches the finest granularity available
POLL_INTERVAL = timedelta(minutes=10)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _most_recent(records: list[dict]) -> dict | None:
    """Return the first record (API returns desc order) or None."""
    return records[0] if records else None


def _most_recent_nonzero(records: list[dict], field: str = "volume") -> dict | None:
    """
    Return the most recent record where `field` is non-zero.
    If all records are zero (e.g. no solar at night), still return the most
    recent one — returning None would make the sensor 'unknown', which is
    wrong for thermal plants that have capacity even when not generating.
    """
    for record in records:
        val = _to_float(record.get(field))
        if val is not None and val != 0.0:
            return record
    # All records are zero — still return the latest rather than None
    return _most_recent(records)


def _pct(value: Any) -> float | None:
    """
    Convert API percentage from normalised 0-1 fraction to 0-100 scale.
    The NED.nl API returns values like 0.0597 meaning 5.97%.
    Guard: if the value is already > 1.5 assume it's already in % and skip multiply.
    """
    f = _to_float(value)
    if f is None:
        return None
    if f > 1.5:
        # Already a percentage value — return as-is (rounded)
        _LOGGER.debug("NED.nl: percentage value %s appears already scaled, using as-is", f)
        return round(f, 4)
    return round(f * 100, 4)


def _enrich(record: dict, point_id: int, type_id: int, activity_id: int) -> dict:
    """Add human-readable name fields to a raw API record."""
    return {
        **record,
        "capacity":      _to_float(record.get("capacity")),
        "volume":        _to_float(record.get("volume")),
        "percentage":    _pct(record.get("percentage")),
        "emission":      _to_float(record.get("emission")),
        "emissionfactor":_to_float(record.get("emissionfactor")),
        "point_id":      point_id,
        "type_id":       type_id,
        "activity_id":   activity_id,
        "point_name":    POINT_NAMES.get(point_id, f"Point {point_id}"),
        "type_name":     TYPE_NAMES.get(type_id,  f"Type {type_id}"),
    }


class NedDataCoordinator(DataUpdateCoordinator):
    """Fetch NED.nl energy data on a 10-minute schedule."""

    def __init__(self, hass: HomeAssistant, client: NedApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="ned_nl",
            update_interval=POLL_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Fetch fresh data from the NED.nl API.

        Returns a dict with two sub-keys per (point, type, activity):
          "pt_{p}_ty_{t}_ac_{a}_cl_2"  → actual/current record (or None)
          "pt_{p}_ty_{t}_ac_{a}_cl_1"  → forecast record (or None)
        """
        try:
            raw = await self.client.get_all_utilizations()
        except Exception as err:
            raise UpdateFailed(f"Error fetching NED.nl data: {err}") from err

        result: dict[str, Any] = {}

        for key, records in raw.items():
            # Parse the key to extract IDs
            # Format: "pt_{p}_ty_{t}_ac_{a}_cl_{c}"
            try:
                parts = key.split("_")
                point_id    = int(parts[1])
                type_id     = int(parts[3])
                activity_id = int(parts[5])
                classif     = int(parts[7])
            except (IndexError, ValueError):
                _LOGGER.warning("NED.nl: cannot parse coordinator key '%s'", key)
                continue

            type_name = TYPE_NAMES.get(type_id, f"type_{type_id}")

            if not records:
                _LOGGER.warning(
                    "NED.nl: EMPTY response for %s (point=%s type=%s/%s cl=%s) "
                    "— check if this type/point combination is available in the API",
                    key, point_id, type_id, type_name, classif,
                )
                result[key] = None
                continue

            # For actual data use the most-recent non-zero volume slot.
            # For forecast use strictly the most recent (future values may be zero).
            if classif == CLASSIFICATION_CURRENT:
                latest = _most_recent_nonzero(records, field="volume")
            else:
                latest = _most_recent(records)

            if latest is None:
                result[key] = None
            else:
                enriched = _enrich(latest, point_id, type_id, activity_id)
                _LOGGER.debug(
                    "NED.nl: %s/%s cl=%s → capacity=%s volume=%s pct=%s validfrom=%s",
                    type_name, point_id, classif,
                    enriched.get("capacity"), enriched.get("volume"),
                    enriched.get("percentage"), latest.get("validfrom"),
                )
                result[key] = enriched

        return result
