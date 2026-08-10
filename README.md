# Casual Theme Trend Analysis

## Requirements

- Python 3.12

## Local installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Run

```powershell
python -m src
```

## Tests and quality checks

```powershell
pytest
ruff check .
mypy src
```

## Sensor Tower source contract parser

The initial Sensor Tower parser handles a verified response sample for local
testing. It does not make network calls, and the semantics of
`current_units_value` and `current_revenue_value` remain pending API-contract
confirmation.

## Sensor Tower market candidates

The implemented market boundary uses the verified unified endpoint
`/v1/unified/sales_report_estimates_comparison_attributes` with the project
scope `category=7012`, `country=WW`, `device_type=total`, and Game Genre
`Puzzle` or `Tabletop`. The request uses `date` and `end_date`; it never sends
`start_date`.

The API is asked for up to `sensor_tower_api_limit` candidates (default `1200`).
Local filtering then preserves source order, removes missing or disallowed
genres, optionally removes records whose `Most Popular Country by Revenue` is
`China`, and retains at most `sensor_tower_final_top_n` records (default
`1000`). Metadata enrichment, pagination, retries, persistence, aggregation,
and Trend Score are not part of this boundary.

The verified request-boundary settings are available through `AppConfig`, YAML,
or the matching `APP_` environment variables: endpoint path, category, country,
device type, custom-tags mode, data model, custom-field name, and its global and
exclude flags. `AppConfig.build_sensor_tower_market_request()` derives the
request and local selection settings from one validated configuration. The
outbound custom-field filter is built from the same allowed genres and filter
settings; an explicitly supplied inconsistent filter is rejected.

For local credentials, copy `.env.example` to `.env` and set
`APP_SENSOR_TOWER_AUTH_TOKEN`. The token is never included in logs, object
representations, or sanitized exception messages. Automated tests use an
in-memory HTTP mock and never access the real Sensor Tower network.
