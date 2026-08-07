# AGENTS.md

This repository is developed together with ChatGPT.

ChatGPT acts as the Tech Lead.

Codex acts as the Software Engineer.

Always follow these rules.

---

# Before Coding

Always read:

1. README.md

2. docs/PRD.md

3. PROJECT_PLAN.md

Only after understanding these documents should implementation begin.

---

# Development Workflow

One Issue

↓

One Pull Request

↓

One Review

↓

Merge

Never implement multiple Issues in one Pull Request.

---

# Project Goal

Build a long-term market intelligence platform for casual games.

The first module is Theme Trend Analysis.

Future modules may include:

- Publisher Analysis
- Genre Analysis
- Creative Analysis
- LiveOps Analysis
- AI Summary

Therefore,

always design reusable modules.

---

# Existing Systems

Two existing systems already exist.

Google Sheets

Purpose

Sensor Tower Top1000 collection.

Reuse:

- API request logic
- Request parameters
- Pagination

daily-newgames-fetcher

Purpose

Daily new games.

Reuse:

- Feishu
- GitHub Actions
- Logging
- Config
- Secrets

Do NOT rewrite these systems before understanding them.

---

# Sensor Tower

Never invent:

- endpoint

- parameters

- fields

Always use real API responses.

Unknown fields must be marked as TODO.

Never guess.

---

# Theme Classification

Always use Sensor Tower Game Theme or Custom Fields.

Never classify themes using LLM.

Never infer themes from names or icons.

---

# Development Rules

Every module should be:

- typed

- documented

- tested

- independently executable

External APIs must have Mock implementations.

---

# Coding Style

Python

Type hints required.

Small modules.

Single responsibility.

No hard-coded secrets.

No duplicated logic.

---

# Storage

Use:

DuckDB

+

Parquet

Feishu is NOT the database.

Feishu is only for collaboration and dashboards.

---

# Pull Requests

Every Pull Request must include:

Purpose

Files changed

Tests

Known limitations

Do NOT modify unrelated files.

---

# Tests

Every new feature requires:

Unit Test

Integration Test

Mock API

---

# Architecture

Business logic must NOT directly depend on:

Sensor Tower fields

Feishu fields

GitHub API

Always use internal models.

---

# When Uncertain

Stop.

Document assumptions.

Ask for clarification.

Never silently guess.

---

# Priority

Correctness

>

Maintainability

>

Performance

>

Speed
