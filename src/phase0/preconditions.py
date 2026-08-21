"""The four preconditions, and the Phase 0 status derived from them.

Pre-registration §15.4: Phase 0 begins only when all four are true. Until then the status is
``DESIGNED, NOT READY FOR EXECUTION`` and no stage may run.

This module holds the register. It does not decide anything — a human records that a Builder was
assigned; the code only reports what is recorded and refuses while anything is missing.

Two of the four are people, and the second one carries more than a name
-----------------------------------------------------------------------

``independent_validator`` is the one precondition whose *quality* decides what the experiment may
do. A Builder is assigned or not; a Validator is assigned, and the assignment reaches one of three
independence statuses, and one of the three blocks the main test. So ticket 02's record joins this
register rather than sitting beside it: :meth:`PreconditionRegister.record_validator` writes the
§15.4 attribution and the full :class:`~phase0.validator.ValidatorAssignment` in the same file and
the same audit chain, and :meth:`PreconditionRegister.report` prints both facts side by side.

The generic :meth:`PreconditionRegister.record` still accepts ``independent_validator`` with a bare
attribution, and that is a deliberate and stated gap rather than an oversight — see the method.
"""

import json
import os

from .errors import NotReadyError
from .validator import (
    ASSIGNED,
    UNASSIGNED,
    ValidatorAssignment,
    label,
    main_test_refusal,
    validation_status,
)

STATUS_NOT_READY = "DESIGNED, NOT READY FOR EXECUTION"
STATUS_READY = "READY FOR EXECUTION"

#: The ticket-02 record, stored beside the four attributions in the same JSON file. Not a member of
#: :data:`PRECONDITION_KEYS`: the start gate reads the four, and this is what the *second* of them
#: means. Keeping them in one file keeps them in one audit chain — two files recording the same
#: assignment are two accounts that can disagree.
VALIDATOR_RECORD_KEY = "independent_validator_record"

#: Ticket number -> (key, human description). Order is the order they are reported in.
PRECONDITIONS = (
    ("primary_builder", "01", "Primary Builder assigned"),
    ("independent_validator", "02", "Independent Validator assigned"),
    ("data_budget", "03", "Data budget approved and vendor access provisioned"),
    ("capacity_reserved", "04", "10-12 week capacity reserved"),
)

PRECONDITION_KEYS = tuple(k for k, _, _ in PRECONDITIONS)


class PreconditionRegister(object):
    """A JSON file recording who or what satisfies each precondition.

    A precondition is satisfied only by a non-empty attribution — a name, a contract reference,
    an approval id. A bare ``true`` is not accepted, because "who" is the part that matters when
    someone asks six months later whether validation was really independent.
    """

    def __init__(self, path, audit_log=None):
        self.path = str(path)
        self._audit = audit_log

    # -- state -----------------------------------------------------------------

    def _load(self):
        if not os.path.exists(self.path):
            return {}
        with open(self.path, "r", encoding="utf-8") as fh:
            content = fh.read().strip()
        return json.loads(content) if content else {}

    def _save(self, data):
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")

    def record(self, key, attribution, requester):
        """Record that a precondition is satisfied, and by whom.

        **On ``independent_validator``.** A bare attribution here satisfies §15.4's start gate and
        nothing else. It does not produce a ticket-02 record, so
        :meth:`independent_validator_state` reads ``UNASSIGNED``, :meth:`validation_status` reads
        ``NOT INDEPENDENT``, and :meth:`report` says so on the line underneath. That is the honest
        shape of the gap: a name in a register is genuinely the fact §15.4 asks for — "two people
        were not found" is the failure it exists to catch — and it is genuinely not the fact the
        validation gate needs. Refusing it outright would make this method the place that decides
        whether Phase 0 may begin at all, which is not its job.

        What it will not do is *overwrite* a ticket-02 record with a bare string. That would erase
        four bound constraints, a week-1 start date and a booking, and leave a register that looks
        assigned; it raises instead. Use :meth:`record_validator` to replace one.
        """
        if key not in PRECONDITION_KEYS:
            raise ValueError(
                "unknown precondition {!r}; expected one of {}".format(
                    key, ", ".join(PRECONDITION_KEYS)
                )
            )
        if not attribution or not str(attribution).strip():
            raise ValueError(
                "precondition {!r} needs an attribution (who or what satisfies it), "
                "not a bare flag".format(key)
            )
        data = self._load()
        if key == "independent_validator" and data.get(VALIDATOR_RECORD_KEY):
            raise ValueError(
                "a ticket-02 Independent Validator record already exists ({!r}); refusing to "
                "replace it with the bare attribution {!r}. Doing so would drop the four bound "
                "independence constraints, the week-1 start date and any booked external review, "
                "and leave a register that still reads as assigned — the cost is a validation "
                "status that looks earned and is not. Call record_validator() with a complete "
                "assignment instead.".format(data[VALIDATOR_RECORD_KEY].get("name"), attribution)
            )
        data[key] = str(attribution).strip()
        self._save(data)
        if self._audit is not None:
            self._audit.append(
                requester, "precondition.record", {"key": key, "attribution": data[key]}
            )
        return data[key]

    # -- the Independent Validator (ticket 02) ---------------------------------

    def record_validator(self, assignment, requester):
        """Record the Independent Validator. The only way out of ``UNASSIGNED``.

        :param assignment: a :class:`~phase0.validator.ValidatorAssignment`. Built by the caller,
            because naming a validator is the project owner's decision — this method has no
            defaults, no partial form and no way to construct one from a name alone.
        :param requester: who recorded it. Written to the audit chain with the record.
        :returns: the assignment.

        Writes two things to one file: the §15.4 attribution under ``independent_validator``, so
        the start gate sees a satisfied precondition, and the full record under
        :data:`VALIDATOR_RECORD_KEY`. The assignment carries the four independence constraints by
        construction, so there is no path through this method that records a validator without
        them.
        """
        if not isinstance(assignment, ValidatorAssignment):
            raise TypeError(
                "record_validator takes a ValidatorAssignment, got {}. The register does not build "
                "one from a name: the independence constraints, the week-1 start date and the "
                "commitment scope are what make the record a ticket-02 record, and a method that "
                "accepted a bare name would have to invent them.".format(type(assignment).__name__)
            )
        data = self._load()
        data["independent_validator"] = assignment.attribution()
        data[VALIDATOR_RECORD_KEY] = assignment.as_dict()
        self._save(data)
        if self._audit is not None:
            self._audit.append(requester, "precondition.record", {
                "key": "independent_validator", "attribution": data["independent_validator"],
            })
            self._audit.append(requester, "validator.record", {
                "name": assignment.name,
                "kind": assignment.kind,
                "start_date": assignment.start_date.isoformat(),
                "covers": list(assignment.covers),
                "constraints": list(c.id for c in assignment.constraints),
                "validation_status": assignment.validation_status().value,
            })
        return assignment

    def validator(self):
        """The recorded :class:`~phase0.validator.ValidatorAssignment`, or ``None``.

        ``None`` is a carried status, not a failure: nobody has been assigned. Every caller that
        turns it into a refusal does so explicitly.
        """
        record = self._load().get(VALIDATOR_RECORD_KEY)
        return None if not record else ValidatorAssignment.from_dict(record)

    def independent_validator_state(self):
        """``ASSIGNED`` or ``UNASSIGNED`` — the machine-readable field ticket 02 asks for.

        ``ASSIGNED`` means a ticket-02 record exists. A bare attribution recorded through
        :meth:`record` reads ``UNASSIGNED``, because the thing that would be assigned — a validator
        bound to the independence constraints — is not there.
        """
        return ASSIGNED if self._load().get(VALIDATOR_RECORD_KEY) else UNASSIGNED

    def validation_status(self):
        """The :class:`contracts.core.ValidationStatus` an assignment can reach **today**."""
        return validation_status(self.validator())

    def book_external_review(self, review, requester):
        """Book the ticket-37 review, moving the status to ``EXTERNALLY REVIEWED``.

        Refused without an assignment to attach it to, and refused when the specialist is the
        Primary Builder recorded under ticket 01 — the builder reviewing the validator's accounts
        converts nothing. :class:`~phase0.validator.ValidatorAssignment` separately refuses the
        validator and its accountable human, so the three names this register knows are all
        excluded at construction rather than by a caller remembering to check.

        The builder match is a substring of the recorded attribution rather than an equality,
        because the attribution is free text ("A. Builder, full-time from 2026-01-05") and an
        equality would miss every real one. It therefore errs toward refusing — a short specialist
        name that happens to occur inside the builder's line is rejected. That is the right
        direction for this check and it is why the refusal quotes both strings, so a false positive
        is legible and can be answered by recording a fuller name.
        """
        assignment = self.validator()
        if assignment is None:
            raise ValueError(
                "no Independent Validator is recorded, so there is nothing for an external review "
                "to review. The order is ticket 02 then ticket 37: booking a review first would "
                "record a cost against an assignment nobody made, and would leave a register in "
                "which UNASSIGNED carried a booking."
            )
        builder = (self._load().get("primary_builder") or "").strip().lower()
        if builder and review.specialist.lower() in builder:
            raise ValueError(
                "the external specialist {!r} is the recorded Primary Builder ({!r}). Ticket 37 "
                "requires a specialist who is neither the builder nor the validator; a review by "
                "the author of the code under review converts MACHINE-INDEPENDENT to nothing, and "
                "recording it as EXTERNALLY REVIEWED would buy the label without the "
                "check.".format(review.specialist, self._load().get("primary_builder"))
            )
        return self.record_validator(assignment.with_external_review(review), requester)

    def independence_refusal(self, what):
        """Why ``what`` may not run under the recorded validation status, or ``None``.

        The check ``execute_stage`` calls for every stage from ``VALIDATION_PASSED`` onward, so
        that "``NOT INDEPENDENT`` blocks the main test" is the stage list refusing rather than a
        sentence in a report.

        **Exactly what it covers.** It fires on every assignment recorded through
        :meth:`record_validator` whose status does not permit the main test — today that is a human
        validator with no external review booked. It returns ``None`` when no ticket-02 record
        exists at all, which is the gap :meth:`record` names: a repository that has not yet done
        ticket 02 has an empty register, and a check that refused there would refuse every stage in
        every rehearsal of this machine and would be switched off within a week. The register
        reports that state as ``UNASSIGNED`` / ``NOT INDEPENDENT`` in :meth:`report` and in
        ``phase0 status`` instead, where it is visible rather than load-bearing.
        """
        assignment = self.validator()
        if assignment is None:
            return None
        return main_test_refusal(assignment.validation_status(), what)

    def validator_report(self):
        """Lines for the status command: the ticket-02 fields, and the status reachable today."""
        state = self.independent_validator_state()
        assignment = self.validator()
        status = validation_status(assignment)
        lines = [
            "{:<28} {}".format("independent_validator", state),
            "{:<28} {}{}".format("validation status today", label(status),
                                 "" if status.permits_main_test else " — the main test is BLOCKED"),
        ]
        if assignment is None:
            attribution = self._load().get("independent_validator")
            if attribution:
                lines.append(
                    "{:<28} the §15.4 precondition carries an attribution ({!r}) that was not "
                    "recorded through the ticket-02 register, so no independence constraint is "
                    "bound to it".format("note", attribution))
            lines.append(
                "{:<28} UNASSIGNED is not a state this code can leave on its own. There is no "
                "default validator and no placeholder: a person records a named one, or this is "
                "what the register says.".format("note"))
            return lines

        lines.append("{:<28} {} ({})".format(
            "name", assignment.name, "AI agent" if assignment.is_ai_agent else "human"))
        if assignment.accountable_human:
            lines.append("{:<28} {}".format("accountable human", assignment.accountable_human))
        lines.append("{:<28} {} (week 1 of a project starting {})".format(
            "start date", assignment.start_date.isoformat(),
            assignment.project_start.isoformat()))
        lines.append("{:<28} {}, covering {}".format(
            "commitment", assignment.commitment.lower().replace("_", "-"),
            ", ".join(assignment.covers)))
        for constraint in assignment.constraints:
            lines.append("{:<28} {}".format("constraint", constraint.requirement))
        review = assignment.external_review
        lines.append("{:<28} {}".format(
            "external specialist review",
            "booked: {} reviewing {} complex accounts from {}".format(
                review.specialist, review.accounts, review.booked_on.isoformat())
            if review is not None else
            "NOT BOOKED — {}".format(assignment.external_review_budget.standing)))
        if assignment.correlated_error_note:
            lines.append("{:<28} {}".format("limitation", assignment.correlated_error_note))
        return lines

    # -- queries ---------------------------------------------------------------

    def satisfied(self):
        data = self._load()
        return {k: data.get(k) for k in PRECONDITION_KEYS if data.get(k)}

    def unmet(self):
        """Human-readable descriptions of what is still missing, in ticket order."""
        data = self._load()
        return [
            "{} (ticket {})".format(desc, ticket)
            for key, ticket, desc in PRECONDITIONS
            if not data.get(key)
        ]

    def is_ready(self):
        return not self.unmet()

    def status(self):
        return STATUS_READY if self.is_ready() else STATUS_NOT_READY

    def require_ready(self):
        """Raise :class:`NotReadyError` naming the unmet preconditions, or return ``True``."""
        unmet = self.unmet()
        if unmet:
            raise NotReadyError(unmet)
        return True

    def report(self):
        """Lines for the status command."""
        data = self._load()
        lines = []
        for key, ticket, desc in PRECONDITIONS:
            value = data.get(key)
            mark = "[x]" if value else "[ ]"
            detail = value if value else "not recorded"
            lines.append("{} {}  {:<48} {}".format(mark, ticket, desc, detail))
        return lines
