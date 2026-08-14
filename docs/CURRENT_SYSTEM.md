# Current System

This document records the audited state of the repository as of BACKTEST-001.
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
- monthly Game Theme aggregation with explicit product, source-coverage,
  publisher, entry, rank, and concentration metrics;
- AGG-002 raw opportunity evidence for market structure, growth sources,
  observed product dimensions, and representative products;
- sequential schema migrations through version 6, atomic derived-output
  replacement, mandatory identity/count readback verification, and
  deterministic ZSTD exports;
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

## HIST-002 implementation status

The HIST-002 read-only range inspection is implemented and verified with
synthetic rows, fake repositories, and temporary DuckDB files. The recorded
real-environment prerequisite evidence is 36 completed months, 35,525 source
snapshots, monthly `snapshot_count` minimum 964 and maximum 1,000,
`structural_issue_count=0`, and `structurally_complete=true`.

## AGG-002 implementation status

The current local `aggregate-themes` workflow builds AGG-001 and AGG-002 from
internal storage rows only. It adds four V2 tables for market structure,
growth-source decomposition, observed Game Sub-genre / Product Model / Art
Style / Setting values, and fixed-limit representative-game evidence. A
version-3 database migrates sequentially to version 4 without rewriting source,
AGG-001, or trend-score rows. The workflow replaces all six derived output sets
atomically, rereads identities and counts, and exports deterministic ZSTD
Parquet files unless export is skipped. No real Sensor Tower, Feishu, DuckDB,
or Parquet operation is part of development validation.

The sanitized accepted AGG-002 evidence is 36 completed months, 35,525 source
snapshots, 2,153 theme-month evidence rows, 20,880 observed-dimension rows,
21,528 representative-game evidence rows, and `verification=passed`.

## MODEL-002 completed and real-environment accepted

The local `model-themes` workflow reads only stored monthly totals and matching
AGG-001/AGG-002 rows. It validates consecutive history, preserves raw theme
labels, zero-fills absent historical theme rows, keeps present-but-NULL metrics
unavailable, and calculates only prefix-safe target outputs. Schema version 5
adds `theme_horizon_metrics`, `theme_model_summaries`, and
`theme_seasonality_profiles` without changing existing tables or columns.

The workflow recomputes the unchanged `calculate_theme_trend_scores(...)`
baseline, atomically replaces the four model output sets, rereads exact
identities/counts, and exports deterministic ZSTD Parquet unless export is
skipped. Sanitized real-environment acceptance evidence is
`schema_version=5`, `history_month_count=36`,
`source_model_summary_row_count=2153`, `legacy_6m_score_row_count=1832`,
`horizon_metric_row_count=20118`, `seasonality_profile_row_count=52584`,
`seasonality_profile_group_count=4382`, and `verification=passed`.
Automated development validation remains synthetic and uses temporary DuckDB
and Parquet files; no new real operation is part of BACKTEST-001 development.

## BACKTEST-001 implementation status

The local `backtest-themes` workflow is implemented as a pure, typed,
leakage-safe evaluation over stored AGG-002 and MODEL-002 rows. It emits exact
T+1/T+2/T+3 raw outcomes, a fixed 19-feature by four-outcome registry, and
observed categorical-segment metrics. Decision features are read only from
the decision month; future evidence is read only from the exact outcome month.
The calculation never calls the legacy score, AGG-002 aggregation, MODEL-002
calculation, Sensor Tower, or Feishu.

Schema version 6 adds exactly `theme_launch_window_outcomes`,
`theme_backtest_feature_metrics`, and `theme_backtest_segment_metrics` without
altering prior tables or columns. Replacement validates typed rows before
opening the transaction, checks stored source identities and outcome months,
atomically replaces the requested range, rereads identities/counts/timestamps,
and can export three deterministic ZSTD Parquet files.

Development validation uses synthetic rows, fake/mock repository boundaries,
temporary DuckDB, and temporary Parquet only. The plan-only path is
credential-free and side-effect-free. The first 36-month history emits the
36M feature registry rows but has no valid 36M predictive evidence; no real
BACKTEST-001 production acceptance is claimed here.

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

- the market-size decision product or Market Size Score;
- a Growth Quality score or recommendation layer;
- competitive white-space metrics;
- business category-fit or migration decisions;
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
