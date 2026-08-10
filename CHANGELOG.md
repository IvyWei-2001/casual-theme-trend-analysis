# Changelog

## Unreleased

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
