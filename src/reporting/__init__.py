"""§10's required outputs, and the only place a number is quantized. Ticket 27 · ticket 34.

Builder lane, and a **leaf**: this package imports the frozen seam and nothing else in the
pipeline. It has no opinion about how a share, a score or a simulation was arrived at — it receives
seam types, aggregates them at full precision, and renders them once.

    report_wallet(quality)                     contracts.BuyQuality  -> WalletReport
    report_basket(pairs)                       (BuyQuality, ValueBasisAmounts) -> BasketReport
    report_window(scores)                      contracts.WindowScore -> WindowReport
    report_capital_level(...)                  §10's per-level block, one of five
    report_capital_ladder(levels)              all five, or a refusal
    report_churn(activities)                   Active / Reduced Activity / Inactive
    diagnostic(...) · profit_ranking(...)      reported, never able to move a gate
    report_run(...)                            everything above, assembled

Three properties carry this package, and each exists because the obvious alternative is a number
nobody measured or a number nobody may act on:

**Quantization happens here and nowhere else.** ``contracts.numeric`` states the policy — *ratios
are never quantized before final aggregation; reporting quantizes exactly once, at the output
boundary* — and :mod:`reporting.boundary` is that boundary. A share rounded before it enters a
weighted mean carries its rounding error into the aggregate, and the error is a function of the
wallet's magnitude, so the bias differs between a basket of small wallets and a basket of large
ones. ``tests/test_quantization_boundary.py`` enforces the rule structurally.

**A diagnostic is a type, not a label.** §10: *"Reporting a diagnostic and then using it to
overturn a gate result is the failure mode this entire document exists to prevent."*
:class:`~reporting.diagnostics.Diagnostic` is not a ``WindowScore``, not a ``BuyQuality``, not a
``Decimal``, and :func:`contracts.calc` refuses it — so no arithmetic anywhere in the pipeline can
consume one, and there is no configuration, flag, or override that promotes it. The comparison
operators raise :class:`~reporting.diagnostics.DiagnosticPromotionRefused` rather than returning
``NotImplemented``, so the refusal names the rule rather than the operator.

**Nothing unmeasurable is reported as zero.** Copy Retention below the addendum §9.3 display
threshold is ``None``. A positive-trade rate over zero executable trades is ``None``. A first-hour
edge share on an ``INDETERMINATE`` window is ``None``. Each of those zeros would read as a measured
result, and §10's entire purpose is that the mix behind a headline number is visible rather than
inferred.

Churn deserves its own line. §10 requires it *independently of the edge result*, so
:func:`report_churn` takes activity counts and nothing else, and :func:`report_run` takes no gate
decision at all. `Reduced Activity` has a pinned boundary — ``REDUCED_ACTIVITY_RATIO =
Decimal("0.25")`` — compared on trade *rates* rather than counts, because the baseline and forward
periods need not be the same length.

Every function here is a pure function of its arguments: no network, no file I/O, no clock, no
global state, no unseeded randomness.
"""

from .aggregate import (  # noqa: F401
    EmptyPopulation,
    mean,
    median,
    rate,
    share,
    total,
)
from .boundary import (  # noqa: F401
    KINDS,
    PERCENTAGE_POINTS,
    RATIO,
    USD,
    UnreportableValue,
    at_output,
    optional_output,
    output_pp,
    output_ratio,
    output_usd,
    scale_for,
)
from .capital import (  # noqa: F401
    CAPITAL_LEVELS,
    COPY_RETENTION_MIN_RAW_QUALITY,
    CapitalLadderReport,
    CapitalLevelReport,
    IncompleteCapitalLadder,
    MismatchedCapitalLevel,
    UnknownCapitalLevel,
    WalletCapitalOutcome,
    level_key,
    report_capital_ladder,
    report_capital_level,
)
from .churn import (  # noqa: F401
    REDUCED_ACTIVITY_RATIO,
    ChurnInputRefused,
    ChurnReport,
    ChurnState,
    WalletActivity,
    report_churn,
)
from .diagnostics import (  # noqa: F401
    ACTIVITY_BAND_BOUNDS,
    DIAGNOSTIC_NAMES,
    DIAGNOSTIC_ONLY,
    MAX_VALID_BUYS,
    MIN_VALID_BUYS,
    ActivityBand,
    Diagnostic,
    DiagnosticPack,
    DiagnosticPromotionRefused,
    DiagnosticRanking,
    DiagnosticRankingRow,
    DiagnosticScope,
    DiagnosticValue,
    UnknownDiagnostic,
    activity_band,
    diagnostic,
    diagnostic_pack,
    profit_ranking,
)
from .run import (  # noqa: F401
    ARTIFACT_KIND,
    GATE_RELEVANCE_STATEMENT,
    NOT_MEASURED,
    DataIntegrity,
    NOT_TESTED,
    PRODUCED_BY,
    IncompleteRunReport,
    RunReport,
    report_run,
    run_artifact,
)
from .wallet import (  # noqa: F401
    BUCKET_ORDER,
    BasketReport,
    InconsistentValueBasis,
    UnreportableBasket,
    ValueBasisAmounts,
    WalletReport,
    report_basket,
    report_wallet,
    value_basis,
)
from .window import (  # noqa: F401
    EXPECTED_WINDOWS,
    GATING_COLUMNS,
    ConflictingWindowResults,
    NonGatingColumnReported,
    WindowColumnReport,
    WindowReport,
    report_window,
)

__all__ = [n for n in dir() if not n.startswith("_")]
