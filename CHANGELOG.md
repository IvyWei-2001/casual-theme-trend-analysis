# Changelog

## Unreleased

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
  dashboard configuration remain deferred to FEISHU-003.
- Added FEISHU-001 read-only Feishu Bitable field inspection with sanitized
  tenant-token authentication, optional view scoping, paginated field metadata,
  mock-only coverage, credential-safe output, and an explicit no-write
  guarantee. The attached `daily-newgames-fetcher-main.zip` is documented as
  the verified endpoint reference; its unsafe error-handling patterns were not
  copied. Trend-row synchronization remains deferred to FEISHU-003.
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
