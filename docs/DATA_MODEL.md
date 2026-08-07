# Internal Data Model

This is a conceptual domain model, not a database schema. It defines the internal contract between the two-stage Sensor Tower ingestion flow, DuckDB persistence, analytics, and Feishu output.

Sensor Tower field names must not leak into business logic. The adapter maps source fields into the internal names below and preserves unresolved semantics as explicit unavailable or TODO states.

## Design principles

- The market/ranking response and the metadata enrichment response are separate external inputs.
- The two inputs are joined through source identity before creating a complete internal observation.
- The project-generated `app_id` is a canonical internal key, not the only identity used for reconciliation.
- `source_app_id` is retained for the source product identity. `unified_app_id` is retained when the source makes it available.
- Missing or unavailable data remains explicit. It must not be converted to zero.
- Weekly and monthly observations share one `Snapshot` model and are distinguished by `cadence`.
- `ThemeMetric` is derived data and never replaces the underlying snapshots.

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
| `app_id` | Internal identifier | Project-owned canonical key used for internal joins. It must not be the only identity key. |
| `source_app_id` | Source identifier | Source product identifier mapped from the observed `app_id` field. It is required for source-derived records. |
| `unified_app_id` | Optional source identifier | Unified product identifier when the source provides one. It may be unavailable. |
| `name` | Text | Normalized display name used in internal reports. |
| `publisher_name` | Optional text | Normalized publisher name when verified source data provides it. |
| `release_date` | Optional date | Chosen release-date concept after the release-date tags are verified. |
| `platforms` | Set of internal platform values | Platforms represented by the product record. |
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
| `source_app_id` | Source identifier | Source app identifier used to join the market/ranking row with metadata enrichment. |
| `period_start` | Optional date/time | Start of the normalized observation period. |
| `period_end` | Optional date/time | End of the normalized observation period. |
| `cadence` | Enum | `weekly` or `monthly`; no separate weekly/monthly model classes. |
| `market_scope` | Internal scope value | Geography and platform scope for the observation. |
| `ranking_metric` | Optional internal descriptor | The ranking basis used by the source request, once verified. |
| `rank_position` | Optional integer | Ranking position in the market result after its semantics are verified. |
| `downloads` | Optional numeric value | Normalized download measure. Units and semantics remain TODO until verified. |
| `revenue` | Optional numeric value | Normalized revenue measure. Currency and semantics remain TODO until verified. |
| `theme` | Optional internal theme reference | Normalized theme assignment from the verified `Game Theme` source tag. Cardinality and missing behavior remain TODO. |
| `source_date` | Optional date/time | Source date mapped from the observed top-level `date` field after its meaning is verified. |
| `availability` | Structured status | Whether each optional measure is observed, unavailable, or not requested. |

The source market/ranking row and metadata record should be merged into a snapshot through `source_app_id`. The source identity must be retained even when the internal canonical `app_id` is resolved.

## ThemeMetric

`ThemeMetric` is a derived aggregate for one theme, period, cadence, and market scope. The initial implementation targets monthly theme aggregation.

| Property | Type | Meaning |
| --- | --- | --- |
| `theme_metric_id` | Internal identifier | Unique aggregate identifier. |
| `theme_id` | Internal identifier | Theme being measured. |
| `period_start` / `period_end` | Date/time | Aggregation period. |
| `cadence` | Enum | Aggregation frequency, initially monthly for the MVP. |
| `market_scope` | Internal scope value | Scope inherited from compatible snapshots. |
| `downloads` | Optional numeric value | Sum or other approved aggregate of normalized downloads. Exact aggregation semantics are TODO until the source metric is verified. |
| `download_share` | Optional numeric value | Theme download share within a compatible period and scope. Denominator and semantics are TODO. |
| `revenue` | Optional numeric value | Sum or other approved aggregate of normalized revenue. Currency and aggregation semantics are TODO. |
| `revenue_share` | Optional numeric value | Theme revenue share within a compatible period and scope. Denominator and semantics are TODO. |
| `product_count` | Integer | Number of distinct products contributing to the theme aggregate. |
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
- One `Snapshot` references its normalized `theme` assignment for that observation.
- One `Theme` can be referenced by snapshots across products and periods.
- One `ThemeMetric` aggregates compatible snapshots for one theme, cadence, period, and scope.
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
