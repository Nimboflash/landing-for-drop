"""Two spellings of one capital level, at the boundary that decides GO.

``CapitalFeasibility`` keys its mapping by ``_level_key``, which runs ``calc`` and then snaps onto
``DESIGN_CAPITAL_LEVELS``. ``calc`` accepts ``str``, ``int`` and ``Decimal``, so three source types
land in one key space — and until this file existed, two caller entries naming ``$1,500,000`` became
one entry with the survivor chosen by whichever the caller's mapping happened to yield last.

The measured cost, driven through ``emit_decision`` on the clean-run evidence and changing nothing
but the order of a three-entry mapping:

    ['1500000', Decimal('1500000'), Decimal('2000000')]  ->  GO
    [Decimal('1500000'), '1500000', Decimal('2000000')]  ->  CONDITIONAL_REVIEW

``tests/integration/test_gate_capital_keys.py`` pins that half — the published verdict. This file
pins the boundary itself, with literals: which inputs are refused, which are not, and what the
surviving mapping contains when nothing collided.

Every expectation below is written out rather than derived from the module. A test that asked
``_level_key`` what it thought the key was would agree with any collapse the function grew.
"""

import itertools
from decimal import Decimal

import pytest

from contracts import EdgeOriginStatus, WindowScore, canonicalise
from gate_validation import (
    DESIGN_CAPITAL_LEVELS,
    CapitalFeasibility,
    ConflictingResults,
    DiagnosticInputRefused,
    assess_capital_feasibility,
    evaluate_windows_detail,
)

D = Decimal

#: The two entries the finding was measured with. They disagree, and the disagreement is
#: deliberately *not* what the refusal is conditioned on — see the agreeing-values case below.
AT_1_5M_FAILING = D("-0.0500")
AT_1_5M_PASSING = D("0.0362")
AT_2M = D("0.0118")


# -- the collision is refused, in every order and through every door --------------


def test_two_spellings_of_one_level_are_refused_in_the_caller_s_order():
    with pytest.raises(ConflictingResults) as excinfo:
        assess_capital_feasibility({
            "1500000": AT_1_5M_FAILING,
            D("1500000"): AT_1_5M_PASSING,
            D("2000000"): AT_2M,
        })
    assert "1500000" in str(excinfo.value)


def test_two_spellings_of_one_level_are_refused_in_the_other_order():
    """The order that used to publish GO. Same input, same refusal — that is the whole point."""
    with pytest.raises(ConflictingResults):
        assess_capital_feasibility({
            D("1500000"): AT_1_5M_PASSING,
            "1500000": AT_1_5M_FAILING,
            D("2000000"): AT_2M,
        })


def test_pairs_are_refused_before_dict_can_collapse_them():
    """The second half of the defect: ``dict(...)`` used to run first and eat the repeat.

    A ``Mapping`` cannot repeat a key, so this door is the only way a caller can supply the *same*
    spelling twice — and it is the door ``assess_capital_feasibility`` used to close by converting.
    """
    with pytest.raises(ConflictingResults):
        assess_capital_feasibility([
            (D("1500000"), AT_1_5M_FAILING),
            (D("1500000"), AT_1_5M_PASSING),
            (D("2000000"), AT_2M),
        ])


def test_the_refusal_is_on_the_collision_not_on_the_values_disagreeing():
    """The class, not the instance.

    A guard conditioned on the two values differing passes every input a reviewer would construct
    and leaves the defect in place: the caller whose key space collapses today hands two different
    numbers tomorrow, and by then the check has been taught to look away.
    """
    with pytest.raises(ConflictingResults):
        assess_capital_feasibility([
            ("1500000", AT_1_5M_PASSING),
            (D("1500000"), AT_1_5M_PASSING),
            (D("2000000"), AT_2M),
        ])


def test_a_non_gating_level_named_twice_is_refused_too():
    """§3.1's other three levels are recorded and inert, and still may not be two entries.

    They reach the decision record and the reporting lane reads them. "It does not decide anything"
    is a statement about the gate, not a licence to publish whichever of two numbers arrived last.
    """
    with pytest.raises(ConflictingResults):
        assess_capital_feasibility([
            ("100000", D("-0.50")),
            (D("100000"), D("0.50")),
            (D("1500000"), AT_1_5M_PASSING),
            (D("2000000"), AT_2M),
        ])


def test_constructing_the_type_directly_is_refused_the_same_way():
    """``emit_decision`` accepts a ``CapitalFeasibility``, not the output of one function.

    So the refusal lives in ``__post_init__``. If it lived in ``assess_capital_feasibility`` a
    caller could build the value itself and reach a published verdict without passing the check.
    """
    with pytest.raises(ConflictingResults):
        CapitalFeasibility(excess_by_level=[
            ("1500000", AT_1_5M_FAILING),
            (D("1500000"), AT_1_5M_PASSING),
        ])


def test_the_refusal_names_both_spellings_and_the_level():
    message = str(pytest.raises(
        ConflictingResults,
        assess_capital_feasibility,
        [("1500000", AT_1_5M_FAILING), (D("1500000"), AT_1_5M_PASSING)],
    ).value)
    assert "'1500000'" in message
    assert "Decimal('1500000')" in message
    assert "$1500000" in message
    assert "last one supplied would have won" in message


# -- what is still accepted, with the surviving values written out ----------------


def test_one_spelling_per_level_is_untouched():
    assessment = assess_capital_feasibility({
        D("1500000"): AT_1_5M_PASSING,
        D("2000000"): AT_2M,
    })
    assert assessment.excess_by_level == {D("1500000"): D("0.0362"), D("2000000"): D("0.0118")}
    assert assessment.feasible is True


def test_pairs_with_one_spelling_per_level_are_untouched():
    assessment = assess_capital_feasibility([
        (D("1500000"), AT_1_5M_PASSING),
        (D("2000000"), AT_2M),
    ])
    assert assessment.excess_by_level == {D("1500000"): D("0.0362"), D("2000000"): D("0.0118")}
    assert assessment.feasible is True


def test_a_string_spelling_alone_still_snaps_onto_the_pre_registered_constant():
    """The snapping is why the collision exists, and it is also load-bearing on its own.

    ``Decimal("1.5E+6")`` and ``Decimal("1500000")`` render differently, and the canonical hash of
    a decision record may not depend on how a caller spelled a number.

    The renderings are asserted, not the ``Decimal``\\ s. ``Decimal("2.0E+6") == Decimal("2000000")``
    is ``True``, so a list comparison here agrees with a ``_level_key`` that has stopped snapping
    entirely — measured: deleting the snap left this whole suite green while the stored key went
    back to rendering ``2.0E+6``. ``str`` is the only comparison that can tell the two apart.
    """
    assessment = assess_capital_feasibility({"1500000": D("0.05"), "2.0E+6": D("0.03")})
    assert [str(level) for level in assessment.excess_by_level] == ["1500000", "2000000"]
    assert assessment.excess_by_level[DESIGN_CAPITAL_LEVELS[0]] == D("0.05")
    assert assessment.excess_by_level[DESIGN_CAPITAL_LEVELS[1]] == D("0.03")
    assert assessment.feasible is True


def test_every_spelling_of_a_level_serialises_to_one_form():
    """What the snap buys, pinned as bytes rather than as a numeric equality.

    ``contracts.canonicalise`` normalises a Decimal *value*'s exponent but renders a Decimal
    *key* with ``str``, and ``excess_by_level`` is keyed by the level — so without the snap the
    same two measurements serialise five different ways depending on how the caller spelled the
    rung. The literal below is the one form all five must produce.
    """
    expected = {"1500000": "0.03", "2000000": "0.02"}
    for spelling in (D("1.5E+6"), D("1500000.00"), D("1500000"), "1.5E+6", 1500000):
        assessment = assess_capital_feasibility({spelling: D("0.03"), D("2000000"): D("0.02")})
        assert canonicalise(assessment.excess_by_level) == expected, spelling


def test_an_unmeasured_level_is_still_a_None_and_still_fails():
    """The collision check runs before the values are read, and does not disturb ticket 33."""
    assessment = assess_capital_feasibility([
        (D("1500000"), None),
        (D("2000000"), AT_2M),
    ])
    assert assessment.excess_by_level == {D("1500000"): None, D("2000000"): D("0.0118")}
    assert assessment.unmeasured_levels == (D("1500000"),)
    assert assessment.feasible is False


def test_a_malformed_entry_is_named_rather_than_unpacked_into_an_incidental_error():
    """Reading pairs instead of calling ``dict`` means a bad entry has to be refused here."""
    with pytest.raises(TypeError) as excinfo:
        assess_capital_feasibility([(D("1500000"), D("0.05"), "extra")])
    assert "is not a (level, excess) pair" in str(excinfo.value)


@pytest.mark.parametrize("entry", [
    (D("1500000"), D("0.05"), "extra"),   # three values: bare unpacking raises ValueError
    (D("1500000"),),                      # one value: bare unpacking raises ValueError
    D("1500000"),                         # not iterable at all: bare unpacking raises TypeError
    None,
])
def test_every_malformed_entry_shape_is_one_named_TypeError_through_both_doors(entry):
    """The exception *type* is the guard, and it is one type for every malformed shape.

    Without the ``try``/``except`` the arity mistakes escape as ``ValueError`` and the non-iterable
    as ``TypeError``, so a caller cannot catch "this mapping is malformed" with one clause and the
    message names neither the parameter nor the entry. Both entry points are checked: the refusal
    lives in ``__post_init__``, so the factory must not be the only door that has it.
    """
    for build in (assess_capital_feasibility,
                  lambda pairs: CapitalFeasibility(excess_by_level=pairs)):
        with pytest.raises(TypeError) as refusal:
            build([entry, (D("2000000"), AT_2M)])
        assert "excess_by_level entry" in str(refusal.value)
        assert "is not a (level, excess) pair" in str(refusal.value)
        assert repr(entry) in str(refusal.value)


# -- the residue, stated as a test rather than only as prose ----------------------


def test_spellings_python_itself_calls_equal_are_gone_before_this_boundary_sees_them():
    """What the refusal cannot reach through a ``Mapping``, and why that is not a hole here.

    ``Decimal("1.5E+6")``, ``Decimal("1500000.00")`` and the ``int`` ``1500000`` all compare and
    hash equal to ``Decimal("1500000")``, so a dict literal carrying two of them is already one
    entry — collapsed by Python, in the caller's own expression, with no trace left for anything
    downstream to refuse. This test pins that fact so the docstring's claim is checked rather than
    asserted, and the case below shows the pairs door does reach it.
    """
    collapsed = {D("1.5E+6"): D("-0.05"), D("1500000"): D("0.03"), 1500000: D("0.07")}
    assert len(collapsed) == 1

    assessment = assess_capital_feasibility(collapsed)
    assert assessment.excess_by_level == {D("1500000"): D("0.07")}


def test_two_window_numbers_python_calls_equal_do_not_become_one_window():
    """The same class one function up, through a door that has no ``Mapping`` to hide behind.

    ``evaluate_windows_detail`` groups results into ``{window: {column: score}}`` and takes the
    window straight off the ``WindowScore``, where the seam declares it ``int`` and enforces
    nothing. ``1``, ``True`` and ``1.0`` are one dict key.

    What that costs, and it is the direction that flatters the hypothesis: a ``leader`` result at
    window 1 and a ``follower_adjusted`` result at window ``True`` are two windows that each carry
    one column, and a window with one column cannot support "both gates passed" — so each fails.
    Merged, they are one window with both columns, and it **passes**. Measured on the code before
    this refusal: ``[(1, True, ())]`` — one verdict, passed, no missing columns, nothing anywhere
    recording that two results had been pooled.
    """
    def score(window, column):
        return WindowScore(
            column=column, window=window,
            mean_advantage=D("1"), median_advantage=D("1"),
            first_hour_edge_share=D("0.1"), positive_edge_contribution=D("1"),
            edge_origin_status=EdgeOriginStatus.VALID,
        )

    for impostor in (True, 1.0, D("1")):
        with pytest.raises(DiagnosticInputRefused) as refusal:
            evaluate_windows_detail(
                [score(1, "leader"), score(impostor, "follower_adjusted")], D("0")
            )
        assert "is a {} and not an int".format(type(impostor).__name__) in str(refusal.value)

    # Two genuinely separate windows, each with one column, still fail — which is the behaviour the
    # merge was borrowing a pass from.
    honest = evaluate_windows_detail(
        [score(1, "leader"), score(2, "follower_adjusted")], D("0")
    )
    assert [(v.window, v.passed) for v in honest.verdicts] == [(1, False), (2, False)]


def test_the_pairs_door_does_reach_the_equal_spellings():
    with pytest.raises(ConflictingResults):
        assess_capital_feasibility([
            (D("1.5E+6"), D("-0.05")),
            (D("1500000"), D("0.03")),
            (D("2000000"), AT_2M),
        ])

    with pytest.raises(ConflictingResults):
        assess_capital_feasibility([
            (1500000, D("-0.05")),
            ("1500000", D("0.03")),
            (D("2000000"), AT_2M),
        ])


# -- the class rather than the traced pair ----------------------------------------

#: Eight ways to write $1,500,000 that ``_level_key`` maps onto ``DESIGN_CAPITAL_LEVELS[0]``.
#: They span every source type ``calc`` accepts (``str``, ``int``, ``Decimal``), both exponent
#: notations, and trailing zeros in each. The point of enumerating them is that the finding was
#: measured on *one* pair — ``"1500000"`` beside ``Decimal("1500000")`` — and a guard that closes
#: one pair is the shape this repository keeps having to reopen.
SPELLINGS_OF_1_5M = (
    "1500000",
    "1.5E+6",
    "1500000.0",
    "1500000.00",
    1500000,
    D("1500000"),
    D("1.5E+6"),
    D("1500000.00"),
)

#: Written out rather than derived from ``len(SPELLINGS_OF_1_5M)``. A test that recomputed its own
#: expectation would agree with a list somebody shortened.
ALL_PAIRS = 28
REACHABLE_THROUGH_A_MAPPING = 22
COLLAPSED_BY_PYTHON_ITSELF = 6


def test_every_spelling_maps_onto_the_pre_registered_constant():
    """The premise. Without this the sweep below would be refusing unrelated levels."""
    for spelling in SPELLINGS_OF_1_5M:
        assessment = assess_capital_feasibility([(spelling, D("0.05")), (D("2000000"), AT_2M)])
        assert [str(level) for level in assessment.excess_by_level] == ["1500000", "2000000"], \
            spelling


def test_the_pairs_door_refuses_every_pair_of_spellings():
    """All 28 pairs, in both orders, with values that disagree and values that agree.

    Nothing here is conditioned on the two excesses differing: half of these calls supply the same
    number twice, and they are refused for the same reason — nobody can say which of two entries is
    *the* measurement at $1,500,000, and supplying both is the evidence that nobody can.
    """
    refused = 0
    for left, right in itertools.combinations(SPELLINGS_OF_1_5M, 2):
        for first, second in ((left, right), (right, left)):
            for one, other in ((AT_1_5M_FAILING, AT_1_5M_PASSING), (AT_2M, AT_2M)):
                with pytest.raises(ConflictingResults) as refusal:
                    assess_capital_feasibility([
                        (first, one), (second, other), (D("2000000"), AT_2M),
                    ])
                assert "$1500000 is named by 2 entries" in str(refusal.value)
        refused += 1
    assert refused == ALL_PAIRS


def test_the_mapping_door_refuses_every_pair_that_survives_python():
    """The other door, and the residue stated as a count rather than as prose.

    A ``dict`` literal collapses the spellings Python itself calls equal before this module can see
    them — six of the twenty-eight pairs. The refusal reaches the other twenty-two, which is every
    pair in which at least one side is a ``str``: a ``str`` is never ``==`` to the ``Decimal`` it
    spells, so both entries survive into the mapping and both arrive here.
    """
    refused = 0
    collapsed = 0
    for left, right in itertools.combinations(SPELLINGS_OF_1_5M, 2):
        book = {left: AT_1_5M_FAILING, right: AT_1_5M_PASSING, D("2000000"): AT_2M}
        if len(book) == 2:
            collapsed += 1
            continue
        with pytest.raises(ConflictingResults):
            assess_capital_feasibility(book)
        refused += 1
    assert (refused, collapsed) == (REACHABLE_THROUGH_A_MAPPING, COLLAPSED_BY_PYTHON_ITSELF)


def test_two_values_that_snap_to_one_level_are_refused_even_off_the_pre_registered_rungs():
    """``_level_key`` returns the value unsnapped when it matches no constant, and the refusal
    still holds — the collision is on the key space, not on the five §3.1 rungs.
    """
    for one, other in (
        (D("1234.0"), D("1.234E+3")),
        ("777", D("777")),
        (D("0E+3"), D("0.000")),
    ):
        with pytest.raises(ConflictingResults):
            assess_capital_feasibility([
                (one, D("0.01")), (other, D("0.02")),
                (D("1500000"), AT_1_5M_PASSING), (D("2000000"), AT_2M),
            ])
