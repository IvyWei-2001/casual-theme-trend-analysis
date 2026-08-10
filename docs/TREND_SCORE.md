# Explainable Monthly Game Theme Trend Score

TREND-001 calculates a deterministic first-version trend and opportunity score
from stored schema-v2 monthly Game Theme metrics. The workflow reads only
`monthly_market_totals` and `theme_monthly_metrics` through internal models. It
does not construct a Sensor Tower client, make a network request, classify a
theme with an LLM, or alter either source table or either schema-v2 derived
table.

## Objective

The score surfaces raw Game Theme labels that are gaining product share,
gaining `units_absolute_share` or `revenue_absolute_share` when those source
metrics are available, accelerating, continuing to receive new Top-N entries,
and showing breadth rather than excessive concentration. History, product
count, source coverage, and publisher coverage reduce confidence. The score is
not a ranking of the largest themes.

`units_absolute_share` and `revenue_absolute_share` retain their exact source
names. Their unresolved business semantics are not changed into downloads or
revenue by this analysis.

## Six-month window

Each target month uses exactly six consecutive natural calendar months:

```text
target-5  target-4  target-3 | target-2  target-1  target
          prior three        |          recent three
```

The recent window is the target month and the two preceding months. The prior
window is the three months before that. A target is created only when all six
`monthly_market_totals` periods exist. A missing source month is not treated as
zero and makes scoring fail for the supplied history.

For every raw theme present in the target month, the analysis builds a calendar
series. If the theme is absent from a stored month, it is zero-filled only for
the values that represent absence from the stored Top-N population:

- `product_count` and `product_share` become zero;
- `units_absolute_share` and `revenue_absolute_share` become zero when the
  month-wide source denominator exists;
- `new_entry_share` becomes zero;
- median rank and publisher values remain unavailable.

An unavailable source share remains unavailable. A genuinely unavailable
`new_entry_share` remains unavailable; it is not replaced with zero. This
distinction lowers actionability or confidence rather than fabricating history.
Absent-month zero filling occurs only in the trend calculation and never adds
rows to `theme_monthly_metrics`.

## Raw feature formulas

For product, units, and revenue shares, let `x_t` be the value in a calendar
month. The three-month averages and share-point gain are:

```text
recent3_average = average(x_target, x_target-1, x_target-2)
prior3_average  = average(x_target-3, x_target-4, x_target-5)
gain_3m         = recent3_average - prior3_average
```

The three-point slopes and acceleration are:

```text
recent3_slope = (x_target - x_target-2) / 2
prior3_slope  = (x_target-3 - x_target-5) / 2
acceleration   = recent3_slope - prior3_slope
```

These are share-point changes, not relative percentage growth. A missing value
in a required average or slope leaves that feature unavailable. Available
product, units, and revenue percentiles can still contribute independently to
their component averages.

Other raw features are:

- `recent3_new_entry_share`: the average new-entry share in the recent three
  calendar months. Absent theme months contribute zero; an unavailable source
  value remains unavailable.
- `median_rank_improvement`: prior-three average median rank minus recent-three
  average median rank, using active theme months only. Positive means the rank
  position improved because lower rank numbers are better.
- `publisher_count_gain_3m`: recent-three active-month publisher-count average
  minus prior-three active-month average.
- `units_absolute_overindex`:
  `latest_units_absolute_share / latest_product_share` when both are available
  and the product share is non-zero; otherwise `NULL`.
- `revenue_absolute_overindex`:
  `latest_revenue_absolute_share / latest_product_share` under the same rule.

The over-index fields are explanatory only and are not included in the MVP
score.

Coverage ratios are calculated from theme product counts and source coverage
counts. `recent3_units_coverage_ratio` and
`recent3_revenue_coverage_ratio` are recent-three covered products divided by
recent-three active products. `latest_publisher_coverage_ratio` is the latest
theme publisher coverage count divided by its latest product count.

## Actionability

Every raw target-month theme remains stored, including literal `Unknown`,
`N/A`, and empty-string labels. A row is actionable only when:

- the label is not empty, `Unknown`, or `N/A`;
- `latest_product_count >= 5`;
- at least three of the six calendar months contain the theme;
- the six source months exist; and
- the latest product share and recent-three new-entry input are available.

The last condition is the required source coverage for the first-version
component inputs. Units and revenue inputs are optional because their
component percentiles explicitly average available values. Their coverage
ratios still reduce confidence. Publisher concentration is also optional and
falls back to product-share concentration when unavailable.

Non-actionable rows use deterministic exclusion reasons, in this order:
`non_actionable_source_label`, `insufficient_latest_product_count`,
`insufficient_active_history`, and `insufficient_metric_coverage`. They have
`NULL` component scores, final score, and rank.

## Cross-theme percentiles

Percentiles are calculated separately inside each target month and only across
actionable themes. For each feature, unavailable values are excluded from that
feature's percentile population. Values are sorted ascending, ties receive
their average one-based rank, and:

```text
percentile = 100 * (average_rank - 1) / (N - 1)
```

When `N = 1`, the percentile is `50`. Higher gain, acceleration, or new-entry
values therefore receive higher percentiles. The growth and acceleration
components average their available product, units, and revenue percentiles.
The new-product component is the percentile of
`recent3_new_entry_share`.

The concentration penalty averages the percentiles of latest product share and
latest top-publisher product share. If publisher concentration is unavailable,
only the product-share percentile is used and publisher coverage still lowers
confidence.

## MVP score formula

The project MVP defaults are named in one location in
`src/analysis/trend_score.py`:

```text
base_trend_score = clip(
    0.45 * growth_score
  + 0.30 * acceleration_score
  + 0.25 * new_product_score
  - 0.20 * concentration_penalty,
    0,
    100
)
```

These are project MVP weights, not Sensor Tower formulas.

Confidence is:

```text
history_confidence  = active_months_6m / 6
size_confidence     = min(latest_product_count / 20, 1)
units_confidence    = recent3_units_coverage_ratio
revenue_confidence  = recent3_revenue_coverage_ratio
publisher_confidence = latest_publisher_coverage_ratio

confidence_score = 100 * (
    0.25 * history_confidence
  + 0.25 * size_confidence
  + 0.20 * units_confidence
  + 0.20 * revenue_confidence
  + 0.10 * publisher_confidence
)

trend_score = base_trend_score * confidence_score / 100
```

Stored values are not rounded. Rounding is used only for console display.
Within one target month, actionable themes rank by trend score descending,
then base score descending, confidence descending, and raw `game_theme`
ascending. Rank is sequential and starts at 1; ranks must not be compared
across target months.

## Storage and command

Schema version 3 adds `theme_trend_scores` without rebuilding or changing
source or schema-v2 tables. A fresh database migrates through versions 1, 2,
and 3. A version-2 database receives only the version-3 table. Recalculation
validates the complete payload and atomically replaces only requested target
months. An export failure therefore leaves committed DuckDB trend rows intact.

Run a plan without opening DuckDB or creating files:

```powershell
python -m src score-themes --start 2025-08 --end 2026-07 --plan-only
```

Run scoring and export the deterministic Parquet result:

```powershell
python -m src score-themes --start 2025-08 --end 2026-07
python -m src score-themes --start 2025-08 --end 2026-07 --skip-export
python -m src score-themes --start 2025-08 --end 2026-07 --top 20
```

The inclusive range defines available history. Twelve months from 2025-08
through 2026-07 produce seven target months from 2026-01 through 2026-07.
Unless export is skipped, the output is:

```text
<export_directory>/theme_trend_scores.parquet
```

The export uses explicit schema order, stable ordering by scope, period, rank
with `NULLS LAST`, and raw theme label, ZSTD compression, a temporary sibling
file, and atomic replacement.

## Interpretation limits

This score does not merge taxonomy labels, infer animal families or other
parent themes, detect seasonality or cycles, forecast, use machine learning,
produce lifecycle labels beyond actionability, or generate AI conclusions. It
does not implement weekly scoring, Feishu synchronization, scheduling, or
GitHub automation. A twelve-month history supports a transparent momentum
comparison, but cannot prove a long-term theme cycle or durable market trend.
