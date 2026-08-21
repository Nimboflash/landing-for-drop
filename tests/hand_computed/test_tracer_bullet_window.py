"""Ticket 19's tracer bullet, pinned: one wallet, one window, every published number a literal.

``tests/hand_computed/test_ingest.py`` pins a *decode* against bytes mainnet returned. This file
pins the whole bullet — the same bytes carried through
:func:`pipeline.run_wallet_window`, the real composition root — and every literal below was read
off a block explorer or computed on paper, never by calling the code under test with a different
spelling of the same expression.

Nothing here opens a socket. The client runs in ``REPLAY_ONLY`` against
``tests/fixtures/tracer_bullet/recordings`` and ``urllib.request.urlopen`` is poisoned, so a test
that reached the chain fails loudly rather than quietly pinning today's answer.

What this file is evidence for
------------------------------

* the four native settlements close to the wei from archive balances alone — no trace anywhere;
* all seven transactions reach the pipeline and all seven decode, including the 1inch limit-order
  fill whose ``OrderFilled`` event started this;
* the published ``buy_quality_30d`` is exactly the buy's raw ETH ratio, which is what one price per
  quote asset per window makes it — see ``test_the_published_return_is_the_raw_eth_ratio``.

What changed under these tests, twice, and why the record of it is kept
-----------------------------------------------------------------------

**State one — the defect.** When this file was first written the seventh transaction did not reach
the pipeline at all. ``ingest.events`` raised ``UnknownEvent`` on the whole receipt, the refusal
happened before ``run_wallet_window`` was called, and the transaction appeared in no census, no
quarantine queue and no coverage report — ``census.total`` read **6** against a real population of
**7**, with every reconciliation in the result balancing against the smaller number and no field
anywhere that could have held the seventh.

**State two — the refusal made survivable.** :class:`pipeline.UndecodableTransaction` gave the
refusal somewhere to live. ``census.total`` read **7** with ``census.undecodable`` **1**, the
quarantine queue held one ``Stage.INGESTION`` record naming topic ``0xb9ed0243…`` on the 1inch v5
router at log 96, and the transaction was scored by nothing.

**State three — the registry widened.** ``OrderFilled`` was admitted to
``ingest.events.SIGNATURES`` as a restatement, the receipt decodes to five transfer legs, and it
classifies ``VALID_SELL`` closing the tail buy. ``census.undecodable`` is **0** and the queue is
empty.

The order of two and three is the whole argument and is why both are recorded. Had the registry
been widened first, this one transaction would have been fixed and the *next* unlisted event would
have gone on vanishing exactly as this one did — the accounting is what makes a decoder gap
visible, and the decoder entry only closes one gap. Each test whose literals moved says in its own
docstring what it used to assert, because a repository that silently rewrites the tests that
recorded a bug loses the only evidence the bug was ever real.

One consequence to be honest about: **this file no longer exercises the undecodable path at all.**
``tests/hand_computed/test_undecodable_population.py`` does, on an event that is still unlisted.
What remains here is the assertion that the path is *wired* and quiet — ``census.undecodable == 0``
and an empty ``Stage.INGESTION`` queue are claims about this population, not about the machinery.
"""

import os
import urllib.request
from decimal import Decimal

import pytest

from contracts import ClassificationStatus, TokenAgeBucket
from pipeline import STAGE_ORDER, Stage, UndecodableTransaction
from transport import REPLAY_ONLY, RecordingCache, RpcClient

from tools import tracer_bullet

# -- the population, by hash ----------------------------------------------------

BUY = "0x10ab9b812107769650f6661c164a5bcfeca80caf67528aebde33090ab63ffc60"
SELL = "0xce4e2048a41ae098cdfd93131895e16d57bd41f6fe1a748bf264178894a1ef42"
ETH_OUT = "0x20562173ef9b9dd70d50f664fc975ac2b08b4bb822f38d249edd3e837b376c31"
ETH_IN = "0x6d9ce0a41e622f40111e8ea7f82512d17e3d656404b1c36aaf6f6cbc197bd0f3"
TAIL_BUY = "0xa51f7010a2ddb12a5d3cb45ed6084c569b85d834141cf078e69e20a4dcfbdef4"
TAIL_SELL = "0x559e18c0d5cd7704369dfbbe4a9520ad6d4b3e172000460b481e8ec9065e76de"
TAIL_ETH_OUT = "0x9c9dd3fb5179d2b0b2ddcb2e6376205c0ddf0c79b7bc0e04f6e98e30a7cb8e66"

WALLET = "0xe15b3d62c2bce51f2a8a8d53d76c36b4fab8721c"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
XUSDP = "0xa1f7c9c6d19e2d0bf20729cb0bf03338a90bed9b"

#: The 1inch v5 aggregation router, and ``topics[0]`` of the log on it that used to refuse the whole
#: receipt. Read off log 96 of ``TAIL_SELL``'s receipt in the committed snapshot.
INCH_ROUTER = "0x1111111254eeb25477b68fb85ed929f73a960582"
ORDER_FILLED_TOPIC = "0xb9ed0243fdf00f0545c63a0af8850c090d86bb46682baec4bf3c496814fe4f02"

#: The three contracts the maker's WETH walks on its way back out of the fill, in order. They exist
#: in this file only because the fill decodes: while it did not, nothing in the run had ever heard
#: of them.
INCH_RESOLVER = "0x84d99aa569d93a9ca187d83734c8c4a519c4e9b1"
INCH_SETTLEMENT = "0xa88800cd213da5ae406ce248380802bd53b47647"
INCH_UNWRAPPER = "0x8290dbccb15b5a516deee2805c58e56075d6605e"

# -- raw amounts, read off the receipts by hand ---------------------------------

#: ``0x58a89891e50df7``, the ``Deposit`` at log 351 and the buy transaction's own ``value``.
BUY_WEI = 24955171186740727
#: ``0x170d08d41afc0e0ee6e``, log 353.
BUY_XUSDP = 6803429558879831256686
#: ``0x7a88a4dd12d65a``, the ``Withdrawal`` at log 573.
SELL_WEI = 34490188823713370
#: ``0x5fee4d0f2b8000``, the ``Deposit`` at log 803.
TAIL_BUY_WEI = 27001967305600000
#: ``0x92ce43e3e0dc6bc25dde``, log 805.
TAIL_BUY_XUSDP = 43344587171932221292126
#: ``0x6f2908d70d4266``, the ``Withdrawal`` at log 105 of ``TAIL_SELL``. What the maker got back.
#: Also, independently, the wallet's own archive balance delta across block 16758317 — see
#: ``test_the_wallet_paid_no_gas_on_the_order_a_third_party_filled``.
TAIL_SELL_WEI = 31288840359330406
#: ``0x910996 9544c50b``, log 99: the WETH the pair paid out before the taker took its cut. The
#: difference from ``TAIL_SELL_WEI`` never reaches the wallet and is not the wallet's to net.
TAIL_SELL_POOL_WEI = 40824413977101579

# -- the price book -------------------------------------------------------------

#: Chainlink ETH/USD ``latestRoundData().answer`` at block 16530248, 8 decimals: $1,587.06.
#: The round was set at ts 1675209335, 276 seconds before the window opens.
CHAINLINK_ANSWER = 158706000000
#: ``158706000000 / 10**(8 + 18)``.
WETH_USD_PER_RAW = Decimal("1.58706E-15")

# -- what the run publishes -----------------------------------------------------

#: ``24955171186740727 * 1.58706E-15``.
COST_USD = Decimal("39.60535398362873819262")
#: ``34490188823713370 * 1.58706E-15``.
PROCEEDS_USD = Decimal("54.73799907456254099220")
#: ``27001967305600000 * 1.58706E-15``. The tail buy is priced but never scored.
TAIL_COST_USD = Decimal("42.85374223202553600000")
#: ``31288840359330406 * 1.58706E-15``. The tail sell, priced and never scored either — §4.8 defers
#: the whole round trip to the next window.
TAIL_PROCEEDS_USD = Decimal("49.65726698067891414636")
#: ``39.60535398362873819262 + 54.73799907456254099220 + 42.85374223202553600000
#: + 49.65726698067891414636``. It read 137.19709529021681518482 while the tail sell was
#: undecodable: a transaction nobody can read is also $49.66 of notional nobody counts.
NOTIONAL_TOTAL_USD = Decimal("186.85436227089572933118")

#: ``54.73799907456254099220 / 39.60535398362873819262 - 1``, which is also
#: ``34490188823713370 / 24955171186740727 - 1`` — see the test of that name.
RETURN_PCT = Decimal("0.3820858436763128080940416532151664002")

#: One buy scored, so §4.4's log-weighted mean is that buy's own return.
BUY_QUALITY = Decimal("0.38208584367631280809404165321516640020")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Replay-only is the claim; a poisoned socket is the proof."""

    def refuse(*args, **kwargs):
        raise AssertionError(
            "tests/hand_computed/test_tracer_bullet_window.py opened a real connection. Every "
            "byte it reads comes from the committed snapshot; a test that reaches the chain pins "
            "today's answer rather than the one these literals were checked against."
        )

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture(scope="module")
def bullet():
    client = RpcClient(
        cache=RecordingCache(tracer_bullet.RECORDINGS), mode=REPLAY_ONLY
    )
    result = tracer_bullet.run(client)
    replayed, live = client.replayed_count()
    assert live == 0, "the bullet went to the network for {} call(s)".format(live)
    assert replayed > 0
    return result


def test_the_snapshot_is_present_and_replay_only_is_possible():
    assert os.path.isdir(tracer_bullet.RECORDINGS), (
        "the tracer bullet's snapshot is missing; re-record it with "
        "`PYTHONPATH=src python -m tools.tracer_bullet --record`"
    )


def test_the_snapshot_the_literals_were_read_off_is_pinned():
    """The count is asserted beside the hash, and the two say different things.

    A bare hash mismatch cannot distinguish "a call was added" from "a recorded answer changed",
    and only the second puts every literal in this file in question.
    """
    cache = RecordingCache(tracer_bullet.RECORDINGS)
    # 34 until the 1inch fill decoded. The three added are ``eth_getCode`` on the resolver, the
    # settlement contract and the WETH unwrapper — addresses the run could not ask about while the
    # receipt that carries them was refused whole.
    assert len(cache.entries()) == 37
    assert cache.fingerprint() == (
        "df18b575f0d18804758dc565b3341435ebeedc67d0d502c5b4facbd0d0e49c8a"
    )


# -- the window -----------------------------------------------------------------


def test_the_window_is_february_2023_by_the_chains_own_seconds(bullet):
    window = bullet["window"]
    assert (window.start_block, window.start_ts) == (16530248, 1675209611)
    assert (window.end_block, window.end_ts) == (16730071, 1677628799)


def test_the_blocks_outside_the_window_straddle_the_calendar_boundaries(bullet):
    before, start, end, after = bullet["edges"]
    # 2023-01-31T23:59:59Z / 2023-02-01T00:00:11Z
    assert (before.number, before.timestamp) == (16530247, 1675209599)
    assert (start.number, start.timestamp) == (16530248, 1675209611)
    # 2023-02-28T23:59:59Z / 2023-03-01T00:00:11Z
    assert (end.number, end.timestamp) == (16730071, 1677628799)
    assert (after.number, after.timestamp) == (16730072, 1677628811)


def test_the_horizon_is_exactly_thirty_days_past_the_window_end(bullet):
    config = bullet["config"]
    assert (config.horizon_block, config.horizon_ts) == (16943478, 1680220799)
    assert config.horizon_ts - bullet["window"].end_ts == 2592000


def test_the_token_trading_start_is_the_block_the_pair_was_funded_and_first_swapped(bullet):
    start = bullet["config"].token_start(XUSDP)
    # 2021-04-14T02:15:16Z — twenty-one months before the window.
    assert (start.block, start.timestamp) == (12235473, 1618366516)


# -- the price ------------------------------------------------------------------


def test_the_price_book_is_chainlinks_answer_scaled_by_weths_own_decimals(bullet):
    answer, weth_decimals = bullet["price_evidence"]
    assert answer == CHAINLINK_ANSWER
    assert weth_decimals == 18
    assert bullet["prices"][WETH] == WETH_USD_PER_RAW


# -- the native settlements, without a trace ------------------------------------


def test_every_native_leg_closes_against_the_wallets_own_archive_balance(bullet):
    rows = {row[0]: row for row in bullet["settlements"]}
    assert sorted(rows) == sorted([BUY, SELL, TAIL_BUY, TAIL_SELL])

    # (tx, block, balance_before, balance_after, gas_paid, legs_sum, measured)
    assert rows[BUY][1:] == (
        16530343, 31820723192820727, 4434183316706784, 2431368689373216,
        -BUY_WEI, -BUY_WEI,
    )
    assert rows[SELL][1:] == (
        16535133, 4434183316706784, 36879281269560881, 2045090870859273,
        SELL_WEI, SELL_WEI,
    )
    assert rows[TAIL_BUY][1:] == (
        16744492, 33881830000000000, 4555364825238180, 2324497869161820,
        -TAIL_BUY_WEI, -TAIL_BUY_WEI,
    )


def test_the_wallet_paid_no_gas_on_the_order_a_third_party_filled(bullet):
    """The tail sell was submitted by a resolver, so the identity carries no gas term at all.

    And its legs now close: the wallet's archive balance moved 31,288,840,359,330,406 wei across
    block 16758317 with no gas paid, and the receipt's WETH unwrap at log 105 is that same number.
    **This row's ``legs`` used to read ``None``** — the balance delta needs no decoder, but the
    amount to compare it against was exactly what the refusal withheld, so the run could measure
    what the wallet received and had nothing to check it against.

    That is worth pinning as its own fact rather than folding into the decode test. It is an
    independent confirmation, from archive state alone, that the newly-decoded legs are right: the
    ``OrderFilled`` entry admits nothing about amounts, and the amount that reaches the wallet is
    still established by subtraction against the chain.
    """
    rows = {row[0]: row for row in bullet["settlements"]}
    tx, block, before, after, gas, legs, measured = rows[TAIL_SELL]
    assert (block, before, after, gas) == (
        16758317, 4555364825238180, 35844205184568586, 0
    )
    assert measured == TAIL_SELL_WEI
    assert legs == TAIL_SELL_WEI


# -- the population: seven handed in, seven read -------------------------------


def test_all_seven_transactions_reach_the_pipeline_and_all_seven_decode(bullet):
    """The 1inch limit-order fill carries ``OrderFilled``, which ``SIGNATURES`` now lists.

    **This test has moved twice and both numbers are recorded.** It first read
    ``len(bullet["transactions"]) == 6`` and ``census.total == 6`` — and was right to: the refusal
    was raised before the composition root was called, the transaction entered nothing, and six was
    the number the run actually published against a real population of seven. It then read
    ``census.total == 7`` with ``census.undecodable == 1``, once an unreadable receipt had somewhere
    to be counted. It now reads ``undecodable == 0``, because the event is classified.

    The middle state is the one that matters and is the reason the order was that way round. Zero
    here is a statement about *this* population, not about the registry: the assertion below is
    that nothing went missing, not that nothing ever can.
    """
    assert len(tracer_bullet.TRANSACTIONS) == 7
    assert len(bullet["transactions"]) == 7
    assert [i for i in bullet["transactions"] if isinstance(i, UndecodableTransaction)] == []
    assert bullet["result"].census.total == 7
    assert bullet["result"].census.undecodable == 0
    assert bullet["result"].quarantine.by_stage(Stage.INGESTION) == ()
    # The accounting is wired and silent, not absent. `tests/hand_computed/
    # test_undecodable_population.py` is where it is exercised, on an event still unlisted.
    assert Stage.INGESTION not in bullet["result"].stages_run
    assert bullet["result"].stages_run == STAGE_ORDER


def test_the_fill_that_used_to_refuse_the_receipt_decodes_to_five_legs(bullet):
    """Log 96 is read and classified; logs 97 to 105 are the movements it restates.

    The five legs are the whole of the fill: the maker's XUSDP into the pair, the WETH out of the
    pair to the resolver, the taker's cut kept, the remainder through the Fusion settlement contract
    to the WETH unwrapper, and the unwrapper's native ETH to the wallet — that last one synthesised
    from the ``Withdrawal`` at log 105 plus the settlement address the run states and
    :func:`tools.tracer_bullet.confirm_native_settlements` confirms.

    Note what ``OrderFilled`` contributes to this list: nothing. Every leg here comes from an
    ERC-20 ``Transfer`` or the WETH unwrap, which is precisely the claim ``moves_value=False``
    makes about it. Admitting the event changed which receipts can be read, not what any of them
    is read as saying.
    """
    by_hash = {item.tx_hash: item for item in bullet["transactions"]}
    fill = by_hash[TAIL_SELL]

    assert [(leg.log_index, leg.token, leg.from_addr, leg.to_addr, leg.raw_amount)
            for leg in fill.transfers] == [
        (97, XUSDP, WALLET, "0xee19920b7da72b0520e3c3f367aab7479e89607b", TAIL_BUY_XUSDP),
        (99, WETH, "0xee19920b7da72b0520e3c3f367aab7479e89607b", INCH_RESOLVER,
         TAIL_SELL_POOL_WEI),
        (102, WETH, INCH_RESOLVER, INCH_SETTLEMENT, TAIL_SELL_WEI),
        (104, WETH, INCH_SETTLEMENT, INCH_UNWRAPPER, TAIL_SELL_WEI),
        (105, WETH, INCH_UNWRAPPER, WALLET, TAIL_SELL_WEI),
    ]
    # log 96 is the OrderFilled itself, and it produced no leg.
    assert 96 not in {leg.log_index for leg in fill.transfers}
    assert (fill.block_number, fill.timestamp) == (16758317, 1677972239)
    assert fill.tx_sender == "0x55dcad916750c19c4ec69d65ff0317767b36ce90"


def test_typing_the_addresses_needed_the_receipt_that_would_not_decode(bullet):
    """A decoder gap does not only lose a transaction — it shrinks the evidence about the rest.

    §6.2 typing reads the transfer legs, and an undecodable transaction has none. While the fill was
    refused this run typed **three** addresses; it now types six, and the three that appeared are
    the 1inch settlement path. Nothing asked about them before, so nothing could have noticed they
    were missing: the narrowing was invisible from inside the result, exactly as the missing
    transaction was.
    """
    typed = {address for address, _, _ in bullet["context_rows"]}

    assert {INCH_RESOLVER, INCH_SETTLEMENT, INCH_UNWRAPPER} <= typed
    assert len(typed) == 6
    assert typed == {
        WALLET, INCH_ROUTER, "0xee19920b7da72b0520e3c3f367aab7479e89607b",
        INCH_RESOLVER, INCH_SETTLEMENT, INCH_UNWRAPPER,
    }


# -- the finding: a plain ETH transfer decodes to nothing -----------------------


def test_the_three_plain_eth_transfers_decode_to_no_legs_at_all(bullet):
    """36,300,876,282,645,881 wei left the wallet in ``ETH_OUT`` and the run sees zero movement.

    ``ingest`` reads logs, and a plain ETH transfer writes none. The transactions are counted in
    the census and excluded by §8 for having no owner evidence — which is the correct refusal on
    the input it was given, and the input is missing the only thing that happened.
    """
    by_hash = {item.tx_hash: item for item in bullet["transactions"]}
    for tx_hash in (ETH_OUT, ETH_IN, TAIL_ETH_OUT):
        assert by_hash[tx_hash].transfers == ()
    assert by_hash[ETH_IN].tx_sender == "0x51836a753e344257b361519e948ffcaf5fb8d521"


# -- classification -------------------------------------------------------------


def test_every_transaction_is_classified_as_the_receipts_say_it_should_be(bullet):
    statuses = {row.tx_hash: row.status for row in bullet["result"].results}
    assert statuses == {
        BUY: ClassificationStatus.VALID_BUY,
        SELL: ClassificationStatus.VALID_SELL,
        TAIL_BUY: ClassificationStatus.VALID_BUY,
        # Absent from this mapping entirely while its receipt could not be read.
        TAIL_SELL: ClassificationStatus.VALID_SELL,
        ETH_OUT: ClassificationStatus.UNSUPPORTED,
        ETH_IN: ClassificationStatus.UNSUPPORTED,
        TAIL_ETH_OUT: ClassificationStatus.UNSUPPORTED,
    }


def test_the_buy_and_the_sell_carry_the_raw_amounts_the_logs_carry(bullet):
    rows = {row.tx_hash: row for row in bullet["result"].results}
    buy = rows[BUY]
    assert (buy.sold_asset, buy.sold_raw_amount) == (WETH, BUY_WEI)
    assert (buy.bought_asset, buy.bought_raw_amount) == (XUSDP, BUY_XUSDP)
    assert (buy.quote_asset, buy.quote_usd) == (WETH, COST_USD)

    sell = rows[SELL]
    assert (sell.sold_asset, sell.sold_raw_amount) == (XUSDP, BUY_XUSDP)
    assert (sell.bought_asset, sell.bought_raw_amount) == (WETH, SELL_WEI)
    assert (sell.quote_asset, sell.quote_usd) == (WETH, PROCEEDS_USD)

    tail = rows[TAIL_BUY]
    assert (tail.sold_asset, tail.sold_raw_amount) == (WETH, TAIL_BUY_WEI)
    assert (tail.bought_asset, tail.bought_raw_amount) == (XUSDP, TAIL_BUY_XUSDP)
    assert tail.quote_usd == TAIL_COST_USD


def test_the_tail_sell_nets_to_the_wallets_side_of_the_fill_and_not_the_pools(bullet):
    """Five legs in, one trade out — and the WETH the *wallet* got, not the WETH the pair paid.

    The pair paid ``TAIL_SELL_POOL_WEI`` at log 99; ``TAIL_SELL_WEI`` reached the wallet three hops
    later, the difference being the taker's cut. Netting is per owner, so the wallet's net is the
    smaller number, and a decoder that had summed the pool's leg into the wallet's position would
    have published a sale 30% larger than the one that happened. Pinned because this is the first
    transaction in the run whose legs pass through addresses that are not the wallet's.
    """
    tail_sell = {row.tx_hash: row for row in bullet["result"].results}[TAIL_SELL]

    assert (tail_sell.sold_asset, tail_sell.sold_raw_amount) == (XUSDP, TAIL_BUY_XUSDP)
    assert (tail_sell.bought_asset, tail_sell.bought_raw_amount) == (WETH, TAIL_SELL_WEI)
    assert tail_sell.bought_raw_amount < TAIL_SELL_POOL_WEI
    assert tail_sell.quote_usd == TAIL_PROCEEDS_USD


# -- the reconciliation ---------------------------------------------------------


def test_the_reconciliation_reads_the_way_the_seven_transactions_say_it_should(bullet):
    """Seven in, and the seven add up: 7 netted + 0 netting-quarantined + 0 undecodable.

    The history in three lines, because every one of them balanced perfectly at the time:

        state one   transactions_in 6, no undecodable term at all
        state two   transactions_in 7, undecodable 1, netted 6, quarantine_records 1
        state three transactions_in 7, undecodable 0, netted 7, quarantine_records 0

    State one is the warning. A reconciliation that adds up says the *stages* agree with each
    other; it says nothing about whether the population they agree over is the real one. That is
    why the identity at the bottom is asserted against ``transactions_in`` and why
    ``test_all_seven_transactions_reach_the_pipeline_and_all_seven_decode`` asserts the seven
    against ``tracer_bullet.TRANSACTIONS`` — a number from outside the run.

    ``consumptions`` and ``status_VALID_SELL`` moved to 2 because the fill closes the tail buy.
    ``buys_scored`` did not move: both tail legs are past the window's end, so §4.8 defers the
    round trip whole.
    """
    lines = dict(bullet["result"].reconciliation())
    assert lines["transactions_in"] == 7
    assert lines["transactions_undecodable"] == 0
    assert lines["attribution_excluded"] == 3
    assert lines["attribution_usable"] == 4
    assert lines["netted"] == 7
    assert lines["netting_quarantined"] == 0
    assert lines["status_VALID_BUY"] == 2
    assert lines["status_VALID_SELL"] == 2
    assert lines["status_UNSUPPORTED"] == 3
    assert lines["fifo_books"] == 1
    assert lines["consumptions"] == 2
    assert lines["buys_outside_window"] == 1
    assert lines["buys_scored"] == 1
    assert lines["open_positions_marked"] == 0
    assert lines["quarantine_records"] == 0
    assert lines["quarantine_transactions"] == 0
    assert lines["wallets_seen"] == 1
    assert lines["wallets_scored"] == 1
    # 7 classified + 0 quarantined + 0 undecodable = 7 handed in. Hand-summed, not recomputed.
    assert (lines["netted"] + lines["netting_quarantined"]
            + lines["transactions_undecodable"]) == lines["transactions_in"]


def test_the_derived_identities_hold_on_a_real_run(bullet):
    """The two statements ``_require_the_census_matches_the_evidence`` deliberately does not check.

    That function's docstring names this test by name and argues that ``stages.netted ==
    len(results)`` and *results + netting quarantines + undecodable == census.total* follow by
    arithmetic from the four checks it does make, so re-checking them there would add a ``raise``
    that can never fire. The argument is sound and the test did not exist, which left the
    derivation resting on nothing measured — and one of its premises, ``census.quarantined ==
    stages.netting_quarantined``, was itself standing behind ``if False:``.

    Asserted here, on the real seven-transaction run, because a positive assertion on measured
    output is a pin and an unreachable ``raise`` is not. Both literals are the tracer bullet's own:
    seven netted results, nothing quarantined at netting, nothing undecodable, seven in the census.
    """
    result = bullet["result"]

    assert result.stages.netted == 7
    assert len(result.results) == 7
    assert result.stages.netted == len(result.results)

    assert result.census.total == 7
    assert result.census.quarantined == 0
    assert result.census.undecodable == 0
    assert (len(result.results) + result.census.quarantined
            + result.census.undecodable) == result.census.total

    # And the premise the derivation rests on, stated rather than assumed.
    assert result.census.quarantined == result.stages.netting_quarantined


def test_no_pool_state_was_needed_because_nothing_was_still_open(bullet):
    """The in-window buy was fully sold sixteen hours later, and the tail buy is not scored here.

    Worth pinning: it means this run exercises §4.4 Case 1 only. Case 2 and Case 3 — a mark against
    a live pool and a dead-pool zero — are untouched by the tracer bullet, so nothing here is
    evidence about them.
    """
    account = bullet["result"].accounts[0]
    assert account.open_raw == 0
    assert account.position is None
    assert bullet["result"].stages.open_positions_marked == 0


# -- the published numbers ------------------------------------------------------


def test_the_scored_buy_publishes_the_numbers_the_bytes_imply(bullet):
    account = bullet["result"].accounts[0]
    assert account.buy.tx_hash == BUY
    assert account.bucket is TokenAgeBucket.D
    assert account.cost_usd == COST_USD
    assert account.realized_raw == BUY_XUSDP
    assert account.realized_cost_usd == COST_USD
    assert account.realized_proceeds_usd == PROCEEDS_USD
    assert account.open_raw == 0
    assert account.marked_usd == 0
    assert account.dead_usd == 0
    assert account.return_pct == RETURN_PCT
    # 1675210751 + 2_592_000
    assert account.buy_horizon_ts == 1677802751
    # The run's horizon is 1680220799, which is 27 days 23 hours past this buy's own.
    assert account.horizon_lag_seconds == 2418048


def test_the_wallets_published_quality_and_its_mix(bullet):
    outcome = bullet["result"].wallets[0]
    assert outcome.wallet == WALLET
    # (2, 1) while the fill was unreadable: the wallet had made a sale the run could not see.
    assert (outcome.n_buys, outcome.n_sells) == (2, 2)
    assert (outcome.n_buys_quarantined, outcome.n_sells_quarantined) == (0, 0)
    quality = outcome.quality
    assert quality.value == BUY_QUALITY
    assert quality.n_buys == 1
    assert quality.realized_share == 1
    assert quality.marked_share == 0
    assert quality.dead_share == 0
    assert list(quality.bucket_weights) == [TokenAgeBucket.D]


def test_usd_coverage_counts_only_what_it_could_price(bullet):
    """Four priced, three not — and the three unpriced ones are the plain ETH transfers.

    The literals here have read (3, 3) over a denominator of six, then (3, 4) over seven, and now
    (4, 3). The middle pair is the interesting one: the fourth unpriced row was the undecodable
    receipt, the surest unpriced row of the four, because nothing in it was decoded and there was
    not even a leg to try a price on.

    ``notional_usd_total`` moved with it, from $137.20 to $186.85. A transaction nobody can read is
    also $49.66 of notional nobody counts, and while it was unreadable the run's own coverage figure
    said the population was 27% smaller in dollars than it was.
    """
    coverage = bullet["result"].coverage
    assert coverage.notional_usd_total == NOTIONAL_TOTAL_USD
    assert coverage.notional_usd_trades == NOTIONAL_TOTAL_USD
    assert coverage.notional_usd_scored == COST_USD
    assert coverage.notional_usd_quarantined == 0
    assert (coverage.transactions_priced, coverage.transactions_unpriced) == (4, 3)
    assert coverage.transactions_priced + coverage.transactions_unpriced == 7
    assert bullet["result"].quarantine.unpriced == 0


def test_the_published_return_is_the_raw_eth_ratio_and_that_is_the_price_books_doing():
    """One price per quote asset per window makes ``buy_quality`` a pure ETH-terms number.

    Both legs are multiplied by the same scalar, so it cancels: the published 0.38209 is exactly
    ``34490188823713370 / 24955171186740727 - 1``. Priced at each leg's own block — Chainlink read
    1587.06 at the buy and 1576.19021 at the sell — the same trade returns 0.37262, which is 0.947
    percentage points lower. Pinned as a literal so the size of the effect is a fact in the suite
    rather than a remark in a report.
    """
    from contracts import calc, divide, mul, sub

    published = sub(divide(calc(SELL_WEI), calc(BUY_WEI)), calc(1))
    assert published == RETURN_PCT

    sell_block_price = Decimal("1.57619021E-15")
    at_own_prices = sub(
        divide(mul(calc(SELL_WEI), sell_block_price), COST_USD), calc(1)
    )
    assert at_own_prices == Decimal("0.3726199237471769542521626234231599962")
    assert sub(published, at_own_prices) == Decimal(
        "0.0094659199291358538418790297920064040"
    )


def test_the_published_return_is_gross_of_the_gas_the_wallet_paid():
    """§4.4 measures the trade, not the wallet, and on a $40 trade the difference is most of it.

    The round trip cost ``2431368689373216 + 2045090870859273`` wei in gas — $7.10 at the window's
    price — against a $15.13 gross gain. Net of gas the wallet made 20.27%, not 38.21%. Neither
    number is wrong; they answer different questions, and only the first is published.

    ``30013729263480881 / 24955171186740727 - 1``, checked at 60 digits outside the frozen context
    before it was written down here.
    """
    from contracts import calc, divide, sub

    gas = 2431368689373216 + 2045090870859273
    assert gas == 4476459560232489
    net = sub(divide(calc(SELL_WEI - gas), calc(BUY_WEI)), calc(1))
    assert net == Decimal("0.2027058054976551558892254993543301620")
