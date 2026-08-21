"""Ticket 02 — the Independent Validator's record, and the status an assignment can reach.

This module holds the *record*, not the decision. Naming a validator is the project owner's act;
nothing here invents a name, defaults one, or supplies one when the register is empty. The only way
out of ``UNASSIGNED`` is :meth:`phase0.preconditions.PreconditionRegister.record_validator` called
with a :class:`ValidatorAssignment` a person built and a requester who asked for it.

Why the constraints are data and not prose
------------------------------------------

The validation gate's entire worth is that the validator derived its expected outputs
independently. If the two lanes share a misunderstanding, the comparison cannot see it: both sides
compute the same wrong answer and **agree**, and agreement is what the gate reads as evidence. So
the four conditions that make the derivation independent — a separate implementation path, no reuse
of the builder's classification/FIFO/valuation functions, expected outputs from raw chain data and
the frozen specification only, reasoning recorded before any comparison — are
:data:`INDEPENDENCE_CONSTRAINTS`, a tuple every assignment carries. They are not a parameter.
:class:`ValidatorAssignment` has no argument by which a caller may supply a shorter list, a longer
one, or none, so there is no assignment in this package that is not bound to all four.

Three statuses, and which one an assignment can reach today
-----------------------------------------------------------

The vocabulary is :class:`contracts.core.ValidationStatus` — deliberately the same enum
``gate_validation`` reads and ticket 36 will emit, rather than a second spelling of one question.
:func:`label` renders the pre-registration's own hyphenation for a human.

    NOT INDEPENDENT       no ticket-02 record, or a record the vocabulary has no better word for.
                          Blocks the main test.
    MACHINE-INDEPENDENT   an AI-agent validator, constraints bound, external review not yet booked.
    EXTERNALLY REVIEWED   the ticket-37 review of 10-15 complex accounts is booked.

:func:`validation_status` derives it. Nothing in this module accepts a status as an argument and
stores it: a status that could be asserted is a status that would be asserted, and an AI validator
asserting ``EXTERNALLY REVIEWED`` is precisely the failure the three-tier label exists to prevent.
The only lever is :class:`ExternalSpecialistReview`, which is a booking — a named specialist, a
count inside 10-15, a date — and which :class:`ValidatorAssignment` refuses if the specialist is
the validator or the person accountable for it.

What ``MACHINE-INDEPENDENT`` is worth, stated where it is produced
-------------------------------------------------------------------

Two agents from the same base model share priors and make *correlated* errors — the same misreading
of an ambiguous rule, the same wrong assumption about a token standard. That is exactly the failure
class independent validation exists to catch, and the class two agents are worst at catching. So an
AI assignment carries :attr:`ValidatorAssignment.correlated_error_note` and the status stops at
``MACHINE-INDEPENDENT`` until :data:`EXTERNAL_REVIEW_BUDGET` is paid. That budget line has no
declined state and no waiver: it is a cost to pay, not an option to consider.

How much of "structurally impossible" this achieves, and how much it does not
-----------------------------------------------------------------------------

The ticket says that bringing a validator in at the end to sign a report "must be structurally
impossible rather than discouraged". Here is the exact ledger.

**Impossible in this package.**

* An assignment that is not bound to all four independence constraints. There is no parameter.
* An assignment whose start date is outside week 1 of the project. :data:`WEEK_ONE_DAYS` is checked
  in the constructor against the project start the caller must also supply, so "joined in week 1"
  is a fact the record carries rather than a claim someone made in a document.
* An assignment whose commitment does not cover all of :data:`REQUIRED_SCOPE` — golden-set build,
  reconciliation, sign-off. A sign-off-only commitment is refused by name.
* A status reached by assertion. No constructor, method or serialised field sets one.
* An AI validator reading as full independence: ``EXTERNALLY REVIEWED`` needs a booking object.
* Leaving ``UNASSIGNED`` without a person. Placeholder names (:data:`_NON_NAMES`) are refused, an
  AI agent without a named accountable human is refused, and this module defines no default,
  example or fallback assignment anywhere — ``tests/phase0/test_validator.py`` scans the module
  namespace to keep it that way.

**Not achieved here, and named rather than implied.**

* The reasoning-before-comparison constraint is *checkable*, not *enforced*. This module gives
  ticket 36 the check — :meth:`ValidatorAssignment.ordering_refusal`, which compares the two
  timestamps and returns the sentence — and cannot make anyone call it. Nothing in ``phase0``
  observes when a validator actually read the builder's output, and no amount of registry design
  can: the copy channel is outside the process.
* "No reuse of the builder's functions" is enforced by ``tests/test_lane_independence.py``, a
  static check over committed code, not by this record. The record names that check as the thing
  that enforces it (:attr:`IndependenceConstraint.checked_by`) so the two do not drift apart, and
  the record's own contribution is that the constraint is *stated and bound* rather than remembered.
* Whether the external specialist is a human, is genuinely external, or reviewed anything is not
  knowable from here. The booking records a name, a count and a date; it refuses the two names this
  package knows are wrong (the validator and its accountable human, and — at the register — the
  primary builder) and cannot refuse a third party who is in fact the builder's colleague.
* A bare attribution recorded through the generic
  :meth:`~phase0.preconditions.PreconditionRegister.record` still satisfies §15.4's start gate. It
  reads ``UNASSIGNED`` here and its status is ``NOT INDEPENDENT``, so it is visible; see that
  method for why it is not refused outright.
"""

import datetime

from contracts.core import ValidationStatus
from contracts.numeric import calc

from .errors import NotIndependentError

# -- is anyone assigned ---------------------------------------------------------

#: A ticket-02 record exists.
ASSIGNED = "ASSIGNED"

#: No ticket-02 record exists. **Not a state this code can leave on its own.** There is no default
#: validator, no placeholder that becomes a name later, and no function anywhere in ``phase0`` that
#: produces an assignment from nothing. A person records one, or this is what the register says.
UNASSIGNED = "UNASSIGNED"

ASSIGNMENT_STATES = (UNASSIGNED, ASSIGNED)

# -- what kind of validator -----------------------------------------------------

HUMAN = "HUMAN"
AI_AGENT = "AI_AGENT"
VALIDATOR_KINDS = (HUMAN, AI_AGENT)

# -- commitment -----------------------------------------------------------------

PART_TIME = "PART_TIME"
FULL_TIME = "FULL_TIME"

#: The commitment levels an Independent Validator may be recorded at. The PRD's profile is
#: "competent enough to hand-verify on-chain accounting, *not* the builder, and available part-time
#: externally", so ``PART_TIME`` is the expected value and ``FULL_TIME`` is permitted because more
#: is not less. Everything else — ad hoc, on call, on request, at sign-off — is absent, and absence
#: is the refusal: there is no string a caller can pass that means "available when we need them".
COMMITMENT_LEVELS = (PART_TIME, FULL_TIME)

GOLDEN_SET = "golden_set"
RECONCILIATION = "reconciliation"
SIGN_OFF = "sign_off"

#: What the commitment must cover, all three. Ticket 02: "a part-time commitment covering the
#: golden-set build, reconciliation, and sign-off."
#:
#: This tuple is the structural answer to "bringing a validator in at the end to sign a report is
#: not independent validation". A record covering only :data:`SIGN_OFF` is refused, and so is one
#: whose start date is past week 1 — the two halves of that failure, each checked.
REQUIRED_SCOPE = (GOLDEN_SET, RECONCILIATION, SIGN_OFF)

#: Which tickets each scope item is the validator's work on, so the commitment is legible as a
#: schedule rather than as three words.
SCOPE_TICKETS = {
    GOLDEN_SET: ("14", "15", "16", "17"),
    RECONCILIATION: ("35",),
    SIGN_OFF: ("38",),
}

#: Week 1 is the first seven days of the project, day 0 included. A validator recorded outside it
#: is refused: §9.5 and the PRD both require the validator to build or approve the golden set
#: *before* the pipeline is complete, and someone who arrives in week 4 cannot have.
WEEK_ONE_DAYS = 7

# -- the external specialist review (ticket 37) ---------------------------------

#: §9.5: "at least 10-15 complex accounts are reviewed by an independent external specialist".
MIN_COMPLEX_ACCOUNTS = 10
MAX_COMPLEX_ACCOUNTS = 15


class ExternalReviewBudget(object):
    """The standing cost of the ticket-37 review. A cost to pay, not an option to consider.

    Two absences are the design. There is no ``declined``, ``waived`` or ``optional`` field, so the
    only states this line has are *booked* and *not yet booked* — and "not yet booked" caps the
    validation status at ``MACHINE-INDEPENDENT`` rather than excusing it. And ``quoted_usd`` is
    ``None`` because no source document quotes a figure: ``None`` here means **nobody has obtained
    a quote**, which is a different claim from ``0``. A zero would say someone checked and it is
    free, which nobody has.
    """

    __slots__ = ("scope", "accounts_min", "accounts_max", "quoted_usd", "standing", "source")

    def __init__(self, scope, accounts_min, accounts_max, quoted_usd, standing, source):
        self.scope = scope
        self.accounts_min = int(accounts_min)
        self.accounts_max = int(accounts_max)
        # calc() refuses a float on sight; money is str or int here as everywhere.
        self.quoted_usd = None if quoted_usd is None else calc(quoted_usd)
        self.standing = standing
        self.source = source

    @property
    def is_quoted(self):
        """Has anyone obtained a price? ``False`` is not ``$0``; see the class docstring."""
        return self.quoted_usd is not None

    @property
    def is_optional(self):
        """Always ``False``, and it is a property rather than a field for that reason.

        A field could be set. The PRD's instruction — "a cost to pay, not an option to consider" —
        survives only if there is no argument, no setter and no serialised key by which a run could
        record that the review was considered and declined.
        """
        return False

    def as_dict(self):
        return {
            "scope": self.scope,
            "accounts_min": self.accounts_min,
            "accounts_max": self.accounts_max,
            "quoted_usd": None if self.quoted_usd is None else str(self.quoted_usd),
            "is_quoted": self.is_quoted,
            "is_optional": self.is_optional,
            "standing": self.standing,
            "source": self.source,
        }


#: Recorded in ticket 02 rather than in ticket 37, because ticket 02 is where somebody decides who
#: validates and that is the moment the cost has to be visible. Ticket 37 spends it.
EXTERNAL_REVIEW_BUDGET = ExternalReviewBudget(
    scope="{}-{} of the most complex golden accounts, drawn from those flagged during golden-set "
          "selection: fee-on-transfer, dead pool, pool migration, Safe, ERC-4337, and a "
          "solver-settled or aggregator-routed trade".format(
              MIN_COMPLEX_ACCOUNTS, MAX_COMPLEX_ACCOUNTS),
    accounts_min=MIN_COMPLEX_ACCOUNTS,
    accounts_max=MAX_COMPLEX_ACCOUNTS,
    quoted_usd=None,
    standing="A COST TO PAY, NOT AN OPTION TO CONSIDER",
    source="pre-registration §9.5; PRD 'Staffing is the most likely cause of death'; ticket 37",
)


# -- the independence constraints, as binding data ------------------------------

class IndependenceConstraint(object):
    """One condition that makes the validator's derivation independent.

    ``checked_by`` names what actually enforces it. That field exists so the record cannot quietly
    claim to be the enforcement: for three of the four the real control is somewhere else — a
    static import check, an audit-log ordering, a human reading a commit — and the record's job is
    to state the condition and carry it to the stage that can check it.
    """

    __slots__ = ("id", "requirement", "why", "checked_by")

    def __init__(self, id, requirement, why, checked_by):  # noqa: A002 - the field is called id
        self.id = id
        self.requirement = requirement
        self.why = why
        self.checked_by = checked_by

    def as_dict(self):
        return {"id": self.id, "requirement": self.requirement, "why": self.why,
                "checked_by": self.checked_by}

    def __repr__(self):
        return "<IndependenceConstraint {}>".format(self.id)


SEPARATE_IMPLEMENTATION_PATH = "separate_implementation_path"
NO_BUILDER_FUNCTION_REUSE = "no_builder_function_reuse"
DERIVED_FROM_RAW_DATA_AND_SPEC = "derived_from_raw_data_and_spec"
REASONING_BEFORE_COMPARISON = "reasoning_recorded_before_comparison"

#: All four, always. :class:`ValidatorAssignment` binds this tuple with no way to supply another,
#: so "a validator recorded without the constraints" is not a state this package can represent.
INDEPENDENCE_CONSTRAINTS = (
    IndependenceConstraint(
        SEPARATE_IMPLEMENTATION_PATH,
        "the validator works on an implementation path separate from the builder's, sharing no "
        "module with it",
        "two implementations that share a module share its bugs, and a shared bug is invisible to "
        "the comparison — both sides compute the same wrong answer and agree",
        "tests/test_lane_independence.py — a static check over committed code, which is the only "
        "control a reviewer can verify from the repository alone",
    ),
    IndependenceConstraint(
        NO_BUILDER_FUNCTION_REUSE,
        "no reuse of the builder's transaction classification, FIFO, or valuation functions",
        "these three are where an ambiguous rule becomes a number; reusing one imports the "
        "builder's reading of the rule and the gate then certifies its own answer",
        "tests/test_lane_independence.py — the validator lane may not import a builder package, "
        "in either direction",
    ),
    IndependenceConstraint(
        DERIVED_FROM_RAW_DATA_AND_SPEC,
        "expected outputs are derived from raw chain data and the frozen specification only — "
        "never from the builder's code, intermediate artefacts, or output",
        "an expected output copied from the thing it is meant to check is not a check; it is a "
        "transcription, and it agrees by construction",
        "ticket 36's validation report, plus the committed per-account reasoning files that name "
        "the transaction hashes, receipts and traces they worked from",
    ),
    IndependenceConstraint(
        REASONING_BEFORE_COMPARISON,
        "the validator's reasoning is recorded and sealed before any comparison is run",
        "reasoning written after the comparison cannot be distinguished from reasoning written to "
        "match it, by the validator or by anyone reading the report afterwards",
        "audit-log ordering: validator_expected_sealed strictly before builder_output_revealed. "
        "This record carries the rule; ValidatorAssignment.ordering_refusal is the check ticket "
        "36 calls with the two timestamps",
    ),
)

CONSTRAINT_IDS = tuple(c.id for c in INDEPENDENCE_CONSTRAINTS)


# -- refusals -------------------------------------------------------------------

#: Strings that are not a name. A validator recorded as one of these would make ``UNASSIGNED`` look
#: like a state code walked out of on its own, which is the one reading of this register that must
#: never be available.
#: Spellings that are obviously not a name.
#:
#: **This is a tripwire, not a guarantee, and the difference matters.** A blocklist of placeholder
#: strings can only ever refuse the spellings somebody thought of; it was written without ``todo``
#: and accepted it for a day, which is the whole argument against relying on it. Any name-shaped
#: string that is not on this list is accepted, and no list closes that.
#:
#: What actually bounds the failure is one layer up:
#: :meth:`phase0.preconditions.PreconditionRegister.record_validator` takes a ``requester`` and
#: writes it to the hash-chained audit log with the record. So a placeholder recorded here is not
#: anonymous — it is attributable to whoever recorded it, at a verifiable position in the chain,
#: and §9.5's reader can see who claimed an assignment nobody made. The list catches the careless
#: case early, where the message can still say what the rule is; the audit chain is what makes the
#: deliberate case answerable.
_NON_NAMES = frozenset({
    "", "-", "--", "?", "??", "x", "tbd", "tba", "tbc", "n/a", "na", "none", "null", "nil",
    "unassigned", "assigned", "unknown", "pending", "anon", "anonymous", "someone", "somebody",
    "validator", "the validator", "independent validator", "an independent validator",
    "agent", "an agent", "ai", "ai agent", "an ai agent", "recorded", "recorded-for-test",
    "placeholder", "default", "same as above", "see above",
    "todo", "to do", "to-do", "fixme", "xxx", "tbd.", "later", "me", "myself", "self",
    "test", "testing", "example", "sample", "dummy", "fake", "temp", "temporary", "foo", "bar",
})


#: Public alias of the tripwire above, for :mod:`phase0.parameters`. Ticket 11's freeze record
#: names the person who froze the pre-registration and refuses the same spellings this one does —
#: one list, so the two records cannot come to disagree about what counts as a name. It is an alias
#: rather than a second set for the same reason :data:`INDEPENDENCE_CONSTRAINTS` is not a
#: parameter: a copy is a thing that can drift.
NON_NAMES = _NON_NAMES


#: Bracket pairs that mark a **template placeholder** — the part of a pasted command a reader was
#: supposed to replace with their own name and did not.
#:
#: This rule exists because the list above leaked a second time, and the second leak is the one that
#: shows why a list was never going to be enough. The first was ``todo``, a spelling nobody thought
#: of. The second was ``<نام شما>`` — Persian for "your name" — pasted verbatim out of a command
#: template into ``phase0 freeze PARAMETERS_FROZEN --requester``. It froze the pre-registration
#: under a name attributable to nobody, and every spelling in :data:`_NON_NAMES` is English, so
#: nothing objected.
#:
#: A blocklist of spellings cannot cross a language boundary; there is no list of every way to
#: write "your name here". A *shape* crosses it for free. Every documentation convention on earth
#: marks the replace-me part by wrapping it, so the wrapping is the signal and the contents do not
#: have to be understood at all.
_PLACEHOLDER_BRACKETS = (
    ("<", ">"), ("[", "]"), ("{", "}"), ("(", ")"),
    ("«", "»"), ("《", "》"), ("〈", "〉"), ("（", "）"), ("【", "】"),
)

#: Characters that make up a fill-in-the-blank rule rather than a name — §17's sign-off block is
#: written with them, and a person who copies the line instead of signing it lands here.
_BLANK_RUN = frozenset("_-. \t·—–")


def why_not_a_name(value):
    """The reason ``value`` is not a name, or ``None`` when nothing here objects.

    One predicate for both registers, so ticket 02's validator record and ticket 11's freeze record
    cannot come to disagree about what a name is. Three rules, weakest last:

    * wrapped in a placeholder bracket — language-independent, and the one that would have caught
      the freeze recorded as ``<نام شما>``;
    * nothing but blanks and punctuation — §17's sign-off line, copied rather than signed;
    * one of the spellings in :data:`_NON_NAMES` — the original tripwire, English-only.

    **Still a tripwire, and the ledger has not changed.** A name-shaped string in any script is
    accepted, and no rule here closes that: ``Ali`` and ``asdf`` are indistinguishable to this
    function. What bounds the deliberate case is unchanged and is one layer up — the requester is
    written into the hash-chained audit log beside the record, so a placeholder that gets through is
    attributable to whoever recorded it. What these rules buy is the *careless* case, caught early
    enough that the message can still say what the rule is.
    """
    text = "" if value is None else str(value).strip()
    for opening, closing in _PLACEHOLDER_BRACKETS:
        if text.startswith(opening) and text.endswith(closing) and len(text) > len(opening):
            return (
                "it is wrapped in {}...{}, which is how a command template marks the part the "
                "reader replaces with their own name. Pasting the line unchanged records a freeze "
                "attributable to nobody, and the contents of the brackets do not have to be read "
                "in any particular language for that to be true".format(opening, closing)
            )
    if text and set(text) <= _BLANK_RUN:
        return (
            "it is a blank rule rather than a name -- §17's sign-off block is written with these "
            "characters, and copying the line is not signing it"
        )
    if text.lower() in _NON_NAMES:
        return "it is one of the placeholder spellings this register refuses: {}".format(
            ", ".join(sorted(n for n in _NON_NAMES if n)))
    return None


def _name(value, what):
    """A person's or an agent's identifier, or a refusal naming the rule, the input and the cost."""
    text = "" if value is None else str(value).strip()
    refusal = why_not_a_name(value)
    if refusal is not None:
        raise ValueError(
            "{} must be a name, got {!r}: {}. Ticket 02 ends with a *named* Independent Validator; "
            "a placeholder recorded here would make UNASSIGNED look like a state the code can "
            "leave on its own, and the register would then report an assignment nobody made. "
            "Naming someone is the project owner's decision and this package will not default "
            "it.".format(what, value, refusal)
        )
    return text


def _date(value, what):
    """A ``datetime.date``, from a date or an ISO ``YYYY-MM-DD`` string."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.date.fromisoformat(value.strip())
        except ValueError:
            raise ValueError(
                "{} must be an ISO date (YYYY-MM-DD), got {!r}".format(what, value)
            )
    raise ValueError(
        "{} is required and must be a date or an ISO YYYY-MM-DD string, got {!r}. Week 1 is a "
        "checkable fact or it is a claim in a document.".format(what, value)
    )


# -- a booked external review ---------------------------------------------------

class ExternalSpecialistReview(object):
    """The ticket-37 booking that converts ``MACHINE-INDEPENDENT`` to ``EXTERNALLY REVIEWED``.

    Constructing one is the only path to that status. It is deliberately a small amount of work and
    deliberately not zero: a named specialist, a count inside :data:`MIN_COMPLEX_ACCOUNTS` to
    :data:`MAX_COMPLEX_ACCOUNTS`, and the date it was booked.

    **What it does not establish.** That the specialist is a human, that they are external to the
    project, or that they reviewed anything. This class refuses the names this package knows are
    wrong — :class:`ValidatorAssignment` refuses a specialist who is the validator or the person
    accountable for it, and the register refuses the primary builder — and it cannot refuse a third
    party who is in fact the builder's colleague. Ticket 37 is where the findings are resolved;
    this is where the cost is committed.
    """

    __slots__ = ("specialist", "accounts", "booked_on", "cost_usd", "note")

    def __init__(self, specialist, accounts, booked_on, cost_usd=None, note=""):
        self.specialist = _name(specialist, "the external specialist")
        accounts = int(accounts)
        if not MIN_COMPLEX_ACCOUNTS <= accounts <= MAX_COMPLEX_ACCOUNTS:
            raise ValueError(
                "the external specialist review covers {}-{} complex accounts; got {}. §9.5 fixes "
                "the range, and it is a range rather than a minimum because the accounts are the "
                "flagged ones — fewer is not the review, and more is a different, unbudgeted "
                "piece of work whose cost nobody has agreed.".format(
                    MIN_COMPLEX_ACCOUNTS, MAX_COMPLEX_ACCOUNTS, accounts)
            )
        self.accounts = accounts
        self.booked_on = _date(booked_on, "the booking date")
        self.cost_usd = None if cost_usd is None else calc(cost_usd)
        self.note = str(note or "")

    def as_dict(self):
        return {
            "specialist": self.specialist,
            "accounts": self.accounts,
            "booked_on": self.booked_on.isoformat(),
            "cost_usd": None if self.cost_usd is None else str(self.cost_usd),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            specialist=data["specialist"], accounts=data["accounts"],
            booked_on=data["booked_on"], cost_usd=data.get("cost_usd"),
            note=data.get("note", ""),
        )

    def __repr__(self):
        return "<ExternalSpecialistReview {} {} accounts>".format(self.specialist, self.accounts)


# -- the assignment -------------------------------------------------------------

CORRELATED_ERROR_NOTE = (
    "Two agents built from the same base model, given the same specification, share priors and "
    "make CORRELATED errors — the same misreading of an ambiguous rule, the same wrong assumption "
    "about a token standard. That is exactly the failure class independent validation exists to "
    "catch and the class two agents are worst at catching, because the comparison reads agreement "
    "as evidence and two lanes running the same mistake agree. The status is therefore "
    "MACHINE-INDEPENDENT at best until the external specialist review of {}-{} complex accounts "
    "is booked; that review is a cost to pay, not an option to consider.".format(
        MIN_COMPLEX_ACCOUNTS, MAX_COMPLEX_ACCOUNTS)
)


#: Appended to :data:`CORRELATED_ERROR_NOTE` once the review is booked. The shared prior is not
#: deleted by paying for the review; it is narrowed to the accounts the review did not cover.
EXTERNAL_REVIEW_RESIDUE = (
    "That review is now booked ({specialist}, {accounts} complex accounts), which is what raises "
    "the status to EXTERNALLY REVIEWED. It reduces the correlated-error residue and does not "
    "remove it: it covers the flagged complex accounts, not the whole run, so every account "
    "outside that set still rests on two agents that share priors."
)


class ValidatorAssignment(object):
    """A named Independent Validator, bound to the independence constraints.

    :param name: who. A placeholder is refused; see :data:`_NON_NAMES`.
    :param kind: :data:`HUMAN` or :data:`AI_AGENT`.
    :param start_date: when they join. Must be inside week 1 of ``project_start``.
    :param project_start: day 0 of the 10-12 week window, so week 1 is checkable rather than
        asserted.
    :param commitment: one of :data:`COMMITMENT_LEVELS`.
    :param covers: the scope of the commitment. Must be all of :data:`REQUIRED_SCOPE`.
    :param accountable_human: required when ``kind`` is :data:`AI_AGENT` — an agent's output is
        somebody's responsibility, and ticket 01 records the same fact for the builder.
    :param external_review: an :class:`ExternalSpecialistReview`, or ``None``.

    The independence constraints are **not** a parameter. Every instance carries
    :data:`INDEPENDENCE_CONSTRAINTS` entire, so there is no assignment in this package that is not
    bound to all four, and no call site at which someone could pass three.

    The status is not a parameter either. :meth:`validation_status` derives it from what is
    recorded; there is no argument, setter or serialised key that sets one.
    """

    __slots__ = ("name", "kind", "start_date", "project_start", "commitment", "covers",
                 "accountable_human", "external_review", "note")

    def __init__(self, name, kind, start_date, project_start, commitment, covers,
                 accountable_human=None, external_review=None, note=""):
        self.name = _name(name, "the Independent Validator's name")

        if kind not in VALIDATOR_KINDS:
            raise ValueError(
                "kind must be one of {}, got {!r}. Which it is decides the ceiling on the "
                "validation status, so it is not optional and there is no default.".format(
                    ", ".join(VALIDATOR_KINDS), kind)
            )
        self.kind = kind

        if kind == AI_AGENT:
            self.accountable_human = _name(
                accountable_human, "the human accountable for the AI validator's output")
        else:
            self.accountable_human = (
                None if accountable_human is None
                else _name(accountable_human, "the accountable human"))

        self.project_start = _date(project_start, "the project start date")
        self.start_date = _date(start_date, "the validator's start date")
        last = self.project_start + datetime.timedelta(days=WEEK_ONE_DAYS - 1)
        if not self.project_start <= self.start_date <= last:
            raise ValueError(
                "the Independent Validator starts in week 1: {} to {} inclusive, given a project "
                "start of {}. Got {}. This is the half of 'bringing a validator in at the end to "
                "sign a report is not independent validation' that a date can check — a validator "
                "who arrives later cannot have built or approved the golden set before the "
                "pipeline was written, so their expected outputs can no longer have been derived "
                "without seeing the builder's.".format(
                    self.project_start.isoformat(), last.isoformat(),
                    self.project_start.isoformat(), self.start_date.isoformat())
            )

        if commitment not in COMMITMENT_LEVELS:
            raise ValueError(
                "commitment must be one of {}, got {!r}. There is deliberately no value meaning "
                "'available when we need them': ticket 01 forbids starting downstream work on a "
                "provisional or shared assignment, and this is the same rule for the second "
                "role.".format(", ".join(COMMITMENT_LEVELS), commitment)
            )
        self.commitment = commitment

        covers = tuple(dict.fromkeys(str(c) for c in (covers or ())))
        unknown = [c for c in covers if c not in REQUIRED_SCOPE]
        if unknown:
            raise ValueError(
                "unknown scope item(s) {}; expected from {}".format(
                    ", ".join(repr(u) for u in unknown), ", ".join(REQUIRED_SCOPE))
            )
        missing = [item for item in REQUIRED_SCOPE if item not in covers]
        if missing:
            raise ValueError(
                "the commitment must cover all of {} — got {}, missing {}. A commitment that "
                "covers only sign-off is the shape ticket 02 exists to refuse: a validator brought "
                "in at the end to sign a report has seen the builder's output before deriving "
                "anything, so there is nothing independent left to compare. Scope items map to "
                "tickets {}.".format(
                    ", ".join(REQUIRED_SCOPE), ", ".join(covers) or "nothing",
                    ", ".join(missing),
                    "; ".join("{}={}".format(k, "/".join(v)) for k, v in sorted(
                        SCOPE_TICKETS.items())))
            )
        self.covers = tuple(item for item in REQUIRED_SCOPE if item in covers)

        if external_review is not None:
            self._refuse_a_self_review(external_review)
        self.external_review = external_review
        self.note = str(note or "")

    # -- what is always true of one ------------------------------------------

    @property
    def constraints(self):
        """All four, always. A property rather than a field so it cannot be reassigned."""
        return INDEPENDENCE_CONSTRAINTS

    @property
    def is_ai_agent(self):
        return self.kind == AI_AGENT

    @property
    def correlated_error_note(self):
        """The honest limitation, for an AI validator. ``None`` for a human.

        It travels with the record rather than living in a document, because the strength of the
        check has to be legible wherever the status is read.

        Booking the review does not delete it. The note gains a second half saying what the review
        did and did not buy: it covers the flagged complex accounts, so the correlated-error
        residue is *reduced* over the rest of the run and not removed. A limitation that vanished
        the moment the cost was paid would teach a reader that ``EXTERNALLY REVIEWED`` means the
        shared prior is gone, and it is not.
        """
        if not self.is_ai_agent:
            return None
        if self.external_review is None:
            return CORRELATED_ERROR_NOTE
        return "{} {}".format(CORRELATED_ERROR_NOTE, EXTERNAL_REVIEW_RESIDUE.format(
            specialist=self.external_review.specialist, accounts=self.external_review.accounts))

    @property
    def external_review_budget(self):
        """:data:`EXTERNAL_REVIEW_BUDGET`. Every assignment carries it; none may decline it."""
        return EXTERNAL_REVIEW_BUDGET

    def _refuse_a_self_review(self, review):
        known = {self.name.lower()}
        if self.accountable_human:
            known.add(self.accountable_human.lower())
        if review.specialist.lower() in known:
            raise ValueError(
                "the external specialist {!r} is the validator or the human accountable for it. "
                "Ticket 37 requires a specialist who is neither the builder nor the validator "
                "agent — a review by the party being reviewed converts nothing, and recording it "
                "as EXTERNALLY REVIEWED would be the exact upgrade-by-assertion the three-tier "
                "label exists to prevent.".format(review.specialist)
            )

    # -- the status ----------------------------------------------------------

    def validation_status(self):
        """The status this assignment can reach today. Derived, never stored, never asserted."""
        return validation_status(self)

    def with_external_review(self, review):
        """A new assignment carrying ``review``. The original is unchanged.

        Immutable rather than a setter so that a recorded assignment cannot be upgraded in place by
        anything holding a reference to it; the register rewrites the file and audits the act.
        """
        if not isinstance(review, ExternalSpecialistReview):
            raise TypeError(
                "external review must be an ExternalSpecialistReview, got {}. The status "
                "EXTERNALLY REVIEWED is reached by booking the review, not by naming it.".format(
                    type(review).__name__)
            )
        return ValidatorAssignment(
            name=self.name, kind=self.kind, start_date=self.start_date,
            project_start=self.project_start, commitment=self.commitment, covers=self.covers,
            accountable_human=self.accountable_human, external_review=review, note=self.note,
        )

    # -- the check ticket 36 calls -------------------------------------------

    def ordering_refusal(self, reasoning_sealed_at, comparison_started_at):
        """Why this comparison may not count, or ``None`` if the ordering held.

        The :data:`REASONING_BEFORE_COMPARISON` constraint in a form a later stage can check: hand
        it the two timestamps and it answers. Equal timestamps are refused as well as inverted
        ones — "sealed at the same instant the comparison began" is not evidence of order, and a
        check that accepted it would pass for any clock too coarse to tell them apart.

        :param reasoning_sealed_at: when the validator's reasoning was committed.
        :param comparison_started_at: when the builder's output was revealed to it.
        :returns: a sentence naming the rule, the two inputs and the cost, or ``None``.

        **What it does not do.** It does not observe either event. It compares two timestamps
        somebody supplies, so it detects a recorded ordering violation and not a copy channel
        outside the process. That residue is why ticket 36's evidence is the audit log's own
        entries rather than a field in a report.
        """
        if reasoning_sealed_at is None or comparison_started_at is None:
            return (
                "the reasoning-before-comparison constraint cannot be checked: sealed_at={!r}, "
                "comparison_started_at={!r}. A missing timestamp is not a passing check. Until "
                "both are recorded the comparison establishes nothing, because reasoning written "
                "afterwards cannot be told from reasoning written to match.".format(
                    reasoning_sealed_at, comparison_started_at)
            )
        if reasoning_sealed_at < comparison_started_at:
            return None
        return (
            "the validator's reasoning was sealed at {!r}, which is not strictly before the "
            "comparison began at {!r}. Constraint {!r} is bound to {}'s assignment and it is "
            "violated. Reasoning recorded at or after the comparison cannot be distinguished from "
            "reasoning recorded to match it, so the comparison is not evidence of independence "
            "and the validation status it would support is NOT INDEPENDENT — which blocks the "
            "main test.".format(
                reasoning_sealed_at, comparison_started_at, REASONING_BEFORE_COMPARISON, self.name)
        )

    # -- serialisation -------------------------------------------------------

    def attribution(self):
        """The one-line "who" the precondition register stores for §15.4."""
        who = "{} ({})".format(self.name, "AI agent" if self.is_ai_agent else "human")
        if self.accountable_human:
            who += ", accountable: {}".format(self.accountable_human)
        return "{}, {} from {}".format(who, self.commitment.lower().replace("_", "-"),
                                       self.start_date.isoformat())

    def as_dict(self):
        """Machine-readable, and it carries the derived facts as well as the recorded ones.

        ``independent_validator``, ``validation_status`` and the constraints are all present, so a
        reader of the JSON does not have to import this module to learn what the record supports.
        They are outputs of :func:`validation_status`, never inputs: :meth:`from_dict` ignores them.
        """
        return {
            "independent_validator": ASSIGNED,
            "name": self.name,
            "kind": self.kind,
            "accountable_human": self.accountable_human,
            "project_start": self.project_start.isoformat(),
            "start_date": self.start_date.isoformat(),
            "starts_in_week_one": True,
            "commitment": self.commitment,
            "covers": list(self.covers),
            "scope_tickets": {k: list(v) for k, v in SCOPE_TICKETS.items()},
            "independence_constraints": [c.as_dict() for c in INDEPENDENCE_CONSTRAINTS],
            "external_review_budget": EXTERNAL_REVIEW_BUDGET.as_dict(),
            "external_review": (None if self.external_review is None
                                else self.external_review.as_dict()),
            "validation_status": self.validation_status().value,
            "validation_status_label": label(self.validation_status()),
            "permits_main_test": self.validation_status().permits_main_test,
            "correlated_error_note": self.correlated_error_note,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild from :meth:`as_dict`. The derived keys are ignored, not trusted.

        A stored ``validation_status`` is a report of what the record supported when it was
        written. Reading it back as authority would be exactly the assertion path this module has
        none of — edit one character in the file and an AI validator would read as
        ``EXTERNALLY REVIEWED``. So the status is recomputed from the booking, every time.
        """
        review = data.get("external_review")
        return cls(
            name=data["name"], kind=data["kind"], start_date=data["start_date"],
            project_start=data["project_start"], commitment=data["commitment"],
            covers=data.get("covers", ()), accountable_human=data.get("accountable_human"),
            external_review=None if review is None else ExternalSpecialistReview.from_dict(review),
            note=data.get("note", ""),
        )

    def __repr__(self):
        return "<ValidatorAssignment {} {} {}>".format(
            self.name, self.kind, label(self.validation_status()))


# -- the status rule ------------------------------------------------------------

#: The pre-registration's spelling of each status, for a reader. The enum is the value.
LABELS = {
    ValidationStatus.MACHINE_INDEPENDENT: "MACHINE-INDEPENDENT",
    ValidationStatus.EXTERNALLY_REVIEWED: "EXTERNALLY REVIEWED",
    ValidationStatus.NOT_INDEPENDENT: "NOT INDEPENDENT",
}


def label(status):
    """The hyphenated label. Unknown status raises rather than falling back to its own name."""
    try:
        return LABELS[ValidationStatus(status)]
    except (KeyError, ValueError):
        raise ValueError(
            "no label for validation status {!r}; expected one of {}. A status without a label "
            "would be reported as whatever its enum name happened to be, which is how a fourth "
            "state gets into a report nobody agreed to.".format(
                status, ", ".join(sorted(LABELS.values())))
        )


def validation_status(assignment):
    """The status an assignment can reach **today**. The whole rule, in one place.

        no assignment                          -> NOT INDEPENDENT
        external specialist review booked      -> EXTERNALLY REVIEWED
        AI agent, no review booked             -> MACHINE-INDEPENDENT
        anything else                          -> NOT INDEPENDENT

    ``anything else`` is one case and it is worth naming: a **human** validator with no external
    review booked. The three-tier vocabulary has no word for it. ``MACHINE-INDEPENDENT`` would be a
    lie in the label — nothing about a person is machine-independent — and ``EXTERNALLY REVIEWED``
    is the thing that has not happened. §9.5's own fallback sentence is unambiguous about which way
    to resolve a gap: "if even limited external review is impossible, Validation Status: NOT
    INDEPENDENT, Main Test Execution: BLOCKED". So the register refuses to invent a fourth label
    and returns the one that blocks. That is deliberately conservative and it is the safe
    direction: the cost of being wrong here is a booking, and the cost of being wrong the other way
    is a published result nobody checked.
    """
    if assignment is None:
        return ValidationStatus.NOT_INDEPENDENT
    if assignment.external_review is not None:
        return ValidationStatus.EXTERNALLY_REVIEWED
    if assignment.is_ai_agent:
        return ValidationStatus.MACHINE_INDEPENDENT
    return ValidationStatus.NOT_INDEPENDENT


def main_test_refusal(status, what):
    """Why ``what`` may not run under this validation status, or ``None`` if it may.

    ``NOT INDEPENDENT`` blocks the main test. The sentence is built here, once, so that every
    enforcement point refuses in the same words and none of them owns the rule —
    :meth:`phase0.preconditions.PreconditionRegister.independence_refusal` carries it into
    ``execute_stage``, and :func:`require_main_test_permitted` raises it for callers that prefer an
    exception.
    """
    status = ValidationStatus(status)
    if status.permits_main_test:
        return None
    return (
        "validation status is {} and {} is refused. §9.5: without independent validation the main "
        "test is BLOCKED, and this is that block — it is the governed stage list refusing, not a "
        "note in a report. Nothing downstream of VALIDATION_PASSED may run: the null distribution "
        "is computed by the same code as the main test, so a null built on unvalidated code cannot "
        "detect the bug it shares. What changes the answer is recording an Independent Validator "
        "bound to the independence constraints ({}) and, for an AI validator, booking the external "
        "specialist review of {}-{} complex accounts — {}.".format(
            label(status), what, ", ".join(CONSTRAINT_IDS),
            MIN_COMPLEX_ACCOUNTS, MAX_COMPLEX_ACCOUNTS, EXTERNAL_REVIEW_BUDGET.standing)
    )


def require_main_test_permitted(status, what):
    """Raise :class:`~phase0.errors.NotIndependentError`, or return ``True``."""
    refusal = main_test_refusal(status, what)
    if refusal is not None:
        raise NotIndependentError(refusal)
    return True
