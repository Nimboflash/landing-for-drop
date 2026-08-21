"""``tools.case_runs``, pinned: the §4.5 section, and the two things the four cases published.

``tests/hand_computed/test_case_survey.py`` pins the *survey* — three marks produced by calling
:func:`marking.mark_position` directly on three real pool snapshots. This file pins the parts of
``tools.case_runs`` that the survey cannot reach, and it exists because of how they failed.

**The §4.5 section had never executed.** ``report_depth`` was written against an imagined
:mod:`depth` API and ran only after the four cases had already printed several hundred lines, so
the run *looked* finished and exited 1 into a terminal nobody read the bottom of. Three separate
mismatches sat behind each other — the price book passed in the seam's shape rather than the
reader's, ``SizingResult.depth``/``.cost`` fields that do not exist, and a v3 pool state whose
reserves were left at zero, which is the one input :func:`depth.measure_depth` refuses by name.
Each was only reachable once the one in front of it was fixed. Nothing in a 3,098-test suite
noticed, because nothing in it ran the file.

So the rule this file applies is narrow and literal: **execute the section, and pin what it
publishes.** Every expected value below is a chain read or is computed by hand from chain reads,
and the arithmetic is written out.

Nothing here opens a socket: ``REPLAY_ONLY`` against ``tests/fixtures/case_runs/recordings``, with
``urllib.request.urlopen`` poisoned.
"""

import urllib.request
from decimal import Decimal

import pytest

from contracts import AssetTier
from depth import DepthModel
from transport import REPLAY_ONLY, RecordingCache, RpcClient

from tools import case_runs

# -- the pool, as three independent sources read it ------------------------------
#
# Uniswap v3 USDC/WETH 0.05%, 0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640, at block 16943478.
# Confirmed against eth.blockscout.com's JSON-RPC — a provider that is not one of the three the
# recordings came from — on 2026-08-11.

V3_LIQUIDITY = 37_039_663_111_270_122_380
V3_SQRT_PRICE_X96 = 1_870_569_395_896_101_347_464_491_938_479_807
V3_USDC_BALANCE = 121_242_053_246_095
V3_WETH_BALANCE = 65_495_754_303_876_223_786_599

#: Uniswap v2 USDT/WETH, 0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852, same block. ``token0`` is
#: WETH and ``token1`` USDT, so the pair the report prints is the *swapped* one — attributing them
#: the other way round produces a plausible price wrong by the ratio of the two.
V2_USDT_RESERVE = 28_661_664_595_256
V2_WETH_RESERVE = 16_014_784_737_252_958_670_584

#: Chainlink ETH/USD ``latestRoundData().answer`` at the horizon, 8 decimals: $1,793.10.
CHAINLINK_ETH_ANSWER = 179_310_000_000
WETH_USD_PER_RAW = Decimal("1.7931E-15")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Replay-only is the claim; a poisoned socket is the proof."""

    def refuse(*args, **kwargs):
        raise AssertionError(
            "tests/hand_computed/test_case_runs.py opened a real connection. Every byte it reads "
            "comes from the committed snapshot; a test that reaches the chain pins today's answer "
            "rather than the one these literals were checked against."
        )

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture(scope="module")
def client():
    return RpcClient(
        endpoints=("https://replay.invalid",),
        cache=RecordingCache(case_runs.RECORDINGS),
        mode=REPLAY_ONLY,
    )


@pytest.fixture(scope="module")
def prices():
    replay = RpcClient(
        endpoints=("https://replay.invalid",),
        cache=RecordingCache(case_runs.RECORDINGS),
        mode=REPLAY_ONLY,
    )
    return case_runs.read_prices(replay)


# -- the price book, in both of its shapes ---------------------------------------


def test_the_price_book_reader_returns_triples_and_the_seam_takes_scalars(prices):
    """The mismatch that took the whole §4.5 section down, pinned as a shape.

    :func:`case_runs.read_prices` answers ``{asset: (usd_per_raw_unit, raw_answer, decimals)}``
    because :func:`case_runs.read_depth_pool` needs the decimals to build a
    :class:`depth.QuoteAsset`. ``run`` also derives a flat ``{asset: usd}`` for
    ``run_wallet_window``, whose seam takes one scalar per quote asset. Passing the flat one to the
    depth reader raised ``TypeError: cannot unpack non-iterable decimal.Decimal object``.
    """
    usd, answer, decimals = prices[case_runs.WETH]

    assert answer == CHAINLINK_ETH_ANSWER
    assert decimals == 18
    # 179310000000 / 10^8 = 1793.10 USD per WETH; / 10^18 = 1.7931E-15 per raw unit.
    assert usd == WETH_USD_PER_RAW


# -- §4.5 on the real constant-product pool --------------------------------------


def test_the_usdt_weth_pair_is_read_with_its_sides_the_right_way_round(client, prices):
    """``token0()`` decides, and for this pair ``token0`` is WETH."""
    priced, state = case_runs.read_depth_pool(client, prices)

    assert (state.asset_reserve_raw, state.quote_reserve_raw) == (
        V2_USDT_RESERVE, V2_WETH_RESERVE,
    )
    assert state.fee_bps == 30
    assert priced.quote.decimals == 18


def test_effective_depth_is_the_quote_reserve_in_usd_for_a_constant_product_pool(client, prices):
    """16,014,784,737,252,958,670,584 raw WETH x 1.7931E-15 USD = $28,716,110.512368280192224170.4

    Constant product has no ticks to cross, so the validity band is unbounded and the model
    publishes no TVL-understatement factor: for ``x*y=k`` the real and the near-spot reading are
    the same number by construction.
    """
    from depth import measure_depth

    priced, _state = case_runs.read_depth_pool(client, prices)
    measured = measure_depth(priced)

    assert measured.model is DepthModel.CONSTANT_PRODUCT
    assert measured.quote_reserve_raw == V2_WETH_RESERVE
    assert measured.effective_depth_usd == Decimal(
        "28716110.512368280192224170400000000000"
    )
    # S1 is one percent of it.
    assert measured.s1_usd == Decimal("287161.10512368280192224170400000000000")
    assert measured.validity_band.max_size_usd is None
    assert measured.tvl_understatement_factor is None


def test_the_cost_cap_and_not_the_wallet_is_what_bounds_the_follower(client, prices):
    """$1,000,000 of capital against a $28.7m pool: the 1% major cap binds first.

    The order comes out at $197,223.22577727156859241306639156623594 — 19.7% of the capital — and
    the four priced components sum to the cap to within the last digits the frozen context carries.
    A run where ``binding_constraint`` came back ``strategy_aum`` would be a run against a pool too
    thin for this test to say anything about the cap.
    """
    priced, _state = case_runs.read_depth_pool(client, prices)

    detail = case_runs.size_to_cost_cap_detail(
        pool=priced, tier=case_runs.DEPTH_TIER,
        strategy_aum=Decimal(case_runs.DEPTH_AUM_USD),
        leader_clip=Decimal(case_runs.DEPTH_LEADER_CLIP_USD),
        gas_usd=Decimal(case_runs.DEPTH_GAS_USD),
    )

    assert detail.tier is AssetTier.MAJOR
    assert detail.cost_cap == Decimal("0.01")
    assert detail.copyable is True
    assert detail.rejection_reason is None
    assert detail.binding_constraint == "cost_cap"
    assert detail.order_usd == Decimal("197223.22577727156859241306639156623594")
    assert detail.costs.dex_fee_pct == Decimal("0.003")
    assert detail.costs.liquidity_limitation_pct == 0
    assert detail.pool_depth_at_trade_usd == Decimal(
        "28716110.512368280192224170400000000000"
    )


# -- §9.6 on the real concentrated pool ------------------------------------------


def test_the_v3_pool_is_read_with_both_of_its_depth_readings(client, prices):
    """Balances *and* ``(L, sqrt(P))``. Leaving the balances at zero is a drained pool.

    ``depth.measure_depth`` bounds ``virtual/real`` against the measured 5-23x understatement band
    and cannot perform that check against a zero, so it quarantines the state by name. An earlier
    shape of ``read_v3_pool`` supplied exactly that state, on the reasoning that a zero reserve is
    what sends ``marking.liquidity.effective_reserves`` down its virtual branch — which handed both
    modules a fabrication instead of the pool.
    """
    state, liquidity, sqrt_price, fee = case_runs.read_v3_pool(client, prices)

    assert (liquidity, sqrt_price, fee) == (V3_LIQUIDITY, V3_SQRT_PRICE_X96, 500)
    assert state.fee_bps == 5
    assert state.asset_reserve_raw == V3_USDC_BALANCE
    assert state.quote_reserve_raw == V3_WETH_BALANCE


def test_the_measured_understatement_factor_lands_inside_the_band_a10_4_measured(client, prices):
    """The first real ``(L, sqrt(P))`` pair this repository has priced. By hand::

        y_v = L * sqrtP // 2^96 = 874,502,929,911,689,640,748,249 raw WETH
        y_real                  =  65,495,754,303,876,223,786,599 raw WETH
        y_v / y_real            = 13.352055247036586715052181565147471157

    A10.4 measured TVL to understate near-spot depth on concentrated pools by 5-23x. 13.35 sits
    inside that, which is a confirmation and not a tautology: the band came from a different
    sample, and the number could as easily have landed outside it — in which case ``depth`` would
    have quarantined this pool rather than priced it.
    """
    from depth import PricedPool, QuoteAsset, measure_depth

    state, _liquidity, _sqrt_price, _fee = case_runs.read_v3_pool(client, prices)
    usd, _answer, decimals = prices[case_runs.WETH]
    measured = measure_depth(PricedPool(
        state=state,
        quote=QuoteAsset(address=case_runs.WETH, decimals=decimals,
                         usd_price=usd * (Decimal(10) ** decimals)),
    ))

    assert measured.model is DepthModel.CONCENTRATED_VIRTUAL_RESERVES
    assert measured.virtual_quote_reserve_raw == 874_502_929_911_689_640_748_249
    assert measured.tvl_understatement_factor == Decimal(
        "13.352055247036586715052181565147471157"
    )
    # 5 and 23 written out rather than imported: importing the band from the module under test
    # would make this assertion pass at any band, which pins nothing.
    assert Decimal("5") < measured.tvl_understatement_factor < Decimal("23")
    # Past ~1% the single-band model stops describing the pool, so the band is finite here where
    # constant product's was None.
    assert measured.validity_band.max_size_usd == measured.s1_usd
    assert measured.validity_band.max_own_slippage == Decimal("0.01")


def test_marking_prices_that_same_state_on_the_band_and_not_on_the_balances(client, prices):
    """The two modules must agree about which curve a real v3 pool is.

    ``depth`` decided by the presence of ``active_liquidity``; ``marking`` decided by whether the
    reserves happened to be non-zero, and a real v3 pool's always are. So the same state was
    concentrated to one module and constant-product to the other, and the mark went out tagged
    ``model=constant_product_reserves``.
    """
    from marking.liquidity import MODEL_VIRTUAL_RESERVES, effective_reserves

    state, _liquidity, _sqrt_price, _fee = case_runs.read_v3_pool(client, prices)
    asset_reserve, quote_reserve, model = effective_reserves(state)

    assert model == MODEL_VIRTUAL_RESERVES
    assert (asset_reserve, quote_reserve) == (
        1_568_818_807_199_339, 874_502_929_911_689_640_748_249,
    )


# -- Permit2, pinned against the log it was admitted on --------------------------
#
# ``tests/hand_computed/test_event_registry.py`` pins the entries ticket 20 added against receipts
# in its own snapshot. This one was found here, on this snapshot, so it is pinned here.

WALLET_B = "0xd42b85640c30ed0c3537daf352bb917d4a836092"
SBET = "0x14c256e65300026b76247e45554bb645c2c294ff"

#: wallet_b's five-lot FIFO sell. The case the whole ``wallet_b`` fixture exists for.
SELL_TX = "0x4efd26163a090cc1fea9faab608273fd0aaffb196a830ed990b0b7f86b4489e1"
PERMIT2 = "0x000000000022d473030f116ddee9f6b43ac78ba3"


def test_the_permit2_log_is_an_allowance_and_names_no_amount_that_moved(client):
    """Log 195 of the sell receipt, word by word.

        topic0   0xc6a377bf…  Permit(address,address,address,uint160,uint48,uint48)
        topic1   owner    = 0xd42b85640c30ed0c3537daf352bb917d4a836092   (wallet_b)
        topic2   token    = 0x14c256e65300026b76247e45554bb645c2c294ff   (SBET)
        topic3   spender  = 0xef1c6e67703c7bd7107eed8303fbe6ec2554bf6b   (the sell router)
        data[0]  amount   = 2^160 - 1        an unlimited allowance
        data[1]  expiry   = 1677818028
        data[2]  nonce    = 0

    Not one of the six is a quantity that changed hands. The falsification is the same one the
    other non-mover entries answer: if the event were the only record of a movement, the receipt
    would not *also* carry the ERC-20 ``Transfer`` legs — and it does, which the next test reads.
    """
    from ingest import PERMIT2_PERMIT, NoValueEvent, decode_log, logs_of, require_receipt

    receipt = require_receipt(client, SELL_TX)
    log = [item for item in logs_of(receipt)
           if item["topics"][0].lower() == PERMIT2_PERMIT][0]

    assert log["address"].lower() == PERMIT2
    assert len(log["topics"]) == 4
    assert log["topics"][1][-40:].lower() == WALLET_B[2:]
    assert log["topics"][2][-40:].lower() == SBET[2:]
    assert log["topics"][3][-40:].lower() == "ef1c6e67703c7bd7107eed8303fbe6ec2554bf6b"
    assert (len(log["data"]) - 2) // 64 == 3
    assert int(log["data"][2:66], 16) == 2 ** 160 - 1
    assert int(log["data"][66:130], 16) == 1_677_818_028
    assert int(log["data"][130:194], 16) == 0

    assert isinstance(decode_log(log), NoValueEvent)


def test_the_permit_restates_nothing_and_the_sbet_legs_are_ordinary_transfers(client):
    """The wallet's SBET leaves in two ERC-20 ``Transfer`` logs, not in the ``Permit``.

    5,382,920,000,000,000,000,000,000 raw to the pair and 468,080,000,000,000,000,000,000 raw as
    the token's transfer tax — 5,851,000,000,000,000,000,000,000 debited in total, an 8.0% tax.
    Admitting the ``Permit`` as a non-mover therefore cannot lose a leg: both legs are already
    decodable movements in the same receipt.
    """
    from ingest import TRANSFER, logs_of, require_receipt

    receipt = require_receipt(client, SELL_TX)
    padded = "0x" + "0" * 24 + WALLET_B[2:]
    out = [int(log["data"], 16) for log in logs_of(receipt)
           if log["topics"][0].lower() == TRANSFER
           and log["address"].lower() == SBET
           and log["topics"][1].lower() == padded]

    assert sorted(out) == [468_080_000_000_000_000_000_000, 5_382_920_000_000_000_000_000_000]
    assert sum(out) == 5_851_000_000_000_000_000_000_000


# -- the conservation the census does not check ----------------------------------


def test_an_unread_transaction_moved_the_very_asset_two_wallets_marks_rest_on(client):
    """The census conserves over transactions. Nothing conserves over assets, and it shows.

    Both marked SBET positions in this case set are of tokens the wallet had already sold, in a
    transaction sitting in the ingestion queue:

    * ``wallet_b`` — 5,851,000,000,000,000,000,000,000 raw left in ``0x4efd2616…``, against
      5,851,509,734,777,355,780,241,633 raw marked open across five lots. The wallet held
      509,734,777,355,780,241,633 — **0.0087%** of what was marked;
    * ``multihop`` — 4,039,659,156,968,642,594,779,227 raw left in ``0xe9aa4509…``, against
      4,039,659,156,968,642,594,779,227 raw marked open. To the raw unit: the wallet sold the
      **whole** position and the run marked all of it.

    Both receipts are refused for the same reason and it is not the ``Permit``: each carries two
    WETH ``Withdrawal`` legs and the wallet's own archive balance accounts for one of them, so
    where the other settled is not established. The seam takes ``{log_index: address}`` and has no
    way to say "this leg I know, that one I do not", so the whole receipt goes to the queue — and
    the queue is not linked to the marks it invalidates by anything at all.

    Pinned as a *finding*, not as a fix: the fix is a trace, or a seam that admits a partially
    established receipt, and neither is this file's to build.
    """
    from ingest import TRANSFER, logs_of, require_receipt

    padded = "0x" + "0" * 24 + WALLET_B[2:]
    receipt = require_receipt(client, SELL_TX)
    left = sum(int(log["data"], 16) for log in logs_of(receipt)
               if log["topics"][0].lower() == TRANSFER
               and log["address"].lower() == SBET
               and log["topics"][1].lower() == padded)

    marked_open = (
        1_404_114_765_260_775_971_113_836
        + 470_522_696_491_540_940_549_350
        + 288_332_611_968_442_146_123_659
        + 2_333_829_004_064_394_261_926_051
        + 1_354_710_656_992_202_460_528_737
    )
    assert marked_open == 5_851_509_734_777_355_780_241_633
    assert left == 5_851_000_000_000_000_000_000_000
    # What the wallet actually still held, and what tools/case_survey.py measured independently.
    assert marked_open - left == 509_734_777_355_780_241_633


# -- the section runs at all -----------------------------------------------------


def test_report_depth_executes_end_to_end_and_returns_both_measurements(client, prices, capsys):
    """The test that would have caught all three mismatches: call the function.

    It asserts almost nothing about the text. What it pins is that ``report_depth`` reaches its
    ``return`` — which is the whole of what was broken, three times over, under a suite that was
    green throughout.
    """
    detail, v3_state, v2_depth, v3_depth = case_runs.report_depth(client, prices)

    assert detail.copyable is True
    assert v3_state.active_liquidity == V3_LIQUIDITY
    assert v2_depth.model is DepthModel.CONSTANT_PRODUCT
    assert v3_depth.model is DepthModel.CONCENTRATED_VIRTUAL_RESERVES

    printed = capsys.readouterr().out
    assert "USDT/WETH v2" in printed
    assert "USDC/WETH" in printed
