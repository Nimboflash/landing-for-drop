"""The arbiter — pre-registration §7 (gate conditions) and §9 (validation gate).

This package decides GO / CONDITIONAL_REVIEW / STOP, and it is **shared**: it belongs to neither
the builder lane nor the validator lane, and it may import only :mod:`contracts`.
``tests/test_lane_independence.py`` enforces that structurally.

The asymmetry is the entire design. If this package could import the builder's scoring code in
order to "check" a result, it would inherit that code's bug and then certify it — and no amount of
statistical machinery downstream would notice, because the null distribution is computed by the
same code. A wrong FIFO rule moves the selected basket and all 1,000 permutations identically. The
95th percentile is duly computed, the number looks healthy, and the gate answers a different
question than the one it was asked.

So the arbiter consumes **serialized artifacts as data**: builder outputs, validator
expected-outputs, the freeze manifest, dataset hashes, module-version hashes. It verifies them with
the seam's own primitives (:func:`contracts.canonical_hash`, :func:`contracts.artifact_envelope`,
:func:`contracts.verify_redundant_derived`), and it takes already-parsed dicts as arguments so the
module stays pure — the caller does the file reading.

Three entry points carry the protocol:

    check_freeze_manifest(manifest, observed) -> List[str]     §9.6, one line per disagreement
    evaluate_windows(scores, threshold)       -> (passed, total) §7.4
    emit_decision(...)                        -> GateDecision   §7.5

And one invariant sits underneath all of them: **INDETERMINATE can never satisfy a Boolean pass
condition.** For every set of window scores and every threshold, however absurd, a window whose
edge-origin status is not VALID does not count toward the passing total. That is what stops an
unmeasurable result becoming a green dashboard, and it is stated as a property test rather than as
a comment.
"""

from .artifacts import (  # noqa: F401
    AT_LEAST,
    AT_MOST,
    BOOL,
    BUY_QUALITY_ABSOLUTE_TOLERANCE_PP,
    DECIMAL_STRING,
    DERIVED,
    ENUM_VALUE,
    EXACTLY,
    EXACT_MATCH_FIELDS,
    GOVERNANCE_ORDER,
    INT_STRING,
    IS_TRUE,
    MISMATCH,
    MISSING,
    OUT_OF_ORDER,
    PREREQUISITE,
    RECONCILIATION_AGREEMENT_FLOOR,
    RECONCILIATION_CONDITIONS,
    SCHEMA,
    SCHEMA_KINDS,
    STRING,
    TOLERANCE,
    UNPINNED,
    USD_RELATIVE_TOLERANCE,
    VALIDATION_GATE_CONDITIONS,
    VALIDATION_LAYER_ORDER,
    CheckReport,
    Condition,
    Discrepancy,
    FieldSpec,
    NumericCheck,
    NumericComparison,
    ToleranceSpec,
    check_conditions_detail,
    check_derived_fields,
    check_exact_fields,
    check_exact_fields_detail,
    check_layer_order,
    check_numeric_fields,
    check_numeric_fields_detail,
    check_reconciliation_coverage,
    check_reconciliation_coverage_detail,
    check_schema,
    check_schema_detail,
    check_sequence_detail,
    check_state_sequence,
    check_validation_gate,
    check_validation_gate_detail,
    verify_envelope,
    verify_envelope_detail,
)
from .decision import (  # noqa: F401
    CONDITIONAL_REVIEW_OPTIONS,
    FORBIDDEN_NEGATIVE_FRAMING,
    GO_SCOPE_WORDING,
    NEGATIVE_RESULT_WORDING,
    NULL_PERCENTILE,
    REQUIRED_MODULES,
    DecisionRecord,
    InconsistentNullSummary,
    RunEvidence,
    check_gate_prerequisites,
    emit_decision,
    emit_decision_detail,
    require_conditional_review_decision,
)
from .manifest import (  # noqa: F401
    POLICY_PINS,
    REQUIRED_MANIFEST_FIELDS,
    ManifestCheck,
    RunStatus,
    check_freeze_manifest,
    check_freeze_manifest_detail,
    freeze_manifest_from,
    invalidate,
    register_code_version,
    require_current_version,
)
from .windows import (  # noqa: F401
    DESIGN_CAPITAL_LEVELS,
    EXPECTED_WINDOWS,
    FOLLOWER_COLUMN,
    LEADER_COLUMN,
    MIN_PASSING_WINDOWS,
    REQUIRED_COLUMNS,
    CapitalFeasibility,
    ColumnVerdict,
    ConflictingResults,
    FIRST_HOUR_EDGE_SHARE_MAX,
    InconsistentEdgeOrigin,
    DiagnosticInputRefused,
    WindowEvaluation,
    WindowVerdict,
    assess_capital_feasibility,
    evaluate_windows,
    evaluate_windows_detail,
)

__all__ = [n for n in dir() if not n.startswith("_")]
