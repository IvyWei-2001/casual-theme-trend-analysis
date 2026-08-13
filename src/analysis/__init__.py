"""Pure analytical functions over normalized DuckDB source rows."""

from .model_v2 import (
    ACCELERATION_NORMALIZED_SLOPE_MARGIN,
    DIRECTION_MIN_R_SQUARED,
    DIRECTION_NORMALIZED_SLOPE_THRESHOLD,
    MODEL_POLICY_VERSION,
    SEASONALITY_MAX_HISTORY_MONTHS,
    SEASONALITY_MIN_HISTORY_MONTHS,
    STABILITY_STABLE_CV_MAX,
    STABILITY_VARIABLE_CV_MAX,
    calculate_theme_model_metrics,
)
from .model_v2_models import (
    ThemeHorizonMetric,
    ThemeModelResult,
    ThemeModelSummary,
    ThemeSeasonalityProfile,
)
from .opportunity_aggregation import aggregate_theme_opportunity_metrics
from .opportunity_models import (
    DEFAULT_REPRESENTATIVE_GAME_LIMIT,
    OpportunityAggregationResult,
    ThemeDimensionMonthlyMetric,
    ThemeGrowthSourceMetric,
    ThemeMarketStructureMetric,
    ThemeRepresentativeGame,
)
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
    "DEFAULT_REPRESENTATIVE_GAME_LIMIT",
    "OpportunityAggregationResult",
    "ThemeDimensionMonthlyMetric",
    "ThemeGrowthSourceMetric",
    "ThemeMarketStructureMetric",
    "ThemeRepresentativeGame",
    "aggregate_theme_opportunity_metrics",
    "ACCELERATION_NORMALIZED_SLOPE_MARGIN",
    "DIRECTION_MIN_R_SQUARED",
    "DIRECTION_NORMALIZED_SLOPE_THRESHOLD",
    "MODEL_POLICY_VERSION",
    "SEASONALITY_MAX_HISTORY_MONTHS",
    "SEASONALITY_MIN_HISTORY_MONTHS",
    "STABILITY_STABLE_CV_MAX",
    "STABILITY_VARIABLE_CV_MAX",
    "ThemeHorizonMetric",
    "ThemeModelResult",
    "ThemeModelSummary",
    "ThemeSeasonalityProfile",
    "calculate_theme_model_metrics",
]
