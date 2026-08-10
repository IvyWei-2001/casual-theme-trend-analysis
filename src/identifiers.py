"""Neutral normalization for required source and application identifiers."""

from __future__ import annotations

import re

_INTEGER_STRING_PATTERN = re.compile(r"^[0-9]+$")
_NUMERIC_LIKE_STRING_PATTERN = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$")


def normalize_required_opaque_id(
    value: object,
    *,
    field_name: str = "identifier",
) -> str:
    """Normalize one required identifier without assuming an integer ID space.

    Positive integers and numeric strings retain the historical decimal-string
    normalization. Other non-empty strings are opaque identifiers and are
    preserved after surrounding whitespace is trimmed. Error messages contain
    only the field name so identifier values cannot leak through validation.
    """

    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a non-empty opaque identifier")

    if isinstance(value, int):
        if value <= 0:
            raise ValueError(f"{field_name} must be a positive identifier")
        return str(value)

    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{field_name} must be a non-empty opaque identifier")
        if not _INTEGER_STRING_PATTERN.fullmatch(cleaned):
            if _NUMERIC_LIKE_STRING_PATTERN.fullmatch(cleaned):
                raise ValueError(f"{field_name} must be a positive identifier")
            return cleaned

        normalized = str(int(cleaned, 10))
        if normalized == "0":
            raise ValueError(f"{field_name} must be a positive identifier")
        return normalized

    raise ValueError(f"{field_name} must be a non-empty opaque identifier")
