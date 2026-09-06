"""Pydantic-facing exact VND compatibility type."""
from decimal import Decimal
from typing import Annotated

from pydantic import BeforeValidator

from ..core.money import exact_vnd, percentage_to_bps

ExactVND = Annotated[int, BeforeValidator(exact_vnd)]


def _exact_signed_vnd(value):
    """Compatibility parser for fields whose service owns the 400 range error."""
    return exact_vnd(value, allow_negative=True)


SignedExactVND = Annotated[int, BeforeValidator(_exact_signed_vnd)]


def _exact_basis_point_percent(value):
    """Normalize a customer-visible percent through canonical integer bps."""
    return Decimal(percentage_to_bps(value)) / Decimal(100)


BasisPointPercent = Annotated[Decimal, BeforeValidator(_exact_basis_point_percent)]

__all__ = ["BasisPointPercent", "ExactVND", "SignedExactVND"]
