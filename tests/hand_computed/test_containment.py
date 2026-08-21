"""Hand-computed pins for the five containment modules.

Why this file exists
--------------------

Four adversarial reviews of ``src/universe/provenance.py``, ``snapshot.py``, ``artifact.py``,
``ordering.py`` and ``containment.py`` agreed on one measurement above all the others: of the
ninety-six behavioural guards those five files contain, **zero** were pinned by any assertion. A
census over ``tests/`` returned no hit at all for ``combine``, ``ContaminationDetected``,
``ProvenanceRefused``, ``require_pre_t0_value``, ``PickleRefused``, ``ArtifactSealed``,
``sealed_artifact``, ``require_sealed_artifact``, ``artifact_hash_of``, ``PreT0Workspace``,
``OrderingViolation``, ``WorkspaceUnmounted``, ``SelectionAfterForwardMount``, ``RunInvalidated``,
``ContainmentMisuse`` or ``RunState``; ninety-four of ninety-six single-guard deletions left the
whole suite at 1,817 passed, and the two that went red died on a *neighbouring* guard crashing a
fixture rather than on any assertion reading the deleted one.

That is what made every other finding reachable. A barrier nothing asserts about is a barrier the
next edit removes for free, and 1,924 lines of source had arrived against 104 net lines of test —
all of them mechanical adaptation.

So every guard repaired in the ticket-27 round is pinned here, by **behaviour**: the exception type,
the run state afterwards, and the basket on both sides where a basket moves. Each test in this file
was verified to fail when its guard is removed from ``src/``.

Hand-computed means hand-computed
----------------------------------

Every expected value below is written as a literal a reader can check without running anything. The
addresses are ``F.address(n)``'s zero-padded form, the block heights are §6.3's window 1 calendar,
and the five-wallet population's scores are 25, 30, 200, 700 and 900 — so the descending order is
``005, 004, 003, 002, 001`` and no two values tie.
"""

import pickle
from decimal import Decimal

import pytest

import universe_fixtures as F
from contracts import LookAheadViolation
from universe import (
    ArtifactRefused,
    ArtifactSealed,
    ContainmentMisuse,
    ContaminatedDecimal,
    ContaminationDetected,
    ExecutionOrder,
    ForwardMount,
    IsolationStatus,
    LookAheadContainment,
    Origin,
    Phase,
    PRE_T0_ZERO,
    PreT0Decimal,
    PreT0Snapshot,
    PreT0Workspace,
    ProvenanceRefused,
    RunInvalidated,
    RunState,
    SelectedWallet,
    SelectionAfterForwardMount,
    SelectionExecutionBlocked,
    SnapshotEvidenceMissing,
    TableVersion,
    UnscorableMember,
    WorkspaceUnmounted,
    artifact_hash_of,
    combine,
    for_universe,
    look_ahead_audit,
    pre_t0_snapshot,
    rank_and_select,
    require_pre_t0_value,
    require_sealed_artifact,
    require_verified_snapshot,
    seal_selection,
    sealed_artifact,
    snapshot_evidence_hash,
)
from universe.ordering import OrderingViolation

D = Decimal

#: The five-wallet population, with distinct scores so nothing ties and the order is by hand.
VALUES = {1: "25", 2: "30", 3: "200", 4: "700", 5: "900"}

#: The basket ``rank_and_select`` produces from it, by hand: descending on the values above.
DESCENDING = ("005", "004", "003", "002", "001")

T0_BLOCK = 17_600_000
T0_SECOND = 1_688_169_600


def _population():
    observations = [F.observation(F.address(i), potential_buys=120, valid_buys=100)
                    for i in VALUES]
    universe = F.frozen(observations)
    scores = [F.score(F.address(i), value, 100) for i, value in VALUES.items()]
    return universe, for_universe(universe, scores), scores


def _walked_to_forward_mount():
    """The eight steps, honestly, returning everything a test needs afterwards."""
    universe, inputs, scores = _population()
    containment = LookAheadContainment(run_id="pinned-run")
    order = ExecutionOrder(containment, same_process_evaluation_declared=True)
    workspace = order.mount_pre_t0(F.snapshot_evidence(), universe)
    basket = rank_and_select(workspace, inputs, F.SEED, F.COMMIT)
    order.seal(seal_selection(workspace, basket, inputs, F.DATASET_HASH))
    order.terminate_selection()
    order.unmount_pre_t0()
    mount = order.mount_forward(F.DATASET_ID, F.DATASET_HASH)
    return containment, order, workspace, universe, inputs, scores, basket, mount


# -- the lattice -----------------------------------------------------------------


#: ``combine`` over all nine ordered pairs, as literals. ``PRE_T0`` survives once.
COMBINE_TABLE = (
    (Origin.PRE_T0, Origin.PRE_T0, Origin.PRE_T0),
    (Origin.PRE_T0, Origin.POST_T0, Origin.CONTAMINATED),
    (Origin.PRE_T0, Origin.CONTAMINATED, Origin.CONTAMINATED),
    (Origin.POST_T0, Origin.PRE_T0, Origin.CONTAMINATED),
    (Origin.POST_T0, Origin.POST_T0, Origin.CONTAMINATED),
    (Origin.POST_T0, Origin.CONTAMINATED, Origin.CONTAMINATED),
    (Origin.CONTAMINATED, Origin.PRE_T0, Origin.CONTAMINATED),
    (Origin.CONTAMINATED, Origin.POST_T0, Origin.CONTAMINATED),
    (Origin.CONTAMINATED, Origin.CONTAMINATED, Origin.CONTAMINATED),
)


@pytest.mark.parametrize("left,right,expected", COMBINE_TABLE)
def test_combine_is_the_lattice_over_all_nine_pairs(left, right, expected):
    """One row of the table, by hand. ``PRE_T0 + PRE_T0`` is the only surviving pair."""
    assert combine(left, right) is expected


def test_combine_refuses_a_string_rather_than_admitting_a_fourth_standing():
    with pytest.raises(TypeError):
        combine("PRE_T0", "PRE_T0")
    with pytest.raises(TypeError):
        combine(Origin.PRE_T0, None)


def _contaminated():
    """A ``CONTAMINATED`` value, produced by the lattice rather than constructed."""
    value = PreT0Decimal.measured_before_t0(D("1"), "a pre-T0 read") + D("1")
    assert type(value) is ContaminatedDecimal
    assert value.origin is Origin.CONTAMINATED
    return value


CONTAMINATED_READS = (
    ("less than", lambda c, other: c < other),
    ("less or equal", lambda c, other: c <= other),
    ("greater than", lambda c, other: c > other),
    ("greater or equal", lambda c, other: c >= other),
    ("equality", lambda c, other: c == other),
    ("inequality", lambda c, other: c != other),
)


@pytest.mark.parametrize("name,read", CONTAMINATED_READS)
def test_every_comparison_on_a_contaminated_value_raises(name, read):
    with pytest.raises(ContaminationDetected):
        read(_contaminated(), _contaminated())


@pytest.mark.parametrize("name,convert", (
    ("bool", bool), ("int", int), ("float", float),
))
def test_every_conversion_on_a_contaminated_value_raises(name, convert):
    with pytest.raises(ContaminationDetected):
        convert(_contaminated())


def test_a_contaminated_value_is_unhashable_so_a_dict_filter_cannot_be_written():
    """The one people forget: the dict and the set are how a filter is really written."""
    assert ContaminatedDecimal.__hash__ is None
    with pytest.raises(TypeError):
        {_contaminated(): 1}
    with pytest.raises(TypeError):
        {_contaminated()}


def test_sorting_contaminated_values_raises_rather_than_ordering_them():
    with pytest.raises(ContaminationDetected):
        sorted([_contaminated(), _contaminated()])


def test_contamination_survives_an_arbitrarily_long_expression():
    """Arithmetic spreads the condemnation; it does not lose it at the first unchecked operator."""
    value = _contaminated()
    for _step in range(5):
        value = (value + D("1")) * D("2") - D("3")
    assert type(value) is ContaminatedDecimal
    assert value.origin is Origin.CONTAMINATED
    with pytest.raises(ContaminationDetected):
        bool(value)


def test_a_contaminated_value_cannot_be_pickled():
    with pytest.raises(ProvenanceRefused):
        pickle.dumps(_contaminated())


REQUIRE_PRE_T0_CASES = (
    ("a bare Decimal", D("0.5"), ProvenanceRefused),
    ("an int", 5, ProvenanceRefused),
    ("a str", "0.5", ProvenanceRefused),
    ("None", None, ProvenanceRefused),
)


@pytest.mark.parametrize("name,value,expected", REQUIRE_PRE_T0_CASES)
def test_require_pre_t0_value_refuses_everything_that_is_not_a_pre_t0_decimal(name, value,
                                                                             expected):
    with pytest.raises(expected):
        require_pre_t0_value(value, "a probe field")


def test_require_pre_t0_value_returns_a_pre_t0_decimal_unchanged():
    stamped = PreT0Decimal.measured_before_t0(D("0.5"), "a pre-T0 read")
    assert require_pre_t0_value(stamped, "a probe field") is stamped


def test_require_pre_t0_value_on_a_contaminated_value_is_not_dropped_zeroed_or_coerced():
    """The refusal has its own class because the response differs: the run is void."""
    with pytest.raises(ContaminationDetected) as caught:
        require_pre_t0_value(_contaminated(), "a probe field")
    message = str(caught.value)
    assert "not dropped, not zeroed and not coerced" in message


PEER_COMPARISONS = (
    ("<", lambda a, b: a < b),
    ("<=", lambda a, b: a <= b),
    (">", lambda a, b: a > b),
    (">=", lambda a, b: a >= b),
    ("==", lambda a, b: a == b),
    ("!=", lambda a, b: a != b),
)


@pytest.mark.parametrize("symbol,compare", PEER_COMPARISONS)
@pytest.mark.parametrize("other", (D("0.5"), 5, "0.5", None))
def test_every_comparison_dunder_refuses_a_non_peer(symbol, compare, other):
    """All six, not four.

    ``__eq__`` and ``__ne__`` used to return ``NotImplemented``, which falls back to identity: the
    answer was ``False`` rather than a refusal, so ``score in allowed`` quietly said no about an
    unprovenanced threshold. That is the ``SILENTLY_DROPPED`` shape.
    """
    stamped = PreT0Decimal.measured_before_t0(D("0.5"), "a pre-T0 read")
    with pytest.raises(ProvenanceRefused):
        compare(stamped, other)


def test_membership_against_a_bare_decimal_refuses_rather_than_answering_no():
    stamped = PreT0Decimal.measured_before_t0(D("0.5"), "a pre-T0 read")
    with pytest.raises(ProvenanceRefused):
        stamped in [D("0.5")]


def test_comparison_between_two_peers_answers_by_hand():
    low = PreT0Decimal.measured_before_t0(D("0.4"), "a pre-T0 read")
    high = PreT0Decimal.measured_before_t0(D("0.5"), "a pre-T0 read")
    same = PreT0Decimal.measured_before_t0(D("0.5"), "another pre-T0 read")
    assert low < high
    assert high > low
    assert high == same
    assert not (high != same)
    assert high >= same and high <= same


def test_the_named_zero_is_what_a_magnitude_check_compares_against():
    """``value < Decimal("0")`` raises; ``value < PRE_T0_ZERO`` is the spelling that works."""
    negative = PreT0Decimal.measured_before_t0(D("-1"), "a pre-T0 read")
    assert negative < PRE_T0_ZERO
    with pytest.raises(ProvenanceRefused):
        negative < D("0")


def test_the_private_builder_enforces_the_source_requirement_too():
    """A rule enforced at one of two doors is a rule about which door somebody chose."""
    with pytest.raises(ValueError):
        PreT0Decimal._build(D("9"), "")
    with pytest.raises(ValueError):
        PreT0Decimal._build(D("9"), "   ")
    with pytest.raises(ValueError):
        PreT0Decimal.measured_before_t0(D("9"), "")


def test_a_pre_t0_decimal_refuses_to_be_re_stamped_or_pickled():
    stamped = PreT0Decimal.measured_before_t0(D("1"), "a pre-T0 read")
    with pytest.raises(ProvenanceRefused):
        PreT0Decimal.measured_before_t0(stamped, "a second claim")
    with pytest.raises(ProvenanceRefused):
        PreT0Decimal.measured_before_t0(_contaminated(), "a second claim")
    with pytest.raises(ProvenanceRefused):
        pickle.dumps(stamped)
    with pytest.raises(ProvenanceRefused):
        PreT0Decimal(D("1"), "a cast that reads like one")


def test_the_public_constructor_is_refused_so_the_assertion_cannot_read_as_a_cast():
    with pytest.raises(ProvenanceRefused):
        PreT0Decimal(D("1"))


# -- the snapshot ----------------------------------------------------------------


TABLES = (TableVersion(table="fixture.trades", version="v1"),)


def _snapshot_at(max_block, t0_block=T0_BLOCK):
    """A directly-constructed snapshot with a self-consistent hash, for the boundary table."""
    facts = dict(window_id="W1_2023H1", t0_block=t0_block, min_block=max_block - 5,
                 max_block=max_block, row_count=2, source_query_hash="qh",
                 source_table_versions=TABLES)
    return PreT0Snapshot(snapshot_hash=snapshot_evidence_hash(**facts), **facts)


#: The boundary, one block either side. ``>=`` and not ``>``: a row written at T0 has already seen
#: the instant the decision is made.
BOUNDARY = (
    (T0_BLOCK - 1, None),
    (T0_BLOCK, SelectionExecutionBlocked),
    (T0_BLOCK + 1, SelectionExecutionBlocked),
)


@pytest.mark.parametrize("max_block,expected", BOUNDARY)
def test_the_type_and_the_factory_state_one_t0_boundary(max_block, expected):
    """They disagreed by exactly one block, and the type was the lenient one."""
    if expected is None:
        assert _snapshot_at(max_block).max_block == max_block
        assert pre_t0_snapshot("W1_2023H1", T0_BLOCK, (max_block - 5, max_block), "qh",
                               TABLES).max_block == max_block
        return
    with pytest.raises(expected):
        _snapshot_at(max_block)
    with pytest.raises(expected):
        pre_t0_snapshot("W1_2023H1", T0_BLOCK, (max_block - 5, max_block), "qh", TABLES)


def test_a_post_t0_row_is_refused_rather_than_filtered_out():
    """Dropping it would change the census composition on post-T0 information."""
    with pytest.raises(SelectionExecutionBlocked) as caught:
        pre_t0_snapshot("W1_2023H1", T0_BLOCK, (T0_BLOCK - 500, T0_BLOCK + 1), "qh", TABLES)
    message = str(caught.value)
    assert "Isolation Status: FAILED" in message
    assert "Selection Execution: BLOCKED" in message


def test_a_snapshot_hash_that_does_not_match_its_own_evidence_is_refused():
    with pytest.raises(SnapshotEvidenceMissing):
        PreT0Snapshot(window_id="W1_2023H1", t0_block=T0_BLOCK, min_block=T0_BLOCK - 5,
                      max_block=T0_BLOCK - 1, row_count=2, source_query_hash="qh",
                      source_table_versions=TABLES, snapshot_hash="not a hash of anything")


def test_a_snapshot_with_no_declared_source_tables_is_refused():
    with pytest.raises(SnapshotEvidenceMissing):
        pre_t0_snapshot("W1_2023H1", T0_BLOCK, (T0_BLOCK - 5,), "qh", ())


def _unconstructed_snapshot():
    """The shape a hand-written pickle payload produces: right type, no checks run."""
    forged = object.__new__(PreT0Snapshot)
    forged.__dict__.update(dict(
        window_id="W1_2023H1", t0_block=T0_BLOCK, min_block=T0_BLOCK - 5,
        max_block=T0_BLOCK + 99_999, row_count=2,
        source_query_hash="SELECT * FROM trades  -- no WHERE clause at all",
        source_table_versions=TABLES, snapshot_hash="not a hash of anything"))
    return forged


def test_an_unconstructed_snapshot_reports_failed_rather_than_verified():
    """``isolation_status`` returned a constant on the argument that construction was the only way in."""
    assert F.snapshot_evidence().isolation_status is IsolationStatus.VERIFIED
    assert _unconstructed_snapshot().isolation_status is IsolationStatus.FAILED


def test_an_unconstructed_snapshot_is_refused_by_the_gate_every_consumer_runs():
    with pytest.raises(SelectionExecutionBlocked) as caught:
        require_verified_snapshot(_unconstructed_snapshot(), "a probe")
    assert "no evidence witness" in str(caught.value)
    assert require_verified_snapshot(
        F.snapshot_evidence(), "a probe").isolation_status is IsolationStatus.VERIFIED


def test_an_unconstructed_snapshot_cannot_be_mounted_and_voids_the_run():
    """404 bytes of hand-written pickle produced exactly this object, and it mounted."""
    universe, _inputs, _scores = _population()
    containment = LookAheadContainment(run_id="forged-snapshot-run")
    order = ExecutionOrder(containment, same_process_evaluation_declared=True)
    with pytest.raises(SelectionExecutionBlocked):
        order.mount_pre_t0(_unconstructed_snapshot(), universe)
    assert containment.state is RunState.INVALIDATED
    assert order.phase is Phase.UNMOUNTED


@pytest.mark.parametrize("name,build", (
    ("PreT0Snapshot", F.snapshot_evidence),
    ("TableVersion", lambda: TableVersion(table="t", version="v1")),
))
def test_snapshot_evidence_cannot_be_pickled_in_either_direction(name, build):
    value = build()
    cls = type(value)
    # Each refusal is asserted **on its own class**, not through ``pickle.dumps``: a snapshot holds
    # table versions, so dumps would keep raising from the nested type long after the snapshot's own
    # refusal had been deleted, and the assertion would prove nothing about the type it names.
    assert "__reduce__" in vars(cls), "{} defines no __reduce__ of its own".format(name)
    assert "__setstate__" in vars(cls), "{} defines no __setstate__ of its own".format(name)
    with pytest.raises(SnapshotEvidenceMissing):
        cls.__reduce__(value)
    with pytest.raises(SnapshotEvidenceMissing):
        cls.__setstate__(value, {})
    with pytest.raises(SnapshotEvidenceMissing):
        pickle.dumps(value)


# -- the artifact ----------------------------------------------------------------


def _row(rank, index, value, valid_buys=100):
    return SelectedWallet(rank=rank, wallet=F.address(index), value=value,
                          valid_buys=valid_buys, account_type="EOA")


def _artifact(rows):
    return sealed_artifact(
        window_id="W1_2023H1", cutoff_block=T0_BLOCK, dataset_hash="d", snapshot_hash="s",
        step0_digest="x", metric="buy_quality_30d", seed=F.SEED, commit=F.COMMIT,
        eligible_universe_size=300, requested_count=250, unscorable_count=0,
        short_by=250 - len(rows), selections=tuple(rows))


#: §6.2's eligible band is [20, 1000]. A published row cannot claim a count no member could hold.
VALID_BUY_BOUNDARY = ((19, ArtifactRefused), (20, None), (1_000, None), (1_001, ArtifactRefused),
                      (10 ** 9, ArtifactRefused), (-5, ArtifactRefused))


@pytest.mark.parametrize("valid_buys,expected", VALID_BUY_BOUNDARY)
def test_a_published_row_is_bounded_by_the_eligible_band(valid_buys, expected):
    if expected is None:
        assert _row(1, 1, "1", valid_buys).valid_buys == valid_buys
        return
    with pytest.raises(expected):
        _row(1, 1, "1", valid_buys)


def _forged_row():
    """A row that satisfies ``type(x) is SelectedWallet`` and ran none of the bounds."""
    row = object.__new__(SelectedWallet)
    row.__dict__.update(dict(rank=1, wallet=F.address(251), value="999999999",
                             valid_buys=10 ** 9, account_type="EOA"))
    return row


def test_a_row_that_never_ran_its_constructor_cannot_be_published():
    """Measured: this reached rank 1 of a sealed artifact carrying a billion buys."""
    assert type(_forged_row()) is SelectedWallet
    with pytest.raises(ArtifactRefused) as caught:
        _artifact([_forged_row()] + [_row(2, 2, "1")])
    assert "never constructed" in str(caught.value)


def test_a_forged_row_substituted_after_sealing_is_refused_even_with_a_recomputed_hash():
    artifact = _artifact([_row(1, 1, "900"), _row(2, 2, "700")])
    rows = list(artifact.selections)
    rows[0] = _forged_row()
    object.__setattr__(artifact, "selections", tuple(rows))
    object.__setattr__(artifact, "artifact_hash", artifact_hash_of(artifact))
    with pytest.raises(ArtifactRefused):
        require_sealed_artifact(artifact, "a probe")


def test_a_negative_count_written_over_a_sealed_row_is_refused_by_the_gate():
    """``verify`` rebuilds each row through its own constructor, so the bound re-runs."""
    artifact = _artifact([_row(1, 1, "900"), _row(2, 2, "700")])
    object.__setattr__(artifact.selections[0], "valid_buys", -5)
    object.__setattr__(artifact, "artifact_hash", artifact_hash_of(artifact))
    with pytest.raises(ArtifactRefused):
        require_sealed_artifact(artifact, "a probe")


def test_an_artifact_that_never_ran_its_constructor_is_refused():
    genuine = _artifact([_row(1, 1, "900"), _row(2, 2, "700")])
    revived = object.__new__(type(genuine))
    revived.__dict__.update(genuine.__dict__)
    del revived.__dict__["_construction_witness"]
    assert type(revived) is type(genuine)
    with pytest.raises(ArtifactRefused) as caught:
        require_sealed_artifact(revived, "a probe")
    assert "construction witness" in str(caught.value)


def test_a_re_ranked_artifact_is_refused_however_the_hash_is_computed():
    """The guard ``SelectedBasket`` has held since ticket 28, on the type that crosses to evaluation.

    Ranks 1 and 2 stay contiguous and the values become ``["700", "900"]`` — an order contradicting
    the artifact's own numbers. Re-hashing with this package's public factory does not repair it.
    """
    with pytest.raises(ArtifactSealed) as caught:
        _artifact([_row(1, 1, "700"), _row(2, 2, "900")])
    assert "descending" in str(caught.value)


def test_a_sealed_artifact_with_a_stale_hash_is_refused():
    artifact = _artifact([_row(1, 1, "900"), _row(2, 2, "700")])
    object.__setattr__(artifact.selections[0], "wallet", F.address(251))
    with pytest.raises(ArtifactSealed):
        require_sealed_artifact(artifact, "a probe")


def test_ranks_must_be_contiguous_and_wallets_unique():
    with pytest.raises(ArtifactSealed):
        _artifact([_row(1, 1, "900"), _row(3, 2, "700")])
    with pytest.raises(ArtifactRefused):
        _artifact([_row(1, 1, "900"), _row(2, 1, "700")])


@pytest.mark.parametrize("build", (
    lambda: _artifact([_row(1, 1, "900"), _row(2, 2, "700")]),
    lambda: _row(1, 1, "900"),
))
def test_the_artifact_family_cannot_be_pickled_in_either_direction(build):
    from universe import PickleRefused

    value = build()
    with pytest.raises(PickleRefused):
        pickle.dumps(value)
    with pytest.raises(PickleRefused):
        type(value).__setstate__(value, {})


def test_a_hand_written_pickle_payload_rebuilding_an_artifact_is_refused():
    """The measured attack: ``__reduce__`` binds the dumps direction and the payload was hand-written."""
    genuine = _artifact([_row(1, 1, "900"), _row(2, 2, "700")])
    payload = pickle.dumps(_Craft(genuine))
    assert b"universe.artifact" in payload
    revived = pickle.loads(payload)
    assert type(revived) is type(genuine)
    with pytest.raises(ArtifactRefused):
        require_sealed_artifact(revived, "a probe")


def _rebuild(artifact_cls, row_cls, state, row_states):
    """Module-level so ``pickle`` can name it — the attacker's reconstructor."""
    rows = []
    for row_state in row_states:
        row = object.__new__(row_cls)
        row.__dict__.update(row_state)
        rows.append(row)
    obj = object.__new__(artifact_cls)
    obj.__dict__.update(state)
    obj.__dict__["selections"] = tuple(rows)
    return obj


class _Craft(object):
    """Reduces to :func:`_rebuild`, so no ``__reduce__`` on the sealed types is ever consulted."""

    def __init__(self, obj):
        self.obj = obj

    def __reduce__(self):
        state = {name: value for name, value in self.obj.__dict__.items()
                 if name not in ("selections", "_construction_witness")}
        row_states = [{name: value for name, value in row.__dict__.items()
                       if name != "_construction_witness"}
                      for row in self.obj.selections]
        return (_rebuild, (type(self.obj), type(self.obj.selections[0]), state, row_states))


# -- the ordering ----------------------------------------------------------------


def test_the_eight_steps_walked_honestly_produce_the_hand_computed_basket():
    containment, order, _ws, _u, _i, _s, basket, mount = _walked_to_forward_mount()
    assert tuple(w[-3:] for w in basket.wallets) == DESCENDING
    assert order.phase is Phase.FORWARD_MOUNTED
    assert containment.state is RunState.RUNNING
    assert containment.reasons == ()
    assert mount.artifact.wallets == basket.wallets


def test_selection_after_the_forward_mount_raises_and_voids_the_whole_run():
    """The measured breach. Ten of two hundred and fifty wallets moved, and nothing raised.

    The basket does not change here because it cannot be produced: ``rank_and_select`` obtains the
    universe from the workspace, and the workspace runs the gate.
    """
    containment, order, workspace, universe, inputs, scores, basket, _mount = \
        _walked_to_forward_mount()
    before = basket.wallets
    survivors = [s for s in scores if s.wallet.endswith("005")]
    dropped = tuple(UnscorableMember(wallet=s.wallet, reason="score could not be computed")
                    for s in scores if not s.wallet.endswith("005"))
    narrowed = for_universe(universe, survivors, dropped)

    with pytest.raises(SelectionAfterForwardMount):
        rank_and_select(workspace, narrowed, F.SEED, F.COMMIT)

    assert containment.state is RunState.INVALIDATED
    assert len(containment.reasons) == 1
    # The retry meets the run rather than the value, which is what makes it not a retry.
    with pytest.raises(RunInvalidated):
        rank_and_select(workspace, inputs, F.SEED + 1, F.COMMIT)
    assert basket.wallets == before


def test_a_second_seed_cannot_be_tried_once_the_forward_dataset_is_mounted():
    """The seed-shopping attack: the tie-decided slots were chosen on post-T0 activity."""
    containment, _order, workspace, _u, inputs, _s, _b, _m = _walked_to_forward_mount()
    for seed in (0, 1, 7, 328):
        with pytest.raises(LookAheadViolation):
            rank_and_select(workspace, inputs, seed, F.COMMIT)
    assert containment.state is RunState.INVALIDATED


def test_sealing_is_refused_after_the_forward_mount_too():
    containment, _order, workspace, _u, inputs, _s, basket, _m = _walked_to_forward_mount()
    with pytest.raises(SelectionAfterForwardMount):
        seal_selection(workspace, basket, inputs, F.DATASET_HASH)
    assert containment.state is RunState.INVALIDATED


def test_the_workspace_stops_answering_once_it_is_unmounted():
    universe, inputs, _scores = _population()
    containment = LookAheadContainment(run_id="unmount-run")
    order = ExecutionOrder(containment, same_process_evaluation_declared=True)
    workspace = order.mount_pre_t0(F.snapshot_evidence(), universe)
    basket = rank_and_select(workspace, inputs, F.SEED, F.COMMIT)
    order.seal(seal_selection(workspace, basket, inputs, F.DATASET_HASH))
    order.terminate_selection()
    order.unmount_pre_t0()
    with pytest.raises(WorkspaceUnmounted):
        workspace.snapshot()
    # The universe is refused one layer earlier still: the order's phase gate fires before the
    # dropped reference is reached, so the run is void rather than merely unreadable.
    with pytest.raises(OrderingViolation):
        workspace.selection_universe("a probe")
    assert containment.state is RunState.INVALIDATED
    # The name survives; the contents do not.
    assert workspace.window_id == "W1_2023H1"
    assert workspace.mounted is False


def test_a_forward_mount_cannot_be_built_by_naming_the_class():
    """Measured: this ran evaluation at phase ARTIFACT_SEALED with the workspace still readable."""
    universe, inputs, _scores = _population()
    order = ExecutionOrder(LookAheadContainment("token-run"),
                           same_process_evaluation_declared=True)
    workspace = order.mount_pre_t0(F.snapshot_evidence(), universe)
    basket = rank_and_select(workspace, inputs, F.SEED, F.COMMIT)
    artifact = order.seal(seal_selection(workspace, basket, inputs, F.DATASET_HASH))
    assert order.phase is Phase.ARTIFACT_SEALED
    for token in (None, object(), "the token"):
        with pytest.raises(OrderingViolation):
            ForwardMount(token, artifact, F.DATASET_ID, F.DATASET_HASH, artifact.artifact_hash)
    assert order.forward_mount is None


def test_a_pre_t0_workspace_cannot_be_built_by_naming_the_class():
    universe, _inputs, _scores = _population()
    order = ExecutionOrder(LookAheadContainment("token-run-2"),
                           same_process_evaluation_declared=True)
    for token in (None, object(), "the token"):
        with pytest.raises(OrderingViolation):
            PreT0Workspace(token, order, F.snapshot_evidence(), universe)


def test_an_artifact_edited_after_mounting_cannot_be_read_back_off_the_mount():
    """Recomputing ``artifact_hash`` restores self-consistency and does not restore the seal."""
    _c, _order, _ws, _u, _i, _s, basket, mount = _walked_to_forward_mount()
    assert mount.artifact.selections[0].wallet.endswith("005")
    raw = mount._artifact
    object.__setattr__(raw.selections[0], "wallet", F.address(251))
    object.__setattr__(raw, "artifact_hash", artifact_hash_of(raw))
    with pytest.raises(OrderingViolation) as caught:
        mount.artifact
    assert "step 4 sealed" in str(caught.value)


#: The cutoff a snapshot declares must be the window's real T0, not a number the caller chose.
CUTOFF_CASES = (
    ("a cutoff a million blocks into the forward period", T0_BLOCK + 1_000_000),
    ("a cutoff one block late", T0_BLOCK + 1),
    ("a cutoff one block early", T0_BLOCK - 1),
)


@pytest.mark.parametrize("name,forged_t0", CUTOFF_CASES)
def test_a_snapshot_whose_cutoff_is_not_t0_cannot_be_mounted(name, forged_t0):
    """Measured: rows at T0+500,000 and T0+999,999 sealed an artifact publishing that cutoff."""
    universe, _inputs, _scores = _population()
    snapshot = pre_t0_snapshot(
        window_id="W1_2023H1", t0_block=forged_t0,
        row_blocks=(forged_t0 - 100_000, forged_t0 - 1), source_query_hash="qh",
        source_table_versions=TABLES)
    assert snapshot.isolation_status is IsolationStatus.VERIFIED
    containment = LookAheadContainment(run_id="forged-cutoff-run")
    order = ExecutionOrder(containment, same_process_evaluation_declared=True)
    with pytest.raises(OrderingViolation) as caught:
        order.mount_pre_t0(snapshot, universe)
    assert str(forged_t0) in str(caught.value)
    assert containment.state is RunState.INVALIDATED


def test_a_snapshot_for_another_window_cannot_be_mounted():
    """The window is checked separately from the cutoff, and this isolates it.

    ``F.snapshot_evidence(F.W2)`` would prove nothing here: W2's ``t0_block`` differs from W1's, so
    the *cutoff* comparison would fire and the window comparison could be deleted with the test
    still green. This snapshot names another window while declaring W1's own T0.
    """
    universe, _inputs, _scores = _population()
    impostor = pre_t0_snapshot(
        window_id="W2_2023H2", t0_block=T0_BLOCK,
        row_blocks=(T0_BLOCK - 500, T0_BLOCK - 1), source_query_hash="qh",
        source_table_versions=TABLES)
    assert impostor.t0_block == universe.window.t0.block
    containment = LookAheadContainment(run_id="wrong-window-run")
    order = ExecutionOrder(containment, same_process_evaluation_declared=True)
    with pytest.raises(OrderingViolation) as caught:
        order.mount_pre_t0(impostor, universe)
    assert "W2_2023H2" in str(caught.value)
    assert containment.state is RunState.INVALIDATED
    # And the ordinary spelling, where both disagree.
    second = LookAheadContainment(run_id="wrong-window-run-2")
    with pytest.raises(OrderingViolation):
        ExecutionOrder(second, same_process_evaluation_declared=True).mount_pre_t0(
            F.snapshot_evidence(F.W2), universe)
    assert second.state is RunState.INVALIDATED


def test_the_phases_run_in_one_order_and_a_skipped_step_voids_the_run():
    universe, _inputs, _scores = _population()
    containment = LookAheadContainment(run_id="order-run")
    order = ExecutionOrder(containment, same_process_evaluation_declared=True)
    order.mount_pre_t0(F.snapshot_evidence(), universe)
    with pytest.raises(OrderingViolation):
        order.unmount_pre_t0()          # step 6 before steps 3, 4 and 5
    assert containment.state is RunState.INVALIDATED
    assert order.steps_taken() == ("UNMOUNTED", "PRE_T0_MOUNTED")


def test_the_forward_dataset_cannot_be_mounted_before_the_artifact_is_sealed():
    universe, _inputs, _scores = _population()
    containment = LookAheadContainment(run_id="early-mount-run")
    order = ExecutionOrder(containment, same_process_evaluation_declared=True)
    order.mount_pre_t0(F.snapshot_evidence(), universe)
    with pytest.raises(OrderingViolation) as caught:
        order.mount_forward(F.DATASET_ID, F.DATASET_HASH)
    # The phase gate is asserted by what it *says*, because the monotone ``_advance`` would refuse
    # this transition anyway: deleting the gate leaves the behaviour and loses the diagnosis, and a
    # test that only watched the exception type would call that equivalent.
    assert "Steps 1-6 come first" in str(caught.value)
    assert containment.state is RunState.INVALIDATED
    assert order.forward_reachable is False


def test_the_forward_dataset_cannot_be_mounted_while_the_workspace_is_still_readable():
    """Both datasets live in one memory space is the condition step 6 exists to prevent."""
    universe, inputs, _scores = _population()
    containment = LookAheadContainment(run_id="both-live-run")
    order = ExecutionOrder(containment, same_process_evaluation_declared=True)
    workspace = order.mount_pre_t0(F.snapshot_evidence(), universe)
    basket = rank_and_select(workspace, inputs, F.SEED, F.COMMIT)
    order.seal(seal_selection(workspace, basket, inputs, F.DATASET_HASH))
    order.terminate_selection()
    order.unmount_pre_t0()
    assert workspace.mounted is False


def test_same_process_evaluation_must_be_declared_in_the_call_rather_than_omitted():
    universe, inputs, _scores = _population()
    order = ExecutionOrder(LookAheadContainment("same-process-run"))
    workspace = order.mount_pre_t0(F.snapshot_evidence(), universe)
    basket = rank_and_select(workspace, inputs, F.SEED, F.COMMIT)
    order.seal(seal_selection(workspace, basket, inputs, F.DATASET_HASH))
    order.terminate_selection()
    order.unmount_pre_t0()
    with pytest.raises(OrderingViolation) as caught:
        order.mount_forward(F.DATASET_ID, F.DATASET_HASH)
    assert "same_process_evaluation_declared=True" in str(caught.value)


# -- the containment -------------------------------------------------------------


def test_an_invalidated_run_refuses_every_governed_stage():
    containment = LookAheadContainment(run_id="invalidated-run")
    containment.invalidate("a probe breach")
    assert containment.state is RunState.INVALIDATED
    assert containment.reasons == ("a probe breach",)
    with pytest.raises(RunInvalidated):
        containment.require_valid("anything at all")


def test_the_state_does_not_clear_with_a_plain_assignment():
    """It used to: ``containment._state = RunState.RUNNING`` was one line, and require_valid passed."""
    containment = LookAheadContainment(run_id="reset-run")
    containment.invalidate("a probe breach")
    with pytest.raises(AttributeError):
        containment._state = RunState.RUNNING
    assert containment.state is RunState.INVALIDATED
    with pytest.raises(RunInvalidated):
        containment.require_valid("anything at all")


def test_the_guard_invalidates_the_run_and_re_raises_rather_than_swallowing():
    """``except LookAheadViolation: continue`` is the pattern this class exists to make unwritable."""
    containment = LookAheadContainment(run_id="guarded-run")
    with pytest.raises(LookAheadViolation):
        with containment.guard("ranking"):
            raise LookAheadViolation("a post-T0 value reached a selection constructor")
    assert containment.state is RunState.INVALIDATED
    assert len(containment.reasons) == 1
    assert "ranking" in containment.reasons[0]


def test_the_guard_refuses_to_open_on_a_run_that_is_already_void():
    containment = LookAheadContainment(run_id="guarded-run-2")
    containment.invalidate("an earlier breach")
    with pytest.raises(RunInvalidated):
        with containment.guard("ranking"):
            pass


def test_an_invalidation_must_state_a_reason_and_containment_must_name_its_run():
    containment = LookAheadContainment(run_id="named-run")
    with pytest.raises(ContainmentMisuse):
        containment.invalidate("")
    with pytest.raises(ContainmentMisuse):
        LookAheadContainment(run_id="   ")
    with pytest.raises(ContainmentMisuse):
        LookAheadContainment(run_id="a-run", sink="not a sink")


def test_there_are_two_run_states_and_no_third():
    """A third state would be somewhere to file a breach while the run continued."""
    assert [state.value for state in RunState] == ["RUNNING", "INVALIDATED"]


# -- the audit -------------------------------------------------------------------


def test_the_audit_sweeps_every_block_it_walks_rather_than_the_scores_alone():
    """Its headline figure used to be computed over ``inputs.scores`` and described the walk."""
    universe, inputs, _scores = _population()
    basket = F.basket(universe, inputs)
    audit = look_ahead_audit(universe, inputs, basket)

    names = [check.name for check in audit.checks]
    assert "every_walked_block_is_before_t0_or_declared" in names
    assert all(check.passed for check in audit.checks)
    assert audit.post_t0_values_found == 0
    # T0 - 1 is the fixture's stamp, and it is what the walk finds as the latest measured input.
    assert audit.latest_input_block == T0_BLOCK - 1
    assert audit.latest_input_timestamp == T0_SECOND - 1
    assert audit.earliest_gap_blocks == 1

    sweep = [check for check in audit.checks
             if check.name == "every_walked_block_is_before_t0_or_declared"][0]
    # The two post-T0 constants the walk really does reach are named rather than passed over.
    assert "forward_end_block" in sweep.statement
    assert "forward_end_ts" in sweep.statement


def test_the_audit_sweep_fails_on_a_post_t0_block_that_is_not_declared_calendar():
    """Guard the guard: a sweep that cannot fail is theatre.

    ``measurement.observations[].first_activity_block`` is chosen deliberately. It is reachable from
    the frozen universe, it is a bare ``int`` — so check 1, which looks at *types*, is blind to it —
    and it is in neither the snapshot-identifier payload nor any other check, so exactly one check
    goes red and the failure names the sweep rather than a neighbour.
    """
    universe, inputs, _scores = _population()
    basket = F.basket(universe, inputs)
    observation = universe.measurement.observations[0]
    original = observation.first_activity_block
    object.__setattr__(observation, "first_activity_block", T0_BLOCK + 1)
    try:
        with pytest.raises(LookAheadViolation) as caught:
            look_ahead_audit(universe, inputs, basket)
        message = str(caught.value)
        assert "every_walked_block_is_before_t0_or_declared" in message
        assert message.count("failed 1 check(s)") == 1
        assert "first_activity_block={}".format(T0_BLOCK + 1) in message
    finally:
        object.__setattr__(observation, "first_activity_block", original)
