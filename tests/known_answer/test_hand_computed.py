"""Layer 1 — every case against the answer that was fixed before the code ran (§9.3).

Each of the sixteen is executed through the §4-order composition and compared, key by key, with
the literals in :mod:`tests.known_answer.battery`. Those literals were derived by evaluating the
pre-registered formulas directly; none was copied back from a test run, and the arithmetic behind
each is written out in the case's ``derivation``.

Beneath the sixteen sit the constants they stand on. Every one is pinned against an **absolute
literal** rather than against the module that defines it: a test asserting
``inactivity == DEAD_INACTIVITY_SECONDS`` moves with the constant and pins nothing about it, and
widening that window is the direction that flatters a rug.
"""

from decimal import Decimal

import pytest

from contracts import (
    FIRST_HOUR_BUCKETS,
    PoolStatus,
    QuarantineRequired,
    TokenAgeBucket,
    ValueBasis,
)
from marking import token_age_bucket
from marking.age import BUCKET_A_BLOCKS, DAY_SECONDS, HOUR_SECONDS
from marking.pools import (
    DEAD_INACTIVITY_SECONDS,
    MARKING_TOLERANCE,
    MINIMUM_EXIT_VALUE_USD,
    THIN_SHORTFALL_RATIO,
)
from netting import RESIDUAL_FLOOR_USD, RESIDUAL_NOTIONAL_RATE

from . import battery as B


def _describe(result):
    if result.error:
        return "{} raised {}".format(result.name, result.error)
    return "{} disagrees with its frozen answer:\n  {}".format(
        result.name, "\n  ".join(result.failures)
    )


# -- the sixteen ----------------------------------------------------------------


@pytest.mark.parametrize("case", B.BATTERY, ids=[c.name for c in B.BATTERY])
def test_case_matches_its_frozen_answer(case):
    """§9.3: 100% must pass, and no failure may be waived as an edge case.

    The comparison is two-sided. A key the pipeline stops producing fails the case, and so does a
    key it starts producing that nobody pre-registered — an answer that grew a field is an answer
    to a different question.
    """
    result = B.evaluate_case(case)
    assert result.passed, _describe(result)


@pytest.mark.parametrize("case", B.BATTERY, ids=[c.name for c in B.BATTERY])
def test_case_shows_its_arithmetic(case):
    """A frozen answer with no derivation can only be re-run, never checked."""
    assert len(case.derivation) >= 3, (
        "{}: the derivation is {} line(s). Show the arithmetic that produces the expected "
        "values, or a reviewer has to trust the number.".format(case.name, len(case.derivation))
    )
    assert case.spec.startswith("§"), (
        "{}: name the pre-registration section the answer comes from".format(case.name)
    )


# -- the constants the cases stand on -------------------------------------------


def test_the_thirty_day_horizon_is_2_592_000_seconds():
    """§4.4 measures the return over the following 30 days. 30 x 86,400."""
    assert B.HORIZON_SECONDS == 2_592_000
    assert B.DAY_SECONDS == 86_400
    assert B.HOUR_SECONDS == 3_600


def test_the_dead_inactivity_window_is_exactly_thirty_days():
    """Addendum §9.1 condition 1, as an absolute literal.

    Widening this is the Dune-flattering direction: a rugged token stays marked at its dust value
    instead of being zeroed, and every wallet that bought garbage looks better for it.
    """
    assert DEAD_INACTIVITY_SECONDS == 2_592_000


def test_the_minimum_exit_and_the_two_shortfall_lines_are_pinned():
    assert MINIMUM_EXIT_VALUE_USD == Decimal("1.00")
    assert MARKING_TOLERANCE == Decimal("0.005")
    assert THIN_SHORTFALL_RATIO == Decimal("0.10")


def test_the_residual_tolerance_shape_is_pinned():
    """Addendum §8: ``max($0.01, 0.01% of notional)``. Both arms, as literals."""
    assert RESIDUAL_FLOOR_USD == Decimal("0.01")
    assert RESIDUAL_NOTIONAL_RATE == Decimal("0.0001")


def test_the_bucket_boundaries_are_pinned():
    """§4.7: first 10 blocks, end of hour 1, end of hour 24 — and the first hour is A plus B."""
    assert BUCKET_A_BLOCKS == 10
    assert HOUR_SECONDS == 3_600
    assert DAY_SECONDS == 86_400
    assert tuple(FIRST_HOUR_BUCKETS) == (TokenAgeBucket.A, TokenAgeBucket.B)


# -- the three ways the dead conjunction must NOT fire --------------------------
#
# Cases 6 and 14 each close one leg of §9.1: case 6's control breaks condition 1 by a single
# second, case 14's replacement breaks condition 3. The third leg is closed here. Together they
# say that no *one* condition zeroes a position — which is the whole content of a conjunction, and
# the thing a guard written against a single traced example would miss.


def test_a_pool_silent_for_thirty_days_is_quiet_and_not_dead_while_it_can_still_be_exited():
    """Condition 1 holds, condition 3 holds, condition 2 does not. Nothing is zeroed.

    The pool has $2,000 of quote against the same reserves as case 5 and has not traded for
    exactly 30 days. A 1,000e18 position exits for $1.9920139620798064329863126462916472277 —
    above the $1.00 minimum by less than a dollar, which is the interesting side of the line.
    """
    quiet = B.pool(
        B.POOL_A, B.OPEN_POOL_ASSET_RESERVE, B.BOUND_POOL_QUOTE_RESERVE,
        last_swap_block=B.HORIZON_BLOCK - B.BLOCKS_PER_30_DAYS,
        last_swap_timestamp=B.HORIZON_TS - B.HORIZON_SECONDS,
    )
    value = B.stage_mark(B.OPEN_POSITION_RAW, quiet)

    assert value.pool_status is PoolStatus.QUIET
    assert value.value_basis is ValueBasis.POOL_MARKED
    assert value.value_usd == Decimal("1.9920139620798064329863126462916472277")
    assert value.executable_quantity == B.OPEN_POSITION_RAW
    assert "cond1_no_swap_for_30d=true" in value.evidence
    assert "cond2_exit_below_minimum=false" in value.evidence
    assert "cond3_no_validated_replacement=true" in value.evidence
    assert "dead_pool=false" in value.evidence


# -- the age derivation must refuse rather than default -------------------------


def test_a_trade_before_the_trading_start_is_quarantined_not_bucketed():
    """§4.7. A buy cannot predate first usable liquidity.

    Returning bucket A would hand the wallet a first-hour purchase it never made, and first-hour
    share is exactly what the Edge Origin condition is trying to measure.
    """
    with pytest.raises(QuarantineRequired):
        token_age_bucket(
            B.TOKEN_START_BLOCK - 1, B.TOKEN_START_TS,
            B.TOKEN_START_BLOCK, B.TOKEN_START_TS,
        )
    with pytest.raises(QuarantineRequired):
        token_age_bucket(
            B.TOKEN_START_BLOCK, B.TOKEN_START_TS - 1,
            B.TOKEN_START_BLOCK, B.TOKEN_START_TS,
        )
