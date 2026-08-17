# Internal Data Model

This is a conceptual domain model, not a database schema. It defines the internal contract between the two-stage Sensor Tower ingestion flow, DuckDB persistence, analytics, and Feishu output.

Sensor Tower field names must not leak into business logic. The adapter maps
source fields into the internal names below, preserves source names where
provenance requires them, and keeps only still-unconfirmed semantics as
explicit unavailable or TODO states.

## Operational market scope

The current stored market sample uses Sensor Tower category `7012`, country
`WW`, `device_type=total`, and Game Genre `Puzzle` or `Tabletop`. The request
may return up to 1200 API candidates; local eligibility filtering then retains
at most 1000 selected records in the `WW Puzzle/Tabletop selected Top-N sample
(cap 1000)`, with the optional exclusion based on `Most Popular Country by
Revenue = China`.

Downloads and Revenue (USD) in this model are measured inside that selected
project sample. Stored values must not be described as the complete global
mobile-games market. The selected sample may contain fewer than 1000 products;
future data-quality output must expose each month's actual `snapshot_count`.

## Design principles

- The market/ranking response and the metadata enrichment response are separate external inputs.
- The two inputs are joined through source identity before creating a complete internal observation.
- `app_id` is a project-owned internal identifier, but it is not the only identity used for reconciliation.
- `source_app_id` is retained for the source product identity. `unified_app_id` is retained when the source makes it available.
- Source and unified identifiers are normalized strings. They may be numeric
  strings for older fixtures or opaque non-numeric strings from the live
  unified endpoint; internal code must not assume an integer ID space.
- Missing or unavailable data remains explicit. It must not be converted to zero.
- Normalized metadata fields reject generated `"Unknown"` and `"N/A"`
  fallbacks, while raw Sensor Tower source observations preserve those
  literals exactly. A missing source observation remains SQL `NULL`; the
  storage boundary does not trim or interpret source text and still rejects
  non-string source values.
- Weekly and monthly observations share one `Snapshot` model and are distinguished by `cadence`.
- `ThemeMetric` is derived data and never replaces the underlying snapshots.

## DB-001 persistent storage contract

DuckDB is the local source of truth for normalized analytical records. Schema
version 7 contains seventeen business tables plus the `schema_migrations`
control table. Version 4 adds four V2 evidence tables, version 5 adds three
MODEL-002 evidence tables, version 6 adds three BACKTEST-001 evidence tables,
and version 7 adds two MONETIZATION-001 evidence tables without changing
source tables, schema-v2 monthly aggregation rows, schema-v3 trend scores, or
prior evidence rows:

- `app_metadata` is the normalized, persistent metadata cache keyed by
  `unified_app_id`. It stores only returned metadata, keeps unavailable values
  as SQL `NULL`, and records the verified publisher-resolution source.
- `market_snapshots` stores one final selected product per stored market period.
  It retains the verified source metric and tag names, including
  `units_absolute` and `revenue_absolute` with their confirmed business
  aliases Downloads (count) and Revenue (USD). It also retains
  `current_units_value` and `current_revenue_value`, whose meanings remain
  unresolved for the fields themselves; no cross-field substitution is made.
  Raw source-tag values are preserved literally, including `"Unknown"` and
  `"N/A"`; those strings are not normalized display fallbacks.
  Every verified source metric is nullable because the live market response
  may omit the current/comparison and generic fields. Omitted values are
  stored as SQL `NULL`, not zero or a substitute from another source field.

Version 5 adds:

- `theme_horizon_metrics`: long-form 6M, 12M, and 36M descriptive and trend
  evidence for six approved metrics;
- `theme_model_summaries`: one explainable policy-versioned summary per
  current AGG-002 theme-month identity, including direction, stability,
  lifecycle, active-history, and absolute-metric seasonality evidence; and
- `theme_seasonality_profiles`: twelve-row calendar-month profiles built from
  recent complete 12-month blocks with per-block normalization.

MODEL-002 uses only normalized internal rows and one injected timezone-aware
calculation timestamp. It preserves raw theme labels, zero-fills absent
historical theme rows, keeps present-but-NULL metrics unavailable, and never
uses later months when producing an earlier target. See
[`MODEL_V2.md`](MODEL_V2.md) for formulas, policy order, readers, replacement,
readback, and export contracts.

Version 6 adds:

- `theme_launch_window_outcomes`: one raw decision-month/theme row per
  evaluated future horizon, retaining decision features, exact future core
  values, absolute/relative changes, directions, percentiles, and top-quintile
  flags;
- `theme_backtest_feature_metrics`: the fixed continuous-feature by primary-
  outcome aggregate registry; and
- `theme_backtest_segment_metrics`: observed rows for the fixed actionability,
  direction, stability, and lifecycle segment registry.

Segment Top-Quintile fields include the explicit
`future_top_quintile_eligible_count` denominator. It counts only numeric
segment rows in decision-month cohorts with at least five numeric outcome
rows; the general `eligible_row_count` remains the coverage and distribution
denominator.

BACKTEST-001 preserves NULL as unavailable and observed zero as numeric. It
zero-fills only the six future core values when a future theme is absent. Its
decision features use the exact decision month; future outcome evidence uses
only the exact shifted month. A version-5 database remains valid for
read-only inspection without creating version-6 tables. See
[`BACKTEST_V1.md`](BACKTEST_V1.md) for the complete pure-analysis and storage
contract.

The composite market-period identity is:

```text
(scope_name, cadence, period_start, period_end)
```

Within one period, `unified_app_id` and `rank_position` are each unique. The
storage repository validates one complete contiguous rank set and matching
request provenance before starting a transaction. It then deletes and inserts
the complete period and commits only after all rows succeed, so a failed
replacement leaves the previous valid period unchanged.

The metadata cache considers a row fresh when `as_of - fetched_at <= 14 days`.
Exactly 14 days is fresh; older rows are stale. Lookup preserves first-seen
input order, deduplicates IDs, distinguishes fresh, stale, and missing values,
and never performs a network refresh. Parquet exports are deterministic archive
outputs with explicit columns, stable ordering, ZSTD compression, and an
atomic temporary-sibling-file replacement. Parquet is not the transactional
source of truth, and generated database/WAL/Parquet files are not committed.

DB-001 does not implement live collection, historical backfill, theme
aggregation, Trend Score, or Feishu synchronization. Live single-period
collection is deferred to DB-002. AGG-001 adds the two derived tables described
below without changing the source-table columns. AGG-002 adds the separate
schema-v4 evidence tables described after the AGG-001 contract. TREND-001 adds
the schema-v3 score table, MODEL-002 adds the schema-v5 evidence tables, and
BACKTEST-001 adds the schema-v6 evidence tables, and MONETIZATION-001 adds the
schema-v7 monetization evidence tables, without changing earlier table
contracts.

## AGG-001 schema-v2 derived storage contract

`monthly_market_totals` and `theme_monthly_metrics` are derived from stored
`market_snapshots` plus the current normalized `app_metadata` cache. The
aggregation layer receives internal rows only; it does not receive Sensor
Tower DTOs and never calls Sensor Tower.

`monthly_market_totals` has one row per `(scope_name, cadence, period_start,
period_end)` and requires `cadence = monthly`. It records:

- `snapshot_count`: every stored source row in the month, including rows with
  NULL `game_theme`;
- `theme_present_count` and `theme_missing_count`: NULL versus non-NULL raw
  `game_theme` counts;
- `metadata_coverage_count`: rows whose `unified_app_id` has an
  `app_metadata` row, even when the metadata name or publisher is NULL;
- `units_absolute_coverage_count` and `units_absolute_sum`: the number of
  covered products and the Downloads count summed over non-NULL
  `units_absolute` values;
- `revenue_absolute_coverage_count` and `revenue_absolute_sum`: the number of
  covered products and the USD Revenue summed over non-NULL
  `revenue_absolute` values.

The two source sums are NULL at zero coverage. An observed sum of zero remains
zero. The source column names remain `units_absolute` and
`revenue_absolute`; business-facing output may use Downloads and Revenue
(USD). NULL is unavailable and is never converted to zero.

`theme_monthly_metrics` has one row for every non-NULL raw `game_theme` value
observed in a month. Labels such as `Unknown`, `N/A`, and an empty string are
literal source labels. NULL does not create a theme row. Its formulas are:

```text
product_share = product_count / monthly_market_totals.snapshot_count
top_100_count = count(rank_position <= 100)
top_500_count = count(rank_position <= 500)
average_rank = arithmetic mean(rank_position)
median_rank = deterministic median(rank_position)
units_absolute_share = theme Downloads sum / month Downloads sum
revenue_absolute_share = theme Revenue (USD) sum / month Revenue (USD) sum
```

The two shares use the compatible selected monthly sample denominator. Their
technical field names remain `units_absolute_share` and
`revenue_absolute_share` so source provenance is retained.

The source metric shares are NULL when the theme sum or month-wide denominator
is unavailable, including a zero denominator. Missing-theme rows remain in the
month-wide denominator, so visible theme shares may sum below 1. Product share
uses the actual stored monthly population rather than a hard-coded 1,000.

New entry is membership in the current stored monthly Top-N population that is
absent from the immediately preceding stored calendar month, joined by
`unified_app_id`. It is not an app release, publication, first launch, or new
theme classification. A missing or empty previous stored month leaves the
new-entry fields NULL; a previous month outside the requested range is used
when it exists in DuckDB.

Publisher metrics use the current normalized metadata cache: coverage counts
non-NULL `publisher_display_name`, publisher count is the distinct non-NULL
name count, and top-publisher product share is the largest publisher product
count divided by publisher coverage. The cache is not historically versioned,
so publisher-name changes are not interpreted historically.

Replacement validates the complete derived payload, deletes only the requested
scope/month keys, inserts both derived tables in one transaction, and commits
only after both succeed. A failed replacement leaves the previous derived
result and all source rows unchanged. DuckDB remains the source of truth;
`monthly_market_totals.parquet` and `theme_monthly_metrics.parquet` are
deterministic exports. AGG-001 does not implement Trend Score.

## AGG-002 schema-v4 opportunity evidence storage contract

AGG-002 consumes only normalized `MarketSnapshotRow` and `AppMetadataRow`
values. It adds four immutable typed derived models and tables:

- `theme_market_structure_metrics`: current theme breadth, rank distribution,
  Downloads and Revenue (USD) coverage/sums/means/medians, top-product shares,
  HHI, publisher concentration, and `release_date_ww` age evidence;
- `theme_growth_source_metrics`: previous-month membership, market new entry,
  theme entry/exit, Top-100/Top-500 turnover, Top-10 retention, and raw metric
  contribution decomposition;
- `theme_dimension_monthly_metrics`: observed raw values for
  `game_subgenre`, `game_product_model`, `game_art_style`, and `game_setting`;
  and
- `theme_representative_games`: fixed-limit traceable evidence for Downloads,
  Revenue (USD), market-new-entry, and strictly positive growth leaders.

All four tables use one theme-month identity plus their table-specific key.
V2 business-facing fields use `downloads_*` and `revenue_usd_*`; source columns
remain `units_absolute` and `revenue_absolute`. Downloads means count and
Revenue means USD. No cents conversion, display rounding, or fixed 1,000-row
denominator is applied. Actual `snapshot_count` is used for market shares.

Raw labels are evidence, not a taxonomy decision: SQL `NULL` creates no group,
while `Unknown`, `N/A`, and an empty string remain separate values. `NULL`
metric values are unavailable; observed zero values remain covered numeric
zeros. Zero denominators yield `NULL` shares/rates. Current metadata names and
publishers may be NULL and are not historically versioned.

Market structure uses covered-value sums, arithmetic means, medians, top-N
shares, and HHI `sum((value / theme_sum) ** 2)`. Product and publisher
concentration are calculated only over compatible covered rows; no artificial
Unknown Publisher group is created. Product age uses only `release_date_ww`,
excludes future dates from medians, and reports future-date counts.

Growth decomposition uses the union of current and previous same-theme IDs,
with absent values treated as zero and present-but-NULL values making the
metric decomposition incomplete. Complete rows reconcile product deltas to
`current_sum - previous_sum`; positive and negative gross contributions remain
separate. The growth rate is defined only for a positive previous sum. Missing
previous months leave previous-dependent fields NULL rather than fabricating an
empty market.

The existing AGG-001 replacement remains available. The new replacement method
validates all six derived payloads before one transaction, deletes only the
requested period identities, inserts the six sets atomically, and leaves source,
metadata, and trend-score tables untouched. Readers support deterministic
period/theme filters; dimension readers add type/value filters and
representative readers add evidence-type filters. Four deterministic ZSTD
Parquet exports use explicit columns, stable ordering, temporary sibling files,
and atomic replacement. AGG-002 does not calculate scores, recommendations,
forecasts, category-fit decisions, migration potential, dashboards, or Feishu
outputs.

## TREND-001 schema-v3 trend score storage contract

`theme_trend_scores` stores one row for every raw Game Theme present in each
scorable target month, including non-actionable labels and insufficient-history
rows. Its identity is `(scope_name, cadence, period_start, period_end,
game_theme)`, and `cadence` is always `monthly`. The row retains the six-month
window boundaries, latest observed fields, rolling share-point features,
coverage inputs, component scores, confidence, final score, deterministic rank,
and a sanitized `calculated_at` timestamp.

The analysis layer creates this row from `MonthlyMarketTotal` and
`ThemeMonthlyMetric` only. It zero-fills absent theme months inside the rolling
grid according to [`docs/TREND_SCORE.md`](TREND_SCORE.md), but it never writes a
synthetic schema-v2 metric. Six consecutive month-wide totals are required;
missing source months are not treated as zero.

Actionable rows have non-NULL component scores, `trend_score`, and
`trend_rank`, with a NULL `exclusion_reason`. Non-actionable rows retain the
raw label and explanatory raw features but have NULL component scores, final
score, and rank plus a deterministic exclusion reason. The score and
confidence formulas are project MVP defaults, not Sensor Tower formulas.

Score replacement validates every row before one transaction, deletes only the
requested target-month keys from `theme_trend_scores`, and inserts the complete
replacement. Source tables and both schema-v2 aggregation tables are not
modified. `theme_trend_scores.parquet` is a deterministic archive export with
explicit columns, stable rank ordering, ZSTD compression, and atomic sibling
replacement.

## MODEL-002 schema-v5 evidence storage contract

MODEL-002 consumes the stored monthly totals and matching
`theme_market_structure_metrics` identities. It adds three long-form/evidence
tables: `theme_horizon_metrics`, `theme_model_summaries`, and
`theme_seasonality_profiles`. The pure calculation is prefix-safe: a target
month can use only itself and earlier complete market months. Target themes are
the raw labels present in that target month's AGG-002 structure rows; absent
historical labels are zero-filled, while present-but-NULL metrics remain
unavailable.

`theme_horizon_metrics` stores six approved metric names over 6M, 12M, and 36M
windows. It retains coverage, descriptive statistics, OLS trend evidence,
transition categories, coefficient of variation, drawdown, and latest-peak
distance. Complete-series-only fields remain `NULL` when a metric has missing
observations. `theme_model_summaries` stores the fixed policy version,
available-history and first-active evidence, share-only direction and
stability summaries, provisional lifecycle stage, and absolute Downloads and
Revenue (USD) seasonality summaries. `theme_seasonality_profiles` stores
twelve calendar-month rows only when at least two valid normalized 12-month
blocks exist.

The repository validates all typed rows and identities before one transaction,
checks that summaries exactly match AGG-002 structure identities, replaces
only requested model periods plus 6M-scorable legacy score periods, rereads
counts and identities, and exports deterministic ZSTD Parquet. An export
failure does not invalidate committed DuckDB rows. MODEL-002 is evidence only;
recommendations, forecasts, backtesting, Feishu output, and automation remain
later issue boundaries. See [`MODEL_V2.md`](MODEL_V2.md) for the full model
contract.

## Model overview

```text
market/ranking response + metadata response
                    |
                    v
          App / Theme / Snapshot
                    |
                    v
              DuckDB storage
                    |
                    v
              ThemeMetric
                     |
                     v
          Trend Score and Feishu
```

## App

`App` represents a normalized product identity that can be observed repeatedly.

| Property | Type | Meaning |
| --- | --- | --- |
| `app_id` | Internal identifier | Project-owned canonical key used for internal joins. |
| `source_app_id` | Opaque source identifier text | Source product identifier mapped from the observed `app_id` field. It is required for source-derived records and is never parsed as an integer. |
| `unified_app_id` | Optional opaque source identifier text | Unified product identifier when the source provides one. It is retained as normalized text and may be unavailable. |
| `name` | Text | Normalized display name used in internal reports. |
| `publisher_name` | Optional text | Normalized publisher name when verified source data provides it. |
| `release_date` | Optional date | Chosen release-date concept after the release-date tags are verified. |
| `platform` | Optional internal platform value | Platform represented by the product record when available. |
| `identity_status` | Enum | Confirmed, ambiguous, or unavailable identity resolution. |

Identity resolution should prefer a verified `unified_app_id` when available, otherwise use the source context plus `source_app_id`. The exact cross-platform and cross-source reconciliation rule is still TODO.

## Theme

`Theme` represents a normalized item in the approved Sensor Tower theme taxonomy.

| Property | Type | Meaning |
| --- | --- | --- |
| `theme_id` | Internal identifier | Stable project-owned identifier. |
| `label` | Text | Canonical label used in analysis. |
| `source_label` | Optional text | Source label retained for audit after the adapter has verified its meaning. |
| `taxonomy_version` | Optional text | Approved taxonomy version when available. |
| `status` | Enum | Active, deprecated, or unresolved. |
| `source_verified` | Boolean | Whether the source-to-internal mapping has been verified. |

The source currently verifies the existence of a `Game Theme` custom-tag label, but not the structure, values, cardinality, or taxonomy behavior of that tag. Those details remain TODO.

## Snapshot

`Snapshot` is the time-scoped observation of one product. It is shared by weekly and monthly data; `cadence` distinguishes the observation frequency rather than creating separate model classes.

| Property | Type | Meaning |
| --- | --- | --- |
| `snapshot_id` | Internal identifier | Unique internal observation identifier. |
| `app_id` | Internal identifier | Canonical internal app reference. |
| `source_app_id` | Opaque source identifier text | Source app identifier used to join the market/ranking row with metadata enrichment. |
| `period_start` | Date/time | Start of the normalized observation period. |
| `period_end` | Date/time | End of the normalized observation period. |
| `source_date` | Optional date/time | Source date mapped from the observed top-level `date` field after its meaning is verified. |
| `cadence` | Enum | `weekly` or `monthly`; no separate weekly/monthly model classes. |
| `market_scope` | Internal scope value | Geography and platform scope for the observation. |
| `ranking_metric` | Optional internal descriptor | The ranking basis used by the source request, once verified. |
| `rank_position` | Optional integer | Ranking position in the market result after its semantics are verified. |
| `units_absolute` | Optional numeric value | Retained DuckDB source column. Confirmed business alias: Downloads, count. NULL is unavailable; an observed zero remains zero. |
| `revenue_absolute` | Optional numeric value | Retained DuckDB source column. Confirmed business alias: Revenue (USD). NULL is unavailable; an observed zero remains zero. |
| `theme_ids` | Zero or more internal identifiers | Normalized theme assignments from the verified `Game Theme` source tag. Cardinality and missing behavior remain TODO. |
| `availability` | Structured status | Whether each optional measure is observed, unavailable, or not requested. |

The source market/ranking row and metadata record should be merged into a snapshot through `source_app_id`. The source identity must be retained even when the internal canonical `app_id` is resolved.

## ThemeMetric

`ThemeMetric` is a derived aggregate for one theme, period, and market scope. The initial implementation targets monthly theme aggregation.

| Property | Type | Meaning |
| --- | --- | --- |
| `theme_metric_id` | Internal identifier | Unique aggregate identifier. |
| `theme_id` | Internal identifier | Theme being measured. |
| `period_start` | Date/time | Start of the aggregation period. |
| `period_end` | Date/time | End of the aggregation period. |
| `market_scope` | Internal scope value | Scope inherited from compatible snapshots. |
| `product_count` | Integer | Number of distinct products contributing to the theme aggregate. |
| `units_absolute_sum` | Optional numeric value | Downloads summed over covered products in the selected monthly sample. NULL at zero coverage; observed zero remains zero. |
| `units_absolute_share` | Optional numeric value | Theme Downloads share using the compatible selected monthly sample denominator. |
| `revenue_absolute_sum` | Optional numeric value | Revenue (USD) summed over covered products in the selected monthly sample. NULL at zero coverage; observed zero remains zero. |
| `revenue_absolute_share` | Optional numeric value | Theme Revenue (USD) share using the compatible selected monthly sample denominator. |
| `new_product_count` | Optional integer | Number of products classified as new under a documented comparison rule. |
| `publisher_count` | Optional integer | Number of distinct normalized publishers when publisher identity is available. |
| `concentration` | Optional numeric value | Dependence on a small number of contributing products under an approved calculation. |
| `growth_rate` | Optional numeric value | Period-over-period growth derived from compatible theme metrics. |
| `acceleration_rate` | Optional numeric value | Change in growth rate across compatible periods. |
| `trend_score` | Optional numeric value | Transparent score calculated from validated internal metrics. |
| `confidence` | Structured value | Coverage, comparability, and data-quality assessment for the aggregate. |

There is deliberately no generic `market_volume` field. The model uses the
explicit source-preserving fields `units_absolute_sum`,
`units_absolute_share`, `revenue_absolute_sum`, and
`revenue_absolute_share`; their business aliases are Downloads and Revenue
(USD), so independent availability and coverage remain auditable.

## Relationships and ownership

- One `App` can have many `Snapshot` records.
- One `Snapshot` belongs to one `App` and carries the source identity used for market-to-metadata joining.
- One `Snapshot` references zero or more `Theme` records through `theme_ids` for that observation.
- One `Theme` can be referenced by snapshots across products and periods.
- One `ThemeMetric` aggregates compatible snapshots for one theme, period, and scope.
- Trend Score is derived from `ThemeMetric`; it is not a Sensor Tower source field.
- Feishu receives selected `ThemeMetric` outputs. It is not the source of truth.
- DuckDB is the analytical store. Parquet remains the approved file-oriented boundary required by the project rules.

## External mapping boundary

The intended one-way boundary is:

```text
market/ranking response
  + metadata response
          |
          v
validated adapter mapping
          |
          v
App / Theme / Snapshot
          |
          v
ThemeMetric
          |
          v
Feishu output mapping
```

The external response DTOs and their field names are integration details. Aggregation functions must not accept them directly. Any unresolved identity, theme, metric, or date mapping must be represented as an explicit validation issue or unavailable value.

## DB-002 single-month workflow boundary

The manual `collect-month` workflow introduces a validated `MonthlyPeriod`
boundary before any external request. A `YYYY-MM` value becomes one natural
period with `period_start`, `period_end`, and `cadence: monthly`; current and
future UTC months are rejected. The workflow then joins the selected market
records with fresh or newly fetched normalized metadata before calling the
storage mappers. It does not make the Sensor Tower DTOs, DuckDB rows, or
Parquet files part of CLI parsing, and it does not infer missing metadata or
unverified metric semantics.

## ST-004 live market-contract compatibility

The adapter supports both verified market-response variants: the earlier
sample with numeric IDs, top-level `custom_tags`, and a larger metric field
set; and the current live shape with opaque string IDs,
`entities[0].custom_tags` overlaid by `aggregate_tags`, and only the observed
`units_*`/`revenue_*` absolute and delta fields. These are source-contract
variants, not separate business models.

The neutral identifier boundary accepts positive integers and legacy numeric
strings for compatibility, while preserving any non-empty opaque string after
trimming. It is used consistently by market DTOs, metadata requests and
integrity checks, cache keys, storage rows, Parquet exports, and DB-002 joins.
Identifier values are not hashed, converted to integers, or exposed in public
errors and summaries. Existing DuckDB identifier columns remain `VARCHAR`;
ST-004 does not change the schema version.

All verified source metric fields remain under their actual source names.
`units_absolute` is the confirmed Downloads count and `revenue_absolute` is
the confirmed Revenue (USD) measure. Missing optional fields become
unavailable/SQL `NULL`; neither field is copied into
`current_units_value`/`current_revenue_value`, and those comparison/current
fields retain their own unresolved semantics. No storage or workflow layer
infers unresolved source behavior. A missing verified custom-tag shape still
fails validation rather than silently creating an empty mapping.
