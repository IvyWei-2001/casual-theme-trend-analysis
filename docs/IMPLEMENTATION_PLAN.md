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
`revenue_absolute` is the source-preserving field for Revenue (USD), by
project-owner confirmation on 2026-08-12. Missing values remain NULL and
observed zero remains zero. The selected sample is not the complete global
mobile-games market.

The existing score is the **6M Momentum Score**. The technical field
`theme_trend_scores.trend_score` and all existing storage fields retain their
names. The score is not Market Size, not a 12M or 36M score, not an investment
recommendation, and not a forecast.

## V2 issue sequence

### 1. CONTRACT-002 - V2 business and data contract

Define the authoritative product questions, decision dimensions, source
semantics, market scope, evidence boundaries, role outputs, Product Greenlight
boundary, and V2 non-goals. This issue changes documentation and adds a
documentation consistency test only.

### 2. HIST-002 - 36-month historical backfill and data-quality validation

Extend the manually validated history to at least 36 consecutive completed
natural months, with coverage, continuity, source compatibility, and
traceability checks. Keep future information out of historical decisions.

### 3. AGG-002 - market size, growth-source, competition, Theme x Sub-genre,
and representative-game aggregates

Add internal aggregates for Market Size, growth-source decomposition,
competition, category fit, migration evidence, and representative products
without making Feishu the data store. The issue must preserve compatible
sample denominators and explicit unavailable values.

### 4. MODEL-002 - 6M, 12M, and 36M trend dimensions, lifecycle, stability, and
seasonality

Add longer-horizon dimensions and lifecycle/stability/seasonality evidence.
Keep the current 6M Momentum Score as a baseline; do not silently reinterpret
existing stored values. Final weights require evidence and review.

### 5. BACKTEST-001 - leakage-safe T+1, T+2, and T+3 launch-window validation

Evaluate historical decisions at the T+1, T+2, and T+3 horizons using only
information available at each historical decision date. Report outcome
coverage, failure cases, and uncertainty.

### 6. DECISION-001 - recommendation, risk, confidence, category fit, and
migration evidence

Compose explainable recommendations from the approved dimensions. Separate
validated Game Sub-genre fit from migration hypotheses and expose risk,
confidence, evidence coverage, and next validation actions.

### 7. FEISHU-004 - business tables, role views, and dashboards

Implement the accepted V2 business tables and role-specific dashboards only
after V2 metrics and backtests are accepted. Tables remain the drill-down and
evidence layer; dashboards remain presentation surfaces.

### 8. AUTOMATION-001 - monthly automated execution after V2 acceptance

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
