"""The thirteen Phase 0 stages, driven in order on the synthetic source, and where the run stops.

What this module is
-------------------

:mod:`tools.mockchain.report` runs *one* stage's worth of work — ``pipeline.buy_quality`` — and
publishes a §10 report from it. This module drives the **whole register**: every key of
``phase0.runs.STAGES``, in order, through ``phase0.execution.execute_stage``, behind the start gate,
with the run record written first, under
:func:`tools.mockchain.governance.execute_synthetic_stage` so that nothing generated can advance
the machine.

It is a *driver*, not a measurement. Everything it records is a fact about the wiring: which stages
can be reached on generated input, which refuse, what each refusal names, and how far the chain gets
before it stops. No number produced here is evidence about the hypothesis, and
:func:`published` deliberately renders every stage value as a short line rather than as an artifact,
so that nothing on this path can be mistaken for the §10 report — which has exactly one publication
route, :func:`tools.mockchain.provenance.publish_synthetic_artifact`, and it is not here.

The three fictions a synthetic run has to tell, and where they are recorded
---------------------------------------------------------------------------

A synthetic run cannot reach a single stage without asserting things that are not true. They are
not hidden inside this module; they are :data:`FICTIONS`, they are carried on
:class:`SyntheticDrive`, and every one of them is written into the hash-chained audit log with the
synthetic snapshot as its attribution, so a reader of the log alone sees them:

1. **The §15.4 start gate.** ``execute_stage`` calls ``preconditions.require_ready()`` first, and
   all four preconditions are unmet in this tree — ticket 03 (an authenticated archival node) most
   of all. To reach any runner at all, this driver records all four as satisfied, attributing each
   to the synthetic snapshot rather than to a person. **Recording a precondition is not the same
   act as meeting it**, and this one is false: there is no data budget, no vendor access and no
   validator. It is written down as ``SYNTHETIC-…-NOT-A-MEASUREMENT`` so that the register and the
   audit log both say who claimed it.
2. **PARAMETERS_FROZEN.** Every build-lane stage requires it, it is a
   :data:`phase0.execution.MANUAL_TRANSITIONS` human act, and it is in
   :data:`tools.mockchain.governance.SYNTHETIC_MAY_NOT_ADVANCE`. No stage advances it, so
   :func:`tools.mockchain.governance.refuse_if_synthetic_would_advance` never sees it — and
   ``phase0.governance.GovernanceMachine.transition`` **would** refuse it, since it now raises on a
   snapshot that declares itself not a measurement. This driver reaches it by calling ``transition``
   without passing the snapshot it is holding, which is the last thing ``phase0`` cannot check and
   the residue :data:`tools.mockchain.governance.GOVERNANCE_GAP` names. It performs it explicitly,
   loudly, and only because ``freeze_parameters`` says so; pass ``freeze_parameters=False`` to see
   what the machine does to a synthetic run that does not tell this lie (every stage ``REFUSED``,
   no run record anywhere).
3. **Drawn inputs where the generator measures nothing.** ``step0.universe`` and
   ``benchmark.match`` consume populations the synthetic chain does not generate — a §6.1 eligible
   universe in four §6.3 windows, and a §6.6 control universe. Those inputs are **drawn from the
   seed**, not measured, and they are listed in :data:`DRAWN_NOT_MEASURED`. Every wallet in them is
   minted by :mod:`tools.mockchain.provenance`, so they are marked; being marked does not make them
   measured. No §7.1 column is computed from the matched sets this driver produces, and
   :mod:`tools.mockchain.report` still refuses to compute one — see ``report.NO_BENCHMARK``.

Where the chain stops, and why the driver does not lift the gate
-----------------------------------------------------------------

``validation.independent`` is the only stage that advances ``VALIDATION_PASSED``, which gates
``CODE_AND_DATA_FROZEN``, which gates all five execution-lane stages. Its runner refuses
unconditionally: ``src/groundtruth/`` does not exist (tickets 02, 36).
``tests/integration/test_stage_runners.py`` reaches the five stages behind that gate by calling
``governance.transition(VALIDATION_PASSED, …)`` by hand and says so. **This driver does not**, and
the reason is not politeness: ``VALIDATION_PASSED`` is one of the four states in
:data:`tools.mockchain.governance.HUMAN_ACT_STATES`, and lifting it on a synthetic snapshot is the
exact claim — *a validation gate passed against real data* — that this whole package exists to make
impossible. So the synthetic run stops where a real run stops, and the five stages behind the gate
are attempted and refused rather than skipped.

They are attempted with a **tripwire** runner (:func:`tripwire_runner`) rather than with assembled
inputs, and that is a claim about the ordering rather than a shortcut: ``execute_stage`` checks
governance at steps 1-2 and calls the runner at step 4, so a refusal that is real never reaches the
runner. If any of the five ever does, the tripwire raises and the stage is recorded ``CRASHED``
with a message naming what went wrong — a synthetic run that reached the execution lane. A runner
that returned a plausible value there would be the worst outcome available.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Optional, Tuple  # noqa: F401  (3.9-compatible annotations)

from contracts import AccountType
from matching_null import NUMERIC_DIMENSIONS, WalletFeatures
from phase0 import governance as gov
from phase0.execution import (
    COMPLETED,
    CRASHED,
    HELD,
    REFUSED,
    STAGE_AUTHORITY,
    wire,
)
from phase0.preconditions import PRECONDITIONS
from phase0.runs import STAGES
from phase0.seeds import new_master_seed
from pipeline.stages import BLOCKED_STAGES, LIVE_STAGES, runner_for
from reporting import CAPITAL_LEVELS
from universe import (
    AccountEvidence,
    AccountWindowObservation,
    BaseRateComparison,
    DataCostReport,
    DEFAULT_POLICY,
    EligibilityVerdict,
    HEURISTIC_MODIFICATIONS,
    PreT0Decimal,
    T0Instant,
    TrainingWindow,
    WarehouseRow,
    WindowDesign,
    WindowKey,
    boundary_movement,
    build_census,
    classify_account,
    screen_warehouse,
)

from pipeline.stages.benchmark import LeaderBuy
from pipeline.stages.step0 import Step0WindowInputs

from .chain import SELECTED_WALLETS, generate_chain
from .governance import SyntheticRunRefused, execute_synthetic_stage
from .provenance import is_synthetic_snapshot, synthetic_address
from .report import (
    SYNTHETIC_COMMIT,
    _basket_basis,
    _quote_assets,
    _scored,
    leader_buys,
    synthetic_report,
)
from .seeds import draw_between

__all__ = [
    "DRAWN_NOT_MEASURED",
    "FICTIONS",
    "REFUSED_BY_HARNESS",
    "SYNTHETIC_COMMIT",
    "SYNTHETIC_REQUESTER",
    "StageOutcome",
    "SyntheticDrive",
    "benchmark_match_inputs",
    "drive_synthetic_phase0",
    "follower_adjust_inputs",
    "published",
    "step0_universe_inputs",
    "synthetic_wiring",
    "tripwire_runner",
]


#: Who the audit log records as having asked. A person's name here would be the same fiction the
#: precondition register carries, one layer down.
SYNTHETIC_REQUESTER = "tools.mockchain synthetic driver (NOT A MEASUREMENT)"

#: What the audit log records as the time. Deterministic by house rule — "no clock" — and shaped so
#: that it cannot be misread as one: a plausible ISO timestamp on a synthetic run would be a
#: fabricated fact about when something happened.
SYNTHETIC_TIMESTAMP = "SYNTHETIC-NOT-A-TIME"

#: A stage the harness refused before ``execute_stage`` was called at all. Not one of
#: :data:`phase0.execution.STAGE_STATUSES`, because it is not an outcome of a governed run — it is
#: a refusal that happened instead of one. Named separately so a reader of the table can tell "the
#: machine refused this" from "the harness never let the machine see it".
REFUSED_BY_HARNESS = "REFUSED_BY_HARNESS"

#: Claims a synthetic run must make before the machine will move at all. Carried, not hidden.
FICTIONS = (
    "the four §15.4 preconditions are recorded as satisfied and none of them is: ticket 01 has no "
    "Primary Builder, ticket 02 no Independent Validator, ticket 03 no data budget or vendor "
    "access, ticket 04 no reserved capacity. execute_stage calls preconditions.require_ready() "
    "before anything else, so a synthetic run reaches no runner without recording all four. Each "
    "is attributed to the synthetic snapshot rather than to a person.",
    "PARAMETERS_FROZEN is entered by hand. It is a human act (ticket 11), it is in "
    "SYNTHETIC_MAY_NOT_ADVANCE, and no stage advances it — so tools.mockchain.governance never "
    "sees it. src/phase0/ would refuse it: GovernanceMachine.transition raises "
    "NotAMeasurementError on a snapshot that declares itself not a measurement. This driver "
    "reaches it only by calling transition WITHOUT passing the snapshot it is holding, which is "
    "the one thing phase0 cannot check. That is the residue named in "
    "tools.mockchain.governance.GOVERNANCE_GAP, demonstrated rather than argued.",
    "step0.universe's four §6.3 windows and benchmark.match's control universe are drawn from the "
    "seed, not generated by the chain. See DRAWN_NOT_MEASURED.",
)

#: Exactly which stage inputs are drawn rather than produced by :mod:`tools.mockchain.chain`, and
#: what a reader must therefore not conclude from the stage's value.
DRAWN_NOT_MEASURED = {
    "step0.universe": (
        "the ten synthetic wallets are placed in all four §6.3 windows and their §6.1 funnel "
        "counts are drawn from the seed. The chain generates one 90-day window and no baseline "
        "period, so there is nothing to measure a §6.1 eligible universe from. Every window "
        "therefore holds ten accounts against §6.1's floor of 10,000 and comes back "
        "INSUFFICIENT CANDIDATE UNIVERSE, which is the status the stage has to carry rather than "
        "crash on. Nothing about the size of a real eligible universe follows from it."
    ),
    "benchmark.match": (
        "the control universe and every wallet's ten §6.6 covariates are drawn from the seed. The "
        "chain generates ten selected wallets and no control universe at all. The matched sets "
        "this stage returns are evidence that §6.6's matching runs under governance and about "
        "nothing else — no per-wallet advantage, no §7.1 column and no benchmark is computed from "
        "them here, and tools.mockchain.report still refuses to compute one (report.NO_BENCHMARK)."
    ),
}

#: How many drawn controls the §6.6 matching is given. §6.6 takes five primary and five robustness
#: controls per selected wallet, so a universe of forty is comfortably more than the nine selected
#: wallets need without making the drive slow.
N_CONTROLS = 40

#: §6.3's four training windows, written out as literals.
#:
#: The calendars are the pre-registered ones and the only other copy in this tree is
#: ``tests/universe_fixtures``, which ``tools/`` may not import. Duplicated rather than derived
#: because nothing in ``src/`` publishes them: ``universe.WindowKey`` closes the *set* of windows
#: and leaves the calendar to whoever registers the design.
WINDOWS = (
    TrainingWindow(
        key=WindowKey.W1_2023H1,
        t0=T0Instant(block=17_600_000, timestamp=1_688_169_600),
        baseline_start_block=16_308_190, baseline_start_ts=1_672_531_200,
        forward_end_block=18_900_000, forward_end_ts=1_703_980_800,
    ),
    TrainingWindow(
        key=WindowKey.W2_2023H2,
        t0=T0Instant(block=18_908_895, timestamp=1_704_067_200),
        baseline_start_block=17_600_000, baseline_start_ts=1_688_169_600,
        forward_end_block=20_200_000, forward_end_ts=1_719_792_000,
    ),
    TrainingWindow(
        key=WindowKey.W3_2024H1,
        t0=T0Instant(block=20_200_000, timestamp=1_719_792_000),
        baseline_start_block=18_908_895, baseline_start_ts=1_704_067_200,
        forward_end_block=21_500_000, forward_end_ts=1_735_603_200,
    ),
    TrainingWindow(
        key=WindowKey.W4_2024H2,
        t0=T0Instant(block=21_525_890, timestamp=1_735_689_600),
        baseline_start_block=20_200_000, baseline_start_ts=1_719_792_000,
        forward_end_block=22_800_000, forward_end_ts=1_751_328_000,
    ),
)

DESIGN = WindowDesign(windows=WINDOWS)

#: The parameter freeze the drawn design claims to have been registered under. Marked, because it
#: travels into the ``Step0Report`` and a bare hex string there would read like a real freeze.
PARAMETER_FREEZE_HASH = "SYNTHETIC-mockchain-v1-parameter-freeze-NOT-A-MEASUREMENT"


# -- the wiring -----------------------------------------------------------------


def _clock():
    return SYNTHETIC_TIMESTAMP


class _RunIds(object):
    """Deterministic, readable, marked run identifiers.

    ``phase0.runs.RunStore`` mints ``uuid4().hex[:12]`` by default, which is unseeded randomness and
    would make two runs of one seed differ in every run record and every audit entry. The id is
    also the run-record filename, so it stays short and filesystem-safe.
    """

    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return "synthetic-{:02d}".format(self.n)


def synthetic_wiring(root, record_preconditions=True):
    """A :class:`phase0.execution.Wiring` under a deterministic clock and run-id factory.

    :param root: the state directory. Everything — audit log, preconditions, governance state, run
        records — is written under it.
    :param record_preconditions: record the four §15.4 preconditions as satisfied, attributed to
        the synthetic snapshot. **This is fiction number one**; see :data:`FICTIONS`. ``False``
        leaves the start gate closed, which is what a synthetic run meets if it tells no lies.

    Returns the wiring. It does not touch the governance state; that is
    :func:`drive_synthetic_phase0`'s second fiction and is performed there, where it is visible.
    """
    wiring = wire(str(root), clock=_clock, id_factory=_RunIds())
    if record_preconditions:
        for key, ticket, description in PRECONDITIONS:
            wiring.preconditions.record(
                key,
                "RECORDED BY A SYNTHETIC RUN, NOT SATISFIED — ticket {} ({}) is unmet in this "
                "tree".format(ticket, description),
                SYNTHETIC_REQUESTER,
            )
    return wiring


# -- inputs the chain can supply ------------------------------------------------


def buy_quality_inputs(chain):
    """``pipeline.buy_quality``'s five inputs — the generated chain, unaltered.

    The only stage in the register whose inputs this fixture *measures* rather than draws: they are
    the same five values :func:`tools.mockchain.report.run_synthetic_window` hands to
    ``pipeline.run_wallet_window``, so the stage computes the run the §10 report is built from.
    """
    return {
        "transactions": chain.transactions,
        "pools": chain.pools,
        "prices": chain.prices,
        "window": chain.window,
        "config": chain.config,
    }


def follower_adjust_inputs(run):
    """``follower.adjust``'s two inputs, both from the run that already happened.

    Every :class:`pipeline.stages.benchmark.LeaderBuy` pairs one scored §4.4 outcome with the pool
    its copy is priced against — the same pool, tier, clip and gas
    :func:`tools.mockchain.report._simulate` uses, so the stage's ladder and the §10 report's are
    the same simulation reached two ways rather than two simulations that could disagree.

    ``value_basis_by_level`` is **the leader's mix at every level**, which is the limitation
    :mod:`tools.mockchain.report` states about its own capital ladder: a follower's realized /
    marked / dead split would need the follower's positions marked at their own horizons, and this
    fixture does not model that.
    """
    scored = _scored(run.result)
    basket = _basket_basis(scored)
    return {
        "leader_buys": leader_buys(run.chain, scored, _quote_assets()),
        "value_basis_by_level": {level: basket for level in CAPITAL_LEVELS},
    }


# -- inputs that are drawn ------------------------------------------------------


def _pre_t0(value, what):
    """Stamp a drawn number as measured before T0, saying in the stamp that it was drawn.

    ``universe``'s selection types refuse a bare ``Decimal`` — a laundered value *is* a bare
    ``Decimal`` by the time it reaches them — so the stamp has to be applied somewhere. The only
    honest somewhere for a synthetic run is here, and the source string says so rather than naming
    a warehouse read that never happened.
    """
    return PreT0Decimal.measured_before_t0(
        value, "drawn by tools.mockchain.stages for {} — NOT A MEASUREMENT".format(what)
    )


def _evidence(seed, wallet, index):
    """§6.2 evidence for one drawn account: an ordinary retail trader, no exclusion rule fires.

    Every account is clean on purpose. A drawn population whose exclusions were also drawn would
    make the §6.1 funnel a function of the draw rather than of the screen, and the point of running
    the stage is the screen.
    """
    return AccountEvidence(
        distinct_funding_sources=1,
        distinct_beneficiaries=1,
        settles_for_other_principals=False,
        share_token_holders=None,
        deployed_tokens_traded=0,
        two_sided_quote_share=None,
        failed_tx_share=_pre_t0(Decimal("0.01"), "failed_tx_share"),
        max_tx_per_hour=3,
        total_tx=draw_between(seed, "universe/total-tx", 100, 900, index),
        distinct_senders=1,
        day_of_week_skewness=_pre_t0(Decimal("0.4"), "day_of_week_skewness"),
        mean_inter_trade_gap_seconds=1800,
        controller_identified=True,
        netting_complete=True,
        labels=(),
    )


def _observation(chain, window, wallet, index):
    """One drawn pre-T0 observation for one synthetic wallet in one §6.3 window.

    ``valid_buys`` is the chain's own ``baseline_valid_buys`` for the wallet — the same count §10's
    churn block is computed from, so the two blocks cannot disagree about how active a wallet was.
    Everything else is drawn.
    """
    valid = chain.baseline_valid_buys[wallet]
    slack = draw_between(chain.seed, "universe/potential-slack", 1, 50, index)
    return AccountWindowObservation(
        account=wallet,
        window_key=window.key,
        account_type=AccountType.EOA,
        potential_buys=valid + slack,
        valid_buys=valid,
        buy_volume_usd=_pre_t0(
            Decimal(draw_between(chain.seed, "universe/buy-volume-usd", 1_000, 500_000, index)),
            "buy_volume_usd",
        ),
        active_days=draw_between(chain.seed, "universe/active-days", 5, 180, index),
        first_activity_block=window.baseline_start_block + 10,
        first_activity_ts=window.baseline_start_ts + 120,
        wallet_age_days=draw_between(chain.seed, "universe/wallet-age-days", 120, 900, index),
        as_of_block=window.t0.block - 1,
        as_of_timestamp=window.t0.timestamp - 1,
        t0=window.t0,
        evidence=_evidence(chain.seed, wallet, index),
    )


def _step0_window(chain, window, offset):
    """One window's §6.1 inputs, assembled through ``universe``'s own two-stage screen.

    Nothing here counts anything: :func:`universe.screen_warehouse` runs stage one,
    :func:`universe.classify_account` runs stage two, :func:`universe.build_census` builds the
    census and :func:`universe.step0.measure_window` — called by the stage runner, not here —
    measures §6.1. This function only supplies the population.
    """
    observations = tuple(
        _observation(chain, window, wallet, offset + index)
        for index, wallet in enumerate(SELECTED_WALLETS)
    )
    screen = screen_warehouse(
        window.key,
        [WarehouseRow(address=o.account, potential_buys=o.potential_buys) for o in observations],
    )
    admitted = tuple(o for o in observations if o.account in screen.admitted_addresses)
    verdicts = tuple(
        [classify_account(o, DEFAULT_POLICY, screen) for o in admitted]
        + [EligibilityVerdict(account=e.account, exclusion=e) for e in screen.exclusions]
    )
    movement = boundary_movement(admitted, verdicts)
    census = build_census(verdicts, screen.rows_screened, movement, window.key)
    eligible = census.admitted_count
    return Step0WindowInputs(
        window=window,
        observations=admitted,
        verdicts=verdicts,
        census=census,
        data_cost=DataCostReport(
            accounts_screened=screen.rows_screened,
            accounts_enriched=len(screen.admitted),
            transactions_enriched=sum(o.potential_buys for o in admitted),
        ),
        policy=DEFAULT_POLICY,
        total_active_accounts=screen.rows_screened * 10,
        accounts_with_at_least_one_valid_buy=max(screen.rows_screened, len(admitted)),
        base_rate=BaseRateComparison(
            window_key=window.key,
            assumed_size=max(eligible, 1),
            source="§13.7 design assumption, pre-registered",
            measured_size=eligible,
            statement=(
                "§13.7 records that the target population may simply not exist at the size "
                "assumed. This window's population is drawn by tools.mockchain.stages and is not "
                "a measurement of anything; see DRAWN_NOT_MEASURED."
            ),
        ),
        heuristic_modifications=HEURISTIC_MODIFICATIONS,
    )


def step0_universe_inputs(chain):
    """``step0.universe``'s four windows, the design that registers them, and the snapshot.

    Drawn, not measured — see :data:`DRAWN_NOT_MEASURED`. Every window carries the same ten marked
    wallets, so every window is ten accounts against §6.1's floor of 10,000.
    """
    return {
        "windows": tuple(
            _step0_window(chain, window, offset * len(SELECTED_WALLETS))
            for offset, window in enumerate(WINDOWS)
        ),
        "design": DESIGN,
        "parameter_freeze_hash": PARAMETER_FREEZE_HASH,
        "dataset_snapshot": chain.snapshot,
    }


def _features(chain, wallet, index, as_of_block):
    """One wallet's ten §6.6 covariates, every numeric dimension drawn from the seed."""
    values = {
        dimension: Decimal(
            draw_between(chain.seed, "benchmark/{}".format(dimension), 0, 100_000, index)
        )
        for dimension in NUMERIC_DIMENSIONS
    }
    return WalletFeatures(
        wallet=wallet,
        account_type=AccountType.EOA,
        values=values,
        as_of_block=as_of_block,
    )


def benchmark_match_inputs(run):
    """``benchmark.match``'s inputs: the run's scored wallets, plus a drawn control universe.

    The selected wallets are the ones that actually produced a :class:`contracts.BuyQuality` in the
    synthetic window, so *which* wallets are matched is a fact about the generated chain. Their
    covariates, and the whole control universe, are drawn — see :data:`DRAWN_NOT_MEASURED`. T0 is
    the window's start block, so every feature is stamped one block before it.
    """
    chain = run.chain
    as_of = chain.window.start_block - 1
    selected = tuple(wallet.wallet for wallet in _scored(run.result))
    controls = tuple(
        synthetic_address("control-{:02d}".format(n)) for n in range(N_CONTROLS)
    )
    features = {}
    for index, wallet in enumerate(selected + controls):
        features[wallet] = _features(chain, wallet, index, as_of)
    return {
        "selected": selected,
        "universe": tuple(sorted(features)),
        "features": features,
        "t0_block": chain.window.start_block,
    }


# -- the tripwire ----------------------------------------------------------------


def tripwire_runner(stage):
    """A runner for a stage that must never be reached on synthetic input.

    ``execute_stage`` checks the start gate and governance at steps 1-2 and calls the runner at
    step 4, so a refusal that is real never reaches this. If one ever does, it raises and the stage
    is recorded ``CRASHED`` against a run record that says what it was about to do — which is the
    loudest outcome available and the only honest one. A runner that returned a value here would
    publish a number from a run that had walked past the validation gate.
    """

    def runner(context):
        raise AssertionError(
            "stage {!r} was actually run under dataset snapshot {!r}. It is an execution-lane "
            "stage: it requires CODE_AND_DATA_FROZEN, which requires VALIDATION_PASSED, which only "
            "validation.independent advances and which that stage's runner refuses "
            "unconditionally because src/groundtruth/ does not exist (tickets 02, 36). Reaching "
            "the runner means either the gate was lifted by hand on a synthetic run or "
            "STAGE_AUTHORITY no longer says what this driver read. Nothing was computed: this "
            "stage has no synthetic inputs and a value here would be a number from a run that "
            "walked past the validation gate.".format(stage, context.dataset_snapshot)
        )

    return runner


#: The five stages behind the validation gate. Derived from :data:`phase0.execution.STAGE_AUTHORITY`
#: rather than listed, so a stage moved into the execution lane tomorrow gets the tripwire without
#: anyone remembering to add it.
BEHIND_THE_GATE = tuple(
    stage for stage in STAGES
    if STAGE_AUTHORITY[stage].requires in (gov.CODE_AND_DATA_FROZEN, gov.NULL_COMPLETE,
                                           gov.THRESHOLD_LOCKED, gov.MAIN_TEST_EXECUTED)
)


# -- what each stage published ---------------------------------------------------


def published(stage, value):
    """One short, deterministic line saying what a completed stage produced.

    Deliberately a *line*, not an artifact. The §10 report has exactly one publication route —
    :func:`tools.mockchain.provenance.publish_synthetic_artifact`, which re-reads the bytes it is
    about to hash — and this is not it. What this renders is enough for a reader of the stage table
    to see that the stage computed something and what shape it had; anything more would be a second
    route from a synthetic run to a published figure.
    """
    if value is None:
        return ""
    if stage == "step0.universe":
        return "{} windows measured, permits_ranking={}, insufficient: {}".format(
            len(value.measurements), value.permits_ranking,
            ", ".join(k.value for k in value.insufficient_windows) or "none",
        )
    if stage == "known_answer.battery":
        return "{}/{} frozen cases pass, pass rate {}".format(
            value["passed"], value["total"], value["known_answer_pass_rate"],
        )
    if stage == "pipeline.buy_quality":
        scored = [w for w in value.wallets if w.quality is not None]
        return "{} wallets scored, {} buys, {} quarantined, {} excluded".format(
            len(scored), sum(len(w.accounts) for w in scored),
            len(value.quarantine.records), len(value.excluded),
        )
    if stage == "benchmark.match":
        return "{} selected, {} matched, {} unmatched".format(
            value.n_selected, value.n_matched, len(value.result.unmatched),
        )
    if stage == "follower.adjust":
        if value.ladder is None:
            return "no ladder: {}".format(value.ladder_refusal)
        return "{} capital levels, {} reportable".format(
            len(value.levels), sum(1 for level in value.levels if level.reported),
        )
    return repr(value)


# -- the drive -------------------------------------------------------------------


@dataclass(frozen=True)
class StageOutcome:
    """What one stage request did. One of these per key of :data:`phase0.runs.STAGES`, in order."""

    stage: str
    #: ``COMPLETED`` / ``REFUSED`` / ``HELD`` / ``CRASHED``, or :data:`REFUSED_BY_HARNESS`.
    status: str
    #: The run record, or ``None`` — and ``None`` is a fact, not a gap: a stage refused before
    #: step 3 leaves no run record because nothing was about to happen.
    run_id: Optional[str]
    #: :func:`published`'s line for a completed stage, empty otherwise.
    value: str
    reason: str
    #: The governance state this stage completed, or ``None``. Always ``None`` here, and a test
    #: pins that: a synthetic run advances nothing.
    advanced_to: Optional[str] = None

    @property
    def blocked(self):
        return self.stage in BLOCKED_STAGES


@dataclass(frozen=True)
class SyntheticDrive:
    """Thirteen stage requests on one synthetic seed, and everything a reader needs to judge them.

    **This is not an artifact and does not become one.** It carries no hash, and the §10 report it
    holds on :attr:`run` was published by :func:`tools.mockchain.provenance.publish_synthetic_artifact`
    before this object existed. What it records is which stages the machine let run on generated
    input and what stopped the rest.
    """

    seed: int
    snapshot: str
    commit: str
    outcomes: Tuple[StageOutcome, ...]
    #: Where the governance machine finished. ``PARAMETERS_FROZEN`` when the parameter freeze was
    #: performed, ``PARAMETERS_OPEN`` when it was not — never anything past either.
    final_state: str
    #: The claims this run had to make. :data:`FICTIONS`, plus the freeze if it was performed.
    fictions: Tuple[str, ...]
    #: The full synthetic run, when one was needed. ``None`` when the start gate was left closed
    #: and no stage could reach a runner.
    run: object = None
    root: str = ""
    audit: object = field(default=None, repr=False)

    def outcome(self, stage):
        for outcome in self.outcomes:
            if outcome.stage == stage:
                return outcome
        raise KeyError("no outcome recorded for stage {!r}".format(stage))

    @property
    def statuses(self):
        return {outcome.stage: outcome.status for outcome in self.outcomes}

    @property
    def completed(self):
        return tuple(o.stage for o in self.outcomes if o.status == COMPLETED)

    def table(self):
        """The stage table, as text. One line per stage, in ``phase0.runs.STAGES`` order."""
        lines = [
            "SYNTHETIC PHASE 0 DRIVE — seed {}".format(self.seed),
            "  snapshot   {}".format(self.snapshot),
            "  commit     {}".format(self.commit),
            "  ends at    {}".format(self.final_state),
            "",
            "  {:<28} {:<20} {:<14} {}".format("stage", "outcome", "run record", "value"),
            "  " + "-" * 100,
        ]
        for outcome in self.outcomes:
            lines.append("  {:<28} {:<20} {:<14} {}".format(
                outcome.stage, outcome.status, outcome.run_id or "-",
                outcome.value or (outcome.reason.splitlines() or [""])[0][:60],
            ))
        return "\n".join(lines)


def _attempt(stage, runner, wiring, snapshot, commit, master_seed):
    """One stage request, with the harness's refusal caught and recorded rather than raised.

    :class:`tools.mockchain.governance.SyntheticRunRefused` is an exception on purpose — it is a
    defect in whatever wired a synthetic source to the real state machine and must not become a row
    in the audit log that reads as governance working. This driver *expects* it for the six stages
    that complete a transition, so it catches it here and records it as
    :data:`REFUSED_BY_HARNESS`, which is not a phase0 status and is not written to the log.
    """
    try:
        result = execute_synthetic_stage(
            stage, runner, SYNTHETIC_REQUESTER,
            governance=wiring.governance, dataset_snapshot=snapshot,
            preconditions=wiring.preconditions, runs=wiring.runs, audit=wiring.audit,
            commit=commit, config={"stage": stage, "source": "tools.mockchain"},
            master_seed=master_seed,
        )
    except SyntheticRunRefused as exc:
        return StageOutcome(stage, REFUSED_BY_HARNESS, None, "", str(exc))
    return StageOutcome(
        stage,
        result.status,
        result.run_id,
        published(stage, result._value) if result.status == COMPLETED else "",
        result.reason or "",
        result.advanced_to,
    )


def drive_synthetic_phase0(seed, root, commit=SYNTHETIC_COMMIT, freeze_parameters=True,
                           run=None):
    """Every one of the thirteen stages, in order, on one synthetic seed.

    :param seed: the chain's seed. An ``int``; :mod:`tools.mockchain.seeds` refuses anything else.
    :param root: the state directory the audit log, preconditions, governance state and run records
        are written under. A caller supplies it because a synthetic run's evidence is a directory
        somebody has to be able to read afterwards.
    :param commit: what the run records pin. See :data:`SYNTHETIC_COMMIT`.
    :param freeze_parameters: perform the ``PARAMETERS_FROZEN`` human act. ``False`` shows what the
        machine does to a synthetic run that tells no lie about it: every stage ``REFUSED`` at
        governance, no run record anywhere, nothing computed.
    :param run: a :class:`tools.mockchain.report.SyntheticRun` to reuse. Built here when omitted;
        supplied by callers that already have one, since it is the expensive part.
    :returns: a :class:`SyntheticDrive`.

    **It advances nothing.** Every stage goes through
    :func:`tools.mockchain.governance.execute_synthetic_stage`, which refuses before the runner any
    stage that completes a transition and refuses after it if the state moved anyway. The one
    transition that happens is the parameter freeze above, performed by this function and recorded
    as a fiction — and it is performed by ``governance.transition`` directly, because no stage
    advances it and therefore nothing in the harness or in ``phase0`` refuses it.

    **It does not lift the validation gate**, so the run stops exactly where a real run stops. See
    the module docstring.
    """
    chain = generate_chain(seed)
    snapshot = chain.snapshot
    if not is_synthetic_snapshot(snapshot):
        raise SyntheticRunRefused(
            "the chain at seed {} carries the snapshot {!r}, which does not declare itself "
            "synthetic. Refusing to drive the Phase 0 stage register under it: the snapshot is "
            "what every run record and every audit entry quotes, and a run the log cannot be told "
            "from a measurement is the one thing this package exists to "
            "prevent.".format(seed, snapshot)
        )

    wiring = synthetic_wiring(root, record_preconditions=True)
    master_seed = new_master_seed(snapshot)
    fictions = list(FICTIONS)

    if freeze_parameters:
        wiring.governance.transition(
            gov.PARAMETERS_FROZEN, SYNTHETIC_REQUESTER,
            {
                "dataset_snapshot": snapshot,
                "note": (
                    "PERFORMED BY A SYNTHETIC RUN. PARAMETERS_FROZEN records a human act (ticket "
                    "11) and no person froze anything. Nothing refused this: no stage advances "
                    "PARAMETERS_FROZEN, so the predicted refusal in tools.mockchain.governance "
                    "never saw it, and this call withholds the snapshot from "
                    "GovernanceMachine.transition, which is the one thing src/phase0/ cannot "
                    "check. The snapshot is in this entry's detail regardless, so the log says "
                    "what the freeze was over even though the machine was not told. See "
                    "GOVERNANCE_GAP."
                ),
            },
        )
    else:
        fictions = [f for f in fictions if not f.startswith("PARAMETERS_FROZEN")]

    if run is None:
        run = synthetic_report(seed)

    inputs = {
        "step0.universe": step0_universe_inputs(chain),
        "known_answer.battery": {},
        "pipeline.buy_quality": buy_quality_inputs(chain),
        "benchmark.match": benchmark_match_inputs(run),
        "follower.adjust": follower_adjust_inputs(run),
        "golden_set.trace": {},
        "reconciliation.cross_source": {},
        "validation.independent": {},
    }

    outcomes = []
    for stage in STAGES:
        if stage in BEHIND_THE_GATE:
            runner = tripwire_runner(stage)
        else:
            runner = runner_for(stage, **inputs[stage])
        outcomes.append(_attempt(stage, runner, wiring, snapshot, commit, master_seed))

    return SyntheticDrive(
        seed=seed,
        snapshot=snapshot,
        commit=commit,
        outcomes=tuple(outcomes),
        final_state=wiring.governance.state,
        fictions=tuple(fictions),
        run=run,
        root=str(root),
        audit=wiring.audit,
    )


# -- the blocked stages, confirmed without the state machine ---------------------


def confirm_blocked(stage):
    """Call a blocked stage's runner directly and return the refusal it raised.

    Why this exists rather than reading the drive's table: ``validation.independent`` completes
    ``VALIDATION_PASSED``, so :func:`tools.mockchain.governance.refuse_if_synthetic_would_advance`
    refuses it *before* ``execute_stage`` is called and its own blocker never gets to speak. The
    stage table therefore records the harness's refusal for it, which is true and is not the whole
    truth — the question "is the stage still blocked on synthetic data?" is a question about the
    runner, and this answers it by calling the runner.

    :returns: the ``pipeline.stages.decide.StageBlocked`` the runner raised.
    :raises AssertionError: if the runner returns instead. A blocked stage that produced a value
        is the finding, and it must not be reported as a passing check.
    """
    from pipeline.stages.decide import StageBlocked

    class _Context(object):
        stage = None
        run_id = "synthetic-blocked-probe"
        commit = SYNTHETIC_COMMIT
        dataset_snapshot = None

    context = _Context()
    context.stage = stage
    runner = runner_for(stage)
    try:
        value = runner(context)
    except StageBlocked as exc:
        return exc
    raise AssertionError(
        "blocked stage {!r} returned {!r} instead of refusing. Its registry entry says it always "
        "raises; a value from it is a wrong number that looks plausible.".format(stage, value)
    )
