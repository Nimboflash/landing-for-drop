"""``pipeline.nullstat.window_statistic`` — the real §8.2 statistic, on numbers worked by hand.

Every expected value below is a literal, computed on paper before the implementation ran. Nothing
in this file recomputes an expression the implementation also computes.

**The population.** Six wallets, every buy in bucket D (so the first-hour numerator is zero and
the Edge Origin arithmetic stays on one line), every dollar realized. Per wallet, a total log
weight ``T`` and a buy quality ``v``::

    selected   0xs1  T=1  v=0.30      0xs2  T=1  v=0.10
    controls   0xc1  T=1  v=0.10      0xc2  T=3  v=0.02
               0xc3  T=1  v=0.00      0xc4  T=1  v=-0.10

Two matched sets: ``0xs1 -> (0xc1, 0xc2)`` and ``0xs2 -> (0xc3, 0xc4)``.

**The observed labelling, by hand.** The matched benchmark is the set's controls pooled by log
weight::

    set 1  benchmark = (1(0.10) + 3(0.02)) / 4 = 0.16/4 = 0.04    advantage = 0.30 - 0.04 = 0.26
    set 2  benchmark = (1(0.00) + 1(-0.10)) / 2 = -0.05           advantage = 0.10 + 0.05 = 0.15

    mean = (0.26 + 0.15)/2 = 0.205        median (even count) = (0.15 + 0.26)/2 = 0.205

Edge Origin, selected basket vs pooled benchmark, bucket D only::

    selected D value  = (1(0.30) + 1(0.10)) / 2 = 0.20        weight share = 1
    benchmark D value = (0.10 + 0.06 + 0.00 - 0.10) / 6 = 0.01
    contribution      = max(0, 1 x (0.20 - 0.01)) = 0.19  >= 0.05, first hour = 0, share = 0, VALID

**One relabelling, by hand.** Move the label onto ``0xc2`` in set 1 and ``0xc4`` in set 2::

    set 1  benchmark = (1(0.10) + 1(0.30)) / 2 = 0.20     advantage = 0.02 - 0.20 = -0.18
    set 2  benchmark = (1(0.00) + 1(0.10)) / 2 = 0.05     advantage = -0.10 - 0.05 = -0.15

    mean = -0.33/2 = -0.165               median = -0.165

    selected D value  = (3(0.02) + 1(-0.10)) / 4 = -0.01
    benchmark D value = (0.10 + 0.00 + 0.30 + 0.10) / 4 = 0.125
    contribution      = max(0, 1 x (-0.135)) = 0 < 0.05   ->  INDETERMINATE, share None

The relabelled window fails the gate at *any* threshold — which is the shape §8.2 wants a null
run to be able to take, and exactly what a mean-only statistic could never report.
"""

import hashlib
from decimal import Decimal as D

import pytest

from contracts import EdgeOriginStatus, MatchedSet, TokenAgeBucket, WindowScore
from matching_null import permutation_null_detail
from scoring import BUCKET_ORDER, BucketBreakdown, WalletScore
from pipeline.nullstat import window_statistic


def wallet_score(wallet, total_weight, value):
    """A one-buy ``WalletScore``: all weight in bucket D, every dollar realized."""
    buckets = []
    for bucket in BUCKET_ORDER:
        if bucket is TokenAgeBucket.D:
            buckets.append(BucketBreakdown(
                bucket=bucket, n_buys=1, weight=D(total_weight),
                weight_share=D("1"), value=D(value),
            ))
        else:
            buckets.append(BucketBreakdown(
                bucket=bucket, n_buys=0, weight=D("0"), weight_share=D("0"), value=None,
            ))
    return WalletScore(
        wallet=wallet, n_buys=1, total_weight=D(total_weight), value=D(value),
        buckets=tuple(buckets), realized_usd=D("100"), marked_usd=D("0"),
        dead_usd=D("0"), basis_total_usd=D("100"),
    )


def scores():
    return {
        "0xs1": wallet_score("0xs1", "1", "0.30"),
        "0xs2": wallet_score("0xs2", "1", "0.10"),
        "0xc1": wallet_score("0xc1", "1", "0.10"),
        "0xc2": wallet_score("0xc2", "3", "0.02"),
        "0xc3": wallet_score("0xc3", "1", "0.00"),
        "0xc4": wallet_score("0xc4", "1", "-0.10"),
    }


OBSERVED = (
    MatchedSet(selected="0xs1", primary_controls=("0xc1", "0xc2")),
    MatchedSet(selected="0xs2", primary_controls=("0xc3", "0xc4")),
)

RELABELLED = (
    MatchedSet(selected="0xc2", primary_controls=("0xs1", "0xc1")),
    MatchedSet(selected="0xc4", primary_controls=("0xs2", "0xc3")),
)


def seed_fn(purpose, index):
    message = "master|commit|{}|{}".format(purpose, index).encode("utf-8")
    return int.from_bytes(hashlib.sha256(message).digest(), "big")


# -- the literals ---------------------------------------------------------------


def test_the_observed_labelling_scores_the_hand_computed_window():
    score = window_statistic(1, "leader", scores())(OBSERVED)
    assert score == WindowScore(
        window=1,
        column="leader",
        mean_advantage=D("0.205"),
        median_advantage=D("0.205"),
        first_hour_edge_share=D("0"),
        positive_edge_contribution=D("0.19"),
        edge_origin_status=EdgeOriginStatus.VALID,
    )
    assert score.passes(D("0.20"))
    assert not score.passes(D("0.21"))


def test_a_relabelling_recomputes_the_whole_gate_not_just_the_mean():
    """The relabelled split goes INDETERMINATE: the total positive edge collapses below 5pp.

    This is the value of returning a ``WindowScore`` rather than a mean — the run fails the gate
    at any threshold, including thresholds its mean of -0.165 would sail past.
    """
    score = window_statistic(1, "leader", scores())(RELABELLED)
    assert score == WindowScore(
        window=1,
        column="leader",
        mean_advantage=D("-0.165"),
        median_advantage=D("-0.165"),
        first_hour_edge_share=None,
        positive_edge_contribution=D("0"),
        edge_origin_status=EdgeOriginStatus.INDETERMINATE,
    )
    assert not score.passes(D("-1"))


def test_the_benchmark_is_pooled_by_log_weight_not_averaged_per_wallet():
    """Set 1 pins the weighting: 0.04 pooled against 0.06 unweighted.

    ``(1(0.10) + 3(0.02))/4 = 0.04``, so the advantage is 0.26 and the mean 0.205. An unweighted
    mean of the two controls would give ``(0.10 + 0.02)/2 = 0.06``, advantage 0.24, mean 0.195 —
    a different published number from the same inputs, distinguishable only because the control
    weights here are unequal on purpose.
    """
    score = window_statistic(1, "leader", scores())(OBSERVED)
    assert score.mean_advantage == D("0.205")
    assert score.mean_advantage != D("0.195")


def test_the_permutation_machinery_accepts_this_statistic_and_shares_its_observed_score():
    """Wired through ``permutation_null_detail``: the observed score is the same literal.

    The observed statistic is the identity labelling through the same function as every run —
    §8.2's rule — so the machinery's ``observed`` must equal the hand-computed score, and every
    run must carry the column and window this statistic was built for (the machinery refuses
    anything else, so completing at all pins that).
    """
    detail = permutation_null_detail(
        OBSERVED, window_statistic(1, "leader", scores()), 5, seed_fn, "leader", 1,
    )
    assert detail.observed.mean_advantage == D("0.205")
    assert detail.observed.positive_edge_contribution == D("0.19")
    assert detail.n_runs == 5


# -- the guards, each pinned by deletion ----------------------------------------


def test_window_must_be_a_positive_int():
    with pytest.raises(ValueError):
        window_statistic(0, "leader", scores())
    with pytest.raises(ValueError):
        window_statistic(True, "leader", scores())


def test_the_column_is_one_of_the_two_preregistered():
    with pytest.raises(ValueError) as excinfo:
        window_statistic(1, "arbitrage", scores())
    assert "arbitrage" in str(excinfo.value)


def test_an_empty_score_book_is_refused():
    with pytest.raises(ValueError) as excinfo:
        window_statistic(1, "leader", {})
    assert "no per-wallet scores" in str(excinfo.value)


def test_a_callable_score_book_is_refused():
    with pytest.raises(TypeError):
        window_statistic(1, "leader", lambda wallet: None)


def test_a_non_string_score_key_is_refused():
    """One wallet is one entry, and that comparison has to be defined — so keys are strings."""
    book = scores()
    book[7] = wallet_score("0x07", "1", "0.10")
    with pytest.raises(TypeError) as excinfo:
        window_statistic(1, "leader", book)
    assert "address strings" in str(excinfo.value)


def test_a_score_that_is_not_a_walletscore_is_refused():
    """The seam's BuyQuality carries weight shares only; a basket cannot be pooled from shares."""
    book = scores()
    book["0xs1"] = book["0xs1"].quality
    with pytest.raises(TypeError) as excinfo:
        window_statistic(1, "leader", book)
    assert "BuyQuality" in str(excinfo.value)


def test_two_spellings_of_one_wallet_are_refused():
    """One wallet, one score — in any spelling, in either insertion order."""
    near = wallet_score("0xC1", "1", "0.10")
    far = wallet_score("0xc1", "1", "0.90")
    rest = {k: v for k, v in scores().items() if k != "0xc1"}
    for first, second in ((near, far), (far, near)):
        book = {first.wallet: first, second.wallet: second}
        book.update(rest)
        with pytest.raises(ValueError) as excinfo:
            window_statistic(1, "leader", book)
        assert "two ways" in str(excinfo.value)


def test_a_key_that_names_a_different_wallet_than_its_record_is_refused():
    """The mis-assembled join: every key well formed, one of them holding another's score."""
    book = scores()
    book["0xzz"] = book.pop("0xc1")
    with pytest.raises(ValueError) as excinfo:
        window_statistic(1, "leader", book)
    assert "0xzz" in str(excinfo.value)


def test_a_relabelled_wallet_with_no_score_is_refused_by_name():
    """A population mismatch is a defect in what assembled the call, not a zero-quality wallet."""
    statistic = window_statistic(1, "leader", scores())
    stranger = (MatchedSet(selected="0xs1", primary_controls=("0xc1", "0xdead")),)
    with pytest.raises(ValueError) as excinfo:
        statistic(stranger)
    assert "0xdead" in str(excinfo.value)


def test_no_sets_is_refused():
    with pytest.raises(ValueError) as excinfo:
        window_statistic(1, "leader", scores())(())
    assert "no matched sets" in str(excinfo.value)


def test_a_non_matchedset_is_refused():
    with pytest.raises(TypeError):
        window_statistic(1, "leader", scores())(("0xs1",))
