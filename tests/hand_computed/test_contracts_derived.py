"""Hand-computed values for the seam's two derived fields.

These exist because the mutation harness found a hole: **nothing in the repository asserted what
``CopySimulation.fill_ratio`` actually computes.** Swapping its numerator and denominator, and
replacing the numerator with ``intended - filled``, both survived the entire 703-test suite.

The near-misses are instructive about why a hole like that persists:

* ``test_shared_purity`` proves ``fill_ratio`` is pure algebra — but deliberately never asks what
  the algebra *says*. It checks the shape of the expression, not its meaning.
* ``test_depth`` asserts on ``OrderBookFill.fill_ratio`` — an identically named field on a
  different type.
* ``test_gate_validation`` recomputes its own ratio from an artifact payload rather than reading
  the property.

Three tests mention the name, none pin the value. That is the shape of a coverage gap that a
coverage percentage will not show you.

Values below are hand-computed and written as literals, at the frozen 38-digit precision. They are
not obtained by re-running the implementation: a test that recomputes the implementation cannot
detect the implementation.
"""

from decimal import Decimal as D

import pytest

from contracts import (
    AssetTier,
    ClassificationStatus,
    CopySimulation,
    LotConsumption,
    NetTradeResult,
)


def _trade(tx="0x1"):
    return NetTradeResult(
        tx, "0xowner", ClassificationStatus.VALID_BUY,
        sold_asset="0xquote", bought_asset="0xasset",
        sold_raw_amount=1, bought_raw_amount=1, quote_asset="0xquote",
    )


def _sim(intended, filled, **kw):
    return CopySimulation(
        capital_level=D("1000000"),
        tier=kw.pop("tier", AssetTier.MAJOR),
        intended_order_usd=D(intended),
        filled_order_usd=D(filled),
        execution_cost_pct=D("0.005"),
        follower_return=kw.pop("follower_return", D("0.1")),
        copyable=kw.pop("copyable", True),
        **kw,
    )


# -- fill_ratio -----------------------------------------------------------------


@pytest.mark.parametrize("intended,filled,expected", [
    # A full fill is exactly 1, not 0.999...
    ("100", "100", "1"),
    # 90/100. The §9.4 threshold sits here, so the value must be exact.
    ("100", "90", "0.9"),
    # 1/3 — no exact decimal form, so this pins the frozen precision: 38 significant digits.
    ("300", "100", "0.33333333333333333333333333333333333333"),
    # Zero fill is a real outcome: the order was placed and nothing came back.
    ("100", "0", "0"),
    # Asymmetric, to catch a numerator/denominator swap. 250/1000 = 0.25; swapped it would be 4.
    ("1000", "250", "0.25"),
])
def test_fill_ratio_is_filled_over_intended(intended, filled, expected):
    sim = _sim(intended, filled, copyable=(D(filled) > 0),
               follower_return=D("0.1") if D(filled) > 0 else None,
               rejection_reason=None if D(filled) > 0 else "nothing filled")
    assert sim.fill_ratio == D(expected)


def test_fill_ratio_direction_is_pinned_not_merely_exercised():
    """Kills the two mutations that survived the 703-test suite.

    Swapped numerator/denominator would give 4; ``intended - filled`` would give 0.75. Both are
    plausible-looking ratios, which is exactly why neither was caught.
    """
    sim = _sim("1000", "250")

    assert sim.fill_ratio == D("0.25")
    assert sim.fill_ratio != D("4")        # numerator and denominator swapped
    assert sim.fill_ratio != D("0.75")     # numerator becomes intended - filled


def test_fill_ratio_is_not_quantized():
    """A two-decimal quantization would round 1/3 to 0.33 and pass a careless equality."""
    sim = _sim("300", "100")
    assert sim.fill_ratio != D("0.33")
    assert len(sim.fill_ratio.as_tuple().digits) > 30


# -- realized_return ------------------------------------------------------------


@pytest.mark.parametrize("cost,proceeds,expected", [
    ("100", "120", "0.2"),
    ("100", "100", "0"),
    ("100", "50", "-0.5"),
    ("100", "0", "-1"),          # total loss is exactly -1
    ("600", "800", "0.3333333333333333333333333333333333333"),   # 4/3 - 1, 37 digits after the point
    ("900", "750", "-0.16666666666666666666666666666666666667"), # 5/6 - 1, 38 digits, HALF_EVEN
])
def test_realized_return_is_proceeds_over_cost_minus_one(cost, proceeds, expected):
    c = LotConsumption(_trade(), _trade("0x2"), 100, D(cost), D(proceeds))
    assert c.realized_return == D(expected)


def test_realized_return_holds_the_frozen_precision():
    """The regression this file's sibling fix was for.

    ``divide(...) - Decimal("1")`` truncated to the ambient 28 digits because only the division
    ran under the frozen context. It looked entirely reasonable, which is why it shipped.
    """
    c = LotConsumption(_trade(), _trade("0x2"), 100, D("600"), D("800"))

    assert len(c.realized_return.as_tuple().digits) == 37
    assert c.realized_return != D("0.3333333333333333333333333333")  # the 28-digit truncation


def test_realized_return_direction_is_pinned():
    """A swapped numerator/denominator gives 0.75 - 1 = -0.25 on a profitable trade."""
    c = LotConsumption(_trade(), _trade("0x2"), 100, D("400"), D("500"))

    assert c.realized_return == D("0.25")
    assert c.realized_return != D("-0.2")   # cost/proceeds - 1
    assert c.realized_return != D("1.25")   # the -1 dropped


# -- canonical form must not depend on ambient state ----------------------------


def test_canonical_form_is_invariant_to_the_ambient_decimal_context():
    """The property the whole artifact-verification design rests on.

    ``normalize()`` and ``quantize()`` respect the *ambient* decimal context, so before this was
    pinned the canonical bytes — and therefore ``canonical_hash`` — moved with a global the seam
    does not control:

        ambient prec  9  ->  0.769230769                               hash 838b8a22...
        ambient prec 28  ->  0.7692307692307692307692307692            hash e6e2cc34...
        ambient prec 38  ->  0.76923076923076923076923076923076923077  hash 6ea083a1...

    §9.6 records that hash in the freeze manifest, and ``gate_validation`` uses it to verify an
    artifact it deliberately refuses to import. A hash that moves with an ambient global would let
    a correct artifact fail verification, or make a re-run under a different context look like a
    different experiment.
    """
    from decimal import localcontext

    from contracts import canonical_hash, canonicalise, divide

    value = divide(D("10"), D("13"))
    forms = set()
    hashes = set()

    for precision in (9, 20, 28, 38, 60, 120):
        with localcontext() as ctx:
            ctx.prec = precision
            forms.add(canonicalise(value))
            hashes.add(canonical_hash(value))

    assert forms == {"0.76923076923076923076923076923076923077"}
    assert len(hashes) == 1


def test_canonical_form_keeps_the_full_frozen_precision():
    """A 38-digit value must not be silently shortened at the reporting boundary.

    The numeric policy permits quantization only through the ``quantize_*`` helpers. Losing ten
    digits inside ``canonicalise`` would be a quantization nobody asked for, applied to the value
    the freeze manifest hashes.
    """
    from contracts import canonicalise, divide

    rendered = canonicalise(divide(D("10"), D("13")))

    assert rendered == "0.76923076923076923076923076923076923077"
    assert len(rendered.replace("0.", "")) == 38


def test_cosmetic_scale_still_collapses():
    """Identity ignores trailing zeros — that part was already right and must stay right."""
    from contracts import canonical_hash, canonicalise

    assert canonicalise(D("2")) == canonicalise(D("2.00")) == "2"
    assert canonical_hash(D("2")) == canonical_hash(D("2.00"))
