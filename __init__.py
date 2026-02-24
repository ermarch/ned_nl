from .const import DOMAIN, CONF_API_KEY, COORDINATOR
from .coordinator import NedCoordinator


async def async_setup_entry(hass, entry):
    coordinator = NedCoordinator(hass, entry.data[CONF_API_KEY])

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        COORDINATOR: coordinator
    }

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    return True
