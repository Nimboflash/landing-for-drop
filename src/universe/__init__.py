"""The candidate universe: measure it, freeze it at T0, rank it, and keep the future out of it.

Tickets 25-28, pre-registration §6.1-§6.5.

    screen_warehouse(...)        potential buys  -> WarehouseScreen        (stage one)
    classify_account(...)        an observation  -> EligibilityVerdict     (stage two)
    build_census(...)            verdicts        -> UniverseCensus
    measure_window(...)          a window        -> Step0Measurement       (ticket 26)
    step0_report(...)            four windows    -> Step0Report
    freeze_universe(...)         admissions      -> FrozenUniverse         (ticket 27)
    for_universe(...)            scores as data  -> RankingInputs
    order.mount_pre_t0(...)      snapshot+univ.  -> PreT0Workspace         (step 1)
    rank_and_select(...)         workspace+scores-> SelectedBasket         (ticket 28)
    seal_selection(...)          workspace+basket-> SelectedWalletArtifact (steps 3-4)
    matching_inputs(...)         universe+basket -> MatchingHandoff        (§6.6's producer)
    look_ahead_audit(...)        all three       -> LookAheadAudit

Note where the :class:`~universe.freeze.FrozenUniverse` goes. It is handed to
:meth:`universe.ordering.ExecutionOrder.mount_pre_t0` and comes back out of
:meth:`universe.ordering.PreT0Workspace.selection_universe`, which is the only route to it in this
package and which runs the ordering gate on every call. That is why ``rank_and_select``'s first
parameter is the workspace: when it was the universe, selection could be re-run at any point in a
run — including with the post-T0 dataset mounted and already read — and the resulting basket was
indistinguishable from a legitimate one.

The package has two sides, and the split is the primary axis of its layout rather than a
secondary concern.

**The selection side** — ``protocol``, ``observation``, ``eligibility``, ``census``, ``step0``,
``freeze``, ``ranking``, ``select``, ``audit`` — may name nothing measured after T0.

**The output side** — ``forward`` — is ticket 27's required post-T0 output and is the only module
that may. The import arrow runs ``forward -> selection side`` and never the reverse; ``forward`` has
in-degree zero inside this package.

Notice what is **absent** from the imports below: there is no line re-exporting anything from
``universe.forward``, and that absence is load-bearing. A re-export would make every importer of
``universe`` an importer of the post-T0 vocabulary in one line — ``from universe import
ForwardLedger, rank_and_select`` would put both halves in one namespace — and it would destroy the
only invariant the cross-package half of ``tests/test_post_t0_barrier.py`` can key on. Consumers of
the output side write ``from universe.forward import ...``, which is visible in a diff and is
allowlisted by name.

``universe`` is a **leaf** builder package. It does not import ``scoring``; §6.5's
``buy_quality_30d`` arrives as data through :class:`~universe.ranking.PreT0Score`, whose coverage
of the frozen membership must be exact. See ``ranking``'s docstring for why the leaf rule made that
input better rather than merely legal.

What this package does not guarantee
------------------------------------

Every stamp it checks is a **claim the caller makes**. Nothing here can see the warehouse query
that produced ``potential_buys``; if that query used ``now()``, or read a continuously backfilled
table, every record built from it is stamped pre-T0 and is not. The structural barrier binds
``src/`` and nothing else — not tests, not notebooks, not the SQL. What it buys is that no module
on the selection path can *name* a post-T0 fact, and that getting a post-T0 number into a
selection-readable type takes a second, differently-named call.
"""

from .audit import (  # noqa: F401
    BARRIER_STATEMENT,
    POST_T0_MODULE,
    AuditCheck,
    LookAheadAudit,
    PostT0ValueFound,
    UndeclaredSelectionInput,
    look_ahead_audit,
)
from .census import (  # noqa: F401
    FAMILY_ORDER,
    UnattributedExclusion,
    UniverseCensus,
    build_census,
)
from .eligibility import (  # noqa: F401
    ADMISSIBLE_ACCOUNT_TYPES,
    DEFAULT_POLICY,
    EXCLUSION_CRITERIA,
    HEURISTIC_MODIFICATIONS,
    INCLUSION_TEST,
    LABEL_SETS,
    RULE_FAMILY,
    RULE_PRECEDENCE,
    SMART_ACCOUNT_EXEMPT_RULES,
    SMART_ACCOUNT_TYPES,
    Admission,
    BoundaryMovement,
    DataCostRefused,
    DataCostReport,
    EligibilityPolicy,
    EligibilityVerdict,
    Exclusion,
    ExclusionFamily,
    ExclusionRule,
    ExclusionStage,
    HeuristicModification,
    WarehouseRow,
    WarehouseScreen,
    boundary_movement,
    classify_account,
    screen_warehouse,
)
from .freeze import (  # noqa: F401
    REMOVAL_REASONS_REFUSED,
    DesignRevision,
    DuplicateMember,
    FrozenUniverse,
    InsufficientCandidateUniverse,
    MatchingHandoff,
    Step0Incomplete,
    UniverseFreezeViolation,
    UniverseMember,
    freeze_universe,
    matching_inputs,
    require_frozen_membership,
    require_step0_complete,
)
from .artifact import (  # noqa: F401
    ArtifactRefused,
    ArtifactSealed,
    PickleRefused,
    SelectedWallet,
    SelectedWalletArtifact,
    artifact_from_snapshot_facts,
    artifact_hash_of,
    require_constructed_row,
    require_sealed_artifact,
    sealed_artifact,
)
from .containment import (  # noqa: F401
    ContainmentMisuse,
    GovernanceSink,
    LookAheadContainment,
    PhaseZeroGovernance,
    RunInvalidated,
    RunState,
    UnrecordedGovernance,
)
from .observation import (  # noqa: F401
    AccountEvidence,
    AccountWindowObservation,
    FieldBlock,
    LabelHit,
    VendorMutability,
    require_pre_t0,
)
from .ordering import (  # noqa: F401
    ExecutionOrder,
    ForwardMount,
    OrderingViolation,
    Phase,
    PreT0Workspace,
    SelectionAfterForwardMount,
    WorkspaceUnmounted,
)
from .provenance import (  # noqa: F401
    PRE_T0_ONE,
    PRE_T0_ZERO,
    ContaminatedDecimal,
    ContaminationDetected,
    Origin,
    PreT0Decimal,
    ProvenanceRefused,
    combine,
    require_pre_t0_value,
)
from .snapshot import (  # noqa: F401
    IsolationStatus,
    PreT0Snapshot,
    SelectionExecutionBlocked,
    SnapshotEvidenceMissing,
    TableVersion,
    pre_t0_snapshot,
    require_verified_snapshot,
    snapshot_evidence_hash,
)
from .protocol import (  # noqa: F401
    ACTIVITY_BAND_BOUNDS,
    MINIMUM_ELIGIBLE_UNIVERSE,
    POTENTIAL_BUY_CEILING,
    POTENTIAL_BUY_FLOOR,
    SECONDS_PER_DAY,
    SELECTED_MAX,
    SELECTED_MIN,
    SELECTION_PERCENT_DENOMINATOR,
    UNIVERSE_SCHEMA_VERSION,
    VALID_BUY_CEILING,
    VALID_BUY_FLOOR,
    WINDOW_ORDER,
    SealedDerivationRefused,
    T0Instant,
    TrainingWindow,
    WindowDesign,
    WindowKey,
    normalise_selection_account,
)
from .ranking import (  # noqa: F401
    RANKING_METRIC,
    SELECTION_INPUT_CLASSES,
    IncompleteRankingInputs,
    PreT0Score,
    RankingInputMismatch,
    RankingInputs,
    UnscorableMember,
    for_universe,
)
from .select import (  # noqa: F401
    ARTIFACT_KIND,
    PRODUCED_BY,
    ActivityBandComposition,
    ClampState,
    SelectedBasket,
    Selection,
    SelectionRefused,
    band_composition,
    basket_artifact,
    rank_and_select,
    seal_selection,
    selected_wallet_count,
)
from .step0 import (  # noqa: F401
    QUANTILES,
    REQUIRED_DISTRIBUTIONS,
    SPEC_DISCREPANCY,
    AccountTypeMix,
    BaseRateComparison,
    BaseRateVerdict,
    Distribution,
    EmptyEligibleUniverse,
    PreRegisteredReplacementRule,
    ReplacementRegistry,
    ReplacementSelector,
    Step0Measurement,
    Step0Report,
    UnregisteredReplacement,
    WindowReplacement,
    WindowStatus,
    distribution,
    measure_window,
    nearest_rank,
    replace_window,
    step0_report,
)

# Deliberately no import from .forward — see the module docstring above. The post-T0 side is
# reached by its own name, ``from universe.forward import ...``, and by nothing shorter.

__all__ = [n for n in dir() if not n.startswith("_")]
