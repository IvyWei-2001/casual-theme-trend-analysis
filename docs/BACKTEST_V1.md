# BACKTEST-001 Leakage-Safe Launch-Window Validation

BACKTEST-001 is the historical evidence layer after AGG-002 and MODEL-002. It
evaluates whether information available in a decision month is associated with
future theme outcomes at T+1, T+2, and T+3. It is descriptive validation, not a
forecast, final score, investment recommendation, Product Greenlight,
Feishu workflow, or automation trigger.

## Command boundary

```powershell
python -m src backtest-themes --start 2023-08 --end 2026-07 --plan-only
python -m src backtest-themes --start 2023-08 --end 2026-07 --skip-export
python -m src backtest-themes --start 2023-08 --end 2026-07
```

The range is inclusive, uses completed natural calendar months, and requires at
least seven months. Plan-only mode is handled before configuration loading and
logging. It does not read credentials, open DuckDB, inspect Parquet, call an
external API, or write local files.

For the first 36-month history, plan-only counts are:

| Evidence family | T+1 | T+2 | T+3 |
| --- | ---: | ---: | ---: |
| Legacy 6M history | 30 | 29 | 28 |
| MODEL-002 12M history | 24 | 23 | 22 |
| MODEL-002 36M history | 0 | 0 | 0 |
| Seasonality history | 12 | 11 | 10 |

Every run emits the fixed 19-feature by four-primary-outcome by three-horizon
registry: 228 feature-metric rows. Segment rows are emitted only for observed
segment values.

## Pure calculation contract

`calculate_theme_launch_window_backtest(...)` accepts only normalized typed
rows already stored or accepted by the upstream modules:

- `MonthlyMarketTotal`;
- `ThemeMarketStructureMetric`;
- `ThemeGrowthSourceMetric`;
- `ThemeTrendScore`;
- `ThemeModelSummary`;
- `ThemeSeasonalityProfile`; and
- one timezone-aware calculation timestamp.

The pure module has no configuration, DuckDB, Parquet, Sensor Tower, Feishu,
HTTP, or workflow dependency. It does not call or reimplement the legacy score,
AGG-002 aggregation, or MODEL-002 calculation. All generated rows share one
`BACKTEST001_V1` policy version and one calculation timestamp.

## Leakage policy

For a decision month `T` and horizon `H`, the raw row uses:

- decision structure, growth-source, legacy score, model summary, and
  seasonality evidence from exactly `T`;
- a future market-structure row from exactly `T + H`; and
- a month-wide total proving that `T + H` exists.

No future model summary, trend score, growth-source row, seasonality profile,
representative product, or aggregate is used to build a decision feature.
Future model rows can therefore change later decision rows without changing an
earlier row that precedes them.

The raw population includes actionable and non-actionable legacy rows and keeps
raw theme labels, including empty or otherwise non-NULL labels. A raw outcome
requires a matching MODEL-002 summary with 6M history. Missing decision-side
source identities are validation errors rather than silently excluded rows.

## Missingness and outcomes

The six future core values are product count, product share, Downloads sum and
share, and Revenue (USD) sum and share. If the future theme is absent, all six
are numeric zero and participate in future-share cohorts. If the future theme
exists but a metric is NULL, that metric remains NULL. An observed numeric zero
remains zero.

For every core decision/future pair, BACKTEST-001 stores an absolute change. It
stores a relative change only when the decision value is greater than zero.
Change directions are `up`, `down`, `unchanged`, or `unavailable`; unchanged
uses the approved `isclose` tolerance.

Future product, Downloads-share, and Revenue-share cohorts use deterministic
percentiles and top-quintile flags. Highest numeric value receives percentile
1, ties use average rank, and a one-row cohort receives 0.5. A top quintile is
`max(1, ceil(N * 0.20))`, sorted by metric descending and then raw theme label
ascending. Numeric absent-theme zeros participate; NULL metrics do not. Cohorts
with fewer than five numeric rows receive NULL top-quintile flags.

## Fixed feature registry

The feature registry is versioned by code and stored with every aggregate row.
`higher_better` features are oriented as stored; `lower_better` features are
negated for evaluation.

| Feature | Group | Hypothesis |
| --- | --- | --- |
| `decision_product_share` | `market_size_baseline` | higher_better |
| `decision_downloads_share` | `market_size_baseline` | higher_better |
| `decision_revenue_usd_share` | `market_size_baseline` | higher_better |
| `legacy_6m_momentum_score` | `legacy_baseline` | higher_better |
| `median_normalized_slope_6m` | `model_trend` | higher_better |
| `median_normalized_slope_12m` | `model_trend` | higher_better |
| `median_normalized_slope_36m` | `model_trend` | higher_better |
| `stability_cv_median_6m` | `model_stability` | lower_better |
| `stability_cv_median_12m` | `model_stability` | lower_better |
| `stability_cv_median_36m` | `model_stability` | lower_better |
| `downloads_product_hhi` | `competition` | lower_better |
| `revenue_usd_product_hhi` | `competition` | lower_better |
| `top_500_turnover_rate` | `competition` | higher_better |
| `downloads_market_new_entry_share_of_current` | `new_entry` | higher_better |
| `revenue_usd_market_new_entry_share_of_current` | `new_entry` | higher_better |
| `downloads_top_10_positive_contribution_share` | `growth_breadth` | lower_better |
| `revenue_usd_top_10_positive_contribution_share` | `growth_breadth` | lower_better |
| `downloads_expected_seasonal_index` | `seasonality` | higher_better |
| `revenue_usd_expected_seasonal_index` | `seasonality` | higher_better |

The four and only four primary outcomes are:

1. `future_downloads_share`;
2. `future_revenue_usd_share`;
3. `downloads_share_absolute_change`; and
4. `revenue_usd_share_absolute_change`.

No composite outcome or final ranking is produced.

## Aggregate feature metrics

For each decision month, feature, horizon, and outcome, numeric feature/outcome
pairs are built after excluding NULL pairs. A cohort needs at least five pairs
for a correlation or top-quintile evaluation.

Spearman correlation uses average ranks for ties and is unavailable for a
constant series. Valid decision-month correlations have equal weight regardless
of cohort size. Stored aggregate statistics include correlation cohort count,
mean/median/linear-interpolated p25 and p75, positive-correlation count/rate,
and a Wilson 95% interval.

For every valid cohort, feature top-quintile selection and future-outcome
top-quintile selection are independent. Stored statistics include valid cohort
count, selected count, overlap/hit count and rate, Wilson interval, base rate,
lift, selected mean/median, and all-eligible mean/median. Lift is NULL when the
base rate is zero. Positive-change count/rate and Wilson intervals are stored
only for the two absolute-change outcomes.

Wilson intervals use `BACKTEST_WILSON_Z`. When there are no valid trials, the
interval is NULL. A low-sample warning is true when eligible rows are below 30
or decision-month cohorts are below six. The warning is descriptive and never
deletes or converts evidence.

## Fixed categorical segments

The segment registry is exactly:

- `legacy_actionability` with `actionable` and `non_actionable`;
- `direction_6m`, `direction_12m`, and `direction_36m`;
- `stability_band_6m`, `stability_band_12m`, and `stability_band_36m`; and
- `lifecycle_stage`.

MODEL-002 enum values are preserved exactly. Segment metrics are emitted for
observed values only and store coverage, distribution percentiles, future
top-quintile evidence, positive-change evidence where applicable, and the
same low-sample warning rule.

## Schema version 6

Version 6 adds exactly these three tables and does not alter existing tables or
columns:

1. `theme_launch_window_outcomes`;
2. `theme_backtest_feature_metrics`; and
3. `theme_backtest_segment_metrics`.

The raw table stores source policy references, legacy/model decision evidence,
decision market and competition features, future core values, six change pairs,
directions, future percentiles, top-quintile flags, and `calculated_at`.

The feature table stores the fixed 228 registry identities and aggregate
coverage, correlation, top-quintile, positive-change, warning, and timestamp
fields. When the first 36-month history cannot supply 36M decision features,
the corresponding rows still exist with zero eligible coverage and NULL
correlation/top-quintile evidence; no 12M evidence is copied into them.

The segment table stores one row per observed segment value, outcome, horizon,
range, and policy identity.

A valid version-5 database is inspected read-only without migration and without
creating version-6 tables. A writable version-5 database migrates sequentially
to version 6 without rebuilding or rewriting prior rows.

## Atomic storage and readers

`replace_theme_backtest_range(...)` validates every typed row, the exact feature
registry, source references, natural-month shifts, future total availability,
counts, rates, intervals, policies, and common timestamps before opening a
transaction. It deletes only the requested range/policy, inserts all three
output sets in one DuckDB transaction, rolls back on failure, and rereads exact
identities, counts, range, horizons, outcomes, source references, rates, and
timestamps.

Readers support range, horizon, feature, outcome, and segment filters and use
deterministic identity ordering. The three Parquet exports use explicit schema
columns, stable ordering, ZSTD compression, and atomic temporary-sibling-file
replacement. Export failure does not undo a committed DuckDB replacement.

## Validation boundary and limitations

Automated validation uses synthetic typed rows, mock/fake repository
boundaries, temporary DuckDB, and temporary Parquet only. No production
database, production Parquet, Sensor Tower request, or Feishu request is part
of development acceptance. The first 36-month history emits 36M feature rows
but does not validate 36M predictive value. Any final recommendation, score,
forecast, business dashboard, or scheduled execution requires a later issue
and separate acceptance.
