# Sensor Tower API Mapping

This document records the verified boundary between the existing Google Sheets / Apps Script workflow, Sensor Tower response samples, and the internal data model. It does not invent an endpoint URL, request method, parameter, or response semantic that is not visible in the available evidence.

Sensor Tower remains the only approved market-data source. Business logic must consume internal models rather than Sensor Tower field names.

## Evidence boundary

### Verified

- The existing Apps Script reads the Sensor Tower API URL and auth token from a `Config` sheet.
- The weekly market request builds this custom field filter:

  ```json
  {
    "custom_fields": [
      {
        "name": "Game Genre",
        "values": ["Puzzle", "Tabletop"],
        "global": true,
        "exclude": false
      }
    ]
  }
  ```

- The request appends `custom_fields_filter_id=<encoded JSON>` to the configured API URL.
- The Apps Script fetches market data first, filters the result locally to 1000 rows, extracts `app_id` values, and fetches metadata separately.
- The existing workflow therefore distinguishes market/ranking data from metadata enrichment.
- The verified metadata enrichment request uses `GET /v1/unified/apps` at the
  verified base URL and sends the unified app IDs selected after local market
  filtering.
- Real Sensor Tower response samples show the following top-level field names:

  ```text
  app_id
  country
  date
  current_units_value
  units_absolute
  comparison_units_value
  units_delta
  units_transformed_delta
  current_revenue_value
  revenue_absolute
  comparison_revenue_value
  revenue_delta
  revenue_transformed_delta
  custom_tags
  ```

- Real response samples show these custom-tag labels under `custom_tags`:

  ```text
  Game Theme
  Game Genre
  Game Sub-genre
  Game Product Model
  Game Art Style
  Game Setting
  Earliest Release Date
  Release Date (WW)
  Publisher Country
  Is Unified
  ```

- In the provided sample, `custom_tags` is observed as a key/value object.
- `Game Theme` is observed as a key under `custom_tags`.
- The `Game Theme` values observed in the sample are strings.
- Example observed `Game Theme` values are `Decoration`, `Candy / Dessert`, `Hypercasual`, `Fashion / Aesthetics / Hair`, `Abstract`, `Tabletop`, and `Vehicles - Car`.
- These examples are sample observations only; no taxonomy rule, hierarchy, or completeness is inferred from them.
- Field existence is verified for every top-level field and custom-tag label listed above. Existence alone does not establish business semantics.

### ST-004 live market-response compatibility

The earlier sample and the current live endpoint are both verified input
variants. The adapter supports their union without renaming or synthesizing
source fields.

The sanitized live diagnostic verified an HTTP 200 JSON array whose row
objects contain these top-level keys:

```text
aggregate_tags
app_id
country
date
entities
units_absolute
units_delta
units_transformed_delta
revenue_absolute
revenue_delta
revenue_transformed_delta
```

The live diagnostic did not contain
`current_units_value`, `comparison_units_value`, `current_revenue_value`,
`comparison_revenue_value`, `absolute`, `delta`, or `transformed_delta`.
These fields remain supported for the earlier sample, but are optional in the
normalized market DTO. When omitted, they remain unavailable and are stored as
SQL `NULL`; no zero or cross-field substitution is applied. In particular,
`units_absolute` is not copied into `current_units_value`, and
`revenue_absolute` is not copied into `current_revenue_value`.

The live `app_id` is a non-numeric opaque string identifier. It is normalized
only by trimming surrounding whitespace; it is never parsed as an integer,
hashed, or replaced with a project-generated ID. Positive integer fixtures and
numeric strings remain supported for compatibility and are represented as
decimal strings after normalization. The same opaque-ID boundary is used for
metadata requests, response integrity checks, cache keys, DuckDB rows, and
DB-002 joins.

The live custom-tag shape is also verified: `entities[0].custom_tags` is
copied and `aggregate_tags` is overlaid, with aggregate values winning on
duplicate keys. A top-level `custom_tags` mapping remains supported for the
earlier sample. If neither verified shape is present, parsing fails instead of
creating an empty mapping. The repository fixture for the live structure is
synthetic and is based only on this sanitized field structure; it is not a
captured response.

### Still TODO

- Before ST-002, the actual endpoint URL, method, and auth transport were
  unresolved. ST-002 records the verified market-request boundary below; the
  response error contract remains represented only by sanitized local errors.
- The response-sample provenance is not sufficient to assign every observed field to the market request or the separate metadata request; field existence remains verified.
- Whether all `custom_tags` entries follow the same key/value structure and value-type rules beyond the provided sample is still TODO.
- The exact semantics, units, currency, period, and transformations of the observed metric fields are still TODO.

## Top1000 endpoint

### Verified

- The verified base URL is `https://api.sensortower.com` and the verified
  endpoint path is `/v1/unified/sales_report_estimates_comparison_attributes`.
- The request method is `GET`; the auth token is supplied as the verified
  `auth_token` query parameter through local configuration.
- The approved project scope is category `7012`, country `WW`,
  `device_type=total`, and Game Genre `Puzzle` or `Tabletop` through the
  unified endpoint. This is a project rule, not a claim about Sensor Tower's
  universal Casual definition.
- The verified query parameters are `comparison_attribute=absolute`,
  `time_range=day`, `measure=units`, `device_type=total`, `category=7012`,
  `country=WW`, `date`, `end_date`, `limit=1200`,
  `custom_tags_mode=include_unified_apps`, `data_model=DM_2025_Q2`,
  `auth_token`, and compact JSON in `custom_fields_filter_id`.
- The custom-field filter is `Game Genre` with values `Puzzle` and `Tabletop`,
  `global: true`, and `exclude: false`.
- These verified request-boundary values are visible through `AppConfig`, YAML,
  and the matching `APP_` environment variables. The current MVP supports only
  `filter_field_name="Game Genre"`, `filter_global=true`,
  `filter_exclude=false`, and allowed genres `Puzzle` and `Tabletop`;
  unsupported filter-scope changes fail configuration validation rather than
  producing a request whose semantics disagree with local selection.
- The endpoint path is carried by both the request and client configuration;
  mismatched paths fail with a typed configuration error before network access.
- `limit=1200` is an over-fetch candidate limit. The local `final_top_n=1000`
  is applied only after eligibility filtering; it is never sent to the API.
- Local eligibility preserves source order, performs case-insensitive Game
  Genre matching, skips missing or disallowed genres, and optionally excludes
  records whose `Most Popular Country by Revenue` is `China`.
- The parser supports the two verified tag shapes: top-level `custom_tags`, or
  `entities[0].custom_tags` overlaid by `aggregate_tags`; unknown source fields
  remain as DTO extras.
- The workflow extracts source `app_id` values from the final market result
  before the separate metadata request. Metadata enrichment is deferred to
  ST-003 and is not implemented in ST-002.
- The observed response field names listed in the Evidence boundary section are verified to exist in real samples. Their business semantics are not thereby verified.

### Still TODO

- Pagination behavior and the response fields used to determine additional pages.
- A formal Sensor Tower sorting guarantee. ST-002 currently preserves source
  response order and does not re-sort records.
- The exact association between observed response fields and the market or metadata response.
- Whether `country` is an input scope, a returned dimension, or both.
- Whether `date` is an observation date, period marker, or another date concept.

The verified market endpoint above is limited to the ST-002 candidate boundary;
historical endpoint semantics remain TODO. The metadata contract is recorded
below and implemented as a separate ST-003 adapter.

## Unified app metadata endpoint

### Verified

- The verified base URL is `https://api.sensortower.com` and the metadata
  endpoint path is `/v1/unified/apps`.
- The request method is `GET`. The verified query parameters are exactly
  `app_id_type=unified`, `app_ids` as a comma-separated list of unified app
  IDs, `fields` as a comma-separated list, and `auth_token`.
- The verified requested fields, in order, are:

  ```text
  name
  publisher
  android_publisher_ids
  itunes_publisher_ids
  android_apps
  itunes_apps
  unified_app_id
  ```

- The verified response envelope is an object with an `apps` array. Each
  metadata app requires `unified_app_id`; `name`, `publisher`, publisher-ID
  arrays, and Android/iTunes app-reference arrays are optional. Unknown source
  fields are tolerated and are not retained in normalized internal metadata.
- `unified_app_id` accepts positive integer values, numeric strings that can
  be safely normalized to decimal strings, and non-empty opaque strings that
  are preserved after trimming. Invalid, boolean, null, zero, negative, and
  empty required IDs fail validation. Android and iTunes reference `app_id`
  values are normalized to optional strings.
- Metadata is requested only after the market candidate request, local
  eligibility filtering, and final `final_top_n` selection. Empty IDs are
  removed, IDs are deduplicated while preserving first-seen order, and batches
  contain at most 50 IDs. A final set of 1,000 unique selected records makes
  exactly 20 metadata requests.
- Metadata is attached in selected market-record order without mutating the
  selected records. Duplicate selected records remain duplicated; missing
  metadata produces `metadata=None` and does not remove a market record.
- Publisher resolution follows the verified Apps Script precedence:
  `android_publisher_ids[0]` with `+` replaced by a space, then `publisher.name`,
  then the first `itunes_publisher_ids` value converted to text, otherwise
  unavailable. The normalized model records the resolution source and keeps
  missing values as `None`, never `"Unknown"` or `"N/A"`.
- A failed batch is retried at most two times after the initial attempt, with a
  1.5-second delay before retries. A 0.3-second delay occurs only between
  batches, never after the final batch. Timeout, HTTP failure, non-2xx response,
  malformed JSON, and malformed response envelopes are retryable. Exhaustion
  raises a sanitized typed batch error that identifies only the batch number.
- Duplicate response IDs and response IDs that were not requested fail
  integrity validation. Missing requested IDs are recorded and logged only as
  counts; the full ID list is not logged. An absent `apps` field is documented
  and tested as an empty result, while a non-list `apps` value is malformed.
- The existing Google Sheets cache contract is a maximum age of 14 days keyed
  by `unified_app_id`, with cached `name`, `publisher`, `androidId`, `iosId`,
  and `updatedAt`; only missing or expired IDs are fetched. ST-003 documents
  this behavior, and DB-001 persists the normalized equivalent in DuckDB.
- The response shape and requested fields are verified from the existing
  working Apps Script contract. The automated metadata responses in this
  repository are synthetic contract fixtures, not captured real Sensor Tower
  exports.

### Still TODO

- Metadata pagination and any additional response fields not included in the
  verified Apps Script contract are intentionally outside ST-003.
- DB-001 implements persistent metadata caching locally; no automatic network
  refresh is performed by the storage lookup.

## Historical data

### Verified

- The PRD requires historical monthly Top1000 data.
- The project plan targets a 36-month historical backfill and lists checkpoint, resume, and validation tasks.
- A top-level `date` field exists in the real response samples.
- The internal model must represent weekly and monthly observations through a cadence value rather than separate model classes.

### Still TODO

- Whether historical loading uses the same endpoint and request shape as the weekly market fetch.
- The request parameter used to select an historical period.
- The earliest available period and the exact 36-month window.
- The exact meaning, timezone, and boundary of a monthly observation.
- Whether historical results are point-in-time rankings or period aggregates.
- Pagination and checkpoint keys for historical loading.
- How renamed, deleted, or platform-specific products are represented.
- Whether the observed `date` field is the source date to persist for historical snapshots.

## Theme source

### Verified

- The PRD and `AGENTS.md` require theme classification from Sensor Tower Game Theme or Custom Fields.
- `custom_tags` is observed as a key/value object in the provided sample.
- `Game Theme` is observed as a key under `custom_tags`.
- The `Game Theme` values observed in the sample are strings.
- Example observed values are `Decoration`, `Candy / Dessert`, `Hypercasual`, `Fashion / Aesthetics / Hair`, `Abstract`, `Tabletop`, and `Vehicles - Car`.
- `Game Genre`, `Game Sub-genre`, `Game Product Model`, `Game Art Style`, and `Game Setting` also exist as verified custom-tag labels.
- The current weekly market filter uses `Game Genre`, not `Game Theme`. It is therefore a market/ranking selection filter and must not be treated as the theme classification itself.
- The examples above are sample observations only; no taxonomy rule, hierarchy, or completeness is inferred from them.

### Still TODO

- Whether `Game Theme` is always exactly one value.
- The full `Game Theme` taxonomy.
- The taxonomy version.
- Historical taxonomy changes.
- Missing and deprecated value behavior.
- The stability of theme labels over time.
- Whether other `custom_tags` entries follow the same structure and value-type rules beyond the provided sample.
- Whether theme values are returned in the market result, metadata result, or both.
- The mapping from source tag values to internal `Theme` records.

No theme may be inferred from the `Game Genre` filter, app name, icon, store copy, or an LLM.

## Downloads

### Verified

- The real response samples contain these unit-related top-level fields:

  ```text
  current_units_value
  units_absolute
  comparison_units_value
  units_delta
  units_transformed_delta
  ```

- The Apps Script obtains market rows before local filtering to 1000 rows.
- The verified live market response may omit the current/comparison unit
  fields and expose only `units_absolute`, `units_delta`, and
  `units_transformed_delta`. The earlier sample contains the larger field set.
- The adapter preserves each observed source metric under its source name and
  stores omitted optional metrics as unavailable/SQL `NULL`.

### Still TODO

- Whether any observed `*_units_*` field represents downloads.
- The exact mapping from source fields to the internal `downloads` value.
- The units, estimation basis, period, timezone, platform scope, and geography scope.
- The meaning of `current_units_value` and `comparison_units_value`.
- The meaning of `units_absolute`, `units_delta`, and `units_transformed_delta`.
- The denominator and calculation rule for `download_share`.
- Missing-value and zero-value behavior.

The system must not describe `current_units_value` as downloads or use it in a share calculation until the semantics are verified by the existing code or approved API documentation.

## Revenue

### Verified

- The real response samples contain these revenue-related top-level field names:

  ```text
  current_revenue_value
  revenue_absolute
  comparison_revenue_value
  revenue_delta
  revenue_transformed_delta
  ```

- The field existence is verified; the business meaning is not.
- The verified live market response may omit the current/comparison revenue
  fields and expose only `revenue_absolute`, `revenue_delta`, and
  `revenue_transformed_delta`. The earlier sample contains the larger field
  set. No field is silently renamed or copied into another source field.

### Still TODO

- The exact mapping from source fields to the internal `revenue` value.
- Whether `current_revenue_value` is a currency amount, an index, an estimate, or another value.
- Currency, exchange-rate, estimation, period, timezone, platform, and geography semantics.
- The meaning of `revenue_absolute`, `comparison_revenue_value`, `revenue_delta`, and `revenue_transformed_delta`.
- The denominator and calculation rule for `revenue_share`.
- Whether revenue is required for the MVP Trend Score.
- Missing-value and zero-value behavior.

The system must not attach a currency or other business semantic to `current_revenue_value` without evidence.

## Publisher

### Verified

- `Publisher Country` exists as a verified custom-tag label under `custom_tags`.
- `custom_tags` itself is a verified top-level response field.

### Still TODO

- A publisher name or publisher identifier field.
- Whether publisher identity is returned in market data, metadata, or a separate response.
- Whether `Publisher Country` is sufficient for any publisher analysis; it is not treated as publisher identity.
- Normalization and identity-merging rules for publishers.
- The distinct-publisher definition used by `publisher_count`.

Publisher counts must be derived from normalized internal publisher data, not guessed from `Publisher Country`.

## Release Date

### Verified

- `Earliest Release Date` exists as a verified custom-tag label.
- `Release Date (WW)` exists as a verified custom-tag label.
- A top-level `date` field also exists in real response samples, but it is not verified as a release date.

### Still TODO

- The actual values and date format contained in the release-date tags.
- The semantic difference between `Earliest Release Date` and `Release Date (WW)`.
- Whether either tag is available in the market response, metadata response, or both.
- Date precision, timezone, platform scope, and handling of missing or conflicting values.
- Which release-date concept should populate the internal app record.
- The exact product-age calculation used by monthly theme aggregation.

Release-date labels may be mapped only after their values and semantics are verified.
