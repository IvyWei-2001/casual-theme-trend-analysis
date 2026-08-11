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

The Sensor Tower parser supports both verified market-response variants for
local testing. The earlier sample uses numeric IDs, top-level `custom_tags`,
and a larger metric field set. The current live shape uses opaque string IDs,
`entities[0].custom_tags` overlaid by `aggregate_tags`, and may omit the
current/comparison and generic metric fields. The parser does not make network
calls, and metric semantics remain pending API-contract confirmation.

Live-contract compatibility is deliberately source-preserving: omitted
optional metrics remain `None` and later become SQL `NULL`; `units_absolute`
is not copied into `current_units_value`, and `revenue_absolute` is not copied
into `current_revenue_value`. A missing verified custom-tag shape fails
validation rather than becoming an empty mapping. The live fixture is
synthetic and contains no captured response or real app ID.

All required source and unified identifiers pass through one neutral boundary.
Positive integer fixtures and numeric strings remain compatible, while
non-empty opaque strings are preserved after trimming. Opaque identifiers are
never parsed as integers, hashed, replaced, or exposed in public errors,
logs, or collection summaries.

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

Metadata request IDs support the same opaque string boundary end to end:
comma-separated batches preserve first-seen order, duplicate IDs are removed,
and response integrity checks compare normalized opaque strings. The previous
numeric synthetic IDs remain supported.

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
ST-003 does not persist this cache; DB-001 now provides the local persistent
cache described below. The endpoint response shape is verified from the working
Apps Script contract, while the automated metadata responses are explicitly
synthetic contract fixtures rather than captured private exports.

## Local analytical storage (DB-001)

DuckDB is the local source of truth for the first persistent analytical layer.
The existing `VARCHAR` identifier columns remain unchanged; opaque source and
unified IDs round-trip through metadata cache rows, market snapshots, period
replacement, and Parquet exports. Missing optional market metrics are stored
as SQL `NULL`.
Schema initialization is explicit and creates the versioned `schema_migrations`,
`app_metadata`, and `market_snapshots` tables. A market period is identified by
`scope_name`, `cadence`, `period_start`, and `period_end`; replacing a period
validates the complete selected set and atomically replaces every row for that
composite key. Re-running the same period is idempotent.

`app_metadata` stores only normalized metadata returned by the verified
enrichment boundary. Cache lookup uses `unified_app_id` and a 14-day maximum
age: exactly 14 days is fresh, older rows are stale, and missing rows remain
missing. The lookup never performs network access or an automatic refresh.

Normalized metadata never generates the display fallbacks `"Unknown"` or
`"N/A"`; missing normalized values remain `None`/SQL `NULL`. Raw Sensor Tower
source observations in `market_snapshots` are a separate class: source strings
are preserved literally, including those two values, without trimming or
interpretation. Missing source values remain `None`/SQL `NULL`, and non-string
source values still fail storage validation.

Parquet is an explicit export/archive boundary, not the transactional source of
truth. DB-001 exports both tables with stable columns and ordering, ZSTD
compression, and an atomic temporary-sibling-file replacement. Generated
`data/**/*.duckdb`, WAL, and Parquet files are ignored and must not be committed.

DB-001 does not call Sensor Tower, provide a live collection command, perform
historical backfill, aggregate themes, calculate Trend Score, or synchronize
Feishu. DB-002 adds the first live single-month collection command described
below, HIST-001 adds the manually executable monthly backfill described after
it, and AGG-001 adds the local monthly Game Theme aggregation described below.

## Live single-month collection (DB-002)

Copy `.env.example` to `.env` and set `APP_SENSOR_TOWER_AUTH_TOKEN` for a live
collection. Do not put credentials in `configs/app.example.yaml`.

Validate a completed month without network, database, or output-file access:

```powershell
python -m src collect-month --month 2026-07 --plan-only
```

Collect one completed natural calendar month:

```powershell
python -m src collect-month --month 2026-07
```

Collect and store in DuckDB without exporting Parquet:

```powershell
python -m src collect-month --month 2026-07 --skip-export
```

The command accepts only completed `YYYY-MM` calendar months, uses UTC to
reject the current incomplete month and future months, and sends the month's
real first and last dates as `date` and `end_date`. A live run fetches market
candidates, applies local eligibility filtering, refreshes only stale or
missing metadata IDs, stores the complete period, and optionally exports
`market_snapshots.parquet` and `app_metadata.parquet` under
`APP_EXPORT_DIRECTORY` (default `data/exports`). The metadata cache maximum age
is 14 days; exactly 14 days remains fresh.

DB-002 supports both the earlier sample and the verified live market contract.
It requests metadata only for final selected rows, keeps selected order as
rank order, does not use stale metadata as a refresh fallback, and does not
alter the approved Top-1000 filtering rules.

DuckDB is the source of truth and Parquet is an export. Rerunning a month
replaces that complete stored month rather than appending duplicates. The
single-month workflow remains manual and monthly-first; it does not schedule
jobs, synchronize Feishu, or calculate theme trends.

## Historical monthly backfill (HIST-001)

Backfill uses an inclusive `YYYY-MM` range and processes months oldest to
newest. Plan the range without a token, database, network request, or output
files:

```powershell
python -m src backfill-months --start 2025-08 --end 2026-07 --plan-only
```

Backfill missing months and export both business tables once after all months
complete:

```powershell
python -m src backfill-months --start 2025-08 --end 2026-07
```

Recollect and atomically replace every requested month:

```powershell
python -m src backfill-months --start 2025-08 --end 2026-07 --refresh-existing
```

Backfill DuckDB without Parquet export:

```powershell
python -m src backfill-months --start 2025-08 --end 2026-07 --skip-export
```

Existing non-empty monthly periods are skipped by default. Rerunning after a
failure therefore resumes at the first missing month while preserving earlier
committed periods. One shared metadata cache, client, and DuckDB repository
are reused across the run; requests are sequential and never parallelized.
The final Parquet export runs once, after all requested months are collected or
skipped. A failed collection does not run that final export, while an export
failure leaves valid DuckDB data intact.

The workflow is manual only: scheduling, weekly backfill, Feishu sync,
lifecycle classification, and Trend Score remain deferred.

## Monthly Game Theme aggregation (AGG-001)

AGG-001 aggregates only already stored DuckDB rows. It never constructs a
Sensor Tower client or makes a network request:

```powershell
python -m src aggregate-themes --start 2025-08 --end 2026-07 --plan-only
python -m src aggregate-themes --start 2025-08 --end 2026-07
python -m src aggregate-themes --start 2025-08 --end 2026-07 --skip-export
```

The inclusive range must contain completed UTC calendar months, and every
requested month must already contain a non-empty stored `market_snapshots`
period. The actual stored `snapshot_count` is each month's product-share
denominator; the aggregation never assumes 1,000 rows, pads ranks, or invents
products. Raw `game_theme` strings are grouped exactly as stored: `Unknown`,
`N/A`, empty strings, and other labels are not renamed, trimmed, merged, or
inferred. NULL themes do not create a theme row and are counted separately in
`monthly_market_totals.theme_missing_count`.

Schema version 2 adds the DuckDB derived tables `monthly_market_totals` and
`theme_monthly_metrics`. Monthly totals contain population, theme presence,
current normalized-metadata coverage, and `units_absolute`/
`revenue_absolute` source coverage and sums. Theme metrics contain product
share, Top-100/Top-500 counts, arithmetic average rank, deterministic median
rank, publisher coverage/concentration, and the equivalent source metric sums
and shares. A source metric sum is NULL when its coverage is zero; observed
zero remains zero. Source metric names and business semantics remain
`units_absolute` and `revenue_absolute`; they are not renamed to downloads or
revenue. Theme shares use month-wide denominators that include rows with a
missing theme, so visible theme shares may sum below 1. A zero or unavailable
denominator produces a NULL share.

New entry means that a product entered the current stored monthly Top-N
population and was absent from the immediately preceding stored calendar
month, using `unified_app_id`. It does not mean app release, publication, or
first-ever launch. If the immediately preceding stored month is unavailable,
new-entry fields remain NULL. Publisher metrics use the current normalized
`app_metadata` cache and are not historically versioned; publisher-name
changes are therefore not interpreted as historical events.

The aggregation replacement is one DuckDB transaction covering both derived
tables. DuckDB is the source of truth. The two derived Parquet files are
deterministic exports only:

```text
<export_directory>/monthly_market_totals.parquet
<export_directory>/theme_monthly_metrics.parquet
```

Trend Score, weekly aggregation, lifecycle labels, opportunity ranking,
Feishu, scheduling, and AI summaries are not part of AGG-001.

## Explainable monthly Game Theme trend score (TREND-001)

TREND-001 reads only the stored `monthly_market_totals` and
`theme_monthly_metrics` tables. It never constructs a Sensor Tower client or
makes a network request:

```powershell
python -m src score-themes --start 2025-08 --end 2026-07 --plan-only
python -m src score-themes --start 2025-08 --end 2026-07
python -m src score-themes --start 2025-08 --end 2026-07 --skip-export
python -m src score-themes --start 2025-08 --end 2026-07 --top 20
```

The range must contain at least six consecutive completed UTC calendar months.
Each target uses a six-month rolling window split into recent three and prior
three months. With 2025-08 through 2026-07, target scores are created for
2026-01 through 2026-07. A missing source month is not zero-filled and fails
the run. A raw theme absent from a present month is zero-filled only inside the
trend grid; it does not create or modify `theme_monthly_metrics` rows.

The score combines cross-theme percentiles for share-point growth,
acceleration, and recent new entries, subtracts a product/publisher
concentration penalty, and applies history, product-size, `units_absolute`,
`revenue_absolute`, and publisher coverage confidence. Its weights are named
project MVP defaults and are not Sensor Tower formulas. Source fields retain
their exact names and unresolved semantics; they are not labeled as downloads
or revenue.

Schema version 3 adds `theme_trend_scores`. DuckDB remains the source of truth;
recalculation atomically replaces only requested target-month score rows. By
default the deterministic export is:

```text
<export_directory>/theme_trend_scores.parquet
```

`--skip-export` stores DuckDB rows without creating this file. `--top N`
changes only the latest-month console display; all calculated rows remain
stored. The console shows component scores and explanatory fields without
product IDs, credentials, or authenticated URLs. See
[`docs/TREND_SCORE.md`](docs/TREND_SCORE.md) for the formulas, eligibility,
percentile method, confidence calculation, and interpretation limits.

Exit codes are `0` for success or plan validation, `2` for CLI/month/local
configuration errors, `3` for Sensor Tower or workflow-data failures, and `4`
for DuckDB or Parquet failures.

## FEISHU-001 read-only field inspection

FEISHU-001 adds a manual, strictly read-only Feishu inspection command:

```powershell
python -m src inspect-feishu --plan-only
python -m src inspect-feishu
```

The command obtains a tenant access token from the configured DataVine custom
app, then reads field metadata from one configured Bitable table. It supports
an optional `view_id` and follows the verified fields endpoint pagination with
`page_size=100`. It never writes fields or records, creates tables or views,
synchronizes trend rows, opens DuckDB, or creates local output files.

Credentials are supplied through the local `.env` file or GitHub Secrets. The
App ID, App Secret, Bitable `app_token`, `table_id`, and optional `view_id` are
configuration values only; no real identifiers belong in source code,
`configs/app.example.yaml`, `.env.example`, tests, or documentation examples.
For a Bitable URL such as
`https://feishu.cn/base/<APP_TOKEN>?table=<TABLE_ID>`, use the value after
`base/` as `APP_FEISHU_BITABLE_APP_TOKEN`, the `table` value as
`APP_FEISHU_BITABLE_TABLE_ID`, and supply a view identifier beginning with
`vew` copied from the selected view in that `/base/` URL only when the
inspection should be scoped to a view. The App Secret must never be committed.

The attached `daily-newgames-fetcher-main.zip` was inspected as the verified
reference for Feishu authentication and Bitable endpoint structure. Its
authentication path, Bearer-token use, and pagination shape were reused as
contract evidence; its bare exception handling, missing timeouts/status
checks, raw credential exposure, and unchecked responses were deliberately
not copied. FEISHU-002 provisions the trend-score field schema; FEISHU-003A
only verifies the read-only record-list contract. FEISHU-003B adds the
separate synchronization reader and explicit batch record writes described
below.

## FEISHU-002 trend-score field schema provisioning

FEISHU-002 provisions the configured Feishu Bitable schema without making
Feishu the source of truth. The live destination begins with one preserved
primary Text field named `文本`, identified from `is_primary = true`; its
field ID is never hard-coded. The command creates exactly 21 non-primary
fields in a deterministic order and retains unrelated fields.

```powershell
python -m src provision-feishu-schema --plan-only
python -m src provision-feishu-schema
python -m src provision-feishu-schema --apply
```

`--plan-only` is handled before configuration loading and logging, so it does
not read YAML, `.env`, credentials, network, DuckDB, or local files. The
default invocation is a live dry-run. Only `--apply` may create missing
fields. Apply checks exact-name collisions and compatible verified Feishu
types/properties before creating fields sequentially, then rereads and
verifies the complete schema. It waits 0.5 seconds only between successful
field creates to reduce same-table Bitable write-conflict risk; it does not
sleep after the final create and does not use concurrency. Reruns are
idempotent; no field is updated or deleted, and no Bitable record is created,
updated, or deleted.

The schema preserves the source terms `units_absolute` and
`revenue_absolute`. Percentage values are later written as decimal ratios,
such as `0.018`, and displayed with two decimal places. The complete logical
schema and the verified formatter choices are documented in
[`docs/FEISHU_SCHEMA.md`](docs/FEISHU_SCHEMA.md). Trend-record synchronization
is implemented separately by FEISHU-003B; dashboard view configuration remains
manual.

The command uses exit code `0` for a successful inspection or plan, `2` for
invalid configuration, `3` for Feishu authentication/API failures, and `4`
for unexpected local failures. `--plan-only` needs no App Secret and performs
no configuration-file, network, database, or file-write operation. An invalid
local schema still returns configuration error code `2`.

## FEISHU-003A read-only record inspection

FEISHU-003A adds a manual, strictly read-only check of the configured Bitable
records:

```powershell
python -m src inspect-feishu-records --plan-only
python -m src inspect-feishu-records
```

The default command authenticates, rereads the complete FEISHU-002 schema, and
stops before the records endpoint unless there is exactly one primary field,
21 compatible non-primary fields, zero missing fields, and zero incompatible
fields. It then uses the table-level records GET endpoint with `page_size=100`
and follows response page tokens until every page has been checked.

Record inspection deliberately does not send `view_id`, `filter`, `sort`, or
`search`: an idempotent future synchronization must see records hidden by a
view filter so it cannot mistake them for missing records. The command keeps
only record-integrity metadata in memory and prints counts, field-name counts,
the primary-field presence count, an app-token suffix, and the table ID. It
never prints record IDs, cell values, raw responses, credentials, or
authenticated URLs, and it never creates, updates, or deletes records.

`--plan-only` is routed before configuration loading and logging. It does not
read YAML, `.env`, credentials, DuckDB, or local files, and does not construct
an HTTP client. FEISHU-003A does not read DuckDB, generate a primary-field
technical key, map `ThemeTrendScore` values, convert `NULL`/`0`, or implement
record payload writes; those choices belong to FEISHU-003B; no
`batch_create` or `batch_update` method is part of this task. If a real table is empty, the only record-level claim this
workflow can make is that the empty-table response envelope, authentication,
and permission path were accepted; it does not claim any non-empty cell-value
shape was observed.

## FEISHU-003B idempotent trend synchronization

FEISHU-003B synchronizes every stored monthly `ThemeTrendScore` row for the
configured `sensor_tower_scope_name` from DuckDB to the provisioned Feishu
table. DuckDB remains the source of truth; the complete stored score set is
authoritative, so adding a new month also updates earlier latest-month flags.

```powershell
python -m src sync-feishu-trends --plan-only
python -m src sync-feishu-trends
python -m src sync-feishu-trends --apply
```

The plan-only command is credential-free and runs before configuration,
logging, YAML, `.env`, DuckDB, HTTP client construction, network access, and
file writes. The default command is an authenticated dry-run. Only explicit
`--apply` can write records. Apply uses only table-level `batch_update` and
`batch_create`, updates before creates, waits 0.5 seconds only between
successful requests, and rereads the complete table for final verification.
The internal default batch size is 100 and the permitted internal range is
1-1000.

The preserved primary Text field `鏂囨湰` is a versioned SHA-256 key:

```text
ctta:v1:{period_start YYYY-MM}:{sha256(UTF-8, scope + \x1f + cadence + \x1f + period_start + \x1f + period_end + \x1f + game_theme)}
```

All 21 provisioned non-primary fields map directly to the internal
`ThemeTrendScore` model. `None` becomes an empty cell, while numeric zero and
boolean false remain real values. The five existing blank records are counted
as unmanaged, preserved, never matched, and never reused. Unmanaged nonblank
records are also untouched. Duplicate managed keys and stale managed records
are surfaced without printing keys or record IDs; duplicates fail before any
write and stale records block apply.

No record delete, view-write, `/records/search`, Sensor Tower request, or real
Feishu request is part of development or automated tests. See
[`docs/FEISHU_SYNC.md`](docs/FEISHU_SYNC.md) for the field table, exact key
algorithm, reconciliation contract, no-delete policy, manual ranked-view
steps, evidence status, and real acceptance sequence.
