# Changelog

## Unreleased

- Added ST-003 Sensor Tower unified app metadata enrichment after final local
  market selection, with verified batching, normalization, retry, pacing, and
  sanitized error handling. Persistent metadata caching remains deferred to
  DuckDB.
- Added the verified Sensor Tower market request boundary and local candidate
  selection pipeline for ST-002.
- Enforced the fixed MVP custom-field semantics and request/client endpoint
  consistency before network access.
