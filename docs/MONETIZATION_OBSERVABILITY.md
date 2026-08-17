# MONETIZATION-001 Monetization Proxy Observability

MONETIZATION-001 is a descriptive evidence layer for the stored monthly
market sample. It reads the verified Sensor Tower Custom Fields already
returned by the existing market response, classifies a transparent product
proxy, and aggregates theme-level Downloads-weighted evidence. It does not
create a score, recommendation, dashboard, Feishu view, automation, or
historical backtest feature.

## Business boundary

The existing source fields retain their database names:

- `units_absolute` is Downloads count.
- `revenue_absolute` is third-party-platform observable Revenue (USD).

Observable Revenue is not total monetization coverage. In particular, a
third-party platform may not observe in-app advertising revenue. Therefore a
zero observable-Revenue value is an observed zero, not proof that total
revenue is zero, and 100% observable-Revenue coverage is not proof that total
monetization is fully covered. MONETIZATION-001 never estimates IAA revenue,
ARPDAU, RPD, LTV, ROAS, CPI, or profitability.

Game Product Model is retained as auxiliary source evidence. It is not a
monetization-classification input, so values such as `Hypercasual`, `Casual`,
or `Hybridcasual` are never directly mapped to IAA, IAP, or Hybrid.

## Verified Custom Fields

The contract uses exactly these eleven source keys:

Advertising evidence:

- `Monetization: Ads`

Contextual fields, excluded from the meaningful-IAP count:

- `Monetization: Ad Removal`
- `In-App Purchases`
- `Monetization: Live Ops`

Meaningful IAP mechanisms:

- `Game IQ - IAP Bundles`
- `Monetization: Currency Bundles`
- `Monetization: Season Pass`
- `Monetization: Starter Pack`
- `Monetization: Subscription`
- `In-App Subscription`
- `Monetization: Loot Box`

Each source value is normalized strictly to `true`, `false`, `unknown`, or
`invalid`. Exact Boolean values and trimmed, case-folded strings `true` and
`false` are recognized. Missing keys and `None` become `unknown`; integers,
yes/no strings, lists, dictionaries, and other values become `invalid`.
Missing does not mean false.

## Product proxy policy

The persisted policy version is `MONETIZATION001_V1`.

For a matched source record, rules are applied in this order:

1. An invalid Ads state or invalid meaningful-IAP state produces
   `unknown` / `invalid_classification_signal`.
2. Ads `true` with no meaningful IAP mechanism produces
   `ads_dominant_candidate` / `low`.
3. Ads `true` with at least one meaningful IAP mechanism produces
   `hybrid_candidate` / `partial`.
4. Ads `false` with at least one meaningful IAP mechanism produces
   `iap_dominant_candidate` / `higher`.
5. Ads `false` with no meaningful IAP mechanism produces `unknown`.
6. Ads `unknown` produces `unknown`; an otherwise inconclusive state remains
   `unknown`.

An unmatched stored product is always `unknown`, with all states `unknown`,
empty canonical audit JSON `{}`, and reason `source_record_unmatched`.

Each product profile stores the exact approved source keys that were present
in `verified_source_tags_json`, using canonical UTF-8 JSON with sorted keys
and compact separators. Source string capitalization is preserved. Unsupported
values are represented safely; arbitrary object internals, credentials, and
URLs are not serialized. The CLI and logs never print this JSON or raw values.

## Theme observability

The stored `market_snapshots` population is authoritative. There is exactly
one profile per stored product and one theme metric per non-NULL raw
`game_theme`; empty strings, `Unknown`, and `N/A` remain distinct labels.

Theme metrics expose product-count proxy shares, Downloads-weighted proxy
shares, and observable-Revenue composition shares. Downloads is the primary
theme-level dominance evidence; product count and observable Revenue remain
supporting evidence. Numeric zero remains zero, SQL `NULL` remains unavailable,
and a missing or non-positive denominator produces a `NULL` share. No values
are rounded and infinity is never emitted.

The provisional applicability constants are:

- `MONETIZATION_MIN_SOURCE_MATCH_RATIO = 0.80`
- `MONETIZATION_PROXY_DOMINANCE_SHARE = 0.50`
- `MONETIZATION_UNKNOWN_SHARE_THRESHOLD = 0.50`

They are descriptive thresholds, not investment weights or backtested decision
thresholds. Applicability is evaluated in this order:

1. Match ratio below 0.80: `unknown`,
   `insufficient_source_match_coverage`.
2. No positive Downloads denominator: `unknown`,
   `no_positive_downloads_denominator`.
3. Unknown proxy Downloads share at least 0.50: `unknown`,
   `unknown_proxy_dominates_downloads`.
4. Ads-candidate Downloads share at least 0.50: `low`,
   `ads_dominant_downloads`.
5. IAP-candidate Downloads share at least 0.50: `higher`,
   `iap_dominant_downloads`.
6. Otherwise: `partial`, `mixed_or_hybrid_downloads`.

## Storage and workflows

Schema version 7 adds exactly these tables without changing existing tables or
columns:

- `app_monetization_profiles`
- `theme_monetization_observability_metrics`

`replace_monetization_period(...)` atomically replaces the two output tables
for one exact stored market period. The collection bundle method atomically
replaces `market_snapshots` plus both output tables. Typed validation, identity
checks, product/theme reconciliation, and internal readback occur before
commit; failures roll back the transaction. DuckDB remains authoritative.

The dedicated latest-month command is:

```powershell
python -m src collect-monetization --month 2026-07 --plan-only
python -m src collect-monetization --month 2026-07
python -m src collect-monetization --month 2026-07 --skip-export
```

Plan-only runs before configuration and logging, validates a completed natural
month, and performs no credential, network, database, directory, or file
operation. Real execution accepts only the latest stored completed month,
calls the existing market endpoint once, reuses existing local selection,
does not call metadata or Feishu, keeps the stored population authoritative,
and counts unmatched/extra fetched products in its sanitized summary.

The two deterministic atomic ZSTD exports are:

- `app_monetization_profiles.parquet`
- `theme_monetization_observability_metrics.parquet`

Future `collect-month` runs reuse their already selected market response and
do not make a second market request. Historical `backfill-months` explicitly
does not build monetization rows.

## Historical-versioning limitation

The current response proves that these Custom Fields are present in the market
response, but it does not prove that their values are historically versioned as
of an arbitrary requested month. MONETIZATION-001 therefore does not perform a
36-month monetization backfill, reinterpret historical Custom Fields, or
re-stratify BACKTEST-001. The first real run observes only the latest stored
completed market month; later monthly runs may accumulate prospective
observations. No historical Revenue result is claimed to be controlled for
monetization mix.

Development and automated tests use synthetic responses, fake or mock clients,
temporary DuckDB files, and temporary Parquet files only. No real Sensor Tower
or Feishu request and no real user DuckDB or Parquet file is part of the
development workflow.
