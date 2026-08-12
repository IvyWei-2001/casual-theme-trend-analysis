"""Local eligibility filtering for Sensor Tower market candidates."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Protocol

from .dto import SensorTowerMarketRecord
from .errors import NoEligibleMarketRecordsError, SensorTowerSelectionConfigurationError
from .request import SensorTowerMarketRequest, SensorTowerSelectionConfig

LOGGER = logging.getLogger(__name__)


class MarketCandidateClient(Protocol):
    """Minimal client contract required by the selection orchestration."""

    def fetch_market_candidates(
        self,
        request: SensorTowerMarketRequest,
    ) -> list[SensorTowerMarketRecord]:
        """Fetch candidates from the external market boundary."""


def select_market_records(
    records: Iterable[SensorTowerMarketRecord],
    *,
    allowed_genres: Iterable[str],
    final_top_n: int,
    exclude_china_revenue_market: bool,
) -> list[SensorTowerMarketRecord]:
    """Select eligible records in source order, stopping after ``final_top_n``.

    The function deliberately does not sort, pad, deduplicate, or infer any
    record values.  Eligibility is based only on normalized custom tags.
    """

    if final_top_n <= 0:
        raise SensorTowerSelectionConfigurationError("final_top_n must be positive")

    normalized_genres = frozenset(normalize_game_genre(genre) for genre in allowed_genres)
    if not normalized_genres or "" in normalized_genres:
        raise SensorTowerSelectionConfigurationError("allowed genre names must be non-empty")

    selected: list[SensorTowerMarketRecord] = []
    candidate_count = 0
    for record in records:
        candidate_count += 1
        genre = record.game_genre
        if genre is None or normalize_game_genre(genre) not in normalized_genres:
            continue

        if (
            exclude_china_revenue_market
            and record.most_popular_country_by_revenue == "China"
        ):
            continue

        selected.append(record)
        if len(selected) == final_top_n:
            break

    if not selected:
        raise NoEligibleMarketRecordsError(candidate_count)

    if len(selected) < final_top_n:
        LOGGER.warning(
            "Sensor Tower market selection returned fewer eligible records: "
            "candidates=%d selected=%d final_top_n=%d",
            candidate_count,
            len(selected),
            final_top_n,
        )

    return selected


def fetch_and_select_market_records(
    client: MarketCandidateClient,
    request: SensorTowerMarketRequest,
    selection_config: SensorTowerSelectionConfig | None = None,
) -> list[SensorTowerMarketRecord]:
    """Fetch and apply the request's local selection rules in source order.

    Normal usage derives the selection configuration directly from the request.
    The optional argument remains available for callers migrating from the
    earlier API, but every field is compared before a request is made.
    """

    request_selection_config = request.selection_config()
    if selection_config is not None:
        mismatches = _selection_config_mismatches(request_selection_config, selection_config)
        if mismatches:
            mismatch_text = ", ".join(mismatches)
            raise SensorTowerSelectionConfigurationError(
                "selection configuration does not match request: " + mismatch_text
            )

    candidates = client.fetch_market_candidates(request)
    return select_market_records(
        candidates,
        allowed_genres=request_selection_config.allowed_genres,
        final_top_n=request_selection_config.final_top_n,
        exclude_china_revenue_market=request_selection_config.exclude_china_revenue_market,
    )


def _selection_config_mismatches(
    expected: SensorTowerSelectionConfig,
    actual: SensorTowerSelectionConfig,
) -> tuple[str, ...]:
    fields = (
        "api_limit",
        "final_top_n",
        "allowed_genres",
        "exclude_china_revenue_market",
        "scope_name",
    )
    return tuple(field for field in fields if getattr(expected, field) != getattr(actual, field))


def _normalize_genre(value: str) -> str:
    return normalize_game_genre(value)


def normalize_game_genre(value: str) -> str:
    """Apply the shared production Game Genre comparison normalization."""

    return value.strip().casefold()
