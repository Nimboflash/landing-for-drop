"""Layer 2 — properties the battery must have to be worth freezing.

Three families:

* **the answers do not depend on anything outside the fixtures** — not on the caller's decimal
  context, not on a clock, not on a file, not on a seed;
* **the fixtures are the kind of data the seam permits** — ints for raw quantities, Decimals for
  money, no float anywhere;
* **the fixture hash actually covers the battery** — every case, every input, and every expected
  answer changes it, which is what makes §9.6's pin worth recording.

The third family is the one with teeth. A hash computed over a summary that had drifted from the
real fixtures would freeze nothing, and it would look exactly like this one.
"""

import ast
import os
from dataclasses import replace
from decimal import Context, Decimal, InvalidOperation, localcontext
from enum import Enum

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from contracts import CALCULATION_CONTEXT, add, quantize_usd, to_canonical_json

from . import battery as B

ROUNDING_MODES = (
    "ROUND_CEILING", "ROUND_DOWN", "ROUND_FLOOR", "ROUND_HALF_DOWN",
    "ROUND_HALF_EVEN", "ROUND_HALF_UP", "ROUND_UP", "ROUND_05UP",
)


def _answers():
    """Every case's observed facts, as one canonical blob."""
    return to_canonical_json(
        {case.name: B.run_case(case) for case in B.BATTERY}
    )


# -- family 1: nothing outside the fixtures decides an answer -------------------


#: Below this ambient precision the pipeline does not produce a *different* answer — it produces
#: none at all, because ``contracts.quantize_ratio`` refuses. See
#: :func:`test_the_reporting_boundary_still_reads_the_ambient_context`, which pins that as the
#: defect it is rather than letting this bound look like a property of the battery.
MIN_AMBIENT_PRECISION = 8


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    precision=st.integers(min_value=MIN_AMBIENT_PRECISION, max_value=60),
    rounding=st.sampled_from(ROUNDING_MODES),
)
def test_no_answer_moves_with_the_caller_s_decimal_context(precision, rounding):
    """The frozen 38-digit context, held from the outside.

    ``decimal`` rounds every operator's result to whatever context is current, so a bare ``+``,
    ``-``, ``*``, ``/``, unary minus or ``abs()`` anywhere in the pipeline makes an answer a
    property of the caller's settings. That defect has shipped three times in this repository,
    once inside the fix for itself, and the truncated value looks entirely reasonable every time.

    This runs the whole battery under an ambient context chosen by Hypothesis — every rounding
    mode, precision 8 through 60 — and requires byte-identical answers and an unchanged fixture
    hash. A module that reached for the ambient context to compute a value fails here rather than
    at the next review. Exhaustively over 1..60 x all eight modes, no answer in this battery ever
    differs; the only ambient sensitivity left is the refusal below precision 8.
    """
    baseline_answers = _answers()
    baseline_hash = B.known_answer_fixture_hash()

    with localcontext(Context(prec=precision, rounding=rounding)):
        assert _answers() == baseline_answers
        assert B.known_answer_fixture_hash() == baseline_hash


def test_the_reporting_boundary_still_reads_the_ambient_context():
    """A defect in a dependency, pinned rather than worked around.

    ``contracts.numeric.quantize_usd`` / ``quantize_ratio`` / ``quantize_pp`` call
    ``Decimal.quantize`` with an explicit rounding mode but **no context**, so the precision they
    are evaluated at is the caller's ambient one and not the frozen 38 digits. ``quantize`` raises
    ``InvalidOperation`` rather than truncating, so no value is silently wrong — but *whether the
    call succeeds at all* is decided by a global the seam does not control. That is the same class
    as the ``canonicalise``/``normalize()`` defect recorded in ``tests/test_frozen_context.py``,
    which was repaired by wrapping the call in ``localcontext(CALCULATION_CONTEXT)``. The repair
    was applied there and not here.

    Two consequences, both asserted below:

    1. ``marking.mark_position`` builds its evidence trail with ``quantize_ratio``, so at ambient
       precision 7 a valuation that has already been computed correctly is aborted by a
       *formatting* step. ``marking/mark.py:_fixed`` names exactly this hazard — "Quantizing an
       audit string must not be able to abort a valuation" — and closes it for one call while the
       other is still open.
    2. The threshold ``marking/mark.py:_fixed`` documents is off by ten orders of magnitude for
       every caller that has not opened a frozen block. It says ``quantize_usd`` raises "above
       roughly 10^32, because six decimal places on a 33-digit value needs more than the frozen 38
       digits". Under the frozen context that is right — 1E+31 passes, 1E+32 raises. Under the
       default ambient 28 digits, which is what a caller has, it raises above 1E+21.

    Not repaired here: ``src/contracts/`` is the frozen seam. This test asserts the behaviour as it
    stands, so the day it is fixed this test fails and is deleted rather than the defect quietly
    disappearing from the record.
    """
    # Its shortfall quantizes to 0.33466800 — eight significant digits, so it needs an ambient
    # precision of at least eight to be *rendered*, having already been computed at 38.
    marking_case = B.case_named("Thin but Live Pool")

    with localcontext(Context(prec=MIN_AMBIENT_PRECISION - 1)):
        with pytest.raises(InvalidOperation):
            B.run_case(marking_case)

    with localcontext(Context(prec=MIN_AMBIENT_PRECISION)):
        assert B.evaluate_case(marking_case).passed

    # The documented bound holds only inside the frozen context.
    with localcontext(CALCULATION_CONTEXT):
        assert quantize_usd(Decimal("1E+31")) is not None
        with pytest.raises(InvalidOperation):
            quantize_usd(Decimal("1E+32"))

    # What a caller running at the Python default actually gets: ten orders of magnitude earlier.
    with localcontext(Context(prec=28)):
        assert quantize_usd(Decimal("1E+21")) is not None
        with pytest.raises(InvalidOperation):
            quantize_usd(Decimal("1E+22"))


def test_running_a_case_twice_gives_the_identical_answer():
    """Purity. No state carries between runs, so ordering and repetition are irrelevant."""
    first = {case.name: to_canonical_json(B.run_case(case)) for case in B.BATTERY}
    second = {case.name: to_canonical_json(B.run_case(case)) for case in reversed(B.BATTERY)}
    assert first == second


def test_the_battery_reaches_no_clock_no_disk_and_no_network():
    """§ "no network, no file I/O in library code, no clock, no unseeded randomness".

    Static, over the committed fixture module. An answer that depended on the date would pass
    today and fail in a month, which is the worst possible failure for a frozen artifact.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "battery.py")
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)

    forbidden = {
        "time", "datetime", "random", "os", "socket", "urllib", "requests", "http",
        "pathlib", "secrets", "uuid", "subprocess",
    }
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & forbidden), (
        "the battery imports {}; a frozen answer may not depend on the clock, the filesystem, the "
        "network, or an unseeded source of randomness".format(sorted(imported & forbidden))
    )

    called = {
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "open" not in called, "the battery reads no files; the fixtures are the fixtures"


# -- family 2: the fixtures obey the seam ---------------------------------------


def _walk(value, path="", seen=None):
    """Every scalar reachable from a fixture, with the path that reached it."""
    if seen is None:
        seen = set()
    if id(value) in seen:
        return
    seen.add(id(value))

    if hasattr(value, "__dataclass_fields__"):
        for name in sorted(value.__dataclass_fields__):
            for item in _walk(getattr(value, name), "{}.{}".format(path, name), seen):
                yield item
        return
    if isinstance(value, dict):
        for key, item in value.items():
            for found in _walk(item, "{}[{!r}]".format(path, key), seen):
                yield found
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for index, item in enumerate(value):
            for found in _walk(item, "{}[{}]".format(path, index), seen):
                yield found
        return
    yield path, value


@pytest.mark.parametrize("case", B.BATTERY, ids=[c.name for c in B.BATTERY])
def test_no_float_reaches_a_fixture_or_an_answer(case):
    """Seam rule: USD and ratios are Decimal, raw quantities are int, never float.

    A float in a fixture would have lost precision before the pipeline ever saw it, and the
    canonical form would refuse to serialise it — but only after the answer had been compared.
    """
    for source, blob in (("inputs", case.inputs), ("expected", case.expected)):
        for path, value in _walk(blob, source):
            assert not isinstance(value, float), (
                "{}: {} is the float {!r}".format(case.name, path, value)
            )


@pytest.mark.parametrize("case", B.BATTERY, ids=[c.name for c in B.BATTERY])
def test_every_expected_answer_has_a_canonical_form(case):
    """If it cannot be canonicalised it cannot be hashed, and §9.6 could not pin it."""
    assert to_canonical_json(case.expected)
    assert to_canonical_json(case.inputs)


@pytest.mark.parametrize("case", B.BATTERY, ids=[c.name for c in B.BATTERY])
def test_expected_answers_are_typed_values_not_rendered_strings(case):
    """A status compared as a string passes against a module that returns the wrong enum whose
    value happens to match. Statuses stay enums, quantities stay ints, money stays Decimal.

    ``None`` is permitted everywhere: the seam's fourth rule makes it the explicit representation
    of an indeterminate value, and a case asserting that a reverted transaction has *no* raw
    amount is asserting exactly that.
    """
    for key, value in case.expected.items():
        if isinstance(value, dict):
            # A mapping of raw quantities — ``unmatched_sell_raw``. Check what is inside it.
            for inner in value.values():
                assert isinstance(inner, int) and not isinstance(inner, bool), (
                    "{}: {} maps to the non-int {!r}".format(case.name, key, inner)
                )
            continue
        if key.endswith(("_raw", "_raw_amount", "_quantity")):
            assert value is None or (isinstance(value, int) and not isinstance(value, bool)), (
                "{}: {} is a raw quantity and must be int, got {!r}".format(case.name, key, value)
            )
        if key.endswith(("_usd", "_share", "_return", "_pct", "quality")):
            assert value is None or isinstance(value, Decimal), (
                "{}: {} is money or a ratio and must be Decimal, got {!r}".format(
                    case.name, key, value)
            )
        if key.endswith(("_status", "_basis", "_bucket")):
            assert value is None or isinstance(value, Enum), (
                "{}: {} is a status and must be the enum, not its rendering".format(
                    case.name, key)
            )


@pytest.mark.parametrize("case", B.BATTERY, ids=[c.name for c in B.BATTERY])
def test_a_documented_refusal_is_also_an_asserted_one(case):
    """``raises`` names an exception a case pre-registers. Something has to check it.

    A field that only documents is a field that drifts: the day the refusal stops happening, prose
    saying it does would still be sitting in the fixture. Every key in ``raises`` must therefore
    also be an ``expected`` answer, so the harness compares it like any other.
    """
    for key, description in case.raises.items():
        assert key in case.expected, (
            "{}: raises[{!r}] documents a refusal that no expected answer checks".format(
                case.name, key)
        )
        assert case.expected[key] is True, (
            "{}: {} documents the refusal {!r}, so the case must assert that it happened".format(
                case.name, key, description)
        )


@pytest.mark.parametrize("case", B.BATTERY, ids=[c.name for c in B.BATTERY])
def test_the_runner_produces_exactly_the_pre_registered_keys(case):
    """No silent additions, no silent omissions.

    A runner that stopped producing a key would otherwise turn an assertion into an absence, and
    an absence is what a waiver looks like from the inside.
    """
    assert set(B.run_case(case)) == set(case.expected), (
        "{}: runner produced {}, pre-registered {}".format(
            case.name,
            sorted(set(B.run_case(case)) - set(case.expected)),
            sorted(set(case.expected) - set(B.run_case(case))),
        )
    )


# -- family 3: the fixture hash covers the battery ------------------------------


_UNPERTURBABLE = object()


def _perturb(value):
    """A different value of the same kind, or :data:`_UNPERTURBABLE`.

    Deliberately minimal: one unit for a number, one character for a string, the next member for
    an enum. A large perturbation would prove less — the claim is that the hash notices *any*
    change, and the smallest available one is the sharpest form of it.

    The Decimal arm goes through ``add`` and not through ``+``. A bare addition runs at the
    caller's ambient precision, so a small perturbation of a long value could be rounded straight
    back onto the original — and this test would then assert that an unchanged battery hashes the
    same, while reporting that it had checked a change.
    """
    if isinstance(value, bool):
        return not value
    if isinstance(value, Enum):
        members = list(type(value))
        for member in members:
            if member is not value:
                return member
        return _UNPERTURBABLE
    if isinstance(value, Decimal):
        return add(value, Decimal("1"))
    if isinstance(value, int):
        return value + 1
    if isinstance(value, str):
        return value + "!"
    if value is None:
        return "was-none"
    return _UNPERTURBABLE


def _hash_with(case, **changes):
    modified = replace(case, **changes)
    return B.known_answer_fixture_hash(
        tuple(modified if c.name == case.name else c for c in B.BATTERY)
    )


def test_the_fixture_hash_is_a_pure_function_of_the_battery():
    assert B.known_answer_fixture_hash() == B.known_answer_fixture_hash()
    assert B.known_answer_fixture_hash(B.BATTERY) == B.known_answer_fixture_hash()
    assert len(B.known_answer_fixture_hash()) == 64


@pytest.mark.parametrize("case", B.BATTERY, ids=[c.name for c in B.BATTERY])
def test_dropping_a_case_changes_the_fixture_hash(case):
    """Every case is inside the hash, so a battery that lost one cannot claim the frozen hash."""
    without = tuple(c for c in B.BATTERY if c.name != case.name)
    assert B.known_answer_fixture_hash(without) != B.known_answer_fixture_hash()


@pytest.mark.parametrize("case", B.BATTERY, ids=[c.name for c in B.BATTERY])
def test_changing_any_expected_answer_changes_the_fixture_hash(case):
    """Requirement 1's teeth, applied to every perturbable answer in every case."""
    baseline = B.known_answer_fixture_hash()
    checked = 0
    for key, value in sorted(case.expected.items()):
        perturbed = _perturb(value)
        if perturbed is _UNPERTURBABLE:
            continue
        answers = dict(case.expected)
        answers[key] = perturbed
        assert _hash_with(case, expected=answers) != baseline, (
            "{}: changing {} from {!r} to {!r} left the fixture hash unchanged".format(
                case.name, key, value, perturbed)
        )
        checked += 1
    assert checked, "{}: no expected answer could be perturbed".format(case.name)


@pytest.mark.parametrize("case", B.BATTERY, ids=[c.name for c in B.BATTERY])
def test_dropping_any_input_changes_the_fixture_hash(case):
    """Every input enters the hash, so the hash is over the fixtures and not over a description
    of them that could drift away from what is actually fed in."""
    baseline = B.known_answer_fixture_hash()
    for key in sorted(case.inputs):
        smaller = {k: v for k, v in case.inputs.items() if k != key}
        assert _hash_with(case, inputs=smaller) != baseline, (
            "{}: dropping input {} left the fixture hash unchanged".format(case.name, key)
        )


def test_changing_a_transaction_a_pool_or_a_price_changes_the_fixture_hash():
    """The three shapes a fixture actually takes, perturbed by the smallest possible amount.

    A raw unit, a block, and the last digit of a price. Each of these is a different experiment,
    and §9.6 exists so that a different experiment cannot be reported under the frozen hash.
    """
    baseline = B.known_answer_fixture_hash()

    case = B.case_named("Simple Buy + Full Sell")
    original = case.inputs["buy"]
    one_more_raw_unit = replace(
        original,
        transfers=(
            replace(original.transfers[0], raw_amount=original.transfers[0].raw_amount + 1),
        ) + original.transfers[1:],
    )
    assert _hash_with(case, inputs=dict(case.inputs, buy=one_more_raw_unit)) != baseline

    one_block_later = replace(original, block_number=original.block_number + 1)
    assert _hash_with(case, inputs=dict(case.inputs, buy=one_block_later)) != baseline

    marking_case = B.case_named("Open Position at Day 30")
    pool_state = marking_case.inputs["pool"]
    one_more_reserve_unit = replace(
        pool_state, quote_reserve_raw=pool_state.quote_reserve_raw + 1
    )
    assert _hash_with(
        marking_case, inputs=dict(marking_case.inputs, pool=one_more_reserve_unit)
    ) != baseline

    # ``add`` and not ``+``: $0.000001 plus 1E-30 needs 25 significant digits, which survives the
    # frozen 38 and would not survive an ambient context set below it. A perturbation that can be
    # rounded away is a test that can pass without perturbing anything.
    prices = dict(case.inputs["prices"])
    prices[B.USDC] = add(prices[B.USDC], Decimal("1E-30"))
    assert prices[B.USDC] != case.inputs["prices"][B.USDC]
    assert _hash_with(case, inputs=dict(case.inputs, prices=prices)) != baseline


def test_cosmetic_decimal_scale_does_not_change_the_fixture_hash():
    """The other half of the claim, and the reason the hash is over the *canonical* form.

    ``Decimal("1000")`` and ``Decimal("1000.00")`` are the same answer written two ways. If the
    hash moved between them, re-freezing would be triggered by formatting, and a hash that moves
    for no substantive reason stops being read.
    """
    case = B.case_named("Simple Buy + Full Sell")
    restated = dict(case.expected)
    restated["buy_quote_usd"] = Decimal("1000.0000")
    assert _hash_with(case, expected=restated) == B.known_answer_fixture_hash()


def test_the_derivation_is_outside_the_hash():
    """Prose explaining a number is not the number. Rewording it must not re-freeze the battery."""
    case = B.BATTERY[0]
    reworded = case.derivation + ("(an added note, changing no value)",)
    assert _hash_with(case, derivation=reworded) == B.known_answer_fixture_hash()
