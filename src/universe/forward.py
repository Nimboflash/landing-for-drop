"""Ticket 27's required output, and the only module in this package that may name a post-T0 fact.

**In-degree zero inside ``src/universe/``.** Nothing in the package imports it,
``universe/__init__.py`` deliberately does not re-export it, and ``tests/test_post_t0_barrier.py``
asserts all of that statically over committed code. The arrow runs one way, and a module boundary is
the only thing an AST check can key on that is impossible to write by accident and impossible to
hide.

This module shares **no helper, no base class and no field type** with the selection side
--------------------------------------------------------------------------------------------

That sentence used to be false, and the audit proved it by execution. ``require_int`` was called
from ``PreT0Score.__post_init__`` and from ``ForwardActivity.__post_init__``; ``normalise_account``
served both; ``class Sealed`` was one base with one registry, so ``isinstance`` answered ``True``
for a selection record *and* a forward record; ``T0Instant`` and ``WindowKey`` were field types on
both families. Every one of those is a signature that accepts both families, which is criterion 1
failing six different ways.

So this module now carries its **own** copies: :class:`ForwardSealed` with its own registry,
:func:`require_forward_int`, :func:`normalise_forward_account`, :class:`ForwardT0Instant`,
:class:`ForwardWindowKey`, :data:`FORWARD_SECONDS_PER_DAY`. They are near-identical to the selection
side's and that is not an argument against them: the point is not that they behave differently, it
is that **no function signature anywhere accepts a value from both families**. Duplication costs a
reader twenty lines. A shared tunnel costs the experiment its result.

The only two selection-side names this module imports are
:class:`universe.artifact.SelectedWalletArtifact` and :class:`universe.ordering.ForwardMount` — the
sealed handoff and the proof that steps 1-6 happened. They are the designated crossing, they carry
primitives only, and they are what makes the ordering checkable rather than conventional.

Why there is a type wall as well as an import wall
---------------------------------------------------

The import wall cannot reach the composition root, which legitimately holds both halves. There, and
only there, :class:`ForwardCount` is what makes::

    still_active = [w for w in basket.wallets if activity[w].forward_valid_buys > 0]

raise instead of returning a filtered list. ``ForwardCount`` refuses ordering, equality, truthiness,
hashing, integer conversion and arithmetic — which is every shape a "still active" filter takes:
sort, group, dedupe, set-test, dict-key, truth-test. **Unhashable is the one people forget and the
most valuable**, because the dict and the set are how such a filter is actually written.

What that does **not** buy, stated because an overclaimed guarantee is worse than an accurate weaker
one. The payload is a plain ``int`` and is reachable from inside this module — it has to be, because
``reporting`` needs the number to compute a churn rate. The honest boundary is **accident versus
intent**: every name a caller reaches for by the domain's vocabulary yields a refusing type, and
getting a selection-readable value out takes a second, differently-named call —
:func:`disclose_for_churn` — that says in a diff what it is doing.

The mirror guard
----------------

:class:`ForwardActivity` refuses a first activity block at or before ``T0``. That guard is as
important as ``require_pre_t0`` and much easier to leave out: without it this type is a laundering
vehicle, since anyone can put pre-T0 activity into a record whose *name* says post-T0 and hand it to
something that trusts the name.

There is deliberately **no upper bound** on ``forward_valid_buys``, pinned by a test. §6.4 forbids
removing a wallet for exceeding 1,000 buys after T0, and a bound here would be exactly that removal
arriving as a validation error.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Tuple, Union

from contracts import ContractError, LookAheadViolation, require_finite

from .artifact import SelectedWalletArtifact, require_sealed_artifact
from .ordering import ForwardMount
from .provenance import ContaminatedDecimal, Origin

#: This module's own copy. ``universe.protocol.SECONDS_PER_DAY`` is the selection side's and is
#: deliberately not imported: a shared constant is a shared import, and a shared import is the hop
#: the barrier check is built to see.
FORWARD_SECONDS_PER_DAY = 86400

#: Bump when any type here changes shape.
FORWARD_SCHEMA_VERSION = "forward-v1"


class ForwardReadRefused(LookAheadViolation):
    """A post-T0 count was asked to behave like a number.

    A subclass of :class:`contracts.LookAheadViolation` rather than a ``TypeError``, for
    ``_NeverGating``'s reason: an agent reading ``'>' not supported between instances of
    'ForwardCount' and 'int'`` fixes it by unwrapping the value, which *is* the bug. An agent
    reading this, and §6.4's own sentence, does not.
    """


class ForwardCoverageGap(ContractError):
    """The post-T0 ledger does not cover the artifact exactly.

    Absence here **flatters** the result, which is what makes it the shape that must raise rather
    than default: a dormant wallet whose row is simply missing drops out of the churn denominator
    and the churn rate looks better than it is. That is the same survivorship bug as a pre-filter,
    arriving through the output path instead of the input path.
    """


class ForwardDerivationRefused(ContractError):
    """A type this module seals was subclassed."""


#: The **post-T0 side's** sealing registry. Separate from ``universe.protocol._PRE_T0_SEALED``, and
#: that separation is the whole repair: one registry over both families made a single base
#: ``isinstance``-true for a selection record and a forward record at the same time.
_FORWARD_SEALED = set()


class ForwardSealed(object):
    """Base of every sealed post-T0 type. Deriving from one is refused at class-definition time.

    No selection type derives from this and no forward type derives from the selection side's base,
    so there is no class anywhere for which ``isinstance`` is true on both sides.
    """

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        for base in cls.__mro__[1:]:
            if base in _FORWARD_SEALED:
                raise ForwardDerivationRefused(
                    "{} derives from {}, which is sealed on the post-T0 side. A subclass could "
                    "override the mirror guard while remaining an isinstance of the base, or carry "
                    "a second base and so a second standing — one object that is both a post-T0 "
                    "record and something a selection function accepts.".format(
                        cls.__name__, base.__name__)
                )


def forward_sealed(cls: type) -> type:
    """Mark a post-T0 class un-derivable. Applied above ``@dataclass`` so it runs last."""
    _FORWARD_SEALED.add(cls)
    return cls


def normalise_forward_account(address: str) -> str:
    """Strip, lowercase, and refuse an empty address — the post-T0 side's own copy.

    Byte-identical in behaviour to ``universe.protocol.normalise_selection_account`` and separate
    from it on purpose. The audit called that function with a forward-side value and a
    selection-side value in the same parameter and both succeeded; that is what "a signature that
    accepts both families" means, and no annotation fixes it.
    """
    if not isinstance(address, str):
        raise TypeError(
            "a post-T0 account address must be a str, got {}".format(type(address).__name__)
        )
    text = address.strip().lower()
    if not text:
        raise ValueError("a post-T0 record with no address cannot be matched to a selected wallet")
    return text


def require_forward_int(value: int, name: str) -> int:
    """Blocks, UTC seconds and counts are ``int`` by seam rule — the post-T0 side's own copy.

    ``bool`` is refused explicitly because it *is* an ``int`` in Python.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            "{} must be an int; post-T0 block numbers, UTC seconds and counts are int by seam "
            "rule. Got {}.".format(name, type(value).__name__)
        )
    return value


@forward_sealed
@dataclass(frozen=True)
class ForwardT0Instant(ForwardSealed):
    """The selection instant as the **post-T0 side** records it.

    A separate type from ``universe.protocol.T0Instant`` carrying the same two numbers. The audit's
    finding was that the shared one was a field type on both ``PreT0Score`` and ``ForwardActivity``,
    so any function taking a ``T0Instant`` took a piece of either family — and the constructor of
    each family accepted a value that had travelled through the other.
    """

    block: int
    timestamp: int

    def __post_init__(self) -> None:
        for name in ("block", "timestamp"):
            value = require_forward_int(getattr(self, name), "ForwardT0Instant.{}".format(name))
            if value <= 0:
                raise ValueError(
                    "ForwardT0Instant.{} is {}; a non-positive block or UTC second is not an "
                    "instant on this chain".format(name, value)
                )


class ForwardWindowKey(str, Enum):
    """§6.3's four windows, as the post-T0 side names them.

    Closed, like the selection side's, and separate from it. The two enums have equal member names
    and are **not** interchangeable: ``ForwardActivity`` refuses a selection ``WindowKey``, so a
    forward record cannot be keyed by an object that a selection function would also accept.
    """

    W1_2023H1 = "W1_2023H1"
    W2_2023H2 = "W2_2023H2"
    W3_2024H1 = "W3_2024H1"
    W4_2024H2 = "W4_2024H2"


class ForwardDecimal(object):
    """A ``Decimal`` measured after ``T0``, carrying ``POST_T0`` into any expression it enters.

    The post-T0 half of the provenance lattice. ``POST_T0 + anything -> CONTAMINATED``, with no
    exception for the case where the other operand is pre-T0 and much larger, or where the operation
    is a division that "only scales" — every such exception is a rule nobody pre-registered.

    So every arithmetic operator here returns a :class:`universe.provenance.ContaminatedDecimal`,
    which holds no number and raises on every read. That is what closes the laundering route the
    brief names::

        laundered = pre_t0_score / (Decimal("1") + forward_return)

    If ``forward_return`` is a :class:`ForwardDecimal`, the inner sum is contaminated, the division
    is contaminated, and ``PreT0Score(value=laundered)`` raises. No forward *object* is read at any
    point, and no runtime descriptor could have seen it.

    Like :class:`ForwardCount`, it refuses comparison, truthiness, hashing and conversion, so it
    cannot be a sort key, a dict key, a set member or a filter predicate.
    """

    __slots__ = ("_post_t0_decimal", "_measured_at_block")

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise ForwardDerivationRefused(
            "{} derives from ForwardDecimal. A subclass could return a plain Decimal from an "
            "operator and re-enter the selection path as an ordinary number.".format(cls.__name__)
        )

    def __init__(self, value: Union[Decimal, int, str], measured_at_block: int) -> None:
        if isinstance(value, float):
            raise TypeError(
                "a float reached ForwardDecimal ({!r}); construct from str, int or Decimal".format(
                    value)
            )
        object.__setattr__(self, "_post_t0_decimal",
                           require_finite(value, "ForwardDecimal value"))
        object.__setattr__(self, "_measured_at_block",
                           require_forward_int(measured_at_block, "ForwardDecimal.measured_at_block"))

    @property
    def origin(self) -> Origin:
        """Always :attr:`universe.provenance.Origin.POST_T0`. Readable because it is not the number."""
        return Origin.POST_T0

    def _refuse(self, what: str) -> "ForwardDecimal":
        raise ForwardReadRefused(
            "a post-T0 value was used in {}. §6.4: post-T0 quantities are reported as an output, "
            "never used as a selection filter, a sort key or a threshold. If this belongs in a "
            "report, project it with universe.forward.disclose_forward_decimal, which says in the "
            "diff what it is doing.".format(what)
        )

    def _contaminate(self, op: str) -> ContaminatedDecimal:
        return ContaminatedDecimal(("POST_T0", "{}(POST_T0)".format(op)))

    def __add__(self, other: object) -> ContaminatedDecimal:
        return self._contaminate("add")

    __radd__ = __add__

    def __sub__(self, other: object) -> ContaminatedDecimal:
        return self._contaminate("sub")

    __rsub__ = __sub__

    def __mul__(self, other: object) -> ContaminatedDecimal:
        return self._contaminate("mul")

    __rmul__ = __mul__

    def __truediv__(self, other: object) -> ContaminatedDecimal:
        return self._contaminate("div")

    __rtruediv__ = __truediv__

    def __neg__(self) -> ContaminatedDecimal:
        return self._contaminate("neg")

    def __lt__(self, other: object) -> bool:
        return self._refuse("an ordering comparison")

    def __le__(self, other: object) -> bool:
        return self._refuse("an ordering comparison")

    def __gt__(self, other: object) -> bool:
        return self._refuse("an ordering comparison")

    def __ge__(self, other: object) -> bool:
        return self._refuse("an ordering comparison")

    def __eq__(self, other: object) -> bool:
        return self._refuse("an equality test")

    def __ne__(self, other: object) -> bool:
        return self._refuse("an equality test")

    def __bool__(self) -> bool:
        return self._refuse("a truth test")

    def __int__(self) -> int:
        return self._refuse("an int() conversion")

    def __float__(self) -> float:
        return self._refuse("a float() conversion")

    def __reduce__(self) -> object:
        raise ForwardReadRefused(
            "a post-T0 value cannot be pickled; a round trip would rebuild the payload with none "
            "of the refusals attached to it"
        )

    __hash__ = None  # a post-T0 Decimal is no more a dict key than a post-T0 count is

    def __repr__(self) -> str:
        return "<ForwardDecimal post-T0>"


class ForwardCount(object):
    """A post-T0 count, in a type that refuses to behave like one.

    Not a dataclass, on purpose: ``contracts.canonicalise`` serialises dataclasses field by field,
    so a dataclass here would reach an artefact un-projected. This class has no canonical form at
    all, and ``canonicalise`` raises on it.

    Every operator a filter needs raises. ``__hash__`` is ``None``, so it cannot be a dict key or a
    set member. ``__repr__`` prints without the number, so it cannot leak into a log somebody
    decides from.

    Sealed against subclassing, so ``class Live(ForwardCount, UniverseMember)`` cannot exist in
    either base order.
    """

    __slots__ = ("_post_t0_value",)

    def __init_subclass__(cls, **kwargs: object) -> None:  # pragma: no cover - the refusal is the behaviour
        raise ForwardReadRefused(
            "{} derives from ForwardCount. A subclass could override the refusals below, or carry "
            "a second base and so a second standing — one object that is both a post-T0 count and "
            "something a selection function accepts.".format(cls.__name__)
        )

    def __init__(self, value: int) -> None:
        object.__setattr__(self, "_post_t0_value",
                           require_forward_int(value, "ForwardCount value"))
        if self._post_t0_value < 0:
            raise ValueError("a post-T0 count is a magnitude; got {}".format(self._post_t0_value))

    def _refuse(self, what: str) -> "ForwardCount":
        raise ForwardReadRefused(
            "a post-T0 count was used in {}. §6.4: post-T0 activity is reported as an output, never "
            "used as a selection filter — and every spelling of a 'still active' filter is one of "
            "sort, group, dedupe, set-test, dict-key or truth-test. If this belongs in a report, "
            "project it with universe.forward.disclose_for_churn, which says in the diff what it is "
            "doing.".format(what)
        )

    def __lt__(self, other: object) -> bool:
        self._refuse("an ordering comparison")

    def __le__(self, other: object) -> bool:
        self._refuse("an ordering comparison")

    def __gt__(self, other: object) -> bool:
        self._refuse("an ordering comparison")

    def __ge__(self, other: object) -> bool:
        self._refuse("an ordering comparison")

    def __eq__(self, other: object) -> bool:
        self._refuse("an equality test")

    def __ne__(self, other: object) -> bool:
        self._refuse("an equality test")

    def __bool__(self) -> bool:
        self._refuse("a truth test")

    def __int__(self) -> int:
        self._refuse("an int() conversion")

    def __index__(self) -> int:
        self._refuse("an index conversion")

    def __float__(self) -> float:
        self._refuse("a float() conversion")

    def __add__(self, other: object) -> "ForwardCount":
        self._refuse("arithmetic")

    __radd__ = __add__
    __sub__ = __add__
    __rsub__ = __add__
    __mul__ = __add__
    __rmul__ = __add__

    def __reduce__(self) -> object:
        raise ForwardReadRefused(
            "a ForwardCount cannot be pickled. pickle.loads reconstructs the object without calling "
            "__init__, so the payload would come back wrapped in a type that never ran a single one "
            "of the refusals above — the audit demonstrated exactly that round trip."
        )

    __hash__ = None

    def __repr__(self) -> str:
        return "<ForwardCount post-T0>"


@forward_sealed
@dataclass(frozen=True, eq=False)
class ForwardActivity(ForwardSealed):
    """One selected wallet's activity **after** ``T0``.

    ``eq=False`` because :class:`ForwardCount` refuses equality, so a generated ``__eq__`` would
    raise on any comparison of two records.

    The mirror guard is in ``__post_init__``: ``first_forward_block`` must be strictly after T0.
    See the module docstring for why that is not a formality.

    ``window_key`` is a :class:`ForwardWindowKey` and ``t0`` a :class:`ForwardT0Instant` — the
    post-T0 side's own enums and value types. Handing this constructor the selection side's
    ``WindowKey`` or ``T0Instant`` is refused, which is the field-type half of criterion 1.
    """

    wallet: str
    window_key: ForwardWindowKey
    snapshot_id: str
    forward_valid_buys: ForwardCount
    forward_days: int
    first_forward_block: int
    measured_at_block: int
    t0: ForwardT0Instant

    def __post_init__(self) -> None:
        object.__setattr__(self, "wallet", normalise_forward_account(self.wallet))
        if type(self.window_key) is not ForwardWindowKey:
            raise TypeError(
                "ForwardActivity.window_key must be a ForwardWindowKey, got {}. The selection "
                "side's WindowKey is refused here on purpose: a field type shared between the two "
                "families is a parameter that accepts either of them.".format(
                    type(self.window_key).__name__)
            )
        if type(self.t0) is not ForwardT0Instant:
            raise TypeError(
                "ForwardActivity.t0 must be a ForwardT0Instant, got {}".format(
                    type(self.t0).__name__)
            )
        if type(self.forward_valid_buys) is not ForwardCount:
            raise ForwardReadRefused(
                "{} carries a {} where a ForwardCount belongs. A bare int here is a post-T0 number "
                "in a type every selection function accepts, which is the whole of what this "
                "module exists to prevent.".format(self.wallet,
                                                   type(self.forward_valid_buys).__name__)
            )
        if not self.snapshot_id or not str(self.snapshot_id).strip():
            raise ValueError(
                "{}'s post-T0 record must name the sealed artifact it belongs to, or it could be "
                "reported against a universe it was not measured over".format(self.wallet)
            )
        for name in ("forward_days", "first_forward_block", "measured_at_block"):
            value = require_forward_int(getattr(self, name), "ForwardActivity.{}".format(name))
            if value < 0:
                raise ValueError("ForwardActivity.{} is {}".format(name, value))
        if self.forward_days <= 0:
            raise ValueError(
                "{} has a post-T0 period of {} day(s); a period of no length cannot carry a trade "
                "rate, and ``reporting.WalletActivity`` refuses one".format(
                    self.wallet, self.forward_days)
            )
        if self.first_forward_block <= self.t0.block:
            raise LookAheadViolation(
                "{} claims its first post-T0 activity at block {}, at or before T0 block {}. This "
                "is the mirror of require_pre_t0 and it is the half that is easy to leave out: "
                "without it, pre-T0 activity can be placed in a record whose name says post-T0 and "
                "handed to something that trusts the name.".format(
                    self.wallet, self.first_forward_block, self.t0.block)
            )
        if self.measured_at_block < self.first_forward_block:
            raise ValueError(
                "{} was measured at block {}, before its first post-T0 activity at {}".format(
                    self.wallet, self.measured_at_block, self.first_forward_block)
            )


@dataclass(frozen=True)
class ForwardDisclosure:
    """One wallet's counts as **plain ints**, ready for ``reporting.WalletActivity``.

    Exactly ``WalletActivity``'s five constructor arguments, in this package's own type because
    ``universe`` is a leaf and may not import ``reporting``. The composition root does the one-line
    adaptation, and that adaptation is the visible seam between the two packages.
    """

    wallet: str
    baseline_valid_buys: int
    baseline_days: int
    forward_valid_buys: int
    forward_days: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "wallet", normalise_forward_account(self.wallet))
        for name in ("baseline_valid_buys", "baseline_days", "forward_valid_buys", "forward_days"):
            value = require_forward_int(getattr(self, name),
                                        "ForwardDisclosure.{}".format(name))
            if value < 0:
                raise ValueError("ForwardDisclosure.{} is {}".format(name, value))


@dataclass(frozen=True, eq=False)
class ForwardLedger:
    """Every selected wallet's post-T0 record, in a container that cannot answer a membership test.

    There is no ``__contains__``, no ``__getitem__``, no ``__iter__``, no ``keys`` and no
    ``wallets``. Even inside the composition root — which legitimately holds both halves — the
    ledger cannot answer "is this wallet in it", which is the container-level version of the same
    argument :class:`ForwardCount` makes about values.

    The one public reader is :func:`disclose_for_churn`.
    """

    artifact_hash: str
    window_key: ForwardWindowKey
    t0: ForwardT0Instant
    records: Tuple[ForwardActivity, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        if type(self.window_key) is not ForwardWindowKey:
            raise TypeError("ForwardLedger.window_key must be a ForwardWindowKey")
        if type(self.t0) is not ForwardT0Instant:
            raise TypeError("ForwardLedger.t0 must be a ForwardT0Instant")
        if not self.artifact_hash or not str(self.artifact_hash).strip():
            raise ValueError("a post-T0 ledger must name the sealed artifact it covers")
        for record in self.records:
            if type(record) is not ForwardActivity:
                raise TypeError(
                    "ForwardLedger.records holds ForwardActivity values, got {}".format(
                        type(record).__name__)
                )

    def __len__(self) -> int:
        return len(self.records)


@dataclass(frozen=True)
class ForwardActivityReport:
    """Ticket 27's post-T0 output, in plain ints, for a report to render.

    ``max_forward_valid_buys`` is published deliberately and has no bound. §6.4 forbids removing a
    wallet for exceeding 1,000 buys after T0, so a wallet at 5,000 is a **finding** — and one that
    would be invisible if this figure were clamped to the eligibility ceiling.
    """

    window_key: ForwardWindowKey
    artifact_hash: str
    n_wallets: int
    n_with_forward_activity: int
    n_dormant: int
    max_forward_valid_buys: int
    total_forward_valid_buys: int

    def __post_init__(self) -> None:
        if type(self.window_key) is not ForwardWindowKey:
            raise TypeError("ForwardActivityReport.window_key must be a ForwardWindowKey")
        for name in ("n_wallets", "n_with_forward_activity", "n_dormant",
                     "max_forward_valid_buys", "total_forward_valid_buys"):
            value = require_forward_int(getattr(self, name),
                                        "ForwardActivityReport.{}".format(name))
            if value < 0:
                raise ValueError("ForwardActivityReport.{} is {}".format(name, value))
        if self.n_with_forward_activity + self.n_dormant != self.n_wallets:
            raise ForwardCoverageGap(
                "the post-T0 report holds {} active and {} dormant wallet(s) against a population "
                "of {}; a wallet in neither state would leave the churn denominator".format(
                    self.n_with_forward_activity, self.n_dormant, self.n_wallets)
            )


@dataclass(frozen=True)
class FrozenEvaluationConfig:
    """The evaluation side's pinned parameters. Frozen for the same reason the selection ones are.

    There is no ``filter``, no ``min_activity`` and no ``drop_dormant``. §6.4 forbids removing a
    wallet after T0 for any of the four reasons it names, and a configuration key is how the fifth
    would arrive.
    """

    commit: str
    forward_period_days: int
    schema_version: str = FORWARD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.commit or not str(self.commit).strip():
            raise ValueError("an evaluation must be pinned to a commit to be reproducible")
        value = require_forward_int(self.forward_period_days,
                                    "FrozenEvaluationConfig.forward_period_days")
        if value <= 0:
            raise ValueError(
                "a forward period of {} day(s) carries no rate and is refused".format(value))


@dataclass(frozen=True, eq=False)
class ForwardDataset:
    """The post-T0 dataset, which cannot be constructed before a sealed artifact exists.

    ``artifact_hash`` is required and is checked against the mount at evaluation time. The audit's
    finding was that ``snapshot_id`` was "a caller-supplied string ('whatever-the-caller-types') and
    nothing validates it against a produced artifact" — this closes that by construction.
    """

    dataset_id: str
    artifact_hash: str
    records: Tuple[ForwardActivity, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        for name in ("dataset_id", "artifact_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    "a forward dataset must name its {}. A dataset that does not name the sealed "
                    "artifact it was assembled after is a dataset that could have existed "
                    "before it.".format(name)
                )
            object.__setattr__(self, name, value.strip())
        for record in self.records:
            if type(record) is not ForwardActivity:
                raise TypeError(
                    "ForwardDataset.records holds ForwardActivity values, got {}".format(
                        type(record).__name__)
                )

    def __len__(self) -> int:
        return len(self.records)


@dataclass(frozen=True)
class ForwardEvaluationArtifact:
    """The evaluation side's output — the mirror of :class:`universe.artifact.SelectedWalletArtifact`.

    Carries the selection artifact's hash so the two are pinned together: an evaluation whose
    ``selection_artifact_hash`` does not match the artifact a reader holds describes a different
    basket, and saying so is the whole of what this field is for.
    """

    selection_artifact_hash: str
    dataset_id: str
    window_key: ForwardWindowKey
    #: Named ``activity_report`` and not ``report`` on purpose. ``tests/test_post_t0_barrier.py``
    #: derives the guarded vocabulary as the names defined in this module *and nowhere else in the
    #: package*; ``report`` is a parameter name in ``step0`` and ``freeze``, so spelling this field
    #: ``report`` either flags two innocent selection modules or — once somebody silences that —
    #: teaches the check to ignore a name this module really does own. A distinctive name keeps the
    #: derivation both precise and self-maintaining.
    activity_report: ForwardActivityReport
    disclosures: Tuple[ForwardDisclosure, ...]
    schema_version: str = FORWARD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "disclosures", tuple(self.disclosures))
        if type(self.activity_report) is not ForwardActivityReport:
            raise TypeError(
                "ForwardEvaluationArtifact.activity_report must be a ForwardActivityReport")
        if type(self.window_key) is not ForwardWindowKey:
            raise TypeError("ForwardEvaluationArtifact.window_key must be a ForwardWindowKey")
        if not self.selection_artifact_hash or not str(self.selection_artifact_hash).strip():
            raise ValueError(
                "an evaluation artifact must name the selection artifact it evaluates")


def forward_ledger(mount: ForwardMount,
                   activities: Tuple[ForwardActivity, ...]) -> ForwardLedger:
    """Bind post-T0 records to a **sealed, mounted** selection artifact.

    :param mount: a :class:`universe.ordering.ForwardMount` — proof that the artifact was produced,
        hashed and sealed, that selection terminated and that the pre-T0 workspace was unmounted.
        First argument on purpose, and a mount rather than a live basket: the audit's version took a
        ``SelectedBasket``, which exists from the moment ranking finishes and therefore gated
        nothing about *when* forward data could be assembled.
    :param activities: exactly one :class:`ForwardActivity` per selected wallet.

    :raises ForwardCoverageGap: on a missing record or an unselected one. A dormant wallet whose row
        is simply absent would drop out of the churn denominator and make the rate look better,
        which is the survivorship bug arriving through the output path.
    """
    if type(mount) is not ForwardMount:
        raise TypeError(
            "forward_ledger takes a ForwardMount, got {}. Selection has to have been sealed and "
            "the pre-T0 workspace unmounted before any post-T0 record is consumed, and the "
            "argument type is what says so.".format(type(mount).__name__)
        )
    artifact = require_sealed_artifact(mount.artifact, "assembling the post-T0 ledger")
    records = tuple(activities)
    seen = {}
    for record in records:
        if type(record) is not ForwardActivity:
            raise TypeError(
                "forward_ledger takes ForwardActivity values, got {}".format(type(record).__name__)
            )
        if record.wallet in seen:
            raise ForwardCoverageGap(
                "{} has two post-T0 records; a wallet counted twice moves every rate in the churn "
                "block and the duplicate is invisible in the result".format(record.wallet)
            )
        if record.snapshot_id != artifact.artifact_hash:
            raise ForwardCoverageGap(
                "{}'s post-T0 record is against {} and the sealed artifact hashes to {}. A record "
                "naming another artifact describes a different population, and the identifier is "
                "the artifact's own hash rather than a string the caller typed.".format(
                    record.wallet, record.snapshot_id, artifact.artifact_hash)
            )
        if record.window_key.value != artifact.window_id:
            raise ForwardCoverageGap(
                "{}'s post-T0 record is for window {} and the artifact is for {}".format(
                    record.wallet, record.window_key.value, artifact.window_id)
            )
        seen[record.wallet] = record

    selected = set(artifact.wallets)
    missing = sorted(selected - set(seen))
    extra = sorted(set(seen) - selected)
    if missing or extra:
        raise ForwardCoverageGap(
            "the post-T0 ledger does not cover the sealed artifact exactly: {} selected wallet(s) "
            "have no record ({}{}) and {} record(s) are for wallets that were not selected ({}{}). "
            "Absence here flatters the result — a dormant wallet with no row leaves the churn "
            "denominator and the churn rate improves — so it raises rather than defaulting to "
            "zero.".format(
                len(missing), ", ".join(missing[:5]),
                "" if len(missing) <= 5 else " (+{} more)".format(len(missing) - 5),
                len(extra), ", ".join(extra[:5]),
                "" if len(extra) <= 5 else " (+{} more)".format(len(extra) - 5),
            )
        )

    t0 = None
    for record in records:
        if t0 is None:
            t0 = record.t0
        elif record.t0 != t0:
            raise ForwardCoverageGap(
                "the post-T0 records carry two different T0 instants; they describe two windows"
            )
    return ForwardLedger(
        artifact_hash=artifact.artifact_hash,
        window_key=ForwardWindowKey(artifact.window_id),
        t0=t0,
        records=records,
    )


def disclose_for_churn(ledger: ForwardLedger,
                       baseline: Tuple["BaselineFact", ...]) -> Tuple[ForwardDisclosure, ...]:
    """The one public reader: project the ledger into plain-int disclosures for ``reporting``.

    Named so that it appears in a diff as what it is. This is the only place a
    :class:`ForwardCount` is unwrapped, and the second, differently-named call the module docstring
    promises.

    :param ledger: the :class:`ForwardLedger`.
    :param baseline: a tuple of :class:`BaselineFact` — pre-T0 counts supplied by the composition
        root, one per wallet. A tuple of nominal records rather than a ``Dict[str, Tuple[int, int]]``
        on purpose: a mapping accepts any key and any pair, so a baseline assembled from the wrong
        column is a shape nothing here could refuse. Required for every wallet in the ledger: a
        wallet whose baseline is missing would be dropped from the churn population, which is the
        coverage gap this module refuses one argument over.

    :returns: a tuple of :class:`ForwardDisclosure`, in wallet order, covering **every** wallet in
        the ledger including the fully dormant ones.
    """
    if type(ledger) is not ForwardLedger:
        raise TypeError("disclose_for_churn takes a ForwardLedger, got {}".format(
            type(ledger).__name__))
    facts = {}
    for fact in tuple(baseline):
        if type(fact) is not BaselineFact:
            raise TypeError(
                "disclose_for_churn takes BaselineFact values, got {}".format(type(fact).__name__))
        facts[fact.wallet] = fact
    out = []
    for record in sorted(ledger.records, key=lambda r: r.wallet):
        if record.wallet not in facts:
            raise ForwardCoverageGap(
                "{} has a post-T0 record and no baseline. Dropping it here would remove a wallet "
                "from the churn denominator, and the wallets whose baselines are hardest to "
                "assemble are not a random sample of the basket.".format(record.wallet)
            )
        fact = facts[record.wallet]
        out.append(ForwardDisclosure(
            wallet=record.wallet,
            baseline_valid_buys=fact.baseline_valid_buys,
            baseline_days=fact.baseline_days,
            # The one unwrap. Everything above this line refuses to read the number.
            forward_valid_buys=record.forward_valid_buys._post_t0_value,
            forward_days=record.forward_days,
        ))
    return tuple(out)


@dataclass(frozen=True)
class BaselineFact:
    """One wallet's pre-T0 counts, restated on the post-T0 side for the churn denominator.

    Restated rather than imported. These two integers are the only pre-T0 facts the churn block
    needs, and a nominal record for them is what keeps ``disclose_for_churn``'s second parameter
    from being a mapping that any pair of numbers fits through.
    """

    wallet: str
    baseline_valid_buys: int
    baseline_days: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "wallet", normalise_forward_account(self.wallet))
        for name in ("baseline_valid_buys", "baseline_days"):
            value = require_forward_int(getattr(self, name), "BaselineFact.{}".format(name))
            if value < 0:
                raise ValueError("BaselineFact.{} is {}".format(name, value))


def disclose_forward_decimal(value: ForwardDecimal, what: str) -> Decimal:
    """The one public reader for a :class:`ForwardDecimal`. Named so it shows up in a diff.

    :param what: what the projection is for, recorded in the refusal if the wrong type arrives.
    """
    if type(value) is not ForwardDecimal:
        raise ForwardReadRefused(
            "disclose_forward_decimal takes a ForwardDecimal, got {} (for {})".format(
                type(value).__name__, what)
        )
    return value._post_t0_decimal


def forward_report(ledger: ForwardLedger) -> ForwardActivityReport:
    """Ticket 27's post-T0 output block, in plain ints."""
    if type(ledger) is not ForwardLedger:
        raise TypeError("forward_report takes a ForwardLedger, got {}".format(
            type(ledger).__name__))
    counts = [record.forward_valid_buys._post_t0_value for record in ledger.records]
    if not counts:
        raise ForwardCoverageGap(
            "a post-T0 report over no wallets. An empty ledger reads as 'nobody traded', which is "
            "the opposite of what an empty basket means."
        )
    return ForwardActivityReport(
        window_key=ledger.window_key,
        artifact_hash=ledger.artifact_hash,
        n_wallets=len(counts),
        n_with_forward_activity=sum(1 for c in counts if c > 0),
        n_dormant=sum(1 for c in counts if c == 0),
        max_forward_valid_buys=max(counts),
        total_forward_valid_buys=sum(counts),
    )


def evaluate_selected_wallets(selected: ForwardMount, forward_data: ForwardDataset,
                              config: FrozenEvaluationConfig,
                              baseline: Tuple[BaselineFact, ...]) -> ForwardEvaluationArtifact:
    """The evaluation-side contract. Takes the mount, the dataset and the frozen config, and nothing
    that could reach back into selection.

    The brief's signature names ``SelectedWalletArtifact`` for the first parameter. This takes the
    :class:`universe.ordering.ForwardMount` that *carries* one, and the difference is the point:
    an artifact on its own exists from the moment it is sealed, so a function taking one could run
    while the pre-T0 workspace was still mounted. A mount cannot exist before step 7.

    That last sentence used to be false, and it is worth recording why: ``ForwardMount``'s
    constructor was public, so ``ForwardMount(artifact, dataset_id, dataset_hash)`` written out at
    phase ``ARTIFACT_SEALED`` produced one, and this function ran to completion over two hundred and
    fifty wallets with the pre-T0 workspace still readable and the order unaware a mount existed. It
    is true now because the constructor demands a token only
    :meth:`universe.ordering.ExecutionOrder.mount_forward` holds — a claim of this shape has to be
    enforced by the type, because it is exactly the kind nobody re-checks.

    :raises ForwardCoverageGap: if the dataset does not name the mounted artifact, or does not cover
        it exactly.
    """
    if type(selected) is not ForwardMount:
        raise TypeError(
            "evaluate_selected_wallets takes a ForwardMount, got {}".format(type(selected).__name__))
    if type(forward_data) is not ForwardDataset:
        raise TypeError(
            "evaluate_selected_wallets takes a ForwardDataset, got {}. A bare list of records would "
            "carry no artifact hash, and the audit's finding was precisely that the identifier "
            "binding forward data to a selection was a string the caller typed.".format(
                type(forward_data).__name__)
        )
    if type(config) is not FrozenEvaluationConfig:
        raise TypeError(
            "evaluate_selected_wallets takes a FrozenEvaluationConfig, got {}".format(
                type(config).__name__))
    artifact = require_sealed_artifact(selected.artifact, "evaluating the selected wallets")
    if forward_data.artifact_hash != artifact.artifact_hash:
        raise ForwardCoverageGap(
            "the forward dataset was assembled against artifact {} and the mount carries {}. The "
            "two must be one artifact, or the evaluation describes a basket nobody "
            "selected.".format(forward_data.artifact_hash, artifact.artifact_hash)
        )
    if forward_data.dataset_id != selected.dataset_id:
        raise ForwardCoverageGap(
            "the forward dataset is {!r} and the mount opened {!r}".format(
                forward_data.dataset_id, selected.dataset_id)
        )
    ledger = forward_ledger(selected, forward_data.records)
    return ForwardEvaluationArtifact(
        selection_artifact_hash=artifact.artifact_hash,
        dataset_id=forward_data.dataset_id,
        window_key=ledger.window_key,
        activity_report=forward_report(ledger),
        disclosures=disclose_for_churn(ledger, baseline),
    )


def forward_period_days(forward_end_ts: int, t0_timestamp: int) -> int:
    """The window's post-T0 period in whole UTC days, from two integers.

    Two ints rather than a ``TrainingWindow``: the previous spelling took the selection side's
    calendar type, which made this a public post-T0 function whose parameter accepted a
    selection-family value. That is criterion 1's failure in its smallest form.
    """
    require_forward_int(forward_end_ts, "forward_period_days forward_end_ts")
    require_forward_int(t0_timestamp, "forward_period_days t0_timestamp")
    if forward_end_ts <= t0_timestamp:
        raise ValueError(
            "a forward period ending at second {} against a T0 of {} has no length".format(
                forward_end_ts, t0_timestamp)
        )
    return (forward_end_ts - t0_timestamp) // FORWARD_SECONDS_PER_DAY
