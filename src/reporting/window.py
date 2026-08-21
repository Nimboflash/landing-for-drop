"""One walk-forward window, rendered — and the sign that quantization would otherwise destroy.

§10's outputs sit beside the gate result rather than inside it, so this module renders window
scores and decides nothing. :meth:`contracts.WindowScore.passes` owns the three §7.1 conditions and
``gate_validation`` applies them; a second copy of that rule here would be a second answer to the
same question, and §9.7 is explicit that nothing may choose between two.

**Non-gating columns are refused, not filtered.** §10 permits a long list of diagnostics and then
forbids them from touching a gate. A report that rendered a diagnostic column in the same table as
``leader`` and ``follower_adjusted`` would produce exactly the artefact §10 warns about — a number
that looks like a gate result, sitting next to two that are — and someone would eventually read the
table and overturn the decision from it. Diagnostics go through
:mod:`reporting.diagnostics`, which gives them a type no gate input can be confused with.

**The sign survives the boundary even when the value does not.** §7.1 condition 2 is
``median_advantage > 0``, a strict inequality on the *unrounded* number. A median advantage of
``1e-9`` is a genuine pass and renders as ``0.00000000`` at the ratio scale. A reader seeing a
passing window beside a zero would conclude the report was broken; a reconciler recomputing the
condition from the published figure would conclude the gate was wrong. So the report carries
``median_advantage_is_positive``, taken from the value as it arrived, and the two travel together.

That is the general shape of the hazard this module guards: quantization is information loss, and
the losses that matter are the ones that change the answer to a question someone will ask of the
rendered figure.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from contracts import ContractError, EdgeOriginStatus, WindowScore, require_finite
from phase0.parameters import PARAMETERS

from .boundary import RATIO, optional_output, output_pp, output_ratio

#: §7.1 runs on the leader column, §7.2 on the follower-adjusted one. The names are the seam's —
#: ``WindowScore.column`` carries them — and ``tests/integration/test_reporting.py`` asserts these
#: are exactly ``gate_validation.REQUIRED_COLUMNS``, so the two cannot drift apart.
GATING_COLUMNS = ("leader", "follower_adjusted")

#: §6.3 fixes four walk-forward windows. Recorded so a report over three can say which is absent
#: rather than looking complete. Read from the ticket-11 frozen set.
EXPECTED_WINDOWS = PARAMETERS.value("windows.count")


class NonGatingColumnReported(ContractError):
    """A column that is not a gating column was passed to the window report."""


class ConflictingWindowResults(ContractError):
    """Two results for the same (window, column), and nothing may choose between them."""


@dataclass(frozen=True)
class WindowColumnReport:
    """One column of one window, rendered.

    ``first_hour_edge_share`` is ``None`` exactly when the edge origin is ``INDETERMINATE``, which
    is the seam's own invariant restated at the boundary rather than re-decided: an unmeasurable
    window carries no share, and a ``0`` in its place would render as a window whose edge was
    entirely outside the first hour — the most favourable possible reading of a measurement that
    does not exist.
    """

    window: int
    column: str
    mean_advantage: Decimal
    median_advantage: Decimal
    mean_advantage_is_positive: bool
    median_advantage_is_positive: bool
    first_hour_edge_share: Optional[Decimal]
    positive_edge_contribution: Decimal
    edge_origin_status: EdgeOriginStatus

    def __post_init__(self):
        if self.edge_origin_status is EdgeOriginStatus.INDETERMINATE:
            if self.first_hour_edge_share is not None:
                raise ValueError("INDETERMINATE must not carry a first-hour share")
        elif self.first_hour_edge_share is None:
            raise ValueError(
                "a measurable window must carry a first-hour share; None is reserved for "
                "INDETERMINATE"
            )


@dataclass(frozen=True)
class WindowReport:
    """One window's columns, plus the ones that are absent.

    Absence is recorded rather than refused. The gate engine fails a window that is missing a
    column, because "both gates passed" is not a claim one column can support; a *report* has the
    opposite duty — to show that the column is missing, so that nobody reads a one-column table as
    a complete one.
    """

    window: int
    columns: Tuple[WindowColumnReport, ...] = ()
    missing_columns: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "missing_columns", tuple(self.missing_columns))

    def column_for(self, column):
        for report in self.columns:
            if report.column == column:
                return report
        raise KeyError("window {} carries no {} column".format(self.window, column))


def report_window(scores):
    """Render one window's :class:`contracts.WindowScore` results.

    :param scores: the scores for a **single** window, in a deterministic order.

    A mixture of window indices is refused. Rendering two windows into one row is how a window that
    failed becomes invisible behind one that passed, and the caller that mixed them almost
    certainly did not mean to.
    """
    items = tuple(scores)
    if not items:
        raise ValueError(
            "no scores were supplied; an empty window report is indistinguishable from a window "
            "that was never evaluated"
        )

    by_column = {}
    window = None
    for score in items:
        if not isinstance(score, WindowScore):
            raise TypeError(
                "report_window renders contracts.WindowScore results, got {}. Diagnostics carry "
                "their own type for exactly this reason: a diagnostic rendered beside the two "
                "gating columns is a number that looks like a gate result.".format(
                    type(score).__name__
                )
            )
        if score.column not in GATING_COLUMNS:
            raise NonGatingColumnReported(
                "column {!r} is not a gating column. §10: only buy_quality decides the gate, and "
                "'reporting a diagnostic and then using it to overturn a gate result is the "
                "failure mode this entire document exists to prevent'. Report it through "
                "reporting.diagnostics, whose type no gate input can be confused with. Gating "
                "columns: {}.".format(score.column, ", ".join(GATING_COLUMNS))
            )
        if window is None:
            window = score.window
        elif score.window != window:
            raise ConflictingWindowResults(
                "scores for windows {} and {} were passed to a single window report; rendering "
                "two windows into one row is how a failing window disappears behind a passing "
                "one".format(window, score.window)
            )
        if score.column in by_column:
            raise ConflictingWindowResults(
                "two results were supplied for window {} column {}; §9.7 discards a superseded "
                "result rather than comparing it with its replacement".format(
                    score.window, score.column
                )
            )
        by_column[score.column] = score

    columns = []
    for column in GATING_COLUMNS:
        score = by_column.get(column)
        if score is None:
            continue

        # Refused here, above the construction, rather than inside it. ``contracts.WindowScore``
        # does not refuse a ``Decimal("NaN")`` advantage, and a bare ``NaN > 0`` raises
        # ``InvalidOperation`` — an untyped arithmetic error where a refusal naming the field
        # belongs. ``output_pp`` below would also catch it, but only because it happens to be
        # written before the sign in the argument list, and a report's refusal must not depend on
        # the order somebody typed the keyword arguments in.
        mean_advantage = require_finite(
            score.mean_advantage, "window {} mean_advantage".format(score.window)
        )
        median_advantage = require_finite(
            score.median_advantage, "window {} median_advantage".format(score.window)
        )

        columns.append(
            WindowColumnReport(
                window=score.window,
                column=column,
                mean_advantage=output_pp(
                    mean_advantage, "window {} mean_advantage".format(score.window)
                ),
                median_advantage=output_pp(
                    median_advantage, "window {} median_advantage".format(score.window)
                ),
                # The sign comes off the value as it arrived, before the boundary touched it.
                # §7.1's conditions are strict inequalities on the unrounded number, and 1e-9 and
                # 0 render identically.
                mean_advantage_is_positive=mean_advantage > 0,
                median_advantage_is_positive=median_advantage > 0,
                first_hour_edge_share=optional_output(
                    score.first_hour_edge_share, RATIO, "first_hour_edge_share"
                ),
                positive_edge_contribution=output_ratio(
                    score.positive_edge_contribution, "positive_edge_contribution"
                ),
                edge_origin_status=score.edge_origin_status,
            )
        )

    return WindowReport(
        window=window,
        columns=tuple(columns),
        missing_columns=tuple(c for c in GATING_COLUMNS if c not in by_column),
    )
