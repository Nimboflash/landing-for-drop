"""The two permutation-null stages and the threshold-calibration stage, as runners.

Pre-registration §8.2 · §8.3 · §8.4.

``phase0.execute_stage(stage, runner, ...)`` authorises a stage, opens its run record, calls
``runner(context)``, and records ``COMPLETED`` / ``REFUSED`` / ``HELD`` / ``CRASHED``. It takes the
runner as an argument because ``phase0`` is SHARED and must not know what a stage *does*. This
module is the other half for three of the thirteen stages::

    null.leader          permutation_null_detail on the "leader" column
    null.follower        permutation_null_detail on the "follower_adjusted" column
    threshold.calibrate  calibrate_threshold_detail over both columns' null distributions

It lives in ``pipeline`` — the composition root, the one builder package permitted to import other
builder packages — because knowing what a stage does is exactly what a runner is for, and
``tests/test_lane_independence.py`` forbids the ``(SHARED, BUILDER)`` edge that would let this code
sit next to the governance machine it is called by.

What a runner is
----------------

``runner(context) -> value``. ``context`` is a ``phase0.execution.StageContext`` carrying the run
id, the commit, and ``child_seed(purpose, index)``. A runner **raises to crash the stage**; it never
catches and returns a plausible-looking ``None``, because a stage that did not complete has no value
to publish. That is not a stylistic preference here: ``StageResult.value`` raises
``StageNotCompleted`` for every non-``COMPLETED`` status precisely so that no caller can read a
value without reading a status, and a runner returning ``None`` on failure would hand that caller a
``COMPLETED`` nothing instead.

This module is not imported by ``phase0`` and imports nothing from it. It duck-types the context on
two attributes — ``stage`` and ``child_seed`` — so the governance package stays a caller rather than
a dependency.

Seeds, and where the purpose string comes from
----------------------------------------------

§8.2 fixes the derivation: ``purpose = "null.<column>.window<N>"``, ``index = 0..999``, over the run
master seed and the commit. That string is built by ``matching_null.null_purpose`` and this module
does not rebuild it — the runners hand ``context.child_seed`` straight to
``permutation_null_detail`` as its ``seed_fn``, so there is one implementation of a derivation the
freeze manifest pins. Note the consequence for the follower stage: the *stage* is ``null.follower``
and the *column* is ``follower_adjusted``, so its purposes read ``null.follower_adjusted.windowN``.
The column name is the pre-registered one and the stage key is governance's; they are deliberately
not forced to match.

Because the derivation takes the commit, a re-run after an invalidation draws genuinely new numbers
rather than inheriting the old ones — which is the property that makes the whole distribution
reproducible from the run record alone, and re-running it after a code change a new experiment.

What these runners do not guarantee
-----------------------------------

* **They do not compute the gate.** ``statistic_fn`` is supplied per window by the caller and must
  recompute the full three-condition §7.1 gate on the relabelled population, returning a
  ``contracts.WindowScore``. ``permutation_null_detail`` checks its *type*, its column and its
  window; nothing anywhere checks that it actually reads the labels it was handed. A
  ``statistic_fn`` that ignored its argument would produce 1,000 identical runs and a null
  collapsed onto a point — ``DegenerateNull`` catches that failure for seeds and not for this.
* **They do not check that all four §6.3 windows are present.** The windows are whatever the
  integrator supplies, recorded in the returned value. A null over three windows is a null over
  three windows, and ``gate_validation.windows`` is where a short gate artifact is refused.
* **They do not bind the calibrated threshold to the main test.** Governance sequences the stages;
  it does not carry a stage's value to the next one. See the module's own note in
  :func:`threshold_calibrate_runner`.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Tuple

from contracts import MatchedSet
from matching_null import (
    NULL_COLUMNS,
    NULL_RUNS,
    CalibrationReport,
    NullDistribution,
    ThresholdNotCalibrated,
    calibrate_threshold_detail,
    permutation_null_detail,
)

#: The three ``phase0.runs.STAGES`` keys this module serves. Written out rather than imported:
#: ``phase0`` is SHARED and importing it here to borrow three strings would put a builder module in
#: the governance package's debt for nothing. The runners check the key they were handed against
#: the one on the context, so a mis-wiring is caught at the first call rather than by inspection.
LEADER_STAGE = "null.leader"
FOLLOWER_STAGE = "null.follower"
CALIBRATE_STAGE = "threshold.calibrate"

#: §8.2 builds exactly two null distributions and ``WindowScore.column`` names them. The strings are
#: ``matching_null.NULL_COLUMNS``; the mapping from stage key to column is this module's, because
#: only the composition root knows that the stage called ``null.follower`` builds the
#: ``follower_adjusted`` column.
_COLUMN_FOR_STAGE = {
    LEADER_STAGE: "leader",
    FOLLOWER_STAGE: "follower_adjusted",
}


# -- inputs ---------------------------------------------------------------------


@dataclass(frozen=True)
class NullWindowInputs:
    """One window's contribution to one column's null.

    :param window: the §6.3 walk-forward window index. Part of the seed purpose, so two windows
        never share a draw.
    :param matched_sets: the §6.6 matched sets for this window, as ``build_matched_sets`` emits
        them. Permuted within, never across.
    :param statistic_fn: ``(relabelled_sets) -> contracts.WindowScore``. It must recompute the whole
        §7.1 gate — mean, median and edge origin — on the relabelled population, for this window and
        this column. Supplied rather than built here because the statistic is the *pipeline*, and a
        null that recomputed some cheaper thing would place its 95th percentile in a different
        experiment (§8.2).

    The semantic refusals over the sets — a duplicate selected wallet, a set with no controls, a
    score belonging to another window — live in ``matching_null.permutation_null_detail`` and are
    not restated here. They therefore arrive when the stage runs, and land as ``CRASHED`` with the
    reason recorded, which is the right outcome for a defect in what assembled the call.
    """

    window: int
    matched_sets: Tuple[MatchedSet, ...]
    statistic_fn: Callable

    def __post_init__(self):
        object.__setattr__(self, "matched_sets", tuple(self.matched_sets))
        if not isinstance(self.window, int) or isinstance(self.window, bool) or self.window < 1:
            raise ValueError(
                "window must be a positive int, got {!r}. It is an identity key — the seed purpose "
                "and the WindowScore are both keyed on it — and True, 1 and 1.0 are one key to "
                "Python.".format(self.window)
            )
        if not callable(self.statistic_fn):
            raise TypeError(
                "statistic_fn must be callable: it is the gate, recomputed on each relabelling"
            )


# -- what the null stages return -------------------------------------------------


@dataclass(frozen=True)
class NullColumnResult:
    """One column's null, across every window the stage covered.

    This is the *rich* result and deliberately not a tuple of ``contracts.PermutationResult``:
    §8.3's calibration needs the per-run ``WindowScore``, since the Null Pass Rate is a
    three-condition question and the seam type carries the mean advantages alone.
    ``matching_null.calibrate_threshold`` refuses the seam type for exactly that reason, so passing
    it forward would make the next stage impossible. :meth:`to_contracts` produces the seam view for
    an artifact, once nothing needs to calibrate from it.
    """

    stage: str
    column: str
    n_runs: int
    distributions: Tuple[NullDistribution, ...]

    def __post_init__(self):
        object.__setattr__(self, "distributions", tuple(self.distributions))
        if not self.distributions:
            raise ValueError("a null result must cover at least one window")
        seen = set()
        for distribution in self.distributions:
            if distribution.column != self.column:
                raise ValueError(
                    "distribution for column {!r} in a {!r} result".format(
                        distribution.column, self.column
                    )
                )
            if distribution.window in seen:
                raise ValueError(
                    "two null distributions for column {!r} window {}; nothing is permitted to "
                    "choose between two answers to one question".format(
                        self.column, distribution.window
                    )
                )
            seen.add(distribution.window)

    @property
    def windows(self):
        return tuple(d.window for d in self.distributions)

    @property
    def purposes(self):
        """The §8.2 seed purposes this result was drawn under, in window order.

        Recorded because it is what a reviewer re-derives the 1,000 draws from, given the run
        record's master seed and commit.
        """
        return tuple(d.purpose for d in self.distributions)

    def by_window(self):
        return {d.window: d for d in self.distributions}

    def to_contracts(self):
        """The seam view — one ``contracts.PermutationResult`` per window.

        Lossy on purpose: it drops the per-run window scores, so a caller holding only this cannot
        calibrate a threshold from it. That is the loss ``calibrate_threshold`` refuses to accept.
        """
        return tuple(d.to_contract() for d in self.distributions)


# -- what the calibration stage returns ------------------------------------------


@dataclass(frozen=True)
class CalibratedThreshold:
    """§8.3's Final Mean Threshold, and the per-distribution evidence behind it.

    ``threshold`` is the number the main test is run against. It is in the units of
    ``WindowScore.mean_advantage``, whichever those are: nothing in this path can tell percentage
    points from a ratio, and the candidates decide it.
    """

    stage: str
    threshold: Decimal
    reports: Tuple[CalibrationReport, ...]
    binding: CalibrationReport
    at_grid_floor: bool

    def __post_init__(self):
        object.__setattr__(self, "reports", tuple(self.reports))
        if not self.reports:
            raise ValueError("a calibration must carry the reports it was decided from")

    @property
    def binding_column(self):
        return self.binding.column

    @property
    def binding_window(self):
        return self.binding.window

    def report_for(self, column, window):
        for report in self.reports:
            if report.column == column and report.window == window:
                return report
        raise KeyError("no calibration report for column {!r} window {}".format(column, window))


# -- the runners -----------------------------------------------------------------


def null_leader_runner(windows, n_runs=NULL_RUNS):
    """Build the ``null.leader`` runner: §8.2's permutation null on the leader column.

    :param windows: an iterable of :class:`NullWindowInputs`, one per §6.3 window. Order does not
        matter — the result is put in window order, because which windows the null covers is a fact
        about the experiment and not about the call.
    :param n_runs: §8.2 pre-registers 1,000, which is the default here because the composition root
        is where the pre-registered figure belongs. A smaller value is legitimate for a smoke run
        and is recorded in every ``NullDistribution`` and every ``PermutationResult`` it produces,
        so a short null cannot later pass as the pre-registered one.
    :returns: ``runner(context) -> NullColumnResult``.

    Separate from :func:`null_follower_runner` because the two stages are separately authorised and
    separately recorded — both feed ``NULL_COMPLETE`` and neither advances it alone. They share an
    implementation because §8.2 requires the two columns to be built by identical code: two
    hand-written copies would be two nulls, and the difference between them would be invisible.
    """
    return _null_runner(LEADER_STAGE, windows, n_runs)


def null_follower_runner(windows, n_runs=NULL_RUNS):
    """Build the ``null.follower`` runner: §8.2's permutation null on the follower-adjusted column.

    Arguments and result as :func:`null_leader_runner`. The column is ``follower_adjusted``, so the
    seed purposes read ``null.follower_adjusted.window<N>`` — the pre-registered column name, not
    the governance stage key.

    The follower column is the follower-*adjusted* metric — §7.2's gate at design capital. Whether
    the ``statistic_fn`` handed in actually applies the execution-cost adjustment is not something
    this module can see or check; it is the integrator's wiring, and getting it wrong would build a
    null for the leader column under the follower's name.
    """
    return _null_runner(FOLLOWER_STAGE, windows, n_runs)


def _null_runner(stage, windows, n_runs):
    column = _COLUMN_FOR_STAGE[stage]
    if column not in NULL_COLUMNS:
        raise ValueError(
            "column {!r} is not one of matching_null.NULL_COLUMNS {}; §8.2 builds a Leader and a "
            "Follower-Adjusted null and nothing else".format(column, NULL_COLUMNS)
        )
    inputs = _ordered_window_inputs(windows, column)
    n_runs = _require_run_count(n_runs)

    def runner(context):
        """Run §8.2's within-matched-set permutation null for one column, window by window.

        Every draw's seed is ``context.child_seed(null_purpose(column, window), index)``, so the
        distribution replays exactly from the run record's master seed and commit. Nothing is
        caught: a statistic that raises, a set that cannot be permuted, or a seed derivation that
        repeats all reach ``execute_stage`` and are recorded as ``CRASHED``.
        """
        _require_stage(context, stage)
        distributions = []
        for item in inputs:
            distributions.append(permutation_null_detail(
                item.matched_sets,
                item.statistic_fn,
                n_runs,
                # The seed function itself, not a wrapper: ``permutation_null_detail`` builds the
                # §8.2 purpose with ``null_purpose`` and this module does not build a second one.
                context.child_seed,
                column,
                item.window,
                # reference_threshold left at its default, which is the observed mean advantage.
                # There is no calibrated threshold to report against yet — §8.4 puts calibration
                # after the null — and a constant here would be a threshold nobody had justified.
                # §8.3's rates are recomputed per candidate by the calibration stage regardless.
            ))
        return NullColumnResult(
            stage=stage,
            column=column,
            n_runs=n_runs,
            distributions=tuple(distributions),
        )

    return runner


def threshold_calibrate_runner(nulls, candidates):
    """Build the ``threshold.calibrate`` runner: §8.3's Final Mean Threshold.

    :param nulls: the values of the two null stages — an iterable of :class:`NullColumnResult`.
        Both §8.2 columns are required, over the same set of windows. A threshold calibrated
        against the leader null alone would be locked without the follower's null ever having
        constrained it, and §7.2 then gates a column whose false-positive rate was never measured.
    :param candidates: the candidate thresholds, in the units of ``WindowScore.mean_advantage``.
        Order and duplicates do not matter. Floats are refused by ``contracts.numeric.calc`` inside
        the calibration module, on sight.
    :returns: ``runner(context) -> CalibratedThreshold``.

    **How one number comes out of several distributions.** §8.3 defines the Null Pass Rate for *a*
    null distribution, and §7 applies *one* Final Mean Threshold to every window and both columns.
    ``calibrate_threshold_detail`` answers the per-distribution question; this runner takes the
    largest of those answers. That is not a policy invented here — a run passes the gate only if
    ``mean_advantage >= threshold``, so raising the threshold can only remove passing runs, so each
    distribution's qualifying candidates are upward-closed on the grid. The maximum of the
    per-distribution minima is therefore *the smallest single candidate at which no distribution
    exceeds 5%*, which is §8.3's sentence read over the whole experiment rather than over one
    column of one window. The per-distribution reports are carried so a reviewer can check that
    reading rather than take it.

    **A grid that runs out is a crash, not a soft result.** ``ThresholdNotCalibrated`` propagates.
    This is the one place in this module where a disappointing-looking outcome is deliberately not
    carried as a status: completing this stage *is* the lock — it is what advances governance to
    ``THRESHOLD_LOCKED`` and unblocks the main test — so a stage that completed while holding no
    justified threshold would authorise the main test against nothing. §8.4 makes the lock step 5 of
    a binding order. The answer to an exhausted grid is a wider grid, not a completed stage.

    **What this runner does not lock.** Governance sequences the stages: ``threshold.calibrate``
    requires ``NULL_COMPLETE`` and advances ``THRESHOLD_LOCKED``, ``main_test`` requires
    ``THRESHOLD_LOCKED``, and the transition check refuses a re-run ("already in this state") and a
    backwards move ("the order is one-way"), so calibration cannot run after the main test and the
    main test cannot run before calibration. What governance does not do is carry a value:
    ``StageResult.to_dict`` omits it on purpose, so the number ``main_test`` is run against is
    whatever the integrator hands it. The *order* is enforced; the *identity of the number* is not.
    """
    ordered = _ordered_nulls(nulls)
    candidates = tuple(candidates)
    if not candidates:
        raise ValueError(
            "no candidate thresholds were supplied; §8.3 chooses the smallest candidate holding "
            "the null pass rate at or below 5%, and there is nothing to choose from"
        )

    def runner(context):
        """Calibrate one threshold against every null distribution the two stages produced.

        Draws no seeds — calibration is a recount of runs that already happened — so the context is
        read only to confirm the runner was wired to the stage it was built for.
        """
        _require_stage(context, CALIBRATE_STAGE)
        reports = []
        for distribution in ordered:
            try:
                reports.append(calibrate_threshold_detail(distribution, candidates))
            except ThresholdNotCalibrated as exc:
                # Re-raised, never absorbed. The original message names the best candidate and its
                # rate but not which distribution produced them, and with two columns times four
                # windows on the grid that is the first thing a reader needs.
                raise ThresholdNotCalibrated(
                    "column {!r} window {} has no calibrated threshold on this grid: {}".format(
                        distribution.column, distribution.window, exc
                    )
                ) from exc

        # ``max`` compares Decimals, which is exact and consults no context; no arithmetic happens
        # here. On a tie it returns the first, and the reports are in (column, window) order — so
        # the *threshold* is identical either way and only which report is named as binding moves.
        binding = max(reports, key=lambda report: report.threshold)
        return CalibratedThreshold(
            stage=CALIBRATE_STAGE,
            threshold=binding.threshold,
            reports=tuple(reports),
            binding=binding,
            # True when the locked threshold is the smallest candidate offered. That is a fact
            # about the grid rather than about the null: the grid may simply not reach low enough,
            # and "the smallest threshold at which" would then mean the smallest one offered.
            at_grid_floor=binding.at_grid_floor,
        )

    return runner


# -- input validation ------------------------------------------------------------
#
# All of it runs when the factory is called — at wiring time, before governance has opened a run
# record. A wiring defect that raised inside the runner instead would leave a run record for a
# stage that could never have run, and the point of writing the record first is that it is evidence
# of something that was genuinely about to happen.


def _require_stage(context, stage):
    """Confirm the runner was wired to the stage it was built for.

    Cheap, and it closes a mis-wiring that nothing else would catch: hand the leader runner to
    ``phase0.execute_stage("null.follower", ...)`` and the run record says ``null.follower`` while
    the value inside it is the leader column's null. Both objects look correct on their own.
    """
    actual = getattr(context, "stage", None)
    if actual != stage:
        raise ValueError(
            "this runner builds {!r} and was called with a context for {!r}. The run record and "
            "the value it records would then disagree about which stage ran.".format(stage, actual)
        )
    if not callable(getattr(context, "child_seed", None)):
        raise TypeError(
            "the stage context must provide child_seed(purpose, index); every draw in this stage "
            "is derived from the run's master seed and commit, and there is no other source"
        )
    return context


def _require_run_count(n_runs):
    if not isinstance(n_runs, int) or isinstance(n_runs, bool) or n_runs < 1:
        raise ValueError("n_runs must be a positive int, got {!r}".format(n_runs))
    return n_runs


def _ordered_window_inputs(windows, column):
    """Validate the per-window inputs and put them in window order."""
    inputs = tuple(windows)
    if not inputs:
        raise ValueError(
            "no windows were supplied for the {} null; a null over no windows is not a smaller "
            "null, it is no null".format(column)
        )
    seen = {}
    for position, item in enumerate(inputs):
        if not isinstance(item, NullWindowInputs):
            raise TypeError(
                "windows must contain NullWindowInputs, got {} at position {}".format(
                    type(item).__name__, position
                )
            )
        if item.window in seen:
            raise ValueError(
                "windows[{}] and windows[{}] both describe window {}. One window is one null "
                "distribution for one column: two would be two answers to the question §7.1 asks "
                "once, and nothing is permitted to choose between them.".format(
                    seen[item.window], position, item.window
                )
            )
        seen[item.window] = position
    return tuple(sorted(inputs, key=lambda item: item.window))


def _ordered_nulls(nulls):
    """Validate the two columns' null results and flatten them to distributions in a fixed order.

    The order is ``NULL_COLUMNS`` then ascending window, so the calibration reports come out the
    same way whatever order the two stage values were handed over in.
    """
    results = tuple(nulls)
    by_column = {}
    for position, result in enumerate(results):
        if not isinstance(result, NullColumnResult):
            raise TypeError(
                "threshold.calibrate consumes the null stages' own values — NullColumnResult — "
                "got {} at position {}. A contracts.PermutationResult cannot be calibrated from: "
                "it carries the mean advantages alone, and §8.3's Null Pass Rate is the share of "
                "runs passing the full three-condition gate.".format(
                    type(result).__name__, position
                )
            )
        if result.column in by_column:
            raise ValueError(
                "two null results for column {!r}; the column has one null distribution per "
                "window and nothing may choose between two of them".format(result.column)
            )
        by_column[result.column] = result

    missing = [c for c in NULL_COLUMNS if c not in by_column]
    if missing:
        raise ValueError(
            "calibration needs both §8.2 null distributions and is missing {}. One Final Mean "
            "Threshold gates both columns, so a threshold calibrated against {} alone is locked "
            "without the other column's false-positive rate ever having constrained it.".format(
                ", ".join(missing), ", ".join(sorted(by_column)) or "nothing"
            )
        )
    unexpected = [c for c in by_column if c not in NULL_COLUMNS]
    if unexpected:
        raise ValueError(
            "unknown null column(s) {}; §8.2 builds exactly {}".format(
                ", ".join(sorted(unexpected)), " and ".join(NULL_COLUMNS)
            )
        )

    windows = {column: set(result.windows) for column, result in by_column.items()}
    reference = windows[NULL_COLUMNS[0]]
    for column in NULL_COLUMNS[1:]:
        if windows[column] != reference:
            raise ValueError(
                "the two nulls cover different windows — {} covers {}, {} covers {}. One threshold "
                "is locked from both, so an asymmetric pair would justify it partly on evidence "
                "one column never supplied.".format(
                    NULL_COLUMNS[0], sorted(reference), column, sorted(windows[column])
                )
            )

    ordered = []
    for column in NULL_COLUMNS:
        result = by_column[column]
        ordered.extend(sorted(result.distributions, key=lambda d: d.window))
    return tuple(ordered)
