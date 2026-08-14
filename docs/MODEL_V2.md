# MODEL-002 V2 Trend, Lifecycle, Stability, and Seasonality Evidence

MODEL-002 is the evidence layer after AGG-002. It adds 6M, 12M, and 36M
descriptive trend horizons, provisional lifecycle labels, stability bands, and
leakage-safe seasonality profiles. It does not create a recommendation,
forecast, launch-window outcome, dashboard, Feishu record, or Product Greenlight.

DuckDB remains authoritative. The calculation layer accepts only normalized
`MonthlyMarketTotal`, `ThemeMarketStructureMetric`, and one injected,
timezone-aware `calculated_at`. Every typed MODEL-002 row, including horizon
metrics, summaries, and seasonality profiles, requires a timezone-aware
`calculated_at`. It has no configuration, network, Sensor Tower,
Feishu, HTTP, or DuckDB dependency. The workflow reads the already stored
AGG-001/AGG-002 rows and performs no collection or aggregation.

The accepted AGG-002 prerequisite evidence is 36 completed months, 35,525
source snapshots, 2,153 theme-month evidence rows, 20,880 observed-dimension
rows, 21,528 representative-game evidence rows, and `verification=passed`.
These are aggregate acceptance counts only; no labels, identifiers, publishers,
raw metric values, or database rows are part of this document.

## Command and plan-only contract

```powershell
python -m src model-themes --start 2023-08 --end 2026-07 --plan-only
python -m src model-themes --start 2023-08 --end 2026-07 --skip-export
python -m src model-themes --start 2023-08 --end 2026-07
```

The plan-only path is routed before configuration loading and logging. It
validates the inclusive completed-month range and prints only the range,
horizon target counts, the unchanged legacy-baseline statement, and disabled
network/database/file-write state. It does not read environment variables,
credentials, DuckDB, Parquet, or local output paths.

For the first 36-month range (`2023-08` through `2026-07`), the target counts
are 31 for 6M, 25 for 12M, 1 for 36M, and 13 seasonality targets. A horizon is
emitted only after its complete market-history length exists.

There is only one 36M target because a 36-month horizon first becomes complete
at the final month of a 36-month history. Stronger historical validation of a
36M dimension needs additional complete history, typically 48–60 months, so
that multiple 36M target decisions can be compared.

## Target population and time-series rules

For each target month, outputs are created only for raw `game_theme` labels
present in that target month’s `theme_market_structure_metrics`. SQL `NULL`
themes create no row. Empty strings and all other non-NULL labels are preserved
literally; MODEL-002 does not trim, merge, translate, classify, or infer labels.

When a target theme is absent from an earlier complete market month, the six
model values are zero-filled: product count, product share, Downloads sum and
share, and Revenue (USD) sum and share. A present-but-`NULL` Downloads or
Revenue value remains unavailable, reduces metric coverage, and prevents
complete-series evidence that requires that value. Observed zero remains a
covered zero.

Each historical target uses only its own month and earlier months. Later rows
cannot change a prior target’s horizon, summary, or seasonality output.

## `theme_horizon_metrics`

This long-form table has one row per target theme, horizon, and metric. Allowed
horizons are 6, 12, and 36 months. Allowed metrics are:

- `product_count`;
- `product_share`;
- `downloads_sum`;
- `downloads_share`;
- `revenue_usd_sum`; and
- `revenue_usd_share`.

Each row stores its window start, expected month count, numeric metric coverage,
active-month count, completeness flag, descriptive statistics, OLS slope and
normalized slope, R², endpoint changes, latest-to-mean ratio, adjacent
transition counts, population standard deviation, coefficient of variation,
maximum drawdown, months since the latest peak, and `calculated_at`.

The calculation rules are:

```text
expected_month_count = horizon_month_count
metric_coverage_count = count(numeric observations)
is_complete = metric_coverage_count == expected_month_count
absolute_change = latest_value - first_value                 # complete only
relative_change = absolute_change / first_value              # first_value > 0
linear_slope = OLS(y against x = 0..horizon-1)              # complete only
normalized_slope = linear_slope / mean_value                 # mean_value > 0
r_squared = 1 - SSE / SST                                   # NULL when SST = 0
latest_to_mean_ratio = latest_value / mean_value             # mean_value > 0
coefficient_of_variation = population_stddev / mean_value    # mean_value > 0
```

Descriptive statistics use all covered numeric observations. Adjacent values
are compared with `isclose(rel_tol=1e-9, abs_tol=1e-12)`; missing endpoints do
not create a transition. Drawdown is bounded to `[0, 1]`, is `NULL` for an
incomplete series, and is numeric zero for an all-zero complete series. Peak
ties use the latest occurrence.

## `theme_seasonality_profiles`

Seasonality requires at least 24 consecutive market months. The most recent
complete multiple of 12 months is selected, capped at 36: 24 months for an
available history of 24–35 months, and 36 months for 36 or more months. Each
selected history is split into consecutive 12-month blocks.

For each metric and block, all 12 values must be numeric and the block mean
must be positive. Each valid block is normalized by its own mean. The selected
history has exactly `complete_year_count = history_month_count // 12`; a profile
is emitted only when `2 <= observation_count <= complete_year_count`, where
`observation_count` is the number of valid blocks that contribute to the
profile, and all 12 calendar-month rows can be produced. For example, a
36-month history with one invalid block emits profiles with
`complete_year_count=3` and `observation_count=2`. Its seasonal indices must
average approximately 1,
`index_deviation` equals `seasonal_index - 1`, and the lowest calendar month
breaks peak/trough ties. Exactly one peak and one trough are stored per metric
profile; a flat profile may use the same month for both.

Within each scope, target month, theme, and metric profile group, all twelve
rows carry the same history start, history month count, complete-year count,
observation count, and calculation timestamp. When a summary has seasonality
profiles, its seasonality history and complete-year fields match those profile
metadata.

The summary stores peak, trough, and amplitude evidence for the complete
`downloads_sum` and `revenue_usd_sum` profiles. Amplitude is the maximum
seasonal index minus the minimum seasonal index. Missing complete profiles
leave those summary fields `NULL`.

## `theme_model_summaries`

There is one summary row per current AGG-002 theme-month identity. It stores
the fixed policy version `MODEL002_V1`, available-history boundaries, first
active month and left-censoring flag, active-month counts, horizon availability,
share-trend medians, stability bands, lifecycle evidence, seasonality summary,
and the calculation timestamp.

First active month is the first supplied month with `product_count > 0`.
Active in the first supplied month sets `first_active_left_censored=true`, so
the theme is never classified as emerging solely from the visible history.
`months_since_first_active` is natural calendar-month distance, with zero in
the first active month.

## Provisional policy constants

The named constants are:

```text
MODEL_POLICY_VERSION = "MODEL002_V1"
DIRECTION_NORMALIZED_SLOPE_THRESHOLD = 0.005
DIRECTION_MIN_R_SQUARED = 0.20
STABILITY_STABLE_CV_MAX = 0.15
STABILITY_VARIABLE_CV_MAX = 0.35
ACCELERATION_NORMALIZED_SLOPE_MARGIN = 0.005
```

Direction uses only `product_share`, `downloads_share`, and
`revenue_usd_share`. Each complete metric with a defined normalized slope is
available evidence. Missing, incomplete, or undefined-slope metrics are
unavailable. An available metric with a slope below the threshold is flat,
regardless of R². Otherwise, missing or low R² is noisy and does not vote.
Positive and negative slopes with adequate R² are up and down. The summary's
`direction_evidence_count_*` stores available share-metric count, separately
from the up/down/flat votes. Fewer than two available metrics produces
`insufficient_history`; at least two matching votes win, otherwise the result
is mixed.

Stability is the median available complete share-metric CV. Fewer than two
values is `insufficient_history`; the remaining bands are stable through 0.15,
variable through 0.35, and volatile above 0.35.

Lifecycle rules are applied in this order:

1. 12M direction insufficient → `insufficient_history`;
2. uncensored, less than 12 months since first active, and 6M up → `emerging`;
3. 6M and 12M up with the 6M median slope at least 0.005 above 12M →
   `accelerating`;
4. 6M up with 12M down, flat, or mixed → `recovering`;
5. 12M down while 6M is not up → `declining`;
6. 12M flat, all 12 months active, and stable/variable → `mature`;
7. 12M up → `growing`;
8. all other sufficiently observed combinations → `mixed`.

These labels are provisional evidence, not investment actions or forecasts.
BACKTEST-001 may validate or revise them.

## Storage and exports

Schema version 5 adds exactly these three tables without changing existing
tables or columns:

1. `theme_horizon_metrics`;
2. `theme_model_summaries`; and
3. `theme_seasonality_profiles`.

A version-4 database migrates to version 5 without rebuilding or rewriting
existing rows. Fresh initialization records versions 1 through 5 in order.
The read-only HIST-002 boundary is version-aware: it accepts a valid v4 source
without requiring MODEL-002 tables or creating migrations, accepts v5, and
rejects unsupported future versions.

`replace_theme_model_range(...)` validates typed rows, identities, timestamps,
source identity equality, horizon references, seasonality groups, and legacy
score references before one transaction. Seasonality groups must contain
calendar months 1 through 12, exactly one peak and trough, and an arithmetic
mean of seasonal indices approximately equal to 1. It replaces the four output
sets:

- legacy `theme_trend_scores` rows for 6M-scorable target periods;
- `theme_horizon_metrics`;
- `theme_model_summaries`; and
- `theme_seasonality_profiles`.

After commit, the workflow rereads exact counts and identities, validates
seasonality groups, and verifies legacy score identities using
`(scope_name, cadence, period_start, period_end, game_theme)` rather than the
backward-compatible four-field `ThemeTrendScore.period_key`. It exports
deterministic atomic ZSTD Parquet files:

```text
theme_trend_scores.parquet
theme_horizon_metrics.parquet
theme_model_summaries.parquet
theme_seasonality_profiles.parquet
```

DuckDB remains valid if any export fails. `--skip-export` commits rows and
reports that Parquet export was skipped.

## Legacy baseline and acceptance boundary

The workflow calls the existing `calculate_theme_trend_scores(...)` unchanged.
MODEL-002 does not copy its weights, thresholds, or actionability rules, and
the new tables do not duplicate the weighted 6M score. The existing
`score-themes` behavior remains the compatibility baseline.

Development validation uses synthetic typed rows, mock repositories, temporary
DuckDB files, and temporary Parquet outputs only. A post-merge real-environment
run, if authorized, must use the accepted 36-month prerequisite, a clean
worktree, explicitly chosen database/export paths, sanitized summaries, and
readback verification. That operational run is separate from this model
implementation and does not authorize Sensor Tower or Feishu writes.
