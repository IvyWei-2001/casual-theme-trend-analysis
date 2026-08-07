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

# Overall Roadmap

Phase 0

System Audit

↓

Phase 1

Infrastructure

↓

Phase 2

Sensor Tower Integration

↓

Phase 3

Historical Backfill

↓

Phase 4

Theme Aggregation

↓

Phase 5

Trend Analysis

↓

Phase 6

Feishu Dashboard

↓

Phase 7

Automation

---

# Phase 0

Goal

Understand current systems.

Deliverables

- Existing architecture
- API mapping
- Migration plan

Exit Criteria

Migration plan approved.

Status

Completed

---

# Phase 1

Goal

Build project infrastructure.

Tasks

INF-001

Repository structure

INF-002

Configuration

INF-003

Logging

INF-004

DuckDB

INF-005

Parquet

INF-006

Storage abstraction

Exit Criteria

Project runs locally.

---

# Phase 2

Goal

Sensor Tower integration.

Tasks

ST-001

Authentication

ST-002

HTTP Client

ST-003

Pagination

ST-004

Top1000

ST-005

Historical Rankings

ST-006

Custom Fields

Exit Criteria

Historical monthly data can be fetched.

---

# Phase 3

Goal

Historical data storage.

Tasks

HB-001

Monthly backfill

HB-002

Checkpoint

HB-003

Resume

HB-004

Validation

Exit Criteria

36 months available.

---

# Phase 4

Goal

Theme aggregation.

Tasks

TH-001

Product Age

TH-002

Market Share

TH-003

Publisher

TH-004

Entry Exit

TH-005

Rank Migration

Exit Criteria

Monthly theme metrics generated.

---

# Phase 5

Goal

Trend Analysis.

Tasks

TA-001

Growth

TA-002

Acceleration

TA-003

Concentration

TA-004

Saturation

TA-005

Lifecycle

TA-006

Trend Score

TA-007

Confidence

Exit Criteria

Theme ranking available.

---

# Phase 6

Goal

Feishu Dashboard.

Tasks

FS-001

Schema

FS-002

Sync

FS-003

Ranking

FS-004

Summary

Exit Criteria

Dashboard available.

---

# Phase 7

Goal

Automation.

Tasks

AT-001

GitHub Actions

AT-002

Weekly workflow

AT-003

Monthly workflow

AT-004

Release Storage

Exit Criteria

Fully automated.

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

Phase 1

Current Issue

INF-001

Repository Structure
