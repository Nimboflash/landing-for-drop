"""The machine-readable register: ``data_budget: APPROVED | PENDING``, and why.

``APPROVED`` needs **two keys, and they turn in different hands.**

    1. A human records the approval — with a name, a date, a reference, and the *specific* total
       and ceiling they signed off. Money is spent by people, and the person is the record.
    2. Every source is ``PROVEN`` — by evidence in this register, not by an absent error.

Neither alone. An approval without proof is a purchase order for data nobody has confirmed exists;
proof without an approval is four working credentials nobody agreed to pay for. Ticket 03 is one
precondition because those two failures cost the same thing — a Phase 0 that starts and cannot
finish.

So ``data_budget`` is a **computed property with no setter**. It cannot be written by a probe, by
the CLI, by a JSON file, or by a future agent who finds the blockers inconvenient; the only way to
change it is to change one of the two facts underneath it. Assigning to it raises ``AttributeError``
— there is a test that goes red if that stops being true, because "we set the flag manually just to
unblock the run" is the exact move this design exists to prevent.

**The approval is bound to a number.** It records the total and ceiling that were signed off, and it
stops matching if either changes. Adding a fifth source, or moving a tier, silently re-opens the
question rather than inheriting a signature given for a different figure.

Money is ``Decimal`` throughout, through :mod:`contracts.numeric` — ``calc()`` rejects a float on
sight, here as everywhere else in this repository. Values are rendered with ``str()`` at the
serialization boundary so the register stays plain JSON with no doubles in it.
"""

import json
import os

from contracts.numeric import calc

from . import budget as budget_module
from . import terms as terms_module
from .outcomes import PROVEN
from .probes import PROBES, capabilities
from .prohibited import prohibited_register_entries
from .redaction import scrub

APPROVED = "APPROVED"
PENDING = "PENDING"

#: Where a human's approval is recorded by default. Alongside the other governance state, and
#: outside this package: it is a fact about the project, not about the code.
DEFAULT_APPROVAL_PATH = os.path.join(
    os.environ.get("PHASE0_STATE_DIR", ".phase0"), "data-budget-approval.json"
)

REGISTER_SCHEMA_VERSION = "provisioning-register-v1"


class HumanApproval(object):
    """A person, a date, a reference, and the exact figures they approved.

    Every field is required. An approval with no approver is one nobody gave; an approval with no
    reference is one nobody can find; an approval with no figures is a signature on a blank cheque,
    which is precisely what a $1,000 ceiling exists to prevent.
    """

    __slots__ = ("approver", "approved_on", "reference", "projected_total", "ceiling", "note")

    def __init__(self, approver, approved_on, reference, projected_total, ceiling, note=""):
        for name, value in (("approver", approver), ("approved_on", approved_on),
                            ("reference", reference)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    "HumanApproval.{} must be a non-empty string — an approval with a blank {} is "
                    "one nobody gave".format(name, name)
                )
        self.approver = approver.strip()
        self.approved_on = approved_on.strip()
        self.reference = reference.strip()
        # calc() refuses float. A budget approved in floats is a budget approved approximately.
        self.projected_total = calc(projected_total)
        self.ceiling = calc(ceiling)
        self.note = (note or "").strip()

    def covers(self, projected_total, ceiling):
        """Does this signature apply to *these* figures?

        Exact equality, on purpose. An approval given for $478/mo against a $1,000 ceiling says
        nothing about $606/mo, and a tolerance here would decide how much unapproved spending is
        close enough — a question nobody should be answering in a comparison operator.
        """
        return (self.projected_total == calc(projected_total)
                and self.ceiling == calc(ceiling))

    def as_dict(self):
        return {
            "approver": self.approver,
            "approved_on": self.approved_on,
            "reference": self.reference,
            "projected_total": str(self.projected_total),
            "ceiling": str(self.ceiling),
            "note": self.note,
        }

    # -- persistence -----------------------------------------------------------

    @classmethod
    def from_dict(cls, data):
        return cls(
            approver=data.get("approver", ""),
            approved_on=data.get("approved_on", ""),
            reference=data.get("reference", ""),
            projected_total=data.get("projected_total", "0"),
            ceiling=data.get("ceiling", "0"),
            note=data.get("note", ""),
        )

    @classmethod
    def load(cls, path=DEFAULT_APPROVAL_PATH):
        """Read a recorded approval, or ``None`` when none has been recorded.

        A missing file is not an error. "Nobody has approved this yet" is the normal state of the
        world at the start of a project, and it is reported, not raised.
        """
        if not path or not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
        if not content:
            return None
        return cls.from_dict(json.loads(content))

    def save(self, path=DEFAULT_APPROVAL_PATH):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.as_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
        return path


class ProvisioningRegister(object):
    """Probe outcomes, budget, terms and the prohibition — as one machine-readable record."""

    def __init__(self, results, approval=None, lines=None, ceiling=None, probes=PROBES,
                 vendor_terms=None):
        self.results = dict(results or {})
        self.approval = approval
        self.lines = budget_module.BUDGET_LINES if lines is None else tuple(lines)
        self.ceiling = budget_module.CEILING_USD if ceiling is None else calc(ceiling)
        self.probes = tuple(probes)
        self.terms = terms_module.VENDOR_TERMS if vendor_terms is None else vendor_terms

    # -- the two keys ----------------------------------------------------------

    @property
    def sources(self):
        """Every source that must be provisioned: the union of budget lines and probes.

        A union rather than either one alone. A source with a cost and no probe would be paid for
        and unverified; a source with a probe and no cost line would be verified and unbudgeted.
        Both are ways for a source to escape the ceiling, so both are counted.
        """
        names = [line.source for line in self.lines]
        for probe in self.probes:
            if probe.source not in names:
                names.append(probe.source)
        return tuple(names)

    @property
    def all_proven(self):
        """Key two. Every source has a result, and every result is ``PROVEN``.

        A source with no result at all is not proven — absence of a probe is not evidence.
        """
        for source in self.sources:
            result = self.results.get(source)
            if result is None or result.status != PROVEN:
                return False
        return True

    @property
    def approval_valid(self):
        """Key one. Somebody signed, and signed for these figures."""
        if self.approval is None:
            return False
        return self.approval.covers(self.projected_total, self.ceiling)

    @property
    def data_budget(self):
        """``APPROVED`` only with both keys. Computed — there is deliberately no setter.

        This is the property ticket 03 asks for, and the whole of its value is that it cannot be
        written. If it could, the first time a probe was inconvenient somebody would write it.
        """
        return APPROVED if (self.approval_valid and self.all_proven) else PENDING

    # -- budget ----------------------------------------------------------------

    @property
    def projected_total(self):
        return budget_module.projected_total(self.lines)

    @property
    def headroom(self):
        return budget_module.headroom(self.lines, self.ceiling)

    @property
    def within_ceiling(self):
        return budget_module.within_ceiling(self.lines, self.ceiling)

    # -- what is still in the way ----------------------------------------------

    def blockers(self):
        """Every reason ``data_budget`` is still ``PENDING``, in the order to act on them.

        Sources first, because they take days and somebody else's decision; the human approval
        last, because it takes a minute and is the final act. An empty list means APPROVED, and the
        CLI's exit code says so.
        """
        out = []
        for source in self.sources:
            result = self.results.get(source)
            if result is None:
                out.append("{}: no probe result recorded — unproven is not provisioned".format(
                    source))
            elif result.status != PROVEN:
                line = "{}: {} — {}".format(source, result.status, result.detail)
                if result.verbatim:
                    line += "\n      endpoint said: {}".format(result.verbatim.strip())
                out.append(line)

        if not self.within_ceiling:
            out.append(
                "projected total ${} exceeds the ${} ceiling".format(
                    self.projected_total, self.ceiling
                )
            )
        if self.approval is None:
            out.append(
                "no human approval recorded for the ${}/mo projected total against the ${}/mo "
                "ceiling — every source could be PROVEN and this would still be PENDING".format(
                    self.projected_total, self.ceiling
                )
            )
        elif not self.approval_valid:
            out.append(
                "the recorded approval covers ${} against a ${} ceiling, but the projected total "
                "is now ${} against ${}. Figures changed after the signature; re-approve.".format(
                    self.approval.projected_total, self.approval.ceiling,
                    self.projected_total, self.ceiling
                )
            )
        return out

    # -- serialization ---------------------------------------------------------

    def as_dict(self):
        """The machine-readable register. Plain JSON, no floats, no credentials.

        Every string is scrubbed of configured credential values on the way out, as a second line
        of defence behind per-record redaction. Belt and braces is the correct amount of caution
        for a file that gets committed.
        """
        capability = capabilities(self.probes)
        document = {
            "schema": REGISTER_SCHEMA_VERSION,
            "ticket": "03-approve-data-budget-and-access",
            "data_budget": self.data_budget,
            "approval_recorded": self.approval is not None,
            "approval_covers_current_figures": self.approval_valid,
            "all_sources_proven": self.all_proven,
            "approval": None if self.approval is None else self.approval.as_dict(),
            "budget": budget_module.as_dict(self.lines, self.ceiling),
            "sources": {
                source: {
                    "capability": capability.get(source),
                    "reachability": (self.results[source].status
                                     if source in self.results else "NOT_PROBED"),
                    "result": (self.results[source].as_dict()
                               if source in self.results else None),
                    "terms": (self.terms[source].as_dict() if source in self.terms else None),
                }
                for source in self.sources
            },
            "prohibited_sources": prohibited_register_entries(),
            "gap_closure_blockers": terms_module.gap_closure_blockers(self.terms),
            "blockers": self.blockers(),
        }
        return _scrubbed(document)

    def to_json(self, indent=2):
        return json.dumps(self.as_dict(), indent=indent, sort_keys=True)


def _scrubbed(value):
    """Recursively remove any configured credential value from a document."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {key: _scrubbed(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrubbed(item) for item in value]
    return value


def build(transport=None, env=None, approval_path=DEFAULT_APPROVAL_PATH, probes=PROBES):
    """Run every probe, read any recorded approval, and return the register."""
    from .probes import run_all

    results = run_all(transport=transport, env=env, probes=probes)
    return ProvisioningRegister(results, approval=HumanApproval.load(approval_path), probes=probes)
