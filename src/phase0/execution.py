"""Governance wired to execution — the half of tickets 05 and 06 that was missing.

``phase0`` could refuse a stage and it could open a run record. Nothing in it ever ran one. The
ordering rules were proven against a state machine nobody called, and the run record was proven to
exist rather than to *precede* anything. :func:`execute_stage` closes that: it checks the start
gate, obtains governance's authorisation, opens the run record, calls the stage, and appends the
outcome — completed, refused, held or crashed — to the hash-chained audit log with its requester.

The runner arrives as a **callable argument**. ``phase0`` is SHARED and may not import a builder
package, so this module cannot know what a stage does. That constraint is the design rather than a
concession to :mod:`tests.test_lane_independence`: governance that could call the pipeline could be
asked to call it differently, and the authority that decides whether a stage may run must not also
be the authority that decides what it computes. What this module can do is refuse, pin, and record.

Order of operations, and why it is that order
---------------------------------------------

    1. the start gate         §15.4 preconditions, before anything is written
    2. governance authorises  the transition the stage would complete — *without* performing it
    2b. the validator register ticket 02's independence status, for the stages standing on the
                              validation gate — a NOT INDEPENDENT validator refuses them here
    3. the run record         written before the runner is called
    4. the runner             handed a :class:`StageContext` of pinned inputs and nothing that decides
    5. governance re-checks   anything that changed under the stage — a HALT, an invalidation —
                              holds the outcome instead of committing it, and so does a dataset
                              snapshot that declares itself not a measurement
    6. the transition         performed only now
    7. the audit entry

Three of those orderings are load-bearing, and each is a different failure:

* **1 before 3.** A refused stage leaves no run record. Nothing was about to happen, so there is
  nothing to reproduce, and a run record for a stage that never ran is evidence of a fiction.
* **3 before 4.** A crashed stage leaves one. Something *was* about to happen, and the record says
  under which commit, configuration, dataset snapshot and master seed.
* **6 after 4.** A crashed stage leaves the governance state where it was. Authorising and
  advancing in one call would move the run forward past work that never happened, and a state that
  has advanced past nothing is worse than a refusal — the refusal is visible.

What authorises a stage
-----------------------

:data:`STAGE_AUTHORITY` maps every stage to the governance state it requires and the state it
completes. A stage that completes a transition is authorised by that transition's own rules, so it
runs exactly once — a second ``main_test`` is refused as "already in this state", with no separate
rule for it. A stage that completes no transition is bounded by a floor and may be re-run, which is
the retry policy the orchestration guide sets per lane: the build lane retries, the execution lane
does not.

Two stages can bear on one transition. ``null.leader`` and ``null.follower`` both feed
``NULL_COMPLETE``, and neither advances it alone: the group is derived from the register by
:func:`companion_stages`, so a stage added to it is automatically *required* rather than
automatically ignored. Completions are counted from the audit log since the last registered code
version, so a re-run after an invalidation starts its null from nothing.

What a mid-stage HALT can and cannot do
---------------------------------------

A runner is an opaque callable, so nothing here can interrupt one in flight — claiming otherwise
would need threads or signals and would be a lie about a guarantee. What a halt arriving mid-stage
*does* do is stop the outcome from being committed: the state does not advance, the value is not
published, and the stage is re-run once the run resumes. The condition checked at step 5 is
"governance no longer authorises this stage", not "someone pressed halt" — an invalidation arriving
mid-stage holds the outcome by the same code, and so will anything else added to
:meth:`~phase0.governance.GovernanceMachine._guard_runnable` later.

That is the whole of the operations capability. It cannot advance the run, cannot revert it, and
cannot touch a recorded gate outcome; it can only stop the next thing from being written.

What the data a stage ran over has to do with whether it advances
------------------------------------------------------------------

This function is the only place that both knows the ``dataset_snapshot`` and decides whether to
advance, so it is the only place where "execute but do not advance" can be expressed at all. A
stage that ran under a snapshot declaring itself not a measurement (:mod:`phase0.snapshots`) is
``HELD``: the runner ran, its outcome is recorded, and step 6 is withheld. The rule itself is
:func:`phase0.governance.advancement_refusal` — it belongs with the states it protects, and
``GovernanceMachine.transition`` enforces the same rule as a backstop for the transitions no stage
earns.
"""

import collections
import os

from .audit import AuditLog
from .errors import NotIndependentError, Phase0Error, StageNotCompleted
from .governance import (
    CODE_AND_DATA_FROZEN,
    DECISION_EMITTED,
    MAIN_TEST_EXECUTED,
    NULL_COMPLETE,
    ORDER,
    PARAMETERS_FROZEN,
    THRESHOLD_LOCKED,
    VALIDATION_PASSED,
    GovernanceMachine,
    advancement_refusal,
    position,
)
from .parameters import ParameterRegister
from .preconditions import PreconditionRegister
from .runs import STAGES, RunStore
from .seeds import derive_child_seed

# -- outcomes -------------------------------------------------------------------

#: The runner ran and governance committed whatever the stage completes.
COMPLETED = "COMPLETED"

#: The start gate or governance refused. The runner was never called.
REFUSED = "REFUSED"

#: The runner ran, and governance would not commit its outcome. Nothing advanced and nothing is
#: published.
#:
#: Two conditions produce it, and they differ in what fixes them. A HALT or an invalidation
#: arriving mid-stage means governance stopped authorising the stage; the stage is re-run once the
#: run is resumed. A dataset snapshot that declares itself not a measurement means the stage may
#: never commit under that snapshot at all — resuming changes nothing, and only re-running against
#: real data does. The status is the same because the *fact* is the same, and it is the fact
#: ``StageResult`` protects: the reason says which, and ``.value`` raises either way.
HELD = "HELD"

#: The runner raised. The run record stays, the state does not move.
CRASHED = "CRASHED"

STAGE_STATUSES = (COMPLETED, REFUSED, HELD, CRASHED)

ACTION_COMPLETED = "stage.completed"
ACTION_REFUSED = "stage.refused"
ACTION_HELD = "stage.held"
ACTION_CRASHED = "stage.crashed"


# -- the register ---------------------------------------------------------------

class StageAuthority(collections.namedtuple("StageAuthority", "requires advances")):
    """What governance demands of one stage.

    :param requires: the governance state the run must have reached. For a stage that completes a
        transition this is necessarily the state immediately before its target, so the
        authorisation check and the transition cannot disagree about what is legal.
    :param advances: the state this stage completes, or ``None`` for a stage that computes
        something without moving the run.
    """

    __slots__ = ()


#: Every stage in :data:`phase0.runs.STAGES`, and what authorises it.
#:
#: A stage absent from here has no ordering rule at all, so absence is a test failure rather than a
#: permissive default — the same discipline ``tests/test_lane_independence.py`` applies to packages.
STAGE_AUTHORITY = {
    # Build lane. Bounded by the parameter freeze, repeatable, moves nothing.
    "step0.universe": StageAuthority(PARAMETERS_FROZEN, None),
    "golden_set.trace": StageAuthority(PARAMETERS_FROZEN, None),
    "known_answer.battery": StageAuthority(PARAMETERS_FROZEN, None),
    "pipeline.buy_quality": StageAuthority(PARAMETERS_FROZEN, None),
    "benchmark.match": StageAuthority(PARAMETERS_FROZEN, None),
    "follower.adjust": StageAuthority(PARAMETERS_FROZEN, None),
    "reconciliation.cross_source": StageAuthority(PARAMETERS_FROZEN, None),

    # The validation gate. Its completion *is* VALIDATION_PASSED.
    "validation.independent": StageAuthority(PARAMETERS_FROZEN, VALIDATION_PASSED),

    # Execution lane. Each completes a transition, so each runs exactly once.
    "null.leader": StageAuthority(CODE_AND_DATA_FROZEN, NULL_COMPLETE),
    "null.follower": StageAuthority(CODE_AND_DATA_FROZEN, NULL_COMPLETE),
    "threshold.calibrate": StageAuthority(NULL_COMPLETE, THRESHOLD_LOCKED),
    "main_test": StageAuthority(THRESHOLD_LOCKED, MAIN_TEST_EXECUTED),
    "decision.emit": StageAuthority(MAIN_TEST_EXECUTED, DECISION_EMITTED),
}

#: Every stage that stands on the validation gate — one that *is* ``VALIDATION_PASSED`` or one that
#: requires it to have happened. Ticket 02 and §9.5: a ``NOT INDEPENDENT`` validation status blocks
#: the main test, and blocking it here is what makes that the governed stage list refusing rather
#: than a note in a report.
#:
#: Derived from :data:`STAGE_AUTHORITY` and :func:`~phase0.governance.position` rather than listed,
#: for the same reason ``NOT_REAL_MAY_NOT_ADVANCE`` is derived: a stage added to the execution lane
#: is covered by default instead of being permitted by omission. The build lane is deliberately
#: outside it — the validator's own golden-set work is a build-lane stage, and a register that
#: refused it would refuse the validator the work that earns the status.
VALIDATION_GATED_STAGES = tuple(sorted(
    name for name, authority in STAGE_AUTHORITY.items()
    if position(authority.requires) >= position(VALIDATION_PASSED)
    or (authority.advances is not None
        and position(authority.advances) >= position(VALIDATION_PASSED))
))

#: The states a person enters directly, because each records a human act rather than a computation:
#: freezing the parameter set (ticket 11) and freezing code and data (ticket 39).
#:
#: Every other state is *earned* by a stage completing. There is deliberately no general "advance"
#: capability anywhere in this package or its command line — one would let the whole chain be
#: walked without anything ever running, which is the failure the state machine exists to prevent.
MANUAL_TRANSITIONS = (PARAMETERS_FROZEN, CODE_AND_DATA_FROZEN)

#: Of the manual transitions, the ones whose act is *about* a dataset, so a caller can be required
#: to name it. Freezing code and data (ticket 39) records which data was frozen — the snapshot is
#: half of what the act consists of. Freezing parameters (ticket 11) happens before any data has
#: been read, so there is nothing to name and requiring one would only teach people to invent one.
#:
#: Data, so that adding a state here is what makes ``phase0 freeze`` demand a snapshot for it.
MANUAL_TRANSITIONS_WITH_A_DATASET = (CODE_AND_DATA_FROZEN,)


def companion_stages(stage):
    """Every stage bearing on the same transition as ``stage``, itself included.

    Empty for a stage that completes no transition. Derived from :data:`STAGE_AUTHORITY` rather
    than listed, so adding a third null stage makes it required without anyone remembering to.
    """
    target = STAGE_AUTHORITY[stage].advances
    if target is None:
        return ()
    return tuple(sorted(name for name, authority in STAGE_AUTHORITY.items()
                        if authority.advances == target))


def completed_stages(audit):
    """Stages recorded complete since the last registered code version.

    Scoping to the last ``governance.register_code_version`` is what makes a re-run after an
    invalidation a genuinely new experiment: the null it rebuilds starts from nothing, exactly as
    the seed derivation makes its draws genuinely new.
    """
    entries = audit.entries()
    start = 0
    for index, entry in enumerate(entries):
        if entry.action == "governance.register_code_version":
            start = index + 1
    return {entry.detail.get("stage") for entry in entries[start:]
            if entry.action == ACTION_COMPLETED}


# -- what the runner is given ---------------------------------------------------

class StageContext(object):
    """The pinned inputs of one stage, handed to the runner.

    It carries what a stage needs to reproduce itself and nothing that decides: no governance
    handle, no way to transition, no way to halt. A runner that could move the state machine would
    be a runner that could authorise itself.
    """

    __slots__ = ("run_id", "stage", "requester", "commit", "config", "config_hash",
                 "dataset_snapshot", "master_seed", "seed_rule")

    def __init__(self, record, config):
        self.run_id = record.run_id
        self.stage = record.stage
        self.requester = record.requester
        self.commit = record.commit
        self.config = dict(config or {})
        self.config_hash = record.config_hash
        self.dataset_snapshot = record.dataset_snapshot
        self.master_seed = record.master_seed
        self.seed_rule = record.seed_rule

    def child_seed(self, purpose, index=0):
        """Derive one child seed under this run's pinned master seed and commit.

        Every stochastic step draws from here rather than from a global RNG, so a stage carries no
        unseeded randomness and the same ``(master_seed, commit)`` replays it exactly.
        """
        return derive_child_seed(self.master_seed, self.commit, purpose, index)

    def __repr__(self):
        return "<StageContext {} run={} commit={}>".format(self.stage, self.run_id, self.commit)


# -- what comes back ------------------------------------------------------------

class StageResult(object):
    """The outcome of one stage request. Every path returns one of these.

    ``value`` is readable only when the stage completed. A refused, held or crashed stage raises
    :class:`~phase0.errors.StageNotCompleted` instead of yielding ``None``, because the caller that
    reads a value without reading a status is the failure this guards — and the guard is on the
    condition "this stage did not complete", not on any one status, so there is no outcome for
    which that caller silently gets a plausible-looking nothing.
    """

    __slots__ = ("stage", "status", "requester", "run_id", "state_before", "state_after",
                 "advanced_to", "pending", "reason", "error", "_value")

    def __init__(self, stage, status, requester, run_id, state_before, state_after,
                 advanced_to=None, pending=(), reason=None, error=None, value=None):
        self.stage = stage
        self.status = status
        self.requester = requester
        self.run_id = run_id
        self.state_before = state_before
        self.state_after = state_after
        self.advanced_to = advanced_to
        self.pending = tuple(pending)
        self.reason = reason
        self.error = error
        self._value = value

    @property
    def completed(self):
        return self.status == COMPLETED

    @property
    def error_type(self):
        return type(self.error).__name__ if self.error is not None else None

    @property
    def value(self):
        if self.status != COMPLETED:
            raise StageNotCompleted(self.stage, self.status, self.reason)
        return self._value

    def raise_for_status(self):
        """Return ``self`` when the stage completed; raise otherwise. For callers that prefer it."""
        if self.status != COMPLETED:
            raise StageNotCompleted(self.stage, self.status, self.reason)
        return self

    def to_dict(self):
        """The governance record of the outcome. Deliberately without the stage's value.

        What a stage computed is the lane's business and belongs in its own artifact; the audit
        trail records that it ran, under what, and what governance did about it.
        """
        return {
            "stage": self.stage,
            "status": self.status,
            "requester": self.requester,
            "run_id": self.run_id,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "advanced_to": self.advanced_to,
            "pending": list(self.pending),
            "reason": self.reason,
            "error_type": self.error_type,
        }

    def __repr__(self):
        return "<StageResult {} {} run={}>".format(self.stage, self.status, self.run_id)


# -- wiring ---------------------------------------------------------------------

Wiring = collections.namedtuple(
    "Wiring", "root audit preconditions governance runs parameters")


def wire(root, clock=None, id_factory=None, run_id=None):
    """The five collaborators, all writing to one state directory and one audit log.

    They share the log deliberately. A precondition recorded in one file, a transition in another
    and a stage outcome in a third would be three accounts of the same run that could disagree; one
    hash-chained sequence cannot.

    ``parameters`` is the ticket-11 :class:`~phase0.parameters.ParameterRegister`. It holds no state
    of its own: the values are a module constant and frozen-ness is read from ``governance``, so it
    is here to give the CLI and the stages one already-wired way to reach both. It carries **no**
    freeze capability that this function supplies — :meth:`~phase0.parameters.ParameterRegister.
    freeze` takes a :class:`~phase0.parameters.FreezeRecord` and nothing here builds one.
    """
    root = str(root)
    log_path = os.path.join(root, "audit.jsonl")
    audit = AuditLog(log_path) if clock is None else AuditLog(log_path, clock)
    governance = GovernanceMachine(
        os.path.join(root, "governance.json"), audit, run_id=run_id)
    return Wiring(
        root=root,
        audit=audit,
        preconditions=PreconditionRegister(os.path.join(root, "preconditions.json"), audit),
        governance=governance,
        runs=RunStore(os.path.join(root, "runs"), audit, clock=clock, id_factory=id_factory),
        parameters=ParameterRegister(governance, audit),
    )


# -- the entry point ------------------------------------------------------------

def execute_stage(stage, runner, requester, *, governance, preconditions, runs, audit,
                  commit, dataset_snapshot, config=None, master_seed=None):
    """Run one stage under the governance machine's authority, and record what happened.

    :param stage: a key of :data:`STAGE_AUTHORITY`. Unknown is a :class:`ValueError`, not a
        refusal — a refusal is governance working, and this is a caller that is wrong.
    :param runner: ``runner(context) -> value``, called with a :class:`StageContext`. Taken as an
        argument because ``phase0`` is SHARED and must not know what a stage does.
    :param requester: who asked — a person or an agent identifier. Required.
    :param governance: the :class:`~phase0.governance.GovernanceMachine`.
    :param preconditions: the :class:`~phase0.preconditions.PreconditionRegister`.
    :param runs: the :class:`~phase0.runs.RunStore`.
    :param audit: the :class:`~phase0.audit.AuditLog` the other three write to. :func:`wire` builds
        a consistent set.
    :param commit: source commit the run is pinned to.
    :param dataset_snapshot: dataset snapshot identifier. Required, and refused blank by the run
        store. One that declares itself not a measurement (:mod:`phase0.snapshots`) is executed and
        recorded, and ``HELD`` rather than committed, for every stage that bears on a transition.
    :param config: the stage's configuration. Hashed into the run record, copied into the context.
    :param master_seed: pin it to replay a documented run; omitted, the run record mints one.
    :returns: a :class:`StageResult`. Never ``None``, on any path.
    """
    authority = STAGE_AUTHORITY.get(stage)
    if authority is None:
        raise ValueError(
            "unknown stage {!r}; expected one of {}".format(stage, ", ".join(sorted(STAGE_AUTHORITY)))
        )
    if not callable(runner):
        raise TypeError(
            "runner must be callable: execute_stage authorises and records, and deliberately does "
            "not know what a stage does"
        )
    if not requester or not str(requester).strip():
        raise ValueError("every stage request must name its requester — human or agent")
    requester = str(requester).strip()

    state_before = governance.state

    # 1-2. the start gate, then governance — both before anything is written.
    try:
        preconditions.require_ready()
        _authorise(governance, authority, "Stage {}".format(stage))
    except Phase0Error as exc:
        return _record_outcome(
            audit, ACTION_REFUSED,
            StageResult(stage, REFUSED, requester, None, state_before, governance.state,
                        reason=str(exc), error=exc),
        )

    # 2b. ticket 02's register. A recorded Independent Validator whose validation status does not
    #     permit the main test refuses every stage from VALIDATION_PASSED onward — including
    #     `validation.independent` itself, which is the only stage that reaches that state, so the
    #     block propagates through governance's own ordering rather than through a second rule.
    #     Still before step 3: a refused stage leaves no run record.
    if stage in VALIDATION_GATED_STAGES:
        refusal = preconditions.independence_refusal("stage {}".format(stage))
        if refusal is not None:
            return _record_outcome(
                audit, ACTION_REFUSED,
                StageResult(stage, REFUSED, requester, None, state_before, governance.state,
                            reason=refusal, error=NotIndependentError(refusal)),
            )

    # 3. the run record, before the runner is called.
    record = runs.open_run(
        stage=stage, commit=commit, config=config if config is not None else {},
        dataset_snapshot=dataset_snapshot, requester=requester, master_seed=master_seed,
    )

    # 4. the runner.
    try:
        value = runner(StageContext(record, config))
    except BaseException as exc:  # evidence is owed for any abrupt exit, not only for Exception
        result = _record_outcome(
            audit, ACTION_CRASHED,
            StageResult(stage, CRASHED, requester, record.run_id, state_before, governance.state,
                        reason="{}: {}".format(type(exc).__name__, exc), error=exc),
        )
        if not isinstance(exc, Exception):
            # KeyboardInterrupt and SystemExit are control flow, not stage failures. The evidence
            # is filed; the exception keeps going.
            raise
        return result

    # 5. governance re-checked. A HALT or an invalidation arriving while the stage ran holds the
    #    outcome rather than committing it — the condition is "governance no longer authorises
    #    this", not "someone pressed halt".
    try:
        _authorise(governance, authority, "Committing stage {}".format(stage))
    except Phase0Error as exc:
        return _record_outcome(
            audit, ACTION_HELD,
            StageResult(stage, HELD, requester, record.run_id, state_before, governance.state,
                        reason=str(exc), error=exc),
        )

    # 5b. the data the stage ran over. A snapshot that declares itself not a measurement holds the
    #     outcome for every stage that bears on a transition — including one whose companions are
    #     still outstanding, because `completed_stages` counts it from the audit log and a
    #     COMPLETED entry here would let a *later* stage advance on the strength of it.
    if authority.advances is not None:
        refusal = advancement_refusal(dataset_snapshot, authority.advances)
        if refusal is not None:
            return _record_outcome(
                audit, ACTION_HELD,
                StageResult(stage, HELD, requester, record.run_id, state_before,
                            governance.state,
                            reason="stage {} completed and is not committed. {}".format(
                                stage, refusal)),
            )

    # 6. the transition, and only now.
    outstanding = [name for name in companion_stages(stage)
                   if name != stage and name not in completed_stages(audit)]
    advanced_to = None
    if authority.advances is not None and not outstanding:
        advanced_to = governance.transition(
            authority.advances, requester, {"stage": stage}, run_id=record.run_id,
            dataset_snapshot=dataset_snapshot,
        )

    # 7. the audit entry.
    return _record_outcome(
        audit, ACTION_COMPLETED,
        StageResult(stage, COMPLETED, requester, record.run_id, state_before, governance.state,
                    advanced_to=advanced_to, pending=outstanding, value=value),
    )


def _authorise(governance, authority, what):
    """Ask governance whether this stage may run, changing nothing.

    Authorisation and commitment are separate calls on purpose. A single ``transition`` here would
    advance the run before the stage had done anything, so a crash would leave the state past work
    that never happened.
    """
    if authority.advances is not None:
        return governance.authorise(authority.advances, what)
    return governance.require_state(authority.requires, what)


def _record_outcome(audit, action, result):
    """Append the outcome, then return it. Every path through :func:`execute_stage` ends here."""
    audit.append(result.requester, action, {
        "stage": result.stage,
        "status": result.status,
        "run_id": result.run_id,
        "state": result.state_after,
        "advanced_to": result.advanced_to,
        "pending": list(result.pending),
        "reason": result.reason,
        "error_type": result.error_type,
    })
    return result
