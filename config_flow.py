import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, CONF_API_KEY, CONF_SCAN_INTERVAL

class NedConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for NED integration."""

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            # Convert comma or space separated intervals if needed
            return self.async_create_entry(title="NED Electricity Prices", data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_API_KEY): str,
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int
        })

        return self.async_show_form(step_id="user", data_schema=schema)
