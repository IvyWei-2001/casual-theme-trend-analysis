# Changelog

## Unreleased

- Added DECISION-001 Phase B local persistence and execution boundaries:
  schema version 9 adds five typed DuckDB output tables with deterministic
  readers and atomic exact-target-month replacement; the stored-evidence
  `decide-themes` CLI calls the frozen Phase A calculation once and writes
  five complete deterministic ZSTD Parquet exports after commit. Plan-only
  performs no configuration, database, network, or file access, and
  `--skip-export` verifies DuckDB while writing no decision Parquet. Category
  fit, migration, non-forecast T+1/T+2/T+3, and observable Revenue (USD)
  limitations remain explicit. Validation uses synthetic models, fake
  repositories, temporary DuckDB, and temporary Parquet only; FEISHU-004,
  AUTOMATION-001, and real-environment DECISION-001 acceptance remain later
  work.
- Replaced MONETIZATION-001 Custom-Field collection with the schema-v8 offline
  observable-Revenue proxy. Stored `revenue_absolute` maps NULL to `unknown`,
  zero to `iaa_candidate`, and positive values to
  `iap_or_hybrid_candidate`; these are candidates rather than observed
  monetization types. The inclusive `derive-monetization` range workflow
  covers the requested stored months, atomically replaces only monetization
  rows, preserves NULL-versus-zero semantics, rejects negative/non-finite
  values, and writes deterministic ZSTD Parquet exports only after success.
  No Custom Fields are used, no IAA revenue is estimated, Product Model is
  context only, and development uses temporary storage and synthetic data.
- Corrected BACKTEST-001 acceptance boundaries: expected decision identities now
  fail on missing middle-month structure, growth, legacy-score, or model-summary
  evidence; seasonality indices use decision-month absolute Downloads and Revenue
  (USD) profiles; raw replacement clears the complete range by decision-month
  start identity, including the month-start end boundary, and verifies all
  three tables before commit; segment Top-Quintile metrics expose valid-cohort
  denominators; aggregate post-commit readback now uses exact run identities;
  and statistical, migration, stale-row, idempotency, rollback, and monthly
  expansion regressions were added. MODEL-002 status is recorded as completed and
  real-environment accepted using sanitized evidence; BACKTEST-001 remains
  synthetic/temporary-DuckDB verified with real acceptance pending.
- Added BACKTEST-001 leakage-safe T+1/T+2/T+3 launch-window validation. The
  schema-v6 implementation adds exactly three tables for raw outcomes,
  continuous-feature metrics, and categorical-segment metrics; uses a fixed
  19-feature/4-outcome registry; preserves NULL versus zero semantics; and
  atomically replaces/readbacks deterministic ZSTD Parquet exports. Plan-only
  execution is credential-free and development validation uses only synthetic
  rows, mock repositories, temporary DuckDB, and temporary Parquet. No final
  score, forecast, recommendation, Feishu operation, automation, or real-data
  acceptance is included.
- Added MODEL-002 multi-horizon trend, lifecycle, stability, and seasonality
  evidence. Schema version 5 adds `theme_horizon_metrics`,
  `theme_model_summaries`, and `theme_seasonality_profiles` without changing
  prior tables or the legacy 6M Momentum formula. The local `model-themes`
  workflow is prefix-safe, preserves raw labels and NULL/zero semantics,
  validates atomic replacement/readback, and exports deterministic ZSTD
  Parquet. Development coverage uses only synthetic rows, mock repositories,
  temporary DuckDB, and temporary Parquet outputs; recommendations,
  forecasts, backtesting, Feishu, and real-data acceptance remain out of scope.
- Added AGG-002 V2 opportunity evidence aggregation. Schema version 4 adds
  market-structure, growth-source, observed-dimension, and representative-game
  tables while preserving AGG-001 and TREND-001. The implementation keeps
  Downloads and Revenue (USD) source semantics, NULL/zero behavior, actual
  sample denominators, current-cache metadata limitations, atomic six-table
  replacement, readback verification, and deterministic ZSTD Parquet exports.
  It does not calculate scores or recommendations and automated coverage uses
  only synthetic source rows and temporary storage.
- Added HIST-002 read-only 36-month history inspection, structural quality
  evidence, and documented safe resumable backfill acceptance.
- Added CONTRACT-002 as a documentation and contract milestone. It confirms
  Downloads and Revenue (USD), defines the six V2 decision questions, separates
  theme opportunity from Product Greenlight, establishes the 36-month V2
  roadmap, and reclassifies the current score as 6M Momentum. This milestone
  does not change production code, data, Feishu, or external services.
- Added the FEISHU-003B live compatibility hotfix for Feishu Number fields:
  writes continue to send JSON numbers, while list-record responses may return
  finite numeric strings. The synchronization reader now strips whitespace and
  uses strict `decimal.Decimal` parsing, returning integral strings as `int`
  and non-integral strings as `float` while rejecting empty, malformed,
  display-formatted, and non-finite values. Date/DateTime epoch integers,
  Checkbox booleans, NULL, and numeric zero semantics remain unchanged. The
  real acceptance state already contained all 411 managed records and preserved
  five unmanaged blank records; MockTransport now mirrors the numeric-string
  read shape and final reread verification converges without writes.
- Added FEISHU-003B idempotent DuckDB-to-Feishu monthly trend
  synchronization. The complete configured-scope `ThemeTrendScore` set is
  authoritative; the preserved primary Text field is a versioned SHA-256
  managed key, all 21 provisioned fields use exact internal mappings, and
  NULL/zero/false values retain their semantics. The default command is a
  live dry-run and only explicit `--apply` uses sequential `batch_update` and
  `batch_create` requests with a 100-record default batch size, 0.5-second
  pacing between successful writes, complete post-write reread verification,
  stale/duplicate protection, and no-delete handling. The five existing blank
  records and unmanaged nonblank records remain untouched. Automated coverage
  uses only synthetic DuckDB data and `httpx.MockTransport`; no real Feishu or
  Sensor Tower request was made.
- Added FEISHU-003A read-only Feishu Bitable record inspection with complete
  FEISHU-002 schema preflight, table-level paginated records GET, no-view
  filtering, record/page integrity validation, credential-safe count summaries,
  and MockTransport coverage. The command has a credential-free plan-only
  path and never reads DuckDB or creates, updates, or deletes records. Record
  payload mapping, NULL/zero conversion, technical-key decisions, and real
  synchronization remain deferred to FEISHU-003B.
- Added FEISHU-002 idempotent Feishu trend-score field-schema provisioning:
  21 deterministic non-primary fields, preserved primary-field handling,
  verified type/property compatibility checks, credential-free plan-only mode,
  live dry-run mode, explicit `--apply`, sequential request pacing, final
  schema reread/verification, sanitized results and failures, mock-only tests,
  and an explicit no-record-write guarantee. The official date formatter
  contract does not support year-month-only display, so the month field uses
  the supported `yyyy/MM/dd` formatter and stores the first calendar day later.
  Plan-only is routed before configuration loading/logging, and therefore
  remains credential-free with no YAML, `.env`, network, database, or file
  access. Field creation uses a 0.5-second delay only between successful
  creates to reduce same-table Bitable write-conflict risk; it does not sleep
  after the final create or use concurrency. Trend-record synchronization and
  dashboard configuration and real record synchronization remain deferred to
  FEISHU-003B.
- Added FEISHU-001 read-only Feishu Bitable field inspection with sanitized
  tenant-token authentication, optional view scoping, paginated field metadata,
  mock-only coverage, credential-safe output, and an explicit no-write
  guarantee. The attached `daily-newgames-fetcher-main.zip` is documented as
  the verified endpoint reference; its unsafe error-handling patterns were not
  copied. Trend-row synchronization remains deferred to FEISHU-003B.
- Added TREND-001 explainable monthly Game Theme trend scoring. Schema version
  3 adds `theme_trend_scores`; the score uses a six-month rolling grid,
  absent-theme zero filling, share-point gains and acceleration,
  actionable-only average-rank percentiles, explicit MVP component and
  confidence weights, deterministic latest-month ranking, atomic DuckDB
  replacement, and a stable ZSTD Parquet export. The workflow never calls
  Sensor Tower and deliberately defers taxonomy merging, cycle detection,
  forecasting, weekly scoring, Feishu, scheduling, and AI summaries.
- Added AGG-001 deterministic monthly Game Theme aggregation over stored
  DuckDB snapshots and normalized metadata. Schema version 2 now migrates
  sequentially and adds `monthly_market_totals` plus `theme_monthly_metrics`,
  with actual monthly population denominators, raw theme labels, explicit NULL
  source coverage, previous-month membership, current-cache publisher metrics,
  atomic derived replacement, and deterministic Parquet exports. The command
  never calls Sensor Tower. Trend Score, weekly aggregation, lifecycle labels,
  opportunity ranking, Feishu, scheduling, and AI summaries remain deferred.
- Added HIST-001 resumable monthly historical backfill with inclusive UTC
  range validation, plan-only mode, existing-period skipping, refresh and
  fail-fast resume behavior, shared metadata-cache reuse, one final Parquet
  export, and sanitized CLI errors. Scheduling, weekly backfill, Feishu,
  theme aggregation, lifecycle classification, and Trend Score remain
  deferred.
- Added ST-005 storage validation that distinguishes normalized metadata from
  raw Sensor Tower source observations: generated `"Unknown"` and `"N/A"`
  fallbacks remain rejected for normalized metadata, while raw source tags
  preserve those literals and missing values remain SQL `NULL`. No schema
  migration was required.
- Added ST-004 compatibility for the sanitized live Sensor Tower market
  response: opaque string IDs now flow through market parsing, metadata
  enrichment, DuckDB, Parquet, and DB-002; verified optional source metrics
  remain nullable; both the earlier sample and live `entities`/
  `aggregate_tags` custom-tag variants are supported. No metric business
  semantics were inferred, and no schema migration or live test was added.
- Added DB-002 live single-month collection: completed UTC calendar-month
  validation, plan-only CLI mode, cache-aware metadata refresh, atomic monthly
  DuckDB replacement, optional Parquet export, sanitized summaries, and
  mock-only workflow coverage. Historical backfill, scheduling, Feishu, theme
  aggregation, and Trend Score remain deferred.
- Added DB-001 DuckDB snapshot and metadata storage: schema versioning,
  normalized metadata persistence, atomic complete-period replacement, a
  14-day metadata-cache lookup, and deterministic atomic ZSTD Parquet exports.
  Live collection, historical backfill, theme aggregation, Trend Score, and
  Feishu synchronization remain deferred.
- Added ST-003 Sensor Tower unified app metadata enrichment after final local
  market selection, with verified batching, normalization, retry, pacing, and
  sanitized error handling; DB-001 now persists its normalized metadata cache
  locally.
- Added the verified Sensor Tower market request boundary and local candidate
  selection pipeline for ST-002.
- Enforced the fixed MVP custom-field semantics and request/client endpoint
  consistency before network access.
