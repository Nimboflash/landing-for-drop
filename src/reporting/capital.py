"""§10's per-capital-level block, at all five levels.

    Raw Buy Quality              Follower-Adjusted Buy Quality
    Mean Copy Retention          Median Copy Retention
    Positive Trade Rate          Realized / Marked / Dead Share
    Unexecutable Trade Share

Ticket 63 says what this block is for: *"so that 'the edge survived' is distinguishable from 'most
of the edge could not be traded at all'."* Every design choice below follows from that sentence.

**Nothing here is ever zero because it could not be measured.** A positive-trade rate over zero
executable trades is ``None``, not ``0`` — a zero would read as "every trade lost money" when what
happened is that no trade could be placed. Copy Retention below its display threshold is ``None``.
An unmeasurable figure is an absence, and §10's whole purpose is that absences do not get published
as findings.

**Copy Retention has a pinned display threshold.** §4.5 said "above a minimum threshold" without
naming it; addendum §9.3 names it::

    Copy Retention is displayed only when Raw Buy Quality >= 2 percentage points

Below that the denominator is small enough that the ratio is dominated by noise, and a wallet with
a raw quality of 0.0001 and a follower-adjusted quality of 0.00005 would publish a retention of 50%
that means nothing whatever. The comparison is ``>=`` and the threshold is ``Decimal("0.02")``;
a wallet sitting exactly on it is displayed.

**The two denominators are different, and both counts are carried.** Unexecutable Trade Share
counts against *every* simulated trade; Positive Trade Rate counts against the *executable* ones,
because an order that was never placed has no return to be positive. Reporting only the rates would
let a 95% positive rate measured on the 4% of trades that were executable read as a healthy result,
which is precisely the confusion ticket 63 names — so ``n_simulated``, ``n_executable`` and
``n_positive`` travel with them.

**Mean Copy Retention is not the ratio of the two mean qualities.** ``mean(f_i / r_i)`` and
``mean(f_i) / mean(r_i)`` are different numbers and the gap is not small when wallet qualities are
spread out. §10 asks for the mean and median of the *per-wallet* retention, so that is what is
computed, and the two mean qualities are reported beside it rather than as its ingredients.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from contracts import (
    ContractError,
    CopySimulation,
    calc,
    divide,
    require_finite,
)
from phase0.parameters import PARAMETERS

from .aggregate import mean, median, rate
from .boundary import PERCENTAGE_POINTS, RATIO, optional_output, output_ratio
from .wallet import ValueBasisAmounts

#: §3.1's five levels. Reported at all five, always: the last two are ``design_capital`` and gate
#: under §7.2, and the first three are what locates the capacity cliff between them. Read from the
#: ticket-11 frozen set, in the document's own order — ``_level_key`` snaps every incoming value
#: onto this tuple, so a sixth level or a reordering here is a different experiment.
CAPITAL_LEVELS = PARAMETERS.value("capital.levels")

#: Addendum §9.3. Two percentage points, as a ratio, from the ticket-11 frozen set.
COPY_RETENTION_MIN_RAW_QUALITY = PARAMETERS.value("copy_retention.display_floor")


class UnknownCapitalLevel(ContractError):
    """A level outside §3.1's five reached the per-level report."""


class IncompleteCapitalLadder(ContractError):
    """§10 requires all five levels, and a missing one is not an empty row."""


class MismatchedCapitalLevel(ContractError):
    """A simulation run at one capital level was reported under another."""


def level_key(value):
    """Snap a level onto the pre-registered constant, or refuse it.

    ``Decimal("1.5E+6")`` and ``Decimal("1500000")`` compare equal and render differently, and the
    canonical hash of a report must not depend on how a caller spelled a number. A level that is
    not one of the five is refused rather than recorded: §10 fixes the ladder, and a sixth rung
    would be a capital level nobody pre-registered.
    """
    level = require_finite(calc(value), "capital_level")
    for known in CAPITAL_LEVELS:
        if level == known:
            return known
    raise UnknownCapitalLevel(
        "${} is not one of §3.1's five capital levels ({}). Copyability is simulated at those "
        "five and the last two are design_capital; a sixth is a different "
        "experiment.".format(level, ", ".join(str(l) for l in CAPITAL_LEVELS))
    )


@dataclass(frozen=True)
class WalletCapitalOutcome:
    """One wallet's raw and follower-adjusted buy quality at one capital level.

    Both at full precision. Copy Retention is derived here rather than supplied, so the display
    threshold is applied once — a caller that computed the ratio itself and handed it over would
    have already decided whether it was displayable, which is the decision this class exists to
    make.
    """

    wallet: str
    raw_buy_quality: Decimal
    follower_adjusted_buy_quality: Decimal

    def __post_init__(self):
        object.__setattr__(self, "wallet", (self.wallet or "").lower())
        if not self.wallet:
            raise ValueError("a capital-level outcome must name its wallet")
        object.__setattr__(
            self, "raw_buy_quality",
            require_finite(calc(self.raw_buy_quality), "raw_buy_quality"),
        )
        object.__setattr__(
            self, "follower_adjusted_buy_quality",
            require_finite(
                calc(self.follower_adjusted_buy_quality), "follower_adjusted_buy_quality"
            ),
        )

    @property
    def retention_is_reportable(self):
        """Addendum §9.3's condition, and the only place it is decided."""
        return self.raw_buy_quality >= COPY_RETENTION_MIN_RAW_QUALITY

    @property
    def copy_retention(self):
        """``Follower-Adjusted Buy Quality / Raw Buy Quality``, or ``None``.

        ``None`` below the threshold — not zero, and not the ratio with a footnote. §4.5: *"Reported
        only when Raw Buy Quality is positive and above a minimum threshold. Otherwise N/A, to avoid
        meaningless ratios."* The threshold also disposes of the negative-denominator case, where
        the ratio would carry a sign nobody could interpret.
        """
        if not self.retention_is_reportable:
            return None
        return divide(self.follower_adjusted_buy_quality, self.raw_buy_quality)


@dataclass(frozen=True)
class CapitalLevelReport:
    """§10's block for one capital level. Every figure has been through the boundary once."""

    capital_level: Decimal
    n_wallets: int
    mean_raw_buy_quality: Decimal
    mean_follower_adjusted_buy_quality: Decimal
    mean_copy_retention: Optional[Decimal]
    median_copy_retention: Optional[Decimal]
    n_retention_reported: int
    n_retention_suppressed: int
    positive_trade_rate: Optional[Decimal]
    unexecutable_trade_share: Decimal
    mean_execution_cost_pct: Optional[Decimal]
    n_simulated: int
    n_executable: int
    n_positive: int
    realized_share: Decimal
    marked_share: Decimal
    dead_share: Decimal
    copy_retention_threshold: Decimal = COPY_RETENTION_MIN_RAW_QUALITY

    def __post_init__(self):
        if self.n_retention_reported + self.n_retention_suppressed != self.n_wallets:
            raise ValueError(
                "retention was reported for {} wallets and suppressed for {}, against a basket of "
                "{}; every wallet is one or the other".format(
                    self.n_retention_reported, self.n_retention_suppressed, self.n_wallets
                )
            )
        if self.n_executable > self.n_simulated:
            raise ValueError(
                "{} executable trades out of {} simulated".format(
                    self.n_executable, self.n_simulated
                )
            )
        if self.n_positive > self.n_executable:
            raise ValueError(
                "{} trades were positive out of {} executable; a trade that could not be placed "
                "has no return to be positive".format(self.n_positive, self.n_executable)
            )
        if (self.mean_copy_retention is None) != (self.n_retention_reported == 0):
            raise ValueError(
                "mean copy retention is {} while {} wallets cleared the display threshold; N/A and "
                "an empty denominator must agree, or a suppressed figure is being published as a "
                "measured one".format(self.mean_copy_retention, self.n_retention_reported)
            )
        if (self.positive_trade_rate is None) != (self.n_executable == 0):
            raise ValueError(
                "positive trade rate is {} while {} trades were executable; a rate over zero "
                "executable trades must be N/A, because a zero there reads as 'every trade lost "
                "money'".format(self.positive_trade_rate, self.n_executable)
            )


@dataclass(frozen=True)
class CapitalLadderReport:
    """All five levels, in ascending order. A missing rung is a refusal, not an empty row."""

    levels: Tuple[CapitalLevelReport, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "levels", tuple(self.levels))
        present = [report.capital_level for report in self.levels]
        if len(set(present)) != len(present):
            raise IncompleteCapitalLadder(
                "a capital level is reported twice: {}".format(present)
            )
        missing = [level for level in CAPITAL_LEVELS if level not in present]
        if missing:
            raise IncompleteCapitalLadder(
                "§10 requires all five capital levels; missing {}. An absent level is not an empty "
                "row — the ladder is how the capacity cliff is located, and a gap in it is exactly "
                "where the cliff would hide.".format(", ".join("${}".format(m) for m in missing))
            )
        if present != sorted(present):
            raise IncompleteCapitalLadder(
                "capital levels must be reported in ascending order so the ladder reads as one; "
                "got {}".format(present)
            )

    def at(self, level):
        key = level_key(level)
        for report in self.levels:
            if report.capital_level == key:
                return report
        raise KeyError("no report at capital level {}".format(key))


def report_capital_level(level, outcomes, simulations, value_basis):
    """§10's block for one capital level.

    :param level: one of :data:`CAPITAL_LEVELS`.
    :param outcomes: :class:`WalletCapitalOutcome` per selected wallet, deterministic order.
    :param simulations: :class:`contracts.CopySimulation` per simulated leader buy, **all at this
        level**. A simulation carrying a different ``capital_level`` is refused rather than
        re-labelled: mixing levels is the one error that would make the capacity cliff disappear
        into an average.
    :param value_basis: the :class:`reporting.wallet.ValueBasisAmounts` for this level.
    """
    key = level_key(level)

    wallet_outcomes = tuple(outcomes)
    for outcome in wallet_outcomes:
        if not isinstance(outcome, WalletCapitalOutcome):
            raise TypeError(
                "report_capital_level consumes WalletCapitalOutcome, got {}. Passing a bare ratio "
                "would mean the caller had already decided whether Copy Retention was "
                "displayable.".format(type(outcome).__name__)
            )
    if not wallet_outcomes:
        raise ValueError(
            "no wallet outcomes at ${}; a capital level with no wallets has no buy quality, and a "
            "zero would read as a measured flat result".format(key)
        )

    sims = tuple(simulations)
    for sim in sims:
        if not isinstance(sim, CopySimulation):
            raise TypeError(
                "report_capital_level consumes contracts.CopySimulation, got {}. The seam type is "
                "what guarantees a non-copyable simulation says why, and that a copyable one "
                "carries a return.".format(type(sim).__name__)
            )
        if level_key(sim.capital_level) != key:
            raise MismatchedCapitalLevel(
                "a simulation run at ${} was passed to the ${} report. Averaging across levels is "
                "the one error that would hide the capacity cliff inside a "
                "mean.".format(sim.capital_level, key)
            )
    if not sims:
        raise ValueError(
            "no simulations at ${}; an unexecutable-trade share of zero over no trades reads as "
            "'everything was executable', which is the opposite of what it means".format(key)
        )

    if not isinstance(value_basis, ValueBasisAmounts):
        raise TypeError(
            "value_basis must be a ValueBasisAmounts, got {}".format(type(value_basis).__name__)
        )

    retentions = tuple(
        outcome.copy_retention
        for outcome in wallet_outcomes
        if outcome.copy_retention is not None
    )

    executable = tuple(sim for sim in sims if sim.copyable)
    # ``require_finite`` before the comparison, not after. ``contracts.CopySimulation`` validates
    # the fill bounds and the tier but does not refuse a non-finite ``follower_return``, and a
    # ``Decimal("NaN")`` here raises ``InvalidOperation`` from the bare ``> 0`` — an untyped
    # arithmetic error, at the boundary, in place of a refusal naming the field. Every figure that
    # reaches a comparison in this module goes through the seam's refusal first.
    n_positive = sum(
        1
        for sim in executable
        if require_finite(sim.follower_return, "follower_return at ${}".format(key)) > 0
    )

    return CapitalLevelReport(
        capital_level=key,
        n_wallets=len(wallet_outcomes),
        mean_raw_buy_quality=output_ratio(
            mean((o.raw_buy_quality for o in wallet_outcomes), "raw_buy_quality"),
            "mean_raw_buy_quality",
        ),
        mean_follower_adjusted_buy_quality=output_ratio(
            mean(
                (o.follower_adjusted_buy_quality for o in wallet_outcomes),
                "follower_adjusted_buy_quality",
            ),
            "mean_follower_adjusted_buy_quality",
        ),
        mean_copy_retention=optional_output(
            mean(retentions, "copy_retention") if retentions else None,
            RATIO,
            "mean_copy_retention",
        ),
        median_copy_retention=optional_output(
            median(retentions, "copy_retention") if retentions else None,
            RATIO,
            "median_copy_retention",
        ),
        n_retention_reported=len(retentions),
        n_retention_suppressed=len(wallet_outcomes) - len(retentions),
        positive_trade_rate=optional_output(
            rate(n_positive, len(executable), "positive trade rate") if executable else None,
            RATIO,
            "positive_trade_rate",
        ),
        unexecutable_trade_share=output_ratio(
            rate(len(sims) - len(executable), len(sims), "unexecutable trade share"),
            "unexecutable_trade_share",
        ),
        mean_execution_cost_pct=optional_output(
            mean((sim.execution_cost_pct for sim in executable), "execution_cost_pct")
            if executable
            else None,
            PERCENTAGE_POINTS,
            "mean_execution_cost_pct",
        ),
        n_simulated=len(sims),
        n_executable=len(executable),
        n_positive=n_positive,
        realized_share=output_ratio(value_basis.realized_share, "realized_share"),
        marked_share=output_ratio(value_basis.marked_share, "marked_share"),
        dead_share=output_ratio(value_basis.dead_share, "dead_share"),
    )


def report_capital_ladder(level_reports):
    """All five §10 levels, checked for completeness and ordered."""
    reports = sorted(tuple(level_reports), key=lambda report: report.capital_level)
    for report in reports:
        if not isinstance(report, CapitalLevelReport):
            raise TypeError(
                "the capital ladder holds CapitalLevelReport rows, got {}".format(
                    type(report).__name__
                )
            )
    return CapitalLadderReport(levels=tuple(reports))
