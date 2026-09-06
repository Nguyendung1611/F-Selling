from __future__ import annotations

from types import SimpleNamespace

import pytest

from fselling.core.money import (
    ExactMoneyError,
    cumulative_basis,
    exact_vnd,
    largest_remainder_allocate,
    percentage_to_bps,
    round_percentage_vnd,
)
from fselling.core.numeric_limits import MAX_SAFE_VND
from fselling.services.inventory_service import consume_cost_pool, restore_cost_pool


@pytest.mark.parametrize("value", [0, 1, 1000.0, "1000", "1000.000"])
def test_exact_vnd_accepts_only_exact_integer_representations(value):
    assert exact_vnd(value) == int(float(value))


@pytest.mark.parametrize(
    "value", [1.5, "1.50", float("nan"), float("inf"), "1e3", MAX_SAFE_VND + 1]
)
def test_exact_vnd_rejects_fractional_nonfinite_ambiguous_and_overflow(value):
    with pytest.raises(ExactMoneyError):
        exact_vnd(value)


def test_percentage_rounds_half_up_once_at_document_level():
    assert percentage_to_bps("12.34") == 1234
    assert round_percentage_vnd(5, 1000) == 1
    assert round_percentage_vnd(15, 1000) == 2


def test_largest_remainder_conserves_sum_and_ties_by_immutable_id():
    result = largest_remainder_allocate(
        2,
        [(30, 1, "third"), (10, 1, "first"), (20, 1, "second")],
    )
    assert dict(result) == {"third": 0, "first": 1, "second": 1}
    assert sum(amount for _, amount in result) == 2


def _pool(*, known: int, unknown: int, basis: int):
    return SimpleNamespace(
        stock=known + unknown,
        cost_known_qty=known,
        cost_unknown_qty=unknown,
        cost_basis_vnd=basis,
        cost_deficit_qty=0,
        cost_state_version=0,
    )


def test_cost_pool_consumes_unknown_first_and_final_known_gets_remainder():
    pool = _pool(known=3, unknown=2, basis=10)
    first = consume_cost_pool(pool, 3)
    assert (first.unknown_qty, first.known_qty, first.cost_basis_vnd) == (2, 1, 3)
    pool.stock -= 3
    final = consume_cost_pool(pool, 2)
    assert (final.unknown_qty, final.known_qty, final.cost_basis_vnd) == (0, 2, 7)
    assert (pool.cost_known_qty, pool.cost_unknown_qty, pool.cost_basis_vnd) == (0, 0, 0)


def test_cumulative_return_target_and_restore_preserve_exact_basis():
    assert [cumulative_basis(10, 3, target) for target in (1, 2, 3)] == [3, 6, 10]
    pool = _pool(known=0, unknown=0, basis=0)
    restore_cost_pool(pool, 3, 0, 10)
    assert (pool.cost_known_qty, pool.cost_unknown_qty, pool.cost_basis_vnd) == (3, 0, 10)

