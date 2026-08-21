"""Invariants for ``pipeline.nullstat.window_statistic``, over generated populations.

Two properties, both of the form "the statistic is a function of the data and of nothing else":

* **a relabelling that swaps two wallets with equal scores moves nothing** — the statistic reads
  a wallet only through its precomputed ``(weight, value, buckets, basis)`` record, so exchanging
  the label between two wallets whose records are equal exchanges nothing. This is the property
  that makes the null's question the sharp one: the label is informative exactly to the extent
  the *scores* differ;
* **the caller's ordering is invisible** — of the sets, and of the score mapping's insertion
  order. At 38 digits each addition rounds, so this is made true by canonical ordering inside the
  module, not assumed.

The generated magnitudes are small on purpose — integer log weights, two-decimal buy qualities —
so every accumulation below is exact and both properties can be asserted as *equality* of the
full ``WindowScore``, not closeness. Rounding behaviour under permuted accumulation is the
module's own concern and is pinned by its canonical ordering, exercised in the second property.

``derandomize=True`` throughout: the house rule forbids unseeded randomness.
"""

from decimal import Decimal as D

from hypothesis import given, settings
from hypothesis import strategies as st

from contracts import MatchedSet, TokenAgeBucket
from scoring import BUCKET_ORDER, BucketBreakdown, WalletScore
from pipeline.nullstat import window_statistic

DETERMINISTIC = settings(derandomize=True, max_examples=60, deadline=None)


def wallet_score(wallet, total_weight, value):
    """A one-buy ``WalletScore``: all weight in bucket D, every dollar realized."""
    buckets = []
    for bucket in BUCKET_ORDER:
        if bucket is TokenAgeBucket.D:
            buckets.append(BucketBreakdown(
                bucket=bucket, n_buys=1, weight=total_weight,
                weight_share=D("1"), value=value,
            ))
        else:
            buckets.append(BucketBreakdown(
                bucket=bucket, n_buys=0, weight=D("0"), weight_share=D("0"), value=None,
            ))
    return WalletScore(
        wallet=wallet, n_buys=1, total_weight=total_weight, value=value,
        buckets=tuple(buckets), realized_usd=D("100"), marked_usd=D("0"),
        dead_usd=D("0"), basis_total_usd=D("100"),
    )


#: Integer log weights and two-decimal buy qualities: small enough that every product and sum in
#: the statistic is exact at 38 digits, so equal inputs give equal outputs bit for bit.
weights = st.integers(min_value=1, max_value=9).map(lambda n: D(n))
qualities = st.integers(min_value=-20, max_value=20).map(lambda k: D(k).scaleb(-2))


@st.composite
def populations(draw):
    """1-3 matched sets over distinct wallets, plus the score book covering every member.

    The first set's first control is forced to carry a copy of that set's selected record, so
    every drawn population contains the equal-score pair the swap property needs.
    """
    n_sets = draw(st.integers(min_value=1, max_value=3))
    sets = []
    scores = {}
    counter = 0
    for _ in range(n_sets):
        members = []
        for _ in range(1 + draw(st.integers(min_value=2, max_value=3))):
            counter += 1
            members.append("0x{:040x}".format(counter))
        for wallet in members:
            scores[wallet] = wallet_score(wallet, draw(weights), draw(qualities))
        sets.append(MatchedSet(selected=members[0], primary_controls=tuple(members[1:])))
    twin = sets[0].primary_controls[0]
    original = scores[sets[0].selected]
    scores[twin] = wallet_score(twin, original.total_weight, original.value)
    return tuple(sets), scores


@given(populations())
@DETERMINISTIC
def test_swapping_two_wallets_with_equal_scores_moves_nothing(population):
    sets, scores = population
    statistic = window_statistic(1, "leader", scores)
    swapped = (MatchedSet(
        selected=sets[0].primary_controls[0],
        primary_controls=(sets[0].selected,) + sets[0].primary_controls[1:],
    ),) + sets[1:]
    assert statistic(sets) == statistic(swapped)


@given(populations())
@DETERMINISTIC
def test_the_statistic_does_not_depend_on_the_callers_ordering(population):
    sets, scores = population
    forward = window_statistic(1, "leader", scores)(sets)
    backward = window_statistic(
        1, "leader", dict(reversed(list(scores.items())))
    )(tuple(reversed(sets)))
    assert forward == backward
