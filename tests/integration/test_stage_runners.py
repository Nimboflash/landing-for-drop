"""Thirteen stages, thirteen real runners, one governed run.

``tests/integration/test_execution.py`` walks the same thirteen stages with a trivial injected
runner and proves that *governance* works. This file walks them with the runners registered in
:data:`pipeline.stages.STAGE_RUNNERS` and asks the other question: does each stage actually compute
what its key says, when reached the only way a stage may be reached — through
``phase0.execution.execute_stage``, behind the start gate, with its run record written first?

Until this commit the answer was no, for all thirteen. The only runner in the tree was
``phase0/cli.py:_trivial_runner``, whose docstring says it "computes nothing on purpose".

What the walk shows, stage by stage
-----------------------------------

    step0.universe               COMPLETED four windows, every one below §6.1's floor
    golden_set.trace             CRASHED   blocked — ticket 03
    known_answer.battery         COMPLETED 16/16 frozen cases, pass rate 1
    pipeline.buy_quality         COMPLETED one wallet, one buy, return -0.25
    benchmark.match              COMPLETED one matched set, five primary controls
    follower.adjust              COMPLETED five capital levels, all reportable
    reconciliation.cross_source  CRASHED   blocked — tickets 03, 12, 13
    validation.independent       CRASHED   blocked — tickets 02, 36
    null.leader                  COMPLETED two windows x forty runs
    null.follower                COMPLETED two windows x forty runs
    threshold.calibrate          COMPLETED locks 0.41
    main_test                    COMPLETED zero of four windows pass at 0.41
    decision.emit                COMPLETED STOP

**``step0.universe`` completes here and refuses in a real run, and both are the point.** Its runner
measures whatever windows it is handed; this walk hands it four fixture universes of three to six
accounts, so it completes and every window comes back ``INSUFFICIENT CANDIDATE UNIVERSE``. A run
with no observations — which is every run in this tree, because nothing here has touched real chain
data — gets ``StageBlocked`` naming ticket 12 instead, and
:func:`test_step0_universe_refuses_when_no_observations_are_supplied` pins that. The stage moved out
of the blocked set when ``src/universe/`` was merged; what it did *not* do is become a stage that
has something to measure.

**The run stops at ``validation.independent``, and the walk lifts the gate by hand.** That stage
advances ``VALIDATION_PASSED``, and ``VALIDATION_PASSED`` is the prerequisite for
``CODE_AND_DATA_FROZEN``, which is the prerequisite for every execution-lane stage. Its runner
refuses unconditionally, because ``src/groundtruth/`` does not exist (tickets 02, 36). So a real
run today reaches the validation gate and stops there — not for want of wiring, which is what this
commit supplies, but for want of an independent validator, which no amount of wiring can supply.
:func:`walk` therefore calls ``governance.transition(VALIDATION_PASSED, ...)`` directly to reach the
five stages behind it, and :func:`test_the_run_cannot_pass_the_validation_gate_on_its_own` pins that
the lift was necessary. A test that had to open a gate to get where it was going has to say so;
otherwise the suite reads as though a whole run were possible today, and it is not.

**The chain is real, and the run ends in a STOP.** ``threshold.calibrate`` is handed what the two
null stages produced, ``main_test`` is evaluated at the threshold calibration locked, and
``decision.emit`` receives the main test's own result. The window scores in ``stage_fixtures`` are
fixed *before* the threshold is known — choosing them afterwards is the thing §8.4's ordering exists
to prevent — and none of them clears 0.41, so zero of four windows pass and the gate says STOP.
That is a result about a toy fixture, not about the hypothesis, and it is pinned here because the
value a chain produces is the only evidence that the chain is joined up.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

import universe_fixtures as U
from contracts import GateOutcome
from phase0 import governance as gov
from phase0.errors import StageNotCompleted, TransitionError
from phase0.execution import COMPLETED, CRASHED, STAGE_AUTHORITY, execute_stage
from phase0.runs import STAGES
from pipeline.execute import run_stage
from pipeline.stages import BLOCKED_STAGES, LIVE_STAGES, runner_for

from . import stage_fixtures as F

D = Decimal


@pytest.fixture
def w(tmp_path):
    return F.wired(tmp_path / "state")


def go(w, stage, inputs=None, requester=F.REQUESTER, commit=F.COMMIT):
    return run_stage(
        stage, requester, wiring=w, commit=commit, dataset_snapshot=F.DATASET_SNAPSHOT,
        inputs=inputs, master_seed=F.MASTER_SEED,
    )


def walk(w):
    """Every one of the thirteen, in order, each value fed to the stage that needs it.

    Returns ``{stage: StageResult}``. The two human acts (§11 and §39's freezes) and the one
    hand-lifted validation gate are performed on the governance machine directly, exactly as
    ``tests/integration/test_execution.py`` performs the freezes: they are not stages.
    """
    results = {}

    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    results["step0.universe"] = go(w, "step0.universe", F.step0_universe_inputs())
    results["golden_set.trace"] = go(w, "golden_set.trace")
    results["known_answer.battery"] = go(w, "known_answer.battery")
    results["pipeline.buy_quality"] = go(w, "pipeline.buy_quality", F.buy_quality_inputs())
    results["benchmark.match"] = go(w, "benchmark.match", F.benchmark_match_inputs())
    results["follower.adjust"] = go(w, "follower.adjust", F.follower_adjust_inputs())
    results["reconciliation.cross_source"] = go(w, "reconciliation.cross_source")
    results["validation.independent"] = go(w, "validation.independent")

    # The gate the blocked stage cannot open. See this module's docstring: without an independent
    # validator there is no honest way to earn VALIDATION_PASSED, and without it the five stages
    # below are unreachable. Lifted here so they can be exercised; never lifted in a real run.
    w.governance.transition(gov.VALIDATION_PASSED, "Research Owner",
                            {"note": "lifted by hand in a test; ticket 36 is not delivered"})
    w.governance.transition(gov.CODE_AND_DATA_FROZEN, "Research Owner")

    results["null.leader"] = go(w, "null.leader", F.null_inputs("leader"))
    results["null.follower"] = go(w, "null.follower", F.null_inputs("follower_adjusted"))

    calibrated = go(w, "threshold.calibrate", F.calibrate_inputs(
        results["null.leader"].value, results["null.follower"].value))
    results["threshold.calibrate"] = calibrated
    threshold = calibrated.value.threshold

    main_test = go(w, "main_test", F.main_test_inputs(threshold))
    results["main_test"] = main_test

    results["decision.emit"] = go(w, "decision.emit", F.decision_inputs(
        main_test.value, results["null.leader"].value, results["null.follower"].value, threshold))

    return results


# -- every stage is reached, and each records the outcome it should ---------------


def test_every_one_of_the_thirteen_stages_is_reached_through_execute_stage(w):
    """The claim this whole commit exists to make: no stage silently has no runner."""
    results = walk(w)

    assert sorted(results) == sorted(STAGES)
    for stage in STAGES:
        assert results[stage].run_id, (
            "{} left no run record, so nothing was ever about to run for it".format(stage))


def test_the_ten_live_stages_completed_and_the_three_blocked_ones_crashed(w):
    results = walk(w)

    assert {stage: results[stage].status for stage in STAGES} == dict(
        [(stage, COMPLETED) for stage in LIVE_STAGES]
        + [(stage, CRASHED) for stage in BLOCKED_STAGES]
    )


def test_a_blocked_stage_publishes_no_value_at_all(w):
    """Not an empty result, not a zero, not a ``None`` — the read itself is refused."""
    results = walk(w)

    for stage in BLOCKED_STAGES:
        with pytest.raises(StageNotCompleted):
            results[stage].value


def test_a_blocked_stage_moves_nothing(w):
    """Four crashes, and the governance state is exactly where the last completion left it."""
    results = walk(w)

    for stage in BLOCKED_STAGES:
        assert results[stage].advanced_to is None
        assert results[stage].state_before == results[stage].state_after


# -- the validation gate, which no runner in this tree can open -------------------


def test_the_run_cannot_pass_the_validation_gate_on_its_own(w):
    """``walk`` lifts ``VALIDATION_PASSED`` by hand. This is why it has to.

    ``validation.independent`` is the only stage that advances ``VALIDATION_PASSED``, its registered
    runner refuses unconditionally, and ``CODE_AND_DATA_FROZEN`` requires ``VALIDATION_PASSED``. So
    a run driven entirely by registered runners halts at the validation gate — which is the honest
    state of this tree, and the reason the execution lane below is exercised behind a lift a real
    run does not get.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    assert STAGE_AUTHORITY["validation.independent"].advances == gov.VALIDATION_PASSED
    assert go(w, "validation.independent").status == CRASHED
    assert w.governance.state == gov.PARAMETERS_FROZEN

    with pytest.raises(TransitionError):
        w.governance.transition(gov.CODE_AND_DATA_FROZEN, "Research Owner")


# -- step0.universe: the stage that measures, and still refuses with nothing to measure ---


def test_step0_universe_measured_all_four_windows_from_the_run_records_snapshot(w):
    """Ticket 26's report: four §6.3 windows, one frozen snapshot, sizes pinned as literals.

    Three, four, five and six accounts — the fixtures' own, written out rather than read back off
    the report, so a runner that measured one window four times changes this line.

    It does **not** pin the ordering, and saying that it did would be the claim this commit exists
    to remove: ``F.STEP0_ELIGIBLE`` already lists the windows in the design's order, so "the design's
    order" and "the order they were supplied in" are the same sequence here and no assertion can
    tell them apart. The test below supplies them in a different order and is where that guarantee
    lives.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    report = go(w, "step0.universe", F.step0_universe_inputs()).value

    assert [m.window.key.value for m in report.measurements] == [
        "W1_2023H1", "W2_2023H2", "W3_2024H1", "W4_2024H2"]
    assert [m.eligible_universe_size for m in report.measurements] == [3, 4, 5, 6]
    assert report.dataset_snapshot == F.DATASET_SNAPSHOT
    assert report.parameter_freeze_hash == F.PARAMETER_FREEZE_HASH
    assert len(report.digest) == 64


def test_step0_universe_reports_the_windows_in_the_designs_order_not_the_callers(w):
    """Which windows Step 0 covered is a fact about the experiment, not about the call.

    The four are handed over as W4, W2, W1, W3 — a caller's order, and one no design registers.
    ``Step0Report`` cannot catch this: it compares the *set* of window keys against the design's,
    so a report in any permutation of the four satisfies it, and ``report.measurements`` is a
    tuple that keeps whatever order it was built in. Every reader downstream — the digest's
    ``windows`` list, a reviewer reading §6.1's four blocks in sequence — would then be reading
    the order the arguments happened to arrive in as though it were §6.3's calendar.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    shuffled = [F.step0_window(U.W4, 6), F.step0_window(U.W2, 4),
                F.step0_window(U.W1, 3), F.step0_window(U.W3, 5)]
    report = go(w, "step0.universe", F.step0_universe_inputs(windows=shuffled)).value

    assert [m.window.key.value for m in report.measurements] == [
        "W1_2023H1", "W2_2023H2", "W3_2024H1", "W4_2024H2"]
    assert [m.eligible_universe_size for m in report.measurements] == [3, 4, 5, 6]


def test_a_re_run_measures_the_same_windows_when_the_inputs_were_lazy(w):
    """Ticket 26: a re-run returns identical numbers — including when the caller passed generators.

    ``Step0WindowInputs`` materialises its three sequences at wiring time. Without that, a caller
    who wrote the observations as a generator expression gets a first run over the whole window
    and a second run over nothing: not a quieter answer, but a different population from the same
    pinned inputs. §6.1's funnel then inverts and the second run crashes, so what this pins is
    that the retry of a held or re-requested stage answers rather than fails.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    lazy = []
    for window, eligible in F.STEP0_ELIGIBLE:
        built = dict(U.step0_inputs(
            [U.observation(U.address(n), window=window) for n in range(1, eligible + 1)],
            window=window))
        for lazily in ("observations", "verdicts", "heuristic_modifications"):
            built[lazily] = (item for item in built[lazily])
        lazy.append(F.Step0WindowInputs(**built))

    first = go(w, "step0.universe", F.step0_universe_inputs(windows=lazy))
    second = go(w, "step0.universe", F.step0_universe_inputs(windows=lazy))

    assert (first.status, second.status) == (COMPLETED, COMPLETED)
    assert [m.eligible_universe_size for m in second.value.measurements] == [3, 4, 5, 6]
    assert first.value.digest == second.value.digest


def test_the_step0_runner_refuses_a_context_for_another_stage(w):
    """The crossed-wire check, made from inside the runner because nothing outside it can.

    ``execute_stage`` takes the runner as an opaque callable — that is the whole reason ``phase0``
    never learns what a stage does — so if the registry mapped ``step0.universe``'s runner to
    another key, a Step 0 report would be filed under that stage's authority and nothing in the
    shared lane could see it. ``decide._require_stage``'s *body* is pinned by mutation 100; this
    pins that this runner calls it.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    result = execute_stage(
        "pipeline.buy_quality",
        runner_for("step0.universe", **F.step0_universe_inputs()),
        F.REQUESTER,
        governance=w.governance, preconditions=w.preconditions, runs=w.runs, audit=w.audit,
        commit=F.COMMIT, dataset_snapshot=F.DATASET_SNAPSHOT,
        config={"stage": "pipeline.buy_quality"}, master_seed=F.MASTER_SEED,
    )

    assert result.status == CRASHED
    assert "computes stage 'step0.universe'" in result.reason
    assert "context for stage 'pipeline.buy_quality'" in result.reason


class _PrintsAsAnotherSnapshot(str):
    """Equal to the run record's snapshot; ``str()`` says something else entirely."""

    def __str__(self):
        return "a-snapshot-nobody-pinned"


def test_the_snapshot_the_runner_checks_is_the_snapshot_the_report_publishes(w):
    """One fact, one identity rule — the class this repository has now found five times.

    ``measure_window`` and ``step0_report`` key the snapshot through ``str()``; the runner's own
    check compares it against the run record with ``==``. Two rules for one fact is a value that
    can satisfy the check and be published under another name, and the check's message says in so
    many words that this is the thing it prevents. The witness below is small on purpose: what is
    being pinned is that the transformation happens once, before the check, so there is no gap for
    a value to sit in.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    sneaky = _PrintsAsAnotherSnapshot(F.DATASET_SNAPSHOT)
    assert sneaky == F.DATASET_SNAPSHOT and str(sneaky) != F.DATASET_SNAPSHOT

    result = go(w, "step0.universe", F.step0_universe_inputs(dataset_snapshot=sneaky))

    assert result.status == CRASHED
    assert "reproducible from neither" in result.reason
    with pytest.raises(StageNotCompleted):
        result.value


def test_step0_universe_measured_the_five_distributions_per_window(w):
    """§6.1's five, by name, for every window — the shapes later matching depends on."""
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    report = go(w, "step0.universe", F.step0_universe_inputs()).value

    for measurement in report.measurements:
        assert sorted(measurement.distributions) == sorted(
            ("valid_buy_count", "buy_volume_usd", "active_days", "wallet_age_days",
             "smart_account_share"))
        assert measurement.distributions["valid_buy_count"].n == \
            measurement.eligible_universe_size


def test_a_window_below_ten_thousand_is_a_carried_status_and_not_a_crash(w):
    """§6.1's stopping condition is a **measurement**, and this is the stage that measures it.

    Every fixture window is far below the floor of 10,000, so all four come back
    ``INSUFFICIENT CANDIDATE UNIVERSE`` — and the stage still COMPLETES and still publishes the
    report. A runner that raised on this would crash on the single most informative cheap result
    Phase 0 can produce, publish nothing, and file a finding in the audit log as a defect. §6.1 says
    such a *window* is not valid and the design must be revised, which is narrower than failing the
    run; the refusals that stop a short universe being **used** are on ``FrozenUniverse`` and
    ``require_step0_complete``, one step later and not here.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    result = go(w, "step0.universe", F.step0_universe_inputs())

    assert result.status == COMPLETED
    report = result.value
    assert [m.status.value for m in report.measurements] == [
        "INSUFFICIENT CANDIDATE UNIVERSE"] * 4
    assert report.permits_ranking is False
    assert sorted(k.value for k in report.insufficient_windows) == [
        "W1_2023H1", "W2_2023H2", "W3_2024H1", "W4_2024H2"]


def test_step0_universe_moves_no_governance_state_and_can_be_re_run(w):
    """A build-lane stage: it measures and advances nothing, so a retry is a retry."""
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    first = go(w, "step0.universe", F.step0_universe_inputs())
    second = go(w, "step0.universe", F.step0_universe_inputs())

    assert first.advanced_to is None and second.advanced_to is None
    assert w.governance.state == gov.PARAMETERS_FROZEN
    assert first.value.digest == second.value.digest, (
        "ticket 26: the counts are reproducible from the frozen snapshot, so a re-run returns "
        "identical numbers")


def test_step0_universe_refuses_when_no_observations_are_supplied(w):
    """The honest refusal, and the only reason left for it.

    The ticket 25-28 blocker this stage used to carry said ``src/universe/`` was on an unmerged
    branch whose barrier audit had failed. That is false now — the package is on this commit and
    the runner above measures with it — so the blocker is gone rather than reworded. What is left
    is ticket 12, which is still true and stays true until an authenticated archival node makes the
    first data pull possible.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    result = go(w, "step0.universe")

    assert result.status == CRASHED
    assert result.error_type == "StageBlocked"
    assert "1 unmet blocker(s)" in result.reason
    assert "ticket 12" in result.reason
    assert "nothing in this repository has touched real chain data" in result.reason
    assert "archival node" in result.reason
    assert "25-28" not in result.reason, (
        "the merged package is on this commit; a refusal still naming the branch it used to live "
        "on is the stale-reason defect this repository keeps closing:\n{}".format(result.reason))
    with pytest.raises(StageNotCompleted):
        result.value


def test_step0_universe_crashes_when_the_windows_are_genuinely_defective(w):
    """A window whose census admits nobody is a measurement that could not be taken.

    Distinct from a *small* universe, which is the status above. Zero admitted accounts leaves
    §6.1's five distributions with no values to be distributions of, so ``measure_window`` raises
    ``EmptyEligibleUniverse``, nothing here catches it, and the stage crashes with the reason
    against a run record that already says what it was about to do.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    inputs = F.step0_universe_inputs()
    inputs["windows"][0] = F.step0_window_admitting_nobody(U.W1)

    result = go(w, "step0.universe", inputs)

    assert result.status == CRASHED
    assert result.error_type == "EmptyEligibleUniverse"
    assert "admitted no accounts at all" in result.reason
    assert w.governance.state == gov.PARAMETERS_FROZEN
    with pytest.raises(StageNotCompleted):
        result.value


def test_step0_universe_refuses_a_calendar_the_design_does_not_register(w):
    """A wiring defect, so it raises before a run record is opened.

    The window key is one of §6.3's four and the calendar is not the one the design registers.
    ``Step0Report`` compares keys and would pass this; only the composition root holds the design's
    own copy of the calendar beside the measured one, so only here can the two be compared.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    moved = replace(U.W1, t0=U.T0Instant(block=U.W1.t0.block + 1_000,
                                         timestamp=U.W1.t0.timestamp + 86_400))

    with pytest.raises(ValueError) as excinfo:
        go(w, "step0.universe", F.step0_universe_inputs(
            windows=[F.step0_window(moved, 3)]))

    assert "the design registers that slot at" in str(excinfo.value)
    assert w.runs.list_runs() == [], (
        "a defect in what assembled the call is not a stage outcome and must not be recorded as one")


def _defective(**overrides):
    """The four windows, with one thing about the wiring made wrong."""
    inputs = F.step0_universe_inputs()
    inputs.update(overrides)
    return inputs


#: Every way the ``step0.universe`` wiring can be defective, and the phrase its refusal must carry.
#: Each is a defect in what *assembled* the call rather than a disappointing measurement, so each
#: raises out of the factory before a run record exists — the split ``pipeline.stages.runner_for``
#: documents, and the reason a mis-wired stage is not recorded as a stage outcome.
DEFECTIVE_WIRINGS = (
    (lambda: _defective(design=None),
     "there is nothing saying which four windows"),
    (lambda: _defective(parameter_freeze_hash="   "),
     "and no parameter_freeze_hash"),
    (lambda: _defective(dataset_snapshot=""),
     "and no dataset_snapshot"),
    (lambda: _defective(windows=["not a Step0WindowInputs"]),
     "windows must hold Step0WindowInputs"),
    (lambda: _defective(windows=[F.step0_window(U.W1, 3), F.step0_window(U.W1, 4)]),
     "both measure window W1_2023H1"),
)


@pytest.mark.parametrize("build,phrase", DEFECTIVE_WIRINGS,
                         ids=["no-design", "no-freeze-hash", "no-snapshot", "wrong-type",
                              "one-window-twice"])
def test_a_defective_step0_wiring_raises_before_a_run_record_is_opened(w, build, phrase):
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    with pytest.raises((TypeError, ValueError)) as excinfo:
        go(w, "step0.universe", build())

    assert phrase in str(excinfo.value)
    assert w.runs.list_runs() == []


def test_a_window_measured_over_no_observations_is_refused_at_wiring_time():
    """Not "a smaller measurement" — §6.1's distributions would have no shape to describe."""
    with pytest.raises(ValueError) as excinfo:
        F.Step0WindowInputs(**dict(U.step0_inputs(
            [U.observation(U.address(1))]), observations=()))

    assert "was given no observations" in str(excinfo.value)


def test_a_window_that_is_not_a_training_window_is_refused_at_wiring_time():
    """The window is the key every other input is checked against, so it is checked first."""
    with pytest.raises(TypeError) as excinfo:
        F.Step0WindowInputs(**dict(U.step0_inputs(
            [U.observation(U.address(1))]), window="W1_2023H1"))

    assert "must be a TrainingWindow" in str(excinfo.value)


def test_step0_universe_refuses_a_snapshot_the_run_record_does_not_pin(w):
    """The report's snapshot and the run record's are one fact, and this is where they meet."""
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    result = go(w, "step0.universe",
                F.step0_universe_inputs(dataset_snapshot="some-other-snapshot"))

    assert result.status == CRASHED
    assert "reproducible from neither" in result.reason


def test_step0_universe_publishes_nothing_over_a_subset_of_the_four_windows(w):
    """Ticket 26 measures all four before any ranking; three of four is a different experiment."""
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    three = [F.step0_window(window, eligible) for window, eligible in F.STEP0_ELIGIBLE[:3]]
    result = go(w, "step0.universe", F.step0_universe_inputs(windows=three))

    assert result.status == CRASHED
    assert "Ticket 26 requires all four" in result.reason
    with pytest.raises(StageNotCompleted):
        result.value


# -- what each live stage actually computed ---------------------------------------


def test_the_known_answer_battery_ran_all_sixteen_frozen_cases(w):
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    value = go(w, "known_answer.battery").value

    assert value["passed"] == 16
    assert value["total"] == 16
    assert value["known_answer_pass_rate"] == D("1")
    assert len(value["fixture_hash"]) == 64


def test_buy_quality_measured_the_hand_computed_minus_a_quarter(w):
    """4,000 TOKEN against $1,500 of reserve: exit 4,000 * 1,500/8,000 = $750 on $1,000."""
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    result = go(w, "pipeline.buy_quality", F.buy_quality_inputs()).value

    assert result.window == 1
    assert result.census.total == 1
    assert len(result.wallets) == 1
    outcome = result.wallets[0]
    assert outcome.wallet == F.TRADER
    assert outcome.quality.value == D("-0.25")


def test_benchmark_match_built_one_set_of_five_primary_controls(w):
    """The wallet at capital 0 draws the wallets at 1..5, in order. Seed from the run record."""
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    match = go(w, "benchmark.match", F.benchmark_match_inputs()).value

    assert match.n_selected == 1
    assert match.n_matched == 1
    assert match.unmatched == ()
    assert match.sets[0].selected == "0xw00"
    assert match.sets[0].primary_controls == ("0xw01", "0xw02", "0xw03", "0xw04", "0xw05")
    assert match.commit == F.COMMIT


def test_benchmark_match_carries_a_failed_balance_rather_than_raising_on_it(w):
    """A ladder universe cannot balance on ``capital_deployed`` — that is a measurement.

    ``balanced`` is False and the whole table is attached. A disappointing measurement is a carried
    status; only a defect in what assembled the call raises.
    """
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    match = go(w, "benchmark.match", F.benchmark_match_inputs()).value

    assert match.balanced is False
    assert match.worst_dimension is not None
    assert match.balance is not None


def test_benchmark_match_derives_its_seed_from_the_run_record(w):
    """Same pinned master seed and commit, same matched set. A caller cannot supply a seed."""
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    first = go(w, "benchmark.match", F.benchmark_match_inputs()).value
    second = go(w, "benchmark.match", F.benchmark_match_inputs()).value

    assert first.seed == second.seed
    assert first.sets[0].primary_controls == second.sets[0].primary_controls

    other = go(w, "benchmark.match", F.benchmark_match_inputs(), commit="b" * 40).value
    assert other.seed != first.seed


def test_follower_adjust_reported_all_five_capital_levels(w):
    w.governance.transition(gov.PARAMETERS_FROZEN, "Research Owner")

    adjustment = go(w, "follower.adjust", F.follower_adjust_inputs()).value

    assert adjustment.complete
    assert adjustment.ladder is not None
    assert adjustment.ladder_refusal is None
    assert [level.capital_level for level in adjustment.levels] == list(F.CAPITAL_LEVELS)
    for level in adjustment.levels:
        assert level.reported, (level.capital_level, level.unreportable_reason)
        assert level.unscorable_wallets == ()


def test_the_two_nulls_cover_both_columns_under_the_pre_registered_purposes(w):
    results = walk(w)

    leader = results["null.leader"].value
    follower = results["null.follower"].value

    assert leader.column == "leader"
    assert follower.column == "follower_adjusted"
    assert leader.windows == F.NULL_WINDOWS == follower.windows
    assert leader.purposes == ("null.leader.window1", "null.leader.window2")
    assert follower.purposes == ("null.follower_adjusted.window1",
                                 "null.follower_adjusted.window2")
    for distribution in leader.distributions + follower.distributions:
        assert len(distribution.runs) == F.NULL_RUNS


def test_neither_null_stage_advances_the_state_alone(w):
    """Both feed ``NULL_COMPLETE``; the first waits for the second. Derived, not listed."""
    results = walk(w)

    leader, follower = results["null.leader"], results["null.follower"]
    assert leader.advanced_to is None
    assert leader.pending == ("null.follower",)
    assert follower.advanced_to == gov.NULL_COMPLETE


def test_calibration_locked_the_smallest_candidate_the_null_could_not_reach(w):
    """The label sits on the signal wallet in about a sixth of relabellings, so the observed
    statistic 0.40 recurs far above the 5% target and 0.41 is the smallest candidate that holds."""
    results = walk(w)

    calibrated = results["threshold.calibrate"].value
    assert calibrated.threshold == D("0.41")
    assert calibrated.at_grid_floor is False
    assert len(calibrated.reports) == 4  # two columns x two windows
    assert results["threshold.calibrate"].advanced_to == gov.THRESHOLD_LOCKED


def test_the_main_test_was_evaluated_at_the_threshold_calibration_locked(w):
    results = walk(w)

    main_test = results["main_test"].value
    assert main_test.threshold == results["threshold.calibrate"].value.threshold
    assert main_test.commit == F.COMMIT
    assert main_test.run_id == results["main_test"].run_id
    assert main_test.evaluation.passed == 0
    assert main_test.capital.feasible is True


def test_the_decision_is_a_stop_and_says_which_threshold_it_failed_against(w):
    """Zero of four windows cleared 0.41. A STOP is a result; the chain produced it end to end."""
    results = walk(w)

    record = results["decision.emit"].value
    assert record.decision.outcome is GateOutcome.STOP
    assert record.decision.windows_passed == 0
    assert record.decision.windows_total == 4
    assert results["decision.emit"].advanced_to == gov.DECISION_EMITTED
    assert any("0.41" in reason for reason in record.decision.reasons)


# -- the run record and the audit log -------------------------------------------


def test_every_stage_left_one_run_record_pinned_to_the_same_experiment(w):
    walk(w)

    records = w.runs.list_runs()
    assert sorted(r.stage for r in records) == sorted(STAGES)
    for record in records:
        assert record.commit == F.COMMIT
        assert record.dataset_snapshot == F.DATASET_SNAPSHOT
        assert record.master_seed == F.MASTER_SEED
        assert record.requester == F.REQUESTER


def test_the_audit_log_records_the_three_refusals_with_their_reasons(w):
    walk(w)

    crashed = [e for e in w.audit.entries() if e.action == "stage.crashed"]
    assert sorted(e.detail["stage"] for e in crashed) == sorted(BLOCKED_STAGES)
    for entry in crashed:
        assert entry.detail["error_type"] == "StageBlocked"
        assert "ticket" in entry.detail["reason"]
    w.audit.verify()
