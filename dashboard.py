"""Generate a Lovelace dashboard YAML from the actual HA entity registry."""
from __future__ import annotations

import logging
import yaml

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .api import (
    ACTIVITY_PROVIDING,
    ACTIVITY_NAMES,
    CLASSIFICATION_CURRENT,
    CLASSIFICATION_FORECAST,
    NO_ACTUAL_TYPES,
    NO_FORECAST_TYPES,
    TYPE_NAMES,
)

_LOGGER = logging.getLogger(__name__)

# ── LiteralStr renders as YAML block scalar (|) ──────────────────────────────
class LiteralStr(str):
    pass

def _literal_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")

yaml.add_representer(LiteralStr, _literal_representer)

_COLORS: dict[int, str] = {
    2:  "#f9c74f", 1:  "#90be6d", 17: "#43aa8b", 18: "#f8961e",
    19: "#6c757d", 20: "#277da1", 25: "#4d908e", 26: "#adb5bd",
    27: "#a78bfa", 59: "#e63946", 56: "#ff9f1c",
}
_EMOJIS: dict[int, str] = {
    2: "☀️", 1: "💨", 17: "🌊", 18: "🔥", 19: "⚫",
    20: "⚛️", 25: "🌿", 26: "➕", 27: "⚡", 59: "⚡", 56: "🏭",
}

def _uid(point_id, type_id, activity_id, classification, metric_key):
    return f"ned_nl_pt_{point_id}_ty_{type_id}_ac_{activity_id}_cl_{classification}_{metric_key}"

def _lookup(reg, point_id, type_id, activity_id, classification, metric_key):
    return reg.async_get_entity_id("sensor", "ned_nl",
        _uid(point_id, type_id, activity_id, classification, metric_key))

def _entities_card(title, rows):
    return {"type": "entities", "title": title, "show_header_toggle": False,
            "entities": [{"entity": e, "name": n} for e, n in rows]}

def _mini_graph(title, hours, group_by, series):
    return {"type": "custom:mini-graph-card", "name": title,
            "hours_to_show": hours, "group_by": group_by,
            "aggregate_func": "last",
            "hour24": True,
            "show": {
                "legend": len(series) > 1,
                "labels": True,
                "extrema": True,
            },
            "entities": [{"entity": e, "name": n, "color": c} for e, n, c in series]}

def _gauge(entity_id, name):
    return {"type": "gauge", "entity": entity_id, "name": name,
            "min": 0, "max": 100, "needle": True,
            "severity": {"green": 40, "yellow": 15, "red": 0}}

def _hstack(cards):
    return {"type": "horizontal-stack", "cards": cards}

_DATA_GENERATOR = LiteralStr(
    "const s = entity.attributes.forecast_series;\n"
    "if (!s || !Array.isArray(s) || s.length === 0) return [];\n"
    "return s;\n"
)

def _apexcharts(title, series):
    # When using data_generator, omit span and apex_config xaxis —
    # the card determines the x-axis range from the returned data.
    return {
        "type": "custom:apexcharts-card",
        "header": {"show": True, "title": title},
        "chart_type": "line",
        "graph_span": "48h",
        "span": {"start": "hour"},
        "now": {"show": True, "label": "now"},
        "series": [{"entity": e, "name": n, "color": c,
                    "data_generator": _DATA_GENERATOR}
                   for e, n, c in series],
    }


def _history_graph(title, entities):
    """Built-in history-graph card — no HACS required."""
    return {
        "type": "history-graph",
        "title": title,
        "hours_to_show": 24,
        "entities": [{"entity": e, "name": n} for e, n in entities],
    }

async def async_generate_dashboard(hass: HomeAssistant,
                                   queries: list[tuple[int, int, int]]) -> None:
    reg = er.async_get(hass)

    actual_vol: dict[tuple, str] = {}
    actual_pct: dict[tuple, str] = {}
    fc_vol:     dict[tuple, str] = {}
    fc_pct:     dict[tuple, str] = {}

    for (point_id, type_id, activity_id) in queries:
        key = (point_id, type_id, activity_id)
        if type_id not in NO_ACTUAL_TYPES:
            if e := _lookup(reg, point_id, type_id, activity_id, CLASSIFICATION_CURRENT, "volume"):
                actual_vol[key] = e
            if e := _lookup(reg, point_id, type_id, activity_id, CLASSIFICATION_CURRENT, "percentage"):
                actual_pct[key] = e
        if type_id not in NO_FORECAST_TYPES:
            if e := _lookup(reg, point_id, type_id, activity_id, CLASSIFICATION_FORECAST, "forecast_volume"):
                fc_vol[key] = e
            if e := _lookup(reg, point_id, type_id, activity_id, CLASSIFICATION_FORECAST, "forecast_percentage"):
                fc_pct[key] = e

    if not actual_vol and not fc_vol:
        _LOGGER.warning("NED.nl dashboard: no entities found — skipping")
        return

    def lbl(key, with_activity=True):
        _, tid, aid = key
        e = _EMOJIS.get(tid, "")
        n = TYPE_NAMES.get(tid, f"Type {tid}")
        if with_activity and aid != ACTIVITY_PROVIDING:
            return f"{e} {n} {ACTIVITY_NAMES.get(aid, '')}".strip()
        return f"{e} {n}".strip()

    def col(key):  return _COLORS.get(key[1], "#aaaaaa")
    def tname(key): return TYPE_NAMES.get(key[1], f"Type {key[1]}")

    prod_keys    = [k for k in actual_vol if k[2] == ACTIVITY_PROVIDING]
    cons_keys    = [k for k in actual_vol if k[2] != ACTIVITY_PROVIDING]
    renew_keys   = [k for k in prod_keys if k[1] in {2, 1, 17}]
    fossil_keys  = [k for k in prod_keys if k[1] in {18, 19}]
    lowcarb_keys = [k for k in prod_keys if k[1] in {20, 25, 2, 1, 17}]
    fc_keys      = list(fc_vol)

    # Overview
    ov_cards = [_entities_card("Current Values",
                    [(actual_vol[k], lbl(k)) for k in prod_keys + cons_keys if k in actual_vol])]
    if renew_keys:
        ov_cards.append(_mini_graph("Renewables - 24h", 24, "hour",
                         [(actual_vol[k], tname(k), col(k)) for k in renew_keys]))
    if prod_keys:
        ov_cards.append(_mini_graph("All Production - 24h", 24, "hour",
                         [(actual_vol[k], tname(k), col(k)) for k in prod_keys]))

    # Percentages
    pct_cards = []
    gk = [k for k in renew_keys if k in actual_pct][:3]
    if gk:
        pct_cards.append(_hstack([_gauge(actual_pct[k], tname(k)) for k in gk]))
    pr = [(actual_pct[k], lbl(k)) for k in prod_keys + cons_keys if k in actual_pct]
    if pr:
        pct_cards.append(_entities_card("Utilisation %", pr))
    if renew_keys:
        pct_cards.append(_mini_graph("Renewable % - 24h", 24, "hour",
                          [(actual_pct[k], tname(k), col(k)) for k in renew_keys if k in actual_pct]))

    # Consumption
    cons_cards = []
    if cons_keys:
        cr = []
        for k in cons_keys:
            if k in actual_vol: cr.append((actual_vol[k], lbl(k)))
            if k in actual_pct: cr.append((actual_pct[k], lbl(k) + " %"))
        if cr: cons_cards.append(_entities_card("Consumption", cr))
        for k in cons_keys:
            if k in actual_vol:
                cons_cards.append(_mini_graph(f"{lbl(k, False)} - 24h", 24, "hour",
                                   [(actual_vol[k], lbl(k, False), col(k))]))

    # Forecast
    fc_cards = []
    if fc_keys:
        fr = []
        for k in fc_keys:
            if k in fc_vol: fr.append((fc_vol[k], lbl(k)))
            if k in fc_pct: fr.append((fc_pct[k], lbl(k) + " %"))
        fc_cards.append(_entities_card("Next forecast slot", fr))
        for k in fc_keys:
            if k in fc_vol:
                fc_cards.append(_apexcharts(
                    f"{tname(k)} Forecast - next 48h",
                    [(fc_vol[k], tname(k), col(k))]))

    # CO2
    co2_cards = []
    cr2 = [(actual_vol[k], lbl(k)) for k in fossil_keys + lowcarb_keys if k in actual_vol]
    cp2 = [(actual_pct[k], lbl(k) + " %") for k in fossil_keys if k in actual_pct]
    if cr2: co2_cards.append(_entities_card("Fossil & Low-carbon", cr2 + cp2))
    if fossil_keys:
        co2_cards.append(_mini_graph("Fossil Sources - 48h", 48, "hour",
                          [(actual_vol[k], tname(k), col(k)) for k in fossil_keys if k in actual_vol]))
    if lowcarb_keys:
        co2_cards.append(_mini_graph("Low-carbon Sources - 48h", 48, "hour",
                          [(actual_vol[k], tname(k), col(k)) for k in lowcarb_keys if k in actual_vol]))

    def _view(title, path, icon, cards):
        return {"title": title, "path": path, "icon": icon, "cards": cards}

    views = [_view("Overview", "ned-overview", "mdi:lightning-bolt-circle", ov_cards)]
    if pct_cards:  views.append(_view("Percentages", "ned-percentages", "mdi:percent", pct_cards))
    if cons_cards: views.append(_view("Consumption", "ned-consumption", "mdi:home-lightning-bolt", cons_cards))
    if fc_cards:   views.append(_view("Forecast",    "ned-forecast",    "mdi:chart-line", fc_cards))
    if co2_cards:  views.append(_view("CO₂",         "ned-co2",         "mdi:molecule-co2", co2_cards))

    yaml_content = (
        "# NED.nl Energy Dashboard — auto-generated, do not edit manually.\n"
        + yaml.dump({"title": "NED.nl Energy", "views": views},
                    allow_unicode=True, default_flow_style=False, sort_keys=False)
    )

    dashboard_path = hass.config.path("ned_nl_dashboard.yaml")
    try:
        def _write():
            with open(dashboard_path, "w", encoding="utf-8") as f:
                f.write(yaml_content)
        await hass.async_add_executor_job(_write)
        _LOGGER.info("NED.nl: dashboard written to %s (%d views)",
                     dashboard_path, len(views))
    except OSError as err:
        _LOGGER.error("NED.nl: could not write dashboard: %s", err)
