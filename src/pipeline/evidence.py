"""Assemble the arbiter's :class:`gate_validation.RunEvidence` from the holders of record.

``decision.emit`` needs a ``RunEvidence`` and correctly refuses to build its own: a runner that
derived the evidence from the run it is reporting on would be certifying itself —
:func:`pipeline.stages.decide.decision_emit_runner` states the rule and takes the value as an
argument. Until this module, nothing in ``src/`` assembled one; the only assembly in the tree was
a hand-built test fixture. This is the assembler.

Why ``pipeline`` and not ``gate_validation``
--------------------------------------------

``gate_validation`` is SHARED: it may import only ``contracts``, and it consumes serialized
artifacts as data precisely so it can never inherit a bug from the code it judges —
``tests/test_lane_independence.py`` holds that edge shut. The assembler must do what the arbiter
must not: read builder-side artifacts. Its inputs are the ``phase0`` governance machine, run store
and audit log, the freeze manifest, and the run's own recorded values. So it lives here, in the
composition root — the one builder package permitted to import both shared packages and leaf
builder packages — and it hands the arbiter a finished :class:`~gate_validation.RunEvidence`
**as data**. The arbiter never calls back into anything in this module.

Collecting, not deriving, and not confirming
--------------------------------------------

:func:`assemble_run_evidence` derives none of the nine fields. Each is collected from its holder
of record, and when a holder cannot supply its part the assembly refuses with
:class:`EvidenceIncomplete` naming the missing piece. It never fills a gap with a value it
computed, because an assembler that filled a gap would be the self-certification this seam exists
to prevent, moved one function over.

    field                       holder of record
    ------------------------    ----------------------------------------------------------------
    manifest                    the freeze manifest, as the caller read it (§9.6)
    observed                    the run's own artifacts (:attr:`ObservedArtifacts.manifest`)
    pinned_module_versions      the ``CODE_AND_DATA_FROZEN`` transition's recorded detail — the
                                ticket-39 freeze act, held by the hash-chained audit log
    observed_module_versions    the run's own artifacts (:attr:`ObservedArtifacts.module_versions`)
    validation_status           the validation report (:attr:`ObservedArtifacts.validation_status`)
    governance_states           the audit log's governance transitions, since the last
                                registered code version (§9.7 scoping)
    locked_threshold            the calibration artifact (:attr:`ObservedArtifacts.locked_threshold`)
                                — governance orders the lock and deliberately carries no value
    run_status                  the governance machine (invalidation, with its reason from the
                                audit log) and the run store (the one commit this era's run
                                records pin; prior eras' commits are the discarded versions)
    result_code_version         the completed ``main_test``'s own run record

Assembling is not confirming. Every §9 comparison — manifest against observed, pinned versions
against reported, locked threshold against applied threshold — stays
``gate_validation.check_gate_prerequisites``'s, made on the assembled value. This module refuses
only when a holder holds nothing, or when two holders of record contradict each other: a
governance machine reporting a state its own audit log never recorded is not evidence anyone can
collect, and an assembler that picked one account over the other would be deriving the very fact
it exists to carry.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional

from gate_validation import RunEvidence, RunStatus
from contracts import ValidationStatus
from phase0.audit import AuditLog
from phase0.execution import ACTION_COMPLETED
from phase0.governance import CODE_AND_DATA_FROZEN, ORDER, GovernanceMachine, position
from phase0.runs import RunStore

__all__ = ["EvidenceIncomplete", "ObservedArtifacts", "assemble_run_evidence"]

#: The audit actions this module reads, exactly as ``phase0`` appends them. ``phase0`` writes
#: these as inline literals (``phase0/governance.py:_record`` call sites, ``phase0/runs.py``
#: ``open_run``) and exports no constant for them; restated here in one place so a renamed action
#: has one assembler line to break rather than five.
GOVERNANCE_TRANSITION = "governance.transition"
GOVERNANCE_INVALIDATE = "governance.invalidate"
REGISTER_CODE_VERSION = "governance.register_code_version"
RUN_OPENED = "run.open"

#: The stage whose completed run record names the code version the result belongs to.
MAIN_TEST_STAGE = "main_test"


class EvidenceIncomplete(Exception):
    """A holder of record cannot supply its part of the evidence, so nothing is assembled.

    Raised, never softened into a partial ``RunEvidence``: the arbiter treats an absent field as a
    refusal too, but a ``RunEvidence`` with a guessed field would sail through, and guessing is
    the one thing an evidence assembler must never do. The message names the missing piece and the
    holder that should have held it, so the fix is an errand rather than an investigation.
    """

    def __init__(self, holder, missing, consequence):
        self.holder = holder
        self.missing = missing
        super().__init__(
            "cannot assemble a RunEvidence: {missing}. The holder of record for this piece is "
            "{holder}. The assembler collects what the holders hold and derives nothing, so the "
            "gap is refused rather than filled. {consequence}".format(
                missing=missing, holder=holder, consequence=consequence
            )
        )


@dataclass(frozen=True)
class ObservedArtifacts:
    """What the run's own builder-side artifacts recorded, carried to the assembler as data.

    Four values with four distinct artifacts of origin, bundled because they share a property the
    ``phase0`` collaborators do not have: governance deliberately records no stage *values*
    (``StageResult.to_dict`` omits them on purpose), so each of these lives in an artifact the
    integrator holds rather than in the state directory. The caller loads the artifacts; this
    type carries what they said. A ``None`` means the artifact could not supply the value, and
    :func:`assemble_run_evidence` refuses it by name rather than passing the hole along.
    """

    #: The §9.6 manifest fields as the run observed them — what the run actually used, reported
    #: field by field, for the arbiter to compare against the pinned manifest.
    manifest: Optional[Dict[str, str]]
    #: The module versions the run reported executing, one per module the gate recognises.
    module_versions: Optional[Dict[str, str]]
    #: The validation report's status (§9.5). The report is the VALIDATOR lane's artifact; this
    #: field is what it says, loaded and not derived — a builder-side derivation of it would
    #: delete the independence the validation gate's worth rests on.
    validation_status: Optional[ValidationStatus]
    #: The threshold the calibration artifact locked (§8.3) — ``CalibratedThreshold.threshold``,
    #: from the ``threshold.calibrate`` stage's own value. Governance sequences the lock and
    #: carries no number; the artifact is the only holder there is.
    locked_threshold: Optional[Decimal]


def _era_start(entries):
    """Index of the first entry after the last registered code version.

    The same scoping :func:`phase0.execution.completed_stages` applies, for the same §9.7 reason:
    a re-run after an invalidation is a new experiment, and evidence assembled for it must not
    quote anything the discarded era recorded.
    """
    start = 0
    for index, entry in enumerate(entries):
        if entry.action == REGISTER_CODE_VERSION:
            start = index + 1
    return start


def _governance_states(governance, entries, start):
    """The state sequence the audit log records for the current era, checked against the machine.

    The machine holds only its current state; the sequence — what the arbiter's §9.1 ordering
    check reads — is held by the log's transition entries. An era that opened with a code
    re-registration starts from the state the register entry says it rewound to; the states up to
    that point were reached before the rewind and preserved through it (parameters stay frozen
    across an invalidation), so the prefix is read off the machine's own binding ``ORDER``.
    """
    if start == 0:
        prefix = (ORDER[0],)
    else:
        rewound_to = entries[start - 1].detail.get("rewound_to")
        # position() raises phase0's own "unknown state" ValueError on a malformed entry.
        prefix = ORDER[:position(rewound_to) + 1]

    transitions = [e for e in entries[start:] if e.action == GOVERNANCE_TRANSITION]

    states = list(prefix)
    for entry in transitions:
        recorded_from = entry.detail.get("from")
        if recorded_from != states[-1]:
            raise EvidenceIncomplete(
                holder="the audit log",
                missing="its governance transitions do not chain — a transition is recorded from "
                        "{!r} where the sequence stood at {!r}".format(recorded_from, states[-1]),
                consequence="A state sequence with a gap in its own account is not a sequence the "
                            "arbiter can be handed; the log must be repaired at its source, not "
                            "smoothed over here.",
            )
        states.append(entry.detail.get("to"))

    if states[-1] != governance.state:
        raise EvidenceIncomplete(
            holder="the governance machine and the audit log, jointly",
            missing="the governance machine reports state {!r} but the audit log's transitions "
                    "end at {!r}".format(governance.state, states[-1]),
            consequence="Two holders of record disagree about what happened, and evidence "
                        "assembled from either account would be contradicted by the other.",
        )
    return tuple(states), transitions


def _pinned_module_versions(transitions):
    """The module pins the ticket-39 freeze act recorded, read from its transition entry.

    §9.6 pins module versions at the code-and-data freeze. That freeze is a manual transition —
    a human act, not a computation — so its record *is* the audit log's ``CODE_AND_DATA_FROZEN``
    entry, and the pins live in the detail the act recorded.
    """
    freezes = [e for e in transitions if e.detail.get("to") == CODE_AND_DATA_FROZEN]
    if not freezes:
        raise EvidenceIncomplete(
            holder="the audit log's CODE_AND_DATA_FROZEN transition (the ticket-39 freeze act)",
            missing="no CODE_AND_DATA_FROZEN transition is recorded since the last registered "
                    "code version",
            consequence="Code and data were never frozen for this era, so there are no pinned "
                        "module versions to collect and no §9.6 freeze for a decision to be "
                        "bound to.",
        )
    detail = freezes[-1].detail.get("detail") or {}
    pinned = detail.get("module_versions")
    if not isinstance(pinned, dict) or not pinned:
        raise EvidenceIncomplete(
            holder="the audit log's CODE_AND_DATA_FROZEN transition (the ticket-39 freeze act)",
            missing="the freeze act recorded no module version pins (its detail carries no "
                    "'module_versions' mapping)",
            consequence="A freeze that did not say what it froze pins nothing, and the arbiter's "
                        "per-module §9.6 check would have nothing of record to compare the run "
                        "against.",
        )
    return dict(pinned)


def _opened_run_ids(entries):
    return {e.detail.get("run_id") for e in entries if e.action == RUN_OPENED}


def _code_versions(runs, entries, start):
    """The era's one commit, and the prior eras' discarded commits, from the run store.

    The store holds every era's records; the audit log holds where the eras break. Records opened
    since the last registered code version must agree on a single commit — the assembler refuses
    a disagreement rather than choosing, because §9.6 requires the main test and the null runs to
    be one experiment at one commit, and choosing would be deriving the one fact this field
    exists to carry. Records from before the break executed the superseded versions §9.7 forbids
    quoting, which is exactly what ``RunStatus.discarded_versions`` is for.
    """
    records = runs.list_runs()
    if not records:
        raise EvidenceIncomplete(
            holder="the run store",
            missing="it holds no run records at all",
            consequence="Nothing has run, so there is no code version of record and no run for a "
                        "decision to be evidence about.",
        )

    current_ids = _opened_run_ids(entries[start:])
    prior_ids = _opened_run_ids(entries[:start])

    unaudited = sorted(r.run_id for r in records
                       if r.run_id not in current_ids and r.run_id not in prior_ids)
    if unaudited:
        raise EvidenceIncomplete(
            holder="the run store and the audit log, jointly",
            missing="run record(s) {} were never opened through the audited path — the audit log "
                    "has no run.open entry for them".format(", ".join(unaudited)),
            consequence="A record the hash-chained log did not witness is not part of this run's "
                        "account, and counting it would let an unaudited record vote on the "
                        "run's code version.",
        )

    current = [r for r in records if r.run_id in current_ids]
    if not current:
        raise EvidenceIncomplete(
            holder="the run store",
            missing="every run record predates the last registered code version",
            consequence="§9.7 discards the previous era outright; a new era with no run records "
                        "has produced nothing that evidence could report.",
        )

    commits = sorted({r.commit for r in current})
    if len(commits) != 1:
        raise EvidenceIncomplete(
            holder="the run store",
            missing="the run records since the last registered code version pin {} different "
                    "commits ({})".format(len(commits), ", ".join(commits)),
            consequence="§9.6 requires the main test and the null runs to be one experiment at "
                        "one commit; an assembler that chose between these would be deriving "
                        "the one fact this field exists to collect.",
        )

    discarded = tuple(sorted({r.commit for r in records if r.run_id in prior_ids}))
    return commits[0], discarded


def _run_status(governance, entries, start, code_version, discarded):
    """The §9.7 status: invalidation from the machine, its reason from the audit log."""
    invalidated = governance.invalidated
    reason = None
    if invalidated:
        invalidations = [e for e in entries[start:] if e.action == GOVERNANCE_INVALIDATE]
        if not invalidations:
            raise EvidenceIncomplete(
                holder="the governance machine and the audit log, jointly",
                missing="the governance machine reports the run INVALIDATED but the audit log "
                        "records no invalidation since the last registered code version",
                consequence="An invalidation with no recorded reason is indistinguishable from "
                            "discarding a result someone disliked, and the two holders of "
                            "record disagree about whether one happened at all.",
            )
        reason = invalidations[-1].detail.get("reason")
    return RunStatus(
        code_version=code_version,
        invalidated=invalidated,
        invalidation_reason=reason,
        discarded_versions=discarded,
    )


def _result_code_version(runs, entries, start):
    """The commit of the completed main test's own run record — the result's code version.

    The result a decision reports is the main test's product, so the version that produced it is
    a fact about that stage's run record. Both holders contribute what they hold: the audit log
    says which run completed the stage in this era, and the run store says which commit that run
    was pinned to before it executed.
    """
    completed = [e for e in entries[start:]
                 if e.action == ACTION_COMPLETED and e.detail.get("stage") == MAIN_TEST_STAGE]
    if not completed:
        raise EvidenceIncomplete(
            holder="the audit log",
            missing="no completed main_test is recorded since the last registered code version",
            consequence="There is no main-test result for a decision to be evidence about; a "
                        "result code version invented here would certify a measurement that "
                        "never happened.",
        )
    run_id = completed[-1].detail.get("run_id")
    record = runs.get(run_id)
    if record is None:
        raise EvidenceIncomplete(
            holder="the run store",
            missing="the audit log records main_test completed under run {!r} but the run store "
                    "holds no record of it".format(run_id),
            consequence="The run record is the only statement of which commit the result was "
                        "produced under, and without it the result belongs to no version "
                        "anyone can name.",
        )
    return record.commit


def assemble_run_evidence(governance, runs, audit, freeze_manifest, observed):
    """Collect the nine fields of a :class:`gate_validation.RunEvidence` from their holders.

    :param governance: the :class:`phase0.governance.GovernanceMachine` — supplies the current
        state (checked against the log's account) and whether the run is invalidated.
    :param runs: the :class:`phase0.runs.RunStore` — supplies the era's one pinned commit, the
        discarded eras' commits, and the completed main test's own record.
    :param audit: the :class:`phase0.audit.AuditLog` the other two write to. Verified before it
        is read: collecting from a tamper-evident log without walking its chain would launder a
        doctored log into evidence. Its :class:`phase0.errors.AuditChainError` propagates.
    :param freeze_manifest: the §9.6 manifest as the caller read it — an already-parsed mapping
        or the seam's ``FreezeManifest``. The caller does the file reading, exactly as it does
        for the arbiter.
    :param observed: an :class:`ObservedArtifacts` — what the run's own artifacts recorded.
    :returns: a :class:`gate_validation.RunEvidence`, assembled and unjudged. Whether it
        *satisfies* §9 is ``gate_validation.check_gate_prerequisites``'s question, asked on the
        returned value; an invalidated run assembles fine here and is refused there.
    :raises EvidenceIncomplete: when a holder cannot supply its part, naming the piece and the
        holder. Nothing partial is ever returned.
    :raises TypeError: for a collaborator of the wrong type — a defect in what assembled the
        call, not a gap in the evidence.
    """
    if not isinstance(governance, GovernanceMachine):
        raise TypeError(
            "governance must be the phase0.governance.GovernanceMachine of the run's state "
            "directory, got {}".format(type(governance).__name__)
        )
    if not isinstance(runs, RunStore):
        raise TypeError(
            "runs must be the phase0.runs.RunStore of the run's state directory, got "
            "{}".format(type(runs).__name__)
        )
    if not isinstance(audit, AuditLog):
        raise TypeError(
            "audit must be the phase0.audit.AuditLog the machine and the store write to, got "
            "{}".format(type(audit).__name__)
        )
    if not isinstance(observed, ObservedArtifacts):
        raise TypeError(
            "observed must be an ObservedArtifacts, got {}. Its four fields name the artifacts "
            "they come from, and a looser bundle would leave the holder of a missing piece "
            "unnameable.".format(type(observed).__name__)
        )
    if not isinstance(freeze_manifest, dict) and not hasattr(freeze_manifest,
                                                             "__dataclass_fields__"):
        raise TypeError(
            "freeze_manifest must be an already-parsed mapping or the seam's FreezeManifest, "
            "got {}. The caller does the file reading.".format(type(freeze_manifest).__name__)
        )

    if isinstance(freeze_manifest, dict) and not freeze_manifest:
        raise EvidenceIncomplete(
            holder="the freeze manifest file (§9.6)",
            missing="the freeze manifest is empty",
            consequence="A manifest with no fields pins nothing, and a decision cannot be bound "
                        "to a freeze that never said what it froze.",
        )
    if not observed.manifest:
        raise EvidenceIncomplete(
            holder="the run's own artifacts (ObservedArtifacts.manifest)",
            missing="the run reported no observed manifest values",
            consequence="Absence is not agreement: the arbiter reads an unobserved field as a "
                        "failure, and an assembler that copied the pinned manifest into the "
                        "observed side would be asserting the §9.6 match it exists to carry as "
                        "two independent accounts.",
        )
    if not observed.module_versions:
        raise EvidenceIncomplete(
            holder="the run's own artifacts (ObservedArtifacts.module_versions)",
            missing="the run reported no module versions",
            consequence="An unreported version is not a matching one, and the arbiter's "
                        "per-module §9.6 check needs the run's own account to compare against "
                        "the pins.",
        )
    if observed.validation_status is None:
        raise EvidenceIncomplete(
            holder="the validation report (ObservedArtifacts.validation_status, ticket 36 — the "
                   "VALIDATOR lane's artifact)",
            missing="no validation status was supplied",
            consequence="§9.5 blocks the main test without independent review, and a status "
                        "invented builder-side would delete the independence the block exists "
                        "to require.",
        )
    if observed.locked_threshold is None:
        raise EvidenceIncomplete(
            holder="the calibration artifact (ObservedArtifacts.locked_threshold, "
                   "threshold.calibrate's own value)",
            missing="no locked threshold was supplied",
            consequence="Governance sequences the lock and deliberately carries no value, so the "
                        "calibration artifact is the only holder there is — and without it the "
                        "arbiter cannot ask whether the windows were evaluated against the "
                        "threshold that was locked.",
        )

    audit.verify()
    entries = audit.entries()
    start = _era_start(entries)

    states, transitions = _governance_states(governance, entries, start)
    pinned = _pinned_module_versions(transitions)
    code_version, discarded = _code_versions(runs, entries, start)
    run_status = _run_status(governance, entries, start, code_version, discarded)
    result_code_version = _result_code_version(runs, entries, start)

    return RunEvidence(
        manifest=freeze_manifest,
        observed=observed.manifest,
        pinned_module_versions=pinned,
        observed_module_versions=observed.module_versions,
        validation_status=observed.validation_status,
        governance_states=states,
        locked_threshold=observed.locked_threshold,
        run_status=run_status,
        result_code_version=result_code_version,
    )
