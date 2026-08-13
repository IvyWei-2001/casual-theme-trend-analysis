# AGG-002 V2 Opportunity Evidence Aggregation

AGG-002 adds raw evidence aggregates for market structure, month-over-month
growth sources, observed product dimensions, and representative products. It
does not create a score, recommendation, forecast, dashboard, or Feishu
table. DuckDB remains authoritative; Parquet is an export boundary.

## Prerequisite and scope

The HIST-002 prerequisite evidence recorded for the accepted 36-month range is:

- 36 completed months;
- 35,525 source snapshots;
- minimum monthly `snapshot_count`: 964;
- maximum monthly `snapshot_count`: 1,000;
- `structural_issue_count`: 0; and
- `structurally_complete`: `true`.

The source is the WW Puzzle/Tabletop selected Top-N sample with a cap of 1,000.
It is not the complete global mobile-games market. Every calculation uses the
actual stored monthly `snapshot_count` and never pads the sample to the cap.

AGG-002 receives only `MarketSnapshotRow`, `AppMetadataRow`, current and
immediately previous stored monthly periods, and one injected timezone-aware
`calculated_at` timestamp. The analysis layer does not load configuration,
construct an external client, access the network, or accept external DTOs.

## Confirmed measures and universal rules

The source-preserving columns retain their existing names:

- `units_absolute` means Downloads count;
- `revenue_absolute` means Revenue (USD).

New business-facing V2 fields use `downloads_*` and `revenue_usd_*`. There is
no cents conversion, division by 100, currency conversion, or display rounding.
For example, a stored `revenue_absolute` value of `978768951` remains a
Revenue (USD) value of `978768951` in the derived aggregate.

SQL `NULL` means unavailable. An observed numeric zero remains zero and
participates in coverage, sums, means, medians, sorting, and leader selection.
A zero denominator produces a `NULL` share or rate; no infinity is returned.
Raw Game Theme and dimension labels are not trimmed, merged, translated,
classified, or inferred. SQL `NULL` creates no group. `Unknown`, `N/A`, and
empty strings are preserved as distinct literal source-value groups and are
never merged or rewritten.

Each month may use only itself, the immediately preceding natural calendar
month, current cached metadata, and current-row release dates. AGG-002 does
not calculate 6M, 12M, or 36M features and does not use later months.

`app_metadata` is a current, non-versioned cache. Names and publishers in V2
evidence therefore describe current cache values, may be `NULL`, and must not
be interpreted as historically versioned publisher identity. No placeholder
name or publisher is created.

## Schema version 4 and output tables

Fresh initialization migrates sequentially through versions 1, 2, 3, and 4.
A version-3 database receives exactly these four new business-derived tables;
the source tables, AGG-001 tables, and `theme_trend_scores` are not rebuilt or
rewritten:

1. `theme_market_structure_metrics`
2. `theme_growth_source_metrics`
3. `theme_dimension_monthly_metrics`
4. `theme_representative_games`

The existing `monthly_market_totals`, `theme_monthly_metrics`, and
`theme_trend_scores` columns, formulas, and stored rows remain unchanged.

### Market structure

`theme_market_structure_metrics` has one row per theme-month identity and
contains product breadth, rank breadth, Downloads and Revenue (USD) size,
product concentration, publisher concentration, and release-date evidence.

For covered metric values `values`:

```text
sum = sum(values)
mean_per_covered_product = sum / coverage_count
median_per_covered_product = median(values)
top_N_product_share = sum(largest N values) / sum
product_hhi = sum((value / sum) ** 2)
theme_metric_share = theme_sum / compatible_month_market_sum
```

For `downloads_share` and `revenue_usd_share`, a `NULL` numerator or denominator
produces `NULL`, a non-positive denominator produces `NULL`, and an observed
zero numerator with a positive denominator produces numeric `0`. Top-1, Top-3,
Top-10 shares and HHI remain `NULL` when the theme sum is unavailable or
non-positive. Publisher product shares use only rows with a current cached
publisher. Publisher Downloads and Revenue (USD) groups use only rows where
both the publisher and the corresponding metric are available. There is no
artificial Unknown Publisher bucket. Coverage counts and ratios remain visible
when metadata is incomplete.

Product age uses only `release_date_ww`:

```text
product_age_days = period_end - release_date_ww
```

Dates after `period_end` increase `release_date_ww_future_count` and are
excluded from age medians. Missing dates reduce coverage. Valid age medians are
`NULL` when no valid dates exist. The same rule is applied to current metric
Top-10 products.

### Growth source

`theme_growth_source_metrics` has one row per theme-month identity. It records
membership, entry, exit, turnover, persistence, and raw change contribution
evidence; it does not assign Growth Quality.

Market new entry means a current unified product ID absent from the immediately
previous whole-market Top-N population. Theme entry means absence from the
previous same-theme group. Theme exit means previous same-theme presence and
current same-theme absence. Continuing means presence in both same-theme groups.
These terms are not release-date or first-publication labels.

Top-100 and Top-500 turnover are calculated from same-theme rank sets:

```text
entry_count = len(current_set - previous_set)
exit_count = len(previous_set - current_set)
retained_count = len(current_set & previous_set)
turnover_rate = entry_count / len(current_set)
```

Turnover is `NULL` when the current set is empty. Downloads and Revenue
(USD) Top-10 retention are selected independently inside the same theme and
use the current covered Top-10 count as the denominator.

For each metric, the decomposition uses the union of current and previous
same-theme IDs. A product absent in one month contributes zero; a present
product with a `NULL` metric makes that metric decomposition incomplete. Only
complete decompositions expose the following fields:

```text
product_delta = current_value_or_zero - previous_value_or_zero
mom_change = sum(product_delta)
theme_entry_contribution = sum(delta for current-only same-theme IDs)
continuing_contribution = sum(delta for IDs in both same-theme groups)
theme_exit_contribution = sum(delta for previous-only same-theme IDs)
positive_contribution_sum = sum(max(delta, 0))
negative_contribution_sum = sum(min(delta, 0))
```

The decomposition validates `mom_change = current_sum - previous_sum` within a
finite tolerance. Positive-contribution shares use the positive gross sum and
are `NULL` when that denominator is zero. The month-over-month growth rate is
`mom_change / previous_sum` only when `previous_sum > 0`; zero or unavailable
previous sums never produce infinity. If the previous natural month is
unavailable, `has_previous_month=false` and all previous-dependent evidence is
`NULL`; an empty market is not fabricated.

### Observed dimensions

`theme_dimension_monthly_metrics` contains observed rows for exactly these
dimension types:

- `game_subgenre`;
- `game_product_model`;
- `game_art_style`; and
- `game_setting`.

Each row is one raw theme-month-dimension-value identity. SQL `NULL` values do
not create rows. Literal `Unknown`, `N/A`, and empty values remain separate.
Product, rank, metric, publisher, and new-entry evidence uses the same
coverage rules as market structure. Shares use the observed theme sum and the
compatible whole-market monthly sum; product shares use the actual theme
product count and `snapshot_count`, not a hard-coded 1,000 denominator. This
table is evidence only and does not infer category fit or migration potential.

### Representative games

`theme_representative_games` stores traceable evidence with the fixed constant
`DEFAULT_REPRESENTATIVE_GAME_LIMIT = 3`. It supports exactly:

- `downloads_leader`;
- `revenue_leader`;
- `market_new_entry_downloads_leader`;
- `market_new_entry_revenue_leader`;
- `downloads_growth_leader`; and
- `revenue_growth_leader`.

Metric leaders exclude `NULL` metrics but keep observed zero values. Ties sort
by metric descending, global rank ascending, then `unified_app_id` ascending.
Market-new-entry leaders filter first. Growth leaders require a previous month,
use zero for an absent previous product, exclude present-but-`NULL` values, and
keep only strictly positive changes. Evidence ranks are contiguous from 1 per
theme-month-evidence group; a product may appear under several evidence types.

## Atomic storage and workflow

`replace_theme_opportunity_range` validates every typed row and identity before
starting a transaction. It then deletes and inserts, in one transaction, the
six derived sets:

- `monthly_market_totals`;
- `theme_monthly_metrics`;
- `theme_market_structure_metrics`;
- `theme_growth_source_metrics`;
- `theme_dimension_monthly_metrics`; and
- `theme_representative_games`.

The replacement is limited to the requested monthly period identities. Every
V2 structure and growth row must match an AGG-001 theme identity; dimensions
and representative rows must also match an AGG-001 theme identity. Any later
insert failure rolls back all six sets. Source snapshots, metadata, and trend
scores are untouched. The existing two-table AGG-001 replacement method remains
available for compatibility.

The existing `aggregate-themes` command now builds AGG-001 and AGG-002 from
one immutable source set, reads one previous month outside the requested range
when it exists, commits the six-set replacement, rereads identities and exact
counts, and exports all six derived outputs unless `--skip-export` is used.
Plan-only remains credential-free and has no DuckDB, network, or file side
effects. The console summary contains counts and safe state only.

The four new exports are deterministic ZSTD Parquet files with explicit column
order, stable identity order, temporary sibling files, and atomic replacement:

```text
theme_market_structure_metrics.parquet
theme_growth_source_metrics.parquet
theme_dimension_monthly_metrics.parquet
theme_representative_games.parquet
```

## Non-goals and post-merge acceptance

AGG-002 does not call Sensor Tower or Feishu, modify source or trend rows,
calculate scores or recommendations, forecast future periods, classify labels,
infer migration potential, create dashboards, add automation, or run against a
real database or real Parquet output during development.

After merge, the bounded acceptance sequence is:

```powershell
python -m src aggregate-themes --start 2023-08 --end 2026-07 --plan-only
python -m src aggregate-themes --start 2023-08 --end 2026-07 --skip-export
python -m src aggregate-themes --start 2023-08 --end 2026-07
```

The real run is authorized only after confirming the clean worktree, accepted
HIST-002 evidence, schema backup/availability, and the intended database and
export paths. Review the sanitized counts, readback verification, six output
files, and preservation of source and trend rows after the run.
