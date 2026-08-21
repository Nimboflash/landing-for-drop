"""Ticket 26 — Step 0: measure the eligible universe in all four windows, and stop if it is short.

§6.1's counts, §6.1's five distributions, the ``INSUFFICIENT CANDIDATE UNIVERSE`` status, §13.7's
base-rate comparison, and the pre-registered replacement machinery.

Three properties carry this module.

**The status is derived, never stored.** :attr:`Step0Measurement.eligible_universe_size` and
:attr:`Step0Measurement.status` are properties. Storing either would let the passing value be set
independently of the number it is about, which is the single cheapest way to publish a window that
is not valid. ``.permits_ranking`` is on the enum for ``EdgeOriginStatus.passes``'s reason: no
``if window.ok:`` can quietly absorb a third meaning later.

**It refuses to be constructed unless the funnel reconciles.** §6.1's counts are monotone by
definition, the account-type breakdown must sum to the census's admitted count, and every
observation must carry the window's own T0. A measurement that does not reconcile cannot be built,
let alone published.

**There is no ordering in this module and no per-wallet score field, and it imports neither
``ranking`` nor ``select``.** Ticket 26's "no wallet ranking, no scoring of candidates against each
other, and no forward-window number is produced in this ticket" is a property of the module's
import set, and ``tests/test_post_t0_barrier.py``'s partition asserts it.

Quantiles
---------

:func:`nearest_rank` is pure integer index arithmetic: sort, then take
``values[ceil(num * n / den) - 1]``. Exact, reproducible by hand, no rounding mode to argue about,
and none of the frozen-context scan's business. The p50 field is named ``p50`` and **not**
``median``, because ``reporting.median`` takes the midpoint of the two middle values on an even
count and the two figures legitimately differ — naming them apart is the control against somebody
reconciling them.

What this module does not guarantee
-----------------------------------

``total_active_accounts`` comes from the warehouse and nothing here can check it. Every funnel
ratio in §6.1 rests on it, and the invariant chain below proves internal consistency only — never
that the top of the funnel is right.
"""

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from typing import Iterator, Optional, Tuple

from contracts import (
    AccountType,
    ContractError,
    add,
    canonical_hash,
    divide,
    require_finite,
)

from .census import UniverseCensus
from .eligibility import (
    BoundaryMovement,
    DataCostReport,
    EligibilityPolicy,
    EligibilityVerdict,
    HeuristicModification,
)
from .observation import AccountWindowObservation
from .protocol import (
    MINIMUM_ELIGIBLE_UNIVERSE,
    UNIVERSE_SCHEMA_VERSION,
    VALID_BUY_CEILING,
    VALID_BUY_FLOOR,
    T0Instant,
    TrainingWindow,
    WindowDesign,
    WindowKey,
    require_pre_t0_int,
)
from .provenance import require_pre_t0_value


class WindowStatus(str, Enum):
    """§6.1's window status, spelled as §6.1 spells it.

    ``INSUFFICIENT CANDIDATE UNIVERSE`` is a **status and not an error**. Measuring a window at
    8,400 eligible accounts is a successful measurement of a real fact — arguably the single most
    important cheap finding Phase 0 can produce — and raising here would make the measurement stage
    crash on its most informative result. The refusal lives one step later, in
    :class:`universe.freeze.FrozenUniverse`: measuring a small universe is a finding, freezing one
    for ranking is a governance violation.
    """

    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT_CANDIDATE_UNIVERSE = "INSUFFICIENT CANDIDATE UNIVERSE"

    @property
    def permits_ranking(self) -> bool:
        return self is WindowStatus.SUFFICIENT


#: The quantiles §6.1's distributions are reported at, as integer ``(name, numerator, denominator)``
#: triples. Ints rather than Decimals on purpose: the index arithmetic below is then exact.
QUANTILES = (
    ("p05", 5, 100),
    ("p25", 25, 100),
    ("p50", 50, 100),
    ("p75", 75, 100),
    ("p95", 95, 100),
)

#: §6.1's five, verbatim: "valid buy count, trading volume, active days, wallet age, EOA vs smart
#: account share".
REQUIRED_DISTRIBUTIONS = (
    "valid_buy_count",
    "buy_volume_usd",
    "active_days",
    "wallet_age_days",
    "smart_account_share",
)


class MeasuredColumn(tuple):
    """One §6.1 column of measured values, as a **named type** rather than a bare tuple.

    ``Tuple[Decimal, ...]`` in a signature is a column of provenance-free scalars — the shape
    ``tests/test_signature_barrier.py``'s rule 4 exists to keep off a selection path, because a
    signature spelled that way accepts any column of numbers from anywhere. Naming the column gives
    the two public quantile functions below a type a caller can be held to, and it is the type
    :func:`distribution` and :func:`nearest_rank` are written against.

    It is a ``tuple`` subclass so the column is still ordered, hashable and frozen, and so the
    arithmetic below is unchanged: this type adds a name and takes nothing away. Construction is
    variadic — ``MeasuredColumn(*column)`` — because a constructor taking a generic sequence would
    reintroduce the annotation the type exists to remove.
    """

    __slots__ = ()

    def __new__(cls, *values: Decimal) -> "MeasuredColumn":
        return tuple.__new__(cls, values)


def nearest_rank(values: MeasuredColumn, num: int, den: int) -> Decimal:
    """The nearest-rank quantile: sort ascending, take ``ceil(num * n / den) - 1``.

    Integer arithmetic throughout — ``-(-(num * n) // den)`` is ``ceil`` without a float and
    without a Decimal, so there is no rounding mode to pin and a reviewer can reproduce any of
    these by counting along the sorted column.

    :raises ValueError: on an empty column. A quantile of nothing is not zero; it is the absence of
        a population, and a zero would read as a measured distribution centred on nothing.
    """
    require_pre_t0_int(num, "nearest_rank numerator")
    require_pre_t0_int(den, "nearest_rank denominator")
    if den <= 0 or num <= 0 or num > den:
        raise ValueError(
            "nearest_rank needs 0 < numerator <= denominator, got {}/{}".format(num, den)
        )
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise ValueError(
            "a quantile over an empty column is undefined, not zero — a zero here would read as a "
            "measured distribution rather than as an absent population"
        )
    index = -(-(num * n) // den) - 1
    return ordered[index]


@dataclass(frozen=True, eq=False)
class QuantileSet:
    """§6.1's five reported quantiles, as five **named fields**.

    This was ``Dict[str, Decimal]``, which is the audit's most dangerous shape: a mapping makes
    "are the five present?" a question about string keys checked at runtime rather than a question
    the type answers. Five fields cannot be missing one, cannot carry a sixth, and cannot be
    addressed by a key nobody registered.

    ``__getitem__`` and equality against a plain mapping of the five labels survive because §6.1 is
    *published* as labelled figures and ``reporting`` reads them by label. Neither is a way in: the
    labels are exactly :data:`QUANTILES`' and there is no key that reaches anything else.
    """

    p05: Decimal
    p25: Decimal
    p50: Decimal
    p75: Decimal
    p95: Decimal

    def __post_init__(self) -> None:
        for label, _num, _den in QUANTILES:
            object.__setattr__(
                self, label, require_finite(getattr(self, label), "quantile {}".format(label)))

    def ordered(self) -> MeasuredColumn:
        """The five, in registered order — the column the monotonicity check reads."""
        return MeasuredColumn(*[getattr(self, label) for label, _n, _d in QUANTILES])

    def __getitem__(self, label: str) -> Decimal:
        for name, _num, _den in QUANTILES:
            if name == label:
                return getattr(self, name)
        raise KeyError(
            "{!r} is not one of §6.1's quantiles {}".format(
                label, ", ".join(name for name, _n, _d in QUANTILES))
        )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, QuantileSet):
            return self.ordered() == other.ordered()
        if isinstance(other, dict):
            return {label: getattr(self, label) for label, _n, _d in QUANTILES} == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.ordered())

    def __repr__(self) -> str:
        return "QuantileSet({})".format(
            ", ".join("{}={}".format(label, getattr(self, label))
                      for label, _n, _d in QUANTILES))


if tuple(QuantileSet.__dataclass_fields__) != tuple(label for label, _n, _d in QUANTILES):
    raise ImportError(
        "QuantileSet's fields and QUANTILES disagree; the five §6.1 reports and the five the type "
        "can hold must be the same five, or one of them is describing a different report"
    )


@dataclass(frozen=True)
class Distribution:
    """One §6.1 distribution: the five quantiles, the mean, and both ends.

    ``__post_init__`` refuses non-monotone quantiles, which is what catches a mis-sorted
    implementation — a p25 above a p75 is arithmetically possible only if the column was ordered
    wrong, and every figure derived from it would still look plausible.
    """

    name: str
    n: int
    quantiles: QuantileSet
    mean: Decimal
    minimum: Decimal
    maximum: Decimal

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("a distribution must name what it is a distribution of")
        require_pre_t0_int(self.n, "Distribution.n")
        if self.n <= 0:
            raise ValueError(
                "distribution {} covers {} value(s); an empty distribution has no quantiles and "
                "publishing one would read as a measured population of nothing".format(
                    self.name, self.n
                )
            )
        if not isinstance(self.quantiles, QuantileSet):
            raise TypeError(
                "distribution {} must carry a QuantileSet, got {}. A mapping here would make the "
                "five §6.1 reports a question about key names.".format(
                    self.name, type(self.quantiles).__name__)
            )
        for name in ("mean", "minimum", "maximum"):
            object.__setattr__(
                self, name,
                require_finite(getattr(self, name), "{}.{}".format(self.name, name)),
            )

        ordered = self.quantiles.ordered()
        for earlier, later in zip(ordered, ordered[1:]):
            if earlier > later:
                raise ValueError(
                    "distribution {} has non-monotone quantiles {}; the column was not sorted, and "
                    "every figure derived from it would still look plausible".format(
                        self.name, ordered)
                )
        if self.minimum > ordered[0] or self.maximum < ordered[-1]:
            raise ValueError(
                "distribution {} has bounds [{}, {}] that do not contain its quantiles {}".format(
                    self.name, self.minimum, self.maximum, ordered)
            )


def distribution(name: str, values: MeasuredColumn) -> Distribution:
    """Build one :class:`Distribution` from a column, at full frozen precision.

    The mean is accumulated in the order supplied and divided once. It is not quantized — nothing
    in this package quantizes; ``reporting`` is the output boundary and quantizing here would carry
    a rounding error into every figure derived from the column.
    """
    column = MeasuredColumn(*[require_finite(v, "{} value".format(name)) for v in values])
    if not column:
        raise ValueError(
            "distribution {} was requested over no values. An empty distribution is the absence of "
            "a population, and §6.1 asks for the shape of the eligible universe — reporting zeros "
            "would describe a universe nobody measured.".format(name)
        )
    running = Decimal("0")
    for value in column:
        running = add(running, value)
    return Distribution(
        name=name,
        n=len(column),
        # Positional, in :data:`QUANTILES`' order. The module-level guard above asserts that
        # ``QuantileSet``'s field order *is* that order, so the positions cannot drift apart
        # without an ImportError at first import rather than a silently relabelled quantile.
        quantiles=QuantileSet(*[nearest_rank(column, num, den) for _label, num, den in QUANTILES]),
        mean=divide(running, len(column)),
        minimum=min(column),
        maximum=max(column),
    )


@dataclass(frozen=True)
class DistributionSet:
    """§6.1's five distributions, as five **named fields**.

    This was ``Dict[str, Distribution]`` on :class:`Step0Measurement`, which is rule 4's shape
    exactly: "are the five present?" became a question about string keys, answered at runtime by a
    missing-key loop and a stray-key loop that a caller could only fail *after* building the
    mapping. Five fields cannot be missing one and cannot carry a sixth, so both of those loops are
    now impossible states rather than checked ones, and the check that remains is the one a type
    cannot make — that the distribution in each slot is a distribution *of that column*.

    ``__getitem__`` and ``__iter__`` survive because §6.1 is *published* as labelled figures and
    ``reporting`` reads them by label. Neither is a way in: the labels are exactly
    :data:`REQUIRED_DISTRIBUTIONS` and there is no key that reaches anything else.
    """

    valid_buy_count: Distribution
    buy_volume_usd: Distribution
    active_days: Distribution
    wallet_age_days: Distribution
    smart_account_share: Distribution

    def __post_init__(self) -> None:
        for name in REQUIRED_DISTRIBUTIONS:
            held = getattr(self, name)
            if not isinstance(held, Distribution):
                raise TypeError(
                    "DistributionSet.{} must be a Distribution, got {}".format(
                        name, type(held).__name__)
                )
            if held.name != name:
                raise ValueError(
                    "the {} slot holds a distribution named {!r}. §6.1's five are published under "
                    "their own labels, so a slot holding another column's shape would report one "
                    "column's figures under another column's name.".format(name, held.name)
                )

    def __getitem__(self, name: str) -> Distribution:
        for registered in REQUIRED_DISTRIBUTIONS:
            if registered == name:
                return getattr(self, registered)
        raise KeyError(
            "{!r} is not one of §6.1's distributions {}".format(
                name, ", ".join(REQUIRED_DISTRIBUTIONS))
        )

    def __iter__(self) -> Iterator[str]:
        """The five registered labels, so ``sorted(measurement.distributions)`` reads §6.1's."""
        return iter(REQUIRED_DISTRIBUTIONS)

    def __len__(self) -> int:
        return len(REQUIRED_DISTRIBUTIONS)


if tuple(DistributionSet.__dataclass_fields__) != tuple(REQUIRED_DISTRIBUTIONS):
    raise ImportError(
        "DistributionSet's fields and REQUIRED_DISTRIBUTIONS disagree; §6.1's five and the five "
        "the type can hold must be the same five, or one of them is describing a different report"
    )


@dataclass(frozen=True)
class AccountTypeMix:
    """§6.1's account-type breakdown of the eligible universe.

    ``other_contract`` is §6.2's fourth admitted type — "contract accounts that clearly control a
    single user portfolio" — which §6.1's required-counts block does not list. See
    :attr:`Step0Measurement.spec_discrepancy`.
    """

    eoa: int
    safe: int
    erc4337: int
    other_contract: int

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = require_pre_t0_int(getattr(self, name), "AccountTypeMix.{}".format(name))
            if value < 0:
                raise ValueError("AccountTypeMix.{} is {}".format(name, value))

    @property
    def total(self) -> int:
        return self.eoa + self.safe + self.erc4337 + self.other_contract

    @property
    def smart_accounts(self) -> int:
        return self.safe + self.erc4337 + self.other_contract


class BaseRateVerdict(str, Enum):
    """§13.7's comparison, as a status rather than a bare ratio."""

    AT_OR_ABOVE_EXPECTATION = "AT_OR_ABOVE_EXPECTATION"
    BELOW_EXPECTATION = "BELOW_EXPECTATION"


@dataclass(frozen=True)
class BaseRateComparison:
    """The measured universe against the size the design assumed it would be.

    §13.7: the target population may simply not exist at the size assumed. Measuring that it does
    not is the **finding**, not the failure — so this is a status and a ratio, never a refusal.

    ``statement`` is required and non-empty, so the comparison ticket 26 asks to be "reported
    rather than left implicit" is a field nobody can omit. ``assumed_size`` is a pre-registered
    parameter passed in; nothing here invents an expectation.
    """

    window_key: WindowKey
    assumed_size: int
    source: str
    measured_size: int
    statement: str

    def __post_init__(self) -> None:
        if not isinstance(self.window_key, WindowKey):
            raise TypeError("BaseRateComparison.window_key must be a WindowKey")
        for name in ("assumed_size", "measured_size"):
            value = require_pre_t0_int(getattr(self, name), "BaseRateComparison.{}".format(name))
            if value < 0:
                raise ValueError("BaseRateComparison.{} is {}".format(name, value))
        if self.assumed_size <= 0:
            raise ValueError(
                "the assumed universe size is {}; §13.7's comparison is a ratio against it and an "
                "assumption of zero is not an assumption".format(self.assumed_size)
            )
        for name in ("source", "statement"):
            if not getattr(self, name) or not str(getattr(self, name)).strip():
                raise ValueError(
                    "a base-rate comparison must state its {}. §13.7's point is that the target "
                    "population may not exist at the size assumed; a ratio with no statement of "
                    "where the assumption came from is a number nobody can contest.".format(name)
                )

    @property
    def ratio(self) -> Decimal:
        """Measured over assumed. Unquantized — ``reporting`` renders it."""
        return divide(self.measured_size, self.assumed_size)

    @property
    def verdict(self) -> BaseRateVerdict:
        if self.measured_size >= self.assumed_size:
            return BaseRateVerdict.AT_OR_ABOVE_EXPECTATION
        return BaseRateVerdict.BELOW_EXPECTATION


#: §6.2 admits "contract accounts that clearly control a single user portfolio"; §6.1's
#: required-counts block lists only EOAs, Safes and ERC-4337. The conflict is *reported* rather than
#: silently resolved, because it moves ``eligible_universe_size`` and therefore the selected wallet
#: count. It should be raised with whoever owns the pre-registration rather than settled here.
SPEC_DISCREPANCY = (
    "§6.2 admits contract accounts that clearly control a single user portfolio; §6.1's required "
    "counts list only EOAs, Safes and ERC-4337. eligible_other_contracts is reported as a fourth "
    "count and is INCLUDED in eligible_universe_size, which makes the final figure larger than a "
    "literal reading of §6.1 would produce and moves Selected Wallet Count with it."
)


@dataclass(frozen=True)
class Step0Measurement:
    """§6.1's block for one window, refusing to be constructed unless it reconciles.

    Every count §6.1 names is here. ``eligible_universe_size``, ``excluded_infrastructure`` and
    ``status`` are **derived properties** rather than stored fields: nobody can publish a universe
    size that disagrees with its account-type breakdown, and nobody can write the passing status
    onto a failing window.
    """

    window: TrainingWindow
    total_active_accounts: int
    accounts_with_at_least_one_valid_buy: int
    accounts_in_valid_buy_band: int
    mix: AccountTypeMix
    census: UniverseCensus
    movement: BoundaryMovement
    data_cost: DataCostReport
    distributions: DistributionSet
    heuristic_modifications: Tuple[HeuristicModification, ...]
    policy: EligibilityPolicy
    dataset_snapshot: str
    base_rate: BaseRateComparison
    observations: Tuple[AccountWindowObservation, ...]
    spec_discrepancy: str = SPEC_DISCREPANCY

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "heuristic_modifications", tuple(self.heuristic_modifications))
        object.__setattr__(self, "observations", tuple(self.observations))

        if type(self.window) is not TrainingWindow:
            raise TypeError("Step0Measurement.window must be a TrainingWindow")
        for name in ("total_active_accounts", "accounts_with_at_least_one_valid_buy",
                     "accounts_in_valid_buy_band"):
            value = require_pre_t0_int(getattr(self, name), "Step0Measurement.{}".format(name))
            if value < 0:
                raise ValueError("Step0Measurement.{} is {}".format(name, value))
        for name, expected in (("mix", AccountTypeMix), ("census", UniverseCensus),
                               ("movement", BoundaryMovement), ("data_cost", DataCostReport),
                               ("policy", EligibilityPolicy),
                               ("distributions", DistributionSet),
                               ("base_rate", BaseRateComparison)):
            if not isinstance(getattr(self, name), expected):
                raise TypeError(
                    "Step0Measurement.{} must be a {}, got {}".format(
                        name, expected.__name__, type(getattr(self, name)).__name__)
                )
        if not self.dataset_snapshot or not str(self.dataset_snapshot).strip():
            raise ValueError(
                "a Step 0 measurement must name the dataset snapshot it was measured from; ticket "
                "26 requires the counts to be reproducible from the frozen snapshot, and a "
                "measurement that does not say which snapshot cannot be re-run"
            )
        if not self.spec_discrepancy or not str(self.spec_discrepancy).strip():
            raise ValueError(
                "spec_discrepancy must state the §6.1/§6.2 conflict over contract accounts; it "
                "moves the eligible universe size, so a blank field would resolve the conflict "
                "silently in the direction that makes the universe larger"
            )

        if self.census.window_key is not self.window.key:
            raise ValueError(
                "the measurement is for window {} and its census is for {}".format(
                    self.window.key.value, self.census.window_key.value)
            )
        if self.base_rate.window_key is not self.window.key:
            raise ValueError(
                "the measurement is for window {} and its base-rate comparison is for {}".format(
                    self.window.key.value, self.base_rate.window_key.value)
            )
        if self.mix.total != self.census.admitted_count:
            raise ValueError(
                "window {}: the account-type breakdown holds {} account(s) and the census admitted "
                "{}. The breakdown is what §6.1 publishes and the census is what reconciles "
                "against the population; a disagreement means one of them is describing a "
                "different universe.".format(
                    self.window.key.value, self.mix.total, self.census.admitted_count)
            )
        if self.movement != self.census.movement:
            raise ValueError(
                "window {} carries a boundary movement that disagrees with its census's".format(
                    self.window.key.value)
            )

        funnel = (
            ("eligible_universe_size", self.eligible_universe_size),
            ("accounts_in_valid_buy_band", self.accounts_in_valid_buy_band),
            ("accounts_with_at_least_one_valid_buy", self.accounts_with_at_least_one_valid_buy),
            ("total_active_accounts", self.total_active_accounts),
        )
        for (lower_name, lower), (upper_name, upper) in zip(funnel, funnel[1:]):
            if lower > upper:
                raise ValueError(
                    "window {}: {} is {} but {} is {}. §6.1's funnel is monotone by definition — "
                    "every eligible account has 20-1,000 valid buys, every account in that band "
                    "has at least one, and every one of those was active. An inversion means a "
                    "count was measured over a different population from the one above "
                    "it.".format(self.window.key.value, lower_name, lower, upper_name, upper)
                )

        # §6.1's five are no longer checked for here. A :class:`DistributionSet` cannot be missing
        # one, cannot carry a sixth, and cannot hold a non-``Distribution`` in a slot — the loops
        # that used to establish those three facts at runtime were replaced by a type that makes
        # all three unconstructable, which is the whole of rule 4's argument in one field.

        for observation in self.observations:
            if type(observation) is not AccountWindowObservation:
                raise TypeError(
                    "Step0Measurement.observations holds AccountWindowObservation values, got "
                    "{}".format(type(observation).__name__)
                )
            if observation.t0 != self.window.t0:
                raise ValueError(
                    "{} carries T0 (block {}, second {}) and window {} has T0 (block {}, second "
                    "{}). A batch mixing two windows' observations would be measured against one "
                    "calendar and reported under the other.".format(
                        observation.account, observation.t0.block, observation.t0.timestamp,
                        self.window.key.value, self.window.t0.block, self.window.t0.timestamp)
                )
            if observation.window_key is not self.window.key:
                raise ValueError(
                    "{} is keyed to window {} in a measurement of {}".format(
                        observation.account, observation.window_key.value, self.window.key.value)
                )

        if self.policy.enable_published_heuristics and not self.heuristic_modifications:
            raise ValueError(
                "window {} enables the published bot heuristics and records no modification. "
                "Ticket 25 requires every modification made to them to be recorded with its "
                "reason, and §6.2's human filter *must* be modified to retain Safes and smart "
                "accounts — so an empty record means either the modification went unrecorded or "
                "the filter silently excluded every smart account.".format(self.window.key.value)
            )
        for modification in self.heuristic_modifications:
            if not isinstance(modification, HeuristicModification):
                raise TypeError(
                    "heuristic_modifications holds HeuristicModification values, got {}".format(
                        type(modification).__name__)
                )

    # -- derived ----------------------------------------------------------------

    @property
    def eligible_eoas(self) -> int:
        return self.mix.eoa

    @property
    def eligible_safes(self) -> int:
        return self.mix.safe

    @property
    def eligible_erc4337(self) -> int:
        return self.mix.erc4337

    @property
    def eligible_other_contracts(self) -> int:
        return self.mix.other_contract

    @property
    def eligible_universe_size(self) -> int:
        """§6.1's final line. Derived from the breakdown, so the two cannot disagree."""
        return self.mix.total

    @property
    def excluded_infrastructure(self) -> int:
        return self.census.excluded_infrastructure

    @property
    def status(self) -> WindowStatus:
        """``INSUFFICIENT CANDIDATE UNIVERSE`` iff the eligible universe is below 10,000.

        Derived, never stored. A stored status could be written independently of the number it is
        about, which is the cheapest possible way to publish an invalid window as a valid one.
        """
        if self.eligible_universe_size < MINIMUM_ELIGIBLE_UNIVERSE:
            return WindowStatus.INSUFFICIENT_CANDIDATE_UNIVERSE
        return WindowStatus.SUFFICIENT

    @property
    def smart_account_share(self) -> Decimal:
        """§6.1's EOA-vs-smart-account share, unquantized."""
        return divide(self.mix.smart_accounts, self.mix.total)


def measure_window(window: TrainingWindow,
                   observations: Tuple[AccountWindowObservation, ...],
                   verdicts: Tuple[EligibilityVerdict, ...],
                   census: UniverseCensus,
                   data_cost: DataCostReport,
                   policy: EligibilityPolicy,
                   dataset_snapshot: str,
                   total_active_accounts: int,
                   accounts_with_at_least_one_valid_buy: int,
                   base_rate: BaseRateComparison,
                   heuristic_modifications: Optional[
                       Tuple[HeuristicModification, ...]] = None) -> "Step0Measurement":
    """§6.1's block for one window. Measures; ranks nothing.

    :param observations: every :class:`~universe.observation.AccountWindowObservation` the
        warehouse screen admitted for enrichment.
    :param verdicts: their :class:`~universe.eligibility.EligibilityVerdict` values, plus the
        stage-one exclusions, exactly as :func:`universe.census.build_census` received them.
    :param total_active_accounts: from the warehouse. Nothing here can check it — see the module
        docstring.
    :param accounts_with_at_least_one_valid_buy: likewise from the warehouse, because accounts
        below the potential-buy floor were never returned and their valid buys are unknowable.

    ``accounts_in_valid_buy_band`` is **derived** from the observations rather than supplied: it is
    a count this module can compute, and a supplied one could disagree with the population the rest
    of the measurement is built from.
    """
    observations = tuple(observations)
    verdicts = tuple(verdicts)
    admitted = [v.admitted for v in verdicts if v.is_admitted]

    mix = AccountTypeMix(
        eoa=sum(1 for a in admitted if a.account_type is AccountType.EOA),
        safe=sum(1 for a in admitted if a.account_type is AccountType.SAFE),
        erc4337=sum(1 for a in admitted if a.account_type is AccountType.ERC4337),
        other_contract=sum(1 for a in admitted if a.account_type is AccountType.OTHER_CONTRACT),
    )

    in_band = sum(
        1 for o in observations if VALID_BUY_FLOOR <= o.valid_buys <= VALID_BUY_CEILING
    )

    if not admitted:
        raise EmptyEligibleUniverse(
            "window {} admitted no accounts at all. §6.1's distributions describe the eligible "
            "universe, and there is no shape to describe — this is a measurement that could not be "
            "taken rather than a universe of size zero, and the two must not be published as the "
            "same thing.".format(window.key.value)
        )

    distributions = DistributionSet(
        valid_buy_count=distribution(
            "valid_buy_count",
            MeasuredColumn(*[Decimal(a.valid_buys) for a in admitted])),
        # ``buy_volume_usd`` is the one admitted field that carries a provenance. It is gated and
        # *then* read: ``require_pre_t0_value`` refuses a contaminated or unprovenanced number here
        # rather than letting one describe §6.1's published shape, and ``.value`` is taken only once
        # the gate has passed. A distribution is a reported shape and not a selection input, so the
        # bare Decimal is where it belongs — but the read has to be earned, not assumed.
        buy_volume_usd=distribution(
            "buy_volume_usd",
            MeasuredColumn(*[require_pre_t0_value(a.buy_volume_usd,
                                                  "{}.buy_volume_usd".format(a.account)).value
                             for a in admitted])),
        active_days=distribution(
            "active_days",
            MeasuredColumn(*[Decimal(a.active_days) for a in admitted])),
        wallet_age_days=distribution(
            "wallet_age_days",
            MeasuredColumn(*[Decimal(a.wallet_age_days) for a in admitted])),
        # §6.1's fifth is a share rather than a column, so its "distribution" is the indicator's:
        # 1 for a smart account, 0 for an EOA. The mean is then the share itself, exactly, and the
        # quantiles say how the two populations sit against each other.
        smart_account_share=distribution(
            "smart_account_share",
            MeasuredColumn(*[Decimal(0) if a.account_type is AccountType.EOA else Decimal(1)
                             for a in admitted])),
    )

    return Step0Measurement(
        window=window,
        total_active_accounts=total_active_accounts,
        accounts_with_at_least_one_valid_buy=accounts_with_at_least_one_valid_buy,
        accounts_in_valid_buy_band=in_band,
        mix=mix,
        census=census,
        movement=census.movement,
        data_cost=data_cost,
        distributions=distributions,
        heuristic_modifications=tuple(
            heuristic_modifications if heuristic_modifications is not None else ()),
        policy=policy,
        dataset_snapshot=str(dataset_snapshot),
        base_rate=base_rate,
        observations=observations,
    )


class EmptyEligibleUniverse(ContractError):
    """No account at all was admitted, so there is no shape to describe.

    Distinct from ``INSUFFICIENT CANDIDATE UNIVERSE``, which is a measured finding about a small
    universe. Zero admitted accounts is not a small universe — it is a measurement that could not
    be taken, and §6.1's five distributions have no values to be distributions of.
    """


@dataclass(frozen=True)
class Step0Report:
    """All four windows' measurements, and whether ranking may proceed at all.

    Exactly one measurement per design window, all sharing the report's dataset snapshot. A report
    covering three of four windows is a different experiment from the pre-registered one, and the
    count is the only place that difference is visible.
    """

    design: WindowDesign
    measurements: Tuple[Step0Measurement, ...]
    parameter_freeze_hash: str
    dataset_snapshot: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "measurements", tuple(self.measurements))
        if not isinstance(self.design, WindowDesign):
            raise TypeError("Step0Report.design must be a WindowDesign")
        for name in ("parameter_freeze_hash", "dataset_snapshot"):
            if not getattr(self, name) or not str(getattr(self, name)).strip():
                raise ValueError("Step0Report must name its {}".format(name))
        keys = [m.window.key for m in self.measurements]
        if sorted(k.value for k in keys) != sorted(k.value for k in self.design.keys):
            raise ValueError(
                "the report measures {} and the design registers {}. Ticket 26 requires all four "
                "§6.3 windows measured before any ranking; a report over a subset would let the "
                "design advance on the windows that happened to look "
                "healthy.".format(
                    ", ".join(sorted(k.value for k in keys)),
                    ", ".join(sorted(k.value for k in self.design.keys)),
                )
            )
        for measurement in self.measurements:
            if not isinstance(measurement, Step0Measurement):
                raise TypeError("Step0Report.measurements holds Step0Measurement values")
            if measurement.dataset_snapshot != self.dataset_snapshot:
                raise ValueError(
                    "window {} was measured from snapshot {!r} and the report claims {!r}. Ticket "
                    "26 requires the counts to be reproducible from the frozen snapshot, and a "
                    "report mixing two of them is reproducible from neither.".format(
                        measurement.window.key.value, measurement.dataset_snapshot,
                        self.dataset_snapshot)
                )

    def measurement(self, key: WindowKey) -> Step0Measurement:
        for measurement in self.measurements:
            if measurement.window.key is key:
                return measurement
        raise KeyError("no measurement for window {}".format(getattr(key, "value", key)))

    @property
    def insufficient_windows(self) -> Tuple[WindowKey, ...]:
        return tuple(
            m.window.key for m in self.measurements
            if m.status is WindowStatus.INSUFFICIENT_CANDIDATE_UNIVERSE
        )

    @property
    def permits_ranking(self) -> bool:
        """Whether **every** window's status permits ranking.

        Per-window refusal lives in :class:`universe.freeze.FrozenUniverse`; this is the report-level
        summary a governance reader wants. It is deliberately not a refusal: §6.1 says the *window*
        is not valid and the design must be revised, which is narrower than refusing the other
        three.
        """
        return not self.insufficient_windows

    @property
    def digest(self) -> str:
        return canonical_hash(_report_payload(self))


def _report_payload(report):
    """The canonical form of a Step 0 report. Counts and identities; not the prose."""
    return {
        "schema_version": UNIVERSE_SCHEMA_VERSION,
        "parameter_freeze_hash": report.parameter_freeze_hash,
        "dataset_snapshot": report.dataset_snapshot,
        "windows": [
            {
                "key": m.window.key.value,
                "t0_block": m.window.t0.block,
                "t0_timestamp": m.window.t0.timestamp,
                "replaced_from": None if m.window.replaced_from is None
                else m.window.replaced_from.value,
                "total_active_accounts": m.total_active_accounts,
                "accounts_with_at_least_one_valid_buy": m.accounts_with_at_least_one_valid_buy,
                "accounts_in_valid_buy_band": m.accounts_in_valid_buy_band,
                "eligible_eoas": m.eligible_eoas,
                "eligible_safes": m.eligible_safes,
                "eligible_erc4337": m.eligible_erc4337,
                "eligible_other_contracts": m.eligible_other_contracts,
                "excluded_infrastructure": m.excluded_infrastructure,
                "eligible_universe_size": m.eligible_universe_size,
                "status": m.status.value,
                "exclusions_by_rule": {
                    entry.rule.value: entry.count for entry in m.census.exclusions_by_rule
                },
            }
            for m in sorted(report.measurements, key=lambda m: m.window.key.value)
        ],
    }


def step0_report(design: WindowDesign, measurements: Tuple[Step0Measurement, ...],
                 parameter_freeze_hash: str, dataset_snapshot: str) -> Step0Report:
    """Assemble the four measurements into ticket 26's report."""
    return Step0Report(
        design=design,
        measurements=tuple(measurements),
        parameter_freeze_hash=str(parameter_freeze_hash),
        dataset_snapshot=str(dataset_snapshot),
    )


# -- the replacement machinery ---------------------------------------------------


class ReplacementSelector(str, Enum):
    """How a replacement window is *derived*, as a closed set.

    §6.1 forbids selecting a replacement window from the same data unless the replacement rule was
    pre-registered. A rule that merely said "a replacement may be chosen" would license an
    arbitrary choice, which is the move the sentence exists to stop. Each member below names a
    derivation this module can check the supplied replacement against, so "the rule was
    pre-registered" and "this is the window the rule produces" are two separate refusals.
    """

    IMMEDIATELY_PRECEDING_PERIOD = "IMMEDIATELY_PRECEDING_PERIOD"
    SECOND_PRECEDING_PERIOD = "SECOND_PRECEDING_PERIOD"


_SELECTOR_SHIFTS = {
    ReplacementSelector.IMMEDIATELY_PRECEDING_PERIOD: 1,
    ReplacementSelector.SECOND_PRECEDING_PERIOD: 2,
}

if sorted(_SELECTOR_SHIFTS) != sorted(ReplacementSelector):
    raise ImportError(
        "every ReplacementSelector needs a derivation; a selector with none would be checked by "
        "nothing and would license an arbitrary replacement"
    )


class UnregisteredReplacement(ContractError):
    """A replacement window was requested that no pre-registered rule produces.

    Choosing a window after seeing data is not a measurement outcome the run may carry. It is the
    specific move §6.1 forbids, and the refusal names which of the five conditions failed.
    """


@dataclass(frozen=True)
class PreRegisteredReplacementRule:
    """One rule, registered before the data was seen, that derives a replacement window.

    ``registered_before_block`` is the block at which the rule was recorded. It must be strictly
    before the original window's T0: a rule registered at or after T0 was registered by somebody who
    could already see the window it applies to.
    """

    rule_id: str
    statement: str
    parameter_freeze_hash: str
    selector: ReplacementSelector
    registered_at_commit: str
    registered_before_block: int

    def __post_init__(self) -> None:
        for name in ("rule_id", "statement", "parameter_freeze_hash", "registered_at_commit"):
            if not getattr(self, name) or not str(getattr(self, name)).strip():
                raise ValueError(
                    "a pre-registered replacement rule must state its {}; a rule nobody can trace "
                    "back to a commit and a parameter freeze is not pre-registered, it is "
                    "asserted".format(name)
                )
        if not isinstance(self.selector, ReplacementSelector):
            raise TypeError(
                "a replacement rule must name a ReplacementSelector; a rule with no derivation "
                "would license any window at all"
            )
        require_pre_t0_int(self.registered_before_block, "registered_before_block")


@dataclass(frozen=True)
class ReplacementRegistry:
    """The pre-registered rules, pinned to the parameter freeze they were registered under."""

    rules: Tuple[PreRegisteredReplacementRule, ...]
    parameter_freeze_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "rules", tuple(self.rules))
        if not self.parameter_freeze_hash or not str(self.parameter_freeze_hash).strip():
            raise ValueError("a replacement registry must name its parameter freeze hash")
        seen = set()
        for rule in self.rules:
            if not isinstance(rule, PreRegisteredReplacementRule):
                raise TypeError("ReplacementRegistry.rules holds PreRegisteredReplacementRule")
            if rule.parameter_freeze_hash != self.parameter_freeze_hash:
                raise UnregisteredReplacement(
                    "rule {!r} was registered under parameter freeze {!r} and the registry claims "
                    "{!r}. A rule imported from another freeze is a rule registered against "
                    "different parameters, which is the same thing as an unregistered "
                    "one.".format(rule.rule_id, rule.parameter_freeze_hash,
                                  self.parameter_freeze_hash)
                )
            if rule.rule_id in seen:
                raise UnregisteredReplacement(
                    "rule id {!r} appears twice; nobody can say which rule authorised a "
                    "replacement".format(rule.rule_id)
                )
            seen.add(rule.rule_id)

    def rule(self, rule_id: str) -> Optional[PreRegisteredReplacementRule]:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        return None


@dataclass(frozen=True)
class WindowReplacement:
    """The record of one slot being replaced, carried on the design for good."""

    rule_id: str
    original_key: WindowKey
    original_t0_block: int
    replacement_t0_block: int
    recorded_at_commit: str
    statement: str

    def __post_init__(self) -> None:
        for name in ("rule_id", "recorded_at_commit", "statement"):
            if not getattr(self, name) or not str(getattr(self, name)).strip():
                raise ValueError("a window replacement must state its {}".format(name))
        if not isinstance(self.original_key, WindowKey):
            raise TypeError("WindowReplacement.original_key must be a WindowKey")
        for name in ("original_t0_block", "replacement_t0_block"):
            require_pre_t0_int(getattr(self, name), "WindowReplacement.{}".format(name))


def replace_window(design: WindowDesign, report: Step0Report, rule_id: str,
                   registry: ReplacementRegistry,
                   replacement: TrainingWindow) -> WindowDesign:
    """Replace one window's calendar under a pre-registered rule, or refuse.

    Five refusals, and each closes a different route to choosing a window after seeing data:

    1. the rule id is not in the registry — an unregistered replacement;
    2. the registry's parameter freeze hash is not the one the Step 0 report pinned;
    3. the rule was registered at or after the original window's T0 — registered by somebody who
       could already see the window it applies to;
    4. the replacement's T0 is later than the original's — picking a fresher window after seeing
       data is the specific move §6.1 forbids;
    5. the replacement is not the window the rule's selector derives.

    And one more that is not about the rule at all: a window whose status is ``SUFFICIENT`` may not
    be replaced. §6.1 permits revision because a window *is not valid*; replacing a valid one is
    choosing between measured outcomes.

    :returns: a new :class:`~universe.protocol.WindowDesign` with the slot's calendar replaced,
        ``replaced_from`` set on it, and a :class:`WindowReplacement` appended to the record.
    """
    if not isinstance(registry, ReplacementRegistry):
        raise TypeError("replace_window needs a ReplacementRegistry")
    if type(replacement) is not TrainingWindow:
        raise TypeError("the replacement must be a TrainingWindow")
    if not isinstance(report, Step0Report):
        raise TypeError("replace_window needs the Step0Report that measured the original window")

    original = design.window(replacement.key)
    measurement = report.measurement(replacement.key)

    if measurement.status is WindowStatus.SUFFICIENT:
        raise UnregisteredReplacement(
            "window {} measured {} eligible accounts and its status is {}. §6.1 permits the design "
            "to be revised because a window *is not valid*; replacing a valid one is choosing "
            "between measured outcomes, which is the thing the pre-registration "
            "exists to prevent.".format(
                original.key.value, measurement.eligible_universe_size, measurement.status.value)
        )

    rule = registry.rule(rule_id)
    if rule is None:
        raise UnregisteredReplacement(
            "no pre-registered replacement rule {!r}; the registry holds {}. §6.1: a replacement "
            "window may not be selected from the same data unless the replacement rule was "
            "pre-registered. Registering one now would be registering it after seeing the "
            "measurement it is meant to answer.".format(
                rule_id, ", ".join(sorted(r.rule_id for r in registry.rules)) or "no rules")
        )
    if registry.parameter_freeze_hash != report.parameter_freeze_hash:
        raise UnregisteredReplacement(
            "the registry is pinned to parameter freeze {!r} and the Step 0 report to {!r}. A rule "
            "registered under different parameters was registered against a different "
            "experiment.".format(registry.parameter_freeze_hash, report.parameter_freeze_hash)
        )
    if rule.registered_before_block >= original.t0.block:
        raise UnregisteredReplacement(
            "rule {!r} was registered at block {}, at or after window {}'s T0 block {}. A rule "
            "registered once T0 has passed was registered by somebody who could already see the "
            "window it applies to.".format(
                rule_id, rule.registered_before_block, original.key.value, original.t0.block)
        )
    if replacement.t0.timestamp > original.t0.timestamp:
        raise UnregisteredReplacement(
            "the replacement for window {} has T0 second {}, later than the original's {}. Picking "
            "a fresher window after seeing the data is the specific move §6.1 "
            "forbids.".format(original.key.value, replacement.t0.timestamp, original.t0.timestamp)
        )

    shift = _SELECTOR_SHIFTS[rule.selector] * original.baseline_seconds
    expected_t0 = original.t0.timestamp - shift
    expected_start = original.baseline_start_ts - shift
    if (replacement.t0.timestamp != expected_t0
            or replacement.baseline_start_ts != expected_start):
        raise UnregisteredReplacement(
            "rule {!r} selects {}, which for window {} derives T0 second {} and baseline start {}; "
            "the replacement supplied has {} and {}. The rule is what was pre-registered, so the "
            "window it derives is the only one it authorises.".format(
                rule_id, rule.selector.value, original.key.value, expected_t0, expected_start,
                replacement.t0.timestamp, replacement.baseline_start_ts)
        )

    revised = replace(replacement, replaced_from=original.key)
    windows = tuple(revised if w.key is original.key else w for w in design.windows)
    record = WindowReplacement(
        rule_id=rule.rule_id,
        original_key=original.key,
        original_t0_block=original.t0.block,
        replacement_t0_block=revised.t0.block,
        recorded_at_commit=rule.registered_at_commit,
        statement=rule.statement,
    )
    return WindowDesign(windows=windows, replacements=design.replacements + (record,))


def _t0(block, timestamp):
    """Convenience for callers assembling a calendar. No policy, no defaults."""
    return T0Instant(block=block, timestamp=timestamp)
