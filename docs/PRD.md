# Casual Theme Trend Analysis

Version: 0.1

Owner: Century Games

Status: Draft

---

# 1. Project Goal

Build a long-term theme trend analysis platform for casual games.

The platform uses Sensor Tower as the only market data source.

The objective is NOT to identify game genres.

The objective is to identify THEME trends.

Examples:

- Animals
- Decoration
- Fashion
- Food
- Candy
- Ocean
- Garden
- Vehicle
- Hypercasual
- Beauty
- Farm

The platform should answer:

- Why is Animal becoming popular?
- Is Animal still growing?
- Which themes are entering the acceleration stage?
- Which themes may become the next hot themes?
- Which themes are driven by only one blockbuster?
- Which themes are already saturated?

---

# 2. Data Source

Only Sensor Tower.

No manual tagging.

No LLM classification.

Theme classification comes from Sensor Tower Game Theme / Custom Fields.

---

# 3. Existing Systems

Current systems:

1.

daily-newgames-fetcher

Purpose:

- Daily new games

Reusable:

- GitHub Actions
- Feishu
- Config
- Logging
- Secrets

2.

Google Sheets

Purpose:

Weekly Global Casual Top1000

Reusable:

- Sensor Tower API
- Request parameters
- Pagination
- Ranking logic

---

# 4. Storage

DuckDB

+

Parquet

No paid database.

Feishu is only used for:

- Dashboard
- Collaboration

---

# 5. Core Workflow

Sensor Tower

↓

Weekly Top1000

↓

Historical Backfill

↓

DuckDB

↓

Theme Aggregation

↓

Trend Analysis

↓

Feishu

---

# 6. MVP

The first version should support:

✓ Historical monthly Top1000

✓ Weekly Top1000

✓ Theme aggregation

✓ Market share

✓ Product age

✓ Publisher count

✓ Entry / Exit

✓ Concentration

✓ Theme ranking

✓ Feishu dashboard

---

# 7. Non Goals

The first version will NOT include:

- AI prediction
- Machine Learning
- LLM theme classification
- Real-time dashboard
- Multi-region comparison

---

# 8. Development Principle

Always reuse existing code.

Never invent Sensor Tower fields.

Always use Mock before production.

Every feature must have tests.

Every feature must be independently executable.
