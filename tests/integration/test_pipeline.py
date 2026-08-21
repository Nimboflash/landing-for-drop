"""A realistic day through the whole machine, reconciled from the result alone.

The unit tests fix each rule. This fixes the thing the rules exist for: that a batch of transactions
representing an ordinary Ethereum day comes out the other end *accounted for* — every transaction in
exactly one status, every §8 exclusion named, every quarantine carrying its volume, and every score
carrying the §10 mix it was built from.

The day contains, deliberately, every shape that has broken a published pipeline:

    an aggregator route with a referral fee and a searcher sandwiching it in the same transaction
    a partial sell spanning two lots, with the closing slice taking the exact remainder
    a position still open at the horizon, marked at the liquidity bound rather than at spot
    a rugged token in a pool that has been silent for thirty days
    a Safe-executed trade and an ERC-4337 trade
    a solver-settled batch carrying two owners and one owner slot
    an arbitrage bot's round trip
    a sell with no matching buy
    a reverted transaction
    a dust residual with no counterparty leg

Nothing here is asserted loosely. The per-buy figures are the ones worked out in
``tests/hand_computed/test_pipeline.py``'s arithmetic, and the run's whole published surface is
pinned by one canonical hash — so a change anywhere in the composition shows up as one failing line
naming what moved.
"""

import dataclasses
from decimal import Decimal

import pytest

from contracts import (
    AccountType,
    AttributionMethod,
    ClassificationStatus,
    NATIVE_ETH,
    PoolState,
    Transfer,
    USDC,
    ValueBasis,
    WETH,
    canonical_hash,
)
from attribution import AttributionContext, SafeExecution, UserOperation
from marking import DEAD_INACTIVITY_SECONDS
from pipeline import (
    MEASUREMENT_HORIZON_SECONDS,
    ObservedTransaction,
    Stage,
    TokenStart,
    Window,
    WindowConfig,
    run_wallet_window,
)

# -- the cast -------------------------------------------------------------------

ALICE = "0x" + "a1" * 20          # plain EOA, the busiest wallet of the day
BOB_SAFE = "0x" + "a2" * 20       # a Safe
CARL = "0x" + "a3" * 20           # an ERC-4337 smart account
DANA = "0x" + "a4" * 20           # sells a token she never bought here
BOT = "0x" + "a5" * 20            # arbitrage
EVE = "0x" + "a6" * 20            # the second owner in the solver batch
SEARCHER = "0x" + "a7" * 20       # untyped: value passes through, never a portfolio
STRANGER = "0x" + "a8" * 20

ROUTER = "0x" + "b0" * 20
SOLVER = "0x" + "b5" * 20
BUNDLER = "0x" + "b6" * 20
REFERRER = "0x" + "b7" * 20
POOL_P = "0x" + "b1" * 20
POOL_Q = "0x" + "b2" * 20
POOL_R = "0x" + "b3" * 20

TOKEN_P = "0x" + "c1" * 20        # bought twice, partially sold, remainder marked
TOKEN_Q = "0x" + "c2" * 20        # rugged
TOKEN_R = "0x" + "c3" * 20        # bought by the smart accounts, sold by Dana with no lot

ONE_USDC = 10 ** 6
ONE_TOKEN = 10 ** 18

START_BLOCK = 18_000_000
START_TS = 1_700_000_000
END_BLOCK = START_BLOCK + 7_200
END_TS = START_TS + 86_400
HORIZON_BLOCK = END_BLOCK + 216_000
HORIZON_TS = END_TS + MEASUREMENT_HORIZON_SECONDS

#: USD per raw unit. USDC at 6 decimals is $1; WETH at 18 decimals at an assumed $3,000.
PRICES = {
    USDC: Decimal("0.000001"),
    WETH: Decimal("0.000000000000003"),
}

INFRASTRUCTURE = frozenset({ROUTER, SOLVER, BUNDLER, REFERRER, POOL_P, POOL_Q, POOL_R})

BASE = AttributionContext(
    infrastructure=INFRASTRUCTURE,
    eoas=frozenset({ALICE, DANA, BOT, EVE, STRANGER}),
    safes=frozenset({BOB_SAFE}),
    smart_accounts=frozenset({CARL}),
)

SAFE_CONTEXT = AttributionContext(
    infrastructure=INFRASTRUCTURE,
    eoas=BASE.eoas,
    safes=BASE.safes,
    smart_accounts=BASE.smart_accounts,
    safe_execution=SafeExecution(safe=BOB_SAFE, signers=(STRANGER,)),
)

ERC4337_CONTEXT = AttributionContext(
    infrastructure=INFRASTRUCTURE,
    eoas=BASE.eoas,
    safes=BASE.safes,
    smart_accounts=BASE.smart_accounts,
    user_operations=(UserOperation(sender=CARL, bundler=BUNDLER),),
)

WINDOW = Window(index=7, start_block=START_BLOCK, start_ts=START_TS,
                end_block=END_BLOCK, end_ts=END_TS)

POOLS = {
    # Alice's remainder is 500 TOKEN_P against a 500 TOKEN_P reserve and 7,000 USDC:
    #   spot = 500e18 * (7e9 / 5e20) * 1e-6 = $7,000
    #   exit = 500e18 * (7e9 / 1e21) * 1e-6 = $3,500      <- the liquidity bound, half of spot
    TOKEN_P: PoolState(
        address=POOL_P, asset=TOKEN_P, quote=USDC,
        asset_reserve_raw=500 * ONE_TOKEN, quote_reserve_raw=7_000 * ONE_USDC,
        last_swap_block=HORIZON_BLOCK, last_swap_timestamp=HORIZON_TS, fee_bps=0,
    ),
    # Rugged: 4,000 TOKEN_Q against a $0.001 reserve, silent for exactly thirty days.
    #   exit = 4e21 * (1000 / 8e21) * 1e-6 = $0.0005  < the $1.00 minimum
    TOKEN_Q: PoolState(
        address=POOL_Q, asset=TOKEN_Q, quote=USDC,
        asset_reserve_raw=4_000 * ONE_TOKEN, quote_reserve_raw=1_000,
        last_swap_block=HORIZON_BLOCK - 216_000,
        last_swap_timestamp=HORIZON_TS - DEAD_INACTIVITY_SECONDS, fee_bps=0,
    ),
    # Deep enough that the smart accounts' positions mark near spot.
    TOKEN_R: PoolState(
        address=POOL_R, asset=TOKEN_R, quote=USDC,
        asset_reserve_raw=10 ** 24, quote_reserve_raw=10 ** 12,
        last_swap_block=HORIZON_BLOCK, last_swap_timestamp=HORIZON_TS, fee_bps=30,
    ),
}

CONFIG = WindowConfig(
    horizon_block=HORIZON_BLOCK,
    horizon_ts=HORIZON_TS,
    token_starts={
        # TOKEN_P and TOKEN_R are mature; TOKEN_Q launched with the window, so buys land in A or B.
        TOKEN_P: TokenStart(block=START_BLOCK - 200_000, timestamp=START_TS - 2_400_000),
        TOKEN_R: TokenStart(block=START_BLOCK - 200_000, timestamp=START_TS - 2_400_000),
        TOKEN_Q: TokenStart(block=START_BLOCK, timestamp=START_TS),
    },
)


def t(token, from_addr, to_addr, raw, index, is_fee=False):
    return Transfer(token=token, from_addr=from_addr, to_addr=to_addr, raw_amount=raw,
                    log_index=index, is_fee=is_fee)


def tx(tx_hash, nth, transfers, sender, context=BASE, success=True):
    """One transaction ``nth`` blocks into the day, timestamp moving with the block."""
    return ObservedTransaction(
        tx_hash=tx_hash,
        block_number=START_BLOCK + nth,
        timestamp=START_TS + nth * 12,
        success=success,
        tx_sender=sender,
        transfers=tuple(transfers),
        context=context,
    )


def the_day():
    """Twelve transactions, in block order."""
    return [
        # 1. Alice buys 1,000 TOKEN_P for 1,000 USDC through an aggregator, paying a referral fee,
        #    with a searcher sandwiching the whole thing inside the same transaction.
        tx("0x01", 10, [
            t(WETH, SEARCHER, POOL_P, 40 * ONE_TOKEN, 0),
            t(TOKEN_P, POOL_P, SEARCHER, 900_000 * ONE_TOKEN, 1),
            t(USDC, ALICE, ROUTER, 1_000 * ONE_USDC, 2),
            t(TOKEN_P, POOL_P, ALICE, 1_000 * ONE_TOKEN, 3),
            t(USDC, ALICE, REFERRER, 2_390_000, 4, is_fee=True),
            t(TOKEN_P, SEARCHER, POOL_P, 900_000 * ONE_TOKEN, 5),
            t(WETH, POOL_P, SEARCHER, 41 * ONE_TOKEN, 6),
        ], sender=ALICE),

        # 2. Alice buys 1,000 more TOKEN_P, this time for 3,000 USDC.
        tx("0x02", 20, [
            t(USDC, ALICE, POOL_P, 3_000 * ONE_USDC, 0),
            t(TOKEN_P, POOL_P, ALICE, 1_000 * ONE_TOKEN, 1),
        ], sender=ALICE),

        # 3. Alice sells 1,500 TOKEN_P for 3,000 USDC — 1,000 out of lot 1, 500 out of lot 2.
        tx("0x03", 30, [
            t(TOKEN_P, ALICE, POOL_P, 1_500 * ONE_TOKEN, 0),
            t(USDC, POOL_P, ALICE, 3_000 * ONE_USDC, 1),
        ], sender=ALICE),

        # 4. Alice buys 4,000 TOKEN_Q for 500 USDC, six blocks after the token started trading.
        tx("0x04", 6, [
            t(USDC, ALICE, POOL_Q, 500 * ONE_USDC, 0),
            t(TOKEN_Q, POOL_Q, ALICE, 4_000 * ONE_TOKEN, 1),
        ], sender=ALICE),

        # 5. A Safe buys TOKEN_R. §6.2: the portfolio is the Safe, and its signer is not a trader.
        tx("0x05", 40, [
            t(USDC, BOB_SAFE, POOL_R, 2_000 * ONE_USDC, 0),
            t(TOKEN_R, POOL_R, BOB_SAFE, 2_000 * ONE_TOKEN, 1),
        ], sender=STRANGER, context=SAFE_CONTEXT),

        # 6. An ERC-4337 smart account buys TOKEN_R. The bundler submitted it and is not the trader.
        tx("0x06", 50, [
            t(USDC, CARL, POOL_R, 1_000 * ONE_USDC, 0),
            t(TOKEN_R, POOL_R, CARL, 1_000 * ONE_TOKEN, 1),
        ], sender=BUNDLER, context=ERC4337_CONTEXT),

        # 7. A solver settles Alice's and Eve's trades in one transaction. Two owners, one owner
        #    slot, nothing in the transaction ranks them: §8 excludes it rather than guessing.
        tx("0x07", 60, [
            t(USDC, ALICE, SOLVER, 400 * ONE_USDC, 0),
            t(TOKEN_R, SOLVER, ALICE, 400 * ONE_TOKEN, 1),
            t(USDC, EVE, SOLVER, 600 * ONE_USDC, 2),
            t(TOKEN_R, SOLVER, EVE, 600 * ONE_TOKEN, 3),
        ], sender=SOLVER),

        # 8. An arbitrage bot routes $956 of USDC out and $956.049 back. §4.3 excludes it: netting
        #    reports it correctly as near-zero, and per-hop summing would book the gross as volume.
        tx("0x08", 70, [
            t(USDC, BOT, POOL_P, 956 * ONE_USDC, 0),
            t(USDC, POOL_R, BOT, 956_049_000, 1),
        ], sender=BOT),

        # 9. Dana sells 1,000 TOKEN_R she never bought inside this window.
        tx("0x09", 80, [
            t(TOKEN_R, DANA, POOL_R, 1_000 * ONE_TOKEN, 0),
            t(USDC, POOL_R, DANA, 1_500 * ONE_USDC, 1),
        ], sender=DANA),

        # 10. A reverted transaction. It moved nothing, and it is still counted.
        tx("0x0a", 90, [
            t(USDC, ALICE, POOL_R, 5_000 * ONE_USDC, 0),
            t(TOKEN_R, POOL_R, ALICE, 5_000 * ONE_TOKEN, 1),
        ], sender=ALICE, success=False),

        # 11. Alice sends $1 to a stranger: one surviving leg, no counterparty, straight to the
        #     reconciliation queue.
        tx("0x0b", 100, [
            t(USDC, ALICE, STRANGER, ONE_USDC, 0),
        ], sender=ALICE),

        # 12. The measurement tail: Bob's Safe sells its TOKEN_R eleven days after the window
        #     closed, well inside the buy's own thirty days.
        ObservedTransaction(
            tx_hash="0x0c",
            block_number=END_BLOCK + 79_200,
            timestamp=END_TS + 950_400,
            success=True,
            tx_sender=STRANGER,
            transfers=(
                t(TOKEN_R, BOB_SAFE, POOL_R, 2_000 * ONE_TOKEN, 0),
                t(USDC, POOL_R, BOB_SAFE, 3_000 * ONE_USDC, 1),
            ),
            context=SAFE_CONTEXT,
        ),
    ]


def run_the_day():
    return run_wallet_window(the_day(), POOLS, PRICES, WINDOW, CONFIG)


def account(result, tx_hash):
    for item in result.accounts:
        if item.buy.tx_hash == tx_hash:
            return item
    raise AssertionError("no account for {}".format(tx_hash))


# -- the reconciliation ---------------------------------------------------------


def test_the_day_reconciles_from_the_result_alone():
    """Twelve in, six trades out, and the difference explained line by line.

    This is the assertion the whole result type exists to support. A reviewer holding only the
    returned object must be able to get from N to M without re-running anything and without being
    told which rows to ignore.
    """
    result = run_the_day()
    lines = dict(result.reconciliation())

    assert lines["transactions_in"] == 12
    assert lines["attribution_excluded"] == 1          # the solver batch
    assert lines["attribution_usable"] == 11
    assert lines["netting_quarantined"] == 0
    assert lines["netted"] == 12

    assert lines["status_VALID_BUY"] == 5
    assert lines["status_VALID_SELL"] == 3
    assert lines["status_CIRCULAR_ARBITRAGE"] == 1
    assert lines["status_FAILED_TRANSACTION"] == 1
    assert lines["status_ABOVE_TOLERANCE_RESIDUAL"] == 1
    assert lines["status_UNSUPPORTED"] == 1            # the excluded batch
    assert lines["status_NO_CLEAR_ENDPOINT"] == 0
    assert sum(v for k, v in lines.items() if k.startswith("status_")) == 12

    # Five buys: four scored (Alice's two TOKEN_P, Alice's TOKEN_Q, Carl's TOKEN_R) and one — Bob's
    # — whose book is fine but which lands in the same book as nothing broken, so it scores too.
    assert lines["buys"] == 5
    assert lines["sells"] == 3
    assert lines["buys_scored"] == 5
    assert lines["buys_quarantined"] == 0
    assert lines["buys_outside_window"] == 0
    assert lines["buys_unscored"] == 0

    # Four (wallet, asset) books: Alice/P, Alice/Q, Bob/R, Carl/R, Dana/R. Dana's is refused.
    assert lines["fifo_books"] == 5
    assert lines["fifo_books_quarantined"] == 1
    assert lines["sells_quarantined"] == 1
    assert lines["wallets_seen"] == 4
    assert lines["wallets_scored"] == 3
    assert lines["wallets_unscorable"] == 1


def test_every_transaction_appears_exactly_once_in_the_census():
    result = run_the_day()
    assert result.census.total == 12
    assert sum(result.census.counts.values()) + result.census.quarantined == 12
    assert {r.tx_hash for r in result.results} == {
        "0x{:02x}".format(n) for n in range(1, 13)
    }
    # The line above is a set comparison, and a set is silent about a hash arriving twice. The
    # census claims to cover twelve transactions, so twelve rows must carry twelve hashes.
    assert len({r.tx_hash for r in result.results}) == len(result.results) == 12


def test_one_duplicated_hash_anywhere_in_the_day_refuses_the_whole_run():
    """Every row of this day is realistic, and one of them arrives twice.

    A day is assembled from paged queries, and the cheapest bug in that assembly is a page boundary
    read twice. Nothing about the resulting input looks wrong: twelve well-formed transactions, all
    inside the measurement period, eleven distinct hashes. Before the boundary check the run
    published a full result over it — the census still totalled twelve, ``StageCounts`` still
    reconciled, and the two rows sharing a hash had simply been pooled somewhere.

    The whole run is refused rather than the duplicated row dropped, and that is the point: this
    result is the reconciliation of one population, and there is no version of it that is honest
    about eleven transactions when twelve were supplied.
    """
    day = the_day()
    duplicated = list(day)
    duplicated[7] = dataclasses.replace(duplicated[7], tx_hash=duplicated[2].tx_hash)

    with pytest.raises(ValueError) as refusal:
        run_wallet_window(duplicated, POOLS, PRICES, WINDOW, CONFIG)

    message = str(refusal.value)
    assert "12 transactions under 11 distinct tx_hash values" in message
    assert "{} appears 2 times, at input positions 2, 7".format(day[2].tx_hash) in message

    # And the honest day is untouched: the refusal is about the duplicate, not about the shape.
    assert run_the_day().census.total == 12


def _checksummed(key):
    return key[:2] + key[2:].upper()


def test_the_same_day_configured_in_checksummed_addresses_is_the_same_day():
    """A caller whose address book is checksummed must get this day's answer, not a different one.

    Vendor tables hand back EIP-55 addresses; the seam works in lowercase. Three of the four
    configuration mappings normalised their keys and one did not, so the same day configured in
    checksummed form used to lose every §4.7 trading start — each buy quarantined as unknown-age,
    against a run that had supplied the starts. Asserted over the whole published answer rather
    than over the buckets, because the failure was upstream of everything.
    """
    control = run_the_day()
    respelled = run_wallet_window(
        the_day(),
        {_checksummed(token): pool for token, pool in POOLS.items()},
        {_checksummed(asset): price for asset, price in PRICES.items()},
        WINDOW,
        WindowConfig(
            horizon_block=HORIZON_BLOCK,
            horizon_ts=HORIZON_TS,
            token_starts={
                _checksummed(token): start for token, start in CONFIG.token_starts.items()
            },
        ),
    )

    assert respelled.stages == control.stages
    assert respelled.census.counts == control.census.counts
    assert respelled.qualities == control.qualities
    assert [a.bucket for a in respelled.accounts] == [a.bucket for a in control.accounts]
    assert respelled.coverage == control.coverage


def test_an_eth_row_beside_a_weth_row_in_the_price_book_refuses_the_whole_run():
    """The collision that shares no characters with itself.

    §4.2 collapses the native-ETH sentinel onto WETH, so a price book with an ETH row and a WETH
    row — the ordinary shape of a vendor's price table — has two keys naming one asset. One of the
    two was silently discarded and which one depended on the order the caller's dict iterated in;
    this day prices WETH at $3,000, and the run would have marked against whichever row landed
    last with nothing published to say a choice had been made.
    """
    with pytest.raises(ValueError) as refusal:
        run_wallet_window(
            the_day(),
            POOLS,
            {
                USDC: Decimal("0.000001"),
                WETH: Decimal("0.000000000000003"),
                NATIVE_ETH: Decimal("0.0000000000000031"),
            },
            WINDOW,
            CONFIG,
        )

    message = str(refusal.value)
    assert "prices" in message
    assert NATIVE_ETH in message
    assert WETH in message

    # The honest book is untouched.
    assert run_the_day().census.total == 12


# -- attribution ----------------------------------------------------------------


def test_the_searcher_is_set_aside_rather_than_promoted_to_owner():
    """A searcher is on both ends of the swap it sandwiched, exactly like the trader. What
    separates them is the context's typing, not two-sidedness — and the evidence says so."""
    result = run_the_day()
    buy = next(r for r in result.results if r.tx_hash == "0x01")
    assert buy.portfolio_owner == ALICE
    assert buy.status is ClassificationStatus.VALID_BUY
    assert buy.quote_usd == Decimal("1000")
    assert result.attribution.by_method[AttributionMethod.DIRECT_EOA] >= 1


def test_the_safe_and_the_smart_account_are_the_traders_not_their_submitters():
    """§6.2. The Safe's signer and the 4337 bundler both submitted a transaction and neither
    traded. ``coalesce(taker, tx_from)`` would publish them as the wallets."""
    result = run_the_day()
    safe_buy = next(r for r in result.results if r.tx_hash == "0x05")
    op_buy = next(r for r in result.results if r.tx_hash == "0x06")

    assert safe_buy.portfolio_owner == BOB_SAFE
    assert op_buy.portfolio_owner == CARL
    assert result.attribution.by_method[AttributionMethod.SAFE_EXECUTION] == 2
    assert result.attribution.by_method[AttributionMethod.ERC4337_SENDER] == 1
    assert result.attribution.by_account_type[AccountType.SAFE] == 2
    assert STRANGER not in result.qualities
    assert BUNDLER not in result.qualities


def test_the_solver_batch_is_excluded_named_and_scored_for_nobody():
    """Two owners and one owner slot. Publishing either one at full confidence is the phantom
    mega-wallet, and erasing the other is the real user going missing from the universe."""
    result = run_the_day()

    assert [record.tx_hash for record in result.excluded] == ["0x07"]
    assert result.excluded[0].method is AttributionMethod.UNRESOLVED
    assert ALICE in result.excluded[0].reason and EVE in result.excluded[0].reason
    assert result.census.unsupported_from_attribution == 1
    assert result.census.unsupported_from_pricing == 0
    assert EVE not in result.qualities
    assert "0x07" not in {a.buy.tx_hash for a in result.accounts}
    assert result.attribution.unresolved == 1
    assert result.attribution.total == 12
    assert result.attribution.usable_for_primary_metric == 11


# -- §4.4 through the composition ------------------------------------------------


def test_the_partial_sell_spans_two_lots_with_the_closing_slice_taking_the_remainder():
    """Alice sells 1,500 TOKEN_P against lots of 1,000 @ $1,000 and 1,000 @ $3,000 for $3,000.

        lot 1  1,000 consumed, basis $1,000, proceeds 1,000/1,500 * 3,000 = $2,000
               return 2,000 / 1,000 - 1 = 1.0
        lot 2    500 consumed, basis 500/1,000 * 3,000 = $1,500,
               proceeds = what is left of the sell = 3,000 - 2,000 = $1,000
               500 still open, marked at the liquidity bound  = $3,500
               return (1,000 + 3,500) / 3,000 - 1 = 0.5

    The second lot is the one that matters: it is realized *and* marked at once, and its return is
    the sum of both bases over the whole basis. A composition that scored the realized part alone
    would report 1,000/3,000 - 1 = -0.667 and read as a losing trade.
    """
    result = run_the_day()

    first = account(result, "0x01")
    assert first.realized_raw == 1_000 * ONE_TOKEN
    assert first.open_raw == 0
    assert first.realized_proceeds_usd == Decimal("2000")
    assert first.return_pct == Decimal("1")

    second = account(result, "0x02")
    assert second.realized_raw == 500 * ONE_TOKEN
    assert second.open_raw == 500 * ONE_TOKEN
    assert second.realized_cost_usd == Decimal("1500")
    assert second.realized_proceeds_usd == Decimal("1000")
    assert second.open_cost_usd == Decimal("1500")
    assert second.position.value_usd == Decimal("3500")
    assert second.position.value_basis is ValueBasis.LIQUIDITY_BOUND
    assert second.marked_usd == Decimal("3500")
    assert second.return_pct == Decimal("0.5")


def test_the_rugged_token_is_zeroed_and_its_exposure_reported():
    result = run_the_day()
    rug = account(result, "0x04")

    assert rug.position.value_basis is ValueBasis.DEAD_ZEROED
    assert rug.position.value_usd == Decimal("0")
    assert rug.marked_usd == Decimal("0")
    assert rug.dead_usd == Decimal("500")
    assert rug.return_pct == Decimal("-1")


def test_alices_score_carries_the_mix_it_was_built_from():
    """§10: realized $3,000, marked $3,500, dead $500 — $7,000 of accounted basis.

    Half of this wallet's accounted value rests on a pool mark and $500 of it on a rug. The score
    alone says none of that, which is why §10 requires the mix and why it is asserted here at the
    top level rather than inside marking.
    """
    result = run_the_day()
    quality = result.qualities[ALICE]

    assert quality.n_buys == 3
    assert quality.marked_share == Decimal("0.5")
    assert quality.realized_share + quality.marked_share + quality.dead_share == Decimal("1")
    assert quality.dead_share > 0
    assert set(quality.bucket_weights) == set(quality.bucket_values)


def test_the_measurement_tail_realizes_the_safes_position_inside_its_own_thirty_days():
    """Bob buys on day 0 and sells eleven days after the window closed — inside his buy's own
    horizon, so §4.4 Case 1 governs it and nothing is marked.

        return = 3,000 / 2,000 - 1 = 0.5
    """
    result = run_the_day()
    row = account(result, "0x05")

    assert row.realized_raw == 2_000 * ONE_TOKEN
    assert row.open_raw == 0
    assert row.position is None
    assert row.late_sold_raw == 0
    assert row.return_pct == Decimal("0.5")
    assert result.qualities[BOB_SAFE].realized_share == Decimal("1")


# -- the queue ------------------------------------------------------------------


def test_danas_broken_book_is_quarantined_with_its_volume_and_nobody_elses():
    """A sell with no matching buy means a buy is missing from our record. FIFO refuses to clamp,
    and the composition queues the book whole — while Bob's and Carl's books over the *same* token
    are untouched, because a lot book belongs to one wallet."""
    result = run_the_day()

    queued = result.quarantine.by_stage(Stage.FIFO)
    assert len(queued) == 1
    assert queued[0].wallet == DANA
    assert queued[0].asset == TOKEN_R
    assert queued[0].tx_hashes == ("0x09",)
    assert queued[0].volume_usd == Decimal("1500")
    # Dana's broken book is $1,500; the queue's total is $1,501 because the $1 dust residual is now
    # a reconciliation-queue record too. Before that routing existed the residual's volume was
    # invisible, which is the silent exclusion ticket 21 exists to prevent. Both entries are
    # priced, so `unpriced` stays 0.
    assert result.quarantine.total_volume_usd == Decimal("1501")
    assert result.quarantine.unpriced == 0

    assert DANA in result.unscorable
    assert BOB_SAFE in result.qualities
    assert CARL in result.qualities


def test_the_arbitrage_round_trip_is_excluded_with_its_phantom_volume_on_the_record():
    """§4.3. $956 routed, $0.049 kept — every leg within tolerance, so there is no endpoint to
    express. Left in, the bot reads as a wallet with thousands of small profitable trades."""
    result = run_the_day()
    arb = next(r for r in result.results if r.tx_hash == "0x08")

    assert arb.status is ClassificationStatus.CIRCULAR_ARBITRAGE
    assert arb.quote_usd == Decimal("956.049")
    assert BOT not in result.qualities
    assert BOT not in result.unscorable       # the bot never had a trade to score


def test_the_dust_residual_and_the_reverted_transaction_are_both_counted():
    result = run_the_day()
    dust = next(r for r in result.results if r.tx_hash == "0x0b")
    reverted = next(r for r in result.results if r.tx_hash == "0x0a")

    assert dust.status is ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL
    assert dust.quote_usd == Decimal("1")
    assert reverted.status is ClassificationStatus.FAILED_TRANSACTION
    assert reverted.reason and "reverted" in reverted.reason


def test_the_residual_reaches_the_reconciliation_queue_with_its_volume_and_age():
    """The queue had a producer and no consumer, so a residual excluded from the primary metric
    surfaced in no queue, no total and no report — the silent exclusion ticket 21 exists to prevent.

    The $1 dust residual is not a trade, so the primary metric never counts it. This asserts it does
    not simply vanish: it is a reconciliation-queue record carrying the volume netting priced ($1)
    and the block it happened at, and that volume is in the queue's total.
    """
    from pipeline.census import Stage

    result = run_the_day()
    dust = next(r for r in result.results if r.tx_hash == "0x0b")

    reconciliation = result.quarantine.by_stage(Stage.RECONCILIATION)
    assert len(reconciliation) == 1, "the residual must reach the queue as exactly one record"

    record = reconciliation[0]
    assert record.tx_hashes == ("0x0b",)
    assert record.volume_usd == Decimal("1"), "the notional netting priced, not None"
    assert record.block_number == dust.block_number, "its age is visible, per ticket 21"
    assert "addendum §8" in record.reason

    # And the volume is not lost: it is in the queue's published total.
    assert result.quarantine.total_volume_usd >= Decimal("1")


def test_the_residual_is_not_double_counted_in_the_census():
    """A residual has a result and is already a census status; the queue record is extra visibility.

    The census counts it once, as ABOVE_TOLERANCE_RESIDUAL. It must not also inflate the netting
    quarantine count — that would report the same transaction as both classified and lost, which is
    the double-count the whole reconciliation guards against. RECONCILIATION is a distinct stage
    from NETTING precisely so the three invariants that read a NETTING record as a refusal stay
    true.
    """
    from pipeline.census import Stage

    result = run_the_day()

    assert result.census.counts[ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL] == 1
    # The netting quarantine count is refusals only, and there is no residual among them.
    netting_records = result.quarantine.by_stage(Stage.NETTING)
    assert result.census.quarantined == len(netting_records)
    assert all("addendum §8 tolerance" not in r.reason for r in netting_records)


# -- coverage -------------------------------------------------------------------


def test_coverage_reports_the_money_and_not_the_row_count():
    """Priced notional across the day, and the share of it that reached a trade and a score.

        buys      1,000 + 3,000 + 500 + 2,000 + 1,000 = $7,500
        sells     3,000 + 1,500 + 3,000               = $7,500
        non-trades  956.049 (the arbitrage round trip) + 1 (the dust residual) = $957.049

    The other two transactions carry no notional at all and are counted rather than costed. Netting
    refused the solver batch at step 2 — before it priced anything — and the reverted transaction at
    step 1, so neither has a gross volume to report. ``transactions_unpriced`` is what keeps the
    share honest about them: a coverage figure computed over a population that is mostly unpriceable
    would otherwise read as very good coverage of very little.
    """
    result = run_the_day()
    coverage = result.coverage

    assert coverage.notional_usd_trades == Decimal("15000")
    assert coverage.notional_usd_non_trades == Decimal("957.049")
    assert coverage.notional_usd_total == Decimal("15957.049")
    # Only the buys of scored wallets reach a published number: Alice $4,500, Bob $2,000,
    # Carl $1,000.
    assert coverage.notional_usd_scored == Decimal("7500")
    # $1,500 (Dana's broken book) + $1 (the dust residual, now visible in the queue rather than
    # silently excluded). The residual's volume is also in notional_usd_non_trades above — those are
    # two lenses on the same dollar, not a partition, so the overlap is two true statements rather
    # than a double-count of a total.
    assert coverage.notional_usd_quarantined == Decimal("1501")
    assert coverage.is_reportable
    assert Decimal("0.93") < coverage.trade_share < Decimal("0.95")
    assert coverage.transactions_priced == 10
    assert coverage.transactions_unpriced == 2


# -- the whole surface, pinned --------------------------------------------------


def summarise(result):
    """Everything the run publishes, as canonicalisable primitives.

    Deliberately built from the *public* surface rather than from internals: if a field a reader
    would act on changes, this moves, and if a private detail changes it does not.
    """
    return {
        "window": result.window,
        "stages": dict(result.reconciliation()),
        "census": {status.value: count for status, count in result.census.counts.items()},
        "census_quarantined": result.census.quarantined,
        "coverage": {
            "total": result.coverage.notional_usd_total,
            "trades": result.coverage.notional_usd_trades,
            "scored": result.coverage.notional_usd_scored,
            "quarantined": result.coverage.notional_usd_quarantined,
            "trade_share": result.coverage.trade_share,
            "scored_share": result.coverage.scored_share,
        },
        "wallets": [
            {
                "wallet": outcome.wallet,
                "scored": outcome.quality is not None,
                "value": None if outcome.quality is None else outcome.quality.value,
                "realized_share": (None if outcome.quality is None
                                   else outcome.quality.realized_share),
                "marked_share": (None if outcome.quality is None
                                 else outcome.quality.marked_share),
                "dead_share": (None if outcome.quality is None
                               else outcome.quality.dead_share),
                "buys": [
                    {
                        "tx": account.buy.tx_hash,
                        "bucket": account.bucket,
                        "cost": account.cost_usd,
                        "realized_raw": account.realized_raw,
                        "open_raw": account.open_raw,
                        "realized": account.realized_proceeds_usd,
                        "marked": account.marked_usd,
                        "dead": account.dead_usd,
                        "return": account.return_pct,
                    }
                    for account in outcome.accounts
                ],
            }
            for outcome in result.wallets
        ],
        "excluded": [record.tx_hash for record in result.excluded],
        "quarantine": [
            {"stage": record.stage, "txs": list(record.tx_hashes),
             "volume": record.volume_usd}
            for record in result.quarantine
        ],
    }


def test_the_whole_published_surface_is_stable():
    """One hash over everything a reader would act on.

    A regression pin, and a cheap one: any change to a score, a share, a count, a queue entry or a
    coverage figure moves this line, and the individual assertions above then say which. It also
    holds the ordering guarantees — the wallets, the accounts and the queue are all in a canonical
    order, so a run that produced the same numbers in a different sequence still fails here.

    Moved once, from ``341d0d11…``, when ``reconciliation()`` gained ``transactions_undecodable``.
    No number in this day changed — its twelve transactions all decode, so the new line reads 0 —
    and that is exactly the kind of movement this pin is supposed to report rather than absorb: the
    published surface grew a field, and a reader diffing two runs is entitled to see that it did.

    Moved again, from ``b32a7b63…``, when the $1 dust residual began reaching the reconciliation
    queue. No score changed and no transaction was reclassified — the residual was always a
    non-trade — but its volume, previously excluded from the primary metric *and* absent from the
    queue, now appears as a Stage.RECONCILIATION record. The queue's total volume moved $1,500 →
    $1,501 and the record count grew by one, which is precisely the movement ticket 21's audit
    found missing.
    """
    assert canonical_hash(summarise(run_the_day())) == (
        "5cc602bebfd50656b1f4c17ab51c06bfc48fe5d438ca68dee8d3b2716f634001"
    )


def test_the_run_is_reproducible_across_invocations():
    assert canonical_hash(summarise(run_the_day())) == canonical_hash(summarise(run_the_day()))
