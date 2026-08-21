"""Every signature ticket 20 added, pinned against the real log it was admitted on.

``ingest.events.SIGNATURES`` is a closed registry, and the failure it exists to prevent is a
*plausible* number rather than an error: an event wrongly marked as moving value credits an address
with money that never moved, and a real mover marked as a restatement loses a leg. Both produce a
trade nobody made, and neither shows up as a crash.

So an entry added from a remembered ABI is a guess. Each of the three admitted here was pinned
against bytes Ethereum mainnet actually returned, replayed from ``tests/fixtures/events/recordings``
in ``REPLAY_ONLY`` — a call the snapshot does not hold raises rather than quietly measuring a
different chain than the one these literals were read off.

The five receipts, and what each one is here to settle
------------------------------------------------------

    0xf4be8ef8…  block 16530251   Uniswap v3, two hops, seven logs, no native leg
    0x2a569c2f…  block 16600177   a Curve 3pool exchange called directly on the pool, three logs
    0xc52d1fbae2… block 16530254  a 1inch v5 limit-order fill, nine logs
    0x8ed9a26a…  block 16530249   an ERC-1155 TransferSingle — declined, and refused here
    0x4634f021…  block 16530248   an ERC-1155 TransferBatch — declined, and refused here

The claim each new entry makes is ``moves_value=False``, and that claim is falsifiable on exactly
these bytes: if the event were the only record of a movement, the receipt would not also contain
the ERC-20 ``Transfer`` legs carrying the same amounts. Every test below that ends in
``_restates_transfers_in_the_same_receipt`` is that falsification attempt, and it is the reason
these are receipts rather than isolated logs.

What this file does not establish
---------------------------------

That the three admitted signatures are decoded correctly *everywhere* — one real log per entry is
one real log. In particular ``only_on`` is set on none of them, so a contract that emits one of
these topics and settles its value movement without an ERC-20 ``Transfer`` would be read as having
moved nothing. That exposure is named in :mod:`ingest.events`'s docstring and is not closed here.
"""

import os
import urllib.request

import pytest

from contracts import USDC, USDT, WETH
from ingest import (
    DECLINED,
    ORDER_FILLED,
    SIGNATURES,
    SWAP_V3,
    TOKEN_EXCHANGE,
    TRANSFER_BATCH,
    TRANSFER_SINGLE,
    NoValueEvent,
    TokenTransfer,
    UnknownEvent,
    decode_log,
    decode_logs,
    logs_of,
    require_receipt,
    require_success,
    transfers_from_logs,
)
from transport import REPLAY_ONLY, RecordingCache, RpcClient

RECORDINGS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fixtures", "events", "recordings",
)

# -- Uniswap v3: 0xf4be8ef8… ------------------------------------------------------
#
# A 0x-protocol multi-hop. Two v3 pools, seven logs, and deliberately no WETH wrap or unwrap, so
# ``transfers_from_logs`` needs no native settlement and the receipt decodes end to end.

V3_TX = "0xf4be8ef8a86eae549ba237abd34daa6f93152005c81d1014927986ae615b5f81"
V3_BLOCK = 16530251

V3_TAKER = "0x8dfc6ba7a7b55e5c73930b1d77d931b6f63a6ddd"
V3_EXCHANGE_PROXY = "0xdef1c0ded9bec7f1a1670819833240f027b25eff"
#: The first hop's pool, and the token it sold.
V3_POOL_1 = "0x1c5c60bef00c820274d4938a5e6d04b124d4910b"
V3_TOKEN_1 = "0x0c10bf8fcb7bf5412187a595ab97a3609160b5c6"
#: The second hop's pool: USDC/WETH 0.05%.
V3_POOL_2 = "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640"

#: ``0x18ec4d931e56699699``, log 345. The token the taker sold into pool 1.
V3_TOKEN_1_RAW = 459749285293695014553
#: ``0x1b2f0b5c``, logs 344 and 349. The USDC between the two hops.
V3_USDC_RAW = 456067932
#: ``0x3fcffb14e2c209a``, log 348. The WETH the taker received.
V3_WETH_RAW = 287385613230678170

#: Log 347's ``amount1`` word, verbatim. int256, two's complement, and negative because the pool
#: paid this leg out.
V3_AMOUNT1_WORD_HOP_1 = "0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffe4d0f4a4"
#: The same 32 bytes read as a ``uint256``. 2**256 - 456067932.
V3_AMOUNT1_AS_UNSIGNED_HOP_1 = (
    115792089237316195423570985008687907853269984665640564039457584007912673572004
)
#: Log 350's ``amount1`` word and its unsigned misreading. 2**256 - 287385613230678170.
V3_AMOUNT1_WORD_HOP_2 = "0xfffffffffffffffffffffffffffffffffffffffffffffffffc03004eb1d3df66"
V3_AMOUNT1_AS_UNSIGNED_HOP_2 = (
    115792089237316195423570985008687907853269984665640564039457296622299898961766
)

# -- Curve: 0x2a569c2f… -----------------------------------------------------------
#
# ``exchange()`` called straight on the 3pool, so the receipt is three logs and nothing else.

CURVE_TX = "0x2a569c2ff464870f6be13b1070bc520d86b0fe580dd183401e0a13d1474d0de9"
CURVE_BLOCK = 16600177
CURVE_POOL = "0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7"
CURVE_BUYER = "0x6a55913755ea287b53bedfc1f603ea62b4a19f51"

#: ``0x1c0afad2715``, log 10 and ``TokenExchange.tokens_sold``.
CURVE_USDT_RAW = 1927092709141
#: ``0x1c0c25aeeb8``, log 11 and ``TokenExchange.tokens_bought``.
CURVE_USDC_RAW = 1927406087864
#: The pool's own coin indices: 2 is USDT, 1 is USDC. ``int128``, and both positive here.
CURVE_SOLD_ID = 2
CURVE_BOUGHT_ID = 1

# -- 1inch: 0xc52d1fbae2… ---------------------------------------------------------
#
# A second ``OrderFilled`` witness, independent of the tracer bullet's 0x559e18c0… and a different
# shape: this one settles in USDC rather than through a WETH unwrap.

ORDER_TX = "0xc52d1fbae2ee3b71ee617ed1f148b8b28145dbf00f71d4864b52544fb6d17435"
ORDER_BLOCK = 16530254
#: 1inch v5 aggregation router — the contract that emits the fill.
ONEINCH_ROUTER = "0x1111111254eeb25477b68fb85ed929f73a960582"
ORDER_MAKER = "0xe6606dbfbefebc90a0eff7ff2e42744282fb460d"
ORDER_RESOLVER = "0x84d99aa569d93a9ca187d83734c8c4a519c4e9b1"
ORDER_SETTLEMENT = "0xa88800cd213da5ae406ce248380802bd53b47647"

#: ``0x1ab6c2ec4a45892c``… log 107. The maker's WETH, leaving.
ORDER_WETH_RAW = 1923063215829457388
#: ``0xb59d000b``, log 114. The USDC the maker received.
ORDER_USDC_RAW = 3046556427

#: Log 106's two data words: the order hash, and ``remaining`` — which is zero because this fill
#: closed the order. Neither is a fill amount.
ORDER_HASH_WORD = "0x7fde61931d7c0e5a3196c348ecd030c2571f4765cf7cbd7d36b183e8f2427b42"
ORDER_REMAINING = 0

# -- ERC-1155, declined -----------------------------------------------------------

SINGLE_TX = "0x8ed9a26a45c101d0f60eb52114c087c72ec45d0b342982f2e9fff0006c2451b0"
SINGLE_LOG_INDEX = 311
SINGLE_CONTRACT = "0x495f947276749ce646f68ac8c248420045cb7b5e"
#: Data word 1 of log 311: the token **id**, not an amount. An OpenSea-packed id whose top 20 bytes
#: are the creator's address, which is why it is enormous.
SINGLE_ID = 44117174291519862098428858737600272443055727955321698122467893821035107057665
#: Data word 2: the value actually transferred.
SINGLE_VALUE = 1

BATCH_TX = "0x4634f02116c89e1cb8438dc19c2f526616c01d80cfc192227e4645245254cad4"
BATCH_LOG_INDEX = 531
BATCH_CONTRACT = "0x76be3b62873462d2142405439777e971754e8e77"
#: Seven ids and seven values in one log, in eighteen data words. There is no fixed width to state.
BATCH_IDS = (10957, 10982, 10987, 10998, 11007, 11012, 11027)
BATCH_DATA_WORDS = 18


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """A test here that reached the chain would be pinning tomorrow's answer, not this one."""

    def refuse(*args, **kwargs):
        raise AssertionError("a test in tests/hand_computed opened a real connection")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture
def client():
    return RpcClient(cache=RecordingCache(RECORDINGS), mode=REPLAY_ONLY)


def _logs(client, tx_hash):
    return logs_of(require_success(require_receipt(client, tx_hash)))


def _log_at(logs, index):
    """The one log at ``index`` in the block, by its own ``logIndex`` rather than by position."""
    for log in logs:
        if int(log["logIndex"], 16) == index:
            return log
    raise AssertionError("no log at index {} in this receipt".format(index))


# -- Uniswap v3 -------------------------------------------------------------------


def test_a_real_uniswap_v3_swap_decodes_as_an_acknowledgement(client):
    """Log 347 comes back named, positioned, and carrying no amount.

    :class:`NoValueEvent` is the whole answer for this signature: it says the log was read and
    classified, not skipped. The amounts are deliberately absent — see the two's-complement test
    below for what reading them would have cost.
    """
    swap = _log_at(_logs(client, V3_TX), 347)

    assert decode_log(swap) == NoValueEvent(
        name="Swap", topic=SWAP_V3, address=V3_POOL_1, log_index=347
    )


def test_the_v3_swap_restates_transfers_in_the_same_receipt(client):
    """The falsification attempt. ``moves_value=False`` is a lie unless these legs are here.

    Both hops, both directions. The v3 ``Swap`` at log 347 says the pool took
    ``V3_TOKEN_1_RAW`` in and paid ``V3_USDC_RAW`` out; logs 345 and 344 are those two movements as
    ERC-20 ``Transfer``s. The same for log 350 against logs 349 and 348. Nothing in either ``Swap``
    is a movement the receipt does not already carry, so classifying it as a restatement loses no
    leg — which is exactly the claim the entry makes and the only claim it makes.
    """
    events = {event.log_index: event for event in decode_logs(_logs(client, V3_TX))}

    # hop 1: token1 in, USDC out
    assert events[345] == TokenTransfer(
        token=V3_TOKEN_1, from_addr=V3_TAKER, to_addr=V3_POOL_1,
        raw_amount=V3_TOKEN_1_RAW, log_index=345,
    )
    assert events[344] == TokenTransfer(
        token=USDC, from_addr=V3_POOL_1, to_addr=V3_EXCHANGE_PROXY,
        raw_amount=V3_USDC_RAW, log_index=344,
    )
    assert isinstance(events[347], NoValueEvent)

    # hop 2: the same USDC in, WETH out
    assert events[349] == TokenTransfer(
        token=USDC, from_addr=V3_EXCHANGE_PROXY, to_addr=V3_POOL_2,
        raw_amount=V3_USDC_RAW, log_index=349,
    )
    assert events[348] == TokenTransfer(
        token=WETH, from_addr=V3_POOL_2, to_addr=V3_TAKER,
        raw_amount=V3_WETH_RAW, log_index=348,
    )
    assert isinstance(events[350], NoValueEvent)


def test_the_v3_amount_words_are_signed_and_nothing_here_reads_them(client):
    """The trap, on the bytes that set it: a negative ``int256`` read unsigned is astronomical.

    ``amount1`` on both hops is the leg the pool paid *out*, so both are negative. Each word is
    64 hex digits of ``f``-prefixed two's complement, and each is a perfectly well-formed
    ``uint256`` — it would pass ``_uint256_word``, pass ``Transfer.__post_init__``'s unsigned
    check, and arrive downstream as a position of 1.16e77 raw units to be priced and scored.

    The literals below are stated, not computed from the code under test: the word is copied from
    the receipt and the unsigned reading is ``2**256`` minus the real magnitude, which is written
    out. What makes the trap unreachable is not a sign-extension helper — there is none — but the
    entry's ``moves_value=False``, which means no word of this log is ever read at all. That is
    what this test pins: the words are here, they are signed, and the decoder returns an event with
    no amount on it.
    """
    logs = _logs(client, V3_TX)
    hop_1, hop_2 = _log_at(logs, 347), _log_at(logs, 350)

    words_1 = _data_words(hop_1)
    words_2 = _data_words(hop_2)

    assert words_1[1] == V3_AMOUNT1_WORD_HOP_1
    assert int(words_1[1], 16) == V3_AMOUNT1_AS_UNSIGNED_HOP_1
    assert V3_AMOUNT1_AS_UNSIGNED_HOP_1 - 2 ** 256 == -V3_USDC_RAW

    assert words_2[1] == V3_AMOUNT1_WORD_HOP_2
    assert int(words_2[1], 16) == V3_AMOUNT1_AS_UNSIGNED_HOP_2
    assert V3_AMOUNT1_AS_UNSIGNED_HOP_2 - 2 ** 256 == -V3_WETH_RAW

    # And the decoded events carry neither reading, because they carry no amount.
    for decoded in (decode_log(hop_1), decode_log(hop_2)):
        assert isinstance(decoded, NoValueEvent)
        assert not hasattr(decoded, "raw_amount")


def test_the_whole_v3_receipt_now_decodes_to_four_legs(client):
    """End to end. Before this ticket the ``Swap`` at log 347 refused the entire receipt.

    Four legs, ordered by log index, and no ``native_settlement`` argument — this transaction has
    no WETH wrap or unwrap, which is why it was chosen: the whole of what is asserted here is the
    registry's doing.
    """
    legs = transfers_from_logs(_logs(client, V3_TX))

    assert [leg.log_index for leg in legs] == [344, 345, 348, 349]
    assert [leg.raw_amount for leg in legs] == [
        V3_USDC_RAW, V3_TOKEN_1_RAW, V3_WETH_RAW, V3_USDC_RAW,
    ]


# -- Curve ------------------------------------------------------------------------


def test_a_real_curve_token_exchange_decodes_as_an_acknowledgement(client):
    exchange = _log_at(_logs(client, CURVE_TX), 12)

    assert decode_log(exchange) == NoValueEvent(
        name="TokenExchange", topic=TOKEN_EXCHANGE, address=CURVE_POOL, log_index=12
    )


def test_the_token_exchange_restates_transfers_in_the_same_receipt(client):
    """``tokens_sold`` and ``tokens_bought`` are the two ``Transfer`` amounts, word for word.

    This receipt is three logs, so there is nowhere for a fourth movement to hide: the USDT in at
    log 10 and the USDC out at log 11 are the whole of what the pool did, and the ``TokenExchange``
    at log 12 names both of them again. That equality is asserted against the raw data words rather
    than against a re-decode, so it would fail if either side moved.
    """
    events = {event.log_index: event for event in decode_logs(_logs(client, CURVE_TX))}

    assert events[10] == TokenTransfer(
        token=USDT, from_addr=CURVE_BUYER, to_addr=CURVE_POOL,
        raw_amount=CURVE_USDT_RAW, log_index=10,
    )
    assert events[11] == TokenTransfer(
        token=USDC, from_addr=CURVE_POOL, to_addr=CURVE_BUYER,
        raw_amount=CURVE_USDC_RAW, log_index=11,
    )

    sold_id, tokens_sold, bought_id, tokens_bought = [
        int(word, 16) for word in _data_words(_log_at(_logs(client, CURVE_TX), 12))
    ]
    assert (sold_id, bought_id) == (CURVE_SOLD_ID, CURVE_BOUGHT_ID)
    assert tokens_sold == CURVE_USDT_RAW
    assert tokens_bought == CURVE_USDC_RAW


def test_the_whole_curve_receipt_now_decodes_to_two_legs(client):
    legs = transfers_from_logs(_logs(client, CURVE_TX))

    assert [(leg.token, leg.raw_amount) for leg in legs] == [
        (USDT, CURVE_USDT_RAW), (USDC, CURVE_USDC_RAW),
    ]


# -- 1inch OrderFilled ------------------------------------------------------------


def test_a_real_order_filled_decodes_as_an_acknowledgement(client):
    """A second witness, independent of the tracer bullet's ``0x559e18c0…``.

    Same router, different order, different settlement asset — this one pays the maker in USDC and
    never touches a WETH unwrap, so it exercises the entry without the native leg riding along.
    """
    fill = _log_at(_logs(client, ORDER_TX), 106)

    assert decode_log(fill) == NoValueEvent(
        name="OrderFilled", topic=ORDER_FILLED, address=ONEINCH_ROUTER, log_index=106
    )


def test_order_filled_carries_an_order_hash_and_a_residual_not_an_amount(client):
    """The reason this entry is a restatement rather than a mover, read off the log.

    Its two data words are the order hash and ``remaining`` — how much of the maker's amount is
    *still unfilled*. On this log ``remaining`` is 0 because the fill closed the order, and a
    decoder that had read word 2 positionally as "the amount" would therefore have recorded a fill
    of nothing at all on a transaction that moved 1.92 WETH. On a partial fill it would have
    recorded the leftover. Neither is a movement; the movements are the ``Transfer``s.
    """
    order_hash, remaining = _data_words(_log_at(_logs(client, ORDER_TX), 106))

    assert order_hash == ORDER_HASH_WORD
    assert int(remaining, 16) == ORDER_REMAINING
    assert ORDER_WETH_RAW != ORDER_REMAINING


def test_order_filled_restates_transfers_in_the_same_receipt(client):
    """The maker's WETH out at log 107 and its USDC back at log 114, both as ordinary Transfers."""
    events = {event.log_index: event for event in decode_logs(_logs(client, ORDER_TX))}

    assert events[107] == TokenTransfer(
        token=WETH, from_addr=ORDER_MAKER, to_addr=ORDER_RESOLVER,
        raw_amount=ORDER_WETH_RAW, log_index=107,
    )
    assert events[114] == TokenTransfer(
        token=USDC, from_addr=ORDER_SETTLEMENT, to_addr=ORDER_MAKER,
        raw_amount=ORDER_USDC_RAW, log_index=114,
    )
    assert isinstance(events[106], NoValueEvent)


def test_the_whole_order_receipt_now_decodes_to_six_legs(client):
    """Nine logs in, six value legs out; the other three are the fill, a v3 ``Swap`` and an approval.

    This receipt needs *both* new entries — ``OrderFilled`` at log 106 and the v3 ``Swap`` at
    log 111 — so it is also the check that widening the registry twice did not leave a gap between
    the two.
    """
    legs = transfers_from_logs(_logs(client, ORDER_TX))

    assert [leg.log_index for leg in legs] == [107, 108, 109, 110, 112, 114]


# -- ERC-1155: declined, and refused ---------------------------------------------


def test_a_real_erc1155_transfer_single_is_still_refused(client):
    """Declined, not admitted, and the refusal names the log so the queue can act on it.

    ``UnknownEvent`` is the same exception an unheard-of topic earns, which is deliberate:
    :mod:`pipeline.chain` turns it into a counted row, and a declined event needs counting for the
    same reason. The three fields are what a quarantine record is built from.
    """
    single = _log_at(_logs(client, SINGLE_TX), SINGLE_LOG_INDEX)

    with pytest.raises(UnknownEvent) as refusal:
        decode_log(single)

    assert refusal.value.topic == TRANSFER_SINGLE
    assert refusal.value.address == SINGLE_CONTRACT
    assert refusal.value.log_index == SINGLE_LOG_INDEX
    assert "deliberately does not admit" in str(refusal.value)


def test_the_erc1155_id_would_have_arrived_as_an_amount(client):
    """Why it is declined rather than added: the trap, measured on this log's own words.

    Data word 1 is the **id** and word 2 is the value. An ERC-20-shaped decoder reads ``data[0:32]``
    as the amount, and on this real log that word is an OpenSea-packed id — the creator's address
    in the top 20 bytes — worth about 4.4e76 raw units. The actual transfer is of one unit.

    The gap between the two is the whole argument. It is not a rounding error and it is not a crash:
    it is an ordinary unsigned integer that would price and score, and 1155 has its own topic so no
    topic-count guard would ever see it. The only thing standing between that word and a published
    number is that this topic is not in ``SIGNATURES``.
    """
    words = _data_words(_log_at(_logs(client, SINGLE_TX), SINGLE_LOG_INDEX))

    assert int(words[0], 16) == SINGLE_ID
    assert int(words[1], 16) == SINGLE_VALUE
    assert SINGLE_ID > 4 * 10 ** 76 > SINGLE_VALUE


def test_a_real_erc1155_transfer_batch_is_still_refused(client):
    """Seven assets in one log, in a data field with no fixed width to state."""
    batch = _log_at(_logs(client, BATCH_TX), BATCH_LOG_INDEX)

    with pytest.raises(UnknownEvent) as refusal:
        decode_log(batch)

    assert refusal.value.topic == TRANSFER_BATCH
    assert refusal.value.address == BATCH_CONTRACT
    assert len(_data_words(batch)) == BATCH_DATA_WORDS
    assert [int(word, 16) for word in _data_words(batch)[3:10]] == list(BATCH_IDS)
    assert len(set(BATCH_IDS)) == len(BATCH_IDS), (
        "seven distinct ids on one contract; token=contract would net them against each other"
    )


def test_the_declined_entries_name_the_logs_they_were_measured_on():
    """The written reasons cite real bytes, and this is what keeps that honest.

    A reason that cited a transaction nobody had recorded would be indistinguishable from a reason
    somebody made up, which is the failure this whole file exists to prevent one level down.
    """
    assert SINGLE_TX[:10] in DECLINED[TRANSFER_SINGLE].reason
    assert BATCH_TX[:10] in DECLINED[TRANSFER_BATCH].reason
    assert str(BATCH_LOG_INDEX) in DECLINED[TRANSFER_BATCH].reason
    assert str(SINGLE_LOG_INDEX) in DECLINED[TRANSFER_SINGLE].reason


# -- the shapes the entries state, checked against the real logs ------------------


@pytest.mark.parametrize(
    "topic,tx_hash,index",
    [
        (ORDER_FILLED, ORDER_TX, 106),
        (SWAP_V3, V3_TX, 347),
        (TOKEN_EXCHANGE, CURVE_TX, 12),
    ],
)
def test_each_new_entry_states_the_shape_its_real_log_has(client, topic, tx_hash, index):
    """``topics`` and ``data_words`` are enforced on every log, so a wrong one refuses everything.

    Stated in the registry from an ABI and checked here against the chain. If the two disagreed the
    entry would be worse than absent: every real occurrence of the event would raise
    ``LogShapeMismatch``, and every transaction carrying one would be quarantined for a reason that
    was this file's fault rather than the chain's.
    """
    signature = SIGNATURES[topic]
    log = _log_at(_logs(client, tx_hash), index)

    assert len(log["topics"]) == signature.topics
    assert len(_data_words(log)) == signature.data_words


def _data_words(log):
    """``log["data"]`` as a list of ``0x``-prefixed 32-byte words. Test-local on purpose.

    :mod:`ingest.events` has no function that hands back the words of an event it classifies as
    moving nothing — that is the property under test — so these tests do the split themselves
    rather than reaching for a helper the decoder does not have.
    """
    body = log["data"][2:]
    assert len(body) % 64 == 0, "not a whole number of ABI words: {!r}".format(log["data"])
    return ["0x" + body[start:start + 64] for start in range(0, len(body), 64)]
