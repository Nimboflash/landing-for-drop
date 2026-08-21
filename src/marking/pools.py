"""Pool lifecycle: the dead conjunction, replacement validation, and the look-ahead guard.

Addendum §9.1 defines death as a conjunction of three conditions, and the conjunction is the
whole point::

    no successful swap for 30 days
    AND executable exit value below the minimum threshold
    AND no validated replacement pool exists

Any single condition on its own zeroes positions that could genuinely be sold. A pool can be
quiet for a month and still be exitable; a token can migrate its liquidity somewhere live. The
opposite error is Dune's: forward-filling a daily price for up to 30 days shows a rugged token as
flat rather than -100%, which systematically flatters exactly the wallets that buy garbage. Both
errors are one-directional and this module has to avoid both, which is why neither a bare time
window nor a bare price staleness check appears anywhere in it.

A migration is also a change of venue, and a venue carries its own quote asset. Following one
across quote assets would price the new pool's reserves with the old pool's price — the two are up
to twelve orders of magnitude apart — so :func:`require_same_quote_asset` refuses instead, and
refuses by raising rather than by rejecting the replacement, because a rejected replacement is how
a live position gets zeroed.
"""

from decimal import Decimal

from contracts import LookAheadViolation, PoolState, QuarantineRequired, normalise_asset
from phase0.parameters import PARAMETERS

from .liquidity import UnmodelledPoolError, effective_reserves

#: §9.1 condition 1. Thirty days of UTC seconds — 2_592_000. Half-open at the top: exactly 30 days
#: of silence satisfies "no successful swap for 30 days".
#:
#: Pinned by ``test_the_inactivity_window_is_exactly_thirty_days`` against the literal 2_592_000,
#: from both sides, at the second. A test that dates its pool ``HORIZON_TS -
#: DEAD_INACTIVITY_SECONDS`` moves with this line and pins nothing about it: widening the window
#: to 90 days used to leave the whole marking suite green, and widening it is the Dune-flattering
#: direction — a rug stays marked at its dust value instead of being zeroed.
#:
#: Read from the ticket-11 frozen set rather than written as ``30 * 24 * 60 * 60``. The arithmetic
#: was the tell: a window expressed as a product is a window somebody can retune one factor of, and
#: the frozen set carries the 2,592,000 seconds the addendum fixed.
DEAD_INACTIVITY_SECONDS = PARAMETERS.value("dead_pool.inactivity_seconds")

#: §9.1 condition 2. The pre-registration and the addendum both say "the minimum threshold"
#: without naming a figure, so it is pinned **here**, in the lane that applies it, and reported
#: as an open item — see :data:`phase0.parameters.NOT_PREREGISTERED`, which names this constant as
#: the one threshold in the dead-pool conjunction that the frozen set deliberately does not carry.
#: One dollar: below it, the exit is worth less than any plausible gas cost, so
#: the position is unsellable in the only sense that matters to a follower.
#:
#: Pinned at the microdollar either side of the threshold — an exit of exactly $1.00 is *not*
#: below it — so neither the figure nor the strictness of the comparison can drift. Before that
#: pin existed the threshold could be raised a thousandfold with every marking test still green,
#: because no case ever landed between $0.000001 and $4,533.
MINIMUM_EXIT_VALUE_USD = Decimal("1.00")

#: §9.2 pins pool-level marking reconciliation at 0.5%. Reused here as the materiality line for
#: the ``value_basis`` label: a shortfall smaller than the tolerance at which two independent
#: computations are required to agree is not a shortfall anyone can act on. This changes the
#: *label* only — the returned value is always the bounded one.
MARKING_TOLERANCE = Decimal("0.005")

#: Reporting label only. A position whose realisable exit is more than a tenth below spot is
#: THIN. Never used to zero anything, and never consulted by the dead conjunction — a status is a
#: description of a pool, not a decision about a position.
THIN_SHORTFALL_RATIO = Decimal("0.10")


class QuoteAssetMismatch(QuarantineRequired):
    """The venue that would price the exit is quoted in a different asset than the price supplied.

    Not an :class:`~marking.liquidity.UnmodelledPoolError`: the pool is perfectly modellable. What
    is missing is a price for *its* quote asset, and that is an input this lane was not handed
    rather than a gap in the depth model.

    Deliberately an exception rather than a rejected replacement. See
    :func:`require_same_quote_asset` for why the difference decides whether a live position is
    zeroed.
    """


def require_no_lookahead(pool, horizon_block, horizon_ts, label):
    """Refuse a pool snapshot taken after the marking horizon.

    Marking a day-30 position against a day-31 reserve reads as an ordinary successful mark and
    invalidates everything downstream of it. The check is cheap and the bug is silent, which is
    the whole argument for having it.
    """
    if pool.last_swap_block > horizon_block:
        raise LookAheadViolation(
            "{} {} last traded at block {}, after the marking horizon block {}. A mark may only "
            "use state visible at the horizon.".format(
                label, pool.address, pool.last_swap_block, horizon_block
            )
        )
    if pool.last_swap_timestamp > horizon_ts:
        raise LookAheadViolation(
            "{} {} last traded at {}, after the marking horizon {}. A mark may only use state "
            "visible at the horizon.".format(
                label, pool.address, pool.last_swap_timestamp, horizon_ts
            )
        )


def inactivity_seconds(pool, horizon_ts):
    """Seconds since the pool's last successful swap, as at the horizon."""
    return horizon_ts - pool.last_swap_timestamp


def is_inactive(pool, horizon_ts):
    """§9.1 condition 1, on its own. Never sufficient to zero a position."""
    return inactivity_seconds(pool, horizon_ts) >= DEAD_INACTIVITY_SECONDS


def validate_replacement(pool, replacement, horizon_ts):
    """§9.2: follow a migration only on liquidity history, real trading, and unchanged identity.

    Returns ``(validated, evidence)``. A rejection is never silent — the reason is carried into
    ``PositionValue.evidence``, because "we zeroed this position" and "we zeroed this position
    after refusing a replacement pool that traded a different token" are audited differently.

    Note that a validated replacement blocks death *even when the replacement is itself thin*.
    That is the conjunction as written: condition 3 asks whether a replacement exists, and the
    replacement's own depth is then priced honestly by the liquidity bound rather than used as a
    second, unwritten death test.
    """
    if replacement is None:
        return False, ("replacement=none",)

    if not isinstance(replacement, PoolState):
        raise TypeError(
            "replacement_pool must be a PoolState, got {}".format(type(replacement).__name__)
        )

    if normalise_asset(replacement.asset) != normalise_asset(pool.asset):
        return False, (
            "replacement_rejected:token_identity_changed:{}!={}".format(
                normalise_asset(replacement.asset), normalise_asset(pool.asset)
            ),
        )

    if replacement.address == pool.address:
        return False, ("replacement_rejected:same_pool:{}".format(replacement.address),)

    if replacement.last_swap_block <= 0:
        return False, (
            "replacement_rejected:no_observed_swap:{}".format(replacement.address),
        )

    if is_inactive(replacement, horizon_ts):
        return False, (
            "replacement_rejected:no_recent_trading:{}:{}s".format(
                replacement.address, inactivity_seconds(replacement, horizon_ts)
            ),
        )

    try:
        effective_reserves(replacement)
    except UnmodelledPoolError:
        # An unmodellable replacement cannot be *validated*, but it also must not be silently
        # treated as absent: the evidence says which of the two happened.
        return False, (
            "replacement_rejected:no_modellable_liquidity:{}".format(replacement.address),
        )

    return True, ("replacement_validated:{}".format(replacement.address),)


def require_same_quote_asset(pool, venue, quote_usd):
    """Refuse to price an exit at a venue quoted in an asset the supplied price is not for.

    ``mark_position`` receives exactly one price: USD per raw unit of ``pool.quote``. Following a
    migration changes the reserves the exit is walked along but not the price it is multiplied by,
    and raw units differ by up to twelve orders of magnitude across the four §4.6 quote assets —
    USDC at 6 decimals is ~1e-6 USD per raw unit, WETH at 18 decimals ~3e-15. A TOKEN/USDC ->
    TOKEN/WETH migration priced that way marks 3.3e8x high; the reverse pairing marks 3.3e8x low
    and lands as an entirely plausible -100% rug. Neither reading is detectably wrong from the
    number alone, which is precisely why it has to be refused at the seam rather than sanity
    checked afterwards.

    **Why a raise and not a rejected replacement.** Returning "no validated replacement" would
    satisfy §9.1 condition 3, and a quiet primary with a dust exit would then be zeroed — a
    -100% manufactured out of a venue change, which is the error this module exists to prevent
    and the more expensive of the two. The position is real, the pool is real, and the only thing
    missing is a price this lane was not handed: that is the reconciliation queue's case exactly.

    **Why not a second price parameter.** ``mark_position(..., replacement_quote_usd=...)`` would
    move the same defect one frame out — the caller would then be the one pairing a price with a
    venue, unchecked — and it would let a mark be produced from a pairing nothing in the record
    can verify. Refusing keeps the guarantee that a returned mark was priced in the asset the
    price was quoted in, and ``PositionValue.evidence`` carries ``venue_quote`` and the price per
    raw unit so a §9.2 re-derivation can confirm it from the record.
    """
    if normalise_asset(venue.quote) != normalise_asset(pool.quote):
        raise QuoteAssetMismatch(
            "the position in pool {} (quoted in {}) would be exited at replacement pool {}, "
            "quoted in {}. quote_usd={} is USD per raw unit of {} and cannot price {}: raw units "
            "differ by up to 1e12 across the §4.6 quote assets, so the mark would be wrong by "
            "orders of magnitude and still look like an ordinary valuation. Quarantined rather "
            "than zeroed — the liquidity is alive, it is the price that is missing.".format(
                pool.address, normalise_asset(pool.quote), venue.address,
                normalise_asset(venue.quote), quote_usd, normalise_asset(pool.quote),
                normalise_asset(venue.quote),
            )
        )
