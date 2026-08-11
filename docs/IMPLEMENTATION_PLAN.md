# Implementation Plan

This plan keeps the first delivery small and prioritizes monthly historical analysis. It follows the audited two-stage Sensor Tower contract. It is an implementation sequence, not an authorization to implement code in this documentation task.

Every implementation issue remains narrow and should produce one pull request with tests, documentation, type hints, logging, and known limitations. No separate market-intelligence modules are introduced by this plan.

## MVP scope guard

The first delivery contains only:

- Sensor Tower ingestion;
- DuckDB persistence;
- historical monthly loading;
- monthly theme aggregation;
- Trend Score; and
- Feishu synchronization.

The first dashboard delivery is monthly-first. Weekly tracking may be added as a later incremental capability, but it must not block the first monthly dashboard.

The MVP does not include AI prediction, machine learning, LLM theme classification, real-time dashboards, multi-region comparison, scheduled automation, or separate Publisher, Genre, Creative, LiveOps, or AI Summary modules.

## 1. Bootstrap repository

### Purpose

Close the system-audit gap and establish the internal contracts needed by the rest of the MVP.

### Work items

- Keep the audited Google Sheets / Apps Script behavior documented: Config-sheet URL and token inputs, custom field filter, local 1000-row limit, source app ID extraction, and separate metadata enrichment.
- Use `FEISHU-001` in step 7 to inspect the attached Feishu reference before any synchronization work begins.
- Keep the Sensor Tower endpoint URL, request method, and unresolved field semantics as explicit TODOs until evidence is available.
- Confirm the internal `App`, `Theme`, `Snapshot`, and `ThemeMetric` contracts, including source and unified product identity.
- Establish configuration, logging, mock, and test conventions without implementing business logic in this phase.

### Exit criteria

Phase 0 is complete enough to begin `INF-001` once the old Sensor Tower / Apps Script contract and internal data model are documented. Feishu inspection is not a prerequisite for Bootstrap, Sensor Tower, DuckDB, historical loading, or theme aggregation; `FEISHU-001` is performed in step 7.

## 2. Sensor Tower adapter

### Purpose

Create the narrow external boundary required to normalize one verified response sample.

### Work items

- Keep the market/ranking request and metadata enrichment request as separate adapter responsibilities.
- Read the configured URL and auth token through the established configuration boundary; do not hard-code secrets.
- Reproduce the verified custom field filter exactly: `Game Genre`, values `Puzzle` and `Tabletop`, `global: true`, `exclude: false`.
- Preserve the verified query parameter name `custom_fields_filter_id` and its encoded JSON value without inventing an endpoint URL.
- Apply the existing workflow's local 1000-row limit after the market fetch, then use source `app_id` values to request metadata.
- Map only verified response field existence into internal models. Keep the semantics of unit and revenue fields unresolved until evidence verifies them.
- Add mock responses and contract tests for market rows, metadata enrichment, source IDs, custom tags, and unavailable fields.

### Exit criteria

One real approved sample and one deterministic mock sample can be normalized into internal `App`, `Theme`, and `Snapshot` records. Sensor Tower field names do not enter aggregation code.

## 3. DuckDB persistence

### Purpose

Persist normalized internal records without making DuckDB or Feishu fields part of business logic.

### DB-001 implemented boundary

The first persistence issue implements a versioned DuckDB storage package with
`app_metadata` and `market_snapshots` tables. `app_metadata` is the normalized
14-day metadata cache; missing metadata is not materialized as a placeholder.
`market_snapshots` uses the composite period identity
`(scope_name, cadence, period_start, period_end)` and preserves the verified
source metric and tag names without assigning unresolved download or revenue
semantics.

Period writes are complete-period replacements. The repository validates IDs,
rank contiguity, period identity, and request provenance before deleting the
old period, inserts all rows in one transaction, and commits only after the
complete replacement succeeds. Parquet is an explicit deterministic
export/archive boundary with stable columns and ordering; DuckDB remains the
local source of truth.

DB-001 has no live collection command and does not implement historical
backfill, theme aggregation, Trend Score, Feishu synchronization, credentials,
or authenticated URL storage. DB-002 adds the first live single-period
collection boundary.

### DB-002 implemented boundary

DB-002 provides the first manually executable live workflow:

1. Validate one completed natural `YYYY-MM` month using UTC boundaries.
2. Build the verified market request with `date` and `end_date`.
3. Fetch and parse up to the configured candidate limit, then apply the
   existing local eligibility selection in source order.
4. Initialize DuckDB, classify selected unified IDs through the 14-day cache,
   fetch only stale or missing IDs, and merge fresh plus newly returned
   metadata without using stale refresh results as fallback.
5. Map the final ordered records to internal storage rows, upsert only newly
   returned metadata, and atomically replace the complete monthly period.
6. Export both business tables through the existing repository Parquet
   boundary unless export is explicitly skipped.

`python -m src collect-month --month YYYY-MM --plan-only` validates the month
and request configuration without requiring a token or opening a database.
The live command is intentionally single-month and manually invoked. It does
not implement pagination, scheduling, Feishu, theme aggregation, Trend Score,
or raw response persistence. DuckDB remains the source of truth when a
Parquet export fails.

### HIST-001 implemented boundary

HIST-001 adds a manually executable, resumable inclusive monthly backfill:

1. Validate exact `YYYY-MM` start and end boundaries against one injected UTC
   clock, rejecting malformed, impossible, current, future, and reversed ranges.
2. In plan-only mode, print the chronological month sequence without creating
   a client, opening DuckDB, or creating output files.
3. Open and initialize one DuckDB repository, skip non-empty complete periods
   by default, and recollect them only with `--refresh-existing`.
4. Lazily create one Sensor Tower client only when a month needs collection;
   delegate each month to DB-002 with Parquet export disabled.
5. Stop on the first failure, preserve earlier committed periods, and resume
   later through atomic period replacement rather than a checkpoint file.
6. Export `market_snapshots.parquet` and `app_metadata.parquet` exactly once
   after all requested months succeed unless `--skip-export` is supplied.

The workflow is sequential and manual. It does not add scheduling, weekly
backfill, new Sensor Tower endpoints or filters, raw-response persistence,
Feishu synchronization, theme aggregation, lifecycle classification, or Trend
Score. DuckDB remains the source of truth.

### Work items

- Persist normalized app metadata and market snapshot rows through a repository abstraction.
- Preserve `source_app_id`, optional `unified_app_id`, source date, cadence, ranking metric, and explicit unavailable-data state.
- Make the market/ranking-to-metadata merge idempotent by internal/source identity rules.
- Keep DuckDB as the analytical store and retain the project-approved Parquet boundary where file-oriented storage is required.
- Add unit tests for identity resolution and persistence plus an integration test against a temporary local DuckDB database.

### Exit criteria

The same normalized input can be persisted repeatedly without creating duplicate observations, and stored records can be read using internal model concepts only.

## 4. Historical monthly loading

### Purpose

Load the historical monthly observations needed for the first dashboard after the verified adapter and persistence paths are stable.

### Work items

- Use the verified historical request contract when it becomes available; do not assume the weekly endpoint or parameters apply.
- Store monthly observations with `cadence: monthly` and retain the verified source date when its semantics are known.
- Add resumable period validation and failure behavior through atomic monthly
  replacement; no separate checkpoint file is required for HIST-001.
- Start with a small verified period, then expand toward the roadmap's 36-month target only after data-quality checks pass.
- Keep missing observations explicit and never convert unavailable units or revenue to zero.

### Exit criteria

A historical monthly slice can be loaded idempotently into DuckDB, resumed after interruption, and validated by period, scope, source identity, and row counts.

## 5. Theme monthly aggregation

### Purpose

Aggregate product snapshots into explicit monthly `ThemeMetric` records.

### AGG-001 implemented boundary

AGG-001 adds deterministic monthly Game Theme aggregation over the stored
`market_snapshots` and current normalized `app_metadata` tables:

1. Upgrade the supported DuckDB schema sequentially from version 1 to version
   2, preserving all existing source rows and adding only
   `monthly_market_totals` and `theme_monthly_metrics`.
2. Validate an inclusive completed UTC month range without opening DuckDB in
   `--plan-only` mode.
3. Require every requested source month to be present and non-empty, using the
   actual stored row count and raw source Game Theme strings.
4. Calculate month-wide population and coverage totals, then per-theme counts,
   shares, rank statistics, source-metric coverage/sums/shares, membership
   entry fields, and publisher coverage/concentration.
5. Use the immediately preceding natural calendar month as the membership
   baseline when that stored period exists, including a baseline outside the
   requested range. A missing or empty baseline leaves entry fields NULL.
6. Replace both derived tables in one transaction and export deterministic
   Parquet files only after the DuckDB commit.

AGG-001 preserves `units_absolute` and `revenue_absolute` as source metric
names, keeps missing values NULL, and does not implement Trend Score, weekly
aggregation, lifecycle labels, opportunity ranking, Feishu, scheduling, or AI
summaries. Publisher metrics use the current, non-versioned metadata cache and
therefore do not claim historical publisher identity.

### Work items

- Map the verified `Game Theme` custom-tag label into internal `Theme` records after its value structure is confirmed.
- Do not use the weekly `Game Genre` filter as a theme classifier.
- Produce `product_count` and `new_product_count` under documented identity and comparison rules.
- Produce `publisher_count` only when publisher identity is available and normalized.
- Produce `concentration`, `growth_rate`, and `acceleration_rate` from compatible monthly records.
- Populate `downloads`, `download_share`, `revenue`, and `revenue_share` only after the corresponding source semantics and denominators are verified.
- Preserve confidence and unavailable-data status with every aggregate.

### Exit criteria

The same internal snapshots produce deterministic monthly theme metrics, scope and periods are not mixed, and every metric can be traced back to contributing products.

## 6. Trend Score

### Purpose

Rank themes with a transparent and reproducible calculation over internal `ThemeMetric` records.

### Work items

- Define a versioned score specification using validated growth, acceleration, concentration, product breadth, and available scale metrics.
- Keep score weights, normalization, range, and thresholds configurable and documented.
- Lower confidence when required metrics are missing or observations are not comparable; do not fabricate a score from unavailable data.
- Add unit tests for normal, missing-data, tied-rank, and boundary cases.

### TREND-001 implemented boundary

TREND-001 implements the first deterministic monthly score over stored
schema-v2 aggregates:

1. Require at least six consecutive natural calendar months and build a
   target-month rolling grid with recent-three and prior-three windows.
2. Zero-fill only absent raw theme months inside the grid; a missing
   `monthly_market_totals` month fails scoring.
3. Calculate share-point gains, three-point slopes, acceleration, new-entry
   momentum, rank improvement, publisher breadth, and explanatory over-index
   values from internal models only.
4. Calculate actionable-only cross-theme average-rank percentiles, apply the
   documented MVP component, concentration, confidence, and final-score
   formulas, and assign deterministic target-month ranks.
5. Migrate DuckDB schema version 2 to version 3 with a separate
   `theme_trend_scores` table, atomically replace requested score rows, and
   export deterministic `theme_trend_scores.parquet`.
6. Provide `python -m src score-themes` with plan-only, skip-export, and latest
   Top-N display modes. The command never constructs a Sensor Tower client.

The score weights are project MVP defaults rather than Sensor Tower formulas.
Taxonomy merging, weekly scoring, cycle detection, forecasting, machine
learning, Feishu synchronization, scheduling, and AI summaries remain outside
this issue. No predictive model or LLM is required.

### Exit criteria

Identical internal inputs always produce the same score, and each score can be explained from its contributing theme metrics and confidence state. TREND-001 satisfies this exit criterion for the six-month monthly MVP.

## 7. Feishu integration foundation and sync

### Purpose

Inspect the configured Feishu destination safely before publishing validated
monthly theme metrics, while keeping DuckDB as the source of truth.

### Work items

- `FEISHU-001`: Inspect the attached `daily-newgames-fetcher-main.zip` as the
  verified reference, then implement tenant-token authentication and a
  read-only Bitable field-list command with optional view scoping and
  pagination.
- Keep the verified authentication path and Bitable endpoint structure from
  the reference, but do not copy its unsafe exception handling, missing
  timeout/status checks, or credential logging behavior.
- `FEISHU-001` must not create or update fields, records, tables, views, or
  dashboards. It must not synchronize Trend Score rows.
- `FEISHU-002`: Provision the verified, deterministic 21-field Trend Score
  schema after preserving the existing primary Text field as the future
  technical key. Create missing fields only after explicit `--apply`; do not
  update or delete fields and do not write records.
- Keep the Feishu field schema in its own typed integration boundary. The
  schema preserves `units_absolute` and `revenue_absolute` and stores future
  percentage values as decimal ratios.
- `FEISHU-003`: Map internal Trend Score outputs to the provisioned fields,
  add idempotent record synchronization, and publish the ranked monthly view.
  Real-time dashboards and workflows remain out of scope.

### Exit criteria

FEISHU-001 can authenticate through a mock boundary, inspect every configured
field in response order, report duplicate names, and prove that no Bitable
write method is called. FEISHU-002 can provision the complete schema through a
mock boundary, rerun without duplicate field creation, and distinguish
unavailable configuration from a live destination. Record synchronization
remains deferred to FEISHU-003.

## MVP verification sequence

The first monthly dashboard is accepted in this order:

1. Bootstrap the repository once the Sensor Tower / Apps Script contract and internal data model are documented.
2. Normalize one verified Sensor Tower sample through the market/ranking and metadata paths.
3. Persist the normalized records in DuckDB through DB-001.
4. Load and validate a small historical monthly slice.
5. Produce deterministic monthly `ThemeMetric` aggregates.
6. Calculate and explain Trend Scores.
7. Complete `FEISHU-001` read-only field inspection and FEISHU-002 schema
   provisioning, then defer trend-row synchronization to `FEISHU-003`.

Each external boundary needs a deterministic mock, unit tests, and an integration test. Real credentials must be provided through configuration and never committed.
