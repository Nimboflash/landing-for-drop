"""The case survey, pinned: real inputs for the paths no real byte had reached, every number a literal.

``tests/hand_computed/test_tracer_bullet_window.py`` pins §4.4 **Case 1** — a buy sold in full
inside the window, ``open_raw == 0``, no pool state needed anywhere in the run. This file pins what
that left untouched: a position still open at the marking horizon, a pool that is dead by all three
§9.1 conditions, one sale spanning five lots, a two-hop route, a token whose trading start is inside
the window, and two different kinds of fee-on-transfer.

Nothing here opens a socket. ``tools.case_survey`` runs in ``REPLAY_ONLY`` against
``tests/fixtures/case_survey/recordings`` and ``urllib.request.urlopen`` is poisoned, so a test that
reached the chain fails loudly rather than quietly pinning today's answer.

What this file is evidence for
------------------------------

* :mod:`marking` and :mod:`depth` — 2,378 lines that had never seen a chain byte — now produce
  three marks from three real pool snapshots, and all three are pinned here as literals;
* the §9.1 conjunction is load-bearing on real data and not only in constructed tests: one position
  satisfies condition 2 alone and is **not** zeroed, one satisfies all three and is;
* two ways the amount received differs from the amount sent, one of which no reading of the logs
  can correct.

What it is not
--------------

Not a golden set, not an account selection, and not a measurement of anything. Two wallets are two
wallets; see ``tools/case_survey.py`` for how they were found and what that population is worth.

On the one number that does not agree to the last digit
--------------------------------------------------------

:data:`RESIDUAL_MARK_USD` is the implementation's, and a single-expression computation of the same
quantity at 60 digits ends ``…759596`` where the seam ends ``…759595``. That is one unit in the
last of 38 places, and it is the documented consequence of the seam rounding at each step
(``divide`` then ``multiply``) rather than once at the end. It is recorded here rather than papered
over, because a reader checking these literals with a calculator will find it.
"""

import os
import urllib.request
from decimal import Decimal

import pytest

from contracts import PoolState, PoolStatus, TokenAgeBucket, ValueBasis
from marking import mark_position
from marking.age import token_age_bucket
from transport import REPLAY_ONLY, RecordingCache, RpcClient

from tools import case_survey
from tools.case_survey import (
    DEAD_HOLDER,
    DEAD_HOLDER_CREDITED_RAW,
    DEAD_HOLDER_LOT,
    DEAD_PAIR,
    DEAD_PAIR_CREATED_BLOCK,
    DEAD_TOKEN,
    DEAD_VENUE,
    HORIZON_BLOCK,
    MEASUREMENT_TAIL_SECONDS,
    MULTIHOP_CREDITED_RAW,
    MULTIHOP_SWAP_OUT_RAW,
    MULTIHOP_TAX_RAW,
    SBET,
    SBET_PAIR,
    SBET_PAIR_CREATED_BLOCK,
    SBET_TRADING_START_BLOCK,
    SBET_TRADING_START_TS,
    SBET_VENUE,
    SurveyRefused,
    WALLET_A,
    WALLET_A_LOTS,
    WALLET_A_OPEN_RAW,
    WALLET_B,
    WALLET_B_LOTS,
    WALLET_B_OPEN_RAW,
    WALLET_B_SELL_BLOCK,
    WALLET_B_SELL_DEBITED_RAW,
    WALLET_B_SELL_TAX_RAW,
    WALLET_B_SELL_TO_POOL_RAW,
    WALLET_B_SELL_TX,
    WINDOW_END_BLOCK,
    confirm_credited_amounts,
    confirm_fifo_consumption,
    confirm_horizon,
    confirm_multi_hop,
    confirm_native_proceeds,
    confirm_no_replacement_for,
    confirm_position,
    confirm_the_v3_pool_is_not_a_replacement,
    confirm_trading_start,
    confirm_venue,
)

# -- the snapshot ---------------------------------------------------------------

#: Every ``(call, answer)`` in the committed snapshot, hashed. Asserted beside the count because the
#: two say different things: the count says how much evidence there is, and the hash says it is the
#: same evidence these literals were read off.
SNAPSHOT_FINGERPRINT = "5bdafc7acb9156f9e81f05b9e48718841b6cfbf5c75b693e03b6571cffb451c0"
SNAPSHOT_CALLS = 496

#: What a run *makes*, which is one more than the snapshot *holds*: the sale's receipt is read
#: twice, once for its transfer legs and once for its gas. The two numbers are asserted separately
#: because a call added to the survey and a call added to the snapshot are different events.
SURVEY_CALLS = 497

# -- the price book -------------------------------------------------------------

#: Chainlink ETH/USD ``latestRoundData().answer`` at the horizon block, 8 decimals: $1,793.10.
CHAINLINK_ETH_ANSWER = 179310000000
#: ``179310000000 / 10**(8 + 18)``.
WETH_USD_PER_RAW = Decimal("1.7931E-15")

# -- what the three marks come to ------------------------------------------------
#
# Each is ``quantity x average_exit_price x price``, with the constant-product average exit price
#
#     avg = (10000 - 30) * quote_reserve / (10000 * asset_reserve + (10000 - 30) * quantity)
#
# and the §4.4 minimum taken against ``quantity x (quote_reserve / asset_reserve) x price``. The
# numbers below were computed from the reserves at a separate 60-digit precision, not by calling
# the code under test with a different spelling.

#: 11,831,462,774,808,522,772,923,324 raw SBET against reserves of 90,396,688,352,888,500,346,836,453
#: SBET and 25,786,853,741,718,141,371 wei. The position is 13.09% of the pool's token reserve, so
#: the bound bites: spot is $6,051.86 and the realisable exit is $714.62 less.
OPEN_MARK_USD = Decimal("5337.2405597113265805265733578442336486")
OPEN_SPOT_USD = Decimal("6051.8588281435176749143505902788649426")
OPEN_SHORTFALL = Decimal("0.11808244")

#: 509,734,777,355,780,241,633 raw in the same pool — 0.00056% of it, so the bound is 0.3% and the
#: mark is essentially spot. Twenty-six cents, against a minimum exit threshold of one dollar.
RESIDUAL_MARK_USD = Decimal("0.25994850775847457589111513497642237595")
RESIDUAL_SPOT_USD = Decimal("0.26073216567274990850118653844124394683")

#: The dead pool's exit for the holder's whole position: two ten-billionths of a dollar. It is the
#: number ``DEAD_ZEROED`` replaces with an exact zero, and it is written out here because "the exit
#: was below the threshold" is a different claim from "the pool could not be priced".
#:
#: As text, because that is how the evidence trail carries it: ``marking.mark._fixed`` formats with
#: ``'f'`` and never in exponent notation, deliberately, so that §9.2 can re-derive a mark from the
#: record. ``str(Decimal(...))`` of the same value is ``2.037…E-10`` and would not match.
DEAD_EXIT_TEXT = "0.00000000020370230847771090103982249042367244510"
DEAD_EXIT_USD = Decimal(DEAD_EXIT_TEXT)

# -- FIFO, by hand ---------------------------------------------------------------

#: ``1404114765260775971113836 + 470522696491540940549350 + 288332611968442146123659
#: + 2333829004064394261926051`` — lots one to four, which the sale consumes whole.
LOTS_ONE_TO_FOUR = 4496799077785153319712896

#: ``5851000000000000000000000 - 4496799077785153319712896`` — what the sale takes out of lot five.
PARTIAL_CONSUMPTION = 1354200922214846680287104

#: ``1354710656992202460528737 - 1354200922214846680287104`` — what lot five keeps, and what the
#: wallet's ``balanceOf`` reads at the horizon 411,865 blocks later.
LOT_FIVE_REMAINDER = 509734777355780241633

# -- fee-on-transfer, by hand ----------------------------------------------------

#: ``11335529769194231 - 11108819173810347``. The rug token credited 98% of what its own
#: ``Transfer`` log said moved, and wrote nothing anywhere about the other 2%.
UNLOGGED_SHORTFALL = 226710595383884


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Replay-only is the claim; a poisoned socket is the proof."""

    def refuse(*args, **kwargs):
        raise AssertionError(
            "tests/hand_computed/test_case_survey.py opened a real connection. Every byte it reads "
            "comes from the committed snapshot; a test that reaches the chain pins today's answer "
            "rather than the one these literals were checked against."
        )

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture(scope="module")
def client():
    return RpcClient(
        endpoints=("https://replay.invalid",),
        cache=RecordingCache(case_survey.RECORDINGS),
        mode=REPLAY_ONLY,
    )


@pytest.fixture(scope="module")
def survey():
    """The whole survey, run once against the snapshot. Returns its three marks."""
    replay = RpcClient(
        endpoints=("https://replay.invalid",),
        cache=RecordingCache(case_survey.RECORDINGS),
        mode=REPLAY_ONLY,
    )
    marks = case_survey.run(replay)
    replayed, live = replay.replayed_count()
    assert live == 0, "the survey went to the network for {} call(s)".format(live)
    assert replayed == SURVEY_CALLS
    return marks


class CannedClient(object):
    """A client that answers from a script, for the guards whose trigger the chain does not supply.

    Five refusals in ``tools.case_survey`` fire on inputs no recording holds and none ever will —
    a pool that served a swap *after* its stated last one, a block where the stated first swap is
    not, a receipt in which the wallet does hold the intermediate, a token with a second pool where
    the survey says there is none. Recording those would mean writing bytes into the snapshot that
    no node ever sent, which is a far worse thing to have in a fixture directory than a stub that
    is obviously a stub.

    So: everything the *positive* path asserts comes from the committed snapshot, and only the
    negative path is scripted. ``receipt`` may be built by editing a real recorded receipt, which is
    what :func:`test_an_intermediate_the_wallet_does_hold_is_refused` does.
    """

    def __init__(self, logs=None, receipt=None, eth_call=None):
        self._logs = logs or (lambda **kwargs: [])
        self._receipt = receipt
        self._eth_call = eth_call or {}

    def get_logs(self, from_block=None, to_block=None, address=None, topics=None):
        return self._logs(from_block=from_block, to_block=to_block, address=address, topics=topics)

    def get_transaction_receipt(self, tx_hash):
        return self._receipt

    def get_block_by_number(self, block, full_transactions=False):
        return {"timestamp": hex(0)}

    def call(self, method, params=None):
        if method != "eth_call":
            raise AssertionError("CannedClient was asked for {}".format(method))
        return self._eth_call[params[0]["data"][:10]]


def _word(value):
    """An int as a 32-byte return word, the way a node hands one back."""
    return "{:064x}".format(value)


def _swap_log(block, address):
    return {
        "blockNumber": hex(block), "logIndex": "0x0", "address": address,
        "topics": [case_survey.SWAP_V2, case_survey.word(address), case_survey.word(address)],
        "data": "0x" + _word(0) * 4,
    }


# -- the snapshot is the evidence ------------------------------------------------


def test_the_snapshot_is_present():
    assert os.path.isdir(case_survey.RECORDINGS), (
        "the case survey's snapshot is missing; re-record it with "
        "`PYTHONPATH=src python -m tools.case_survey --record`"
    )


def test_the_snapshot_the_literals_were_read_off_is_pinned():
    """Both numbers, because they fail differently.

    The count moving means a call was added or dropped. The fingerprint moving with the count
    unchanged means an *answer* changed under a call that still exists — a re-recording against a
    node that returned something else — and that is the failure that would otherwise slide past.
    """
    cache = RecordingCache(case_survey.RECORDINGS)
    assert len(cache.entries()) == SNAPSHOT_CALLS
    assert cache.fingerprint() == SNAPSHOT_FINGERPRINT


def test_the_survey_replays_with_no_socket(survey):
    assert set(survey) == {"A open", "B residual", "dead holder"}


# -- the horizon and §4.7 --------------------------------------------------------


def test_the_horizon_is_thirty_days_past_the_window(client):
    """Not asserted from the constant: the window's own last block plus 2,592,000 seconds."""
    horizon_ts = confirm_horizon(client)
    assert horizon_ts == 1680220799
    window_end_ts = case_survey.read_timestamp(client, WINDOW_END_BLOCK)
    assert window_end_ts == 1677628799
    assert window_end_ts + MEASUREMENT_TAIL_SECONDS == 1680220799
    assert case_survey.read_timestamp(client, HORIZON_BLOCK - 1) == 1680220787


def test_the_trading_start_is_inside_the_window_and_needs_two_events(client):
    """§4.7's start is where liquidity and a swap both hold — here, four blocks apart.

    Ticket 19's XUSDP was minted and first swapped in the same block, twenty-one months before its
    window, so "the first block at which both hold" never had to be decided there. Here the pair is
    created at 16530898, funded at 16530944 and first swapped at 16530948, and only the third of
    those is the start.
    """
    start_block, start_ts = confirm_trading_start(client)
    assert (start_block, start_ts) == (SBET_TRADING_START_BLOCK, SBET_TRADING_START_TS)
    assert start_block == 16530948
    assert case_survey.SBET_FIRST_MINT_BLOCK == 16530944
    assert SBET_PAIR_CREATED_BLOCK < case_survey.SBET_FIRST_MINT_BLOCK < start_block
    assert start_block <= WINDOW_END_BLOCK


@pytest.mark.parametrize(
    "block, timestamp, expected",
    [
        # wallet A, four lots: block ages 4, 20, 86, 170; time ages 48, 240, 1032, 2040 seconds.
        (16530952, 1675218095, TokenAgeBucket.A),
        (16530968, 1675218287, TokenAgeBucket.B),
        (16531034, 1675219079, TokenAgeBucket.B),
        (16531118, 1675220087, TokenAgeBucket.B),
        # wallet B, five lots: block ages 5, 8, 13, 17, 21.
        (16530953, 1675218107, TokenAgeBucket.A),
        (16530956, 1675218143, TokenAgeBucket.A),
        (16530961, 1675218203, TokenAgeBucket.B),
        (16530965, 1675218251, TokenAgeBucket.B),
        (16530969, 1675218299, TokenAgeBucket.B),
    ],
)
def test_every_lot_lands_in_a_real_age_bucket(block, timestamp, expected):
    """Both §4.7 buckets that a token launched inside a window can produce, on real trades.

    The boundary is block age 10 and it falls between wallet B's second and third lot — 8 blocks
    and 13 blocks after the first swap — so the A/B line is crossed by two consecutive buys of the
    same wallet, minutes apart. No fixture chose that.
    """
    assert token_age_bucket(block, timestamp, SBET_TRADING_START_BLOCK, SBET_TRADING_START_TS) is expected


# -- case 1: a position still open at the horizon --------------------------------


def test_wallet_a_never_disposed_of_anything(client):
    """Four buys, and not one outgoing transfer in 412,580 blocks.

    ``confirm_position`` reads every ``Transfer`` of the token with this wallet on either side
    across the whole range in 10,000-block slices — 42 of them per side — and this assertion is
    that the answer is *exactly* the four lots. Empty slices are the evidence; a sale hiding in one
    of them is what would otherwise turn a marked position into a realised one.
    """
    balance = confirm_position(
        client, SBET, WALLET_A, WALLET_A_LOTS, (), WALLET_A_OPEN_RAW, SBET_PAIR_CREATED_BLOCK
    )
    assert balance == WALLET_A_OPEN_RAW == 11831462774808522772923324
    assert sum(lot.logged_raw for lot in WALLET_A_LOTS) == WALLET_A_OPEN_RAW
    assert len(WALLET_A_LOTS) == 4


def test_the_open_position_is_bound_by_the_pool_and_not_by_spot(survey):
    """§4.4's ``min()`` is doing work here, and the difference is $714.62.

    The position is 13.09% of the pool's own token reserve. Marked at spot it is worth $6,051.86;
    walked down the curve it realises $5,337.24. This is the case the whole ``depth`` module exists
    for, and until this snapshot it had only ever been shown values somebody chose.
    """
    mark = survey["A open"]
    assert mark.value_usd == OPEN_MARK_USD
    assert mark.value_basis is ValueBasis.LIQUIDITY_BOUND
    assert mark.pool_status is PoolStatus.THIN
    assert mark.executable_quantity == WALLET_A_OPEN_RAW
    assert "spot_usd={}".format(OPEN_SPOT_USD) in mark.evidence
    assert "shortfall_vs_spot={}".format(OPEN_SHORTFALL) in mark.evidence
    # Quantized, because this subtraction is the one number here computed in the *ambient* context
    # rather than the frozen one — it is a reader's arithmetic, not the seam's.
    assert (OPEN_SPOT_USD - OPEN_MARK_USD).quantize(Decimal("0.01")) == Decimal("714.62")


# -- case 2: one sale over five lots ---------------------------------------------


def test_the_sale_spans_four_whole_lots_and_leaves_the_fifth_partly_consumed(client):
    whole, index, partial = confirm_fifo_consumption(
        WALLET_B_LOTS, WALLET_B_SELL_DEBITED_RAW, WALLET_B_OPEN_RAW
    )
    assert (whole, index, partial) == (4, 4, PARTIAL_CONSUMPTION)
    assert sum(lot.logged_raw for lot in WALLET_B_LOTS[:4]) == LOTS_ONE_TO_FOUR
    assert WALLET_B_SELL_DEBITED_RAW - LOTS_ONE_TO_FOUR == PARTIAL_CONSUMPTION
    assert WALLET_B_LOTS[4].logged_raw - PARTIAL_CONSUMPTION == LOT_FIVE_REMAINDER


def test_the_remainder_of_lot_five_is_what_the_chain_says_the_wallet_holds(client):
    """The FIFO arithmetic and the wallet's archive balance are two independent facts here.

    One is five ``Transfer`` logs and a subtraction; the other is ``balanceOf`` at a block 411,865
    later. They agree to the raw unit, which is what makes the partial lot a measurement rather
    than an inference.
    """
    disposals = (
        (WALLET_B_SELL_BLOCK, WALLET_B_SELL_TX, WALLET_B_SELL_TO_POOL_RAW),
        (WALLET_B_SELL_BLOCK, WALLET_B_SELL_TX, WALLET_B_SELL_TAX_RAW),
    )
    balance = confirm_position(
        client, SBET, WALLET_B, WALLET_B_LOTS, disposals, WALLET_B_OPEN_RAW,
        SBET_PAIR_CREATED_BLOCK,
    )
    assert balance == LOT_FIVE_REMAINDER == 509734777355780241633
    assert sum(lot.logged_raw for lot in WALLET_B_LOTS) - WALLET_B_SELL_DEBITED_RAW == balance


def test_a_twenty_six_cent_position_in_a_live_pool_is_not_dead(survey):
    """§9.1 condition 2 holds on its own here, and the position is marked anyway.

    Twenty-six cents is below the one-dollar minimum exit. Zeroing on that alone is the error the
    conjunction exists to prevent — the pool this sits in served a swap 3,768 seconds before the
    horizon — and this is the first time a real input has ever put the two conditions on opposite
    sides of each other.
    """
    mark = survey["B residual"]
    assert mark.value_usd == RESIDUAL_MARK_USD
    assert mark.value_basis is ValueBasis.POOL_MARKED
    assert mark.pool_status is PoolStatus.LIVE
    assert "cond2_exit_below_minimum=true" in mark.evidence
    assert "cond1_no_swap_for_30d=false" in mark.evidence
    assert "cond3_no_validated_replacement=true" in mark.evidence
    assert "dead_pool=false" in mark.evidence
    assert mark.value_usd < Decimal("1.00")
    assert "spot_usd={}".format(RESIDUAL_SPOT_USD) in mark.evidence


def test_the_sale_debits_more_than_it_credits_the_pool(client):
    """Fee-on-transfer, the kind the logs can correct: two legs out, one of them the tax.

    A netting pass that reads only the leg reaching the pool sees a disposal of 5,382,920e18 where
    the wallet was actually debited 5,851,000e18 — 8% short — and leaves 468,080e18 in a lot that
    never closes. The residual only reconciles against the debited figure.
    """
    debited, _credited = confirm_credited_amounts(client)
    assert debited == WALLET_B_SELL_DEBITED_RAW == 5851000000000000000000000
    assert WALLET_B_SELL_TO_POOL_RAW + WALLET_B_SELL_TAX_RAW == debited
    assert Decimal(WALLET_B_SELL_TAX_RAW) / Decimal(debited) == Decimal("0.08")


def test_the_sale_proceeds_arrive_with_no_log_and_the_balance_identity_closes(client):
    """The ETH the sale paid is invisible to logs, exactly as ticket 19's plain transfer was.

    The pool's WETH is unwrapped to a third-party router the wallet called instead of Uniswap's,
    and that contract forwards the ETH by an internal transfer. Nothing is emitted. The only
    evidence is the wallet's own archive balance across the block, plus the gas it paid — and it
    closes to the wei against the WETH the pool released, so the intermediary took nothing.
    """
    assert confirm_native_proceeds(client) == 696382285113914004
    assert case_survey.WALLET_B_PROCEEDS_WEI == 696382285113914004


# -- case 3: multi-hop -----------------------------------------------------------


def test_the_multi_hop_wallet_never_holds_the_intermediate(client):
    """USDT in, SBET out, and 503,774,480,161,845,292 wei of WETH that goes pool to pool.

    The intermediate is never credited to the wallet. An endpoint rule that treated every asset
    appearing in the transaction as a leg would report this wallet as having bought and sold WETH
    it never held, in a transaction where it did neither.
    """
    spent, middle, received = confirm_multi_hop(client)
    assert spent == 800000000
    assert middle == 503774480161845292
    assert received == MULTIHOP_CREDITED_RAW == 4039659156968642594779227


def test_the_pool_released_more_than_the_wallet_received(client):
    """Fee-on-transfer on the buy side: the ``Swap`` output is not what arrived."""
    confirm_multi_hop(client)
    assert MULTIHOP_SWAP_OUT_RAW - MULTIHOP_CREDITED_RAW == MULTIHOP_TAX_RAW
    assert MULTIHOP_SWAP_OUT_RAW == 4390933866270263689977420
    assert MULTIHOP_TAX_RAW == 351274709301621095198193


# -- case 4: a pool that is dead by all three conditions -------------------------


def test_the_dead_pool_satisfies_every_condition_separately(client, survey):
    """§9.1 is a conjunction and here, for the first time on real data, all three hold.

    Condition 1 is 5,003,772 seconds — 57.9 days — of measured silence: 42 empty log slices between
    the last swap and the horizon. Condition 2 is a pool holding 1,005,205,305,507 wei. Condition 3
    is a search of both Uniswap factories over every block from the pair's creation to the horizon
    that found the pair's own creation event and nothing else.
    """
    confirm_venue(client, DEAD_VENUE)
    confirm_no_replacement_for(client, DEAD_TOKEN, DEAD_PAIR, DEAD_PAIR_CREATED_BLOCK)
    mark = survey["dead holder"]
    assert mark.value_usd == 0
    assert mark.value_basis is ValueBasis.DEAD_ZEROED
    assert mark.pool_status is PoolStatus.DEAD
    assert mark.executable_quantity == 0
    for condition in ("cond1_no_swap_for_30d=true", "cond2_exit_below_minimum=true",
                      "cond3_no_validated_replacement=true",
                      "dead_pool=no_swap_for_30d+exit_below_minimum+no_validated_replacement"):
        assert condition in mark.evidence
    assert "primary_inactivity_s=5003772" in mark.evidence
    assert 5003772 > 30 * 24 * 60 * 60


def test_the_zeroed_position_was_not_worth_nothing_it_was_worth_two_ten_billionths(survey):
    """``DEAD_ZEROED`` replaces a computed number, and the number is in the evidence.

    That distinction is the difference between §9.1 and a price feed going stale: the exit *was*
    priced, on real reserves, and then zeroed because all three conditions held.
    """
    mark = survey["dead holder"]
    assert "extractable_usd={}".format(DEAD_EXIT_TEXT) in mark.evidence
    assert DEAD_EXIT_USD < Decimal("1.00")
    assert DEAD_EXIT_USD > 0


def test_the_holder_bought_once_and_never_moved_it(client):
    balance = confirm_position(
        client, DEAD_TOKEN, DEAD_HOLDER, (DEAD_HOLDER_LOT,), (), DEAD_HOLDER_CREDITED_RAW,
        DEAD_PAIR_CREATED_BLOCK,
    )
    assert balance == DEAD_HOLDER_CREDITED_RAW == 11108819173810347
    assert DEAD_HOLDER_LOT.block == 16530608


# -- case 5: the fee-on-transfer no log can correct ------------------------------


def test_the_credited_amount_is_not_the_amount_in_the_transfer_log(client):
    """The sharpest thing in the snapshot, and the reason both halves of the check exist.

    ``ingest.events`` reads ``Transfer`` logs and can do nothing else. On this token the log says
    11,335,529,769,194,231 raw arrived and the balance moved by 11,108,819,173,810,347 — 98% of it
    — with **no second log** anywhere in the receipt to account for the difference. A lot opened
    from the logs is 2.04% larger than the position the wallet actually holds, and every quantity
    derived from it inherits that. No test built from a value somebody chose would produce this.
    """
    _debited, credited = confirm_credited_amounts(client)
    assert credited == DEAD_HOLDER_CREDITED_RAW
    assert DEAD_HOLDER_LOT.logged_raw - credited == UNLOGGED_SHORTFALL == 226710595383884
    assert credited < DEAD_HOLDER_LOT.logged_raw
    # 11,335,529,769,194,231 x 49/50 = 11,108,819,173,810,346.38, so the credit is that rounded up
    # by one raw unit. Written out because "it is exactly 98%" is very nearly true and is not.
    assert credited != DEAD_HOLDER_LOT.logged_raw * 49 // 50
    assert credited == DEAD_HOLDER_LOT.logged_raw * 49 // 50 + 1


# -- the second venue that is not a replacement ----------------------------------


def test_the_v3_pool_exists_and_holds_nothing(client):
    """A second SBET venue was created inside the measurement period. It is empty.

    Recorded rather than omitted: leaving it out would be the flattering choice, because a second
    live venue would change what the marked position could actually be sold into. Its active
    liquidity at the horizon is zero and it had served no swap in the preceding 10,000 blocks.
    """
    liquidity, sqrt_price, fee = confirm_the_v3_pool_is_not_a_replacement(client)
    assert liquidity == 0
    assert fee == 3000
    assert sqrt_price == 22381130613336255217520001
    assert case_survey.SBET_V3_CREATED_BLOCK > WINDOW_END_BLOCK
    assert case_survey.SBET_V3_CREATED_BLOCK < HORIZON_BLOCK


def test_a_pool_with_no_liquidity_is_unmodelled_and_not_dead():
    """The real v3 state lands on ``UnmodelledPoolError``, which is not a zero.

    ``L = 0`` with a real ``sqrt_price_x96``: there is a price and there is no depth. Marking
    refuses rather than returning ``$0``, because "no model fits this pool" and "this pool is dead"
    are different facts and only the second is a measurement.
    """
    from marking.liquidity import UnmodelledPoolError

    empty = PoolState(
        address=case_survey.SBET_V3_POOL,
        asset=SBET,
        quote=case_survey.WETH,
        asset_reserve_raw=0,
        quote_reserve_raw=0,
        last_swap_block=case_survey.SBET_V3_CREATED_BLOCK,
        last_swap_timestamp=1677628799,
        fee_bps=30,
        active_liquidity=0,
        sqrt_price_x96=22381130613336255217520001,
    )
    with pytest.raises(UnmodelledPoolError):
        mark_position(
            remaining_raw=WALLET_A_OPEN_RAW, pool=empty, horizon_block=HORIZON_BLOCK,
            horizon_ts=1680220799, quote_usd=WETH_USD_PER_RAW,
        )


# -- the marks are reproducible from the recorded reserves alone -----------------


def test_the_marks_come_out_of_the_recorded_reserves_and_one_chainlink_round(client, survey):
    """Rebuilt from the snapshot's own numbers, outside :func:`case_survey.run`.

    Not a second spelling of the same call: the pool states are constructed here from the reserves
    ``confirm_venue`` read back off the chain, and the price from the Chainlink answer, so a
    ``Venue`` constant drifting away from what the recordings hold fails here rather than silently
    marking against a stale number.
    """
    asset_reserve, quote_reserve = confirm_venue(client, SBET_VENUE)
    price, answer = case_survey.read_quote_price(client, case_survey.CHAINLINK_ETH_USD, HORIZON_BLOCK)
    assert answer == CHAINLINK_ETH_ANSWER
    per_raw = price / Decimal(10) ** 18
    assert per_raw == WETH_USD_PER_RAW
    pool = PoolState(
        address=SBET_PAIR, asset=SBET, quote=case_survey.WETH,
        asset_reserve_raw=asset_reserve, quote_reserve_raw=quote_reserve,
        last_swap_block=16943170, last_swap_timestamp=1680217031, fee_bps=30,
    )
    rebuilt = mark_position(
        remaining_raw=WALLET_A_OPEN_RAW, pool=pool, horizon_block=HORIZON_BLOCK,
        horizon_ts=1680220799, quote_usd=per_raw,
    )
    assert rebuilt.value_usd == OPEN_MARK_USD == survey["A open"].value_usd


# -- every refusal in the survey, pinned -----------------------------------------
#
# Each test below deletes one guard's precondition rather than the guard, and requires the refusal.
# A guard that stopped raising would leave the survey printing a claim the snapshot does not
# support, which is the one failure mode a file of literals cannot catch by itself.


def test_a_horizon_that_is_not_thirty_days_past_the_window_is_refused(client, monkeypatch):
    monkeypatch.setattr(case_survey, "BLOCK_BEFORE_HORIZON", 16943478)
    with pytest.raises(SurveyRefused, match="do not straddle the horizon deadline"):
        confirm_horizon(client)


def test_a_window_end_outside_february_is_refused(client, monkeypatch):
    monkeypatch.setattr(case_survey, "MAR_1_2023", 1)
    with pytest.raises(SurveyRefused, match="the window does not close where"):
        confirm_horizon(client)


def test_reserves_that_are_not_what_the_pool_holds_are_refused(client):
    wrong = case_survey.Venue(
        address=SBET_PAIR, asset=SBET, quote=case_survey.WETH,
        asset_reserve_raw=SBET_VENUE.asset_reserve_raw + 1,
        quote_reserve_raw=SBET_VENUE.quote_reserve_raw,
        last_swap_block=SBET_VENUE.last_swap_block,
        last_swap_timestamp=SBET_VENUE.last_swap_timestamp,
    )
    with pytest.raises(SurveyRefused, match="this survey states"):
        confirm_venue(client, wrong)


def test_a_venue_whose_sides_are_neither_of_the_stated_assets_is_refused(client):
    """Reversing asset and quote does not produce an error downstream, it produces a price."""
    wrong = case_survey.Venue(
        address=SBET_PAIR, asset=case_survey.USDT, quote=case_survey.WETH,
        asset_reserve_raw=SBET_VENUE.asset_reserve_raw,
        quote_reserve_raw=SBET_VENUE.quote_reserve_raw,
        last_swap_block=SBET_VENUE.last_swap_block,
        last_swap_timestamp=SBET_VENUE.last_swap_timestamp,
    )
    with pytest.raises(SurveyRefused, match="Neither side matches"):
        confirm_venue(client, wrong)


def _venue_client(swaps_at_last, swaps_after):
    """A pool that reports :data:`DEAD_VENUE`'s reserves and whichever swap history is asked for."""
    reserves = "0x" + _word(DEAD_VENUE.asset_reserve_raw) + _word(DEAD_VENUE.quote_reserve_raw) + _word(0)

    def logs(from_block, to_block, address, topics):
        if from_block == DEAD_VENUE.last_swap_block and to_block == from_block:
            return [_swap_log(from_block, DEAD_PAIR)] if swaps_at_last else []
        return [_swap_log(from_block, DEAD_PAIR)] if swaps_after else []

    return CannedClient(logs=logs, eth_call={
        case_survey.GET_RESERVES: reserves,
        case_survey.TOKEN0: "0x" + _word(int(DEAD_TOKEN, 16)),
        case_survey.TOKEN1: "0x" + _word(int(case_survey.WETH, 16)),
    })


def test_a_pool_that_swapped_after_its_stated_last_swap_is_refused():
    """§9.1 condition 1 is the whole dead verdict; a swap inside the silence has to be fatal."""
    with pytest.raises(SurveyRefused, match="more swap"):
        confirm_venue(_venue_client(swaps_at_last=True, swaps_after=True), DEAD_VENUE)


def test_a_block_with_no_swap_at_all_is_refused_as_a_last_swap():
    with pytest.raises(SurveyRefused, match="emitted no Swap in block"):
        confirm_venue(_venue_client(swaps_at_last=False, swaps_after=False), DEAD_VENUE)


def test_a_last_swap_timestamp_that_is_not_the_blocks_is_refused(client, monkeypatch):
    wrong = case_survey.Venue(
        address=SBET_PAIR, asset=SBET, quote=case_survey.WETH,
        asset_reserve_raw=SBET_VENUE.asset_reserve_raw,
        quote_reserve_raw=SBET_VENUE.quote_reserve_raw,
        last_swap_block=SBET_VENUE.last_swap_block,
        last_swap_timestamp=SBET_VENUE.last_swap_timestamp + 1,
    )
    with pytest.raises(SurveyRefused, match="has timestamp"):
        confirm_venue(client, wrong)


def test_a_trading_start_with_no_mint_behind_it_is_refused(client, monkeypatch):
    monkeypatch.setattr(case_survey, "SBET_FIRST_MINT_BLOCK", SBET_PAIR_CREATED_BLOCK)
    with pytest.raises(SurveyRefused, match="no Mint at block"):
        confirm_trading_start(client)


def test_liquidity_without_a_swap_is_not_a_trading_start():
    """§4.7 needs both events. A pool that was funded and never traded has not started trading."""
    mint = {
        "blockNumber": hex(case_survey.SBET_FIRST_MINT_BLOCK), "logIndex": "0x0",
        "address": SBET_PAIR, "topics": [case_survey.MINT_V2], "data": "0x" + _word(0),
    }
    canned = CannedClient(logs=lambda **kwargs: [mint])
    with pytest.raises(SurveyRefused, match="no Swap at block"):
        confirm_trading_start(canned)


def test_a_trading_start_timestamp_that_is_not_the_blocks_is_refused(client, monkeypatch):
    monkeypatch.setattr(case_survey, "SBET_TRADING_START_TS", 1)
    with pytest.raises(SurveyRefused, match="has timestamp"):
        confirm_trading_start(client)


def test_a_trading_start_outside_the_window_is_refused(client, monkeypatch):
    monkeypatch.setattr(case_survey, "WINDOW_END_BLOCK", SBET_TRADING_START_BLOCK - 1)
    with pytest.raises(SurveyRefused, match="outside the window"):
        confirm_trading_start(client)


def test_a_lot_the_chain_does_not_hold_is_refused(client):
    lots = WALLET_A_LOTS[:3]
    with pytest.raises(SurveyRefused, match="received"):
        confirm_position(client, SBET, WALLET_A, lots, (), WALLET_A_OPEN_RAW,
                         SBET_PAIR_CREATED_BLOCK)


def test_a_disposal_the_survey_does_not_know_about_is_refused(client):
    """The one that matters most: an unlisted sale is a lot FIFO would never have to match."""
    with pytest.raises(SurveyRefused, match="A disposal this survey does not know about"):
        confirm_position(client, SBET, WALLET_B, WALLET_B_LOTS, (), WALLET_B_OPEN_RAW,
                         SBET_PAIR_CREATED_BLOCK)


def test_an_open_position_that_is_not_the_wallets_balance_is_refused(client):
    with pytest.raises(SurveyRefused, match="this survey states an open position"):
        confirm_position(client, SBET, WALLET_A, WALLET_A_LOTS, (), WALLET_A_OPEN_RAW + 1,
                         SBET_PAIR_CREATED_BLOCK)


def test_a_sale_that_exhausts_every_lot_is_not_a_multi_lot_case():
    total = sum(lot.logged_raw for lot in WALLET_B_LOTS)
    with pytest.raises(SurveyRefused, match="exhausts all"):
        confirm_fifo_consumption(WALLET_B_LOTS, total, 0)


def test_a_sale_inside_the_first_lot_is_not_a_multi_lot_case():
    with pytest.raises(SurveyRefused, match="consumes only"):
        confirm_fifo_consumption(WALLET_B_LOTS, WALLET_B_LOTS[0].logged_raw - 1, 1)


def test_a_sale_landing_exactly_on_a_lot_boundary_leaves_no_partial_lot():
    with pytest.raises(SurveyRefused, match="no partially consumed lot"):
        confirm_fifo_consumption(WALLET_B_LOTS, LOTS_ONE_TO_FOUR, 0)


def test_a_residual_that_disagrees_with_the_arithmetic_is_refused():
    with pytest.raises(SurveyRefused, match="residual and the arithmetic disagree"):
        confirm_fifo_consumption(WALLET_B_LOTS, WALLET_B_SELL_DEBITED_RAW, LOT_FIVE_REMAINDER + 1)


def test_a_sale_whose_legs_are_not_the_stated_ones_is_refused(client, monkeypatch):
    monkeypatch.setattr(case_survey, "WALLET_B_SELL_TAX_RAW", 1)
    with pytest.raises(SurveyRefused, match="this survey states"):
        confirm_credited_amounts(client)


def test_a_debited_total_that_is_not_the_sum_of_the_legs_is_refused(client, monkeypatch):
    monkeypatch.setattr(case_survey, "WALLET_B_SELL_DEBITED_RAW", 1)
    with pytest.raises(SurveyRefused, match="the sale's legs sum to"):
        confirm_credited_amounts(client)


def test_a_credited_amount_that_is_not_the_stated_one_is_refused(client, monkeypatch):
    monkeypatch.setattr(case_survey, "DEAD_HOLDER_CREDITED_RAW", DEAD_HOLDER_CREDITED_RAW + 1)
    with pytest.raises(SurveyRefused, match="was credited"):
        confirm_credited_amounts(client)


def test_a_credit_that_does_not_undershoot_its_log_is_not_the_unlogged_fee_case(client, monkeypatch):
    """If the token ever credited what its log said, this case would have to be struck."""
    monkeypatch.setattr(case_survey, "DEAD_HOLDER_LOT",
                        case_survey.Lot(DEAD_HOLDER_LOT.tx_hash, DEAD_HOLDER_LOT.block,
                                        DEAD_HOLDER_LOT.timestamp, DEAD_HOLDER_CREDITED_RAW))
    with pytest.raises(SurveyRefused, match="no longer overstates"):
        confirm_credited_amounts(client)


def test_proceeds_that_the_balance_identity_does_not_confirm_are_refused(client, monkeypatch):
    monkeypatch.setattr(case_survey, "WALLET_B_PROCEEDS_WEI", 1)
    with pytest.raises(SurveyRefused, match="it received"):
        confirm_native_proceeds(client)


def test_a_sale_sent_by_somebody_else_breaks_the_gas_term(client, monkeypatch):
    monkeypatch.setattr(case_survey, "WALLET_B", WALLET_A)
    with pytest.raises(SurveyRefused, match="was sent by"):
        confirm_native_proceeds(client)


def test_a_route_that_is_not_two_pools_is_refused(client, monkeypatch):
    monkeypatch.setattr(case_survey, "MULTIHOP_TX", WALLET_B_SELL_TX)
    with pytest.raises(SurveyRefused, match="a multi-hop route is two swaps on two pools"):
        confirm_multi_hop(client)


def test_a_route_through_other_pools_than_the_stated_ones_is_refused(client, monkeypatch):
    monkeypatch.setattr(case_survey, "MULTIHOP_USDT_PAIR", DEAD_PAIR)
    with pytest.raises(SurveyRefused, match="routes through"):
        confirm_multi_hop(client)


def test_multi_hop_amounts_that_are_not_the_stated_ones_are_refused(client, monkeypatch):
    monkeypatch.setattr(case_survey, "MULTIHOP_USDT_IN_RAW", 1)
    with pytest.raises(SurveyRefused, match="moves USDT"):
        confirm_multi_hop(client)


def test_an_intermediate_the_wallet_does_hold_is_refused(client):
    """The real receipt with one leg added: the WETH now passes through the wallet.

    That is a different transaction — a sale of USDT for WETH followed by a purchase of SBET with
    it — and §6.2's endpoints are a different pair. The guard is what stops the two being filed
    under one name.
    """
    receipt = client.get_transaction_receipt(case_survey.MULTIHOP_TX)
    forged = dict(receipt)
    forged["logs"] = list(receipt["logs"]) + [{
        "blockNumber": receipt["blockNumber"], "logIndex": "0xfff", "address": case_survey.WETH,
        "topics": [case_survey.TRANSFER, case_survey.word(case_survey.MULTIHOP_USDT_PAIR),
                   case_survey.word(case_survey.MULTIHOP_WALLET)],
        "data": "0x" + _word(case_survey.MULTIHOP_WETH_MID_RAW),
    }]
    with pytest.raises(SurveyRefused, match="credits or debits WETH"):
        confirm_multi_hop(CannedClient(receipt=forged))


def test_a_swap_output_that_is_not_the_stated_one_is_refused(client, monkeypatch):
    monkeypatch.setattr(case_survey, "MULTIHOP_SWAP_OUT_RAW", 1)
    with pytest.raises(SurveyRefused, match="the SBET pool released"):
        confirm_multi_hop(client)


def test_a_tax_that_is_not_the_difference_is_refused(client, monkeypatch):
    monkeypatch.setattr(case_survey, "MULTIHOP_TAX_RAW", 1)
    with pytest.raises(SurveyRefused, match="states a tax of"):
        confirm_multi_hop(client)


def test_a_v3_pool_with_liquidity_would_have_to_be_considered(client, monkeypatch):
    monkeypatch.setattr(case_survey, "SBET_V3_LIQUIDITY_AT_HORIZON", 1)
    with pytest.raises(SurveyRefused, match="not treated as a replacement venue"):
        confirm_the_v3_pool_is_not_a_replacement(client)


def test_a_v3_pool_whose_price_is_not_the_stated_one_is_refused(client, monkeypatch):
    monkeypatch.setattr(case_survey, "SBET_V3_FEE", 500)
    with pytest.raises(SurveyRefused, match="reports sqrtPriceX96"):
        confirm_the_v3_pool_is_not_a_replacement(client)


def test_the_search_that_clears_the_rug_token_is_the_one_that_finds_sbets_second_pool(client):
    """§9.1 condition 3 is a measurement here because the same search returns both answers.

    Over the recorded population it finds seven pools that are not one of the 57 originals, two of
    them for SBET — including the v3 pool at :data:`case_survey.SBET_V3_POOL`. Run against the rug
    token it finds nothing at all. A search that could only ever come back empty would establish
    nothing about the token it came back empty for.
    """
    assert confirm_no_replacement_for(client, DEAD_TOKEN, DEAD_PAIR, DEAD_PAIR_CREATED_BLOCK)
    population = case_survey.enumerate_candidate_population(client)
    assert len(population) == 57
    known = {pair for _token, pair in population}
    found = [row for row in case_survey.search_for_a_second_venue(
        client, tuple(token for token, _pair in population), case_survey.FACTORY_SLICES[0][0])
        if row[2] not in known]
    assert len(found) == 7
    assert case_survey.SBET_V3_POOL in {row[2] for row in found}
    assert DEAD_TOKEN not in {row[3] for row in found} | {row[4] for row in found}


def test_a_token_with_a_second_pool_is_refused_by_the_no_replacement_check():
    created = {
        "blockNumber": hex(16600000), "logIndex": "0x0", "address": case_survey.FACTORY_V2,
        "topics": [case_survey.PAIR_CREATED, case_survey.word(DEAD_TOKEN),
                   case_survey.word(case_survey.WETH)],
        "data": "0x" + _word(int(SBET_PAIR, 16)) + _word(1),
    }
    canned = CannedClient(logs=lambda **kwargs: [created])
    with pytest.raises(SurveyRefused, match="other pool"):
        confirm_no_replacement_for(canned, DEAD_TOKEN, DEAD_PAIR, HORIZON_BLOCK - 1)
