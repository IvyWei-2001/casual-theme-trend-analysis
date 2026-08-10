"""Pure analytical functions over normalized DuckDB source rows."""

from .trend_models import ThemeTrendScore
from .trend_score import (
    MVP_CONFIDENCE_WEIGHTS,
    MVP_TREND_SCORE_WEIGHTS,
    ConfidenceWeights,
    TrendScoreWeights,
    calculate_theme_trend_scores,
    calculate_trend_scores,
)

__all__ = [
    "ConfidenceWeights",
    "MVP_CONFIDENCE_WEIGHTS",
    "MVP_TREND_SCORE_WEIGHTS",
    "ThemeTrendScore",
    "TrendScoreWeights",
    "calculate_theme_trend_scores",
    "calculate_trend_scores",
]
