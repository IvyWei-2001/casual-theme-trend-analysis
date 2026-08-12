# Casual Theme Opportunity Decision Contract

Version: V2 / CONTRACT-002
Status: Authoritative business contract
Confirmed source semantics: 2026-08-12

This document defines the V2 business contract for Casual Theme Trend
Analysis. It is the authority for product positioning, decision terminology,
confirmed source semantics, evidence boundaries, and the future delivery
sequence. It describes future capabilities without claiming that they are
already implemented.

## 1. Product positioning

The product is not merely a theme trend ranking. It is a theme-opportunity
decision system for publishing leadership, executives, market intelligence,
product and R&D, operations, and analysts.

The system helps the company decide whether a theme deserves exploration or
project validation. It does not independently decide whether a specific game
should be published.

The current technical MVP supplies a six-month momentum baseline. The V2
system will add the evidence and decision dimensions needed for a longer-term,
explainable opportunity assessment.

## 2. Six mandatory decision questions

These are the top-level product questions. Each question requires an explicit
evidence boundary; a plausible interpretation is not a substitute for the
required evidence.

### 2.1 How large is the market for this theme?

- **Business purpose:** establish the scale of the selected market sample and
  identify themes with meaningful demand and product presence.
- **Evidence required:** 36-month Downloads and Revenue (USD), product and
  publisher coverage, sample scope, and representative products.
- **Decision output:** market-size dimensions with visible coverage and scope
  qualifiers.
- **Must not be inferred:** the selected sample must not be described as the
  complete global mobile-games market, and a large observed total must not be
  treated as proof of a publishable game.

### 2.2 Is the market genuinely and sustainably growing?

- **Business purpose:** distinguish durable theme development from a short
  spike, seasonal rebound, or one-product event.
- **Evidence required:** demand growth, supply growth, per-product efficiency,
  new-product and existing-product contribution, top-product and broad
  multi-product contribution, seasonality, and lifecycle evidence.
- **Decision output:** a Growth Quality assessment with its component drivers,
  data coverage, and confidence.
- **Must not be inferred:** one month, one blockbuster, or a current ranking
  cannot establish sustainable growth.

### 2.3 Is there competitive room for a new product?

- **Business purpose:** identify potential room for differentiated entry.
- **Evidence required:** future evidence must separately expose new-entry
  product count, new-entry product success rate, Downloads share captured by
  new entrants, Revenue (USD) share captured by new entrants, Top 100 and Top
  500 turnover, incumbent/head-product persistence or product age, whether
  growth remains locked in established products, and whether new products
  successfully break the existing structure. Product breadth, publisher
  concentration, market-share distribution, representative products,
  lifecycle position, and comparable category evidence remain supporting
  context.
- **Decision output:** Competitive White Space evidence, including saturation
  and concentration risks. Concentration alone is insufficient to prove white
  space.
- **Must not be inferred:** low observed scale or low product count alone does
  not prove white space; missing coverage is not evidence of low competition.
- Thresholds, formulas, weights, and decision rules for this evidence are
  deferred to AGG-002, MODEL-002, and BACKTEST-001.

### 2.4 If development starts now, will the opportunity remain attractive at
T+1, T+2, and T+3 months?

- **Business purpose:** align the decision with the typical production cycle,
  rather than evaluating only whether a theme is hot today.
- **Evidence required:** leakage-safe historical launch-window outcomes at
  T+1, T+2, and T+3, together with the market, growth, competition, and
  lifecycle features available at the historical decision date.
- **Decision output:** Launch Window scenarios, recommended timing, and the
  uncertainty around each horizon.
- **Must not be inferred:** current heat is not a forecast, and a historical
  decision must not use information that was unavailable at that time.

### 2.5 In which game sub-genres and product forms has the theme been validated,
and where is migration only a hypothesis?

- **Business purpose:** separate observed category fit from an opportunity that
  still needs product validation.
- **Evidence required:** Game Sub-genre, Game Product Model, Game Art Style,
  Game Setting, representative games, repeated examples, and adjacent-category
  evidence where migration is proposed.
- **Decision output:** validated fit, proven combinations, and separately
  labeled migration hypotheses with evidence and risks.
- **Must not be inferred:** adjacency, compatibility, or low penetration is not
  proof that a theme has succeeded in another Game Sub-genre.

### 2.6 Why should the company act, what are the primary risks, and how
confident is the conclusion?

- **Business purpose:** make the recommendation auditable and useful for an
  explicit next action.
- **Evidence required:** component dimensions, risk indicators, data coverage,
  sample sizes, traceable source records, and confidence limitations.
- **Decision output:** recommendation, rationale, primary risks, confidence,
  and the next validation step.
- **Must not be inferred:** this conclusion is not a product Greenlight and
  confidence must not conceal missing or incompatible evidence.

## 3. Required decision dimensions

The future V2 product must expose these dimensions:

- **Market Size**
- **Growth Quality**
- **Competitive White Space**
- **Launch Window**
- **Category Fit and Migration Potential**
- **Risk and Confidence**

The final product may later expose an **Investment Priority**, but it must
never show only one opaque score. Every recommendation must remain explainable
from its component dimensions, evidence, and limitations.

## 4. Growth-quality decomposition

Growth must be decomposed into the following evidence dimensions:

- demand growth;
- supply growth;
- per-product efficiency growth;
- new-product contribution;
- existing-product contribution;
- top-product contribution;
- broad multi-product contribution;
- seasonal rebound; and
- a possible one-blockbuster event.

CONTRACT-002 does not define final formulas or weights. Those decisions belong
to AGG-002, MODEL-002, and BACKTEST-001 and must remain subject to validation.

## 5. Production-cycle boundary

A game typically requires at least 1-3 months of production. Therefore, the
primary investment question is not whether a theme is hot today, but whether
its advantage is expected to remain at launch after one, two, or three months.

The future Launch Window model must be backtested using historical T+1, T+2,
and T+3 outcomes. It must not use future information when calculating a
historical decision.

## 6. Theme opportunity versus game Greenlight

The two decisions are separate:

| Decision | Contract question |
| --- | --- |
| Theme opportunity system | Should we explore or validate this theme? |
| Product Greenlight system | Should we publish this specific game? |

Final product Greenlight additionally requires evidence not currently provided
by this project:

- product quality;
- marketability;
- creative performance;
- CPI / IPM;
- retention;
- monetization;
- LTV / ROAS;
- production cost; and
- team capability.

These are not blockers for theme-opportunity V2, but the theme system must not
claim to replace the Product Greenlight system.

## 7. Role-specific outputs

### Executive / publishing leadership

The output must make visible the largest markets, large and growing themes,
best T+1 to T+3 opportunities, high-risk or overheated themes, and the
recommendation, rationale, risk, and confidence.

### Market intelligence

The output must support 36-month Downloads and Revenue (USD), growth-source
decomposition, lifecycle, seasonality, competition, and representative
products.

### R&D / product

The output must support validated Game Sub-genres, Game Product Model, Game
Art Style, Game Setting, representative games, proven combinations, potential
migration opportunities, and migration evidence and risks.

### Operations

The output must show historical peak and low seasons, lifecycle state, T+1 /
T+2 / T+3 launch windows, recommended launch timing, and overheating or
reversal risk.

### Analysts

The output must expose formulas, source fields, data coverage, sample size,
confidence, known limitations, and source-record traceability.

## 8. Confirmed source semantics

The following business semantics were confirmed by the project owner on
2026-08-12. They were not inferred solely from the response field names.

| Source field | Confirmed business meaning | Unit |
| --- | --- | --- |
| `units_absolute` | Downloads | count |
| `revenue_absolute` | Revenue | USD |

Source adapters and the DuckDB schema retain the exact source field names
`units_absolute` and `revenue_absolute` for provenance. Business-facing output
may display **Downloads** and **Revenue (USD)**.

NULL means the measure is unavailable and must never become zero. An observed
numeric zero remains zero.

For the selected monthly sample:

- `units_absolute_sum` is Downloads summed over covered products;
- `revenue_absolute_sum` is USD revenue summed over covered products; and
- their shares use the compatible selected monthly sample denominator.

These definitions do not resolve unrelated delta, transformed, comparison,
date, sorting, pagination, or other source-contract questions.

## 9. Market-scope statement

The current operational scope is:

- Sensor Tower category `7012`;
- country `WW`;
- `device_type=total`;
- Game Genre `Puzzle` or `Tabletop`;
- up to 1200 API candidates;
- local eligibility filtering that retains at most 1000 selected records; and
- the optional current exclusion rule based on `Most Popular Country by
  Revenue = China`.

Downloads and Revenue (USD) are measured inside the `WW Puzzle/Tabletop
selected Top-N sample (cap 1000)`. The selected sample may contain fewer than
1000 products and must not be described as the complete global mobile-games
market. Future data-quality output must expose each month's actual
`snapshot_count`, rather than implying a fixed denominator.

Recommended dashboard language:

> Scope: WW Puzzle/Tabletop selected Top-N sample (cap 1000)

Business field labels may remain **Downloads** and **Revenue (USD)** when this
scope statement is visible.

## 10. Historical horizon

- **36 consecutive completed natural months** are the minimum V2 production
  history.
- With current latest month July 2026, the first intended range is August
  2023 through July 2026.
- 48-60 months are desirable when available for stronger rolling validation of
  36-month features.
- Six months is short-term momentum only.
- Twelve months is medium-term persistence.
- Thirty-six months supplies structural trend, lifecycle, stability, and
  seasonality evidence.

Thirty-six months alone does not prove a forecast.

## 11. Category-fit evidence boundary

### Validated fit

Validated fit means observed adoption and performance in a Game Sub-genre,
supported by products, Downloads, Revenue (USD), and multiple examples where
available.

### Migration hypothesis

A migration hypothesis is an inferred opportunity in another Game Sub-genre.
It may be supported by adjacent-category evidence, low penetration, a
compatible product model, art style, or setting, but it must not be presented
as proven market fact.

No manual theme tagging or LLM theme classification may be introduced. Theme
classification remains based on Sensor Tower Game Theme / Custom Fields.

## 12. Future Feishu product

The intended future output surfaces are defined here without implementing
them.

### Underlying business tables

1. Theme Decision Overview
2. Theme Monthly History
3. Theme x Sub-genre Fit
4. Representative Game Evidence
5. Metric Definitions and Data Quality

### Primary dashboards

1. Theme Opportunity Overview
2. Market Trend Analysis
3. Theme x Category Opportunity
4. Project and Launch Window

Dashboards are the executive and role-specific entry points. Tables remain the
drill-down and evidence layer. FEISHU-004 will implement them only after V2
metrics and backtests are accepted.

## 13. V2 non-goals

CONTRACT-002 does not implement:

- historical backfill;
- formulas;
- model weights;
- forecasting;
- machine learning;
- AI-generated recommendations;
- CPI or retention integration;
- new DuckDB tables;
- Feishu fields, records, views, or dashboards;
- GitHub Actions; or
- scheduling.

The contract may describe these future capabilities, but must not claim that
they already exist.
