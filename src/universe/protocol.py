"""The pre-registered numbers, the four-window calendar, and the address normal form.

Stated once, here, and computed nowhere. §6.1, §6.2, §6.3 and §6.5 each fix a constant that some
later module would otherwise be free to restate; a second copy of a bound is a second bound, and
the two disagree the first time one of them is edited.

Two decisions in this module are worth reading before the constants:

**``T0Instant`` carries a block *and* a UTC second.** The seam pairs every timestamp with a block
number, and the two consumers here want different ones: a score is stamped in blocks, a warehouse
row in seconds. A T0 that were only a block would leave the second edge unverifiable, and
:func:`universe.observation.require_pre_t0` refuses an unverifiable claim rather than skipping it.
It is a *value* rather than an argument some functions take and others forget — the record carries
it, so a record whose T0 was never supplied does not exist.

**``WindowKey`` is closed.** §6.3 names exactly four training windows. A fifth cannot be *named*,
which is what makes "a replacement window was chosen after seeing the data" impossible to express
without going through :func:`universe.step0.replace_window` and its pre-registered rule.

:func:`normalise_selection_account` is this package's own copy and is deliberately **not** imported
from ``attribution``. The leaf rule in ``tests/test_lane_independence.py`` forbids the import, and
``reporting/aggregate.py``'s argument applies anyway: a shared helper is a shared bug that both
sides inherit through a dependency each believes to be neutral.

Everything here is **pre-T0 only**, in its name
------------------------------------------------

An earlier draft of this module argued exactly the sentence above and then shared its helpers with
the post-T0 side anyway. ``require_int`` was called from ``PreT0Score.__post_init__`` *and* from
``ForwardActivity.__post_init__``; ``normalise_account`` was called from both families;
``class Sealed`` was one base with one module-level registry over both, so
``isinstance(pre_t0_thing, Sealed)`` and ``isinstance(forward_thing, Sealed)`` were both ``True``
and any parameter annotated ``Sealed`` accepted either.

So the names below say ``pre_t0`` and ``selection``, and ``universe.forward`` carries its **own**
copies of every one of them. The duplication is the price and it is a low one: a shared tunnel is
worth far more to an attacker than two copies of ten lines cost the reader, because a tunnel is a
single signature that both families fit through and there is no annotation that closes it.

What this module does not guarantee: nothing here validates that an address is an address, that a
block number corresponds to the timestamp beside it, or that the calendar bounds a caller supplies
are the ones §6.3 names. Those are claims the caller makes, and every guarantee downstream is
conditional on their being true.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from contracts import ContractError
from phase0.parameters import PARAMETERS

#: Bump when any type in this package changes shape. It is hashed into the universe snapshot
#: identifier, so an artefact written under an older version is re-derived rather than
#: reinterpreted.
UNIVERSE_SCHEMA_VERSION = "universe-v1"

# -- the two-stage buffer (§6.2, ticket 25) --------------------------------------
#
# The warehouse admits on POTENTIAL buys; eligibility is decided on VALID buys after netting. The
# gap between the two pairs is the buffer, and it is the whole point: filtering at 20-1,000 in the
# first pass silently drops every account netting would have moved across the boundary, and the
# drop is invisible because the account was never returned.
#
# Every bound below is READ from the ticket-11 frozen parameter set rather than written down here.
# The names stay, because ``POTENTIAL_BUY_FLOOR`` reads better at a call site than a dotted string
# does — what changed is that they are now views onto one value instead of a second copy of it. A
# local literal is a bound this package could edit without the frozen set noticing, which is the
# drift ticket 11's third criterion exists to close; an unknown key raises at import time, so a
# typo here is a failure to start rather than a silent default.

POTENTIAL_BUY_FLOOR = PARAMETERS.value("eligibility.potential_buys.floor")
POTENTIAL_BUY_CEILING = PARAMETERS.value("eligibility.potential_buys.ceiling")

VALID_BUY_FLOOR = PARAMETERS.value("eligibility.valid_buys.floor")
VALID_BUY_CEILING = PARAMETERS.value("eligibility.valid_buys.ceiling")

#: §6.1. A window below this is `INSUFFICIENT CANDIDATE UNIVERSE`.
MINIMUM_ELIGIBLE_UNIVERSE = PARAMETERS.value("universe.minimum_eligible_accounts")

# -- selection (§6.5, ticket 28) -------------------------------------------------

SELECTED_MIN = PARAMETERS.value("selection.minimum")
SELECTED_MAX = PARAMETERS.value("selection.maximum")

#: ``1% of Eligible Universe`` as integer arithmetic: ``size // SELECTION_PERCENT_DENOMINATOR``.
#: Kept as a named denominator so the percentage is visible as a percentage rather than as a magic
#: 100 inside a floor division.
SELECTION_PERCENT_DENOMINATOR = 100

#: §10's activity bands, by valid-buy count, inclusive at both ends. Read from the ticket-11 frozen
#: set, which is what closed the drift surface this line used to describe: the package is a leaf and
#: still may not import ``reporting``, but both it and ``reporting.diagnostics`` may import
#: ``phase0``, so the shared constant that was unavailable when the two copies were written now
#: exists. ``PARAMETERS`` checks the tiling at construction — a gap between two bands would report
#: fewer wallets than the run selected and look like an empty band.
ACTIVITY_BAND_BOUNDS = PARAMETERS.value("reporting.activity_bands")


class SealedDerivationRefused(ContractError):
    """A type this package seals was subclassed.

    Subclassing is not a hypothetical route around a construction invariant. A subclass overriding
    ``__post_init__`` drops every check its base runs while remaining an ``isinstance`` of it, and
    a subclass with two bases carries two standings in one object — which is exactly the confusion
    the pre-T0 / post-T0 split exists to prevent. Every entry point in this package therefore
    checks ``type(x) is T`` rather than ``isinstance``, and the sealed types below make the
    subclass that would defeat that check unconstructible in either base order.
    """


#: The **selection side's** registry, and nothing else's. ``universe.forward`` keeps its own,
#: unreachable from here. One registry over both families was the audit's finding: it made
#: ``Sealed`` a base that ``isinstance`` answered ``True`` for on either side, so a parameter
#: annotated with it accepted both.
_PRE_T0_SEALED = set()


class PreT0Sealed(object):
    """Base of every sealed **pre-T0** type: deriving from one is refused at definition time.

    Modelled on ``reporting.diagnostics._Sealed``. The check is on the *derivation* rather than on
    any particular base list, so a subclass is refused whichever order its bases are written in.

    ``isinstance(x, PreT0Sealed)`` is deliberately never used as a gate anywhere in this package.
    The base exists to make subclassing impossible, not to answer membership questions — the gates
    are ``type(x) is T`` on the concrete type. A base used as a gate is a base an attacker only has
    to reach once.
    """

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        for base in cls.__mro__[1:]:
            if base in _PRE_T0_SEALED:
                raise SealedDerivationRefused(
                    "{} derives from {}, which is sealed on the pre-T0 side. A subclass can "
                    "override __post_init__ and drop the T0 check its base runs, while still "
                    "satisfying every isinstance test written against the base — and a subclass "
                    "with a second base carries two standings in one object. Neither is a shape "
                    "this package can distinguish.".format(cls.__name__, base.__name__)
                )


def pre_t0_sealed(cls: type) -> type:
    """Mark a pre-T0 class un-derivable. Applied above ``@dataclass`` so it runs last.

    Annotated ``type`` rather than ``object``: a class object is not a value, so this parameter is
    not a tunnel any metric could travel through, and ``type`` is the narrowest name Python has for
    what it actually takes.
    """
    _PRE_T0_SEALED.add(cls)
    return cls


def normalise_selection_account(address: str) -> str:
    """Strip, lowercase, and refuse an empty address — **on the selection side only**.

    Stripping is deliberate here and deliberately absent from ``contracts.normalise_asset``: an
    account address arriving from a warehouse export routinely carries padding, and unlike a token
    key there is no second key space this could disagree with — every selection address in this
    package goes through this one function on the way in.

    ``universe.forward`` has its own copy under its own name. The two are byte-identical today and
    that is fine: the value of the split is not that they behave differently, it is that no single
    signature accepts an address from both families, so this function cannot become the tunnel it
    was.

    What it does not do: validate that the result is an address. ``"not-an-address"`` normalises to
    itself and is refused by nothing here.
    """
    if not isinstance(address, str):
        raise TypeError(
            "a selection account address must be a str, got {}. A non-string address cannot be "
            "compared against the frozen membership, and every refusal in this package is a "
            "comparison against it.".format(type(address).__name__)
        )
    text = address.strip().lower()
    if not text:
        raise ValueError(
            "an account with no address cannot be counted in a census, excluded by a named rule, "
            "or pinned in a frozen universe"
        )
    return text


def require_pre_t0_int(value: int, name: str) -> int:
    """Blocks, UTC seconds and counts are ``int`` by seam rule — never Decimal, never bool.

    ``bool`` is refused explicitly because it *is* an ``int`` in Python: ``valid_buys=True`` would
    pass an ``isinstance`` check and count as one buy.

    Named ``pre_t0`` because the post-T0 side has its own copy. The audit ran the old shared
    ``require_int`` with a forward-side value and a selection-side value in the same parameter and
    both succeeded; that is the definition of a signature accepting both families.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            "{} must be an int; block numbers, UTC seconds and counts are int by seam rule. "
            "Got {}.".format(name, type(value).__name__)
        )
    return value


@pre_t0_sealed
@dataclass(frozen=True)
class T0Instant(PreT0Sealed):
    """The selection instant, in both dimensions the seam requires.

    Both fields are required. A T0 carrying only a block cannot check a record's timestamp, and
    ``require_pre_t0`` refuses a timestamp it cannot check rather than ignoring it — a guard a
    caller can switch off by omitting an argument is not a guard.
    """

    block: int
    timestamp: int

    def __post_init__(self) -> None:
        for name in ("block", "timestamp"):
            value = require_pre_t0_int(getattr(self, name), "T0Instant.{}".format(name))
            if value <= 0:
                raise ValueError(
                    "T0Instant.{} is {}; a non-positive block or UTC second is not an instant on "
                    "this chain, and every pre-T0 comparison in this package is against "
                    "it".format(name, value)
                )


class WindowKey(str, Enum):
    """§6.3's four training windows, and no fifth.

    Closed on purpose. §6.1 forbids selecting a replacement window after seeing data unless the
    replacement rule was pre-registered; a window that cannot be *named* cannot be chosen by
    someone editing a list. The one route to a different calendar is
    :func:`universe.step0.replace_window`, which reuses the slot's key and records what replaced it.
    """

    W1_2023H1 = "W1_2023H1"
    W2_2023H2 = "W2_2023H2"
    W3_2024H1 = "W3_2024H1"
    W4_2024H2 = "W4_2024H2"


#: §6.3's order. Used only for reporting and for the four-window completeness check.
WINDOW_ORDER = (
    WindowKey.W1_2023H1,
    WindowKey.W2_2023H2,
    WindowKey.W3_2024H1,
    WindowKey.W4_2024H2,
)

SECONDS_PER_DAY = 86400


@pre_t0_sealed
@dataclass(frozen=True)
class TrainingWindow(PreT0Sealed):
    """One §6.3 window: a baseline that ends at ``T0`` and a forward period that starts there.

    **The baseline's end is ``T0`` by construction and not by a field.** §6.5 ranks on the six
    months before T0; a separately supplied ``baseline_end`` is a field that can disagree with T0,
    and the disagreement would be invisible because both values look reasonable.

    ``replaced_from`` is set only by :func:`universe.step0.replace_window`. A window carrying it is
    one whose slot was revised under a pre-registered rule, and it travels into the snapshot
    identifier so the revision cannot be dropped from the record.
    """

    key: WindowKey
    t0: T0Instant
    baseline_start_block: int
    baseline_start_ts: int
    forward_end_block: int
    forward_end_ts: int
    replaced_from: Optional[WindowKey] = None

    def __post_init__(self) -> None:
        if not isinstance(self.key, WindowKey):
            raise TypeError(
                "a training window must be keyed by a WindowKey, got {}. The enum is closed at "
                "§6.3's four windows so that a fifth cannot be named.".format(
                    type(self.key).__name__
                )
            )
        if type(self.t0) is not T0Instant:
            raise TypeError(
                "window {} must carry a T0Instant, got {}. A pair of bare ints would let the block "
                "and the second be supplied in either order with nothing to "
                "notice.".format(self.key.value, type(self.t0).__name__)
            )
        for name in ("baseline_start_block", "baseline_start_ts",
                     "forward_end_block", "forward_end_ts"):
            require_pre_t0_int(getattr(self, name), "{}.{}".format(self.key.value, name))
        if self.replaced_from is not None and not isinstance(self.replaced_from, WindowKey):
            raise TypeError("replaced_from must be a WindowKey or None")

        if not (self.baseline_start_block < self.t0.block < self.forward_end_block):
            raise ValueError(
                "window {} has baseline_start_block {}, T0 block {} and forward_end_block {}. The "
                "baseline must end strictly before T0 and the forward period must start strictly "
                "after it; a baseline that reaches T0 has already seen the instant the selection "
                "decision is made.".format(
                    self.key.value, self.baseline_start_block, self.t0.block,
                    self.forward_end_block,
                )
            )
        if not (self.baseline_start_ts < self.t0.timestamp < self.forward_end_ts):
            raise ValueError(
                "window {} has baseline_start_ts {}, T0 second {} and forward_end_ts {}; the same "
                "ordering is required in seconds as in blocks, or one dimension would admit what "
                "the other refuses.".format(
                    self.key.value, self.baseline_start_ts, self.t0.timestamp,
                    self.forward_end_ts,
                )
            )

    @property
    def baseline_seconds(self) -> int:
        return self.t0.timestamp - self.baseline_start_ts

    @property
    def baseline_days(self) -> int:
        """Whole UTC days in the baseline. Integer arithmetic — exact, and no rounding question."""
        return self.baseline_seconds // SECONDS_PER_DAY

    @property
    def forward_seconds(self) -> int:
        return self.forward_end_ts - self.t0.timestamp

    @property
    def forward_days(self) -> int:
        return self.forward_seconds // SECONDS_PER_DAY


@dataclass(frozen=True)
class WindowDesign:
    """The four-window design (§6.3), plus the record of anything that replaced a slot.

    Exactly four windows with distinct keys. Three would be a design nobody registered, and a
    duplicate key would give one slot two calendars with nothing to say which is the slot.

    ``replacements`` is annotated as a **string forward reference** to
    :class:`universe.step0.WindowReplacement`. ``step0`` imports this module, so importing it back
    would close a cycle; a string annotation is nominal to a reader and to the static signature
    check, and is never resolved at runtime. It is deliberately not ``Tuple[object, ...]``, which
    was the previous spelling and which named no type at all. What is checked here is that the tuple
    is a tuple; what a replacement *means* is ``step0``'s to enforce, and it does.
    """

    windows: Tuple[TrainingWindow, ...]
    replacements: Tuple["WindowReplacement", ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "windows", tuple(self.windows))
        object.__setattr__(self, "replacements", tuple(self.replacements))
        for window in self.windows:
            if type(window) is not TrainingWindow:
                raise TypeError(
                    "a window design holds TrainingWindow values, got {}. A subclass overriding "
                    "__post_init__ would carry a baseline that reaches past "
                    "T0.".format(type(window).__name__)
                )
        if len(self.windows) != len(WINDOW_ORDER):
            raise ValueError(
                "the design holds {} window(s); §6.3 registers exactly {}. Running on fewer is a "
                "different experiment from the one that was pre-registered, and the count is the "
                "only place that difference is visible.".format(
                    len(self.windows), len(WINDOW_ORDER)
                )
            )
        keys = [w.key for w in self.windows]
        if len(set(keys)) != len(keys):
            duplicated = sorted({k.value for k in keys if keys.count(k) > 1})
            raise ValueError(
                "window key(s) {} appear more than once. One slot with two calendars has no answer "
                "to 'which window is this', and supplying both is the evidence that nobody "
                "knows.".format(", ".join(duplicated))
            )

    def window(self, key: "WindowKey") -> TrainingWindow:
        for candidate in self.windows:
            if candidate.key is key:
                return candidate
        raise KeyError(
            "the design has no window {}; it holds {}".format(
                getattr(key, "value", key), ", ".join(w.key.value for w in self.windows)
            )
        )

    @property
    def keys(self) -> Tuple["WindowKey", ...]:
        return tuple(w.key for w in self.windows)
