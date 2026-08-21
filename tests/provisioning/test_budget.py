"""Budget arithmetic, against hand-computed literals.

Three digits and one addition, so the temptation is to assert nothing. The reason to assert
everything is that this is the number a human signs, and :class:`HumanApproval` binds the signature
to it — get the total wrong and the approval is either refused forever or, worse, given for a figure
nobody checked.

The arithmetic goes through :mod:`contracts.numeric` like every other number in this repository:
money is ``Decimal``, ``calc()`` rejects a float on sight, and the results below are written out as
literals rather than recomputed from the constants. A test that derives its expectation from the
code under test pins nothing — the marking module already learned that the expensive way (see
``docs/module-review.md``: every dead-pool test derived its timestamps from the constant, so the
suite moved with the constant instead of pinning it).
"""

from decimal import Decimal

import pytest

from tools.provisioning.budget import (
    BUDGET_LINES,
    CEILING_USD,
    BudgetLine,
    as_dict,
    headroom,
    priced_lines,
    projected_total,
    unpriced_sources,
    utilisation,
    within_ceiling,
)


# -- hand-computed ---------------------------------------------------------------

def test_projected_total_is_349_plus_129_plus_0():
    #   dune               349
    #   coingecko_onchain  129
    #   binance_klines       0
    #   archival_rpc     unpriced — contributes nothing, and is not a zero
    #   ------------------------
    #   total              478
    assert projected_total() == Decimal("478")


def test_headroom_is_1000_minus_478():
    assert CEILING_USD == Decimal("1000")
    assert headroom() == Decimal("522")


def test_utilisation_is_478_over_1000():
    assert utilisation() == Decimal("0.478")


def test_the_total_is_inside_the_ceiling():
    assert within_ceiling() is True


def test_money_is_decimal_never_float():
    for value in (projected_total(), headroom(), utilisation(), CEILING_USD):
        assert isinstance(value, Decimal)
        assert not isinstance(value, float)


# -- unpriced is not zero --------------------------------------------------------

def test_the_archival_rpc_is_unpriced_rather_than_free():
    """"—" and "$0" are different claims. $0 says someone checked; "—" says nobody bought."""
    assert unpriced_sources() == ("archival_rpc",)
    lines = {line.source: line for line in BUDGET_LINES}
    assert lines["archival_rpc"].monthly_usd is None
    assert lines["archival_rpc"].is_priced is False
    # Binance really is free, and says so with a number.
    assert lines["binance_klines"].monthly_usd == Decimal("0")
    assert lines["binance_klines"].is_priced is True


def test_an_unpriced_line_is_not_summed_as_zero():
    """The distinction has to survive the arithmetic, not just the docstring."""
    lines = (
        BudgetLine("priced", "100", "tier", "note"),
        BudgetLine("unpriced", None, "tier", "note"),
    )
    assert projected_total(lines) == Decimal("100")
    assert len(priced_lines(lines)) == 1
    assert unpriced_sources(lines) == ("unpriced",)


def test_a_total_over_the_ceiling_is_reported_as_over():
    lines = (BudgetLine("expensive", "1200", "tier", "note"),)
    assert projected_total(lines) == Decimal("1200")
    assert within_ceiling(lines) is False
    assert headroom(lines) == Decimal("-200")


# -- floats are refused ----------------------------------------------------------

def test_a_float_cost_is_refused_on_sight():
    with pytest.raises(TypeError) as excinfo:
        BudgetLine("dune", 349.0, "Plus", "note")
    assert "float is not permitted" in str(excinfo.value)


def test_a_float_ceiling_is_refused_on_sight():
    with pytest.raises(TypeError):
        within_ceiling(BUDGET_LINES, 1000.0)


# -- serialization ---------------------------------------------------------------

def test_the_serialized_budget_carries_strings_and_no_doubles():
    document = as_dict()
    assert document["projected_total"] == "478"
    assert document["headroom"] == "522"
    assert document["utilisation"] == "0.478"
    assert document["ceiling"] == "1000"
    assert document["currency"] == "USD"
    assert document["period"] == "monthly"
    assert document["within_ceiling"] is True
    assert document["unpriced_sources"] == ["archival_rpc"]
    for line in document["lines"]:
        assert not isinstance(line["monthly_usd"], float)
    assert [line["source"] for line in document["lines"]] == [
        "dune", "coingecko_onchain", "binance_klines", "archival_rpc"
    ]
