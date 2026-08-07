# Casual Theme Trend Analysis

## Requirements

- Python 3.12

## Local installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Run

```powershell
python -m src
```

## Tests and quality checks

```powershell
pytest
ruff check .
mypy src
```

## Sensor Tower source contract parser

The initial Sensor Tower parser handles a verified response sample for local
testing. It does not make network calls, and the semantics of
`current_units_value` and `current_revenue_value` remain pending API-contract
confirmation.
