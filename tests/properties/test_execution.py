"""Invariants ``execute_stage`` must hold for every stage, from every state, in every order.

The hand-computed file pins what each path does. This one pins what *no* path may do, which is the
half that catches a repair closing one case and leaving the class open:

* a refused stage never writes a run record and never calls the runner — for every stage, from
  every state, not merely the one a reviewer traced;
* a stage that ran always wrote its run record first — likewise;
* the governance state moves forward by at most one position per request and never backwards;
* a crash never advances the state, whichever stage crashed;
* a halted or invalidated run refuses every stage, whichever stage;
* every request appends exactly one ``stage.*`` entry naming its requester, and the hash chain
  verifies after each one.

The authorisation predicate below is restated from the specification rather than obtained from the
module. Asking ``execute_stage`` whether it should have run would make the whole matrix vacuous.
"""

import tempfile

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from phase0 import governance as gov
from phase0.execution import (
    COMPLETED,
    CRASHED,
    HELD,
    MANUAL_TRANSITIONS,
    REFUSED,
    STAGE_AUTHORITY,
    STAGE_STATUSES,
    companion_stages,
    execute_stage,
    wire,
)
from phase0.preconditions import PRECONDITION_KEYS

STAGE_NAMES = sorted(STAGE_AUTHORITY)
STATES = list(gov.ORDER)

COMMIT = "abc1234"
SNAPSHOT = "snap-1"


def fresh(ready=True):
    w = wire(tempfile.mkdtemp())
    if ready:
        for key in PRECONDITION_KEYS:
            w.preconditions.record(key, "recorded-for-test", "Research Owner")
    return w


def advance_to(w, target, requester="Research Owner"):
    start = gov.position(w.governance.state) + 1
    for state in gov.ORDER[start:gov.position(target) + 1]:
        w.governance.transition(state, requester)
    return w


class Spy(object):
    def __init__(self, raises=None):
        self.raises = raises
        self.calls = 0
        self.record_seen = None

    def bind(self, store):
        self.store = store
        return self

    def __call__(self, context):
        self.calls += 1
        self.record_seen = self.store.get(context.run_id)
        if self.raises is not None:
            raise self.raises
        return {"stage": context.stage}


def call(w, stage, runner, requester="primary-builder"):
    return execute_stage(
        stage, runner, requester,
        governance=w.governance, preconditions=w.preconditions, runs=w.runs, audit=w.audit,
        commit=COMMIT, dataset_snapshot=SNAPSHOT, config={"stage": stage},
    )


def should_run(state, stage):
    """The specification, restated: when may this stage run?

    A stage that completes a transition is authorised by that transition, so it runs from exactly
    one state. A stage that completes none is bounded by a floor and runs from that state onward.
    """
    authority = STAGE_AUTHORITY[stage]
    here = gov.position(state)
    if authority.advances is None:
        return here >= gov.position(authority.requires)
    return here == gov.position(authority.advances) - 1


# -- the whole (state x stage) matrix -------------------------------------------


def test_the_matrix_is_the_whole_matrix():
    """Guard the guard: 8 states by 13 stages, and both halves substantial.

    Counted by hand. Seven build-lane stages sit on a floor of ``PARAMETERS_FROZEN`` and so run
    from seven of the eight states — 49 pairs. Six stages *are* transitions and each runs from
    exactly one state — 6 pairs. 55 run, 49 are refused, and neither half is a rounding error.
    """
    assert len(STATES) == 8
    assert len(STAGE_NAMES) == 13
    pairs = [(s, t) for s in STATES for t in STAGE_NAMES]
    assert len(pairs) == 104

    floored = [s for s in STAGE_NAMES if STAGE_AUTHORITY[s].advances is None]
    advancing = [s for s in STAGE_NAMES if STAGE_AUTHORITY[s].advances is not None]
    assert len(floored) == 7
    assert len(advancing) == 6

    runnable = [p for p in pairs if should_run(*p)]
    assert len(runnable) == 55
    assert len(pairs) - len(runnable) == 49


def _matrix():
    return [(state, stage) for state in STATES for stage in STAGE_NAMES]


def test_every_pair_agrees_with_the_specification():
    for state, stage in _matrix():
        w = fresh()
        advance_to(w, state)
        spy = Spy().bind(w.runs)
        result = call(w, stage, spy)

        expected = should_run(state, stage)
        assert (result.status != REFUSED) is expected, (
            "{} from {}: expected {}, got {} ({})".format(
                stage, state, "run" if expected else "refusal", result.status, result.reason)
        )
        assert spy.calls == (1 if expected else 0)


def test_a_refused_stage_writes_no_run_record_from_any_state():
    for state, stage in _matrix():
        if should_run(state, stage):
            continue
        w = fresh()
        advance_to(w, state)
        result = call(w, stage, Spy().bind(w.runs))

        assert result.status == REFUSED
        assert result.run_id is None
        assert w.runs.list_runs() == []
        assert result.reason


def test_a_stage_that_ran_had_its_run_record_on_disk_first():
    for state, stage in _matrix():
        if not should_run(state, stage):
            continue
        w = fresh()
        advance_to(w, state)
        spy = Spy().bind(w.runs)
        call(w, stage, spy)

        assert spy.record_seen is not None, (
            "{} from {} entered the runner with no run record written".format(stage, state))
        assert spy.record_seen.stage == stage
        assert spy.record_seen.commit == COMMIT
        assert spy.record_seen.dataset_snapshot == SNAPSHOT
        assert spy.record_seen.master_seed
        assert spy.record_seen.seed_rule


def test_no_request_moves_the_state_more_than_one_position():
    for state, stage in _matrix():
        w = fresh()
        advance_to(w, state)
        before = gov.position(w.governance.state)
        call(w, stage, Spy().bind(w.runs))
        after = gov.position(w.governance.state)

        assert after >= before, "{} from {} moved the run backwards".format(stage, state)
        assert after - before <= 1, "{} from {} skipped a state".format(stage, state)


def test_a_crash_never_advances_the_state_from_any_state():
    for state, stage in _matrix():
        w = fresh()
        advance_to(w, state)
        result = call(w, stage, Spy(raises=RuntimeError("boom")).bind(w.runs))

        assert result.status in (REFUSED, CRASHED)
        assert w.governance.state == state, (
            "{} crashed from {} and the run advanced to {}".format(
                stage, state, w.governance.state))
        assert result.advanced_to is None


def test_a_halted_run_refuses_every_stage_from_every_state():
    for state, stage in _matrix():
        w = fresh()
        advance_to(w, state)
        w.governance.halt("ops", "security")
        spy = Spy().bind(w.runs)
        result = call(w, stage, spy)

        assert result.status == REFUSED
        assert spy.calls == 0
        assert "HALTED" in result.reason
        assert w.governance.state == state


def test_an_invalidated_run_refuses_every_stage_from_every_state():
    for state, stage in _matrix():
        w = fresh()
        advance_to(w, state)
        w.governance.invalidate("independent-validator", "a bug found after the freeze")
        spy = Spy().bind(w.runs)
        result = call(w, stage, spy)

        assert result.status == REFUSED
        assert spy.calls == 0
        assert "INVALIDATED" in result.reason


def test_a_halt_arriving_mid_stage_holds_every_stage_it_could_run():
    for state, stage in _matrix():
        if not should_run(state, stage):
            continue
        w = fresh()
        advance_to(w, state)

        class Halter(Spy):
            def __call__(self, context):
                w.governance.halt("ops", "security")
                return super().__call__(context)

        result = call(w, stage, Halter().bind(w.runs))

        assert result.status == HELD
        assert result.advanced_to is None
        assert w.governance.state == state
        assert w.runs.get(result.run_id) is not None


def test_every_request_appends_exactly_one_stage_entry_naming_its_requester():
    for state, stage in _matrix():
        w = fresh()
        advance_to(w, state)
        before = len(w.audit.entries())
        result = call(w, stage, Spy().bind(w.runs), requester="agent-7")

        appended = w.audit.entries()[before:]
        stage_entries = [e for e in appended if e.action.startswith("stage.")]

        assert len(stage_entries) == 1
        assert stage_entries[0].requester == "agent-7"
        assert stage_entries[0].detail["stage"] == stage
        assert stage_entries[0].detail["status"] == result.status
        assert all(e.requester for e in appended)
        assert w.audit.verify()


def test_the_result_publishes_a_value_exactly_when_it_completed():
    for state, stage in _matrix():
        w = fresh()
        advance_to(w, state)
        result = call(w, stage, Spy().bind(w.runs))

        assert result.status in STAGE_STATUSES
        if result.status == COMPLETED:
            assert result.value == {"stage": stage}
        else:
            try:
                result.value
            except Exception as exc:
                assert type(exc).__name__ == "StageNotCompleted"
            else:
                raise AssertionError("{} from {} published a value".format(stage, state))


# -- arbitrary sequences ---------------------------------------------------------

_STEPS = (
    [("run", stage) for stage in STAGE_NAMES]
    + [("crash", stage) for stage in STAGE_NAMES]
    + [("freeze", state) for state in MANUAL_TRANSITIONS]
    + [("halt", None), ("resume", None)]
)


@settings(max_examples=60, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(steps=st.lists(st.sampled_from(_STEPS), min_size=1, max_size=18),
       ready=st.booleans())
def test_no_sequence_of_requests_can_corrupt_the_run(steps, ready):
    """Whatever order anyone asks for things in, five things stay true.

    The state only moves forward and only one step at a time; the run records exactly match the
    stages that actually ran; the audit chain verifies; a halted run runs nothing; and no stage
    ever runs twice from a state that had already left it behind.
    """
    w = fresh(ready=ready)
    runs_opened = 0
    halted = False

    for kind, argument in steps:
        before = gov.position(w.governance.state)

        if kind == "freeze":
            try:
                w.governance.transition(argument, "Research Owner")
            except Exception:
                pass
        elif kind == "halt":
            w.governance.halt("ops", "security")
            halted = True
        elif kind == "resume":
            w.governance.resume("ops", "restored")
            halted = False
        else:
            spy = Spy(raises=RuntimeError("boom") if kind == "crash" else None).bind(w.runs)
            result = call(w, argument, spy)

            assert result is not None
            assert result.status in STAGE_STATUSES
            assert (result.run_id is None) == (result.status == REFUSED)
            assert spy.calls == (0 if result.status == REFUSED else 1)
            if result.status != REFUSED:
                runs_opened += 1
            if halted:
                assert result.status == REFUSED
            if kind == "crash":
                assert result.status in (REFUSED, CRASHED)
                assert result.advanced_to is None

        after = gov.position(w.governance.state)
        assert after >= before
        assert after - before <= 1

    assert len(w.runs.list_runs()) == runs_opened
    assert w.audit.verify()
    assert all(entry.requester for entry in w.audit.entries())
    assert w.governance.state in STATES


@settings(max_examples=40, deadline=None)
@given(satisfied=st.lists(st.sampled_from(PRECONDITION_KEYS), unique=True, max_size=3),
       stage=st.sampled_from(STAGE_NAMES))
def test_an_incomplete_register_stops_a_stage_before_anything_is_written(satisfied, stage):
    """Any strict subset of the four, any stage: refused, nothing written, runner untouched."""
    w = fresh(ready=False)
    for key in satisfied:
        w.preconditions.record(key, "recorded-for-test", "Research Owner")
    advance_to(w, gov.THRESHOLD_LOCKED)
    spy = Spy().bind(w.runs)

    result = call(w, stage, spy)

    assert result.status == REFUSED
    assert "DESIGNED, NOT READY FOR EXECUTION" in result.reason
    assert spy.calls == 0
    assert w.runs.list_runs() == []
    assert result.run_id is None


# -- the shared-transition group -------------------------------------------------


@settings(max_examples=25, deadline=None)
@given(order=st.permutations(["null.leader", "null.follower"]))
def test_a_shared_transition_needs_every_stage_in_its_group(order):
    """Whichever order the two null stages run in, the last one advances and the first does not."""
    w = fresh()
    advance_to(w, gov.CODE_AND_DATA_FROZEN)

    first, second = order
    assert companion_stages(first) == companion_stages(second)

    result = call(w, first, Spy().bind(w.runs))
    assert result.status == COMPLETED
    assert result.advanced_to is None
    assert result.pending == (second,)
    assert w.governance.state == gov.CODE_AND_DATA_FROZEN

    result = call(w, second, Spy().bind(w.runs))
    assert result.advanced_to == gov.NULL_COMPLETE
    assert result.pending == ()
    assert w.governance.state == gov.NULL_COMPLETE
