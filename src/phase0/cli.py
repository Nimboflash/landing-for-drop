"""``phase0`` command line — the thing that actually executes in tickets 05 and 06.

    phase0 status                          report the preconditions and the derived status
    phase0 record-precondition <key> <who> record a precondition and who satisfies it
    phase0 record-validator ...            record the ticket-02 Independent Validator
    phase0 book-external-review ...        book the ticket-37 review of 10-15 complex accounts
    phase0 request <stage>                 open a run record for a stage; refused unless ready
    phase0 run <stage>                     execute a stage end to end under governance
    phase0 freeze <state>                  enter a state that records a human act
    phase0 parameters                      print the ticket-11 parameter set and freeze status
    phase0 decisions                       every act only a person may perform
    phase0 request-parameter-change ...    ask to move a threshold; always refused, on the record
    phase0 halt / phase0 resume            the operations capability
    phase0 audit                           print the audit log and verify its hash chain

The demo for ticket 05 is a refusal: request a stage while a precondition is missing and the
command names the missing one and exits non-zero.

``run`` is the demo for the two halves meeting. It injects a **trivial runner** — the command
computes nothing, because ``phase0`` is SHARED and must not know what a stage does — and shows all
four outcomes from the command line::

    phase0 run step0.universe --requester b --commit abc1234 --dataset-snapshot snap-1
    phase0 run step0.universe ... --crash "the decoder does not know this router"
    phase0 run step0.universe ... --halt-mid-stage

Exit codes are the outcome, so a shell script cannot mistake a refusal for a result::

    0  COMPLETED     2  REFUSED     3  HELD     4  CRASHED

``freeze`` deliberately accepts only ``PARAMETERS_FROZEN`` and ``CODE_AND_DATA_FROZEN``. There is
no general "advance" command: one would let the whole chain be walked from a shell without anything
ever running, which is precisely what the state machine exists to prevent. Every other state is
earned by a stage completing under ``run``.

``freeze CODE_AND_DATA_FROZEN`` requires ``--dataset-snapshot`` and refuses one that declares
itself not a measurement; ``freeze PARAMETERS_FROZEN`` takes the flag but does not require it,
because a parameter freeze precedes any data. See :func:`cmd_freeze` for what that leaves open.
"""

import argparse
import os
import sys

from .errors import Phase0Error, TransitionError
from .execution import (
    COMPLETED,
    CRASHED,
    HELD,
    MANUAL_TRANSITIONS,
    MANUAL_TRANSITIONS_WITH_A_DATASET,
    REFUSED,
    execute_stage,
    wire,
)
from .governance import PARAMETERS_FROZEN
from .parameters import NOT_PREREGISTERED, FreezeRecord
from .decisions import report as decisions_report
from .preconditions import PRECONDITION_KEYS
from .runs import STAGES
from .validator import (
    COMMITMENT_LEVELS,
    REQUIRED_SCOPE,
    VALIDATOR_KINDS,
    ExternalSpecialistReview,
    ValidatorAssignment,
    label,
)

DEFAULT_ROOT = os.environ.get("PHASE0_STATE_DIR", ".phase0")

#: The outcome is the exit code. A refusal that exited 0 would be a green build over a stage that
#: never ran.
EXIT_CODES = {COMPLETED: 0, REFUSED: 2, HELD: 3, CRASHED: 4}


def _wire(root):
    return wire(root)


def cmd_status(args):
    w = _wire(args.root)
    pre, gov = w.preconditions, w.governance

    print("Phase 0 — Hypothesis Falsification Test")
    print("=" * 64)
    print("\nPreconditions (pre-registration §15.4)\n")
    for line in pre.report():
        print("  " + line)

    print("\nStatus:            {}".format(pre.status()))
    print("Governance state:  {}".format(gov.state))
    if gov.halted:
        print("Operations:        HALTED")
    if gov.invalidated:
        print("Run status:        INVALIDATED")
    if gov.gate_outcome:
        print("Gate outcome:      {}".format(gov.gate_outcome))

    print("\nIndependent Validator (ticket 02)\n")
    for line in pre.validator_report():
        print("  " + line)

    print("\nAuthoritative parameter set (ticket 11)\n")
    for line in w.parameters.report():
        print("  " + line)

    if not pre.is_ready():
        print("\nNo pipeline stage may run. Unmet:")
        for item in pre.unmet():
            print("  - {}".format(item))
    return 0


def cmd_record_precondition(args):
    w = _wire(args.root)
    value = w.preconditions.record(args.key, args.attribution, args.requester)
    print("Recorded {}: {}".format(args.key, value))
    print("Status is now: {}".format(w.preconditions.status()))
    return 0


def cmd_record_validator(args):
    """Record the ticket-02 Independent Validator. Every field is required for a reason.

    There is no ``--name`` default, no ``--kind`` default and no way to omit the start date or the
    project start: week 1 is a checkable fact only if both dates are given, and a command that
    supplied any of them would be the code leaving ``UNASSIGNED`` on its own.

    ``--covers`` defaults to all three scope items because the record is refused without all three
    anyway; the flag exists so that a caller who tries to record a sign-off-only commitment gets
    the named refusal rather than being unable to express it.
    """
    w = _wire(args.root)
    assignment = ValidatorAssignment(
        name=args.name, kind=args.kind, start_date=args.start_date,
        project_start=args.project_start, commitment=args.commitment,
        covers=args.covers, accountable_human=args.accountable_human, note=args.note,
    )
    w.preconditions.record_validator(assignment, args.requester)
    print("Recorded Independent Validator: {}".format(assignment.attribution()))
    print("independent_validator:   {}".format(w.preconditions.independent_validator_state()))
    print("Validation status today: {}".format(label(w.preconditions.validation_status())))
    if assignment.correlated_error_note:
        print("\n{}".format(assignment.correlated_error_note))
    return 0


def cmd_book_external_review(args):
    """Book the ticket-37 review. The one act that reaches ``EXTERNALLY REVIEWED``."""
    w = _wire(args.root)
    review = ExternalSpecialistReview(
        specialist=args.specialist, accounts=args.accounts, booked_on=args.booked_on,
        cost_usd=args.cost_usd, note=args.note,
    )
    w.preconditions.book_external_review(review, args.requester)
    print("Booked: {} reviewing {} complex accounts from {}.".format(
        review.specialist, review.accounts, review.booked_on.isoformat()))
    print("Validation status today: {}".format(label(w.preconditions.validation_status())))
    return 0


def cmd_request(args):
    w = _wire(args.root)

    w.preconditions.require_ready()  # raises NotReadyError naming the unmet preconditions

    record = w.runs.open_run(
        stage=args.stage,
        commit=args.commit,
        config={"stage": args.stage},
        dataset_snapshot=args.dataset_snapshot,
        requester=args.requester,
    )
    print("Accepted. Run record written before execution:")
    print("  run_id           {}".format(record.run_id))
    print("  stage            {}".format(record.stage))
    print("  commit           {}".format(record.commit))
    print("  config_hash      {}".format(record.config_hash))
    print("  dataset_snapshot {}".format(record.dataset_snapshot))
    print("  master_seed      {}...".format(record.master_seed[:16]))
    print("  seed_rule        {}".format(record.seed_rule))
    return 0


def _trivial_runner(args, governance):
    """The injected stage body for the ``run`` demo.

    It computes nothing on purpose. ``execute_stage`` takes the runner as an argument precisely so
    that governance never learns what a stage does, and a command line that quietly knew would
    give that back.
    """

    def runner(context):
        if args.halt_mid_stage:
            governance.halt(args.requester, "operations halt injected mid-stage")
        if args.crash:
            raise RuntimeError(args.crash)
        return {
            "stage": context.stage,
            "run_id": context.run_id,
            "child_seed_0": context.child_seed("{}.demo".format(context.stage), 0),
            "note": args.note,
        }

    return runner


def cmd_run(args):
    w = _wire(args.root)

    result = execute_stage(
        args.stage, _trivial_runner(args, w.governance), args.requester,
        governance=w.governance, preconditions=w.preconditions, runs=w.runs, audit=w.audit,
        commit=args.commit, dataset_snapshot=args.dataset_snapshot,
        config={"stage": args.stage, "note": args.note},
    )

    print("{}  {}".format(result.status, result.stage))
    print("  requester        {}".format(result.requester))
    print("  run record       {}".format(result.run_id or "none written — nothing was about to run"))
    print("  state before     {}".format(result.state_before))
    print("  state after      {}".format(result.state_after))
    if result.advanced_to:
        print("  advanced to      {}".format(result.advanced_to))
    if result.pending:
        print("  awaiting         {}".format(", ".join(result.pending)))
    if result.reason:
        print("  reason           {}".format(result.reason))
    if result.completed:
        print("  value            {}".format(result.value))
    return EXIT_CODES[result.status]


def cmd_freeze(args):
    """Enter one of the two states that record a human act.

    ``--dataset-snapshot`` is **required for CODE_AND_DATA_FROZEN** and optional for
    ``PARAMETERS_FROZEN``, and the asymmetry is the act rather than a convenience.
    :data:`~phase0.execution.MANUAL_TRANSITIONS_WITH_A_DATASET` is the list. Ticket 39 freezes code
    *and data*, so which data was frozen is half of what is being recorded and the machine can
    check it; ticket 11 freezes a pre-registration before any data has been read, so there is
    nothing to name.

    **What that leaves uncovered, stated rather than implied.** A ``PARAMETERS_FROZEN`` performed
    with no snapshot is not checked against anything — the run may later turn out to have been over
    generated data and this command will have said nothing, because at the moment it ran there was
    no data to speak of. Passing ``--dataset-snapshot`` there is refused if it declares itself not
    a measurement; omitting it is unexamined, not permitted.

    **``--commit`` and ``--frozen-on`` are the ticket-11 record**, and they go together or not at
    all. Given both, ``PARAMETERS_FROZEN`` is written through
    :meth:`~phase0.parameters.ParameterRegister.freeze` and §17's "Frozen at commit" and
    "Pre-registration frozen on" lines end up in the audit log. Given neither, the older looser
    transition is written and the register afterwards reads ``FROZEN WITHOUT A TICKET-11 RECORD``:
    every write is still refused, and what is missing is the evidence of *which* text was frozen.
    Neither flag has a default and no code path here invents one — this command cannot freeze
    anything that a person did not type their own name into.
    """
    w = _wire(args.root)
    if args.state in MANUAL_TRANSITIONS_WITH_A_DATASET and not args.dataset_snapshot:
        raise TransitionError(
            w.governance.state, args.state,
            "freezing code and data records which data was frozen, so --dataset-snapshot is "
            "required for this state. Refusing to write the freeze without it: a freeze that does "
            "not name its dataset cannot be checked against anything and cannot be reproduced by "
            "the reader who has to trust it",
        )
    if bool(args.commit) != bool(args.frozen_on):
        raise TransitionError(
            w.governance.state, args.state,
            "--commit and --frozen-on are one record and are given together. A freeze carrying a "
            "commit and no date, or a date and no commit, is half of §17's sign-off block, and "
            "the half that is missing is the one a reader would have had to take on trust",
        )
    if args.commit and args.state != PARAMETERS_FROZEN:
        raise TransitionError(
            w.governance.state, args.state,
            "--commit and --frozen-on record the ticket-11 pre-registration freeze and apply only "
            "to {}. {} freezes code and data, and names its subject with --dataset-snapshot "
            "instead".format(PARAMETERS_FROZEN, args.state),
        )

    if args.commit:
        # FreezeRecord raises ValueError on a placeholder name, a moving commit reference or a
        # date it cannot read. Those are three ways a *person at a shell* mistypes the one command
        # in this tool that records a human act, not three ways a caller has a bug — so they are
        # converted here into the refusal main() prints, with the record's own sentence carried
        # through unchanged. The class keeps raising ValueError for programmatic misuse.
        try:
            record = FreezeRecord(
                requester=args.requester, commit=args.commit, frozen_on=args.frozen_on,
                note=args.note,
            )
        except ValueError as exc:
            raise TransitionError(w.governance.state, args.state, str(exc))
        state = w.parameters.freeze(record)
        record = w.parameters.freeze_record()
        print("Governance state is now: {}".format(state))
        print("Pre-registration frozen on:  {}".format(record.frozen_on.isoformat()))
        print("Frozen at commit:            {}".format(record.commit))
        print("Frozen by:                   {}".format(record.requester))
        print("Parameter set:               {} ({} parameters)".format(
            w.parameters.freeze_status(), len(w.parameters.parameters)))
        return 0

    state = w.governance.transition(args.state, args.requester, {
        "note": args.note, "dataset_snapshot": args.dataset_snapshot,
    }, dataset_snapshot=args.dataset_snapshot)
    print("Governance state is now: {}".format(state))
    if state == PARAMETERS_FROZEN:
        print("Parameter set:           {}".format(w.parameters.freeze_status()))
        print("  Every write is refused. What is not on record is the commit and the date, so a "
              "reader cannot check which text was frozen. Pass --commit and --frozen-on to write "
              "the ticket-11 record.")
    return 0


def cmd_decisions(args):
    """Every act only a person may perform, with what each one needs. Reads; never writes.

    Written after a request to automate the approvals. The motive was right — reconstructing a
    week of context before a thirty-second act is a real bottleneck — and the literal form would
    void the experiment: a record naming nobody answers the one question it exists to answer, and
    does it while looking answered. See :mod:`phase0.decisions`.
    """
    w = _wire(args.root)
    for line in decisions_report(w.preconditions, w.governance, w.parameters):
        print(line)
    return 0


def cmd_parameters(args):
    """Print the authoritative parameter set and its freeze status. Reads, never writes."""
    w = _wire(args.root)
    print("Authoritative parameter set (ticket 11)")
    print("=" * 64)
    for line in w.parameters.report():
        print("  " + line)
    print("\n{:<44} {:<26} {}".format("key", "value", "source"))
    print("  " + "-" * 62)
    for line in w.parameters.parameters.report():
        print(line)
    if NOT_PREREGISTERED:
        print("\nNeeded by the machine and named in neither document:\n")
        for key, why in sorted(NOT_PREREGISTERED.items()):
            print("  {}\n    {}".format(key, why))
    return 0


def cmd_request_parameter_change(args):
    """Ticket 11's demo, from the shell: ask to move a threshold and be refused, on the record.

    It always fails. There is no flag that makes it succeed, before the freeze or after, and the
    two refusals are different because they cost different things — see
    :meth:`~phase0.parameters.ParameterRegister.request_change`. Either way the audit entry naming
    the requester is written *before* the refusal is raised, so the record exists whether or not
    anyone reads the message.
    """
    w = _wire(args.root)
    w.parameters.request_change(args.key, args.value, args.requester, reason=args.reason)
    raise AssertionError(  # pragma: no cover - request_change has no path that returns
        "request_change returned instead of refusing; the parameter set has acquired a write path"
    )


def cmd_halt(args):
    w = _wire(args.root)
    w.governance.halt(args.requester, args.reason)
    print("HALTED at {}. State held; nothing advanced, reverted or changed.".format(
        w.governance.state))
    return 0


def cmd_resume(args):
    w = _wire(args.root)
    w.governance.resume(args.requester, args.reason)
    print("Resumed at {}.".format(w.governance.state))
    return 0


def cmd_audit(args):
    w = _wire(args.root)
    log = w.audit
    entries = log.entries()
    if not entries:
        print("Audit log is empty.")
        return 0
    for e in entries:
        print("{:>4}  {}  {:<32}  {}".format(e.seq, e.ts, e.action, e.requester))
    log.verify()
    print("\nHash chain verified over {} entries.".format(len(entries)))
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="phase0", description=__doc__.split("\n")[0])
    p.add_argument("--root", default=DEFAULT_ROOT, help="state directory (default: .phase0)")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("status", help="report preconditions and derived status")

    rp = sub.add_parser("record-precondition", help="record a precondition and its attribution")
    rp.add_argument("key", choices=PRECONDITION_KEYS)
    rp.add_argument("attribution", help="who or what satisfies it")
    rp.add_argument("--requester", required=True)

    rv = sub.add_parser("record-validator",
                        help="record the ticket-02 Independent Validator (all fields required)")
    rv.add_argument("--name", required=True, help="who — a placeholder is refused")
    rv.add_argument("--kind", required=True, choices=VALIDATOR_KINDS)
    rv.add_argument("--start-date", required=True, dest="start_date",
                    help="YYYY-MM-DD; must fall in week 1 of --project-start")
    rv.add_argument("--project-start", required=True, dest="project_start",
                    help="YYYY-MM-DD; day 0 of the 10-12 week window")
    rv.add_argument("--commitment", required=True, choices=COMMITMENT_LEVELS)
    rv.add_argument("--covers", nargs="+", default=list(REQUIRED_SCOPE), choices=REQUIRED_SCOPE,
                    help="all three are required; the flag exists so a short list is refused "
                         "by name rather than being inexpressible")
    rv.add_argument("--accountable-human", dest="accountable_human", default=None,
                    help="required when --kind is AI_AGENT")
    rv.add_argument("--note", default="")
    rv.add_argument("--requester", required=True)

    er = sub.add_parser("book-external-review",
                        help="book the ticket-37 review of 10-15 complex accounts")
    er.add_argument("--specialist", required=True)
    er.add_argument("--accounts", required=True, type=int)
    er.add_argument("--booked-on", required=True, dest="booked_on", help="YYYY-MM-DD")
    er.add_argument("--cost-usd", dest="cost_usd", default=None,
                    help="a decimal string; a float is refused by contracts.numeric.calc")
    er.add_argument("--note", default="")
    er.add_argument("--requester", required=True)

    rq = sub.add_parser("request", help="open a run record for a pipeline stage")
    rq.add_argument("stage", choices=STAGES)
    rq.add_argument("--requester", required=True)
    rq.add_argument("--commit", required=True)
    rq.add_argument("--dataset-snapshot", required=True, dest="dataset_snapshot")

    rn = sub.add_parser("run", help="execute a stage end to end with a trivial injected runner")
    rn.add_argument("stage", choices=STAGES)
    rn.add_argument("--requester", required=True)
    rn.add_argument("--commit", required=True)
    rn.add_argument("--dataset-snapshot", required=True, dest="dataset_snapshot")
    rn.add_argument("--note", default="trivial injected runner")
    rn.add_argument("--crash", metavar="MESSAGE",
                    help="make the injected runner raise, to demonstrate the crash path")
    rn.add_argument("--halt-mid-stage", action="store_true", dest="halt_mid_stage",
                    help="halt the run from inside the stage, to demonstrate the hold path")

    fz = sub.add_parser("freeze", help="enter a state that records a human act")
    fz.add_argument("state", choices=MANUAL_TRANSITIONS)
    fz.add_argument("--requester", required=True)
    fz.add_argument("--note", default="")
    fz.add_argument("--dataset-snapshot", dest="dataset_snapshot", default=None,
                    help="the data being frozen; required for {}, refused if it declares itself "
                         "not a measurement".format(", ".join(MANUAL_TRANSITIONS_WITH_A_DATASET)))
    fz.add_argument("--commit", default=None,
                    help="{} only: the commit the pre-registration is frozen at. A hash, never a "
                         "branch name or HEAD. Given together with --frozen-on".format(
                             PARAMETERS_FROZEN))
    fz.add_argument("--frozen-on", dest="frozen_on", default=None,
                    help="{} only: the date, YYYY-MM-DD. Given together with --commit".format(
                        PARAMETERS_FROZEN))

    sub.add_parser("parameters",
                   help="print the authoritative parameter set and its freeze status")

    sub.add_parser("decisions",
                   help="every act only a person may perform, and what each one needs")

    pc = sub.add_parser(
        "request-parameter-change",
        help="ask to change a parameter. Always refused, always recorded, exits non-zero")
    pc.add_argument("key", help="a key of the frozen set; see `phase0 parameters`")
    pc.add_argument("value", help="what the caller wants it to become; recorded verbatim")
    pc.add_argument("--requester", required=True, help="who asked. A placeholder is refused")
    pc.add_argument("--reason", default=None)

    ht = sub.add_parser("halt", help="operations: stop execution and hold state")
    ht.add_argument("--requester", required=True)
    ht.add_argument("--reason", required=True)

    rs = sub.add_parser("resume", help="operations: resume a halted run")
    rs.add_argument("--requester", required=True)
    rs.add_argument("--reason", required=True)

    sub.add_parser("audit", help="print the audit log and verify its hash chain")
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1

    handlers = {
        "status": cmd_status,
        "record-precondition": cmd_record_precondition,
        "record-validator": cmd_record_validator,
        "book-external-review": cmd_book_external_review,
        "request": cmd_request,
        "run": cmd_run,
        "freeze": cmd_freeze,
        "parameters": cmd_parameters,
        "decisions": cmd_decisions,
        "request-parameter-change": cmd_request_parameter_change,
        "halt": cmd_halt,
        "resume": cmd_resume,
        "audit": cmd_audit,
    }
    try:
        return handlers[args.command](args)
    except Phase0Error as exc:
        print("REFUSED: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
