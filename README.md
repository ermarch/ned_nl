# NED.nl Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A custom Home Assistant integration for live Dutch electricity grid data from the [NED.nl API](https://api.ned.nl).

## Features

- **Actual + Forecast sensors** — current production AND upcoming forecast for each energy type
- **54 sensors** per point: 9 energy types × (3 actual + 3 forecast) metrics
- Metrics per source: **Capacity** (kW), **Volume** (kWh), **Utilization %**
- **Energy Dashboard ready** — volume sensors use `total_increasing` state class
- **Options flow** — change granularity and monitored regions after setup, no reinstall needed
- **10-minute polling** — uses NED.nl's finest granularity for most up-to-date solar/wind data
- Dutch & English UI

## Installation

### Via HACS (recommended)
1. HACS → Integrations → ⋮ → Custom repositories
2. Add this repository URL, category **Integration**
3. Install **NED.nl Energy Data** and restart Home Assistant

### Manual
1. Copy files → `config/custom_components/ned_nl`
2. Restart Home Assistant

### Install the dashboard
The graphs use custom:apexcharts-card which you can install via HACS if you don't have it already.

## Setup

1. **Settings → Devices & Services → Add Integration → NED.nl**
2. Enter your API key (register free at [ned.nl/nl/registreer](https://ned.nl/nl/registreer))
3. Choose granularity (10-min recommended for solar/wind)
4. Select which geographic points to monitor

## Sensor reference

| Sensor | Unit | Notes |
|--------|------|-------|
| `…_capacity` | kW | Installed capacity for the period |
| `…_volume` | kWh | Energy produced – feeds HA Energy Dashboard |
| `…_percentage` | % | Utilisation of installed capacity |
| `…_forecast_capacity` | kW | Upcoming forecast capacity |
| `…_forecast_volume` | kWh | Upcoming forecast volume |
| `…_forecast_percentage` | % | Upcoming forecast utilisation |

### Example IDs
```
sensor.ned_nl_netherlands_solar_volume
sensor.ned_nl_netherlands_wind_offshore_capacity
sensor.ned_nl_netherlands_solar_forecast_volume
sensor.ned_nl_noord_holland_solar_percentage
```

### Attributes on every sensor
- `validfrom` / `validto` — time interval this record covers
- `lastupdate` — when NED.nl last updated this record
- `is_forecast` — `true` for forecast sensors
- `emission_co2_kg`, `emissionfactor_kg_per_kwh` — CO₂ data where available

## Energy Dashboard

Add any `*_volume` sensor to **Settings → Energy → Add source**.  
Solar and wind volume sensors work best; they use `state_class: total_increasing`.

## Options

After setup, go to **Settings → Devices & Services → NED.nl → Configure** to change:
- **Granularity**: 10-min / Hourly / Daily
- **Points**: which provinces / offshore areas to monitor

Changes take effect immediately (integration reloads automatically).

## Why does solar show zero at night?

It shouldn't with this version — the coordinator now uses a **48-hour lookback window** and picks the **most recent non-zero slot**, so you always see the last actual production reading. The sensor will only be 0 if the entire last 48 hours had zero solar production (e.g. prolonged cloud cover or winter nights).

## API reference

- Docs: https://ned.nl/nl/handleiding-api  
- Swagger UI: https://api.ned.nl/v1  
- Rate limit: 200 requests per 5 minutes
