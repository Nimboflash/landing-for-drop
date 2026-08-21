"""Ticket 11 — every parameter written out again by hand, and the freeze that closes the set.

Nothing here is recomputed from :mod:`phase0.parameters`. :data:`EXPECTED` is a second transcription
of ``docs/phase-0-preregistration.md`` and ``docs/decision-engine-addendum.md``, made from the
documents rather than from the module, and the module is checked against it. A test that read the
table it is testing would pass on any table at all — including one where somebody moved 40% to 55%
and updated the docstring beside it.

Four things this file exists to make expensive:

* **a parameter that quietly disagrees with the document.** :data:`EXPECTED` is exhaustive in both
  directions: a key in the module and not here fails, and a key here and not in the module fails.
  Adding a parameter therefore costs a transcription from the document, which is the point;
* **a threshold living in two places.** :data:`MIGRATED` is every module constant that now reads
  from the frozen set, held equal to it here; :data:`UNMIGRATED` is every copy that is still a copy,
  named and held equal to the frozen value it duplicates. The second list is the honest one — a
  partial migration that says so is worth more than a complete one nobody checked;
* **the sentence somebody would rather rewrite.** §11.3's negative-result wording is pinned
  character for character, including the full stop, at the moment before it is the sentence that has
  to be published;
* **a freeze that nobody performed.** The register must read ``NOT FROZEN`` in this repository, and
  no test here may leave it otherwise. Every test that freezes anything does so on a
  :class:`~phase0.governance.GovernanceMachine` under ``tmp_path``; the module-level
  :data:`~phase0.parameters.PARAMETERS` is read-only and shared, and there is no writer for it to
  be endangered by.

Python 3.9: no ``|`` unions, no ``list[str]``.
"""

import datetime
import inspect
from decimal import Decimal

import pytest

from phase0.audit import AuditLog
from phase0.cli import build_parser, main
from phase0.errors import FrozenError, ParameterSetNotWritable
from phase0.governance import PARAMETERS_FROZEN, GovernanceMachine
from phase0.parameters import (
    ACTION_CHANGE_REFUSED,
    ACTION_FREEZE,
    BANDS,
    BLOCKS,
    CLAUSES,
    COUNT,
    DAYS,
    FLAG,
    FROZEN,
    FROZEN_WITHOUT_A_RECORD,
    NOT_FROZEN,
    NOT_PREREGISTERED,
    PARAMETERS,
    RATIO,
    SECONDS,
    TEXT,
    UNMINTED,
    USD,
    USD_LEVELS,
    WINDOWS,
    FreezeRecord,
    Parameter,
    ParameterRegister,
    ParameterSet,
    UnknownParameter,
)
from phase0.runs import RunRecord

# -- the transcription ----------------------------------------------------------
#
# key -> (value, unit, source). Values are written the way the documents write them: a Decimal for
# every ratio and dollar amount, an int for every count, and the exact string for every wording.
# Nothing below is computed — ``2592000`` is spelled out rather than written ``30 * 86400``, because
# a test that spells a constant as an expression over the same factors the code used moves with the
# code and pins nothing about it.

WINDOWS_EXPECTED = (
    ("2023-01", "2023-06", "2023-07", "2023-12"),
    ("2023-07", "2023-12", "2024-01", "2024-06"),
    ("2024-01", "2024-06", "2024-07", "2024-12"),
    ("2024-07", "2024-12", "2025-01", "2025-06"),
)

#: §11.3, character for character, transcribed from the document's own block quote. Written as one
#: string with the line break of the document removed, which is the only edit: the document wraps it
#: across two lines and a wrapped sentence is the same sentence.
NEGATIVE_RESULT = (
    "No sufficient persistent and copyable wallet-selection edge was found for the Ethereum "
    "Mainnet target population and capital profile."
)

#: §11.3's "Not:" block, lowercased into a sentence fragment the way the module carries it.
FORBIDDEN_FRAMING = "wallet-based copy trading does not work on any blockchain"

#: §11.2's four bullets plus its closing sentence, in the document's order.
ARBITRUM = (
    "does not participate in the main gate",
    "may not be used to rescue a weak Ethereum result",
    "does not permit thresholds to be changed after results are seen",
    "is reported only as a check on generalisability",
    "must be pre-registered as a secondary diagnostic, not introduced after Ethereum fails",
)

#: §10, transcribed from the line ``Sensitivity by activity band:  20–99 / 100–499 / 500–1,000
#: valid buys``. Two edits, neither of them to a number: the document's en-dashes become hyphens and
#: its thousands comma is dropped, because the labels are dictionary keys and a report column header
#: rather than prose. The bounds are inclusive at both ends, which is how "20–99" reads.
ACTIVITY_BANDS_EXPECTED = (
    ("20-99", 20, 99),
    ("100-499", 100, 499),
    ("500-1000", 500, 1000),
)

#: Addendum §9.1's three lines, in its order.
DEAD_POOL = (
    "no successful swap for 30 days",
    "executable exit value is below the minimum threshold",
    "no validated replacement pool exists",
)

EXPECTED = {
    # -- §6.3, §7: the four walk-forward windows --
    "windows.walk_forward": (WINDOWS_EXPECTED, WINDOWS, "§6.3"),
    "windows.count": (4, COUNT, "§6.3"),
    "windows.required_to_pass": (3, COUNT, "§7"),

    # -- addendum §7, §6.1, §6.2: the two-stage eligibility buffer and the universe floor --
    "eligibility.potential_buys.floor": (10, COUNT, "addendum §7"),
    "eligibility.potential_buys.ceiling": (1200, COUNT, "addendum §7"),
    "eligibility.valid_buys.floor": (20, COUNT, "§6.2"),
    "eligibility.valid_buys.ceiling": (1000, COUNT, "§6.2"),
    "universe.minimum_eligible_accounts": (10000, COUNT, "§6.1"),

    # -- §6.5: clamp(1% of eligible universe, 250, 1000) --
    "selection.rate_of_eligible_universe": (Decimal("0.01"), RATIO, "§6.5"),
    "selection.minimum": (250, COUNT, "§6.5"),
    "selection.maximum": (1000, COUNT, "§6.5"),

    # -- §3.1, §7.2: the five capital levels, and the two that gate --
    "capital.levels": (
        (Decimal("100000"), Decimal("250000"), Decimal("500000"),
         Decimal("1500000"), Decimal("2000000")),
        USD_LEVELS, "§3.1",
    ),
    "capital.gating_levels": ((Decimal("1500000"), Decimal("2000000")), USD_LEVELS, "§7.2"),

    # -- addendum §8: max($0.01, 0.01% of transaction notional) --
    "netting.residual_tolerance.floor_usd": (Decimal("0.01"), USD, "addendum §8"),
    "netting.residual_tolerance.notional_rate": (Decimal("0.0001"), RATIO, "addendum §8"),

    # -- addendum §9.1: the three-part dead-pool conjunction --
    "dead_pool.conditions": (DEAD_POOL, CLAUSES, "addendum §9.1"),
    "dead_pool.inactivity_seconds": (2592000, SECONDS, "addendum §9.1"),
    "dead_pool.all_conditions_required": (True, FLAG, "addendum §9.1"),

    # -- §4.7: the token-age bucket boundaries --
    "token_age.bucket_a.blocks": (10, BLOCKS, "§4.7"),
    "token_age.bucket_b.seconds": (3600, SECONDS, "§4.7"),
    "token_age.bucket_c.seconds": (86400, SECONDS, "§4.7"),
    "token_age.first_hour_buckets": (("A", "B"), CLAUSES, "§4.7"),

    # -- §7.1, §7.3, §8.3: the gate thresholds --
    "gate.starting_mean_threshold": (Decimal("0.15"), RATIO, "§8.3"),
    "gate.first_hour_edge_share_max": (Decimal("0.40"), RATIO, "§7.1"),
    "gate.minimum_total_positive_edge": (Decimal("0.05"), RATIO, "§7.1"),
    "gate.significance.null_percentile": (Decimal("0.95"), RATIO, "§7.3"),
    "gate.significance.max_empirical_p": (Decimal("0.05"), RATIO, "§7.3"),

    # -- addendum §9.4, §9.5: execution cost caps, long tail, the fill requirement --
    "execution.cost_cap.major": (Decimal("0.01"), RATIO, "addendum §9.5"),
    "execution.cost_cap.mid_cap": (Decimal("0.02"), RATIO, "addendum §9.5"),
    "execution.long_tail_treatment": ("EXCLUDED FROM ETHEREUM PHASE 0", TEXT, "addendum §9.5"),
    "execution.minimum_fill_ratio": (Decimal("0.90"), RATIO, "addendum §9.4"),

    # -- addendum §9.3: the Copy Retention display floor --
    "copy_retention.display_floor": (Decimal("0.02"), RATIO, "addendum §9.3"),

    # -- §4.4, §4.8: the measurement horizon and the window-edge extension --
    "measurement.horizon_days": (30, DAYS, "§4.4"),
    "measurement.window_edge_extension_days": (30, DAYS, "§4.8"),

    # -- §10: the activity bands, and §9.5: the external review --
    "reporting.activity_bands": (ACTIVITY_BANDS_EXPECTED, BANDS, "§10"),
    "validation.complex_accounts_min": (10, COUNT, "§9.5"),
    "validation.complex_accounts_max": (15, COUNT, "§9.5"),

    # -- §6.6: the benchmarks --
    "benchmark.primary_matched_controls": (5, COUNT, "§6.6"),
    "benchmark.robustness_controls": (5, COUNT, "§6.6"),
    "benchmark.covariate_balance_smd_max": (Decimal("0.10"), RATIO, "§6.6"),

    # -- §8.2, §8.3: the null --
    "null.runs_per_window_per_column": (1000, COUNT, "§8.2"),
    "null.pass_rate_target": (Decimal("0.05"), RATIO, "§8.3"),

    # -- addendum §11: the master seed, and the policy that is what is actually frozen --
    "seeds.policy": ("one master seed, deterministic child seeds", TEXT, "addendum §11"),
    "seeds.derivation_rule": (
        "child_seed = HMAC-SHA256(key=master_seed, msg=f'{commit}|{purpose}|{index}') "
        "interpreted as a big-endian 256-bit integer",
        TEXT, "addendum §11",
    ),
    "seeds.field_separator": ("|", TEXT, "addendum §11"),
    "seeds.master_seed_bytes": (32, COUNT, "addendum §11"),
    "seeds.master_seed": (None, UNMINTED, "addendum §11"),

    # -- §3, §11.2: scope, and the chain that is outside the gate --
    "scope.primary_chain": ("Ethereum mainnet", TEXT, "§3"),
    "scope.arbitrum.standing": (
        "SECONDARY DIAGNOSTIC — OUTSIDE THE GATE", TEXT, "§11.2"),
    "scope.arbitrum.participates_in_gate": (False, FLAG, "§11.2"),
    "scope.arbitrum.constraints": (ARBITRUM, CLAUSES, "§11.2"),

    # -- §11.3: the wording of a negative result --
    "reporting.negative_result_wording": (NEGATIVE_RESULT, TEXT, "§11.3"),
    "reporting.forbidden_negative_framing": (FORBIDDEN_FRAMING, TEXT, "§11.3"),
}


# -- fixtures -------------------------------------------------------------------

@pytest.fixture
def audit(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl")


@pytest.fixture
def register(tmp_path, audit):
    """A register over a governance machine of its own, under ``tmp_path``.

    The parameter table is the real one — :data:`~phase0.parameters.PARAMETERS` — because that is
    what these tests are about. Only the *state* is temporary, and it has to be: a test that froze
    the repository's own machine would leave ``PARAMETERS_FROZEN`` behind it, which is a claim that
    a person acted.
    """
    return ParameterRegister(
        GovernanceMachine(tmp_path / "governance.json", audit), audit)


def freeze_record(**over):
    kwargs = dict(requester="N. Alishahi", commit="5b4565d", frozen_on="2026-08-15",
                  note="ticket 11")
    kwargs.update(over)
    return FreezeRecord(**kwargs)


# -- every parameter, against the document --------------------------------------

def test_every_key_in_the_document_is_in_the_set_and_nothing_else_is():
    """Exhaustive in both directions. A new parameter costs a transcription or the suite is red."""
    assert set(PARAMETERS.keys()) == set(EXPECTED), (
        "missing from the set: {}\nnot transcribed here: {}".format(
            sorted(set(EXPECTED) - set(PARAMETERS.keys())),
            sorted(set(PARAMETERS.keys()) - set(EXPECTED)),
        )
    )


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_parameter_matches_the_document(key):
    value, unit, source = EXPECTED[key]
    parameter = PARAMETERS.parameter(key)
    assert parameter.value == value
    assert parameter.unit == unit
    assert parameter.source == source


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_parameter_types_are_exact(key):
    """The value that comes back is the value that went in — no float anywhere on the path."""
    expected, unit, _source = EXPECTED[key]
    value = PARAMETERS.value(key)
    assert not isinstance(value, float)
    if unit in (RATIO, USD):
        assert isinstance(value, Decimal)
        # str(), not float(): a Decimal that lost digits still compares equal to a shorter one
        # written the same way, and the digits are the whole reason these are Decimals.
        assert str(value) == str(expected)
    elif unit == USD_LEVELS:
        assert all(isinstance(item, Decimal) for item in value)
        assert [str(item) for item in value] == [str(item) for item in expected]
    elif unit in (COUNT, BLOCKS, SECONDS, DAYS):
        assert isinstance(value, int) and not isinstance(value, bool)
    elif unit == FLAG:
        assert isinstance(value, bool)
    elif unit == UNMINTED:
        assert value is None


def test_a_float_cannot_be_stored_as_a_ratio():
    """0.15 as a float is a different gate. Construction fails rather than the value drifting."""
    with pytest.raises(Exception) as exc:
        Parameter("gate.starting_mean_threshold", 0.15, RATIO, "§8.3")
    assert "float" in str(exc.value).lower()


def test_a_float_cannot_be_stored_as_a_count():
    with pytest.raises(TypeError) as exc:
        Parameter("universe.minimum_eligible_accounts", 10000.0, COUNT, "§6.1")
    assert "exact int" in str(exc.value)


def test_true_is_not_a_count():
    """``True`` is an ``int`` in Python, and 'True accounts' is not a universe floor."""
    with pytest.raises(TypeError):
        Parameter("universe.minimum_eligible_accounts", True, COUNT, "§6.1")


def test_a_parameter_without_a_citation_is_refused():
    with pytest.raises(ValueError) as exc:
        Parameter("gate.invented", "0.55", RATIO, "")
    assert "source section" in str(exc.value)


def test_an_unknown_unit_is_refused_rather_than_passed_through():
    with pytest.raises(ValueError) as exc:
        Parameter("gate.invented", "0.55", "percent", "§7.1")
    assert "unknown unit" in str(exc.value)


def test_asking_for_a_threshold_nobody_pre_registered_raises():
    """Returning ``None`` would let a stage run on an invented number."""
    with pytest.raises(UnknownParameter):
        PARAMETERS.value("gate.long_tail_cost_cap")


def test_a_duplicate_key_is_refused():
    with pytest.raises(ValueError) as exc:
        ParameterSet((
            Parameter("a.b", 1, COUNT, "§1"),
            Parameter("a.b", 2, COUNT, "§1"),
        ))
    assert "duplicate parameter" in str(exc.value)


# -- the two the ticket calls out separately ------------------------------------

def test_the_negative_result_wording_is_pinned_character_for_character():
    """§11.3. Fixed here, before any result exists, because after one exists it is contested."""
    wording = PARAMETERS.value("reporting.negative_result_wording")
    assert wording == (
        "No sufficient persistent and copyable wallet-selection edge was found for the Ethereum "
        "Mainnet target population and capital profile."
    )
    assert len(wording) == 133
    assert wording.endswith("capital profile.")
    assert "Ethereum Mainnet" in wording
    assert PARAMETERS.source("reporting.negative_result_wording") == "§11.3"


def test_the_negative_result_wording_names_its_scope():
    """A finding that dropped the scope would be a finding nobody measured.

    §11.3's "Not:" line is carried as its own parameter so the over-claim has a name, and the two
    are different strings.
    """
    wording = PARAMETERS.value("reporting.negative_result_wording")
    forbidden = PARAMETERS.value("reporting.forbidden_negative_framing")
    assert forbidden == "wallet-based copy trading does not work on any blockchain"
    assert forbidden != wording
    assert "any blockchain" not in wording


def test_arbitrum_is_recorded_now_as_secondary_and_outside_the_gate():
    """§11.2, and the timing is the content: it is here *before* any Ethereum result exists."""
    assert PARAMETERS.value("scope.arbitrum.standing") == (
        "SECONDARY DIAGNOSTIC — OUTSIDE THE GATE")
    assert PARAMETERS.value("scope.arbitrum.participates_in_gate") is False
    assert PARAMETERS.value("scope.arbitrum.constraints") == ARBITRUM
    for key in ("scope.arbitrum.standing", "scope.arbitrum.participates_in_gate",
                "scope.arbitrum.constraints"):
        assert PARAMETERS.source(key) == "§11.2"


def test_arbitrum_cannot_be_moved_inside_the_gate_by_any_writer():
    """There is no writer. The flag is not settable, and the set has no mutator to set it with."""
    for name in ("add", "update", "set", "__setitem__", "with_override", "replace"):
        assert not hasattr(ParameterSet, name), (
            "ParameterSet grew a {!r}; a stage could then be handed a set that differs from the "
            "one the freeze covered".format(name)
        )
    assert PARAMETERS.value("scope.primary_chain") == "Ethereum mainnet"


# -- the freeze record ----------------------------------------------------------

def test_a_freeze_record_cannot_be_built_without_a_person():
    for name in (None, "", "  ", "n/a", "tbd", "unknown", "someone"):
        with pytest.raises(ValueError) as exc:
            freeze_record(requester=name)
        assert "must be a name" in str(exc.value)


def test_a_freeze_record_refuses_a_moving_reference_as_its_commit():
    for moving in ("HEAD", "main", "master", "latest"):
        with pytest.raises(ValueError) as exc:
            freeze_record(commit=moving)
        assert "must be a hash" in str(exc.value)


def test_a_freeze_record_refuses_a_commit_too_short_to_identify_anything():
    with pytest.raises(ValueError) as exc:
        freeze_record(commit="5b456")
    assert "hexadecimal" in str(exc.value)


def test_a_freeze_record_requires_a_date():
    with pytest.raises(ValueError) as exc:
        freeze_record(frozen_on=None)
    assert "required" in str(exc.value)


def test_a_freeze_record_carries_the_commit_and_the_date():
    record = freeze_record()
    assert record.requester == "N. Alishahi"
    assert record.commit == "5b4565d"
    assert record.frozen_on == datetime.date(2026, 8, 15)
    assert record.as_dict()["frozen_on"] == "2026-08-15"


def test_freeze_takes_a_record_and_nothing_else(register):
    """No ``requester=`` string overload. A defaulted commit names no text at all."""
    with pytest.raises(TypeError) as exc:
        register.freeze("N. Alishahi")
    assert "FreezeRecord" in str(exc.value)


def test_no_freeze_method_has_a_default_argument():
    """The whole boundary, checked structurally: nothing here can freeze without being told who.

    ``phase0.parameters`` may not acquire a ``freeze(requester="the owner")`` or a
    ``freeze_if_ready()``. A default requester is a freeze attributable to nobody, and
    ``PARAMETERS_FROZEN`` is a record of a human act.
    """
    signature = inspect.signature(ParameterRegister.freeze)
    parameters = [p for name, p in signature.parameters.items() if name != "self"]
    assert [p.name for p in parameters] == ["record"]
    assert parameters[0].default is inspect.Parameter.empty

    for name, _member in inspect.getmembers(ParameterRegister, inspect.isfunction):
        assert "if_ready" not in name and "auto" not in name, (
            "ParameterRegister grew {!r}; the freeze is a human act and has exactly one "
            "entry point".format(name)
        )

    for field in ("requester", "commit", "frozen_on"):
        assert inspect.signature(FreezeRecord.__init__).parameters[field].default \
            is inspect.Parameter.empty


# -- not frozen, and staying that way -------------------------------------------

def test_a_fresh_register_is_not_frozen(register):
    assert register.frozen is False
    assert register.freeze_status() == NOT_FROZEN
    assert register.freeze_record() is None
    assert any("NOT FROZEN" in line for line in register.report())


def test_the_values_are_readable_before_the_freeze(register):
    """Refusing to answer until the freeze would send every stage back to a local copy."""
    assert register.value("gate.first_hour_edge_share_max") == Decimal("0.40")
    assert register.frozen is False


def test_this_repository_has_not_frozen_its_parameters(tmp_path, audit):
    """The state this repository is in, asserted rather than assumed.

    A fresh machine reads ``PARAMETERS_OPEN``, and nothing in ``phase0.parameters`` advances it. If
    this ever fails, either a test left a freeze behind or a code path acquired one.
    """
    machine = GovernanceMachine(tmp_path / "governance.json", audit)
    assert machine.state != PARAMETERS_FROZEN
    assert ParameterRegister(machine, audit).freeze_status() == NOT_FROZEN


# -- the freeze, and the refusal that follows it --------------------------------

def test_freezing_records_the_commit_the_date_and_the_person(register, audit):
    state = register.freeze(freeze_record())
    assert state == PARAMETERS_FROZEN
    assert register.frozen is True
    assert register.freeze_status() == FROZEN

    record = register.freeze_record()
    assert record.requester == "N. Alishahi"
    assert record.commit == "5b4565d"
    assert record.frozen_on.isoformat() == "2026-08-15"

    entry = [e for e in audit.entries() if e.action == ACTION_FREEZE][-1]
    assert entry.requester == "N. Alishahi"
    assert entry.detail["commit"] == "5b4565d"
    assert entry.detail["frozen_on"] == "2026-08-15"
    assert entry.detail["parameters"] == len(PARAMETERS)
    audit.verify()


def test_a_freeze_through_the_looser_path_is_a_status_and_not_an_error(register, audit):
    """``phase0 freeze PARAMETERS_FROZEN --requester X`` names a person and no commit.

    That is a documentation gap, not a broken run: every write is still refused, and what is
    missing is the evidence of *which* text was frozen. Reported, not raised.
    """
    register._governance.transition(PARAMETERS_FROZEN, "R. Owner")
    assert register.frozen is True
    assert register.freeze_status() == FROZEN_WITHOUT_A_RECORD
    assert register.freeze_record() is None
    assert any("commit and the date" in line for line in register.report())


def test_a_change_after_the_freeze_is_refused_with_the_requester_named(register, audit):
    """Ticket 11's demo, and the audit entry is the half that matters."""
    register.freeze(freeze_record())

    with pytest.raises(FrozenError) as exc:
        register.request_change(
            "gate.first_hour_edge_share_max", "0.55", "R. Vance",
            reason="the window would pass at 55%")

    message = str(exc.value)
    assert "gate.first_hour_edge_share_max" in message
    assert "R. Vance" in message
    assert "0.40" in message and "0.55" in message
    assert "frozen at commit 5b4565d on 2026-08-15 by N. Alishahi" in message
    assert "INVALIDATED" in message

    entry = [e for e in audit.entries() if e.action == ACTION_CHANGE_REFUSED][-1]
    assert entry.requester == "R. Vance"
    assert entry.detail["key"] == "gate.first_hour_edge_share_max"
    assert entry.detail["current_value"] == "0.40"
    assert entry.detail["proposed_value"] == "0.55"
    assert entry.detail["outcome"] == "REJECTED"
    assert entry.detail["freeze_status"] == FROZEN
    assert entry.detail["freeze_record"]["requester"] == "N. Alishahi"
    assert entry.detail["reason"] == "the window would pass at 55%"
    audit.verify()


def test_a_change_before_the_freeze_is_refused_differently_and_still_recorded(register, audit):
    """Two refusals, because they cost different things and the audit reader has to tell them apart.

    Before the freeze the honest answer is "this register was never the editor"; answering "frozen"
    would be a false statement about the state of the experiment.
    """
    with pytest.raises(ParameterSetNotWritable) as exc:
        register.request_change("gate.starting_mean_threshold", "0.10", "R. Vance")

    message = str(exc.value)
    assert "NOT FROZEN — that part is true and is not the reason" in message
    assert "R. Vance" in message

    entry = [e for e in audit.entries() if e.action == ACTION_CHANGE_REFUSED][-1]
    assert entry.requester == "R. Vance"
    assert entry.detail["freeze_status"] == NOT_FROZEN
    assert entry.detail["freeze_record"] is None
    assert entry.detail["outcome"] == "REJECTED"


def test_the_refusal_is_unconditional_on_the_content_of_the_change(register):
    """A widening, a clarification and a typo fix are all refused, and for the same reason."""
    register.freeze(freeze_record())
    for proposed in ("0.40", "0.4", Decimal("0.40")):
        with pytest.raises(FrozenError):
            register.request_change(
                "gate.first_hour_edge_share_max", proposed, "R. Vance",
                reason="only restating the same number")


def test_an_unknown_key_raises_without_writing_an_audit_entry(register, audit):
    """A typo is a caller bug. Logging it as an attempted change puts noise in the one record
    that has to stay legible."""
    before = len(audit.entries())
    with pytest.raises(UnknownParameter):
        register.request_change("gate.no_such_threshold", "0.55", "R. Vance")
    assert len(audit.entries()) == before


def test_a_change_request_from_nobody_is_refused(register):
    for name in (None, "", "tbd", "n/a"):
        with pytest.raises(ValueError) as exc:
            register.request_change("gate.starting_mean_threshold", "0.10", name)
        assert "must be a name" in str(exc.value)


#: The template placeholders that must not be able to freeze a pre-registration, in the scripts a
#: reader of this project actually pastes from. The first entry is not hypothetical: it is the
#: string that froze this repository's parameter set on 2026-08-16, copied out of a command whose
#: ``--requester "<نام شما>"`` was never filled in.
PASTED_PLACEHOLDERS = ("<نام شما>", "<your name>", "<name>", "[NAME]", "{name}", "《姓名》", "____")


@pytest.mark.parametrize("pasted", PASTED_PLACEHOLDERS)
def test_a_freeze_cannot_be_recorded_under_a_pasted_placeholder(tmp_path, pasted):
    """The leak that actually happened, and the reason a word list was never going to close it.

    ``NON_NAMES`` catches the spellings somebody thought of, and every one of them is English. A
    person following this project's own instructions pasted ``--requester "<نام شما>"`` — Persian
    for "your name" — and the register recorded the pre-registration as frozen by that, under a
    real commit and a real date. Nothing in the suite objected, and a freeze carrying a plausible
    commit is worse than one carrying an obvious blank: it looks signed.

    What closes it is a shape rather than a vocabulary. Every documentation convention marks the
    replace-me part by wrapping it, so the wrapping is the signal and the contents never have to be
    read. That is why this case is parametrised across scripts — the rule must not care which one.
    """
    with pytest.raises(ValueError) as exc:
        FreezeRecord(requester=pasted, commit="e5cb2ea", frozen_on="2026-08-16")

    message = str(exc.value)
    assert "must be a name" in message
    assert "attributable to nobody" in message


def test_a_real_name_is_accepted_in_a_non_latin_script():
    """The rule refuses a shape, so it must not have refused a language along with it.

    A guard that closed the placeholder hole by rejecting anything it could not read would have
    made the register unusable by most of the people who might sign it, and that failure would show
    up as somebody transliterating their own name to get past a check — which is a worse record
    than the one this is all meant to protect.
    """
    record = FreezeRecord(requester="علی رضایی", commit="e5cb2ea", frozen_on="2026-08-16")
    assert record.requester == "علی رضایی"


def test_a_name_wrapped_in_parentheses_is_refused_and_that_is_the_intended_trade():
    """The rule's false positive, pinned so it is a decision rather than a surprise.

    ``(N. Alishahi)`` is a name and this refuses it, because parentheses are also how half the
    world's documentation marks a placeholder. The trade is deliberate and asymmetric: a false
    positive costs one refusal carrying a message that says exactly what to do, and a false
    negative costs a pre-registration frozen by nobody, discovered — if ever — long after the
    result it was supposed to have preceded.
    """
    with pytest.raises(ValueError) as exc:
        FreezeRecord(requester="(N. Alishahi)", commit="e5cb2ea", frozen_on="2026-08-16")
    assert "wrapped in (...)" in str(exc.value)


def test_a_register_without_an_audit_log_is_refused(tmp_path):
    """A refusal that left no record is the failure this class exists to prevent."""
    machine = GovernanceMachine(tmp_path / "g.json", AuditLog(tmp_path / "a.jsonl"))
    with pytest.raises(ValueError) as exc:
        ParameterRegister(machine, None)
    assert "audit log" in str(exc.value)


def test_governance_refuses_a_parameter_write_once_frozen(tmp_path, audit):
    """The older ``GovernanceMachine.write_parameter`` path is closed by the same state."""
    machine = GovernanceMachine(tmp_path / "governance.json", audit)
    machine.write_parameter("scratch", 1, "R. Owner")
    machine.transition(PARAMETERS_FROZEN, "R. Owner")
    with pytest.raises(FrozenError):
        machine.write_parameter("scratch", 2, "R. Owner")


# -- readable by every downstream stage, and carried nowhere twice ---------------
#
# MIGRATED: a module constant that now READS the frozen value. Held equal here so that re-inlining
# a literal with a different number goes red, and so the list of what was migrated is a list
# somebody has to maintain rather than a claim in a docstring.
#
# UNMIGRATED: a copy that is still a copy. Each entry says why it was left, and each is held equal
# to the frozen value it duplicates — which is the most a test can do about a duplicate it did not
# remove. This list is the honest half of ticket 11's third criterion.

MIGRATED = (
    ("depth.orderbook", "MIN_FILL_RATIO", "execution.minimum_fill_ratio"),
    ("marking.age", "BUCKET_A_BLOCKS", "token_age.bucket_a.blocks"),
    ("marking.age", "HOUR_SECONDS", "token_age.bucket_b.seconds"),
    ("marking.age", "DAY_SECONDS", "token_age.bucket_c.seconds"),
    ("marking.pools", "DEAD_INACTIVITY_SECONDS", "dead_pool.inactivity_seconds"),
    ("matching_null.matching", "PRIMARY_CONTROLS", "benchmark.primary_matched_controls"),
    ("matching_null.matching", "ROBUSTNESS_CONTROLS", "benchmark.robustness_controls"),
    ("matching_null.permutation", "NULL_RUNS", "null.runs_per_window_per_column"),
    ("matching_null.permutation", "SIGNIFICANCE_PERCENTILE", "gate.significance.null_percentile"),
    ("matching_null.permutation", "NULL_PASS_RATE_TARGET", "null.pass_rate_target"),
    ("netting.balance", "RESIDUAL_FLOOR_USD", "netting.residual_tolerance.floor_usd"),
    ("netting.balance", "RESIDUAL_NOTIONAL_RATE", "netting.residual_tolerance.notional_rate"),
    ("reporting.capital", "CAPITAL_LEVELS", "capital.levels"),
    ("reporting.capital", "COPY_RETENTION_MIN_RAW_QUALITY", "copy_retention.display_floor"),
    ("reporting.diagnostics", "MIN_VALID_BUYS", "eligibility.valid_buys.floor"),
    ("reporting.diagnostics", "MAX_VALID_BUYS", "eligibility.valid_buys.ceiling"),
    ("reporting.diagnostics", "ACTIVITY_BANDS", "reporting.activity_bands"),
    ("universe.protocol", "ACTIVITY_BAND_BOUNDS", "reporting.activity_bands"),
    ("reporting.window", "EXPECTED_WINDOWS", "windows.count"),
    ("scoring.edge", "FIRST_HOUR_EDGE_SHARE_MAX", "gate.first_hour_edge_share_max"),
    ("scoring.edge", "MIN_TOTAL_POSITIVE_EDGE", "gate.minimum_total_positive_edge"),
    ("universe.protocol", "POTENTIAL_BUY_FLOOR", "eligibility.potential_buys.floor"),
    ("universe.protocol", "POTENTIAL_BUY_CEILING", "eligibility.potential_buys.ceiling"),
    ("universe.protocol", "VALID_BUY_FLOOR", "eligibility.valid_buys.floor"),
    ("universe.protocol", "VALID_BUY_CEILING", "eligibility.valid_buys.ceiling"),
    ("universe.protocol", "MINIMUM_ELIGIBLE_UNIVERSE", "universe.minimum_eligible_accounts"),
    ("universe.protocol", "SELECTED_MIN", "selection.minimum"),
    ("universe.protocol", "SELECTED_MAX", "selection.maximum"),
)

#: ``(module, constant, key, expected, why it was not migrated)``. ``expected`` is written out by
#: hand rather than read from the frozen set, so a case where both copies moved together still
#: fails.
UNMIGRATED = (
    (
        "gate_validation.windows", "EXPECTED_WINDOWS", "windows.count", 4,
        "gate_validation is the arbiter and tests/integration/test_gate_validation.py::"
        "test_the_package_imports_only_the_seam permits it contracts and the standard library "
        "and nothing else. It may not import phase0 for the same reason it may not import "
        "scoring: an arbiter that can call what it judges can inherit the bug it is judging. The "
        "copy stays and is held equal here.",
    ),
    (
        "gate_validation.windows", "MIN_PASSING_WINDOWS", "windows.required_to_pass", 3,
        "Same boundary as above.",
    ),
    (
        "gate_validation.windows", "DESIGN_CAPITAL_LEVELS", "capital.gating_levels",
        (Decimal("1500000"), Decimal("2000000")),
        "Same boundary as above.",
    ),
    (
        "gate_validation.windows", "FIRST_HOUR_EDGE_SHARE_MAX", "gate.first_hour_edge_share_max",
        Decimal("0.40"),
        "Same boundary as above, and this entry is younger than the others for a reason worth "
        "keeping: until 2026-08-16 the arbiter held no first-hour limit at all. It read "
        "edge_origin_status, an enum scoring had already decided, and copied first_hour_edge_share "
        "into the verdict without comparing it to anything -- so a VALID score carrying a share of "
        "0.95 passed §7.1. The constant exists now so the package can refuse a status and a share "
        "that cannot both be true, and it is a copy because importing phase0 would let the arbiter "
        "reach the lane it judges.",
    ),
    (
        "gate_validation.decision", "NULL_PERCENTILE", "gate.significance.null_percentile",
        Decimal("0.95"),
        "Same boundary, and added for the same reason as FIRST_HOUR_EDGE_SHARE_MAX above: §7.3's "
        "two bounds reached the arbiter as fields the caller declared, while null_statistics -- "
        "the distribution both are derived from -- sat unread in the same object. The arbiter now "
        "recomputes the nearest-rank 95th percentile itself, which needs the quantile locally.",
    ),
    (
        "gate_validation.decision", "NEGATIVE_RESULT_WORDING",
        "reporting.negative_result_wording", NEGATIVE_RESULT,
        "Same boundary as above, and the most uncomfortable entry in this list: the module that "
        "emits §11.3's sentence is the one module that may not read it from the frozen set. Held "
        "character for character here against the transcription at the top of this file, which is "
        "what a test can do about it.",
    ),
    (
        "gate_validation.decision", "FORBIDDEN_NEGATIVE_FRAMING",
        "reporting.forbidden_negative_framing", FORBIDDEN_FRAMING,
        "Same boundary as above.",
    ),
    (
        "contracts.core", "EXECUTION_COST_CAP", None, None,
        "src/contracts/ is the frozen seam and is not edited by this ticket; it also cannot "
        "import phase0, which imports it. The two caps are held equal below against "
        "execution.cost_cap.major and .mid_cap.",
    ),
    (
        "contracts.metrics", "SMD_BALANCE_TARGET", "benchmark.covariate_balance_smd_max",
        Decimal("0.10"),
        "Frozen seam; see above.",
    ),
    (
        "pipeline.inputs", "MEASUREMENT_HORIZON_SECONDS", None, 2592000,
        "The frozen set carries §4.4's horizon in days (measurement.horizon_days = 30) and this "
        "package needs seconds. Reading it here would multiply a frozen value at import time, "
        "which tests/test_frozen_context.py flags as unguarded Decimal arithmetic — it cannot see "
        "that a DAYS parameter is an exact int — and the house rule is that its allowlists stay "
        "empty. So the literal stays and the equality is pinned here instead.",
    ),
)


def _module(dotted):
    import importlib

    return importlib.import_module(dotted)


@pytest.mark.parametrize(
    "module,constant,key", MIGRATED, ids=["{}.{}".format(m, c) for m, c, _k in MIGRATED])
def test_a_migrated_constant_is_the_frozen_value(module, constant, key):
    """The stage reads the frozen set. Not a copy that happens to agree with it today."""
    assert getattr(_module(module), constant) == PARAMETERS.value(key)


@pytest.mark.parametrize(
    "module,constant,key", MIGRATED, ids=["{}.{}".format(m, c) for m, c, _k in MIGRATED])
def test_a_migrated_constant_is_read_and_not_restated(module, constant, key):
    """The equality above is not enough, and this is the case with the teeth.

    A literal re-inlined at the same value passes ``==`` forever and is a threshold that can drift
    out of the frozen set silently — which is the whole failure ticket 11's third criterion names.
    So the *shape* is asserted too, from the committed source rather than from the imported value:
    the module-level binding must be a call to ``PARAMETERS.value`` naming this exact key.

    What it cannot see: a module that reads the frozen value and then adjusts it, or one that reads
    a different key into a differently named constant. It sees restatement, which is the thing that
    actually happens.
    """
    import ast
    import os

    source_file = _module(module).__file__
    with open(source_file, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=os.path.basename(source_file))

    bindings = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == constant for t in node.targets)
    ]
    assert len(bindings) == 1, (
        "{}.{} is bound {} times at module level; the frozen set must have exactly one "
        "reader".format(module, constant, len(bindings))
    )

    call = bindings[0].value
    assert isinstance(call, ast.Call), (
        "{}.{} is assigned a {} rather than a call to PARAMETERS.value. A literal here is a copy "
        "of the frozen value that can drift out of it without anything "
        "noticing".format(module, constant, type(call).__name__)
    )
    assert isinstance(call.func, ast.Attribute) and call.func.attr == "value"
    assert isinstance(call.func.value, ast.Name) and call.func.value.id == "PARAMETERS"
    assert len(call.args) == 1 and isinstance(call.args[0], ast.Constant)
    assert call.args[0].value == key


@pytest.mark.parametrize(
    "module,constant,key,expected,why", UNMIGRATED,
    ids=["{}.{}".format(m, c) for m, c, _k, _e, _w in UNMIGRATED])
def test_an_unmigrated_copy_still_agrees_with_the_document(module, constant, key, expected, why):
    """Named duplicates, held equal to the transcription. See ``UNMIGRATED`` for each reason."""
    assert why, "every unmigrated copy must say why it was left"
    present = getattr(_module(module), constant)
    if expected is None:
        # A copy whose shape is not a single value — see the dedicated case below. It is still
        # listed here so the inventory of duplicates is complete in one place.
        assert present
        return
    assert present == expected
    if key is not None:
        assert PARAMETERS.value(key) == expected


# -- the known-answer battery, which must disagree with the code and agree with §  --
#
# Ticket 18's second criterion: the battery's expected answers are "authored from the frozen
# definitions". Ticket 11 is what made that checkable — before today the definitions were not
# frozen, so there was nothing to author them from.
#
# The battery is the one place in this repository where reading the frozen set would be WRONG, and
# it says so itself: "a horizon that moves with a constant somewhere else pins nothing about the
# horizon". A regression battery that followed the code would change its expected answers whenever
# the code changed, which is the one thing it exists not to do. So its constants stay literals.
#
# What binds them is this table. Same shape as UNMIGRATED and for a sharper reason: those are copies
# that could not be migrated, this is a copy that must not be. The battery certifies the pipeline
# against §9.8's known_answer_pass_rate == 1, so a battery whose constants had drifted from the
# frozen set would certify the pipeline against definitions the experiment is not pre-registered on
# -- and it would report a perfect score while doing it.

#: ``(constant, frozen key, multiplier, why the units differ)``. The multiplier is applied to the
#: frozen value, never to the battery's, so a test cannot make the two agree by scaling the side it
#: is checking.
BATTERY_CONSTANTS = (
    ("HORIZON_SECONDS", "measurement.horizon_days", 86400,
     "§4.4 states the horizon in days and the battery needs seconds"),
    ("DAY_SECONDS", "token_age.bucket_c.seconds", 1,
     "§4.7's bucket C boundary is 24 hours, which is also the battery's day"),
    ("HOUR_SECONDS", "token_age.bucket_b.seconds", 1,
     "§4.7's bucket B boundary is one hour"),
)


@pytest.mark.parametrize("constant,key,multiplier,why", BATTERY_CONSTANTS,
                         ids=[c for c, _k, _m, _w in BATTERY_CONSTANTS])
def test_a_battery_constant_agrees_with_the_frozen_definition(constant, key, multiplier, why):
    """The frozen regression suite and the frozen parameter set say the same thing.

    A failure means one of two things and both are serious: either a parameter moved after the
    freeze, which §17 forbids outright, or the battery was edited to match an implementation. The
    second is the quieter one — the battery would keep reporting 16/16 while certifying the pipeline
    against a definition nobody pre-registered.
    """
    from known_answer import battery

    assert why
    assert getattr(battery, constant) == PARAMETERS.value(key) * multiplier


def test_the_battery_reads_no_parameter_at_import():
    """It must *not* follow the frozen set, and the test above must not have quietly made it.

    Guard on the guard above. Holding two literals equal is only worth something while there are
    two: if the battery ever read ``PARAMETERS.value`` into these constants, the equality would hold
    forever by construction and the check would be theatre — the same vacuous green that
    ``token_imbalance`` was.
    """
    import ast
    import os

    from known_answer import battery

    with open(battery.__file__, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=os.path.basename(battery.__file__))

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])

    assert "phase0" not in imported, (
        "the known-answer battery imports phase0, so its expected answers can now move with the "
        "frozen set. They must be independent literals -- the battery's own comment says a horizon "
        "that moves with a constant somewhere else pins nothing about the horizon"
    )

    for constant, _key, _multiplier, _why in BATTERY_CONSTANTS:
        bindings = [
            node for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == constant for t in node.targets)
        ]
        assert len(bindings) == 1, "{} is bound {} times".format(constant, len(bindings))
        assert isinstance(bindings[0].value, ast.Constant), (
            "{} is not a plain literal any more".format(constant))


# -- the sweep that keeps the two lists above honest -----------------------------
#
# MIGRATED and UNMIGRATED are hand-written, and a hand-written inventory of duplicates is exactly
# as complete as whoever wrote it remembered to be. The first version of this file was two entries
# short — phase0/seeds.py held MASTER_SEED_BYTES = 32 and FIELD_SEPARATOR = "|" while the frozen
# set restated both as literals, in the same block where seeds.derivation_rule was deliberately
# read from RunRecord rather than retyped. Both copies agreed, so every test passed; setting the
# frozen width to 48 left new_master_seed minting 32 bytes and nothing said so.
#
# So the sweep below derives the inventory from the tree instead: every module-level constant in
# src/ whose literal equals a frozen value must be accounted for in one of the three lists. Most
# matches are collisions between unrelated quantities, which is why COINCIDENTAL exists and why
# each entry has to say what the number actually measures.

#: ``(module, constant, what the number measures instead)``. Same integer or decimal as a frozen
#: value, different quantity — so there is nothing to migrate and nothing to hold equal. Each entry
#: is a claim that can be checked by reading the cited module, and a wrong one is a duplicate
#: hiding in the list meant to catch duplicates, so they are written narrowly.
COINCIDENTAL = (
    ("pipeline.keccak", "_RHO", "Keccak-f[1600] rotation offsets; 10 and 20 are bit counts."),
    ("pipeline.keccak", "_PI", "Keccak-f[1600] lane permutation indices, 0-24."),
    ("pipeline.keccak", "DIGEST_BYTES", "Keccak-256's digest width. 32 because the hash is 256 "
                                        "bits, not because the master seed is 32 bytes."),
    ("pipeline.poolread", "_WORD", "The EVM ABI word, 32 bytes."),
    ("pipeline.pooladdress", "FEE_TIERS", "Uniswap v3 fee tiers in hundredths of a basis point; "
                                          "10000 is the 1% tier."),
    ("pipeline.tokenstart", "CHUNK_BLOCKS", "The eth_getLogs block-range cap free endpoints "
                                            "enforce."),
    ("transport.client", "DEFAULT_BACKOFF_SECONDS", "Waits between retries, in seconds."),
    ("transport.http", "DEFAULT_TIMEOUT", "An HTTP timeout in seconds, unrelated to §4.4's "
                                          "30-day measurement horizon."),
    ("depth.amm", "ONE_PERCENT", "A depth probe size, not a cost cap."),
    ("depth.amm", "TEN_PERCENT", "The other depth probe size."),
    ("depth.amm", "MODEL_SIZE_RATIO_10PCT_OVER_1PCT", "The ratio between those two probes."),
    ("depth.amm", "MEASURED_TVL_UNDERSTATEMENT", "A10.4's measured 5-23x TVL band."),
    ("depth.execution", "BPS", "Basis points per unit."),
    ("marking.liquidity", "BPS", "Basis points per unit."),
    ("marking.liquidity", "MEASURED_TVL_UNDERSTATEMENT", "A10.4's band again."),
    ("marking.pools", "THIN_SHORTFALL_RATIO", "The THIN reporting label's shortfall, which zeroes "
                                              "nothing and is not §6.6's balance target."),
    ("contracts.numeric", "SCALE_PERCENTAGE_POINTS", "A decimal quantisation scale, 4dp."),
    ("contracts.numeric", "SCALE_SMD", "A decimal quantisation scale, 4dp."),
    ("universe.forward", "FORWARD_SECONDS_PER_DAY", "A unit conversion. Bucket C's 86,400 is a "
                                                    "bucket edge; this is how long a day is."),
    ("universe.protocol", "SECONDS_PER_DAY", "The same unit conversion."),
    ("universe.protocol", "SELECTION_PERCENT_DENOMINATOR", "The 100 in '1% of eligible universe', "
                                                           "named so the percentage is visible."),
    ("universe.step0", "QUANTILES", "§6.1's reporting quantiles, as integer triples."),
    ("pipeline.pooladdress", "PINNED_POOLS", "Known-pool fixtures; the 500 is Uniswap v3's 0.05% "
                                             "fee tier on USDC/WETH, not a band boundary."),
)

#: ``(module, constant, key)``. The migration pointing the other way: the module holds the single
#: literal and :data:`PARAMETERS` reads it, because ``phase0.parameters`` imports both of these
#: modules and neither can import it back. Listed separately from ``MIGRATED`` rather than folded
#: into it because the assertion is different — there is no copy to hold equal, so what is checked
#: is that the table's value *is* the module's object and that the entry is written as a name.
#:
#: The guarantee is the same one pointing the other way, and it is worth saying where it is weaker:
#: a stage cannot reach these through the register, but a person editing ``seeds.py`` moves the
#: frozen value with one hand. What stops that silently is the transcription in ``EXPECTED`` above,
#: which writes 32, ``"|"``, 10 and 15 out against the documents by hand.
UPSTREAM = (
    ("phase0.seeds", "MASTER_SEED_BYTES", "seeds.master_seed_bytes"),
    ("phase0.seeds", "FIELD_SEPARATOR", "seeds.field_separator"),
    ("phase0.validator", "MIN_COMPLEX_ACCOUNTS", "validation.complex_accounts_min"),
    ("phase0.validator", "MAX_COMPLEX_ACCOUNTS", "validation.complex_accounts_max"),
)


def _accounted():
    named = {(m, c) for m, c, _k in MIGRATED}
    named |= {(m, c) for m, c, _k, _e, _w in UNMIGRATED}
    named |= {(m, c) for m, c, _w in COINCIDENTAL}
    named |= {(m, c) for m, c, _k in UPSTREAM}
    return named


def _frozen_literals():
    """Every frozen value as its string form, mapped to the keys that carry it."""
    wanted = {}

    def remember(value, key):
        if value is None or isinstance(value, bool):
            return
        if isinstance(value, tuple):
            for item in value:
                remember(item, key)
        elif isinstance(value, (int, Decimal, str)):
            wanted.setdefault(str(value), set()).add(key)

    for parameter in PARAMETERS.parameters():
        remember(parameter.value, parameter.key)
    return wanted


def _literals_of(expr):
    """The literal values a module-level assignment binds, looking through Decimal/calc/tuples."""
    import ast

    if isinstance(expr, ast.Constant) and isinstance(expr.value, (int, str, float)):
        return [expr.value]
    if (isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name)
            and expr.func.id in ("Decimal", "calc") and expr.args):
        return _literals_of(expr.args[0])
    if isinstance(expr, (ast.Tuple, ast.List)):
        found = []
        for element in expr.elts:
            found.extend(_literals_of(element))
        return found
    return []


def _unnamed_constants(accounted):
    """Module-level constants in ``src/`` holding a frozen value and absent from ``accounted``.

    Takes the inventory as an argument rather than reading it, so the test below can hand it a
    deliberately incomplete one and check that the sweep notices.
    """
    import ast
    import os

    source_root = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "src")
    wanted = _frozen_literals()
    unnamed = []

    for directory, _subdirs, filenames in os.walk(source_root):
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(directory, filename)
            dotted = os.path.relpath(path, source_root)[:-3].replace(os.sep, ".")
            if dotted == "phase0.parameters":
                continue  # the table itself
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                for literal in _literals_of(node.value):
                    if isinstance(literal, bool) or str(literal) not in wanted:
                        continue
                    for name in names:
                        if (dotted, name) not in accounted:
                            unnamed.append("{}.{} = {!r} equals {}".format(
                                dotted, name, literal,
                                "/".join(sorted(wanted[str(literal)]))))
    return sorted(set(unnamed))


def test_no_module_level_constant_duplicates_a_frozen_value_unnamed():
    """Every literal in ``src/`` equal to a frozen value is in one of the four lists.

    The check the two hand-written inventories cannot perform on themselves. It walks the committed
    source rather than the imported modules, so a constant assembled at import time out of the
    frozen set does not look like a literal, and a literal does not stop looking like one because
    it happens to equal the value it duplicates.

    What it cannot see, stated so the pass is not read as more than it is: a threshold written
    inline at a call site rather than bound to a module-level name, a value stored in a different
    unit (§4.4's 30 days as 2,592,000 seconds is why ``pipeline.inputs`` is in ``UNMIGRATED`` by
    hand), and a duplicate of a value that is not in the frozen set at all. It catches the case
    that actually occurred, which is a constant beside a migrated one that nobody migrated.
    """
    unnamed = _unnamed_constants(_accounted())
    assert not unnamed, (
        "module-level constants carrying a frozen value and named in none of MIGRATED, UPSTREAM, "
        "UNMIGRATED or COINCIDENTAL:\n  " + "\n  ".join(unnamed) + "\n\nEach is a copy that should "
        "read the frozen set; a value the table reads because an import cycle forbids the other "
        "direction (UPSTREAM); a copy that cannot be migrated and belongs in UNMIGRATED with its "
        "reason; or a different quantity that happens to share a number and belongs in "
        "COINCIDENTAL saying what it measures."
    )


def test_the_sweep_catches_the_case_that_actually_got_through():
    """The sweep, with one entry taken out of its inventory. Deleting a guard must go RED.

    ``phase0.seeds.MASTER_SEED_BYTES`` is the constant the first version of this ticket missed, so
    it is the one the check is exercised on: drop it from the inventory and the sweep must name it,
    with the frozen key it collides with. A sweep that passed here would be a sweep that passes
    whatever it is given, and the test above would prove nothing.
    """
    incomplete = _accounted() - {("phase0.seeds", "MASTER_SEED_BYTES")}
    flagged = _unnamed_constants(incomplete)

    assert flagged == ["phase0.seeds.MASTER_SEED_BYTES = 32 equals seeds.master_seed_bytes"], (
        "the sweep did not report the one constant removed from its inventory; it reported "
        "{!r}".format(flagged)
    )


@pytest.mark.parametrize(
    "module,constant,key", UPSTREAM, ids=["{}.{}".format(m, c) for m, c, _k in UPSTREAM])
def test_an_upstream_value_is_the_modules_object_and_not_a_copy_of_it(module, constant, key):
    """The table reads the module. Equality is not enough — the entry must be written as a name.

    ``==`` passes forever on two literals that agree, which is exactly how ``32`` and ``"|"`` sat
    in both places without anything failing. So the frozen entry's *source* is checked: its second
    argument must be the bare name imported from the module, never a restatement of the value.
    """
    import ast

    assert PARAMETERS.value(key) == getattr(_module(module), constant)

    with open(_module("phase0.parameters").__file__, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    entries = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "Parameter" and node.args
        and isinstance(node.args[0], ast.Constant) and node.args[0].value == key
    ]
    assert len(entries) == 1, "{} is declared {} times".format(key, len(entries))
    declared = entries[0].args[1]
    assert isinstance(declared, ast.Name) and declared.id == constant, (
        "{} is declared as a {} rather than as the name {}. A literal here is a second copy of a "
        "value {} already holds, and two copies that agree today are exactly the drift ticket 11's "
        "third criterion names.".format(key, type(declared).__name__, constant, module)
    )


def test_the_seams_execution_cost_caps_agree_with_the_frozen_set():
    """``contracts.core.EXECUTION_COST_CAP`` is keyed by tier, so it gets its own case.

    Long-tail has no entry in either place, and for the same reason: addendum §9.5 excludes it from
    Ethereum Phase 0 outright, so a missing key must raise rather than default. The frozen set says
    that in words — ``execution.long_tail_treatment`` — and the seam says it by absence.
    """
    from contracts.core import EXECUTION_COST_CAP, AssetTier

    assert EXECUTION_COST_CAP[AssetTier.MAJOR] == Decimal("0.01")
    assert EXECUTION_COST_CAP[AssetTier.MID_CAP] == Decimal("0.02")
    assert AssetTier.LONG_TAIL not in EXECUTION_COST_CAP
    assert PARAMETERS.value("execution.cost_cap.major") == Decimal("0.01")
    assert PARAMETERS.value("execution.cost_cap.mid_cap") == Decimal("0.02")
    assert PARAMETERS.value("execution.long_tail_treatment") == (
        "EXCLUDED FROM ETHEREUM PHASE 0")


def test_the_seed_derivation_rule_is_read_from_the_run_record_not_retyped():
    """One sentence. A reader re-derives a run's seeds from it and the run record carries it."""
    assert PARAMETERS.value("seeds.derivation_rule") == RunRecord.SEED_RULE
    assert "|" in RunRecord.SEED_RULE
    assert PARAMETERS.value("seeds.field_separator") == "|"


#: Ticket 11's third criterion names its minimum contents in prose — "the authoritative parameter
#: set contains at minimum: the four walk-forward windows; the eligibility bounds ...". Transcribed
#: here clause by clause, in the ticket's own order, as ``(the ticket's words, the key)``. A clause
#: needing more than one key gets more than one row rather than a key that bundles them, so a
#: removal shows up as the specific thing that went missing.
TICKET_11_MINIMUM = (
    ("the four walk-forward windows", "windows.walk_forward"),
    ("the eligibility bounds (10-1,200 potential buys)", "eligibility.potential_buys.floor"),
    ("the eligibility bounds (10-1,200 potential buys)", "eligibility.potential_buys.ceiling"),
    ("the eligibility bounds (20-1,000 valid buys)", "eligibility.valid_buys.floor"),
    ("the eligibility bounds (20-1,000 valid buys)", "eligibility.valid_buys.ceiling"),
    ("the universe floor of 10,000 accounts", "universe.minimum_eligible_accounts"),
    ("clamp(1% of eligible universe, 250, 1000)", "selection.rate_of_eligible_universe"),
    ("clamp(1% of eligible universe, 250, 1000)", "selection.minimum"),
    ("clamp(1% of eligible universe, 250, 1000)", "selection.maximum"),
    ("the five capital levels", "capital.levels"),
    ("max($0.01, 0.01% of transaction notional)", "netting.residual_tolerance.floor_usd"),
    ("max($0.01, 0.01% of transaction notional)", "netting.residual_tolerance.notional_rate"),
    ("the three-part dead-pool conjunction", "dead_pool.conditions"),
    ("the token-age bucket boundaries", "token_age.bucket_a.blocks"),
    ("the token-age bucket boundaries", "token_age.bucket_b.seconds"),
    ("the token-age bucket boundaries", "token_age.bucket_c.seconds"),
    ("the starting mean threshold of 15pp", "gate.starting_mean_threshold"),
    ("the Edge Origin threshold as resolved in 09", "gate.first_hour_edge_share_max"),
    ("the 5pp small-denominator guard", "gate.minimum_total_positive_edge"),
    ("the execution cost caps of 1% majors", "execution.cost_cap.major"),
    ("the execution cost caps of 2% mid-cap", "execution.cost_cap.mid_cap"),
    ("the >=90% fill requirement", "execution.minimum_fill_ratio"),
    ("the Copy Retention 2pp display floor", "copy_retention.display_floor"),
    ("and the master seed", "seeds.master_seed"),
)


@pytest.mark.parametrize("clause,key", TICKET_11_MINIMUM,
                         ids=[key for _clause, key in TICKET_11_MINIMUM])
def test_the_ticket_eleven_minimum_contents_are_present(clause, key):
    """The ticket's own list, checked against the table rather than read alongside it.

    "At minimum" is the ticket's phrase, so this is a floor and not an inventory — the set carries
    more than this, and it should. What the case defends against is the quiet direction: a
    parameter removed or renamed during a later refactor, leaving a set that still looks
    authoritative and no longer contains something the ticket required by name.
    """
    assert key in PARAMETERS, "{} — no parameter {!r}".format(clause, key)
    assert PARAMETERS.parameter(key).source


def test_the_five_capital_levels_are_five():
    """The one clause in the list that says how many, so the count is the assertion."""
    assert len(PARAMETERS.value("capital.levels")) == 5


def test_the_activity_bands_tile_the_eligible_range_exactly():
    """A relationship between §10 and §6.2, asserted rather than encoded.

    §10 writes its bands out itself and §6.2 writes the eligibility bounds out itself, and the two
    happen to meet: the lowest band opens at the valid-buy floor and the highest closes at the
    ceiling. Deriving one from the other in the table would make §10's breakdown move whenever
    §6.2's floor moved, which §10 does not say — so both are frozen from their own sections and the
    agreement is checked here.

    It is worth checking rather than assuming because the failure is quiet in the direction that
    matters: were the floor to rise above 20, every wallet between the old and new floor would fall
    in a band the universe stage can no longer select for, and the §10 table would carry a column
    that is empty for a reason no reader could see.
    """
    bands = PARAMETERS.value("reporting.activity_bands")

    assert bands[0][1] == PARAMETERS.value("eligibility.valid_buys.floor")
    assert bands[-1][2] == PARAMETERS.value("eligibility.valid_buys.ceiling")


def test_a_band_table_with_a_hole_in_it_is_refused():
    """The guard on the unit, exercised on each way a band table can be wrong.

    A gap is the one worth naming: it drops every wallet whose count falls in it from the report
    entirely, and an under-covered table looks exactly like a correct one unless somebody adds the
    columns up.
    """
    with pytest.raises(ValueError) as gap:
        Parameter("t", (("a", 20, 99), ("b", 101, 499)), BANDS, "§10")
    assert "a gap" in str(gap.value)

    with pytest.raises(ValueError) as overlap:
        Parameter("t", (("a", 20, 99), ("b", 99, 499)), BANDS, "§10")
    assert "an overlap" in str(overlap.value)

    with pytest.raises(ValueError) as backwards:
        Parameter("t", (("a", 99, 20),), BANDS, "§10")
    assert "runs backwards" in str(backwards.value)

    with pytest.raises(TypeError):
        Parameter("t", (("a", 20.0, 99),), BANDS, "§10")

    with pytest.raises(TypeError):
        Parameter("t", (), BANDS, "§10")


def test_the_master_seed_is_not_minted_and_none_is_the_claim():
    """A zero or an empty string here would say somebody chose one. Nobody has."""
    assert PARAMETERS.value("seeds.master_seed") is None
    assert PARAMETERS.parameter("seeds.master_seed").unit == UNMINTED
    assert "NOT MINTED" in PARAMETERS.parameter("seeds.master_seed").note


def test_the_one_threshold_neither_document_names_is_named_rather_than_invented():
    """A §-citation the § does not contain would be a manufactured pre-registration."""
    assert set(NOT_PREREGISTERED) == {"marking.pools.MINIMUM_EXIT_VALUE_USD"}
    assert "marking.pools.MINIMUM_EXIT_VALUE_USD" not in PARAMETERS

    from marking.pools import MINIMUM_EXIT_VALUE_USD

    assert MINIMUM_EXIT_VALUE_USD == Decimal("1.00")
    assert "No figure in either document" in NOT_PREREGISTERED[
        "marking.pools.MINIMUM_EXIT_VALUE_USD"]


def test_every_parameter_carries_a_section():
    """The whole table, in one assertion: no value in it came out of anybody's memory."""
    uncited = [p.key for p in PARAMETERS.parameters() if not p.source.strip()]
    assert not uncited


def test_as_dict_renders_decimals_as_strings_and_never_as_floats():
    """A log that disagrees with the value is worse than no log."""
    rendered = PARAMETERS.as_dict()
    assert rendered["gate.first_hour_edge_share_max"]["value"] == "0.40"
    assert rendered["capital.levels"]["value"] == [
        "100000", "250000", "500000", "1500000", "2000000"]

    def _floats(value):
        if isinstance(value, float):
            return True
        if isinstance(value, dict):
            return any(_floats(v) for v in value.values())
        if isinstance(value, list):
            return any(_floats(v) for v in value)
        return False

    assert not _floats(rendered)


# -- the demo, from the shell ---------------------------------------------------
#
# Ticket 11's demo is "an attempted threshold edit that fails with an audit record". The API cases
# above prove the refusal; these prove it is reachable by a person at a terminal, which is where an
# attempted edit actually comes from.

def test_the_cli_reports_the_set_as_not_frozen(tmp_path, capsys):
    code = main(["--root", str(tmp_path / "state"), "parameters"])
    out = capsys.readouterr().out
    assert code == 0
    assert "NOT FROZEN" in out
    assert "gate.first_hour_edge_share_max" in out and "0.40" in out
    assert "marking.pools.MINIMUM_EXIT_VALUE_USD" in out


def test_the_cli_refuses_a_threshold_edit_and_names_the_requester(tmp_path, capsys):
    root = str(tmp_path / "state")
    code = main(["--root", root, "freeze", PARAMETERS_FROZEN, "--requester", "N. Alishahi",
                 "--commit", "5b4565d", "--frozen-on", "2026-08-15"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Frozen at commit:            5b4565d" in out

    code = main(["--root", root, "request-parameter-change",
                 "gate.first_hour_edge_share_max", "0.55",
                 "--requester", "R. Vance", "--reason", "the window would pass at 55%"])
    captured = capsys.readouterr()
    assert code == 2
    assert "REFUSED" in captured.err
    assert "R. Vance" in captured.err

    log = AuditLog(tmp_path / "state" / "audit.jsonl")
    entry = [e for e in log.entries() if e.action == ACTION_CHANGE_REFUSED][-1]
    assert entry.requester == "R. Vance"
    assert entry.detail["proposed_value"] == "0.55"
    assert entry.detail["outcome"] == "REJECTED"
    log.verify()


@pytest.mark.parametrize("requester,commit,frozen_on,expected", (
    ("N. Alishahi", "HEAD", "2026-08-15", "must be a hash"),
    ("TBD", "5b4565d", "2026-08-15", "must be a name"),
    ("N. Alishahi", "5b4565d", "not-a-date", "must be an ISO date"),
))
def test_the_cli_refuses_a_mistyped_freeze_record_as_a_refusal(
        tmp_path, capsys, requester, commit, frozen_on, expected):
    """Three ways a person mistypes the one command that records a human act.

    ``FreezeRecord`` raises ``ValueError`` for each, which is right for a caller with a bug and
    wrong at a shell: it reached the terminal as a traceback while the half-a-record case one test
    below — the same kind of mistake, made at the same prompt — printed ``REFUSED`` and returned 2.
    ``cmd_freeze`` converts them, so the two agree, and the record's own sentence is carried
    through rather than replaced by a generic message.
    """
    code = main(["--root", str(tmp_path / "state"), "freeze", PARAMETERS_FROZEN,
                 "--requester", requester, "--commit", commit, "--frozen-on", frozen_on])

    assert code == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("REFUSED:")
    assert expected in captured.err
    assert "Traceback" not in captured.err


def test_the_cli_refuses_half_a_freeze_record(tmp_path, capsys):
    """A commit with no date, or a date with no commit, is half of §17's sign-off block."""
    code = main(["--root", str(tmp_path / "a"), "freeze", PARAMETERS_FROZEN,
                 "--requester", "N. Alishahi", "--commit", "5b4565d"])
    assert code == 2
    assert "given together" in capsys.readouterr().err

    code = main(["--root", str(tmp_path / "b"), "freeze", PARAMETERS_FROZEN,
                 "--requester", "N. Alishahi", "--frozen-on", "2026-08-15"])
    assert code == 2
    assert "given together" in capsys.readouterr().err


def test_the_cli_refuses_a_ticket_eleven_record_on_the_other_freeze(tmp_path, capsys):
    """``--commit`` records which *text* was frozen; ticket 39 freezes code and data instead.

    Accepting it there would write a ``FreezeRecord`` about a pre-registration onto a transition
    that is not about one, and ``freeze_record()`` would then read it back as the ticket-11 record.
    """
    root = str(tmp_path / "state")
    main(["--root", root, "freeze", PARAMETERS_FROZEN, "--requester", "N. Alishahi",
          "--commit", "5b4565d", "--frozen-on", "2026-08-15"])
    capsys.readouterr()

    code = main(["--root", root, "freeze", "CODE_AND_DATA_FROZEN", "--requester", "N. Alishahi",
                 "--dataset-snapshot", "snap-1",
                 "--commit", "5b4565d", "--frozen-on", "2026-08-16"])
    assert code == 2
    assert "apply only to PARAMETERS_FROZEN" in capsys.readouterr().err


def test_the_cli_has_no_command_that_freezes_without_a_person():
    """Every path to ``PARAMETERS_FROZEN`` from the shell requires ``--requester``.

    Checked on the parser rather than by inspection: a new flag with a default would otherwise be
    a freeze the machine performed and attributed to whoever ran the command last.
    """
    parser = build_parser()
    actions = {a.dest: a for a in parser._subparsers._group_actions}  # noqa: SLF001
    freeze = actions["command"].choices["freeze"]
    requester = [a for a in freeze._actions if a.dest == "requester"][0]  # noqa: SLF001
    assert requester.required is True
    assert requester.default is None

    change = actions["command"].choices["request-parameter-change"]
    change_requester = [a for a in change._actions if a.dest == "requester"][0]  # noqa: SLF001
    assert change_requester.required is True
