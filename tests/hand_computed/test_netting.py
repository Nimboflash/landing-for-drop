"""Worked netting examples whose answers were computed by hand before the code existed.

§9.3 discipline: for deterministic logic — net balance change, failed-transaction exclusion,
circular arbitrage — the output must equal the pre-determined answer *exactly*. No case here is
waivable as an edge case, and every expected number below is arithmetic written out in the
comment above it rather than a value copied back from a test run.

Price book convention: ``usd per raw unit``. USDC/USDT have 6 decimals at $1, so one raw unit is
$0.000001. WETH has 18 decimals at an assumed $3,000, so one raw unit is $3e-15. These are exact
Decimals; nothing here is a float.
"""

from decimal import Decimal, localcontext

import pytest

from contracts import (
    AccountType,
    Attribution,
    AttributionMethod,
    ClassificationStatus,
    NATIVE_ETH,
    QuarantineRequired,
    Transaction,
    Transfer,
    USDC,
    USDT,
    WETH,
    divide,
    to_canonical_json,
)
from netting import net_transaction, residual_tolerance_usd, transaction_notional_usd

# -- fixtures shared by every case ----------------------------------------------

OWNER = "0x1111111111111111111111111111111111111111"
POOL_A = "0x2222222222222222222222222222222222222222"
POOL_B = "0x3333333333333333333333333333333333333333"
SEARCHER = "0x4444444444444444444444444444444444444444"
VICTIM = "0x5555555555555555555555555555555555555555"

PEPE = "0x6982508145454ce325ddbe47a25d4ec3d2311933"   # 18 decimals, long-tail: no USD price
SHIB = "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce"   # 18 decimals, long-tail
WSOL = "0xd31a59c85ae9d8edefec411d448f90841571b89c"   # 9 decimals, long-tail

#: USD per raw unit. Only quote assets appear — §4.6 permits a USD price for nothing else, and
#: netting never asks for one, which is what keeps a long-tail oracle out of the metric.
PRICES = {
    USDC: Decimal("0.000001"),
    USDT: Decimal("0.000001"),
    WETH: Decimal("0.000000000000003"),  # $3,000 / 1e18
}

ONE_USDC = 1_000_000
ONE_TOKEN = 10 ** 18


def attribution(owner=OWNER, method=AttributionMethod.DIRECT_EOA,
                account_type=AccountType.EOA, tx_hash="0xtx"):
    return Attribution(
        tx_hash=tx_hash,
        tx_sender=owner if owner else "0x0",
        portfolio_owner=owner,
        account_type=account_type,
        method=method,
        confidence=Decimal("1"),
        evidence=("hand-computed fixture",),
    )


def transfer(token, from_addr, to_addr, raw, log_index, is_fee=False):
    return Transfer(token=token, from_addr=from_addr, to_addr=to_addr,
                    raw_amount=raw, log_index=log_index, is_fee=is_fee)


def transaction(transfers, success=True, attr=None, tx_hash="0xtx",
                block_number=18_000_000, timestamp=1_700_000_000):
    return Transaction(
        tx_hash=tx_hash,
        block_number=block_number,
        timestamp=timestamp,
        success=success,
        attribution=attr if attr is not None else attribution(tx_hash=tx_hash),
        transfers=tuple(transfers),
    )


# -- the tolerance itself -------------------------------------------------------


def test_tolerance_is_the_floor_on_small_notionals():
    # Addendum §8: max($0.01, 0.01% of notional). 0.01% of $50 is $0.005, below the floor.
    assert residual_tolerance_usd(Decimal("50")) == Decimal("0.01")


def test_tolerance_is_proportional_on_large_notionals():
    # 0.01% of $956.049 = $0.0956049, above the $0.01 floor.
    assert residual_tolerance_usd(Decimal("956.049")) == Decimal("0.0956049")


def test_tolerance_crossover_is_at_one_hundred_dollars():
    # 0.01% of $100 is exactly $0.01 — the two arms meet here.
    assert residual_tolerance_usd(Decimal("100")) == Decimal("0.01")
    assert residual_tolerance_usd(Decimal("100.01")) == Decimal("0.010001")


def test_tolerance_refuses_float():
    with pytest.raises(TypeError):
        residual_tolerance_usd(956.049)


# -- A. the simple buy ----------------------------------------------------------


def test_simple_buy():
    """1,000 USDC out, 500 PEPE in. One asset leg, one quote leg, quote negative → BUY."""
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
    ])
    result = net_transaction(tx, PRICES)

    assert result.status is ClassificationStatus.VALID_BUY
    assert result.sold_asset == USDC
    assert result.sold_raw_amount == 1_000_000_000        # raw units, exact, never rounded
    assert result.bought_asset == PEPE
    assert result.bought_raw_amount == 500 * ONE_TOKEN
    assert result.quote_asset == USDC
    # 1_000_000_000 raw x $0.000001 = $1,000.000000 exactly
    assert result.quote_usd == Decimal("1000.000000")
    assert result.residuals == ()
    assert result.portfolio_owner == OWNER
    assert result.block_number == 18_000_000
    assert result.timestamp == 1_700_000_000
    # §4.4 aggregation reads the asset side; the property restates the leg fields, not a rule.
    assert result.asset == PEPE
    assert result.asset_raw_amount == 500 * ONE_TOKEN


def test_simple_sell():
    """5,000 SHIB out, 1,500 USDC in. Quote leg positive → SELL."""
    tx = transaction([
        transfer(SHIB, OWNER, POOL_A, 5000 * ONE_TOKEN, 0),
        transfer(USDC, POOL_A, OWNER, 1500 * ONE_USDC, 1),
    ])
    result = net_transaction(tx, PRICES)

    assert result.status is ClassificationStatus.VALID_SELL
    assert result.sold_asset == SHIB
    assert result.sold_raw_amount == 5000 * ONE_TOKEN
    assert result.bought_asset == USDC
    assert result.bought_raw_amount == 1_500_000_000
    assert result.quote_asset == USDC
    assert result.quote_usd == Decimal("1500.000000")
    assert result.asset == SHIB


# -- B. the multi-hop route, and the phantom it must not emit --------------------


def test_multi_hop_route_emits_no_phantom_weth_buy():
    """USDC -> WETH -> PEPE.

    Reading per-hop rows here yields a "bought WETH" event that never represented intent. Netting
    must cancel the WETH leg to exactly zero and emit one buy of PEPE.

        USDC:  -956_000_000                         = -$956.000000
        WETH:  +300_000_000_000_000_000
               -300_000_000_000_000_000             =  0 raw exactly
        PEPE:  +12_000 x 1e18                       =  unpriceable, survives

    notional = largest one-way flow among priceable tokens
             = max(USDC 956_000_000 -> $956.000000, WETH 3e17 -> $900.000000)
             = $956.000000
    tolerance = max($0.01, 0.0001 x 956.000000) = $0.0956
    """
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 956 * ONE_USDC, 0),
        transfer(WETH, POOL_A, OWNER, 300_000_000_000_000_000, 1),
        transfer(WETH, OWNER, POOL_B, 300_000_000_000_000_000, 2),
        transfer(PEPE, POOL_B, OWNER, 12_000 * ONE_TOKEN, 3),
    ])
    assert transaction_notional_usd(tx, PRICES) == Decimal("956.000000")
    assert residual_tolerance_usd(Decimal("956.000000")) == Decimal("0.0956")

    result = net_transaction(tx, PRICES)

    assert result.status is ClassificationStatus.VALID_BUY
    assert result.bought_asset == PEPE
    assert result.bought_asset != WETH, "the phantom intermediate buy §4.2 exists to prevent"
    assert result.sold_asset == USDC
    assert result.sold_raw_amount == 956_000_000
    assert result.quote_usd == Decimal("956.000000")

    # The intermediate is *recorded as cancelled*, not silently absent: an unexplained
    # disappearance and a netted-to-zero intermediate are different facts.
    assert len(result.residuals) == 1
    weth_residual = result.residuals[0]
    assert weth_residual.token == WETH
    assert weth_residual.raw == 0
    assert weth_residual.usd == Decimal("0")


def test_split_route_resolves_to_one_intent():
    """The same $956 split across two pools and three transfers, plus a partial WETH hop.

    Route shape must not change the answer — a first-hop/last-hop heuristic would see two buys.
    """
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 500 * ONE_USDC, 0),
        transfer(USDC, OWNER, POOL_B, 456 * ONE_USDC, 1),
        transfer(PEPE, POOL_A, OWNER, 6_000 * ONE_TOKEN, 2),
        transfer(PEPE, POOL_B, OWNER, 6_000 * ONE_TOKEN, 3),
    ])
    result = net_transaction(tx, PRICES)

    assert result.status is ClassificationStatus.VALID_BUY
    assert result.sold_raw_amount == 956_000_000
    assert result.bought_raw_amount == 12_000 * ONE_TOKEN
    assert result.quote_usd == Decimal("956.000000")


# -- C. circular arbitrage ------------------------------------------------------


def test_circular_arbitrage_produces_no_position():
    """$956 USDC -> SOL -> USDC for $0.049.

        USDC:  -956_000_000 + 956_049_000 = +49_000 raw = +$0.049000
        WSOL:  +X then -X                 = 0 raw exactly

    notional = largest one-way USDC flow = 956_049_000 raw = $956.049000
    tolerance = max($0.01, 0.0001 x 956.049) = $0.0956049
    $0.049 <= $0.0956049 → negligible → every leg drops out → CIRCULAR_ARBITRAGE.

    Per-leg summing would book ~$1,912 of user volume here (both directions of a round trip) and
    make an arbitrage bot look like a prolific profitable trader.
    """
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 956_000_000, 0),
        transfer(WSOL, POOL_A, OWNER, 4_780_000_000, 1),
        transfer(WSOL, OWNER, POOL_B, 4_780_000_000, 2),
        transfer(USDC, POOL_B, OWNER, 956_049_000, 3),
    ])
    assert transaction_notional_usd(tx, PRICES) == Decimal("956.049000")

    result = net_transaction(tx, PRICES)

    assert result.status is ClassificationStatus.CIRCULAR_ARBITRAGE
    assert result.status.is_trade is False
    assert result.sold_asset is None and result.bought_asset is None
    assert result.reason is not None
    # Volume stays visible so the excluded phantom can be reported rather than vanishing.
    assert result.quote_usd == Decimal("956.049000")
    residual_by_token = {d.token: d for d in result.residuals}
    assert residual_by_token[USDC].raw == 49_000
    assert residual_by_token[USDC].usd == Decimal("0.049000")
    assert residual_by_token[WSOL].raw == 0


def test_same_token_round_trip_is_circular_arbitrage():
    """Out and back in the same token, netting to exactly zero, is still a round trip."""
    tx = transaction([
        transfer(WETH, OWNER, POOL_A, ONE_TOKEN, 0),
        transfer(WETH, POOL_A, OWNER, ONE_TOKEN, 1),
    ])
    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.CIRCULAR_ARBITRAGE


# -- D. residual above tolerance ------------------------------------------------


def test_round_trip_above_tolerance_goes_to_the_reconciliation_queue():
    """The same shape as the arb, but $50 of profit on $1,006.

        USDC: -956_000_000 + 1_006_000_000 = +50_000_000 raw = +$50.000000
        notional  = $1,006.000000
        tolerance = max($0.01, $0.10060) = $0.10060
        $50 > $0.1006 → one surviving leg with no counterparty → ABOVE_TOLERANCE_RESIDUAL
    """
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 956_000_000, 0),
        transfer(WSOL, POOL_A, OWNER, 4_780_000_000, 1),
        transfer(WSOL, OWNER, POOL_B, 4_780_000_000, 2),
        transfer(USDC, POOL_B, OWNER, 1_006_000_000, 3),
    ])
    assert residual_tolerance_usd(Decimal("1006.000000")) == Decimal("0.1006")

    result = net_transaction(tx, PRICES)

    assert result.status is ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL
    assert result.status.is_trade is False
    residual_by_token = {d.token: d for d in result.residuals}
    assert residual_by_token[USDC].raw == 50_000_000
    assert residual_by_token[USDC].usd == Decimal("50.000000")
    assert "reconciliation" in result.reason


def test_residual_exactly_at_tolerance_is_negligible():
    """The comparison is ``<=``. Dust of exactly $0.10 against a $1,000 notional drops out.

    notional = $1,000.000000 → tolerance = $0.100000 → the 100_000-raw USDT leg is negligible,
    leaving one asset leg and one quote leg.
    """
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
        transfer(USDT, POOL_A, OWNER, 100_000, 2),  # $0.100000 exactly
    ])
    result = net_transaction(tx, PRICES)

    assert result.status is ClassificationStatus.VALID_BUY
    assert result.bought_asset == PEPE
    assert [(d.token, d.raw) for d in result.residuals] == [(USDT, 100_000)]


def test_residual_one_raw_unit_above_tolerance_survives_as_a_third_leg():
    """$0.100001 against the same $1,000 notional. One raw unit decides it.

    A global two-decimal USD quantization would have rounded both this case and the previous one
    to $0.10 and lost the distinction entirely — which is why USD is carried at full precision.
    """
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
        transfer(USDT, POOL_A, OWNER, 100_001, 2),  # $0.100001
    ])
    result = net_transaction(tx, PRICES)

    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    assert len(result.residuals) == 3


def test_small_trade_uses_the_dollar_floor():
    """$50 notional → 0.01% is $0.005, so the $0.01 floor governs.

    $0.008 of dust is negligible; $0.012 is not.
    """
    negligible = transaction([
        transfer(USDC, OWNER, POOL_A, 50 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, ONE_TOKEN, 1),
        transfer(USDT, POOL_A, OWNER, 8_000, 2),   # $0.008
    ])
    assert net_transaction(negligible, PRICES).status is ClassificationStatus.VALID_BUY

    surviving = transaction([
        transfer(USDC, OWNER, POOL_A, 50 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, ONE_TOKEN, 1),
        transfer(USDT, POOL_A, OWNER, 12_000, 2),  # $0.012
    ])
    assert net_transaction(surviving, PRICES).status is ClassificationStatus.NO_CLEAR_ENDPOINT


# -- E. ETH and WETH are one asset ----------------------------------------------


def test_native_eth_and_weth_collapse_to_one_leg():
    """1 ETH out, 0.4 WETH refunded, 5,000 PEPE in.

        WETH: -1e18 + 4e17 = -6e17 raw → -$1,800.000000 at $3,000/ETH
        notional = what the endpoint left behind = $1,800.000000
        tolerance = max($0.01, $0.18) = $0.18

    The 0.4 ETH refund is not part of what was traded, so it is not part of the size either: the
    notional and ``quote_usd`` are the same $1,800.000000, which is what the trade cost. Sizing
    this at the 1e18 raw that went out would say a transaction is as large as its largest gross
    flow, and that is the rule a refunded order abuses.

    Collapsed, that is one quote leg and one asset leg → BUY. Left uncollapsed it would be three
    legs — ETH out, WETH in, PEPE in — and route endpoints would appear as two different assets.
    """
    tx = transaction([
        transfer(NATIVE_ETH, OWNER, POOL_A, ONE_TOKEN, 0),
        transfer(WETH, POOL_A, OWNER, 400_000_000_000_000_000, 1),
        transfer(PEPE, POOL_A, OWNER, 5_000 * ONE_TOKEN, 2),
    ])
    assert transaction_notional_usd(tx, PRICES) == Decimal("1800.000000")

    result = net_transaction(tx, PRICES)

    assert result.status is ClassificationStatus.VALID_BUY
    assert result.sold_asset == WETH
    assert result.sold_raw_amount == 600_000_000_000_000_000
    assert result.quote_usd == Decimal("1800.000000")
    assert result.residuals == ()


def test_uncollapsed_eth_would_split_one_endpoint_into_two():
    """The counterfactual, run with a stand-in address so the collapse cannot apply.

    Three legs instead of two, and the buy disappears. This is what skipping normalisation costs.
    """
    fake_eth = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    tx = transaction([
        transfer(fake_eth, OWNER, POOL_A, ONE_TOKEN, 0),
        transfer(WETH, POOL_A, OWNER, 400_000_000_000_000_000, 1),
        transfer(PEPE, POOL_A, OWNER, 5_000 * ONE_TOKEN, 2),
    ])
    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT


def test_an_uncollapsed_native_eth_transfer_is_refused():
    """Defence in depth for the assertion §4.2 requires.

    ``Transfer`` collapses the sentinel on construction, so reaching netting with a raw
    ``NATIVE_ETH`` token means the seam was bypassed. Netting refuses rather than netting ETH and
    WETH as two assets.
    """
    bad = transfer(WETH, OWNER, POOL_A, ONE_TOKEN, 0)
    object.__setattr__(bad, "token", NATIVE_ETH)
    tx = transaction([bad, transfer(PEPE, POOL_A, OWNER, ONE_TOKEN, 1)])

    with pytest.raises(QuarantineRequired) as excinfo:
        net_transaction(tx, PRICES)
    assert "ETH" in str(excinfo.value)


# -- F. MEV bundles and multicalls ----------------------------------------------


def test_unrelated_bundle_transfers_do_not_corrupt_the_sum():
    """The owner's buy, sandwiched by a searcher's trades in the same transaction.

    The result must be byte-identical to the same buy alone.
    """
    clean = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
    ])
    bundled = transaction([
        transfer(WETH, SEARCHER, POOL_A, 40 * ONE_TOKEN, 0),        # front-run
        transfer(PEPE, POOL_A, SEARCHER, 900_000 * ONE_TOKEN, 1),
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 2),          # the owner's trade
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 3),
        transfer(PEPE, SEARCHER, POOL_A, 900_000 * ONE_TOKEN, 4),   # back-run
        transfer(WETH, POOL_A, SEARCHER, 41 * ONE_TOKEN, 5),
        transfer(USDT, VICTIM, POOL_B, 5_000 * ONE_USDC, 6),        # an unrelated multicall leg
    ])

    assert to_canonical_json(net_transaction(bundled, PRICES)) == \
        to_canonical_json(net_transaction(clean, PRICES))


def test_skipping_the_owner_filter_is_shown_to_corrupt_the_result():
    """The same bundle, netted without the owner filter, to show what the filter buys.

    The naive sum below is what a per-transaction group-by that forgets the owner produces: six
    non-zero token legs of someone else's money mixed into the owner's intent.
    """
    bundled_transfers = [
        transfer(WETH, SEARCHER, POOL_A, 40 * ONE_TOKEN, 0),
        transfer(PEPE, POOL_A, SEARCHER, 900_000 * ONE_TOKEN, 1),
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 2),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 3),
        transfer(PEPE, SEARCHER, POOL_A, 900_000 * ONE_TOKEN, 4),
        transfer(WETH, POOL_A, SEARCHER, 41 * ONE_TOKEN, 5),
        transfer(USDT, VICTIM, POOL_B, 5_000 * ONE_USDC, 6),
    ]
    naive = {}
    for t in bundled_transfers:  # every transfer counted, from whoever to whoever
        naive[t.token] = naive.get(t.token, 0) + t.raw_amount

    assert len(naive) == 4, "the unfiltered sum sees four tokens, not the owner's two"

    result = net_transaction(transaction(bundled_transfers), PRICES)
    assert result.status is ClassificationStatus.VALID_BUY
    assert result.sold_raw_amount == 1_000_000_000
    assert result.bought_raw_amount == 500 * ONE_TOKEN


# -- G. fees and referrals ------------------------------------------------------


def test_fee_transfers_are_not_endpoints_and_do_not_enter_the_cost():
    """A 2.5 USDC referral fee sits alongside a 1,000 USDC buy.

    The endpoint is 1,000 USDC, not 1,002.5: §4.2 requires fee and referral transfers to be kept
    out of endpoint detection.
    """
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(USDC, OWNER, SEARCHER, 2_500_000, 1, is_fee=True),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 2),
    ])
    result = net_transaction(tx, PRICES)

    assert result.status is ClassificationStatus.VALID_BUY
    assert result.sold_raw_amount == 1_000_000_000
    assert result.quote_usd == Decimal("1000.000000")
    assert result.residuals == ()


def test_a_transaction_of_nothing_but_fees_is_not_a_trade():
    tx = transaction([
        transfer(USDC, OWNER, SEARCHER, 2_500_000, 0, is_fee=True),
    ])
    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    assert result.reason is not None


# -- H. failed transactions -----------------------------------------------------


def test_failed_transaction_is_never_netted():
    """§4.1 requires ``meta.err == null``. A reverted transaction moved nothing."""
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
    ], success=False)
    result = net_transaction(tx, PRICES)

    assert result.status is ClassificationStatus.FAILED_TRANSACTION
    assert result.residuals == ()
    assert result.quote_usd is None
    assert result.reason is not None
    assert result.block_number == 18_000_000  # still locatable in the coverage report


# -- I. attribution -------------------------------------------------------------


def test_tx_sender_fallback_attribution_is_unsupported_not_a_trade():
    """Addendum §8: uncertain owner attribution is excluded from the primary metric.

    ``coalesce(taker, tx_from)`` is exactly this case, and silently attributing the trade to the
    solver is how phantom mega-wallets get made.
    """
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
    ], attr=attribution(method=AttributionMethod.TX_SENDER_FALLBACK))
    result = net_transaction(tx, PRICES)

    assert result.status is ClassificationStatus.UNSUPPORTED
    assert "attribution" in result.reason


def test_unresolved_attribution_is_unsupported():
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
    ], attr=attribution(owner=None, method=AttributionMethod.UNRESOLVED,
                        account_type=AccountType.UNKNOWN))
    result = net_transaction(tx, PRICES)

    assert result.status is ClassificationStatus.UNSUPPORTED
    assert result.portfolio_owner is None


def test_infrastructure_account_is_unsupported():
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
    ], attr=attribution(account_type=AccountType.INFRASTRUCTURE,
                        method=AttributionMethod.ROUTER_RECIPIENT))
    assert net_transaction(tx, PRICES).status is ClassificationStatus.UNSUPPORTED


def test_a_failed_transaction_with_bad_attribution_is_reported_as_failed():
    """Ordering is fixed and enforced: the success filter runs first (ticket 21, step 1)."""
    tx = transaction([], success=False,
                     attr=attribution(method=AttributionMethod.TX_SENDER_FALLBACK))
    assert net_transaction(tx, PRICES).status is ClassificationStatus.FAILED_TRANSACTION


# -- J. shapes with no expressible intent ---------------------------------------


def test_quote_to_quote_has_no_clear_endpoint():
    """USDC -> WETH. Both legs are quote assets; neither is "the asset" being traded."""
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 3000 * ONE_USDC, 0),
        transfer(WETH, POOL_A, OWNER, ONE_TOKEN, 1),
    ])
    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    assert "quote" in result.reason


def test_long_tail_to_long_tail_has_no_valid_quote_asset():
    """PEPE -> SHIB. §4.1 requires a valid quote asset; there is none, and no price is invented."""
    tx = transaction([
        transfer(PEPE, OWNER, POOL_A, 500 * ONE_TOKEN, 0),
        transfer(SHIB, POOL_A, OWNER, 900 * ONE_TOKEN, 1),
    ])
    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    assert result.quote_usd is None


def test_two_assets_bought_with_one_quote_has_no_clear_endpoint():
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
        transfer(SHIB, POOL_A, OWNER, 700 * ONE_TOKEN, 2),
    ])
    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    assert len(result.residuals) == 3


def test_two_legs_moving_the_same_direction_are_not_a_swap():
    """A deposit of USDC and PEPE together is not a trade in either direction."""
    tx = transaction([
        transfer(USDC, POOL_A, OWNER, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
    ])
    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    assert "direction" in result.reason


def test_a_one_sided_receipt_is_a_residual_not_a_trade():
    """An inbound transfer with nothing going out: one leg, above tolerance, no counterparty."""
    tx = transaction([
        transfer(USDC, POOL_A, OWNER, 1000 * ONE_USDC, 0),
    ])
    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL
    assert result.residuals[0].usd == Decimal("1000.000000")


def test_a_transaction_touching_the_owner_not_at_all_has_no_endpoint():
    tx = transaction([
        transfer(USDC, VICTIM, POOL_A, 1000 * ONE_USDC, 0),
    ])
    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    assert result.residuals == ()


def test_an_unpriceable_long_tail_dust_leg_is_never_assumed_negligible():
    """No price, no negligibility claim.

    A leg whose USD value is unknown cannot be compared against the tolerance, so it survives and
    the transaction lands in NO_CLEAR_ENDPOINT rather than being resolved on a guess.
    """
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
        transfer(SHIB, POOL_A, OWNER, 1, 2),  # one raw unit of a token with no oracle
    ])
    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    shib = [d for d in result.residuals if d.token == SHIB][0]
    assert shib.raw == 1
    assert shib.usd is None, "None is the honest answer; a zero here would be a sentinel"


# -- K. pricing rules -----------------------------------------------------------


def test_a_trade_whose_quote_leg_cannot_be_priced_is_quarantined():
    """§4.1: trade size must be computable. An unpriced quote asset is quarantined, not guessed."""
    tx = transaction([
        transfer(WETH, OWNER, POOL_A, ONE_TOKEN, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
    ])
    result = net_transaction(tx, {USDC: Decimal("0.000001")})  # no WETH price

    assert result.status is ClassificationStatus.UNSUPPORTED
    assert "computable" in result.reason


def test_no_price_is_ever_requested_for_a_long_tail_token():
    """§4.6 is enforced structurally: netting never asks the book about a non-quote asset."""
    asked = []

    def book(token, raw_amount):
        asked.append(token)
        return PRICES[token] * raw_amount

    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
    ])
    result = net_transaction(tx, book)

    assert result.status is ClassificationStatus.VALID_BUY
    assert set(asked) == {USDC}, "a long-tail oracle must not be reachable from netting"


def test_a_float_price_is_refused_at_the_boundary():
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
    ])
    with pytest.raises(TypeError):
        net_transaction(tx, {USDC: 0.000001})


def test_a_negative_price_is_refused():
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
    ])
    with pytest.raises(ValueError):
        net_transaction(tx, {USDC: Decimal("-0.000001")})


# -- L. what is allowed to set the tolerance ------------------------------------
#
# The tolerance is `max($0.01, 0.01% of transaction notional)`, so whatever is permitted to set the
# notional is permitted to decide what counts as unexplained money. Everything below fixes one
# rule: a leg that leaves nothing behind is a phantom, and a phantom sizes nothing.


def _sale_with_fifty_dollars_unexplained(extra=()):
    """1,000 USDC out, 500 PEPE in, and +50 USDT the route never explains.

        USDC: -1_000_000_000   = -$1,000.000000
        USDT:    +50_000_000   =    +$50.000000
        PEPE:  +500e18         =  unpriceable, always survives

    Three surviving legs → NO_CLEAR_ENDPOINT, queued under addendum §8. ``extra`` adds transfers
    that must not change that.
    """
    return transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
        transfer(USDT, POOL_A, OWNER, 50_000_000, 2),
    ] + list(extra))


def test_the_unexplained_fifty_dollars_is_queued():
    """The control. notional = max($1,000.000000, $50.000000) = $1,000.000000,
    tolerance = max($0.01, 0.0001 x 1000) = $0.100000, and $50 > $0.10."""
    tx = _sale_with_fifty_dollars_unexplained()
    assert transaction_notional_usd(tx, PRICES) == Decimal("1000.000000")
    assert residual_tolerance_usd(Decimal("1000.000000")) == Decimal("0.10")

    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    assert len(result.residuals) == 3


def test_a_leg_that_cancels_to_zero_cannot_enlarge_the_tolerance():
    """A 300 WETH flash loan, borrowed and repaid in the same transaction, decides nothing.

        WETH: +300e18 then -300e18 = 0 raw exactly

    Its gross one-way flow is 3e20 raw x $0.000000000000003 = $900,000.000000, which as a notional
    would give a tolerance of max($0.01, 0.0001 x 900000) = $90.00 and write the $50 off as dust —
    the same economic transaction admitted to the primary metric as a clean buy because of a loan
    that netted to nothing. The notional is the size of the endpoints, so the loan contributes
    none of it: it stays $1,000.000000, the tolerance stays $0.10, and the $50 stays queued.
    """
    lender = "0x7777777777777777777777777777777777777777"
    tx = _sale_with_fifty_dollars_unexplained([
        transfer(WETH, lender, OWNER, 300 * ONE_TOKEN, 3),
        transfer(WETH, OWNER, lender, 300 * ONE_TOKEN, 4),
    ])

    assert transaction_notional_usd(tx, PRICES) == Decimal("1000.000000")

    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    # The loan is recorded as cancelled, exactly like a route intermediate.
    weth = [d for d in result.residuals if d.token == WETH][0]
    assert weth.raw == 0
    usdt = [d for d in result.residuals if d.token == USDT][0]
    assert usdt.usd == Decimal("50.000000"), "the $50 is still on the record, not written off"


def test_a_leg_that_almost_cancels_cannot_enlarge_the_tolerance_either():
    """The same loan repaid one raw unit short of round: 300e18 in, 300e18 + 1e12 out.

        WETH: +300e18 - (300e18 + 1e12) = -1_000_000_000_000 raw
              1e12 x $0.000000000000003 = $0.003000
        gross one-way flow = 300e18 + 1e12 = $900,003.000000

    $0.003 out of $900,003.000000 is 0.00000033% of what the leg routed: it left no endpoint, so
    it sizes nothing and the notional stays $1,000.000000. A rule that only excluded an
    exactly-zero net would be one raw unit from being defeated.
    """
    lender = "0x7777777777777777777777777777777777777777"
    tx = _sale_with_fifty_dollars_unexplained([
        transfer(WETH, lender, OWNER, 300 * ONE_TOKEN, 3),
        transfer(WETH, OWNER, lender, 300 * ONE_TOKEN + 1_000_000_000_000, 4),
    ])

    assert transaction_notional_usd(tx, PRICES) == Decimal("1000.000000")
    assert net_transaction(tx, PRICES).status is ClassificationStatus.NO_CLEAR_ENDPOINT


def test_a_shortfall_above_the_dollar_floor_still_leaves_no_endpoint():
    """The same loan repaid $0.021 short — twice the $0.01 residual floor, and then some.

        WETH: +300e18 - (300e18 + 7_000_000_000_000) = -7_000_000_000_000 raw
              7e12 x $0.000000000000003 = $0.021000
        gross one-way flow = 300_000_007_000_000_000_000 raw = $900,000.021000

    A rule that excluded only nets at or below the fixed $0.01 floor calls this leg an endpoint,
    hands the notional $900,000.021000 and the tolerance $90.0000021, and writes the $50 off: an
    absolute test with a consequence that scales with the leg. What decides it is the shortfall
    against the leg's own flow, not against a fixed floor — $0.021 out of $900,000.021000 is
    0.0000023%, so nothing stayed and nothing is sized.

    The notional stays $1,000.000000, the tolerance stays $0.100000, the $50 stays queued.
    """
    lender = "0x7777777777777777777777777777777777777777"
    tx = _sale_with_fifty_dollars_unexplained([
        transfer(WETH, lender, OWNER, 300 * ONE_TOKEN, 3),
        transfer(WETH, OWNER, lender, 300 * ONE_TOKEN + 7_000_000_000_000, 4),
    ])

    assert transaction_notional_usd(tx, PRICES) == Decimal("1000.000000")

    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    usdt = [d for d in result.residuals if d.token == USDT][0]
    assert usdt.usd == Decimal("50.000000")


def test_the_cancelling_leg_may_be_a_thousand_times_larger_and_change_nothing():
    """A 300,000 WETH loan — $900,000,000 — repaid $51 short.

        WETH: +300_000e18 - (300_000e18 + 17_000_000_000_000_000)
              = -17_000_000_000_000_000 raw
              1.7e16 x $0.000000000000003 = $51.000000
        gross one-way flow = 300_000_017_000_000_000_000_000 raw = $900,000,051.000000

    Sized by its gross this one leg sets a $90,000.0051 tolerance, under which the $1,000 endpoint,
    the $50 residual and the $51 shortfall are all dust and the transaction reads as a lone
    unpriceable PEPE leg. $51 out of $900,000,051.000000 is 0.0000057% — the same fraction as the
    $0.021 case three thousand times smaller — so the same rule answers both, and the shortfall
    stands as a $51 residual of its own rather than as a licence to discard the others.
    """
    lender = "0x7777777777777777777777777777777777777777"
    tx = _sale_with_fifty_dollars_unexplained([
        transfer(WETH, lender, OWNER, 300_000 * ONE_TOKEN, 3),
        transfer(WETH, OWNER, lender, 300_000 * ONE_TOKEN + 17_000_000_000_000_000, 4),
    ])

    assert transaction_notional_usd(tx, PRICES) == Decimal("1000.000000")

    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    by_token = {d.token: d for d in result.residuals}
    assert by_token[USDT].usd == Decimal("50.000000")
    assert by_token[WETH].usd == Decimal("-51.000000"), "the shortfall is money, not a threshold"


def test_an_endpoint_is_sized_by_what_stayed_not_by_what_it_routed():
    """No loan at all: a 900,000 USDC order of which 899,000 USDC is refunded.

        USDC: -900_000_000_000 + 899_000_000_000 = -1_000_000_000 raw = -$1,000.000000
              gross one-way flow = 900_000_000_000 raw = $900,000.000000
        USDT:      +50_000_000                                       =    +$50.000000
        PEPE:  +500e18                                               = unpriceable, survives

    The USDC leg is a genuine endpoint — $1,000 stayed — so no rule about cancelling legs touches
    it, and excluding phantoms does not help here. But 99.888% of what it routed came back, and
    sizing the transaction at the $900,000 that moved instead of the $1,000 that stayed buys a
    $90.000000 tolerance and writes the $50 off: a clean VALID_BUY of 500 PEPE with $50 sitting in
    residuals that nothing downstream reads.

    An endpoint is worth what it left behind. notional = max($1,000.000000, $50.000000) =
    $1,000.000000, tolerance = $0.100000, and all three legs survive.
    """
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 900_000 * ONE_USDC, 0),
        transfer(USDC, POOL_A, OWNER, 899_000 * ONE_USDC, 1),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 2),
        transfer(USDT, POOL_A, OWNER, 50_000_000, 3),
    ])

    assert transaction_notional_usd(tx, PRICES) == Decimal("1000.000000")

    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    assert len(result.residuals) == 3
    by_token = {d.token: d for d in result.residuals}
    assert by_token[USDC].usd == Decimal("-1000.000000")
    assert by_token[USDT].usd == Decimal("50.000000")


def test_the_exclusion_boundary_is_the_legs_own_proportional_tolerance():
    """Exactly at 0.01% of its own flow, and one raw unit past it.

        gross one-way flow  300e18 raw                        = $900,000.000000
        0.01% of that                                         =      $90.000000

        at the boundary:  net -30_000_000_000_000_000 raw     =     -$90.000000  -> came back
        one raw unit on:  net -30_000_000_000_000_001 raw     =     -$90.000000000000003
                                                              >      $90.000000  -> an endpoint

    The comparison is ``<=``, so the boundary case leaves no endpoint and sizes nothing: the $50
    USDC sale is the only endpoint and the notional is $50.000000. One raw unit further and the
    leg is an endpoint — worth the $90.000000000000003 that stayed, never the $900,000 that moved.
    Either way the consequence is bounded by the leg's own net, which is the whole repair: under
    the old rule the two sides of a boundary differed by a factor of nine thousand.
    """
    lender = "0x7777777777777777777777777777777777777777"

    def loaned(repaid_raw):
        return transaction([
            transfer(USDC, OWNER, POOL_A, 50 * ONE_USDC, 0),
            transfer(PEPE, POOL_A, OWNER, ONE_TOKEN, 1),
            transfer(WETH, lender, OWNER, repaid_raw, 2),
            transfer(WETH, OWNER, lender, 300 * ONE_TOKEN, 3),
        ])

    at_boundary = loaned(300 * ONE_TOKEN - 30_000_000_000_000_000)
    one_unit_past = loaned(300 * ONE_TOKEN - 30_000_000_000_000_001)

    assert transaction_notional_usd(at_boundary, PRICES) == Decimal("50.000000")
    assert transaction_notional_usd(one_unit_past, PRICES) == \
        Decimal("90.000000000000003")


def test_a_transaction_that_left_no_endpoint_at_all_is_sized_by_what_it_routed():
    """The one place a gross flow still sets the tolerance, and what it can and cannot do.

    A 300 WETH round trip that keeps $51 and nothing else:

        WETH: +300e18 - (300e18 + 17_000_000_000_000) = -17_000_000_000_000 raw
              1.7e13 x $0.000000000000003 = $0.051000
        gross one-way flow = $900,000.051000, and 0.01% of that is $90.0000051

    No token left an endpoint, so there is no endpoint to size the transaction by and the round
    trip is measured at what it routed — the same reading §4.3 gives the $956 arbitrage. It cannot
    admit anything to the primary metric: every leg that reaches this branch is already within its
    own proportional tolerance, hence within the transaction's, so the only status this branch can
    produce is CIRCULAR_ARBITRAGE — excluded, with its volume still on the record.

    This is the remaining hole and it is deliberate: $0.051 of a $900,000 round trip is written off
    as arbitrage profit rather than queued. It is not a route into the trade population.
    """
    lender = "0x7777777777777777777777777777777777777777"
    tx = transaction([
        transfer(WETH, lender, OWNER, 300 * ONE_TOKEN, 0),
        transfer(WETH, OWNER, lender, 300 * ONE_TOKEN + 17_000_000_000_000, 1),
    ])

    assert transaction_notional_usd(tx, PRICES) == Decimal("900000.051000")

    result = net_transaction(tx, PRICES)
    assert result.status is ClassificationStatus.CIRCULAR_ARBITRAGE
    assert result.quote_usd == Decimal("900000.051000")


def test_an_owner_to_owner_transfer_is_counted_once_not_twice():
    """A 100,000,000 USDC transfer the owner sends to itself moved nothing.

    Summed on both sides it nets to zero (right) while inflating the gross one-way flow (wrong).
    The gross no longer sets the notional, but it is still what a net is judged against:

        endpoint only:   sent 1_000_000_000                        → net    -$1,000.000000
                                                                     gross   $1,000.000000
        counted twice:   sent 100_001_000_000_000                  → net    -$1,000.000000
                         received 100_000_000_000_000                gross $100,001,000.000000

    0.01% of $100,001,000.000000 is $10,000.100000, and $1,000 is under it — so the real endpoint
    reads as a leg that came back, the transaction is sized by $0.120000 of dust, and the gross
    volume the reconciliation queue sorts by is off by five orders of magnitude. The result must be
    byte-identical with the self-transfer and without it.
    """
    legs = [
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
        transfer(USDT, POOL_A, OWNER, 120_000, 2),          # $0.120000
    ]
    plain = transaction(legs)
    with_self_move = transaction(legs + [
        transfer(USDC, OWNER, OWNER, 100_000_000 * ONE_USDC, 3),  # owner to owner: nothing moved
    ])

    assert transaction_notional_usd(with_self_move, PRICES) == Decimal("1000.000000")
    assert to_canonical_json(net_transaction(with_self_move, PRICES)) == \
        to_canonical_json(net_transaction(plain, PRICES))

    result = net_transaction(with_self_move, PRICES)
    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    assert result.quote_usd == Decimal("1000.000000"), "the self-move is not volume either"
    assert len(result.residuals) == 3, "the self-transfer is not an endpoint and not a residual"


def test_a_cancelling_leg_never_changes_a_clean_trade():
    """The other direction: a phantom leg must not turn a clean buy into something else.

    The buy of `test_simple_buy` with a 300 WETH loan wrapped around it is the same buy.
    """
    lender = "0x7777777777777777777777777777777777777777"
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
        transfer(WETH, lender, OWNER, 300 * ONE_TOKEN, 2),
        transfer(WETH, OWNER, lender, 300 * ONE_TOKEN, 3),
    ])
    result = net_transaction(tx, PRICES)

    assert result.status is ClassificationStatus.VALID_BUY
    assert result.sold_asset == USDC and result.sold_raw_amount == 1_000_000_000
    assert result.bought_asset == PEPE
    assert result.quote_usd == Decimal("1000.000000")


# -- M. the frozen context holds through every operation ------------------------
#
# `divide` returns 38 significant digits. Decimal's unary minus and `abs` are *arithmetic*: they
# round to the ambient context, which is 28 digits by default. Any USD value derived from a
# division therefore loses ten digits the moment its sign is touched — the defect that shipped in
# LotConsumption.realized_return, in a place where it looks like punctuation.

#: A price book that derives WETH's USD price the way any book would: a pool holding $7,000,000 of
#: quote value against 3,000 WETH, so one raw unit is $7,000,000 / 3,000e18.
#:
#:   divide(7000000, 3000e18) = 2.3333333333333333333333333333333333333E-15
#:                              (a 2 followed by 37 threes: 38 significant digits, the frozen
#:                               precision — the exact value does not terminate)
DIVIDED_PRICES = {WETH: divide(Decimal("7000000"), Decimal(3000 * 10 ** 18))}

#: 3 WETH at that price:
#:   3_000_000_000_000_000_000 x 2.3333333333333333333333333333333333333E-15
#:      = 6999.9999999999999999999999999999999999      (38 significant digits, exact at prec=38)
#: It is *not* $7,000: the price was rounded to 38 digits before the multiplication, so the product
#: sits 1E-34 below. Rounded to the ambient 28 digits it becomes exactly
#: 7000.000000000000000000000000 — rounder, more plausible, and wrong.
THREE_WETH_USD = Decimal("6999.9999999999999999999999999999999999")

#: Written out rather than as ``-THREE_WETH_USD``, and that is the whole point of this section: a
#: unary minus *in this file* rounds to the ambient 28 digits too, so the negated constant would
#: equal the buggy value and the test would agree with the defect it exists to catch. (It did, on
#: the first run.)
THREE_WETH_USD_SENT = Decimal("-6999.9999999999999999999999999999999999")


def test_a_quote_leg_keeps_every_digit_the_frozen_context_gives_it():
    """3 WETH out, 500 PEPE in. The trade size is the quote leg's magnitude.

    ``abs(quote_leg.usd)`` under the ambient 28-digit context reports $7,000 exactly — a rounder,
    more plausible number than the true one, and a different canonical hash for any validator
    re-deriving it under the frozen context (§9).
    """
    tx = transaction([
        transfer(WETH, OWNER, POOL_A, 3 * ONE_TOKEN, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
    ])
    result = net_transaction(tx, DIVIDED_PRICES)

    assert result.status is ClassificationStatus.VALID_BUY
    assert result.quote_usd == THREE_WETH_USD
    assert result.quote_usd != Decimal("7000")


def test_a_sent_leg_is_the_exact_negation_of_the_received_leg():
    """The same 3 WETH, sent and received, must differ only in sign.

    ``-magnitude`` rounds to the ambient context, so the sent leg comes back as
    -7000.000000000000000000000000 while its received twin keeps all 38 digits — and the two no
    longer cancel, which is exactly what the conservation invariant exists to detect.
    """
    sent = net_transaction(transaction([
        transfer(WETH, OWNER, POOL_A, 3 * ONE_TOKEN, 0),
    ]), DIVIDED_PRICES)
    received = net_transaction(transaction([
        transfer(WETH, POOL_A, OWNER, 3 * ONE_TOKEN, 0),
    ]), DIVIDED_PRICES)

    assert sent.status is ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL
    assert received.status is ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL
    assert sent.residuals[0].usd == THREE_WETH_USD_SENT
    assert received.residuals[0].usd == THREE_WETH_USD
    assert sent.residuals[0].usd + received.residuals[0].usd == Decimal("0")


def test_the_callers_ambient_decimal_context_cannot_change_the_answer():
    """§9 requires byte-identical output from an independent re-derivation.

    A validator running under a different ambient precision must get the same bytes, so nothing in
    netting may read ``getcontext()``. Every arithmetic operation belongs inside
    CALCULATION_CONTEXT.

        1_234_567_890_123 raw USDC x $0.000001 = $1,234,567.890123   (13 significant digits)

    Thirteen digits is more than a 9-digit context can hold, so a caller running at prec=9 gets
    $1,234,567.89 out of ``abs()`` — 12.3 cents of a trade size, invented by the caller's context
    and invisible in the record. The canonical form normalises scale, so only a changed *value*
    shows up here: this is the smallest such case, not an exotic one.
    """
    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1_234_567_890_123, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
        transfer(USDT, POOL_A, OWNER, 3, 2),  # $0.000003 of dust, below the floor
    ])
    baseline = net_transaction(tx, PRICES)
    assert baseline.quote_usd == Decimal("1234567.890123")

    with localcontext() as ctx:
        ctx.prec = 9
        narrow = net_transaction(tx, PRICES)

    assert narrow.quote_usd == Decimal("1234567.890123")
    assert to_canonical_json(narrow) == to_canonical_json(baseline)


# -- N. the negligibility comparison runs on the value, not on a rounded copy ----
#
# `_is_negligible` is the gate every leg passes through, and it compares a magnitude against the
# tolerance. Taking that magnitude with `abs()` rounds it to the *ambient* context first, so a leg
# is discarded or kept on the strength of digits the caller's context happened to keep. This is the
# one comparison in the module where the difference is a status rather than a trailing digit.

#: $0.10 plus one unit in the 38th significant digit — one ulp of the frozen context, above the
#: tolerance a $1,000 notional produces. Written as a literal: deriving it would need the very
#: arithmetic under test, and rounding it to the ambient 28 digits gives exactly $0.10.
ONE_TENTH_PLUS_ONE_ULP = Decimal("0.10000000000000000000000000000000000001")


def test_a_leg_one_ulp_above_the_tolerance_is_not_negligible():
    """A USDT leg worth $0.10000000000000000000000000000000000001 against a $0.100000 tolerance.

        notional  = $1,000.000000  (the USDC endpoint)
        tolerance = max($0.01, 0.0001 x 1000) = $0.100000

    The leg is above it, so it survives: three legs, no expressible endpoint pair, queued.

    Under ``abs()`` the same leg reads as 0.1000000000000000000000000000 — the 28-digit ambient
    rounding — which is *within* tolerance, so it is discarded as dust and the transaction becomes
    a clean VALID_BUY of 500 PEPE for $1,000. Ten digits the caller's context dropped decide
    whether $0.10 of unexplained money is on the record.
    """
    def book(token, raw_amount):
        if token == USDT:
            return ONE_TENTH_PLUS_ONE_ULP
        return PRICES[token] * raw_amount

    tx = transaction([
        transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
        transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
        transfer(USDT, OWNER, POOL_A, 100_000, 2),
    ])

    assert transaction_notional_usd(tx, book) == Decimal("1000.000000")
    assert residual_tolerance_usd(Decimal("1000.000000")) == Decimal("0.10")

    result = net_transaction(tx, book)

    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    assert len(result.residuals) == 3
    usdt = [d for d in result.residuals if d.token == USDT][0]
    assert usdt.usd == Decimal("-0.10000000000000000000000000000000000001")


# -- canonical form -------------------------------------------------------------


def test_every_status_survives_canonical_json():
    """A float leaking in through any path raises in ``to_canonical_json``."""
    cases = [
        transaction([transfer(USDC, OWNER, POOL_A, 1000 * ONE_USDC, 0),
                     transfer(PEPE, POOL_A, OWNER, 500 * ONE_TOKEN, 1)]),
        transaction([transfer(SHIB, OWNER, POOL_A, 5 * ONE_TOKEN, 0),
                     transfer(USDC, POOL_A, OWNER, 900 * ONE_USDC, 1)]),
        transaction([transfer(USDC, OWNER, POOL_A, 956_000_000, 0),
                     transfer(USDC, POOL_A, OWNER, 956_049_000, 1)]),
        transaction([transfer(USDC, POOL_A, OWNER, 1000 * ONE_USDC, 0)]),
        transaction([transfer(USDC, OWNER, POOL_A, 3000 * ONE_USDC, 0),
                     transfer(WETH, POOL_A, OWNER, ONE_TOKEN, 1)]),
        transaction([], success=False),
        transaction([], attr=attribution(method=AttributionMethod.TX_SENDER_FALLBACK)),
    ]
    seen = set()
    for tx in cases:
        result = net_transaction(tx, PRICES)
        seen.add(result.status)
        blob = to_canonical_json(result)
        assert '"{}"'.format(result.status.value) in blob

    assert seen == {
        ClassificationStatus.VALID_BUY,
        ClassificationStatus.VALID_SELL,
        ClassificationStatus.CIRCULAR_ARBITRAGE,
        ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL,
        ClassificationStatus.NO_CLEAR_ENDPOINT,
        ClassificationStatus.FAILED_TRANSACTION,
        ClassificationStatus.UNSUPPORTED,
    }, "every ClassificationStatus netting can emit is exercised here"
