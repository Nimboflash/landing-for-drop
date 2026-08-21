"""Wallet churn in three states — §10, ticket 27, ticket 34.

    Churn Rate = selected wallets with no valid buy in the forward period
                 / total selected wallets

    Reported in three states: Active · Reduced Activity · Inactive

§10 states the formula and then, in the next sentence, states why the formula alone is not enough:
*"A wallet that fell from 100 trades to 1 is effectively dead to the system even though it is
technically alive."* The formula counts that wallet as active. The three states exist so that it
is not counted as healthy.

**Churn is reported independently of the edge result.** Nothing in this module reads a window
score, a gate outcome, a threshold, or a buy quality, and :func:`report_churn` takes no argument
through which one could arrive. If 60% of top wallets go quiet within six months, the system has a
churn problem that no engine fixes and no positive gate result offsets — so the finding must not be
computable only in the branch where the gate passed.

The pinned threshold
--------------------

§10 requires a `Reduced Activity` state and does not name its boundary, so this module names it,
once, as an absolute constant::

    REDUCED_ACTIVITY_RATIO = Decimal("0.25")

A wallet is `Reduced Activity` when it still trades but its forward trade *rate* is below a quarter
of its baseline rate. The comparison is on rates rather than counts because the baseline and
forward periods need not be the same length, and a wallet observed for 90 forward days against 400
baseline days would otherwise look like it had collapsed purely from the arithmetic of the calendar.

The ratio is computed as a single cross-product division::

    activity_ratio = (forward_buys x baseline_days) / (baseline_buys x forward_days)

rather than as a ratio of two separately computed rates. The products are exact integers, so the
whole figure rounds once instead of three times, and the boundary cases below are exact rather than
approximate — which is what lets ``0.25`` be a boundary a test can actually stand on.

Boundary, pinned by test rather than by comment: ``<`` is strict, so a wallet sitting exactly on
one quarter of its baseline rate is `Active`. §10's own example — 100 trades falling to 1 over the
same period — lands at 0.01 and is `Reduced Activity`.

What the relative rule does not catch
-------------------------------------

A wallet with a *low* baseline that keeps a quarter of it — 20 valid buys falling to 5 — is
`Active` here, and 5 buys in six months is arguably not a wallet anyone can copy. That is a real
limitation and it is recorded rather than patched, for two reasons. §10's definition is relative
and its example is a rate collapse; and §6 already floors eligibility at 20 valid buys in the
*baseline*, while ticket 27 forbids post-``T0`` activity from being used as anything but an output
— so an absolute forward floor would be a second threshold nobody pre-registered, applied to the
one input the design is specifically built not to filter on.

The counts that would answer the absolute question stay with the caller in the
:class:`WalletActivity` records, and the report carries the population size beside every rate, so
the figure can be recomputed against a different rule. What it may not do is change silently.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Tuple

from contracts import ContractError, divide, mul

from .aggregate import rate
from .boundary import output_ratio


class ChurnState(str, Enum):
    """§10's three states, spelled as §10 spells them.

    An enum rather than a boolean ``is_active``, for the same reason
    :class:`contracts.EdgeOriginStatus` is an enum: a two-valued type forces `Reduced Activity` to
    collapse into one of the other two, and the whole point of the third state is that it belongs
    to neither.
    """

    ACTIVE = "Active"
    REDUCED_ACTIVITY = "Reduced Activity"
    INACTIVE = "Inactive"


#: The forward trade rate, as a fraction of the baseline trade rate, below which a still-trading
#: wallet is `Reduced Activity`. Pinned here, once, and carried in every :class:`ChurnReport` so a
#: published churn figure says which boundary produced it.
REDUCED_ACTIVITY_RATIO = Decimal("0.25")


class ChurnInputRefused(ContractError):
    """The activity record cannot support a churn state, and none will be guessed."""


@dataclass(frozen=True)
class WalletActivity:
    """One selected wallet's valid-buy counts either side of ``T0``.

    Counts, not trades: churn asks how often a wallet acted, not what the action was worth. Both
    periods carry their own length because they are not required to be equal — the forward period
    is the walk-forward window, the baseline is whatever selection measured over.

    ``baseline_valid_buys`` must be positive. §6 selects wallets on 20–1,000 valid buys, so a
    selected wallet with a zero baseline is a bookkeeping error rather than a quiet wallet, and
    dividing by it would produce an undefined ratio that the state machine would then have to
    interpret. Refusing is the only reading that does not invent a finding.
    """

    wallet: str
    baseline_valid_buys: int
    baseline_days: int
    forward_valid_buys: int
    forward_days: int

    def __post_init__(self):
        object.__setattr__(self, "wallet", (self.wallet or "").lower())
        if not self.wallet:
            raise ChurnInputRefused("a churn record must name its wallet")
        for name in ("baseline_valid_buys", "baseline_days", "forward_valid_buys", "forward_days"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(
                    "{} must be an int, got {}; a Decimal count would let a fractional trade "
                    "reach a churn state".format(name, type(value).__name__)
                )
        if self.baseline_valid_buys <= 0:
            raise ChurnInputRefused(
                "wallet {} has {} baseline valid buys. §6 selects on 20-1,000 valid buys, so a "
                "non-positive baseline is a bookkeeping error, not a quiet wallet — and there is "
                "no activity ratio to compare against a threshold.".format(
                    self.wallet, self.baseline_valid_buys
                )
            )
        if self.forward_valid_buys < 0:
            raise ChurnInputRefused("forward valid buys cannot be negative")
        for name in ("baseline_days", "forward_days"):
            if getattr(self, name) <= 0:
                raise ChurnInputRefused(
                    "{} is {} for wallet {}; a period of no length cannot carry a trade "
                    "rate".format(name, getattr(self, name), self.wallet)
                )

    @property
    def baseline_rate(self):
        """Valid buys per day before ``T0``. Reported; not what the state is decided on."""
        return divide(self.baseline_valid_buys, self.baseline_days)

    @property
    def forward_rate(self):
        """Valid buys per day after ``T0``."""
        return divide(self.forward_valid_buys, self.forward_days)

    @property
    def activity_ratio(self):
        """``forward_rate / baseline_rate``, rounded once.

        Computed from the cross-product rather than from :attr:`forward_rate` and
        :attr:`baseline_rate`, which would round three times. The products are exact integers, so
        this figure is exact wherever the quotient terminates — including at the ``0.25``
        boundary, where an approximate value would make the state depend on the 38th digit.
        """
        return divide(
            mul(self.forward_valid_buys, self.baseline_days),
            mul(self.baseline_valid_buys, self.forward_days),
        )

    @property
    def state(self):
        """§10's three states.

        Order matters. A wallet with no forward buys is `Inactive` on §10's own definition, and it
        is tested first so that the ratio — which would be exactly zero, and therefore also below
        the threshold — cannot classify it as merely reduced.
        """
        if self.forward_valid_buys == 0:
            return ChurnState.INACTIVE
        if self.activity_ratio < REDUCED_ACTIVITY_RATIO:
            return ChurnState.REDUCED_ACTIVITY
        return ChurnState.ACTIVE


@dataclass(frozen=True)
class ChurnReport:
    """§10's churn block. Rates are quantized; counts are exact.

    ``churn_rate`` is §10's formula verbatim — the *Inactive* share, and nothing else. It is not
    quietly widened to include `Reduced Activity`, because that would be publishing a different
    number under a pre-registered name. The wallets §10's prose calls effectively dead are counted
    separately, in :attr:`effectively_dead_rate`, which is named so that it cannot be mistaken for
    the pre-registered figure.
    """

    n_wallets: int
    n_active: int
    n_reduced_activity: int
    n_inactive: int
    churn_rate: Decimal
    active_rate: Decimal
    reduced_activity_rate: Decimal
    inactive_rate: Decimal
    effectively_dead_rate: Decimal
    reduced_activity_threshold: Decimal
    states: Tuple[Tuple[str, ChurnState], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "states", tuple((w, s) for w, s in self.states))
        counted = self.n_active + self.n_reduced_activity + self.n_inactive
        if counted != self.n_wallets:
            raise ValueError(
                "the three churn states hold {} wallets but the population is {}; a wallet that "
                "belongs to no state, or to two, makes every rate below meaningless".format(
                    counted, self.n_wallets
                )
            )
        if self.churn_rate != self.inactive_rate:
            raise ValueError(
                "churn_rate is {} and inactive_rate is {}. §10 defines Churn Rate as the share "
                "with no valid buy in the forward period, which is exactly the Inactive share; "
                "the two fields are a redundant assertion and a disagreement between them means "
                "one of the counts is wrong.".format(self.churn_rate, self.inactive_rate)
            )
        if len(self.states) != self.n_wallets:
            raise ValueError(
                "{} per-wallet states were recorded for a population of {}".format(
                    len(self.states), self.n_wallets
                )
            )


def report_churn(activities):
    """§10's churn block from per-wallet activity, and from nothing else.

    :param activities: an iterable of :class:`WalletActivity`, in a deterministic order.

    There is no gate, window, threshold, or score parameter, and adding one would be the mechanism
    by which churn stopped being a finding in its own right. ``tests/integration/test_reporting.py``
    asserts the signature stays that way.
    """
    records = tuple(activities)
    for record in records:
        if not isinstance(record, WalletActivity):
            raise TypeError(
                "churn is computed from WalletActivity records, got {}. Passing raw counts would "
                "let a baseline of zero, or a period of zero days, reach the ratio without "
                "passing the refusals that WalletActivity applies.".format(type(record).__name__)
            )

    seen = set()
    for record in records:
        if record.wallet in seen:
            raise ChurnInputRefused(
                "wallet {} appears twice in the churn population; a wallet counted twice moves "
                "every rate in the block and the duplicate is invisible in the "
                "result".format(record.wallet)
            )
        seen.add(record.wallet)

    if not records:
        # ``rate`` would refuse the zero denominator anyway; refusing here names the actual
        # problem instead of describing a division.
        raise ChurnInputRefused(
            "churn was requested over no wallets. A churn rate of zero over an empty basket reads "
            "as 'nobody churned', which is the opposite of what an empty basket means."
        )

    states = tuple((record.wallet, record.state) for record in records)
    n_active = sum(1 for _, s in states if s is ChurnState.ACTIVE)
    n_reduced = sum(1 for _, s in states if s is ChurnState.REDUCED_ACTIVITY)
    n_inactive = sum(1 for _, s in states if s is ChurnState.INACTIVE)
    n_wallets = len(states)

    inactive_rate = output_ratio(rate(n_inactive, n_wallets, "inactive rate"), "inactive_rate")

    return ChurnReport(
        n_wallets=n_wallets,
        n_active=n_active,
        n_reduced_activity=n_reduced,
        n_inactive=n_inactive,
        # §10's formula, and the same number as inactive_rate by construction. Both are stored so
        # ChurnReport can check them against each other.
        churn_rate=inactive_rate,
        active_rate=output_ratio(rate(n_active, n_wallets, "active rate"), "active_rate"),
        reduced_activity_rate=output_ratio(
            rate(n_reduced, n_wallets, "reduced activity rate"), "reduced_activity_rate"
        ),
        inactive_rate=inactive_rate,
        effectively_dead_rate=output_ratio(
            rate(n_inactive + n_reduced, n_wallets, "effectively dead rate"),
            "effectively_dead_rate",
        ),
        reduced_activity_threshold=REDUCED_ACTIVITY_RATIO,
        states=states,
    )
