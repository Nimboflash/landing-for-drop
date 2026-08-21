"""Realistic multi-transaction scenarios: a wallet's day, an arbitrage bot's day, and the queue.

The unit tests fix each rule; these fix the thing the rules exist for — that a whole batch comes
out accounted for. §9.4 asks for 100% supported-transaction coverage and zero unexplained missing
trades, and the only way to show that is to run a batch and reconcile the counts against what went
in.
"""

from decimal import Decimal

from contracts import (
    AccountType,
    Attribution,
    AttributionMethod,
    ClassificationStatus,
    NATIVE_ETH,
    Transaction,
    Transfer,
    USDC,
    USDT,
    WBTC,
    WETH,
    canonical_hash,
    to_canonical_json,
)
from netting import (
    QUEUED_STATUSES,
    net_transaction,
    net_transactions,
    reconciliation_queue,
    status_counts,
)

WALLET = "0x1111111111111111111111111111111111111111"
UNIVERSAL_ROUTER = "0x2222222222222222222222222222222222222222"
POOL_USDC_WETH = "0x3333333333333333333333333333333333333333"
POOL_WETH_PEPE = "0x4444444444444444444444444444444444444444"
SEARCHER = "0x5555555555555555555555555555555555555555"
REFERRER = "0x6666666666666666666666666666666666666666"
STRANGER = "0x7777777777777777777777777777777777777777"

PEPE = "0x6982508145454ce325ddbe47a25d4ec3d2311933"
SHIB = "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce"
WSOL = "0xd31a59c85ae9d8edefec411d448f90841571b89c"

PRICES = {
    USDC: Decimal("0.000001"),
    USDT: Decimal("0.000001"),
    WETH: Decimal("0.000000000000003"),  # $3,000 / 1e18
}

ONE_USDC = 1_000_000
ONE_TOKEN = 10 ** 18
BLOCK_0 = 18_000_000
TIME_0 = 1_700_000_000


def _attr(owner=WALLET, method=AttributionMethod.DIRECT_EOA,
          account_type=AccountType.EOA, tx_hash="0x0"):
    return Attribution(
        tx_hash=tx_hash,
        tx_sender=owner if owner else "0x0",
        portfolio_owner=owner,
        account_type=account_type,
        method=method,
        confidence=Decimal("1"),
        evidence=("integration fixture",),
    )


def _t(token, from_addr, to_addr, raw, index, is_fee=False):
    return Transfer(token=token, from_addr=from_addr, to_addr=to_addr,
                    raw_amount=raw, log_index=index, is_fee=is_fee)


def _tx(tx_hash, transfers, nth, success=True, attr=None):
    """One transaction, ``nth`` blocks into the day. Timestamp and block move together — the seam
    requires a timestamp to be paired with a block number, never carried alone."""
    return Transaction(
        tx_hash=tx_hash,
        block_number=BLOCK_0 + nth,
        timestamp=TIME_0 + nth * 12,
        success=success,
        attribution=attr if attr is not None else _attr(tx_hash=tx_hash),
        transfers=tuple(transfers),
    )


# -- the wallet's day -----------------------------------------------------------


def wallet_day():
    """Nine transactions covering every shape §4.2 has to survive, in block order."""
    return [
        # 1. Aggregator route USDC -> WETH -> PEPE, split across two pools, with a referral fee
        #    and a searcher sandwiching the whole thing inside the same transaction.
        _tx("0xa1", [
            _t(WETH, SEARCHER, POOL_WETH_PEPE, 40 * ONE_TOKEN, 0),
            _t(PEPE, POOL_WETH_PEPE, SEARCHER, 900_000 * ONE_TOKEN, 1),
            _t(USDC, WALLET, UNIVERSAL_ROUTER, 600 * ONE_USDC, 2),
            _t(USDC, WALLET, UNIVERSAL_ROUTER, 356 * ONE_USDC, 3),
            _t(WETH, POOL_USDC_WETH, WALLET, 300_000_000_000_000_000, 4),
            _t(WETH, WALLET, POOL_WETH_PEPE, 300_000_000_000_000_000, 5),
            _t(PEPE, POOL_WETH_PEPE, WALLET, 12_000 * ONE_TOKEN, 6),
            _t(USDC, WALLET, REFERRER, 2_390_000, 7, is_fee=True),
            _t(PEPE, SEARCHER, POOL_WETH_PEPE, 900_000 * ONE_TOKEN, 8),
            _t(WETH, POOL_WETH_PEPE, SEARCHER, 41 * ONE_TOKEN, 9),
        ], nth=1),

        # 2. A straightforward ETH buy, entering in native ETH with a WETH refund.
        _tx("0xa2", [
            _t(NATIVE_ETH, WALLET, UNIVERSAL_ROUTER, ONE_TOKEN, 0),
            _t(WETH, UNIVERSAL_ROUTER, WALLET, 400_000_000_000_000_000, 1),
            _t(SHIB, POOL_WETH_PEPE, WALLET, 5_000 * ONE_TOKEN, 2),
        ], nth=2),

        # 3. Selling half the PEPE back for USDC, with $0.004 of dust left behind.
        _tx("0xa3", [
            _t(PEPE, WALLET, POOL_WETH_PEPE, 6_000 * ONE_TOKEN, 0),
            _t(USDC, POOL_WETH_PEPE, WALLET, 700 * ONE_USDC, 1),
            _t(USDT, POOL_WETH_PEPE, WALLET, 4_000, 2),
        ], nth=3),

        # 4. A circular arbitrage: $956 out and $956.049 back through wSOL.
        _tx("0xa4", [
            _t(USDC, WALLET, POOL_USDC_WETH, 956_000_000, 0),
            _t(WSOL, POOL_USDC_WETH, WALLET, 4_780_000_000, 1),
            _t(WSOL, WALLET, POOL_WETH_PEPE, 4_780_000_000, 2),
            _t(USDC, POOL_WETH_PEPE, WALLET, 956_049_000, 3),
        ], nth=4),

        # 5. A reverted swap. The transfers are present in the source and must not be netted.
        _tx("0xa5", [
            _t(USDC, WALLET, POOL_USDC_WETH, 5_000 * ONE_USDC, 0),
            _t(PEPE, POOL_USDC_WETH, WALLET, 90_000 * ONE_TOKEN, 1),
        ], nth=5, success=False),

        # 6. A partial fill: $2,000 sent, $1,400 of it returned, and no asset received.
        _tx("0xa6", [
            _t(USDC, WALLET, UNIVERSAL_ROUTER, 2_000 * ONE_USDC, 0),
            _t(USDC, UNIVERSAL_ROUTER, WALLET, 1_400 * ONE_USDC, 1),
        ], nth=6),

        # 7. A solver-settled trade whose owner is only the transaction sender by default.
        _tx("0xa7", [
            _t(USDC, WALLET, UNIVERSAL_ROUTER, 1_000 * ONE_USDC, 0),
            _t(PEPE, UNIVERSAL_ROUTER, WALLET, 400 * ONE_TOKEN, 1),
        ], nth=7, attr=_attr(method=AttributionMethod.TX_SENDER_FALLBACK, tx_hash="0xa7")),

        # 8. A stablecoin rotation: both endpoints are quote assets.
        _tx("0xa8", [
            _t(USDC, WALLET, POOL_USDC_WETH, 3_000 * ONE_USDC, 0),
            _t(USDT, POOL_USDC_WETH, WALLET, 2_998 * ONE_USDC, 1),
        ], nth=8),

        # 9. A transaction that has nothing to do with this wallet at all.
        _tx("0xa9", [
            _t(USDC, STRANGER, POOL_USDC_WETH, 10_000 * ONE_USDC, 0),
            _t(PEPE, POOL_USDC_WETH, STRANGER, 1_000 * ONE_TOKEN, 1),
        ], nth=9),
    ]


def test_the_day_is_fully_accounted_for():
    """Every transaction lands in exactly one status, and the counts are the pre-computed ones."""
    results = net_transactions(wallet_day(), PRICES)
    counts = status_counts(results)

    assert sum(counts.values()) == len(results) == 9
    assert counts == {
        ClassificationStatus.VALID_BUY: 2,                # 0xa1 (PEPE), 0xa2 (SHIB)
        ClassificationStatus.VALID_SELL: 1,               # 0xa3
        ClassificationStatus.CIRCULAR_ARBITRAGE: 1,       # 0xa4
        ClassificationStatus.FAILED_TRANSACTION: 1,       # 0xa5
        ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL: 1,  # 0xa6
        ClassificationStatus.UNSUPPORTED: 1,              # 0xa7
        ClassificationStatus.NO_CLEAR_ENDPOINT: 2,        # 0xa8, 0xa9
    }
    # Every status appears in the mapping, including the ones this day never produced, so two
    # coverage reports from different days are comparable line by line.
    assert set(counts) == set(ClassificationStatus)


def test_no_event_leaves_the_pipeline_unexplained():
    """A trade, or a reason. There is no third outcome — a silent drop is a hard error."""
    for result in net_transactions(wallet_day(), PRICES):
        assert result.status.is_trade or result.reason
        assert result.tx_hash
        assert result.block_number is not None and result.timestamp is not None


def test_the_aggregator_route_produces_one_buy_and_no_phantom():
    """0xa1: split route, WETH intermediate, referral fee, MEV sandwich — one intent survives."""
    result = net_transaction(wallet_day()[0], PRICES)

    assert result.status is ClassificationStatus.VALID_BUY
    assert result.bought_asset == PEPE
    assert result.bought_raw_amount == 12_000 * ONE_TOKEN
    # 600 + 356 = 956 USDC. The 2.39 USDC referral fee is not part of the endpoint.
    assert result.sold_asset == USDC
    assert result.sold_raw_amount == 956_000_000
    assert result.quote_usd == Decimal("956.000000")
    # The WETH hop is recorded as cancelled rather than reported as a purchase.
    assert [(d.token, d.raw) for d in result.residuals] == [(WETH, 0)]


def test_no_result_in_the_day_ever_reports_buying_the_intermediate():
    """The phantom §4.2 exists to prevent, checked across the whole batch rather than one case."""
    for result in net_transactions(wallet_day(), PRICES):
        if result.status.is_trade:
            assert result.asset not in (WETH, USDC, USDT), (
                "the traded asset is the non-quote side; a quote asset here means an intermediate "
                "hop was mistaken for intent"
            )


def test_the_native_eth_entry_nets_against_the_weth_refund():
    result = net_transaction(wallet_day()[1], PRICES)

    assert result.status is ClassificationStatus.VALID_BUY
    assert result.sold_asset == WETH
    assert result.sold_raw_amount == 600_000_000_000_000_000  # 1.0 ETH out, 0.4 WETH back
    assert result.quote_usd == Decimal("1800.000000")
    assert result.bought_asset == SHIB


def test_the_sell_keeps_its_dust_out_of_the_endpoints():
    result = net_transaction(wallet_day()[2], PRICES)

    assert result.status is ClassificationStatus.VALID_SELL
    assert result.sold_asset == PEPE
    assert result.sold_raw_amount == 6_000 * ONE_TOKEN
    assert result.bought_asset == USDC
    assert result.quote_usd == Decimal("700.000000")
    # $0.004 against a $700 notional: below the $0.07 proportional tolerance and below the floor.
    assert [(d.token, d.raw) for d in result.residuals] == [(USDT, 4_000)]


def test_arbitrage_volume_is_excluded_rather_than_booked():
    """An arbitrage bot's day: five round trips, zero positions, and the volume that vanishes.

    Per-leg summing would report ten swap rows and roughly $9,560 of user volume here. That is how
    arbitrage bots come to look like wallets with thousands of small profitable trades.
    """
    day = []
    for i in range(5):
        day.append(_tx("0xb{}".format(i), [
            _t(USDC, WALLET, POOL_USDC_WETH, 956_000_000, 0),
            _t(WSOL, POOL_USDC_WETH, WALLET, 4_780_000_000, 1),
            _t(WSOL, WALLET, POOL_WETH_PEPE, 4_780_000_000, 2),
            _t(USDC, POOL_WETH_PEPE, WALLET, 956_049_000, 3),
        ], nth=i))

    results = net_transactions(day, PRICES)

    assert all(r.status is ClassificationStatus.CIRCULAR_ARBITRAGE for r in results)
    assert not [r for r in results if r.status.is_trade]

    per_leg_volume = sum(
        (Decimal(t.raw_amount) * PRICES[USDC] for tx in day for t in tx.transfers
         if t.token == USDC),
        Decimal("0"),
    )
    assert per_leg_volume == Decimal("9560.245000")
    netted_volume = sum((r.quote_usd for r in results if r.status.is_trade), Decimal("0"))
    assert netted_volume == Decimal("0")
    # The excluded gross is still reportable — excluded is not the same as invisible.
    assert sum((r.quote_usd for r in results), Decimal("0")) == Decimal("4780.245000")


# -- the same day, borrowed -----------------------------------------------------

LENDER = "0x8888888888888888888888888888888888888888"

#: WBTC at $60,000 with 8 decimals: one raw unit is $0.0006. No transaction in the day touches it,
#: so adding it to the book changes nothing on its own.
LOAN_PRICES = dict(PRICES)
LOAN_PRICES[WBTC] = Decimal("0.0006")

#: 1,000 WBTC — $60,000,000 borrowed and repaid inside the transaction.
LOAN_RAW = 100_000_000_000


def _borrowed(tx):
    """The same transaction with a flash loan wrapped around it: in at the top, back at the end."""
    ordered = ([(WBTC, LENDER, WALLET, LOAN_RAW, False)]
               + [(t.token, t.from_addr, t.to_addr, t.raw_amount, t.is_fee) for t in tx.transfers]
               + [(WBTC, WALLET, LENDER, LOAN_RAW, False)])
    return Transaction(
        tx_hash=tx.tx_hash, block_number=tx.block_number, timestamp=tx.timestamp,
        success=tx.success, attribution=tx.attribution,
        transfers=tuple(_t(token, src, dst, raw, i, is_fee)
                        for i, (token, src, dst, raw, is_fee) in enumerate(ordered)),
    )


def test_a_flash_loan_around_every_transaction_changes_no_classification():
    """The day, borrowed. Every classification and every endpoint quantity is unchanged.

    $60,000,000 of WBTC transits the wallet in each transaction and is gone by the end of it. As a
    notional it would set a tolerance of max($0.01, 0.0001 x 60,000,000) = $6,000.00 — larger than
    anything the wallet actually traded that day, so every endpoint in the day becomes dust and
    nine ordinary transactions read as round trips with nothing in them.

    The tolerance answers "how large was this trade", and a leg that came back in full was not
    part of it. That the lender, not the trader, could otherwise pick the threshold is the point:
    it is the one input to the negligibility rule an outsider controls.
    """
    # 0xa9 is a stranger's transaction that the wallet has no part in. Lending *it* $60m would make
    # the wallet a participant — a different transaction, not the same one wrapped — and netting
    # rightly reads a borrow-and-repay with nothing else in it as a round trip.
    day = [tx if tx.tx_hash == "0xa9" else _borrowed(tx) for tx in wallet_day()]

    plain = net_transactions(wallet_day(), LOAN_PRICES)
    borrowed = net_transactions(day, LOAN_PRICES)

    assert status_counts(borrowed) == status_counts(plain)

    def endpoints(result):
        return (result.status, result.sold_asset, result.sold_raw_amount, result.bought_asset,
                result.bought_raw_amount, result.quote_asset,
                result.quote_usd if result.status.is_trade else None)

    by_hash = {r.tx_hash: endpoints(r) for r in plain}
    for result in borrowed:
        assert endpoints(result) == by_hash[result.tx_hash]

    # And the same transactions still owe someone an answer.
    assert [r.tx_hash for r in reconciliation_queue(borrowed)] == \
        [r.tx_hash for r in reconciliation_queue(plain)]


def test_the_queue_still_reports_the_gross_volume_that_moved():
    """Volume and size are different questions, and the queue is asked the first one.

    ``quote_usd`` on a non-trade is the gross one-way flow of everything that moved, borrowed legs
    included — that is what makes the phantom volume an arbitrage exclusion removed reportable. It
    is deliberately *not* what the tolerance is a percentage of.
    """
    borrowed = net_transactions([_borrowed(tx) for tx in wallet_day()], LOAN_PRICES)
    partial_fill = [r for r in borrowed if r.tx_hash == "0xa6"][0]

    assert partial_fill.status is ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL
    # 100_000_000_000 raw WBTC x $0.0006 = $60,000,000.0000
    assert partial_fill.quote_usd == Decimal("60000000.0000")
    residual_by_token = {d.token: d for d in partial_fill.residuals}
    assert residual_by_token[USDC].usd == Decimal("-600.000000")  # unchanged by the loan
    assert residual_by_token[WBTC].raw == 0                       # the loan, recorded as cancelled


# -- the reconciliation queue ---------------------------------------------------


def test_the_queue_holds_exactly_what_owes_an_answer():
    results = net_transactions(wallet_day(), PRICES)
    queue = reconciliation_queue(results)

    assert [r.tx_hash for r in queue] == ["0xa6", "0xa7", "0xa8", "0xa9"]
    assert all(r.status in QUEUED_STATUSES for r in queue)
    # Settled findings stay out: a reverted transaction and a round trip have known causes, and
    # queueing them would bury the transactions that actually need a human.
    assert "0xa4" not in [r.tx_hash for r in queue]
    assert "0xa5" not in [r.tx_hash for r in queue]


def test_the_queue_shows_volume_and_age():
    queue = reconciliation_queue(net_transactions(wallet_day(), PRICES))

    assert [r.timestamp for r in queue] == sorted(r.timestamp for r in queue), "oldest first"
    for entry in queue:
        assert entry.block_number is not None and entry.timestamp is not None
        assert entry.reason

    partial_fill = [r for r in queue if r.tx_hash == "0xa6"][0]
    assert partial_fill.status is ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL
    assert partial_fill.quote_usd == Decimal("2000.000000")       # gross volume, visible
    assert partial_fill.residuals[0].usd == Decimal("-600.000000")  # what did not come back


def test_queued_transactions_never_carry_a_position():
    for entry in reconciliation_queue(net_transactions(wallet_day(), PRICES)):
        assert not entry.status.is_trade
        assert entry.sold_asset is None and entry.bought_asset is None


# -- determinism and purity -----------------------------------------------------


def test_the_batch_is_byte_stable_and_carries_no_state_between_transactions():
    """Same input, byte-identical output — and netting one transaction cannot change the next."""
    first = net_transactions(wallet_day(), PRICES)
    second = net_transactions(wallet_day(), PRICES)
    assert to_canonical_json(first) == to_canonical_json(second)

    one_at_a_time = tuple(net_transaction(tx, PRICES) for tx in reversed(wallet_day()))
    by_hash = {r.tx_hash: to_canonical_json(r) for r in one_at_a_time}
    for result in first:
        assert by_hash[result.tx_hash] == to_canonical_json(result)


def test_the_whole_day_hashes_and_the_hash_is_reproducible():
    """The canonical hash is what a freeze manifest records; it must not depend on this process."""
    day = net_transactions(wallet_day(), PRICES)
    assert canonical_hash(day) == canonical_hash(net_transactions(wallet_day(), PRICES))
    assert len(canonical_hash(day)) == 64


def test_a_callable_price_book_and_a_mapping_agree():
    """The two accepted ``quote_usd`` shapes are interchangeable, not two different policies."""
    def book(token, raw_amount):
        return PRICES[token] * raw_amount

    assert to_canonical_json(net_transactions(wallet_day(), book)) == \
        to_canonical_json(net_transactions(wallet_day(), PRICES))
