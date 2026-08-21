"""The arbiter's terminal act: confirm everything, then emit one decision, or refuse.

**No module returns a final gate decision independently.** :func:`emit_decision` will not produce a
:class:`contracts.GateDecision` until every one of the following is confirmed from artifacts:

    module versions present and matching
    ValidationStatus permits the main test              (§9.5)
    dataset snapshot hash matches the freeze manifest   (§9.6)
    the threshold was locked, and locked BEFORE the main test ran   (§8.4)
    golden-set and known-answer fixture hashes match    (§9.2, §9.3, via the manifest)
    the run is not invalidated, and the result is not from a superseded version   (§9.7)

Any mismatch raises :class:`contracts.FreezeViolation` naming the field. There is no warning path,
no "emit with caveats", and no override. A warning that still emits is worse than no check at all,
because it certifies the result and files the doubt somewhere nobody reads.

The outcome rule (§7.4, §7.5):

    >=3 of 4 windows pass BOTH gates, and both columns clear their own null   ->  GO
    the leader side passes but capital feasibility fails at design capital    ->  CONDITIONAL_REVIEW
    anything else                                                            ->  STOP

The middle line is the whole reason there are three states rather than two. A raw positive leader
edge may not conceal an execution-capacity failure — and note that ``GateDecision.__post_init__``
independently refuses ``GO`` alongside ``capital_feasibility_failed``. The rule is therefore
enforced twice, by the seam and by this module, and this module is written to satisfy it rather
than to work around it.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Dict, Optional, Tuple

from contracts import (
    CALCULATION_CONTEXT,
    ContractError,
    FreezeViolation,
    GateDecision,
    GateOutcome,
    PermutationResult,
    ValidationStatus,
    calc,
    divide,
    require_finite,
)

from .artifacts import (
    MISMATCH,
    MISSING,
    PREREQUISITE,
    CheckReport,
    Discrepancy,
    _mapping,
    check_sequence_detail,
    GOVERNANCE_ORDER,
)
from .manifest import (
    RunStatus,
    check_freeze_manifest_detail,
    freeze_manifest_from,
)
from .windows import (
    EXPECTED_WINDOWS,
    FOLLOWER_COLUMN,
    LEADER_COLUMN,
    MIN_PASSING_WINDOWS,
    CapitalFeasibility,
    WindowEvaluation,
)

#: Every module whose version must be pinned and matched before a decision exists. "The main test
#: and the null runs must use the same commit and the same shared functions" (§9.6) — a per-module
#: version is how that is checked without importing any of them.
REQUIRED_MODULES = (
    "attribution",
    "contracts",
    "depth",
    "fifo",
    "marking",
    "matching_null",
    "netting",
    "scoring",
)

#: §7.5. In CONDITIONAL REVIEW one of these must be explicitly decided before Phase 1. The list is
#: closed: "think about it" is not on it, and neither is "proceed anyway".
CONDITIONAL_REVIEW_OPTIONS = (
    "reduce_design_capital",
    "restrict_token_universe",
    "restrict_wallets_by_copy_capacity",
    "reduce_base_position_size",
    "stop",
)

#: §11.3, verbatim. The scope is part of the finding.
NEGATIVE_RESULT_WORDING = (
    "No sufficient persistent and copyable wallet-selection edge was found for the Ethereum "
    "Mainnet target population and capital profile."
)

#: §11.3, explicitly not available. Phase 0 says nothing about Base, Solana, or memecoin markets.
FORBIDDEN_NEGATIVE_FRAMING = "wallet-based copy trading does not work on any blockchain"

#: §11.1 / ticket 43. A GO means the edge existed historically and would have survived transfer to
#: **one** follower at design capital. It does not mean the edge survives the product existing.
GO_SCOPE_WORDING = (
    "A GO means the edge existed historically and would have survived transfer to one follower at "
    "design capital. It does not mean the edge will survive the product existing, and Phase 0 did "
    "not test Berk-Green capital degradation, generalisation beyond Ethereum Mainnet, or whether "
    "the full product would be profitable."
)


@dataclass(frozen=True)
class RunEvidence:
    """Everything the arbiter must confirm, as data it did not compute.

    Nine fields, one per thing that can be wrong. They are separate rather than bundled into a
    single "run report" because the refusal must name the field: "the freeze does not hold" sends a
    reviewer through the whole manifest, while "dataset_snapshot differs" sends them to the query.
    """

    manifest: Dict[str, str]
    observed: Dict[str, str]
    pinned_module_versions: Dict[str, str]
    observed_module_versions: Dict[str, str]
    validation_status: ValidationStatus
    governance_states: Tuple[str, ...]
    locked_threshold: Optional[Decimal]
    run_status: RunStatus
    result_code_version: str

    def __post_init__(self):
        object.__setattr__(self, "governance_states", tuple(self.governance_states))
        if not isinstance(self.validation_status, ValidationStatus):
            raise TypeError(
                "validation_status must be a ValidationStatus, got {}. A bare string would let "
                "an unknown status pass the permits_main_test check by not being "
                "NOT_INDEPENDENT.".format(type(self.validation_status).__name__)
            )
        if not isinstance(self.run_status, RunStatus):
            raise TypeError("run_status must be a RunStatus")
        if self.locked_threshold is not None:
            object.__setattr__(
                self, "locked_threshold",
                require_finite(calc(self.locked_threshold), "locked_threshold"),
            )


def _module_version_discrepancies(pinned, observed):
    found = []
    for module in REQUIRED_MODULES:
        if module not in pinned:
            found.append(Discrepancy(
                kind=MISSING, field="module_versions.{}".format(module),
                detail="has no version pinned by the freeze; §9.6 requires the main test and the "
                       "null runs to use the same shared functions, which is unverifiable without "
                       "a pinned version",
            ))
            continue
        if module not in observed:
            found.append(Discrepancy(
                kind=MISSING, field="module_versions.{}".format(module),
                detail="reported no version for the run; an unreported version is not a matching "
                       "one",
            ))
            continue
        if pinned[module] != observed[module]:
            found.append(Discrepancy(
                kind=MISMATCH, field="module_versions.{}".format(module),
                expected=str(pinned[module]), observed=str(observed[module]),
                detail="differs from the pinned version; the run did not execute the frozen code",
            ))
    for module in sorted(observed):
        if module not in REQUIRED_MODULES:
            found.append(Discrepancy(
                kind=MISMATCH, field="module_versions.{}".format(module),
                observed=str(observed[module]),
                detail="is not a module the gate recognises; an unrecognised module in the run is "
                       "code nobody froze",
            ))
    return tuple(found)


def check_gate_prerequisites(evidence, applied_threshold):
    """Every §9 confirmation, collected. An empty report is the only thing that permits a decision.

    :param evidence: a :class:`RunEvidence`.
    :param applied_threshold: the threshold the windows were actually evaluated against, taken from
        the evaluation rather than from the caller — so that a locked threshold and an applied one
        cannot be asserted to agree by whoever benefits from their agreeing.
    """
    if not isinstance(evidence, RunEvidence):
        raise TypeError("check_gate_prerequisites needs a RunEvidence")

    manifest_check = check_freeze_manifest_detail(evidence.manifest, evidence.observed)
    found = list(manifest_check.discrepancies)

    found.extend(_module_version_discrepancies(
        evidence.pinned_module_versions, evidence.observed_module_versions))

    if not evidence.validation_status.permits_main_test:
        found.append(Discrepancy(
            kind=PREREQUISITE, field="validation_status",
            expected="a status permitting the main test", observed=evidence.validation_status.value,
            detail="§9.5: with no independent review the main test execution is BLOCKED, and the "
                   "block is governance rather than a note in a report",
        ))

    found.extend(check_sequence_detail(
        evidence.governance_states, GOVERNANCE_ORDER, "governance_states").discrepancies)

    if "MAIN_TEST_EXECUTED" not in evidence.governance_states:
        found.append(Discrepancy(
            kind=PREREQUISITE, field="governance_states",
            detail="no MAIN_TEST_EXECUTED stage was recorded; a decision cannot precede the "
                   "single main-test execution it reports",
        ))
    elif "THRESHOLD_LOCKED" not in evidence.governance_states:
        found.append(Discrepancy(
            kind=PREREQUISITE, field="governance_states",
            detail="the main test ran without a recorded THRESHOLD_LOCKED stage; §8.4 locks the "
                   "threshold before the main test, and a threshold chosen after the result is "
                   "not a threshold",
        ))
    else:
        locked_at = evidence.governance_states.index("THRESHOLD_LOCKED")
        ran_at = evidence.governance_states.index("MAIN_TEST_EXECUTED")
        if locked_at > ran_at:
            found.append(Discrepancy(
                kind=PREREQUISITE, field="governance_states",
                detail="THRESHOLD_LOCKED is recorded after MAIN_TEST_EXECUTED; §8.4 step 6 runs "
                       "the main test only once, against an already-locked threshold",
            ))

    if evidence.locked_threshold is None:
        found.append(Discrepancy(
            kind=MISSING, field="locked_threshold",
            detail="no calibrated threshold was locked; §8.3 locks the smallest threshold at "
                   "which the null pass rate is <= 5%, and an unlocked threshold means the gate "
                   "has no calibrated bar to clear",
        ))
    elif evidence.locked_threshold != applied_threshold:
        found.append(Discrepancy(
            kind=MISMATCH, field="threshold",
            expected=str(evidence.locked_threshold), observed=str(applied_threshold),
            detail="the windows were evaluated against a threshold other than the locked one; "
                   "§8.4 step 7 is that after observing the main result, nothing changes",
        ))

    if not evidence.run_status.permits_decision:
        found.append(Discrepancy(
            kind=PREREQUISITE, field="run_status",
            observed="INVALIDATED: {}".format(evidence.run_status.invalidation_reason),
            detail="§9.7: an invalidated run emits no decision. Fix the bug, register a NEW code "
                   "version, re-run the entire validation gate, rebuild the null from scratch, "
                   "and re-run the main test. The previous result is discarded, not patched",
        ))
    elif evidence.result_code_version in evidence.run_status.discarded_versions:
        found.append(Discrepancy(
            kind=PREREQUISITE, field="result_code_version",
            expected=evidence.run_status.code_version, observed=evidence.result_code_version,
            detail="the result was produced by a superseded code version; selectively using the "
                   "old or the new result is prohibited (§9.7)",
        ))
    elif evidence.result_code_version != evidence.run_status.code_version:
        found.append(Discrepancy(
            kind=MISMATCH, field="result_code_version",
            expected=evidence.run_status.code_version, observed=evidence.result_code_version,
            detail="the result was not produced by the authoritative code version",
        ))

    # Read through ``_mapping``, not through ``isinstance(..., dict)``. Both spellings of a
    # manifest are supported everywhere else in this package — ``check_freeze_manifest_detail``
    # above and ``freeze_manifest_from`` below both accept a ``FreezeManifest`` dataclass through
    # ``_mapping`` — so an ``isinstance`` test here made this one confirmation real for a caller
    # who had parsed JSON and absent for a caller who held the seam type. Measured: with the same
    # manifest pinning 3f1c9a… while the run executed 7b2e4d…, the dict form reports "the freeze
    # manifest pins a commit the run did not execute" and the dataclass form reports nothing and
    # emits the decision. ``_mapping`` cannot raise here — the call above has already run it on
    # this same value.
    pinned_commit = _mapping(evidence.manifest, "manifest").get("source_commit")
    if pinned_commit is not None and pinned_commit != evidence.run_status.code_version:
        found.append(Discrepancy(
            kind=MISMATCH, field="source_commit",
            expected=evidence.run_status.code_version, observed=str(pinned_commit),
            detail="the freeze manifest pins a commit the run did not execute",
        ))

    return CheckReport(what="gate_prerequisites", discrepancies=tuple(found))


#: §7.3's quantile, held locally because this package may not import ``phase0``. Same standing as
#: ``windows.FIRST_HOUR_EDGE_SHARE_MAX``: a copy, held equal to ``gate.significance.null_percentile``
#: by a test in ticket 11's ``UNMIGRATED`` list.
NULL_PERCENTILE = Decimal("0.95")


class InconsistentNullSummary(ContractError):
    """A permutation result's declared percentile or p-value disagrees with its own distribution.

    §7.3's two bounds arrive as *fields* — the caller declares them — while ``null_statistics``,
    the distribution both are derived from, arrives in the same object. Until this check existed the
    arbiter read the fields and never the distribution, so a null summary off by one rung produced a
    GO indistinguishable from a real one.

    Unlike the first-hour check in :mod:`gate_validation.windows`, this one *derives*: it recomputes
    both bounds from the raw statistics. That is a second implementation, and it is the point — the
    two conventions are genuine degrees of freedom, both pinned in prose, and an arbiter that
    recomputes them from the documented rule is the only reader that can catch the builder drifting
    off it. What stays in the seam is the gate rule itself (``observed > p95 and p <= 0.05``); what
    is recomputed here are its *inputs*.
    """


def _percentile_nearest_rank(values):
    """``index = ceil(q * n) - 1`` on the ascending sort, at :data:`NULL_PERCENTILE`.

    Nearest-rank, not interpolated, and written out from the rule rather than imported: at
    n = 1,000 the 95th percentile is the 950th value under this convention and something between
    the 950th and 951st under the linear ones, so two implementations that pick differently produce
    two different gates with no way to tell which the pre-registration meant.
    """
    ordered = sorted(calc(v) for v in values)
    if not ordered:
        raise InconsistentNullSummary("the percentile of an empty distribution is undefined")
    with localcontext(CALCULATION_CONTEXT):
        position = +(NULL_PERCENTILE * len(ordered))
    index = int(position)
    if position != index:  # ceil, on a positive Decimal
        index += 1
    return ordered[max(0, index - 1)]


def _empirical_p(observed, values):
    """``(1 + #{null >= observed}) / (1 + n)``.

    The ``+1`` on both sides is the standard permutation correction: without it a distribution no
    run beat reports ``p = 0``, a claim no finite number of runs can support, and one that sails
    through ``p <= 0.05`` on an arithmetic artefact. ``>=`` and not ``>`` — a run that ties the
    observed result is evidence against it.
    """
    ordered = [calc(v) for v in values]
    if not ordered:
        raise InconsistentNullSummary("an empirical p-value needs a distribution")
    return divide(sum(1 for v in ordered if v >= observed) + 1, len(ordered) + 1)


def _require_consistent_null(result):
    """Refuse a permutation result whose declared bounds its own distribution cannot produce."""
    recomputed_percentile = _percentile_nearest_rank(result.null_statistics)
    if recomputed_percentile != result.percentile_95:
        raise InconsistentNullSummary(
            "column {} declares percentile_95 = {}, and the nearest-rank 95th percentile of its "
            "own {} null statistics is {}. §7.3 compares the observed result against that "
            "percentile, so a declared value the distribution does not support decides the gate on "
            "a number nothing produced.".format(
                result.column, result.percentile_95, len(result.null_statistics),
                recomputed_percentile)
        )

    recomputed_p = _empirical_p(result.observed_statistic, result.null_statistics)
    if recomputed_p != result.empirical_p:
        floor = divide(1, len(result.null_statistics) + 1)
        raise InconsistentNullSummary(
            "column {} declares empirical_p = {}, and (1 + #{{null >= {}}}) / (1 + {}) is {}. The "
            "smallest p-value {} runs can report at all is {}, so a declared value below it is not "
            "a stronger result — it is a claim the evidence does not reach.".format(
                result.column, result.empirical_p, result.observed_statistic,
                len(result.null_statistics), recomputed_p, len(result.null_statistics), floor)
        )


def _refuse(report):
    raise FreezeViolation(
        "the gate refuses to emit a decision; {} confirmation(s) failed:\n  {}\n\n"
        "No module returns a final gate decision independently, and there is no path that emits "
        "one with a warning. Every field named above must be resolved and the check re-run.".format(
            len(report.discrepancies), "\n  ".join(report.messages)
        )
    )


@dataclass(frozen=True)
class DecisionRecord:
    """The decision, plus everything a reviewer needs to reach it again without this code.

    Reduced to :attr:`decision` at the seam. The rich record is what an audit reads; the
    :class:`contracts.GateDecision` is what the rest of the system is allowed to consume, and it
    deliberately carries less — a consumer that could see the window-by-window detail could pick
    the windows it liked.
    """

    decision: GateDecision
    manifest_hash: str
    evaluation: WindowEvaluation
    capital: CapitalFeasibility
    leader_null: PermutationResult
    follower_null: PermutationResult
    evidence: RunEvidence
    confirmations: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "confirmations", tuple(self.confirmations))


def _check_null(result, column, field_name):
    if not isinstance(result, PermutationResult):
        raise TypeError(
            "{} must be a contracts.PermutationResult, got {}".format(
                field_name, type(result).__name__)
        )
    if result.column != column:
        return Discrepancy(
            kind=MISMATCH, field=field_name, expected=column, observed=result.column,
            detail="each result is tested against its own null distribution and never borrows the "
                   "other's; §7.3 sets a separate 95th percentile per column",
        )
    return None


def emit_decision_detail(evidence, evaluation, capital_feasibility, leader_null, follower_null):
    """Confirm everything, then decide. Raises rather than returning a qualified answer."""
    if not isinstance(evaluation, WindowEvaluation):
        raise TypeError("evaluation must be a WindowEvaluation from evaluate_windows_detail")
    if not isinstance(capital_feasibility, CapitalFeasibility):
        raise TypeError("capital_feasibility must be a CapitalFeasibility")

    report = check_gate_prerequisites(evidence, evaluation.threshold)
    extra = []

    for result, column, name in (
        (leader_null, LEADER_COLUMN, "leader_null"),
        (follower_null, FOLLOWER_COLUMN, "follower_null"),
    ):
        discrepancy = _check_null(result, column, name)
        if discrepancy is not None:
            extra.append(discrepancy)

    if evaluation.total != EXPECTED_WINDOWS:
        extra.append(Discrepancy(
            kind=MISMATCH, field="windows_total",
            expected=str(EXPECTED_WINDOWS), observed=str(evaluation.total),
            detail="§6.3 pre-registers four walk-forward windows and §7.4 requires at least three "
                   "of them; a different count is a different experiment",
        ))

    if extra:
        report = CheckReport(what=report.what, discrepancies=report.discrepancies + tuple(extra))
    if not report.ok:
        _refuse(report)

    manifest_check = check_freeze_manifest_detail(evidence.manifest, evidence.observed)
    manifest = freeze_manifest_from(evidence.manifest)

    # §7.3 arrives already decided, and until 2026-08-16 the arbiter took it. `percentile_95` and
    # `empirical_p` are fields the caller declares, while `null_statistics` — the distribution both
    # are derived from — sits in the same object unread. Recomputed here and refused on
    # disagreement; see _require_consistent_null.
    _require_consistent_null(leader_null)
    _require_consistent_null(follower_null)

    windows_passed = evaluation.passed
    leader_windows = evaluation.passed_for(LEADER_COLUMN)
    leader_significant = leader_null.significant
    follower_significant = follower_null.significant
    capital_failed = not capital_feasibility.feasible

    leader_side_passes = leader_windows >= MIN_PASSING_WINDOWS and leader_significant
    both_gates_pass = (
        windows_passed >= MIN_PASSING_WINDOWS and leader_significant and follower_significant
    )

    if both_gates_pass and not capital_failed:
        outcome = GateOutcome.GO
    elif leader_side_passes and capital_failed:
        outcome = GateOutcome.CONDITIONAL_REVIEW
    else:
        outcome = GateOutcome.STOP

    reasons = _reasons(
        outcome=outcome,
        evaluation=evaluation,
        windows_passed=windows_passed,
        leader_windows=leader_windows,
        leader_significant=leader_significant,
        follower_significant=follower_significant,
        capital_feasibility=capital_feasibility,
        manifest_hash=manifest_check.manifest_hash,
    )

    decision = GateDecision(
        outcome=outcome,
        windows_passed=windows_passed,
        windows_total=evaluation.total,
        leader_significant=leader_significant,
        follower_significant=follower_significant,
        validation_status=evidence.validation_status,
        manifest=manifest,
        capital_feasibility_failed=capital_failed,
        reasons=reasons,
    )

    return DecisionRecord(
        decision=decision,
        manifest_hash=manifest_check.manifest_hash,
        evaluation=evaluation,
        capital=capital_feasibility,
        leader_null=leader_null,
        follower_null=follower_null,
        evidence=evidence,
        confirmations=(
            "freeze manifest consistent with the run",
            "module versions pinned and matching: {}".format(", ".join(REQUIRED_MODULES)),
            "validation status {} permits the main test".format(evidence.validation_status.value),
            "threshold {} was locked before the main test ran".format(evidence.locked_threshold),
            "run is not invalidated and the result belongs to code version {}".format(
                evidence.run_status.code_version),
        ),
    )


def emit_decision(evidence, evaluation, capital_feasibility, leader_null, follower_null):
    """§7.5. The terminal output, reduced to the seam type."""
    return emit_decision_detail(
        evidence, evaluation, capital_feasibility, leader_null, follower_null
    ).decision


def _reasons(outcome, evaluation, windows_passed, leader_windows, leader_significant,
             follower_significant, capital_feasibility, manifest_hash):
    reasons = [
        "{} of {} windows passed both gates at the locked threshold {}".format(
            windows_passed, evaluation.total, evaluation.threshold),
        "{} of {} windows passed gate 1 (leader skill persistence)".format(
            leader_windows, evaluation.total),
        "leader result {} its own null distribution at the 95th percentile with p <= 0.05".format(
            "cleared" if leader_significant else "did not clear"),
        "follower-adjusted result {} its own null distribution at the 95th percentile with "
        "p <= 0.05".format("cleared" if follower_significant else "did not clear"),
        "bound to freeze manifest {}".format(manifest_hash),
    ]

    if capital_feasibility.feasible:
        reasons.append(
            "follower-adjusted excess buy quality is positive at both design capital levels"
        )
    else:
        reasons.extend(capital_feasibility.reasons)

    reasons.extend(evaluation.failing_reasons)

    if outcome is GateOutcome.GO:
        reasons.append(GO_SCOPE_WORDING)
    elif outcome is GateOutcome.CONDITIONAL_REVIEW:
        reasons.append(
            "§7.5: the gate result is PASSED and capital feasibility FAILED, so one of the "
            "following must be explicitly decided before Phase 1: {}. A positive raw edge may not "
            "conceal an execution-capacity failure.".format(", ".join(CONDITIONAL_REVIEW_OPTIONS))
        )
    else:
        reasons.append(NEGATIVE_RESULT_WORDING)
        reasons.append(
            "Phase 0 says nothing about Base, Arbitrum, Solana, or memecoin markets; the framing "
            "'{}' is explicitly not available.".format(FORBIDDEN_NEGATIVE_FRAMING)
        )

    return tuple(reasons)


def require_conditional_review_decision(choice):
    """§7.5 / ticket 43. The decision that must follow a CONDITIONAL_REVIEW, from the closed list."""
    if choice not in CONDITIONAL_REVIEW_OPTIONS:
        raise FreezeViolation(
            "conditional_review_decision: {!r} is not one of the pre-registered options ({}). The "
            "list is closed so that 'proceed anyway' is unavailable rather than "
            "discouraged.".format(choice, ", ".join(CONDITIONAL_REVIEW_OPTIONS))
        )
    return choice
