"""Ticket 25: the two-stage buffer, and §6.2's infrastructure test as a table of named predicates.

The two stages
--------------

Stage one is the **warehouse filter**. It admits accounts on ``POTENTIAL`` buys in
``[10, 1200]`` from a :class:`WarehouseRow`, a type with **no field for a transaction history** —
filter-early / enrich-late is a property of the entry type rather than a discipline anybody has to
keep. Stage two decides eligibility on ``VALID`` buys in ``[20, 1000]`` after netting.

The gap between the two pairs is the buffer, and it is load-bearing. Filtering at 20-1,000 in the
first pass silently drops every account netting would have moved across the boundary, and the drop
is invisible because those accounts were never returned. :class:`BoundaryMovement` counts the
movement in both directions, which is ticket 25's "count that moved across the boundary".

Infrastructure by test, not by name list
----------------------------------------

§6.2's test is one sentence: *the account must represent one decision-maker or one portfolio, not
infrastructure passing through other people's transactions.* Routers, aggregators, relayers,
bundlers, bridges and CEX hot wallets are not six rules — they are one measurable consequence of
that sentence, ``SETTLES_FOR_MULTIPLE_PRINCIPALS``. Treasuries and public vaults are another,
``PUBLIC_CAPITAL_POOL``. Each rule in :data:`EXCLUSION_CRITERIA` states the exact measurable test
that fires it.

No unattributed exclusion
-------------------------

Ticket 25's "every excluded account is attributable to a named rule; there is no unattributed
exclusion bucket" is not a check in this module. It is the **absence of a value**:
:class:`ExclusionRule` is closed with no ``OTHER`` and no ``UNKNOWN`` member, and
:attr:`Exclusion.rule` has no default — so an unattributed exclusion has nothing to be spelled
with. :class:`universe.census.UniverseCensus` then refuses to be constructed unless the per-rule
counts reconcile against the population.

What this module does not guarantee
-----------------------------------

The infrastructure test is only as good as evidence that does not exist yet. Nothing here has
touched chain data; ``distinct_beneficiaries``, ``share_token_holders`` and
``controller_identified`` are fields a future data layer must populate honestly, and a
systematically understated beneficiary count would admit a public vault under a rule table that
looks rigorous. Ticket 25's golden-set spot check is the only control on that, and it is a sample.

Relatedly, the behavioural-versus-label line is softer than the table makes it look. If the
behavioural predicates turn out weak in practice, the labelled sets will do most of the work and
this module will be a name list with a better docstring. The per-rule census counts make that
visible; nothing detects it.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple

from contracts import AccountType, ContractError, divide

from .observation import AccountEvidence, AccountWindowObservation, VendorMutability
from .protocol import (
    POTENTIAL_BUY_CEILING,
    POTENTIAL_BUY_FLOOR,
    VALID_BUY_CEILING,
    VALID_BUY_FLOOR,
    WindowKey,
    normalise_selection_account,
    require_pre_t0_int,
)
from .provenance import PRE_T0_ZERO, PreT0Decimal, require_pre_t0_value

#: §6.2's two published ratio thresholds, as pre-registered pre-T0 constants rather than bare
#: ``Decimal`` literals on the dataclass. Both of them decide an exclusion, so both of them
#: influence the composition of the candidate universe — and the invariant is about every value that
#: does, not only about the ones that look like measurements. Written through
#: :meth:`universe.provenance.PreT0Decimal.pre_registered`, which is a differently-named call that
#: says in a diff that a constant is being asserted rather than a number measured.
PRE_T0_LIKELY_BOTS_FAILED_SHARE = PreT0Decimal.pre_registered(
    "0.9", "§6.2 published: Dune likely_bots failed/total > 0.9")
PRE_T0_MARKET_MAKING_TWO_SIDED_SHARE = PreT0Decimal.pre_registered(
    "0.5", "named here because §6.2 does not name it: market-making two-sided quote share")

#: §6.2's test, quoted once. Every criterion below is a measurable consequence of this sentence.
INCLUSION_TEST = (
    "the account must represent one decision-maker or one portfolio, not infrastructure passing "
    "through other people's transactions"
)


class ExclusionFamily(str, Enum):
    """The four families §6.1's required counts are reported in."""

    THRESHOLD = "THRESHOLD"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    AUTOMATION = "AUTOMATION"
    COVERAGE = "COVERAGE"


class ExclusionRule(str, Enum):
    """Every way an account leaves the population. Closed, with no ``OTHER`` and no ``UNKNOWN``.

    That closure *is* ticket 25's no-unattributed-exclusion criterion. A residual member would be
    the bucket, and it would fill up quietly.

    ``ENRICHMENT_INCOMPLETE`` is deliberately a **named** rule in the ``COVERAGE`` family rather
    than a residual: the account nobody could net stays visible in the same census as the account
    that was refused, neither disappears, and it stays out of the infrastructure count where it
    would flatter the exclusion story.
    """

    # warehouse stage — decided on potential buys, before any netting
    POTENTIAL_BUYS_BELOW_FLOOR = "POTENTIAL_BUYS_BELOW_FLOOR"
    POTENTIAL_BUYS_ABOVE_CEILING = "POTENTIAL_BUYS_ABOVE_CEILING"

    # netted stage — decided on valid buys
    VALID_BUYS_BELOW_FLOOR = "VALID_BUYS_BELOW_FLOOR"
    VALID_BUYS_ABOVE_CEILING = "VALID_BUYS_ABOVE_CEILING"

    # infrastructure — §6.2's test
    SETTLES_FOR_MULTIPLE_PRINCIPALS = "SETTLES_FOR_MULTIPLE_PRINCIPALS"
    ECONOMIC_CONTROLLER_UNIDENTIFIED = "ECONOMIC_CONTROLLER_UNIDENTIFIED"
    PUBLIC_CAPITAL_POOL = "PUBLIC_CAPITAL_POOL"
    MARKET_MAKING_INVENTORY = "MARKET_MAKING_INVENTORY"
    DEPLOYER_TRADING_OWN_TOKEN = "DEPLOYER_TRADING_OWN_TOKEN"

    # published labelled sets and heuristics
    LABELLED_MEV = "LABELLED_MEV"
    LABELLED_SANDWICH = "LABELLED_SANDWICH"
    LABELLED_ARBITRAGE = "LABELLED_ARBITRAGE"
    BOT_HEURISTIC = "BOT_HEURISTIC"

    # cadence
    NON_HUMAN_TRADING_CADENCE = "NON_HUMAN_TRADING_CADENCE"

    # scope
    OUTSIDE_TRAINING_WINDOW = "OUTSIDE_TRAINING_WINDOW"

    # coverage
    ENRICHMENT_INCOMPLETE = "ENRICHMENT_INCOMPLETE"


#: The exact measurable test each rule applies. Prose, but prose a reviewer can check a predicate
#: against — a rule whose criterion nobody wrote down is a name-list exclusion wearing a test's
#: clothes.
EXCLUSION_CRITERIA = {
    ExclusionRule.POTENTIAL_BUYS_BELOW_FLOOR:
        "potential buys < {} at the warehouse filter (§6.2 lower bound, buffered)".format(
            POTENTIAL_BUY_FLOOR),
    ExclusionRule.POTENTIAL_BUYS_ABOVE_CEILING:
        "potential buys > {} at the warehouse filter (§6.2 upper bound, buffered)".format(
            POTENTIAL_BUY_CEILING),
    ExclusionRule.VALID_BUYS_BELOW_FLOOR:
        "valid buys after netting < {} (§6.2: the lower bound controls selection noise)".format(
            VALID_BUY_FLOOR),
    ExclusionRule.VALID_BUYS_ABOVE_CEILING:
        "valid buys after netting > {} (§6.2: ~5.5/day, excludes likely-automated "
        "behaviour). Applied to valid buys, never to total transactions.".format(
            VALID_BUY_CEILING),
    ExclusionRule.SETTLES_FOR_MULTIPLE_PRINCIPALS:
        "distinct beneficiaries above the policy's maximum, or the data layer states the account "
        "settles for other principals. This is the one measurable consequence shared by DEX "
        "routers, aggregator contracts, relayers, bundlers, bridges and CEX hot wallets.",
    ExclusionRule.ECONOMIC_CONTROLLER_UNIDENTIFIED:
        "the economic controller was looked for and not identified (§6.2's catch-all). Evidence "
        "of None means nobody looked, and the rule does not fire on it.",
    ExclusionRule.PUBLIC_CAPITAL_POOL:
        "a share token is issued against the account's capital and held by more than the policy's "
        "maximum number of holders — protocol treasuries and public vaults.",
    ExclusionRule.MARKET_MAKING_INVENTORY:
        "two-sided quote share at or above the policy threshold — market-making contracts.",
    ExclusionRule.DEPLOYER_TRADING_OWN_TOKEN:
        "the account deployed at least one token it also traded (§6.2, verbatim).",
    ExclusionRule.LABELLED_MEV:
        "membership of labels.mev_ethereum.",
    ExclusionRule.LABELLED_SANDWICH:
        "membership of labels.sandwich_attackers or dex.sandwiches.",
    ExclusionRule.LABELLED_ARBITRAGE:
        "membership of labels.arbitrage_traders or dex.atomic_arbitrages.",
    ExclusionRule.BOT_HEURISTIC:
        "Dune's likely_bots macro: (>= 100 tx AND >= 25 tx/hour) OR (>= 2,500 tx AND <= 30 "
        "distinct senders) OR failed/total > 0.9.",
    ExclusionRule.NON_HUMAN_TRADING_CADENCE:
        "the inverse human filter: day-of-week skewness of exactly zero, or mean inter-trade gap "
        "above the policy's 60-minute bound. Smart accounts are exempt — see "
        "SMART_ACCOUNT_EXEMPT_RULES.",
    ExclusionRule.OUTSIDE_TRAINING_WINDOW:
        "the observation is keyed to a different §6.3 window from the screen it was classified "
        "against.",
    ExclusionRule.ENRICHMENT_INCOMPLETE:
        "netting did not complete for this account, so its valid-buy count is not a measurement. "
        "A named coverage rule rather than a residual bucket, and deliberately outside the "
        "infrastructure family, where it would flatter the exclusion story.",
}

RULE_FAMILY = {
    ExclusionRule.POTENTIAL_BUYS_BELOW_FLOOR: ExclusionFamily.THRESHOLD,
    ExclusionRule.POTENTIAL_BUYS_ABOVE_CEILING: ExclusionFamily.THRESHOLD,
    ExclusionRule.VALID_BUYS_BELOW_FLOOR: ExclusionFamily.THRESHOLD,
    ExclusionRule.VALID_BUYS_ABOVE_CEILING: ExclusionFamily.THRESHOLD,
    ExclusionRule.SETTLES_FOR_MULTIPLE_PRINCIPALS: ExclusionFamily.INFRASTRUCTURE,
    ExclusionRule.ECONOMIC_CONTROLLER_UNIDENTIFIED: ExclusionFamily.INFRASTRUCTURE,
    ExclusionRule.PUBLIC_CAPITAL_POOL: ExclusionFamily.INFRASTRUCTURE,
    ExclusionRule.MARKET_MAKING_INVENTORY: ExclusionFamily.INFRASTRUCTURE,
    ExclusionRule.DEPLOYER_TRADING_OWN_TOKEN: ExclusionFamily.INFRASTRUCTURE,
    ExclusionRule.LABELLED_MEV: ExclusionFamily.AUTOMATION,
    ExclusionRule.LABELLED_SANDWICH: ExclusionFamily.AUTOMATION,
    ExclusionRule.LABELLED_ARBITRAGE: ExclusionFamily.AUTOMATION,
    ExclusionRule.BOT_HEURISTIC: ExclusionFamily.AUTOMATION,
    ExclusionRule.NON_HUMAN_TRADING_CADENCE: ExclusionFamily.AUTOMATION,
    ExclusionRule.OUTSIDE_TRAINING_WINDOW: ExclusionFamily.THRESHOLD,
    ExclusionRule.ENRICHMENT_INCOMPLETE: ExclusionFamily.COVERAGE,
}

# Checked at import, and raised as an ImportError rather than asserted. ``python -O`` strips an
# assert, and a rule with no stated criterion — or with no family — is a name-list exclusion
# wearing a test's clothes. ``reporting/boundary.py`` checks its scale table the same way.
for _table, _label in ((EXCLUSION_CRITERIA, "EXCLUSION_CRITERIA"), (RULE_FAMILY, "RULE_FAMILY")):
    _missing = sorted(r.value for r in ExclusionRule if r not in _table)
    if _missing:
        raise ImportError(
            "{} does not cover exclusion rule(s): {}. Ticket 25 requires every excluded account to "
            "be attributable to a *named* rule, and a rule with no stated criterion or no family "
            "is a name list with better manners.".format(_label, ", ".join(_missing))
        )
    _stray = sorted(getattr(r, "value", str(r)) for r in _table if not isinstance(r, ExclusionRule))
    if _stray:
        raise ImportError("{} names things that are not ExclusionRules: {}".format(_label, _stray))

#: Which rule is *reported* when several fire, pinned INFRASTRUCTURE-FIRST.
#:
#: §6.1 requires "excluded infrastructure contracts" as its own line, and a router excluded as
#: ``VALID_BUYS_ABOVE_CEILING`` understates that line while overstating the automation one. Nothing
#: is destroyed by the choice: :attr:`EligibilityVerdict.also_matched` carries every rule that fired
#: and did not win, so a reviewer can recompute the census under a different precedence without
#: re-running anything.
RULE_PRECEDENCE = (
    ExclusionRule.SETTLES_FOR_MULTIPLE_PRINCIPALS,
    ExclusionRule.PUBLIC_CAPITAL_POOL,
    ExclusionRule.MARKET_MAKING_INVENTORY,
    ExclusionRule.DEPLOYER_TRADING_OWN_TOKEN,
    ExclusionRule.ECONOMIC_CONTROLLER_UNIDENTIFIED,
    ExclusionRule.LABELLED_MEV,
    ExclusionRule.LABELLED_SANDWICH,
    ExclusionRule.LABELLED_ARBITRAGE,
    ExclusionRule.BOT_HEURISTIC,
    ExclusionRule.NON_HUMAN_TRADING_CADENCE,
    ExclusionRule.OUTSIDE_TRAINING_WINDOW,
    ExclusionRule.ENRICHMENT_INCOMPLETE,
    ExclusionRule.POTENTIAL_BUYS_BELOW_FLOOR,
    ExclusionRule.POTENTIAL_BUYS_ABOVE_CEILING,
    ExclusionRule.VALID_BUYS_BELOW_FLOOR,
    ExclusionRule.VALID_BUYS_ABOVE_CEILING,
)

if sorted(r.value for r in RULE_PRECEDENCE) != sorted(r.value for r in ExclusionRule):
    raise ImportError(
        "RULE_PRECEDENCE does not order every ExclusionRule exactly once; a rule missing from it "
        "would win or lose a tie by dictionary order"
    )

#: §6.2's human filter "excludes all contracts and must be modified to retain Safes and smart
#: accounts". The exemption is deliberately **narrow**: a Safe running a market-making book is
#: still excluded by ``MARKET_MAKING_INVENTORY``. Exempting smart accounts from everything would
#: turn a retention rule into a bypass.
SMART_ACCOUNT_EXEMPT_RULES = frozenset({
    ExclusionRule.NON_HUMAN_TRADING_CADENCE,
    ExclusionRule.ECONOMIC_CONTROLLER_UNIDENTIFIED,
})

#: The account types the exemption applies to. §6.2 retains all three, and their portfolio identity
#: is the account itself.
SMART_ACCOUNT_TYPES = (AccountType.SAFE, AccountType.ERC4337)

#: Account types that may be admitted at all. ``INFRASTRUCTURE`` and ``UNKNOWN`` are excluded by
#: definition — an account nobody could type is one whose economic controller was not identified.
ADMISSIBLE_ACCOUNT_TYPES = (
    AccountType.EOA,
    AccountType.SAFE,
    AccountType.ERC4337,
    AccountType.OTHER_CONTRACT,
)


@dataclass(frozen=True)
class HeuristicModification:
    """One published heuristic, and exactly what was changed about it, and why.

    Ticket 25: "every modification made to them is recorded with its reason". Required non-empty in
    :class:`universe.step0.Step0Measurement` whenever the corresponding rule is enabled, so the
    record is a construction invariant rather than a note somebody meant to write.
    """

    source: str
    published_rule: str
    modification: str
    reason: str

    def __post_init__(self) -> None:
        for name in ("source", "published_rule", "modification", "reason"):
            value = getattr(self, name)
            if not value or not str(value).strip():
                raise ValueError(
                    "a heuristic modification must state its {}; ticket 25 requires every "
                    "modification recorded *with its reason*, and a blank field is the "
                    "modification nobody can contest".format(name)
                )


HEURISTIC_MODIFICATIONS = (
    HeuristicModification(
        source="Dune spellbook",
        published_rule="likely_bots",
        modification="applied unchanged as ExclusionRule.BOT_HEURISTIC",
        reason=(
            "§6.2 names the macro's three legs verbatim and this package reuses them as published; "
            "restating them with different bounds would be a new heuristic under an old name"
        ),
    ),
    HeuristicModification(
        source="Dune spellbook",
        published_rule="inverse human filter (day-of-week skewness != 0, mean inter-trade gap > "
                       "60 minutes)",
        modification=(
            "Safes and ERC-4337 accounts are exempt from NON_HUMAN_TRADING_CADENCE; the filter is "
            "applied to EOAs and other contract accounts unchanged"
        ),
        reason=(
            "§6.2: the published filter 'excludes all contracts and must be modified to retain "
            "Safes and smart accounts'. The exemption is confined to the cadence rule and to the "
            "controller rule: a Safe running a market-making book is still excluded by "
            "MARKET_MAKING_INVENTORY, because exempting smart accounts from every rule would turn "
            "a retention rule into a bypass"
        ),
    ),
)


@dataclass(frozen=True)
class EligibilityPolicy:
    """§6.2's published thresholds, plus the cuts this design must name because §6.2 does not.

    The policy is hashed into the universe's snapshot identifier, so changing a threshold changes
    the universe's **identity** rather than silently changing its contents.

    The four fields below the published ones are unregistered degrees of freedom being fixed after
    the pre-registration was written. They are recorded as parameters rather than buried in a
    predicate precisely because that is the class of thing this project is arranged against.
    """

    # §6.2, published verbatim
    likely_bots_min_tx: int = 100
    likely_bots_min_tx_per_hour: int = 25
    likely_bots_high_tx: int = 2500
    likely_bots_max_distinct_senders: int = 30
    likely_bots_failed_share: PreT0Decimal = PRE_T0_LIKELY_BOTS_FAILED_SHARE
    human_min_inter_trade_gap_seconds: int = 3600

    # named here because §6.2 does not name them
    max_distinct_beneficiaries: int = 1
    max_share_token_holders: int = 1
    market_making_two_sided_share: PreT0Decimal = PRE_T0_MARKET_MAKING_TWO_SIDED_SHARE

    enable_published_heuristics: bool = True

    def __post_init__(self) -> None:
        for name in ("likely_bots_min_tx", "likely_bots_min_tx_per_hour", "likely_bots_high_tx",
                     "likely_bots_max_distinct_senders", "human_min_inter_trade_gap_seconds",
                     "max_distinct_beneficiaries", "max_share_token_holders"):
            value = require_pre_t0_int(getattr(self, name), "EligibilityPolicy.{}".format(name))
            if value < 0:
                raise ValueError("EligibilityPolicy.{} is {}".format(name, value))
        for name in ("likely_bots_failed_share", "market_making_two_sided_share"):
            object.__setattr__(
                self, name,
                require_pre_t0_value(getattr(self, name), "EligibilityPolicy.{}".format(name)),
            )
        if not isinstance(self.enable_published_heuristics, bool):
            raise TypeError("EligibilityPolicy.enable_published_heuristics must be a bool")


DEFAULT_POLICY = EligibilityPolicy()


class ExclusionStage(str, Enum):
    """Which of the two passes decided the account."""

    WAREHOUSE = "warehouse"
    NETTED = "netted"


@dataclass(frozen=True)
class WarehouseRow:
    """What the warehouse returns for one account in stage one.

    **There is no transaction field on this type.** Filter-early / enrich-late is a property of the
    entry type rather than a discipline anybody has to keep: a stage-one predicate cannot read a
    history it has no way to name, so full histories are extracted only for the accounts this
    screen admits.
    """

    address: str
    potential_buys: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "address", normalise_selection_account(self.address))
        value = require_pre_t0_int(self.potential_buys, "WarehouseRow.potential_buys")
        if value < 0:
            raise ValueError(
                "{} has {} potential buys; a count is a magnitude".format(self.address, value)
            )


@dataclass(frozen=True)
class Exclusion:
    """One account refused entry, with the named rule that refused it.

    ``evidence`` is required and non-empty. An unexplained drop is prohibited outright by the
    failure policy — ``pipeline.census.ExclusionRecord`` says so for transactions, and this is that
    rule one population up.

    ``label_provenance`` is **required** when the rule is one of the labelled sets, so a
    mutable-label exclusion is visibly counted rather than indistinguishable from a point-in-time
    one. That count is the bias exposure §6.2's continuously recomputed label sets create.
    """

    account: str
    stage: ExclusionStage
    rule: ExclusionRule
    evidence: Tuple[str, ...]
    label_provenance: Optional[VendorMutability] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "account", normalise_selection_account(self.account))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if not isinstance(self.stage, ExclusionStage):
            raise TypeError("Exclusion.stage must be an ExclusionStage")
        if not isinstance(self.rule, ExclusionRule):
            raise TypeError(
                "Exclusion.rule must be an ExclusionRule, got {}. The enum is closed with no OTHER "
                "and no UNKNOWN member so that an unattributed exclusion has nothing to be spelled "
                "with.".format(type(self.rule).__name__)
            )
        if not self.evidence or any(not str(e).strip() for e in self.evidence):
            raise ValueError(
                "{} was excluded under {} with no evidence. An unexplained drop is prohibited "
                "outright by the failure policy: the account must be traceable back to the "
                "measurement that refused it.".format(self.account, self.rule.value)
            )
        if self.rule in LABELLED_RULES and self.label_provenance is None:
            raise ValueError(
                "{} was excluded under {}, a published label set, with no label_provenance. §6.2's "
                "label sets are continuously recomputed, so excluding on today's label may be "
                "excluding for something the account did after T0 — look-ahead in the exclusion "
                "direction. Counted and reported rather than refused, which is only possible if "
                "every such exclusion says which it is.".format(self.account, self.rule.value)
            )
        if (self.label_provenance is not None
                and not isinstance(self.label_provenance, VendorMutability)):
            raise TypeError("Exclusion.label_provenance must be a VendorMutability or None")


LABELLED_RULES = frozenset({
    ExclusionRule.LABELLED_MEV,
    ExclusionRule.LABELLED_SANDWICH,
    ExclusionRule.LABELLED_ARBITRAGE,
})

#: Which §6.2 labelled set feeds which rule.
LABEL_SETS = {
    "labels.mev_ethereum": ExclusionRule.LABELLED_MEV,
    "labels.sandwich_attackers": ExclusionRule.LABELLED_SANDWICH,
    "dex.sandwiches": ExclusionRule.LABELLED_SANDWICH,
    "labels.arbitrage_traders": ExclusionRule.LABELLED_ARBITRAGE,
    "dex.atomic_arbitrages": ExclusionRule.LABELLED_ARBITRAGE,
}


@dataclass(frozen=True)
class Admission:
    """One account admitted to the eligible universe, with the pre-T0 facts later stages need.

    ``crossed_boundary`` is ``True`` when the account is eligible on valid buys but was **not**
    within ``[20, 1000]`` on potential buys. That is ticket 25's "count that moved across the
    boundary", recorded per account rather than only in aggregate, so a reviewer can list them.
    """

    account: str
    account_type: AccountType
    valid_buys: int
    potential_buys: int
    active_days: int
    buy_volume_usd: PreT0Decimal
    wallet_age_days: int
    crossed_boundary: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "account", normalise_selection_account(self.account))
        if self.account_type not in ADMISSIBLE_ACCOUNT_TYPES:
            raise ValueError(
                "{} was admitted as {}; only {} may enter the eligible universe. INFRASTRUCTURE "
                "and UNKNOWN are excluded by definition, and admitting one would put an account "
                "nobody could type into the population §6.6 matches on.".format(
                    self.account, self.account_type.value,
                    ", ".join(t.value for t in ADMISSIBLE_ACCOUNT_TYPES),
                )
            )
        if not (VALID_BUY_FLOOR <= self.valid_buys <= VALID_BUY_CEILING):
            raise ValueError(
                "{} was admitted with {} valid buys, outside §6.2's [{}, {}]".format(
                    self.account, self.valid_buys, VALID_BUY_FLOOR, VALID_BUY_CEILING
                )
            )
        if not isinstance(self.crossed_boundary, bool):
            raise TypeError("Admission.crossed_boundary must be a bool")
        object.__setattr__(
            self, "buy_volume_usd",
            require_pre_t0_value(self.buy_volume_usd, "{}.buy_volume_usd".format(self.account)),
        )


@dataclass(frozen=True)
class EligibilityVerdict:
    """Exactly one of admitted or excluded, and never both and never neither.

    "Neither" is the unattributed bucket. "Both" is an account counted twice. Both are
    unrepresentable rather than checked later, because a census that has already been built from
    them has nothing left to reconcile against.

    ``also_matched`` carries every rule that fired and did not win under :data:`RULE_PRECEDENCE`,
    so the census can be recomputed under a different precedence without re-running anything.
    """

    account: str
    admitted: Optional[Admission] = None
    exclusion: Optional[Exclusion] = None
    also_matched: Tuple[ExclusionRule, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "account", normalise_selection_account(self.account))
        object.__setattr__(self, "also_matched", tuple(self.also_matched))
        if (self.admitted is None) == (self.exclusion is None):
            raise ValueError(
                "{} is {} — a verdict must be exactly one of admitted or excluded. Neither is the "
                "unattributed exclusion bucket ticket 25 forbids; both is one account counted "
                "twice, in a population whose size decides the selected wallet count.".format(
                    self.account,
                    "both admitted and excluded" if self.admitted is not None
                    else "neither admitted nor excluded",
                )
            )
        if self.admitted is not None and self.admitted.account != self.account:
            raise ValueError("verdict for {} carries an admission for {}".format(
                self.account, self.admitted.account))
        if self.exclusion is not None and self.exclusion.account != self.account:
            raise ValueError("verdict for {} carries an exclusion for {}".format(
                self.account, self.exclusion.account))
        for rule in self.also_matched:
            if not isinstance(rule, ExclusionRule):
                raise TypeError("also_matched holds ExclusionRule values")
        if self.exclusion is not None and self.exclusion.rule in self.also_matched:
            raise ValueError(
                "{}: the winning rule {} also appears in also_matched, which would count it "
                "twice under a recomputed precedence".format(self.account, self.exclusion.rule.value)
            )

    @property
    def is_admitted(self) -> bool:
        return self.admitted is not None


@dataclass(frozen=True)
class WarehouseScreen:
    """Stage one's result: who was admitted for enrichment, and who was refused before it.

    Carries ``rows_screened`` so the census can reconcile against the whole of stage one rather
    than against the part of it that survived.
    """

    window_key: WindowKey
    admitted: Tuple[WarehouseRow, ...]
    exclusions: Tuple[Exclusion, ...]
    rows_screened: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "admitted", tuple(self.admitted))
        object.__setattr__(self, "exclusions", tuple(self.exclusions))
        if not isinstance(self.window_key, WindowKey):
            raise TypeError("WarehouseScreen.window_key must be a WindowKey")
        require_pre_t0_int(self.rows_screened, "WarehouseScreen.rows_screened")
        if len(self.admitted) + len(self.exclusions) != self.rows_screened:
            raise ValueError(
                "the warehouse screen saw {} row(s) but accounts for {} admitted plus {} excluded. "
                "A row that is neither is a candidate that vanished before anything could name a "
                "rule for it.".format(
                    self.rows_screened, len(self.admitted), len(self.exclusions)
                )
            )

    @property
    def admitted_addresses(self) -> frozenset:
        return frozenset(row.address for row in self.admitted)

    def potential_buys(self, address: str) -> Optional[int]:
        for row in self.admitted:
            if row.address == address:
                return row.potential_buys
        return None


def screen_warehouse(window_key: WindowKey,
                     rows: Tuple["WarehouseRow", ...]) -> "WarehouseScreen":
    """Stage one: admit ``[10, 1200]`` potential buys, and name a rule for everything else.

    :param window_key: the §6.3 window this screen belongs to. Carried so that
        :func:`classify_account` can refuse an observation from a different window by a named rule
        rather than by silently classifying it against the wrong calendar.
    :param rows: :class:`WarehouseRow` values. A duplicate address is refused: two rows for one
        account would be screened twice and could be admitted and excluded at once, and nobody can
        say which row is the row.
    """
    if not isinstance(window_key, WindowKey):
        raise TypeError("screen_warehouse needs a WindowKey, got {}".format(type(window_key).__name__))
    admitted = []
    exclusions = []
    seen = set()
    screened = 0
    for row in rows:
        if type(row) is not WarehouseRow:
            raise TypeError(
                "the warehouse screen takes WarehouseRow values, got {}. The type has no field for "
                "a transaction history, which is what makes filter-early/enrich-late a property of "
                "the entry rather than a habit.".format(type(row).__name__)
            )
        if row.address in seen:
            raise ValueError(
                "{} appears twice in the warehouse rows. One account with two potential-buy counts "
                "has no answer to 'how many', and supplying both is the evidence that nobody "
                "knows.".format(row.address)
            )
        seen.add(row.address)
        screened += 1
        if row.potential_buys < POTENTIAL_BUY_FLOOR:
            exclusions.append(Exclusion(
                account=row.address, stage=ExclusionStage.WAREHOUSE,
                rule=ExclusionRule.POTENTIAL_BUYS_BELOW_FLOOR,
                evidence=("potential_buys={} < {}".format(row.potential_buys, POTENTIAL_BUY_FLOOR),),
            ))
        elif row.potential_buys > POTENTIAL_BUY_CEILING:
            exclusions.append(Exclusion(
                account=row.address, stage=ExclusionStage.WAREHOUSE,
                rule=ExclusionRule.POTENTIAL_BUYS_ABOVE_CEILING,
                evidence=("potential_buys={} > {}".format(row.potential_buys, POTENTIAL_BUY_CEILING),),
            ))
        else:
            admitted.append(row)
    return WarehouseScreen(
        window_key=window_key,
        admitted=tuple(admitted),
        exclusions=tuple(exclusions),
        rows_screened=screened,
    )


# -- the §6.2 predicates ---------------------------------------------------------
#
# Each returns ``(fired, evidence)``. ``fired`` is False when the evidence is absent, and the
# account is then recorded as *unassessed* for that rule rather than as passing it — see
# ``AccountEvidence``. Every one of them is a measurable consequence of INCLUSION_TEST.


def _settles_for_multiple_principals(evidence: AccountEvidence,
                                     policy: "EligibilityPolicy") -> Tuple[bool, Optional[str]]:
    if evidence.settles_for_other_principals is True:
        return True, "the data layer states this account settles for other principals"
    if (evidence.distinct_beneficiaries is not None
            and evidence.distinct_beneficiaries > policy.max_distinct_beneficiaries):
        return True, "distinct_beneficiaries={} > {}".format(
            evidence.distinct_beneficiaries, policy.max_distinct_beneficiaries)
    return False, None


def _public_capital_pool(evidence: AccountEvidence,
                         policy: "EligibilityPolicy") -> Tuple[bool, Optional[str]]:
    if (evidence.share_token_holders is not None
            and evidence.share_token_holders > policy.max_share_token_holders):
        return True, "share_token_holders={} > {}".format(
            evidence.share_token_holders, policy.max_share_token_holders)
    return False, None


def _market_making_inventory(evidence: AccountEvidence,
                             policy: "EligibilityPolicy") -> Tuple[bool, Optional[str]]:
    if (evidence.two_sided_quote_share is not None
            and evidence.two_sided_quote_share >= policy.market_making_two_sided_share):
        return True, "two_sided_quote_share={} >= {}".format(
            evidence.two_sided_quote_share, policy.market_making_two_sided_share)
    return False, None


def _deployer_trading_own_token(evidence: AccountEvidence,
                                _policy: "EligibilityPolicy") -> Tuple[bool, Optional[str]]:
    if evidence.deployed_tokens_traded is not None and evidence.deployed_tokens_traded > 0:
        return True, "deployed_tokens_traded={}".format(evidence.deployed_tokens_traded)
    return False, None


def _controller_unidentified(evidence: AccountEvidence,
                             _policy: "EligibilityPolicy") -> Tuple[bool, Optional[str]]:
    if evidence.controller_identified is False:
        return True, "the economic controller was looked for and not identified"
    return False, None


def _bot_heuristic(evidence: AccountEvidence,
                   policy: "EligibilityPolicy") -> Tuple[bool, Optional[str]]:
    if not policy.enable_published_heuristics:
        return False, None
    if (evidence.total_tx is not None and evidence.max_tx_per_hour is not None
            and evidence.total_tx >= policy.likely_bots_min_tx
            and evidence.max_tx_per_hour >= policy.likely_bots_min_tx_per_hour):
        return True, "likely_bots leg 1: total_tx={} >= {} and max_tx_per_hour={} >= {}".format(
            evidence.total_tx, policy.likely_bots_min_tx,
            evidence.max_tx_per_hour, policy.likely_bots_min_tx_per_hour)
    if (evidence.total_tx is not None and evidence.distinct_senders is not None
            and evidence.total_tx >= policy.likely_bots_high_tx
            and evidence.distinct_senders <= policy.likely_bots_max_distinct_senders):
        return True, "likely_bots leg 2: total_tx={} >= {} and distinct_senders={} <= {}".format(
            evidence.total_tx, policy.likely_bots_high_tx,
            evidence.distinct_senders, policy.likely_bots_max_distinct_senders)
    if (evidence.failed_tx_share is not None
            and evidence.failed_tx_share > policy.likely_bots_failed_share):
        return True, "likely_bots leg 3: failed_tx_share={} > {}".format(
            evidence.failed_tx_share, policy.likely_bots_failed_share)
    return False, None


def _non_human_cadence(evidence: AccountEvidence,
                       policy: "EligibilityPolicy") -> Tuple[bool, Optional[str]]:
    if not policy.enable_published_heuristics:
        return False, None
    if (evidence.day_of_week_skewness is not None
            and evidence.day_of_week_skewness == PRE_T0_ZERO):
        return True, "day_of_week_skewness is exactly 0 (the inverse human filter)"
    if (evidence.mean_inter_trade_gap_seconds is not None
            and evidence.mean_inter_trade_gap_seconds > policy.human_min_inter_trade_gap_seconds):
        return True, "mean_inter_trade_gap_seconds={} > {}".format(
            evidence.mean_inter_trade_gap_seconds, policy.human_min_inter_trade_gap_seconds)
    return False, None


_INFRASTRUCTURE_PREDICATES = (
    (ExclusionRule.SETTLES_FOR_MULTIPLE_PRINCIPALS, _settles_for_multiple_principals),
    (ExclusionRule.PUBLIC_CAPITAL_POOL, _public_capital_pool),
    (ExclusionRule.MARKET_MAKING_INVENTORY, _market_making_inventory),
    (ExclusionRule.DEPLOYER_TRADING_OWN_TOKEN, _deployer_trading_own_token),
    (ExclusionRule.ECONOMIC_CONTROLLER_UNIDENTIFIED, _controller_unidentified),
    (ExclusionRule.BOT_HEURISTIC, _bot_heuristic),
    (ExclusionRule.NON_HUMAN_TRADING_CADENCE, _non_human_cadence),
)


def classify_account(observation: AccountWindowObservation,
                     policy: "EligibilityPolicy" = DEFAULT_POLICY,
                     screen: Optional["WarehouseScreen"] = None) -> "EligibilityVerdict":
    """Stage two: one account's verdict, with every rule that fired recorded.

    :param observation: an :class:`~universe.observation.AccountWindowObservation`. Checked by
        exact type: a subclass overriding ``__post_init__`` would skip the T0 check and arrive here
        carrying post-T0 counts.
    :param policy: the §6.2 thresholds. Hashed into the snapshot identifier by
        :class:`universe.freeze.FrozenUniverse`, so a changed threshold is a changed universe
        identity rather than a quietly changed membership.
    :param screen: the stage-one :class:`WarehouseScreen`, when there is one. Supplying it makes an
        observation for an account the warehouse never admitted a caller defect rather than an
        extra admission, and it is what ``OUTSIDE_TRAINING_WINDOW`` is decided against.

    Ordering is :data:`RULE_PRECEDENCE`, infrastructure first. Every other rule that fired travels
    on :attr:`EligibilityVerdict.also_matched`.
    """
    if type(observation) is not AccountWindowObservation:
        raise TypeError(
            "classify_account takes an AccountWindowObservation, got {}. The exact type is what "
            "guarantees the record was built through the T0 check; a subclass overriding "
            "__post_init__ is an isinstance and runs none of it.".format(type(observation).__name__)
        )
    if screen is not None and not isinstance(screen, WarehouseScreen):
        raise TypeError("screen must be a WarehouseScreen or None")
    if screen is not None and observation.account not in screen.admitted_addresses:
        raise ValueError(
            "{} was classified against a warehouse screen that did not admit it. Stage two decides "
            "eligibility for the accounts stage one returned; an observation from outside that set "
            "would enter the census as an admission the screen cannot reconcile "
            "against.".format(observation.account)
        )

    evidence = observation.evidence
    exempt = (SMART_ACCOUNT_EXEMPT_RULES if observation.account_type in SMART_ACCOUNT_TYPES
              else frozenset())

    fired = {}

    if screen is not None and observation.window_key is not screen.window_key:
        fired[ExclusionRule.OUTSIDE_TRAINING_WINDOW] = (
            "observation is keyed to {} and the screen to {}".format(
                observation.window_key.value, screen.window_key.value)
        )

    for rule, predicate in _INFRASTRUCTURE_PREDICATES:
        if rule in exempt:
            continue
        hit, why = predicate(evidence, policy)
        if hit:
            fired[rule] = why

    label_provenance = {}
    for hit in evidence.labels:
        rule = LABEL_SETS.get(hit.set_name)
        if rule is None:
            continue
        fired[rule] = "member of {} at block {}".format(hit.set_name, hit.snapshot_block)
        label_provenance[rule] = hit.provenance

    if not evidence.netting_complete:
        fired[ExclusionRule.ENRICHMENT_INCOMPLETE] = (
            "netting did not complete, so valid_buys={} is not a measurement".format(
                observation.valid_buys)
        )

    if observation.potential_buys < POTENTIAL_BUY_FLOOR:
        fired[ExclusionRule.POTENTIAL_BUYS_BELOW_FLOOR] = "potential_buys={} < {}".format(
            observation.potential_buys, POTENTIAL_BUY_FLOOR)
    elif observation.potential_buys > POTENTIAL_BUY_CEILING:
        fired[ExclusionRule.POTENTIAL_BUYS_ABOVE_CEILING] = "potential_buys={} > {}".format(
            observation.potential_buys, POTENTIAL_BUY_CEILING)

    if observation.valid_buys < VALID_BUY_FLOOR:
        fired[ExclusionRule.VALID_BUYS_BELOW_FLOOR] = "valid_buys={} < {}".format(
            observation.valid_buys, VALID_BUY_FLOOR)
    elif observation.valid_buys > VALID_BUY_CEILING:
        fired[ExclusionRule.VALID_BUYS_ABOVE_CEILING] = "valid_buys={} > {}".format(
            observation.valid_buys, VALID_BUY_CEILING)

    if observation.account_type not in ADMISSIBLE_ACCOUNT_TYPES:
        fired[ExclusionRule.ECONOMIC_CONTROLLER_UNIDENTIFIED] = (
            "account_type is {}, which names no identifiable single portfolio".format(
                observation.account_type.value)
        )

    if not fired:
        crossed = not (VALID_BUY_FLOOR <= observation.potential_buys <= VALID_BUY_CEILING)
        return EligibilityVerdict(
            account=observation.account,
            admitted=Admission(
                account=observation.account,
                account_type=observation.account_type,
                valid_buys=observation.valid_buys,
                potential_buys=observation.potential_buys,
                active_days=observation.active_days,
                buy_volume_usd=observation.buy_volume_usd,
                wallet_age_days=observation.wallet_age_days,
                crossed_boundary=crossed,
            ),
        )

    ordered = [rule for rule in RULE_PRECEDENCE if rule in fired]
    winner = ordered[0]
    return EligibilityVerdict(
        account=observation.account,
        exclusion=Exclusion(
            account=observation.account,
            stage=ExclusionStage.NETTED,
            rule=winner,
            evidence=(fired[winner], EXCLUSION_CRITERIA[winner]),
            label_provenance=label_provenance.get(winner),
        ),
        also_matched=tuple(ordered[1:]),
    )


@dataclass(frozen=True)
class BoundaryMovement:
    """What the two-stage buffer actually did, in six counts.

    The first two are ticket 25's headline — the accounts netting moved *into* eligibility, which a
    single-stage filter at 20-1,000 would have dropped without trace. The next two are the movement
    in the other direction. The last two are evidence about whether the buffer itself is truncating
    the population: an eligible universe crowded onto the bounds is one the bounds are deciding.
    """

    retained_by_lower_buffer: int
    retained_by_upper_buffer: int
    fell_below_floor: int
    rose_above_cap: int
    at_lower_bound_eligible: int
    at_upper_bound_eligible: int

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = require_pre_t0_int(getattr(self, name), "BoundaryMovement.{}".format(name))
            if value < 0:
                raise ValueError("BoundaryMovement.{} is {}".format(name, value))

    @property
    def retained_by_buffer(self) -> int:
        """Ticket 25's headline count."""
        return self.retained_by_lower_buffer + self.retained_by_upper_buffer


def boundary_movement(observations: Tuple[AccountWindowObservation, ...],
                      verdicts: Tuple["EligibilityVerdict", ...]) -> "BoundaryMovement":
    """Measure the buffer's effect over one window's observations and their verdicts.

    The two *retained* counts are taken over admissions only — an account the buffer carried into
    stage two and that was then excluded as infrastructure was not retained by the buffer, it was
    excluded. The two *movement* counts are taken over every observation, because netting moving an
    account out of the band is a fact about netting whichever rule ends up naming it.
    """
    admitted = {v.account: v.admitted for v in verdicts if v.is_admitted}
    lower = upper = below = above = at_low = at_high = 0
    for observation in observations:
        in_final_band = VALID_BUY_FLOOR <= observation.potential_buys <= VALID_BUY_CEILING
        if in_final_band and observation.valid_buys < VALID_BUY_FLOOR:
            below += 1
        if in_final_band and observation.valid_buys > VALID_BUY_CEILING:
            above += 1
        admission = admitted.get(observation.account)
        if admission is None:
            continue
        if admission.crossed_boundary:
            if observation.potential_buys < VALID_BUY_FLOOR:
                lower += 1
            else:
                upper += 1
        if admission.valid_buys == VALID_BUY_FLOOR:
            at_low += 1
        if admission.valid_buys == VALID_BUY_CEILING:
            at_high += 1
    return BoundaryMovement(
        retained_by_lower_buffer=lower,
        retained_by_upper_buffer=upper,
        fell_below_floor=below,
        rose_above_cap=above,
        at_lower_bound_eligible=at_low,
        at_upper_bound_eligible=at_high,
    )


class DataCostRefused(ContractError):
    """The reported data cost cannot describe the run it claims to."""


@dataclass(frozen=True)
class DataCostReport:
    """Ticket 25's "the data cost is reported".

    The point of the two-stage shape is that full transaction histories are extracted only for
    candidate wallets rather than for the whole chain. That claim is worth exactly the number
    beside it, so the number travels with the measurement.
    """

    accounts_screened: int
    accounts_enriched: int
    transactions_enriched: int

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = require_pre_t0_int(getattr(self, name), "DataCostReport.{}".format(name))
            if value < 0:
                raise ValueError("DataCostReport.{} is {}".format(name, value))
        if self.accounts_enriched > self.accounts_screened:
            raise DataCostRefused(
                "{} account(s) were enriched against {} screened. Enrichment happens only for "
                "accounts the warehouse screen admitted, so more enriched than screened means the "
                "filter-early/enrich-late claim describes a different run from the one that "
                "produced these numbers.".format(self.accounts_enriched, self.accounts_screened)
            )

    @property
    def enrichment_share(self) -> Decimal:
        """Share of screened accounts whose full history was pulled. Unquantized."""
        return divide(self.accounts_enriched, self.accounts_screened)
