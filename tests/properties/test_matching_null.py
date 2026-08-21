"""Invariants for ``matching_null``, over generated universes and relabellings.

The two the pre-registration names explicitly:

* **the same seed and commit reproduce an identical distribution** — §9.6 puts the seed policy in
  the freeze manifest precisely so a run can be replayed on a machine that has never seen it;
* **permutation preserves membership** — the multiset of wallets is unchanged by relabelling.
  This is what separates a permutation null from a resampling one, and it is the property that
  makes the null's question the sharp one: the same six wallets are in the same set before and
  after, so nothing but the label has moved.

The rest are the ones a wrong implementation passes the hand-computed tests without violating: a
control that is also a selected wallet, a balance table computed over distinct controls rather
than control slots, an effective sample size that exceeds the number of slots, a percentile that
interpolates between two runs that never happened.

``derandomize=True`` throughout: the house rule forbids unseeded randomness, and a property suite
that fails only on Tuesdays is worse than none.
"""

import hashlib
from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from contracts import (
    MATCHING_DIMENSIONS,
    AccountType,
    EdgeOriginStatus,
    LookAheadViolation,
    WindowScore,
    divide,
    to_canonical_json,
)
from matching_null import (
    NULL_PASS_RATE_TARGET,
    NUMERIC_DIMENSIONS,
    PRIMARY_CONTROLS,
    MatchingInfeasible,
    ThresholdNotCalibrated,
    WalletFeatures,
    build_matched_sets,
    build_matched_sets_detail,
    calibrate_threshold,
    calibrate_threshold_detail,
    distance,
    effective_sample_size,
    empirical_p_value,
    mean_of,
    percentile_nearest_rank,
    permutation_null,
    permutation_null_detail,
    relabel,
    squared_distance,
    standardise,
    standardised_mean_difference,
    z_vector,
)

D = Decimal
DETERMINISTIC = settings(derandomize=True, max_examples=100, deadline=None)

T0_BLOCK = 18_000_000

#: Small integers. Large magnitudes are a separate concern — ``contracts.canonicalise`` normalises
#: at Python's default 28 digits, so a 33-digit feature value with a fractional part cannot be
#: serialized whatever this module does with it.
magnitudes = st.integers(min_value=0, max_value=200).map(lambda n: D(n))

account_types = st.sampled_from([AccountType.EOA, AccountType.SAFE, AccountType.ERC4337])


def wallet_address(index):
    return "0x{:040x}".format(index + 1)


@st.composite
def feature_records(draw, index, account_type=AccountType.EOA):
    values = {d: draw(magnitudes) for d in NUMERIC_DIMENSIONS}
    return WalletFeatures(
        wallet=wallet_address(index),
        account_type=account_type,
        values=values,
        as_of_block=draw(st.integers(min_value=1, max_value=T0_BLOCK - 1)),
    )


@st.composite
def universes(draw, min_size=12, max_size=22, max_selected=3, single_type=True):
    """A frozen T0 universe and a selection out of it, always leaving enough controls to match.

    ``single_type=True`` keeps every wallet the same account type so the exact-match caliper never
    starves the pool; the mixed-type case is exercised separately, where starvation is the point.
    """
    size = draw(st.integers(min_value=min_size, max_value=max_size))
    types = [
        AccountType.EOA if single_type else draw(account_types) for _ in range(size)
    ]
    records = {}
    for index in range(size):
        record = draw(feature_records(index, types[index]))
        records[record.wallet] = record

    n_selected = draw(st.integers(min_value=1, max_value=max_selected))
    chosen = draw(st.lists(
        st.sampled_from(sorted(records)), min_size=n_selected, max_size=n_selected, unique=True
    ))
    return sorted(records), records, chosen


def quality_of(wallet):
    """A deterministic per-wallet score. Pure, seeded by the address, no RNG."""
    digest = hashlib.sha256(wallet.encode("utf-8")).hexdigest()
    return D(int(digest[:4], 16) % 200) - D("100")


def make_statistic(column="leader", window=1):
    """A realistic ``statistic_fn``: mean and median buy-quality advantage over the sets."""

    def statistic(sets):
        advantages = [
            mean_of([quality_of(s.selected)]) - mean_of([quality_of(w) for w in s.primary_controls])
            for s in sets
        ]
        ordered = sorted(advantages)
        return WindowScore(
            window=window,
            column=column,
            mean_advantage=mean_of(advantages),
            median_advantage=ordered[len(ordered) // 2],
            first_hour_edge_share=D("0.2"),
            positive_edge_contribution=D("10"),
            edge_origin_status=EdgeOriginStatus.VALID,
        )

    return statistic


def seed_fn(purpose, index):
    message = "master|commit|{}|{}".format(purpose, index).encode("utf-8")
    return int.from_bytes(hashlib.sha256(message).digest(), "big")


def other_seed_fn(purpose, index):
    message = "other-master|commit|{}|{}".format(purpose, index).encode("utf-8")
    return int.from_bytes(hashlib.sha256(message).digest(), "big")


# -- matching -------------------------------------------------------------------


@given(universes())
@DETERMINISTIC
def test_every_matched_set_is_well_formed(universe):
    wallets, records, selected = universe
    result = build_matched_sets_detail(selected, wallets, records, T0_BLOCK, seed=1)

    selected_set = set(selected)
    for match in result.matches:
        controls = [c.wallet for c in match.primary]
        assert len(controls) == PRIMARY_CONTROLS
        assert len(set(controls)) == PRIMARY_CONTROLS, "a control cannot fill two slots in one set"
        assert match.selected not in controls
        # A selected wallet standing as someone's control would put the treatment group on both
        # sides of the contrast.
        assert not selected_set.intersection(controls)
        # Exact matching on the one categorical dimension.
        for control in controls:
            assert records[control].account_type is records[match.selected].account_type


@given(universes())
@DETERMINISTIC
def test_controls_are_the_nearest_available_ones(universe):
    """No candidate outside the chosen set is closer than the worst chosen one."""
    wallets, records, selected = universe
    result = build_matched_sets_detail(selected, wallets, records, T0_BLOCK, seed=1)
    standardisation = standardise([records[w] for w in sorted(wallets)])

    for match in result.matches:
        chosen = {c.wallet for c in match.primary} | {c.wallet for c in match.robustness}
        worst = max(c.squared_distance for c in match.primary)
        origin = z_vector(records[match.selected], standardisation)
        for candidate in wallets:
            if candidate in chosen or candidate in set(selected):
                continue
            if records[candidate].account_type is not records[match.selected].account_type:
                continue
            assert squared_distance(origin, z_vector(records[candidate], standardisation)) >= worst


@given(universes(), st.integers(min_value=0, max_value=2 ** 32))
@DETERMINISTIC
def test_matching_does_not_depend_on_the_order_the_caller_supplied(universe, seed):
    """Decimal addition is not associative at 38 digits, so this has to be made true, not assumed."""
    wallets, records, selected = universe
    forward = build_matched_sets(selected, wallets, records, T0_BLOCK, seed)[0]
    backward = build_matched_sets(
        list(reversed(selected)), list(reversed(wallets)), records, T0_BLOCK, seed
    )[0]

    assert forward == backward


@given(universes())
@DETERMINISTIC
def test_the_balance_table_covers_all_ten_dimensions_and_is_finite(universe):
    wallets, records, selected = universe
    _sets, balance = build_matched_sets(selected, wallets, records, T0_BLOCK, seed=1)

    assert set(balance.smd) == set(MATCHING_DIMENSIONS)
    for value in balance.smd.values():
        assert value.is_finite(), "an infinite SMD would compare False against every target"


@given(universes())
@DETERMINISTIC
def test_reuse_never_makes_the_benchmark_look_bigger_than_it_is(universe):
    wallets, records, selected = universe
    result = build_matched_sets_detail(selected, wallets, records, T0_BLOCK, seed=1)
    balance = result.balance
    slots = result.control_slots

    assert 1 <= balance.unique_controls <= slots
    assert D("0") <= balance.control_reuse_rate < D("1")
    assert D("1") <= balance.effective_sample_size <= slots
    # Kish's ESS equals the slot count exactly when no control is reused, and is strictly below it
    # otherwise. That equivalence is the whole reason it is reported.
    if balance.unique_controls == slots:
        assert balance.effective_sample_size == slots
        assert balance.control_reuse_rate == 0
    else:
        assert balance.effective_sample_size < slots
        assert balance.control_reuse_rate > 0


@given(universes(), st.integers(min_value=0, max_value=2 ** 32))
@DETERMINISTIC
def test_the_seed_changes_only_tie_breaking_never_the_distances(universe, seed):
    """Two seeds may pick different controls, but only from among equally close candidates."""
    wallets, records, selected = universe
    a = build_matched_sets_detail(selected, wallets, records, T0_BLOCK, seed)
    b = build_matched_sets_detail(selected, wallets, records, T0_BLOCK, seed + 1)

    assert [m.selected for m in a.matches] == [m.selected for m in b.matches]
    for left, right in zip(a.matches, b.matches):
        assert sorted(c.squared_distance for c in left.primary) == \
            sorted(c.squared_distance for c in right.primary)


@given(universes(min_size=8, max_size=14, max_selected=2, single_type=False))
@DETERMINISTIC
def test_a_starved_account_type_is_reported_or_refused_never_matched_across_types(universe):
    """§6.6 has ten dimensions; borrowing a control of another type would silently drop one."""
    wallets, records, selected = universe
    try:
        result = build_matched_sets_detail(selected, wallets, records, T0_BLOCK, seed=1)
    except MatchingInfeasible:
        return  # zero matched sets is a refusal, not an empty balanced table
    matched = {m.selected for m in result.matches}
    reported = {u.wallet for u in result.unmatched}
    assert matched | reported == set(selected)
    assert not matched & reported


@given(st.lists(magnitudes, min_size=1, max_size=8), st.lists(magnitudes, min_size=1, max_size=8))
@DETERMINISTIC
def test_the_standardised_mean_difference_is_zero_exactly_when_the_means_agree(left, right):
    smd = standardised_mean_difference(left, right, fallback_sd=D("1"))
    assert smd.is_finite()
    assert (smd == 0) == (mean_of(left) == mean_of(right))


@given(st.lists(st.integers(min_value=1, max_value=20), min_size=1, max_size=12))
@DETERMINISTIC
def test_effective_sample_size_is_bounded_by_the_slot_count(counts):
    slots = sum(counts)
    ess = effective_sample_size(counts)
    assert D("1") <= ess <= D(slots)
    assert (ess == D(slots)) == all(c == 1 for c in counts)


# -- distances ------------------------------------------------------------------


@given(
    st.lists(magnitudes, min_size=9, max_size=9),
    st.lists(magnitudes, min_size=9, max_size=9),
)
@DETERMINISTIC
def test_distance_is_a_metric_on_the_standardised_space(left, right):
    left, right = tuple(left), tuple(right)
    assert squared_distance(left, right) == squared_distance(right, left)
    assert squared_distance(left, right) >= 0
    assert (squared_distance(left, right) == 0) == (left == right)
    assert distance(left, right) >= 0


# -- the look-ahead trap --------------------------------------------------------


@given(universes(), st.integers(min_value=0, max_value=5))
@DETERMINISTIC
def test_any_feature_at_or_after_t0_is_refused(universe, offset):
    """``>=``: at T0 is a violation, because a feature computed at T0 has already seen T0."""
    wallets, records, selected = universe
    poisoned = dict(records)
    victim = wallets[0]
    poisoned[victim] = WalletFeatures(
        wallet=victim,
        account_type=records[victim].account_type,
        values=records[victim].values,
        as_of_block=T0_BLOCK + offset,
    )
    with pytest.raises(LookAheadViolation):
        build_matched_sets(selected, wallets, poisoned, T0_BLOCK, seed=1)


@given(universes(), st.sampled_from(MATCHING_DIMENSIONS))
@DETERMINISTIC
def test_one_forward_dimension_among_ten_is_enough_to_refuse(universe, dimension):
    wallets, records, selected = universe
    victim = wallets[-1]
    poisoned = dict(records)
    poisoned[victim] = WalletFeatures(
        wallet=victim,
        account_type=records[victim].account_type,
        values=records[victim].values,
        as_of_block=records[victim].as_of_block,
        dimension_blocks={dimension: T0_BLOCK},
    )
    with pytest.raises(LookAheadViolation) as excinfo:
        build_matched_sets(selected, wallets, poisoned, T0_BLOCK, seed=1)
    assert dimension in str(excinfo.value)


# -- the permutation ------------------------------------------------------------


@given(universes(), st.integers(min_value=0, max_value=2 ** 40))
@DETERMINISTIC
def test_relabelling_preserves_the_multiset_of_wallets(universe, seed):
    """The stated invariant. Nothing leaves a set and nothing joins one; only the label moves."""
    wallets, records, selected = universe
    sets, _balance = build_matched_sets(selected, wallets, records, T0_BLOCK, seed=1)

    before = sorted(w for s in sets for w in s.members)
    relabelling = relabel(sets, seed, run_index=0)

    assert sorted(relabelling.members()) == before
    for original, moved in zip(sets, relabelling.sets):
        assert sorted(moved.members) == sorted(original.members)
        assert moved.selected in original.members
        assert moved.selected not in moved.primary_controls
        assert moved.robustness_controls == original.robustness_controls


@given(universes(), st.integers(min_value=2, max_value=12))
@DETERMINISTIC
def test_the_same_seed_and_commit_reproduce_an_identical_distribution(universe, n_runs):
    """§9.6's whole purpose: a run replayable on a machine that has never seen it."""
    wallets, records, selected = universe
    sets, _balance = build_matched_sets(selected, wallets, records, T0_BLOCK, seed=1)
    statistic = make_statistic()

    first = permutation_null_detail(sets, statistic, n_runs, seed_fn, "leader", 1)
    second = permutation_null_detail(sets, statistic, n_runs, seed_fn, "leader", 1)

    assert first.statistics == second.statistics
    assert [r.chosen_positions for r in first.runs] == [r.chosen_positions for r in second.runs]
    assert first.to_contract() == second.to_contract()


@given(universes(), st.integers(min_value=2, max_value=12))
@DETERMINISTIC
def test_a_different_master_seed_gives_a_different_set_of_draws(universe, n_runs):
    """Otherwise the seed is decorative and the freeze manifest records nothing."""
    wallets, records, selected = universe
    sets, _balance = build_matched_sets(selected, wallets, records, T0_BLOCK, seed=1)
    statistic = make_statistic()

    mine = permutation_null_detail(sets, statistic, n_runs, seed_fn, "leader", 1)
    theirs = permutation_null_detail(sets, statistic, n_runs, other_seed_fn, "leader", 1)

    assert [r.seed for r in mine.runs] != [r.seed for r in theirs.runs]
    # The observed labelling is not a draw, so it must agree whatever the seed.
    assert mine.observed == theirs.observed


@given(universes(), st.integers(min_value=2, max_value=12))
@DETERMINISTIC
def test_the_observed_statistic_never_enters_the_null(universe, n_runs):
    wallets, records, selected = universe
    sets, _balance = build_matched_sets(selected, wallets, records, T0_BLOCK, seed=1)
    null = permutation_null_detail(sets, make_statistic(), n_runs, seed_fn, "leader", 1)

    assert len(null.statistics) == n_runs == null.to_contract().n_runs
    assert null.observed_statistic == null.to_contract().observed_statistic


@given(universes(), st.integers(min_value=2, max_value=12))
@DETERMINISTIC
def test_the_seam_wrapper_is_exactly_the_rich_result_reduced(universe, n_runs):
    """``permutation_null`` must add nothing of its own, or the two paths could disagree."""
    wallets, records, selected = universe
    sets, _balance = build_matched_sets(selected, wallets, records, T0_BLOCK, seed=1)
    statistic = make_statistic()

    assert permutation_null(sets, statistic, n_runs, seed_fn, "leader", 1) == \
        permutation_null_detail(sets, statistic, n_runs, seed_fn, "leader", 1).to_contract()


# -- percentile, p-value, calibration -------------------------------------------


@given(st.lists(magnitudes, min_size=1, max_size=40))
@DETERMINISTIC
def test_the_percentile_is_always_a_value_the_null_actually_produced(values):
    percentile = percentile_nearest_rank(values, D("0.95"))
    assert percentile in values
    assert sum(1 for v in values if v <= percentile) >= len(values) * D("0.95")


@given(st.lists(magnitudes, min_size=1, max_size=40), magnitudes)
@DETERMINISTIC
def test_the_empirical_p_value_is_never_zero_and_never_above_one(values, observed):
    """The floor is 1/(n+1) — computed with ``divide``, so it is the frozen policy's 1/(n+1).

    Written as ``1 / (Decimal(n) + 1)`` this assertion fails: Python's default context rounds
    1/6 up at the 28th digit while the module carries 38, so the hand-written bound comes out
    fractionally *above* the value it is bounding.
    """
    p = empirical_p_value(observed, values)
    assert D("0") < p <= D("1")
    assert p >= divide(1, len(values) + 1)


def null_from(means, statuses=None, medians=None, column="leader", window=1):
    from matching_null import NullDistribution, NullRun, null_purpose

    runs = []
    for index, mean in enumerate(means):
        status = EdgeOriginStatus.VALID if statuses is None else statuses[index]
        median = D("1") if medians is None else medians[index]
        runs.append(NullRun(
            index=index,
            seed=index + 1,
            chosen_positions=(0,),
            score=WindowScore(
                window=window,
                column=column,
                mean_advantage=mean,
                median_advantage=median,
                first_hour_edge_share=(
                    None if status is EdgeOriginStatus.INDETERMINATE else D("0.2")
                ),
                positive_edge_contribution=D("10"),
                edge_origin_status=status,
            ),
        ))
    return NullDistribution(
        column=column,
        window=window,
        purpose=null_purpose(column, window),
        observed=runs[0].score,
        runs=tuple(runs),
        n_runs=len(runs),
        reference_threshold=D("0"),
    )


@given(st.lists(magnitudes, min_size=1, max_size=30), magnitudes, magnitudes)
@DETERMINISTIC
def test_the_null_pass_rate_never_rises_as_the_threshold_rises(means, low, high):
    assume(low <= high)
    null = null_from(means)
    assert null.pass_rate(low) >= null.pass_rate(high)
    assert D("0") <= null.pass_rate(low) <= D("1")


@given(st.lists(magnitudes, min_size=1, max_size=30),
       st.lists(magnitudes, min_size=1, max_size=6))
@DETERMINISTIC
def test_a_calibrated_threshold_is_always_one_of_the_candidates_and_always_qualifies(
    means, candidates
):
    null = null_from(means)
    try:
        threshold = calibrate_threshold(null, candidates)
    except ThresholdNotCalibrated:
        # Every candidate leaves the null passing more than 5% of the time. A legitimate outcome
        # of too narrow a grid, and the one case where a number must not be returned.
        assert all(null.pass_rate(c) > NULL_PASS_RATE_TARGET for c in candidates)
        return

    assert threshold in candidates
    assert null.pass_rate(threshold) <= NULL_PASS_RATE_TARGET
    # "Smallest at which" — no smaller candidate may also qualify.
    assert all(
        null.pass_rate(c) > NULL_PASS_RATE_TARGET for c in candidates if c < threshold
    )
    # The report and the bare answer are the same calibration.
    report = calibrate_threshold_detail(null, candidates)
    assert report.threshold == threshold
    assert {r.threshold for r in report.rates} == set(candidates)


@given(st.lists(magnitudes, min_size=1, max_size=20))
@DETERMINISTIC
def test_extra_conditions_can_only_lower_the_pass_rate(means):
    """§8.2's reason for insisting on the full gate, stated as an inequality."""
    permissive = null_from(means)
    strict = null_from(
        means,
        statuses=[
            EdgeOriginStatus.VALID if i % 2 else EdgeOriginStatus.INDETERMINATE
            for i in range(len(means))
        ],
    )
    for threshold in (D("0"), D("50"), D("200")):
        assert strict.pass_rate(threshold) <= permissive.pass_rate(threshold)


# -- the seam -------------------------------------------------------------------


@given(universes())
@DETERMINISTIC
def test_every_output_survives_canonical_json(universe):
    wallets, records, selected = universe
    matching = build_matched_sets_detail(selected, wallets, records, T0_BLOCK, seed=1)
    null = permutation_null_detail(
        matching.sets, make_statistic(), 3, seed_fn, "leader", 1
    )

    for artifact in (matching.balance, matching.sets[0], null, null.to_contract()):
        assert to_canonical_json(artifact).startswith("{")
