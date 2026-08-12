# Historical Data Quality Inspection

HIST-002 adds a read-only inspection step for the V2 production-history
minimum: 36 consecutive completed natural months. The first intended range is
`2023-08` through `2026-07`.

The inspected population is the WW Puzzle/Tabletop selected Top-N sample (cap
1000), not the complete global mobile-games market. A month may validly contain
fewer than 1000 products; `snapshot_count` always reports its actual stored
population.

## Safe acceptance sequence

First validate the range without configuration, credentials, DuckDB, network,
or file writes:

```powershell
python -m src inspect-history --start 2023-08 --end 2026-07 --plan-only
```

Inventory the existing store without changing it:

```powershell
python -m src inspect-history --start 2023-08 --end 2026-07
```

Use the existing resumable workflow to collect only missing months. Do not use
`--refresh-existing` for the initial extension:

```powershell
python -m src backfill-months --start 2023-08 --end 2026-07
```

After a successful backfill, require structural completeness in a second
read-only inspection:

```powershell
python -m src inspect-history --start 2023-08 --end 2026-07 --require-complete
```

Backfill remains oldest-to-newest, stops at its first failed month, preserves
earlier committed months, skips already-present non-empty periods on rerun,
and exports only once at the end. HIST-002 does not call aggregation, scoring,
Feishu, dashboards, or automation.

## Inspection evidence

The default inspection returns zero after it reports missing or structurally
invalid history; this permits safe pre-backfill inventory. `--require-complete`
returns four after the same full report unless every expected month is present,
has no structural issue, and all present months use one compatible request
provenance tuple.

Each present month reports aggregate-only evidence: actual snapshot count,
configured cap, duplicate IDs and ranks, rank continuity, provenance variants,
Downloads and Revenue (USD) coverage/counts/sums, six Sensor Tower Custom
Field coverage measures, and current metadata and release-date coverage. It
also reports the count of rows whose stored country, device type, category, or
data model differs from the configured request contract. It never prints
product identifiers, names, publishers, field values, URLs, tokens, or raw
rows.

Structural failure includes an over-cap or empty present period, duplicate IDs
or ranks, non-contiguous ranks, mixed provenance, wrong stored identity/scope/
cadence, negative Downloads or Revenue (USD), disallowed Game Genre, or a
stored China-revenue-market exclusion when that option is enabled. There is no
invented coverage threshold in HIST-002.

Game Genre comparison uses the same `strip().casefold()` normalization as the
production selection boundary. The raw stored value is preserved; missing or
unrelated genres remain structural issues.

`units_absolute` is Downloads (count), and `revenue_absolute` is Revenue
(USD). NULL means unavailable, while observed zero remains zero. A metric with
zero covered values has a NULL sum; covered zeros produce a numeric zero sum.

Metadata is a current, non-versioned cache. Metadata, name, and publisher
coverage therefore describe current cache availability for a historical
month—not a historically versioned publisher identity.

The repository tracks read-write and read-only connection modes explicitly.
Reusing an open repository with the opposite mode is rejected; closing resets
the mode so a later open can choose either mode.
