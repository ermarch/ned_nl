from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .const import DOMAIN, DEFAULT_SCAN_INTERVAL
from .coordinator import NedCoordinator
PLATFORMS = ["sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    scan_interval = entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL)
    api_key = entry.data.get("api_key")

    coordinator = NedCoordinator(hass, api_key, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True
