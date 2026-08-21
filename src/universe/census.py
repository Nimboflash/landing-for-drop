"""The account-level census: N considered, M admitted, and a rule-attributed account of N − M.

This is ``pipeline/census.py``'s sentence one population up. There it is *N transactions went in, M
trades came out*; here it is *N accounts were screened, M entered the universe, and every one of
the N − M carries the name of the rule that refused it.*

The reconciliation is enforced in ``__post_init__`` rather than asserted in a report, for
``pipeline.census``'s own reason: a report is written once and a constructor runs on every result.
Ticket 25's "there is no unattributed exclusion bucket" is therefore two things together — the
closed :class:`~universe.eligibility.ExclusionRule` enum, which gives an unattributed exclusion
nothing to be spelled with, and this arithmetic, which refuses a census in which one exists anyway.

``unmeasurable_outside_warehouse`` is typed ``None`` and is never an ``int``. Accounts with fewer
than :data:`~universe.protocol.POTENTIAL_BUY_FLOOR` potential buys were never returned by the
warehouse, so their count is **unknowable** — and ``CoverageReport``'s precedent is that an
unmeasurable figure is ``None`` and never ``0``. That population is not necessarily small and its
direction is not neutral: an account with 8 vendor-visible potential buys and 25 correctly-netted
valid buys is invisible to this design, and the vendors decode Safes, 4337 accounts and exotic
routes worst — which is exactly the direction ticket 25 says to be careful about.

What this module does not guarantee: it reconciles the population the warehouse *returned*. It
says nothing about the query that produced it, and ``considered`` is a number the caller supplies.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from contracts import ContractError

from .eligibility import (
    RULE_FAMILY,
    BoundaryMovement,
    EligibilityVerdict,
    ExclusionFamily,
    ExclusionRule,
)
from .observation import VendorMutability
from .protocol import POTENTIAL_BUY_FLOOR, WindowKey, require_pre_t0_int

#: §6.1's reporting order for the four families.
FAMILY_ORDER = (
    ExclusionFamily.THRESHOLD,
    ExclusionFamily.INFRASTRUCTURE,
    ExclusionFamily.AUTOMATION,
    ExclusionFamily.COVERAGE,
)


@dataclass(frozen=True)
class RuleCount:
    """One exclusion rule and how many accounts it took, as a nominal pair.

    Replaces ``Dict[ExclusionRule, int]``. A mapping on a selection path is a tunnel: it accepts any
    key and any value, nothing declares what it holds, and the audit named container laundering as
    the most dangerous of the fifteen routes because a ``Mapping`` turns the whole type barrier into
    a hope about key names. Here the key space is a closed enum *and* the container is a tuple of a
    declared record, so both halves are nominal.
    """

    rule: ExclusionRule
    count: int

    def __post_init__(self) -> None:
        if not isinstance(self.rule, ExclusionRule):
            raise TypeError(
                "a RuleCount is keyed by an ExclusionRule, got {}".format(type(self.rule).__name__))
        value = require_pre_t0_int(self.count, "RuleCount[{}].count".format(self.rule.value))
        if value < 0:
            raise ValueError("RuleCount[{}] is {}".format(self.rule.value, value))


class UnattributedExclusion(ContractError):
    """The census does not reconcile: accounts left the population with no rule named.

    Not a status. A census that does not reconcile has no meaning to carry — the eligible universe
    size it reports is the number §6.5 derives the selected wallet count from, so a population that
    has silently lost members produces a basket drawn at a selection pressure nobody measured.
    ``pipeline.census.ClassificationCensus`` raises on the same shape.
    """


@dataclass(frozen=True)
class UniverseCensus:
    """One window's account ledger, refusing to exist unless it adds up.

    ``exclusions_by_rule`` carries **every** :class:`~universe.eligibility.ExclusionRule`, including
    the zeroes. That is ``ClassificationCensus``'s rule: a census that omits what it never saw
    cannot be differenced against the next run's, and an absent key cannot tell "nobody was excluded
    by this rule" from "nobody applied it".
    """

    window_key: WindowKey
    considered: int
    admitted_count: int
    exclusions_by_rule: Tuple[RuleCount, ...]
    movement: BoundaryMovement
    #: Accounts excluded on a label whose source recomputes it — the mutable-label bias exposure.
    mutable_label_exclusions: int = 0
    #: Always ``None``. Accounts below the warehouse floor were never returned, so their number is
    #: unknowable rather than zero. It is a field so that the unknown is *published*.
    unmeasurable_outside_warehouse: Optional[int] = None

    def __post_init__(self) -> None:
        if not isinstance(self.window_key, WindowKey):
            raise TypeError("UniverseCensus.window_key must be a WindowKey")
        for name in ("considered", "admitted_count", "mutable_label_exclusions"):
            value = require_pre_t0_int(getattr(self, name), "UniverseCensus.{}".format(name))
            if value < 0:
                raise ValueError("UniverseCensus.{} is {}".format(name, value))
        if not isinstance(self.movement, BoundaryMovement):
            raise TypeError("UniverseCensus.movement must be a BoundaryMovement")
        if self.unmeasurable_outside_warehouse is not None:
            raise ValueError(
                "unmeasurable_outside_warehouse is {}; it must stay None. Accounts with fewer than "
                "{} potential buys are never returned by the warehouse, so their count is not "
                "something this run measured — and a 0 there would read as 'nobody was below the "
                "floor', which is the opposite of what is known.".format(
                    self.unmeasurable_outside_warehouse, POTENTIAL_BUY_FLOOR
                )
            )

        entries = tuple(self.exclusions_by_rule)
        for entry in entries:
            if type(entry) is not RuleCount:
                raise TypeError(
                    "exclusions_by_rule holds RuleCount values, got {}".format(
                        type(entry).__name__)
                )
        if len({entry.rule for entry in entries}) != len(entries):
            raise UnattributedExclusion(
                "the census counts a rule twice; two answers to one tally means something must "
                "choose between them, and nothing is permitted to"
            )
        counts = {entry.rule: entry.count for entry in entries}
        missing = sorted(r.value for r in ExclusionRule if r not in counts)
        if missing:
            raise UnattributedExclusion(
                "the census omits exclusion rule(s): {}. Every rule is carried whether or not it "
                "fired, so this run's census can be differenced against the next one's.".format(
                    ", ".join(missing)
                )
            )
        object.__setattr__(
            self, "exclusions_by_rule",
            tuple(sorted(entries, key=lambda entry: entry.rule.value)),
        )

        excluded = sum(counts.values())
        if self.admitted_count + excluded != self.considered:
            raise UnattributedExclusion(
                "{} account(s) were considered in window {}; {} were admitted and {} are "
                "attributed to a named rule, leaving {} unaccounted for. Ticket 25 forbids an "
                "unattributed exclusion bucket, and the missing accounts are exactly that bucket: "
                "they shrink the eligible universe, which is the number §6.5 derives the selected "
                "wallet count from, so the basket would be drawn at a selection pressure nobody "
                "measured.".format(
                    self.considered, self.window_key.value, self.admitted_count, excluded,
                    self.considered - self.admitted_count - excluded,
                )
            )
        if self.movement.retained_by_buffer > self.admitted_count:
            raise UnattributedExclusion(
                "the buffer is reported as retaining {} account(s) into a universe of {}. A "
                "retained account is by definition an admitted one, so the buffer's headline count "
                "would exceed the population it is a property of.".format(
                    self.movement.retained_by_buffer, self.admitted_count
                )
            )
        if self.mutable_label_exclusions > excluded:
            raise UnattributedExclusion(
                "{} exclusion(s) are attributed to a mutable label against {} exclusions in "
                "total".format(self.mutable_label_exclusions, excluded)
            )

    @property
    def excluded_total(self) -> int:
        return sum(entry.count for entry in self.exclusions_by_rule)

    def count_for(self, rule: ExclusionRule) -> int:
        """How many accounts one named rule took. Every rule is carried, so this never guesses."""
        for entry in self.exclusions_by_rule:
            if entry.rule is rule:
                return entry.count
        raise KeyError(
            "the census carries no entry for {}, which cannot happen for a constructed "
            "census".format(getattr(rule, "value", rule))
        )

    def by_family(self, family: ExclusionFamily) -> int:
        """Exclusions in one of §6.1's four reporting families, including the zeroes.

        A function of one family rather than a mapping of all four, for the same reason
        ``exclusions_by_rule`` stopped being a dict: a returned mapping is a mutable copy of a
        census that spent its whole ``__post_init__`` proving it reconciles.
        """
        if not isinstance(family, ExclusionFamily):
            raise TypeError("by_family takes an ExclusionFamily, got {}".format(
                type(family).__name__))
        return sum(entry.count for entry in self.exclusions_by_rule
                   if RULE_FAMILY[entry.rule] is family)

    @property
    def excluded_infrastructure(self) -> int:
        """§6.1's own line. Precedence is infrastructure-first so this count is not understated."""
        return self.by_family(ExclusionFamily.INFRASTRUCTURE)


def build_census(verdicts: Tuple[EligibilityVerdict, ...], considered: int,
                 movement: BoundaryMovement, window_key: WindowKey) -> "UniverseCensus":
    """Tally one window's verdicts into a census that has to reconcile.

    :param verdicts: every :class:`~universe.eligibility.EligibilityVerdict` for this window,
        including the stage-one exclusions the warehouse screen produced. Both stages go in one
        ledger, because an account refused before enrichment is as much a member of ``N − M`` as
        one refused after it.
    :param considered: the size of the population the verdicts are an account of, **supplied**
        rather than derived from ``len(verdicts)``. Deriving it would make the reconciliation
        vacuous: the census would be a tally of whatever arrived, and an account lost upstream
        would balance perfectly.
    :param movement: the :class:`~universe.eligibility.BoundaryMovement` for the same window.
    :param window_key: the §6.3 window. Required rather than inferred — a verdict is a statement
        about an account and carries no window, and inferring one from a batch would let two
        windows' verdicts be tallied into one ledger with nothing to notice.
    :raises UnattributedExclusion: on a duplicate account, or when the tally does not reconcile.
    """
    counts = {rule: 0 for rule in ExclusionRule}
    admitted = 0
    mutable_labels = 0
    seen = set()
    for verdict in verdicts:
        if not isinstance(verdict, EligibilityVerdict):
            raise TypeError(
                "the census is built from EligibilityVerdict values, got {}. A bare pair of "
                "account and rule could be neither admitted nor excluded, which is the "
                "unattributed bucket arriving through the argument.".format(type(verdict).__name__)
            )
        if verdict.account in seen:
            raise UnattributedExclusion(
                "{} has two verdicts. One account counted twice moves the eligible universe size, "
                "and therefore the selected wallet count, and the duplicate is invisible in "
                "both.".format(verdict.account)
            )
        seen.add(verdict.account)
        if verdict.is_admitted:
            admitted += 1
        else:
            counts[verdict.exclusion.rule] += 1
            if verdict.exclusion.label_provenance is VendorMutability.MUTABLE_VENDOR_FIELD:
                mutable_labels += 1

    return UniverseCensus(
        window_key=window_key,
        considered=considered,
        admitted_count=admitted,
        exclusions_by_rule=tuple(
            RuleCount(rule=rule, count=count) for rule, count in sorted(
                counts.items(), key=lambda item: item[0].value)),
        movement=movement,
        mutable_label_exclusions=mutable_labels,
    )
