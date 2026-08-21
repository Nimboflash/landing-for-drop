"""Invariants for ``universe``, over generated populations — and the T0 removal battery.

Three groups, and the middle one is the one this file exists for.

**Negative properties.** The things a wrong implementation would break: a census that does not
reconcile, an exclusion with no named rule, a clamp that leaves ``[250, 1000]``, a buffer whose
retained count exceeds the population it is a property of.

**The positive half — a change that must move nothing, moves nothing.** A suite made only of
refusals passes perfectly on an implementation that refuses everything. Four properties here
change something real and require the answer to be *identical*: the order the observations arrive
in, a funnel count measured above the eligibility line, the seed when no two scores tie, and every
post-T0 fact there is. Each of those is a plausible edit, and each would be invisible to a suite
that only asked what raises.

**The §6.4 removal battery.** Ticket 27: after ``T0`` no wallet is removed for exceeding 1,000
buys, sharply increasing activity, reducing activity, or going fully inactive — *proven by a test
that attempts each removal and is refused*. The battery below attempts all four, plus a fifth
motive nobody named, and requires the same refusal for all five. That fifth case is the point: the
guard is conditioned on the **collision** between the frozen membership and the Step 0 count, not
on the reason anybody gives for the removal, so closing the four named motives closes the class
rather than four traced instances.

``derandomize=True`` throughout: the house rule forbids unseeded randomness, and a property suite
that fails only on Tuesdays is worse than none.
"""

from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from contracts import AccountType, LookAheadViolation

import universe_fixtures as F
from universe import (
    DEFAULT_POLICY,
    MINIMUM_ELIGIBLE_UNIVERSE,
    POTENTIAL_BUY_CEILING,
    POTENTIAL_BUY_FLOOR,
    SELECTED_MAX,
    SELECTED_MIN,
    VALID_BUY_CEILING,
    VALID_BUY_FLOOR,
    ClampState,
    ExclusionRule,
    FrozenUniverse,
    IncompleteRankingInputs,
    InsufficientCandidateUniverse,
    UniverseFreezeViolation,
    UniverseMember,
    UnscorableMember,
    boundary_movement,
    build_census,
    classify_account,
    for_universe,
    freeze_universe,
    rank_and_select,
    screen_warehouse,
    selected_wallet_count,
    WarehouseRow,
)
from universe.forward import (
    ForwardActivity,
    ForwardCount,
    ForwardReadRefused,
    ForwardT0Instant,
    ForwardWindowKey,
    forward_ledger,
    forward_report,
)

D = Decimal


def forward_key(window=F.W1):
    """§6.3's window as the **post-T0 side** names it.

    ``ForwardWindowKey`` and ``WindowKey`` have equal member names and are not interchangeable: a
    forward record keyed by the selection side's enum would be a record keyed by an object every
    selection function also accepts. Converting through ``.value`` is the whole of the crossing, and
    it is spelled out here rather than hidden in a fixture so the two families stay visible.
    """
    return ForwardWindowKey(window.key.value)


def forward_t0(window=F.W1):
    """The selection instant, restated in the post-T0 side's own value type."""
    return ForwardT0Instant(block=window.t0.block, timestamp=window.t0.timestamp)

DETERMINISTIC = settings(derandomize=True, max_examples=200, deadline=None)

#: Universe sizes across the whole range §6.5's clamp has to cover, including zero.
universe_sizes = st.integers(min_value=0, max_value=5_000_000)

#: Potential-buy counts spanning both warehouse bounds with room either side.
potential_buys = st.integers(min_value=0, max_value=2_000)

#: Valid-buy counts spanning both eligibility bounds with room either side.
valid_buys = st.integers(min_value=0, max_value=1_500)

account_types = st.sampled_from([AccountType.EOA, AccountType.SAFE, AccountType.ERC4337,
                                 AccountType.OTHER_CONTRACT])


@st.composite
def populations(draw, min_size=1, max_size=8):
    """A window's worth of accounts: distinct indices, arbitrary counts, admissible types."""
    indices = draw(st.lists(st.integers(min_value=1, max_value=200), min_size=min_size,
                            max_size=max_size, unique=True))
    return [
        (index, draw(potential_buys), draw(valid_buys), draw(account_types))
        for index in indices
    ]


def _observations(population):
    return [
        F.observation(F.address(index), potential_buys=potential, valid_buys=valid,
                      account_type=account_type)
        for index, potential, valid, account_type in population
    ]


# -- §6.5's clamp ----------------------------------------------------------------


@DETERMINISTIC
@given(size=universe_sizes)
def test_the_selected_count_never_leaves_the_pre_registered_bounds(size):
    count, state = selected_wallet_count(size)
    assert SELECTED_MIN <= count <= SELECTED_MAX
    assert isinstance(state, ClampState)


@DETERMINISTIC
@given(smaller=universe_sizes, larger=universe_sizes)
def test_a_larger_universe_never_selects_fewer_wallets(smaller, larger):
    """Monotone. A non-monotone clamp would make selection pressure move the wrong way."""
    low, high = sorted((smaller, larger))
    assert selected_wallet_count(low)[0] <= selected_wallet_count(high)[0]


@DETERMINISTIC
@given(size=universe_sizes)
def test_the_clamp_state_and_the_count_agree(size):
    """The state is a claim about the count; the two cannot disagree.

    The bounds quoted here are the ones ``tests/hand_computed/test_universe.py`` pins by hand —
    24,999 is the largest universe that clamps low, 100,100 the smallest that clamps high.
    """
    count, state = selected_wallet_count(size)
    if state is ClampState.CLAMPED_LOW:
        assert count == SELECTED_MIN and size <= 24_999
    elif state is ClampState.CLAMPED_HIGH:
        assert count == SELECTED_MAX and size >= 100_100
    else:
        assert SELECTED_MIN <= count <= SELECTED_MAX and 25_000 <= size <= 100_099


# -- the two stages --------------------------------------------------------------


@DETERMINISTIC
@given(counts=st.lists(potential_buys, min_size=0, max_size=12))
def test_the_warehouse_screen_accounts_for_every_row_it_saw(counts):
    rows = [WarehouseRow(address=F.address(index + 1), potential_buys=count)
            for index, count in enumerate(counts)]
    screen = screen_warehouse(F.W1.key, rows)

    assert len(screen.admitted) + len(screen.exclusions) == screen.rows_screened == len(rows)
    for row in screen.admitted:
        assert POTENTIAL_BUY_FLOOR <= row.potential_buys <= POTENTIAL_BUY_CEILING
    for exclusion in screen.exclusions:
        assert exclusion.rule in ExclusionRule
        assert exclusion.evidence


@DETERMINISTIC
@given(population=populations())
def test_every_account_leaves_by_a_named_rule_or_does_not_leave(population):
    """The census has to reconcile, and there is nothing for an unattributed exclusion to be."""
    observations = _observations(population)
    screen = F.screened(observations)
    verdicts = [classify_account(o, DEFAULT_POLICY, screen) for o in observations
                if o.account in screen.admitted_addresses]
    from universe import EligibilityVerdict
    verdicts.extend(EligibilityVerdict(account=e.account, exclusion=e)
                    for e in screen.exclusions)
    admitted_observations = [o for o in observations if o.account in screen.admitted_addresses]
    movement = boundary_movement(admitted_observations, verdicts)

    census = build_census(verdicts, screen.rows_screened, movement, F.W1.key)

    assert census.admitted_count + census.excluded_total == census.considered
    assert {entry.rule for entry in census.exclusions_by_rule} == set(ExclusionRule)
    assert census.movement.retained_by_buffer <= census.admitted_count
    for verdict in verdicts:
        assert verdict.is_admitted or verdict.exclusion.rule in ExclusionRule


@DETERMINISTIC
@given(population=populations())
def test_an_admitted_account_is_always_inside_the_final_band(population):
    observations = _observations(population)
    screen = F.screened(observations)
    for observation in observations:
        if observation.account not in screen.admitted_addresses:
            continue
        verdict = classify_account(observation, DEFAULT_POLICY, screen)
        if verdict.is_admitted:
            assert VALID_BUY_FLOOR <= verdict.admitted.valid_buys <= VALID_BUY_CEILING
            assert POTENTIAL_BUY_FLOOR <= verdict.admitted.potential_buys <= POTENTIAL_BUY_CEILING


@DETERMINISTIC
@given(population=populations())
def test_the_buffer_only_ever_claims_accounts_it_actually_carried(population):
    """``crossed_boundary`` is true exactly when the potential count was outside ``[20, 1000]``."""
    observations = _observations(population)
    screen = F.screened(observations)
    for observation in observations:
        if observation.account not in screen.admitted_addresses:
            continue
        verdict = classify_account(observation, DEFAULT_POLICY, screen)
        if not verdict.is_admitted:
            continue
        inside_final_band = (
            VALID_BUY_FLOOR <= verdict.admitted.potential_buys <= VALID_BUY_CEILING)
        assert verdict.admitted.crossed_boundary is not inside_final_band


# -- the positive half: a change that must move nothing, moves nothing -----------


def _universe_and_scores(population, values=None):
    observations = _observations(population)
    universe = F.frozen(observations)
    scores = [
        F.score(member.wallet,
                (values or {}).get(member.wallet, "1.5"),
                member.valid_buys)
        for member in universe.members
    ]
    return universe, scores


@DETERMINISTIC
@given(population=populations(min_size=2))
def test_the_order_the_observations_arrive_in_moves_nothing(population):
    """Reversing the input must produce the identical universe, identity and basket.

    A membership that depended on arrival order would hash differently for the same universe, and
    every downstream pin would read as a different experiment.
    """
    observations = _observations(population)
    assume(any(VALID_BUY_FLOOR <= o.valid_buys <= VALID_BUY_CEILING
               and POTENTIAL_BUY_FLOOR <= o.potential_buys <= POTENTIAL_BUY_CEILING
               for o in observations))

    forwards = F.frozen(observations)
    backwards = F.frozen(list(reversed(observations)))

    assert forwards.wallets == backwards.wallets
    assert forwards.snapshot_id == backwards.snapshot_id
    assert forwards.measurement.eligible_universe_size == \
        backwards.measurement.eligible_universe_size

    scores = [F.score(m.wallet, "1.5", m.valid_buys) for m in forwards.members]
    first = F.basket(forwards, for_universe(forwards, scores))
    second = F.basket(backwards, for_universe(backwards, scores))
    assert first.wallets == second.wallets
    assert first.step0_digest == second.step0_digest


@DETERMINISTIC
@given(population=populations(min_size=1), inflation=st.integers(min_value=1, max_value=10_000))
def test_a_funnel_count_above_the_eligibility_line_moves_no_selected_wallet(inflation,
                                                                           population):
    """``total_active_accounts`` is measured above the eligible line and must not reach selection.

    §6.5 derives the count from the *eligible* universe. A basket that moved when the chain got
    busier would be a basket derived from the wrong denominator.
    """
    observations = _observations(population)
    assume(any(VALID_BUY_FLOOR <= o.valid_buys <= VALID_BUY_CEILING
               and POTENTIAL_BUY_FLOOR <= o.potential_buys <= POTENTIAL_BUY_CEILING
               for o in observations))

    base = F.frozen(observations)
    busier = F.frozen(observations,
                      total_active_accounts=base.measurement.total_active_accounts + inflation)

    assert base.measurement.eligible_universe_size == busier.measurement.eligible_universe_size
    assert base.wallets == busier.wallets

    scores = [F.score(m.wallet, "1.5", m.valid_buys) for m in base.members]
    quiet = F.basket(base, for_universe(base, scores))
    loud = F.basket(busier, for_universe(busier, scores))
    assert quiet.wallets == loud.wallets
    assert quiet.requested_count == loud.requested_count
    assert quiet.clamp_state is loud.clamp_state


@DETERMINISTIC
@given(seed_a=st.integers(min_value=0, max_value=10 ** 6),
       seed_b=st.integers(min_value=0, max_value=10 ** 6),
       size=st.integers(min_value=2, max_value=8))
def test_the_seed_moves_nothing_when_no_two_scores_tie(seed_a, seed_b, size):
    """The seed breaks ties and does nothing else.

    A seed that reordered distinct scores would mean the ranking depended on a number that is not
    ``buy_quality_30d``, which is the one thing §6.5 says selection ranks on.
    """
    observations = [F.observation(F.address(i), potential_buys=120, valid_buys=100)
                    for i in range(1, size + 1)]
    universe = F.frozen(observations)
    scores = [F.score(F.address(i), str(i), 100) for i in range(1, size + 1)]
    inputs = for_universe(universe, scores)

    first = F.basket(universe, inputs, seed_a)
    second = F.basket(universe, inputs, seed_b)
    assert first.wallets == second.wallets
    assert [s.rank for s in first.selections] == [s.rank for s in second.selections]


@DETERMINISTIC
@given(forward=st.integers(min_value=0, max_value=50_000))
def test_every_post_t0_fact_there_is_moves_no_selected_wallet(forward):
    """The whole point of ticket 27, stated as a property rather than as a barrier.

    Whatever a wallet did after T0 — nothing at all, or five times the eligibility ceiling — the
    basket is the same basket, because the basket was already built when the record was made.
    """
    observations = [F.observation(F.address(i), potential_buys=120, valid_buys=100)
                    for i in (1, 2, 3)]
    universe = F.frozen(observations)
    scores = [F.score(F.address(i), str(i), 100) for i in (1, 2, 3)]
    inputs = for_universe(universe, scores)
    basket = F.basket(universe, inputs)
    before = basket.wallets
    mount = F.mounted(universe, basket, inputs)

    activities = [
        ForwardActivity(
            wallet=wallet,
            window_key=forward_key(),
            snapshot_id=mount.artifact.artifact_hash,
            forward_valid_buys=ForwardCount(forward if index else 0),
            forward_days=180,
            first_forward_block=F.W1.t0.block + 1,
            measured_at_block=F.W1.forward_end_block,
            t0=forward_t0(),
        )
        for index, wallet in enumerate(basket.wallets)
    ]
    ledger = forward_ledger(mount, activities)
    report = forward_report(ledger)

    assert basket.wallets == before
    assert report.n_wallets == 3
    assert report.max_forward_valid_buys == forward


# -- §6.4: the removal battery ---------------------------------------------------


#: §6.4's four motives, plus a fifth nobody named. The fifth is the load-bearing one: a guard
#: conditioned on the *reason* would close four traced instances and leave the class open, so the
#: refusal below is conditioned on the collision between the membership and the Step 0 count and
#: never asks why.
REMOVAL_MOTIVES = (
    "the wallet exceeded 1,000 buys after T0",
    "the wallet sharply increased its activity after T0",
    "the wallet reduced its activity after T0",
    "the wallet went fully inactive after T0",
    "a motive §6.4 never names, invented after the fact",
)


def _five_account_universe():
    observations = [F.observation(F.address(i), potential_buys=120, valid_buys=100)
                    for i in (1, 2, 3, 4, 5)]
    return F.measured(observations)


@pytest.mark.parametrize("motive", REMOVAL_MOTIVES)
def test_no_wallet_can_be_removed_after_t0_for_any_reason(motive):
    """Attempt the removal — every one of the five — and require the same refusal.

    The removal is attempted the only way this package makes available: rebuilding the freeze from
    a verdict list one member short. There is no ``filter``, no ``exclude``, no ``drop`` and no
    ``with_members``, so this is the whole of the surface.
    """
    measurement, verdicts, _census, _screen = _five_account_universe()
    victim = F.address(3)
    survivors = [v for v in verdicts if v.account != victim]
    assert len(survivors) == len(verdicts) - 1, motive

    with pytest.raises(UniverseFreezeViolation) as raised:
        freeze_universe(measurement, survivors, F.SNAPSHOT, revision=F.REVISION)
    message = str(raised.value)
    assert "4 member(s)" in message and "5" in message


@pytest.mark.parametrize("motive", REMOVAL_MOTIVES)
def test_the_refusal_does_not_ask_why(motive):
    """Same refusal, same message shape, for all five motives — including the unnamed one.

    A guard that read the motive would be a guard on the traced instances. This one is conditioned
    on the collision.
    """
    measurement, verdicts, _census, _screen = _five_account_universe()
    frozen_members = tuple(
        UniverseMember(wallet=v.admitted.account, account_type=v.admitted.account_type,
                       valid_buys=v.admitted.valid_buys)
        for v in sorted((v for v in verdicts if v.is_admitted), key=lambda v: v.account)
    )
    with pytest.raises(UniverseFreezeViolation):
        FrozenUniverse(window=F.W1, members=frozen_members[1:], measurement=measurement,
                       dataset_snapshot=F.SNAPSHOT, revision=F.REVISION)


def test_the_frozen_universe_offers_no_removal_api_at_all():
    """The refusal above is a cross-check. This is the reason it is the only surface there is."""
    surface = {name for name in dir(FrozenUniverse) if not name.startswith("_")}
    for forbidden in ("filter", "exclude", "drop", "remove", "add", "with_members", "without"):
        assert forbidden not in surface
    assert "wallets" in surface and "members" in FrozenUniverse.__dataclass_fields__


def test_a_wallet_that_blew_up_and_went_dormant_stays_in_the_sample():
    """§6.4's own sentence, as an executable statement.

    Two wallets: one runs 5,000 buys after T0 — five times the eligibility ceiling — and one does
    nothing at all. Both are still in the basket, and both are still in the churn denominator.
    """
    observations = [F.observation(F.address(i), potential_buys=120, valid_buys=100)
                    for i in (1, 2)]
    universe = F.frozen(observations)
    scores = [F.score(F.address(i), str(i), 100) for i in (1, 2)]
    inputs = for_universe(universe, scores)
    basket = F.basket(universe, inputs)

    exploded, dormant = basket.wallets
    mount = F.mounted(universe, basket, inputs)
    sealed_id = mount.artifact.artifact_hash
    ledger = forward_ledger(mount, [
        ForwardActivity(wallet=exploded, window_key=forward_key(), snapshot_id=sealed_id,
                        forward_valid_buys=ForwardCount(5_000), forward_days=180,
                        first_forward_block=F.W1.t0.block + 1,
                        measured_at_block=F.W1.forward_end_block, t0=forward_t0()),
        ForwardActivity(wallet=dormant, window_key=forward_key(), snapshot_id=sealed_id,
                        forward_valid_buys=ForwardCount(0), forward_days=180,
                        first_forward_block=F.W1.t0.block + 1,
                        measured_at_block=F.W1.forward_end_block, t0=forward_t0()),
    ])
    report = forward_report(ledger)

    assert set(basket.wallets) == {exploded, dormant}
    assert report.n_wallets == 2
    assert report.n_dormant == 1
    assert report.max_forward_valid_buys == 5_000, (
        "a bound here would be §6.4's forbidden removal arriving as a validation error")


def test_a_small_universe_cannot_be_frozen_without_an_explicit_revision():
    """§6.1's floor, exercised on its own rather than by making every fixture 10,000 long.

    Every other fixture in this suite passes a :class:`DesignRevision` so the population can be a
    size a reviewer counts by hand. This is the test that pays for that.
    """
    measurement, verdicts, _census, _screen = _five_account_universe()
    assert measurement.eligible_universe_size < MINIMUM_ELIGIBLE_UNIVERSE

    with pytest.raises(InsufficientCandidateUniverse):
        freeze_universe(measurement, verdicts, F.SNAPSHOT, revision=None)

    revised = freeze_universe(measurement, verdicts, F.SNAPSHOT, revision=F.REVISION)
    assert len(revised.members) == 5
    assert revised.revision is F.REVISION


def test_the_revision_travels_into_the_universes_identity():
    """"Explicitly revised" is four facts hashed into the snapshot, not a flag somebody set."""
    measurement, verdicts, _census, _screen = _five_account_universe()
    from universe import DesignRevision
    other = DesignRevision(rule_id="fixture-only", revised_by="somebody else",
                           reason=F.REVISION.reason, recorded_at_commit=F.COMMIT)
    first = freeze_universe(measurement, verdicts, F.SNAPSHOT, revision=F.REVISION)
    second = freeze_universe(measurement, verdicts, F.SNAPSHOT, revision=other)
    assert first.snapshot_id != second.snapshot_id


# -- the ranked population is never narrowed -------------------------------------


@DETERMINISTIC
@given(size=st.integers(min_value=2, max_value=6), drop=st.integers(min_value=0, max_value=5))
def test_a_missing_score_is_refused_rather_than_shrinking_the_ranked_population(size, drop):
    """Equality of coverage, not subset. A dict could not tell zero from never-arrived."""
    assume(drop < size)
    observations = [F.observation(F.address(i), potential_buys=120, valid_buys=100)
                    for i in range(1, size + 1)]
    universe = F.frozen(observations)
    scores = [F.score(F.address(i), "1.5", 100) for i in range(1, size + 1)]

    with pytest.raises(IncompleteRankingInputs):
        for_universe(universe, scores[:drop] + scores[drop + 1:])

    stated = for_universe(
        universe,
        scores[:drop] + scores[drop + 1:],
        unscorable=(UnscorableMember(wallet=F.address(drop + 1),
                                     reason="every buy priced at zero"),),
    )
    assert stated.covered == size


@DETERMINISTIC
@given(size=st.integers(min_value=1, max_value=6))
def test_a_score_for_a_wallet_the_universe_does_not_contain_is_refused(size):
    observations = [F.observation(F.address(i), potential_buys=120, valid_buys=100)
                    for i in range(1, size + 1)]
    universe = F.frozen(observations)
    scores = [F.score(F.address(i), "1.5", 100) for i in range(1, size + 2)]
    with pytest.raises(IncompleteRankingInputs):
        for_universe(universe, scores)


# -- the post-T0 type wall -------------------------------------------------------


@pytest.mark.parametrize("shape,call", [
    ("an ordering comparison", lambda c: c > 0),
    ("a reversed ordering comparison", lambda c: 0 < c),
    ("an equality test", lambda c: c == 0),
    ("an inequality test", lambda c: c != 0),
    ("a truth test", lambda c: bool(c)),
    ("an int() conversion", lambda c: int(c)),
    ("arithmetic", lambda c: c + 1),
    ("reversed arithmetic", lambda c: 1 + c),
    ("a min() over a mixed sequence", lambda c: min([c, c])),
])
def test_every_spelling_of_a_still_active_filter_refuses(shape, call):
    """Sort, group, dedupe, set-test, dict-key, truth-test. Each one raises."""
    with pytest.raises(ForwardReadRefused):
        call(ForwardCount(7))


def test_a_post_t0_count_cannot_be_a_dict_key_or_a_set_member():
    """Unhashable is the one people forget, and the dict and the set are how the filter is written."""
    with pytest.raises(TypeError):
        {ForwardCount(7): "still active"}
    with pytest.raises(TypeError):
        set([ForwardCount(7)])


def test_the_post_t0_count_does_not_print_its_number():
    """It must not leak into a log somebody decides from."""
    assert repr(ForwardCount(4_242)) == "<ForwardCount post-T0>"
    assert "4242" not in repr(ForwardCount(4_242))


def test_pre_t0_activity_cannot_be_laundered_through_a_post_t0_record():
    """The mirror guard, and the half that is easy to leave out."""
    with pytest.raises(LookAheadViolation):
        ForwardActivity(
            wallet=F.address(1), window_key=forward_key(), snapshot_id="s",
            forward_valid_buys=ForwardCount(1), forward_days=180,
            first_forward_block=F.W1.t0.block, measured_at_block=F.W1.forward_end_block,
            t0=forward_t0(),
        )


def test_a_bare_int_cannot_stand_in_for_a_post_t0_count():
    with pytest.raises(ForwardReadRefused):
        ForwardActivity(
            wallet=F.address(1), window_key=forward_key(), snapshot_id="s",
            forward_valid_buys=3, forward_days=180,
            first_forward_block=F.W1.t0.block + 1, measured_at_block=F.W1.forward_end_block,
            t0=forward_t0(),
        )
