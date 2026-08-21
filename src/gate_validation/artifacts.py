"""Reading results as data: schema, envelopes, exact fields, tolerances, ordering, coverage.

Everything in this module takes an **already-parsed mapping** and returns a report. It reads no
files, imports no pipeline module, and calls nothing that produced the numbers it inspects. That is
not fastidiousness: an arbiter that can execute the code it judges inherits that code's bug and then
certifies it, and the null distribution cannot save you — the null is computed by the same code, so
a wrong FIFO rule moves the selected basket and all 1,000 permutations identically and shows up as
nothing at all.

The checks answer six separable questions, and they are separate because a single "is this artifact
ok" boolean cannot tell a reviewer which of them failed:

    schema validity          does the artifact even have the shape it claims?
    envelope integrity       does the payload still hash to what the writer recorded?
    exact fields (§9.2)      do the deterministic fields match to the raw unit, with no tolerance?
    numeric fields (§9.2)    do the priced fields match inside their stated tolerance?
    ordering (§9.1, §8.4)    did the stages happen in the binding order?
    coverage (§9.4, §9.8)    was every required condition actually measured, and did it hold?

Two rules run through all of them.

**An unreported condition is a failure, never a pass.** The tempting default — skip a field that is
absent — turns "we did not measure independent review" into "independent review is fine", which is
the exact shape of the bug the validation gate exists to catch.

**A JSON number where a Decimal belongs is a schema violation.** Nearly every consumer parses a JSON
number as a double, which reintroduces the float this project's whole seam design avoids. By the
time such a value reaches a comparison the precision is already gone, so it is rejected at the door
rather than reconciled later.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Optional, Tuple

from contracts import (
    CALCULATION_CONTEXT,
    ENUM_SCHEMA_VERSION,
    DerivedFieldMismatch,
    calc,
    canonical_hash,
    canonicalise,
    divide,
    verify_redundant_derived,
)

# -- discrepancy kinds ----------------------------------------------------------
# Named rather than free text so a caller can filter a report without parsing prose.

MISSING = "missing"
MISMATCH = "mismatch"
UNPINNED = "unpinned"
SCHEMA = "schema"
TOLERANCE = "tolerance"
OUT_OF_ORDER = "out_of_order"
DERIVED = "derived"
PREREQUISITE = "prerequisite"


@dataclass(frozen=True)
class Discrepancy:
    """One thing that is wrong, with enough context to reproduce the judgement.

    ``expected`` and ``observed`` are text because an artifact is text by the time the arbiter sees
    it. Storing them as Decimals would mean re-deciding, here, what the artifact's string meant —
    which is precisely the interpretation the arbiter is not allowed to perform on the builder's
    behalf.
    """

    kind: str
    field: str
    detail: str
    expected: Optional[str] = None
    observed: Optional[str] = None

    def __str__(self):
        text = "{}: {}".format(self.field, self.detail)
        if self.expected is not None or self.observed is not None:
            text += " (expected {!r}, observed {!r})".format(self.expected, self.observed)
        return text


@dataclass(frozen=True)
class CheckReport:
    """The result of one check. Empty means clean; there is no third state.

    Reports accumulate rather than short-circuit. A reviewer fixing artifacts needs the whole list,
    and stopping at the first problem would make the number of review rounds equal to the number of
    problems.
    """

    what: str
    discrepancies: Tuple[Discrepancy, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "discrepancies", tuple(self.discrepancies))

    @property
    def ok(self):
        return not self.discrepancies

    @property
    def messages(self):
        return [str(d) for d in self.discrepancies]


# -- reading a scalar out of an artifact ----------------------------------------


def _comparable(value):
    """Canonical text for a parsed artifact value, or the reason it cannot have one.

    A float never gets a canonical form here. ``contracts.canonicalise`` would raise on it, and an
    exception thrown mid-report would hide every later finding behind the first one.
    """
    if isinstance(value, float):
        return None, (
            "serialized as a JSON number ({!r}); JSON numbers are parsed as doubles by nearly "
            "every consumer, which reintroduces the float the seam exists to keep out".format(value)
        )
    try:
        return canonicalise(value), None
    except (TypeError, ValueError) as exc:
        return None, str(exc)


def _mapping(value, what):
    """Accept an already-parsed dict, or a dataclass reduced through the seam's own canonical form.

    Deliberately not a file path. The caller reads the file; this module stays pure, which is what
    lets the whole arbiter be tested without a filesystem.
    """
    if hasattr(value, "__dataclass_fields__"):
        return canonicalise(value)
    if isinstance(value, dict):
        return value
    raise TypeError(
        "{} must be an already-parsed mapping (or a dataclass), got {}. The caller does the file "
        "reading; this module reads data, never code and never disk.".format(
            what, type(value).__name__
        )
    )


# -- schema validity ------------------------------------------------------------

STRING = "string"
INT_STRING = "int_string"
DECIMAL_STRING = "decimal_string"
BOOL = "bool"
ENUM_VALUE = "enum"

SCHEMA_KINDS = (STRING, INT_STRING, DECIMAL_STRING, BOOL, ENUM_VALUE)


@dataclass(frozen=True)
class FieldSpec:
    """One field's declared shape.

    ``optional`` permits ``None`` — an explicit INDETERMINATE — and never permits absence. The
    distinction is the whole reason ``WindowScore.first_hour_edge_share`` is ``Optional`` rather
    than defaulted to zero: a missing measurement and a measured zero are different facts, and only
    one of them may be reported.
    """

    name: str
    kind: str
    optional: bool = False
    allowed: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "allowed", tuple(self.allowed))
        if self.kind not in SCHEMA_KINDS:
            raise ValueError(
                "unknown field kind {!r}; permitted: {}".format(self.kind, ", ".join(SCHEMA_KINDS))
            )
        if self.kind == ENUM_VALUE and not self.allowed:
            raise ValueError("an enum field must declare its permitted values")


def _check_field(payload, spec):
    if spec.name not in payload:
        return Discrepancy(
            kind=MISSING, field=spec.name,
            detail="absent from the artifact; an absent field is not an optional one, and "
                   "'not present' can never be read as 'measured and empty'",
        )

    value = payload[spec.name]

    if value is None:
        if spec.optional:
            return None
        return Discrepancy(
            kind=SCHEMA, field=spec.name,
            detail="is null, but null is reserved here for an explicit indeterminate state and "
                   "this field does not have one",
        )

    if isinstance(value, float):
        return Discrepancy(
            kind=SCHEMA, field=spec.name, observed=repr(value),
            detail="is a JSON number; every numeric field crosses the seam as a string so that no "
                   "consumer parses it as a double",
        )

    if spec.kind == BOOL:
        if not isinstance(value, bool):
            return Discrepancy(kind=SCHEMA, field=spec.name, observed=repr(value),
                               detail="must be a JSON boolean")
        return None

    if isinstance(value, bool) or isinstance(value, int):
        return Discrepancy(
            kind=SCHEMA, field=spec.name, observed=repr(value),
            detail="is a JSON number; integers cross the seam as decimal strings because raw token "
                   "quantities routinely exceed 2^53",
        )

    if not isinstance(value, str):
        return Discrepancy(kind=SCHEMA, field=spec.name, observed=type(value).__name__,
                           detail="must be a string")

    if spec.kind == INT_STRING:
        try:
            int(value)
        except ValueError:
            return Discrepancy(kind=SCHEMA, field=spec.name, observed=value,
                               detail="must be an integer written as a decimal string")
    elif spec.kind == DECIMAL_STRING:
        try:
            parsed = Decimal(value)
        except InvalidOperation:
            return Discrepancy(kind=SCHEMA, field=spec.name, observed=value,
                               detail="must be a Decimal written as a string")
        else:
            if not parsed.is_finite():
                return Discrepancy(
                    kind=SCHEMA, field=spec.name, observed=value,
                    detail="is not finite; a NaN compares False against every threshold and would "
                           "read downstream as an ordinary negative result",
                )
    elif spec.kind == ENUM_VALUE and value not in spec.allowed:
        return Discrepancy(kind=SCHEMA, field=spec.name, observed=value,
                           expected="one of {}".format(", ".join(spec.allowed)),
                           detail="is not a permitted value")

    return None


def check_schema_detail(payload, fields):
    """Validate one artifact payload against its declared field specs."""
    payload = _mapping(payload, "payload")
    found = []
    for spec in fields:
        discrepancy = _check_field(payload, spec)
        if discrepancy is not None:
            found.append(discrepancy)
    return CheckReport(what="schema", discrepancies=tuple(found))


def check_schema(payload, fields):
    return check_schema_detail(payload, fields).messages


# -- artifact envelopes ---------------------------------------------------------

ENVELOPE_KEYS = ("kind", "produced_by", "schema_version", "payload", "payload_hash")


def verify_envelope_detail(envelope):
    """Confirm an envelope written by :func:`contracts.artifact_envelope` still says what it said.

    The hash is recomputed from the payload rather than trusted, because the payload is the thing a
    later editor is tempted to "correct". §9.7 is explicit that a run with a discovered bug is
    invalidated rather than patched — an artifact edited in place is a patch wearing the original
    hash, and this is where that shows up.
    """
    envelope = _mapping(envelope, "envelope")
    found = []

    for key in ENVELOPE_KEYS:
        if key not in envelope:
            found.append(Discrepancy(
                kind=MISSING, field=key,
                detail="missing from the artifact envelope; an artifact without provenance cannot "
                       "be attributed to a run",
            ))
    if found:
        return CheckReport(what="envelope", discrepancies=tuple(found))

    # Compared as text, not as an int. ``contracts.artifact_envelope`` builds the version as an
    # int, and every integer crosses the seam as a decimal string — so the same envelope reads
    # back from its own canonical JSON with ``"1"`` where it was written with ``1``. An identity
    # comparison here would refuse every artifact that had actually been through a file, which is
    # all of them.
    if str(envelope["schema_version"]) != str(ENUM_SCHEMA_VERSION):
        found.append(Discrepancy(
            kind=MISMATCH, field="schema_version",
            expected=str(ENUM_SCHEMA_VERSION), observed=str(envelope["schema_version"]),
            detail="was written under a different enum schema; a renamed status is a changed "
                   "meaning, so the artifact must be re-derived rather than reinterpreted",
        ))

    recomputed = canonical_hash(envelope["payload"])
    if recomputed != envelope["payload_hash"]:
        found.append(Discrepancy(
            kind=MISMATCH, field="payload_hash",
            expected=envelope["payload_hash"], observed=recomputed,
            detail="does not match the payload it accompanies; the payload was altered after it "
                   "was written",
        ))

    for key in ("kind", "produced_by"):
        if not envelope[key]:
            found.append(Discrepancy(kind=MISSING, field=key,
                                     detail="is empty; an anonymous artifact is unauditable"))

    return CheckReport(what="envelope", discrepancies=tuple(found))


def verify_envelope(envelope):
    return verify_envelope_detail(envelope).messages


def check_derived_fields(payload, recomputations, tolerance=None):
    """Recompute exported derived values from the primitives they claim to summarise.

    Delegates to :func:`contracts.verify_redundant_derived` and converts its refusal into a finding
    rather than letting it escape. The arbiter's product is a complete report; a raised exception
    here would mask every check that runs after it, and the caller refuses the decision on any
    non-empty report anyway.
    """
    payload = _mapping(payload, "payload")
    try:
        verify_redundant_derived(payload, recomputations, tolerance=tolerance)
    except DerivedFieldMismatch as exc:
        return CheckReport(what="derived", discrepancies=(
            Discrepancy(kind=DERIVED, field="derived_fields", detail=str(exc)),
        ))
    return CheckReport(what="derived")


# -- §9.2 exact deterministic fields --------------------------------------------

#: §9.2. Raw token amounts match at the raw-unit level, with no percentage tolerance whatsoever.
#: Case is compared as written: an address normalised on one side and not the other is a real
#: inconsistency between two artifacts, and an arbiter that smoothed it over would be doing the
#: builder's normalisation for it — on the builder's behalf, without saying so.
EXACT_MATCH_FIELDS = (
    "transaction_hash",
    "block_number",
    "wallet_address",
    "token_address",
    "pool_address",
    "direction",
    "raw_token_quantity",
    "raw_quote_quantity",
    "fifo_lot_assignment",
    "realized_status",
)


def check_exact_fields_detail(expected, observed, fields=EXACT_MATCH_FIELDS):
    expected = _mapping(expected, "expected")
    observed = _mapping(observed, "observed")
    found = []

    for name in fields:
        if name not in expected:
            found.append(Discrepancy(kind=MISSING, field=name,
                                     detail="not present in the expected record"))
            continue
        if name not in observed:
            found.append(Discrepancy(
                kind=MISSING, field=name,
                detail="not present in the observed record; an unproduced deterministic field is "
                       "a mismatch, never a match",
            ))
            continue

        want, want_problem = _comparable(expected[name])
        got, got_problem = _comparable(observed[name])
        if want_problem or got_problem:
            found.append(Discrepancy(kind=SCHEMA, field=name,
                                     detail=want_problem or got_problem))
            continue
        if want != got:
            found.append(Discrepancy(
                kind=MISMATCH, field=name, expected=want, observed=got,
                detail="differs, and §9.2 admits no tolerance on a deterministic field",
            ))

    return CheckReport(what="exact_fields", discrepancies=tuple(found))


def check_exact_fields(expected, observed, fields=EXACT_MATCH_FIELDS):
    return check_exact_fields_detail(expected, observed, fields).messages


# -- §9.2 tolerance-controlled numeric fields -----------------------------------

#: §9.2. Maximum relative error per event, and in wallet realized value.
USD_RELATIVE_TOLERANCE = Decimal("0.005")

#: §9.2. Buy Quality is compared in **percentage points, absolutely** — not relatively. A relative
#: rule would let a large advantage absorb a large error, which is the wrong way round: the bigger
#: the claimed edge, the more a half-point of drift matters.
BUY_QUALITY_ABSOLUTE_TOLERANCE_PP = Decimal("0.5")

#: §9.4. Agreement floors on the random reconciliation sample.
RECONCILIATION_AGREEMENT_FLOOR = Decimal("0.995")


@dataclass(frozen=True)
class ToleranceSpec:
    name: str
    tolerance: Decimal
    relative: bool = True

    def __post_init__(self):
        object.__setattr__(self, "tolerance", calc(self.tolerance))
        if self.tolerance < 0:
            raise ValueError("a negative tolerance would admit nothing and reject everything")


@dataclass(frozen=True)
class NumericComparison:
    """One field compared, with the arithmetic a reviewer would have to redo to disagree."""

    field: str
    expected: Decimal
    observed: Decimal
    difference: Decimal
    relative_error: Optional[Decimal]
    tolerance: Decimal
    relative: bool
    within: bool


@dataclass(frozen=True)
class NumericCheck:
    comparisons: Tuple[NumericComparison, ...]
    report: CheckReport

    def __post_init__(self):
        object.__setattr__(self, "comparisons", tuple(self.comparisons))

    @property
    def ok(self):
        return self.report.ok

    @property
    def discrepancies(self):
        return self.report.discrepancies

    @property
    def messages(self):
        return self.report.messages

    def comparison_for(self, field):
        for comparison in self.comparisons:
            if comparison.field == field:
                return comparison
        raise KeyError("no comparison was made for {!r}".format(field))


def _compare(spec, expected, observed):
    """The whole arithmetic, inside one frozen-context block.

    The block spans the subtraction as well as the division. ``divide`` alone is not enough: the
    arithmetic that follows it lands back in Python's default 28-digit context, and two values that
    agree to 28 digits and then diverge fail an exact comparison for no substantive reason.
    """
    with localcontext(CALCULATION_CONTEXT):
        difference = +(observed - expected)
        relative_error = None
        if expected != 0:
            relative_error = +(divide(abs(difference), abs(expected)))

        if not spec.relative:
            within = abs(difference) <= spec.tolerance
        elif relative_error is None:
            # A relative tolerance against a zero baseline has no value, and both tempting
            # fallbacks are wrong: zero passes everything, infinity fails everything. Exact
            # equality is the only rule that means what it says.
            within = difference == 0
        else:
            within = relative_error <= spec.tolerance

    return NumericComparison(
        field=spec.name,
        expected=expected,
        observed=observed,
        difference=difference,
        relative_error=relative_error,
        tolerance=spec.tolerance,
        relative=spec.relative,
        within=within,
    )


def check_numeric_fields_detail(expected, observed, specs):
    expected = _mapping(expected, "expected")
    observed = _mapping(observed, "observed")
    comparisons = []
    found = []

    for spec in specs:
        if spec.name not in expected:
            found.append(Discrepancy(kind=MISSING, field=spec.name,
                                     detail="not present in the expected record"))
            continue
        if spec.name not in observed:
            found.append(Discrepancy(
                kind=MISSING, field=spec.name,
                detail="was not reported; an unreported value can never be inside a tolerance",
            ))
            continue

        try:
            want = calc(expected[spec.name])
            got = calc(observed[spec.name])
        except (TypeError, ValueError) as exc:
            found.append(Discrepancy(kind=SCHEMA, field=spec.name, detail=str(exc)))
            continue

        comparison = _compare(spec, want, got)
        comparisons.append(comparison)
        if not comparison.within:
            if comparison.relative and comparison.relative_error is None:
                detail = (
                    "differs from a zero baseline, where a relative tolerance is undefined and "
                    "exact equality is required"
                )
            elif comparison.relative:
                detail = "relative error {} exceeds the {} tolerance".format(
                    comparison.relative_error, spec.tolerance
                )
            else:
                # ``copy_abs`` rather than ``abs``: the copy operations ignore the decimal context
                # entirely, where ``abs()`` rounds to it. ``_compare`` built the difference at the
                # frozen 38 digits and this sentence is the evidence a reviewer re-derives from
                # the expected and observed values printed beside it, so it may not quietly arrive
                # ten digits shorter than the subtraction it claims to report.
                detail = "absolute difference {} exceeds the {} tolerance".format(
                    comparison.difference.copy_abs(), spec.tolerance
                )
            found.append(Discrepancy(
                kind=TOLERANCE, field=spec.name,
                expected=str(want), observed=str(got), detail=detail,
            ))

    return NumericCheck(
        comparisons=tuple(comparisons),
        report=CheckReport(what="numeric_fields", discrepancies=tuple(found)),
    )


def check_numeric_fields(expected, observed, specs):
    return check_numeric_fields_detail(expected, observed, specs).messages


# -- §9.1 / §8.4 ordering -------------------------------------------------------

#: The binding governance order. Two edges in it carry the whole design: ``NULL_COMPLETE`` is
#: unreachable without ``VALIDATION_PASSED``, because the null is computed by the same code and
#: cannot detect the bug it shares; and ``MAIN_TEST_EXECUTED`` is unreachable without
#: ``THRESHOLD_LOCKED``, because a threshold chosen after the result is not a threshold.
GOVERNANCE_ORDER = (
    "PARAMETERS_OPEN",
    "PARAMETERS_FROZEN",
    "VALIDATION_PASSED",
    "CODE_AND_DATA_FROZEN",
    "NULL_COMPLETE",
    "THRESHOLD_LOCKED",
    "MAIN_TEST_EXECUTED",
    "DECISION_EMITTED",
)

#: §9.1, binding. The pipeline proves itself correct before it computes anything that matters.
VALIDATION_LAYER_ORDER = (
    "GOLDEN_DATASET",
    "KNOWN_ANSWER_TESTS",
    "CROSS_SOURCE_RECONCILIATION",
    "INDEPENDENT_VALIDATION",
    "CODE_AND_DATA_FREEZE",
    "NULL_DISTRIBUTION",
    "MAIN_TEST",
)


def check_sequence_detail(observed, order, field):
    """The observed stages must be a contiguous prefix of the binding order.

    A prefix, not a subset: a run in progress has legitimately not reached the later stages, but a
    run that skipped one has not reached the later stages either — it has only recorded that it
    did. Nothing here rewinds, repeats, or reorders.
    """
    observed = tuple(observed)
    found = []

    if not observed:
        return CheckReport(what=field, discrepancies=(
            Discrepancy(kind=MISSING, field=field,
                        detail="no stages were recorded; an unrecorded run cannot be audited"),
        ))

    for index, state in enumerate(observed):
        if state not in order:
            found.append(Discrepancy(
                kind=SCHEMA, field="{}[{}]".format(field, index), observed=str(state),
                detail="is not a stage of the binding order",
            ))
            continue
        if index >= len(order):
            found.append(Discrepancy(
                kind=OUT_OF_ORDER, field="{}[{}]".format(field, index), observed=str(state),
                detail="is recorded past the end of the binding order",
            ))
            continue
        if state != order[index]:
            found.append(Discrepancy(
                kind=OUT_OF_ORDER, field="{}[{}]".format(field, index),
                expected=order[index], observed=str(state),
                detail="is out of order; the sequence must advance one stage at a time from {}"
                       .format(order[0]),
            ))

    return CheckReport(what=field, discrepancies=tuple(found))


def check_state_sequence(states):
    return check_sequence_detail(states, GOVERNANCE_ORDER, "governance_states").messages


def check_layer_order(layers):
    return check_sequence_detail(layers, VALIDATION_LAYER_ORDER, "validation_layers").messages


# -- §9.4 / §9.8 required coverage ----------------------------------------------

AT_LEAST = ">="
AT_MOST = "<="
EXACTLY = "=="
IS_TRUE = "is_true"


@dataclass(frozen=True)
class Condition:
    """One measured quantity and the bar it must clear, with the reason recorded beside it."""

    field: str
    comparison: str
    bound: Optional[Decimal]
    why: str

    def __post_init__(self):
        if self.comparison not in (AT_LEAST, AT_MOST, EXACTLY, IS_TRUE):
            raise ValueError("unknown comparison {!r}".format(self.comparison))
        if self.comparison == IS_TRUE:
            if self.bound is not None:
                raise ValueError("a boolean condition takes no bound")
        else:
            object.__setattr__(self, "bound", calc(self.bound))


#: §9.8, all ten. Failure of any one leaves the null distribution and the main test unauthorised.
VALIDATION_GATE_CONDITIONS = (
    Condition("golden_set_precision", EXACTLY, Decimal("1"),
              "no spurious buy created; a single unresolved false positive fails the gate"),
    Condition("golden_set_recall", EXACTLY, Decimal("1"),
              "no valid buy missed; a single unresolved false negative fails the gate"),
    Condition("known_answer_pass_rate", EXACTLY, Decimal("1"),
              "no failing known-answer test may be waived as an edge case"),
    Condition("raw_quantity_mismatches", EXACTLY, Decimal("0"),
              "raw amounts match at the raw-unit level, with no percentage tolerance"),
    Condition("fifo_assignment_mismatches", EXACTLY, Decimal("0"),
              "FIFO assignment is deterministic; a mismatch is a wrong rule, not a rounding"),
    Condition("max_per_event_usd_relative_error", AT_MOST, USD_RELATIVE_TOLERANCE,
              "0.5% per event; differences above tolerance are found and fixed, never averaged"),
    Condition("max_wallet_buy_quality_difference_pp", AT_MOST, BUY_QUALITY_ABSOLUTE_TOLERANCE_PP,
              "0.5 percentage points absolute on the metric the gate actually reads"),
    Condition("reconciliation_event_agreement", AT_LEAST, RECONCILIATION_AGREEMENT_FLOOR,
              "99.5% agreement on the random sample of >=200 accounts"),
    Condition("unexplained_golden_set_differences", EXACTLY, Decimal("0"),
              "every remaining difference falls into a documented category"),
    Condition("independent_review_completed", IS_TRUE, None,
              "§9.5: without independent review the status is NOT INDEPENDENT and the main test "
              "is blocked"),
)

#: §9.4, on the golden set and on the random sample.
RECONCILIATION_CONDITIONS = (
    Condition("supported_transaction_coverage", EXACTLY, Decimal("1"),
              "100% of supported transactions reconcile against raw chain data"),
    Condition("unexplained_missing_trades", EXACTLY, Decimal("0"),
              "an unexplained dropped event is prohibited outright"),
    Condition("unexplained_extra_trades", EXACTLY, Decimal("0"),
              "a trade the raw data does not contain was invented by the decoder"),
    Condition("raw_balance_delta_mismatches", EXACTLY, Decimal("0"),
              "the balance delta is the ground truth the netting rule is derived from"),
    Condition("sample_event_agreement", AT_LEAST, RECONCILIATION_AGREEMENT_FLOOR,
              "99.5% event agreement on the random sample"),
    Condition("sample_notional_agreement", AT_LEAST, RECONCILIATION_AGREEMENT_FLOOR,
              "99.5% notional agreement on the random sample"),
)


def _check_condition(report, condition):
    if condition.field not in report:
        return Discrepancy(
            kind=MISSING, field=condition.field,
            detail="was not reported, so the condition cannot hold. {}".format(condition.why),
        )

    value = report[condition.field]

    if condition.comparison == IS_TRUE:
        if value is True:
            return None
        return Discrepancy(
            kind=MISMATCH, field=condition.field, expected="true", observed=repr(value),
            detail="is not true. {}".format(condition.why),
        )

    if isinstance(value, bool):
        return Discrepancy(kind=SCHEMA, field=condition.field, observed=repr(value),
                           detail="is a boolean where a measured quantity belongs")
    try:
        measured = calc(value)
    except (TypeError, ValueError) as exc:
        return Discrepancy(kind=SCHEMA, field=condition.field, detail=str(exc))

    if condition.comparison == EXACTLY:
        held = measured == condition.bound
    elif condition.comparison == AT_LEAST:
        held = measured >= condition.bound
    else:
        held = measured <= condition.bound

    if held:
        return None
    return Discrepancy(
        kind=MISMATCH, field=condition.field,
        expected="{} {}".format(condition.comparison, condition.bound), observed=str(measured),
        detail="fails its condition. {}".format(condition.why),
    )


def check_conditions_detail(report, conditions, what):
    report = _mapping(report, what)
    found = []
    for condition in conditions:
        discrepancy = _check_condition(report, condition)
        if discrepancy is not None:
            found.append(discrepancy)
    return CheckReport(what=what, discrepancies=tuple(found))


def check_validation_gate_detail(report):
    """§9.8. Ten conditions, every one required."""
    return check_conditions_detail(report, VALIDATION_GATE_CONDITIONS, "validation_gate")


def check_validation_gate(report):
    return check_validation_gate_detail(report).messages


def check_reconciliation_coverage_detail(report):
    """§9.4. Coverage is a measured quantity, and an unmeasured one is not full coverage."""
    return check_conditions_detail(report, RECONCILIATION_CONDITIONS, "reconciliation")


def check_reconciliation_coverage(report):
    return check_reconciliation_coverage_detail(report).messages
