"""Sensor platform for NED.nl integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import (
    ACTIVITY_PROVIDING,
    ACTIVITY_CONSUMING,
    ACTIVITY_IMPORT,
    ACTIVITY_EXPORT,
    CLASSIFICATION_CURRENT,
    CLASSIFICATION_FORECAST,
    NO_ACTUAL_TYPES,
    NO_FORECAST_TYPES,
    POINT_NAMES,
    TYPE_NAMES,
)

ACTIVITY_NAMES: dict[int, str] = {
    ACTIVITY_PROVIDING: "Production",
    ACTIVITY_CONSUMING: "Consumption",
    ACTIVITY_IMPORT:    "Import",
    ACTIVITY_EXPORT:    "Export",
}
from .const import DOMAIN
from .coordinator import NedDataCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class NedSensorDescription(SensorEntityDescription):
    """One metric for one (point, type, activity, classification) combo."""
    value_field: str = "volume"
    is_forecast: bool = False


# ── Actual / current sensors ─────────────────────────────────────────────────
# Units are stored as W / Wh (API returns kW / kWh, converted on read ×1000).
# HA auto-scales W → kW → MW → GW based on magnitude, keeping display tidy.
_ACTUAL_METRICS: list[NedSensorDescription] = [

    NedSensorDescription(
        key="volume",
        native_unit_of_measurement=UnitOfEnergy.MEGA_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lightning-bolt",
        value_field="volume",
        suggested_display_precision=2,
    ),
    NedSensorDescription(
        key="percentage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        value_field="percentage",
        suggested_display_precision=1,
    ),
]

# ── Forecast sensors ──────────────────────────────────────────────────────────
# No state_class: forecasts are predictions, not measurements. Without
# state_class HA does not attempt to compile long-term statistics for these
# sensors, avoiding unit-mismatch warnings when the unit changes.
_FORECAST_METRICS: list[NedSensorDescription] = [

    NedSensorDescription(
        key="forecast_volume",
        native_unit_of_measurement=UnitOfEnergy.MEGA_WATT_HOUR,
        icon="mdi:lightning-bolt-outline",
        value_field="volume",
        is_forecast=True,
        suggested_display_precision=2,
    ),
    NedSensorDescription(
        key="forecast_percentage",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:chart-line",
        value_field="percentage",
        is_forecast=True,
        suggested_display_precision=1,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create sensors for every (point, type, activity, metric, classification)."""
    coordinator: NedDataCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[NedSensor] = []
    for (point_id, type_id, activity_id) in coordinator.client.queries:
        point_name = POINT_NAMES.get(point_id, f"Point {point_id}")
        type_name  = TYPE_NAMES.get(type_id,   f"Type {type_id}")

        # Skip actual sensors for types that only have forecast data.
        if type_id not in NO_ACTUAL_TYPES:
            for metric in _ACTUAL_METRICS:
                entities.append(NedSensor(
                    coordinator=coordinator,
                    point_id=point_id,
                    type_id=type_id,
                    activity_id=activity_id,
                    classification=CLASSIFICATION_CURRENT,
                    point_name=point_name,
                    type_name=type_name,
                    metric=metric,
                ))

        # Only create forecast sensors for types that actually have forecast data.
        if type_id not in NO_FORECAST_TYPES:
            for metric in _FORECAST_METRICS:
                entities.append(NedSensor(
                    coordinator=coordinator,
                    point_id=point_id,
                    type_id=type_id,
                    activity_id=activity_id,
                    classification=CLASSIFICATION_FORECAST,
                    point_name=point_name,
                    type_name=type_name,
                    metric=metric,
                ))

    async_add_entities(entities)


class NedSensor(CoordinatorEntity[NedDataCoordinator], SensorEntity):
    """A single NED.nl sensor for one point/type/activity/classification/metric."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NedDataCoordinator,
        point_id: int,
        type_id: int,
        activity_id: int,
        classification: int,
        point_name: str,
        type_name: str,
        metric: NedSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._point_id       = point_id
        self._type_id        = type_id
        self._activity_id    = activity_id
        self._classification  = classification
        self._metric         = metric

        # Stable coordinator lookup key
        self._data_key = (
            f"pt_{point_id}_ty_{type_id}_ac_{activity_id}_cl_{classification}"
        )

        # e.g. "ned_nl_pt0_ty2_ac1_cl2_volume"
        self._attr_unique_id = f"ned_nl_{self._data_key}_{metric.key}"

        # Sensor name excludes point_name — the device card already shows the region.
        # e.g. "Solar Capacity" / "Electricity Load Consumption Capacity"
        label = metric.key.replace("forecast_", "Forecast ").replace("_", " ").title()
        activity_label = ACTIVITY_NAMES.get(activity_id, "")
        if activity_id != ACTIVITY_PROVIDING:
            self._attr_name = f"{type_name} {activity_label} {label}"
        else:
            self._attr_name = f"{type_name} {label}"

        # native_unit_of_measurement is a dynamic property — not set here
        self._attr_device_class  = metric.device_class
        self._attr_state_class   = metric.state_class
        self._attr_icon          = metric.icon

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"ned_nl_p{point_id}")},
            name=f"NED.nl – {point_name}",
            manufacturer="NED.nl / Nationaal Energie Dashboard",
            model="Dutch Energy Grid",
            configuration_url="https://ned.nl",
        )

    # ── Dynamic unit scaling ────────────────────────────────────────────────
    # Raw values from the coordinator are in MW / MWh / %.
    # We scale up to GW/GWh when ≥ 1000, down to kW/kWh when < 1,
    # and all the way to W/Wh when < 0.001 — keeping 2–4 significant digits.

    _POWER_UNITS  = [                           # ascending thresholds in MW
        (1_000,    UnitOfPower.GIGA_WATT),
        (1,        UnitOfPower.MEGA_WATT),
        (0.001,    UnitOfPower.KILO_WATT),
        (0,        UnitOfPower.WATT),
    ]
    _ENERGY_UNITS = [                           # ascending thresholds in MWh
        (1_000,    UnitOfEnergy.GIGA_WATT_HOUR),
        (1,        UnitOfEnergy.MEGA_WATT_HOUR),
        (0.001,    UnitOfEnergy.KILO_WATT_HOUR),
        (0,        UnitOfEnergy.WATT_HOUR),
    ]
    # Conversion factors from MW / MWh to each target unit
    _POWER_FACTOR  = {
        UnitOfPower.GIGA_WATT:  1e-3,
        UnitOfPower.MEGA_WATT:  1.0,
        UnitOfPower.KILO_WATT:  1e3,
        UnitOfPower.WATT:       1e6,
    }
    _ENERGY_FACTOR = {
        UnitOfEnergy.GIGA_WATT_HOUR:  1e-3,
        UnitOfEnergy.MEGA_WATT_HOUR:  1.0,
        UnitOfEnergy.KILO_WATT_HOUR:  1e3,
        UnitOfEnergy.WATT_HOUR:       1e6,
    }

    def _scaled(self) -> tuple[float | None, str | None]:
        """Return (scaled_value, unit) choosing the most readable SI prefix.

        Values are stored in MW / MWh by the coordinator. We pick the most
        human-readable SI prefix: GW for ≥1000 MW, MW for ≥1, kW for ≥0.001,
        W below that.
        """
        record = self._record
        if not record:
            return None, self._metric.native_unit_of_measurement

        raw = record.get(self._metric.value_field)
        if raw is None:
            return None, self._metric.native_unit_of_measurement

        base_unit = self._metric.native_unit_of_measurement

        if base_unit == UnitOfPower.MEGA_WATT:
            table, factors = self._POWER_UNITS, self._POWER_FACTOR
        elif base_unit == UnitOfEnergy.MEGA_WATT_HOUR:
            table, factors = self._ENERGY_UNITS, self._ENERGY_FACTOR
        else:
            return raw, base_unit  # percentage — return as-is

        # Sanity-correct for entities that HA may have registered in an older
        # unit: if a value that should be MW looks implausibly large (> 100 GW)
        # it is probably still in kW — divide by 1000 to bring back to MW.
        mw_val = raw
        if abs(mw_val) > 100_000:          # > 100 GW is not realistic for NL
            mw_val = mw_val / 1_000        # kW → MW correction
        if abs(mw_val) > 100_000_000:      # still huge → was in W
            mw_val = mw_val / 1_000        # W → kW → MW second pass

        abs_mw = abs(mw_val)
        for threshold, unit in table:
            if abs_mw >= threshold:
                return round(mw_val * factors[unit], 3), unit

        return mw_val, table[-1][1]  # fallback: smallest unit

    @property
    def native_value(self) -> float | None:
        return self._scaled()[0]

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._scaled()[1]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        record = self._record
        if not record:
            return {}
        attrs: dict[str, Any] = {
            "point_name":              record.get("point_name"),
            "type_name":               record.get("type_name"),
            "is_forecast":             self._metric.is_forecast,
            "validfrom":               record.get("validfrom"),
            "validto":                 record.get("validto"),
            "lastupdate":              record.get("lastupdate"),
            "emission_co2_kg":         record.get("emission"),
            "emissionfactor_kg_per_kwh": record.get("emissionfactor"),
        }
        # Expose the full upcoming forecast series for custom dashboard cards
        # (e.g. custom:apexcharts-card with data_generator).
        # Only the capacity sensor carries this to avoid tripling the attribute data.
        if self._metric.is_forecast and self._metric.key == "forecast_capacity":
            series = record.get("_forecast_series")
            if series:
                attrs["forecast_series"] = series
        return attrs

    @property
    def _record(self) -> dict | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._data_key)
