"""Which hard paths the generated data actually reaches — asserted, and the rest listed.

A fixture that is *supposed* to reach a dead pool and does not is worse than no fixture: the suite
is green, the path is untested, and the green is the reason nobody looks. So every path
``tools/mockchain/chain.py``'s table claims is checked here against the run, by its outcome rather
than by its label — ``PoolStatus.DEAD`` on a position, not a wallet called ``dead-pool``.

The last section is the other half of the same duty. It lists, with the measured count, every path
this fixture does **not** reach: no quarantine, no §8 attribution exclusion, no residual above
tolerance, no failed transaction, no late sale past a buy's own 30-day horizon, no long-tail
rejection, no USDT or WBTC leg, and three of the four §6.3 windows missing. Those are not defects in
the generator — several of them are error paths a well-formed source should not produce — but a
reader who assumed the pipeline had been exercised end to end would be wrong about each of them, and
"exercised" is exactly the claim this package exists to support.

Every literal below was measured from the seed-7 run and then written down. None is recomputed from
the implementation it pins.
"""

import dataclasses

import pytest

from contracts import (
    NATIVE_ETH,
    ClassificationStatus,
    PoolStatus,
    TokenAgeBucket,
    Transfer,
    USDC,
    ValueBasis,
    WETH,
    calc,
    divide,
    sub,
)
from depth import size_to_cost_cap
from pipeline import ObservedTransaction
from reporting import CAPITAL_LEVELS, ChurnState
from reporting.diagnostics import MAX_VALID_BUYS, MIN_VALID_BUYS

from tools.mockchain import report as report_module
from tools.mockchain import run_synthetic_window
from tools.mockchain.chain import (
    POOL_MIGRATED_NEW,
    SELECTED_WALLETS,
    TOKEN_DEAD,
    TOKEN_MIGRATED,
    WALLET_BAND_HIGH,
    WALLET_BAND_LOW,
    WALLET_DEAD_POOL,
    WALLET_DORMANT,
    WALLET_ETH_ROUTE,
    WALLET_FRESH,
    WALLET_MIGRATED,
    WALLET_PARTIAL,
    WALLET_SILENT,
    WINDOW_BLOCKS,
    WINDOW_START_BLOCK,
)


def _wallet(result, address):
    return {outcome.wallet: outcome for outcome in result.wallets}[address]


def _accounts_for(result, address):
    return _wallet(result, address).accounts


# -- 1. a dead pool -------------------------------------------------------------


def test_a_dead_pool_zeroes_a_position_through_the_whole_conjunction(result):
    """All three §9.1 conditions true, and the evidence names each of them separately."""
    accounts = _accounts_for(result, WALLET_DEAD_POOL)
    assert len(accounts) == 2
    for account in accounts:
        assert account.buy.bought_asset == TOKEN_DEAD
        assert account.position.pool_status is PoolStatus.DEAD
        assert account.position.value_basis is ValueBasis.DEAD_ZEROED
        assert account.position.value_usd == 0
        assert account.dead_usd > 0, "the exposure the zero verdict decided is carried, not lost"
        evidence = dict(
            item.split("=", 1) for item in account.position.evidence if "=" in item
        )
        assert evidence["cond1_no_swap_for_30d"] == "true"
        assert evidence["cond2_exit_below_minimum"] == "true"
        assert evidence["cond3_no_validated_replacement"] == "true"
        assert evidence["dead_pool"] == (
            "no_swap_for_30d+exit_below_minimum+no_validated_replacement"
        )


def test_the_dead_wallet_scores_minus_one_and_nothing_softens_it(result):
    """A rug is -100%. If this ever reads as flat, the Dune error has been reintroduced."""
    quality = _wallet(result, WALLET_DEAD_POOL).quality
    assert quality.value == calc("-1")
    assert quality.dead_share == calc("1")
    assert quality.realized_share == 0
    assert quality.marked_share == 0


def test_the_dead_share_reaches_the_published_basket(run):
    assert run.report.basket.dead_usd > 0
    assert run.report.basket.dead_share > 0


# -- 2. a token whose liquidity migrated ----------------------------------------


def test_a_migration_is_followed_to_the_replacement_venue_instead_of_being_zeroed(result):
    """Condition 1 holds and condition 3 does not, so the conjunction fails and the mark is real."""
    accounts = _accounts_for(result, WALLET_MIGRATED)
    assert len(accounts) == 2
    for account in accounts:
        assert account.buy.bought_asset == TOKEN_MIGRATED
        assert account.position.pool_status is PoolStatus.MIGRATED
        assert account.position.value_basis is ValueBasis.POOL_MARKED
        assert account.position.value_usd > 0
        evidence = account.position.evidence
        assert "venue={}".format(POOL_MIGRATED_NEW) in evidence
        assert "venue_is_replacement=true" in evidence
        assert "replacement_validated:{}".format(POOL_MIGRATED_NEW) in evidence
        flags = dict(item.split("=", 1) for item in evidence if "=" in item)
        assert flags["cond1_no_swap_for_30d"] == "true"
        assert flags["cond3_no_validated_replacement"] == "false"
        assert flags["dead_pool"] == "false"
        # The replacement is quoted in the same asset as the primary, which is what
        # ``marking.pools.require_same_quote_asset`` demands before it will follow a venue change.
        assert flags["venue_quote"] == WETH


# -- 3. ETH / WETH, the §4.2 collapse -------------------------------------------


def test_the_native_eth_sentinel_collapses_onto_weth_at_the_seam():
    leg = Transfer(
        token=NATIVE_ETH, from_addr="0x" + "a" * 40, to_addr="0x" + "b" * 40,
        raw_amount=1, log_index=0,
    )
    assert leg.token == WETH


def test_the_eth_route_wallet_nets_two_legs_in_one_asset_into_one_quote_leg(chain, result):
    """Paid 2x in native ETH, refunded x in WETH. §4.2 makes that one asset and one net leg."""
    sent = {
        transaction.tx_hash: transaction for transaction in chain.transactions
        if transaction.tx_sender == WALLET_ETH_ROUTE
    }
    assert len(sent) == 3
    trades = [trade for trade in result.results if trade.tx_hash in sent]
    assert len(trades) == 3
    for trade in trades:
        transaction = sent[trade.tx_hash]
        paid, refunded = transaction.transfers[0], transaction.transfers[1]
        assert paid.token == refunded.token == WETH, "both legs are WETH only after the collapse"
        assert paid.raw_amount == 2 * refunded.raw_amount
        assert trade.status is ClassificationStatus.VALID_BUY
        assert trade.quote_asset == WETH
        assert trade.sold_raw_amount == refunded.raw_amount, (
            "the net quote leg is the intended spend, not the gross ETH sent"
        )


def test_without_the_collapse_the_same_shape_has_no_clear_endpoint(chain):
    """The counterfactual, run through the real pipeline rather than argued.

    The refund comes back in a *different* quote asset, so the two legs no longer net. Three legs
    survive the residual tolerance, and netting refuses to choose two of them.
    """
    def split_the_pair(transaction):
        if transaction.tx_sender != WALLET_ETH_ROUTE:
            return transaction
        legs = tuple(
            Transfer(
                token=USDC if index == 1 else leg.token,
                from_addr=leg.from_addr, to_addr=leg.to_addr,
                raw_amount=leg.raw_amount // 10 ** 12 if index == 1 else leg.raw_amount,
                log_index=leg.log_index, is_fee=leg.is_fee,
            )
            for index, leg in enumerate(transaction.transfers)
        )
        return ObservedTransaction(
            tx_hash=transaction.tx_hash, block_number=transaction.block_number,
            timestamp=transaction.timestamp, success=True, tx_sender=transaction.tx_sender,
            transfers=legs, context=transaction.context,
        )

    counterfactual = dataclasses.replace(
        chain, transactions=tuple(split_the_pair(t) for t in chain.transactions)
    )
    result = run_synthetic_window(counterfactual)
    affected = {
        transaction.tx_hash for transaction in chain.transactions
        if transaction.tx_sender == WALLET_ETH_ROUTE
    }
    statuses = [trade.status for trade in result.results if trade.tx_hash in affected]
    assert statuses == [ClassificationStatus.NO_CLEAR_ENDPOINT] * 3
    assert result.census.counts[ClassificationStatus.NO_CLEAR_ENDPOINT] == 3


# -- 4. partial sells and FIFO lot matching -------------------------------------


def test_a_sell_crosses_lot_boundaries_and_leaves_a_partially_consumed_lot(result):
    accounts = _accounts_for(result, WALLET_PARTIAL)
    assert len(accounts) == 6
    partially_consumed = [
        account for account in accounts
        if 0 < account.realized_raw < account.buy.asset_raw_amount
    ]
    assert len(partially_consumed) == 1, "no lot was cut across; FIFO matched whole lots only"
    fully_consumed = [account for account in accounts if account.open_raw == 0]
    untouched = [account for account in accounts if account.realized_raw == 0]
    assert len(fully_consumed) == 3
    assert len(untouched) == 2
    # Three sells produced six consumptions, so at least one sell spanned more than one lot.
    assert result.stages.sells == 3
    assert result.stages.consumptions == 6


def test_fifo_conserves_raw_quantity_against_the_generator(chain, result):
    """An identity across the seam: what the generator sold is what FIFO matched. Exact, no tolerance.

    This is the one check here that compares two independent accounts of the same fact — the
    transfers the generator emitted, and the consumptions FIFO recorded — rather than reading one
    of them twice.
    """
    from tools.mockchain.chain import TOKEN_ALPHA

    sold_raw = sum(
        leg.raw_amount
        for transaction in chain.transactions
        for leg in transaction.transfers
        if leg.from_addr == WALLET_PARTIAL and leg.token == TOKEN_ALPHA
    )
    accounts = _accounts_for(result, WALLET_PARTIAL)
    matched = sum(account.realized_raw + account.late_sold_raw for account in accounts)
    assert sold_raw == matched == 15567113883942394404411


def test_the_measurement_tail_defers_a_buy_rather_than_scoring_it(result):
    """§4.8: a sell in the tail matches; a buy in the tail opens a lot for the next window."""
    assert result.stages.buys == 1042
    assert result.stages.buys_outside_window == 1
    assert result.stages.buys_scored == 1041
    assert sum(len(w.accounts) for w in result.wallets) == 1041


# -- 5. a wallet that goes dormant ----------------------------------------------


def test_the_dormant_wallet_stops_trading_in_the_first_hours_of_the_window(chain):
    blocks = sorted(
        transaction.block_number for transaction in chain.transactions
        if transaction.tx_sender == WALLET_DORMANT
    )
    assert len(blocks) == 3
    assert blocks[0] == WINDOW_START_BLOCK + 500
    assert blocks[-1] == WINDOW_START_BLOCK + 694
    # 694 blocks is 2h19m of a 90-day window: silent for the remaining 99.89% of it.
    assert (blocks[-1] - WINDOW_START_BLOCK) * 500 < WINDOW_BLOCKS


def test_the_churn_block_covers_the_selected_population_including_the_wallet_that_never_traded(run):
    """Churn is reported over the *selected* wallets, not the survivors. That is the whole point."""
    states = dict(run.report.churn.states)
    assert len(states) == len(SELECTED_WALLETS) == 10
    assert run.report.churn.n_wallets == 10
    assert run.report.basket.n_wallets == 9
    assert states[WALLET_SILENT] is ChurnState.INACTIVE
    assert states[WALLET_DORMANT] is ChurnState.REDUCED_ACTIVITY
    assert states[WALLET_BAND_HIGH] is ChurnState.ACTIVE
    assert run.report.churn.n_active == 1
    assert run.report.churn.n_reduced_activity == 8
    assert run.report.churn.n_inactive == 1


def test_the_churn_state_is_driven_by_the_drawn_baseline_not_by_the_dormancy_pattern(chain, run):
    """Stated because the label is easy to over-read.

    ``dormant`` is `Reduced Activity` — and so are seven other wallets, because
    ``chain.baseline_valid_buys`` is *drawn* from the seed in §6's 20-1,000 band while the forward
    period holds a handful of buys. The churn block is therefore exercising ``report_churn``'s rate
    comparison over a real population; it is not evidence that this fixture distinguishes a wallet
    that went quiet from one that was always small. The dormancy itself is pinned above, on the
    blocks.
    """
    assert chain.baseline_valid_buys[WALLET_DORMANT] >= MIN_VALID_BUYS
    assert chain.forward_valid_buys[WALLET_DORMANT] == 3
    reduced = [
        wallet for wallet, state in run.report.churn.states
        if state is ChurnState.REDUCED_ACTIVITY
    ]
    assert WALLET_DORMANT in reduced
    assert len(reduced) == 8


# -- 6. both edges of the 20-1000 valid-buy band --------------------------------


def test_the_band_edges_are_reached_exactly(chain, result):
    assert (MIN_VALID_BUYS, MAX_VALID_BUYS) == (20, 1000)
    assert chain.forward_valid_buys[WALLET_BAND_LOW] == MIN_VALID_BUYS
    assert chain.forward_valid_buys[WALLET_BAND_HIGH] == MAX_VALID_BUYS
    # And the pipeline agrees with the generator about how many of them were valid buys.
    assert _wallet(result, WALLET_BAND_LOW).quality.n_buys == MIN_VALID_BUYS
    assert _wallet(result, WALLET_BAND_HIGH).quality.n_buys == MAX_VALID_BUYS


def test_the_high_edge_wallet_moved_the_pool_it_is_later_marked_against(chain, result):
    """1,000 buys into one pool is enough of its own flow to matter, which is why it is there."""
    accounts = _accounts_for(result, WALLET_BAND_HIGH)
    first, last = accounts[0], accounts[-1]
    assert first.buy.block_number < last.buy.block_number
    # Same USD spend buys progressively fewer raw tokens as the wallet walks the curve up.
    first_rate = divide(first.buy.asset_raw_amount, first.cost_usd)
    last_rate = divide(last.buy.asset_raw_amount, last.cost_usd)
    assert last_rate < first_rate


def test_the_fee_leg_is_dropped_and_never_counted_as_the_trade(chain, result):
    """``band-low`` pays a referral fee on every buy; netting drops it at step 4."""
    with_fee = [
        transaction for transaction in chain.transactions
        if transaction.tx_sender == WALLET_BAND_LOW
    ]
    assert len(with_fee) == 20
    assert all(any(leg.is_fee for leg in t.transfers) for t in with_fee)
    hashes = {t.tx_hash: t for t in with_fee}
    for trade in result.results:
        if trade.tx_hash in hashes:
            spend = hashes[trade.tx_hash].transfers[0]
            fee = hashes[trade.tx_hash].transfers[2]
            assert fee.is_fee and fee.raw_amount > 0
            assert trade.sold_raw_amount == spend.raw_amount


# -- extra paths the fixture also reaches ---------------------------------------


def test_all_four_token_age_buckets_are_produced(result):
    counts = {
        bucket: sum(1 for account in result.accounts if account.bucket is bucket)
        for bucket in TokenAgeBucket
    }
    assert counts == {
        TokenAgeBucket.A: 1, TokenAgeBucket.B: 1, TokenAgeBucket.C: 1, TokenAgeBucket.D: 1038,
    }
    fresh = _accounts_for(result, WALLET_FRESH)
    assert sorted(account.bucket.value for account in fresh) == ["A", "B", "C", "D"]


def test_all_three_value_bases_that_this_fixture_can_produce_are_produced(result):
    counts = {}
    for account in result.accounts:
        if account.position is not None:
            counts[account.position.value_basis] = counts.get(account.position.value_basis, 0) + 1
    assert counts == {
        ValueBasis.POOL_MARKED: 1035,
        ValueBasis.DEAD_ZEROED: 2,
        ValueBasis.LIQUIDITY_BOUND: 1,
    }


def test_every_capital_level_simulates_every_scored_buy(run):
    ladder = run.report.capital_ladder
    assert len(ladder.levels) == len(CAPITAL_LEVELS) == 5
    for level in ladder.levels:
        assert level.n_simulated == 1041
        assert level.n_simulated - level.n_executable == 4, (
            "the four uncopyable buys are the two dead-pool and two migrated-pool positions, "
            "whose horizon reserves cannot absorb the leader's own clip"
        )


def test_gas_is_charged_and_binds_nothing_and_both_halves_are_measured(chain, result):
    """The docstring in ``report.py`` used to claim gas made small clips uncopyable. It does not.

    Same ladder, ``gas_usd=0``: the same four buys are uncopyable, and the largest amount $15 of
    gas adds to a surviving buy's total execution cost is ``0.00015`` at the $100k level — where the
    follower's order is bounded by the AUM, so the charge is exactly ``15/100000``. At the top level
    the cost cap binds instead and the sizing search absorbs the gas entirely.
    """
    quotes = report_module._quote_assets()
    scored = report_module._scored(result)
    for level, expected_worst in (
        (CAPITAL_LEVELS[0], calc("0.00015")),
        (CAPITAL_LEVELS[-1], calc("0.000000000001")),
    ):
        uncopyable_with_gas = 0
        uncopyable_without = 0
        worst = calc("0")
        for wallet in scored:
            for account in wallet.accounts:
                charged = report_module._simulate(chain, account, level, quotes)
                free = size_to_cost_cap(
                    report_module._priced_pool(chain, account.buy.asset, quotes),
                    report_module.SYNTHETIC_TIER, level, account.cost_usd, calc("0"),
                    leader_return=account.return_pct,
                )
                uncopyable_with_gas += 0 if charged.copyable else 1
                uncopyable_without += 0 if free.copyable else 1
                if charged.copyable and free.copyable:
                    difference = sub(charged.execution_cost_pct, free.execution_cost_pct)
                    worst = difference if difference > worst else worst
        assert uncopyable_with_gas == uncopyable_without == 4
        assert worst <= expected_worst
    assert report_module.GAS_USD == calc("15")


# -- what this fixture does NOT reach -------------------------------------------


def test_the_paths_this_fixture_does_not_exercise_are_listed_with_their_measured_zero(result):
    """Every one of these is a path a reader might assume the end-to-end run covered. It does not."""
    assert result.census.counts[ClassificationStatus.CIRCULAR_ARBITRAGE] == 0
    assert result.census.counts[ClassificationStatus.NO_CLEAR_ENDPOINT] == 0
    assert result.census.counts[ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL] == 0
    assert result.census.counts[ClassificationStatus.FAILED_TRANSACTION] == 0
    assert result.census.counts[ClassificationStatus.UNSUPPORTED] == 0
    assert len(result.quarantine) == 0, "no reconciliation-queue case is produced"
    assert result.stages.fifo_books_quarantined == 0
    assert result.stages.netting_quarantined == 0
    assert len(result.excluded) == 0, "no §8 attribution exclusion is produced"
    assert result.attribution.fallback == 0, "no TX_SENDER_FALLBACK attribution is produced"
    assert result.stages.wallets_unscorable == 0
    assert sum(account.late_sold_raw for account in result.accounts) == 0, (
        "no §4.4 Case-2 sale after a buy's own 30-day horizon is produced"
    )


def test_the_quote_assets_this_fixture_never_uses(chain):
    """Two of the four §4.6 quote assets are never priced, so their conversion path is untested."""
    from contracts import QUOTE_ASSETS

    used = {pool.quote for pool in chain.pools.values()}
    assert used == {WETH, USDC}
    assert len(QUOTE_ASSETS) == 4
    assert set(chain.prices) == {WETH, USDC}


def test_only_one_of_the_four_walk_forward_windows_is_reported(run):
    """§6.3 fixes four windows and §7.4 requires three to pass. This run has one, and says so."""
    assert [window.window for window in run.report.windows] == [1]
    assert run.report.missing_windows == (2, 3, 4)


def test_the_two_gating_columns_are_reported_missing_rather_than_computed(run):
    """There is no §6.6 matched benchmark here, so there is no advantage to report."""
    from reporting import GATING_COLUMNS

    window = run.report.windows[0]
    assert window.columns == ()
    assert window.missing_columns == GATING_COLUMNS
    assert len(GATING_COLUMNS) == 2


def test_the_long_tail_exclusion_path_is_not_reached_and_the_reason_is_stated():
    """``depth.cost_cap_for`` raises for ``LONG_TAIL``, so a long-tail fixture has no ladder."""
    from contracts import AssetTier, LongTailExcludedError
    from depth import cost_cap_for

    assert report_module.SYNTHETIC_TIER is AssetTier.MID_CAP
    with pytest.raises(LongTailExcludedError):
        cost_cap_for(AssetTier.LONG_TAIL)
