# FEISHU-003B Idempotent Feishu Trend Synchronization

FEISHU-003B publishes the complete stored `ThemeTrendScore` set for the
configured project scope to the already-provisioned Feishu Bitable table.
DuckDB remains the analytical source of truth. Feishu is a managed dashboard
projection and is never used to calculate, repair, or replace score rows.

## Commands and safety modes

The MVP has no month, start, or end arguments. It always synchronizes every
stored score row where `scope_name` equals `APP_SENSOR_TOWER_SCOPE_NAME` and
`cadence` equals `monthly`.

```powershell
python -m src sync-feishu-trends --plan-only
python -m src sync-feishu-trends
python -m src sync-feishu-trends --apply
```

`--plan-only` is a local contract check. It is routed before `load_config()`
and logging, and does not read YAML, `.env`, credentials, DuckDB, an HTTP
client, the network, or any output file.

The default command is an authenticated dry-run. It reads the authoritative
DuckDB scores, authenticates, validates the complete FEISHU-002 schema, reads
all table-level records, and prints reconciliation counts. It sends no record
write request.

Only `--apply` can send record writes. Apply performs a complete preflight,
writes updates before creates, rereads every record, and rebuilds the plan
from the same immutable source score tuple. An apply with no planned changes
sends no write requests.

Exit-code categories are:

- `0`: successful contract check, dry-run, apply, or no-op apply;
- `2`: local CLI/configuration validation;
- `3`: Feishu authentication, transport, API, or write failure;
- `4`: DuckDB, source-integrity, schema-integrity, managed-record, or final-
  verification failure.

## Authoritative source and source validation

The workflow uses `DuckDBRepository.get_theme_trend_scores()` with exactly the
configured scope and `cadence="monthly"`. It does not construct a Sensor
Tower client and does not modify `theme_trend_scores`, market snapshots,
aggregates, or any Parquet file.

The complete returned set is required to be non-empty, contain only
`ThemeTrendScore` values, use one scope, use monthly cadence, and have unique
source identities:

```text
(scope_name, cadence, period_start, period_end, game_theme)
```

Rows retain the repository's deterministic source order while reconciliation
actions are sorted by this same identity for response-order-independent plans.
The latest month is the maximum `period_start` in the complete set. Every row
in that month receives `是否最新月份 = true`; all older rows receive
`是否最新月份 = false`.

## Technical managed key

The existing primary Text field `文本` is the technical key. The exact
versioned algorithm is:

```python
canonical_identity = "\x1f".join(
    (
        score.scope_name,
        score.cadence,
        score.period_start.isoformat(),
        score.period_end.isoformat(),
        score.game_theme,
    )
)
digest = sha256(canonical_identity.encode("utf-8")).hexdigest()
managed_key = f"ctta:v1:{score.period_start.strftime('%Y-%m')}:{digest}"
```

The digest is the full lowercase 64-character SHA-256 hexadecimal digest.
The accepted format is:

```text
^ctta:v1:[0-9]{4}-[0-9]{2}:[0-9a-f]{64}$
```

The delimiter and UTF-8 encoding make the key deterministic and safe for
Unicode, separators, slashes, spaces, and newlines in source values. Keys are
never printed in normal output or public synchronization errors.

## Exact 22-field mapping

The primary field is always included in a create payload. The following 21
non-primary fields are written in the FEISHU-002 schema order:

| Feishu field | Source value |
| --- | --- |
| `月份` | `period_start`, first natural-month day at UTC midnight |
| `题材` | `game_theme` |
| `是否最新月份` | `period_start == max(period_start)` |
| `是否可行动` | `is_actionable` |
| `排除原因` | `exclusion_reason` |
| `趋势排名` | `trend_rank` |
| `趋势分` | `trend_score` |
| `置信度` | `confidence_score` |
| `增长分` | `growth_score` |
| `加速度分` | `acceleration_score` |
| `新产品分` | `new_product_score` |
| `集中度惩罚` | `concentration_penalty` |
| `最新产品数` | `latest_product_count` |
| `最新产品份额` | `latest_product_share` |
| `units_absolute份额` | `latest_units_absolute_share` |
| `revenue_absolute份额` | `latest_revenue_absolute_share` |
| `近3月新进入占比` | `recent3_new_entry_share` |
| `排名改善` | `median_rank_improvement` |
| `units_absolute超配倍数` | `units_absolute_overindex` |
| `revenue_absolute超配倍数` | `revenue_absolute_overindex` |
| `计算时间` | timezone-aware `calculated_at` |

`units_absolute` and `revenue_absolute` retain their exact source names. No
display rounding is applied before writing. Dates are integer Unix epoch
milliseconds. `calculated_at` is converted to UTC and truncated to integer
milliseconds.

`None` becomes an empty Feishu cell. Create payloads omit optional `None`
fields; update payloads send JSON `null` when an existing value must be
cleared. Numeric zero remains numeric `0`, and boolean `False` remains
boolean `false`. Numeric comparison accepts int/float representation changes
within the documented `1e-9` finite tolerance.

## Existing-record classification

The sync reader uses the table-level `GET /records` endpoint with
`page_size=100`. It sends no `view_id`, filter, sort, search, or view write
operation. It preserves the existing pagination and duplicate-record-ID
integrity checks.

Every table record is classified from the primary field:

| Category | Behavior |
| --- | --- |
| managed | A valid technical key; eligible for matching and update |
| unmanaged blank | Preserved, ignored, and never updated or deleted |
| unmanaged nonblank | Preserved, ignored, and never updated or deleted |
| duplicate managed key | Fatal before any write; only a count is reported |
| stale managed | A valid key absent from the complete source set; visible in dry-run and fatal for apply |

The five existing blank records are therefore counted as
`unmanaged_blank_record_count`, do not consume source matches, and are never
reused for creates. Creates always use `batch_create` and add new records.
There is no delete or stale-record cleanup policy in this MVP.

For managed records, the reader accepts a direct Text string or an array of
plain objects containing string `text` values. It normalizes managed text,
finite numbers, booleans, and integer date values. An unsupported managed
cell shape fails before apply writes. Unmanaged records are not required to
have valid unrelated cells.

## Reconciliation and writes

The pure reconciliation plan reports source score/month counts, current and
managed record counts, unmanaged counts, duplicate/stale counts, and
create/update/unchanged counts. It does not expose themes, keys, IDs, cell
values, payloads, or complete tokens.

Only these record endpoints are implemented:

```text
POST /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create
POST /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update
```

The internal default batch size is `100`; any configured/internal value must
be between `1` and `1000`. Requests are sequential, with no concurrency, no
`ignore_consistency_check`, no `view_id`, no single-record writes, and no
delete/search calls. A `0.5` second delay is used only between successful write
requests and never after the final request.

Every write response must be a 2xx JSON mapping with integer `code=0`, a data
mapping, a records list of exactly the requested length, and unique non-empty
record IDs. IDs are validated and then discarded from the public result.

If a transport timeout or malformed response occurs after Feishu may have
completed a batch, the client does not repeat that payload. A later run
rereads the complete table and safely continues from a new plan. Earlier
successful batches are not rolled back. A partial synchronization is reported
as a sanitized typed error.

After writes, the workflow rereads every record and rebuilds the plan from the
same source rows. Apply succeeds only when duplicate and stale counts are
zero, create and update counts are zero, and managed-record count equals the
source score count.

## Manual ranked-view steps

View APIs are deliberately not implemented. After a successful synchronization:

1. Open the configured Feishu Bitable table.
2. Use the existing grid view.
3. Filter `是否最新月份` = checked.
4. Filter `是否可行动` = checked.
5. Sort `趋势排名` ascending.
6. Keep `月份`, `题材`, `趋势排名`, `趋势分`, `置信度`,
   `增长分`, `加速度分`, `新产品分`, and `集中度惩罚`
   visible.
7. Preserve the technical primary field and all quality-status fields.

## Evidence status and limitations

Code-verified behavior includes source validation, exact key/mapping logic,
payload omission/null/zero rules, deterministic reconciliation, pagination
boundaries, endpoint allow-list, batch response validation, pacing, and
sanitized formatting.

Mock-verified behavior uses synthetic DuckDB rows, temporary DuckDB files, and
`httpx.MockTransport`. It covers plan-only isolation, five blank records,
unmanaged records, idempotent create/rerun, update-only reconciliation,
stale/duplicate failures, batch pacing, and final reread verification. No
automated test calls real Feishu.

Real-environment behavior remains an acceptance step. The development run for
FEISHU-003B makes no real Feishu request or write and makes no Sensor Tower
request. Real acceptance must use a separately approved configured table and
follow the sequence below. This MVP does not schedule synchronization, create
views, merge theme taxonomies, calculate scores, delete stale rows, or turn
Feishu into a source of truth.

## Real acceptance sequence

1. Confirm the configured DuckDB contains the complete intended monthly score
   set and that the target table has the FEISHU-002 schema.
2. Run `inspect-feishu-records` and confirm the table-level read is healthy.
3. Run `sync-feishu-trends` without `--apply` and review counts, especially
   unmanaged blank/nonblank, duplicate, stale, create, and update counts.
4. Confirm the five blank rows remain preserved and that no stale managed row
   requires an explicit data decision.
5. Run `sync-feishu-trends --apply` only after the dry-run is approved.
6. Confirm the sanitized final verification summary and use the manual ranked
   view steps above.
7. Rerun the dry-run and confirm `create_count=0` and `update_count=0`.
