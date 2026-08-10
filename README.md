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
`1000`). Metadata enrichment is requested only for those final selected
records; pagination, persistence, aggregation, and Trend Score remain outside
this boundary.

The verified request-boundary settings are available through `AppConfig`, YAML,
or the matching `APP_` environment variables for visibility. The current MVP
supports only `filter_field_name="Game Genre"`, `filter_global=true`,
`filter_exclude=false`, and allowed genres `Puzzle` and `Tabletop`; unsupported
filter-scope changes fail configuration validation instead of being silently
reinterpreted by local selection. `AppConfig.build_sensor_tower_market_request()`
derives the request and local selection settings from one validated
configuration. The outbound custom-field filter is built from the approved
scope and an explicitly supplied inconsistent filter is rejected. The request
and client endpoint paths must also match; a mismatch fails before network
access.

For local credentials, copy `.env.example` to `.env` and set
`APP_SENSOR_TOWER_AUTH_TOKEN`. The token is never included in logs, object
representations, or sanitized exception messages. Automated tests use an
in-memory HTTP mock and never access the real Sensor Tower network.

## Sensor Tower unified app metadata enrichment

ST-003 uses the verified `GET /v1/unified/apps` endpoint at
`https://api.sensortower.com`. It sends exactly these query parameters:
`app_id_type=unified`, comma-separated `app_ids`, the comma-separated fields
`name,publisher,android_publisher_ids,itunes_publisher_ids,android_apps,itunes_apps,unified_app_id`,
and `auth_token`.

Metadata is requested only after local eligibility filtering and final
`final_top_n` selection. IDs are deduplicated in first-seen order and fetched
in batches of at most 50; 1,000 unique selected records therefore make 20
metadata requests. Selected market-record order is preserved when metadata is
attached, and a missing metadata response keeps its market record with
`metadata=None`.

Publisher display names follow the verified Apps Script precedence:
`android_publisher_ids[0]` with `+` changed to a space, then `publisher.name`,
then `itunes_publisher_ids[0]` converted to text, otherwise unavailable.
Internal missing names and publishers remain `None`; the adapter does not use
`"Unknown"` or `"N/A"`.

The default operational behavior is two retries after the initial failed
attempt (at most three attempts per batch), a 1.5-second retry delay, and a
0.3-second delay only between batches. A final failure raises a sanitized
batch error without IDs, URLs, tokens, or the original HTTPX exception chain.

The existing Google Sheets cache contract is documented for compatibility:
maximum age 14 days, key `unified_app_id`, cached values `name`, `publisher`,
`androidId`, `iosId`, and `updatedAt`, with only missing or expired IDs fetched.
ST-003 does not persist this cache; persistent caching is deferred to the
DuckDB storage issue. The endpoint response shape is verified from the working
Apps Script contract, while the automated metadata responses are explicitly
synthetic contract fixtures rather than captured private exports.
