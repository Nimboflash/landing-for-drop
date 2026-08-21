"""Provenance that travels **with the value**, so laundering has nowhere to hide.

A runtime descriptor on a forward field catches a *direct read*. It cannot catch this::

    forward_return  = Decimal("0.42")            # already unwrapped, somewhere upstream
    laundered_score = pre_t0_score / (Decimal("1") + forward_return)
    PreT0Score(value=laundered_score)            # no forward object is read at all

By the time the selection type sees it, the number is an ordinary ``Decimal`` and every check that
inspects *objects* passes. The only thing that closes it is a provenance the arithmetic carries.

The algebra
-----------

::

    PRE_T0       + PRE_T0    -> PRE_T0
    PRE_T0       + POST_T0   -> CONTAMINATED
    POST_T0      + anything  -> CONTAMINATED
    CONTAMINATED + anything  -> CONTAMINATED

and one clause the brief's table leaves implicit and this module makes explicit:

::

    PRE_T0       + <bare Decimal / int / str>  -> CONTAMINATED

A bare ``Decimal`` has *unknown* provenance, and unknown is not ``PRE_T0``. Treating it as pre-T0
would reopen the laundering route in one line, because a laundered value is exactly a bare Decimal.
The one door for a genuinely pre-registered constant is :meth:`PreT0Decimal.pre_registered`, which
is a differently-named call that says in a diff what it is doing.

Why ``CONTAMINATED`` refuses to hold a number
----------------------------------------------

:class:`ContaminatedDecimal` carries **no value at all**. It records the trail that produced it and
raises on every read, every comparison, every truth test and every conversion. A contaminated value
that could still be read is a contaminated value that gets read — the wrapper would buy a warning
label rather than a barrier. This mirrors ``universe.forward.ForwardCount``'s argument one layer
down: unhashable is the one people forget, because the dict and the set are how a filter is really
written.

What this module does not guarantee
-----------------------------------

It binds values that pass through **these operators**, and it does not bind a value that leaves
through :attr:`PreT0Decimal.value` and comes back through
:meth:`PreT0Decimal.measured_before_t0`. That round trip is two lines and it moves a basket —
measured::

    laundered = pre_t0_score.value * (Decimal("1") + forward_return)   # bare Decimals throughout
    PreT0Decimal.measured_before_t0(laundered, "a pre-T0 read")        # PRE_T0 again

The lattice never sees an operand it can condemn, because the multiplication happens between two
bare ``Decimal`` objects. The wallet whose post-T0 return was folded in moved from rank 5 to rank 4
and nothing raised.

This is not a hole that can be closed here, and the module does not pretend otherwise. ``.value``
has to be readable — a pre-T0 number is exactly what selection is allowed to see, and a wrapper that
refused to be read could not be serialized into an artifact. ``measured_before_t0`` has to accept a
bare number — it is the boundary at which a measurement enters the system, and a laundered value and
a genuine warehouse read are the same object by then. What the type buys is that the claim is
**attributed**: ``source`` is required, and the re-stamp is one call that names itself in a diff.
What stops the run being *decided* by such a value is one layer up — the ordering barrier, which
means selection cannot execute at a point where a forward return is available to fold in.

An earlier version of this section said such a value "arrives as a bare Decimal and is therefore
CONTAMINATED at the next operation and refused by every selection constructor — which is the safe
direction". That holds only for a bare ``Decimal`` handed *straight* to a constructor, and it is not
the interesting case.

It also does not reach into ``contracts.numeric``: ``add``/``sub``/``mul``/``divide`` still take and
return bare ``Decimal``. This module is a layer above them, and every operator below routes through
them so the frozen 38-digit context still holds.

Where this lives, and why it is not in ``contracts``
-----------------------------------------------------

``src/contracts/`` is the frozen seam: types, enums, serialization, numeric policy, construction
invariants, error definitions — and no substantive calculation, enforced by
``tests/test_shared_purity.py``. The lattice below **is** calculation: :func:`combine` decides an
outcome from two inputs by a rule, and the operators compose values. Its permitted categories have
no box that fits, and the only honest label would be the one the file forbids by name.

The second reason is the stronger one. A provenance lattice in ``contracts`` would be a surface both
families inherit through a dependency each believes to be neutral — the exact shape
``test_shared_purity``'s docstring exists to prevent, and the exact shape this package is being
rebuilt to remove. So it lives here, on the selection side, and the post-T0 side keeps its **own**
value type (``universe.forward.ForwardDecimal``) which contaminates on contact.
"""

from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple, Union

from contracts import LookAheadViolation, add, divide, mul, require_finite, sub


class Origin(str, Enum):
    """Where a value came from, relative to ``T0``. Three states, and there is no fourth.

    There is deliberately no ``UNKNOWN``. A value whose origin nobody can state is not a fourth
    standing to be reasoned about later; it is refused at the selection boundary now, which is what
    :attr:`CONTAMINATED` means when it arrives from a bare ``Decimal``.
    """

    #: Measured strictly before ``T0``, and composed only from other ``PRE_T0`` values.
    PRE_T0 = "PRE_T0"

    #: Measured at or after ``T0``.
    POST_T0 = "POST_T0"

    #: Composed from at least one value that was not ``PRE_T0``. Absorbing.
    CONTAMINATED = "CONTAMINATED"


class ProvenanceRefused(LookAheadViolation):
    """A value was used where its provenance does not permit it.

    A subclass of :class:`contracts.LookAheadViolation` rather than a ``TypeError``, on
    ``ForwardReadRefused``'s ground: an agent reading ``unsupported operand type`` fixes it by
    unwrapping the value, which *is* the bug. An agent reading this does not.
    """


class ContaminationDetected(LookAheadViolation):
    """A ``CONTAMINATED`` value reached a selection constructor.

    Distinct from :class:`ProvenanceRefused` because the two call for different responses: a refused
    *operation* is a programming error at the call site, and a contaminated *value* reaching
    selection means the run is void — see :mod:`universe.containment`.
    """


def combine(left: Origin, right: Origin) -> Origin:
    """The lattice's one rule, as a function of two origins.

    ``PRE_T0`` only survives when both sides are ``PRE_T0``. Everything else is absorbing, and the
    absorption is deliberately total rather than "post-T0 wins unless the pre-T0 side is larger" or
    any other rule that would need a threshold nobody pre-registered.
    """
    if type(left) is not Origin or type(right) is not Origin:
        raise TypeError(
            "combine() takes two Origin values, got {} and {}. The lattice is closed at three "
            "states; a string or a bare None here would be a fourth standing arriving by "
            "accident.".format(type(left).__name__, type(right).__name__)
        )
    if left is Origin.PRE_T0 and right is Origin.PRE_T0:
        return Origin.PRE_T0
    return Origin.CONTAMINATED


#: The trail a contaminated value carries: what it was made of, in order, as origin names.
Trail = Tuple[str, ...]


class ContaminatedDecimal(object):
    """A value the lattice has condemned. It holds no number, and every question it is asked raises.

    Every read, comparison, conversion, truth test and hash raises. There is no ``.value``, no
    ``__int__``, no ``__float__``, no ``__hash__`` and no ``__bool__`` that returns — because the
    single most useful thing a contaminated value could do for an attacker is come back out as an
    ordinary number, and a wrapper that permits that is a label rather than a barrier.

    One measured exception, stated rather than glossed: CPython's sequence containment and tuple
    comparison check **identity before calling** ``__eq__``, so ``c in [c]``, ``(c,) == (c,)``,
    ``[c].count(c)`` and ``[c].index(c)`` all answer without reaching this class. That is the same
    object being asked about itself; ``c in [d]`` for a different contaminated value raises, as does
    every other spelling. No laundering route was found through it, and the bound is recorded here
    because "answers no question" was absolute where the behaviour is not.

    Arithmetic on it returns another :class:`ContaminatedDecimal`, so the condemnation survives an
    arbitrarily long expression rather than being lost at the first operator that did not check.

    Final: subclassing is refused at class-definition time.
    """

    __slots__ = ("_trail",)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise ProvenanceRefused(
            "{} derives from ContaminatedDecimal. A subclass could restore a read that this type "
            "exists to withhold, and would remain a contaminated value to every isinstance check "
            "written against the base.".format(cls.__name__)
        )

    def __init__(self, trail: Trail = ()) -> None:
        object.__setattr__(self, "_trail", tuple(str(step) for step in trail))

    @property
    def origin(self) -> Origin:
        """Always :attr:`Origin.CONTAMINATED`. Readable because it is not the number."""
        return Origin.CONTAMINATED

    @property
    def trail(self) -> Trail:
        """What this value was composed from, in order. For the refusal message, not for a decision."""
        return self._trail

    def _refuse(self, what: str) -> "ContaminatedDecimal":
        raise ContaminationDetected(
            "a CONTAMINATED value was used in {}. It was composed from {} and there is no "
            "arithmetic, comparison or conversion that makes it pre-T0 again. §6.4: selection uses "
            "pre-T0 information only, and a value that reached this point through a post-T0 or "
            "unprovenanced operand voids the run it would decide — it is not dropped, not zeroed "
            "and not coerced.".format(what, " then ".join(self._trail) or "an unrecorded operand")
        )

    def _spread(self, op: str, other: object) -> "ContaminatedDecimal":
        return ContaminatedDecimal(self._trail + ("{}({})".format(op, _origin_name(other)),))

    def __add__(self, other: object) -> "ContaminatedDecimal":
        return self._spread("add", other)

    def __radd__(self, other: object) -> "ContaminatedDecimal":
        return self._spread("add", other)

    def __sub__(self, other: object) -> "ContaminatedDecimal":
        return self._spread("sub", other)

    def __rsub__(self, other: object) -> "ContaminatedDecimal":
        return self._spread("sub", other)

    def __mul__(self, other: object) -> "ContaminatedDecimal":
        return self._spread("mul", other)

    def __rmul__(self, other: object) -> "ContaminatedDecimal":
        return self._spread("mul", other)

    def __truediv__(self, other: object) -> "ContaminatedDecimal":
        return self._spread("div", other)

    def __rtruediv__(self, other: object) -> "ContaminatedDecimal":
        return self._spread("div", other)

    def __neg__(self) -> "ContaminatedDecimal":
        return self._spread("neg", self)

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

    def __index__(self) -> int:
        return self._refuse("an index conversion")

    def __reduce__(self) -> object:
        raise ProvenanceRefused(
            "a CONTAMINATED value cannot be pickled. Pickle reconstructs an object without running "
            "__init__, so a round trip is a laundering machine: it would rebuild the payload with "
            "none of the refusals above attached to it."
        )

    __hash__ = None

    def __repr__(self) -> str:
        return "<ContaminatedDecimal {}>".format(" then ".join(self._trail) or "unrecorded")


def _origin_name(value: object) -> str:
    """The origin of an arbitrary operand, as a string, for the trail. Never reads a number."""
    origin = getattr(value, "origin", None)
    if type(origin) is Origin:
        return origin.value
    return "UNPROVENANCED:{}".format(type(value).__name__)


class PreT0Decimal(object):
    """A ``Decimal`` measured strictly before ``T0``, in a type that keeps saying so.

    Constructed from a bare number **only** through :meth:`measured_before_t0` or
    :meth:`pre_registered`, both of which name what the caller is asserting. ``PreT0Decimal(x)``
    itself is refused, so the assertion cannot be made by writing a constructor call that reads like
    a cast.

    Arithmetic with another :class:`PreT0Decimal` yields a :class:`PreT0Decimal`. Arithmetic with
    **anything else** — a bare ``Decimal``, an ``int``, a post-T0 value, a contaminated one — yields
    a :class:`ContaminatedDecimal`. That is the whole lattice, and it is enforced by the operators
    rather than by a check somebody has to remember to call.

    Ordering **and equality** hold only against another :class:`PreT0Decimal`; all six comparison
    dunders raise against anything else, because ``score > threshold`` is precisely how a threshold
    computed from forward data would enter a selection path without any arithmetic happening at all.

    Note what that does and does not cover. ``score > threshold`` on the wrapper raises;
    ``score.value > threshold`` does not, because ``.value`` is a bare ``Decimal`` by design and by
    the time the ``>`` runs there is no wrapper left to refuse. The module docstring's section on
    what this does not guarantee is about exactly that read.

    Final: subclassing is refused at class-definition time. A subclass could override an operator
    and re-label a contaminated result ``PRE_T0``.
    """

    __slots__ = ("_pre_t0_value", "_source")

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise ProvenanceRefused(
            "{} derives from PreT0Decimal. A subclass can override __add__ and hand back a "
            "PreT0Decimal for an operation the lattice condemns, while remaining an isinstance of "
            "the base every selection constructor accepts.".format(cls.__name__)
        )

    def __init__(self, value: Optional[Union[Decimal, int, str]] = None,
                 source: Optional[str] = None) -> None:
        # Annotated with the shapes somebody reaching for this as a cast would actually write,
        # rather than `object`. The parameters are never read: the call is refused whatever it is
        # handed, and the annotation exists so the refusal is not the only documentation.
        raise ProvenanceRefused(
            "PreT0Decimal(...) is not a public constructor. A bare Decimal has unknown provenance, "
            "and a constructor that accepted one would let a laundered value be re-labelled PRE_T0 "
            "in a line that reads like a cast. Use PreT0Decimal.measured_before_t0(value, source) "
            "for a measurement, or PreT0Decimal.pre_registered(text, source) for a constant the "
            "protocol fixes — both name in a diff what is being asserted."
        )

    @staticmethod
    def _build(value: Union[Decimal, int, str], source: str) -> "PreT0Decimal":
        """The one constructor, and the one place the source requirement is enforced.

        The check used to live in :meth:`measured_before_t0` only, which meant
        ``PreT0Decimal._build(Decimal("9"), "")`` produced an unattributed pre-T0 claim — and
        ``_build`` is what every operator in this class calls. A rule enforced at one of two doors
        is a rule about which door somebody chose.
        """
        if not source or not str(source).strip():
            raise ValueError(
                "a pre-T0 value must name its source. This is the boundary at which an unverifiable "
                "claim enters the system, and an unattributed claim is one nobody can contest later."
            )
        instance = object.__new__(PreT0Decimal)
        object.__setattr__(instance, "_pre_t0_value", require_finite(value, source))
        object.__setattr__(instance, "_source", str(source).strip())
        return instance

    @classmethod
    def measured_before_t0(cls, value: Union[Decimal, int, str], source: str) -> "PreT0Decimal":
        """Assert that ``value`` was measured strictly before ``T0``, naming who says so.

        ``source`` is required and non-empty — enforced in :meth:`_build`, so the private helper
        cannot be used to skip it. It is not decoration: this call is the one place a provenance
        claim enters the system from outside it, so a claim with no author is a claim nobody can
        contest. Nothing here can verify the claim — see the module docstring — and the stamps on
        the record that carries it are checked separately against ``T0``.
        """
        if isinstance(value, float):
            raise TypeError(
                "a float reached PreT0Decimal.measured_before_t0 ({!r}). It has already lost "
                "precision before this call saw it, so accepting it would launder the loss.".format(
                    value)
            )
        if isinstance(value, (PreT0Decimal, ContaminatedDecimal)):
            raise ProvenanceRefused(
                "PreT0Decimal.measured_before_t0 takes a bare number and stamps it. It was handed "
                "a {}, which already carries a provenance — re-stamping is how CONTAMINATED "
                "becomes PRE_T0 in one line.".format(type(value).__name__)
            )
        if not isinstance(value, (Decimal, int, str)) or isinstance(value, bool):
            raise TypeError(
                "PreT0Decimal.measured_before_t0 takes a Decimal, int or str, got {}".format(
                    type(value).__name__)
            )
        if not source or not str(source).strip():
            raise ValueError(
                "a pre-T0 measurement must name its source. This is the boundary at which an "
                "unverifiable claim enters the system, and an unattributed claim is one nobody can "
                "contest later."
            )
        return cls._build(value, str(source).strip())

    @classmethod
    def pre_registered(cls, text: str, source: str) -> "PreT0Decimal":
        """A constant the pre-registration fixes, written as a string literal.

        Separate from :meth:`measured_before_t0` because the two claims are different: a threshold
        in §6.2 has no measurement date and is pre-T0 by being pre-registered, while a measurement
        is pre-T0 only if the query that produced it was. Collapsing them would let a measurement be
        smuggled in under the word "constant".
        """
        if not isinstance(text, str):
            raise TypeError(
                "a pre-registered constant is written as a string literal so the digits in the "
                "source are the digits in the run; got {}".format(type(text).__name__)
            )
        return cls.measured_before_t0(Decimal(text), source)

    # -- reads --

    @property
    def origin(self) -> Origin:
        return Origin.PRE_T0

    @property
    def source(self) -> str:
        """Who asserted that this value is pre-T0."""
        return self._source

    @property
    def value(self) -> Decimal:
        """The number, as a bare ``Decimal``.

        Readable on purpose: a pre-T0 value is exactly the thing selection is allowed to see, and a
        wrapper that refused to be read could not be serialized into an artifact. The barrier is on
        what may *become* a ``PreT0Decimal``, not on reading one.
        """
        return self._pre_t0_value

    # -- the lattice, carried by the operators --

    def _compose(self, op: str, other: object,
                 apply: object) -> Union["PreT0Decimal", ContaminatedDecimal]:
        if type(other) is PreT0Decimal:
            return PreT0Decimal._build(
                apply(self._pre_t0_value, other._pre_t0_value),
                "{}({}, {})".format(op, self._source, other._source),
            )
        return ContaminatedDecimal((
            "PRE_T0", "{}({})".format(op, _origin_name(other)),
        ))

    def __add__(self, other: object) -> Union["PreT0Decimal", ContaminatedDecimal]:
        return self._compose("add", other, add)

    def __radd__(self, other: object) -> Union["PreT0Decimal", ContaminatedDecimal]:
        return self._compose("add", other, add)

    def __sub__(self, other: object) -> Union["PreT0Decimal", ContaminatedDecimal]:
        return self._compose("sub", other, sub)

    def __rsub__(self, other: object) -> Union["PreT0Decimal", ContaminatedDecimal]:
        return self._compose("sub", other, sub)

    def __mul__(self, other: object) -> Union["PreT0Decimal", ContaminatedDecimal]:
        return self._compose("mul", other, mul)

    def __rmul__(self, other: object) -> Union["PreT0Decimal", ContaminatedDecimal]:
        return self._compose("mul", other, mul)

    def __truediv__(self, other: object) -> Union["PreT0Decimal", ContaminatedDecimal]:
        return self._compose("div", other, divide)

    def __rtruediv__(self, other: object) -> Union["PreT0Decimal", ContaminatedDecimal]:
        return self._compose("div", other, divide)

    def __neg__(self) -> "PreT0Decimal":
        return PreT0Decimal._build(sub(0, self._pre_t0_value), "neg({})".format(self._source))

    # -- comparison: only against another pre-T0 value --

    def _require_peer(self, other: object, what: str) -> "PreT0Decimal":
        """Every one of the six comparison dunders routes through here.

        ``__eq__`` and ``__ne__`` used to return ``NotImplemented`` instead, and the difference was
        not academic: ``NotImplemented`` falls back to identity, so ``score == cutoff`` answered
        ``False`` and ``score in allowed`` answered ``False`` rather than refusing. A membership
        test that quietly answers "no" about an unprovenanced threshold is the ``SILENTLY_DROPPED``
        shape, and it is worse than the ordering case because nothing in the code reads as a
        comparison having been refused.
        """
        if type(other) is not PreT0Decimal:
            raise ProvenanceRefused(
                "a pre-T0 value was compared against {} in {}. Comparison is how a threshold enters "
                "a selection path without any arithmetic happening: `score.value > cutoff` decides "
                "membership, and a cutoff of unknown provenance decides it on unknown "
                "information.".format(_origin_name(other), what)
            )
        return other

    def __lt__(self, other: object) -> bool:
        return self._pre_t0_value < self._require_peer(other, "an ordering comparison").value

    def __le__(self, other: object) -> bool:
        return self._pre_t0_value <= self._require_peer(other, "an ordering comparison").value

    def __gt__(self, other: object) -> bool:
        return self._pre_t0_value > self._require_peer(other, "an ordering comparison").value

    def __ge__(self, other: object) -> bool:
        return self._pre_t0_value >= self._require_peer(other, "an ordering comparison").value

    def __eq__(self, other: object) -> bool:
        return self._pre_t0_value == self._require_peer(other, "an equality test").value

    def __ne__(self, other: object) -> bool:
        return self._pre_t0_value != self._require_peer(other, "an equality test").value

    def __hash__(self) -> int:
        return hash((Origin.PRE_T0.value, self._pre_t0_value))

    def __reduce__(self) -> object:
        raise ProvenanceRefused(
            "a PreT0Decimal cannot be pickled. Unpickling reconstructs the object without running "
            "any constructor, so the provenance stamp would be restored by the attacker's own "
            "bytes rather than by an assertion anybody made. Serialize the artifact through "
            "universe.artifact instead — canonical, schema-versioned, and hashed."
        )

    def __repr__(self) -> str:
        return "<PreT0Decimal {} from {}>".format(self._pre_t0_value, self._source)


def require_pre_t0_value(value: Union[PreT0Decimal, ContaminatedDecimal],
                         field: str) -> PreT0Decimal:
    """The selection-side gate: ``type(value) is PreT0Decimal`` or the run is void.

    The parameter is annotated with the two **provenance-carrying** types rather than ``object``.
    That is the contract this gate states: hand it a value that knows where it came from. A bare
    ``Decimal`` arriving here is not a measurement this function is meant to judge — it is a defect
    in what assembled the call, and it raises, naming the rule and what it costs. Python does not
    enforce annotations, which is why the body still checks; the annotation is what stops the
    signature *itself* being the tunnel, since ``object`` here would accept a forward value in the
    one function every selection constructor routes through.

    ``isinstance`` is deliberately not used. A subclass is refused at class-definition time, so the
    two would agree today — and agreeing today is the property this package has already been burned
    by. The exact-type check keeps agreeing when somebody finds a way to make a subclass.

    :raises ContaminationDetected: on a :class:`ContaminatedDecimal` — the run is void, and the
        caller must not catch this and drop the wallet.
    :raises ProvenanceRefused: on a bare ``Decimal``, an ``int``, a post-T0 value, or anything else.
    """
    if type(value) is PreT0Decimal:
        return value
    if type(value) is ContaminatedDecimal:
        raise ContaminationDetected(
            "{} was handed a CONTAMINATED value (composed from {}). It is not dropped, not zeroed "
            "and not coerced: a contaminated value reaching a selection constructor means the "
            "composition of the candidate universe was decided on post-T0 or unprovenanced "
            "information, and the run that would contain it is void.".format(
                field, " then ".join(getattr(value, "trail", ())) or "an unrecorded operand")
        )
    raise ProvenanceRefused(
        "{} must be a PreT0Decimal, got {}. A bare Decimal is refused on purpose: it is exactly "
        "what a laundered value looks like by the time it reaches a selection type — "
        "`pre / (1 + forward_return)` reads as an ordinary number and no forward object is touched "
        "at any point. Stamp measured values with PreT0Decimal.measured_before_t0(value, source) "
        "at the boundary where the claim can still be attributed.".format(
            field, type(value).__name__)
    )


#: The numeric zero, pre-T0 by being a bound rather than a measurement.
#:
#: Every magnitude check in this package compares against it — ``buy_volume_usd < PRE_T0_ZERO`` — and
#: comparing a :class:`PreT0Decimal` against a bare ``Decimal("0")`` raises, deliberately. A single
#: named constant is what stops that refusal being answered by scattering ``Decimal("0")`` back
#: through the selection path, which would reopen exactly the comparison route the type closes.
PRE_T0_ZERO = PreT0Decimal.pre_registered("0", "the numeric zero: a bound, not a measurement")

#: The numeric one, on the same ground. Used where a share or a ratio is bounded above.
PRE_T0_ONE = PreT0Decimal.pre_registered("1", "the numeric one: a bound, not a measurement")
