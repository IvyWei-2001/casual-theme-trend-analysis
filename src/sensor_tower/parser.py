"""Parsing helpers for the verified Sensor Tower market-response variants."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from .dto import SensorTowerMarketRecord


def parse_market_response(payload: object) -> list[SensorTowerMarketRecord]:
    """Parse an already-decoded Sensor Tower market response.

    The verified responses are JSON arrays of row objects. The adapter supports
    the two observed custom-tag locations: a top-level ``custom_tags`` mapping
    and ``entities[0].custom_tags`` overlaid by ``aggregate_tags``. Pydantic
    validation is intentionally allowed to propagate so invalid required
    fields, especially the top-level date and app ID, produce structured
    validation errors.
    """

    if not isinstance(payload, list):
        raise TypeError("Sensor Tower market response must be a JSON array")

    records: list[SensorTowerMarketRecord] = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise TypeError(f"Sensor Tower market record at index {index} must be a JSON object")
        records.append(SensorTowerMarketRecord.model_validate(_normalize_market_record(item)))
    return records


def _normalize_market_record(item: Mapping[object, object]) -> dict[object, object]:
    """Normalize only the verified custom-tag response shapes.

    The original record is copied before replacing ``custom_tags`` so every
    unknown source field remains available as a DTO extra field.  Unsupported
    shapes are left untouched and fail normal DTO validation rather than being
    guessed into a new source contract.
    """

    normalized = dict(item)
    top_level_tags = item.get("custom_tags")
    if isinstance(top_level_tags, Mapping):
        normalized["custom_tags"] = dict(top_level_tags)
        return normalized

    entities = item.get("entities")
    if not isinstance(entities, list) or not entities:
        return normalized

    first_entity = entities[0]
    if not isinstance(first_entity, Mapping):
        return normalized

    entity_tags = first_entity.get("custom_tags")
    if not isinstance(entity_tags, Mapping):
        return normalized

    normalized_tags = dict(entity_tags)
    aggregate_tags = item.get("aggregate_tags")
    if isinstance(aggregate_tags, Mapping):
        normalized_tags.update(aggregate_tags)
    normalized["custom_tags"] = normalized_tags
    return normalized


def load_market_response_file(path: str | Path) -> object:
    """Read a local JSON response file without applying DTO validation."""

    with Path(path).open("r", encoding="utf-8") as response_file:
        return cast(object, json.load(response_file))


def parse_market_response_file(path: str | Path) -> list[SensorTowerMarketRecord]:
    """Read and parse a local response file for fixtures and manual testing."""

    return parse_market_response(load_market_response_file(path))
