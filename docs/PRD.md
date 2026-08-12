# Casual Theme Trend Analysis

Version: 0.2
Owner: Century Games
Status: Active - V2 contract approved

The authoritative business contract is
[`BUSINESS_DECISION_CONTRACT.md`](BUSINESS_DECISION_CONTRACT.md).

## 1. Product goal

Build a long-term theme-opportunity decision system for casual games. The
system supports publishing leadership, executives, market intelligence,
product and R&D, operations, and analysts.

It helps decide whether a theme deserves exploration or project validation. It
does not independently decide whether a specific game should be published;
Product Greenlight remains a separate decision.

## 2. Six V2 business questions

The product must answer:

1. How large is the market for this theme?
2. Is the market genuinely and sustainably growing?
3. Is there competitive room for a new product?
4. If development starts now, will the opportunity remain attractive at T+1,
   T+2, and T+3 months?
5. In which game sub-genres and product forms has the theme been validated,
   and where is migration only a hypothesis?
6. Why should the company act, what are the primary risks, and how confident
   is the conclusion?

The required decision dimensions are Market Size, Growth Quality, Competitive
White Space, Launch Window, Category Fit and Migration Potential, and Risk and
Confidence. A future Investment Priority may summarize these dimensions only
when its components remain explainable; one opaque score is not sufficient.

## 3. Audience outputs

- **Executive / publishing leadership:** largest markets, large and growing
  themes, best T+1 to T+3 opportunities, high-risk or overheated themes, and
  recommendation, rationale, risk, and confidence.
- **Market intelligence:** 36-month Downloads and Revenue (USD),
  growth-source decomposition, lifecycle, seasonality, competition, and
  representative products.
- **R&D / product:** validated Game Sub-genres, Game Product Model, Game Art
  Style, Game Setting, representative games, proven combinations, migration
  opportunities, and migration evidence and risks.
- **Operations:** historical peak and low seasons, lifecycle state, T+1/T+2/T+3
  launch windows, recommended launch timing, and overheating or reversal risk.
- **Analysts:** formulas, source fields, data coverage, sample size,
  confidence, known limitations, and source-record traceability.

## 4. Data source and classification boundary

Sensor Tower is the only approved market-data source. Theme classification
comes from Sensor Tower Game Theme / Custom Fields. No manual tagging, name or
icon inference, or LLM theme classification is permitted.

The current operational sample uses:

- category `7012`;
- country `WW`;
- `device_type=total`;
- Game Genre `Puzzle` or `Tabletop`;
- up to 1200 API candidates;
- local eligibility filtering that retains at most 1000 selected records; and
- the optional exclusion rule based on `Most Popular Country by Revenue =
  China`.

Downloads and Revenue (USD) are measured inside the `WW Puzzle/Tabletop
selected Top-N sample (cap 1000)`. The selected sample may contain fewer than
1000 products and is not the complete global mobile-games market. Future
data-quality output must expose each month's actual `snapshot_count`, rather
than implying a fixed denominator.

## 5. Confirmed source semantics

The project owner confirmed on 2026-08-12, rather than the project inferring
from field names alone:

| Source field | Business meaning | Unit |
| --- | --- | --- |
| `units_absolute` | Downloads | count |
| `revenue_absolute` | Revenue | USD |

Adapters and DuckDB retain `units_absolute` and `revenue_absolute` for
provenance. Business-facing output may use Downloads and Revenue (USD). NULL
means unavailable and remains NULL; an observed numeric zero remains zero.

For the selected monthly sample, `units_absolute_sum` is Downloads summed over
covered products, `revenue_absolute_sum` is USD revenue summed over covered
products, and their shares use the compatible selected monthly sample
denominator.

## 6. Historical and production-cycle requirements

V2 requires a minimum of **36 consecutive completed natural months**. With
current latest month July 2026, the first intended range is August 2023
through July 2026. 48-60 months are desirable when available for rolling
validation of 36-month features.

Six months is short-term momentum only; twelve months is medium-term
persistence; thirty-six months is evidence for structural trend, lifecycle,
stability, and seasonality. Thirty-six months alone does not prove a forecast.

A game typically requires at least 1-3 months of production. The primary
investment question is therefore whether an advantage is expected to remain at
launch after one, two, or three months. Historical T+1, T+2, and T+3
validation must be leakage-safe.

## 7. Theme opportunity versus Product Greenlight

The theme system asks: **Should we explore or validate this theme?**

Product Greenlight asks: **Should we publish this specific game?**

Product Greenlight additionally requires product quality, marketability,
creative performance, CPI / IPM, retention, monetization, LTV / ROAS,
production cost, and team capability. These are not blockers for theme-
opportunity V2, but this system must not claim to replace them.

## 8. Future business outputs

The intended underlying tables are:

1. Theme Decision Overview
2. Theme Monthly History
3. Theme x Sub-genre Fit
4. Representative Game Evidence
5. Metric Definitions and Data Quality

The intended primary dashboards are:

1. Theme Opportunity Overview
2. Market Trend Analysis
3. Theme x Category Opportunity
4. Project and Launch Window

Dashboards are executive and role-specific entry points; tables remain the
drill-down and evidence layer. FEISHU-004 will implement them only after V2
metrics and backtests are accepted.

## 9. V2 non-goals

CONTRACT-002 does not implement historical backfill, formulas, model weights,
forecasting, machine learning, AI-generated recommendations, CPI or retention
integration, new DuckDB tables, Feishu fields/records/views/dashboards,
GitHub Actions, or scheduling. Future capabilities may be described in the
roadmap, but they are not claimed as current behavior.

## 10. Engineering principles

- Reuse existing verified systems and contracts.
- Never invent Sensor Tower endpoints, parameters, fields, or semantics.
- Keep business logic independent of Sensor Tower and Feishu field names.
- Use mocks before production integrations.
- Give every feature tests, documentation, type hints, logging, and an
  independently executable boundary.
