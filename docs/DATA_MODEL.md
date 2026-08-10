# Internal Data Model

This is a conceptual domain model, not a database schema. It defines the internal contract between the two-stage Sensor Tower ingestion flow, DuckDB persistence, analytics, and Feishu output.

Sensor Tower field names must not leak into business logic. The adapter maps source fields into the internal names below and preserves unresolved semantics as explicit unavailable or TODO states.

## Design principles

- The market/ranking response and the metadata enrichment response are separate external inputs.
- The two inputs are joined through source identity before creating a complete internal observation.
- `app_id` is a project-owned internal identifier, but it is not the only identity used for reconciliation.
- `source_app_id` is retained for the source product identity. `unified_app_id` is retained when the source makes it available.
- Source and unified identifiers are normalized strings. They may be numeric
  strings for older fixtures or opaque non-numeric strings from the live
  unified endpoint; internal code must not assume an integer ID space.
- Missing or unavailable data remains explicit. It must not be converted to zero.
- Weekly and monthly observations share one `Snapshot` model and are distinguished by `cadence`.
- `ThemeMetric` is derived data and never replaces the underlying snapshots.

## DB-001 persistent storage contract

DuckDB is the local source of truth for normalized analytical records. DB-001
implements two business tables plus the `schema_migrations` control table:

- `app_metadata` is the normalized, persistent metadata cache keyed by
  `unified_app_id`. It stores only returned metadata, keeps unavailable values
  as SQL `NULL`, and records the verified publisher-resolution source.
- `market_snapshots` stores one final selected product per stored market period.
  It retains the verified source metric and tag names, including
  `current_units_value` and `current_revenue_value`; their business semantics
  remain source-contract TODOs and are not renamed to `downloads` or `revenue`.
  Every verified source metric is nullable because the live market response
  may omit the current/comparison and generic fields. Omitted values are
  stored as SQL `NULL`, not zero or a substitute from another source field.

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
collection is deferred to DB-002.

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
| `downloads` | Optional numeric value | Normalized download measure. Units and semantics remain TODO until verified. |
| `revenue` | Optional numeric value | Normalized revenue measure. Currency and semantics remain TODO until verified. |
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
| `downloads` | Optional numeric value | Sum or other approved aggregate of normalized downloads. Exact aggregation semantics are TODO until the source metric is verified. |
| `download_share` | Optional numeric value | Theme download share within a compatible period and scope. Denominator and semantics are TODO. |
| `revenue` | Optional numeric value | Sum or other approved aggregate of normalized revenue. Currency and aggregation semantics are TODO. |
| `revenue_share` | Optional numeric value | Theme revenue share within a compatible period and scope. Denominator and semantics are TODO. |
| `new_product_count` | Optional integer | Number of products classified as new under a documented comparison rule. |
| `publisher_count` | Optional integer | Number of distinct normalized publishers when publisher identity is available. |
| `concentration` | Optional numeric value | Dependence on a small number of contributing products under an approved calculation. |
| `growth_rate` | Optional numeric value | Period-over-period growth derived from compatible theme metrics. |
| `acceleration_rate` | Optional numeric value | Change in growth rate across compatible periods. |
| `trend_score` | Optional numeric value | Transparent score calculated from validated internal metrics. |
| `confidence` | Structured value | Coverage, comparability, and data-quality assessment for the aggregate. |

There is deliberately no generic `market_volume` field. The model uses explicit `downloads`, `download_share`, `revenue`, and `revenue_share` fields so their independent data availability and semantics can be audited.

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
Missing optional fields become unavailable/SQL `NULL`; `units_absolute` is
not copied into `current_units_value`, and `revenue_absolute` is not copied
into `current_revenue_value`. The source metric semantics remain TODO and are
not inferred by the storage or workflow layers. A missing verified custom-tag
shape still fails validation rather than silently creating an empty mapping.
