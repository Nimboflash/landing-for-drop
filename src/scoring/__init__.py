"""Outcomes into a wallet score, and wallet scores into a window verdict. §4.4 · §7.1 · §10.

Builder lane. Consumes and returns frozen seam types only.

    from scoring import buy_outcome, buy_quality, edge_origin, score_window

    quality = buy_quality([buy_outcome(...), ...], wallet)      # contracts.BuyQuality
    origin  = edge_origin(selected_quality, benchmark_quality)  # where the edge came from
    score   = score_window(window, "leader", advantages, origin)  # contracts.WindowScore

Three things this package refuses to do, each because the obvious alternative is a number nobody
measured:

* it never reports a buy quality for a basket with no buys, no priced volume, or no recorded value
  basis (:class:`UnscorableWallet`);
* it never substitutes zero for a benchmark bucket the benchmark did not trade
  (:class:`BenchmarkBucketMissing`);
* **it never reports a first-hour edge share below the 5-percentage-point floor.** The share becomes
  ``None``, the status becomes ``INDETERMINATE``, and the window fails. ``INDETERMINATE`` is not a
  pass, and returning ``Decimal("0")`` in its place would silently convert an unmeasurable window
  into a passing one — the single most dangerous possible bug in the scoring path.

The §10 mix travels with every score. A result resting 80% on marking is not credible however
positive it looks, and the only way anyone downstream can know is if the realized / marked / dead
shares arrive attached to the number rather than in a separate report.

Every function here is a pure function of its arguments: no network, no file I/O, no clock, no
global state, no unseeded randomness.
"""

from .edge import (  # noqa: F401
    EDGE_ORIGIN_LIMITATIONS,
    FIRST_HOUR_EDGE_SHARE_MAX,
    MIN_TOTAL_POSITIVE_EDGE,
    BenchmarkBucketMissing,
    BucketEdge,
    EdgeOrigin,
    edge_origin,
)
from .quality import (  # noqa: F401
    BucketBreakdown,
    UnscorableWallet,
    WalletScore,
    buy_outcome,
    buy_quality,
    buy_quality_detail,
)
from .weights import (  # noqa: F401
    BUCKET_ORDER,
    ONE,
    ZERO,
    arithmetic_mean,
    median,
    trade_weight,
    weighted_mean,
)
from .window import (  # noqa: F401
    COLUMNS,
    WindowEvaluation,
    evaluate_window,
    score_window,
)

__all__ = [n for n in dir() if not n.startswith("_")]
