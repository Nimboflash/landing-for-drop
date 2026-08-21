"""Ticket 05 acceptance — preconditions, the start gate, run records, seeds, and the audit log."""

import json

import pytest

from phase0.audit import AuditLog
from phase0.cli import main
from phase0.errors import AuditChainError, NotReadyError
from phase0.preconditions import (
    PRECONDITION_KEYS, STATUS_NOT_READY, STATUS_READY, PreconditionRegister,
)
from phase0.runs import RunStore, config_hash
from phase0.seeds import derive_child_seed, derive_child_seeds, new_master_seed


@pytest.fixture
def register(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    return PreconditionRegister(tmp_path / "pre.json", log)


def satisfy_all(register, requester="Research Owner"):
    for key in PRECONDITION_KEYS:
        register.record(key, "recorded-for-test", requester)
    return register


# -- preconditions and the start gate -----------------------------------------

def test_status_is_not_ready_with_nothing_recorded(register):
    assert register.status() == STATUS_NOT_READY
    assert len(register.unmet()) == 4


def test_status_is_not_ready_with_three_of_four(register):
    for key in PRECONDITION_KEYS[:3]:
        register.record(key, "someone", "owner")
    assert register.status() == STATUS_NOT_READY
    assert len(register.unmet()) == 1


def test_status_is_ready_only_with_all_four(register):
    satisfy_all(register)
    assert register.status() == STATUS_READY
    assert register.is_ready()


def test_refusal_names_the_specific_unmet_precondition(register):
    register.record("primary_builder", "A. Builder", "owner")
    register.record("data_budget", "PO-1234", "owner")

    with pytest.raises(NotReadyError) as exc:
        register.require_ready()

    message = str(exc.value)
    assert "Independent Validator assigned (ticket 02)" in message
    assert "capacity reserved (ticket 04)" in message
    assert "Primary Builder" not in message, "a satisfied precondition must not be listed"


def test_a_precondition_needs_an_attribution_not_a_flag(register):
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            register.record("primary_builder", bad, "owner")


def test_unknown_precondition_is_rejected(register):
    with pytest.raises(ValueError):
        register.record("vibes", "good", "owner")


def test_recording_a_precondition_is_audited(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    reg = PreconditionRegister(tmp_path / "pre.json", log)
    reg.record("independent_validator", "V. Alidator, external contract #7", "Research Owner")

    entry = log.entries()[-1]
    assert entry.action == "precondition.record"
    assert entry.requester == "Research Owner"
    assert entry.detail["attribution"].startswith("V. Alidator")


# -- run records ---------------------------------------------------------------

def test_run_record_carries_everything_needed_to_reproduce(tmp_path):
    store = RunStore(tmp_path / "runs", AuditLog(tmp_path / "audit.jsonl"))
    rec = store.open_run(
        stage="step0.universe", commit="abc1234",
        config={"window": 1, "min_valid_buys": 20},
        dataset_snapshot="dune-2026-07-31", requester="builder",
    )
    for field in ("commit", "config_hash", "dataset_snapshot", "master_seed", "seed_rule"):
        assert getattr(rec, field)
    assert rec.seed_rule.startswith("child_seed = HMAC-SHA256")


def test_run_record_is_written_before_the_stage_executes(tmp_path):
    """open_run returns only after the file exists on disk."""
    store = RunStore(tmp_path / "runs")
    rec = store.open_run("main_test", "abc1234", {}, "snap-1", "builder")
    path = tmp_path / "runs" / "{}.json".format(rec.run_id)
    assert path.exists()
    assert json.loads(path.read_text())["stage"] == "main_test"


def test_run_record_survives_reload(tmp_path):
    store = RunStore(tmp_path / "runs")
    rec = store.open_run("null.leader", "abc1234", {"runs": 1000}, "snap-1", "builder")
    again = RunStore(tmp_path / "runs").get(rec.run_id)
    assert again.to_dict() == rec.to_dict()


def test_unknown_stage_is_rejected(tmp_path):
    store = RunStore(tmp_path / "runs")
    with pytest.raises(ValueError):
        store.open_run("just.try.it", "abc1234", {}, "snap-1", "builder")


def test_config_hash_is_order_independent():
    assert config_hash({"a": 1, "b": 2}) == config_hash({"b": 2, "a": 1})
    assert config_hash({"a": 1}) != config_hash({"a": 2})


# -- seeds ---------------------------------------------------------------------

def test_same_master_seed_and_commit_reproduce_the_same_child_seeds():
    master = new_master_seed(entropy="fixed-for-test")
    first = derive_child_seeds(master, "abc1234", "null.leader.window1", 5)
    second = derive_child_seeds(master, "abc1234", "null.leader.window1", 5)
    assert first == second


def test_child_seeds_differ_across_purpose_index_and_commit():
    master = new_master_seed(entropy="fixed-for-test")
    base = derive_child_seed(master, "abc1234", "null.leader.window1", 0)
    assert base != derive_child_seed(master, "abc1234", "null.leader.window1", 1)
    assert base != derive_child_seed(master, "abc1234", "null.follower.window1", 0)
    assert base != derive_child_seed(master, "def5678", "null.leader.window1", 0)


def test_a_new_code_version_produces_different_draws():
    """A re-run after invalidation is a new experiment, not the old one with a patch."""
    master = new_master_seed(entropy="fixed")
    before = derive_child_seeds(master, "commit-before-fix", "null.leader.window1", 100)
    after = derive_child_seeds(master, "commit-after-fix", "null.leader.window1", 100)
    assert set(before).isdisjoint(after)


def test_seed_derivation_rejects_missing_inputs():
    master = new_master_seed(entropy="fixed")
    for bad in ("", None):
        with pytest.raises(ValueError):
            derive_child_seed(master, bad, "purpose", 0)
        with pytest.raises(ValueError):
            derive_child_seed(master, "abc1234", bad, 0)
    with pytest.raises(ValueError):
        derive_child_seed(master, "abc1234", "purpose", -1)


# -- audit log -----------------------------------------------------------------

def test_audit_log_chains_and_verifies(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(5):
        log.append("builder", "stage.run", {"i": i})
    assert log.verify()
    assert [e.seq for e in log.entries()] == [0, 1, 2, 3, 4]


def test_an_altered_entry_is_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append("builder", "governance.gate_outcome", {"outcome": "STOP"})
    log.append("builder", "run.open", {"stage": "main_test"})

    lines = path.read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered["detail"]["outcome"] = "GO"
    lines[0] = json.dumps(tampered, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")

    with pytest.raises(AuditChainError) as exc:
        log.verify()
    assert "seq 0" in str(exc.value)


def test_a_removed_entry_is_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(4):
        log.append("builder", "stage.run", {"i": i})

    lines = path.read_text().splitlines()
    del lines[1]
    path.write_text("\n".join(lines) + "\n")

    with pytest.raises(AuditChainError):
        log.verify()


def test_an_entry_must_name_its_requester(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            log.append(bad, "stage.run", {})


# -- the CLI demo for ticket 05 ------------------------------------------------

def test_cli_refuses_a_stage_while_a_precondition_is_missing(tmp_path, capsys):
    root = str(tmp_path / "state")
    code = main(["--root", root, "record-precondition", "primary_builder",
                 "A. Builder", "--requester", "owner"])
    assert code == 0

    code = main(["--root", root, "request", "step0.universe", "--requester", "builder",
                 "--commit", "abc1234", "--dataset-snapshot", "snap-1"])
    captured = capsys.readouterr()

    assert code == 2
    assert "REFUSED" in captured.err
    assert "Independent Validator" in captured.err


def test_cli_accepts_the_same_stage_once_all_four_are_recorded(tmp_path, capsys):
    root = str(tmp_path / "state")
    for key in PRECONDITION_KEYS:
        main(["--root", root, "record-precondition", key, "recorded", "--requester", "owner"])

    code = main(["--root", root, "request", "step0.universe", "--requester", "builder",
                 "--commit", "abc1234", "--dataset-snapshot", "snap-1"])
    captured = capsys.readouterr()

    assert code == 0
    assert "Accepted" in captured.out
    assert "master_seed" in captured.out


def test_cli_status_reports_not_ready_by_default(tmp_path, capsys):
    main(["--root", str(tmp_path / "state"), "status"])
    out = capsys.readouterr().out
    assert STATUS_NOT_READY in out
    assert "No pipeline stage may run" in out
