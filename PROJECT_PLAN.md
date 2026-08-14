# Project Plan

Project: Casual Theme Trend Analysis
Status: Active
Current focus: multi-horizon trend, lifecycle, stability, and seasonality evidence

## Development principles

The project is built incrementally. Each issue has one narrow purpose and
each pull request implements one issue only. Every implementation issue must
include tests, documentation, type hints, logging, known limitations, and a
mock boundary for external APIs.

DuckDB is the analytical source of truth and Parquet is the approved
file-oriented export boundary. Feishu is a collaboration and dashboard
projection. Sensor Tower is the only approved market-data source, and themes
must come from Sensor Tower Game Theme / Custom Fields rather than manual or
LLM classification.

## Completed technical MVP

The original monthly technical MVP is complete enough to support the next V2
contract work. The merged implementation includes:

- typed Python configuration, logging, CLI, validation, and tests;
- verified Sensor Tower market and metadata boundaries with local candidate
  selection and metadata caching;
- DuckDB and Parquet persistence;
- manual monthly collection and resumable historical backfill;
- monthly Game Theme aggregation;
- the current six-month momentum scoring baseline; and
- Feishu schema provisioning, read-only inspection, idempotent trend
  synchronization, and the documented manual ranked view.

The current score is a 6M Momentum Score. It is not the V2 opportunity
decision, an investment recommendation, or a forecast.

## V2 issue sequence

Implement the next issues in exactly this order:

1. **CONTRACT-002 - V2 business and data contract (completed)**
2. **HIST-002 - 36-month historical backfill and data-quality validation
   (completed and real-environment accepted)**
3. **AGG-002 - market size, growth-source, competition, Theme x Sub-genre,
   and representative-game aggregates (completed and real-environment
   accepted)**
4. **MODEL-002 - 6M, 12M, and 36M trend dimensions, lifecycle, stability, and
   seasonality (current)**
5. **BACKTEST-001 - leakage-safe T+1, T+2, and T+3 launch-window validation**
6. **DECISION-001 - recommendation, risk, confidence, category fit, and
   migration evidence**
7. **FEISHU-004 - business tables, role views, and dashboards**
8. **AUTOMATION-001 - monthly automated execution after V2 acceptance**

CONTRACT-002 and HIST-002 are complete; AGG-002 is completed and
real-environment accepted; MODEL-002 is the current
focus. The recorded HIST-002 evidence is 36 completed months, 35,525 source snapshots,
monthly `snapshot_count` bounds of 964 and 1,000, zero structural issues, and
structural completeness. Final model weights are not selected in
CONTRACT-002. AUTOMATION-001 is paused until FEISHU-004 and cross-functional
acceptance. The one-issue/one-PR rule continues throughout this sequence.

## Scope guard

AGG-002 adds only raw evidence aggregates and their local storage/export
workflow. MODEL-002 adds descriptive multi-horizon evidence and provisional
lifecycle/stability/seasonality labels without changing the legacy 6M
Momentum formula. Neither issue adds forecasting, recommendations, CPI or
retention integration, Feishu fields/records/views/dashboards, GitHub Actions,
or scheduling. BACKTEST-001 and later issues remain responsible for outcomes
and business decisions.

The V2 product must keep theme opportunity separate from Product Greenlight.
The latter additionally requires product quality, marketability, creative
performance, CPI / IPM, retention, monetization, LTV / ROAS, production cost,
and team capability.
