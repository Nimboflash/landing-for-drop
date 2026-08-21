"""The registry, the entry point, and the four outcomes — reached with real runners.

Three things are fixed here.

**Completeness, in both directions.** :data:`pipeline.stages.STAGE_RUNNERS` and
:data:`phase0.runs.STAGES` must name the same thirteen stages. A key missing from the registry is a
stage that can be authorised, refused, held and recorded while computing nothing — the situation
this commit exists to end, and the situation that held for every stage in the tree until it. A key
in the registry that is not a stage is a runner nobody can request: it looks wired, it is not, and
nothing else in the suite would notice.

**The lane direction.** ``phase0`` is SHARED and ``pipeline`` is BUILDER, so the
``(SHARED, BUILDER)`` edge is forbidden — ``tests/test_lane_independence.py`` holds that over every
package. It is re-asserted here, narrowly and by name, because this is the commit that would have
been tempted to break it: wiring thirteen runners into ``phase0.execute_stage`` looks like it wants
``import pipeline`` in ``phase0``. It does not. The runner is injected, and injection runs the other
way.

**All four outcomes, each through a registered runner.** ``COMPLETED``, ``REFUSED`` (governance
declines before anything is written), ``HELD`` (an operations halt arrives while the stage is
running) and ``CRASHED`` (the runner raises). ``tests/integration/test_execution.py`` already shows
those four with a trivial runner; the question here is whether they still land correctly when the
runner is doing real work, because a runner that swallowed its own failure would produce a
``COMPLETED`` with a plausible-looking value and nothing in ``phase0`` could tell.
"""

import ast
import os
from decimal import Decimal

import pytest

from phase0 import governance as gov
from phase0.errors import StageNotCompleted
from phase0.execution import COMPLETED, CRASHED, HELD, REFUSED, execute_stage
from phase0.runs import STAGES
from pipeline.execute import run_stage, stages_runnable_without_inputs
from pipeline.execute import main as pipeline_stage_main
from pipeline.stages import (
    BLOCKED_STAGES,
    LIVE_STAGES,
    STAGE_RUNNERS,
    UnregisteredStage,
    runner_for,
)
from pipeline.stages.inference import NullWindowInputs

from . import stage_fixtures as F

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                   "src")


@pytest.fixture
def w(tmp_path):
    return F.wired(tmp_path / "state")


def go(w, stage, inputs=None, requester=F.REQUESTER, commit=F.COMMIT):
    return run_stage(
        stage, requester, wiring=w, commit=commit, dataset_snapshot=F.DATASET_SNAPSHOT,
        inputs=inputs, master_seed=F.MASTER_SEED,
    )


# -- completeness ----------------------------------------------------------------


def test_the_registry_and_the_stage_list_name_the_same_thirteen_stages():
    """Both directions, and the failure message says which direction failed.

    A one-sided check is the trap here: ``set(STAGES) <= set(STAGE_RUNNERS)`` passes happily with a
    fourteenth registered runner that no ``execute_stage`` call can ever reach, and
    ``set(STAGE_RUNNERS) <= set(STAGES)`` passes with an empty registry.

    Deletion-tested. Removing this function does *not* turn the suite red, and that is worth
    recording rather than hiding: both directions are over-determined by
    ``test_the_blocked_index_and_the_live_list_partition_the_thirteen`` and by
    ``test_stage_runners.py``'s walk, which requests all thirteen by name. What this check adds is
    the *diagnosis* — a missing key here says "these stages have no registered runner", where the
    walk says only that ``UnregisteredStage`` was raised somewhere in the middle of a run.
    """
    missing = sorted(set(STAGES) - set(STAGE_RUNNERS))
    extra = sorted(set(STAGE_RUNNERS) - set(STAGES))

    assert not missing, (
        "these stages have no registered runner: {}. phase0 would still authorise, refuse, hold "
        "and record each of them while nothing ran — which is exactly the gap this registry "
        "closes, and it closes silently if a stage is simply left out.".format(", ".join(missing))
    )
    assert not extra, (
        "these registry keys are not stages in phase0.runs.STAGES: {}. execute_stage refuses an "
        "unknown stage, so a runner filed under one can never be reached — it looks wired and is "
        "not.".format(", ".join(extra))
    )
    assert len(STAGE_RUNNERS) == 13


def test_every_registered_value_is_callable_and_builds_a_runner():
    for stage, factory in STAGE_RUNNERS.items():
        assert callable(factory), "{} is registered to a non-callable".format(stage)


def test_the_blocked_index_and_the_live_list_partition_the_thirteen():
    assert set(BLOCKED_STAGES) | set(LIVE_STAGES) == set(STAGES)
    assert not set(BLOCKED_STAGES) & set(LIVE_STAGES)
    assert len(BLOCKED_STAGES) == 3
    assert len(LIVE_STAGES) == 10


def test_an_unregistered_stage_is_a_caller_error_and_not_a_refusal():
    with pytest.raises(UnregisteredStage) as excinfo:
        runner_for("pipeline.buy_qualtiy")
    assert "no runner is registered" in str(excinfo.value)


# -- the lane direction ------------------------------------------------------------


def _imported_top_level(path):
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_phase0_still_imports_nothing_from_the_builder_lane():
    """The one import this commit must not have added.

    ``tests/test_lane_independence.py`` proves this over every package pair. It is repeated here by
    name because the wiring is the moment someone reaches for it: ``execute_stage`` needs a runner,
    the runners are in ``pipeline``, and ``import pipeline`` inside ``phase0`` would make the whole
    thing compile. It would also make governance able to call the code it authorises, which is the
    one thing the seam exists to prevent — so the arrow points the other way and this test says so.
    """
    offenders = []
    for dirpath, _dirnames, filenames in os.walk(os.path.join(SRC, "phase0")):
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            for imported in _imported_top_level(path):
                if imported in ("pipeline", "reporting", "attribution", "netting", "fifo",
                                "marking", "scoring", "depth", "matching_null", "groundtruth"):
                    offenders.append("{} imports {}".format(os.path.relpath(path, SRC), imported))

    assert not offenders, (
        "phase0 is SHARED and must not import a builder package:\n  {}\n\nThe runner is injected "
        "into execute_stage as a callable argument, from pipeline.execute. If wiring needed this "
        "import, the direction is backwards.".format("\n  ".join(offenders))
    )


def test_the_builder_lane_is_the_side_that_imports_phase0():
    """The other half of the same fact, so the pair reads as a direction rather than a ban."""
    imported = _imported_top_level(os.path.join(SRC, "pipeline", "execute.py"))
    assert "phase0" in imported


# -- the four outcomes, each through a registered runner ---------------------------


def test_completed_a_stage_that_did_real_work(w):
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    result = go(w, "known_answer.battery")

    assert result.status == COMPLETED
    assert result.value["passed"] == 16
    assert result.run_id


def test_refused_before_the_state_the_stage_requires(w):
    """Governance declines, the runner is never called, and no run record is written.

    A refused stage leaves none on purpose: nothing was about to happen, so there is nothing to
    reproduce, and a run record for a stage that never ran is evidence of a fiction.
    """
    result = go(w, "known_answer.battery")  # still PARAMETERS_OPEN

    assert result.status == REFUSED
    assert result.run_id is None
    assert w.runs.list_runs() == []
    with pytest.raises(StageNotCompleted):
        result.value


def test_held_when_an_operations_halt_arrives_while_the_stage_runs(w):
    """The halt lands inside the statistic, which is a caller-supplied input to ``null.leader``.

    Nothing can interrupt a runner in flight — it is an opaque callable — so what a halt does is
    stop the outcome from being committed. The distribution was computed and is discarded: the
    state does not advance, no value is published, and the stage is re-run once the run resumes.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")
    w.governance.transition(gov.VALIDATION_PASSED, "Research Owner")
    w.governance.transition(gov.CODE_AND_DATA_FROZEN, "Research Owner")

    halted = {"done": False}
    real = F.statistic_for("leader", 1)

    def halting_statistic(labelled):
        if not halted["done"]:
            halted["done"] = True
            w.governance.halt("operations", "halt injected mid-stage")
        return real(labelled)

    inputs = {
        "windows": [NullWindowInputs(
            window=1, matched_sets=F.matched_sets(), statistic_fn=halting_statistic,
        )],
        "n_runs": F.NULL_RUNS,
    }

    result = go(w, "null.leader", inputs)

    assert result.status == HELD
    assert halted["done"], "the halt never fired, so this test proved nothing"
    assert result.run_id, "a stage that ran leaves a run record even when its outcome is held"
    assert result.advanced_to is None
    assert w.governance.state == gov.CODE_AND_DATA_FROZEN
    with pytest.raises(StageNotCompleted):
        result.value


def test_crashed_when_a_live_runner_raises_on_a_defect_in_its_inputs(w):
    """Two transactions with one ``tx_hash``. ``pipeline`` refuses; nothing here catches it.

    A duplicate hash is a defect in what assembled the call, not a disappointing measurement, so it
    is a crash — and the crash carries a run record saying what the stage was about to do.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    inputs = F.buy_quality_inputs()
    inputs["transactions"] = F.BUY_TRANSACTIONS + F.BUY_TRANSACTIONS

    result = go(w, "pipeline.buy_quality", inputs)

    assert result.status == CRASHED
    assert result.run_id
    assert w.runs.get(result.run_id) is not None
    assert w.governance.state == gov.PARAMETERS_FROZEN
    with pytest.raises(StageNotCompleted):
        result.value


def test_a_crossed_registry_wire_is_caught_by_the_runner_itself(w):
    """``execute_stage`` takes the runner as an opaque callable and cannot check the pairing.

    Guard the guard: hand ``main_test``'s runner to ``decision.emit``'s key and the runner refuses,
    naming both stages. Without that check the value of one stage would be filed under another
    stage's authority with nothing in ``phase0`` able to see it.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    crossed = runner_for("main_test", **F.main_test_inputs(Decimal("0.24")))
    result = execute_stage(
        "step0.universe", crossed, F.REQUESTER,
        governance=w.governance, preconditions=w.preconditions, runs=w.runs, audit=w.audit,
        commit=F.COMMIT, dataset_snapshot=F.DATASET_SNAPSHOT,
    )

    assert result.status == CRASHED
    assert "main_test" in result.reason and "step0.universe" in result.reason


# -- the blocked three ----------------------------------------------------------------
#
# There were four. ``step0.universe`` left this set when ``src/universe/`` was merged: it has a real
# runner now and refuses only when it is given nothing to measure, which is a fact about the data
# and not about the registry. ``test_stage_runners.py`` holds both halves of that.

#: Ticket numbers each blocked stage must name in its refusal. From the tickets themselves, not read
#: back from the messages: a refusal whose expectation was copied from its own output pins nothing.
BLOCKED_TICKETS = {
    "golden_set.trace": ("03", "13"),
    "reconciliation.cross_source": ("03", "12", "13"),
    "validation.independent": ("02", "36"),
}


@pytest.mark.parametrize("stage", sorted(BLOCKED_STAGES))
def test_a_blocked_stage_refuses_and_names_the_ticket_it_waits_on(w, stage):
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    result = go(w, stage)

    assert result.status == CRASHED
    assert result.error_type == "StageBlocked"
    for ticket in BLOCKED_TICKETS[stage]:
        assert "ticket {}".format(ticket) in result.reason, (
            "{} does not name ticket {} in its refusal:\n{}".format(stage, ticket, result.reason))
    assert "unblocked by:" in result.reason, (
        "{} names a blocker without saying what would clear it, which is a status rather than a "
        "refusal: it cannot be acted on and cannot be checked against the tree later".format(stage))


@pytest.mark.parametrize("stage", sorted(BLOCKED_STAGES))
def test_a_blocked_stage_says_what_an_empty_answer_would_have_looked_like(w, stage):
    """The reason the stage raises rather than returning nothing, in the refusal itself.

    A stage that returned an empty tuple would publish "0 traces" or "0 unexplained differences" —
    a measurement — where there is the absence of one. The message has to carry that, because the
    audit log is where a reader meets this stage and the docstring is not.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    reason = go(w, stage).reason

    assert "is a measurement and this is the absence of one" in reason


def test_a_blocked_stage_cannot_be_talked_into_completing(w):
    """It takes no inputs, so there is no argument that could make it produce a value."""
    for stage in BLOCKED_STAGES:
        with pytest.raises(TypeError):
            runner_for(stage, anything="at all")


# -- the entry point ----------------------------------------------------------------


def test_the_command_line_can_drive_exactly_the_stages_that_need_no_inputs():
    """Derived from the factories' signatures, so it cannot drift from them."""
    drivable = stages_runnable_without_inputs()

    assert set(BLOCKED_STAGES) <= set(drivable)
    assert "known_answer.battery" in drivable
    assert "step0.universe" in drivable, (
        "every argument of step0_universe_runner defaults to 'not supplied' so that the refusal it "
        "makes with no observations is reachable from a shell; a required argument would move that "
        "refusal out of reach of the only entry point an operator has")
    assert "pipeline.buy_quality" not in drivable
    assert "decision.emit" not in drivable


def test_the_command_line_lists_the_thirteen_and_what_each_is_wired_to(capsys):
    assert pipeline_stage_main(["stages"]) == 0

    printed = capsys.readouterr().out
    for stage in STAGES:
        assert stage in printed
    assert "BLOCKED" in printed


def test_the_command_line_refuses_a_stage_whose_inputs_it_cannot_supply(capsys):
    code = pipeline_stage_main([
        "run", "decision.emit", "--requester", "someone", "--commit", F.COMMIT,
        "--dataset-snapshot", F.DATASET_SNAPSHOT,
    ])

    assert code == 2
    assert "cannot supply" in capsys.readouterr().err


def test_the_command_line_exits_four_on_a_blocked_stage(tmp_path, capsys):
    """A refusal that exited 0 would be a green build over a stage that never ran.

    ``EXIT_CODES`` is ``phase0.cli``'s, imported rather than restated, so the two entry points
    cannot come to disagree about what a crash is worth.
    """
    root = str(tmp_path / "state")
    F.wired(root).governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    code = pipeline_stage_main([
        "--root", root, "run", "golden_set.trace", "--requester", "someone",
        "--commit", F.COMMIT, "--dataset-snapshot", F.DATASET_SNAPSHOT,
    ])

    assert code == 4
    assert "CRASHED" in capsys.readouterr().out


def test_a_wiring_defect_raises_before_a_run_record_is_opened(w):
    """The split ``run_stage`` documents: a defect in the call is not a stage outcome.

    ``decision.emit`` handed something that is not a ``MainTestResult`` fails in the factory, so no
    run record is written and nothing is recorded — the stage was never about to run.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    with pytest.raises(TypeError):
        go(w, "decision.emit", {
            "main_test": "not a MainTestResult",
            "leader_null": None,
            "follower_null": None,
            "evidence": None,
        })

    assert w.runs.list_runs() == []
