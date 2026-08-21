"""Worked examples for matching, the permutation null, and calibration.

Every expected value below was derived by hand before the code was written, on universes built so
the arithmetic closes exactly.

The ladder universe is the workhorse::

    thirteen wallets, capital_deployed = 0, 1, 2, ..., 12
    the other eight numeric dimensions constant

For n consecutive integers the population variance is (n^2 - 1) / 12, so at n = 13::

    mean = 6                variance = (169 - 1) / 12 = 14              sd = sqrt(14)

and the wallet at 0 sits sqrt-14ths of a standard deviation from each of the others, in strict
order: its five nearest controls are the wallets at 1, 2, 3, 4, 5 and its five robustness controls
are the wallets at 6, 7, 8, 9, 10.

Where an expectation is irrational it is evaluated **under the frozen 38-digit policy**, never at
Python's default 28 — the two agree for 28 digits and then diverge, which is the whole reason the
policy is frozen.
"""

import hashlib
from decimal import ROUND_UP, Context, Decimal, localcontext

import pytest

from contracts import (
    CALCULATION_CONTEXT,
    MATCHING_DIMENSIONS,
    SMD_BALANCE_TARGET,
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
    DegenerateNull,
    MatchingInfeasible,
    NullDistribution,
    NullRun,
    ThresholdNotCalibrated,
    WalletFeatures,
    build_matched_sets,
    build_matched_sets_detail,
    calibrate_threshold,
    calibrate_threshold_detail,
    categorical_imbalance,
    effective_sample_size,
    empirical_p_value,
    null_purpose,
    percentile_nearest_rank,
    permutation_null,
    permutation_null_detail,
    relabel,
    sqrt_of,
    standardise,
)

D = Decimal

T0_BLOCK = 18_000_000
T0_TS = 1_695_000_000
SEED = 20260731


def features(wallet, capital, account_type=AccountType.EOA, as_of_block=T0_BLOCK - 1, **overrides):
    """A feature record whose only varying dimension is ``capital_deployed`` unless told otherwise.

    Holding eight of the nine numeric dimensions constant is not a simplification of the model —
    they are still matched on, and a constant dimension has zero variance across the universe, so
    every wallet's standardised coordinate on it is 0 and it contributes nothing to any distance.
    That path is exercised by every test in this file.
    """
    values = {dimension: D("0") for dimension in NUMERIC_DIMENSIONS}
    values["capital_deployed"] = D(str(capital))
    values.update({k: D(str(v)) for k, v in overrides.items()})
    return WalletFeatures(
        wallet=wallet,
        account_type=account_type,
        values=values,
        as_of_block=as_of_block,
    )


def ladder():
    """Thirteen wallets at capital_deployed 0..12. Selected: the one at 0."""
    records = {}
    for value in range(13):
        wallet = "0xw{:02d}".format(value)
        records[wallet] = features(wallet, value)
    return records


# -- standardisation ------------------------------------------------------------


def test_the_ladder_universe_has_the_hand_computed_mean_and_spread():
    """13 consecutive integers from 0: mean 6, population variance (13^2 - 1)/12 = 14."""
    standardisation = standardise(ladder().values())

    assert standardisation["capital_deployed"].mean == D("6")
    assert standardisation["capital_deployed"].sd == sqrt_of(D("14"))
    assert standardisation["capital_deployed"].n == 13


def test_a_constant_dimension_standardises_to_zero_rather_than_dividing_by_zero():
    """A dimension nobody differs on distinguishes nobody. It stays in the table, at 0.

    ``divide`` refuses a zero denominator, and rightly — but a constant dimension is not a
    division-by-zero incident, it is a dimension carrying no information. Dropping it silently
    would be the wrong fix, because then a reader could not tell it from a dimension that was
    never matched on.
    """
    standardisation = standardise(ladder().values())

    assert standardisation["active_days"].sd == 0
    assert standardisation["active_days"].z(D("0")) == 0
    assert standardisation["active_days"].z(D("999")) == 0


def test_the_zero_wallet_sits_at_minus_six_over_root_fourteen():
    """z = (0 - 6) / sqrt(14)."""
    standardisation = standardise(ladder().values())
    with localcontext(CALCULATION_CONTEXT):
        expected = +(divide(D("-6"), D("14").sqrt()))

    assert standardisation["capital_deployed"].z(D("0")) == expected


# -- matching -------------------------------------------------------------------


def test_the_five_nearest_and_the_next_five_are_the_hand_computed_ones():
    """Selected at 0: primary = wallets at 1..5, robustness = wallets at 6..10, strictly ordered."""
    records = ladder()
    result = build_matched_sets_detail(
        ["0xw00"], sorted(records), records, T0_BLOCK, SEED
    )

    match = result.matches[0]
    assert tuple(c.wallet for c in match.primary) == (
        "0xw01", "0xw02", "0xw03", "0xw04", "0xw05"
    )
    assert tuple(c.wallet for c in match.robustness) == (
        "0xw06", "0xw07", "0xw08", "0xw09", "0xw10"
    )
    assert match.candidates_considered == 12


def test_the_distance_to_each_control_is_its_gap_over_root_fourteen():
    """|0 - k| / sqrt(14), evaluated under the frozen policy rather than the default context."""
    records = ladder()
    result = build_matched_sets_detail(["0xw00"], sorted(records), records, T0_BLOCK, SEED)

    with localcontext(CALCULATION_CONTEXT):
        sd = D("14").sqrt()
        expected = [+(divide(D(k), sd)) for k in (1, 2, 3, 4, 5)]

    for candidate, want in zip(result.matches[0].primary, expected):
        assert abs(candidate.distance - want) < D("1e-30")


def test_the_selected_wallet_is_never_its_own_control():
    """The treatment group cannot stand on both sides of the contrast."""
    records = ladder()
    sets, _balance = build_matched_sets(
        ["0xw00", "0xw01"], sorted(records), records, T0_BLOCK, SEED
    )

    chosen = {w for s in sets for w in s.primary_controls}
    assert "0xw00" not in chosen
    assert "0xw01" not in chosen


def test_a_selected_wallet_outside_the_frozen_universe_is_refused():
    """§6.4 freezes the universe at T0 and draws everything from it."""
    records = ladder()
    records["0xoutsider"] = features("0xoutsider", 3)
    with pytest.raises(ValueError) as excinfo:
        build_matched_sets(["0xoutsider"], sorted(ladder()), records, T0_BLOCK, SEED)
    assert "frozen T0 universe" in str(excinfo.value)


# -- covariate balance ----------------------------------------------------------


def test_the_ladder_balance_table_is_the_hand_computed_one():
    """Selected {0} against controls {1,2,3,4,5}::

        mean_t = 0        var_t = 0
        mean_c = 3        var_c = (4 + 1 + 0 + 1 + 4) / 5 = 2
        pooled = sqrt((0 + 2) / 2) = 1
        SMD    = (0 - 3) / 1 = -3

    An SMD of -3 is a catastrophic match, and it should be: one extreme wallet has no comparable
    control in a thirteen-wallet ladder. The table says so rather than averaging it away.
    """
    records = ladder()
    _sets, balance = build_matched_sets(["0xw00"], sorted(records), records, T0_BLOCK, SEED)

    assert balance.smd["capital_deployed"] == D("-3")
    assert balance.balanced is False
    assert balance.worst_dimension == ("capital_deployed", D("-3"))
    assert balance.unique_controls == 5
    assert balance.control_reuse_rate == 0
    assert balance.effective_sample_size == 5


def test_all_ten_dimensions_appear_in_the_table():
    """Nine numeric plus the categorical. A missing row is a confounder reported as absent."""
    records = ladder()
    _sets, balance = build_matched_sets(["0xw00"], sorted(records), records, T0_BLOCK, SEED)

    assert set(balance.smd) == set(MATCHING_DIMENSIONS)
    assert balance.smd["account_type"] == 0
    for dimension in NUMERIC_DIMENSIONS:
        if dimension != "capital_deployed":
            assert balance.smd[dimension] == 0


def balanced_universe():
    """Two selected wallets at 10 and 20, each with five controls centred on it.

        selected slots   10, 20                       mean 15
        control slots    8,9,10,11,12,18,19,20,21,22  mean 15   ->  SMD 0
    """
    records = {}
    records["0xsel10"] = features("0xsel10", 10)
    records["0xsel20"] = features("0xsel20", 20)
    for value in (8, 9, 10, 11, 12, 18, 19, 20, 21, 22):
        wallet = "0xc{:02d}".format(value)
        records[wallet] = features(wallet, value)
    return records


def test_a_symmetric_match_reaches_exactly_zero_standardised_difference():
    """Both group means land on 15, so the numerator is 0 and the SMD is 0 on every dimension."""
    records = balanced_universe()
    _sets, balance = build_matched_sets(
        ["0xsel10", "0xsel20"], sorted(records), records, T0_BLOCK, SEED
    )

    assert balance.smd["capital_deployed"] == 0
    assert balance.balanced is True
    assert abs(balance.smd["capital_deployed"]) < SMD_BALANCE_TARGET
    assert balance.unique_controls == 10
    assert balance.control_reuse_rate == 0
    assert balance.effective_sample_size == 10


def test_each_selected_wallet_takes_the_five_controls_around_it():
    records = balanced_universe()
    sets, _balance = build_matched_sets(
        ["0xsel10", "0xsel20"], sorted(records), records, T0_BLOCK, SEED
    )
    by_selected = {s.selected: set(s.primary_controls) for s in sets}

    assert by_selected["0xsel10"] == {"0xc08", "0xc09", "0xc10", "0xc11", "0xc12"}
    assert by_selected["0xsel20"] == {"0xc18", "0xc19", "0xc20", "0xc21", "0xc22"}


def reuse_universe():
    """Two selected wallets that must share the same five controls.

        five controls at 10, five far away at 100
        selected at 10 and 11 both take the five at 10
    """
    records = {"0xsel10": features("0xsel10", 10), "0xsel11": features("0xsel11", 11)}
    for i in range(5):
        records["0xnear{}".format(i)] = features("0xnear{}".format(i), 10)
        records["0xfar{}".format(i)] = features("0xfar{}".format(i), 100)
    return records


def test_reuse_shows_up_as_a_halved_effective_sample_size():
    """Ten control slots filled by five distinct wallets::

        reuse rate = (10 - 5) / 10 = 0.5
        ESS        = 10^2 / (5 x 2^2) = 100 / 20 = 5

    ``unique_controls`` alone cannot say this: it counts five either way, whether the five are
    used evenly or one of them carries half the benchmark. Kish's ESS is the number that does.
    """
    records = reuse_universe()
    _sets, balance = build_matched_sets(
        ["0xsel10", "0xsel11"], sorted(records), records, T0_BLOCK, SEED
    )

    assert balance.unique_controls == 5
    assert balance.control_reuse_rate == D("0.5")
    assert balance.effective_sample_size == 5


def test_the_reuse_universe_smd_is_root_two():
    """selected {10, 11} against ten control slots all at 10::

        mean_t = 10.5   var_t = 0.25        mean_c = 10   var_c = 0
        pooled = sqrt(0.125)
        SMD    = 0.5 / sqrt(0.125) = 0.5 x sqrt(8) = sqrt(2)
    """
    records = reuse_universe()
    _sets, balance = build_matched_sets(
        ["0xsel10", "0xsel11"], sorted(records), records, T0_BLOCK, SEED
    )

    assert abs(balance.smd["capital_deployed"] - sqrt_of(D("2"))) < D("1e-30")
    assert balance.balanced is False


def test_effective_sample_size_is_kish():
    """(sum w)^2 / sum w^2, checked on counts whose answer is obvious by inspection."""
    assert effective_sample_size([1, 1, 1, 1]) == 4     # 16 / 4  — four distinct controls
    assert effective_sample_size([2, 2]) == 2           # 16 / 8  — two, each used twice
    assert effective_sample_size([4]) == 1              # 16 / 16 — one control carrying everything
    assert effective_sample_size([3, 1]) == D("1.6")    # 16 / 10 — lopsided, and it shows


def test_account_type_is_matched_exactly_so_its_imbalance_is_zero():
    """Exact matching makes the category proportions identical by construction."""
    assert categorical_imbalance(
        [AccountType.EOA, AccountType.SAFE],
        [AccountType.EOA] * 5 + [AccountType.SAFE] * 5,
    ) == 0
    # And a hypothetical relaxed caliper blows straight through the 0.10 target.
    assert categorical_imbalance([AccountType.EOA], [AccountType.SAFE]) == 1


def test_controls_must_share_the_selected_wallet_s_account_type():
    records = ladder()
    records["0xsafe"] = features("0xsafe", 3, account_type=AccountType.SAFE)
    sets, _balance = build_matched_sets(
        ["0xw06"], sorted(records), records, T0_BLOCK, SEED
    )
    assert "0xsafe" not in sets[0].primary_controls


def test_a_selected_wallet_with_too_few_comparable_controls_is_reported_unmatched():
    """The only §6.4-legitimate reason a selected wallet leaves: the universe had no match."""
    records = ladder()
    records["0xsafe"] = features("0xsafe", 3, account_type=AccountType.SAFE)
    records["0xsafe2"] = features("0xsafe2", 4, account_type=AccountType.SAFE)

    result = build_matched_sets_detail(
        ["0xw00", "0xsafe"], sorted(records), records, T0_BLOCK, SEED
    )

    assert [m.selected for m in result.matches] == ["0xw00"]
    assert [u.wallet for u in result.unmatched] == ["0xsafe"]
    assert result.unmatched[0].candidates_available == 1
    assert "SAFE" in result.unmatched[0].reason
    assert result.balance.unmatched_selected == ("0xsafe",)


def test_no_matched_set_at_all_raises_rather_than_reporting_perfect_balance():
    """``all(())`` is ``True``, so an empty balance table would call itself balanced."""
    records = {
        "0xlonely": features("0xlonely", 1, account_type=AccountType.SAFE),
        "0xa": features("0xa", 2),
        "0xb": features("0xb", 3),
    }
    with pytest.raises(MatchingInfeasible) as excinfo:
        build_matched_sets(["0xlonely"], sorted(records), records, T0_BLOCK, SEED)
    assert "balanced" in str(excinfo.value)


def test_a_caliper_is_off_unless_asked_for():
    """§6.6 pre-registers no caliper, so the default cannot invent one.

    With one, the arithmetic decides who leaves. sqrt(14) ~ 3.742, so the wallet at 0 reaches its
    fifth control at 5/sqrt(14) ~ 1.336 and fails a caliper of 1, while the wallet at 6 — the
    centre of the ladder — reaches its fifth at 3/sqrt(14) ~ 0.802 and passes.
    """
    records = ladder()
    assert build_matched_sets_detail(
        ["0xw00"], sorted(records), records, T0_BLOCK, SEED
    ).caliper is None

    result = build_matched_sets_detail(
        ["0xw00", "0xw06"], sorted(records), records, T0_BLOCK, SEED, caliper=D("1")
    )
    assert [m.selected for m in result.matches] == ["0xw06"]
    assert [u.wallet for u in result.unmatched] == ["0xw00"]
    assert "caliper" in result.unmatched[0].reason


# -- the look-ahead trap --------------------------------------------------------


def test_a_feature_computed_at_t0_is_a_violation_not_a_pass():
    """``>=``, not ``>``. A feature computed at T0 has already seen T0."""
    records = ladder()
    records["0xw03"] = features("0xw03", 3, as_of_block=T0_BLOCK)

    with pytest.raises(LookAheadViolation) as excinfo:
        build_matched_sets(["0xw00"], sorted(records), records, T0_BLOCK, SEED)
    assert "0xw03" in str(excinfo.value)


def test_a_feature_from_after_t0_is_a_violation():
    records = ladder()
    records["0xw03"] = features("0xw03", 3, as_of_block=T0_BLOCK + 1)
    with pytest.raises(LookAheadViolation):
        build_matched_sets(["0xw00"], sorted(records), records, T0_BLOCK, SEED)


def test_one_forward_dimension_among_ten_is_caught():
    """The headline failure: nine honest dimensions and one that has seen the outcome."""
    records = ladder()
    records["0xw04"] = WalletFeatures(
        wallet="0xw04",
        account_type=AccountType.EOA,
        values={d: D("0") for d in NUMERIC_DIMENSIONS},
        as_of_block=T0_BLOCK - 1,
        dimension_blocks={"first_hour_purchase_share": T0_BLOCK + 5000},
    )
    with pytest.raises(LookAheadViolation) as excinfo:
        build_matched_sets(["0xw00"], sorted(records), records, T0_BLOCK, SEED)
    assert "first_hour_purchase_share" in str(excinfo.value)


def test_a_timestamp_with_nothing_to_check_it_against_is_refused():
    """A guard a caller can switch off by omitting an argument is not a guard."""
    records = ladder()
    records["0xw02"] = WalletFeatures(
        wallet="0xw02",
        account_type=AccountType.EOA,
        values={d: D("0") for d in NUMERIC_DIMENSIONS},
        as_of_block=T0_BLOCK - 1,
        as_of_timestamp=T0_TS - 1,
    )
    with pytest.raises(LookAheadViolation) as excinfo:
        build_matched_sets(["0xw00"], sorted(records), records, T0_BLOCK, SEED)
    assert "no t0_timestamp" in str(excinfo.value)

    # Supplied, and in the past: fine.
    build_matched_sets(
        ["0xw00"], sorted(records), records, T0_BLOCK, SEED, t0_timestamp=T0_TS
    )
    # Supplied, and at T0: refused.
    records["0xw02"] = WalletFeatures(
        wallet="0xw02",
        account_type=AccountType.EOA,
        values={d: D("0") for d in NUMERIC_DIMENSIONS},
        as_of_block=T0_BLOCK - 1,
        as_of_timestamp=T0_TS,
    )
    with pytest.raises(LookAheadViolation):
        build_matched_sets(
            ["0xw00"], sorted(records), records, T0_BLOCK, SEED, t0_timestamp=T0_TS
        )


def test_the_categorical_dimension_cannot_be_smuggled_in_as_a_number():
    with pytest.raises(ValueError) as excinfo:
        WalletFeatures(
            wallet="0xw",
            account_type=AccountType.EOA,
            values=dict({d: D("0") for d in NUMERIC_DIMENSIONS}, account_type=D("1")),
            as_of_block=T0_BLOCK - 1,
        )
    assert "enum declaration order" in str(excinfo.value)


def test_a_missing_dimension_is_refused_rather_than_matched_on_nine():
    values = {d: D("0") for d in NUMERIC_DIMENSIONS if d != "wallet_age"}
    with pytest.raises(ValueError) as excinfo:
        WalletFeatures(
            wallet="0xw", account_type=AccountType.EOA, values=values,
            as_of_block=T0_BLOCK - 1,
        )
    assert "wallet_age" in str(excinfo.value)


def test_a_float_feature_is_refused_at_construction():
    values = {d: D("0") for d in NUMERIC_DIMENSIONS}
    values["buy_volume"] = 1500.5
    with pytest.raises(TypeError):
        WalletFeatures(
            wallet="0xw", account_type=AccountType.EOA, values=values,
            as_of_block=T0_BLOCK - 1,
        )


# -- the permutation ------------------------------------------------------------


def score(mean, median=D("1"), status=EdgeOriginStatus.VALID, share=D("0.2"),
          column="leader", window=1):
    return WindowScore(
        window=window,
        column=column,
        mean_advantage=D(str(mean)),
        median_advantage=D(str(median)),
        first_hour_edge_share=None if status is EdgeOriginStatus.INDETERMINATE else share,
        positive_edge_contribution=D("10"),
        edge_origin_status=status,
    )


def seed_fn(purpose, index):
    """Stands in for the §9.6 derivation, which is HMAC over the master seed and the commit."""
    message = "master-seed|deadbeef|{}|{}".format(purpose, index).encode("utf-8")
    return int.from_bytes(hashlib.sha256(message).digest(), "big")


def one_set_universe():
    records = ladder()
    sets, _balance = build_matched_sets(["0xw00"], sorted(records), records, T0_BLOCK, SEED)
    return sets


def test_the_purpose_string_is_the_pre_registered_one():
    assert null_purpose("leader", 3) == "null.leader.window3"
    assert null_purpose("follower_adjusted", 1) == "null.follower_adjusted.window1"
    with pytest.raises(ValueError):
        null_purpose("random_basket", 1)


def test_relabelling_moves_the_label_and_nothing_else():
    """The multiset of wallets is unchanged; only which member wears the label has moved."""
    sets = one_set_universe()
    before = sorted(w for s in sets for w in s.members)

    relabelling = relabel(sets, seed=12345, run_index=0)

    assert sorted(relabelling.members()) == before
    assert len(relabelling.sets[0].primary_controls) == 5
    assert relabelling.sets[0].selected not in relabelling.sets[0].primary_controls
    assert relabelling.sets[0].selected in sets[0].members


def test_the_observed_statistic_comes_from_the_identity_labelling():
    """Run the same function on the real labels, so observed and null are commensurable."""
    sets = one_set_universe()
    quality = {"0xw00": D("40")}

    def statistic(labelled):
        return score(sum(quality.get(s.selected, D("0")) for s in labelled))

    detail = permutation_null_detail(sets, statistic, 8, seed_fn, "leader", 1)

    assert detail.observed_statistic == D("40")
    assert detail.purpose == "null.leader.window1"
    assert len(detail.runs) == 8
    # Only the wallet that was actually selected scores; every relabelling that picks a control
    # scores zero, which is what a null with no signal in the labels looks like.
    assert set(detail.statistics) <= {D("0"), D("40")}


def test_a_statistic_from_another_window_cannot_enter_this_distribution():
    sets = one_set_universe()
    with pytest.raises(ValueError) as excinfo:
        permutation_null(sets, lambda s: score(1, window=2), 4, seed_fn, "leader", 1)
    assert "another experiment" in str(excinfo.value)


def test_a_bare_number_is_not_a_gate():
    """§8.2: the null gate is the full three-condition gate, so a mean alone is not enough."""
    sets = one_set_universe()
    with pytest.raises(TypeError) as excinfo:
        permutation_null(sets, lambda s: D("1"), 4, seed_fn, "leader", 1)
    assert "three-condition" in str(excinfo.value)


def test_a_seed_derivation_that_ignores_its_index_is_refused():
    """A constant seed collapses 1,000 runs onto one point and nothing else looks wrong."""
    sets = one_set_universe()
    with pytest.raises(DegenerateNull) as excinfo:
        permutation_null(sets, lambda s: score(1), 5, lambda purpose, index: 7, "leader", 1)
    assert "ignoring" in str(excinfo.value)


def test_the_draw_is_uniform_over_the_six_members():
    """Six thousand deterministic seeds; each position drawn between 900 and 1,100 times.

    Fixed seeds, so this is a statement about a specific set of draws rather than a test that
    fails on Tuesdays. The rejection sampling makes the draw exactly uniform, not almost.
    """
    sets = one_set_universe()
    counts = {}
    for seed in range(6000):
        position = relabel(sets, seed=seed, run_index=0).chosen_positions[0]
        counts[position] = counts.get(position, 0) + 1

    assert sorted(counts) == [0, 1, 2, 3, 4, 5]
    assert all(900 <= n <= 1100 for n in counts.values()), counts


# -- percentile and p-value -----------------------------------------------------


@pytest.mark.parametrize(
    "n,expected",
    [
        (10, 10),     # ceil(0.95 x 10)  = 10  -> the 10th value
        (20, 19),     # ceil(0.95 x 20)  = 19  -> the 19th
        (100, 95),    # ceil(0.95 x 100) = 95  -> the 95th
        (1000, 950),  # ceil(0.95 x 1000) = 950 -> the 950th, the pre-registered case
    ],
)
def test_the_95th_percentile_is_nearest_rank(n, expected):
    """index = ceil(q x n) - 1 on the ascending sort, so the answer is always a real run."""
    values = [D(i) for i in range(1, n + 1)]
    assert percentile_nearest_rank(values, D("0.95")) == D(expected)


def test_the_percentile_is_always_a_value_the_null_produced():
    assert percentile_nearest_rank([D("3"), D("1"), D("2")], D("0.95")) == D("3")


def test_the_empirical_p_value_carries_the_plus_one_correction():
    """(1 + #{null >= observed}) / (1 + n). No run beating the observed value is not p = 0."""
    nulls = [D(i) for i in range(1, 11)]

    assert empirical_p_value(D("10"), nulls) == divide(2, 11)   # one tie
    assert empirical_p_value(D("11"), nulls) == divide(1, 11)   # nothing at or above
    assert empirical_p_value(D("0"), nulls) == divide(11, 11)   # everything at or above
    assert empirical_p_value(D("11"), nulls) > 0


# -- calibration ----------------------------------------------------------------


def distribution(scores, column="leader", window=1, observed=None, reference=D("15")):
    runs = tuple(
        NullRun(index=i, seed=1_000 + i, chosen_positions=(0,), score=s)
        for i, s in enumerate(scores)
    )
    return NullDistribution(
        column=column,
        window=window,
        purpose=null_purpose(column, window),
        observed=observed if observed is not None else score(D("30")),
        runs=runs,
        n_runs=len(runs),
        reference_threshold=reference,
    )


def worked_example_scores():
    """§8.3's worked example, constructed exactly::

        4 runs at 30pp     >= 24, >= 20, >= 15
        5 runs at 22pp             >= 20, >= 15
        9 runs at 17pp                    >= 15
       82 runs at  5pp
        --
      100 runs           ->  18% at 15pp, 9% at 20pp, 4% at 24pp
    """
    return (
        [score(30) for _ in range(4)]
        + [score(22) for _ in range(5)]
        + [score(17) for _ in range(9)]
        + [score(5) for _ in range(82)]
    )


def test_the_worked_example_from_section_8_3():
    """15pp -> 18%, 20pp -> 9%, 24pp -> 4%; lock at 24pp."""
    null = distribution(worked_example_scores())

    assert null.pass_rate(D("15")) == D("0.18")
    assert null.pass_rate(D("20")) == D("0.09")
    assert null.pass_rate(D("24")) == D("0.04")
    assert calibrate_threshold(null, [D("15"), D("20"), D("24")]) == D("24")


def test_the_calibrated_threshold_is_the_smallest_qualifying_candidate_whatever_the_order():
    null = distribution(worked_example_scores())
    assert calibrate_threshold(null, [D("30"), D("24"), D("26"), D("24.0")]) == D("24")


def test_the_full_three_condition_gate_calibrates_a_different_threshold_from_the_mean_alone():
    """Four of the five runs clearing 20pp fail edge origin, so the full gate locks 20pp, not 24pp.

    On the mean alone the rate at 20pp is 9/100 and the answer would be 24pp. Counting the two
    conditions §8.2 requires — median above zero, edge origin measurable — four of those nine runs
    are failures, the rate at 20pp is 5/100, and 20pp locks. The two gates disagree, which is
    exactly why §8.2 forbids calibrating one against the other.
    """
    scores = (
        [score(30) for _ in range(4)]
        + [score(22)]
        + [score(22, status=EdgeOriginStatus.INDETERMINATE) for _ in range(4)]
        + [score(17) for _ in range(9)]
        + [score(5) for _ in range(82)]
    )
    null = distribution(scores)

    mean_only = sum(1 for run in null.runs if run.score.mean_advantage >= D("20"))
    assert mean_only == 9

    assert null.pass_rate(D("20")) == D("0.05")
    assert null.pass_rate(D("20")) <= NULL_PASS_RATE_TARGET
    assert calibrate_threshold(null, [D("15"), D("20"), D("24")]) == D("20")


def test_a_negative_median_fails_the_gate_however_large_the_mean():
    """§7.1 condition 2 — one 1000% token cannot carry a basket whose median buy lost money."""
    null = distribution([score(100, median=D("0")) for _ in range(10)])
    assert null.pass_rate(D("15")) == 0


def test_an_exhausted_grid_raises_rather_than_returning_the_largest_candidate():
    """§8.4 locks the threshold before the main test runs; a made-up one would be locked too."""
    null = distribution(worked_example_scores())
    with pytest.raises(ThresholdNotCalibrated) as excinfo:
        calibrate_threshold(null, [D("1"), D("2")])
    assert "wider grid" in str(excinfo.value)


def test_a_grid_that_never_reaches_low_enough_is_reported_not_hidden():
    null = distribution(worked_example_scores())
    report = calibrate_threshold_detail(null, [D("24"), D("31")])

    assert report.threshold == D("24")
    assert report.at_grid_floor is True
    assert [r.passing_runs for r in report.rates] == [4, 0]


def test_calibrating_from_the_seam_type_is_refused():
    """A ``PermutationResult`` carries the means only, so it can only support a one-condition gate."""
    null = distribution(worked_example_scores())
    with pytest.raises(TypeError) as excinfo:
        calibrate_threshold(null.to_contract(), [D("24")])
    assert "three-condition" in str(excinfo.value)


def test_a_float_candidate_is_refused():
    null = distribution(worked_example_scores())
    with pytest.raises(TypeError):
        calibrate_threshold(null, [24.0])


# -- the seam -------------------------------------------------------------------


def test_the_null_reduces_to_the_seam_type():
    null = distribution(worked_example_scores(), reference=D("24"))
    result = null.to_contract()

    assert result.column == "leader"
    assert result.n_runs == 100
    assert result.observed_statistic == D("30")
    assert result.null_pass_rate == D("0.04")
    # 100 runs sorted ascending: the 95th is a 22.
    assert result.percentile_95 == D("22")
    # 4 runs tie the observed 30, so p = 5/101.
    assert result.empirical_p == divide(5, 101)
    assert result.significant is True


def test_every_output_survives_canonical_json():
    """A float leaking in through any path raises here rather than reaching the freeze manifest."""
    records = ladder()
    matching = build_matched_sets_detail(
        ["0xw00", "0xw01"], sorted(records), records, T0_BLOCK, SEED
    )
    null = permutation_null_detail(
        matching.sets,
        lambda s: score(1, column="follower_adjusted", window=2),
        4, seed_fn, "follower_adjusted", 2,
    )
    report = calibrate_threshold_detail(null, [D("0"), D("5")])

    for artifact in (
        matching,
        matching.balance,
        matching.robustness_balance,
        matching.sets[0],
        null,
        null.to_contract(),
        relabel(matching.sets, seed=7, run_index=0),
        report,
    ):
        payload = to_canonical_json(artifact)
        assert payload.startswith("{")


# -- the frozen context, held from outside the module -----------------------------
#
# A helper that is only correct because its caller happens to have opened a
# `localcontext(CALCULATION_CONTEXT)` block is not correct — it is lucky, and the luck runs out
# the first time someone calls it from somewhere else. These tests call the module's public
# functions from the *default* ambient context, which is 28 digits against values carried at 38,
# and require the frozen answer anyway.


def test_effective_sample_size_holds_38_digits_from_an_unfrozen_caller():
    """Kish's ESS on two counts big enough that the squares overflow 28 digits.

        w        = 10^15 + 1                and   3*10^15 + 7
        sum w    = 4*10^15 + 8              = 4000000000000008
        (sum w)^2                           = 16000000000000064000000000000064
        sum w^2  = (10^30 + 2*10^15 + 1) + (9*10^30 + 42*10^15 + 49)
                 = 10^31 + 44*10^15 + 50    = 10000000000000044000000000000050

    Both are 32-digit integers. Squaring under the ambient 28-digit context drops the last four
    digits of each, and the quotient then diverges from the frozen one in its 31st significant
    digit. The value below is the exact quotient at 38 digits.
    """
    counts = [10 ** 15 + 1, 3 * 10 ** 15 + 7]
    expected = D("1.5999999999999993600000000000012160000")

    assert effective_sample_size(counts) == expected

    with localcontext(Context(prec=6, rounding=ROUND_UP)):
        assert effective_sample_size(counts) == expected
