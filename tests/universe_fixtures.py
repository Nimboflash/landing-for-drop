"""Shared fixture builders for the ``universe`` tests.

Not a test module — nothing here asserts anything, and nothing here computes an expected value.
Every function is a *constructor* with legible defaults, so that a test which cares about one field
can set that field and leave the rest alone.

The calendars are §6.3's, written as absolute literals. A fixture that derived T0 from a constant
somewhere in ``src`` would move with it and pin nothing.

Where the provenance stamp goes, and why it goes there
------------------------------------------------------

Every ratio and every score below is built with :func:`pre_t0`, which is
:meth:`universe.provenance.PreT0Decimal.measured_before_t0` under a shorter name. The selection
types refuse a bare ``Decimal`` on purpose — a laundered value *is* a bare ``Decimal`` by the time
it reaches them — so the stamp has to be applied somewhere, and the only honest somewhere is the
boundary where a human can still say what the number measures. In a real run that boundary is the
warehouse read. In this suite it is here.

That makes these fixtures the *only* place in the tests that asserts pre-T0 origin, which is
deliberate: a test that could stamp a value inline, anywhere it liked, would be a test that proves
the barrier can be walked around.
"""

from decimal import Decimal

from contracts import AccountType

from universe import (
    AccountEvidence,
    AccountWindowObservation,
    BaseRateComparison,
    DataCostReport,
    DEFAULT_POLICY,
    DesignRevision,
    ExecutionOrder,
    HEURISTIC_MODIFICATIONS,
    LookAheadContainment,
    PreT0Decimal,
    PreT0Score,
    T0Instant,
    TableVersion,
    TrainingWindow,
    WindowDesign,
    WindowKey,
    boundary_movement,
    build_census,
    classify_account,
    freeze_universe,
    measure_window,
    pre_t0_snapshot,
    rank_and_select,
    screen_warehouse,
    seal_selection,
    WarehouseRow,
)


def pre_t0(value, source="the fixture warehouse read, taken strictly before T0"):
    """Stamp a fixture number as measured before ``T0``.

    ``None`` passes through, because ``None`` is UNMEASURED and the evidence types distinguish that
    from zero. A value that is already a :class:`~universe.provenance.PreT0Decimal` passes through
    too, so a test may pass one it built itself with a more specific source.
    """
    if value is None or isinstance(value, PreT0Decimal):
        return value
    return PreT0Decimal.measured_before_t0(value, source)

SNAPSHOT = "dune-2026-07-31"
COMMIT = "abc1234"
SEED = 42

#: §6.3 window 1: train Jan-Jun 2023, test Jul-Dec 2023. UTC seconds are the calendar's, written
#: out; the block numbers are plausible mainnet heights for those instants.
W1 = TrainingWindow(
    key=WindowKey.W1_2023H1,
    t0=T0Instant(block=17_600_000, timestamp=1_688_169_600),   # 2023-07-01T00:00:00Z
    baseline_start_block=16_308_190,
    baseline_start_ts=1_672_531_200,                            # 2023-01-01T00:00:00Z
    forward_end_block=18_900_000,
    forward_end_ts=1_703_980_800,                               # 2023-12-31T00:00:00Z
)

W2 = TrainingWindow(
    key=WindowKey.W2_2023H2,
    t0=T0Instant(block=18_908_895, timestamp=1_704_067_200),    # 2024-01-01T00:00:00Z
    baseline_start_block=17_600_000,
    baseline_start_ts=1_688_169_600,
    forward_end_block=20_200_000,
    forward_end_ts=1_719_792_000,
)

W3 = TrainingWindow(
    key=WindowKey.W3_2024H1,
    t0=T0Instant(block=20_200_000, timestamp=1_719_792_000),    # 2024-07-01T00:00:00Z
    baseline_start_block=18_908_895,
    baseline_start_ts=1_704_067_200,
    forward_end_block=21_500_000,
    forward_end_ts=1_735_603_200,
)

W4 = TrainingWindow(
    key=WindowKey.W4_2024H2,
    t0=T0Instant(block=21_525_890, timestamp=1_735_689_600),    # 2025-01-01T00:00:00Z
    baseline_start_block=20_200_000,
    baseline_start_ts=1_719_792_000,
    forward_end_block=22_800_000,
    forward_end_ts=1_751_328_000,
)

DESIGN = WindowDesign(windows=(W1, W2, W3, W4))


def address(index):
    """A deterministic 20-byte address from a small integer."""
    return "0x{:040x}".format(index)


def human_evidence(**overrides):
    """Evidence for an ordinary retail trader: no rule fires."""
    values = dict(
        distinct_funding_sources=1,
        distinct_beneficiaries=1,
        settles_for_other_principals=False,
        share_token_holders=None,
        deployed_tokens_traded=0,
        two_sided_quote_share=None,
        failed_tx_share=Decimal("0.01"),
        max_tx_per_hour=3,
        total_tx=200,
        distinct_senders=1,
        day_of_week_skewness=Decimal("0.4"),
        mean_inter_trade_gap_seconds=1800,
        controller_identified=True,
        netting_complete=True,
        labels=(),
    )
    values.update(overrides)
    for ratio in ("two_sided_quote_share", "failed_tx_share", "day_of_week_skewness"):
        values[ratio] = pre_t0(
            values[ratio], "the fixture's §6.2 evidence read for {}".format(ratio))
    return AccountEvidence(**values)


def observation(account, potential_buys=120, valid_buys=100, window=W1, account_type=None,
                evidence=None, buy_volume_usd=None, active_days=40, wallet_age_days=400,
                as_of_block=None, as_of_timestamp=None, **kwargs):
    """One pre-T0 observation, stamped a day before ``T0`` unless a test says otherwise."""
    return AccountWindowObservation(
        account=account,
        window_key=window.key,
        account_type=account_type or AccountType.EOA,
        potential_buys=potential_buys,
        valid_buys=valid_buys,
        buy_volume_usd=pre_t0(
            Decimal("50000") if buy_volume_usd is None else buy_volume_usd,
            "the fixture's pre-T0 buy volume read",
        ),
        active_days=active_days,
        first_activity_block=window.baseline_start_block + 10,
        first_activity_ts=window.baseline_start_ts + 120,
        wallet_age_days=wallet_age_days,
        as_of_block=(window.t0.block - 1 if as_of_block is None else as_of_block),
        as_of_timestamp=(window.t0.timestamp - 1 if as_of_timestamp is None
                         else as_of_timestamp),
        t0=window.t0,
        evidence=evidence if evidence is not None else human_evidence(),
        **kwargs
    )


def score(wallet, value, n_buys, window=W1, **kwargs):
    """One pre-T0 ``buy_quality_30d``, stamped a day before ``T0``."""
    values = dict(
        wallet=wallet,
        metric="buy_quality_30d",
        value=pre_t0(value, "scoring.buy_quality_detail, computed strictly before T0"),
        n_buys=n_buys,
        as_of_block=window.t0.block - 1,
        as_of_timestamp=window.t0.timestamp - 1,
        t0=window.t0,
        baseline_start_block=window.baseline_start_block,
        baseline_start_ts=window.baseline_start_ts,
        source="scoring.buy_quality_detail",
    )
    values.update(kwargs)
    return PreT0Score(**values)


def screened(observations, window=W1, extra_rows=()):
    """Run stage one over the accounts these observations describe, plus any extra rows."""
    rows = [WarehouseRow(address=o.account, potential_buys=o.potential_buys)
            for o in observations]
    rows.extend(extra_rows)
    return screen_warehouse(window.key, rows)


def classified(observations, screen, policy=DEFAULT_POLICY):
    """Stage two over the admitted observations, plus stage one's own exclusions as verdicts."""
    from universe import EligibilityVerdict

    verdicts = [classify_account(o, policy, screen) for o in observations
                if o.account in screen.admitted_addresses]
    verdicts.extend(
        EligibilityVerdict(account=exclusion.account, exclusion=exclusion)
        for exclusion in screen.exclusions
    )
    return tuple(verdicts)


def step0_inputs(observations, window=W1, policy=DEFAULT_POLICY, extra_rows=(),
                 total_active_accounts=None, accounts_with_at_least_one_valid_buy=None,
                 assumed_size=None):
    """Everything :func:`universe.step0.measure_window` needs for one window, **minus the snapshot**.

    Returned as a mapping of its own keyword arguments, so that a caller who wants the measurement
    calls :func:`measured` and a caller who wants to hand the same inputs to something else — the
    ``step0.universe`` stage runner, say — gets exactly the values ``measured`` would have used
    rather than a second construction of them that could drift from it.

    ``dataset_snapshot`` is left out on purpose: it belongs to whoever assembles the report, and
    ``universe.step0.Step0Report`` refuses a report whose windows carry two different ones.
    """
    screen = screened(observations, window, extra_rows)
    admitted_observations = tuple(o for o in observations
                                  if o.account in screen.admitted_addresses)
    verdicts = classified(observations, screen, policy)
    movement = boundary_movement(admitted_observations, verdicts)
    census = build_census(verdicts, screen.rows_screened, movement, window.key)
    eligible = census.admitted_count
    return {
        "window": window,
        "observations": admitted_observations,
        "verdicts": verdicts,
        "census": census,
        "data_cost": DataCostReport(
            accounts_screened=screen.rows_screened,
            accounts_enriched=len(screen.admitted),
            transactions_enriched=sum(o.potential_buys for o in admitted_observations),
        ),
        "policy": policy,
        "total_active_accounts": (total_active_accounts if total_active_accounts is not None
                                  else screen.rows_screened * 10),
        "accounts_with_at_least_one_valid_buy": (
            accounts_with_at_least_one_valid_buy
            if accounts_with_at_least_one_valid_buy is not None
            else max(screen.rows_screened, len(admitted_observations))
        ),
        "base_rate": BaseRateComparison(
            window_key=window.key,
            assumed_size=assumed_size if assumed_size is not None else max(eligible, 1),
            source="§13.7 design assumption, pre-registered",
            measured_size=eligible,
            statement=(
                "§13.7 records that the target population may simply not exist at the size "
                "assumed; this window's measured eligible universe is compared against it."
            ),
        ),
        "heuristic_modifications": HEURISTIC_MODIFICATIONS,
    }


def measured(observations, window=W1, policy=DEFAULT_POLICY, extra_rows=(),
             total_active_accounts=None, accounts_with_at_least_one_valid_buy=None,
             assumed_size=None, snapshot=SNAPSHOT):
    """The whole of Step 0 for one window, from a list of observations."""
    inputs = step0_inputs(
        observations, window, policy, extra_rows, total_active_accounts,
        accounts_with_at_least_one_valid_buy, assumed_size,
    )
    return (
        measure_window(dataset_snapshot=snapshot, **inputs),
        inputs["verdicts"],
        inputs["census"],
        screened(observations, window, extra_rows),
    )


#: Every fixture universe here is a handful of accounts, which is below §6.1's floor of 10,000 —
#: so :class:`universe.FrozenUniverse` refuses to freeze one without an explicit revision. That
#: refusal is the point of the type and it is not being worked around: it is exercised directly by
#: ``test_a_small_universe_cannot_be_frozen_without_an_explicit_revision`` in the properties file,
#: and every other test passes this so that the fixture can be a size a reviewer can count by hand.
REVISION = DesignRevision(
    rule_id="fixture-only",
    revised_by="the test suite",
    reason=(
        "a fixture universe is deliberately small enough to be hand-checked; the §6.1 floor is "
        "exercised on its own rather than by making every fixture 10,000 accounts long"
    ),
    recorded_at_commit=COMMIT,
)


def frozen(observations, window=W1, revision=REVISION, **kwargs):
    """A frozen universe for one window, from a list of observations.

    ``revision`` defaults to :data:`REVISION` — see its comment. Pass ``revision=None`` to see the
    refusal a real run would meet.
    """
    measurement, verdicts, _census, _screen = measured(observations, window, **kwargs)
    return freeze_universe(measurement, verdicts, kwargs.get("snapshot", SNAPSHOT),
                           revision=revision)


#: The dataset the fixture snapshots claim to be taken from. A pair of names rather than one, so a
#: test can tell "the mount opened the wrong dataset" from "the artifact names the wrong snapshot".
DATASET_ID = "fixture-forward-dataset"
DATASET_HASH = "fixture-dataset-hash"


def snapshot_evidence(window=W1, row_blocks=None):
    """A verified :class:`~universe.snapshot.PreT0Snapshot` for one window.

    The row census is two blocks strictly inside the baseline, so ``max_block <= t0_block`` holds by
    construction rather than by assertion. A test that wants to see
    :class:`~universe.snapshot.SelectionExecutionBlocked` passes ``row_blocks`` containing one at or
    after T0 and gets the refusal a contaminated warehouse read would produce.
    """
    blocks = row_blocks if row_blocks is not None else (
        window.baseline_start_block, window.t0.block - 1)
    return pre_t0_snapshot(
        window_id=window.key.value,
        t0_block=window.t0.block,
        row_blocks=tuple(blocks),
        source_query_hash="the fixture's pre-T0 warehouse query, hashed",
        source_table_versions=(TableVersion(table="fixture.trades", version="v1"),),
    )


def mount_workspace(universe, window=None, run_id="fixture-run", row_blocks=None):
    """Steps 1 and 2's precondition: an order at ``PRE_T0_MOUNTED``, and the workspace it produced.

    Returns ``(order, workspace)``. Every test that ranks goes through here, because
    :func:`universe.select.rank_and_select` takes the workspace rather than the universe — that is
    the ordering barrier, and a fixture that could hand it a bare
    :class:`~universe.freeze.FrozenUniverse` would be a fixture proving the barrier can be walked
    around.

    ``window`` defaults to the universe's own, because
    :meth:`universe.ordering.ExecutionOrder.mount_pre_t0` refuses a snapshot whose window or whose
    ``t0_block`` disagrees with the universe's. A test that wants to see that refusal passes the
    other window explicitly.
    """
    containment = LookAheadContainment(run_id=run_id)
    order = ExecutionOrder(containment, same_process_evaluation_declared=True)
    evidence = snapshot_evidence(universe.window if window is None else window, row_blocks)
    workspace = order.mount_pre_t0(evidence, universe)
    return order, workspace


def basket(universe, inputs, seed=SEED, commit=COMMIT, window=None):
    """Rank one window through a freshly mounted workspace. The common case, in one line."""
    _order, workspace = mount_workspace(universe, window)
    return rank_and_select(workspace, inputs, seed, commit)


def mounted(universe, basket, inputs, window=None, dataset_id=DATASET_ID,
            dataset_hash=DATASET_HASH):
    """Walk the eight steps to the one moment forward data may be opened, and return the mount.

    This exists so that a post-T0 test cannot cheat by hand-building the thing that proves selection
    already finished. Every step is taken in order — mount the pre-T0 snapshot and the universe,
    seal the artifact, terminate selection, unmount the workspace, mount the forward dataset — and
    :class:`~universe.ordering.ExecutionOrder` refuses any of them taken early. Since ticket 27's
    repair, :class:`~universe.ordering.ForwardMount` refuses construction without the order's
    private token too, so there is no shorter route left to write.

    ``same_process_evaluation_declared=True`` is passed because a pytest run is one process. It is a
    constructor argument rather than a default precisely so that this line, and not an omission, is
    where a reader sees that step 8's process boundary is not being enforced here.
    """
    containment = LookAheadContainment(run_id="fixture-run")
    order = ExecutionOrder(containment, same_process_evaluation_declared=True)
    evidence = snapshot_evidence(universe.window if window is None else window)
    workspace = order.mount_pre_t0(evidence, universe)
    order.seal(seal_selection(workspace, basket, inputs, dataset_hash))
    order.terminate_selection()
    order.unmount_pre_t0()
    return order.mount_forward(dataset_id, dataset_hash)
