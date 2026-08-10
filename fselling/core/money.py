"""Exact VND parsing, checked arithmetic and deterministic allocation.

Money persisted by I05 is always an integer number of VND.  Compatibility
parsers accept numeric representations such as ``1000.0`` only when the value
is exactly integral; they never round a fractional VND.
"""
from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Sequence, TypeVar

from .numeric_limits import MAX_SAFE_QUANTITY, MAX_SAFE_VND

JS_MAX_SAFE_INTEGER = 9_007_199_254_740_991
BASIS_POINTS_SCALE = 10_000

_PLAIN_ZERO_FRACTION = re.compile(r"^[+-]?\d+(?:\.0+)?$")
_PLAIN_PERCENT = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


class ExactMoneyError(ValueError):
    """A value cannot be represented as a bounded integer VND amount."""


def exact_vnd(value: Any, *, allow_negative: bool = False) -> int:
    """Return an exact integer VND representation or raise.

    JSON numbers ending in ``.0`` and plain digit strings with a zero-only
    fractional part are compatibility representations.  Exponents and locale
    formatting are intentionally rejected for strings because their contract
    is ambiguous across clients.
    """
    if isinstance(value, bool) or value is None:
        raise ExactMoneyError("VND value must be an exact integer representation")
    if isinstance(value, int):
        result = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ExactMoneyError("VND value must not contain a fraction")
        result = int(value)
    elif isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise ExactMoneyError("VND value must not contain a fraction")
        result = int(value)
    elif isinstance(value, str):
        raw = value.strip()
        if not _PLAIN_ZERO_FRACTION.fullmatch(raw):
            raise ExactMoneyError("VND string must contain digits and an optional zero fraction")
        try:
            result = int(raw.split(".", 1)[0])
        except ValueError as exc:  # pragma: no cover - guarded by the regex
            raise ExactMoneyError("Invalid VND value") from exc
    else:
        raise ExactMoneyError("Unsupported VND representation")
    if not allow_negative and result < 0:
        raise ExactMoneyError("VND value must be non-negative")
    if abs(result) > MAX_SAFE_VND:
        raise ExactMoneyError("VND value exceeds MAX_SAFE_VND")
    return result


def percentage_to_bps(value: Any) -> int:
    """Convert an exact percentage representation to integer basis points."""
    if isinstance(value, bool) or value is None:
        raise ExactMoneyError("Percentage must be numeric")
    raw = str(value).strip()
    if not _PLAIN_PERCENT.fullmatch(raw):
        raise ExactMoneyError("Percentage must be a plain decimal")
    try:
        percent = Decimal(raw)
        scaled = percent * Decimal(100)
    except InvalidOperation as exc:
        raise ExactMoneyError("Invalid percentage") from exc
    if not percent.is_finite() or scaled != scaled.to_integral_value():
        raise ExactMoneyError("Percentage must be exactly representable in basis points")
    bps = int(scaled)
    if bps < 0 or bps > BASIS_POINTS_SCALE:
        raise ExactMoneyError("Percentage must be between 0 and 100")
    return bps


def checked_quantity(value: Any, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Quantity must be an integer")
    lower = 1 if positive else 0
    if value < lower or value > MAX_SAFE_QUANTITY:
        raise ValueError("Quantity is outside the supported range")
    return value


def checked_vnd(value: int, *, allow_negative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Money must be an integer")
    if (not allow_negative and value < 0) or abs(value) > MAX_SAFE_VND:
        raise ValueError("Money is outside the supported range")
    return value


def checked_add(*values: int, allow_negative: bool = False) -> int:
    return checked_vnd(sum(values), allow_negative=allow_negative)


def checked_multiply(quantity: int, unit_vnd: int) -> int:
    checked_quantity(quantity)
    checked_vnd(unit_vnd)
    return checked_vnd(quantity * unit_vnd)


def round_percentage_vnd(amount_vnd: int, basis_points: int) -> int:
    """ROUND_HALF_UP once at document level using Decimal from integers."""
    checked_vnd(amount_vnd)
    if not isinstance(basis_points, int) or not 0 <= basis_points <= BASIS_POINTS_SCALE:
        raise ValueError("Basis points are outside 0..10000")
    rounded = (
        (Decimal(amount_vnd) * Decimal(basis_points)) / Decimal(BASIS_POINTS_SCALE)
    ).to_integral_value(rounding=ROUND_HALF_UP)
    return checked_vnd(int(rounded))


T = TypeVar("T")


def largest_remainder_allocate(
    total_vnd: int,
    destinations: Sequence[tuple[int, int, T]],
) -> list[tuple[T, int]]:
    """Allocate a document amount by weight with deterministic tie-breaking.

    Each destination is ``(immutable_id, nonnegative_weight, payload)``.  Floors
    are assigned first; remaining đồng go by remainder descending and then
    immutable destination id ascending.
    """
    checked_vnd(total_vnd)
    if not destinations:
        if total_vnd:
            raise ValueError("Cannot allocate a non-zero amount without destinations")
        return []
    weight_sum = sum(weight for _, weight, _ in destinations)
    if weight_sum < 0 or any(weight < 0 for _, weight, _ in destinations):
        raise ValueError("Allocation weights must be non-negative")
    if total_vnd == 0:
        return [(payload, 0) for _, _, payload in destinations]
    if weight_sum <= 0:
        raise ValueError("Cannot allocate by zero total weight")

    rows: list[list[Any]] = []
    floor_sum = 0
    for destination_id, weight, payload in destinations:
        numerator = total_vnd * weight
        floor_value, remainder = divmod(numerator, weight_sum)
        floor_sum += floor_value
        rows.append([destination_id, remainder, payload, floor_value])
    remaining = total_vnd - floor_sum
    for row in sorted(rows, key=lambda item: (-item[1], item[0]))[:remaining]:
        row[3] += 1
    result = [(row[2], checked_vnd(int(row[3]))) for row in rows]
    if sum(amount for _, amount in result) != total_vnd:
        raise AssertionError("Largest-remainder allocation did not conserve the total")
    return result


def cumulative_basis(total_basis_vnd: int, known_qty: int, target_known_qty: int) -> int:
    """Exact cumulative basis target; the final consume receives all remainder."""
    checked_vnd(total_basis_vnd)
    checked_quantity(known_qty)
    checked_quantity(target_known_qty)
    if target_known_qty > known_qty:
        raise ValueError("Known target exceeds the source allocation")
    if target_known_qty == 0:
        return 0
    if target_known_qty == known_qty:
        return total_basis_vnd
    return (total_basis_vnd * target_known_qty) // known_qty


def json_safe_integer(value: int) -> int | str:
    """Use a decimal string only when a version-2 JSON number would be unsafe."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("json_safe_integer expects int")
    return value if abs(value) <= JS_MAX_SAFE_INTEGER else str(value)


__all__ = [
    "BASIS_POINTS_SCALE",
    "ExactMoneyError",
    "JS_MAX_SAFE_INTEGER",
    "checked_add",
    "checked_multiply",
    "checked_quantity",
    "checked_vnd",
    "cumulative_basis",
    "exact_vnd",
    "json_safe_integer",
    "largest_remainder_allocate",
    "percentage_to_bps",
    "round_percentage_vnd",
]
