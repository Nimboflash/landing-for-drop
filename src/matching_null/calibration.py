"""Threshold calibration against the permutation null.

Pre-registration §8.3::

    Null Pass Rate        = null runs passing the full gate / total null runs
    Final Mean Threshold  = the smallest threshold at which Null Pass Rate <= 5%

Worked example from §8.3, reproduced in the hand-computed tests::

    15pp threshold  ->  18% null pass rate
    20pp threshold  ->   9% null pass rate
    24pp threshold  ->   4% null pass rate
    -> lock the final threshold at 24pp

"Passing" is the **full three-condition §7.1 gate**, not the mean advantage alone. §8.2 is explicit
about why: a null scored on two conditions while the real test uses three puts the 95th percentile
in a different experiment and voids the calibration. That is why this module takes a
:class:`~matching_null.permutation.NullDistribution` and refuses a bare
:class:`contracts.PermutationResult` — the seam type carries the mean advantages and nothing else,
so calibrating from one is only possible by quietly dropping the other two conditions.

Units are the caller's. ``mean_advantage`` might be percentage points or a ratio; the candidates
must be in whichever it is. Nothing here can tell the difference, and a guess dressed up as a
check would be worse than the plain statement: **supply candidates in the same units as
``WindowScore.mean_advantage``.**
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple

from contracts import ContractError, PermutationResult, calc, require_finite

from .permutation import NULL_PASS_RATE_TARGET, NullDistribution


class ThresholdNotCalibrated(ContractError):
    """No candidate on the grid holds the null pass rate at or below 5%.

    Not a negative finding, and not a number to be softened. §8.4 makes threshold calibration step
    4 of a binding order, before the main test is permitted to run at all — so "the grid ran out"
    means the experiment has no locked threshold yet, not that it failed. Returning the largest
    candidate would supply a threshold the null never justified, and the main test would then run
    against it.
    """


@dataclass(frozen=True)
class CandidateRate:
    """One candidate threshold and what the null did at it."""

    threshold: Decimal
    passing_runs: int
    n_runs: int
    pass_rate: Decimal

    @property
    def qualifies(self):
        return self.pass_rate <= NULL_PASS_RATE_TARGET


@dataclass(frozen=True)
class CalibrationReport:
    """The rich calibration. :func:`calibrate_threshold` returns only ``threshold``.

    ``at_grid_floor`` is worth carrying. If the smallest candidate already holds the null at 5%,
    the grid may simply not reach low enough, and §8.3's "smallest threshold at which" then refers
    to the smallest one *offered* rather than the smallest one that works. That is a fact about
    the grid, not about the null, and it belongs in the report rather than in a raised error.
    """

    column: str
    window: int
    n_runs: int
    target: Decimal
    rates: Tuple[CandidateRate, ...]
    threshold: Decimal
    at_grid_floor: bool


def _candidate_grid(candidates):
    values = []
    for candidate in candidates:
        # calc() refuses float on sight, which is the check that matters: a 0.05 threshold typed
        # as a float has already lost precision before it can be compared to anything.
        values.append(require_finite(calc(candidate), "threshold candidate"))
    if not values:
        raise ValueError("no candidate thresholds were supplied")
    # Deduplicated on numeric value, so Decimal("15") and Decimal("15.0") are one candidate.
    # That collapse is intended — a threshold *is* its numeric value, and the two spellings do not
    # name two candidates the way "0xC1" and "0xc1" name two feature records.
    #
    # What does survive on iteration order is the winner's *exponent*: `setdefault` keeps the
    # first spelling seen, so `[D("15"), D("15.0")]` locks `Decimal("15")` and the reverse order
    # locks `Decimal("15.0")`. Measured, that residue reaches nothing published — the two compare
    # equal at every use here, and `contracts.serialization.canonicalise` normalises the exponent,
    # so both render `"15"` and hash identically. It is visible only in a `repr` of the report or
    # in the text of a `ThresholdNotCalibrated` message. Stated rather than normalised away,
    # because a reader checking this line for the collapse defect should be told where it stops.
    unique = {}
    for value in values:
        unique.setdefault(value, value)
    return sorted(unique.values())


def calibrate_threshold(null, candidates):
    """§8.3. The smallest candidate at which the null pass rate is at or below 5%.

    :param null: a :class:`~matching_null.permutation.NullDistribution`. A
        :class:`contracts.PermutationResult` is refused — see the module docstring.
    :param candidates: thresholds, in the units of ``WindowScore.mean_advantage``. Order does not
        matter; duplicates collapse.
    :raises ThresholdNotCalibrated: when no candidate qualifies.
    """
    return calibrate_threshold_detail(null, candidates).threshold


def calibrate_threshold_detail(null, candidates):
    """As :func:`calibrate_threshold`, keeping the pass rate at every candidate."""
    if isinstance(null, PermutationResult):
        raise TypeError(
            "calibrate_threshold needs a NullDistribution, not a PermutationResult. The seam type "
            "carries the null's mean advantages only, and §8.3's Null Pass Rate is the share of "
            "runs passing the full three-condition §7.1 gate — median and edge origin included. "
            "Calibrating from the means alone would silently substitute a one-condition gate, "
            "which §8.2 rules out because the resulting percentile describes a different "
            "experiment."
        )
    if not isinstance(null, NullDistribution):
        raise TypeError(
            "calibrate_threshold needs a NullDistribution, got {}".format(type(null).__name__)
        )

    grid = _candidate_grid(candidates)
    rates = []
    for threshold in grid:
        passing = sum(1 for run in null.runs if run.passed(threshold))
        rates.append(CandidateRate(
            threshold=threshold,
            passing_runs=passing,
            n_runs=null.n_runs,
            pass_rate=null.pass_rate(threshold),
        ))

    qualifying = [rate for rate in rates if rate.qualifies]
    if not qualifying:
        best = min(rates, key=lambda r: r.pass_rate)
        raise ThresholdNotCalibrated(
            "no candidate holds the null pass rate at or below {}; the best of {} candidate(s) "
            "was {} at a rate of {}. §8.4 requires the threshold to be locked before the main "
            "test runs, so the answer is a wider grid, not the largest candidate on this "
            "one.".format(NULL_PASS_RATE_TARGET, len(rates), best.threshold, best.pass_rate)
        )

    chosen = qualifying[0]
    return CalibrationReport(
        column=null.column,
        window=null.window,
        n_runs=null.n_runs,
        target=NULL_PASS_RATE_TARGET,
        rates=tuple(rates),
        threshold=chosen.threshold,
        at_grid_floor=chosen.threshold == grid[0],
    )
