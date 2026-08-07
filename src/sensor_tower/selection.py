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

    normalized_genres = frozenset(_normalize_genre(genre) for genre in allowed_genres)
    if not normalized_genres or "" in normalized_genres:
        raise SensorTowerSelectionConfigurationError("allowed genre names must be non-empty")

    selected: list[SensorTowerMarketRecord] = []
    candidate_count = 0
    for record in records:
        candidate_count += 1
        genre = record.game_genre
        if genre is None or _normalize_genre(genre) not in normalized_genres:
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
    selection_config: SensorTowerSelectionConfig,
) -> list[SensorTowerMarketRecord]:
    """Fetch, normalize through the client, and apply local selection rules."""

    if request.api_limit != selection_config.api_limit:
        raise SensorTowerSelectionConfigurationError(
            "request api_limit must match selection configuration api_limit"
        )

    candidates = client.fetch_market_candidates(request)
    return select_market_records(
        candidates,
        allowed_genres=selection_config.allowed_genres,
        final_top_n=selection_config.final_top_n,
        exclude_china_revenue_market=selection_config.exclude_china_revenue_market,
    )


def _normalize_genre(value: str) -> str:
    return value.strip().casefold()
