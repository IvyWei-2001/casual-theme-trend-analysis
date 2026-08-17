# MONETIZATION-001 Observable-Revenue Proxy Observability

MONETIZATION-001 is a deliberately simple, offline evidence layer derived
only from stored `market_snapshots` rows. It is not an observed monetization
type. The policy covers every requested stored completed month; for the
accepted history, `--start 2023-08 --end 2026-07` covers 36 months.

## Business boundary

`revenue_absolute` means only third-party-platform observable Revenue (USD).
It does not include complete IAA advertising revenue and must never be
described as actual total revenue. The proxy does not estimate IAA revenue.

The exact product mapping is:

| `revenue_absolute` | `observable_revenue_state` | `monetization_proxy` | `classification_reason` |
| --- | --- | --- | --- |
| `NULL` | `unavailable` | `unknown` | `observable_revenue_unavailable` |
| `0` | `zero` | `iaa_candidate` | `observable_revenue_zero` |
| `> 0` | `positive` | `iap_or_hybrid_candidate` | `observable_revenue_positive` |

Business-facing meanings are fixed:

- `iaa_candidate`: IAA candidate (observable Revenue = 0)
- `iap_or_hybrid_candidate`: IAP or Hybrid candidate (observable Revenue > 0)
- `unknown`: Unknown (observable Revenue unavailable)

`iaa_candidate` is never confirmed or pure IAA. Observable Revenue = 0 does
not prove actual total revenue = 0 or pure IAA. Observable Revenue > 0 does
not distinguish pure IAP from Hybrid. Observable-Revenue coverage is not total
commercial-revenue coverage. No field estimates IAA advertising revenue.

Negative, NaN, and infinite observable-Revenue values are invalid and fail
before DuckDB writes or Parquet exports. An observed numeric zero remains zero;
an unavailable value remains SQL `NULL`.

Game Product Model is retained only as raw context. It does not determine the
proxy. Historical Sensor Tower Custom Fields are not used. The derived CSV
column `变现模式`, weekly CSVs, raw JSON files, Ads, Ad Removal, IAP, Live Ops,
or any other unavailable Custom Field are outside this implementation.

## App-level storage

The active schema is version 8 and retains the table name
`app_monetization_profiles`. Each stored market snapshot produces exactly one
profile, including a NULL observable Revenue or NULL raw Game Theme. The
active profile columns are:

- scope, cadence, period boundaries, source app ID, and unified app ID;
- raw Game Theme and raw Game Product Model context;
- `monetization_policy_version = MONETIZATION001_OBSERVABLE_REVENUE_PROXY_V1`;
- nullable `observable_revenue_usd`;
- `observable_revenue_state`, `monetization_proxy`, and
  `classification_reason`; and
- deterministic `calculated_at`.

The active schema contains no Custom-Field audit, Ads state, IAP mechanism
state, source-record-match state, or superseded proxy columns.

## Theme-level storage

The active table remains `theme_monetization_observability_metrics`. It has
one row for every non-NULL raw Game Theme in each requested month. NULL themes
have no theme row. Empty strings, `Unknown`, and `N/A` remain distinct raw
labels.

Each row stores product count, observable-Revenue coverage count/ratio/sum,
the three proxy product counts/shares, Downloads coverage count/ratio/sum,
Downloads sums/shares by the three proxy classes, scope/month identity, the
policy version, and `calculated_at`. It does not store class-level
observable-Revenue shares because those would be tautological under this
Revenue-defined classifier.

Downloads means stored `units_absolute`. Downloads weighting is descriptive
evidence only; it does not estimate advertising revenue. Product counts
reconcile exactly:

```text
iaa_candidate_product_count
+ iap_or_hybrid_candidate_product_count
+ unknown_product_count
= product_count
```

Numeric zero is retained as zero. A zero or unavailable denominator produces a
NULL share. A zero coverage count produces a NULL sum; a covered observed
numeric zero produces a numeric zero sum. The derived theme identities are
validated against the existing non-NULL-theme monthly aggregation and model
summary populations when those populations are present; the identity count is
calculated from the database, never hard-coded.

## Offline range workflow

The command reads only stored market snapshots. It makes zero Sensor Tower,
metadata, Feishu, or other network requests and does not require a Sensor Tower
token, Custom Field response, raw JSON file, weekly CSV, or Game Product Model
classification.

```powershell
python -m src derive-monetization --start 2023-08 --end 2026-07 --plan-only
python -m src derive-monetization --start 2023-08 --end 2026-07 --skip-export
python -m src derive-monetization --start 2023-08 --end 2026-07
```

The range is inclusive and processed oldest to newest. Every requested month
must have a non-empty stored monthly market period; missing months fail rather
than being skipped. The complete range is validated before one atomic
replacement of only the two monetization output tables for the requested
periods. Existing market, aggregation, MODEL-002, and BACKTEST-001 rows are
not modified. Both deterministic ZSTD Parquet files are exported once after
successful persistence unless `--skip-export` is supplied. Calculation or
persistence failure performs no export.

`--plan-only` runs before configuration loading and logging. It validates the
completed-month range only and does not access YAML, `.env`, credentials,
DuckDB, network, or local output files.

The superseded `collect-monetization` command is removed; no Sensor Tower
request is required for monetization derivation. Future `collect-month`
integration reuses the selected market snapshot rows already available to that
workflow. It makes no second market request, Custom Fields request, metadata
request specifically for monetization, or historical recalculation.

## Schema migration

Schema version 8 preserves all schema-v1 through schema-v6 tables and rows. A
normal upgrade from schema v6 creates the interim v7 tables transactionally,
then replaces only those empty interim monetization tables with the v8 schema.
An existing interim v7 database is supported only when both legacy
monetization tables are empty. If either contains rows, migration fails before
dropping or overwriting anything; legacy Custom-Field rows are never
reinterpreted as observable-Revenue rows. Read-only schema verification
understands the final v8 contract.

## Validation boundary

Automated validation uses synthetic typed rows, mocks, temporary DuckDB, and
temporary Parquet only. It does not access the real Sensor Tower API, the
production DuckDB, its verified backup, real exports, or Feishu. Real-
environment acceptance is a separate step and is not part of implementation.
