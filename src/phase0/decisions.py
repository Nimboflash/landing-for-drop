"""Every act this machine cannot perform, with everything needed to perform it.

This module exists because of a request to automate the approvals, and because that request was
reasonable in its motive and impossible in its literal form. Both halves are worth writing down.

Why there is no auto-approver
-----------------------------

The pre-registration's entire worth is a claim about time and attribution: a *person* fixed these
numbers before any result existed, and can be asked about it afterwards. A script that writes a name
into a :class:`~phase0.parameters.FreezeRecord` produces an audit entry naming nobody — the chain
still verifies, the status still reads ``FROZEN``, and the one question the record exists to answer
("who decided this, and when did they decide it?") now has no answer. That is strictly worse than an
unfrozen set, because it *looks* answered.

This is not hypothetical here. The first freeze performed against this repository went through with
the placeholder from its own instructions pasted unchanged, and the register accepted it, because the
tripwire was a list of English spellings. Fixing it took replacing a vocabulary with a shape. An
automatic approver is that same hole, reintroduced deliberately and with better spelling.

Three of the open acts also commit resources this machine does not own: a monthly data budget, a
specialist review fee, and ten to twelve weeks of a person's time. Those are not refusals about
governance; they are somebody else's money and somebody else's calendar.

What this module does instead
-----------------------------

The honest bottleneck is not that a human must act. It is that acting requires reconstructing a
week of context first. So each :class:`Decision` below carries the question, what it blocks, what a
decider actually needs to know, the exact command, and — where one exists — what this machine
already prepared. The act stays human; the homework does not.

``phase0 decisions`` prints them. Nothing here writes anything.
"""

from .governance import PARAMETERS_FROZEN, position
from .preconditions import PRECONDITION_KEYS

__all__ = ["Decision", "open_decisions", "report"]


class Decision(object):
    """One act only a person may perform.

    :param key: short identifier.
    :param question: what is actually being decided, in one line.
    :param blocks: what does not move until it is made.
    :param needs: what the decider has to know or supply that this machine cannot supply.
    :param command: the exact invocation, or ``None`` when the act is not a command at all.
    :param prepared: what is already done, so the decider is not re-doing it.
    :param why_not_automatable: the specific reason, per act, rather than one blanket sentence.
    """

    __slots__ = ("key", "question", "blocks", "needs", "command", "prepared",
                 "why_not_automatable")

    def __init__(self, key, question, blocks, needs, command, prepared, why_not_automatable):
        self.key = key
        self.question = question
        self.blocks = blocks
        self.needs = needs
        self.command = command
        self.prepared = prepared
        self.why_not_automatable = why_not_automatable

    def lines(self):
        out = ["{}  {}".format(self.key, self.question),
               "    blocks     {}".format(self.blocks),
               "    needs      {}".format(self.needs)]
        if self.prepared:
            out.append("    prepared   {}".format(self.prepared))
        out.append("    not mine   {}".format(self.why_not_automatable))
        if self.command:
            out.append("    command    {}".format(self.command))
        return out

    def __repr__(self):
        return "<Decision {}>".format(self.key)


_BUILDER = Decision(
    key="01",
    question="Who is the Primary Builder?",
    blocks="ticket 05's start gate, and through it every stage in the machine",
    needs="a named person who will own the build",
    command='phase0 record-precondition primary_builder "<name>" --requester "<you>"',
    prepared="",
    why_not_automatable=(
        "accountability is the content of the record. A name nobody can be asked about records "
        "nothing"
    ),
)

_VALIDATOR = Decision(
    key="02",
    question="Who is the Independent Validator, and which human is accountable for them?",
    blocks="tickets 14-17 (the golden set), 36, and the validation gate",
    needs=(
        "a name, plus a named accountable human. Direction is settled — an AI validator, capped at "
        "MACHINE-INDEPENDENT — so the shape is decided and only the naming is open"
    ),
    command=(
        'phase0 record-validator --name "<name>" --kind <human|ai_agent> '
        '--start-date <YYYY-MM-DD> --project-start <YYYY-MM-DD> --commitment <level> '
        '--requester "<you>"   (an ai_agent kind also requires its accountable human)'
    ),
    prepared=(
        "the register, the four binding independence constraints, the three reachable statuses, "
        "and the correlated-error note that an AI assignment carries"
    ),
    why_not_automatable=(
        "an AI validator naming itself is the correlated-error problem closing its own loop. §9.5 "
        "requires an accountable human precisely so the assignment is answerable to somebody who "
        "is not the thing being assigned"
    ),
)

_BUDGET = Decision(
    key="03",
    question="Is the data budget approved? (~$478/month)",
    blocks="tickets 12 and 13, and through them the golden set and everything downstream",
    needs="approval to spend money, monthly, on vendor and archival access",
    command='phase0 record-precondition data_budget "<approver and terms>" --requester "<you>"',
    prepared=(
        "the provisioning probes, and the finding that free public endpoints already serve "
        "receipts, logs and archive state — what they refuse is trace_transaction"
    ),
    why_not_automatable="it is a commitment of money this machine does not own",
)

_CAPACITY = Decision(
    key="04",
    question="Are 10-12 weeks of capacity reserved?",
    blocks="ticket 05's start gate",
    needs="a commitment of a person's calendar",
    command='phase0 record-precondition capacity_reserved "<who and when>" --requester "<you>"',
    prepared="",
    why_not_automatable="it is a commitment of somebody's time this machine does not own",
)

_EXTERNAL_REVIEW = Decision(
    key="§9.5",
    question="Book the external specialist review of 10-15 complex accounts.",
    blocks=(
        "the validation status ceiling. With an AI validator this review is the ONLY thing that "
        "narrows the shared prior, so it moved from a formality to the load-bearing item"
    ),
    needs="a quote from a specialist, then the booking",
    command=(
        'phase0 book-external-review --requester "<you>" --specialist "<who>" --accounts 12 '
        '--booked-on <YYYY-MM-DD> --cost-usd "<amount>"'
    ),
    prepared=(
        "the budget line, which has no declined/waived/optional state — quoted_usd is None, "
        "meaning nobody has obtained a quote, which is a different claim from $0"
    ),
    why_not_automatable=(
        "it is money, and the whole point is a reviewer outside this system. A machine booking its "
        "own external review has not obtained an external review"
    ),
)

_SIGN_OFF = Decision(
    key="§17",
    question="Sign the pre-registration's remaining sign-off lines.",
    blocks="nothing mechanically; it is the document's own record of who stands behind it",
    needs="the Product/Research Owner line, and the two that follow tickets 01 and 02",
    command="edit docs/phase-0-preregistration.md §17",
    prepared=(
        "the freeze date and commit are already written in, from the hash-chained audit log: "
        "2026-08-16 at 4bbae13"
    ),
    why_not_automatable="a signature written by the thing being signed for is not a signature",
)


def open_decisions(preconditions, governance, parameters=None):
    """Every act still outstanding, in the order they unblock things.

    Reads state; writes nothing. A decision already made drops off the list, so an empty result is
    a real statement rather than a default.
    """
    recorded = set(preconditions.satisfied())

    pending = []
    for key, decision in zip(PRECONDITION_KEYS, (_BUILDER, _VALIDATOR, _BUDGET, _CAPACITY)):
        if key not in recorded:
            pending.append(decision)

    pending.append(_EXTERNAL_REVIEW)

    if position(governance.state) >= position(PARAMETERS_FROZEN):
        pending.append(_SIGN_OFF)

    return tuple(pending)


def report(preconditions, governance, parameters=None):
    """Lines for ``phase0 decisions``."""
    pending = open_decisions(preconditions, governance, parameters)
    if not pending:
        return ["No human act is outstanding."]

    lines = [
        "{} act(s) only a person may perform.".format(len(pending)),
        "",
        "This machine prepares them and does not perform them. The pre-registration's worth is that",
        "a person fixed these numbers before any result existed and can be asked about it; a script",
        "writing a name produces a record naming nobody, which is worse than no record because it",
        "looks like one.",
        "",
    ]
    for decision in pending:
        lines.extend(decision.lines())
        lines.append("")
    return lines
