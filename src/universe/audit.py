"""The look-ahead audit — run-time evidence that the compile-time barrier held for **this** run.

Tickets 27 and 28 both ask for it: *a look-ahead audit runs over the frozen universe and reports
zero post-T0 inputs reaching any selection path*, covering *post-T0 activity, forward returns, and
any vendor field whose value is recomputed over time.*

This module deliberately does **not** import the module it audits. It walks the object graph of the
three selection inputs and refuses any value whose ``type(v).__module__`` is the string
``'universe.forward'`` — compared as a string, so the auditor never executes what it judges. That is
the same asymmetry that makes ``gate_validation`` an arbiter: a checker that can call the code it
checks can inherit its bug and then certify it.

Read this report correctly
---------------------------

``post_t0_values_found == 0`` is **near-tautological** and must not be quoted as a finding. Every
such value would have raised at construction — a post-T0 stamp cannot be put on an observation or a
score at all — so a zero here is what a working type system looks like, not evidence that anyone
was careful.

The fields a reviewer actually reads are :attr:`LookAheadAudit.latest_input_block`,
:attr:`LookAheadAudit.latest_input_timestamp` and :attr:`LookAheadAudit.earliest_gap_blocks` —
re-derived from stored fields rather than trusting that a constructor ran — and
:attr:`LookAheadAudit.undeclared_input_classes`, which goes non-empty the moment somebody adds an
input type nobody audited.

A failed audit **raises**. :class:`LookAheadAudit` refuses to be constructed with a failed check, so
"zero post-T0 inputs reached any selection path" is a refusal to publish anything else rather than a
field somebody set.

What it does not cover: the warehouse query upstream of every record here, and any post-T0 figure a
composition root computes from its own raw data without ever touching this package.
"""

from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Tuple

from contracts import ContractError, LookAheadViolation

from .freeze import FrozenUniverse
from .observation import VendorMutability
from .ranking import SELECTION_INPUT_CLASSES, RankingInputs
from .select import SelectedBasket

#: Compared as a **string**. Importing the module in order to check for it would make the auditor a
#: consumer of exactly what it audits, and would put the post-T0 vocabulary in this module's
#: namespace — where ``tests/test_post_t0_barrier.py`` would then find it, correctly.
POST_T0_MODULE = "universe.forward"

BARRIER_STATEMENT = (
    "Values produced after the selection instant live in a separate module with in-degree zero "
    "inside this package; no module on the selection path imports it, names any of its types, or "
    "can be handed one of its values without raising."
)


class PostT0ValueFound(LookAheadViolation):
    """A value from the post-T0 module was reachable from a selection input."""


class UndeclaredSelectionInput(ContractError):
    """A record type nobody declared was reachable on the selection path.

    The run-time complement to the AST rule. A new input type added later is not in
    :data:`~universe.ranking.SELECTION_INPUT_CLASSES`, so the audit fails until somebody declares it
    — which is the moment to ask what its provenance is.
    """


@dataclass(frozen=True)
class AuditCheck:
    """One named check, whether it held, and the sentence it is a check of."""

    name: str
    passed: bool
    statement: str

    def __post_init__(self) -> None:
        if not self.name or not self.statement:
            raise ValueError("an audit check must name itself and state what it checked")
        if not isinstance(self.passed, bool):
            raise TypeError("AuditCheck.passed must be a bool")


@dataclass(frozen=True)
class LookAheadAudit:
    """The audit report, which cannot exist for a run that failed it."""

    window_key: str
    snapshot_id: str
    t0_block: int
    t0_timestamp: int
    scores_checked: int
    values_inspected: int
    post_t0_values_found: int
    latest_input_block: int
    latest_input_timestamp: int
    earliest_gap_blocks: int
    input_classes_examined: Tuple[str, ...]
    undeclared_input_classes: Tuple[str, ...]
    barrier_statement: str
    checks: Tuple[AuditCheck, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", tuple(self.checks))
        object.__setattr__(self, "input_classes_examined", tuple(self.input_classes_examined))
        object.__setattr__(self, "undeclared_input_classes", tuple(self.undeclared_input_classes))
        failed = [check for check in self.checks if not check.passed]
        if failed:
            raise LookAheadViolation(
                "the look-ahead audit failed {} check(s) and will not be published as a report: "
                "{}. A failed audit is not a finding to carry beside a result — the result it "
                "would sit beside is void.".format(
                    len(failed), "; ".join("{}: {}".format(c.name, c.statement) for c in failed))
            )
        if self.post_t0_values_found != 0:
            raise PostT0ValueFound(
                "{} post-T0 value(s) were reachable from a selection input".format(
                    self.post_t0_values_found)
            )
        if self.undeclared_input_classes:
            raise UndeclaredSelectionInput(
                "record type(s) reachable on the selection path that nobody declared: {}. Add them "
                "to universe.ranking.SELECTION_INPUT_CLASSES once their provenance has been "
                "checked — the point of the refusal is that somebody has to look.".format(
                    ", ".join(self.undeclared_input_classes))
            )
        if not self.checks:
            raise ValueError(
                "an audit with no checks reports nothing and would read as a pass; every check in "
                "an empty list holds"
            )

    @property
    def statement(self) -> str:
        return (
            "{} score(s) checked against T0 block {}; the closest any input got to T0 was {} "
            "block(s). Read post_t0_values_found=0 as a working type system rather than as "
            "evidence.".format(self.scores_checked, self.t0_block, self.earliest_gap_blocks)
        )


def _walk(value, seen, on_value, path=""):
    """Depth-first over dataclasses, tuples, lists, dicts and sets, visiting every value once.

    ``path`` is the dotted field path the value was reached by, and it is threaded through because
    the audit's block figures used to be computed from ``inputs.scores`` alone while the walk
    covered thousands of values — so the headline number did not describe the thing it had walked.
    A block height is only a block height because of the field it sits in; there is nothing about
    the integer 17,599,999 that says so.
    """
    if id(value) in seen:
        return
    seen.add(id(value))
    on_value(value, path)
    if isinstance(value, (str, bytes, int, float, Decimal, Enum)) or value is None:
        return
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            _walk(getattr(value, field.name), seen, on_value,
                  "{}.{}".format(path, field.name) if path else field.name)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _walk(key, seen, on_value, "{}[key]".format(path))
            _walk(item, seen, on_value, "{}[]".format(path))
        return
    if isinstance(value, (tuple, list, set, frozenset)):
        for item in value:
            _walk(item, seen, on_value, "{}[]".format(path))
        return


#: Field names that are **declared** post-T0 by design rather than measured after T0.
#:
#: A training window states the calendar of its own forward period; those two numbers are after T0
#: by definition and are constants of the design rather than measurements of anything. They are
#: reachable from the frozen universe, so the block sweep below would otherwise report them as
#: post-T0 inputs — and silently skipping them is how a sweep comes to prove nothing. Naming them
#: here means the audit reports them explicitly as declared, and means any *other* post-T0 block
#: reachable from a selection input fails check seven.
#:
#: Matched on the **leaf** field name, so a window reached by any path is covered and a field of the
#: same name somewhere else would be covered too — which is the conservative direction to be wrong
#: in only because both names exist on exactly one type. ``tests/hand_computed/test_containment.py``
#: pins that.
DECLARED_POST_T0_CALENDAR = ("forward_end_block", "forward_end_ts")


def _clock_kind(path):
    """``"block"``, ``"timestamp"`` or ``None`` for a dotted field path.

    A block height is only a block height because of the field it sits in; there is nothing about
    the integer 17,599,999 that says so. This is the whole of the classification, written once.
    """
    leaf = path.rsplit("[]", 1)[-1].lstrip(".").rsplit(".", 1)[-1]
    if leaf.endswith("_ts") or leaf.endswith("timestamp"):
        return "timestamp"
    if leaf.endswith("block"):
        return "block"
    return None


def _leaf(path):
    return path.rsplit("[]", 1)[-1].lstrip(".").rsplit(".", 1)[-1]


def _is_input_record(value):
    """A record that declares its own provenance is an input whose provenance somebody must own.

    Deliberately structural rather than a hardcoded list of types. Every selection record in this
    package carries a ``provenance`` field, and nothing else does — so a new input type added later
    is recognised as one without this module being edited, and is then refused until it is declared.
    """
    return (is_dataclass(value) and not isinstance(value, type)
            and any(f.name == "provenance" for f in fields(value)))


def look_ahead_audit(
    universe: FrozenUniverse,
    inputs: RankingInputs,
    basket: SelectedBasket,
) -> LookAheadAudit:
    """Walk the three selection inputs and refuse anything that should not be reachable from them.

    :param universe: the frozen :class:`~universe.freeze.FrozenUniverse`.
    :param inputs: the :class:`~universe.ranking.RankingInputs` the basket was ranked on.
    :param basket: the :class:`~universe.select.SelectedBasket`.

    Six checks, and only the first is near-tautological:

    1. no value from the post-T0 module is reachable from any of the three;
    2. every score's provenance is ``POINT_IN_TIME``, **re-derived from the stored field** rather
       than trusted because a constructor ran;
    3. every score's stamps are strictly before T0, likewise re-derived;
    4. the snapshot identifier the basket pins is the one the universe computes now;
    5. the scored population was not narrowed — scores plus stated absences equal the membership;
    6. the basket is a subset of the frozen membership.
    """
    if not isinstance(universe, FrozenUniverse):
        raise TypeError("look_ahead_audit needs a FrozenUniverse")
    if not isinstance(inputs, RankingInputs):
        raise TypeError("look_ahead_audit needs RankingInputs")
    if not isinstance(basket, SelectedBasket):
        raise TypeError("look_ahead_audit needs a SelectedBasket")

    t0 = universe.window.t0
    inspected = []
    post_t0 = []
    record_types = {}
    #: Every block height the walk reached, as ``(path, block)``. This is what the reported figures
    #: are derived from, so ``latest_input_block`` describes the walk rather than a subset of it.
    walked_blocks = []
    undeclared_post_t0_blocks = []

    def visit(value, path):
        inspected.append(1)
        if type(value).__module__ == POST_T0_MODULE:
            post_t0.append(type(value).__name__)
        if _is_input_record(value):
            record_types[type(value).__name__] = type(value)
        kind = _clock_kind(path) if type(value) is int and not isinstance(value, bool) else None
        if kind is not None:
            walked_blocks.append((path, kind, value))
            limit = t0.block if kind == "block" else t0.timestamp
            if value > limit and _leaf(path) not in DECLARED_POST_T0_CALENDAR:
                undeclared_post_t0_blocks.append("{}={}".format(path, value))

    seen = set()
    for root in (universe, inputs, basket):
        _walk(root, seen, visit)

    if post_t0:
        raise PostT0ValueFound(
            "value(s) of type {} from {} are reachable from a selection input. §6.4: post-T0 "
            "activity is reported as an output, never used as a selection filter — and a value "
            "that can be *reached* from the ranking inputs is one a future edit can read.".format(
                ", ".join(sorted(set(post_t0))), POST_T0_MODULE)
        )

    declared = {cls.__name__ for cls in SELECTION_INPUT_CLASSES}
    undeclared = tuple(sorted(name for name in record_types if name not in declared))

    latest_block = 0
    latest_timestamp = 0
    gaps = []
    mutable = []
    late = []
    for score in inputs.scores:
        if score.provenance is not VendorMutability.POINT_IN_TIME:
            mutable.append(score.wallet)
        if score.as_of_block >= t0.block or score.as_of_timestamp >= t0.timestamp:
            late.append(score.wallet)
        gaps.append(t0.block - score.as_of_block)

    # Derived from the walk, not from ``inputs.scores``. The two disagreed: the walk covered every
    # value reachable from all three roots and the reported figure described a subset of one of
    # them, so a reader comparing ``values_inspected`` against ``latest_input_block`` was comparing
    # two different populations — and the two ``forward_end_*`` constants sat inside the walk with
    # nothing said about them. Declared calendar and the T0 boundary itself are excluded, because
    # neither is an input measurement and including either would make the figure read as though
    # something had been measured at T0.
    for path, kind, clock in walked_blocks:
        if _leaf(path) in DECLARED_POST_T0_CALENDAR:
            continue
        if kind == "block":
            if clock < t0.block:
                latest_block = max(latest_block, clock)
        elif clock < t0.timestamp:
            latest_timestamp = max(latest_timestamp, clock)

    checks = (
        AuditCheck(
            name="no_post_t0_types_on_the_selection_path",
            passed=not post_t0,
            statement=(
                "No value whose type is defined in {} is reachable from the frozen universe, the "
                "ranking inputs or the basket. Near-tautological: such a value could not have been "
                "constructed. Read the block figures instead.".format(POST_T0_MODULE)
            ),
        ),
        AuditCheck(
            name="every_score_is_point_in_time",
            passed=not mutable,
            statement=(
                "Every ranking score is stamped {}, re-derived from the stored field. A vendor "
                "field whose source recomputes it has no knowable value at T0.".format(
                    VendorMutability.POINT_IN_TIME.value)
            ),
        ),
        AuditCheck(
            name="every_score_is_strictly_before_t0",
            passed=not late,
            statement=(
                "Every ranking score's block and second are strictly before T0 (block {}, second "
                "{}), re-derived rather than trusted because a constructor ran.".format(
                    t0.block, t0.timestamp)
            ),
        ),
        AuditCheck(
            name="snapshot_identifier_is_the_one_the_universe_computes",
            passed=basket.snapshot_id == universe.snapshot_id,
            statement=(
                "The basket pins the snapshot identifier this universe hashes to now, so a "
                "membership edited after selection would be visible here."
            ),
        ),
        AuditCheck(
            name="the_scored_population_was_not_narrowed",
            passed=inputs.covered == len(universe.members),
            statement=(
                "Scores plus stated absences cover the frozen membership exactly. A missing score "
                "would shrink the ranked population silently, and score computation fails for "
                "wallets whose buys all priced at zero — which correlates with going quiet."
            ),
        ),
        AuditCheck(
            name="the_basket_is_a_subset_of_the_frozen_membership",
            passed=set(basket.wallets) <= set(universe.wallets),
            statement=(
                "Every selected wallet is a member of the universe frozen at T0 (§6.4)."
            ),
        ),
        AuditCheck(
            name="every_walked_block_is_before_t0_or_declared",
            passed=not undeclared_post_t0_blocks,
            statement=(
                "Every one of the {} block heights and second stamps reachable from the frozen "
                "universe, the ranking inputs and the basket is at or before T0 (block {}, second "
                "{}), except the declared forward calendar {} — which a training window states "
                "about itself and which measures nothing. Check 1 is near-tautological because a "
                "post-T0 *type* could not be constructed; this one is not, because a bare int "
                "carries no type at all and is exactly what a post-T0 measurement looks like by "
                "the time it reaches a selection record.{}".format(
                    len(walked_blocks), t0.block, t0.timestamp,
                    " and ".join(DECLARED_POST_T0_CALENDAR),
                    "" if not undeclared_post_t0_blocks else " Found: {}.".format(
                        ", ".join(sorted(undeclared_post_t0_blocks))))
            ),
        ),
    )

    return LookAheadAudit(
        window_key=universe.window.key.value,
        snapshot_id=universe.snapshot_id,
        t0_block=t0.block,
        t0_timestamp=t0.timestamp,
        scores_checked=len(inputs.scores),
        values_inspected=len(inspected),
        post_t0_values_found=len(post_t0),
        latest_input_block=latest_block,
        latest_input_timestamp=latest_timestamp,
        earliest_gap_blocks=min(gaps) if gaps else 0,
        input_classes_examined=tuple(sorted(record_types)),
        undeclared_input_classes=undeclared,
        barrier_statement=BARRIER_STATEMENT,
        checks=checks,
    )
