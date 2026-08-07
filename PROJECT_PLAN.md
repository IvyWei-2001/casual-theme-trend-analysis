# PROJECT PLAN

Project: Casual Theme Trend Analysis

Status: Active

---

# Development Principle

This project is developed incrementally.

Each phase must be independently executable.

Each Pull Request should complete ONE issue only.

Never implement multiple milestones in one Pull Request.

---

# MVP Execution Order

The first delivery prioritizes monthly historical analysis:

1. Bootstrap repository
2. Sensor Tower adapter
3. DuckDB persistence
4. Historical monthly loading
5. Theme monthly aggregation
6. Trend Score
7. Feishu sync

Weekly tracking is a later incremental capability. It must not block the first monthly dashboard delivery.

---

# Phase 0

Goal

Complete the system audit and document the external contracts.

Deliverables

- Existing architecture
- Sensor Tower API mapping
- Internal data model
- MVP implementation plan
- Feishu implementation review from `daily-newgames-fetcher`

Exit Criteria

- The old Google Sheets / Apps Script contract is documented.
- The Feishu implementation from `daily-newgames-fetcher` is inspected and its reusable contract is documented.

Status

Completed in the roadmap; the implementation gate remains open until the Feishu inspection is complete.

---

# Phase 1

Goal

Bootstrap the repository for independent local execution.

Tasks

INF-001

Repository structure

INF-002

Configuration

INF-003

Logging

INF-004

DuckDB foundation

INF-005

Parquet boundary

INF-006

Storage abstraction

Exit Criteria

The project foundation can run locally without external API access.

---

# Phase 2

Goal

Normalize a verified Sensor Tower response sample.

Tasks

ST-001

Authentication boundary

ST-002

HTTP client boundary

ST-003

Pagination contract

ST-004

Market/ranking response mapping

ST-005

Metadata enrichment mapping

ST-006

Custom-tag mapping

Exit Criteria

The market/ranking and metadata paths can be mapped into internal models using verified response evidence and mocks.

---

# Phase 3

Goal

Persist normalized internal records in DuckDB.

Tasks

DB-001

App identity persistence

DB-002

Theme persistence

DB-003

Snapshot persistence

DB-004

Validation and idempotency

Exit Criteria

The same normalized input can be persisted and read without duplicate observations.

---

# Phase 4

Goal

Load historical monthly data for the first dashboard.

Tasks

HB-001

Monthly loading

HB-002

Checkpoint

HB-003

Resume

HB-004

Validation

Exit Criteria

A small verified monthly history is available and can later expand toward the 36-month roadmap target.

---

# Phase 5

Goal

Generate monthly theme metrics.

Tasks

TH-001

Theme mapping

TH-002

Product count

TH-003

Downloads and download share

TH-004

Revenue and revenue share

TH-005

Publisher count and concentration

TH-006

Growth and acceleration

Exit Criteria

Monthly `ThemeMetric` records are generated from compatible internal snapshots without assuming unverified metric semantics.

---

# Phase 6

Goal

Calculate an explainable Trend Score.

Tasks

TA-001

Growth

TA-002

Acceleration

TA-003

Concentration

TA-004

Trend Score

TA-005

Confidence

Exit Criteria

Monthly theme ranking is reproducible, explainable, and explicit about insufficient data.

---

# Phase 7

Goal

Synchronize the first monthly theme dashboard to Feishu.

Tasks

FS-001

Feishu implementation review

FS-002

Schema mapping

FS-003

Sync

FS-004

Ranking and summary

Exit Criteria

The validated monthly theme ranking is available in Feishu without making Feishu the source of truth.

---

# Deferred Incremental Capabilities

- Weekly tracking after the monthly dashboard is validated.
- Scheduled automation after the manual MVP flow is reliable.

This plan does not add new future platform modules.

---

# Rules

Every Issue

Must include:

- Tests

- Documentation

- Type hints

- Logging

Every PR

Must:

- Pass Ruff

- Pass Pytest

- Update README

- Update CHANGELOG

---

# Current Sprint

Current Focus

Phase 1 Bootstrap Repository

Current Issue

INF-001

Repository Structure
