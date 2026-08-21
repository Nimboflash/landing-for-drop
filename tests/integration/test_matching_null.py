"""The §8.4 sequence end to end, on universes shaped like the ones the pipeline will meet.

    frozen T0 universe -> matched sets -> permutation null -> calibrated threshold -> artifact

Two scenarios are run through it, and the contrast between them is the point of the whole design:

* a **skilled** cohort, whose selected wallets really do out-perform their own matched controls.
  The observed statistic sits outside the null and the result is significant.
* a **placebo** cohort, drawn from the same high-activity population as its controls, which beats
  a naive random basket handsomely and beats its matched controls not at all. This is the June
  2026 arXiv:2607.02795 shape — "skilled" cohorts at +132.3% against activity-matched placebos at
  +216.3% — and a random-basket null certifies it. The permutation null does not.

Seeds come from the real §9.6 derivation in ``phase0.seeds``, injected as ``seed_fn``. The module
under test never imports it; this file does, which is what makes the composition an integration
test rather than another unit one.
"""

from decimal import Decimal

import pytest

from contracts import (
    AccountType,
    EdgeOriginStatus,
    SMD_BALANCE_TARGET,
    WindowScore,
    artifact_envelope,
    canonical_hash,
    divide,
    to_canonical_json,
)
from matching_null import (
    NULL_RUNS,
    NUMERIC_DIMENSIONS,
    WalletFeatures,
    build_matched_sets_detail,
    calibrate_threshold,
    calibrate_threshold_detail,
    mean_of,
    permutation_null,
    permutation_null_detail,
)
from phase0.seeds import derive_child_seed, new_master_seed

D = Decimal

#: Window 1 of §6.3: train Jan-Jun 2023, test Jul-Dec 2023. T0 is the boundary.
T0_BLOCK = 17_500_000
T0_TS = 1_688_169_600

MASTER_SEED = new_master_seed(entropy="phase0-matching-null-integration")
COMMIT = "bf97b00cafe"

#: §7.1 condition 3: first-hour edge share above this is UNCOPYABLE_DOMINATED, a hard failure.
FIRST_HOUR_LIMIT = D("0.40")
#: §7.1's small-denominator guard, in percentage points.
MINIMUM_POSITIVE_EDGE = D("5")

#: Within a cluster: the selected wallet at 0 and five controls whose offsets sum to zero, so a
#: perfectly matched design produces an exactly zero standardised mean difference and the balance
#: table is verifiable by inspection rather than by tolerance.
NEAR_OFFSETS = (-2, -1, 1, 2, 0)
#: No far offset may share a magnitude with a near one, and none may be zero. A second wallet at
#: offset 0 would tie the near one at distance 0, the tie-break would decide which of them is
#: *primary*, and the primary offsets would then sum to +/-2 instead of 0 — a small imbalance
#: arriving from nowhere but the seed.
FAR_OFFSETS = (-52, -51, 51, 52, 60)


def seed_fn(purpose, index):
    """The §9.6 derivation, injected. HMAC over the master seed, keyed by commit and purpose."""
    return derive_child_seed(MASTER_SEED, COMMIT, purpose, index)


def wallet_features(wallet, base, offset, account_type=AccountType.EOA):
    """A pre-T0 feature record on the ten §6.6 dimensions.

    ``base`` sets the wallet's activity cluster; ``offset`` is the within-cluster jitter. Both are
    applied to every numeric dimension, so matching is genuinely nine-dimensional rather than a
    one-dimensional sort wearing nine labels.
    """
    values = {}
    for position, dimension in enumerate(NUMERIC_DIMENSIONS):
        values[dimension] = D(base * (position + 1) + offset)
    return WalletFeatures(
        wallet=wallet,
        account_type=account_type,
        values=values,
        as_of_block=T0_BLOCK - 1_000,
        as_of_timestamp=T0_TS - 3_600,
    )


def clustered_universe(n_clusters=6, account_type=AccountType.EOA):
    """``n_clusters`` tight activity clusters of eleven wallets each: one selected, ten controls.

    The five near controls become the primary set and the five far ones the robustness set, and
    both groups' offsets sum to zero, so the selected wallet sits exactly at its controls' mean on
    every dimension.
    """
    records = {}
    selected = []
    for cluster in range(n_clusters):
        base = 100 * (cluster + 1)
        leader = "0xlead{:02d}".format(cluster)
        records[leader] = wallet_features(leader, base, 0, account_type)
        selected.append(leader)
        for index, offset in enumerate(NEAR_OFFSETS):
            wallet = "0xnear{:02d}{:02d}".format(cluster, index)
            records[wallet] = wallet_features(wallet, base, offset, account_type)
        for index, offset in enumerate(FAR_OFFSETS):
            wallet = "0xfar{:02d}{:02d}".format(cluster, index)
            records[wallet] = wallet_features(wallet, base, offset, account_type)
    return records, selected


def dormant_wallets(records, n=20):
    """Low-activity addresses: in the frozen universe, never anyone's control.

    They are what a naive Random Active Wallets basket would draw. §6.6 keeps that basket as a
    sanity floor and forbids measuring any threshold against it, and these wallets are why.
    """
    dormant = []
    for index in range(n):
        wallet = "0xdorm{:03d}".format(index)
        records[wallet] = wallet_features(wallet, 1, index % 3)
        dormant.append(wallet)
    return dormant


def median_of(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return mean_of([ordered[middle - 1], ordered[middle]])


def make_statistic(quality, first_hour_fraction=D("0.25"), column="leader", window=1):
    """Recompute the whole §7.1 gate on a labelled population.

    This is the caller's job, not the null's — but it has to be the *full* gate, so the small
    denominator guard and the first-hour ceiling are implemented here rather than assumed away.
    A null scored on the mean alone would put its 95th percentile in a different experiment.
    """

    def statistic(sets):
        advantages = []
        for matched in sets:
            controls = mean_of([quality[w] for w in matched.primary_controls])
            advantages.append(quality[matched.selected] - controls)

        positive = sum((a for a in advantages if a > 0), D("0"))
        if positive < MINIMUM_POSITIVE_EDGE:
            # §7.1: edge origin cannot be measured, so the window fails. Not a pass, and not a
            # zero share — the share is None, and WindowScore refuses to carry one.
            status = EdgeOriginStatus.INDETERMINATE
            share = None
        else:
            share = first_hour_fraction
            status = (
                EdgeOriginStatus.VALID if share <= FIRST_HOUR_LIMIT
                else EdgeOriginStatus.UNCOPYABLE_DOMINATED
            )

        return WindowScore(
            window=window,
            column=column,
            mean_advantage=mean_of(advantages),
            median_advantage=median_of(advantages),
            first_hour_edge_share=share,
            positive_edge_contribution=positive,
            edge_origin_status=status,
        )

    return statistic


def quality_map(records, selected, skill_bonus=D("0"), dormant=()):
    """Post-T0 buy quality per wallet, in percentage points.

    Deliberately built *after* matching and never fed back into it: §6.4 reports post-T0 activity
    as an output and forbids using it as a selection filter, and this is the value that would
    invalidate everything if it leaked into a feature.
    """
    quality = {}
    for index, wallet in enumerate(sorted(records)):
        # A deterministic spread across the active population, so the null has something to
        # distribute rather than two point masses.
        quality[wallet] = D(index % 7) * D("4") - D("10")
    for wallet in dormant:
        quality[wallet] = D("-8")
    for wallet in selected:
        quality[wallet] = quality[wallet] + skill_bonus
    return quality


# -- the matching step ----------------------------------------------------------


def test_a_well_specified_universe_matches_inside_the_balance_target():
    """§6.6: absolute SMD below 0.10 on all ten dimensions, and here exactly zero.

    Each selected wallet's five primary controls have offsets summing to zero on every dimension,
    so the group means coincide and the standardised difference is 0 rather than merely small.
    """
    records, selected = clustered_universe()
    dormant_wallets(records)

    result = build_matched_sets_detail(
        selected, sorted(records), records, T0_BLOCK, seed=99,
        t0_timestamp=T0_TS,
    )

    assert len(result.matches) == 6
    assert result.unmatched == ()
    assert result.balance.balanced is True
    for dimension, value in result.balance.smd.items():
        assert abs(value) < SMD_BALANCE_TARGET, dimension
    assert result.balance.smd["capital_deployed"] == 0
    assert result.balance.unique_controls == 30
    assert result.balance.control_reuse_rate == 0
    assert result.balance.effective_sample_size == 30


def test_the_five_robustness_controls_are_reported_alongside_and_are_the_farther_ones():
    """§6.6: five more, reported, unable to change the gate."""
    records, selected = clustered_universe()
    result = build_matched_sets_detail(
        selected, sorted(records), records, T0_BLOCK, seed=99, t0_timestamp=T0_TS
    )

    match = result.matches[0]
    assert all(c.wallet.startswith("0xnear00") for c in match.primary)
    assert all(c.wallet.startswith("0xfar00") for c in match.robustness)
    assert min(c.distance for c in match.robustness) > max(c.distance for c in match.primary)
    assert result.robustness_balance is not None
    assert result.robustness_balance.unique_controls == 30


def test_dormant_wallets_stay_in_the_frozen_universe_but_never_become_controls():
    """§6.4 keeps them; §6.6's distance keeps them out of the benchmark."""
    records, selected = clustered_universe()
    dormant = dormant_wallets(records)

    result = build_matched_sets_detail(
        selected, sorted(records), records, T0_BLOCK, seed=99, t0_timestamp=T0_TS
    )
    chosen = {c.wallet for m in result.matches for c in m.primary}

    assert result.universe_size == 66 + len(dormant)
    assert not chosen.intersection(dormant)


# -- the null -------------------------------------------------------------------


def test_a_real_edge_clears_its_own_null():
    """A cohort that genuinely beats its matched controls lands outside the null distribution."""
    records, selected = clustered_universe()
    result = build_matched_sets_detail(
        selected, sorted(records), records, T0_BLOCK, seed=99, t0_timestamp=T0_TS
    )
    quality = quality_map(records, selected, skill_bonus=D("30"))

    null = permutation_null_detail(
        result.sets, make_statistic(quality), 500, seed_fn, "leader", 1
    )

    assert null.observed_statistic > null.percentile_95
    assert null.empirical_p <= D("0.05")
    assert null.to_contract().significant is True


def test_the_activity_matched_placebo_does_not_clear_its_null():
    """The June 2026 shape: a naive basket comparison says skill, the permutation null says no.

    The selected wallets here have no bonus at all — they are ordinary members of a high-activity
    population. Against a random basket of dormant addresses they look outstanding. Against the
    controls they were matched to, they look like what they are.
    """
    records, selected = clustered_universe()
    dormant = dormant_wallets(records)
    result = build_matched_sets_detail(
        selected, sorted(records), records, T0_BLOCK, seed=99, t0_timestamp=T0_TS
    )
    quality = quality_map(records, selected, skill_bonus=D("0"), dormant=dormant)

    naive_basket_advantage = mean_of([quality[w] for w in selected]) - mean_of(
        [quality[w] for w in dormant]
    )
    null = permutation_null_detail(
        result.sets, make_statistic(quality), 500, seed_fn, "leader", 1
    )

    # The blunt comparison is emphatic, and worthless.
    assert naive_basket_advantage > D("5")
    # The sharp one is not.
    assert null.observed_statistic <= null.percentile_95
    assert null.empirical_p > D("0.05")
    assert null.to_contract().significant is False


def test_the_pre_registered_thousand_runs_reproduce_from_master_seed_and_commit():
    """§8.2's 1,000 runs per window per column, and §9.6's replayability."""
    records, selected = clustered_universe()
    result = build_matched_sets_detail(
        selected, sorted(records), records, T0_BLOCK, seed=99, t0_timestamp=T0_TS
    )
    quality = quality_map(records, selected, skill_bonus=D("30"))
    statistic = make_statistic(quality)

    first = permutation_null_detail(result.sets, statistic, NULL_RUNS, seed_fn, "leader", 1)
    replay = permutation_null_detail(result.sets, statistic, NULL_RUNS, seed_fn, "leader", 1)

    assert first.n_runs == 1000
    assert first.purpose == "null.leader.window1"
    assert first.statistics == replay.statistics
    assert canonical_hash(first.to_contract()) == canonical_hash(replay.to_contract())
    # The seeds really are the injected derivation's, at the pre-registered purpose and indices.
    assert first.runs[0].seed == derive_child_seed(MASTER_SEED, COMMIT, "null.leader.window1", 0)
    assert first.runs[999].seed == derive_child_seed(
        MASTER_SEED, COMMIT, "null.leader.window1", 999
    )


def test_a_different_commit_is_a_different_experiment():
    """§9.6 makes the commit an input on purpose: a re-run after an invalidation is a new draw."""
    records, selected = clustered_universe()
    result = build_matched_sets_detail(
        selected, sorted(records), records, T0_BLOCK, seed=99, t0_timestamp=T0_TS
    )
    statistic = make_statistic(quality_map(records, selected, skill_bonus=D("30")))

    def patched_seed_fn(purpose, index):
        return derive_child_seed(MASTER_SEED, "deadbeef99", purpose, index)

    mine = permutation_null_detail(result.sets, statistic, 200, seed_fn, "leader", 1)
    theirs = permutation_null_detail(result.sets, statistic, 200, patched_seed_fn, "leader", 1)

    assert [r.seed for r in mine.runs] != [r.seed for r in theirs.runs]
    assert mine.observed == theirs.observed


def test_each_window_and_column_draws_its_own_seeds():
    """§8.2: 1,000 runs *per window per column*, from distinct purposes."""
    records, selected = clustered_universe()
    result = build_matched_sets_detail(
        selected, sorted(records), records, T0_BLOCK, seed=99, t0_timestamp=T0_TS
    )
    quality = quality_map(records, selected, skill_bonus=D("30"))

    seeds = {}
    for column in ("leader", "follower_adjusted"):
        for window in (1, 2, 3, 4):
            null = permutation_null_detail(
                result.sets,
                make_statistic(quality, column=column, window=window),
                20, seed_fn, column, window,
            )
            assert null.purpose == "null.{}.window{}".format(column, window)
            seeds[(column, window)] = [r.seed for r in null.runs]

    flattened = [s for run_seeds in seeds.values() for s in run_seeds]
    assert len(set(flattened)) == len(flattened), "seeds collided across windows or columns"


# -- calibration ----------------------------------------------------------------


def test_the_threshold_is_calibrated_against_the_full_gate_and_then_locked():
    """§8.3, on a real null rather than a constructed one."""
    records, selected = clustered_universe()
    result = build_matched_sets_detail(
        selected, sorted(records), records, T0_BLOCK, seed=99, t0_timestamp=T0_TS
    )
    quality = quality_map(records, selected, skill_bonus=D("30"))
    null = permutation_null_detail(
        result.sets, make_statistic(quality), 500, seed_fn, "leader", 1
    )

    candidates = [D(v) for v in ("5", "10", "15", "20", "24", "30")]
    report = calibrate_threshold_detail(null, candidates)

    assert report.threshold == calibrate_threshold(null, candidates)
    assert report.threshold in candidates
    assert null.pass_rate(report.threshold) <= D("0.05")
    # Monotone by construction, and worth asserting on a real distribution rather than a
    # hand-built one: a non-monotone rate would mean the gate is not a conjunction.
    rates = [r.pass_rate for r in report.rates]
    assert rates == sorted(rates, reverse=True)
    # The observed result must clear the threshold it was calibrated against for the window to
    # pass §7.1 condition 1 at all.
    assert null.observed.passes(report.threshold) is True


def test_the_null_can_refuse_to_calibrate_rather_than_invent_a_threshold():
    """A grid that never holds the null at 5% yields no threshold, not the largest candidate."""
    from matching_null import ThresholdNotCalibrated

    records, selected = clustered_universe()
    result = build_matched_sets_detail(
        selected, sorted(records), records, T0_BLOCK, seed=99, t0_timestamp=T0_TS
    )
    quality = quality_map(records, selected, skill_bonus=D("30"))
    null = permutation_null_detail(
        result.sets, make_statistic(quality), 200, seed_fn, "leader", 1
    )

    with pytest.raises(ThresholdNotCalibrated):
        calibrate_threshold(null, [D("-1000")])


# -- artifacts ------------------------------------------------------------------


def test_the_whole_chain_serialises_into_a_stable_artifact():
    """``gate_validation`` reads these files and never imports the code that wrote them."""
    records, selected = clustered_universe()
    result = build_matched_sets_detail(
        selected, sorted(records), records, T0_BLOCK, seed=99, t0_timestamp=T0_TS
    )
    quality = quality_map(records, selected, skill_bonus=D("30"))
    null_result = permutation_null(
        result.sets, make_statistic(quality), 200, seed_fn, "leader", 1
    )

    envelope = artifact_envelope(
        kind="matching_null.window1.leader",
        produced_by="matching_null",
        payload={
            "balance": result.balance,
            "sets": result.sets,
            "null": null_result,
            "seed": result.seed,
            "t0_block": result.t0_block,
        },
    )

    assert envelope["payload_hash"] == artifact_envelope(
        kind="matching_null.window1.leader",
        produced_by="matching_null",
        payload={
            "balance": result.balance,
            "sets": result.sets,
            "null": null_result,
            "seed": result.seed,
            "t0_block": result.t0_block,
        },
    )["payload_hash"]
    # Raw quantities and seeds serialise as decimal strings, never JSON numbers.
    assert '"t0_block":"{}"'.format(T0_BLOCK) in to_canonical_json(envelope["payload"])
    assert "e+" not in to_canonical_json(envelope).lower()


def test_the_balance_report_carries_everything_section_6_6_requires():
    """unique controls · reuse frequency · effective sample size · unmatched · covariate balance."""
    records, selected = clustered_universe()
    # One selected wallet of a type with no controls at all, so the unmatched row is populated.
    records["0xorphan"] = wallet_features("0xorphan", 300, 0, AccountType.ERC4337)
    selected = selected + ["0xorphan"]

    result = build_matched_sets_detail(
        selected, sorted(records), records, T0_BLOCK, seed=99, t0_timestamp=T0_TS
    )
    balance = result.balance

    assert balance.unmatched_selected == ("0xorphan",)
    assert balance.unique_controls == 30
    assert balance.control_reuse_rate == divide(0, 30)
    assert balance.effective_sample_size == 30
    assert len(balance.smd) == 10
    assert balance.worst_dimension[0] in balance.smd
