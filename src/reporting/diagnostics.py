"""Diagnostics — reported, and structurally incapable of reaching a gate decision.

§10 lists a page of things worth knowing and then draws the line the whole pre-registration exists
to draw:

    Only ``buy_quality`` decides the gate.

    Reporting a diagnostic and then using it to overturn a gate result is the failure mode this
    entire document exists to prevent.

A comment saying so is not a control. Neither is a filter in the gate engine, because a filter is
something a future edit can widen. The control here is the **type**: a diagnostic is a
:class:`Diagnostic`, which is not a :class:`contracts.WindowScore`, not a
:class:`contracts.BuyQuality`, not a :class:`contracts.CopySimulation`, and not a ``Decimal`` — and
neither is its payload, which is a :class:`DiagnosticValue`.

What that buys, exactly
-----------------------

* :func:`contracts.calc` accepts ``Decimal``, ``int`` and ``str`` and refuses everything else, and
  every numeric primitive in the seam — ``divide``, ``add``, ``sub``, ``mul``, ``require_finite`` —
  is built on it. Neither a diagnostic nor the value you reach for on one can enter *any*
  arithmetic in the pipeline. At the gate the refusal holds wherever the arbiter reads its figure
  through ``calc``, which is every entry point that compares a *quantity* — measured, with a
  ``DiagnosticValue`` in the field: ``evaluate_windows``, ``evaluate_windows_detail`` and
  ``assess_capital_feasibility`` raise ``TypeError``; ``check_numeric_fields_detail`` and
  ``_check_condition`` (so ``check_validation_gate`` and ``check_reconciliation_coverage``) record
  a ``SCHEMA`` discrepancy — see :class:`DiagnosticValue` for the one non-numeric condition and
  what it does instead. **It is not every gate entry point, and the exception is measured rather
  than argued**: ``gate_validation.check_derived_fields`` delegates to
  ``contracts.verify_redundant_derived``, which reads the claimed figure as
  ``Decimal(str(claimed_raw))`` rather than through ``calc`` — and ``DiagnosticValue.__str__`` is
  the rendered figure. So a payload behaves there exactly as the bare ``Decimal`` it wraps::

      check_derived_fields({"total": d.value, "a": "0.3", "b": "0.31"}, recomputations)
      -> 0 discrepancies   (d.value carries 0.61000000; the §9 derived check HELD)
      check_derived_fields({"total": d.value, "a": "0.3", "b": "0.32"}, recomputations)
      -> 1 discrepancy     (which is how we know the number was genuinely read)

  What that costs, exactly: a diagnostic payload can satisfy a §9 *internal-consistency* check,
  and still cannot satisfy a §9.8 or §9.4 *bar* — those all run through ``_check_condition``.
  Closing it means ``verify_redundant_derived`` reading through ``calc``, which is inside the
  frozen seam and not this module's to change.
  ``tests/integration/test_reporting_claims.py`` pins both halves, so this paragraph goes red the
  day either one moves;
* the comparison operators below raise :class:`DiagnosticPromotionRefused` rather than returning
  ``NotImplemented``, on the wrapper and on the payload alike, in both operand orders. Equality is
  the deliberate exception — see :class:`DiagnosticValue`;
* subclassing is refused. ``class Promoted(Diagnostic, WindowScore)`` would satisfy both
  ``isinstance`` checks; every diagnostic type is final, so no derivation of one exists to try it
  with, in either base order;
* ``gate_validation`` is in the *shared* lane and ``reporting`` is in the *builder* lane, so
  ``tests/test_lane_independence.py`` already makes it impossible for the arbiter to import this
  module at all.

What it does **not** buy, and why the difference is worth stating
----------------------------------------------------------------

An overclaimed guarantee is worse than an accurate weaker one, because the next reader relies on
it. This module used to say there was "no configuration, flag, or override that promotes a
diagnostic into a gate input… including by an agent who wanted it". That was false in two ways, and
one of them cannot be made true:

**The number is extractable, and must be.** ``DiagnosticValue.amount`` is a ``Decimal`` and
``str(value)`` is the rendered figure, and both are types ``calc`` accepts. This is not an
oversight that a further wrapper would fix. ``calc`` accepts exactly ``Decimal``, ``int`` and
``str`` — the three faithful representations of a number — so *any* field that carries the figure
is a field ``calc`` accepts, and the only calc-refusing payload is another wrapper, forever. A
report exists to publish its numbers; no wall both publishes a number and withholds it.

So the property is bounded, and the boundary is **accident versus intent**. Every name a caller
reaches for by the domain's own vocabulary — ``d.value``, ``row.value`` — yields a type the seam
refuses. Getting a gate-readable number out takes a second, differently-named step — ``.amount``,
or ``str(...)`` — and in the *reporting* lane that step says in the diff what it is doing.

Where that stops being true is worth naming, because it was previously stated as though it were
unconditional: ``str()`` is a protocol, not a name, so a reader anywhere can invoke it without
writing anything that looks like an extraction. ``contracts.verify_redundant_derived`` does exactly
that (``Decimal(str(claimed_raw))``), inside the arbiter, with nothing in any diff — the measured
consequence is the ``check_derived_fields`` result in the bullet above. So the claim is: it stops
the reach that looks like ordinary attribute access; it does not stop ``str()``; and it does not
stop a caller who has decided to extract a number, which nothing can.

**``object.__setattr__`` rewrites any field of any Python object**, ``WindowScore`` included. No
class prevents it and this one does not try. Two things make it uninteresting as a promotion route:
the label was never the wall, so rewriting ``gate_relevance`` to ``"GATE"`` leaves an object that
is still not a ``Decimal`` and still not a ``WindowScore``; and anyone able to make the call already
holds the number they would be promoting, so the rewrite buys them nothing they did not have.

What *is* closable there is the consequence, and it is closed as far as it goes:
:meth:`DiagnosticPack.verify` rebuilds every item from the fields it is holding, which re-runs each
item's own ``__post_init__`` at publication instead of trusting that it held at construction. A
rewritten diagnostic — bad label, bare-``Decimal`` payload, unregistered name, a ``kind`` outside
``KINDS``, a payload whose kind disagrees with its item's, a non-finite amount, a duck-typed
``scope``, or a ``WindowScore`` spliced into ``items`` — is refused before it reaches an artifact.

The bound on that, since an unbounded version of the sentence is what this module is trying not to
write: **rewriting the amount from one finite number to another is not caught, and cannot be.** No
invariant on a diagnostic says which measurements are plausible, because a diagnostic exists to
carry whatever was measured. What the rewrite does not buy is standing — the figure is still a
``DiagnosticValue``, ``calc`` still refuses it, and it still reaches a report rather than a gate.

``gate_relevance`` is a stored field rather than a class attribute so that it survives
serialization: ticket 34 requires that a number cannot travel without its status, and a class
attribute would vanish the moment the record was canonicalised. It is validated to be exactly
``DIAGNOSTIC_ONLY`` at construction and again at publication. Read it as a label for the humans
downstream, not as the mechanism — the mechanism is the type.

Ranking is computed on the **unquantized** value and displayed at the output scale. Ranking on the
displayed figure would tie two wallets that genuinely differ below six decimal places, and a tie in
an absolute-profit ranking is exactly the kind of small wrongness that survives review.
"""

from dataclasses import dataclass, fields
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple

from contracts import ContractError, calc, canonicalise, require_finite
from phase0.parameters import PARAMETERS

from .boundary import KINDS, RATIO, USD, at_output
from .capital import level_key

#: The one permitted value of :attr:`Diagnostic.gate_relevance`. There is no second value, and no
#: argument that produces one.
DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"

#: §10's diagnostics, plus ticket 34's activity-band sensitivity. The set is closed: a diagnostic
#: nobody pre-registered is a new measurement introduced after the fact, which §9.7 and §8.4 exist
#: to prevent. Adding one is a pre-registration amendment, not an argument.
DIAGNOSTIC_NAMES = (
    "absolute_profit_ranking",
    "simple_wallet_return",
    "buy_return_7d",
    "buy_return_90d",
    "buy_win_rate",
    "median_return",
    "tail_loss",
    "bucket_a_isolated",
    "activity_band_sensitivity",
)


class ActivityBand(str, Enum):
    """§10's sensitivity bands, by valid-buy count."""

    B_20_99 = "20-99"
    B_100_499 = "100-499"
    B_500_1000 = "500-1000"


#: §10's bands as the frozen set holds them: ``(label, low, high)``, ascending and contiguous.
ACTIVITY_BANDS = PARAMETERS.value("reporting.activity_bands")

#: The same table keyed by :class:`ActivityBand`, which is the shape this module reads it in.
#: Derived rather than restated, so §10's numbers live in exactly one place; ``ActivityBand(label)``
#: raises if the frozen labels and the enum ever stop agreeing, which is the failure that would
#: otherwise show up as a band silently missing from a report.
#:
#: §6 makes 20 the eligibility floor and 1,000 the ceiling, so the bands tile the eligible range
#: exactly. That is a relationship between §10 and §6.2 rather than a derivation — it is asserted in
#: ``tests/hand_computed/test_parameters.py`` and in ``test_reporting.py``, not encoded here.
ACTIVITY_BAND_BOUNDS = {
    ActivityBand(label): (low, high) for label, low, high in ACTIVITY_BANDS
}

#: The eligibility band the activity bands must tile, read from the ticket-11 frozen set rather
#: than restated. Two copies of "20 to 1,000" is two eligible populations, and the §10 sensitivity
#: table would then be a breakdown of a set the universe stage never selected.
MIN_VALID_BUYS = PARAMETERS.value("eligibility.valid_buys.floor")
MAX_VALID_BUYS = PARAMETERS.value("eligibility.valid_buys.ceiling")


class DiagnosticPromotionRefused(ContractError):
    """Something attempted to give a diagnostic the standing of a gate input."""


class UnknownDiagnostic(ContractError):
    """A diagnostic name that was not pre-registered reached the pack."""


#: Every diagnostic type, registered by :func:`_final` as each class is defined. Two things read it,
#: and both want exactly this set: :meth:`_Sealed.__init_subclass__`, which refuses to derive from
#: anything in it, and :func:`_rebuilt`, which re-runs the ``__post_init__`` of anything in it. A
#: type added later is covered by both without either being edited.
_FINAL = set()


class _Sealed(object):
    """Base of every diagnostic type: deriving from one of them is refused.

    Subclassing is not a hypothetical route. ``class Promoted(Diagnostic, WindowScore)`` produces an
    object that satisfies *both* ``isinstance`` checks, so the gate engine reads it as a score and
    the pack accepts it as a diagnostic — one object, two standings, which is precisely the
    confusion the type wall exists to prevent. Reversing the bases does the same thing, and so does
    a subclass with no gate base at all: overriding ``__post_init__`` drops the label check, and
    overriding ``__gt__`` undoes the comparison refusals.

    So the check is on the *derivation*, not on any particular base list. Every combination above
    derives from a diagnostic type, and none of them is constructible.

    This closes ``reporting``'s half without touching ``contracts``: both orders of
    ``(Diagnostic, WindowScore)`` derive from ``Diagnostic``, so refusing here refuses them both,
    and ``WindowScore`` needs no ``__init_subclass__`` of its own. The other direction — a class
    deriving from ``WindowScore`` alone — is not this wall's business: such an object is a gate
    input, honestly typed as one, and the pack refuses it on sight.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for base in cls.__mro__[1:]:
            if base in _FINAL:
                raise DiagnosticPromotionRefused(
                    "{} derives from {}, which is final. A subclass of a diagnostic type can carry "
                    "another type's shape as well — ``class X(Diagnostic, WindowScore)`` satisfies "
                    "both isinstance checks in either base order — and can drop the checks its "
                    "base runs by overriding __post_init__ or the comparison refusals. §10: only "
                    "buy_quality decides the gate.".format(cls.__name__, base.__name__)
                )


def _final(cls):
    """Mark a class un-derivable. Applied above ``@dataclass`` so it runs last."""
    _FINAL.add(cls)
    return cls


def activity_band(valid_buys):
    """The §10 band a wallet's valid-buy count falls in.

    A count outside ``[20, 1000]`` raises. Both directions matter and for different reasons: below
    20 the wallet was never eligible, and above 1,000 §6.2 excludes it as likely automated — so
    either would be a wallet that should not be in the population at all, and folding it into the
    nearest band would hide a selection bug inside a diagnostic nobody is allowed to act on.
    """
    if not isinstance(valid_buys, int) or isinstance(valid_buys, bool):
        raise TypeError("valid_buys must be an int, got {}".format(type(valid_buys).__name__))
    for band, (low, high) in ACTIVITY_BAND_BOUNDS.items():
        if low <= valid_buys <= high:
            return band
    raise ValueError(
        "{} valid buys is outside the §6 eligible range [{}, {}], so it belongs to no sensitivity "
        "band. Folding it into the nearest one would file a selection error as a "
        "diagnostic.".format(valid_buys, MIN_VALID_BUYS, MAX_VALID_BUYS)
    )


def _canonical_text(value, field):
    """One spelling per name, because the scope is an **identity key**.

    Applied to every string a scope carries, not to the one a reviewer happened to name. The class
    is: *a value that identifies a measurement must have a canonical form, or two spellings of one
    scope are two entries and something downstream has to choose between them.* Measured on the
    unfixed code, both directions of the class were live::

        DiagnosticScope(chain="ethereum", …)  and  DiagnosticScope(chain="Ethereum", …)
        -> two pack entries for buy_win_rate, 0.61 and 0.19, both published

    and the same for ``population`` ("selected" / "Selected") and for the capital level below. The
    fix is not a comparison that ignores case — that would leave the *published* scope carrying
    whichever spelling arrived — but a normalisation of the stored field, so the artifact and the
    key agree by construction and the duplicate check then refuses the pair out loud.

    Three collapses, and the third was left out of an earlier version of this sentence, which said
    "case-folding and internal whitespace, and nothing else": ``str.split()`` **also strips**, so
    ``"  ETHEREUM  "`` and ``"ethereum"`` are one scope. Stated because this function's whole
    subject is which spellings collapse onto one key, and a list of collapses that omits one is the
    exact defect the rest of this module is about. In full — leading and trailing whitespace
    removed, internal runs of any whitespace collapsed to a single space, ASCII case folded. No
    other character is touched.

    **Trimming here, and refusing in** :func:`pipeline.inputs.asset_keyed`, is a deliberate
    disagreement rather than an inconsistency, and the difference is what the key is looked up
    *with*. An asset key is matched against addresses that have been through
    ``contracts.normalise_asset``, which does not strip — so a padded key there is reachable by
    nothing and trimming it would give ``pipeline`` a key space the frozen seam does not have. A
    scope is never looked up against anything outside this module: it is only ever compared with
    another scope built the same way, so there is no second key space to disagree with, and a
    padded chain name is a caller's typo rather than an unreachable entry.

    A chain name and a population name are identifiers rather than prose, exactly as an address is,
    and this module lowercases addresses for the same reason.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(
            "{} must be a string naming a scope, got {}".format(field, type(value).__name__)
        )
    return " ".join(value.split()).lower()


@_final
@dataclass(frozen=True)
class DiagnosticScope(_Sealed):
    """Where a diagnostic was measured — ticket 34's "every diagnostic carries its scope".

    A number without its scope is worse than no number: "buy win rate 61%" is unfalsifiable until
    someone says which chain, which window, which capital level and which population it describes,
    and by then it has been quoted.

    The scope is also the identity half of :func:`_scope_key`, which is what makes two answers to
    one question refusable. Every field is therefore stored in a canonical form — see
    :func:`_canonical_text` for the strings and :func:`reporting.capital.level_key` for the level —
    so that scopes naming the same measurement are equal, hash equal, key equal and serialise
    identically. ``window`` is an ``int`` and ``band`` an :class:`ActivityBand`; both are canonical
    already, and the type checks below are what keeps them so.
    """

    chain: str
    window: int
    population: str
    capital_level: Optional[Decimal] = None
    liquidity_band: Optional[str] = None
    band: Optional[ActivityBand] = None

    def __post_init__(self):
        object.__setattr__(self, "chain", _canonical_text(self.chain, "chain"))
        object.__setattr__(self, "population", _canonical_text(self.population, "population"))
        object.__setattr__(
            self, "liquidity_band", _canonical_text(self.liquidity_band, "liquidity_band")
        )
        if not self.chain:
            raise ValueError("a diagnostic must name the chain it was measured on")
        if not isinstance(self.window, int) or isinstance(self.window, bool):
            raise TypeError("window must be an int index, got {}".format(type(self.window).__name__))
        if not self.population:
            raise ValueError(
                "a diagnostic must name its population; 'buy win rate 61%' means different things "
                "for the selected basket and for the matched controls"
            )
        if self.liquidity_band is not None and not self.liquidity_band:
            raise ValueError(
                "liquidity_band is present and empty, which is an absence spelled as a presence: "
                "it keys differently from None and reads the same in a report. Pass None."
            )
        if self.capital_level is not None:
            # ``level_key`` rather than ``calc``: it snaps onto §3.1's five, so Decimal("1.5E+6")
            # and Decimal("1500000") — equal, and rendered differently by ``str`` — become the one
            # constant, and a level nobody pre-registered is refused instead of keyed.
            object.__setattr__(self, "capital_level", level_key(self.capital_level))
        if self.band is not None and not isinstance(self.band, ActivityBand):
            raise TypeError("band must be an ActivityBand, got {}".format(type(self.band).__name__))


class _NeverGating(_Sealed):
    """Mixin: comparison against anything is a typed refusal, not a ``TypeError``.

    Python would already raise for ``diagnostic > threshold`` on a dataclass with ``order=False``.
    The reason to define these anyway is legibility at the moment it matters: an agent reading
    ``'>' not supported between instances of 'Diagnostic' and 'Decimal'`` fixes it by unwrapping
    the value, which is the bug. An agent reading :class:`DiagnosticPromotionRefused` and §10's own
    sentence does not.
    """

    def _refuse(self, other):
        raise DiagnosticPromotionRefused(
            "a diagnostic was compared against {!r}. §10: only buy_quality decides the gate, and "
            "'reporting a diagnostic and then using it to overturn a gate result is the failure "
            "mode this entire document exists to prevent'. If this comparison belongs in a report, "
            "compare the reported figures; if it belongs in a decision, it is not a "
            "diagnostic.".format(other)
        )

    def __lt__(self, other):
        self._refuse(other)

    def __le__(self, other):
        self._refuse(other)

    def __gt__(self, other):
        self._refuse(other)

    def __ge__(self, other):
        self._refuse(other)


@_final
@dataclass(frozen=True, eq=False)
class DiagnosticValue(_NeverGating):
    """A diagnostic's measured payload, at output scale, in a type the gate cannot read.

    This exists because the wall used to be one attribute access deep. ``Diagnostic`` was a type
    ``calc`` refuses, but ``Diagnostic.value`` was a plain ``Decimal`` — so
    ``evaluate_windows_detail([], d.value)`` was accepted as a calibrated threshold and
    ``assess_capital_feasibility({level: d.value})`` returned ``feasible=True``. The comparison
    operators stopped ``d > threshold`` and did nothing about ``d.value > threshold``, which is the
    same promotion with one more keystroke.

    Wrapping the payload closes it at the same place the wrapper was already closed: ``calc``
    accepts ``Decimal``, ``int`` and ``str`` and refuses everything else, and this is none of them,
    so no numeric primitive in the seam will consume one. Ordering is refused by
    :class:`_NeverGating`, in both directions — ``threshold < d.value`` lands on the reflected
    operator and is refused there too.

    **Equality is permitted, and the asymmetry is deliberate — but not for the reason this docstring
    used to give.** It said equality is never a gate rule. It is one ten times over:
    ``gate_validation.artifacts`` states ten of §9.8's and §9.4's bars as ``EXACTLY``, and
    "golden-set precision is exactly 1" or "unexplained missing trades is exactly 0" are gates in
    every sense that matters. Believing otherwise is how the exception gets widened next time.

    What actually makes equality safe is the same thing that makes ordering safe, and it is not this
    class: for every condition that names a *numeric* comparison — ``EXACTLY``, ``AT_LEAST``,
    ``AT_MOST`` — ``_check_condition`` routes the reported figure through :func:`contracts.calc`
    before it compares anything, and ``calc`` refuses this type, so the condition is recorded as a
    ``SCHEMA`` discrepancy: unmeasurable, never held.

    The one condition that names no quantity is measured rather than assumed. ``IS_TRUE``
    (``independent_review_completed``, §9.5) tests ``value is True`` *before* ``calc`` is reached,
    so a payload there yields ``MISMATCH``, not ``SCHEMA``. Over all sixteen of
    ``VALIDATION_GATE_CONDITIONS + RECONCILIATION_CONDITIONS`` with a ``DiagnosticValue`` in the
    field: fifteen ``SCHEMA``, one ``MISMATCH``, **zero held**. The load-bearing half — the gate
    never reaches an ``==`` and no condition holds — is true of all sixteen; the mechanism is not
    ``calc`` in every one of them, and the previous version of this paragraph said it was.

    So equality is permitted here for the reason a report wants it and at no cost: checking a
    rendered figure against an expected one is what a report is *for*. ``d.value == D("0.61")``
    answers, and ``d.value > D("0.61")`` refuses — the ordering refusal earns its keep on
    legibility, not on safety, exactly as :class:`_NeverGating` says.

    **What the cross-type equality costs, stated because it is a real cost.** ``__hash__`` is
    ``hash(self.amount)`` and not a hash of the fields, so ``a == b`` implies ``hash(a) == hash(b)``
    for every operand type ``__eq__`` accepts — without that, ``d.value == D("1")`` was ``True``
    while ``D("1") in {d.value}`` was ``False`` and ``{d.value, D("1")}`` had two slots, which is
    ``==`` disagreeing with itself depending on which container asked. What remains, and cannot be
    removed while a payload compares equal to a bare number, is that equality is **not transitive
    across kinds**::

        usd_one == D("1")  -> True
        ratio_one == D("1") -> True
        usd_one == ratio_one -> False     # the scale is part of what a number means

    Two payloads at the same amount and different kinds now hash equal and compare unequal, which is
    legal and is the direction that fails safe: a collision costs a comparison, a missing collision
    would cost a lookup. Nothing in ``src`` uses a payload as a dict or set key; this is stated so
    that the first thing that does is not surprised by it.

    There is no ``as_decimal()`` — nothing in ``src`` needs one. But be clear about what
    :attr:`amount` is: **it is a bare ``Decimal`` and ``calc`` accepts it**, so
    ``evaluate_windows_detail([], d.value.amount)`` is taken as a calibrated threshold exactly as
    ``d.value`` used to be. That is deliberate and unavoidable, not a hole left unattended.
    :func:`contracts.canonicalise` reads it by ``getattr`` to serialize the record, and a wrapper
    around the wrapper would only move the same reach one hop further out: ``calc`` accepts
    ``Decimal``, ``int`` and ``str``, which is every faithful way to write a number down.

    The line this type draws is therefore not "the number is unreachable" — it is "the number is
    not reached **by accident**". ``d.value`` is what a caller writes when they want the
    diagnostic's figure, and it now answers with something the gate refuses. ``d.value.amount`` is
    what they write when they have decided to take the raw number out, and it reads that way in a
    diff, which is where it should be caught.

    ``amount`` stays a ``Decimal`` rather than the rendered string so that serialization keeps the
    seam's Decimal policy — the non-finite refusal, the exponent normalisation, no ``e+`` notation.
    A string field would carry ``"NaN"`` straight into an artifact.
    """

    amount: Decimal
    kind: str

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(
                "unknown output kind {!r} for a diagnostic value; §10 reports in {}".format(
                    self.kind, ", ".join(KINDS)
                )
            )
        object.__setattr__(
            self, "amount", require_finite(calc(self.amount), "diagnostic value")
        )

    def __eq__(self, other):
        if isinstance(other, DiagnosticValue):
            return self.amount == other.amount and self.kind == other.kind
        if isinstance(other, Decimal) or (isinstance(other, int) and not isinstance(other, bool)):
            return self.amount == other
        return NotImplemented

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __hash__(self):
        # ``hash(self.amount)``, not a hash of the fields: ``__eq__`` above accepts a bare
        # ``Decimal``/``int`` operand, and the ``__eq__``/``__hash__`` contract is that equal
        # objects hash equally. Hashing the ``kind`` too would make ``d.value == D("1")`` true and
        # ``D("1") in {d.value}`` false at the same time.
        return hash(self.amount)

    def __str__(self):
        return format(self.amount, "f")

    def __repr__(self):
        return "DiagnosticValue({}, kind={!r})".format(format(self.amount, "f"), self.kind)


def _as_payload(value, kind, field):
    """Coerce a figure onto the diagnostic side of the wall.

    Coercion rather than refusal, because the value legitimately arrives as a ``Decimal`` from
    :func:`reporting.boundary.at_output` — the point is that it cannot leave as one, and a field
    that is a :class:`DiagnosticValue` however it was constructed is the property that holds.
    """
    if isinstance(value, DiagnosticValue):
        if value.kind != kind:
            raise ValueError(
                "{} carries a {} payload inside a {} diagnostic; the scale is part of what a "
                "reported number means".format(field, value.kind, kind)
            )
        return value
    return DiagnosticValue(amount=require_finite(calc(value), field), kind=kind)


def _check_gate_relevance(value):
    if value != DIAGNOSTIC_ONLY:
        raise DiagnosticPromotionRefused(
            "gate_relevance is {!r}; the only permitted value is {!r}. There is no configuration, "
            "flag, or override that promotes a diagnostic into a gate input, and this refusal is "
            "what makes that a property of the type rather than a habit of its "
            "callers.".format(value, DIAGNOSTIC_ONLY)
        )


def _check_name(name):
    if name not in DIAGNOSTIC_NAMES:
        raise UnknownDiagnostic(
            "{!r} is not a pre-registered diagnostic. §10 fixes the list; introducing a new "
            "measurement after results are visible is what §8.4 and §9.7 exist to prevent. "
            "Pre-registered: {}.".format(name, ", ".join(DIAGNOSTIC_NAMES))
        )


@_final
@dataclass(frozen=True)
class Diagnostic(_NeverGating):
    """One scalar diagnostic, already at its output scale.

    Not a :class:`contracts.WindowScore`, not a :class:`contracts.BuyQuality`, not a ``Decimal`` —
    and neither is :attr:`value`, which is the half this type used to leave open. Both the wrapper
    and its payload are types :func:`contracts.calc` refuses, so no arithmetic anywhere in the
    pipeline can consume either, and the gate engine's inputs are types neither can impersonate.
    """

    name: str
    scope: DiagnosticScope
    kind: str
    value: DiagnosticValue
    gate_relevance: str = DIAGNOSTIC_ONLY

    def __post_init__(self):
        _check_name(self.name)
        _check_gate_relevance(self.gate_relevance)
        if self.kind not in KINDS:
            raise ValueError("unknown output kind {!r} for diagnostic {}".format(self.kind, self.name))
        if not isinstance(self.scope, DiagnosticScope):
            raise TypeError("a diagnostic must carry a DiagnosticScope")
        object.__setattr__(
            self, "value", _as_payload(self.value, self.kind, "diagnostic {}".format(self.name))
        )


@_final
@dataclass(frozen=True)
class DiagnosticRankingRow(_NeverGating):
    """One row of a ranking. ``rank`` came from the unquantized value; ``value`` is displayed.

    ``rank`` and ``wallet`` stay plain: a position in a list and an address are coordinates, not
    measurements, and wrapping them would say a rank is a quantity someone might gate on.
    """

    rank: int
    wallet: str
    value: DiagnosticValue

    def __post_init__(self):
        if not isinstance(self.rank, int) or isinstance(self.rank, bool) or self.rank < 1:
            raise ValueError("a ranking row's rank must be a positive int, got {!r}".format(self.rank))
        if not self.wallet:
            raise ValueError("a ranking row must name its wallet")
        object.__setattr__(
            self, "value", _as_payload(self.value, USD, "profit for {}".format(self.wallet))
        )


@_final
@dataclass(frozen=True)
class DiagnosticRanking(_NeverGating):
    """An ordered diagnostic — §10's absolute USD profit ranking.

    Separate from :class:`Diagnostic` because a ranking is not a scalar and squeezing one into a
    scalar field would mean serialising an ordering as a string.
    """

    name: str
    scope: DiagnosticScope
    kind: str
    rows: Tuple[DiagnosticRankingRow, ...] = ()
    gate_relevance: str = DIAGNOSTIC_ONLY

    def __post_init__(self):
        object.__setattr__(self, "rows", tuple(self.rows))
        _check_name(self.name)
        _check_gate_relevance(self.gate_relevance)
        if self.kind not in KINDS:
            raise ValueError("unknown output kind {!r} for diagnostic {}".format(self.kind, self.name))
        if not isinstance(self.scope, DiagnosticScope):
            raise TypeError("a diagnostic must carry a DiagnosticScope")
        if not self.rows:
            raise ValueError(
                "an empty ranking is not a ranking; it is an absence, and publishing it as an "
                "ordered list of nothing reads as 'no wallet made money'"
            )
        for row in self.rows:
            if not isinstance(row, DiagnosticRankingRow):
                raise DiagnosticPromotionRefused(
                    "a {} was placed in a diagnostic ranking. A ranking row carries a payload the "
                    "gate cannot read; anything else would put a readable number inside a "
                    "DIAGNOSTIC_ONLY record.".format(type(row).__name__)
                )
            if row.value.kind != self.kind:
                raise ValueError(
                    "ranking {!r} is reported in {} and row {} carries a {} payload; the scale is "
                    "part of what a reported number means".format(
                        self.name, self.kind, row.rank, row.value.kind
                    )
                )


@_final
@dataclass(frozen=True)
class DiagnosticPack(_NeverGating):
    """Every diagnostic for one run, and nothing that is not one.

    The membership check is the second half of the structural separation. The first half stops a
    diagnostic reaching the gate; this half stops a gate input being carried in the diagnostics
    pack, where it would acquire the pack's ``DIAGNOSTIC_ONLY`` label and stop being auditable as
    a gate input.

    The pack re-runs each item's own invariants rather than trusting that they held at the item's
    construction. Construction-time validation is not tamper-proofing: ``object.__setattr__``
    rewrites a field of any Python object and no class can prevent it. What the pack can do — and
    does — is refuse to *carry* an item whose invariants no longer hold, which is what stops a
    rewrite reaching an artifact. See :meth:`verify`.

    "Re-runs" is meant literally, and it did not used to be. Passing an item on as an already-built
    object runs no ``__post_init__`` at all, so the sentence above was true only of the checks the
    pack happens to restate — of :class:`Diagnostic`'s five, two. :func:`_rebuilt` reconstructs each
    item from the fields it currently holds, which runs every one of them, and runs them without
    this class knowing what they are.

    **What that catches**, each demonstrated in ``tests/integration/test_reporting.py`` and
    ``tests/integration/test_reporting_claims.py``: a rewritten ``gate_relevance``, an unregistered
    ``name``, a spliced non-diagnostic, a duck-typed row spliced into a ranking, a bare-``Decimal``
    payload on an item or on a ranking row, a ``kind`` outside :data:`KINDS`, a ``value.kind``
    disagreeing with its item's **or with its ranking's declared kind** — the second of those was
    the check nothing pinned, and deleting it published a USD figure under a ``ratio`` label — a
    non-finite ``value.amount``, a duck-typed ``scope``, and a ``scope`` whose own fields no longer
    validate.

    It also refuses **two items answering one question**: the key is the name plus
    :func:`_scope_key`, and the scope is stored in canonical form, so a respelled capital level or
    a differently-cased chain is the same key rather than a second entry. That refusal is the
    reason the scope has a canonical form at all — see :class:`DiagnosticScope`.

    **What it does not, stated because the previous version of this docstring did not.** Rewriting
    ``value.amount`` from one *finite* ``Decimal`` to another is not detected, and no reconstruction
    could detect it: the payload is a measurement and no invariant on the item constrains which
    measurements are plausible — ``tail_loss`` is negative, ``buy_return_90d`` may exceed 1, and a
    rule refusing 99999 would be a rule about the world rather than about the type. The wall against
    *that* rewrite is unchanged and lives elsewhere: the figure is still a :class:`DiagnosticValue`
    that ``calc`` refuses, so a rewritten number reaches a report and still never reaches a gate.
    """

    items: Tuple[object, ...] = ()
    gate_relevance: str = DIAGNOSTIC_ONLY

    def __post_init__(self):
        object.__setattr__(self, "items", tuple(self.items))
        _check_gate_relevance(self.gate_relevance)
        seen = set()
        for item in self.items:
            if not isinstance(item, (Diagnostic, DiagnosticRanking)):
                raise DiagnosticPromotionRefused(
                    "a {} was placed in the diagnostics pack. The pack carries diagnostics only: "
                    "anything else would inherit the pack's DIAGNOSTIC_ONLY label and stop being "
                    "auditable as whatever it actually is.".format(type(item).__name__)
                )
            _check_name(item.name)
            _check_gate_relevance(item.gate_relevance)
            # ``_check_payload`` is the only check anywhere that sees a bare ``Decimal`` sitting in
            # a payload slot: ``_as_payload`` coerces one away, so a *kept* rebuild would launder
            # exactly this tamper.
            #
            # The order is not what makes the *bare-``Decimal``* tamper refusable — that is
            # ``_check_payload`` inspecting the item in place, which would still hold if it ran
            # second, and would stop holding the moment a rebuild's result was kept.
            #
            # The order **is** load-bearing for something else, and the previous version of this
            # comment denied it: it said swapping the two lines refuses every input "with the same
            # exception type and the same message, and the suite stays green". Re-measured on this
            # tree, that is false. Both orders raise ``DiagnosticPromotionRefused`` for a spliced
            # non-row, and the messages differ:
            #
            #     this order      "a str was placed in diagnostic ranking 'absolute_profit_ranking'"
            #     swapped         "a str was placed in a diagnostic ranking"
            #
            # because with ``_rebuilt`` first the refusal comes from ``DiagnosticRanking``'s own
            # reconstruction, which does not know which ranking it is rebuilding.
            # ``tests/integration/test_reporting_claims.py::
            # test_a_spliced_row_with_no_payload_at_all_is_a_typed_refusal`` goes red on the swap,
            # so the suite does not stay green either.
            _check_payload(item)
            _rebuilt(item)
            key = (item.name, _scope_key(item.scope))
            if key in seen:
                raise UnknownDiagnostic(
                    "diagnostic {!r} appears twice for the same scope; two answers to one question "
                    "means something must choose between them, and nothing is permitted "
                    "to".format(item.name)
                )
            seen.add(key)

    def named(self, name):
        """Every item carrying one diagnostic name, in insertion order."""
        return tuple(item for item in self.items if item.name == name)

    def verify(self):
        """Build the pack again from the items it is holding, and return it.

        Called at the point of publication rather than only at construction, because the window
        between the two is where a rewrite would land. Everything it checks is
        :meth:`__post_init__`'s, deliberately: a check added there is one this method runs, and a
        second list of rules here would be a list to forget something from.
        """
        DiagnosticPack(items=self.items, gate_relevance=self.gate_relevance)
        return self


def _rebuilt(value):
    """One diagnostic value tree, reconstructed from the fields its objects currently hold.

    This is what makes "re-run the item's invariants" mean anything. Handing an already-built object
    back to a constructor re-runs **none** of that object's ``__post_init__`` — it is a field
    assignment. Rebuilding it from ``getattr`` of every field runs all of it.

    Depth first, so a rewritten :class:`DiagnosticValue` is re-validated *before* the
    :class:`Diagnostic` that carries it is rebuilt around it, which is what makes the kind-agreement
    check between the two run at all.

    Reconstruction rather than a list of re-checks is the point: this function does not know what
    any type's invariants are, so a check added to any ``__post_init__`` is one it runs. Membership
    in :data:`_FINAL` is the test for "a type this module owns"; anything else — a ``WindowScore``
    spliced into ``items``, a duck-typed ``scope``, a ``Decimal``, an ``ActivityBand`` — is passed
    through untouched, so that what meets it is a typed refusal from the constructor it is handed
    to rather than an incidental ``TypeError`` from calling somebody else's.

    That holds on *this* function's path. It did not hold on the pack's, and the difference is the
    kind of thing a docstring quietly absorbs: :meth:`DiagnosticPack.__post_init__` runs
    :func:`_check_payload` first, and until it guarded its row loop a spliced non-row met
    ``AttributeError: 'str' object has no attribute 'value'`` there — refused, but by a duck test.
    The guard is now in ``_check_payload``, so the claim describes the whole path rather than this
    half of it.

    It is a re-validation, not a repair: the rebuilt object is discarded, and
    :meth:`DiagnosticPack.__post_init__` keeps the item it was handed. Nothing may be *fixed* on the
    way to an artifact, because a rewrite silently corrected is a rewrite nobody hears about — and
    :func:`_as_payload` coerces a bare ``Decimal`` by design, so a rebuild whose result was kept
    would launder exactly the tamper ``_check_payload`` exists to catch. That is a reason to keep
    discarding the result; it is **not** the reason the pack runs ``_check_payload`` before this
    function — the bare-``Decimal`` tamper is refused in either order, because ``_check_payload``
    inspects the item in place.

    The ordering is not inert, though, and an earlier version of this paragraph said it was:
    re-measured, swapping the two calls leaves a spliced non-row refused with the same exception
    type but a **message that no longer names the ranking**, and turns
    ``tests/integration/test_reporting_claims.py::
    test_a_spliced_row_with_no_payload_at_all_is_a_typed_refusal`` red. See the comment in
    :meth:`DiagnosticPack.__post_init__` for the two messages side by side.
    """
    if isinstance(value, tuple):
        return tuple(_rebuilt(entry) for entry in value)
    if type(value) not in _FINAL:
        return value
    return type(value)(**dict(
        (field.name, _rebuilt(getattr(value, field.name)))
        for field in fields(value) if field.init
    ))


def _check_payload(item):
    """Every measured figure an item carries is on the diagnostic side of the wall.

    The row loop guards the type before it reads ``.value``. Without that guard this function was
    the first thing a spliced non-row met — it runs before :func:`_rebuilt` — and it met it with
    ``AttributeError: 'str' object has no attribute 'value'``, an incidental error from a duck test
    this module makes a point of not relying on. Same refusal either way; the difference is whether
    the message names the defect.
    """
    if isinstance(item, Diagnostic):
        values = [item.value]
    else:
        for row in item.rows:
            if not isinstance(row, DiagnosticRankingRow):
                raise DiagnosticPromotionRefused(
                    "a {} was placed in diagnostic ranking {!r}. A ranking row carries a payload "
                    "the gate cannot read; anything else would put a readable number inside a "
                    "DIAGNOSTIC_ONLY record.".format(type(row).__name__, item.name)
                )
        values = [row.value for row in item.rows]
    for value in values:
        if not isinstance(value, DiagnosticValue):
            raise DiagnosticPromotionRefused(
                "diagnostic {!r} carries a {} payload rather than a DiagnosticValue. A bare "
                "Decimal is a type the gate engine reads: it is accepted as a calibrated "
                "threshold and as a follower-adjusted excess. §10: only buy_quality decides the "
                "gate.".format(item.name, type(value).__name__)
            )


def _scope_key(scope):
    """The identity of a measurement, in a form where equal scopes give equal keys.

    Two independent reasons that holds, because one of them alone is a repair a refactor deletes:
    :class:`DiagnosticScope` stores every field canonically, *and* the one field whose Python
    equality does not imply an equal rendering — the ``Decimal`` level, where ``Decimal("1.5E+6")``
    and ``Decimal("1500000")`` are equal and ``str`` disagrees — is rendered here by
    :func:`contracts.canonicalise`, which is the same rendering the artifact gets. Keying on
    ``str(scope.capital_level)`` was the defect: it made one measurement into two entries, and the
    pack published both answers to the question its own message says nothing may choose between.
    """
    return (
        scope.chain,
        scope.window,
        scope.population,
        None if scope.capital_level is None else canonicalise(scope.capital_level),
        scope.liquidity_band,
        None if scope.band is None else scope.band.value,
    )


def diagnostic(name, scope, value, kind=RATIO):
    """Build one scalar diagnostic, quantized once at the boundary."""
    return Diagnostic(
        name=name,
        scope=scope,
        kind=kind,
        value=at_output(value, kind, "diagnostic {}".format(name)),
    )


def profit_ranking(scope, rows, name="absolute_profit_ranking"):
    """§10's absolute USD profit ranking.

    :param rows: ``(wallet, profit_usd)`` pairs, unquantized.

    Ordering is decided on the **unquantized** profit, descending, with ties broken by wallet
    address ascending so the output is byte-stable. Equal profits share the lower rank — competition
    ranking — because a tie invented by the display scale, or broken by an address, would be an
    ordering claim the data does not support.

    The displayed value is quantized afterwards. Two wallets whose profits differ below the USD
    output scale therefore render identically and still rank in the right order, which is the
    correct way round: ranking on the rendered figure would silently declare them equal.
    """
    prepared = []
    for wallet, profit in rows:
        address = (wallet or "").lower()
        if not address:
            raise ValueError("a ranking row must name its wallet")
        prepared.append((address, require_finite(calc(profit), "profit for {}".format(address))))

    if len({address for address, _ in prepared}) != len(prepared):
        raise ValueError(
            "a wallet appears twice in the ranking; the duplicate occupies a rank that belongs to "
            "another wallet and is invisible in the published order"
        )

    # Two stable passes rather than one key of ``(-profit, wallet)``. Unary minus on a Decimal
    # rounds to the *ambient* context — the exact defect ``contracts.numeric`` exists to eliminate
    # — and here it would round two profits into a tie and then rank them by address. Sorting by
    # address first and by profit descending second gets the same order with no arithmetic at all.
    ordered = sorted(prepared, key=lambda row: row[0])
    ordered = sorted(ordered, key=lambda row: row[1], reverse=True)

    ranked = []
    previous_value = None
    previous_rank = 0
    for index, (address, profit) in enumerate(ordered, start=1):
        if previous_value is not None and profit == previous_value:
            rank = previous_rank
        else:
            rank = index
        previous_value, previous_rank = profit, rank
        ranked.append(
            DiagnosticRankingRow(
                rank=rank,
                wallet=address,
                value=at_output(profit, USD, "profit for {}".format(address)),
            )
        )

    return DiagnosticRanking(name=name, scope=scope, kind=USD, rows=tuple(ranked))


def diagnostic_pack(items=()):
    """Collect diagnostics for one run."""
    return DiagnosticPack(items=tuple(items))
