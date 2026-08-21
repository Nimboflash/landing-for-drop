"""The CI workflow, checked from the repository rather than trusted.

Ticket 18's seventh criterion asks that the known-answer battery be "run on every subsequent
pipeline ticket, not only at the validation gate". That is a claim about the development process,
and until `.github/workflows/suite.yml` existed the only mechanical repetition in this project was
somebody remembering to type ``pytest``.

A workflow file closes it and a workflow file is also one ``git rm`` from not existing, with nothing
in the suite noticing — which is the same shape as every other rule in this repository that is
enforced rather than described. So the file is pinned here: it must exist, it must run the battery as
a step of its own, that step must not be permitted to fail, and it must pin the interpreter the tree
is actually written for.

**Parsed as text, not as YAML, and that is a real limitation.** ``pyproject.toml`` declares
``dependencies = []`` and the tree has no runtime dependency at all; adding PyYAML so a test could
read a config file would be a poor trade. So these checks are substring and line-shape assertions.
They would not notice a workflow that was syntactically valid YAML expressing something different in
a way that happened to contain the right substrings. What they do notice is the deletion, the
renaming, and the quiet ``continue-on-error`` — which are the three things that actually happen.

The stronger version of this criterion — a stage-level rule refusing a measuring stage until the
battery has run in that run — was attempted on 2026-08-16 and reverted. See
``docs/tickets/18-freeze-known-answer-battery.md``: it added an ordering rule beside
``STAGE_AUTHORITY`` rather than inside it, and ``tests/properties/test_execution.py`` was right to
fail. This file is the process half; that one is still open.
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "suite.yml")


@pytest.fixture(scope="module")
def workflow():
    assert os.path.exists(WORKFLOW), (
        "{} is gone. Ticket 18's seventh criterion is that the known-answer battery is the standing "
        "regression suite; with no CI the only thing running it is somebody's memory.".format(
            os.path.relpath(WORKFLOW, ROOT))
    )
    with open(WORKFLOW, encoding="utf-8") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def directives(workflow):
    """The workflow with its comment lines removed.

    Needed because these checks are substring assertions over text, and the file explains itself at
    length: the comment describing *why* there is no separate mutation step contains the string
    ``tests/mutations``, which made the check asserting its absence fail on the prose arguing for it.

    A comment must neither satisfy a check nor trip one. That is a limitation of reading YAML as text
    rather than parsing it, and it is worth the trade only while the limitation is stated — see this
    module's docstring.
    """
    return "\n".join(line for line in workflow.split("\n") if not line.strip().startswith("#"))


def test_the_workflow_runs_the_known_answer_battery_as_its_own_step(directives):
    """Its own step, not merely inside the full suite.

    The battery is already collected by a bare ``pytest``, so this step adds no coverage. What it
    adds is a check that goes red on its own line: sixteen frozen cases failing inside 3,500 passing
    dots is a fact nobody reads, and §9.3's "no failing test may be waived as an edge case" is
    hard to honour about a failure nobody saw.
    """
    assert "tests/known_answer" in directives
    assert re.search(r"name:\s*Known-answer battery", directives), (
        "the battery step lost its name, so a failure no longer says what failed"
    )


def test_no_step_is_allowed_to_fail_quietly(directives):
    """``continue-on-error`` on any step here is the waiver mechanism §9.3 forbids, spelled in YAML.

    It would turn a red check green while the battery failed underneath — the same outcome as
    marking a case ``xfail``, reached through a file the known-answer package's own AST scan does not
    read.
    """
    assert "continue-on-error" not in directives
    assert "|| true" not in directives, "a shell fallback is the same waiver by another route"


def test_the_workflow_pins_the_interpreter_the_tree_is_written_for(directives):
    """3.9, because the tree is written to 3.9 and a later one would pass while hiding that.

    No ``|`` unions and no ``list[str]`` anywhere in ``src/``; those are 3.10 syntax. A CI job on
    3.12 would accept code this project cannot run, and the failure would surface on whichever
    machine actually has 3.9 — which is the one the suite is developed on.
    """
    assert 'python-version: "3.9"' in directives

    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as handle:
        pyproject = handle.read()
    assert 'requires-python = ">=3.9"' in pyproject, (
        "the workflow pins 3.9 and pyproject no longer asks for it; one of the two moved"
    )


def test_the_mutation_battery_is_not_run_as_a_second_step(directives):
    """It is the most expensive thing in the project and `pytest` already collects it.

    Measured rather than assumed: each mutation copies the tree and runs pytest in a **subprocess**,
    so 113 mutations are roughly 226 cold interpreter starts. Locally that hides inside six minutes
    because ``__pycache__`` is warm; a fresh runner has no such thing, and running it a second time
    for a step label would double the slowest part of the job.

    This case exists because the first version of the workflow did exactly that.
    """
    assert "tests/mutations" not in directives, (
        "the mutation battery has a step of its own again; the full-suite step already runs it"
    )


def test_the_cheap_checks_run_before_the_slow_one(directives):
    """Fast failure, and it is the reason the steps are in the order they are.

    A tree broken in the ways that matter most should fail in under a minute rather than after the
    mutation battery has finished. If the full suite were first, every failure would cost the whole
    job — and the one line of output identifying it would be a single red dot among three and a half
    thousand.
    """
    battery = directives.index("Known-answer battery")
    structural = directives.index("Structural checks")
    full = directives.index("Full suite")

    assert battery < structural < full


def test_the_timeout_allows_for_a_cold_mutation_battery(directives):
    """Six minutes warm is not the number this job sees, and a timeout kill reads as a failure.

    A job cancelled on timeout is indistinguishable in the checks list from a job whose tests
    failed, which would make the standing regression suite a source of false alarms — and a check
    people learn to ignore is worse than no check.
    """
    match = re.search(r"timeout-minutes:\s*(\d+)", directives)
    assert match, "the job has no timeout, so a hung run occupies a runner until GitHub kills it"
    assert int(match.group(1)) >= 45, (
        "timeout-minutes is {}; the mutation battery alone is ~226 subprocess pytest runs from a "
        "cold cache".format(match.group(1))
    )


def test_the_workflow_runs_the_structural_checks_by_name(directives):
    """The checks whose failure means the architecture moved, not that a number changed."""
    for named in ("test_lane_independence.py", "test_shared_purity.py", "test_post_t0_barrier.py",
                  "test_signature_barrier.py", "test_frozen_context.py"):
        assert named in directives, "{} is not named in the workflow".format(named)


def test_it_runs_on_push_rather_than_only_when_asked(directives):
    """A workflow that only runs on ``workflow_dispatch`` is not standing, it is available."""
    triggers = directives.split("on:", 1)[1].split("permissions:", 1)[0]
    assert "push:" in triggers
    assert "pull_request:" in triggers
