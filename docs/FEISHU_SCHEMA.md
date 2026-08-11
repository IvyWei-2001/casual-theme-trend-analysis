# FEISHU-002 Feishu trend-score schema

FEISHU-002 provisions the configured Feishu Bitable table schema needed for
the future monthly Trend Score view. DuckDB remains the analytical source of
truth. This issue creates fields only; it does not create, update, delete, or
list Bitable records.

## Verified starting state

The inspected destination starts with one primary Text field named `文本`.
The command identifies that field from the live response's
`is_primary = true` value. Its field ID is intentionally not hard-coded. The
primary field is preserved, never renamed, updated, or deleted, and is
reserved as the future unique record key.

FEISHU-002 creates 21 non-primary fields in the order below. Existing
unrelated fields are retained and ignored.

| # | Field name | Logical type | Display/property |
| ---: | --- | --- | --- |
| 1 | 月份 | date | `yyyy/MM/dd`; later synchronization stores the first calendar day |
| 2 | 题材 | text | plain text |
| 3 | 是否最新月份 | checkbox | checkbox |
| 4 | 是否可行动 | checkbox | checkbox |
| 5 | 排除原因 | text | plain text |
| 6 | 趋势排名 | number | integer formatter `0` |
| 7 | 趋势分 | number | two-decimal formatter `0.00` |
| 8 | 置信度 | number | two-decimal formatter `0.00` |
| 9 | 增长分 | number | two-decimal formatter `0.00` |
| 10 | 加速度分 | number | two-decimal formatter `0.00` |
| 11 | 新产品分 | number | two-decimal formatter `0.00` |
| 12 | 集中度惩罚 | number | two-decimal formatter `0.00` |
| 13 | 最新产品数 | number | integer formatter `0` |
| 14 | 最新产品份额 | number | percentage formatter `0.00%` |
| 15 | units_absolute份额 | number | percentage formatter `0.00%` |
| 16 | revenue_absolute份额 | number | percentage formatter `0.00%` |
| 17 | 近3月新进入占比 | number | percentage formatter `0.00%` |
| 18 | 排名改善 | number | two-decimal formatter `0.00` |
| 19 | units_absolute超配倍数 | number | two-decimal formatter `0.00` |
| 20 | revenue_absolute超配倍数 | number | two-decimal formatter `0.00` |
| 21 | 计算时间 | date-time | `yyyy-MM-dd HH:mm`, including time |

`units_absolute` and `revenue_absolute` remain the exact source terms. They
are not relabeled as downloads or revenue. Percentage values are stored later
as decimal ratios: a value such as `0.018` displays as `1.80%`.

## Verified Feishu field contract

The implementation uses the official Bitable field endpoint:

```text
POST /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields
```

The verified API types are text `1`, number `2`, date `5`, and checkbox `7`.
Plain text, plain number, date, and checkbox fields omit `ui_type` because it
is not required for these shapes. Number properties use the documented
`formatter` values. Date properties use the documented `date_formatter` and
explicitly set `auto_fill` to `false`.

The current official date formatter list does not include a year-month-only
format such as `YYYY-MM`, so `月份` uses the supported `yyyy/MM/dd` formatter.
The first calendar day is stored later to represent a target month. The audit
field uses the supported `yyyy-MM-dd HH:mm` formatter.

## Commands

Validate and print the local schema without credentials, network access,
DuckDB access, or file writes:

```powershell
python -m src provision-feishu-schema --plan-only
```

The default command is a live dry-run. It authenticates, reads the current
field list, reports compatible, missing, and incompatible desired fields, and
creates nothing:

```powershell
python -m src provision-feishu-schema
```

Field creation requires explicit `--apply`:

```powershell
python -m src provision-feishu-schema --apply
```

Apply performs a complete preflight comparison before the first create, then
creates missing fields sequentially, rereads the complete field list, and
verifies every desired field. It never updates or deletes an existing field.
The command rejects `--plan-only --apply`.

## Safety and reruns

- Matching uses exact field names, not response order.
- A wrong type, UI type, numeric formatter, or date formatter is reported and
  stops apply before any create.
- Duplicate existing names among desired fields, missing primary fields, and
  multiple primary fields are integrity failures.
- A named default delay is used only between successful create calls; tests
  inject the sleeper.
- A later create failure does not roll back already-created fields. The next
  run rereads the live schema and creates only the remaining missing fields.
- Results expose only sanitized metadata, including an app-token suffix; they
  never expose secrets, authenticated URLs, request bodies, or raw responses.
- Authentication uses POST, inspection uses GET, and apply's additional POSTs
  target only the field collection. No record endpoint or PUT, PATCH, or
  DELETE request is implemented.

Trend-record synchronization, the future use of the preserved primary field
as the idempotent record key, and dashboard configuration remain deferred to
FEISHU-003.
