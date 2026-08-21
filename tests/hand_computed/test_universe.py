"""Hand-computed answers for ``universe``. Every expected value is a literal.

Nothing in this file re-evaluates the implementation's own expression. This repository has been
bitten by exactly that: an assertion that recomputes ``size // 100`` blesses whatever the code
does, including the ceiling that raises selection pressure above the 1% §6.5 authorises.

The clamp table below is §6.5's own, verbatim. The five rounding cases after it are the ones the
pre-registration does **not** pin — all four of its worked examples are exact multiples of 100 — so
they are recorded here as a decision rather than presented as a derivation.

Two assertions in this file are **golden pins** rather than derivations, and they say so where they
appear: the seeded tie-break permutation, whose value is a SHA-256 digest nobody can compute by
hand. Re-deriving it inside the test would be the defect this file's first paragraph is about. What
a golden pin buys is that the value cannot move without somebody editing this file.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from contracts import AccountType, ContractError, LookAheadViolation

import universe_fixtures as F
from universe import (
    ACTIVITY_BAND_BOUNDS,
    DEFAULT_POLICY,
    EXCLUSION_CRITERIA,
    MINIMUM_ELIGIBLE_UNIVERSE,
    POTENTIAL_BUY_CEILING,
    POTENTIAL_BUY_FLOOR,
    RULE_FAMILY,
    RULE_PRECEDENCE,
    SELECTED_MAX,
    SELECTED_MIN,
    VALID_BUY_CEILING,
    VALID_BUY_FLOOR,
    AccountEvidence,
    AccountTypeMix,
    ClampState,
    DataCostReport,
    EligibilityVerdict,
    ExclusionFamily,
    ExclusionRule,
    FieldBlock,
    InsufficientCandidateUniverse,
    LabelHit,
    VendorMutability,
    Selection,
    SelectionRefused,
    Step0Measurement,
    UnattributedExclusion,
    WarehouseRow,
    WindowStatus,
    band_composition,
    boundary_movement,
    build_census,
    classify_account,
    distribution,
    for_universe,
    freeze_universe,
    nearest_rank,
    rank_and_select,
    screen_warehouse,
    selected_wallet_count,
)

D = Decimal


# -- §6.5's clamp, and every boundary of it --------------------------------------
#
# ``clamp(1% of Eligible Universe, 250, 1000)``. Written as ``(size, count, state)`` triples with
# the count as a literal. A test that wrote ``size // 100`` would agree with a ceiling, a floor and
# a round-half-even implementation alike, and the three disagree for roughly half of all sizes.


#: §6.5's own four worked examples, verbatim from the pre-registration.
SPEC_CLAMP_TABLE = (
    (20_000, 250, ClampState.CLAMPED_LOW),
    (50_000, 500, ClampState.UNCLAMPED),
    (80_000, 800, ClampState.UNCLAMPED),
    (200_000, 1_000, ClampState.CLAMPED_HIGH),
)


@pytest.mark.parametrize("size,count,state", SPEC_CLAMP_TABLE)
def test_the_pre_registered_clamp_table(size, count, state):
    assert selected_wallet_count(size) == (count, state)


#: Both edges of both clamps, by hand. The interesting numbers are the ones either side of a
#: transition: 24,999 is the largest universe that still clamps low and 25,000 the smallest that
#: does not; 100,099 is the largest that is still unclamped and 100,100 the smallest that clamps
#: high. A ``>`` written as ``>=`` moves exactly one of these four and nothing else, which is why
#: the pairs are here rather than one representative value per state.
CLAMP_BOUNDARIES = (
    (0, 250, ClampState.CLAMPED_LOW),
    (1, 250, ClampState.CLAMPED_LOW),
    (24_900, 250, ClampState.CLAMPED_LOW),
    (24_999, 250, ClampState.CLAMPED_LOW),
    (25_000, 250, ClampState.UNCLAMPED),
    (25_100, 251, ClampState.UNCLAMPED),
    (99_900, 999, ClampState.UNCLAMPED),
    (100_000, 1_000, ClampState.UNCLAMPED),
    (100_099, 1_000, ClampState.UNCLAMPED),
    (100_100, 1_000, ClampState.CLAMPED_HIGH),
    (1_000_000, 1_000, ClampState.CLAMPED_HIGH),
)


@pytest.mark.parametrize("size,count,state", CLAMP_BOUNDARIES)
def test_every_clamp_boundary_by_hand(size, count, state):
    assert selected_wallet_count(size) == (count, state)


def test_the_clamp_bounds_are_the_pre_registered_ones():
    assert SELECTED_MIN == 250
    assert SELECTED_MAX == 1_000


#: The five cases the pre-registration does not pin, because all four of its worked examples are
#: exact multiples of 100. Each row is ``(size, floor, round_half_even, ceiling)`` — the three
#: candidate roundings written out, so the disagreement is visible rather than argued about — and
#: the decision recorded here is **floor**.
#:
#: Floor is chosen for one reason, and it is not "it is what ``//`` does": a fractional wallet
#: cannot be selected, and rounding down keeps realised selection pressure at or below the 1% §6.5
#: authorises, where ceiling would push it above. This is an unregistered degree of freedom being
#: fixed after the pre-registration was written, and it belongs in the frozen parameter set and not
#: only here.
ROUNDING_DECISIONS = (
    (25_050, 250, 250, 251),      # 1% is exactly 250.5 — half-even goes down, ceiling goes up
    (25_051, 250, 251, 251),      # 250.51 — nearest goes up, floor does not
    (25_149, 251, 251, 252),      # 251.49 — nearest agrees with floor here, ceiling does not
    (25_150, 251, 252, 252),      # 251.5 — half-even goes *up*, to the even 252
    (99_999, 999, 1_000, 1_000),  # 999.99 — the other two round into the high clamp's own value
)


@pytest.mark.parametrize("size,floor,half_even,ceiling", ROUNDING_DECISIONS)
def test_the_one_percent_fraction_rounds_down_for_a_count(size, floor, half_even, ceiling):
    """Floor, deliberately. The other two candidates are named so the choice is visible."""
    count, state = selected_wallet_count(size)
    assert state is ClampState.UNCLAMPED
    assert count == floor
    assert floor <= half_even <= ceiling


def test_the_three_roundings_genuinely_disagree_on_every_row():
    """Guard the table: a row where all three agreed would prove nothing about the decision."""
    agreeing = [size for size, floor, half_even, ceiling in ROUNDING_DECISIONS
                if floor == half_even == ceiling]
    assert agreeing == []


def test_a_negative_universe_is_a_defect_and_not_a_status():
    """A negative population has no 1%. This is a defect in what assembled the call."""
    with pytest.raises(SelectionRefused):
        selected_wallet_count(-1)


def test_the_clamp_does_not_raise_on_a_universe_below_the_floor():
    """§6.1's refusal lives on the object that would carry it into an experiment, not here.

    A function that raised at small values would be one nobody could write a clamp table for, and
    the table above is the whole point of the function.
    """
    assert selected_wallet_count(100) == (250, ClampState.CLAMPED_LOW)


# -- the two-stage buffer --------------------------------------------------------
#
# Eight accounts, chosen so that every count :class:`BoundaryMovement` reports is 1 and a
# transposition of any two of them would be visible.
#
#   ...001  potential    12, valid    25  -> admitted, carried in by the LOWER buffer
#   ...002  potential 1,100, valid   900  -> admitted, carried in by the UPPER buffer
#   ...003  potential   100, valid    15  -> netting moved it BELOW the floor
#   ...004  potential   500, valid 1,001  -> netting moved it ABOVE the cap
#   ...005  potential   120, valid    20  -> admitted, sitting exactly on the lower bound
#   ...006  potential   900, valid 1,000  -> admitted, sitting exactly on the upper bound
#   ...05a  potential     5               -> refused by the warehouse, below 10
#   ...05b  potential 1,500               -> refused by the warehouse, above 1,200

BUFFER_ACCOUNTS = (
    (1, 12, 25),
    (2, 1_100, 900),
    (3, 100, 15),
    (4, 500, 1_001),
    (5, 120, 20),
    (6, 900, 1_000),
)

BELOW_WAREHOUSE_FLOOR = 90
ABOVE_WAREHOUSE_CEILING = 91


def _buffer_window():
    observations = [
        F.observation(F.address(index), potential_buys=potential, valid_buys=valid)
        for index, potential, valid in BUFFER_ACCOUNTS
    ]
    extra = (
        WarehouseRow(address=F.address(BELOW_WAREHOUSE_FLOOR), potential_buys=5),
        WarehouseRow(address=F.address(ABOVE_WAREHOUSE_CEILING), potential_buys=1_500),
    )
    return F.measured(observations, extra_rows=extra)


def test_the_buffer_bounds_are_the_pre_registered_pair_of_pairs():
    assert (POTENTIAL_BUY_FLOOR, POTENTIAL_BUY_CEILING) == (10, 1_200)
    assert (VALID_BUY_FLOOR, VALID_BUY_CEILING) == (20, 1_000)


def test_the_count_that_moved_across_the_boundary():
    """Ticket 25's headline: how many accounts netting carried across the eligibility boundary.

    Two, one from each direction. A single-stage filter at 20-1,000 would have dropped both before
    anything could name a rule for them, and the drop would be invisible because those accounts
    were never returned.
    """
    measurement, _verdicts, _census, _screen = _buffer_window()
    movement = measurement.movement

    assert movement.retained_by_lower_buffer == 1
    assert movement.retained_by_upper_buffer == 1
    assert movement.retained_by_buffer == 2

    assert movement.fell_below_floor == 1
    assert movement.rose_above_cap == 1

    assert movement.at_lower_bound_eligible == 1
    assert movement.at_upper_bound_eligible == 1


def test_the_upper_bound_is_applied_to_valid_buys_and_not_to_total_transactions():
    """...002 ran 1,100 potential buys and is admitted; ...004 ran 500 and is not.

    That pair is the criterion. Approvals, transfers and administrative operations inflate the
    coarse warehouse count, and applying the ceiling there would drop ...002 for activity that is
    not buying.
    """
    _measurement, verdicts, _census, _screen = _buffer_window()
    by_account = {v.account: v for v in verdicts}

    inflated = by_account[F.address(2)]
    assert inflated.is_admitted
    assert inflated.admitted.potential_buys == 1_100
    assert inflated.admitted.valid_buys == 900
    assert inflated.admitted.crossed_boundary is True

    genuinely_over = by_account[F.address(4)]
    assert genuinely_over.is_admitted is False
    assert genuinely_over.exclusion.rule is ExclusionRule.VALID_BUYS_ABOVE_CEILING
    assert genuinely_over.exclusion.evidence[0] == "valid_buys=1001 > 1000"


def test_the_two_stages_reconcile_account_by_account():
    measurement, _verdicts, census, screen = _buffer_window()

    assert screen.rows_screened == 8
    assert len(screen.admitted) == 6
    assert len(screen.exclusions) == 2

    assert census.considered == 8
    assert census.admitted_count == 4
    assert census.excluded_total == 4

    fired = {entry.rule.value: entry.count for entry in census.exclusions_by_rule if entry.count}
    assert fired == {
        "POTENTIAL_BUYS_BELOW_FLOOR": 1,
        "POTENTIAL_BUYS_ABOVE_CEILING": 1,
        "VALID_BUYS_BELOW_FLOOR": 1,
        "VALID_BUYS_ABOVE_CEILING": 1,
    }
    assert census.by_family(ExclusionFamily.THRESHOLD) == 4
    assert census.by_family(ExclusionFamily.INFRASTRUCTURE) == 0
    assert census.by_family(ExclusionFamily.AUTOMATION) == 0
    assert census.by_family(ExclusionFamily.COVERAGE) == 0
    assert measurement.eligible_universe_size == 4
    assert measurement.accounts_in_valid_buy_band == 4


def test_the_warehouse_row_carries_no_transaction_history():
    """Filter-early / enrich-late as a property of the entry type rather than of a habit."""
    assert sorted(WarehouseRow.__dataclass_fields__) == ["address", "potential_buys"]


def test_the_data_cost_of_filtering_early():
    """Ticket 25 asks for the cost to be reported; the claim is worth the number beside it."""
    measurement, _verdicts, _census, _screen = _buffer_window()
    cost = measurement.data_cost
    assert cost.accounts_screened == 8
    assert cost.accounts_enriched == 6
    # 12 + 1,100 + 100 + 500 + 120 + 900 — the six admitted rows, and neither refused one.
    assert cost.transactions_enriched == 2_732


def test_a_data_cost_claiming_more_enriched_than_screened_is_refused():
    with pytest.raises(ContractError):
        DataCostReport(accounts_screened=6, accounts_enriched=7, transactions_enriched=1)


# -- no unattributed exclusion ---------------------------------------------------


#: Every way an account can leave the population, as literals. There is no ``OTHER`` and no
#: ``UNKNOWN``, and that absence *is* ticket 25's criterion — a residual member would be the
#: bucket, and it would fill up quietly.
EVERY_EXCLUSION_RULE = (
    "POTENTIAL_BUYS_BELOW_FLOOR",
    "POTENTIAL_BUYS_ABOVE_CEILING",
    "VALID_BUYS_BELOW_FLOOR",
    "VALID_BUYS_ABOVE_CEILING",
    "SETTLES_FOR_MULTIPLE_PRINCIPALS",
    "ECONOMIC_CONTROLLER_UNIDENTIFIED",
    "PUBLIC_CAPITAL_POOL",
    "MARKET_MAKING_INVENTORY",
    "DEPLOYER_TRADING_OWN_TOKEN",
    "LABELLED_MEV",
    "LABELLED_SANDWICH",
    "LABELLED_ARBITRAGE",
    "BOT_HEURISTIC",
    "NON_HUMAN_TRADING_CADENCE",
    "OUTSIDE_TRAINING_WINDOW",
    "ENRICHMENT_INCOMPLETE",
)


def test_the_exclusion_enum_is_closed_and_has_no_residual_member():
    assert sorted(rule.value for rule in ExclusionRule) == sorted(EVERY_EXCLUSION_RULE)
    assert len(EVERY_EXCLUSION_RULE) == 16
    for forbidden in ("OTHER", "UNKNOWN", "MISC", "RESIDUAL", "UNATTRIBUTED"):
        assert forbidden not in EVERY_EXCLUSION_RULE


@pytest.mark.parametrize("rule", list(ExclusionRule), ids=lambda r: r.value)
def test_every_rule_states_a_criterion_and_belongs_to_a_family(rule):
    assert EXCLUSION_CRITERIA[rule].strip()
    assert isinstance(RULE_FAMILY[rule], ExclusionFamily)
    assert rule in RULE_PRECEDENCE


def test_an_account_matching_no_rule_does_not_silently_vanish():
    """The account nothing fires on. It must arrive, by name, on the admitted side.

    Its evidence is entirely **unmeasured** — every field ``None`` — which is the version of this
    account most likely to fall through a residual bucket, because no predicate has anything to say
    about it. It is admitted, counted in the census, and frozen into the universe under its own
    address.
    """
    quiet = F.address(77)
    observation = F.observation(quiet, potential_buys=120, valid_buys=100,
                                evidence=AccountEvidence())
    screen = F.screened([observation])
    verdict = classify_account(observation, DEFAULT_POLICY, screen)

    assert verdict.is_admitted is True
    assert verdict.exclusion is None
    assert verdict.also_matched == ()
    assert verdict.admitted.account == quiet

    census = build_census((verdict,), 1, boundary_movement([observation], (verdict,)), F.W1.key)
    assert census.considered == 1
    assert census.admitted_count == 1
    assert census.excluded_total == 0

    universe = F.frozen([observation])
    assert universe.wallets == (quiet,)


def test_an_account_that_vanished_is_refused_rather_than_absorbed():
    """The teeth. Drop one verdict and the census will not exist.

    This is the shape ticket 25 forbids: the account is gone, no rule names it, and the eligible
    universe — the number §6.5 derives the selected wallet count from — is quietly one smaller.
    """
    observations = [F.observation(F.address(i), potential_buys=120, valid_buys=100)
                    for i in (1, 2, 3)]
    screen = F.screened(observations)
    verdicts = tuple(classify_account(o, DEFAULT_POLICY, screen) for o in observations)
    movement = boundary_movement(observations, verdicts)

    with pytest.raises(UnattributedExclusion) as raised:
        build_census(verdicts[:2], 3, movement, F.W1.key)
    assert "unattributed" in str(raised.value).lower()


def test_a_census_carries_every_rule_including_the_ones_that_never_fired():
    """An absent key cannot tell "nobody was excluded by this" from "nobody applied it"."""
    observation = F.observation(F.address(1), potential_buys=120, valid_buys=100)
    screen = F.screened([observation])
    verdict = classify_account(observation, DEFAULT_POLICY, screen)
    census = build_census((verdict,), 1, boundary_movement([observation], (verdict,)), F.W1.key)

    assert {entry.rule for entry in census.exclusions_by_rule} == set(ExclusionRule)
    assert sum(entry.count for entry in census.exclusions_by_rule) == 0


def test_accounts_below_the_warehouse_floor_are_unknowable_and_not_zero():
    """``None``, never ``0``. A zero would read as "nobody was below the floor"."""
    measurement, _verdicts, census, _screen = _buffer_window()
    assert census.unmeasurable_outside_warehouse is None
    assert measurement.census.unmeasurable_outside_warehouse is None


# -- §6.2's infrastructure test --------------------------------------------------


def test_the_reported_rule_is_infrastructure_first_and_the_rest_still_travel():
    """One account firing five rules. Nothing is destroyed by the precedence choice.

    §6.1 requires "excluded infrastructure contracts" as its own line, so a router excluded as
    ``NON_HUMAN_TRADING_CADENCE`` would understate that line and overstate the automation one.
    """
    evidence = F.human_evidence(
        distinct_beneficiaries=9,
        deployed_tokens_traded=2,
        controller_identified=False,
        day_of_week_skewness=D("0"),
        labels=(LabelHit(set_name="labels.mev_ethereum", snapshot_block=17_000_000,
                         provenance=VendorMutability.MUTABLE_VENDOR_FIELD),),
    )
    observation = F.observation(F.address(70), potential_buys=120, valid_buys=100,
                                evidence=evidence)
    screen = F.screened([observation])
    verdict = classify_account(observation, DEFAULT_POLICY, screen)

    assert verdict.exclusion.rule is ExclusionRule.SETTLES_FOR_MULTIPLE_PRINCIPALS
    assert [rule.value for rule in verdict.also_matched] == [
        "DEPLOYER_TRADING_OWN_TOKEN",
        "ECONOMIC_CONTROLLER_UNIDENTIFIED",
        "LABELLED_MEV",
        "NON_HUMAN_TRADING_CADENCE",
    ]
    assert verdict.exclusion.evidence[0] == "distinct_beneficiaries=9 > 1"
    assert RULE_FAMILY[verdict.exclusion.rule] is ExclusionFamily.INFRASTRUCTURE


def test_unmeasured_evidence_does_not_pass_a_rule_it_was_never_tested_against():
    """``None`` means UNMEASURED. A ``None`` read as a pass admits an unassessed router."""
    unassessed = F.observation(F.address(71), potential_buys=120, valid_buys=100,
                               evidence=AccountEvidence(controller_identified=None))
    looked_and_failed = F.observation(F.address(72), potential_buys=120, valid_buys=100,
                                      evidence=AccountEvidence(controller_identified=False))
    screen = F.screened([unassessed, looked_and_failed])

    assert classify_account(unassessed, DEFAULT_POLICY, screen).is_admitted is True
    refused = classify_account(looked_and_failed, DEFAULT_POLICY, screen)
    assert refused.exclusion.rule is ExclusionRule.ECONOMIC_CONTROLLER_UNIDENTIFIED


@pytest.mark.parametrize("account_type", [AccountType.SAFE, AccountType.ERC4337])
def test_a_smart_account_survives_the_published_human_filter(account_type):
    """§6.2: the day-of-week filter excludes all contracts and must be modified to retain these."""
    evidence = F.human_evidence(day_of_week_skewness=D("0"), mean_inter_trade_gap_seconds=7_200)
    smart = F.observation(F.address(73), potential_buys=120, valid_buys=100,
                          account_type=account_type, evidence=evidence)
    eoa = F.observation(F.address(74), potential_buys=120, valid_buys=100,
                        account_type=AccountType.EOA, evidence=evidence)
    screen = F.screened([smart, eoa])

    assert classify_account(smart, DEFAULT_POLICY, screen).is_admitted is True
    excluded = classify_account(eoa, DEFAULT_POLICY, screen)
    assert excluded.exclusion.rule is ExclusionRule.NON_HUMAN_TRADING_CADENCE


def test_the_smart_account_exemption_is_not_a_bypass():
    """A Safe running a market-making book is still excluded. The exemption is two rules wide."""
    book = F.observation(
        F.address(75), potential_buys=120, valid_buys=100, account_type=AccountType.SAFE,
        evidence=F.human_evidence(two_sided_quote_share=D("0.8")),
    )
    screen = F.screened([book])
    verdict = classify_account(book, DEFAULT_POLICY, screen)
    assert verdict.exclusion.rule is ExclusionRule.MARKET_MAKING_INVENTORY


def test_a_mutable_label_exclusion_is_counted_rather_than_hidden():
    """§6.2's label sets are continuously recomputed — look-ahead in the exclusion direction.

    It is counted and reported rather than refused, which is the weakest joint in this package, and
    the count is what makes the exposure per window readable instead of implicit.
    """
    labelled = F.observation(
        F.address(76), potential_buys=120, valid_buys=100,
        evidence=F.human_evidence(labels=(
            LabelHit(set_name="dex.sandwiches", snapshot_block=17_000_000,
                     provenance=VendorMutability.MUTABLE_VENDOR_FIELD),
        )),
    )
    clean = F.observation(F.address(78), potential_buys=120, valid_buys=100)
    screen = F.screened([labelled, clean])
    verdicts = tuple(classify_account(o, DEFAULT_POLICY, screen) for o in (labelled, clean))
    census = build_census(verdicts, 2, boundary_movement([labelled, clean], verdicts), F.W1.key)

    assert verdicts[0].exclusion.rule is ExclusionRule.LABELLED_SANDWICH
    assert verdicts[0].exclusion.label_provenance is VendorMutability.MUTABLE_VENDOR_FIELD
    assert census.mutable_label_exclusions == 1
    assert census.count_for(ExclusionRule.LABELLED_SANDWICH) == 1


def test_incomplete_enrichment_is_a_named_coverage_rule_and_not_infrastructure():
    """The account nobody could net stays visible, and stays out of the infrastructure count."""
    unnetted = F.observation(F.address(79), potential_buys=120, valid_buys=100,
                             evidence=F.human_evidence(netting_complete=False))
    screen = F.screened([unnetted])
    verdict = classify_account(unnetted, DEFAULT_POLICY, screen)
    assert verdict.exclusion.rule is ExclusionRule.ENRICHMENT_INCOMPLETE
    assert RULE_FAMILY[ExclusionRule.ENRICHMENT_INCOMPLETE] is ExclusionFamily.COVERAGE


# -- §6.1's distributions --------------------------------------------------------


def test_nearest_rank_by_counting_along_the_column():
    """Sort ascending, take ``ceil(num * n / den) - 1``. Counted by hand over 1..10."""
    column = [D(value) for value in range(1, 11)]
    assert nearest_rank(column, 5, 100) == D(1)     # ceil(0.5) - 1 = 0
    assert nearest_rank(column, 25, 100) == D(3)    # ceil(2.5) - 1 = 2
    assert nearest_rank(column, 50, 100) == D(5)    # ceil(5.0) - 1 = 4
    assert nearest_rank(column, 75, 100) == D(8)    # ceil(7.5) - 1 = 7
    assert nearest_rank(column, 95, 100) == D(10)   # ceil(9.5) - 1 = 9


def test_a_quantile_of_an_empty_column_is_undefined_and_not_zero():
    with pytest.raises(ValueError):
        nearest_rank([], 50, 100)


def test_a_hand_counted_distribution():
    """Five valid-buy counts, supplied out of order so the sort is doing work.

    20, 30, 40, 50, 60. Mean 200/5 = 40 exactly. Every quantile is a member of the column, because
    nearest-rank never interpolates.
    """
    dist = distribution("valid_buy_count", [D(60), D(20), D(40), D(30), D(50)])
    assert dist.n == 5
    assert dist.quantiles == {
        "p05": D(20), "p25": D(30), "p50": D(40), "p75": D(50), "p95": D(60),
    }
    assert dist.mean == D(40)
    assert dist.minimum == D(20)
    assert dist.maximum == D(60)


def test_the_five_required_distributions_of_a_measured_window():
    measurement, _verdicts, _census, _screen = _buffer_window()
    assert sorted(measurement.distributions) == [
        "active_days", "buy_volume_usd", "smart_account_share", "valid_buy_count",
        "wallet_age_days",
    ]
    # The four admitted accounts are ...001 (25), ...002 (900), ...005 (20), ...006 (1,000).
    valid_buys = measurement.distributions["valid_buy_count"]
    assert valid_buys.minimum == D(20)
    assert valid_buys.maximum == D(1_000)
    assert valid_buys.mean == D("486.25")   # 1,945 / 4
    assert valid_buys.quantiles["p50"] == D(25)


def test_the_smart_account_share_of_an_all_eoa_window_is_zero():
    measurement, _verdicts, _census, _screen = _buffer_window()
    assert measurement.smart_account_share == D(0)
    assert measurement.eligible_eoas == 4
    assert measurement.eligible_safes == 0
    assert measurement.eligible_erc4337 == 0
    assert measurement.eligible_other_contracts == 0


# -- §6.1's stopping condition ---------------------------------------------------


def test_insufficient_candidate_universe_is_a_carried_status_and_not_a_raise():
    """Measuring a small universe is a finding — arguably the cheapest important one Phase 0 has.

    Raising here would crash the measurement stage on its most informative possible result.
    """
    measurement, _verdicts, _census, _screen = _buffer_window()

    assert MINIMUM_ELIGIBLE_UNIVERSE == 10_000
    assert measurement.eligible_universe_size == 4
    assert measurement.status is WindowStatus.INSUFFICIENT_CANDIDATE_UNIVERSE
    assert measurement.status.value == "INSUFFICIENT CANDIDATE UNIVERSE"
    assert measurement.status.permits_ranking is False


def _sized(measurement, eligible):
    """The same measurement with its eligible universe moved to ``eligible``, and nothing else.

    Every count §6.1 reconciles is moved with it — the account-type breakdown, the census's
    admitted and considered totals, and the three funnel rungs above the universe — so the value
    is as constructable as any other :class:`Step0Measurement` and ``__post_init__`` re-runs on it.
    Only the size moves, which is the one variable the stopping condition reads.

    Built by replacement rather than by measuring ten thousand accounts because measuring them
    costs eleven and a half seconds per window, and the slowest test in this suite is four. The
    end-to-end path was walked by hand at 9,999 / 10,000 / 10,001 through ``execute_stage``: all
    three COMPLETE, all three are carried in the report, and the statuses are the three below.
    """
    excluded = sum(entry.count for entry in measurement.census.exclusions_by_rule)
    census = replace(measurement.census, admitted_count=eligible,
                     considered=eligible + excluded)
    return replace(
        measurement,
        mix=AccountTypeMix(eoa=eligible, safe=0, erc4337=0, other_contract=0),
        census=census,
        movement=census.movement,
        accounts_in_valid_buy_band=eligible,
        accounts_with_at_least_one_valid_buy=eligible,
        total_active_accounts=eligible,
    )


def test_the_stopping_condition_is_below_ten_thousand_and_not_at_it():
    """Which side of §6.1's floor is valid, as literals. Ticket 26 decides it and the code follows.

    Ticket 26: "Any window whose eligible universe is **below** 10,000 accounts is marked
    ``INSUFFICIENT CANDIDATE UNIVERSE``", and §6.1: "**If** the eligible universe in a window is
    below 10,000 accounts". So 9,999 is not valid and 10,000 is — a window that lands exactly on
    the floor has met the pre-registered condition and may be ranked.

    Nothing else in this suite exercises the sufficient side: every fixture universe is a handful
    of accounts, so ``<`` and ``<=`` were indistinguishable here and one character decided whether
    a window sitting exactly on the pre-registered floor gets ranked or sends the whole four-window
    design back to be revised. The three sizes below are written out; none is read back off the
    implementation.
    """
    measurement, _verdicts, _census, _screen = _buffer_window()

    assert MINIMUM_ELIGIBLE_UNIVERSE == 10_000

    assert _sized(measurement, 9_999).status is WindowStatus.INSUFFICIENT_CANDIDATE_UNIVERSE
    assert _sized(measurement, 10_000).status is WindowStatus.SUFFICIENT
    assert _sized(measurement, 10_001).status is WindowStatus.SUFFICIENT

    assert _sized(measurement, 9_999).status.permits_ranking is False
    assert _sized(measurement, 10_000).status.permits_ranking is True


def test_freezing_an_insufficient_window_for_ranking_is_a_raise():
    """The other half of the split. Measuring is a finding; freezing one for ranking is not."""
    measurement, verdicts, _census, _screen = _buffer_window()
    with pytest.raises(InsufficientCandidateUniverse) as raised:
        freeze_universe(measurement, verdicts, F.SNAPSHOT, revision=None)
    assert "INSUFFICIENT CANDIDATE UNIVERSE" in str(raised.value)


def test_the_status_is_derived_and_cannot_be_written_onto_a_failing_window():
    """A stored status could be set independently of the number it is about."""
    assert "status" not in Step0Measurement.__dataclass_fields__
    assert "eligible_universe_size" not in Step0Measurement.__dataclass_fields__


# -- §6.4: the T0 boundary -------------------------------------------------------


def test_an_observation_stamped_at_t0_is_refused():
    """``>=`` and not ``>``: a value computed at T0 has already seen T0."""
    with pytest.raises(LookAheadViolation):
        F.observation(F.address(1), as_of_block=F.W1.t0.block)


def test_an_observation_stamped_at_t0s_second_is_refused():
    with pytest.raises(LookAheadViolation):
        F.observation(F.address(1), as_of_timestamp=F.W1.t0.timestamp)


def test_an_observation_one_block_before_t0_is_accepted():
    """The positive half of the boundary — the guard must not refuse the last legal instant."""
    observation = F.observation(F.address(1), as_of_block=F.W1.t0.block - 1,
                                as_of_timestamp=F.W1.t0.timestamp - 1)
    assert observation.as_of_block == F.W1.t0.block - 1


def test_a_mutable_vendor_field_cannot_be_a_selection_input():
    """A field whose source recomputes it has no knowable value at T0."""
    with pytest.raises(LookAheadViolation):
        F.observation(F.address(1), provenance=VendorMutability.MUTABLE_VENDOR_FIELD)


def test_one_forward_looking_field_among_many_is_still_refused():
    """Every record-level stamp is pre-T0; one field's own block is not, and that is enough."""
    with pytest.raises(LookAheadViolation):
        F.observation(F.address(1),
                      field_blocks=(FieldBlock(field_name="valid_buys", block=F.W1.t0.block),))


def test_a_per_field_provenance_entry_naming_no_field_is_refused():
    with pytest.raises(ValueError):
        F.observation(F.address(1),
                      field_blocks=(FieldBlock(field_name="forward_returns", block=1),))


# -- ticket 28's basket ----------------------------------------------------------


def test_the_activity_bands_tile_the_eligible_range_exactly():
    assert ACTIVITY_BAND_BOUNDS == (("20-99", 20, 99), ("100-499", 100, 499),
                                    ("500-1000", 500, 1_000))
    assert ACTIVITY_BAND_BOUNDS[0][1] == VALID_BUY_FLOOR
    assert ACTIVITY_BAND_BOUNDS[-1][2] == VALID_BUY_CEILING


def test_band_composition_at_every_band_edge():
    """Six wallets, one on each edge of each band. Every count is 2, by hand."""
    counts = (20, 99, 100, 499, 500, 1_000)
    selections = tuple(
        Selection(wallet=F.address(index), rank=index, value=D(1), valid_buys=valid,
                  account_type=AccountType.EOA)
        for index, valid in enumerate(counts, start=1)
    )
    composition = band_composition(selections)
    assert (composition.b_20_99, composition.b_100_499, composition.b_500_1000) == (2, 2, 2)
    assert composition.selected == 6
    assert composition.as_mapping == {"20-99": 2, "100-499": 2, "500-1000": 2}


def test_a_wallet_in_no_band_is_a_selection_error_filed_as_a_diagnostic():
    outside = (Selection(wallet=F.address(1), rank=1, value=D(1), valid_buys=19,
                         account_type=AccountType.EOA),)
    with pytest.raises(SelectionRefused):
        band_composition(outside)


#: A **golden pin**, not a derivation. ``_tiebreak_key`` is a SHA-256 digest of ``seed|wallet`` and
#: nobody can compute it by hand; what these pin is that the permutation cannot move without a diff
#: to this file. The two seeds produce different orders *inside* the tie group and identical orders
#: outside it, which is the property that matters: the seed decides ties and decides nothing else.
TIE_ORDER_SEED_42 = ("005", "001", "002", "003", "004", "006")
TIE_ORDER_SEED_0 = ("001", "005", "002", "003", "004", "006")

#: ...001 and ...005 both score 3.0; ...002, ...003 and ...004 all score 1.5; ...006 scores 0.5.
TIED_VALUES = {1: "3.0", 2: "1.5", 3: "1.5", 4: "1.5", 5: "3.0", 6: "0.5"}


def _tied_basket(seed):
    observations = [F.observation(F.address(i), potential_buys=120, valid_buys=100)
                    for i in TIED_VALUES]
    universe = F.frozen(observations)
    scores = [F.score(F.address(i), value, 100) for i, value in TIED_VALUES.items()]
    return F.basket(universe, for_universe(universe, scores), seed)


@pytest.mark.parametrize("seed,order", [(42, TIE_ORDER_SEED_42), (0, TIE_ORDER_SEED_0)])
def test_exact_ties_are_broken_by_the_seed_and_by_nothing_measured(seed, order):
    basket = _tied_basket(seed)
    assert tuple(s.wallet[-3:] for s in basket.selections) == order
    # The tie groups never mix: the two 3.0s hold ranks 1-2 whatever the seed does inside them.
    assert [str(s.value) for s in basket.selections] == ["3.0", "3.0", "1.5", "1.5", "1.5", "0.5"]
    assert [s.rank for s in basket.selections] == [1, 2, 3, 4, 5, 6]


def test_the_seed_reorders_a_tie_group_and_leaves_the_group_alone():
    """If these two were equal the tie-break would be inert and the pins above would prove nothing."""
    assert TIE_ORDER_SEED_42 != TIE_ORDER_SEED_0
    assert set(TIE_ORDER_SEED_42[:2]) == set(TIE_ORDER_SEED_0[:2])
    assert TIE_ORDER_SEED_42[-1] == TIE_ORDER_SEED_0[-1] == "006"


def test_the_same_snapshot_commit_and_seed_produce_the_same_basket():
    first = _tied_basket(42)
    second = _tied_basket(42)
    assert first.wallets == second.wallets
    assert first.snapshot_id == second.snapshot_id
    assert first.step0_digest == second.step0_digest


def test_a_basket_shorter_than_the_derived_count_carries_the_shortfall_as_a_status():
    """Six scorable wallets against a derived request of 250. The gap travels; it does not raise."""
    basket = _tied_basket(42)
    assert basket.requested_count == 250
    assert basket.clamp_state is ClampState.CLAMPED_LOW
    assert len(basket.selections) == 6
    assert basket.short_by == 244
    assert basket.unscorable_count == 0


def test_the_verdict_type_admits_neither_both_nor_neither():
    with pytest.raises(ValueError):
        EligibilityVerdict(account=F.address(1))


def test_an_empty_warehouse_screen_is_a_screen_of_nothing_and_not_an_error():
    screen = screen_warehouse(F.W1.key, [])
    assert screen.rows_screened == 0
    assert screen.admitted == ()
    assert screen.exclusions == ()
