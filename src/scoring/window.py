"""One walk-forward window's result for one column (§7.1, ticket 33's input).

    1.  Mean Buy Quality Advantage      >= Calibrated Mean Threshold
    2.  Median Buy Quality Advantage    > 0
    3.  First-Hour Edge Share           <= 40%

All three, per window. :meth:`contracts.WindowScore.passes` evaluates them together and nothing here
re-implements it — a second copy of a three-condition gate is how the null ends up testing a
two-condition one, and §8.2 is explicit that if the null used a different gate the 95th percentile
would refer to a different experiment and the calibration would be void.

Condition 2 exists because long-tail return distributions are severely skewed: one token returning
1000% can carry a basket in which 90% of buys lost money.

Condition 3 arrives already decided, as a :class:`scoring.edge.EdgeOrigin`. ``INDETERMINATE`` and
``UNCOPYABLE_DOMINATED`` both fail the window, and neither can be rescued by conditions 1 and 2 —
:attr:`contracts.EdgeOriginStatus.passes` is True for ``VALID`` alone, which is why the status is an
enum rather than a boolean that an ``if window.passed:`` could quietly absorb.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple

from contracts import WindowScore, calc, require_finite

from .edge import EdgeOrigin
from .weights import arithmetic_mean, median

#: §7.1 is run twice: once on the leader's raw buy quality, once on the follower-adjusted metric.
#: A third name would be a column nobody pre-registered, so an unknown one is refused.
COLUMNS = ("leader", "follower_adjusted")


@dataclass(frozen=True)
class WindowEvaluation:
    """The full answer, of which :class:`contracts.WindowScore` is the seam-shaped summary.

    The per-wallet advantages are kept because the mean and the median are the two numbers most
    often disputed, and a reviewer who has only the summary cannot tell a basket of consistent small
    winners from one carried by a single token.
    """

    window: int
    column: str
    advantages: Tuple[Decimal, ...]
    mean_advantage: Decimal
    median_advantage: Decimal
    edge: EdgeOrigin

    def __post_init__(self):
        object.__setattr__(self, "advantages", tuple(self.advantages))

    @property
    def n_selected(self):
        return len(self.advantages)

    @property
    def score(self):
        """The frozen-seam view. Every field the gate engine is allowed to read."""
        return WindowScore(
            window=self.window,
            column=self.column,
            mean_advantage=self.mean_advantage,
            median_advantage=self.median_advantage,
            first_hour_edge_share=self.edge.share,
            positive_edge_contribution=self.edge.total_positive_contribution,
            edge_origin_status=self.edge.status,
        )

    def passes(self, mean_threshold):
        """§7.1's three conditions, delegated to the seam so there is exactly one copy of them."""
        return self.score.passes(require_finite(calc(mean_threshold), "mean_threshold"))


def score_window(window, column, advantages, edge):
    """One window's :class:`contracts.WindowScore`.

    Use :func:`evaluate_window` for the per-wallet advantages behind the mean and the median.
    """
    return evaluate_window(window, column, advantages, edge).score


def evaluate_window(window, column, advantages, edge):
    """:func:`score_window`, with everything a reviewer needs to reproduce the number."""
    if not isinstance(window, int) or isinstance(window, bool):
        raise TypeError("window must be an int index, got {}".format(type(window).__name__))
    if column not in COLUMNS:
        raise ValueError(
            "unknown column {!r}; §7.1 pre-registers exactly {}. A new column is a new experiment, "
            "not a new argument.".format(column, " and ".join(COLUMNS))
        )
    if not isinstance(edge, EdgeOrigin):
        raise TypeError(
            "the Edge Origin decision must arrive already made, as a scoring.EdgeOrigin, got "
            "{}".format(type(edge).__name__)
        )

    # arithmetic_mean and median both refuse an empty sequence: a window with no selected wallets
    # has no result, and a zero advantage would read as a measured dead heat.
    values = tuple(require_finite(calc(a), "advantage") for a in advantages)

    return WindowEvaluation(
        window=window,
        column=column,
        advantages=values,
        mean_advantage=arithmetic_mean(values),
        median_advantage=median(values),
        edge=edge,
    )
