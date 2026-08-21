"""The decision queue, and the guarantee that it stays a queue.

``phase0 decisions`` was written after a request to automate the human approvals. The motive was
right — reconstructing a week of context before a thirty-second act is a real bottleneck — and the
literal form would void the experiment, so what got built prepares the acts and does not perform
them.

The first case below is therefore the important one: this module must have no write path. Every
other test here is about the report being useful; that one is about it not becoming the thing it was
asked to be.
"""

import ast
import os

import pytest

from phase0 import decisions as decisions_module
from phase0.cli import main
from phase0.decisions import Decision, open_decisions, report
from phase0.preconditions import PRECONDITION_KEYS


def test_the_module_has_no_write_path(tmp_path):
    """The guarantee, checked structurally rather than promised in prose.

    A queue that could record its own items is an approver, which is exactly what was declined. So
    the module's source may not call anything that writes: no ``record``, no ``record_validator``,
    no ``book_external_review``, no ``transition``, no ``freeze``, no ``open``.

    Checked over the committed source rather than by inspection, because the failure mode is a
    later edit that adds one convenience call — and the convenience is the whole danger.
    """
    with open(decisions_module.__file__, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=os.path.basename(decisions_module.__file__))

    # Keyed on the RECEIVER, not on the method name. The first version of this check forbade
    # `append` outright and failed on `lines.append` — building a list of strings is not writing to
    # an audit log. What actually matters is which object is being talked to: the injected registers
    # are the only things here that can change state, so calls to them are allowlisted to reads and
    # everything else about them is a failure.
    REGISTERS = {"preconditions", "governance", "runs", "audit", "parameters"}
    READS = {"satisfied", "state", "unmet", "is_ready", "status", "report", "value",
             "freeze_status", "validation_status", "entries"}

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        receiver = node.func.value
        if isinstance(receiver, ast.Name) and receiver.id in REGISTERS:
            if node.func.attr not in READS:
                offenders.append("{}.{}".format(receiver.id, node.func.attr))

    assert not offenders, (
        "phase0.decisions calls {}; it prepares human acts and must not perform them. A queue that "
        "can record its own items is the auto-approver this module exists instead of".format(
            sorted(set(offenders)))
    )


def test_the_write_path_check_would_actually_fire():
    """Guard the guard. A structural check that cannot fail is theatre.

    Plants the convenience that would turn the queue into an approver — recording a precondition
    on the way past — and asserts the detector names it.
    """
    planted = ast.parse(
        "def go(preconditions):\n"
        "    lines = []\n"
        "    lines.append('fine')\n"
        "    preconditions.satisfied()\n"
        "    preconditions.record('primary_builder', 'someone', 'me')\n"
    )

    REGISTERS = {"preconditions", "governance", "runs", "audit", "parameters"}
    READS = {"satisfied", "state", "unmet", "is_ready", "status", "report", "value",
             "freeze_status", "validation_status", "entries"}
    offenders = []
    for node in ast.walk(planted):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            receiver = node.func.value
            if isinstance(receiver, ast.Name) and receiver.id in REGISTERS:
                if node.func.attr not in READS:
                    offenders.append("{}.{}".format(receiver.id, node.func.attr))

    assert offenders == ["preconditions.record"], offenders


def test_every_decision_says_why_it_is_not_automatable(tmp_path):
    """Per act, not one blanket sentence.

    "A human must do it" is unfalsifiable and teaches nobody anything. Each entry has to say what
    specifically cannot be delegated — accountability, money, somebody's calendar, or the
    independence the act exists to establish — because those are different reasons and only some of
    them would still apply if the project were resourced differently.
    """
    w = _wired(tmp_path)
    for decision in open_decisions(w.preconditions, w.governance, w.parameters):
        assert decision.why_not_automatable, decision.key
        assert len(decision.why_not_automatable) > 40, (
            "{} gives a reason too short to be a reason".format(decision.key))
        assert decision.blocks, "{} does not say what it blocks".format(decision.key)
        assert decision.needs, "{} does not say what the decider must supply".format(decision.key)


def _wired(tmp_path):
    from phase0.execution import wire

    return wire(str(tmp_path / "state"))


def test_a_recorded_precondition_drops_off_the_queue(tmp_path):
    """An empty queue has to be reachable, or the report is decoration.

    A list that always shows the same six items is one nobody reads twice. This records one
    precondition through the real register and asserts the corresponding entry disappears.
    """
    w = _wired(tmp_path)
    before = {d.key for d in open_decisions(w.preconditions, w.governance, w.parameters)}
    assert "01" in before

    w.preconditions.record(PRECONDITION_KEYS[0], "A. Builder", "Research Owner")

    after = {d.key for d in open_decisions(w.preconditions, w.governance, w.parameters)}
    assert "01" not in after
    assert "02" in after, "recording one precondition must not clear the others"


def test_the_sign_off_entry_appears_only_once_the_parameters_are_frozen(tmp_path):
    """§17's remaining signatures are not a task until there is a freeze to sign for."""
    from phase0 import governance as gov

    w = _wired(tmp_path)
    assert "§17" not in {d.key for d in open_decisions(w.preconditions, w.governance)}

    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    assert "§17" in {d.key for d in open_decisions(w.preconditions, w.governance)}


def test_every_command_names_a_real_subcommand():
    """A queue whose commands do not run is worse than no queue: it costs a person an attempt.

    Each entry's command is checked against the parser's actual subcommands, so a renamed
    subcommand breaks this rather than being discovered by whoever tried to act on it.
    """
    from phase0.cli import build_parser

    parser = build_parser()
    known = set()
    for action in parser._actions:
        if hasattr(action, "choices") and action.choices:
            known.update(str(c) for c in action.choices)

    class _Empty(object):
        def satisfied(self):
            return {}

    class _Open(object):
        state = "PARAMETERS_OPEN"

    for decision in open_decisions(_Empty(), _Open()):
        if not decision.command or not decision.command.startswith("phase0 "):
            continue
        subcommand = decision.command.split()[1]
        assert subcommand in known, (
            "{} points at `phase0 {}`, which is not a subcommand".format(
                decision.key, subcommand)
        )


def test_the_report_states_the_refusal_rather_than_only_listing_work(tmp_path):
    """A reader who meets this list should learn why it is a list and not a script."""
    w = _wired(tmp_path)
    text = "\n".join(report(w.preconditions, w.governance, w.parameters))

    assert "does not perform them" in text
    assert "naming nobody" in text


def test_the_command_line_prints_the_queue(tmp_path, capsys):
    code = main(["--root", str(tmp_path / "state"), "decisions"])
    out = capsys.readouterr().out

    assert code == 0
    assert "only a person may perform" in out
    assert "Primary Builder" in out


def test_a_decision_carrying_no_command_is_still_reported():
    """Not every act is a command. §17 is an edit to a document, and the queue must still hold it."""
    decision = Decision(
        key="X", question="q", blocks="b", needs="n", command=None, prepared="",
        why_not_automatable="a reason long enough to actually be a reason, stated plainly",
    )
    lines = decision.lines()

    assert any("q" in line for line in lines)
    assert not any(line.strip().startswith("command") for line in lines)
