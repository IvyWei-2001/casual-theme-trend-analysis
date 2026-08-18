# Current System

This document records the audited state of the repository as of
DECISION-001 Phase B.
It distinguishes implemented and accepted technical behavior from the
future V2 decision product. The descriptions below are based on the current
merged implementation, not the original scaffold roadmap.

## Current product boundary

Casual Theme Trend Analysis is a typed Python project whose first module is
Theme Trend Analysis. Sensor Tower is the only approved market-data source.
Themes come from Sensor Tower Game Theme / approved theme fields; the project
does not use manual theme tagging, app-name or icon inference, or LLM theme
classification. MONETIZATION-001 does not use monetization Custom Fields.

The current market sample uses category `7012`, country `WW`,
`device_type=total`, Game Genre `Puzzle` or `Tabletop`, and up to 1200 API
candidates. Local eligibility filtering retains at most 1000 selected records:
the `WW Puzzle/Tabletop selected Top-N sample (cap 1000)`. Downloads and
observable Revenue (USD) are measured within this selected sample, not the complete
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
- sequential schema migrations through version 7, atomic derived-output
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
credential-free and side-effect-free. The project-owner-provided accepted
boundary is 2023-08 through 2026-07 with `outcome_row_count=5147`,
`feature_metric_row_count=228`, `segment_metric_row_count=336`, and
`verification=passed`. The first 36-month history emits the 36M feature
registry rows but does not validate 36M predictive value.

## MONETIZATION-001 implementation status

MONETIZATION-001 adds the pure typed modules
`src/analysis/monetization_models.py` and
`src/analysis/monetization_observability.py`, plus the offline
`derive-monetization` range workflow. It reads only stored
`market_snapshots` and uses policy
`MONETIZATION001_OBSERVABLE_REVENUE_PROXY_V1`: NULL observable Revenue is
`unknown`, zero is `iaa_candidate`, and positive is
`iap_or_hybrid_candidate`. These are candidate labels, not observed
monetization types. Zero observable Revenue does not prove zero actual total
revenue or pure IAA; positive observable Revenue does not distinguish IAP from
Hybrid; and no IAA advertising revenue is estimated. Game Product Model is
context only, and historical Custom Fields are not used.

Schema version 8 adds the compact `app_monetization_profiles` and
`theme_monetization_observability_metrics` tables; schema-v1 through v6
tables and rows remain unchanged. The inclusive range command covers
2023-08 through 2026-07 when requested, requires every stored month, makes no
Sensor Tower, metadata, Feishu, or other network request, and atomically
replaces only monetization rows. DuckDB is authoritative; the two outputs are
deterministic atomic ZSTD Parquet exports. Future `collect-month` reuses its
already selected market rows without a second request.

Development validation uses synthetic rows, mocks, temporary DuckDB, and
temporary Parquet only; no real Sensor Tower, Feishu, production database,
backup, or real export operation is included. MONETIZATION-001 does not change
AGG, MODEL-002, or BACKTEST-001 results, and BACKTEST-001 is not described as
controlling for true monetization type.

## DECISION-001 Phase A and Phase B implementation status

DECISION-001 is the current issue. Phase A adds the pure typed modules
`src/analysis/decision_models.py` and `src/analysis/decision_v1.py`, plus the
authoritative [`DECISION_V1.md`](DECISION_V1.md) policy document and focused
synthetic contract tests. Policy version `DECISION001_V1` maps accepted
MODEL-002 lifecycle evidence, current-month cross-theme Market Size and
competitive-risk percentiles, confidence boundaries, category fit, migration
hypotheses, normalized risks, recommendations, and exactly three non-forecast
launch-window rows.

The calculation preserves raw non-NULL theme and Game Sub-genre labels,
requires exact target-population reconciliation, injects one timezone-aware
timestamp, and rejects future or incompatible typed rows. It uses only
normalized project models and has no database, configuration, HTTP, Sensor
Tower, Feishu, CLI, workflow, or export dependency. Business-facing metric
wording is `observable Revenue (USD)`; `revenue_absolute` remains the
technical source field. Observable Revenue limitations remain explicit even
with complete field coverage.

Phase A did not add schema or database tables, repository readers/writers,
Parquet exports, or a CLI. Phase B now adds schema version 9 persistence and exactly five
DECISION-001 tables, typed deterministic readers, atomic exact-target-month
replacement, a stored-evidence-only workflow, the `decide-themes` CLI, and
five complete deterministic ZSTD Parquet exports. The Phase B workflow reads
only stored target-month evidence and at most twelve trailing completed
months of category evidence, calls the Phase A calculation once, never reads
raw future launch outcomes, and never recalculates upstream AGG, MODEL,
BACKTEST, or MONETIZATION results.

Plan-only runs before configuration and logging, opens no database, creates no
files, and constructs no external client. `--skip-export` commits and
verifies DuckDB rows but writes no decision Parquet. DuckDB is the source of
truth. Development validation uses synthetic models, fake repositories,
temporary DuckDB, and temporary Parquet only. No Sensor Tower, metadata,
Custom Fields, Feishu, HTTP, production database, automation, push, or PR
operation is part of this phase. DECISION-001 has not been real-environment
accepted; FEISHU-004 and AUTOMATION-001 remain later work.

## Confirmed metric terminology

The project owner confirmed on 2026-08-12 that `units_absolute` means
Downloads (count) and `revenue_absolute` means third-party-platform observable
Revenue (USD). The source names remain in adapters and DuckDB for provenance.
NULL remains unavailable and must not become zero; an observed numeric zero
remains zero. This observable Revenue is not complete total revenue.

The existing score is therefore labeled **6M Momentum Score**. It is not
Market Size, a 12M or 36M trend score, an investment recommendation, or a
forecast. The six-month implementation is a technical baseline for V2
backtesting.

## Not yet implemented

The following V2 capabilities are not yet implemented:

- DECISION-001 Feishu projection;
- final business tables and dashboards;
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
