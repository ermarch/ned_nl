"""Config flow + options flow for NED.nl integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import (
    NedApiClient,
    GRANULARITY_10MIN,
    GRANULARITY_HOURLY,
    GRANULARITY_DAILY,
    GRANULARITY_TIMEZONE_AMSTERDAM,
    CLASSIFICATION_CURRENT,
    POINT_NAMES,
    DEFAULT_QUERIES,
)
from .const import DOMAIN, CONF_GRANULARITY, CONF_POINTS

_LOGGER = logging.getLogger(__name__)

GRANULARITY_OPTIONS = {
    str(GRANULARITY_10MIN):  "10 minutes (most up-to-date, recommended)",
    str(GRANULARITY_HOURLY): "Hourly",
    str(GRANULARITY_DAILY):  "Daily",
}

POINT_OPTIONS = {str(k): v for k, v in POINT_NAMES.items()}


class NedNlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = NedApiClient(
                api_key=user_input["api_key"],
                session=session,
                granularity=int(user_input.get(CONF_GRANULARITY, GRANULARITY_10MIN)),
                granularity_timezone=GRANULARITY_TIMEZONE_AMSTERDAM,
                classification=CLASSIFICATION_CURRENT,
            )

            try:
                valid = await client.validate_api_key()
                if not valid:
                    errors["api_key"] = "invalid_auth"
                else:
                    await self.async_set_unique_id(
                        f"ned_nl_{user_input['api_key'][:8]}"
                    )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title="NED.nl Energy Data",
                        data={"api_key": user_input["api_key"]},
                        options={
                            CONF_GRANULARITY: int(
                                user_input.get(CONF_GRANULARITY, GRANULARITY_10MIN)
                            ),
                            CONF_POINTS: user_input.get(
                                CONF_POINTS, [str(p) for p in {q[0] for q in DEFAULT_QUERIES}]
                            ),
                        },
                    )
            except aiohttp.ClientResponseError as err:
                _LOGGER.error("NED.nl HTTP %s during setup", err.status)
                errors["api_key"] = "invalid_auth" if err.status in (401, 403) else "cannot_connect"
            except (aiohttp.ClientConnectorError, aiohttp.ClientError) as err:
                _LOGGER.error("NED.nl connection error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected NED.nl config flow error")
                errors["base"] = "unknown"

        schema = vol.Schema({
            vol.Required("api_key"): str,
            vol.Optional(CONF_GRANULARITY, default=str(GRANULARITY_10MIN)): SelectSelector(
                SelectSelectorConfig(
                    options=[{"value": k, "label": v} for k, v in GRANULARITY_OPTIONS.items()],
                    mode=SelectSelectorMode.LIST,
                )
            ),
            vol.Optional(CONF_POINTS, default=["0"]): SelectSelector(
                SelectSelectorConfig(
                    options=[{"value": k, "label": v} for k, v in POINT_OPTIONS.items()],
                    mode=SelectSelectorMode.DROPDOWN,
                    multiple=True,
                )
            ),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> NedNlOptionsFlow:
        return NedNlOptionsFlow(config_entry)


class NedNlOptionsFlow(config_entries.OptionsFlow):
    """Allow changing granularity and points after setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_GRANULARITY: int(user_input[CONF_GRANULARITY]),
                    CONF_POINTS: user_input[CONF_POINTS],
                },
            )

        current_gran = str(
            self._config_entry.options.get(CONF_GRANULARITY, GRANULARITY_10MIN)
        )
        current_points = self._config_entry.options.get(
            CONF_POINTS, ["0"]
        )

        schema = vol.Schema({
            vol.Required(CONF_GRANULARITY, default=current_gran): SelectSelector(
                SelectSelectorConfig(
                    options=[{"value": k, "label": v} for k, v in GRANULARITY_OPTIONS.items()],
                    mode=SelectSelectorMode.LIST,
                )
            ),
            vol.Required(CONF_POINTS, default=current_points): SelectSelector(
                SelectSelectorConfig(
                    options=[{"value": k, "label": v} for k, v in POINT_OPTIONS.items()],
                    mode=SelectSelectorMode.DROPDOWN,
                    multiple=True,
                )
            ),
        })

        return self.async_show_form(step_id="init", data_schema=schema)
