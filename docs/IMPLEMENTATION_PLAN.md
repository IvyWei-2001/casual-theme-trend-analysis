# Implementation Plan

This plan describes the completed technical MVP and the accepted V2 delivery
sequence. It is an implementation sequence, not authorization to expand the
scope of the current issue. One issue continues to produce one pull request.

## Completed technical MVP boundary

The original monthly technical MVP is complete enough to begin V2 contract
work. Current behavior includes:

- typed configuration, logging, CLI workflows, validation, and tests;
- verified Sensor Tower market and unified-app metadata request boundaries;
- local candidate filtering for the approved WW Puzzle/Tabletop sample;
- DuckDB persistence and deterministic Parquet exports;
- manual completed-month collection;
- resumable inclusive monthly backfill;
- monthly Game Theme aggregation with explicit coverage and NULL behavior;
- a deterministic six-month momentum baseline; and
- Feishu schema provisioning, read-only field/record inspection, idempotent
  trend synchronization, numeric-string compatibility, and a documented
  manual ranked view.

`units_absolute` is the source-preserving field for Downloads (count), and
`revenue_absolute` is the source-preserving field for observable Revenue (USD), by
project-owner confirmation on 2026-08-12. Missing values remain NULL and
observed zero remains zero. The selected sample is not the complete global
mobile-games market.

The existing score is the **6M Momentum Score**. The technical field
`theme_trend_scores.trend_score` and all existing storage fields retain their
names. The score is not Market Size, not a 12M or 36M score, not an investment
recommendation, and not a forecast.

## V2 issue sequence

### 1. CONTRACT-002 - V2 business and data contract (completed)

Define the authoritative product questions, decision dimensions, source
semantics, market scope, evidence boundaries, role outputs, Product Greenlight
boundary, and V2 non-goals. This issue changes documentation and adds a
documentation consistency test only.

### 2. HIST-002 - 36-month historical backfill and data-quality validation (completed and real-environment accepted)

Add read-only range inspection for at least 36 consecutive completed natural
months, with coverage, continuity, source compatibility, and traceability
checks. Reuse the existing resumable backfill for missing periods; keep future
information out of historical decisions.

Recorded prerequisite evidence: 36 completed months, 35,525 source snapshots,
monthly `snapshot_count` minimum 964 and maximum 1,000,
`structural_issue_count=0`, and `structurally_complete=true`.

### 3. AGG-002 - market size, growth-source, competition, Theme x Sub-genre,
 and representative-game aggregates (completed)

Add raw internal aggregates for market structure, growth-source decomposition,
publisher/product concentration, observed product dimensions, and
representative products without making Feishu the data store. Preserve
compatible sample denominators, explicit unavailable values, current-cache
metadata limitations, and the existing AGG-001/TREND-001 baseline. Scores,
recommendations, and business dashboards remain later-issue work.

### 4. MODEL-002 - 6M, 12M, and 36M trend dimensions, lifecycle, stability, and
seasonality (completed and real-environment accepted)

Add longer-horizon dimensions and lifecycle/stability/seasonality evidence.
The local implementation now uses schema version 5, pure normalized-row
calculation, atomic model-output replacement, deterministic Parquet export,
and the `model-themes` command. Keep the current 6M Momentum Score as a
baseline; do not silently reinterpret existing stored values. The provisional
policy labels remain evidence only and require BACKTEST-001 validation before
any business decision layer.

Sanitized real-environment acceptance evidence is
`schema_version=5`, `history_month_count=36`,
`source_model_summary_row_count=2153`, `legacy_6m_score_row_count=1832`,
`horizon_metric_row_count=20118`, `seasonality_profile_row_count=52584`,
`seasonality_profile_group_count=4382`, and `verification=passed`.

### 5. BACKTEST-001 - leakage-safe T+1, T+2, and T+3 launch-window validation

The local implementation reads accepted AGG-002 and MODEL-002 rows only. It
adds schema-v6 raw outcomes, fixed continuous-feature metrics, and observed
categorical-segment metrics; preserves NULL/zero semantics; validates exact
future-month identities; and atomically replaces/readbacks the three output
tables. The credential-free plan-only path reports the 36-month registry
counts without storage or file access. The accepted project boundary covers
2023-08 through 2026-07 with `outcome_row_count=5147`,
`feature_metric_row_count=228`, `segment_metric_row_count=336`, and
`verification=passed`.

### 6. MONETIZATION-001 - monetization proxy observability (completed and real-environment accepted)

Derive an explicitly labeled candidate heuristic offline from stored
`market_snapshots` only. `revenue_absolute` is third-party-platform observable
Revenue (USD): NULL is `unknown`, zero is `iaa_candidate`, and positive is
`iap_or_hybrid_candidate`. Schema version 8 adds exactly two compact output
tables, covers every requested stored month including 2023-08 through 2026-07,
and atomically replaces only those monetization rows. The issue must not
estimate IAA revenue, treat a candidate as an observed type, map Game Product
Model to monetization, use historical Custom Fields, change BACKTEST-001, add
DECISION-001 scores, create Feishu views, or make a Sensor Tower request.
Future `collect-month` reuses its already selected market rows without a second
request or historical recalculation.

### 7. DECISION-001 - recommendation, risk, confidence, category fit, and
migration evidence (current issue; Phase A)

Phase A freezes policy version `DECISION001_V1` and implements the pure typed
calculation layer over existing normalized AGG-002, MODEL-002, BACKTEST-001,
legacy 6M Momentum, and MONETIZATION-001 evidence. It emits immutable theme
decision summaries, exactly three non-forecast launch-window assessments,
normalized risks, Game Sub-genre fit rows, and explicitly unvalidated
migration hypotheses. The authoritative thresholds, rule order, enums,
limitations, and output identities are documented in
[`docs/DECISION_V1.md`](DECISION_V1.md).

Phase A does not implement storage, schema migration, repository readers or
writers, CLI, workflow orchestration, Parquet, Feishu output, automation,
Sensor Tower requests, or real-environment execution. Business-facing metric
wording for this issue is `observable Revenue (USD)`; `revenue_absolute`
remains the technical source field.

### 8. FEISHU-004 - business tables, role views, and dashboards

Implement the accepted V2 business tables and role-specific dashboards only
after V2 metrics and backtests are accepted. Tables remain the drill-down and
evidence layer; dashboards remain presentation surfaces.

### 9. AUTOMATION-001 - monthly automated execution after V2 acceptance

Automate the accepted monthly workflow only after FEISHU-004 and
cross-functional acceptance. AUTOMATION-001 is intentionally paused until
those gates are complete.

## Contract and scope rules

- Sensor Tower remains the only approved market-data source.
- Game Theme / Custom Fields remains the only approved theme-classification
  source; no manual tagging or LLM classification.
- DuckDB remains the source of truth; Feishu is not a database.
- V2 may expose an Investment Priority only when its component dimensions
  remain explainable; one opaque score is not acceptable.
- Product Greenlight is separate from theme opportunity and requires product,
  creative, user-acquisition, retention, monetization, cost, and team evidence
  outside the current theme system.
- Final model weights are not selected in CONTRACT-002.
- Every issue has one pull request, with focused tests, documentation, type
  hints, logging, mocks, and known limitations.
