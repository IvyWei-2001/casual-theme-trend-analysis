# Current System

This document records the audited state of the repository as of HIST-002.
It distinguishes implemented and accepted technical behavior from the
future V2 decision product. The descriptions below are based on the current
merged implementation, not the original scaffold roadmap.

## Current product boundary

Casual Theme Trend Analysis is a typed Python project whose first module is
Theme Trend Analysis. Sensor Tower is the only approved market-data source.
Themes come from Sensor Tower Game Theme / Custom Fields; the project does
not use manual theme tagging, app-name or icon inference, or LLM theme
classification.

The current market sample uses category `7012`, country `WW`,
`device_type=total`, Game Genre `Puzzle` or `Tabletop`, and up to 1200 API
candidates. Local eligibility filtering retains at most 1000 selected records:
the `WW Puzzle/Tabletop selected Top-N sample (cap 1000)`. Downloads and
Revenue (USD) are measured within this selected sample, not the complete
global mobile-games market. The selected sample may contain fewer than 1000
products; future data-quality output must expose each month's actual
`snapshot_count`.

## Implemented and real-environment accepted

The following capabilities are present in the repository and accepted at the
current MVP boundary:

- typed Python project structure, configuration, logging, validation, and
  executable CLI workflows;
- verified Sensor Tower market and metadata request boundaries, including
  source-preserving parsing, opaque identifiers, local eligibility selection,
  metadata caching, and mock transport coverage;
- DuckDB as the local analytical source of truth and Parquet as the deterministic
  export/archive boundary;
- manual single-month collection and resumable historical monthly backfill;
- read-only range-based historical quality inspection, including a
  `--require-complete` structural gate and no-write DuckDB connection;
- monthly Game Theme aggregation with explicit product, source-coverage,
  publisher, entry, rank, and concentration metrics;
- the current six-month momentum scoring workflow, stored under the unchanged
  technical `theme_trend_scores` schema and interpreted as 6M Momentum;
- Feishu schema provisioning with a preserved primary field and deterministic
  compatibility checks;
- read-only Feishu field and record inspection;
- idempotent DuckDB-to-Feishu trend synchronization with update-before-create
  batches, stale and duplicate protection, unmanaged-record preservation, and
  final reread verification;
- numeric-string Feishu Number compatibility at the read boundary; and
- the current Feishu view configuration as a documented manual ranked view
  named `最新月度趋势`: `是否最新月份 = true` and `是否可行动 = true` are
  related with AND, and `趋势排名` is sorted ascending. The technical primary
  field `文本` remains visible. The visible analytical fields are `月份`,
  `题材`, `趋势排名`, `趋势分`, `置信度`, `增长分`, `加速度分`, `新产品分`,
  and `集中度惩罚`; other quality-status and explanatory fields remain in the
  table but are hidden from this view. View APIs are not implemented.

The sanitized real-environment acceptance evidence currently recorded is:

- seven scored target months;
- 411 managed trend records;
- five preserved unmanaged blank records; and
- successful zero-create / zero-update idempotency verification.

No credentials, app tokens, table IDs, record IDs, managed keys, or raw
payloads belong in this document or the repository.

## Confirmed metric terminology

The project owner confirmed on 2026-08-12 that `units_absolute` means
Downloads (count) and `revenue_absolute` means Revenue (USD). The source names
remain in adapters and DuckDB for provenance. NULL remains unavailable and
must not become zero; an observed numeric zero remains zero.

The existing score is therefore labeled **6M Momentum Score**. It is not
Market Size, a 12M or 36M trend score, an investment recommendation, or a
forecast. The six-month implementation is a technical baseline for V2
backtesting.

## Not yet implemented

The following V2 capabilities are not yet implemented:

- 36-month production history;
- the market-size decision product;
- growth-quality decomposition;
- competitive white-space metrics;
- Theme x Sub-genre aggregation;
- lifecycle and seasonality;
- leakage-safe T+1 / T+2 / T+3 launch-window backtesting;
- investment recommendation;
- final business tables and dashboards; and
- automation.

The current six-month MVP is not the final business product. In particular,
the current score must not be presented as a complete opportunity decision or
as a Product Greenlight.

## Future decision-system boundary

V2 will answer six questions: market size, sustainable growth, competitive
room, T+1/T+2/T+3 launch-window attractiveness, validated category fit versus
migration hypothesis, and action rationale with risk and confidence. The
future output must remain explainable from Market Size, Growth Quality,
Competitive White Space, Launch Window, Category Fit and Migration Potential,
and Risk and Confidence.

Product Greenlight remains a separate decision. Product quality,
marketability, creative performance, CPI / IPM, retention, monetization,
LTV / ROAS, production cost, and team capability are outside the evidence
currently supplied by the theme-opportunity system.

## External-system boundary

DuckDB remains the source of truth. Feishu is a collaboration and dashboard
projection, not the database. Development and automated tests use synthetic
data and `httpx.MockTransport`; no real Sensor Tower or Feishu request is part
of the current implementation task.
