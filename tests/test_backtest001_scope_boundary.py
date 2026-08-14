"""Static boundary checks for the pure BACKTEST-001 calculation module."""

from __future__ import annotations

import inspect

from src.analysis import backtest_v1


def test_pure_backtest_module_has_no_external_or_recalculation_boundary() -> None:
    source = inspect.getsource(backtest_v1)

    assert "calculate_theme_trend_scores" not in source
    assert "calculate_theme_model_metrics" not in source
    assert "aggregate_theme_opportunity_metrics" not in source
    assert "from ..storage" not in source
    assert "from ..config" not in source
    assert "from ..feishu" not in source
    assert "from ..sensor_tower" not in source

    parameters = inspect.signature(backtest_v1.calculate_theme_launch_window_backtest).parameters
    assert tuple(parameters) == (
        "monthly_market_totals",
        "theme_market_structure_metrics",
        "theme_growth_source_metrics",
        "theme_trend_scores",
        "theme_model_summaries",
        "theme_seasonality_profiles",
        "calculated_at",
    )
