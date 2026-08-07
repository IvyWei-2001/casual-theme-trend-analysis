# Implementation Plan

This plan keeps the MVP small and follows the audited two-stage Sensor Tower contract. It is an implementation sequence, not an authorization to implement code in this documentation task.

Every implementation issue remains narrow and should produce one pull request with tests, documentation, type hints, logging, and known limitations. No separate market-intelligence modules are introduced by this plan.

## MVP scope guard

The MVP contains only:

- Sensor Tower ingestion;
- DuckDB persistence;
- historical monthly loading;
- monthly theme aggregation;
- Trend Score; and
- Feishu synchronization.

Weekly market data is the first Sensor Tower ingestion mode. Historical monthly loading is the second ingestion mode. They share the same internal `Snapshot` model and differ by `cadence`.

The MVP does not include AI prediction, machine learning, LLM theme classification, real-time dashboards, multi-region comparison, scheduled automation, or separate Publisher, Genre, Creative, LiveOps, or AI Summary modules.

## A. Bootstrap

### Purpose

Close the system-audit gap and establish the internal contracts needed by the rest of the MVP.

### Work items

- Keep the audited Google Sheets / Apps Script behavior documented: Config-sheet URL and token inputs, custom field filter, local 1000-row limit, source app ID extraction, and separate metadata enrichment.
- Inspect the Feishu implementation in `daily-newgames-fetcher` and document the reusable authentication, destination, field-mapping, and sync contract.
- Keep the Sensor Tower endpoint URL, request method, and unresolved field semantics as explicit TODOs until evidence is available.
- Confirm the internal `App`, `Theme`, `Snapshot`, and `ThemeMetric` contracts, including source and unified product identity.
- Establish configuration, logging, mock, and test conventions without implementing business logic in this phase.

### Exit criteria

Phase 0 is complete only when the old Apps Script contract and the reusable Feishu implementation are both inspected and documented. The current repository meets the first condition from verified evidence but not the second.

## B. Sensor Tower adapter using verified sample

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

## C. DuckDB persistence

### Purpose

Persist normalized internal records without making DuckDB or Feishu fields part of business logic.

### Work items

- Persist `App`, `Theme`, and `Snapshot` through a repository abstraction.
- Preserve `source_app_id`, optional `unified_app_id`, source date, cadence, ranking metric, and explicit unavailable-data state.
- Make the market/ranking-to-metadata merge idempotent by internal/source identity rules.
- Keep DuckDB as the analytical store and retain the project-approved Parquet boundary where file-oriented storage is required.
- Add unit tests for identity resolution and persistence plus an integration test against a temporary local DuckDB database.

### Exit criteria

The same normalized input can be persisted repeatedly without creating duplicate observations, and stored records can be read using internal model concepts only.

## D. Historical monthly loading

### Purpose

Load historical monthly market observations after the verified adapter and persistence paths are stable.

### Work items

- Use the verified historical request contract when it becomes available; do not assume the weekly endpoint or parameters apply.
- Store monthly observations with `cadence: monthly` and retain the verified source date when its semantics are known.
- Add checkpoint, resume, retry, and validation behavior.
- Start with a small verified period, then expand toward the roadmap's 36-month target only after data-quality checks pass.
- Keep missing observations explicit and never convert unavailable units or revenue to zero.

### Exit criteria

A historical monthly slice can be loaded idempotently into DuckDB, resumed after interruption, and validated by period, scope, source identity, and row counts.

## E. Theme monthly aggregation

### Purpose

Aggregate product snapshots into explicit monthly `ThemeMetric` records.

### Work items

- Map the verified `Game Theme` custom-tag label into internal `Theme` records after its value structure is confirmed.
- Do not use the weekly `Game Genre` filter as a theme classifier.
- Produce `product_count` and `new_product_count` under documented identity and comparison rules.
- Produce `publisher_count` only when publisher identity is available and normalized.
- Produce `concentration`, `growth_rate`, and `acceleration_rate` from compatible monthly records.
- Populate `downloads`, `download_share`, `revenue`, and `revenue_share` only after the corresponding source semantics and denominators are verified.
- Preserve confidence and unavailable-data status with every aggregate.

### Exit criteria

The same internal snapshots produce deterministic monthly theme metrics, scope and cadence are not mixed, and every metric can be traced back to contributing products.

## F. Trend Score

### Purpose

Rank themes with a transparent and reproducible calculation over internal `ThemeMetric` records.

### Work items

- Define a versioned score specification using validated growth, acceleration, concentration, product breadth, and available scale metrics.
- Keep score weights, normalization, range, and thresholds configurable and documented.
- Lower confidence when required metrics are missing or observations are not comparable; do not fabricate a score from unavailable data.
- Add unit tests for normal, missing-data, tied-rank, and boundary cases.

The exact formula, weights, and use of downloads or revenue remain TODO until their source semantics are verified and the score specification is approved. No predictive model or LLM is required.

### Exit criteria

Identical internal inputs always produce the same score, and each score can be explained from its contributing theme metrics and confidence state.

## G. Feishu sync

### Purpose

Publish validated monthly theme metrics to Feishu while keeping DuckDB as the source of truth.

### Work items

- Base the adapter on the inspected `daily-newgames-fetcher` Feishu implementation.
- Define the smallest output containing theme identity, period, cadence, explicit metrics, Trend Score, confidence, and data-quality status.
- Map internal `ThemeMetric` values to Feishu fields without making Feishu field names part of analytics logic.
- Add idempotent synchronization and a mock Feishu boundary for tests.
- Publish a ranked monthly theme view; real-time dashboards and workflows remain out of scope.

### Exit criteria

A validated local result can be synchronized repeatedly without duplicate output, and Feishu distinguishes unavailable data from zero.

## MVP verification sequence

The MVP is accepted in this order:

1. Bootstrap the audited contracts and inspect the reusable Feishu implementation.
2. Normalize one verified Sensor Tower sample through the market/ranking and metadata paths.
3. Persist the normalized records in DuckDB.
4. Load and validate a small historical monthly slice.
5. Produce deterministic monthly `ThemeMetric` aggregates.
6. Calculate and explain Trend Scores.
7. Sync the results through the Feishu adapter.

Each external boundary needs a deterministic mock, unit tests, and an integration test. Real credentials must be provided through configuration and never committed.
