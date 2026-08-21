"""Matched controls, the permutation null, and threshold calibration.

Pre-registration §6.6 · §7.1 · §7.3 · §8 · ticket 33.

Three steps, in the binding §8.4 order:

    build_matched_sets   5 primary + 5 robustness controls per selected wallet, matched on the
                         ten §6.6 dimensions, with a balance table that has to justify itself
    permutation_null     1,000 relabellings *within* each matched set, the full three-condition
                         gate recomputed on each
    calibrate_threshold  the smallest candidate holding the null pass rate at or below 5%

Two lines that this package exists to hold, and both are easy to cross without anything breaking:

**Matching uses pre-T0 information only.** One forward-period feature makes the matched sets fit
the outcome. Nothing crashes, every number looks reasonable, the balance table looks *better* than
it should, and the whole result is void. Every feature record carries the block it was computed at
and is refused at or after T0 — ``>=``, because a feature computed at T0 has already seen T0.

**The null is a permutation, not a resampling.** Relabelling within a matched set preserves the
set's covariate profile exactly, so the null asks whether the label assignment carries information
given groups already balanced on all ten dimensions. A random basket can only ask whether *some*
selection of that size could do as well — the question that failed to catch the June 2026 placebo
result, where activity-matched placebo cohorts returned +216.3% against supposedly skilled
cohorts' +132.3%.

Nothing here derives a seed. ``seed_fn`` is injected, so the §9.6 master-seed derivation stays in
one place and this package imports nothing but ``contracts``.
"""

from .calibration import (  # noqa: F401
    CalibrationReport,
    CandidateRate,
    ThresholdNotCalibrated,
    calibrate_threshold,
    calibrate_threshold_detail,
)
from .features import (  # noqa: F401
    CATEGORICAL_DIMENSION,
    NUMERIC_DIMENSIONS,
    Standardisation,
    WalletFeatures,
    distance,
    mean_of,
    require_pre_t0,
    sqrt_of,
    squared_distance,
    standardise,
    variance_of,
    z_vector,
)
from .matching import (  # noqa: F401
    PRIMARY_CONTROLS,
    ROBUSTNESS_CONTROLS,
    Candidate,
    MatchDetail,
    MatchingInfeasible,
    MatchingResult,
    UnmatchedSelected,
    build_matched_sets,
    build_matched_sets_detail,
    categorical_imbalance,
    effective_sample_size,
    standardised_mean_difference,
)
from .permutation import (  # noqa: F401
    NULL_COLUMNS,
    NULL_PASS_RATE_TARGET,
    NULL_RUNS,
    SIGNIFICANCE_PERCENTILE,
    DegenerateNull,
    NullDistribution,
    NullRun,
    Relabelling,
    empirical_p_value,
    null_purpose,
    percentile_nearest_rank,
    permutation_null,
    permutation_null_detail,
    relabel,
)

__all__ = [n for n in dir() if not n.startswith("_")]
