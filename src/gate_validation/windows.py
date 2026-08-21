"""Turning window scores into a count, and capital levels into a feasibility verdict.

§7 states the rule in one line — *a window is PASSED only if both gates pass, and the project
proceeds only if at least 3 of 4 windows pass* — and every subtlety in this module is about the
ways that line can be satisfied without being true.

**The pass rule itself is not reimplemented here.** :meth:`contracts.WindowScore.passes` owns the
three §7.1 conditions, and this module calls it. Writing a second copy of the rule in the arbiter
would create exactly the situation the arbiter exists to prevent: two implementations of one
condition, disagreeing silently, with the one that decides the gate being whichever was consulted
last. What this module adds is the *reasons* — restated from the same stored fields, never
recomputed into a second verdict — so a reviewer can see which condition bound.

Three refusals, each of which would otherwise be a way to pass:

``DiagnosticInputRefused``
    Also covers a result whose ``window`` is not an ``int``: the results are *grouped* by that
    field, so it is an identity key, and ``1``, ``True`` and ``1.0`` are one key to Python.
    §10 permits a long list of diagnostics and then says: only ``buy_quality`` decides the gate.
    "Reporting a diagnostic and then using it to overturn a gate result is the failure mode this
    entire document exists to prevent." So the engine does not filter diagnostics out — it refuses
    an artifact that contains one, which is the difference between a rule and a habit.

``ConflictingResults``
    Two answers to the same (window, column) means something must choose between them, and §9.7 is
    explicit that nothing may. The same refusal covers two entries naming one capital level, for
    the same reason one key up: see :func:`_level_keyed`.

A window missing a required column
    Fails. It has one result, not two, and "both gates passed" is not a claim it can support.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional, Tuple

from contracts import (
    ContractError,
    EdgeOriginStatus,
    WindowScore,
    calc,
    require_finite,
)

#: §7.1 is computed on the leader; §7.2 on the follower-adjusted column at design capital. The
#: names are the seam's, not this module's — ``WindowScore.column`` carries them.
LEADER_COLUMN = "leader"
FOLLOWER_COLUMN = "follower_adjusted"
REQUIRED_COLUMNS = (LEADER_COLUMN, FOLLOWER_COLUMN)

#: §6.3 fixes four walk-forward windows and §7.4 requires at least three. Both are part of the
#: pre-registration, so both are constants here rather than arguments — a "3 of 2" gate would be a
#: different experiment wearing the same name.
EXPECTED_WINDOWS = 4
MIN_PASSING_WINDOWS = 3

#: §3.1. Five capital levels are simulated; these two are ``design_capital`` and these two gate.
DESIGN_CAPITAL_LEVELS = (Decimal("1500000"), Decimal("2000000"))


class DiagnosticInputRefused(ContractError):
    """A column that is not a gating column reached the gate engine."""


class InconsistentEdgeOrigin(ContractError):
    """A window score's edge-origin status contradicts its own first-hour share.

    Not a second implementation of §7.1 — see this module's docstring, which is right that an
    arbiter growing its own copy of the gate rule is the failure it exists to prevent. This is a
    *consistency* check on two fields the caller supplied together, and it produces no verdict of
    its own: either the pair is possible and nothing changes, or it is impossible and this raises.

    It exists because the audit of ticket 33 found the arbiter certifying a condition it never
    examined. §7.1's third condition arrives as ``edge_origin_status``, an enum computed by
    ``scoring``, and ``first_hour_edge_share`` arrives beside it — and nothing compared them. A
    scoring defect stamping ``VALID`` on a share of 0.95 produced a GO that no test in this package
    could distinguish from a real one, because the number that would have exposed it was sitting
    unread in the same object.
    """


class ConflictingResults(ContractError):
    """Two results exist for the same question, and nothing is permitted to choose between them."""


# -- per-column and per-window verdicts ------------------------------------------


@dataclass(frozen=True)
class ColumnVerdict:
    """One column's outcome in one window, with the stored fields that produced it.

    The fields are copied out rather than referenced so the verdict serialises to something a
    reviewer can check without the original score object — which is the point of an artifact.
    """

    window: int
    column: str
    passed: bool
    reasons: Tuple[str, ...]
    mean_advantage: Decimal
    median_advantage: Decimal
    first_hour_edge_share: Optional[Decimal]
    edge_origin_status: EdgeOriginStatus

    def __post_init__(self):
        object.__setattr__(self, "reasons", tuple(self.reasons))
        if self.passed and self.reasons:
            raise ValueError(
                "window {} column {} is recorded as passed while carrying failure reasons {}; a "
                "verdict and its explanation cannot disagree".format(
                    self.window, self.column, self.reasons)
            )
        if not self.passed and not self.reasons:
            raise ValueError(
                "window {} column {} failed without saying why; an unexplained failure cannot be "
                "reviewed and cannot be fixed".format(self.window, self.column)
            )


@dataclass(frozen=True)
class WindowVerdict:
    """One window. Passes only when every required column is present and every one of them passes."""

    window: int
    passed: bool
    columns: Tuple[ColumnVerdict, ...]
    missing_columns: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "missing_columns", tuple(self.missing_columns))

    def column_for(self, column):
        for verdict in self.columns:
            if verdict.column == column:
                return verdict
        raise KeyError("window {} carries no {} column".format(self.window, column))

    def passed_column(self, column):
        """Whether one named column passed. A column that is absent did not pass."""
        for verdict in self.columns:
            if verdict.column == column:
                return verdict.passed
        return False

    @property
    def reasons(self):
        out = []
        for column in self.missing_columns:
            out.append("{} column is absent, so both gates cannot have passed".format(column))
        for verdict in self.columns:
            out.extend("{}: {}".format(verdict.column, reason) for reason in verdict.reasons)
        return tuple(out)


@dataclass(frozen=True)
class WindowEvaluation:
    """Every window's verdict at one threshold. The threshold is carried, never assumed.

    Carrying it matters because §8.4 locks the threshold before the main test runs, and the
    decision engine compares this value against the locked one. An evaluation that did not record
    which threshold produced it could not be checked against the lock at all.
    """

    threshold: Decimal
    verdicts: Tuple[WindowVerdict, ...]

    def __post_init__(self):
        object.__setattr__(self, "verdicts", tuple(self.verdicts))

    @property
    def total(self):
        return len(self.verdicts)

    @property
    def passed(self):
        return sum(1 for v in self.verdicts if v.passed)

    def passed_for(self, column):
        """How many windows that one column passed — Gate 1 alone, or Gate 2 alone."""
        return sum(1 for v in self.verdicts if v.passed_column(column))

    def verdict_for(self, window):
        for verdict in self.verdicts:
            if verdict.window == window:
                return verdict
        raise KeyError("no verdict for window {}".format(window))

    @property
    def failing_reasons(self):
        out = []
        for verdict in self.verdicts:
            for reason in verdict.reasons:
                out.append("window {}: {}".format(verdict.window, reason))
        return tuple(out)


#: §7.1's first-hour limit, held locally because this package may not import ``phase0``.
#:
#: That import ban is the lane rule and it is not negotiable here — an arbiter that can call what it
#: judges can inherit the bug it is judging. So this is a copy, in the same sense as the four
#: ``gate_validation`` entries already in ticket 11's ``UNMIGRATED`` list, and it is held equal to
#: ``gate.first_hour_edge_share_max`` by a test there. A copy a test pins is the most this boundary
#: allows; a copy nobody pins is what this constant was invented to replace, because until it
#: existed the package had no first-hour limit at all.
#:
#: §7.1 as resolved in ticket 09: strictly greater than 40% fails, exactly 40% passes.
FIRST_HOUR_EDGE_SHARE_MAX = Decimal("0.40")


def _require_consistent_edge_origin(score):
    """Refuse a score whose edge-origin status and first-hour share cannot both be true.

    Deliberately not a verdict. It compares two fields the caller supplied *to each other* and
    raises when the pair is impossible, which is the established shape in this repository — refuse
    on the contradiction rather than pick a side, because picking is the thing that publishes a
    number nobody can defend.

    ``INDETERMINATE`` is exempt in both directions: it means the share could not be measured, so
    there is nothing to be consistent with, and the small-denominator guard that produces it lives
    in ``scoring`` where the denominator is.
    """
    status, share = score.edge_origin_status, score.first_hour_edge_share

    if status is EdgeOriginStatus.INDETERMINATE or share is None:
        return

    if status is EdgeOriginStatus.VALID and share > FIRST_HOUR_EDGE_SHARE_MAX:
        raise InconsistentEdgeOrigin(
            "window {} column {} reports edge origin VALID with a first-hour edge share of {}, "
            "which exceeds §7.1's limit of {}. Those cannot both be true: a share above the limit "
            "is UNCOPYABLE_DOMINATED by definition. Refusing rather than choosing one — the "
            "arbiter cannot know which of the two is the defect, and a gate outcome published on "
            "the wrong one is indistinguishable from a real one.".format(
                score.window, score.column, share, FIRST_HOUR_EDGE_SHARE_MAX)
        )

    if status is EdgeOriginStatus.UNCOPYABLE_DOMINATED and share <= FIRST_HOUR_EDGE_SHARE_MAX:
        raise InconsistentEdgeOrigin(
            "window {} column {} reports edge origin UNCOPYABLE_DOMINATED with a first-hour edge "
            "share of {}, which is within §7.1's limit of {}. Those cannot both be true. This "
            "direction fails a window that should have passed, so it costs a finding rather than "
            "manufacturing one — and it is refused for the same reason: the arbiter does not know "
            "which field is wrong.".format(
                score.window, score.column, share, FIRST_HOUR_EDGE_SHARE_MAX)
        )


def _reasons_for(score, threshold):
    """Why this column did not pass, restated from the stored fields.

    Descriptive only. ``WindowScore.passes`` decides; this explains. If the two ever disagree the
    construction check on :class:`ColumnVerdict` fails loudly rather than publishing a verdict with
    a contradictory explanation — a mismatch here would mean the arbiter had grown its own second
    copy of the gate rule, which is the one thing it must not have.
    """
    reasons = []

    if score.edge_origin_status is EdgeOriginStatus.INDETERMINATE:
        reasons.append(
            "edge origin is INDETERMINATE — total positive edge contribution ({}) was too small "
            "to measure the first-hour share, and an unmeasurable window is not a passing one"
            .format(score.positive_edge_contribution)
        )
    elif score.edge_origin_status is EdgeOriginStatus.UNCOPYABLE_DOMINATED:
        reasons.append(
            "edge origin is UNCOPYABLE_DOMINATED — a first-hour edge share of {} exceeds the §7.1 "
            "limit, and §7.1 makes that a hard failure rather than a warning"
            .format(score.first_hour_edge_share)
        )

    if score.mean_advantage < threshold:
        reasons.append(
            "mean advantage {} is below the calibrated threshold {}".format(
                score.mean_advantage, threshold)
        )
    if score.median_advantage <= 0:
        reasons.append(
            "median advantage {} is not strictly positive; §7.1 condition 2 exists because one "
            "token returning 1000% can carry a basket in which most buys lost money".format(
                score.median_advantage)
        )

    return tuple(reasons)


def evaluate_windows_detail(scores, threshold):
    """Group scores by window, apply the seam's pass rule, and explain every failure.

    :param scores: an iterable of :class:`contracts.WindowScore`.
    :param threshold: the calibrated mean threshold (§8.3), in the same units as
        ``mean_advantage``. Any finite value is accepted, including an absurd one — the invariant
        that INDETERMINATE never passes must hold at *every* threshold, so refusing implausible
        ones here would only hide whether it does.
    """
    threshold = require_finite(calc(threshold), "threshold")

    by_window = {}
    order = []
    for score in scores:
        if not isinstance(score, WindowScore):
            raise TypeError(
                "the gate engine reads WindowScore results only, got {}. It consumes typed "
                "results as data and cannot be handed something it would have to "
                "interpret.".format(type(score).__name__)
            )
        # ``WindowScore.window`` is declared ``int`` and the seam does not enforce it, and this
        # module groups on that field — so the identity rule has to be applied here. It is the same
        # rule ``permutation.permutation_null_detail`` applies to ``MatchedSet.selected``: two
        # results are results for the same window when they name the same window, and that
        # comparison has to be defined. Unenforced, ``1``, ``True`` and ``1.0`` are one dict key,
        # and this is the *iterable* door — nothing has collapsed in the caller's own expression
        # before it arrives, which is exactly the door ``_level_keyed`` exists to guard one key
        # space over. Measured: a ``leader`` score at ``window=1`` and a ``follower_adjusted``
        # score at ``window=True`` are two windows that each lack a required column, and each
        # therefore fails; grouped together they become one window that PASSES, with no trace.
        if not isinstance(score.window, int) or isinstance(score.window, bool):
            raise DiagnosticInputRefused(
                "a result names window {!r}, which is a {} and not an int. Results are grouped by "
                "window, so two results are for the same window when they name the same one — and "
                "Python calls 1, True and 1.0 the same key. Two windows each missing a required "
                "column each fail; merged into one they pass, and nothing in the evaluation says a "
                "merge happened. Refused rather than coerced: which window a result belongs to is "
                "the caller's fact to state, not this module's to "
                "infer.".format(score.window, type(score.window).__name__)
            )
        if score.column not in REQUIRED_COLUMNS:
            raise DiagnosticInputRefused(
                "column {!r} is not a gating column. §10 permits diagnostics to be reported and "
                "forbids them from touching the gate: only buy_quality decides. The engine refuses "
                "the artifact rather than filtering the column out, so that a diagnostic cannot "
                "reach the decision by being quietly ignored somewhere else. Gating columns: "
                "{}.".format(score.column, ", ".join(REQUIRED_COLUMNS))
            )
        columns = by_window.setdefault(score.window, {})
        if score.column in columns:
            raise ConflictingResults(
                "two results were supplied for window {} column {}. Nothing may select between "
                "them: §9.7 discards a superseded result rather than comparing it with its "
                "replacement.".format(score.window, score.column)
            )
        if score.window not in order:
            order.append(score.window)
        columns[score.column] = score

    verdicts = []
    for window in sorted(order):
        columns = by_window[window]
        column_verdicts = []
        for column in REQUIRED_COLUMNS:
            score = columns.get(column)
            if score is None:
                continue
            # Before anything is derived from it: the two fields §7.1's third condition rests on
            # must be capable of both being true. See _require_consistent_edge_origin — this adds
            # no verdict, it refuses an impossible pair.
            _require_consistent_edge_origin(score)
            # Both are computed and handed to ColumnVerdict, whose construction check refuses a
            # verdict that disagrees with its own explanation. That is the cross-check: if the
            # arbiter's restatement ever diverged from the seam's rule, this raises instead of
            # publishing a number.
            column_verdicts.append(ColumnVerdict(
                window=window,
                column=column,
                passed=score.passes(threshold),
                reasons=_reasons_for(score, threshold),
                mean_advantage=score.mean_advantage,
                median_advantage=score.median_advantage,
                first_hour_edge_share=score.first_hour_edge_share,
                edge_origin_status=score.edge_origin_status,
            ))
        missing = tuple(c for c in REQUIRED_COLUMNS if c not in columns)
        verdicts.append(WindowVerdict(
            window=window,
            passed=not missing and all(v.passed for v in column_verdicts),
            columns=tuple(column_verdicts),
            missing_columns=missing,
        ))

    return WindowEvaluation(threshold=threshold, verdicts=tuple(verdicts))


def evaluate_windows(scores, threshold):
    """§7.4. ``(windows passing both gates, windows evaluated)``."""
    evaluation = evaluate_windows_detail(scores, threshold)
    return evaluation.passed, evaluation.total


# -- §7.2 economic copyability at design capital ---------------------------------


def _level_key(value):
    """Snap a level onto the pre-registered constant so serialisation stays byte-stable.

    ``Decimal("1.5E+6")`` and ``Decimal("1500000")`` compare and hash equal but render differently,
    and the canonical hash of a decision record must not depend on how a caller spelled a number.

    This is a *collapsing* transformation, and a wider one than it looks: ``calc`` accepts ``str``,
    ``int`` and ``Decimal``, so ``"1500000"``, ``1500000`` and ``Decimal("1.5E+6")`` are three
    spellings that arrive as different things and leave as one key. :func:`_level_keyed` is what
    makes that a refusal rather than a silent last-one-wins.
    """
    level = calc(value)
    for known in DESIGN_CAPITAL_LEVELS:
        if level == known:
            return known
    return level


def _level_pairs(excess_by_level):
    """The caller's ``(level, excess)`` pairs, in order, with nothing collapsed on the way in.

    ``dict(excess_by_level)`` would be the obvious spelling and is the wrong one: handed a sequence
    of pairs it applies its own last-one-wins rule to a repeated level before anything here can
    object, so the check below would be reading a mapping this module built rather than the one the
    caller supplied. A ``Mapping`` cannot repeat a key, but every entry point here accepts pairs.
    """
    items = getattr(excess_by_level, "items", None)
    return tuple(items() if callable(items) else excess_by_level)


def _level_keyed(pairs, what):
    """``{_level_key(level): excess}``, refusing two entries that name one capital level.

    **This is** :func:`pipeline.inputs.asset_keyed`'s rule, one key space over. That function
    could not be reused: ``pipeline`` is the builder lane, ``gate_validation`` is SHARED, and
    ``tests/test_lane_independence.py`` forbids a shared->builder edge outright — the arbiter may
    not import the code it judges, or it inherits that code's bug and then certifies it. So the
    rule is restated here rather than shared, and the two must be kept in step by review.

    The refusal is on the **collision**, not on the two values disagreeing. A guard conditioned on
    disagreement closes whichever instance a reviewer happened to construct and leaves the class
    open: the entries happening to agree is luck, and the defect is that nobody can say which of
    the two entries is *the* entry at that level. Supplying both is the evidence that nobody can.

    What it costs when it is not refused, measured on the clean-run evidence in
    ``tests/integration/test_gate_validation.py`` driven through :func:`decision.emit_decision`,
    with three entries at two levels and only the caller's iteration order changed::

        ['1500000', Decimal('1500000'), Decimal('2000000')]  ->  GO
        [Decimal('1500000'), '1500000', Decimal('2000000')]  ->  CONDITIONAL_REVIEW

    ``-0.0500`` at $1.5M is deleted by the surviving ``0.0362`` in the first ordering and deletes
    it in the second. ``CapitalFeasibility.feasible`` is read at ``decision.py`` and is the whole
    of the GO-versus-CONDITIONAL_REVIEW branch, so that is the published §7 verdict moving on dict
    ordering alone.

    **What this does not reach, and cannot.** Two spellings that Python itself considers equal —
    ``Decimal("1.5E+6")``, ``Decimal("1500000.00")`` and the ``int`` ``1500000`` all compare and
    hash equal to ``Decimal("1500000")`` — are already one entry inside the caller's own ``dict``
    literal before this function is called, with the last value winning and no trace left for
    anything here to see. Through the *pairs* door nothing has collapsed yet and those are refused
    too; through a ``Mapping`` they are not reachable. What survives a ``Mapping`` to be refused
    here is every spelling that is not ``==`` to the level it names: the ``str`` forms
    (``"1500000"``, ``"1.5E+6"``), which is exactly the pair measured above.

    :param pairs: ``(level, excess)`` pairs from :func:`_level_pairs`, in the caller's order.
    :param what: the parameter's name, so the message names the mapping the caller passed.
    :raises ConflictingResults: two entries name one capital level.
    """
    order = []
    spellings = {}
    values = {}
    for entry in pairs:
        try:
            level, excess = entry
        except (TypeError, ValueError):
            raise TypeError(
                "{} entry {!r} is not a (level, excess) pair. This entry point reads pairs rather "
                "than calling dict(), so that two entries naming one level are refused instead of "
                "silently collapsed — which means a malformed entry has to be named here."
                .format(what, entry)
            )
        key = _level_key(level)
        if key not in spellings:
            order.append(key)
            spellings[key] = []
            values[key] = excess
        spellings[key].append(level)

    collided = [key for key in order if len(spellings[key]) > 1]
    if not collided:
        return {key: values[key] for key in order}
    raise ConflictingResults(
        "{} names {} capital level(s) more than once: {}. A level is snapped onto the "
        "pre-registered constant before it is used — calc() maps str, int and Decimal onto one "
        "key space — so two spellings of one level arrive as two entries and leave as one, and "
        "the last one supplied would have won. That makes §7.2 feasibility, and therefore the "
        "GO / CONDITIONAL_REVIEW branch, a function of the order the caller's mapping happens to "
        "iterate in, which is not a verdict a run can be reproduced from. "
        "Refused rather than resolved: keeping either entry, or refusing only when the two "
        "disagree, would require knowing which spelling the caller meant, and supplying both is "
        "the evidence that nobody does.".format(
            what,
            len(collided),
            "; ".join(
                "${} is named by {} entries: {}".format(
                    key,
                    len(spellings[key]),
                    ", ".join(repr(level) for level in spellings[key]),
                )
                for key in collided
            ),
        )
    )


@dataclass(frozen=True)
class CapitalFeasibility:
    """Follower-Adjusted Excess Buy Quality per capital level, and whether §7.2 is satisfied.

    ``None`` at a level means it could not be measured. That is a failure, not an abstention
    (ticket 33) — the alternative is a gate that passes because a measurement is missing, which is
    the identical shape of every bug this protocol is built around.

    Construction is the only boundary this type has, which is why the key refusal lives here rather
    than in :func:`assess_capital_feasibility`: ``decision.emit_decision_detail`` refuses anything
    that is not a ``CapitalFeasibility``, so no second *factory* can be added that reaches a
    published verdict while skipping the check.

    Stated with the residue, because "every path runs through ``__post_init__``" is stronger than
    Python allows and an earlier version of this paragraph claimed it: ``object.__new__`` builds an
    instance without running ``__post_init__`` at all, and ``object.__setattr__`` then fills
    ``excess_by_level`` with anything — including the two-spellings mapping refused below. That
    instance satisfies the ``isinstance`` check in ``emit_decision_detail``. No class prevents it
    and this one does not try; what the boundary rules out is an ordinary caller reaching a verdict
    through a second front door, not a caller who has decided to bypass construction.
    """

    excess_by_level: Dict[Decimal, Optional[Decimal]]

    def __post_init__(self):
        keyed = _level_keyed(_level_pairs(self.excess_by_level), "excess_by_level")
        normalised = {}
        for key, excess in keyed.items():
            if excess is None:
                normalised[key] = None
            else:
                normalised[key] = require_finite(
                    calc(excess), "excess at capital level {}".format(key)
                )
        object.__setattr__(self, "excess_by_level", normalised)

    @property
    def missing_levels(self):
        return tuple(l for l in DESIGN_CAPITAL_LEVELS if l not in self.excess_by_level)

    @property
    def unmeasured_levels(self):
        return tuple(l for l in DESIGN_CAPITAL_LEVELS
                     if l in self.excess_by_level and self.excess_by_level[l] is None)

    @property
    def failing_levels(self):
        return tuple(
            l for l in DESIGN_CAPITAL_LEVELS
            if l in self.excess_by_level
            and self.excess_by_level[l] is not None
            and self.excess_by_level[l] <= 0
        )

    @property
    def feasible(self):
        """§7.2: both levels, both strictly positive, both actually measured."""
        return not (self.missing_levels or self.unmeasured_levels or self.failing_levels)

    @property
    def reasons(self):
        out = []
        for level in self.missing_levels:
            out.append(
                "follower-adjusted excess buy quality was not simulated at ${}; §7.2 gates on "
                "both design capital levels".format(level)
            )
        for level in self.unmeasured_levels:
            out.append(
                "follower-adjusted excess buy quality at ${} could not be measured, which is a "
                "window failure and not an abstention".format(level)
            )
        for level in self.failing_levels:
            out.append(
                "follower-adjusted excess buy quality at ${} is {}, and §7.2 requires strictly "
                "greater than zero".format(level, self.excess_by_level[level])
            )
        return tuple(out)


def assess_capital_feasibility(excess_by_level):
    """§7.2. Levels outside ``DESIGN_CAPITAL_LEVELS`` are recorded and do not decide anything.

    Accepts a mapping or a sequence of ``(level, excess)`` pairs, and hands either to
    :class:`CapitalFeasibility` **unconverted**. The ``dict(excess_by_level)`` that used to stand
    here was the whole of the second half of the defect: handed pairs it collapsed a repeated level
    by its own last-one-wins rule before ``__post_init__`` could object, so the refusal one layer
    down was reading a mapping this function had already cleaned up.
    """
    return CapitalFeasibility(excess_by_level=excess_by_level)
