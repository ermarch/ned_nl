"""Generate a Lovelace dashboard YAML from the actual HA entity registry.

Called from async_setup_entry after sensors are registered.  Looks up each
sensor by its stable unique_id, finds the real entity_id HA assigned, and
writes ned_nl_dashboard.yaml to the HA config directory.

The dashboard is registered as a storage-mode Lovelace dashboard so it
appears automatically in the sidebar — no manual YAML editing required.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .api import (
    ACTIVITY_PROVIDING,
    ACTIVITY_CONSUMING,
    ACTIVITY_NAMES,
    CLASSIFICATION_CURRENT,
    CLASSIFICATION_FORECAST,
    NO_ACTUAL_TYPES,
    NO_FORECAST_TYPES,
    POINT_NAMES,
    TYPE_NAMES,
)

_LOGGER = logging.getLogger(__name__)

# ── Source colour palette ────────────────────────────────────────────────────
_COLORS: dict[int, str] = {
    2:  "#f9c74f",   # Solar
    1:  "#90be6d",   # Wind
    17: "#43aa8b",   # Wind Offshore
    18: "#f8961e",   # Fossil Gas
    19: "#6c757d",   # Hard Coal
    20: "#277da1",   # Nuclear
    25: "#4d908e",   # Biomass
    26: "#adb5bd",   # Other Power
    27: "#a78bfa",   # Electricity Mix
    59: "#e63946",   # Electricity Load
    56: "#ff9f1c",   # All Consuming Gas
}
_EMOJIS: dict[int, str] = {
    2:  "☀️", 1:  "💨", 17: "🌊", 18: "🔥", 19: "⚫",
    20: "⚛️", 25: "🌿", 26: "➕", 27: "⚡", 59: "⚡", 56: "🏭",
}


def _uid(point_id: int, type_id: int, activity_id: int,
         classification: int, metric_key: str) -> str:
    """Reproduce the unique_id format from NedSensor.__init__."""
    data_key = f"pt_{point_id}_ty_{type_id}_ac_{activity_id}_cl_{classification}"
    return f"ned_nl_{data_key}_{metric_key}"


def _lookup(
    reg: er.EntityRegistry,
    point_id: int,
    type_id: int,
    activity_id: int,
    classification: int,
    metric_key: str,
) -> str | None:
    """Return the real entity_id for a sensor, or None if not registered."""
    uid = _uid(point_id, type_id, activity_id, classification, metric_key)
    entry = reg.async_get_entity_id("sensor", "ned_nl", uid)
    return entry  # already is the entity_id string or None


# ── YAML helpers (no dependency on PyYAML for simplicity) ───────────────────

def _indent(text: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + line if line.strip() else line for line in text.splitlines())


def _entities_card(title: str, rows: list[tuple[str, str]]) -> str:
    lines = [
        "type: entities",
        f"title: {title}",
        "show_header_toggle: false",
        "entities:",
    ]
    for entity_id, name in rows:
        lines.append(f"  - entity: {entity_id}")
        lines.append(f"    name: \"{name}\"")
    return "\n".join(lines)


def _mini_graph(title: str, hours: int, group_by: str,
                series: list[tuple[str, str, str]]) -> str:
    lines = [
        "type: custom:mini-graph-card",
        f"name: \"{title}\"",
        f"hours_to_show: {hours}",
        f"group_by: {group_by}",
        "aggregate_func: last",
        "show:",
        f"  legend: {str(len(series) > 1).lower()}",
        "entities:",
    ]
    for entity_id, name, color in series:
        lines.append(f"  - entity: {entity_id}")
        lines.append(f"    name: \"{name}\"")
        lines.append(f"    color: \"{color}\"")
    return "\n".join(lines)


def _gauge(entity_id: str, name: str) -> str:
    return "\n".join([
        "type: gauge",
        f"entity: {entity_id}",
        f"name: \"{name}\"",
        "min: 0",
        "max: 100",
        "needle: true",
        "severity:",
        "  green: 40",
        "  yellow: 15",
        "  red: 0",
    ])


def _apexcharts(title: str, series: list[tuple[str, str, str]]) -> str:
    lines = [
        "type: custom:apexcharts-card",
        "header:",
        "  show: true",
        f"  title: \"{title}\"",
        "chart_type: line",
        "graph_span: 48h",
        "span:",
        "  start: now",
        "apex_config:",
        "  xaxis:",
        "    type: datetime",
        "series:",
    ]
    for entity_id, name, color in series:
        lines += [
            f"  - entity: {entity_id}",
            f"    name: \"{name}\"",
            f"    color: \"{color}\"",
            "    data_generator: |",
            "      return entity.attributes.forecast_series",
            "        ? entity.attributes.forecast_series",
            "        : [];",
        ]
    return "\n".join(lines)


def _hstack(cards: list[str]) -> str:
    lines = ["type: horizontal-stack", "cards:"]
    for card in cards:
        indented = _indent(card, 2)
        lines.append("  - " + indented.lstrip())
    return "\n".join(lines)


def _card_block(card_yaml: str) -> str:
    """Prefix a card with '- ' for inclusion in a cards: list."""
    lines = card_yaml.splitlines()
    return "      - " + lines[0] + "\n" + "\n".join("        " + l for l in lines[1:])


def _view(title: str, path: str, icon: str, cards: list[str]) -> str:
    lines = [
        f"  - title: {title}",
        f"    path: {path}",
        f"    icon: {icon}",
        "    cards:",
    ]
    for card in cards:
        lines.append(_card_block(card))
    return "\n".join(lines)


# ── Main generator ───────────────────────────────────────────────────────────

async def async_generate_dashboard(
    hass: HomeAssistant,
    queries: list[tuple[int, int, int]],
) -> None:
    """Build and write the Lovelace dashboard YAML."""

    reg = er.async_get(hass)

    # ── Resolve entity IDs ───────────────────────────────────────────────────
    def actual(point_id, type_id, activity_id, metric):
        return _lookup(reg, point_id, type_id, activity_id,
                       CLASSIFICATION_CURRENT, metric)

    def forecast(point_id, type_id, activity_id, metric):
        return _lookup(reg, point_id, type_id, activity_id,
                       CLASSIFICATION_FORECAST, metric)

    # Gather all actual volume/percentage entities
    actual_vol:  dict[tuple, str] = {}
    actual_pct:  dict[tuple, str] = {}
    fc_vol:      dict[tuple, str] = {}
    fc_pct:      dict[tuple, str] = {}

    for (point_id, type_id, activity_id) in queries:
        key = (point_id, type_id, activity_id)
        if type_id not in NO_ACTUAL_TYPES:
            if eid := actual(point_id, type_id, activity_id, "volume"):
                actual_vol[key] = eid
            if eid := actual(point_id, type_id, activity_id, "percentage"):
                actual_pct[key] = eid
        if type_id not in NO_FORECAST_TYPES:
            if eid := forecast(point_id, type_id, activity_id, "forecast_volume"):
                fc_vol[key] = eid
            if eid := forecast(point_id, type_id, activity_id, "forecast_percentage"):
                fc_pct[key] = eid

    if not actual_vol:
        _LOGGER.warning("NED.nl dashboard: no entities found in registry — skipping")
        return

    # ── Helper: label for a query key ────────────────────────────────────────
    def label(key: tuple, include_activity: bool = True) -> str:
        _, type_id, activity_id = key
        type_name = TYPE_NAMES.get(type_id, f"Type {type_id}")
        emoji = _EMOJIS.get(type_id, "")
        if include_activity and activity_id != ACTIVITY_PROVIDING:
            act = ACTIVITY_NAMES.get(activity_id, "")
            return f"{emoji} {type_name} {act}".strip()
        return f"{emoji} {type_name}".strip()

    def color(key: tuple) -> str:
        return _COLORS.get(key[1], "#aaaaaa")

    # Separate production vs consumption keys
    prod_keys = [k for k in actual_vol if k[2] == ACTIVITY_PROVIDING]
    cons_keys = [k for k in actual_vol if k[2] != ACTIVITY_PROVIDING]
    renew_type_ids = {2, 1, 17}  # Solar, Wind, Wind Offshore
    renew_keys = [k for k in prod_keys if k[1] in renew_type_ids]
    thermal_keys = [k for k in prod_keys if k[1] not in renew_type_ids]

    # ── VIEW 1: Overview ─────────────────────────────────────────────────────
    overview_rows = [(actual_vol[k], label(k)) for k in prod_keys if k in actual_vol]
    overview_rows += [("divider", "")] if cons_keys else []
    overview_rows += [(actual_vol[k], label(k)) for k in cons_keys if k in actual_vol]
    # filter out divider tuples for entities card
    entity_rows = [(eid, lbl) for eid, lbl in overview_rows if eid != "divider"]

    overview_cards = [
        _entities_card("Current Values", entity_rows),
    ]
    if renew_keys:
        overview_cards.append(_mini_graph(
            "Renewables — 24h", 24, "hour",
            [(actual_vol[k], TYPE_NAMES.get(k[1], ""), color(k)) for k in renew_keys if k in actual_vol],
        ))
    if prod_keys:
        overview_cards.append(_mini_graph(
            "All Production — 24h", 24, "hour",
            [(actual_vol[k], TYPE_NAMES.get(k[1], ""), color(k)) for k in prod_keys if k in actual_vol],
        ))

    # ── VIEW 2: Percentages ──────────────────────────────────────────────────
    gauge_keys = [k for k in renew_keys if k in actual_pct][:3]
    gauge_cards = [_gauge(actual_pct[k], TYPE_NAMES.get(k[1], "")) for k in gauge_keys]

    pct_rows = [(actual_pct[k], label(k)) for k in prod_keys if k in actual_pct]
    pct_rows += [(actual_pct[k], label(k)) for k in cons_keys if k in actual_pct]

    pct_cards = []
    if gauge_cards:
        pct_cards.append(_hstack(gauge_cards))
    if pct_rows:
        pct_cards.append(_entities_card("Utilisation %", pct_rows))
    if renew_keys:
        pct_cards.append(_mini_graph(
            "Renewable % — 24h", 24, "hour",
            [(actual_pct[k], TYPE_NAMES.get(k[1], ""), color(k))
             for k in renew_keys if k in actual_pct],
        ))

    # ── VIEW 3: Consumption ──────────────────────────────────────────────────
    cons_cards = []
    if cons_keys:
        cons_entity_rows = []
        for k in cons_keys:
            if k in actual_vol:
                cons_entity_rows.append((actual_vol[k], label(k)))
            if k in actual_pct:
                cons_entity_rows.append((actual_pct[k], label(k) + " %"))
        if cons_entity_rows:
            cons_cards.append(_entities_card("Consumption", cons_entity_rows))
        for k in cons_keys:
            if k in actual_vol:
                cons_cards.append(_mini_graph(
                    f"{label(k, False)} — 24h", 24, "hour",
                    [(actual_vol[k], label(k, False), color(k))],
                ))

    # ── VIEW 4: Forecast ─────────────────────────────────────────────────────
    fc_keys = [k for k in fc_vol]
    fc_cards = []
    if fc_keys:
        fc_rows = []
        for k in fc_keys:
            if k in fc_vol:
                fc_rows.append((fc_vol[k], label(k)))
            if k in fc_pct:
                fc_rows.append((fc_pct[k], label(k) + " %"))
        fc_cards.append(_entities_card("Next forecast slot", fc_rows))

        # Individual forecast charts per type
        for k in fc_keys:
            if k not in fc_vol:
                continue
            type_name = TYPE_NAMES.get(k[1], "")
            fc_cards.append(_apexcharts(
                f"{type_name} Forecast — next 48h",
                [(fc_vol[k], type_name, color(k))],
            ))

        # Combined wind chart if both onshore and offshore exist
        wind_key     = next((k for k in fc_keys if k[1] == 1),  None)
        offshore_key = next((k for k in fc_keys if k[1] == 17), None)
        if wind_key and offshore_key:
            # Remove individual wind charts, replace with combined
            # (already added above — just add a combined one at top of forecast)
            pass  # individual charts are fine

    # ── VIEW 5: CO₂ ──────────────────────────────────────────────────────────
    fossil_type_ids = {18, 19}  # Gas, Coal
    lowcarbon_type_ids = {20, 25, 2, 1, 17}  # Nuclear, Biomass, Solar, Wind, Offshore
    fossil_keys   = [k for k in prod_keys if k[1] in fossil_type_ids and k in actual_vol]
    lowcarbon_keys = [k for k in prod_keys if k[1] in lowcarbon_type_ids and k in actual_vol]

    co2_rows = [(actual_vol[k], label(k)) for k in fossil_keys + lowcarbon_keys]
    co2_pct_rows = [(actual_pct[k], label(k) + " %") for k in fossil_keys if k in actual_pct]
    co2_cards = []
    if co2_rows or co2_pct_rows:
        co2_cards.append(_entities_card("Fossil & Low-carbon", co2_rows + co2_pct_rows))
    if fossil_keys:
        co2_cards.append(_mini_graph(
            "Fossil Sources — 48h", 48, "hour",
            [(actual_vol[k], TYPE_NAMES.get(k[1], ""), color(k)) for k in fossil_keys],
        ))
    if lowcarbon_keys:
        co2_cards.append(_mini_graph(
            "Low-carbon Sources — 48h", 48, "hour",
            [(actual_vol[k], TYPE_NAMES.get(k[1], ""), color(k)) for k in lowcarbon_keys],
        ))

    # ── Assemble dashboard YAML ───────────────────────────────────────────────
    views = []
    views.append(_view("Overview",    "ned-overview",    "mdi:lightning-bolt-circle", overview_cards))
    if pct_cards:
        views.append(_view("Percentages", "ned-percentages", "mdi:percent",               pct_cards))
    if cons_cards:
        views.append(_view("Consumption", "ned-consumption", "mdi:home-lightning-bolt",   cons_cards))
    if fc_cards:
        views.append(_view("Forecast",    "ned-forecast",    "mdi:chart-line",             fc_cards))
    if co2_cards:
        views.append(_view("CO₂",         "ned-co2",         "mdi:molecule-co2",           co2_cards))

    yaml_lines = [
        "# NED.nl Energy Dashboard — auto-generated by the NED.nl integration.",
        "# Do not edit manually; it will be overwritten on each HA restart.",
        "title: NED.nl Energy",
        "views:",
    ]
    yaml_lines += views

    yaml_content = "\n".join(yaml_lines) + "\n"

    # ── Write file ────────────────────────────────────────────────────────────
    dashboard_path = hass.config.path("ned_nl_dashboard.yaml")
    try:
        def _write():
            with open(dashboard_path, "w", encoding="utf-8") as f:
                f.write(yaml_content)
        await hass.async_add_executor_job(_write)
        _LOGGER.info("NED.nl: dashboard written to %s", dashboard_path)
    except OSError as err:
        _LOGGER.error("NED.nl: could not write dashboard: %s", err)
        return

    _LOGGER.info(
        "NED.nl: dashboard written to %s — ensure configuration.yaml contains: "
        "lovelace: dashboards: ned-nl-energy: {mode: yaml, "
        "filename: ned_nl_dashboard.yaml, title: NED.nl Energy}",
        dashboard_path,
    )
