# Changelog

## Unreleased

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
