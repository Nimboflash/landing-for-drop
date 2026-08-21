"""The within-matched-set permutation null.

Pre-registration §8.2 · §7.3.

    For each matched set — 1 selected wallet + its 5 primary controls:
        randomly reassign which member carries the "selected" label
    Recompute the full gate on the relabelled population

The permutation preserves each set's covariate profile *exactly* — the same six wallets are in the
same set before and after, only the label moves — so the null asks the sharp question: given groups
already balanced on all ten §6.6 dimensions, is the label assignment informative at all?

A resampling null cannot ask that. It asks whether *some* basket of this size could do as well,
which is a blunter question and one that has already failed in the field: the June 2026 placebo
study found apparently-skilled cohorts returning +132.3% while activity-matched placebos returned
+216.3%. A random-basket null passes that; permuting within matched sets does not, because the
placebo cohorts are *in* the sets.

Two rules this module will not let a caller break:

* **the null gate is the full three-condition gate.** ``statistic_fn`` must return a
  :class:`contracts.WindowScore`, whose ``passes`` is all three §7.1 conditions and can never be
  satisfied by ``INDETERMINATE``. A null scored on the mean alone would place its 95th percentile
  in a different experiment from the one the gate runs, and §8.2 says in as many words that the
  calibration would then be void.
* **the observed statistic comes out of the same machinery.** It is the identity labelling — run
  ``-1``, so to speak — passed through the very same ``statistic_fn``. Computing the observed
  value by another path is how a percentile ends up compared against something it does not
  describe.

Seeds are injected, never derived here. ``seed_fn(purpose, index)`` is the caller's derivation
(§9.6's master seed plus commit), with ``purpose = "null.<column>.window<N>"`` and
``index = 0..n_runs-1``. This module imports nothing but ``contracts``.
"""

import hashlib
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Tuple

from contracts import (
    CALCULATION_CONTEXT,
    ContractError,
    MatchedSet,
    PermutationResult,
    WindowScore,
    calc,
    divide,
    require_finite,
)
from phase0.parameters import PARAMETERS

ZERO = Decimal("0")
ONE = Decimal("1")

#: §8.2. One thousand runs per window per column. Exposed as a constant and defaulted to nowhere:
#: ``n_runs`` is an argument so tests can run twenty, and the pre-registered figure is this one.
#: Read from the ticket-11 frozen set.
NULL_RUNS = PARAMETERS.value("null.runs_per_window_per_column")

#: §8.2 builds exactly two null distributions, and ``WindowScore.column`` uses these two strings.
#: A third value would produce a distribution no gate could be matched to.
NULL_COLUMNS = ("leader", "follower_adjusted")

#: §7.3 / §8.3, from the ticket-11 frozen set. These two are what "statistically significant" and
#: "calibrated" mean, and the calibration in ``matching_null.calibration`` is measured against
#: them — a local copy would let the bar move without the frozen set recording that it had.
SIGNIFICANCE_PERCENTILE = PARAMETERS.value("gate.significance.null_percentile")
NULL_PASS_RATE_TARGET = PARAMETERS.value("null.pass_rate_target")


class DegenerateNull(ContractError):
    """The seed derivation produced repeats, so the runs are not independent draws.

    A collision among 1,000 draws from a 256-bit derivation has probability of order 1e-71. In
    practice this means ``seed_fn`` ignores one of its arguments — a constant seed makes all 1,000
    runs identical, the distribution collapses to a point, and the 95th percentile becomes that
    point. Nothing else about the run looks wrong.
    """


def null_purpose(column, window):
    """``"null.<column>.window<N>"`` — the §8.2 purpose string, built in one place."""
    if column not in NULL_COLUMNS:
        raise ValueError(
            "column must be one of {}, got {!r}. §8.2 builds a Leader and a Follower-Adjusted "
            "null and nothing else; a third column is a distribution with no gate to "
            "serve.".format(", ".join(NULL_COLUMNS), column)
        )
    if not isinstance(window, int) or isinstance(window, bool) or window < 1:
        raise ValueError("window must be a positive int, got {!r}".format(window))
    return "null.{}.window{}".format(column, window)


def _uniform_index(seed, set_index, k):
    """A uniform draw from ``range(k)``, by rejection sampling over a SHA-256 stream.

    Exactly uniform, not almost: the modulo of a 256-bit hash by 6 is biased by about 5e-77, which
    could not matter — but "biased by an amount I have argued is small" is a sentence a
    pre-registered null should not need, and rejection removes it for ten lines of code. The
    rejection branch is taken with probability under 1e-76, so the loop is a formality.

    Derived by hashing rather than by seeding ``random``: the stdlib generator's outputs are not
    guaranteed stable across Python versions, and a null distribution that changes when the
    interpreter is upgraded is not reproducible from the freeze manifest.
    """
    if k < 1:
        raise ValueError("cannot draw from an empty set")
    span = 1 << 256
    limit = (span // k) * k
    counter = 0
    while True:
        digest = hashlib.sha256(
            "{}|{}|{}".format(seed, set_index, counter).encode("utf-8")
        ).digest()
        value = int.from_bytes(digest, "big")
        if value < limit:
            return value % k
        counter += 1


@dataclass(frozen=True)
class Relabelling:
    """One run's relabelled population, and the draw that produced it.

    ``sets`` is the same wallets in the same sets — only which member wears the "selected" label
    has moved. ``chosen_positions`` records the draw per set, so a reviewer can replay the run from
    the seed alone without re-running the statistic.
    """

    run_index: int
    seed: int
    sets: Tuple[MatchedSet, ...]
    chosen_positions: Tuple[int, ...]

    def members(self):
        """The multiset of wallets, flattened. Invariant under relabelling — that is the test."""
        return tuple(w for s in self.sets for w in s.members)


def relabel(sets, seed, run_index):
    """Draw a new "selected" member uniformly within each matched set.

    The draw is over ``selected + primary_controls`` only. Robustness controls ride along
    unchanged: §6.6 says they cannot change the gate, and the gate is what is being recomputed.

    This primitive takes ``sets`` in the order given and draws for position ``i`` from
    ``(seed, i, len(members))`` — so calling it directly with the same sets in two orders gives
    two different relabellings. It is not the place that fixes that:
    :func:`permutation_null_detail`, the entry point, orders the sets by selected wallet before it
    calls here, and that is the only path the pipeline uses.
    """
    relabelled = []
    positions = []
    for set_index, matched in enumerate(sets):
        members = matched.members
        position = _uniform_index(seed, set_index, len(members))
        positions.append(position)
        new_selected = members[position]
        relabelled.append(MatchedSet(
            selected=new_selected,
            primary_controls=tuple(w for i, w in enumerate(members) if i != position),
            robustness_controls=matched.robustness_controls,
        ))
    return Relabelling(
        run_index=run_index,
        seed=seed,
        sets=tuple(relabelled),
        chosen_positions=tuple(positions),
    )


@dataclass(frozen=True)
class NullRun:
    """One permutation run: its seed, its draw, and the full window score it produced."""

    index: int
    seed: int
    chosen_positions: Tuple[int, ...]
    score: WindowScore

    @property
    def statistic(self):
        return self.score.mean_advantage

    def passed(self, threshold):
        """The full three-condition §7.1 gate. ``INDETERMINATE`` can never satisfy it."""
        return self.score.passes(threshold)


@dataclass(frozen=True)
class NullDistribution:
    """The rich null. :meth:`to_contract` reduces it to :class:`contracts.PermutationResult`.

    The seam type carries the statistics; this carries the *scores*. That difference is what makes
    calibration possible at all: §8.3 recomputes the pass rate at each candidate threshold, and
    the pass rate is a three-condition question. From a bare list of mean advantages you can only
    answer a one-condition version of it, and §8.2 forbids exactly that substitution.
    """

    column: str
    window: int
    purpose: str
    observed: WindowScore
    runs: Tuple[NullRun, ...]
    n_runs: int
    reference_threshold: Decimal

    def __post_init__(self):
        object.__setattr__(self, "runs", tuple(self.runs))
        if len(self.runs) != self.n_runs:
            raise ValueError(
                "n_runs is {} but {} runs were recorded".format(self.n_runs, len(self.runs))
            )
        if self.n_runs < 1:
            raise ValueError("a null distribution needs at least one run")

    @property
    def statistics(self):
        return tuple(run.statistic for run in self.runs)

    @property
    def observed_statistic(self):
        return self.observed.mean_advantage

    def pass_rate(self, threshold):
        """§8.3's Null Pass Rate at one candidate threshold, on the full gate."""
        threshold = require_finite(threshold, "threshold")
        passing = sum(1 for run in self.runs if run.passed(threshold))
        return divide(passing, self.n_runs)

    @property
    def percentile_95(self):
        return percentile_nearest_rank(self.statistics, SIGNIFICANCE_PERCENTILE)

    @property
    def empirical_p(self):
        return empirical_p_value(self.observed_statistic, self.statistics)

    def to_contract(self):
        return PermutationResult(
            column=self.column,
            observed_statistic=self.observed_statistic,
            null_statistics=self.statistics,
            n_runs=self.n_runs,
            percentile_95=self.percentile_95,
            empirical_p=self.empirical_p,
            null_pass_rate=self.pass_rate(self.reference_threshold),
        )


def percentile_nearest_rank(values, quantile):
    """The nearest-rank percentile: the smallest value at or above which the quantile sits.

    ``index = ceil(q * n) - 1`` on the ascending sort. Pinned because it is a genuine degree of
    freedom — nearest-rank and the several linear-interpolation conventions disagree, and at
    n = 1,000 the 95th percentile is the 950th value under this rule and something between the
    950th and 951st under others. Two implementations that pick differently produce two different
    gates and no way to tell which one the pre-registration meant.

    Nearest-rank also has the property the gate wants: the reported percentile is always a value
    the null actually produced, never an interpolation between two runs that never happened.

    ``sorted`` is stable, so among values that are numerically equal but differently scaled —
    ``Decimal("1.0")`` and ``Decimal("1.00")`` — the one returned is whichever came first in
    ``values``. Measured: that is the only thing about this function the caller's ordering can
    move, it is invisible after ``contracts.serialization.canonicalise`` normalises the exponent,
    and on the path that matters it cannot arise at all, since ``NullDistribution.statistics``
    comes out of ``runs`` in run-index order.
    """
    ordered = sorted(calc(v) for v in values)
    if not ordered:
        raise ValueError("the percentile of an empty distribution is undefined")
    quantile = require_finite(quantile, "quantile")
    if not (ZERO < quantile <= ONE):
        raise ValueError("quantile must lie in (0, 1], got {}".format(quantile))
    n = len(ordered)
    with localcontext(CALCULATION_CONTEXT):
        position = +(quantile * n)
    index = int(position)
    if position != index:      # ceil, on a positive Decimal
        index += 1
    return ordered[max(0, index - 1)]


def empirical_p_value(observed, statistics):
    """``(1 + #{null >= observed}) / (1 + n)``.

    The ``+1`` on both sides is the standard permutation correction. Without it a distribution in
    which no run beat the observed value reports ``p = 0`` — a claim 1,000 runs cannot support, and
    one that would sail through the ``p <= 0.05`` gate on the strength of an arithmetic artefact.
    With it the smallest reportable p-value at 1,000 runs is 1/1001, which is what the evidence
    actually bounds.

    ``>=`` and not ``>``: a run that ties the observed result is evidence against, not for.
    """
    observed = require_finite(observed, "observed")
    ordered = [calc(v) for v in statistics]
    if not ordered:
        raise ValueError("an empirical p-value needs a distribution")
    at_least = sum(1 for v in ordered if v >= observed)
    return divide(at_least + 1, len(ordered) + 1)


def permutation_null(sets, statistic_fn, n_runs, seed_fn, column, window,
                     reference_threshold=None):
    """§8.2's null for one column and one window. Returns the seam type.

    See :func:`permutation_null_detail` for the full result, which is what
    :func:`~matching_null.calibration.calibrate_threshold` needs.
    """
    return permutation_null_detail(
        sets, statistic_fn, n_runs, seed_fn, column, window,
        reference_threshold=reference_threshold,
    ).to_contract()


def permutation_null_detail(sets, statistic_fn, n_runs, seed_fn, column, window,
                            reference_threshold=None):
    """Run the permutation null and keep every run's full window score.

    :param sets: the matched sets from §6.6. Permuted within, never across. Two sets naming the
        same selected wallet — in any spelling — are **refused**, and the sets are put into
        selected-wallet order before anything is drawn, because ``_uniform_index`` keys the draw
        on a set's position in the list. Both are the same rule §6.6 applies to the universe:
        one wallet is one entry, and the result is a function of the data, not of the caller's
        ordering. Neither changes anything on the pipeline's own path — ``build_matched_sets``
        already emits distinct sets in address order.
    :param statistic_fn: ``(relabelled_sets) -> contracts.WindowScore``. It must recompute the
        whole gate — mean, median and edge origin — on the relabelled population. Its ``column``
        and ``window`` are checked against this call's, because a score belonging to another
        window would land in this distribution without a murmur.
    :param n_runs: §8.2 pre-registers :data:`NULL_RUNS`. Smaller values are for tests and
        diagnostics and are recorded as such in the result.
    :param seed_fn: ``(purpose, index) -> int``. The caller's §9.6 derivation from the master seed
        and the commit. Taken as an argument so this module derives no seeds of its own and
        imports nothing outside ``contracts``.
    :param reference_threshold: the threshold ``null_pass_rate`` is reported at. ``None`` — the
        default — uses the **observed mean advantage**, which needs no pre-registered constant and
        cannot be in the wrong units, since it is drawn from the same statistic. §8.3's calibration
        rates are recomputed per candidate by ``calibrate_threshold`` and do not come from here.
    """
    purpose = null_purpose(column, window)
    matched_sets = tuple(sets)
    if not matched_sets:
        raise ValueError("there is nothing to permute: no matched sets were supplied")
    seen = {}
    for position, matched in enumerate(matched_sets):
        if not isinstance(matched, MatchedSet):
            raise TypeError(
                "sets must contain MatchedSet, got {}".format(type(matched).__name__)
            )
        if len(matched.members) < 2:
            raise ValueError(
                "matched set for {} has no controls to permute with; relabelling it is the "
                "identity and would contribute a constant to the null".format(matched.selected)
            )
        if not isinstance(matched.selected, str):
            raise TypeError(
                "sets[{}].selected must be a wallet address string, got {}. Two matched sets are "
                "the same set when they name the same address, and that comparison has to be "
                "defined.".format(position, type(matched.selected).__name__)
            )
        # Case-folded, because that is what a wallet address is throughout this package —
        # ``WalletFeatures`` lowercases and ``matching._distinct_lower`` refuses two spellings of
        # one universe member on exactly this ground. ``MatchedSet`` is seam-frozen and does no
        # folding of its own, so the identity rule is applied here rather than assumed.
        key = matched.selected.lower()
        if key in seen:
            raise ValueError(
                "sets[{}] and sets[{}] both name {} as the selected wallet. One wallet is one "
                "matched set: a duplicate is relabelled twice and enters the null twice under one "
                "label — the refusal §6.6 already makes on the selected list itself. Measured on "
                "the two-set null in tests/hand_computed/test_matching_null_identity.py, "
                "admitting the duplicate moved the published null pass rate from 0.9 to "
                "0.75.".format(seen[key], position, key)
            )
        seen[key] = position

    # Address order throughout, never the caller's — the rule matching.py applies to the universe,
    # for the same reason and with a sharper consequence. ``_uniform_index`` keys the draw on the
    # set's *position*, so handing the same sets over in a different order gives wallet A the draw
    # that belonged to wallet B. On the two-set null in tests/hand_computed/
    # test_matching_null_identity.py that moves the published null pass rate from 0.9 to 0.8 —
    # a §8.3 calibration input, changed by nothing but the order of a list.
    # ``build_matched_sets`` already emits sets in selected-wallet order, so this is the identity
    # on the pipeline's own path; it is here so no other caller can be the exception.
    matched_sets = tuple(sorted(matched_sets, key=lambda m: m.selected.lower()))
    if not isinstance(n_runs, int) or isinstance(n_runs, bool) or n_runs < 1:
        raise ValueError("n_runs must be a positive int, got {!r}".format(n_runs))
    if not callable(statistic_fn):
        raise TypeError("statistic_fn must be callable")
    if not callable(seed_fn):
        raise TypeError("seed_fn must be callable")

    def score(labelled, what):
        result = statistic_fn(labelled)
        if not isinstance(result, WindowScore):
            raise TypeError(
                "statistic_fn returned {} for {}; it must return a contracts.WindowScore. The "
                "null gate is the full three-condition §7.1 gate, and a bare number cannot carry "
                "the median or the edge-origin status it needs.".format(
                    type(result).__name__, what
                )
            )
        if result.column != column or result.window != window:
            raise ValueError(
                "statistic_fn returned a score for column {!r} window {} while building the null "
                "for column {!r} window {}; a score from another experiment would enter this "
                "distribution unremarked".format(
                    result.column, result.window, column, window
                )
            )
        return result

    # The observed value is the identity labelling put through the same function as every
    # permutation. A separately computed observed statistic is how a percentile ends up being
    # compared against a number it does not describe.
    observed = score(matched_sets, "the observed labelling")

    seeds = []
    runs = []
    for index in range(n_runs):
        seed = seed_fn(purpose, index)
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise TypeError(
                "seed_fn must return an int, got {} at index {}".format(
                    type(seed).__name__, index
                )
            )
        seeds.append(seed)
        relabelling = relabel(matched_sets, seed, index)
        runs.append(NullRun(
            index=index,
            seed=seed,
            chosen_positions=relabelling.chosen_positions,
            score=score(relabelling.sets, "run {}".format(index)),
        ))

    if len(set(seeds)) != len(seeds):
        raise DegenerateNull(
            "seed_fn produced {} distinct seeds across {} runs for purpose {!r}. A 256-bit "
            "derivation does not collide at this scale, so this means the derivation is ignoring "
            "its index — and identical seeds make identical runs, collapsing the null onto a "
            "single point that the 95th percentile then reports as a distribution.".format(
                len(set(seeds)), len(seeds), purpose
            )
        )

    if reference_threshold is None:
        reference = observed.mean_advantage
    else:
        reference = require_finite(reference_threshold, "reference_threshold")

    return NullDistribution(
        column=column,
        window=window,
        purpose=purpose,
        observed=observed,
        runs=tuple(runs),
        n_runs=n_runs,
        reference_threshold=reference,
    )
