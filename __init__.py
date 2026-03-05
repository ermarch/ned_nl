"""NED.nl Home Assistant Integration.

Provides live Dutch electricity grid data from the NED.nl API.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    NedApiClient,
    DEFAULT_QUERIES,
    GRANULARITY_10MIN,
    GRANULARITY_TIMEZONE_AMSTERDAM,
    CLASSIFICATION_CURRENT,
    POINT_NAMES,
    TYPE_NAMES,
)
from .const import DOMAIN, CONF_GRANULARITY, CONF_POINTS

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


def _build_queries(option_points: list[str]) -> list[tuple[int, int, int]]:
    """
    Build query tuples for the selected points.
    Uses the full DEFAULT_QUERIES list filtered to the chosen points,
    so each selected point gets all default energy-type sensors.
    """
    selected = {int(p) for p in option_points}
    # Include queries for selected points; fall back to all defaults if none match
    filtered = [q for q in DEFAULT_QUERIES if q[0] in selected]
    return filtered or DEFAULT_QUERIES


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up NED.nl from a config entry."""
    options = entry.options
    granularity = options.get(CONF_GRANULARITY, GRANULARITY_10MIN)
    point_strings = options.get(CONF_POINTS, ["0"])

    queries = _build_queries(point_strings)

    session = async_get_clientsession(hass)
    client = NedApiClient(
        api_key=entry.data["api_key"],
        session=session,
        granularity=granularity,
        granularity_timezone=GRANULARITY_TIMEZONE_AMSTERDAM,
        classification=CLASSIFICATION_CURRENT,
        queries=queries,
    )

    from .coordinator import NedDataCoordinator
    coordinator = NedDataCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Generate the Lovelace dashboard. We call it directly here (after
    # async_forward_entry_setups) so sensors are already in the registry
    # and the file exists before HA's Lovelace tries to read it.
    from .dashboard import async_generate_dashboard
    await async_generate_dashboard(hass, queries)

    # Re-setup when options change (granularity / points)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up when the integration is deleted."""
    import os
    dashboard_path = hass.config.path("ned_nl_dashboard.yaml")
    try:
        await hass.async_add_executor_job(os.remove, dashboard_path)
        _LOGGER.info("NED.nl: removed dashboard file %s", dashboard_path)
    except FileNotFoundError:
        pass
    except OSError as err:
        _LOGGER.warning("NED.nl: could not remove dashboard file: %s", err)
