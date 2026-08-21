"""Layer 3 — the battery as an artifact of the run, not just a test file.

Three things are checked here that no individual case can check about itself:

* **it is complete and cannot quietly shrink** — the sixteen §9.3 names, in order, every one of
  them actually executed, and no skip or xfail anywhere in the package;
* **its hash is frozen** — pinned to an absolute literal, carried in the §9.6 freeze manifest, and
  verified by ``gate_validation`` the way the arbiter will verify it;
* **it is wired to the gate** — a known-answer failure produces a pass rate below 1, which fails
  §9.8, which leaves the null distribution and the main test unauthorised. §9.1 puts
  ``KNOWN_ANSWER_TESTS`` second in the binding order, and governance makes ``NULL_COMPLETE``
  unreachable without ``VALIDATION_PASSED``.
"""

import ast
import os
from decimal import Decimal

import pytest

from contracts import NUMERIC_POLICY_VERSION, REPORTING_SCHEMA_VERSION, FreezeManifest
from gate_validation.artifacts import (
    VALIDATION_LAYER_ORDER,
    check_layer_order,
    check_validation_gate,
)
from gate_validation.manifest import (
    REQUIRED_MANIFEST_FIELDS,
    check_freeze_manifest,
    freeze_manifest_from,
)
from phase0.governance import NULL_COMPLETE, VALIDATION_PASSED, position

from . import battery as B

PACKAGE = os.path.dirname(os.path.abspath(__file__))

#: §9.6. The frozen hash of the sixteen cases — their inputs and their pre-registered answers.
#: Written as an absolute literal, because that is the entire point of a freeze: this value may
#: change only by re-freezing the battery on purpose, and §9.7 then invalidates the run rather
#: than patching it.
FROZEN_KNOWN_ANSWER_FIXTURE_HASH = (
    "8e41d2e9c447732579a960bcaf45d707b4169593b5081c35a7cee99b17f13b7e"
)


# -- completeness ----------------------------------------------------------------


def test_the_battery_holds_exactly_the_sixteen_cases_in_order():
    """§9.3 names sixteen. A battery that can lose one is not a battery."""
    assert tuple(c.name for c in B.BATTERY) == B.REQUIRED_CASE_NAMES
    assert len(B.BATTERY) == 16
    assert len(set(B.REQUIRED_CASE_NAMES)) == 16


def test_every_required_case_has_a_runner_and_every_runner_has_a_case():
    assert set(B.RUNNERS) == set(B.REQUIRED_CASE_NAMES)


#: Every shape a waiver takes in pytest. ``importorskip`` is here because a conditional import is
#: the politest way to make a case disappear: the suite stays green and the count drops.
FORBIDDEN_MARKERS = ("skip", "skipif", "xfail")
FORBIDDEN_CALLS = ("skip", "xfail", "importorskip")


def _waivers_in(source, name):
    """Every skip, xfail or conditional-import waiver in one module, as ``file:line`` strings.

    Four shapes, and the last three were added after an audit found the first one alone was
    evadable by anyone who did not have to try. The check is only worth what its narrowest branch
    is worth, and its narrowest branch used to require the literal name ``pytest`` to the left of
    the dot:

    * ``@pytest.mark.skip`` / ``.skipif`` / ``.xfail`` — the original, and the obvious one;
    * ``pytest.skip()``, ``pytest.xfail()``, ``pytest.importorskip()`` — likewise;
    * ``from pytest import skip`` then a bare ``skip()``. Identical effect, invisible to a check
      keyed on the attribute chain. The import itself is flagged, so the waiver is caught at the
      line that makes it available rather than at each use;
    * ``__test__ = False``. Not a pytest marker at all — it tells collection to skip the module
      entirely, so every case in it disappears and the suite still reports green over what is
      left. It is one line and it is the quietest of the four.
    """
    tree = ast.parse(source, filename=name)
    offences = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_MARKERS:
            if isinstance(node.value, ast.Attribute) and node.value.attr == "mark":
                offences.append("{}:{} @pytest.mark.{}".format(name, node.lineno, node.attr))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (node.func.attr in FORBIDDEN_CALLS
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "pytest"):
                offences.append("{}:{} pytest.{}()".format(name, node.lineno, node.func.attr))
        if isinstance(node, ast.ImportFrom) and node.module in ("pytest", "_pytest.outcomes"):
            for alias in node.names:
                if alias.name in FORBIDDEN_CALLS or alias.name in FORBIDDEN_MARKERS:
                    offences.append("{}:{} from pytest import {}".format(
                        name, node.lineno, alias.name))
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__test__":
                    offences.append("{}:{} __test__ = ... (disables collection for the whole "
                                    "module)".format(name, node.lineno))
    return offences


def test_no_case_may_be_skipped_or_expected_to_fail():
    """§9.3: "No failing test may be waived as an 'edge case'."

    Structural, over the committed package, in the style of ``tests/test_lane_independence.py``.
    A rule stated in a docstring is a habit; a rule a static check enforces is a rule. Marking a
    known-answer case ``xfail`` is precisely the waiver §9.3 forbids, and it is a two-line change
    that nothing else in the suite would notice — the file would still be green.
    """
    offences = []
    for name in sorted(os.listdir(PACKAGE)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(PACKAGE, name), "r", encoding="utf-8") as fh:
            offences.extend(_waivers_in(fh.read(), name))

    assert not offences, (
        "the known-answer package contains a waiver mechanism: {}. §9.3 requires 100% to pass and "
        "provides no 'known edge case' state; a failing case is fixed or the gate "
        "fails.".format(", ".join(offences))
    )


def test_the_waiver_check_would_actually_catch_a_waiver():
    """Guard the guard. A structural check that cannot fail is theatre.

    Each of the four shapes is planted and the detector required to find it — including the two
    that are easiest to write by accident, ``skipif`` on a platform condition and
    ``importorskip`` on a package that has not landed yet.
    """
    planted = '''
import pytest

@pytest.mark.xfail(reason="known edge case")
def test_dead_pool():
    pass

@pytest.mark.skip
def test_thin_pool():
    pass

@pytest.mark.skipif(True, reason="not on this platform")
def test_migration():
    pass

def test_multi_hop():
    pytest.skip("later")

def test_first_hour():
    pipeline = pytest.importorskip("pipeline")
'''
    found = _waivers_in(planted, "planted.py")
    assert len(found) == 5, found
    assert any("xfail" in f for f in found)
    assert any("@pytest.mark.skip" in f for f in found)
    assert any("skipif" in f for f in found)
    assert any("pytest.skip()" in f for f in found)
    assert any("importorskip" in f for f in found)

    clean = '''
import pytest

@pytest.mark.parametrize("case", [1, 2])
def test_case(case):
    assert case
'''
    assert _waivers_in(clean, "clean.py") == []


def test_the_waiver_check_catches_the_two_shapes_that_used_to_walk_past_it():
    """Found by audit, not by inspection, and both were one line.

    The detector keyed on the literal name ``pytest`` to the left of the dot, so importing the same
    function by another route reached the same outcome with nothing objecting. And ``__test__``
    is not a pytest marker at all — it removes the module from collection, so every case in it
    disappears and the suite reports green over whatever is left, which is the exact shape of the
    waiver §9.3 forbids.

    Planted separately from the four above rather than folded in, so the count assertion there
    keeps meaning what it meant when it was written.
    """
    by_import = '''
from pytest import skip, importorskip

def test_dead_pool():
    skip("later")
'''
    found = _waivers_in(by_import, "by_import.py")
    assert any("from pytest import skip" in f for f in found), found
    assert any("from pytest import importorskip" in f for f in found), found

    by_collection = '''
__test__ = False

def test_thin_pool():
    assert False
'''
    found = _waivers_in(by_collection, "by_collection.py")
    assert len(found) == 1 and "disables collection" in found[0], found

    # A module that merely mentions the word is not a waiver: the check must not fire on prose or
    # on an unrelated name, or it becomes noise and someone widens the exclusions to quiet it.
    innocent = '''
SKIP_REASONS_ARE_FORBIDDEN = "no case may be skipped"

def test_case():
    assert SKIP_REASONS_ARE_FORBIDDEN
'''
    assert _waivers_in(innocent, "innocent.py") == []


def test_the_hand_computed_layer_runs_the_whole_battery_and_not_a_subset():
    """The parametrization must be ``B.BATTERY`` itself.

    Replacing it with a literal list of the cases that happen to pass would leave sixteen names in
    ``REQUIRED_CASE_NAMES``, a green suite, and a battery that tests three things.
    """
    path = os.path.join(PACKAGE, "test_hand_computed.py")
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)

    parametrized = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "parametrize" or len(node.args) < 2:
            continue
        argnames = node.args[0]
        if not (isinstance(argnames, ast.Constant) and argnames.value == "case"):
            continue
        values = node.args[1]
        parametrized.append(
            isinstance(values, ast.Attribute) and values.attr == "BATTERY"
        )

    assert parametrized, "no test parametrizes over the battery's cases"
    assert all(parametrized), (
        "a case-level test parametrizes over something other than the whole battery"
    )


def test_every_stage_of_the_ordered_pipeline_is_exercised(monkeypatch):
    """The battery spans the pipeline rather than one module — measured, not asserted by hand.

    §9.3's list is not sixteen netting tests. The five §4 stages are instrumented and the whole
    battery run; every stage must be reached by at least one case, or the battery is a unit-test
    suite wearing a pre-registration's name.
    """
    stages = ("stage_net", "stage_age", "stage_fifo", "stage_mark", "stage_score")
    reached = {stage: set() for stage in stages}
    running = {"case": None}

    def instrument(stage_name, original):
        def wrapper(*args, **kwargs):
            reached[stage_name].add(running["case"])
            return original(*args, **kwargs)

        return wrapper

    for stage in stages:
        monkeypatch.setattr(B, stage, instrument(stage, getattr(B, stage)))

    for case in B.BATTERY:
        running["case"] = case.name
        B.run_case(case)

    unreached = sorted(stage for stage in stages if not reached[stage])
    assert not unreached, (
        "these §4 stages are never reached by any case: {}. The battery spans the pipeline or it "
        "is a unit-test suite wearing a pre-registration's name.".format(unreached)
    )
    # Every case must reach at least one stage — a case that computed nothing would otherwise
    # pass by asserting nothing.
    covered = set().union(*reached.values())
    assert covered == set(B.REQUIRED_CASE_NAMES), (
        "these cases reach no pipeline stage at all: {}".format(
            sorted(set(B.REQUIRED_CASE_NAMES) - covered)
        )
    )


# -- the harness -----------------------------------------------------------------


def test_the_battery_reports_pass_fail_per_case_and_a_pass_rate():
    report = B.battery_report()
    assert report["total"] == 16
    assert report["passed"] == 16
    assert report["known_answer_pass_rate"] == Decimal("1")
    assert len(report["results"]) == 16
    assert all(r.passed for r in report["results"])
    assert {r.name for r in report["results"]} == set(B.REQUIRED_CASE_NAMES)


def test_against_an_empty_pipeline_the_harness_reports_sixteen_failures(monkeypatch):
    """Ticket 18's acceptance demo, kept as a permanent test.

    "Run against an empty pipeline, the harness reports sixteen failures and exits with a failure
    status." Every runner is replaced by one that computes nothing, which is what an unimplemented
    stage looks like from here. The harness must attribute each failure to its case — sixteen
    anonymous errors would be useless — and the pass rate must be exactly zero, not merely low.
    """
    def unimplemented(_inputs):
        raise NotImplementedError("this stage of the pipeline does not exist yet")

    monkeypatch.setattr(B, "RUNNERS", {name: unimplemented for name in B.RUNNERS})

    report = B.battery_report()
    assert report["passed"] == 0
    assert report["known_answer_pass_rate"] == Decimal("0")
    assert len(report["results"]) == 16
    for result in report["results"]:
        assert not result.passed
        assert result.name in B.REQUIRED_CASE_NAMES
        assert "NotImplementedError" in result.error

    # And that failure is what §9.8 reads.
    messages = check_validation_gate(_gate_report(report["known_answer_pass_rate"]))
    assert any("known_answer_pass_rate" in m for m in messages)


def test_a_single_failing_case_is_enough_to_fail_the_gate(monkeypatch):
    """15 of 16 is not "almost passing". §9.8 compares the rate to 1 exactly."""
    original = dict(B.RUNNERS)
    broken = dict(original)

    def wrong(_inputs):
        return {"buy_status": None}

    broken["Simple Buy + Full Sell"] = wrong
    monkeypatch.setattr(B, "RUNNERS", broken)

    report = B.battery_report()
    assert report["passed"] == 15
    assert report["known_answer_pass_rate"] != Decimal("1")

    messages = check_validation_gate(_gate_report(report["known_answer_pass_rate"]))
    assert any("known_answer_pass_rate" in m for m in messages), messages


def _gate_report(pass_rate):
    """A §9.8 report that satisfies every condition except the one under test."""
    return {
        "golden_set_precision": Decimal("1"),
        "golden_set_recall": Decimal("1"),
        "known_answer_pass_rate": pass_rate,
        "raw_quantity_mismatches": Decimal("0"),
        "fifo_assignment_mismatches": Decimal("0"),
        "max_per_event_usd_relative_error": Decimal("0.001"),
        "max_wallet_buy_quality_difference_pp": Decimal("0.1"),
        "reconciliation_event_agreement": Decimal("0.999"),
        "unexplained_golden_set_differences": Decimal("0"),
        "independent_review_completed": True,
    }


def test_a_clean_battery_leaves_the_gate_condition_satisfied():
    """The other half: the wiring must also let a correct battery through, or it proves nothing."""
    report = B.battery_report()
    assert check_validation_gate(_gate_report(report["known_answer_pass_rate"])) == []


# -- §9.1 ordering and §9.6 pinning ---------------------------------------------


def test_known_answer_tests_are_the_second_validation_layer():
    """§9.1 is binding: golden dataset, then known-answer tests, then everything else."""
    assert VALIDATION_LAYER_ORDER[1] == "KNOWN_ANSWER_TESTS"
    assert check_layer_order(("GOLDEN_DATASET", "KNOWN_ANSWER_TESTS")) == []
    skipped = check_layer_order(("GOLDEN_DATASET", "CROSS_SOURCE_RECONCILIATION"))
    assert skipped, "skipping the known-answer layer must be refused, not merely noticed"


def test_a_failing_battery_structurally_blocks_the_null_distribution():
    """Ticket 18: a known-answer failure prevents ``VALIDATION_PASSED``.

    The consequence is what matters. §9.8 leaves the null unauthorised, and governance makes
    ``NULL_COMPLETE`` unreachable without ``VALIDATION_PASSED`` — because the null is computed by
    the same code as the main test and cannot detect a bug it shares.
    """
    assert position(VALIDATION_PASSED) < position(NULL_COMPLETE)


def test_the_fixture_hash_is_frozen_to_an_absolute_literal():
    """§9.6 records this value. If the battery changes, this test fails — by design.

    A test comparing the hash to a freshly computed one would pass against any battery at all,
    which is the difference between recording a freeze and performing one.
    """
    assert B.known_answer_fixture_hash() == FROZEN_KNOWN_ANSWER_FIXTURE_HASH


def test_the_freeze_manifest_carries_the_fixture_hash_and_the_arbiter_checks_it():
    """The arbiter never imports the battery. It compares two recorded strings."""
    pinned = _manifest(B.known_answer_fixture_hash())
    assert check_freeze_manifest(pinned, dict(pinned)) == []

    manifest = freeze_manifest_from(pinned)
    assert isinstance(manifest, FreezeManifest)
    assert manifest.known_answer_fixture_hash == FROZEN_KNOWN_ANSWER_FIXTURE_HASH


def test_a_run_using_different_fixtures_is_a_freeze_violation():
    """The whole reason the hash exists: a battery that was edited after the freeze is a different
    experiment, and it must not be reportable under the frozen manifest."""
    pinned = _manifest(FROZEN_KNOWN_ANSWER_FIXTURE_HASH)
    observed = dict(pinned)
    observed["known_answer_fixture_hash"] = "0" * 64

    messages = check_freeze_manifest(pinned, observed)
    assert any("known_answer_fixture_hash" in m for m in messages), messages


def _manifest(fixture_hash):
    values = {
        "source_commit": "0" * 40,
        "dataset_snapshot": "snapshot-2026-08-01",
        "golden_set_version": "golden-v1",
        "protocol_coverage_version": "coverage-v1",
        "decoder_version": "decoder-v1",
        "model_version": "model-v1",
        "config_hash": "c" * 64,
        "master_seed": "s" * 64,
        "known_answer_fixture_hash": fixture_hash,
        "validation_report_hash": "v" * 64,
        "numeric_policy_version": NUMERIC_POLICY_VERSION,
        "reporting_schema_version": REPORTING_SCHEMA_VERSION,
    }
    missing = set(REQUIRED_MANIFEST_FIELDS) - set(values)
    assert not missing, (
        "the seam gained manifest field(s) {} that this fixture does not pin; a manifest the test "
        "cannot fill is one the battery is not really checked against".format(sorted(missing))
    )
    return values


@pytest.mark.parametrize("case", B.BATTERY, ids=[c.name for c in B.BATTERY])
def test_each_case_is_reproducible_from_the_record_alone(case):
    """A frozen case must survive being written down and read back.

    ``gate_validation`` reads artifacts as data and never imports what produced them, so anything
    the battery cannot express as canonical JSON is something the arbiter can never verify.
    """
    from contracts import canonical_hash, to_canonical_json

    blob = to_canonical_json({"inputs": case.inputs, "expected": case.expected})
    assert blob
    assert canonical_hash({"inputs": case.inputs, "expected": case.expected})
