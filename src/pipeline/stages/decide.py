"""The two terminal stage runners, and the three stages that cannot honestly run yet.

:func:`phase0.execution.execute_stage` authorises a stage, opens its run record *before* the stage
runs, calls ``runner(context)``, and records ``COMPLETED`` / ``REFUSED`` / ``HELD`` / ``CRASHED``. It
takes the runner as an argument because ``phase0`` is SHARED and must not know what a stage does.
This module supplies five of those runners. It lives in ``pipeline`` because ``pipeline`` is the
composition root — the one builder package permitted to import other builder packages — and because
``tests/test_lane_independence.py`` forbids the ``(SHARED, BUILDER)`` edge these runners would need
if they lived in ``phase0``.

**Factories, not bare runners.** Every public function takes the stage's inputs and returns a
``runner(context)``. The inputs are pinned at wiring time, the closure holds nothing else, and this
module therefore knows nothing about a command line, a registry, or a state directory.

Two stages that run, and what composing them is worth
-----------------------------------------------------

``main_test``      evaluates the four pre-registered windows against the **locked** threshold and
                   assesses §7.2 capital feasibility, once.
``decision.emit``  hands that result, the two nulls and the run evidence to
                   :func:`gate_validation.emit_decision_detail`, which confirms every §9 condition
                   and then decides GO / CONDITIONAL_REVIEW / STOP, or refuses.

``gate_validation`` is SHARED and may not import builder code. These runners pass it typed values —
``contracts.WindowScore``, ``contracts.PermutationResult``, a
:class:`gate_validation.RunEvidence` — and it consumes them as data. Nothing here lets it reach back
into the code it judges, and nothing here reimplements a rule it owns: the §7.1 pass conditions live
on ``contracts.WindowScore.passes``, the §7.2 feasibility rule on
``gate_validation.CapitalFeasibility``, and the §7.4/§7.5 outcome rule in
``gate_validation.decision``. A second copy of any of them in this file would be exactly the
situation the arbiter exists to prevent.

What the composition adds that neither side can add alone is the **link between the two stages**:
:class:`MainTestResult` is produced by the ``main_test`` runner and is the only thing
:func:`decision_emit_runner` accepts. ``gate_validation`` cannot tell a ``WindowEvaluation`` that
came from the main test from one recomputed at a friendlier threshold after the result was visible —
it sees a value either way. This module can, because it is the thing that ran the main test. The
guarantee is only as strong as construction: a caller who builds a :class:`MainTestResult` by hand,
or reaches one through ``object.__new__``, satisfies the same check. What is ruled out is a second
*front door*, not a caller who has decided to go round the back.

Three stages that cannot run, and why they raise
-------------------------------------------------

``golden_set.trace``, ``reconciliation.cross_source`` and ``validation.independent`` have no inputs
in this tree. Their runners raise :class:`StageBlocked`, naming the ticket, what is missing, and
what would clear it, in the style of :class:`phase0.errors.NotReadyError`, which names its unmet
preconditions rather than saying "not ready".

There were four. ``step0.universe`` left this module when ``src/universe/`` landed on ``main``: it
has a real runner in :mod:`pipeline.stages.step0` and refuses only for want of observations, which
is a different claim from "this code is not here". :func:`blocked_stage_runner` and
:class:`Blocker` are still what it refuses *with* — a stage that stops being blocked should keep the
refusal it earned and lose the reason that expired, not swap one mechanism for another.

They raise rather than return, and the distinction is the whole point of the protocol. A
``golden_set.trace`` that returned "0 traces", a ``reconciliation.cross_source`` that returned "0
unexplained differences", or a ``validation.independent`` that returned an empty report would each
be indistinguishable from a *measurement* the moment it was published, and each would read as the
best possible one. ``execute_stage`` records ``CRASHED`` with the reason against a run record that
already exists, so the refusal is in the hash-chained audit log and the stage publishes nothing.

**These three are placeholders to be replaced, not conditions to be relaxed.** Each refuses
unconditionally, so it will keep refusing after its blocker clears; the fix is to write the runner
the stage then deserves and wire that instead — which is exactly what happened to ``step0.universe``
in :mod:`pipeline.stages.step0`. Deleting the refusal without wiring anything gives back a stage
that completes having done nothing, which is worse than the refusal because the refusal is visible.

Two of the three must not be wired to builder code even once they are unblocked, and this is a
constraint no import check can express. ``golden_set.trace`` (ticket 15) records answers computed
"from transactions, event logs, traces, and actual balance changes — never from the builder's code
or intermediate artefacts", and ``validation.independent`` (ticket 36) is the VALIDATOR lane's
separate implementation path. A builder-lane runner that *computed* either would delete the
independence the validation gate's entire worth rests on, while leaving every structural check
green. What may eventually live here is a runner that loads and verifies what the other lane
recorded — never one that derives it.
"""

from dataclasses import dataclass

from gate_validation import (
    CapitalFeasibility,
    RunEvidence,
    WindowEvaluation,
    assess_capital_feasibility,
    emit_decision_detail,
    evaluate_windows_detail,
)

__all__ = [
    "Blocker",
    "StageBlocked",
    "MainTestAlreadyRun",
    "MainTestResult",
    "blocked_stage_runner",
    "golden_set_trace_runner",
    "reconciliation_cross_source_runner",
    "validation_independent_runner",
    "main_test_runner",
    "decision_emit_runner",
]


# -- the wiring check every runner here makes ------------------------------------


def _require_stage(context, expected):
    """The context's stage is the one this runner was built for.

    ``execute_stage`` takes the runner as an opaque callable, so it cannot check that the registry
    mapped the right function to the right key. A crossed wire would file one stage's value under
    another stage's authority — a ``main_test`` value completing ``DECISION_EMITTED``, say — and
    nothing in ``phase0`` could see it. One comparison here closes that, and it costs nothing.

    It checks the wiring, not the inputs: a runner built with the wrong *arguments* under the right
    key passes this and is the integrator's to get right.
    """
    if context.stage != expected:
        raise ValueError(
            "this runner computes stage {!r} and was called with a context for stage {!r}. The "
            "runner and the stage key are married in the registry, and execute_stage takes the "
            "runner as an opaque callable — so a crossed wire would record one stage's value "
            "under another stage's authority with nothing in phase0 able to see "
            "it.".format(expected, context.stage)
        )


# -- blocked stages ---------------------------------------------------------------


@dataclass(frozen=True)
class Blocker:
    """One thing a stage is waiting for, named the way a precondition is named.

    Three fields rather than one message, because a reviewer asks three different questions and a
    single sentence answers whichever one it happened to be written for: *which ticket owns this*,
    *what is actually absent*, and *what would make it present*. The last is the one most often left
    out, and its absence is what turns a blocker into a shrug.
    """

    #: The ticket number that owns the blocker, as it appears in ``docs/tickets/``.
    ticket: str
    #: What is absent, stated as a fact about this tree rather than as a status.
    missing: str
    #: What would clear it. Not "unblock ticket N" — the concrete thing that has to exist.
    unblocked_by: str

    def __post_init__(self):
        for field in ("ticket", "missing", "unblocked_by"):
            value = getattr(self, field)
            if not value or not str(value).strip():
                raise ValueError(
                    "a Blocker must name its {}; a blocker that does not say what is missing or "
                    "what would clear it is the 'not ready' message that phase0.errors."
                    "NotReadyError exists to replace".format(field)
                )

    def __str__(self):
        return "ticket {} — {}\n      unblocked by: {}".format(
            self.ticket, self.missing, self.unblocked_by
        )


class StageBlocked(Exception):
    """A stage was requested whose inputs do not exist in this tree.

    Raised, never returned, and never softened into an empty result. ``execute_stage`` records
    ``CRASHED`` with this message against the run record it opened before calling the runner, so the
    refusal and the conditions it was made under are both in the audit log.

    ``CRASHED`` rather than a governance ``REFUSED`` because governance is not what is wrong here.
    The state machine authorises these stages correctly — they are legal at ``PARAMETERS_FROZEN``.
    What is wrong is that something asked for a measurement whose data does not exist, and that is a
    defect in whatever assembled the call.

    Carries :attr:`blockers` as structured values so a caller can report them without parsing the
    message.
    """

    def __init__(self, stage, blockers, produces, empty_reads_as):
        self.stage = stage
        self.blockers = tuple(blockers)
        self.produces = produces
        self.empty_reads_as = empty_reads_as
        if not self.blockers:
            raise ValueError(
                "StageBlocked must name at least one blocker; 'blocked' with nothing named is a "
                "status rather than a refusal, and cannot be acted on or disputed"
            )
        super().__init__(
            "Stage {!r} cannot run: {} unmet blocker(s).\n  {}\n\n"
            "It would have produced {}. It returns nothing and raises instead, because {!r} is a "
            "measurement and this is the absence of one — and once either is published as this "
            "stage's value, nothing downstream can tell them apart.".format(
                stage,
                len(self.blockers),
                "\n  ".join(str(blocker) for blocker in self.blockers),
                produces,
                empty_reads_as,
            )
        )


def blocked_stage_runner(stage, blockers, produces, empty_reads_as):
    """A runner for a stage that has no inputs: it refuses, and names what it is waiting for.

    :param stage: the stage key this runner is wired under. Checked against the context, so a
        crossed wire names the mismatch instead of refusing under the wrong stage's name.
    :param blockers: one or more :class:`Blocker` values. Empty is refused here, at *wiring* time,
        so a stage wired to say nothing fails before a run record is ever opened for it.
        :class:`StageBlocked` refuses it a second time for anyone who raises it directly.
    :param produces: what the stage would have produced, in a reviewer's words.
    :param empty_reads_as: what an empty or zero return would look like on a dashboard — "0 traces",
        "0 unexplained differences". Quoted back in the refusal so the reason the stage raises is in
        the message rather than in this docstring.
    :returns: ``runner(context)``, which always raises :class:`StageBlocked`.

    It guarantees that the stage publishes no value and that the audit log carries a legible reason.
    It guarantees nothing about whether the blockers listed are still the real ones: they are fixed
    at wiring time and this function cannot detect that one has cleared. That is deliberate — a
    refusal that tested for its own blocker could go quiet on its own, and a stage that starts
    completing because a directory appeared is not a stage anyone wired.
    """
    blockers = tuple(blockers)
    if not blockers:
        raise ValueError(
            "blocked_stage_runner({!r}) was given no blockers. 'Blocked' with nothing named is a "
            "status rather than a refusal: it cannot be acted on, cannot be disputed, and cannot "
            "be checked against the tree later to see whether it is still true.".format(stage)
        )
    for blocker in blockers:
        if not isinstance(blocker, Blocker):
            raise TypeError(
                "blocked_stage_runner({!r}) needs Blocker values, got {}. The three fields are "
                "the point — a free-text reason is where 'unblocked by' goes "
                "missing.".format(stage, type(blocker).__name__)
            )

    def runner(context):
        _require_stage(context, stage)
        raise StageBlocked(stage, blockers, produces, empty_reads_as)

    return runner


def golden_set_trace_runner():
    """``golden_set.trace`` — blocked. Hand-traced expected outputs need an archival node.

    Takes no inputs because there are none to take. See the module docstring for why this runner
    must not later be pointed at builder code: ticket 15 requires the answers to be derived from raw
    chain data only, and a builder-lane derivation of them would leave every structural check green
    while removing the independence the comparison depends on.
    """
    return blocked_stage_runner(
        "golden_set.trace",
        (
            Blocker(
                ticket="03",
                missing=(
                    "no authenticated archival node is provisioned. Three public endpoints were "
                    "checked and each refuses archive and trace requests — publicnode answers "
                    "\"Archive requests require a personal token\", Ankr and llamarpc likewise "
                    "(docs/build-status.md, verified infrastructure gaps)"
                ),
                unblocked_by=(
                    "an approved data budget and working archival RPC credentials, proven by a "
                    "live trace call and recorded in the precondition register"
                ),
            ),
            Blocker(
                ticket="13",
                missing=(
                    "src/groundtruth/ does not exist, so there is no raw-chain reader for a trace "
                    "to be taken with. It was built on 2026-08-16 and removed the same day when "
                    "ticket 02 settled on an AI validator: a reference the validator did not write "
                    "is the sharpest form of the correlated-error problem, not a head start"
                ),
                unblocked_by=(
                    "the validator's own reader, written from raw chain data and the specification "
                    "only. The removed one is at commit 7644955 and consulting it would undo the "
                    "reason it was removed"
                ),
            ),
        ),
        produces="hand-traced expected outputs for every selected golden-set account",
        empty_reads_as="0 traces",
    )


def reconciliation_cross_source_runner():
    """``reconciliation.cross_source`` — blocked. Validation layer 3 has one source, not two.

    Ticket 35's two sources are the normalised vendor feed and **raw chain data**. A second vendor
    is explicitly not a substitute: two normalisation vendors share assumptions and demonstrably
    take opposite conventions on the same events, so agreement between them measures their shared
    convention rather than the truth.
    """
    return blocked_stage_runner(
        "reconciliation.cross_source",
        (
            Blocker(
                ticket="03",
                missing=(
                    "the raw-chain side of the reconciliation is unreachable: receipts, event logs "
                    "and execution traces need an authenticated archival node, and none is "
                    "provisioned"
                ),
                unblocked_by=(
                    "working archival RPC credentials, proven by a live call against receipts, "
                    "logs and traces"
                ),
            ),
            Blocker(
                ticket="12",
                missing=(
                    "the vendor side has never been pulled — nothing in this repository has "
                    "touched real chain data, so there is no normalised source to reconcile"
                ),
                unblocked_by=(
                    "the first data pull, with its coverage gap measured and recorded"
                ),
            ),
            Blocker(
                ticket="13",
                missing=(
                    "src/groundtruth/ does not exist, so nothing can read the raw side "
                    "independently of the decoder being checked — and the vendor side has never "
                    "been pulled either, so both halves of this reconciliation are absent"
                ),
                unblocked_by="the VALIDATOR lane's raw-chain reader, and the first data pull",
            ),
        ),
        produces=(
            "the layer-3 reconciliation of the normalised vendor source against raw chain data, "
            "over the whole golden set and a random sample of at least 200 accounts"
        ),
        empty_reads_as="0 unexplained differences at 100% coverage",
    )


def validation_independent_runner():
    """``validation.independent`` — blocked. There is no Independent Validator and no second path.

    This is the stage whose completion **is** ``VALIDATION_PASSED``, and ``VALIDATION_PASSED`` is
    what §9.5 makes the main test conditional on. So a value invented here would not merely be a
    wrong number: it would unblock the experiment. See the module docstring — even unblocked, this
    stage's value must come from the VALIDATOR lane and not from anything in ``pipeline``.
    """
    return blocked_stage_runner(
        "validation.independent",
        (
            Blocker(
                ticket="02",
                missing=(
                    "no Independent Validator is assigned or recorded in the precondition "
                    "register, so there is nobody whose derivation would be the independent one"
                ),
                unblocked_by=(
                    "a named validator recorded in the register, joining in week 1, bound by the "
                    "constraint that they write none of the pipeline's classification, FIFO or "
                    "valuation logic"
                ),
            ),
            Blocker(
                ticket="36",
                missing=(
                    "src/groundtruth/ does not exist: there is no separate implementation path to "
                    "derive expected outputs from, and therefore no machine-readable validation "
                    "report that could block or permit the main test"
                ),
                unblocked_by=(
                    "the validator's own derivation, with its reasoning recorded before "
                    "comparison, and the correlated-error limitation recorded in the same report"
                ),
            ),
        ),
        produces=(
            "the layer-4 validation report — the Independent Validator's expected outputs, derived "
            "from raw chain data and the specification only, compared against the builder's"
        ),
        empty_reads_as="0 disagreements, VALIDATION_PASSED",
    )


# ``step0.universe`` was the fourth blocked stage and is not one any more. ``src/universe/`` is on
# this commit, so the runner is real and lives in :mod:`pipeline.stages.step0`; what remains of the
# old refusal is one blocker, ticket 12, on the empty-input path. It is not registered here because
# it is no longer a stage that cannot run — it is a stage with nothing yet to measure.


# -- main_test --------------------------------------------------------------------


class MainTestAlreadyRun(Exception):
    """A ``main_test`` runner was asked to run a second time.

    §8.4 step 6 runs the main test once and step 7 is that after observing the result, nothing
    changes. A second invocation is a second chance at the answer whether or not the inputs are the
    same, and the runner cannot tell an honest re-run from a second attempt — only the caller that
    assembled the inputs can. So it refuses and says what the first invocation did.
    """

    def __init__(self, first_run_id, first_completed, second_run_id):
        self.first_run_id = first_run_id
        self.first_completed = first_completed
        self.second_run_id = second_run_id
        super().__init__(
            "the main test has already been run by this runner, under run {}, and was asked to run "
            "again under run {}. The first invocation {}. §8.4 runs the main test once and step 7 "
            "is that after observing the result nothing changes; a second invocation is a second "
            "chance at the answer whether or not the inputs are the same, and this runner cannot "
            "tell the two apart.\n\n"
            "Governance already refuses a second main_test on its own — MAIN_TEST_EXECUTED has "
            "been reached, so execute_stage returns REFUSED and never calls a runner. Reaching "
            "this exception means the runner was invoked outside that path, which is a defect in "
            "whatever assembled the call.\n\n"
            "A main test whose outcome was HELD published nothing and does have to be re-run. "
            "Build a new runner for it, from the inputs the new run pins. Rebuilding is a "
            "deliberate act with a record; letting one closure answer twice is not.".format(
                first_run_id,
                second_run_id,
                "produced a result" if first_completed else "raised before producing one",
            )
        )


@dataclass(frozen=True)
class MainTestResult:
    """The one forward measurement, bound to the run record that produced it.

    Produced only by the runner :func:`main_test_runner` returns, and it is the only thing
    :func:`decision_emit_runner` accepts — that pairing is what stops a ``WindowEvaluation``
    computed *after* the result was visible from reaching the decision engine wearing the main
    test's clothes. The check is an ``isinstance``, so it rules out a second front door and not a
    caller who constructs one of these by hand.

    The threshold is **not** a field. It is read off :attr:`evaluation`, which carried it from the
    evaluation that used it, so there is no second copy of the number to disagree with the first.
    ``gate_validation.check_gate_prerequisites`` compares that same value against the threshold the
    run recorded as locked, and refuses if they differ.
    """

    #: The ``phase0`` run record this measurement was taken under.
    run_id: str
    #: The commit the run was pinned to.
    commit: str
    evaluation: WindowEvaluation
    capital: CapitalFeasibility

    def __post_init__(self):
        if not self.run_id or not str(self.run_id).strip():
            raise ValueError(
                "a main-test result must name the run record it was taken under; a forward number "
                "with no run record is a number nobody can reproduce"
            )
        if not self.commit or not str(self.commit).strip():
            raise ValueError("a main-test result must name the commit it was computed at")
        if not isinstance(self.evaluation, WindowEvaluation):
            raise TypeError(
                "evaluation must be a gate_validation.WindowEvaluation, got {}".format(
                    type(self.evaluation).__name__)
            )
        if not isinstance(self.capital, CapitalFeasibility):
            raise TypeError(
                "capital must be a gate_validation.CapitalFeasibility, got {}. Its constructor is "
                "the boundary that refuses two spellings of one design capital level, and §7.2 "
                "feasibility is the whole of the GO / CONDITIONAL_REVIEW branch.".format(
                    type(self.capital).__name__)
            )

    @property
    def threshold(self):
        """The threshold the windows were actually evaluated against."""
        return self.evaluation.threshold


def main_test_runner(window_scores, excess_by_level, locked_threshold):
    """Wire ``main_test``: evaluate the four windows at the locked threshold, once.

    :param window_scores: ``contracts.WindowScore`` values, both columns, for the four
        pre-registered windows. Materialised into a tuple here, at wiring time, so a generator
        cannot leave the measurement empty. ``gate_validation.evaluate_windows_detail`` owns what is
        admissible: a non-gating column, a repeated ``(window, column)``, and a ``window`` that is
        not an ``int`` are each refused there, and none of those refusals is restated here.
    :param excess_by_level: follower-adjusted excess buy quality per design capital level, as a
        mapping or as ``(level, excess)`` pairs. ``None`` at a level means it could not be measured,
        which §7.2 treats as a failure and not an abstention.

        Handed to ``assess_capital_feasibility`` **unconverted**. A ``dict()`` here would apply its
        own last-one-wins rule to two spellings of one level before ``CapitalFeasibility`` could
        refuse them, and the published §7 outcome would then move between GO and CONDITIONAL_REVIEW
        on the caller's iteration order alone. The refusal reads the caller's own mapping; this
        function must not clean it up first.
    :param locked_threshold: the threshold ``threshold.calibrate`` locked (§8.3). Passed to the
        evaluation as given. It is not re-derived and not adjusted: a threshold chosen after the
        result is not a threshold, and the arbiter refuses a decision whose evaluation used one
        other than the locked value.
    :returns: ``runner(context) -> MainTestResult``.

    **The runner runs at most once, and refuses afterwards.** One invocation, whatever its outcome:
    a first call that raised still spends it, because the runner cannot distinguish a re-run from a
    second attempt at a better answer, and the caller that assembled the inputs can. See
    :class:`MainTestAlreadyRun`, which says what the first invocation did and what to do about a
    held run.

    That latch is a backstop, not the primary control. Governance already refuses a second
    ``main_test`` — ``MAIN_TEST_EXECUTED`` completes the transition the stage is authorised by, so
    ``execute_stage`` returns ``REFUSED`` without calling a runner at all. This closes the path where
    the runner is invoked outside ``execute_stage``. It does **not** stop a caller from building a
    second runner over different inputs and running that; nothing in this module could, and
    governance is what does.
    """
    scores = tuple(window_scores)
    # Empty until the runner is entered. Then it carries the first invocation's run id and whether
    # that invocation got as far as producing a result.
    first = {}

    def runner(context):
        _require_stage(context, "main_test")
        if first:
            raise MainTestAlreadyRun(first["run_id"], first["completed"], context.run_id)
        # Latched before anything is computed, so a runner that raised halfway through has still
        # spent its one invocation. The alternative latches on success and quietly permits a
        # retry — and a retry is where a second set of inputs gets a second chance.
        first["run_id"] = context.run_id
        first["completed"] = False

        evaluation = evaluate_windows_detail(scores, locked_threshold)
        capital = assess_capital_feasibility(excess_by_level)
        result = MainTestResult(
            run_id=context.run_id,
            commit=context.commit,
            evaluation=evaluation,
            capital=capital,
        )
        first["completed"] = True
        return result

    return runner


# -- decision.emit ----------------------------------------------------------------


def decision_emit_runner(main_test, leader_null, follower_null, evidence):
    """Wire ``decision.emit``: confirm everything, then emit one decision, or refuse.

    :param main_test: the :class:`MainTestResult` the ``main_test`` stage produced. Deliberately not
        a ``WindowEvaluation`` and deliberately not the window scores: this stage must not be able
        to evaluate anything itself, because an evaluation performed here would be one performed
        after the main result was visible.
    :param leader_null: the leader column's ``contracts.PermutationResult`` from ``null.leader``.
    :param follower_null: the follower-adjusted column's, from ``null.follower``. Each result is
        tested against its own null and never borrows the other's; ``gate_validation`` checks that
        each names the column it is being used for, and that check is not restated here.
    :param evidence: a :class:`gate_validation.RunEvidence` — the freeze manifest and what the run
        observed, the pinned and observed module versions, the validation status, the governance
        state sequence, the locked threshold, the run status and the result's code version. Built by
        whoever holds those artifacts; this module does not assemble it, because a runner that
        derived the evidence from the run it is reporting on would be certifying itself.
    :returns: ``runner(context) -> gate_validation.DecisionRecord``. ``.decision`` is the
        ``contracts.GateDecision`` the rest of the system is allowed to consume; the record around it
        carries the window-by-window detail an audit reads.

    Everything that decides is ``gate_validation``'s. This runner adds exactly two checks, both of
    which are about *this run* rather than about the result, and neither of which the arbiter is in
    a position to make:

    * the value came from the main test, not from an evaluation assembled beside it — the
      ``isinstance`` on :class:`MainTestResult`, whose limits are stated on that class;
    * the main test and the decision are the same experiment — ``main_test.commit`` against
      ``context.commit``, both taken from ``phase0`` run records and therefore the same identifier
      space by construction. This is a check on the two run records agreeing. It is *not* the §9.6
      manifest check: ``gate_validation`` separately compares the manifest's ``source_commit``
      against the run status's code version, and neither check subsumes the other.

    Type errors are raised at wiring time, so a mis-wired decision stage fails before a run record
    is opened for it rather than as a crash inside one.
    """
    if not isinstance(main_test, MainTestResult):
        raise TypeError(
            "main_test must be the MainTestResult the main_test stage produced, got {}. A bare "
            "WindowEvaluation is refused on purpose: the decision engine cannot tell one that came "
            "from the main test from one recomputed at a friendlier threshold once the result was "
            "visible, and this is the seam that can.".format(type(main_test).__name__)
        )
    if not isinstance(evidence, RunEvidence):
        raise TypeError(
            "evidence must be a gate_validation.RunEvidence, got {}. Its nine fields are separate "
            "so that a refusal names the field that failed; a looser value would have to be "
            "interpreted, and the arbiter interprets nothing.".format(type(evidence).__name__)
        )

    def runner(context):
        _require_stage(context, "decision.emit")
        if main_test.commit != context.commit:
            raise ValueError(
                "the main test ran under run {} at commit {}, and the decision is being emitted "
                "under run {} at commit {}. §9.6 requires the main test and everything bound to it "
                "to be one experiment at one commit; a decision emitted at a different commit "
                "reports a result the code that emitted it did not produce.".format(
                    main_test.run_id, main_test.commit, context.run_id, context.commit
                )
            )
        return emit_decision_detail(
            evidence,
            main_test.evaluation,
            main_test.capital,
            leader_null,
            follower_null,
        )

    return runner
