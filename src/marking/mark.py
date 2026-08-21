"""§4.4 Case 2 and Case 3 — valuing a position that is still open at the 30-day horizon.

    Marked Value = min(Remaining x Pool Exit Price, Extractable Given Real Liquidity)

Both terms are computed, and the minimum is taken explicitly rather than assumed, even though the
liquidity bound provably never exceeds the spot mark for a constant-product curve. Writing the
``min()`` out keeps the §4.4 formula legible at the point it is applied, and it is the assertion
that would fail loudly if a future depth model ever produced a bound above spot.
"""

from decimal import Decimal

from contracts import (
    PoolState,
    PoolStatus,
    PositionValue,
    ValueBasis,
    normalise_asset,
    quantize_ratio,
    require_finite,
)

from .liquidity import (
    UnmodelledPoolError,
    effective_reserves,
    exit_value_usd,
    shortfall_vs_spot,
    spot_value_usd,
)
from .pools import (
    MARKING_TOLERANCE,
    MINIMUM_EXIT_VALUE_USD,
    THIN_SHORTFALL_RATIO,
    inactivity_seconds,
    is_inactive,
    require_no_lookahead,
    require_same_quote_asset,
    validate_replacement,
)

ZERO = Decimal("0")


def _fixed(value):
    """Render a Decimal for the evidence trail, exactly, without exponent notation.

    Deliberately **not** quantized. Two reasons, and the second was found the hard way:

    * Marking is not the reporting boundary. These marks feed a log-weighted mean, and the
      evidence has to let §9.2 re-derive the mark to 0.5% — a rounded trail cannot.
    * ``quantize_usd`` raises ``InvalidOperation`` above roughly 10^32, because six decimal
      places on a 33-digit value needs more than the frozen 38 digits of precision. Quantizing
      an audit string must not be able to abort a valuation.
    """
    return format(value, "f")


def _require_raw_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            "{} must be an int; raw token quantities, block numbers and UTC seconds are int by "
            "seam rule, never Decimal and never float. Got {}.".format(
                name, type(value).__name__
            )
        )
    return value


def mark_position(remaining_raw, pool, horizon_block, horizon_ts, quote_usd,
                  replacement_pool=None):
    """Value an open position at the marking horizon, and say how the value was arrived at.

    ``remaining_raw`` is a raw token quantity (int). ``quote_usd`` is **USD per raw unit of the
    quote asset** — no type in ``contracts`` carries token decimals, so a per-whole-token price
    would need metadata the seam does not supply, and inventing a decimals lookup here would put
    an unaudited scaling factor in front of every mark.

    ``horizon_block`` and ``horizon_ts`` are the paired block/timestamp of the horizon. Any pool
    snapshot from after them raises :class:`contracts.LookAheadViolation`.

    **A migration is followed only within one quote asset.** ``quote_usd`` prices one raw unit of
    ``pool.quote``, so exiting at a replacement quoted in another asset would multiply that
    venue's reserves by the wrong asset's price — 3.3e8x high for TOKEN/USDC -> TOKEN/WETH, and
    3.3e8x low for the reverse, which reads as a plausible -100% rug. Such a migration raises
    :class:`~marking.pools.QuoteAssetMismatch` and goes to the reconciliation queue. It is a
    refusal rather than a rejected replacement because rejecting it would satisfy §9.1 condition 3
    and zero a position whose liquidity is demonstrably alive; and it is a refusal rather than a
    second ``replacement_quote_usd`` parameter because that would only move the mispairing out to
    the caller, unchecked and unrecorded. See :func:`~marking.pools.require_same_quote_asset`.

    Returns a :class:`contracts.PositionValue` in every case except three, all of which raise:

    * a pool with no supported depth model — :class:`~marking.liquidity.UnmodelledPoolError`,
      because ``PoolStatus.UNMODELLED`` is not ``PoolStatus.DEAD`` and must not become a zero;
    * an exit that would be priced in an asset ``quote_usd`` is not for — ``QuoteAssetMismatch``;
    * a snapshot from after the horizon — ``LookAheadViolation``.

    A dead pool is not an error. It is a legitimate observed outcome and comes back as
    ``value_usd=0`` / ``DEAD_ZEROED`` / ``PoolStatus.DEAD``, on the full §9.1 conjunction and
    never on one condition alone.
    """
    _require_raw_int(remaining_raw, "remaining_raw")
    _require_raw_int(horizon_block, "horizon_block")
    _require_raw_int(horizon_ts, "horizon_ts")
    if remaining_raw < 0:
        raise ValueError(
            "remaining_raw is {}; a position cannot hold a negative quantity. A short is a "
            "different instrument and this module has no model for one.".format(remaining_raw)
        )
    if not isinstance(pool, PoolState):
        raise TypeError("pool must be a PoolState, got {}".format(type(pool).__name__))

    # require_finite runs through calc(), which refuses float on sight.
    price = require_finite(quote_usd, "quote_usd")
    if price <= 0:
        raise ValueError(
            "quote_usd is {}; a quote asset price must be strictly positive. §4.6 restricts USD "
            "conversion to liquid quote assets precisely so this is always available — a "
            "zero here means the quote price lookup failed and must not be marked as a "
            "worthless position.".format(price)
        )

    require_no_lookahead(pool, horizon_block, horizon_ts, "pool")
    if replacement_pool is not None:
        require_no_lookahead(replacement_pool, horizon_block, horizon_ts, "replacement pool")

    replacement_ok, replacement_evidence = validate_replacement(pool, replacement_pool, horizon_ts)
    primary_inactive = is_inactive(pool, horizon_ts)

    # The exit happens wherever the liquidity actually is. A validated replacement takes over only
    # once the primary has gone quiet — if the primary is still trading, that is where a follower
    # would sell, and switching venues would be picking the friendlier of two prices.
    migrated = replacement_ok and primary_inactive
    venue = replacement_pool if migrated else pool

    # Only when the replacement actually becomes the venue. A pool quoted in another asset that
    # the mark never touches is not a mispricing, and quarantining on its mere existence would
    # drop exactly the multi-pool tokens §9.3 requires be kept. When the primary is still trading
    # the replacement changes nothing: condition 1 has already failed, so it cannot zero anything
    # either.
    if migrated:
        require_same_quote_asset(pool, venue, price)

    # Raises for an unmodellable venue. Deliberately *before* the dead conjunction: otherwise a
    # pool nothing can price would trivially satisfy "exit value below the threshold" and every
    # modelling gap would be reported as a rug.
    asset_reserve, quote_reserve, model = effective_reserves(venue)

    spot_usd = spot_value_usd(remaining_raw, asset_reserve, quote_reserve, price)
    extractable_usd = exit_value_usd(
        remaining_raw, asset_reserve, quote_reserve, venue.fee_bps, price
    )
    marked_usd = min(spot_usd, extractable_usd)
    if marked_usd < 0:
        raise UnmodelledPoolError(
            "pool {} priced a negative exit ({}); PoolStatus.UNMODELLED rather than a zeroed "
            "position.".format(venue.address, marked_usd)
        )

    shortfall = shortfall_vs_spot(spot_usd, marked_usd)

    below_threshold = marked_usd < MINIMUM_EXIT_VALUE_USD
    conditions = (
        ("cond1_no_swap_for_30d", primary_inactive),
        ("cond2_exit_below_minimum", below_threshold),
        ("cond3_no_validated_replacement", not replacement_ok),
    )

    evidence = [
        "venue={}".format(venue.address),
        "venue_is_replacement={}".format("true" if migrated else "false"),
        # The venue's quote asset and the price paid per raw unit of it. Without both, a §9.2
        # re-derivation cannot tell a WETH-quoted venue priced at the WETH price from one priced
        # at the USDC price — the two differ by 1e9 and neither is visible in ``value_usd``.
        "venue_quote={}".format(normalise_asset(venue.quote)),
        "quote_usd_per_raw_quote={}".format(_fixed(price)),
        model,
        "fee_bps={}".format(venue.fee_bps),
        "remaining_raw={}".format(remaining_raw),
        "spot_usd={}".format(_fixed(spot_usd)),
        "extractable_usd={}".format(_fixed(extractable_usd)),
        "shortfall_vs_spot={}".format(_fixed(quantize_ratio(shortfall))),
        "minimum_exit_usd={}".format(_fixed(MINIMUM_EXIT_VALUE_USD)),
        "primary_inactivity_s={}".format(inactivity_seconds(pool, horizon_ts)),
        "horizon_block={}".format(horizon_block),
        "horizon_ts={}".format(horizon_ts),
    ]
    evidence.extend(replacement_evidence)
    evidence.extend("{}={}".format(name, "true" if held else "false") for name, held in conditions)

    if all(held for _name, held in conditions):
        evidence.append(
            "dead_pool=no_swap_for_30d+exit_below_minimum+no_validated_replacement"
        )
        # Zero, not the last observed price. Dune forward-fills for up to 30 days, which renders a
        # rugged token flat instead of -100% and flatters every wallet that bought garbage.
        return PositionValue(
            value_usd=ZERO,
            value_basis=ValueBasis.DEAD_ZEROED,
            executable_quantity=0,
            pool_status=PoolStatus.DEAD,
            evidence=tuple(evidence),
        )

    evidence.append("dead_pool=false")

    if shortfall > MARKING_TOLERANCE:
        basis = ValueBasis.LIQUIDITY_BOUND
    else:
        basis = ValueBasis.POOL_MARKED

    if migrated:
        status = PoolStatus.MIGRATED
    elif primary_inactive:
        status = PoolStatus.QUIET
    elif shortfall > THIN_SHORTFALL_RATIO:
        status = PoolStatus.THIN
    else:
        status = PoolStatus.LIVE

    # The whole remaining quantity clears a constant-product curve — the price is what degrades,
    # not the fill — so the executable quantity is the position itself. It is zero only when the
    # position is zeroed, which is the distinction the field is carrying.
    return PositionValue(
        value_usd=marked_usd,
        value_basis=basis,
        executable_quantity=remaining_raw,
        pool_status=status,
        evidence=tuple(evidence),
    )
