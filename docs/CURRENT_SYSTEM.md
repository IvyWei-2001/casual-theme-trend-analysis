# Current System

This document records the audited repository state and separates verified behavior in the existing external systems from capabilities that are only planned.

## Current project goal

The project is intended to become a long-term market-intelligence platform for casual games. The first module is Theme Trend Analysis.

The platform identifies theme trends rather than game genres. It should help answer whether a theme is growing, accelerating, becoming saturated, or being driven by one blockbuster rather than a broad group of products.

Sensor Tower is the only approved market-data source. Theme classification must come from Sensor Tower Game Theme or Custom Fields. Manual tagging, name or icon inference, and LLM classification are out of scope.

## Existing project structure

The repository is currently a documentation scaffold:

```text
casual-theme-trend-analysis/
|-- AGENTS.md
|-- PROJECT_PLAN.md
|-- README.md
`-- docs/
    |-- API_MAPPING.md
    |-- CURRENT_SYSTEM.md
    |-- DATA_MODEL.md
    |-- IMPLEMENTATION_PLAN.md
    `-- PRD.md
```

No Python package, test suite, configuration module, storage implementation, API client, mock API, Feishu integration, or automation workflow is present in this repository.

Two external systems are referenced by the project documents but are not present in this repository:

- Google Sheets / Apps Script, which collects the weekly market Top1000.
- `daily-newgames-fetcher`, which is expected to provide reusable Feishu, logging, configuration, secrets, and automation patterns.

The Google Sheets / Apps Script contract is now partially documented from verified implementation and response evidence. The Feishu implementation in `daily-newgames-fetcher` has not yet been inspected.

## Existing documents

| Document | Current role | Observed status |
| --- | --- | --- |
| `README.md` | Repository entry point | Contains only the project title. |
| `docs/PRD.md` | Product requirements | Version 0.1, status Draft. Defines the goal, Sensor Tower boundary, storage direction, MVP outcomes, and non-goals. |
| `PROJECT_PLAN.md` | Roadmap and issue sequence | Status Active. It marks Phase 0 Completed and lists Phase 1 / `INF-001 Repository Structure` as the current sprint. |
| `AGENTS.md` | Engineering constraints | Requires typed, documented, tested, independently executable modules, mock external APIs, internal domain models, and no invented Sensor Tower fields. |
| `docs/CURRENT_SYSTEM.md` | Audited repository and system state | Updated by this audit correction. |
| `docs/API_MAPPING.md` | Sensor Tower contract mapping | Updated with verified Apps Script and response-sample facts plus remaining TODOs. |
| `docs/DATA_MODEL.md` | Internal domain model | Updated with source and unified app identity, time-scoped snapshots, and explicit theme metrics. |
| `docs/IMPLEMENTATION_PLAN.md` | MVP execution order | Updated to the requested Bootstrap-to-Feishu sequence. |

## Verified current data flow

The existing Apps Script implementation establishes the following two-stage flow:

```text
Config sheet
  -> configured Sensor Tower URL and auth token
  -> market / ranking request with an encoded custom field filter
  -> local filtering to 1000 market rows
  -> extract source app_id values
  -> separate metadata enrichment request
```

The weekly market request filters with a custom field named `Game Genre` and values `Puzzle` and `Tabletop`. This is a market/ranking selection rule, not the theme-classification rule. Real response samples also expose `custom_tags`, including a `Game Theme` tag and other metadata tags; the exact value semantics remain documented as TODO in `API_MAPPING.md`.

The current system therefore has a confirmed boundary between market/ranking data and metadata enrichment. The repository does not yet contain a normalized adapter for either stage.

## Current development stage

### Roadmap status

`PROJECT_PLAN.md` declares Phase 0, System Audit, as Completed and Phase 1, Infrastructure, as the current phase.

### Audited status

Phase 0 must not be treated as fully complete yet. It becomes complete only when both conditions below are satisfied:

1. The old Google Sheets / Apps Script contract is documented, including its Config-sheet URL and token inputs, custom field filter, local 1000-row limit, separate metadata enrichment, and verified response fields.
2. The Feishu implementation from `daily-newgames-fetcher` is inspected and its reusable contract is documented.

This audit correction documents the first condition from the verified evidence provided for this task. The second condition remains open, so the system audit gate remains open even though the roadmap file still says Completed.

## Missing modules and open system work

The following capabilities are planned but do not yet exist in this repository.

### Foundation

- Typed Python package and reusable module layout.
- Configuration loading and validation for local execution.
- Structured logging and error handling.
- Test harness and shared mock fixtures.

### Sensor Tower integration

- Adapter for the market/ranking request.
- Separate metadata enrichment adapter.
- Authentication transport and request handling.
- Pagination, retry, and response validation behavior.
- Weekly Top1000 ingestion.
- Historical monthly Top1000 loading and backfill controls.
- Mapping of verified response fields into internal models.

The endpoint URL, request method, complete parameter contract, metadata request contract, and several field semantics remain TODO.

### Internal data and storage

- Internal `App`, `Theme`, `Snapshot`, and `ThemeMetric` models.
- Identity resolution across `source_app_id`, optional `unified_app_id`, and the internal canonical `app_id`.
- Mapping layer that merges market/ranking rows with metadata enrichment.
- DuckDB persistence and repository abstraction.
- Parquet storage boundary required by the project rules.
- Data validation and explicit unavailable-data handling.

### Analytics

- Monthly theme aggregation.
- Explicit downloads, download share, revenue, and revenue share metrics after their source semantics are verified.
- Product count, new-product count, publisher count, concentration, growth, acceleration, Trend Score, and confidence calculations.

### Feishu output

- Inspection and documentation of the existing `daily-newgames-fetcher` Feishu implementation.
- Reusable Feishu schema and field mapping.
- Sync/export adapter and ranked theme views.

Feishu is an output and collaboration surface, not the canonical database.

### Deferred capabilities

AI prediction, machine learning, LLM classification, real-time dashboards, multi-region comparison, scheduled automation, and separate Publisher, Genre, Creative, LiveOps, or AI Summary modules are outside this MVP audit and implementation scope.
