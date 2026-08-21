"""Ticket 02 — the Independent Validator's record, its three statuses, and every refusal.

The register decides nothing. What it has to do is make some things *unsayable*: a validator with
no independence constraints, a status somebody asserted, an AI agent reading as full independence,
a validator who joins in week 4 to sign a report, and an ``UNASSIGNED`` that the code could leave
on its own. Each of those is a case below, and each expected value is written out as a literal
rather than recomputed from the module under test.

The three statuses are the point of the file. ``MACHINE-INDEPENDENT`` is genuinely better than
``NOT INDEPENDENT`` and genuinely weaker than ``EXTERNALLY REVIEWED``, because two agents from one
base model make *correlated* errors — and a correlated error is invisible to the comparison the
validation gate reads, since both lanes compute the same wrong answer and agree. So the tests here
care less about which string comes back than about which one is *unreachable* from where.
"""

import datetime
import inspect
from decimal import Decimal

import pytest

from contracts.core import ValidationStatus
from phase0 import validator as V
from phase0.audit import AuditLog
from phase0.errors import NotIndependentError
from phase0.preconditions import VALIDATOR_RECORD_KEY, PreconditionRegister
from phase0.validator import (
    AI_AGENT,
    ASSIGNED,
    EXTERNAL_REVIEW_BUDGET,
    HUMAN,
    INDEPENDENCE_CONSTRAINTS,
    PART_TIME,
    REQUIRED_SCOPE,
    UNASSIGNED,
    ExternalSpecialistReview,
    ValidatorAssignment,
    label,
    main_test_refusal,
    require_main_test_permitted,
    validation_status,
)

#: Day 0 of the 10-12 week window. Week 1 is 2026-01-05 .. 2026-01-11 inclusive, by hand:
#: 5 + 7 - 1 = 11.
PROJECT_START = "2026-01-05"
WEEK_ONE_LAST_DAY = "2026-01-11"
WEEK_TWO_FIRST_DAY = "2026-01-12"


def ai(**over):
    kwargs = dict(
        name="Validator Agent V", kind=AI_AGENT, start_date="2026-01-07",
        project_start=PROJECT_START, commitment=PART_TIME, covers=REQUIRED_SCOPE,
        accountable_human="R. Owner",
    )
    kwargs.update(over)
    return ValidatorAssignment(**kwargs)


def human(**over):
    return ai(name="V. Alidator", kind=HUMAN, accountable_human=None, **over)


def booking(**over):
    kwargs = dict(specialist="S. Pecialist", accounts=12, booked_on="2026-02-01")
    kwargs.update(over)
    return ExternalSpecialistReview(**kwargs)


@pytest.fixture
def register(tmp_path):
    return PreconditionRegister(tmp_path / "pre.json", AuditLog(tmp_path / "audit.jsonl"))


# -- the three statuses, each reachable and each reported ------------------------

def test_nothing_recorded_is_unassigned_and_not_independent(register):
    assert register.independent_validator_state() == UNASSIGNED
    assert register.validation_status() is ValidationStatus.NOT_INDEPENDENT
    assert label(register.validation_status()) == "NOT INDEPENDENT"
    assert register.validation_status().permits_main_test is False


def test_an_ai_agent_with_no_review_booked_reaches_machine_independent(register):
    register.record_validator(ai(), "R. Owner")

    assert register.independent_validator_state() == ASSIGNED
    assert register.validation_status() is ValidationStatus.MACHINE_INDEPENDENT
    assert label(register.validation_status()) == "MACHINE-INDEPENDENT"
    assert register.validation_status().permits_main_test is True


def test_booking_the_external_review_reaches_externally_reviewed(register):
    register.record_validator(ai(), "R. Owner")
    register.book_external_review(booking(), "R. Owner")

    assert register.validation_status() is ValidationStatus.EXTERNALLY_REVIEWED
    assert label(register.validation_status()) == "EXTERNALLY REVIEWED"


def test_a_human_validator_with_no_review_booked_is_not_independent(register):
    """The one case the three-tier vocabulary has no better word for.

    ``MACHINE-INDEPENDENT`` would be a lie in the label and ``EXTERNALLY REVIEWED`` is the thing
    that has not happened, so the register returns the status that blocks rather than inventing a
    fourth. §9.5 resolves the gap the same way: without external review the status is
    ``NOT INDEPENDENT`` and the main test is BLOCKED.
    """
    register.record_validator(human(), "R. Owner")

    assert register.independent_validator_state() == ASSIGNED
    assert register.validation_status() is ValidationStatus.NOT_INDEPENDENT
    assert register.independence_refusal("the main test") is not None


def test_a_human_validator_reaches_externally_reviewed_by_booking(register):
    register.record_validator(human(), "R. Owner")
    register.book_external_review(booking(), "R. Owner")
    assert register.validation_status() is ValidationStatus.EXTERNALLY_REVIEWED


def test_every_status_has_a_label_and_an_unknown_one_raises():
    assert sorted(V.LABELS.values()) == [
        "EXTERNALLY REVIEWED", "MACHINE-INDEPENDENT", "NOT INDEPENDENT"]
    assert set(V.LABELS) == set(ValidationStatus)
    with pytest.raises(ValueError) as exc:
        label("PROBABLY_FINE")
    assert "no label for validation status" in str(exc.value)


# -- NOT INDEPENDENT blocks the main test ---------------------------------------

def test_not_independent_refuses_and_the_refusal_names_the_rule_and_the_cost():
    refusal = main_test_refusal(ValidationStatus.NOT_INDEPENDENT, "the main test")

    assert refusal is not None
    assert "NOT INDEPENDENT" in refusal
    assert "§9.5" in refusal
    assert "the main test is refused" in refusal
    assert "10-15 complex accounts" in refusal
    assert "A COST TO PAY, NOT AN OPTION TO CONSIDER" in refusal
    # the four constraint ids, named in the refusal so the reader learns what would change it
    for constraint in INDEPENDENCE_CONSTRAINTS:
        assert constraint.id in refusal


def test_the_other_two_statuses_do_not_refuse():
    for status in (ValidationStatus.MACHINE_INDEPENDENT, ValidationStatus.EXTERNALLY_REVIEWED):
        assert main_test_refusal(status, "the main test") is None
        assert require_main_test_permitted(status, "the main test") is True


def test_require_main_test_permitted_raises_not_independent():
    with pytest.raises(NotIndependentError):
        require_main_test_permitted(ValidationStatus.NOT_INDEPENDENT, "the main test")


# -- a validator cannot be recorded without the constraints ---------------------

def test_every_assignment_carries_all_four_constraints():
    assert [c.id for c in ai().constraints] == [
        "separate_implementation_path",
        "no_builder_function_reuse",
        "derived_from_raw_data_and_spec",
        "reasoning_recorded_before_comparison",
    ]
    assert ai().constraints is INDEPENDENCE_CONSTRAINTS


def test_there_is_no_argument_by_which_the_constraints_could_be_shortened():
    """The structural claim, checked against the signature rather than asserted in prose."""
    import inspect

    parameters = set(inspect.signature(ValidatorAssignment.__init__).parameters)
    assert "constraints" not in parameters
    assert "independence_constraints" not in parameters
    with pytest.raises(TypeError):
        ai(constraints=())


def test_the_constraints_survive_a_round_trip_through_json(register):
    register.record_validator(ai(), "R. Owner")
    again = register.validator()
    assert [c.id for c in again.constraints] == [c.id for c in INDEPENDENCE_CONSTRAINTS]


def test_each_constraint_names_what_actually_enforces_it():
    """``checked_by`` exists so the record cannot quietly claim to be the enforcement."""
    by_id = {c.id: c.checked_by for c in INDEPENDENCE_CONSTRAINTS}
    assert "tests/test_lane_independence.py" in by_id["separate_implementation_path"]
    assert "tests/test_lane_independence.py" in by_id["no_builder_function_reuse"]
    assert "ticket 36" in by_id["derived_from_raw_data_and_spec"]
    assert "ordering_refusal" in by_id["reasoning_recorded_before_comparison"]


# -- a status cannot be asserted ------------------------------------------------

def test_no_constructor_or_method_takes_a_status():
    import inspect

    for name in ("__init__", "with_external_review", "from_dict"):
        parameters = set(inspect.signature(getattr(ValidatorAssignment, name)).parameters)
        assert not {"status", "validation_status", "validation_status_label"} & parameters, name


def test_a_tampered_status_in_the_stored_record_is_ignored(register):
    """Edit one character in the file and an AI validator must not read as EXTERNALLY REVIEWED."""
    register.record_validator(ai(), "R. Owner")

    data = register._load()
    data[VALIDATOR_RECORD_KEY]["validation_status"] = "EXTERNALLY_REVIEWED"
    data[VALIDATOR_RECORD_KEY]["validation_status_label"] = "EXTERNALLY REVIEWED"
    data[VALIDATOR_RECORD_KEY]["permits_main_test"] = True
    register._save(data)

    assert register.validation_status() is ValidationStatus.MACHINE_INDEPENDENT


def test_with_external_review_refuses_anything_that_is_not_a_booking():
    for not_a_booking in ("S. Pecialist", True, {"specialist": "S. Pecialist"}):
        with pytest.raises(TypeError) as exc:
            ai().with_external_review(not_a_booking)
        assert "booking the review, not by naming it" in str(exc.value)


def test_an_ai_validator_cannot_review_itself():
    for specialist in ("Validator Agent V", "validator agent v", "R. Owner"):
        with pytest.raises(ValueError) as exc:
            ai().with_external_review(booking(specialist=specialist))
        assert "neither the builder nor the validator" in str(exc.value)


def test_the_primary_builder_cannot_be_the_external_specialist(register):
    register.record("primary_builder", "A. Builder, full-time", "R. Owner")
    register.record_validator(ai(), "R. Owner")

    with pytest.raises(ValueError) as exc:
        register.book_external_review(booking(specialist="A. Builder"), "R. Owner")
    assert "recorded Primary Builder" in str(exc.value)
    assert register.validation_status() is ValidationStatus.MACHINE_INDEPENDENT


def test_a_review_cannot_be_booked_before_anyone_is_assigned(register):
    with pytest.raises(ValueError) as exc:
        register.book_external_review(booking(), "R. Owner")
    assert "nothing for an external review to review" in str(exc.value)
    assert register.independent_validator_state() == UNASSIGNED


# -- the external specialist review is a cost, not an option --------------------

def test_the_budget_line_is_ten_to_fifteen_accounts_and_unpriced_rather_than_free():
    assert EXTERNAL_REVIEW_BUDGET.accounts_min == 10
    assert EXTERNAL_REVIEW_BUDGET.accounts_max == 15
    assert EXTERNAL_REVIEW_BUDGET.quoted_usd is None
    assert EXTERNAL_REVIEW_BUDGET.is_quoted is False
    assert EXTERNAL_REVIEW_BUDGET.quoted_usd != Decimal("0"), (
        "'—' and '$0' are different claims: $0 says someone checked, '—' says nobody bought")
    assert EXTERNAL_REVIEW_BUDGET.standing == "A COST TO PAY, NOT AN OPTION TO CONSIDER"


def test_the_budget_line_has_no_declined_state():
    assert EXTERNAL_REVIEW_BUDGET.is_optional is False
    assert "is_optional" not in EXTERNAL_REVIEW_BUDGET.__slots__, (
        "is_optional must stay a property; a field could be set")
    for absent in ("declined", "waived", "optional", "skip", "not_required"):
        assert absent not in EXTERNAL_REVIEW_BUDGET.as_dict()
    assert EXTERNAL_REVIEW_BUDGET.as_dict()["is_optional"] is False


def test_every_assignment_carries_the_budget_line_and_none_may_decline_it():
    assert ai().external_review_budget is EXTERNAL_REVIEW_BUDGET
    assert ai().as_dict()["external_review_budget"]["is_optional"] is False


def test_a_review_covers_ten_to_fifteen_accounts_at_the_boundaries():
    assert booking(accounts=10).accounts == 10
    assert booking(accounts=15).accounts == 15
    for outside in (0, 9, 16, 200):
        with pytest.raises(ValueError) as exc:
            booking(accounts=outside)
        assert "10-15 complex accounts" in str(exc.value)


def test_a_float_cost_is_refused_by_the_frozen_numeric_policy():
    with pytest.raises(TypeError) as exc:
        booking(cost_usd=1500.0)
    assert "float is not permitted" in str(exc.value)
    assert booking(cost_usd="1500").cost_usd == Decimal("1500")


# -- the validator joins in week 1 ----------------------------------------------

def test_week_one_is_the_first_seven_days_inclusive():
    assert V.WEEK_ONE_DAYS == 7
    assert ai(start_date=PROJECT_START).start_date == datetime.date(2026, 1, 5)
    assert ai(start_date=WEEK_ONE_LAST_DAY).start_date == datetime.date(2026, 1, 11)


def test_a_start_date_outside_week_one_is_refused():
    for late in (WEEK_TWO_FIRST_DAY, "2026-02-01", "2026-03-16"):
        with pytest.raises(ValueError) as exc:
            ai(start_date=late)
        assert "starts in week 1: 2026-01-05 to 2026-01-11 inclusive" in str(exc.value)
        assert "sign a report is not independent validation" in str(exc.value)


def test_a_start_date_before_the_project_is_refused():
    with pytest.raises(ValueError):
        ai(start_date="2026-01-04")


def test_a_missing_or_unparseable_date_is_refused():
    for bad in (None, "", "next week", "05/01/2026", 20260105):
        with pytest.raises(ValueError):
            ai(start_date=bad)
        with pytest.raises(ValueError):
            ai(project_start=bad)


# -- the commitment covers the whole of the validator's work --------------------

def test_the_commitment_must_cover_golden_set_reconciliation_and_sign_off():
    assert ai().covers == ("golden_set", "reconciliation", "sign_off")
    assert REQUIRED_SCOPE == ("golden_set", "reconciliation", "sign_off")


def test_a_sign_off_only_commitment_is_refused_by_name():
    with pytest.raises(ValueError) as exc:
        ai(covers=("sign_off",))
    message = str(exc.value)
    assert "missing golden_set, reconciliation" in message
    assert "brought in at the end to sign a report" in message


def test_every_partial_scope_is_refused():
    for partial in ((), ("golden_set",), ("reconciliation",),
                    ("golden_set", "reconciliation"), ("golden_set", "sign_off")):
        with pytest.raises(ValueError):
            ai(covers=partial)


def test_an_unknown_scope_item_is_refused():
    with pytest.raises(ValueError) as exc:
        ai(covers=REQUIRED_SCOPE + ("vibes",))
    assert "unknown scope item" in str(exc.value)


def test_the_commitment_level_has_no_value_meaning_available_on_request():
    assert V.COMMITMENT_LEVELS == ("PART_TIME", "FULL_TIME")
    for bad in ("AD_HOC", "ON_CALL", "AS_NEEDED", "SIGN_OFF_ONLY", "part_time", None):
        with pytest.raises(ValueError) as exc:
            ai(commitment=bad)
        assert "available when we need them" in str(exc.value)


# -- UNASSIGNED is not a state the code can leave on its own --------------------

def test_a_placeholder_name_is_refused():
    for placeholder in ("TBD", "  tba ", "unassigned", "the validator", "an AI agent",
                        "someone", "n/a", "-", "", None, "placeholder", "recorded-for-test"):
        with pytest.raises(ValueError) as exc:
            ai(name=placeholder)
        assert "must be a name" in str(exc.value)
        assert "UNASSIGNED look like a state the code can leave" in str(exc.value)


def test_an_ai_validator_needs_a_named_accountable_human():
    for missing in (None, "", "TBD"):
        with pytest.raises(ValueError) as exc:
            ai(accountable_human=missing)
        assert "the human accountable for the AI validator's output" in str(exc.value)


def test_the_module_defines_no_default_or_example_assignment():
    """A module-level instance is how a default gets in. There must be none."""
    instances = [name for name, value in vars(V).items()
                 if isinstance(value, (ValidatorAssignment, ExternalSpecialistReview))]
    assert instances == [], (
        "phase0.validator defines {} at module level. A ready-made assignment or booking is a "
        "default validator by another name, and it would make UNASSIGNED a state the code could "
        "leave without anyone deciding anything.".format(", ".join(instances))
    )


def test_the_register_will_not_build_an_assignment_from_a_name(register):
    for not_an_assignment in ("V. Alidator", {"name": "V. Alidator"}, None, True):
        with pytest.raises(TypeError) as exc:
            register.record_validator(not_an_assignment, "R. Owner")
        assert "record_validator takes a ValidatorAssignment" in str(exc.value)
    assert register.independent_validator_state() == UNASSIGNED


def test_a_bare_attribution_satisfies_15_4_and_is_still_unassigned_here(register):
    """The gap, pinned so it stays visible rather than becoming folklore."""
    register.record("independent_validator", "V. Alidator, contract #7", "R. Owner")

    assert register.satisfied()["independent_validator"] == "V. Alidator, contract #7"
    assert register.independent_validator_state() == UNASSIGNED
    assert register.validation_status() is ValidationStatus.NOT_INDEPENDENT
    assert register.validator() is None
    report = "\n".join(register.validator_report())
    assert "was not recorded through the ticket-02 register" in report


def test_a_bare_attribution_may_not_overwrite_a_ticket_02_record(register):
    register.record_validator(ai(), "R. Owner")

    with pytest.raises(ValueError) as exc:
        register.record("independent_validator", "V. Alidator", "R. Owner")
    assert "refusing to replace it with the bare attribution" in str(exc.value)
    assert register.validation_status() is ValidationStatus.MACHINE_INDEPENDENT


def test_the_other_three_preconditions_are_unaffected(register):
    for key in ("primary_builder", "data_budget", "capacity_reserved"):
        register.record(key, "recorded", "R. Owner")
    assert len(register.unmet()) == 1
    assert register.unmet() == ["Independent Validator assigned (ticket 02)"]


# -- the correlated-error limitation travels with the record --------------------

def test_an_ai_assignment_states_the_correlated_error_limitation():
    note = ai().correlated_error_note
    assert "same base model" in note
    assert "CORRELATED errors" in note
    assert "MACHINE-INDEPENDENT at best until the external specialist review" in note
    assert "a cost to pay, not an option to consider" in note


def test_a_human_assignment_carries_no_correlated_error_note():
    assert human().correlated_error_note is None


def test_booking_the_review_narrows_the_limitation_rather_than_deleting_it():
    reviewed = ai().with_external_review(booking())
    note = reviewed.correlated_error_note
    assert "CORRELATED errors" in note, "paying the cost does not delete the shared prior"
    assert "reduces the correlated-error residue and does not remove it" in note
    assert "S. Pecialist, 12 complex accounts" in note


# -- reasoning before comparison, in a form a later stage can check -------------

SEALED = "2026-03-01T09:00:00Z"
COMPARED = "2026-03-01T14:00:00Z"


def test_sealing_strictly_before_the_comparison_passes():
    assert ai().ordering_refusal(SEALED, COMPARED) is None


def test_sealing_after_the_comparison_is_refused():
    refusal = ai().ordering_refusal(COMPARED, SEALED)
    assert refusal is not None
    assert "reasoning_recorded_before_comparison" in refusal
    assert "NOT INDEPENDENT" in refusal


def test_sealing_at_the_same_instant_is_refused():
    """'At the same instant' is not evidence of order, and a coarse clock must not buy a pass."""
    assert ai().ordering_refusal(SEALED, SEALED) is not None


def test_a_missing_timestamp_is_not_a_passing_check():
    for pair in ((None, COMPARED), (SEALED, None), (None, None)):
        refusal = ai().ordering_refusal(*pair)
        assert refusal is not None
        assert "A missing timestamp is not a passing check" in refusal


# -- the machine-readable record ------------------------------------------------

def test_the_record_exposes_the_two_fields_ticket_02_asks_for():
    record = ai().as_dict()
    assert record["independent_validator"] == ASSIGNED
    assert record["validation_status"] == "MACHINE_INDEPENDENT"
    assert record["validation_status_label"] == "MACHINE-INDEPENDENT"
    assert record["permits_main_test"] is True
    assert record["starts_in_week_one"] is True
    assert [c["id"] for c in record["independence_constraints"]] == [
        c.id for c in INDEPENDENCE_CONSTRAINTS]


def test_the_record_round_trips(register):
    original = ai().with_external_review(booking(cost_usd="1500"))
    register.record_validator(original, "R. Owner")
    again = register.validator()

    assert again.as_dict() == original.as_dict()
    assert again.external_review.cost_usd == Decimal("1500")
    assert again.validation_status() is ValidationStatus.EXTERNALLY_REVIEWED


def test_recording_a_validator_is_audited(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    reg = PreconditionRegister(tmp_path / "pre.json", log)
    reg.record_validator(ai(), "Research Owner")

    actions = [e.action for e in log.entries()]
    assert actions == ["precondition.record", "validator.record"]
    detail = log.entries()[-1].detail
    assert detail["name"] == "Validator Agent V"
    assert detail["kind"] == "AI_AGENT"
    assert detail["validation_status"] == "MACHINE_INDEPENDENT"
    assert detail["constraints"] == [c.id for c in INDEPENDENCE_CONSTRAINTS]
    assert log.verify()


def test_validation_status_of_no_assignment_is_not_independent():
    assert validation_status(None) is ValidationStatus.NOT_INDEPENDENT


def test_the_placeholder_list_is_a_tripwire_and_says_so():
    """The blocklist was written without ``todo`` and accepted it for a day.

    That is the argument against relying on it, and it is why the constant's own comment now says
    the list is a tripwire rather than a guarantee. What bounds the deliberate case is one layer
    up: ``record_validator`` takes a ``requester`` and writes it to the hash-chained audit log, so
    a placeholder recorded here is attributable to whoever recorded it.

    Pinned both ways. If someone deletes a spelling the list already learned, this goes red; if
    someone deletes the comment that says the list is not a guarantee, the second half does.
    """
    from phase0 import validator as _V

    for spelling in ("todo", "TODO", "  ToDo  ", "fixme", "dummy", "foo", "test"):
        with pytest.raises(ValueError):
            ai(name=spelling, kind=HUMAN, accountable_human=None)

    source = inspect.getsource(_V)
    assert "tripwire, not a guarantee" in source
    assert "record_validator" in source.split("_NON_NAMES = frozenset")[0][-1400:]
