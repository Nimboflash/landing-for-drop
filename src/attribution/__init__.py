"""Who a transaction economically belongs to — the step that runs before netting.

Netting groups signed transfers by ``(transaction, owner, token)``. It cannot start until the
owner is known, and an owner recovered wrongly poisons everything downstream of it: the candidate
universe, the ranking, the null distribution. This package answers that one question, and refuses
it when the answer is not in the evidence.

    resolve_attribution(tx_hash, tx_sender, transfers, context) -> Attribution

``tx_sender`` and ``portfolio_owner`` stay separate fields for the length of the pipeline
(amendment A6.1, Allium's shape). Neither may overwrite the other, and the only path from one to
the other is flagged ``TX_SENDER_FALLBACK`` and excluded from the primary metric.
"""

from .context import (  # noqa: F401
    NULL_ADDRESS,
    AttributionContext,
    SafeExecution,
    UserOperation,
    normalise_address,
)
from .coverage import (  # noqa: F401
    AttributionCoverage,
    attribution_coverage,
    attribution_fallback_rate,
)
from .resolve import (  # noqa: F401
    CONFIDENCE,
    AttributionInvariantError,
    require_resolved_attribution,
    resolve_attribution,
)

__all__ = [
    "AttributionContext",
    "AttributionCoverage",
    "AttributionInvariantError",
    "CONFIDENCE",
    "NULL_ADDRESS",
    "SafeExecution",
    "UserOperation",
    "attribution_coverage",
    "attribution_fallback_rate",
    "normalise_address",
    "require_resolved_attribution",
    "resolve_attribution",
]
