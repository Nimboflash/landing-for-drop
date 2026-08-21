"""The governance state machine — ticket 06.

The pre-registration's ordering rules are the experiment's integrity. They are not advice, and
they cannot live in people's memory across a 10-12 week run worked by different sessions and
different agents. This module makes them a property of the system: **no stage executes that
governance has not authorised.**

The order, from ticket 06:

    PARAMETERS_OPEN -> PARAMETERS_FROZEN -> VALIDATION_PASSED -> CODE_AND_DATA_FROZEN
    -> NULL_COMPLETE -> THRESHOLD_LOCKED -> MAIN_TEST_EXECUTED -> DECISION_EMITTED

Two properties are load-bearing and are proven by rejection tests rather than by inspection:

* ``NULL_COMPLETE`` is unreachable without ``VALIDATION_PASSED`` — because the null distribution
  is computed by the same code as the main test, and a bug affects both identically. A null built
  on unvalidated code cannot detect the bug it shares.
* ``MAIN_TEST_EXECUTED`` is unreachable without ``THRESHOLD_LOCKED`` — because a threshold chosen
  after seeing the result is not a threshold.

There is no override path. A request to reinterpret a failed gate is refused by the same mechanism
that refuses any other unauthorised write.

What the data a run was over has to do with the order
-----------------------------------------------------

Every state past ``PARAMETERS_OPEN`` is a claim about a real experiment: four of them that a person
acted, three that a computation was performed over the experiment's data. A run whose dataset
snapshot *declares itself not a measurement* — see :mod:`phase0.snapshots` — may execute stages and
record what they produced, and may not leave the machine in a state making either claim.
:func:`advancement_refusal` is that rule; :meth:`GovernanceMachine.transition` and
:func:`phase0.execution.execute_stage` are the two places it is enforced, and the difference
between them is only what a refusal looks like at each.
"""

import json
import os

from .errors import (
    FrozenError,
    HaltedError,
    InvalidatedError,
    NotAMeasurementError,
    TransitionError,
)
from .snapshots import declaration_clause

# -- states -------------------------------------------------------------------

PARAMETERS_OPEN = "PARAMETERS_OPEN"
PARAMETERS_FROZEN = "PARAMETERS_FROZEN"
VALIDATION_PASSED = "VALIDATION_PASSED"
CODE_AND_DATA_FROZEN = "CODE_AND_DATA_FROZEN"
NULL_COMPLETE = "NULL_COMPLETE"
THRESHOLD_LOCKED = "THRESHOLD_LOCKED"
MAIN_TEST_EXECUTED = "MAIN_TEST_EXECUTED"
DECISION_EMITTED = "DECISION_EMITTED"

#: The only permitted order. Index in this tuple is the only ordering that exists.
ORDER = (
    PARAMETERS_OPEN,
    PARAMETERS_FROZEN,
    VALIDATION_PASSED,
    CODE_AND_DATA_FROZEN,
    NULL_COMPLETE,
    THRESHOLD_LOCKED,
    MAIN_TEST_EXECUTED,
    DECISION_EMITTED,
)

#: What each transition requires, phrased for the refusal message.
_PREREQUISITE_REASON = {
    PARAMETERS_FROZEN: "the parameter set must be open and complete before it can be frozen",
    VALIDATION_PASSED: "the four-layer validation gate runs against frozen parameters",
    CODE_AND_DATA_FROZEN: "code and data are frozen only after validation passes",
    NULL_COMPLETE: (
        "the null distribution is computed by the same code as the main test; building it "
        "before validation passes means a shared bug cannot be detected by it"
    ),
    THRESHOLD_LOCKED: "the threshold is calibrated against a completed null distribution",
    MAIN_TEST_EXECUTED: (
        "the main test runs once, against a locked threshold; a threshold chosen after the "
        "result is not a threshold"
    ),
    DECISION_EMITTED: "the decision record follows the single main-test execution",
}

#: Terminal gate outcomes. Write-once.
GATE_GO = "GO"
GATE_CONDITIONAL_REVIEW = "CONDITIONAL REVIEW"
GATE_STOP = "STOP"
GATE_OUTCOMES = (GATE_GO, GATE_CONDITIONAL_REVIEW, GATE_STOP)


#: The four states that record a **human act about a real experiment**: a person froze the
#: pre-registration (ticket 11), the four-layer validation gate passed against real data, a person
#: froze code and data (ticket 39), a decision record was emitted about a hypothesis.
#:
#: Named as a group because advancing one of these on data that was not measured is a machine
#: asserting that a person did something, which is the sharpest form of the failure this whole
#: instrument exists to prevent.
HUMAN_ACT_STATES = (
    PARAMETERS_FROZEN,
    VALIDATION_PASSED,
    CODE_AND_DATA_FROZEN,
    DECISION_EMITTED,
)

#: The three that record a **computation over the experiment's data** rather than a human act.
COMPUTED_STATES = (NULL_COMPLETE, THRESHOLD_LOCKED, MAIN_TEST_EXECUTED)

#: Every state a run under a not-real snapshot may not reach: all of them except the one the
#: machine starts in.
#:
#: Derived from :data:`ORDER` rather than listed, so a state added to the machine is refused by
#: default instead of being permitted by omission. That direction is deliberate: the failure being
#: guarded is a state advancing that nobody meant to advance, and a hand-written list would quietly
#: stop covering the machine the day it grew.
#:
#: It is wider than :data:`HUMAN_ACT_STATES` because the computed three are worth refusing too, and
#: ``MAIN_TEST_EXECUTED`` most of all: it is write-once, so a run over data that does not exist
#: would consume the single main-test execution the pre-registration is built around and the real
#: one would afterwards be refused as *"already in this state"*. That is not a reputational
#: problem, it is a destroyed experiment.
NOT_REAL_MAY_NOT_ADVANCE = frozenset(ORDER) - {PARAMETERS_OPEN}


def position(state):
    try:
        return ORDER.index(state)
    except ValueError:
        raise ValueError("unknown state {!r}".format(state))


def _why_protected(to_state):
    """Why this particular state may not be reached on data that was not measured."""
    if to_state in HUMAN_ACT_STATES:
        return (
            "{} records a human act about a real experiment — a person froze a pre-registration or "
            "froze code and data, or a validation gate passed against real data, or a decision was "
            "emitted about a hypothesis. Nothing computed from data that is not a measurement is "
            "evidence that any of those happened.".format(to_state)
        )
    if to_state in COMPUTED_STATES:
        return (
            "{} records a computation over the experiment's data. A null distribution built over "
            "data that was never measured is a distribution of nothing, a threshold calibrated "
            "against it has no referent, and MAIN_TEST_EXECUTED is write-once — reaching it here "
            "would consume the single main-test execution and the real one would afterwards be "
            "refused as 'already in this state'.".format(to_state)
        )
    return (
        "{} is a state of the pre-registered experiment past PARAMETERS_OPEN, so reaching it "
        "claims the experiment progressed. It carries no more specific reason than that because it "
        "was added to ORDER without being classified as a human act or a computation; it is "
        "refused by default, which is the direction NOT_REAL_MAY_NOT_ADVANCE is derived in "
        "precisely so a new state is covered before anyone remembers to cover it.".format(to_state)
    )


def advancement_refusal(dataset_snapshot, to_state):
    """Why this snapshot may not advance the machine to ``to_state``, or ``None`` if it may.

    The whole rule, in one place, so the two enforcement points cannot drift into disagreeing about
    it: :meth:`GovernanceMachine.transition` raises the sentence and
    :func:`phase0.execution.execute_stage` carries it as the reason of a ``HELD`` result. The
    difference between them is what a refusal looks like at each, not what is refused.

    :param dataset_snapshot: the identifier the run is pinned to. ``None`` — a transition that was
        never told which data it is about — returns ``None``. See
        :meth:`GovernanceMachine.transition` for what that does and does not cover.
    :param to_state: the state that would be reached.
    :returns: a sentence naming the snapshot, the rule, the state and what advancing would cost, or
        ``None`` when nothing objects.

    **What it decides and what it does not.** It answers only "would advancing on this data claim
    something that did not happen?". It says nothing about ordering, halts, invalidation or whether
    the data is any good; ``_check_transition`` and ``_guard_runnable`` own those, and a snapshot
    that passes here has not been authorised by anything.
    """
    clause = declaration_clause(dataset_snapshot)
    if clause is None:
        return None
    if to_state not in NOT_REAL_MAY_NOT_ADVANCE:
        return None
    return (
        "{} Advancing to {} is refused. {} A run under such a snapshot may execute stages and "
        "record what they produced — the run record, the stage outcome and the audit entry are all "
        "written — and may not leave the governance machine in a state that says the experiment "
        "progressed. There is nothing here to resume or retry: the snapshot is what is wrong, so "
        "the only thing that changes the answer is re-running against a real dataset "
        "snapshot.".format(clause, to_state, _why_protected(to_state))
    )


class GovernanceMachine(object):
    """Authorises stages. Records everything. Cannot mutate a result.

    :param path: JSON file holding the machine's own state.
    :param audit_log: an :class:`~phase0.audit.AuditLog`. Required — an unrecorded transition is
        not permitted.
    :param run_id: the run record every transition belongs to.
    """

    def __init__(self, path, audit_log, run_id=None):
        self.path = str(path)
        self._audit = audit_log
        self._run_id = run_id

    # -- persistence -----------------------------------------------------------

    def _load(self):
        if not os.path.exists(self.path):
            return {
                "state": PARAMETERS_OPEN,
                "halted": False,
                "invalidated": False,
                "invalidation_reason": None,
                "code_version": None,
                "parameters": {},
                "gate_outcome": None,
                "run_id": self._run_id,
            }
        with open(self.path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def _save(self, data):
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")

    # -- queries ---------------------------------------------------------------

    @property
    def state(self):
        return self._load()["state"]

    @property
    def halted(self):
        return bool(self._load()["halted"])

    @property
    def invalidated(self):
        return bool(self._load()["invalidated"])

    @property
    def gate_outcome(self):
        return self._load().get("gate_outcome")

    def parameters(self):
        return dict(self._load().get("parameters", {}))

    def _record(self, requester, action, detail, run_id=None):
        payload = dict(detail or {})
        payload["run_id"] = run_id or self._load().get("run_id") or self._run_id
        self._audit.append(requester, action, payload)

    # -- guards ----------------------------------------------------------------

    def _guard_runnable(self, data, what):
        if data["invalidated"]:
            raise InvalidatedError(
                "Run is INVALIDATED ({}). {} is refused. Register a new code version, then "
                "re-run the whole validation gate, rebuild the null from scratch, and re-run "
                "the main test. Patching the previous run is not permitted, and choosing "
                "between the old and new result is not permitted.".format(
                    data.get("invalidation_reason") or "no reason recorded", what
                )
            )
        if data["halted"]:
            raise HaltedError(
                "Run is HALTED by operations. {} is refused until it is resumed. A halt holds "
                "state; it does not advance, revert, or change anything.".format(what)
            )

    # -- transitions -----------------------------------------------------------

    def _check_transition(self, data, to_state):
        """Everything :meth:`transition` refuses, decided without performing it.

        Split out so that a stage can be *authorised* before it runs and the state advanced only
        after it succeeds. Advancing at authorisation time would move the run past work that had
        not happened yet, and a crash would leave it there.
        """
        current = data["state"]
        try:
            target = position(to_state)
        except ValueError:
            raise TransitionError(current, to_state, "unknown state")
        here = position(current)

        if target == here:
            raise TransitionError(current, to_state, "already in this state")
        if target < here:
            raise TransitionError(
                current, to_state,
                "the order is one-way; a completed stage cannot be revisited, and reverting "
                "would let a result be recomputed after it was seen",
            )
        if target > here + 1:
            missing = ORDER[here + 1:target]
            raise TransitionError(
                current, to_state,
                "out of order — {} must complete first. {}".format(
                    ", ".join(missing), _PREREQUISITE_REASON.get(to_state, "")
                ).strip(),
            )
        return current

    def authorise(self, to_state, what=None):
        """Would a transition to ``to_state`` be permitted? Raises the same refusal, writes nothing.

        :param what: named in the halt and invalidation refusals, so the reason says which stage
            was stopped rather than only which transition.
        """
        data = self._load()
        self._guard_runnable(data, what or "Transition to {}".format(to_state))
        self._check_transition(data, to_state)
        return data["state"]

    def require_state(self, minimum, what):
        """Refuse unless the run has reached ``minimum``, without advancing anything.

        The floor for a stage that computes something without completing a transition. It is a
        floor rather than an equality so such a stage stays re-runnable for the rest of the run:
        the build lane retries, and only stages that *are* transitions run exactly once.
        """
        data = self._load()
        self._guard_runnable(data, what)
        current = data["state"]
        here, floor = position(current), position(minimum)
        if here < floor:
            missing = ORDER[here + 1:floor + 1]
            raise TransitionError(
                current, what,
                "out of order — {} must complete first. {}".format(
                    ", ".join(missing), _PREREQUISITE_REASON.get(minimum, "")
                ).strip(),
            )
        return current

    def transition(self, to_state, requester, detail=None, run_id=None, dataset_snapshot=None):
        """Advance exactly one step. Anything else is refused.

        :param run_id: the run record this transition belongs to, when a stage earned it. Defaults
            to the machine's own run id.
        :param dataset_snapshot: the identifier of the data this transition is about, when the
            caller has one.
        :raises NotAMeasurementError: ``dataset_snapshot`` declares itself not a measurement. See
            :func:`advancement_refusal`.

        **What ``dataset_snapshot`` covers, and what it does not.** This method is the backstop:
        ``execute_stage`` is not the only caller, so a check that lived only there would leave the
        two manual human acts — ``PARAMETERS_FROZEN`` and ``CODE_AND_DATA_FROZEN``, entered from
        ``phase0 freeze`` — reachable on data that was never measured. Passing the snapshot here
        closes that.

        It closes it **only for callers that pass one**. The parameter defaults to ``None`` because
        one transition genuinely has no dataset to name: ``PARAMETERS_FROZEN`` freezes a
        pre-registration before any data has been read. This method cannot tell that case from a
        caller who simply withheld the snapshot it had, and it does not pretend to — an omitted
        snapshot is not checked, and an unchecked transition is not a permitted one, it is an
        unexamined one.
        """
        data = self._load()
        refusal = advancement_refusal(dataset_snapshot, to_state)
        if refusal is not None:
            raise NotAMeasurementError(refusal)
        self._guard_runnable(data, "Transition to {}".format(to_state))
        current = self._check_transition(data, to_state)

        data["state"] = to_state
        self._save(data)
        self._record(requester, "governance.transition",
                     {"from": current, "to": to_state, "detail": detail or {}},
                     run_id=run_id)
        return to_state

    # -- parameter set ---------------------------------------------------------

    def write_parameter(self, key, value, requester):
        """Write a parameter. Refused once the parameter set is frozen.

        Refused for *any* write, including one that only widens or clarifies a definition. There
        is no such thing as a harmless edit to a frozen pre-registration: the reader cannot tell
        a clarification from a result-driven change, so neither can the machine.
        """
        data = self._load()
        self._guard_runnable(data, "Parameter write")
        if position(data["state"]) >= position(PARAMETERS_FROZEN):
            raise FrozenError(
                "Parameter set is frozen (state {}); refusing to write {!r}. This applies to "
                "clarifications and widenings as well as changes. If a parameter is genuinely "
                "wrong, that is an invalidation, not an edit.".format(data["state"], key)
            )
        data.setdefault("parameters", {})[key] = value
        self._save(data)
        self._record(requester, "governance.parameter_write", {"key": key, "value": value})
        return value

    def freeze_parameters(self, requester, manifest=None, dataset_snapshot=None):
        """Perform the ticket 11 human act.

        ``dataset_snapshot`` is accepted and passed through, and is ``None`` by default because the
        parameter freeze precedes any data: there is normally nothing to name. A caller that *does*
        know which data it is standing on — a harness driving the machine over generated input, say
        — passes it and is refused. One that names nothing is not checked.
        """
        return self.transition(PARAMETERS_FROZEN, requester, {"manifest": manifest or {}},
                               dataset_snapshot=dataset_snapshot)

    # -- gate outcome ----------------------------------------------------------

    def record_gate_outcome(self, outcome, requester, evidence=None):
        """Write the terminal outcome. Write-once, with no override path."""
        if outcome not in GATE_OUTCOMES:
            raise ValueError(
                "outcome must be one of {}, got {!r}".format(", ".join(GATE_OUTCOMES), outcome)
            )
        data = self._load()
        self._guard_runnable(data, "Gate outcome write")
        if position(data["state"]) < position(MAIN_TEST_EXECUTED):
            raise TransitionError(
                data["state"], "record_gate_outcome",
                "the gate outcome follows the main test; it cannot be written before it",
            )
        if data.get("gate_outcome") is not None:
            raise FrozenError(
                "Gate outcome is already recorded as {!r} and is write-once. There is no path "
                "by which a person or an agent may reinterpret it. If the run itself was "
                "invalid, invalidate the run — that is a different claim, and it discards the "
                "result rather than rewriting it.".format(data["gate_outcome"])
            )
        data["gate_outcome"] = outcome
        self._save(data)
        self._record(requester, "governance.gate_outcome",
                     {"outcome": outcome, "evidence": evidence or {}})
        return outcome

    # -- operations ------------------------------------------------------------

    def halt(self, requester, reason):
        """Stop execution and hold state. Cannot advance, revert, or mutate anything.

        Available to operations for security, data corruption, or infrastructure failure. It is
        deliberately the only operations capability, and it is deliberately inert.
        """
        data = self._load()
        data["halted"] = True
        self._save(data)
        self._record(requester, "governance.halt", {"reason": reason, "state": data["state"]})
        return True

    def resume(self, requester, reason):
        data = self._load()
        data["halted"] = False
        self._save(data)
        self._record(requester, "governance.resume", {"reason": reason, "state": data["state"]})
        return True

    # -- invalidation ----------------------------------------------------------

    def invalidate(self, requester, reason):
        """Mark the run INVALIDATED. Nothing advances until a new code version is registered."""
        data = self._load()
        data["invalidated"] = True
        data["invalidation_reason"] = reason
        self._save(data)
        self._record(requester, "governance.invalidate",
                     {"reason": reason, "state_at_invalidation": data["state"]})
        return True

    def register_code_version(self, commit, requester, note=None):
        """Clear an invalidation by registering the fixed code, and rewind the work to redo.

        Parameters stay frozen — re-opening them would be changing parameters after seeing a
        result, which is the thing the whole design exists to prevent. Everything downstream of
        the freeze is discarded and redone: validation gate, null distribution, main test.
        """
        data = self._load()
        if not data["invalidated"]:
            raise InvalidatedError(
                "Run is not invalidated; there is nothing to clear. Registering a code version "
                "is the recovery path from an invalidation, not a way to change code mid-run."
            )
        previous_state = data["state"]
        if position(previous_state) > position(PARAMETERS_FROZEN):
            data["state"] = PARAMETERS_FROZEN
        data["invalidated"] = False
        data["invalidation_reason"] = None
        data["code_version"] = commit
        data["gate_outcome"] = None
        self._save(data)
        self._record(requester, "governance.register_code_version", {
            "commit": commit,
            "note": note,
            "rewound_from": previous_state,
            "rewound_to": data["state"],
        })
        return data["state"]
