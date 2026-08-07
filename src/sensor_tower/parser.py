"""Parsing helpers for a verified Sensor Tower market response sample."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from .dto import SensorTowerMarketRecord


def parse_market_response(payload: object) -> list[SensorTowerMarketRecord]:
    """Parse an already-decoded Sensor Tower market response.

    The verified sample is a JSON array of row objects.  Pydantic validation is
    intentionally allowed to propagate so invalid fields, especially the
    top-level date, produce a structured validation error.
    """

    if not isinstance(payload, list):
        raise TypeError("Sensor Tower market response must be a JSON array")

    records: list[SensorTowerMarketRecord] = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise TypeError(f"Sensor Tower market record at index {index} must be a JSON object")
        records.append(SensorTowerMarketRecord.model_validate(item))
    return records


def load_market_response_file(path: str | Path) -> object:
    """Read a local JSON response file without applying DTO validation."""

    with Path(path).open("r", encoding="utf-8") as response_file:
        return cast(object, json.load(response_file))


def parse_market_response_file(path: str | Path) -> list[SensorTowerMarketRecord]:
    """Read and parse a local response file for fixtures and manual testing."""

    return parse_market_response(load_market_response_file(path))
