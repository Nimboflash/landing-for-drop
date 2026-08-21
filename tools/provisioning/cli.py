"""``provisioning-probe`` — run every probe, print what is provisioned, and exit non-zero until it
all is.

    provisioning-probe                 run the four probes, print the table and the blockers
    provisioning-probe --json          the machine-readable register on stdout
    provisioning-probe terms           the vendor terms that constrain the freeze
    provisioning-probe prohibited      the coin-level endpoints that are refused in code
    provisioning-probe approve ...     record a human's approval of the budget

**Exit non-zero while ``data_budget`` is PENDING.** A green exit has to mean provisioned, because a
green exit is the only part of this anybody will read on a busy day. The exit code is the outcome:

    0  APPROVED     both keys turned: a human signed, and all four sources are PROVEN
    1  PENDING      at least one blocker, each named on stderr
    2  usage error

``approve`` writes the human's half and nothing else. It cannot make ``data_budget`` APPROVED on its
own — running it with a source still unproven prints the remaining blockers and still exits 1 — and
that is the design, not a limitation. The command exists so the signature is recorded where the code
can see it, not so the flag can be set.

Credentials are read from the environment and never printed. The register is scrubbed on the way
out, so ``--json`` is safe to redirect into a file that gets committed.
"""

import argparse
import os
import sys

from . import terms as terms_module
from .budget import CEILING_USD, projected_total
from .outcomes import PROVEN
from .prohibited import PROHIBITED_SOURCES
from .redaction import CREDENTIAL_ENV_VARS
from .register import APPROVED, DEFAULT_APPROVAL_PATH, HumanApproval, build

EXIT_APPROVED = 0
EXIT_PENDING = 1
EXIT_USAGE = 2

#: Purely cosmetic, and only where a terminal will render it.
_MARK = {"PROVEN": "[x]"}


def _mark(status):
    return _MARK.get(status, "[ ]")


def _print_table(register, stream):
    stream.write("\nPhase 0 — ticket 03, data budget and vendor access\n")
    stream.write("=" * 78 + "\n\n")

    stream.write("{:<20} {:<14} {}\n".format("SOURCE", "REACHABILITY", "CAPABILITY UNDER TEST"))
    stream.write("-" * 78 + "\n")
    for source in register.sources:
        result = register.results.get(source)
        status = result.status if result else "NOT_PROBED"
        capability = next(
            (p.capability for p in register.probes if p.source == source), "(no probe)"
        )
        stream.write("{} {:<18} {:<14} {}\n".format(
            _mark(status), source, status, _wrap(capability, 40)
        ))

    stream.write("\n")
    for source in register.sources:
        result = register.results.get(source)
        if result is None:
            continue
        stream.write("  {}: {}\n".format(source, result.detail))
        if result.verbatim:
            stream.write("      endpoint said, verbatim: {}\n".format(result.verbatim.strip()))
        if result.status == PROVEN and result.evidence:
            stream.write("      evidence: {}\n".format(_evidence_line(result.evidence)))

    stream.write("\nBUDGET\n")
    stream.write("-" * 78 + "\n")
    for line in register.lines:
        amount = "unpriced (no invoice attached)" if not line.is_priced else "${}/mo".format(
            line.monthly_usd
        )
        stream.write("  {:<20} {:<32} {}\n".format(line.source, amount, line.tier))
    stream.write("  {:<20} ${}/mo against a ${}/mo ceiling (headroom ${})\n".format(
        "projected total", register.projected_total, register.ceiling, register.headroom
    ))

    blockers = register.blockers()
    stream.write("\nDATA BUDGET: {}\n".format(register.data_budget))
    stream.write("-" * 78 + "\n")
    if not blockers:
        stream.write("  Both keys turned: a human recorded the approval and every source is "
                     "PROVEN.\n")
    else:
        stream.write("  Blocked by {} thing(s):\n".format(len(blockers)))
        for blocker in blockers:
            stream.write("    - {}\n".format(blocker))
    stream.write("\n")


def _wrap(text, width):
    return text if len(text) <= width else text[: width - 1] + "…"


def _evidence_line(evidence):
    return ", ".join("{}={}".format(k, evidence[k]) for k in sorted(evidence))[:400]


def _credentials_note(env, stream):
    missing = [name for name in CREDENTIAL_ENV_VARS if not (env.get(name) or "").strip()]
    if missing:
        stream.write("Credentials not configured: {}\n".format(", ".join(missing)))
        stream.write("Nothing was contacted for those sources. Export them and re-run.\n")


# -- commands ------------------------------------------------------------------

def cmd_probe(args, out, err, env, transport=None):
    register = build(env=env, approval_path=args.approval_path, transport=transport)
    if args.json:
        out.write(register.to_json() + "\n")
    else:
        _credentials_note(env, out)
        _print_table(register, out)

    if register.data_budget == APPROVED:
        return EXIT_APPROVED
    err.write("data_budget is PENDING: {} blocker(s). Exiting non-zero.\n".format(
        len(register.blockers())
    ))
    return EXIT_PENDING


def cmd_approve(args, out, err, env, transport=None):
    total = projected_total()
    approval = HumanApproval(
        approver=args.approver,
        approved_on=args.on,
        reference=args.reference,
        projected_total=total,
        ceiling=CEILING_USD,
        note=args.note or "",
    )
    path = approval.save(args.approval_path)
    out.write("Recorded: {} approved ${}/mo against the ${}/mo ceiling on {} ({}).\n".format(
        approval.approver, total, CEILING_USD, approval.approved_on, approval.reference
    ))
    out.write("Written to {}\n".format(path))
    out.write(
        "\nThis is one of the two keys. data_budget stays PENDING until every source is also "
        "PROVEN — run `provisioning-probe` to see what is left.\n"
    )
    return EXIT_APPROVED


def cmd_terms(args, out, err, env, transport=None):
    document = terms_module.as_dict()
    for source in sorted(document["sources"]):
        entry = document["sources"][source]
        out.write("\n{} — {}\n".format(source, entry["vendor"]))
        out.write("  history starts: {}   covers window 1: {}\n".format(
            entry["history_starts"], entry["covers_window_1"]
        ))
        for term in entry["terms"]:
            flag = " [BLOCKS GAP CLOSURE]" if term["blocks_gap_closure"] else ""
            out.write("  - ({}) {}{}\n".format(term["kind"], term["statement"], flag))
            out.write("      source: {}\n".format(term["provenance"]))
    out.write("\n")
    return EXIT_APPROVED


def cmd_prohibited(args, out, err, env, transport=None):
    out.write("\nPROHIBITED sources — refused in code, not merely documented.\n")
    out.write("Calling one requires an explicit SourceOverride(approver, reason, ticket).\n\n")
    for source in PROHIBITED_SOURCES:
        out.write("  {:<26} {}\n".format(source.source_id, source.shape))
        out.write("  {:<26} {}\n\n".format("", source.why))
    return EXIT_APPROVED


def build_parser():
    parser = argparse.ArgumentParser(
        prog="provisioning-probe",
        description="Prove the Phase 0 data sources are reachable, rather than assume it.",
    )
    parser.add_argument("--json", action="store_true", help="print the machine-readable register")
    parser.add_argument(
        "--approval-path", default=DEFAULT_APPROVAL_PATH,
        help="where the human approval is recorded (default: %(default)s)",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("probe", help="run every probe (default)")
    sub.add_parser("terms", help="vendor terms that constrain the freeze")
    sub.add_parser("prohibited", help="the coin-level endpoints refused in code")

    approve = sub.add_parser("approve", help="record a human's approval of the budget")
    approve.add_argument("--approver", required=True, help="who approved it")
    approve.add_argument("--on", required=True, help="date of approval, ISO (YYYY-MM-DD)")
    approve.add_argument("--reference", required=True,
                         help="where the decision is recorded: PO number, minute, ticket")
    approve.add_argument("--note", default="")
    return parser


COMMANDS = {
    "probe": cmd_probe,
    None: cmd_probe,
    "approve": cmd_approve,
    "terms": cmd_terms,
    "prohibited": cmd_prohibited,
}


def main(argv=None, out=None, err=None, env=None, transport=None):
    """``transport`` is the seam, not a flag: it lets the suite drive all five outcomes through
    the real command without a network and without a credential. Left ``None`` in production, in
    which case each probe builds its own live transport *after* its credential check."""
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    env = os.environ if env is None else env

    parser = build_parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code else EXIT_APPROVED

    return COMMANDS[args.command](args, out, err, env, transport=transport)


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    sys.exit(main())
