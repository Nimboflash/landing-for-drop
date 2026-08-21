"""``step0.universe`` — ticket 26's four-window measurement, and the one blocker still standing.

``phase0.execution.execute_stage(stage, runner, ...)`` authorises a stage, opens its run record
*before* the stage runs, calls ``runner(context)``, and records ``COMPLETED`` / ``REFUSED`` /
``HELD`` / ``CRASHED``. It takes the runner as an argument because ``phase0`` is SHARED and must not
know what a stage does. This module is the other half for one stage: §6.1's counts and
distributions, measured per window, assembled into a :class:`universe.step0.Step0Report`.

It lives in ``pipeline`` because ``pipeline`` is the composition root — the one builder package
permitted to import another — and ``universe`` is a leaf that imports no sibling. Composing
``universe.measure_window`` over four windows is exactly the work a composition root exists to do,
and ``tests/test_lane_independence.py`` forbids the ``(SHARED, BUILDER)`` edge it would take to do
it anywhere near the governance machine.

What changed, and what did not
------------------------------

``step0.universe`` used to be wired to :func:`pipeline.stages.decide.blocked_stage_runner` under two
blockers. The first said ``src/universe/`` was not on this commit — it lived on an unmerged branch
whose post-T0 look-ahead barrier had failed an audit. **That is no longer true.** The package is on
``main``, the barrier was rebuilt as a five-layer containment system, and it was attacked; the
blocker naming it has been deleted rather than reworded, because a refusal that names a reason which
has since become false is the defect class this repository has spent several commits removing.

The second blocker is untouched and still decides the stage's outcome in this tree. There is no
measured universe anywhere in this repository: nothing here has touched real chain data, and the
first data pull needs the authenticated archival node ticket 03 is waiting on. So a caller with no
observations still gets a refusal, from :data:`NO_MEASURED_UNIVERSE` — the same
:class:`~pipeline.stages.decide.StageBlocked`, in the same audit log, naming one ticket instead of
two.

The two paths, and why the empty one is not simply "measure nothing"
--------------------------------------------------------------------

    step0_universe_runner()                    -> refuses, naming ticket 12
    step0_universe_runner(windows, design,     -> measures, and returns a Step0Report
                          freeze_hash, snapshot)

A runner that measured an empty population would publish a §6.1 block reading "0 eligible accounts"
in every window, which is indistinguishable on a dashboard from a measurement that was taken and
found nothing — and it is the more flattering reading, because zero eligible accounts is a fact
about the world rather than about the tree. ``universe.step0`` refuses that too, from the other
side: :class:`universe.step0.EmptyEligibleUniverse` says a window admitting no account at all is a
measurement that could not be taken rather than a universe of size zero.

A short universe is a **status**, not an error
-----------------------------------------------

§6.1's floor is 10,000 eligible accounts, and a window below it is
``INSUFFICIENT CANDIDATE UNIVERSE``. That is a measured finding — arguably the most valuable cheap
finding Phase 0 can produce — so :attr:`universe.step0.Step0Measurement.status` derives it and
nothing raises. **This runner does not convert it into a crash on the way out.** A stage that
crashed on its most informative result would publish nothing at all, and the audit log would carry a
defect where a finding belongs. §6.1 says the *window* is not valid and the four-window design must
be revised before the main test, which is narrower than failing the run: the refusal with teeth
lives in :class:`universe.freeze.FrozenUniverse` and :func:`universe.freeze.require_step0_complete`,
where freezing or ranking a short universe is refused. Measuring one is not.

What the stage does not do
--------------------------

It measures. It does not freeze a universe, does not rank, does not select, and produces no
forward-window number — ticket 26's last acceptance criterion, and here it is a property of this
module's import set rather than a promise.

It also does not enforce ticket 26's *other* ordering criterion, that Step 0 completion is a
governance precondition for ranking. ``phase0.execution.STAGE_AUTHORITY`` does not enforce it and
cannot as it stands: there is no ranking stage among ``phase0.runs.STAGES``' thirteen, so there is
nothing for the register to order Step 0 against, and ``step0.universe`` advances no governance
state that a later stage could require. Enforcing it from here would be the wrong direction — a
builder-lane runner policing the order it is itself subject to is a stage authorising itself — so
this module states the gap instead of closing it. ``universe.freeze.require_step0_complete`` is the
only check that exists today, and it is a call rather than a shape.
"""

from dataclasses import dataclass
from typing import Tuple

from universe import (
    AccountWindowObservation,
    BaseRateComparison,
    DataCostReport,
    EligibilityPolicy,
    EligibilityVerdict,
    HeuristicModification,
    TrainingWindow,
    UniverseCensus,
    WindowDesign,
    measure_window,
    step0_report,
)

from .decide import Blocker, _require_stage, blocked_stage_runner

__all__ = [
    "STAGE",
    "NO_MEASURED_UNIVERSE",
    "PRODUCES",
    "EMPTY_READS_AS",
    "Step0WindowInputs",
    "step0_universe_runner",
]

#: The registry key this module serves. Written out rather than imported from ``phase0``: that
#: package is SHARED, and borrowing one string from it would put a builder module in its debt for
#: nothing. The runner checks it against the context, so a crossed wire is caught at the first call.
STAGE = "step0.universe"

#: The one thing ``step0.universe`` is still waiting for.
#:
#: Ticket 12, and nothing else. The ticket 25-28 blocker that used to sit beside it named an unmerged
#: branch and a failed barrier audit; ``src/universe/`` is on this commit and the barrier was rebuilt
#: and attacked, so that blocker was deleted rather than softened. This one is unchanged in
#: substance and says what would clear it: the first data pull, which cannot happen until ticket 03
#: provides an authenticated archival node.
NO_MEASURED_UNIVERSE = Blocker(
    ticket="12",
    missing=(
        "there is no measured universe to report: nothing in this repository has touched real "
        "chain data"
    ),
    unblocked_by=(
        "the first data pull, with its coverage gap measured and recorded — which needs the "
        "authenticated archival node ticket 03 is waiting on, since the three public endpoints "
        "checked each refuse archive requests"
    ),
)

#: What the stage would have produced, in a reviewer's words. Quoted back in the refusal.
PRODUCES = (
    "the eligible universe measured in all four walk-forward windows, with the distributions later "
    "matching depends on, and the under-10,000-accounts stopping condition evaluated per window"
)

#: What an empty return would read as on a dashboard. The reason the stage raises instead.
EMPTY_READS_AS = "0 eligible accounts"


# -- what one window's measurement is assembled from ------------------------------


@dataclass(frozen=True)
class Step0WindowInputs:
    """Everything :func:`universe.step0.measure_window` needs for one §6.3 window, as one value.

    Ten separate arguments per window, times four windows, is a call nobody can read and a call
    where two of them can be silently swapped. Grouping them per window makes the window the unit —
    which is what §6.1 measures — and lets the factory check the one thing neither side can check
    alone: that this window's calendar is the one the pre-registered design registers.

    The field names and their meanings are ``measure_window``'s own and are deliberately not
    restated: a second copy of a parameter list is a second thing to get out of date. Two of them
    are worth a sentence here anyway, because they are the ones a reader assumes are derived and
    they are not:

    :param total_active_accounts: from the warehouse. Nothing anywhere in this tree can check it,
        and every §6.1 funnel ratio rests on it.
    :param accounts_with_at_least_one_valid_buy: likewise from the warehouse, because accounts below
        the potential-buy floor were never returned and their valid buys are unknowable.

    ``dataset_snapshot`` is **not** a field. It belongs to the report — ``Step0Report`` refuses a
    report whose windows were measured from two different snapshots — so the factory takes it once
    and stamps every window with it. A per-window snapshot would be four places for one fact to be
    written down, and the disagreement between them is what the report's own check exists to catch.
    """

    window: TrainingWindow
    observations: Tuple[AccountWindowObservation, ...]
    verdicts: Tuple[EligibilityVerdict, ...]
    census: UniverseCensus
    data_cost: DataCostReport
    policy: EligibilityPolicy
    total_active_accounts: int
    accounts_with_at_least_one_valid_buy: int
    base_rate: BaseRateComparison
    heuristic_modifications: Tuple[HeuristicModification, ...] = ()

    def __post_init__(self) -> None:
        # Materialised here, at wiring time. A generator is exhausted by the first run, so the
        # second run of the same inputs would measure a different population from the first —
        # exactly what ticket 26's "a re-run returns identical numbers" forbids. It would not get
        # as far as publishing a confident nothing: ``measure_window`` counts the eligible universe
        # from the verdicts and the in-band accounts from the observations, so an exhausted pair
        # inverts §6.1's funnel and ``Step0Measurement`` refuses the result. What these three lines
        # buy is that the re-run returns the first run's answer instead of a crash somebody has to
        # diagnose. Pinned by ``test_a_re_run_measures_the_same_windows_when_the_inputs_were_lazy``.
        object.__setattr__(self, "observations", tuple(self.observations))
        object.__setattr__(self, "verdicts", tuple(self.verdicts))
        object.__setattr__(self, "heuristic_modifications", tuple(self.heuristic_modifications))
        if type(self.window) is not TrainingWindow:
            raise TypeError(
                "Step0WindowInputs.window must be a TrainingWindow, got {}. It is the key the "
                "design, the census, the base-rate comparison and every observation are checked "
                "against, so a value that merely looks like one would be checked against "
                "nothing.".format(type(self.window).__name__)
            )
        if not self.observations:
            raise ValueError(
                "window {} was given no observations. A window measured over an empty population "
                "is not a smaller measurement: §6.1's five distributions describe the shape of the "
                "eligible universe and there would be no shape to describe, so the figures would "
                "read as a universe somebody measured and found empty.".format(
                    self.window.key.value)
            )


# -- the runner -------------------------------------------------------------------


def step0_universe_runner(windows=(), design=None, parameter_freeze_hash=None,
                          dataset_snapshot=None):
    """Wire ``step0.universe``: measure §6.1 in every window the design registers, or refuse.

    :param windows: :class:`Step0WindowInputs`, one per §6.3 window. Order does not matter — the
        measurements are put in the design's order, because which windows Step 0 covered is a fact
        about the experiment and not about the call. ``Step0Report`` cannot enforce that: it
        compares the *set* of keys against the design's, so it accepts any permutation. Pinned by
        ``test_step0_universe_reports_the_windows_in_the_designs_order_not_the_callers``, which
        supplies them in an order no design registers. **Empty is the refusal path**, not an
        error: see below.
    :param design: the pre-registered :class:`universe.protocol.WindowDesign`. Required once
        anything is supplied, because ``Step0Report`` is a report *about* a design and ticket 26
        requires all four of its windows measured before any ranking.
    :param parameter_freeze_hash: the parameter freeze the design and the replacement registry were
        registered under. Carried into the report, where
        :func:`universe.step0.replace_window` compares it against the registry's before it will
        authorise a replacement window.
    :param dataset_snapshot: the frozen snapshot the counts are measured from, stamped on every
        window. Ticket 26 requires the counts to be reproducible from it.
    :returns: ``runner(context) -> universe.step0.Step0Report``.

    **With no windows the stage still refuses, and says why.** It returns
    :func:`pipeline.stages.decide.blocked_stage_runner`'s runner under :data:`NO_MEASURED_UNIVERSE`
    — one blocker, ticket 12, unchanged in substance from when this whole stage was blocked. The
    stage publishes no value, ``execute_stage`` records ``CRASHED`` with the reason against a run
    record that already exists, and the refusal is in the hash-chained audit log. Wiring the empty
    call to a measurement over nothing would publish "0 eligible accounts" in four windows, which
    reads as a finding about the world.

    **What the runner guarantees.** Every supplied window is measured by ``universe.measure_window``
    and by nothing else here — no count is recomputed, no threshold is re-applied, and §6.1's rules
    stay in the package that owns them. All four measurements are stamped with the one
    ``dataset_snapshot`` the run record pins, and the runner refuses to run under a context whose
    snapshot is a different one. A report over anything other than the design's four windows is
    refused by ``Step0Report`` itself, so a run that measured three of them publishes nothing.

    **A window below §6.1's floor completes.** Its status is ``INSUFFICIENT CANDIDATE UNIVERSE``,
    it is carried in the returned report, and ``Step0Report.permits_ranking`` is then ``False``.
    Nothing here inspects that status and nothing here raises on it — see the module docstring.

    **What it does not guarantee.** It cannot tell that the observations are the whole of a window;
    no function reachable from here knows what the whole of a window is. It cannot tell that they
    were really measured before T0 — every provenance stamp in ``universe`` is a claim the caller
    makes at the warehouse read, and the structural barrier binds ``src/`` rather than the SQL. And
    it does not check that these inputs are the ones the run record's ``config`` describes, for the
    reason :mod:`pipeline.stages.measure` gives: a runner that re-derived its inputs from the run
    record would be a second authority on what the run's inputs were.
    """
    supplied = tuple(windows)
    if not supplied:
        return blocked_stage_runner(STAGE, (NO_MEASURED_UNIVERSE,), PRODUCES, EMPTY_READS_AS)

    if not isinstance(design, WindowDesign):
        raise TypeError(
            "step0.universe was given {} window(s) of observations and {} as its design. Ticket 26 "
            "measures the four §6.3 windows the design registers; without one there is nothing "
            "saying which four windows this run was supposed to cover, and a report over whichever "
            "windows happened to be supplied is a different experiment from the pre-registered "
            "one.".format(len(supplied), type(design).__name__)
        )
    _require_named("parameter_freeze_hash", parameter_freeze_hash)
    _require_named("dataset_snapshot", dataset_snapshot)
    # One identity rule for one fact. ``measure_window`` and ``step0_report`` both key the snapshot
    # through ``str()``, and the check inside the runner compares it against the run record's. A
    # value checked by ``==`` and published through ``str()`` is a value derived two ways, and a
    # value that satisfies one rule and not the other passes the check and is then filed under a
    # name the run record does not pin — which is the thing that check's own message says cannot
    # happen. So the transformation happens once, here, and the checked value and the published
    # value are the same value.
    dataset_snapshot = str(dataset_snapshot)
    ordered = _in_design_order(supplied, design)

    def runner(context):
        """Measure §6.1 window by window, then assemble ticket 26's report.

        Draws no seed: Step 0 is a deterministic function of a frozen snapshot, so the context is
        read for the stage key and for the snapshot the run record pinned, and for nothing else.
        Nothing is caught — a census that does not reconcile, a window admitting no account at all,
        an observation carrying another window's T0 all reach ``execute_stage`` as ``CRASHED`` with
        their own reason, which is the right outcome for a defect in what assembled the call.
        """
        _require_stage(context, STAGE)
        if context.dataset_snapshot != dataset_snapshot:
            raise ValueError(
                "this runner was wired to measure from dataset snapshot {!r} and the run record "
                "pins {!r}. Ticket 26 requires the counts to be reproducible from the frozen "
                "snapshot, and a report filed under a run record naming a different one is "
                "reproducible from neither — the report would name the snapshot it was measured "
                "from and the audit trail would name another.".format(
                    dataset_snapshot, context.dataset_snapshot)
            )

        measurements = []
        for item in ordered:
            measurements.append(measure_window(
                window=item.window,
                observations=item.observations,
                verdicts=item.verdicts,
                census=item.census,
                data_cost=item.data_cost,
                policy=item.policy,
                dataset_snapshot=dataset_snapshot,
                total_active_accounts=item.total_active_accounts,
                accounts_with_at_least_one_valid_buy=item.accounts_with_at_least_one_valid_buy,
                base_rate=item.base_rate,
                heuristic_modifications=item.heuristic_modifications,
            ))
        # No status is read here, and none is acted on. A window below §6.1's floor is a carried
        # finding; the refusals that stop a short universe being *used* are on FrozenUniverse and
        # require_step0_complete, one step later.
        return step0_report(
            design=design,
            measurements=tuple(measurements),
            parameter_freeze_hash=parameter_freeze_hash,
            dataset_snapshot=dataset_snapshot,
        )

    return runner


# -- wiring-time checks -----------------------------------------------------------
#
# All of it runs when the factory is called, before governance has opened a run record. A wiring
# defect that raised inside the runner instead would leave a run record for a stage that could
# never have run, and the point of writing that record first is that it is evidence of something
# genuinely about to happen.


def _require_named(what, value):
    if value is None or not str(value).strip():
        raise ValueError(
            "step0.universe was given windows to measure and no {}. Ticket 26 requires the counts "
            "to be reproducible from the frozen snapshot and pinned to the parameter freeze they "
            "were registered under; a report that names neither cannot be re-run and cannot be "
            "tied to the design it measures.".format(what)
        )
    return value


def _in_design_order(windows, design):
    """Validate the per-window inputs against the design, and put them in its order.

    Three refusals, and the last is one only the composition root is in a position to make.
    ``Step0Report`` compares the report's window *keys* against the design's, which is what catches
    a report over three of the four. It cannot catch a window keyed correctly and carrying a
    different calendar, because it never sees the design's copy of that calendar beside the measured
    one — this function does, and a slot measured under a T0 the design does not register is the
    whole of what §6.3's pre-registered calendar is for. Changing a calendar is
    :func:`universe.step0.replace_window`'s to authorise, under a pre-registered rule, and it
    produces a new design rather than a differently-measured window.

    There is deliberately **no** "this window is not one the design registers" check, because it
    cannot fire: ``WindowKey`` is closed at §6.3's four and ``WindowDesign`` refuses anything but
    four distinct keys, so every design registers all four and ``positions`` is always complete. A
    guard that cannot fire is one nobody can delete-test, and an unpinned guard reads as a
    protection that is not there.
    """
    positions = {key: index for index, key in enumerate(design.keys)}
    seen = {}
    for position, item in enumerate(windows):
        if not isinstance(item, Step0WindowInputs):
            raise TypeError(
                "windows must hold Step0WindowInputs, got {} at position {}. Ten loose arguments "
                "per window is a call in which two of them can be swapped without anything "
                "noticing.".format(type(item).__name__, position)
            )
        key = item.window.key
        if key in seen:
            raise ValueError(
                "windows[{}] and windows[{}] both measure window {}. One window is one §6.1 block; "
                "two would be two answers to the question ticket 26 asks once, and nothing is "
                "permitted to choose between them.".format(seen[key], position, key.value)
            )
        seen[key] = position
        registered = design.window(key)
        if item.window != registered:
            raise ValueError(
                "windows[{}] measures window {} under T0 (block {}, second {}) and the design "
                "registers that slot at (block {}, second {}). The calendar is pre-registered, so "
                "measuring the slot under another one is running a window nobody registered while "
                "reporting it under a name somebody did. A calendar is changed by "
                "universe.step0.replace_window, under a pre-registered rule, and that produces a "
                "new design.".format(
                    position, key.value, item.window.t0.block, item.window.t0.timestamp,
                    registered.t0.block, registered.t0.timestamp)
            )
    return tuple(sorted(windows, key=lambda item: positions[item.window.key]))
