"""The tracer bullet: one real transaction, decoded, every number pinned by hand.

Every other file under ``tests/hand_computed`` pins arithmetic against values computed on paper.
This one pins a decode against **bytes Ethereum mainnet actually returned**, replayed from the
committed snapshot in ``tests/fixtures/transport/recordings``. Nothing here opens a socket: the
client runs in ``REPLAY_ONLY``, so a call the snapshot does not hold raises rather than quietly
measuring a different chain than the one these literals were read off.

The transaction, from ticket 19's brief:

    tx      0xb8681e7a43edca5fe12d5fc0183b901d73255f86e4188715e3d556ba57f269e3
    block   16308001
    wallet  0xe15b3d62c2bce51f2a8a8d53d76c36b4fab8721c
    to      0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45   (Uniswap Universal Router)
    value   0 wei

Eight logs, two hops, and a final leg that unwraps WETH to native ETH:

    34  Transfer  0x97e6…  wallet -> pair1        137_600_202_427_056_205_955
    35  Transfer  USDC     pair1  -> pair2                       41_407_684
    36  Sync      pair1
    37  Swap      pair1
    38  Transfer  WETH     pair2  -> router            34_502_101_357_740_557
    39  Sync      pair2
    40  Swap      pair2
    41  Withdrawal WETH    router                      34_502_101_357_740_557

Every literal below was read off those bytes by hand. None of them is recomputed by calling the
code under test with a different spelling of the same expression.

Two things this file establishes that the brief asserted
--------------------------------------------------------

**Where the native ETH landed, without a trace.** ``test_the_native_settlement_is_confirmed_by_the
_wallets_own_balance`` closes the identity ``balance delta + gas = withdrawal`` from archive state.
That is the evidence for the one input :func:`ingest.receipts.transfers_from_logs` refuses to
guess.

**That the transaction is *not* inside window 1.** The brief says "block 16308001, January 2023,
inside window 1". Measured against §6.3's window 1 train period (Jan 2023 – Jun 2023), it is not:
the block's own timestamp is 2022-12-31T23:22:23Z, 2,257 seconds before the period opens. See
``test_the_tracer_bullet_falls_just_outside_window_1``.
"""

import os
import urllib.request

import pytest

from contracts import NATIVE_ETH, WETH
from ingest import (
    DecimalsReader,
    NativeUnwrap,
    NoValueEvent,
    TokenTransfer,
    decode_logs,
    gas_cost,
    logs_of,
    native_balance_delta,
    native_legs,
    require_receipt,
)
from pipeline import observed_transaction, window_from_blocks
from transport import REPLAY_ONLY, RecordingCache, RpcClient

RECORDINGS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fixtures", "transport", "recordings",
)

# -- the transaction ------------------------------------------------------------

TX = "0xb8681e7a43edca5fe12d5fc0183b901d73255f86e4188715e3d556ba57f269e3"
BLOCK = 16308001
#: ``0x63b0c42f``. 2022-12-31T23:22:23Z — see the window test below.
TIMESTAMP = 1672528943
BLOCK_HASH = "0x87add6e0e83d92f3ed41e260380b44693a74ec03fb5388c0f767fc1a778edbf5"

WALLET = "0xe15b3d62c2bce51f2a8a8d53d76c36b4fab8721c"
ROUTER = "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45"
PAIR_1 = "0xfa2556534f435935b3562f8819d40bbf7b2b470d"
PAIR_2 = "0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc"
TOKEN_X = "0x97e6e31afb2d93d437301e006d9da714616766a5"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"

#: ``0x775961f11fe873083``, log 34. TOKEN_X leaving the wallet.
TOKEN_X_RAW = 137600202427056205955
#: ``0x277d4c4``, log 35. USDC between the two pairs.
USDC_RAW = 41407684
#: ``0x7a937a776ec20d``, logs 38 and 41. The WETH leg, and the ETH the unwrap released.
WETH_RAW = 34502101357740557

#: The log index of the ``Withdrawal``. Named because the settlement mapping is keyed by it.
UNWRAP_LOG = 41

# -- gas and balances -----------------------------------------------------------

#: ``gasUsed`` 0x2e743 = 190_275, ``effectiveGasPrice`` 0x36c303300 = 14_700_000_000 wei.
GAS_USED = 190275
GAS_PRICE = 14700000000
GAS_COST = 2797042500000000

#: ``eth_getBalance(WALLET, 0xf8d720)`` = 0x644b47bc70a0d7.
BALANCE_BEFORE = 28230269147324631
#: ``eth_getBalance(WALLET, 0xf8d721)`` = 0xd4eedcff3d09e4.
BALANCE_AFTER = 59935328005065188

# -- §6.3 window 1, train period (Jan 2023 - Jun 2023) --------------------------

#: 2023-01-01T00:00:00Z and 2023-07-01T00:00:00Z as UTC seconds.
JAN_1_2023 = 1672531200
JUL_1_2023 = 1688169600

#: The first block whose timestamp is at or after JAN_1_2023, found by bisection over headers and
#: pinned here with the block before it as evidence that it is the first.
WINDOW_1_START_BLOCK = 16308190
WINDOW_1_START_TS = 1672531211
BLOCK_BEFORE_WINDOW_1 = 16308189
BLOCK_BEFORE_WINDOW_1_TS = 1672531199

#: The last block whose timestamp is before JUL_1_2023, with the block after it as the same
#: evidence on the closing edge.
WINDOW_1_END_BLOCK = 17595509
WINDOW_1_END_TS = 1688169599
BLOCK_AFTER_WINDOW_1 = 17595510
BLOCK_AFTER_WINDOW_1_TS = 1688169611


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Replay-only is the claim; a poisoned socket is the proof."""

    def refuse(*args, **kwargs):
        raise AssertionError(
            "tests/hand_computed/test_ingest.py opened a real connection. Every byte it reads "
            "comes from the committed snapshot; a test that reaches the chain pins today's answer "
            "rather than the one these literals were read off."
        )

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture
def client():
    return RpcClient(cache=RecordingCache(RECORDINGS), mode=REPLAY_ONLY)


@pytest.fixture
def tracer(client):
    return observed_transaction(client, TX, native_settlement={UNWRAP_LOG: WALLET})


# -- the eight logs -------------------------------------------------------------


def test_every_log_is_accounted_for_and_none_is_skipped(client):
    """Eight logs in, eight decoded events out: four movements and four acknowledged non-events.

    The count is the assertion. A decoder that recognised the three transfers and the withdrawal
    and returned nothing for Sync and Swap would satisfy every other test in this file, and would
    be one unlisted signature away from dropping a real settlement.
    """
    receipt = require_receipt(client, TX)
    events = decode_logs(logs_of(receipt))

    assert len(events) == 8
    assert [event.log_index for event in events] == [34, 35, 36, 37, 38, 39, 40, 41]
    assert [type(event).__name__ for event in events] == [
        "TokenTransfer", "TokenTransfer", "NoValueEvent", "NoValueEvent",
        "TokenTransfer", "NoValueEvent", "NoValueEvent", "NativeUnwrap",
    ]
    assert [event.name for event in events if isinstance(event, NoValueEvent)] == [
        "Sync", "Swap", "Sync", "Swap",
    ]


def test_the_three_erc20_transfers_decode_to_the_bytes_on_chain(client):
    receipt = require_receipt(client, TX)
    transfers = [e for e in decode_logs(logs_of(receipt)) if isinstance(e, TokenTransfer)]

    assert transfers == [
        TokenTransfer(token=TOKEN_X, from_addr=WALLET, to_addr=PAIR_1,
                      raw_amount=TOKEN_X_RAW, log_index=34),
        TokenTransfer(token=USDC, from_addr=PAIR_1, to_addr=PAIR_2,
                      raw_amount=USDC_RAW, log_index=35),
        TokenTransfer(token=WETH, from_addr=PAIR_2, to_addr=ROUTER,
                      raw_amount=WETH_RAW, log_index=38),
    ]


def test_the_withdrawal_is_the_native_leg_and_names_only_the_router(client):
    """The unwrap says how much and says the router — and does not say where it went next."""
    receipt = require_receipt(client, TX)
    unwraps = [e for e in decode_logs(logs_of(receipt)) if isinstance(e, NativeUnwrap)]

    assert unwraps == [NativeUnwrap(holder=ROUTER, raw_amount=WETH_RAW, log_index=UNWRAP_LOG)]
    assert native_legs(logs_of(receipt)) == (UNWRAP_LOG,)


# -- the assembled ObservedTransaction ------------------------------------------


def test_the_observed_transaction_carries_the_chains_own_identity(tracer):
    assert tracer.tx_hash == TX
    assert tracer.block_number == BLOCK
    assert tracer.timestamp == TIMESTAMP
    assert tracer.tx_sender == WALLET
    assert tracer.success is True


def test_the_four_transfers_in_log_order_with_the_unwrap_settled_on_the_wallet(tracer):
    """The whole decode, as five-tuples, in one assertion.

    The fourth leg is the synthesised one: the native ETH the router released, moving to the
    wallet. Its token is spelled ``WETH`` here because ``contracts.Transfer.__post_init__``
    collapses ``NATIVE_ETH`` onto it (§4.2) — the ingest code passes the sentinel, and the frozen
    seam does the collapse.
    """
    assert [(t.token, t.from_addr, t.to_addr, t.raw_amount, t.log_index)
            for t in tracer.transfers] == [
        (TOKEN_X, WALLET, PAIR_1, TOKEN_X_RAW, 34),
        (USDC, PAIR_1, PAIR_2, USDC_RAW, 35),
        (WETH, PAIR_2, ROUTER, WETH_RAW, 38),
        (WETH, ROUTER, WALLET, WETH_RAW, 41),
    ]
    assert NATIVE_ETH != WETH, "the collapse above is a real one, not two names for one string"


def test_the_wallets_own_net_is_one_token_out_and_one_asset_in(tracer):
    """What the wallet actually did, summed by hand from the four legs.

    Two tokens touch the wallet and no others: TOKEN_X leaves, the collapsed ETH/WETH asset
    arrives. The intermediate USDC hop and the pair-to-router WETH hop cancel out of the wallet's
    own account because neither endpoint is the wallet.
    """
    net = {}
    for leg in tracer.transfers:
        if leg.from_addr == WALLET:
            net[leg.token] = net.get(leg.token, 0) - leg.raw_amount
        if leg.to_addr == WALLET:
            net[leg.token] = net.get(leg.token, 0) + leg.raw_amount

    assert net == {TOKEN_X: -137600202427056205955, WETH: 34502101357740557}


def test_the_router_nets_to_zero_once_the_unwrap_is_settled(tracer):
    """The router is a pass-through, and the decode says so rather than being told so.

    It receives WETH at log 38 and pays out the same asset at log 41. If the settlement address
    were wrong the router would net non-zero — which is the cheapest check a caller has on the one
    input this package makes them supply.
    """
    net = 0
    for leg in tracer.transfers:
        if leg.token != WETH:
            continue
        if leg.from_addr == ROUTER:
            net -= leg.raw_amount
        if leg.to_addr == ROUTER:
            net += leg.raw_amount

    assert net == 0


# -- decimals -------------------------------------------------------------------


def test_decimals_are_read_from_the_chain_for_every_token_touched(client, tracer):
    """WETH 18, USDC 6, and the traded token 18 — each from its own ``decimals()`` call."""
    reader = DecimalsReader(client, BLOCK)

    assert reader.for_transfers(tracer.transfers) == {
        TOKEN_X: 18,
        USDC: 6,
        WETH: 18,
    }


def test_the_weth_leg_at_the_wrong_scale_is_not_a_small_error(client):
    """Why decimals are read rather than assumed, stated as the two numbers it moves between.

    ``34_502_101_357_740_557`` raw units is 0.0345 ETH at 18 decimals. Read at USDC's 6 it is
    34,502,101,357 ETH — more ether than has ever existed, and still an ordinary-looking integer.
    """
    reader = DecimalsReader(client, BLOCK)

    assert reader.for_token(WETH) == 18
    assert WETH_RAW // 10 ** 18 == 0
    assert WETH_RAW // 10 ** 6 == 34502101357


# -- the native settlement, established rather than asserted ---------------------


def test_the_native_settlement_is_confirmed_by_the_wallets_own_balance(client):
    """balance delta + gas = the Withdrawal amount, to the wei. No trace involved.

    This is the whole of the evidence that the router forwarded the ETH to the wallet, and it is
    what justifies the ``{41: WALLET}`` supplied everywhere above.

    The precondition — the wallet has exactly one transaction in block 16308001 and received
    nothing else in it — is stated here rather than checked by
    :mod:`ingest.settlement`, which says so: with another transaction in the same block the
    identity would still be arithmetic and would confirm the wrong thing.
    """
    assert gas_cost(require_receipt(client, TX)) == GAS_COST
    assert GAS_USED * GAS_PRICE == GAS_COST

    delta = native_balance_delta(client, WALLET, BLOCK)

    assert BALANCE_AFTER - BALANCE_BEFORE == 31705058857740557
    assert delta == 31705058857740557
    assert delta + GAS_COST == WETH_RAW


# -- §6.3 window 1 --------------------------------------------------------------


def test_window_1s_train_edges_are_the_blocks_the_chain_puts_them_on(client):
    """Both edges read from headers, with their neighbours as the evidence they are the edges."""
    from ingest import block_header

    window = window_from_blocks(client, 1, WINDOW_1_START_BLOCK, WINDOW_1_END_BLOCK)

    assert (window.index, window.start_block, window.start_ts) == (
        1, WINDOW_1_START_BLOCK, WINDOW_1_START_TS)
    assert (window.end_block, window.end_ts) == (WINDOW_1_END_BLOCK, WINDOW_1_END_TS)

    # The edges are edges: the block before opens before 2023 began, the block after closes after
    # June ended.
    assert block_header(client, BLOCK_BEFORE_WINDOW_1).timestamp == BLOCK_BEFORE_WINDOW_1_TS
    assert BLOCK_BEFORE_WINDOW_1_TS < JAN_1_2023 <= WINDOW_1_START_TS
    assert block_header(client, BLOCK_AFTER_WINDOW_1).timestamp == BLOCK_AFTER_WINDOW_1_TS
    assert WINDOW_1_END_TS < JUL_1_2023 <= BLOCK_AFTER_WINDOW_1_TS


def test_the_tracer_bullet_falls_just_outside_window_1(client, tracer):
    """The brief's "January 2023, inside window 1" is off by 37 minutes, measured.

    Block 16308001's own timestamp is 1672528943 = 2022-12-31T23:22:23Z, and §6.3 opens window 1's
    train period at 2023-01-01T00:00:00Z. The gap is 2,257 seconds and 189 blocks.

    Kept as an assertion rather than fixed by moving the window, because the window is the
    specification and the transaction is the measurement. What it costs is nothing for this
    ticket — the decode does not depend on a window — and it is exactly the kind of claim that is
    cheap to state and expensive to discover later inside a selection step.
    """
    window = window_from_blocks(client, 1, WINDOW_1_START_BLOCK, WINDOW_1_END_BLOCK)

    assert tracer.timestamp == TIMESTAMP < JAN_1_2023
    assert JAN_1_2023 - TIMESTAMP == 2257
    assert WINDOW_1_START_BLOCK - BLOCK == 189
    assert window.contains(tracer.block_number, tracer.timestamp) is False


# -- provenance -----------------------------------------------------------------


def test_the_whole_tracer_bullet_replays_and_contacts_nothing(client):
    """Ten calls, every one from the snapshot. Reproducible on a laptop with no network."""
    observed_transaction(client, TX, native_settlement={UNWRAP_LOG: WALLET})
    DecimalsReader(client, BLOCK).for_token(WETH)
    native_balance_delta(client, WALLET, BLOCK)
    window_from_blocks(client, 1, WINDOW_1_START_BLOCK, WINDOW_1_END_BLOCK)

    replayed, live = client.replayed_count()

    assert live == 0
    assert replayed == 7
    assert {record.endpoint for record in client.calls} == {
        "https://eth-mainnet.public.blastapi.io"
    }
    assert all(record.replayed for record in client.calls)
