"""Ticket 11 — the authoritative parameter set, and the freeze that closes it.

The pre-registration's whole worth is that its numbers were fixed before anybody saw a result. That
is a claim about *time*, and a claim about time survives only if the numbers live in one place with
a date and a commit attached to them. This module is that place: every threshold, bound, window,
bucket boundary and wording the experiment turns on, each carrying the section it came from, in one
table that a person freezes and that nothing afterwards may write to.

Three things it is, stated plainly
----------------------------------

* **A table, not a formula.** Nothing here computes anything. ``phase0`` is SHARED and imports no
  builder package, so it could not compute a metric if it wanted to.
* **Readable everywhere.** :data:`PARAMETERS` is a module constant. Every downstream stage reads
  its thresholds from it instead of writing them down again, so a threshold cannot drift out of the
  frozen set in one lane while the set still says otherwise. What is still duplicated is listed in
  ``tests/hand_computed/test_parameters.py`` under ``UNMIGRATED`` and pinned equal there — a named
  partial migration, because an unnamed one is indistinguishable from a complete one.

  That list is checked against the tree rather than maintained by hand:
  ``test_no_module_level_constant_duplicates_a_frozen_value_unnamed`` walks every module-level
  assignment in ``src/`` and fails on any literal equal to a frozen value that appears in neither
  ``MIGRATED`` nor ``UNMIGRATED``. It was written because the first version of this module missed
  two — ``phase0.seeds.MASTER_SEED_BYTES`` and ``FIELD_SEPARATOR``, restated here as ``32`` and
  ``"|"`` while ``seeds.py`` held its own copies — and missed them while the entry directly beside
  them read ``RunRecord.SEED_RULE`` specifically to avoid retyping a value. Both copies agreed, so
  nothing failed. A claim of completeness that nothing checks is worth about what that one was.
* **Not the editor.** :class:`ParameterRegister` has no write path in either state. Before the
  freeze, a value changes by editing the pre-registration and this module together at a commit;
  after it, :meth:`ParameterRegister.request_change` refuses and writes an audit entry naming who
  asked.

What this module does **not** do, and must not
----------------------------------------------

It does not freeze anything. ``PARAMETERS_FROZEN`` records a human act — see
:data:`phase0.execution.MANUAL_TRANSITIONS` — and no code path here reaches it on its own.
:meth:`ParameterRegister.freeze` takes a :class:`FreezeRecord`, which cannot be built without a
person's name, a commit hash and a date, and refuses placeholder names. There is no default
requester, no ``freeze_if_ready``, and no argument whose omission produces one. A register that
nobody has frozen reads :data:`NOT_FROZEN`, and that is the state this repository is in.

It does not make the set *unwritable in memory*. Python has no frozen object, and a caller holding
a reference can reach the private dict. What makes the freeze binding is the refusal plus the
hash-chained audit entry that records the attempt, not attribute privacy — and the honest
consequence is that this module detects an attempted change made through it and cannot detect one
made by editing the source. That is what the commit hash in the freeze record is for.

Where the values come from
--------------------------

Every one is quoted to its section. Two documents supply them, and the split is not cosmetic:

* ``docs/phase-0-preregistration.md`` — the experiment. §-numbers below with no other prefix.
* ``docs/decision-engine-addendum.md`` — the decisions the pre-registration deferred, listed in its
  own §15 as "items this addendum closes": the netting residual tolerance, the dead-pool
  conjunction, the Copy Retention floor, the seed policy, the execution cost caps, the fill
  requirement and the two-stage eligibility buffer. Cited as ``addendum §n``.

A value that appears in neither is not in this table. Exactly one threshold the machine needs falls
in that gap and it is named rather than invented: the dead-pool conjunction's *"executable exit
value is below the minimum threshold"* has no figure in either document. ``marking/pools.py`` pins
$1.00 locally and reports it as an open item; putting it here under a §-citation would manufacture
a pre-registration nobody wrote. See :data:`NOT_PREREGISTERED`.

Types, and why a float is unconstructible here
----------------------------------------------

A parameter set that stores ``0.15`` as a float has already lost the freeze: the value that comes
back is not the value that went in, and the gate it feeds is a different gate. So :class:`Parameter`
coerces by declared unit at construction — every ratio and every dollar amount goes through
:func:`contracts.numeric.calc`, which refuses a ``float`` on sight, and every count, block, second
and day is checked to be an exact ``int`` (``bool`` included in the refusal, since ``True`` is an
``int`` in Python and ``True`` accounts is not a universe floor). There is no unit whose coercion
accepts a float, so the failure mode is a construction error at import time rather than a number
that silently disagrees with the document.
"""

import datetime
from decimal import Decimal

from contracts.numeric import calc

from .errors import FrozenError, ParameterSetNotWritable
from .governance import PARAMETERS_FROZEN, position
from .runs import RunRecord
from .seeds import FIELD_SEPARATOR, MASTER_SEED_BYTES
from .validator import MAX_COMPLEX_ACCOUNTS, MIN_COMPLEX_ACCOUNTS, why_not_a_name

# -- units ----------------------------------------------------------------------
#
# The unit decides the type, and the type is enforced rather than documented. Adding a unit means
# adding its coercion; a Parameter whose unit has none is refused, so a new unit cannot arrive by
# omission with no checking behind it.

#: Dimensionless Decimal. ``0.15`` is fifteen percentage points, in the units buy quality itself
#: uses — the same convention ``scoring`` and ``reporting`` carry.
RATIO = "ratio"

#: A Decimal amount in US dollars.
USD = "usd"

#: A tuple of Decimal US dollar amounts, in the order the document lists them.
USD_LEVELS = "usd_levels"

#: An exact count of things — accounts, buys, runs, controls, windows, a percentile.
COUNT = "count"

#: An exact count of blocks.
BLOCKS = "blocks"

#: An exact count of UTC seconds.
SECONDS = "seconds"

#: An exact count of days.
DAYS = "days"

#: One string, fixed verbatim.
TEXT = "text"

#: A tuple of strings, each fixed verbatim, in the order the document lists them.
CLAUSES = "clauses"

#: A tuple of ``(label, low, high)`` bands, inclusive at both ends, in ascending order. §10 writes
#: its activity bands as ``20–99 / 100–499 / 500–1,000``; this is that table in a form two packages
#: can read. Coercion checks the shape *and* the tiling — ascending, contiguous, no gap and no
#: overlap — because a band table with a hole in it silently drops every wallet that falls in the
#: hole, and a report that omits wallets without saying so is the failure mode worth checking for.
BANDS = "bands"

#: The walk-forward windows: a tuple of ``(train_start, train_end, test_start, test_end)``, each an
#: inclusive ``YYYY-MM``. §6.3 writes them as month names; ``YYYY-MM`` is the same fact in a form a
#: machine can order, and the boundary months are inclusive exactly as the document reads them.
WINDOWS = "windows"

#: ``True`` or ``False``, and nothing that coerces to one.
FLAG = "flag"

#: ``None``, meaning **this value does not exist yet and nobody has chosen one**. Distinct from a
#: zero or an empty string, which would be a choice somebody made. Only the master seed uses it;
#: see the ``seeds.master_seed`` entry in :data:`PARAMETERS`.
UNMINTED = "unminted"


def _exact_int(value, key, unit):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            "parameter {!r} is declared {} and must be an exact int, got {!r} ({}). A float count "
            "is not a count, and bool is refused too — True is an int in Python and 'True "
            "accounts' is not a universe floor.".format(
                key, unit, value, type(value).__name__)
        )
    return value


def _text(value, key):
    if not isinstance(value, str) or not value.strip():
        raise TypeError(
            "parameter {!r} is declared text and must be a non-empty str, got {!r}".format(
                key, value)
        )
    return value


def _bands(key, value):
    """A band table, checked for the two things a band table can be wrong about.

    The shape — ``(label, low, high)``, exact ints, ascending — and the tiling. A gap between two
    bands is not a cosmetic defect: every wallet whose count falls in it is reported under no band
    at all, so the §10 sensitivity table would silently cover fewer wallets than the run selected,
    and nothing downstream would be able to tell that from a genuinely empty band. An overlap is
    the same failure counted twice.
    """
    bands = tuple(tuple(band) for band in value)
    if not bands:
        raise TypeError("parameter {!r} is declared bands and is empty".format(key))
    previous_high = None
    for band in bands:
        if len(band) != 3:
            raise TypeError(
                "parameter {!r} has the band {!r}; each band is (label, low, high)".format(
                    key, band)
            )
        label, low, high = band
        _text(label, key)
        _exact_int(low, key, BANDS)
        _exact_int(high, key, BANDS)
        if low > high:
            raise ValueError(
                "parameter {!r} band {!r} runs backwards: {} > {}".format(key, label, low, high)
            )
        if previous_high is not None and low != previous_high + 1:
            raise ValueError(
                "parameter {!r} band {!r} starts at {} and the one before it ended at {}. Bands "
                "tile the eligible range: {} would leave every wallet between them in no band at "
                "all, which reports fewer wallets than the run selected and looks like an empty "
                "band rather than a hole.".format(
                    key, label, low, previous_high,
                    "a gap" if low > previous_high + 1 else "an overlap")
            )
        previous_high = high
    return bands


def _coerce(key, unit, value):
    """The value as its unit requires it, or a refusal naming the parameter.

    Every numeric unit routes through :func:`contracts.numeric.calc` or :func:`_exact_int`, so
    ``float`` is refused on every path. There is deliberately no fallback branch: an unrecognised
    unit raises rather than passing the value through unchecked.
    """
    if unit in (RATIO, USD):
        return calc(value)
    if unit == USD_LEVELS:
        return tuple(calc(item) for item in value)
    if unit in (COUNT, BLOCKS, SECONDS, DAYS):
        return _exact_int(value, key, unit)
    if unit == TEXT:
        return _text(value, key)
    if unit == CLAUSES:
        return tuple(_text(item, key) for item in value)
    if unit == WINDOWS:
        return tuple(tuple(_text(month, key) for month in window) for window in value)
    if unit == BANDS:
        return _bands(key, value)
    if unit == FLAG:
        if not isinstance(value, bool):
            raise TypeError(
                "parameter {!r} is declared a flag and must be True or False, got {!r}. A truthy "
                "string is not a flag: 'no' is truthy.".format(key, value))
        return value
    if unit == UNMINTED:
        if value is not None:
            raise TypeError(
                "parameter {!r} is declared unminted and must be None, got {!r}. None here means "
                "nobody has chosen a value; any other value would be a choice.".format(key, value))
        return None
    raise ValueError(
        "parameter {!r} declares the unknown unit {!r}. A unit without a coercion checks nothing, "
        "so it is refused rather than passed through.".format(key, unit)
    )


class Parameter(object):
    """One value the pre-registration fixes, and where it came from.

    :param key: the dotted identifier downstream code reads it by.
    :param value: coerced by ``unit`` at construction; see :func:`_coerce`.
    :param unit: one of the unit constants in this module.
    :param source: the section that fixes it, e.g. ``"§6.5"`` or ``"addendum §9.1"``. Required and
        non-empty: a parameter with no citation is a number somebody remembered, and the whole
        point of the table is that no value in it came out of anybody's memory.
    :param note: what the value means, or what it deliberately does not decide.

    **What carrying a source does and does not establish.** It records which section the value was
    taken from, so a reader can check it against the document. It does not verify that the section
    says what the note claims — nothing here parses the pre-registration — so the citation is a
    pointer for a human, and ``tests/hand_computed/test_parameters.py`` is where each value is
    written out again by hand against the document rather than recomputed from this module.
    """

    __slots__ = ("key", "value", "unit", "source", "note")

    def __init__(self, key, value, unit, source, note=""):
        self.key = _text(key, key)
        self.unit = unit
        self.value = _coerce(self.key, unit, value)
        if not source or not str(source).strip():
            raise ValueError(
                "parameter {!r} has no source section. Every value in the frozen set is quoted to "
                "the section that fixes it; an uncited one is a number from memory.".format(key)
            )
        self.source = str(source).strip()
        self.note = str(note or "")

    def as_dict(self):
        return {
            "key": self.key,
            "value": plain(self.value),
            "unit": self.unit,
            "source": self.source,
            "note": self.note,
        }

    def __repr__(self):
        return "<Parameter {} = {!r} ({})>".format(self.key, self.value, self.source)


def plain(value):
    """A JSON-safe rendering that loses no digits: Decimal becomes ``str``, never ``float``.

    Used for audit details and for :meth:`ParameterSet.as_dict`. ``float(Decimal("0.15"))`` would
    round-trip through the exact representation problem the whole numeric policy exists to avoid,
    so it is not an option here even for a log line — a log that disagrees with the value is worse
    than no log.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return [plain(item) for item in value]
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


# -- the set --------------------------------------------------------------------


class UnknownParameter(KeyError):
    """A key nobody registered. A caller bug, not a refusal — see :class:`ParameterSet`."""


class ParameterSet(object):
    """The authoritative table. Ordered, keyed, and with no method that writes.

    Absence of a mutator is the design: there is no ``add``, no ``__setitem__``, no ``update`` and
    no ``with_override``, so a stage cannot be handed a set that differs from the one the freeze
    covered. That is a real guarantee about this class and **not** a guarantee about the process:
    a caller holding the instance can reach ``_by_key`` and Python will not stop it. What stands
    between a determined edit and a published result is the commit hash in the
    :class:`FreezeRecord` and the hash chain in the audit log, not this object's shape.
    """

    def __init__(self, parameters):
        by_key = {}
        order = []
        for parameter in parameters:
            if parameter.key in by_key:
                raise ValueError(
                    "duplicate parameter {!r}. Two entries for one key means one of them is dead "
                    "and nobody knows which, which is the drift this table exists to "
                    "end.".format(parameter.key)
                )
            by_key[parameter.key] = parameter
            order.append(parameter.key)
        self._by_key = by_key
        self._order = tuple(order)

    def __contains__(self, key):
        return key in self._by_key

    def __len__(self):
        return len(self._order)

    def __iter__(self):
        return iter(self._order)

    def keys(self):
        return self._order

    def parameters(self):
        """Every :class:`Parameter`, in declaration order."""
        return tuple(self._by_key[key] for key in self._order)

    def parameter(self, key):
        try:
            return self._by_key[key]
        except KeyError:
            raise UnknownParameter(
                "no parameter {!r} in the frozen set. Known keys: {}. This is a caller error and "
                "not a refusal: a stage asking for a threshold that was never pre-registered has "
                "invented one, and returning None would let it run on the invention.".format(
                    key, ", ".join(self._order))
            )

    def value(self, key):
        """The frozen value. Readable in every state, by every stage, before and after the freeze.

        Readable *before* the freeze on purpose. The values are what the pre-registration says
        whether or not anybody has signed it yet, and a table that refused to answer until the
        freeze would leave every stage to write the number down locally in the meantime — which is
        precisely the duplication the freeze is supposed to prevent.
        """
        return self.parameter(key).value

    def source(self, key):
        return self.parameter(key).source

    def as_dict(self):
        return {key: self._by_key[key].as_dict() for key in self._order}

    def report(self):
        """Lines for the status command, in declaration order."""
        return ["{:<44} {:<26} {}".format(
            parameter.key, _render(parameter.value), parameter.source)
            for parameter in self.parameters()]


def _render(value):
    if isinstance(value, tuple):
        return "({} items)".format(len(value))
    if value is None:
        return "NOT MINTED"
    text = str(value)
    return text if len(text) <= 24 else text[:21] + "..."


# -- the values -----------------------------------------------------------------
#
# Keys are dotted, lowercase and written as literals at every call site, here and in the modules
# that read them. Deliberately literals rather than imported name constants: a typo raises
# :class:`UnknownParameter` at import time, so the loudness is the same, and ``grep -rn
# 'gate.first_hour_edge_share_max' src/`` then finds every reader of a threshold in one command —
# which is the question this table exists to make answerable.
#
# Every number below is written as a string or an int, so no float exists anywhere on the path from
# the document to the table.

#: §11.2, verbatim enough to bind. Arbitrum is pre-registered **now**, as a secondary diagnostic
#: outside the gate, and that is the whole point of it being here rather than in a later ticket: a
#: chain introduced after an Ethereum result is seen is a second look at the same question, and the
#: reader cannot tell it from a first look. Frozen before any measurement, it is a check on
#: generalisability; added afterwards, it is a rescue.
ARBITRUM_CLAUSES = (
    "does not participate in the main gate",
    "may not be used to rescue a weak Ethereum result",
    "does not permit thresholds to be changed after results are seen",
    "is reported only as a check on generalisability",
    "must be pre-registered as a secondary diagnostic, not introduced after Ethereum fails",
)

#: addendum §9.1, the three-part conjunction. All three, or the position is not dead. The
#: conjunction is stricter than the bare inactivity window the pre-registration asked for, and
#: deliberately: a pool can be quiet for thirty days and still be exitable, and a token can migrate
#: to a live pool.
DEAD_POOL_CLAUSES = (
    "no successful swap for 30 days",
    "executable exit value is below the minimum threshold",
    "no validated replacement pool exists",
)

#: §11.3, verbatim, character for character, and pinned as such in the tests. It is fixed *here*,
#: before any result exists, because the moment it is needed is the moment somebody would rather
#: write a softer one — and a sentence rewritten after the finding is a different finding.
NEGATIVE_RESULT_SENTENCE = (
    "No sufficient persistent and copyable wallet-selection edge was found for the Ethereum "
    "Mainnet target population and capital profile."
)


PARAMETERS = ParameterSet((
    # -- the four walk-forward windows (§6.3) --
    Parameter(
        "windows.walk_forward",
        (("2023-01", "2023-06", "2023-07", "2023-12"),
         ("2023-07", "2023-12", "2024-01", "2024-06"),
         ("2024-01", "2024-06", "2024-07", "2024-12"),
         ("2024-07", "2024-12", "2025-01", "2025-06")),
        WINDOWS, "§6.3",
        "(train_start, train_end, test_start, test_end), inclusive months. No information "
        "generated after T0 may be used in selecting wallets at T0.",
    ),
    Parameter("windows.count", 4, COUNT, "§6.3",
              "Four, and a report over three says which is absent rather than looking complete."),
    Parameter("windows.required_to_pass", 3, COUNT, "§7",
              "The project enters Phase 1 only if at least 3 of 4 windows pass."),

    # -- eligibility (§6.1, §6.2, addendum §7) --
    Parameter("eligibility.potential_buys.floor", 10, COUNT, "addendum §7",
              "Outer buffer, counted BEFORE balance netting. Netting removes rows, so a wallet "
              "with 22 potential buys can fall below 20 valid buys; filtering at the final "
              "threshold in the first pass would drop it invisibly."),
    Parameter("eligibility.potential_buys.ceiling", 1200, COUNT, "addendum §7",
              "Outer buffer, before netting."),
    Parameter("eligibility.valid_buys.floor", 20, COUNT, "§6.2",
              "Controls selection noise: admit 5-buy wallets and the top of the ranking is "
              "entirely 5-buy lucky wallets."),
    Parameter("eligibility.valid_buys.ceiling", 1000, COUNT, "§6.2",
              "Applied to valid buys, not total transactions — approvals and transfers inflate "
              "transaction counts. ~5.5/day over six months."),
    Parameter("universe.minimum_eligible_accounts", 10000, COUNT, "§6.1",
              "A window below this is INSUFFICIENT CANDIDATE UNIVERSE and is not valid. A "
              "replacement window may not be chosen afterwards from the same data unless the "
              "replacement rule was pre-registered."),

    # -- selection (§6.5) --
    Parameter("selection.rate_of_eligible_universe", "0.01", RATIO, "§6.5",
              "clamp(1% of eligible universe, 250, 1000). A percentage rather than a fixed count "
              "keeps selection pressure approximately constant across windows."),
    Parameter("selection.minimum", 250, COUNT, "§6.5", "The clamp's lower bound."),
    Parameter("selection.maximum", 1000, COUNT, "§6.5", "The clamp's upper bound."),

    # -- capital (§3.1, §7.2) --
    Parameter("capital.levels",
              ("100000", "250000", "500000", "1500000", "2000000"), USD_LEVELS, "§3.1",
              "Copyability is simulated at all five. The first three locate the capacity cliff; "
              "the last two are design_capital."),
    Parameter("capital.gating_levels", ("1500000", "2000000"), USD_LEVELS, "§7.2",
              "Follower-Adjusted Excess Buy Quality > 0 at both. Both levels, both positive."),

    # -- netting residual tolerance (addendum §8) --
    Parameter("netting.residual_tolerance.floor_usd", "0.01", USD, "addendum §8",
              "max($0.01, 0.01% of transaction notional). The fixed dollar floor handles dust on "
              "small trades; residuals above the tolerance go to the reconciliation queue, not to "
              "the primary metric and not to silence."),
    Parameter("netting.residual_tolerance.notional_rate", "0.0001", RATIO, "addendum §8",
              "0.01% of transaction notional — the other arm of the same max()."),

    # -- dead pools (§4.4 Case 3, addendum §9.1) --
    Parameter("dead_pool.conditions", DEAD_POOL_CLAUSES, CLAUSES, "addendum §9.1",
              "All three. Dead positions are valued at zero — not the last stale price, not a "
              "forward-filled one."),
    Parameter("dead_pool.inactivity_seconds", 2592000, SECONDS, "addendum §9.1",
              "Thirty days of UTC seconds, condition 1 of the conjunction. Half-open at the top: "
              "exactly 30 days of silence satisfies it."),
    Parameter("dead_pool.all_conditions_required", True, FLAG, "addendum §9.1",
              "A conjunction, never a disjunction. Any one condition alone zeroes positions that "
              "could actually be sold."),

    # -- token age buckets (§4.7) --
    Parameter("token_age.bucket_a.blocks", 10, BLOCKS, "§4.7",
              "Bucket A is the first 10 blocks, measured in blocks and not in elapsed time — "
              "'first 10 blocks' is the pre-registered wording."),
    Parameter("token_age.bucket_b.seconds", 3600, SECONDS, "§4.7",
              "Bucket B runs from block 10 through the end of hour 1."),
    Parameter("token_age.bucket_c.seconds", 86400, SECONDS, "§4.7",
              "Bucket C runs from hour 1 through the end of hour 24; D is older than that."),
    Parameter("token_age.first_hour_buckets", ("A", "B"), CLAUSES, "§4.7",
              "First-Hour Purchases = Bucket A + Bucket B. A is reported separately, but the gate "
              "condition applies to the whole first hour."),

    # -- gate thresholds (§7.1, §7.3, §8.3) --
    Parameter("gate.starting_mean_threshold", "0.15", RATIO, "§8.3",
              "15pp is the STARTING value, not a sacred number. §8.3 replaces it with the "
              "smallest threshold holding the null pass rate at or below 5%, and raising it is "
              "expected even though it makes the project harder to pass. Frozen as the starting "
              "point so that the calibrated one can be shown to have come from the null."),
    Parameter("gate.first_hour_edge_share_max", "0.40", RATIO, "§7.1",
              "Edge Origin, condition 3, as resolved in ticket 09: kept at 40% and demoted to a "
              "cheap backstop. Long-tail is excluded from Ethereum Phase 0 (addendum §9.5), which "
              "removes most of what it defended against; Gate 2 is now the primary defence. Kept "
              "rather than tightened because a new number would be intuition rather than "
              "measurement, and kept rather than dropped because the mid-cap first-hour case is "
              "real. Strictly greater than 40% fails; exactly 40% passes."),
    Parameter("gate.minimum_total_positive_edge", "0.05", RATIO, "§7.1",
              "The small-denominator guard, in buy-quality units — 0.05 is five percentage "
              "points. Below it the edge origin is unmeasurable, the status is INDETERMINATE and "
              "the window FAILS. INDETERMINATE is not a pass."),
    Parameter("gate.significance.null_percentile", "0.95", RATIO, "§7.3",
              "Each gate's result must exceed the 95th percentile of its own null. Carried as the "
              "fraction 0.95 rather than the integer 95 because that is the form the quantile is "
              "taken at, and a set that stored 95 would leave every reader dividing by 100."),
    Parameter("gate.significance.max_empirical_p", "0.05", RATIO, "§7.3",
              "Empirical p-value <= 0.05, for the leader and the follower-adjusted column alike."),

    # -- execution costs and fills (§4.5, addendum §9.4, §9.5) --
    Parameter("execution.cost_cap.major", "0.01", RATIO, "addendum §9.5",
              "Maximum total execution cost for major assets. Total means everything: DEX fee, "
              "gas, price impact, slippage and liquidity limitation — not price impact alone."),
    Parameter("execution.cost_cap.mid_cap", "0.02", RATIO, "addendum §9.5",
              "Maximum total execution cost for mid-cap assets."),
    Parameter("execution.long_tail_treatment", "EXCLUDED FROM ETHEREUM PHASE 0", TEXT, "addendum §9.5",
              "There is no long-tail cost cap because there is no long-tail trade: measured "
              "Ethereum long-tail capacity is $0 (§11.1). A missing cap must raise, never default."),
    Parameter("execution.minimum_fill_ratio", "0.90", RATIO, "addendum §9.4",
              "At least 90% order fill. A quote that can only be partly filled is not a fill, and "
              "the follower simulation may use no private RFQ or market-maker inventory."),

    # -- copy retention (addendum §9.3) --
    Parameter("copy_retention.display_floor", "0.02", RATIO, "addendum §9.3",
              "Copy Retention is displayed only when Raw Buy Quality >= 2 percentage points. "
              "Below it the denominator is small enough that the ratio is dominated by noise; the "
              "answer is N/A, which is a different statement from a low retention."),

    # -- measurement horizon (§4.4, §4.8) --
    Parameter("measurement.horizon_days", 30, DAYS, "§4.4",
              "Every valid buy's return is measured over the following 30 days."),
    Parameter("measurement.window_edge_extension_days", 30, DAYS, "§4.8",
              "Measurement may extend up to 30 days past the end of an evaluation window. No "
              "sample is dropped and no partial return is used, identically for every benchmark "
              "basket."),

    # -- §10's activity bands --
    #
    # Not a copy of the eligibility bounds, which is why they are frozen separately: §10 writes the
    # table out itself, as "20–99 / 100–499 / 500–1,000 valid buys". That the outer edges coincide
    # with §6.2's floor and ceiling is a relationship between two documents, and it is asserted as
    # one in the tests rather than encoded here by deriving one from the other — deriving would
    # make §10's table move whenever §6.2 moved, which §10 does not say.
    Parameter("reporting.activity_bands",
              (("20-99", 20, 99), ("100-499", 100, 499), ("500-1000", 500, 1000)), BANDS, "§10",
              "The sensitivity breakdown, by valid-buy count, inclusive at both ends. Frozen here "
              "because two packages need it and neither may import the other: universe/protocol.py "
              "is a leaf that may not import reporting, and before this it carried its own copy "
              "and said so — 'a known drift surface rather than presented as a design'. Both now "
              "read this."),

    # -- the external specialist review (§9.5) --
    Parameter("validation.complex_accounts_min", MIN_COMPLEX_ACCOUNTS, COUNT, "§9.5",
              "'At least 10-15 complex accounts are reviewed by an independent external "
              "specialist.' Read from phase0.validator for the import-cycle reason given in the "
              "seeds block below; the figure itself is §9.5's."),
    Parameter("validation.complex_accounts_max", MAX_COMPLEX_ACCOUNTS, COUNT, "§9.5",
              "The upper end of the same range. A review of ten accounts satisfies §9.5 and a "
              "review of sixteen is not more compliant — the range is what was pre-registered, so "
              "both ends are frozen rather than only the one the code happens to check."),

    # -- benchmarks (§6.6) --
    Parameter("benchmark.primary_matched_controls", 5, COUNT, "§6.6",
              "Five primary matched controls per selected wallet — the benchmark the gate is "
              "measured against, never the naive random basket."),
    Parameter("benchmark.robustness_controls", 5, COUNT, "§6.6",
              "Five additional robustness controls: reported, and unable to change the gate."),
    Parameter("benchmark.covariate_balance_smd_max", "0.10", RATIO, "§6.6",
              "Target balance: absolute standardised mean difference below 0.10 across the ten "
              "matching dimensions."),

    # -- the null (§8.2, §8.3) --
    Parameter("null.runs_per_window_per_column", 1000, COUNT, "§8.2",
              "The entire pipeline, 1,000 times per window per column, permuting the "
              "selected/control labels within each matched set. The null gate must be the full "
              "three-condition gate, or the 95th percentile belongs to a different experiment."),
    Parameter("null.pass_rate_target", "0.05", RATIO, "§8.3",
              "Final Mean Threshold = the smallest threshold at which the null pass rate is at or "
              "below 5%."),

    # -- seeds (§9.6, addendum §11) --
    #
    # Three entries here read their value out of ``phase0.seeds`` and ``phase0.runs`` rather than
    # stating it, which is the opposite direction from every other block in this table, and the
    # reason is an import cycle rather than a preference: ``parameters`` imports ``runs`` for
    # SEED_RULE and ``runs`` imports ``seeds`` for new_master_seed, so ``seeds`` cannot import
    # ``parameters`` back. Something has to be the single home for the width and the separator, and
    # since only one of the two modules *can* read the other, it is this one that reads.
    #
    # That is not a weaker guarantee, it is the same guarantee pointing the other way. There is one
    # literal, in the module that applies it; the frozen set quotes it; and the transcription in
    # tests/hand_computed/test_parameters.py writes 32 and "|" out by hand against addendum §11, so
    # editing seeds.py to widen the master seed still fails a test. What it is not is a route by
    # which a stage could change a frozen value at run time — ``seeds`` has no writer either.
    Parameter("seeds.policy", "one master seed, deterministic child seeds", TEXT, "addendum §11",
              "§9.6 puts the random-seed policy in the freeze manifest; the addendum fixes it. "
              "The policy is what the pre-registration fixes — a seed VALUE is not something "
              "either document names."),
    Parameter("seeds.derivation_rule", RunRecord.SEED_RULE, TEXT, "addendum §11",
              "Recorded verbatim, and read from RunRecord.SEED_RULE rather than retyped, so the "
              "sentence a reader re-derives a run's seeds from cannot drift from the sentence the "
              "run record carries."),
    Parameter("seeds.field_separator", FIELD_SEPARATOR, TEXT, "addendum §11",
              "The separator in the derivation message. Part of the frozen rule, not an "
              "implementation detail: a commit or purpose containing it would move the field "
              "boundary and two runs that must be separate experiments would draw one seed. Read "
              "from phase0.seeds for the reason derivation_rule is read from RunRecord — see the "
              "note there."),
    Parameter("seeds.master_seed_bytes", MASTER_SEED_BYTES, COUNT, "addendum §11",
              "Width of the master seed, in bytes. Read from phase0.seeds, not retyped: that "
              "module is where the width is actually applied, and a table that agreed with it "
              "only by coincidence is the drift this table exists to end."),
    Parameter(
        "seeds.master_seed", None, UNMINTED, "addendum §11",
        "NOT MINTED, and None here is a claim rather than a gap. Neither document names a seed "
        "value, and inventing one would be exactly the kind of number this table exists to keep "
        "out. What the pre-registration freezes is the policy and the derivation rule above; the "
        "VALUE is minted once per run by RunStore.open_run and recorded in that run's own record, "
        "where (master_seed, commit) replays every child seed exactly. A zero or an empty string "
        "here would say somebody chose one, which nobody has.",
    ),

    # -- scope, and the chain that is outside the gate (§3, §11.1, §11.2) --
    Parameter("scope.primary_chain", "Ethereum mainnet", TEXT, "§3",
              "Exclusive. Base has too few clean windows, Solana's trader attribution is "
              "unreliable, and Ethereum is measurably the least bot-concentrated (§11.1)."),
    Parameter("scope.arbitrum.standing", "SECONDARY DIAGNOSTIC — OUTSIDE THE GATE", TEXT, "§11.2",
              "Pre-registered NOW, before any Ethereum result exists. That timing is the whole "
              "content of the parameter."),
    Parameter("scope.arbitrum.participates_in_gate", False, FLAG, "§11.2",
              "Arbitrum does not participate in the main gate. There is no value of this flag "
              "that a later run may set, because there is no writer."),
    Parameter("scope.arbitrum.constraints", ARBITRUM_CLAUSES, CLAUSES, "§11.2",
              "The five clauses, each binding, in the document's own order."),

    # -- the wording of a negative result (§11.3) --
    Parameter("reporting.negative_result_wording", NEGATIVE_RESULT_SENTENCE, TEXT, "§11.3",
              "Fixed verbatim so the sentence cannot be rewritten once it is the one that has to "
              "be published. The scope — Ethereum Mainnet, this target population, this capital "
              "profile — is part of the finding."),
    Parameter("reporting.forbidden_negative_framing",
              "wallet-based copy trading does not work on any blockchain", TEXT, "§11.3",
              "Explicitly NOT available. Phase 0 says nothing about Base, Solana, or memecoin "
              "markets, and a negative result that claimed otherwise would be a finding nobody "
              "measured."),
))


#: Thresholds the machine genuinely needs and **neither document names**. Recorded here so the gap
#: is visible from the frozen set rather than only from the lane that had to invent a figure.
#:
#: One entry, and it is the second condition of the dead-pool conjunction. The pre-registration
#: (§4.4 Case 3) and the addendum (§9.1) both say "below the minimum threshold" without a number.
#: ``marking/pools.py`` pins ``MINIMUM_EXIT_VALUE_USD = Decimal("1.00")`` in the lane that applies
#: it and reports it as an open item. It is **not** a member of :data:`PARAMETERS`: a value with a
#: §-citation that the § does not contain would be a manufactured pre-registration, which is worse
#: than an admitted hole.
NOT_PREREGISTERED = {
    "marking.pools.MINIMUM_EXIT_VALUE_USD": (
        "Condition 2 of the addendum §9.1 dead-pool conjunction — 'executable exit value is below "
        "the minimum threshold'. No figure in either document. Pinned at $1.00 in "
        "marking/pools.py, on the argument that below a dollar the exit is worth less than any "
        "plausible gas cost. Freezing it here under a §-citation would invent one."
    ),
}


# -- the freeze -----------------------------------------------------------------

#: Marks a governance manifest as a ticket-11 freeze record, so :meth:`ParameterRegister.
#: freeze_record` reads back only manifests that were written as one. Without it, any manifest at
#: all would be read as a freeze record and a freeze performed through the looser ``phase0 freeze``
#: path would appear to carry a commit and a date it never had.
FREEZE_MANIFEST_KIND = "phase0.parameters.freeze"

#: Nobody has frozen the parameter set. This is what a fresh register says, and what this
#: repository's register says today.
NOT_FROZEN = "NOT FROZEN"

#: Frozen, with a ticket-11 record naming the person, the commit and the date.
FROZEN = "FROZEN"

#: Governance has reached ``PARAMETERS_FROZEN`` and no ticket-11 record accompanies it. A **carried
#: status, not an error** — the state machine was advanced through the older, looser ``phase0
#: freeze PARAMETERS_FROZEN`` path, which requires a requester and neither a commit nor a date. The
#: parameters are frozen and every write to them is refused; what is missing is the evidence a
#: reader needs to check *which* text was frozen. Reported rather than raised, because raising here
#: would turn a documentation gap into a broken run.
FROZEN_WITHOUT_A_RECORD = "FROZEN WITHOUT A TICKET-11 RECORD"

FREEZE_STATUSES = (NOT_FROZEN, FROZEN, FROZEN_WITHOUT_A_RECORD)

ACTION_FREEZE = "parameters.freeze"
ACTION_CHANGE_REFUSED = "parameters.change_refused"

_HEX = frozenset("0123456789abcdef")

#: A short SHA-1 is 7 characters; a full one is 40; a SHA-256 object name is 64. Anything shorter
#: than 7 is ambiguous in a repository of any size, and ambiguity in the one field that says which
#: text was frozen defeats the field.
COMMIT_MIN_LENGTH = 7
COMMIT_MAX_LENGTH = 64

#: Refused as commits because they move. A freeze recorded at ``HEAD`` names whatever HEAD happens
#: to be when somebody looks, which is not a record of anything.
_MOVING_REFERENCES = frozenset({"head", "main", "master", "latest", "tip", "current", "working"})


def _person(value, what):
    """A person's identifier, or a refusal. No default, and placeholders are refused.

    Shares :func:`phase0.validator.why_not_a_name` with the ticket-02 register — the predicate
    rather than the word list, so the two records cannot come to disagree about what a name is even
    as the rules grow.

    **This is where the real one got through.** The first freeze performed against this repository
    recorded ``<نام شما>`` as the person, pasted out of a command template whose placeholder was
    never replaced. Every spelling in ``NON_NAMES`` is English, so nothing objected, and the
    register then reported the pre-registration frozen by a name attributable to nobody — under a
    real commit and a real date, which is what makes it worse than an obvious blank. The bracket
    rule that now catches it does not read the contents at all.

    The limitation is unchanged and worth restating here rather than only in ``validator``: a
    name-shaped string is accepted whatever it says. What bounds the deliberate case is the
    hash-chained audit entry this name is written into.
    """
    text = "" if value is None else str(value).strip()
    refusal = why_not_a_name(value)
    if refusal is not None:
        raise ValueError(
            "{} must be a name, got {!r}: {}. Freezing the pre-registration is a human act — "
            "§17's sign-off block has a line for the person and this record has the same line. "
            "There is no default requester in this module and no code path that supplies one: a "
            "freeze attributable to nobody is a freeze nobody can be asked about.".format(
                what, value, refusal)
        )
    return text


def _commit(value):
    """A commit hash, or a refusal naming why a moving reference is not one."""
    text = "" if value is None else str(value).strip().lower()
    if text in _MOVING_REFERENCES:
        raise ValueError(
            "the freeze commit must be a hash, got {!r}. A branch name or HEAD moves, so a freeze "
            "recorded at one names whatever it happens to point at when somebody looks — which "
            "is not a record of which text was frozen, and that record is the entire point of "
            "§17's 'Frozen at commit' line.".format(value)
        )
    if not (COMMIT_MIN_LENGTH <= len(text) <= COMMIT_MAX_LENGTH) or not set(text) <= _HEX:
        raise ValueError(
            "the freeze commit must be {}-{} hexadecimal characters, got {!r}. Shorter than {} is "
            "ambiguous in a repository of any size, and the one field that says which text was "
            "frozen may not be ambiguous.".format(
                COMMIT_MIN_LENGTH, COMMIT_MAX_LENGTH, value, COMMIT_MIN_LENGTH)
        )
    return text


def _date(value, what):
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.date.fromisoformat(value.strip())
        except ValueError:
            raise ValueError("{} must be an ISO date (YYYY-MM-DD), got {!r}".format(what, value))
    raise ValueError(
        "{} is required and must be a date or an ISO YYYY-MM-DD string, got {!r}. §17 records the "
        "date the pre-registration was frozen, and 'before the result was seen' is a claim about "
        "time that needs one.".format(what, value)
    )


class FreezeRecord(object):
    """Who froze the pre-registration, at which commit, on what date.

    Every field is required and none has a default. That is the whole of the class's contribution:
    it is impossible to construct one without naming a person, so it is impossible to reach
    ``PARAMETERS_FROZEN`` through :meth:`ParameterRegister.freeze` without one.

    :param requester: the person. Placeholders are refused; see :func:`_person`.
    :param commit: the commit the pre-registration is frozen at. A hash, never a branch name.
    :param frozen_on: the date, ISO ``YYYY-MM-DD`` or a ``datetime.date``.
    :param note: free text — what was frozen, or which review preceded it.

    **What it establishes and what it does not.** It establishes that a named person, on a named
    date, asserted a freeze at a named commit, and it puts all three in the hash-chained audit log
    where a later reader can find them. It does not establish that the commit exists, that the
    person is real, that they were entitled to freeze anything, or that the document at that commit
    is the one they read — nothing in ``phase0`` can reach a repository or a person. It converts a
    claim into an *attributable* claim, which is the most a record can do.
    """

    __slots__ = ("requester", "commit", "frozen_on", "note")

    def __init__(self, requester, commit, frozen_on, note=""):
        self.requester = _person(requester, "the person freezing the pre-registration")
        self.commit = _commit(commit)
        self.frozen_on = _date(frozen_on, "the freeze date")
        self.note = str(note or "")

    def as_dict(self):
        return {
            "kind": FREEZE_MANIFEST_KIND,
            "requester": self.requester,
            "commit": self.commit,
            "frozen_on": self.frozen_on.isoformat(),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(requester=data["requester"], commit=data["commit"],
                   frozen_on=data["frozen_on"], note=data.get("note", ""))

    def __repr__(self):
        return "<FreezeRecord {} at {} on {}>".format(
            self.requester, self.commit, self.frozen_on.isoformat())


class ParameterRegister(object):
    """The frozen set bound to the governance machine, and the refusal that closes it.

    :param governance: the :class:`~phase0.governance.GovernanceMachine`. Frozen-ness is **read**
        from it rather than stored here, so there is no second flag that could disagree with the
        state machine about whether the parameters are frozen.
    :param audit: the :class:`~phase0.audit.AuditLog` the machine writes to. Required — a rejected
        parameter change that left no record is the failure this class exists to prevent, so there
        is no register without a log to write to.
    :param parameters: the :class:`ParameterSet`. Defaults to :data:`PARAMETERS`, which is the
        authoritative one; the argument exists so a test can exercise the machinery over a small
        table rather than so a run can substitute a different set.

    Reading is always permitted. Writing is never permitted — not before the freeze and not after —
    and the two refusals are different exceptions because they cost different things:
    :class:`~phase0.errors.ParameterSetNotWritable` before, :class:`~phase0.errors.FrozenError`
    after.
    """

    def __init__(self, governance, audit, parameters=PARAMETERS):
        self._governance = governance
        if audit is None:
            raise ValueError(
                "a ParameterRegister needs an audit log. Ticket 11's requirement is that a "
                "rejected change is rejected WITH an audit record naming the requester; a "
                "register that could refuse silently would satisfy the sentence and not the point."
            )
        self._audit = audit
        self._parameters = parameters

    # -- reading ---------------------------------------------------------------

    @property
    def parameters(self):
        return self._parameters

    def value(self, key):
        """The frozen value of one parameter. Readable in every state."""
        return self._parameters.value(key)

    @property
    def frozen(self):
        """Has the parameter set been closed? Read from governance, never stored twice."""
        return position(self._governance.state) >= position(PARAMETERS_FROZEN)

    def freeze_record(self):
        """The ticket-11 :class:`FreezeRecord`, or ``None`` if no freeze carried one.

        Read back out of the audit log rather than out of a file this class writes, so the record
        a reader is shown is the hash-chained one: altering it breaks the chain at that entry and
        :meth:`~phase0.audit.AuditLog.verify` says where.

        ``None`` is a carried status with two causes and they are distinguished by
        :meth:`freeze_status`: nobody has frozen anything, or somebody froze through the older
        ``phase0 freeze PARAMETERS_FROZEN`` path, which names a requester and neither a commit nor
        a date.
        """
        found = None
        for entry in self._audit.entries():
            if entry.action != "governance.transition":
                continue
            detail = entry.detail or {}
            if detail.get("to") != PARAMETERS_FROZEN:
                continue
            manifest = (detail.get("detail") or {}).get("manifest") or {}
            if manifest.get("kind") == FREEZE_MANIFEST_KIND:
                found = manifest
        return None if found is None else FreezeRecord.from_dict(found)

    def freeze_status(self):
        """One of :data:`FREEZE_STATUSES`. Never raises; this is a report, not a gate."""
        if not self.frozen:
            return NOT_FROZEN
        return FROZEN if self.freeze_record() is not None else FROZEN_WITHOUT_A_RECORD

    def report(self):
        """Lines for the status command: the freeze status, and the record if there is one."""
        status = self.freeze_status()
        lines = ["{:<28} {}".format("parameter set", status),
                 "{:<28} {} parameters, {} unfrozen threshold(s) named in NOT_PREREGISTERED".format(
                     "contents", len(self._parameters), len(NOT_PREREGISTERED))]
        record = self.freeze_record()
        if record is not None:
            lines.append("{:<28} {}".format("frozen by", record.requester))
            lines.append("{:<28} {}".format("frozen at commit", record.commit))
            lines.append("{:<28} {}".format("frozen on", record.frozen_on.isoformat()))
            if record.note:
                lines.append("{:<28} {}".format("note", record.note))
        elif status == FROZEN_WITHOUT_A_RECORD:
            lines.append(
                "{:<28} governance reads {} but no ticket-11 record accompanies it, so the "
                "commit and the date the pre-registration was frozen at are not on record. "
                "Every write is still refused.".format("note", PARAMETERS_FROZEN))
        else:
            lines.append(
                "{:<28} NOT FROZEN is not a state this code can leave on its own. Freezing is a "
                "human act: a person builds a FreezeRecord naming themselves, the commit and the "
                "date. There is no default requester anywhere in this module.".format("note"))
        return lines

    # -- the human act ---------------------------------------------------------

    def freeze(self, record):
        """Record the ticket-11 freeze. **Called by a person, never by a stage.**

        :param record: a :class:`FreezeRecord`. There is no other signature — no ``requester=``
            string, no ``commit=None``, and no form of this method that invents any field. The
            record cannot exist without a person's name, so neither can the transition.
        :returns: the new governance state.
        :raises TypeError: anything other than a :class:`FreezeRecord`.

        It delegates to :meth:`~phase0.governance.GovernanceMachine.freeze_parameters`, which
        applies the ordering rules and writes the transition to the audit log. This method adds the
        commit and the date; it removes nothing and relaxes nothing, and in particular it cannot
        reach ``PARAMETERS_FROZEN`` from any state governance would refuse.
        """
        if not isinstance(record, FreezeRecord):
            raise TypeError(
                "freeze takes a FreezeRecord, got {}. §17's sign-off block records a person, a "
                "date and a commit; a method that accepted a bare requester would have to default "
                "the other two, and a freeze whose commit was defaulted names no text at "
                "all.".format(type(record).__name__)
            )
        state = self._governance.freeze_parameters(record.requester, manifest=record.as_dict())
        self._audit.append(record.requester, ACTION_FREEZE, {
            "commit": record.commit,
            "frozen_on": record.frozen_on.isoformat(),
            "note": record.note,
            "parameters": len(self._parameters),
        })
        return state

    # -- the refusal -----------------------------------------------------------

    def request_change(self, key, proposed_value, requester, reason=None):
        """Ask to change a parameter. Always refused, and always recorded.

        :param key: a key of the set. An unknown one raises :class:`UnknownParameter` **without**
            writing an audit entry — that is a caller with a typo, not somebody trying to move a
            threshold, and logging it as an attempted change would put noise in the one record
            that has to stay legible.
        :param proposed_value: what the caller wants it to become. Recorded verbatim in the audit
            entry, because *what* somebody wanted to change it to is the interesting part.
        :param requester: who asked. Required, placeholders refused, and written into the audit
            entry — this is the "naming the requester" half of ticket 11's demo.
        :param reason: free text, recorded.
        :raises FrozenError: once the set is frozen.
        :raises ParameterSetNotWritable: before it is.

        The refusal is unconditional on the *content* of the change. A widening, a clarification,
        a correction of an obvious typo in a threshold: all refused, because a reader six months
        later cannot tell a clarification from a result-driven change, and neither can this
        method.
        """
        requester = _person(requester, "the requester of a parameter change")
        parameter = self._parameters.parameter(key)  # raises UnknownParameter, writes nothing
        frozen = self.frozen
        record = self.freeze_record()
        entry = self._audit.append(requester, ACTION_CHANGE_REFUSED, {
            "key": parameter.key,
            "source": parameter.source,
            "current_value": plain(parameter.value),
            "proposed_value": plain(proposed_value),
            "reason": str(reason or "no reason given"),
            "outcome": "REJECTED",
            "freeze_status": self.freeze_status(),
            "freeze_record": None if record is None else record.as_dict(),
        })

        if frozen:
            where = (
                "frozen at commit {} on {} by {}".format(
                    record.commit, record.frozen_on.isoformat(), record.requester)
                if record is not None else
                "frozen, though no ticket-11 record names the commit or the date"
            )
            raise FrozenError(
                "Parameter {!r} is frozen; refusing to change it from {!r} to {!r}. Requested by "
                "{}: {}. The pre-registration is {} ({}). §17: no threshold, definition, "
                "parameter, window or rule may change on the basis of an observed result — and "
                "this applies to clarifications and widenings as well as to changes, because the "
                "reader cannot tell one from the other and neither can this method. What it costs "
                "to proceed anyway is §9.7 and not an edit: the run is INVALIDATED, the bug or the "
                "document is fixed, a new code version is registered, the ENTIRE validation gate "
                "is re-run, the null distribution is rebuilt from scratch and the main test is "
                "re-run — and selectively using the old or the new result is prohibited. This "
                "refusal is audit entry #{} naming {}.".format(
                    parameter.key, plain(parameter.value), plain(proposed_value),
                    requester, str(reason or "no reason given"), where, parameter.source,
                    entry.seq, requester)
            )

        raise ParameterSetNotWritable(
            "Parameter {!r} is not writable through this register; refusing to change it from "
            "{!r} to {!r}. Requested by {}: {}. The set is NOT FROZEN — that part is true and is "
            "not the reason. The reason is that this register is not the parameter set's editor: "
            "the values come from {} in docs/, and one changes by editing the document and "
            "phase0/parameters.py together, in one commit, reviewed, BEFORE anybody freezes. "
            "After the freeze the same request costs a full invalidation under §9.7. This refusal "
            "is audit entry #{} naming {}.".format(
                parameter.key, plain(parameter.value), plain(proposed_value),
                requester, str(reason or "no reason given"), parameter.source,
                entry.seq, requester)
        )
