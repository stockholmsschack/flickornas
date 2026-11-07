"""Shared primitive numeric predicates."""

from __future__ import annotations

import math


def is_positive_integer(value: object) -> bool:
    """Return whether value is an integer greater than zero."""
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def is_non_negative_integer(value: object) -> bool:
    """Return whether value is an integer greater than or equal to zero."""
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def is_positive_finite_number(value: object) -> bool:
    """Return whether value is a finite number greater than zero."""
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value > 0
    )


def is_non_negative_finite_number(value: object) -> bool:
    """Return whether value is a finite number greater than or equal to zero."""
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value >= 0
    )
