"""Refusals.

Every refusal in this package is an exception carrying a legible reason. Nothing in the
skeleton returns a silent ``False`` — a stage that is not allowed to run must say which
rule stopped it and who asked.
"""


class Phase0Error(Exception):
    """Base for every refusal."""


class NotReadyError(Phase0Error):
    """A stage was requested while Phase 0 status is not ready.

    Carries the unmet preconditions so the refusal names them rather than saying "not ready".
    """

    def __init__(self, unmet):
        self.unmet = list(unmet)
        names = ", ".join(self.unmet)
        super().__init__(
            "Phase 0 status is DESIGNED, NOT READY FOR EXECUTION. "
            "Unmet precondition(s): {}".format(names)
        )


class TransitionError(Phase0Error):
    """A state transition arrived out of order."""

    def __init__(self, current, requested, reason):
        self.current = current
        self.requested = requested
        super().__init__(
            "Refused transition {} -> {}: {}".format(current, requested, reason)
        )


class NotAMeasurementError(Phase0Error):
    """A transition was asked for under a snapshot that declares itself not a measurement.

    Raised rather than carried as a status, because :meth:`phase0.governance.GovernanceMachine
    .transition` has no status vocabulary — its contract is "advance or raise", and a transition
    that silently did nothing would be worse than either. The stage path is different: there the
    runner has already run, so ``execute_stage`` carries a ``HELD`` :class:`~phase0.execution
    .StageResult` instead of raising, and this exception never reaches it.

    A :class:`Phase0Error`, so both command lines print it as a refusal rather than a traceback.
    Note the consequence: a caller that wraps ``transition`` in ``except Phase0Error`` converts
    this into whatever that caller does with a refusal. Nothing in ``src/`` does — the transition
    at step 6 of ``execute_stage`` is deliberately outside its ``try`` — and nothing should.
    """


class NotIndependentError(Phase0Error):
    """The recorded validation status does not permit the stage that was asked for.

    Ticket 02 and §9.5: ``NOT INDEPENDENT`` blocks the main test, and it blocks it *through the
    governed stage list* rather than through a note in a report. A :class:`Phase0Error`, so
    ``execute_stage`` records it as a ``REFUSED`` outcome and both command lines print it as a
    refusal.

    It is an error rather than a carried status because it answers "may this run?", and the two
    callers of that question — a stage request and an explicit
    :func:`phase0.validator.require_main_test_permitted` — both want an answer they cannot ignore.
    The register's own report of the same fact is a status, not this: an unmet precondition is
    something :meth:`phase0.preconditions.PreconditionRegister.report` prints, and only a *request
    to proceed anyway* raises.
    """


class FrozenError(Phase0Error):
    """A write was attempted against a frozen parameter set or a frozen run."""


class ParameterSetNotWritable(Phase0Error):
    """A change to the authoritative parameter set was requested *before* the freeze.

    Deliberately not a :class:`FrozenError`. The set is not frozen yet, and answering "frozen"
    would be a false statement about the state of the experiment — the reader of an audit log has
    to be able to tell "rejected because the pre-registration is closed" from "rejected because
    this register was never the editor". Both are refusals and they cost different things.

    What it means: :class:`~phase0.parameters.ParameterRegister` has no write path in either
    state. The values come from ``docs/phase-0-preregistration.md`` and
    ``docs/decision-engine-addendum.md``, and a value changes by editing those documents and
    ``phase0/parameters.py`` together, at a commit, **before** anybody freezes. After the freeze
    the same request raises :class:`FrozenError` instead, and the fix is an invalidation rather
    than an edit.
    """


class InvalidatedError(Phase0Error):
    """The run is INVALIDATED and cannot advance until a new code version is registered."""


class HaltedError(Phase0Error):
    """The run is halted by operations."""


class AuditChainError(Phase0Error):
    """The audit log's hash chain does not verify — entries were altered or removed."""


class StageNotCompleted(Phase0Error):
    """A stage that did not complete was asked for its value.

    Raised for refusal, hold and crash alike. The guard is on the condition — this stage did not
    complete — rather than on any one status, so a caller that reads a value without reading a
    status has no outcome for which it silently receives a plausible-looking ``None``.
    """

    def __init__(self, stage, status, reason):
        self.stage = stage
        self.status = status
        self.reason = reason
        super().__init__(
            "Stage {!r} did not complete (status {}): {}. A refused, held or crashed stage has "
            "no value to publish; read .status and .reason instead.".format(
                stage, status, reason or "no reason recorded"
            )
        )
