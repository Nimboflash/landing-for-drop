"""Ticket 19's tracer bullet: one real wallet, one real window, driven through the real pipeline.

    PYTHONPATH=src .venv/bin/python -m tools.tracer_bullet

Every byte comes from ``tests/fixtures/tracer_bullet/recordings``, replayed. The default mode is
``REPLAY_ONLY``: a call the snapshot does not hold raises rather than quietly measuring a different
chain than the one the printed numbers were checked against. ``--record`` is how the snapshot is
(re-)made, and it is the only mode that opens a socket.

What this reproduces
--------------------

One wallet — ``0xe15b3d62c2bce51f2a8a8d53d76c36b4fab8721c``, the address ticket 19 names — over
February 2023, with the §4.8 measurement tail running to 30 days past the window's end. Seven
transactions, decoded from receipts by :mod:`ingest`, assembled by :mod:`pipeline.chain`, and run
through :func:`pipeline.run_wallet_window` — the real composition root, with no stage skipped and
no shortcut around it.

**All seven reach the pipeline, and all seven now decode.** That took two tickets and the second
one is why the sentence changed.

On this bullet's first run the seventh transaction — a 1inch limit-order fill — did not reach the
pipeline at all. Its ``OrderFilled`` log was not in ``ingest.events.SIGNATURES``, the decoder's
refusal was an exception raised *before* ``run_wallet_window`` was called, ``census.total`` read 6
against a real population of 7, and every published number reconciled against the smaller figure
with nothing anywhere to say so. That is the finding this file exists to have made.

It was answered twice, in that order and deliberately so. :mod:`pipeline.inputs` made a refusal
*survivable*: an unreadable receipt became :class:`pipeline.UndecodableTransaction`, a counted row
in the census and a named record in the quarantine queue. Only then did ticket 20 widen the
registry, because widening it first would have fixed this one transaction and left the next
unlisted event silently doing the same thing. With ``OrderFilled`` admitted the fill decodes to
five transfer legs, nets against the tail buy, and classifies ``VALID_SELL``.

So this run's ``census.undecodable`` is 0 and its queue is empty — which means **this file no
longer exercises the machinery that finding produced.** ``tests/hand_computed/test_undecodable_
population.py`` does, on an event that is still unlisted. A registry is never finished, and the run
that proves the counting works must not be the run whose gap happened to be closed.

What it does **not** reproduce: a measurement of anything. One wallet is one wallet. See the
report accompanying ticket 19 for what this establishes and what it does not.

The inputs that are the caller's, and where each came from
----------------------------------------------------------

Six things this run supplies that no receipt contains. Each is stated here rather than derived,
because deriving them is a different ticket, and each is checkable by a reader:

* **the window's edges** (:data:`WINDOW_START_BLOCK`, :data:`WINDOW_END_BLOCK`) — the first block
  at or after 2023-02-01T00:00:00Z and the last before 2023-03-01T00:00:00Z, found by bisection
  over headers. The blocks on either side are read too, and :func:`confirm_window_edges` checks
  that they straddle the calendar boundary, so the claim "this is where February starts" is a
  measurement in the run rather than an assertion in a comment;
* **the population** (:data:`TRANSACTIONS`) — every transaction touching the wallet inside the
  measurement period, taken from a block explorer's account listing. It is a caller input because
  nothing in this repository enumerates a wallet's transactions, and the transaction at
  :data:`ETH_IN_TX` shows why it cannot be done from logs alone: a plain ETH transfer to an EOA
  emits no log at all;
* **the native settlements** (:data:`NATIVE_SETTLEMENT`) — where each WETH wrap or unwrap's native
  ETH came from or went to. Stated by the caller, as :mod:`ingest.receipts` requires, and then
  *confirmed by measurement* in :func:`confirm_native_settlements` against the wallet's own archive
  balance. No trace is used anywhere in this run;
* **the price book** (:func:`read_weth_price`) — one USD price per §4.6 quote asset, read from
  Chainlink's ETH/USD aggregator on-chain at the window's opening block. The pipeline's seam takes
  one scalar per quote asset for a whole window; that is a real limitation and the report says what
  it costs.

* **the §6.2 address typing** (:data:`INFRASTRUCTURE`, :func:`build_context`) — which of the
  addresses on a transfer leg are venues. Half of it is measured (``eth_getCode`` says which carry
  code) and half is stated, because nothing on-chain distinguishes a router from a smart-account
  portfolio. Without it every one of these transactions resolves ``UNRESOLVED`` and the run scores
  nothing at all; that was measured before the typing was added, and it is the sharpest thing this
  bullet found.

The §4.7 token trading start is the sixth, and it is measured here rather than assumed: see
:data:`TOKEN_START_BLOCK` and :func:`confirm_token_start`.

What is deliberately **not** here: any use of a trace, any `latest` tag, any float, and any
`src/groundtruth/`.
"""

import argparse
import os
import sys
from dataclasses import replace

from attribution import AttributionContext
from contracts import WETH, calc, divide
from ingest import (
    LogRefused,
    block_header,
    gas_cost,
    native_balance,
    native_legs,
    logs_of,
    require_receipt,
    require_success,
    token_decimals,
)
from pipeline import (
    ObservedTransaction,
    TokenStart,
    UndecodableTransaction,
    WindowConfig,
    observed_transaction,
    run_wallet_window,
    window_from_blocks,
)
from transport import AUTO, REPLAY_ONLY, RecordingCache, RpcClient, block_parameter

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Its own snapshot directory. Deliberately not the one under ``tests/fixtures/transport``: that
#: snapshot's fingerprint is pinned by ``tests/transport/test_cache.py``, and a run that added
#: calls to it would turn a reproducibility check into a chore.
RECORDINGS = os.path.join(REPO, "tests", "fixtures", "tracer_bullet", "recordings")

# -- the wallet -----------------------------------------------------------------

#: Ticket 19's wallet, kept rather than replaced. It satisfies the brief's test — a clean buy that
#: spends a quote asset and receives a non-quote token — inside the required period, and no leg of
#: any of its seven transactions needs a trace.
WALLET = "0xe15b3d62c2bce51f2a8a8d53d76c36b4fab8721c"

#: The token it trades, and the Uniswap v2 pair it trades it in.
XUSDP = "0xa1f7c9c6d19e2d0bf20729cb0bf03338a90bed9b"
PAIR = "0xee19920b7da72b0520e3c3f367aab7479e89607b"

# -- the window: February 2023, with §4.8's 30-day tail -------------------------

#: 2023-02-01T00:00:00Z and 2023-03-01T00:00:00Z as UTC seconds.
FEB_1_2023 = 1675209600
MAR_1_2023 = 1677628800

WINDOW_INDEX = 1

#: First block at or after ``FEB_1_2023``; the block before it is read as the evidence that it is
#: the first.
WINDOW_START_BLOCK = 16530248
BLOCK_BEFORE_WINDOW = 16530247

#: Last block before ``MAR_1_2023``, with the block after it as the same evidence.
WINDOW_END_BLOCK = 16730071
BLOCK_AFTER_WINDOW = 16730072

#: §4.8's marking horizon: the first block at or after ``window.end_ts + 30 days``. Every open
#: position is valued here and every transaction up to here is part of the measurement period.
HORIZON_BLOCK = 16943478

# -- the population -------------------------------------------------------------

#: The clean buy. 0.024955171186740727 ETH out (wrapped by the router at log 351), 6,803.43 XUSDP
#: in. Inside the window.
BUY_TX = "0x10ab9b812107769650f6661c164a5bcfeca80caf67528aebde33090ab63ffc60"

#: The sale that closes it, 16 hours later and still inside the window. The proceeds arrive as
#: native ETH through the unwrap at log 573.
SELL_TX = "0xce4e2048a41ae098cdfd93131895e16d57bd41f6fe1a748bf264178894a1ef42"

#: A plain ETH payment out. No logs at all, so it decodes to no transfers.
ETH_OUT_TX = "0x20562173ef9b9dd70d50f664fc975ac2b08b4bb822f38d249edd3e837b376c31"

#: A plain ETH payment *in*, sent by somebody else. The wallet is the recipient, so its own
#: ``tx_sender`` is a stranger's address. No logs, and therefore invisible to any enumeration that
#: works from logs.
ETH_IN_TX = "0x6d9ce0a41e622f40111e8ea7f82512d17e3d656404b1c36aaf6f6cbc197bd0f3"

#: A second buy of the same token, in the measurement tail. §4.8 opens its lot and defers its
#: score to the next window.
TAIL_BUY_TX = "0xa51f7010a2ddb12a5d3cb45ed6084c569b85d834141cf078e69e20a4dcfbdef4"

#: The 1inch limit order that closes the tail buy — filled by a third-party resolver, so the
#: transaction's sender is not the wallet.
TAIL_SELL_TX = "0x559e18c0d5cd7704369dfbbe4a9520ad6d4b3e172000460b481e8ec9065e76de"

#: A second plain ETH payment out, in the tail.
TAIL_ETH_OUT_TX = "0x9c9dd3fb5179d2b0b2ddcb2e6376205c0ddf0c79b7bc0e04f6e98e30a7cb8e66"

#: Every transaction touching the wallet between the window's first block and the marking horizon,
#: oldest first. Assembled from a block explorer's account listing — external, internal and token
#: transfers unioned — because nothing in this repository enumerates a wallet's transactions and
#: ``ETH_IN_TX`` cannot be found from logs.
TRANSACTIONS = (
    BUY_TX,
    SELL_TX,
    ETH_OUT_TX,
    ETH_IN_TX,
    TAIL_BUY_TX,
    TAIL_SELL_TX,
    TAIL_ETH_OUT_TX,
)

#: ``{tx_hash: {log_index: address}}`` — where each WETH wrap or unwrap's native ETH came from or
#: went to. Every entry names the wallet, and every entry is confirmed against archive state by
#: :func:`confirm_native_settlements` before the run.
NATIVE_SETTLEMENT = {
    BUY_TX: {351: WALLET},
    SELL_TX: {573: WALLET},
    TAIL_BUY_TX: {803: WALLET},
    TAIL_SELL_TX: {105: WALLET},
}

# -- §4.7: the token's trading start --------------------------------------------

#: XUSDP's pair was created, funded and first swapped in one block — 2021-04-14T02:15:16Z, twenty-one
#: months before this window. Both events are in :func:`confirm_token_start`'s logs, so the start is
#: a measurement here and not a lookup.
TOKEN_START_BLOCK = 12235473

# -- §4.6: the price book -------------------------------------------------------

#: Chainlink's ETH/USD aggregator (the proxy address a reader can open on any explorer) and the
#: ``latestRoundData()`` selector. Written out rather than computed: this file holds no keccak, and
#: a constant is what a reader checks against the explorer's "Read Contract" tab.
CHAINLINK_ETH_USD = "0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419"
LATEST_ROUND_DATA = "0xfeaf968c"

#: The aggregator answers in 8 decimals.
CHAINLINK_DECIMALS = 8

# -- §6.2: what each address in these transactions is ---------------------------

#: Every code-bearing address that appears on a transfer leg in this population, with what it is.
#: §6.2 excludes routers, aggregators, settlement contracts and pools from the candidate universe
#: entirely, and nothing on-chain distinguishes a router from a smart-account portfolio — both are
#: contracts. So this is a **caller input**, taken from a block explorer's labels, and it is the
#: fifth thing this run supplies that no receipt contains.
#:
#: :func:`build_context` refuses to run if a code-bearing address turns up that is not listed here.
#: An unlisted contract left untyped is not a smaller answer: attribution would either refuse the
#: whole transaction or, worse, admit a venue as a candidate portfolio.
#:
#: Five entries. It was two until ticket 20 admitted ``OrderFilled`` to
#: ``ingest.events.SIGNATURES``: the 1inch limit-order fill at :data:`TAIL_SELL_TX` decodes now, and
#: its four transfer legs run through three contracts that no other transaction here touches. So
#: the shortness of the old list was partly an artefact of the decoder's gap — a transaction the
#: decoder could not read is also a transaction whose addresses nobody has to type, and that is a
#: narrowing of the §6.2 evidence that looked like a small list.
#:
#: The three new ones are the 1inch Fusion settlement path, in the order the WETH walks it. Their
#: labels come from a block explorer, as the other two do; the last is additionally *measured*
#: here, in that :func:`confirm_native_settlements` closes the wallet's balance identity to the wei
#: against the ETH it releases. That is a stronger claim than a label, and it is the only one of the
#: five that has it.
#:
#: The payee of the wallet's three plain ETH transfers,
#: ``0x38454e3e70e702b650fb2c5430f2cd2ef56473cf``, is deliberately **not** here: it never appears on
#: a transfer leg, because ``ingest`` reads logs and a plain ETH transfer writes none. An entry for
#: it would be an entry nothing ever reads.
INFRASTRUCTURE = {
    "0x1111111254eeb25477b68fb85ed929f73a960582": "1inch v5 aggregation router",
    "0xee19920b7da72b0520e3c3f367aab7479e89607b": "Uniswap v2 pair XUSDP/WETH",
    "0x84d99aa569d93a9ca187d83734c8c4a519c4e9b1": "1inch Labs resolver — the taker that filled "
                                                  "the order and paid for the fill's gas",
    "0xa88800cd213da5ae406ce248380802bd53b47647": "1inch Fusion settlement contract",
    "0x8290dbccb15b5a516deee2805c58e56075d6605e": "1inch WETH unwrapper — receives the maker's "
                                                  "WETH and forwards native ETH to the maker; the "
                                                  "one address here confirmed by measurement",
}

#: The height every ``eth_getCode`` in this run is taken at. A tag would make "is this an EOA?"
#: an answer about today rather than about the window.
CODE_AT_BLOCK = WINDOW_START_BLOCK


class TracerBulletRefused(RuntimeError):
    """A precondition this run states did not hold when it was measured.

    Raised rather than reported, because every one of them is a claim the printed numbers rest on:
    a window edge that is not an edge, a settlement address the balance does not confirm, or a
    trading start with no liquidity behind it would each make the run publish a number about
    something other than what it says it is about.
    """


# -- the client -----------------------------------------------------------------


def build_client(record=False):
    """The RPC client, replaying by default and recording only when asked."""
    cache = RecordingCache(RECORDINGS)
    return RpcClient(cache=cache, mode=AUTO if record else REPLAY_ONLY)


# -- the four caller inputs, each confirmed by measurement -----------------------


def confirm_window_edges(client):
    """The two blocks outside the window straddle the calendar boundary. Returns their headers.

    Guarantees that ``WINDOW_START_BLOCK`` is the first block of February 2023 and
    ``WINDOW_END_BLOCK`` the last, given the chain these recordings came from. Guarantees nothing
    about either block being canonical — :mod:`ingest.blocks` says so, and no free endpoint offers
    a way to establish it.
    """
    before = block_header(client, BLOCK_BEFORE_WINDOW)
    after = block_header(client, BLOCK_AFTER_WINDOW)
    start = block_header(client, WINDOW_START_BLOCK)
    end = block_header(client, WINDOW_END_BLOCK)
    if not (before.timestamp < FEB_1_2023 <= start.timestamp):
        raise TracerBulletRefused(
            "block {} (ts {}) and block {} (ts {}) do not straddle 2023-02-01T00:00:00Z (ts {}), "
            "so the window does not open where this run says it does.".format(
                BLOCK_BEFORE_WINDOW, before.timestamp, WINDOW_START_BLOCK, start.timestamp,
                FEB_1_2023,
            )
        )
    if not (end.timestamp < MAR_1_2023 <= after.timestamp):
        raise TracerBulletRefused(
            "block {} (ts {}) and block {} (ts {}) do not straddle 2023-03-01T00:00:00Z (ts {}), "
            "so the window does not close where this run says it does.".format(
                WINDOW_END_BLOCK, end.timestamp, BLOCK_AFTER_WINDOW, after.timestamp, MAR_1_2023,
            )
        )
    return before, start, end, after


def confirm_native_settlements(client):
    """Every stated native settlement, checked against the wallet's own archive balance.

    The identity is :mod:`ingest.settlement`'s:

        balance(wallet, block) - balance(wallet, block - 1)  +  gas the wallet paid
            =  the wei the wallet received in native ETH

    Its precondition — the wallet had exactly one transaction in that block and received nothing
    else — is stated by this run and is *not* checked by ``ingest.settlement``. It is checked here
    instead, in the only way a snapshot can: the population above is every transaction touching the
    wallet in the period, so a second transaction in one of these blocks would appear in it.

    Returns one row per transaction with a native leg, for printing. Raises if any identity does not
    close to the wei. A transaction :mod:`ingest.events` refused is still measured — the balance
    delta needs no decoder — and its row carries ``None`` where the legs would have been, because
    the amount to compare against is exactly what the refusal withheld.
    """
    rows = []
    for tx_hash in TRANSACTIONS:
        settlement = NATIVE_SETTLEMENT.get(tx_hash)
        if not settlement:
            continue
        receipt = require_success(require_receipt(client, tx_hash))
        block = int(receipt["blockNumber"], 16)
        same_block = [h for h in TRANSACTIONS if h != tx_hash
                      and _block_of(client, h) == block]
        if same_block:
            raise TracerBulletRefused(
                "the balance identity for {} assumes the wallet had one transaction in block {}, "
                "and this run's own population also holds {}.".format(
                    tx_hash, block, ", ".join(same_block)
                )
            )
        # ``ingest.settlement.native_balance_delta`` is the same subtraction; both balances are read
        # here so the two operands can be printed as evidence rather than only their difference.
        after = native_balance(client, WALLET, block)
        before = native_balance(client, WALLET, block - 1)
        paid_gas = gas_cost(receipt) if receipt["from"].lower() == WALLET else 0
        measured = after - before + paid_gas
        try:
            legs = _native_amounts(receipt)
        except LogRefused:
            rows.append((tx_hash, block, before, after, paid_gas, None, measured))
            continue
        if set(settlement) != {index for index, _ in legs}:
            raise TracerBulletRefused(
                "{} states settlements for log(s) {} and its native legs are at {}".format(
                    tx_hash, sorted(settlement), sorted(index for index, _ in legs)
                )
            )
        # A wrap moves ETH away from the wallet, an unwrap moves it towards: the signed sum of the
        # legs is what the delta must equal once gas is added back.
        expected = sum(amount for _, amount in legs)
        if measured != expected:
            raise TracerBulletRefused(
                "{}: the wallet's balance moved {} wei across block {} and paid {} wei of gas, so "
                "it received {} wei of native ETH; the receipt's WETH wrap/unwrap legs sum to {}. "
                "The stated settlement address is not confirmed.".format(
                    tx_hash, after - before, block, paid_gas, measured, expected
                )
            )
        rows.append((tx_hash, block, before, after, paid_gas, expected, measured))
    return rows


def confirm_token_start(client):
    """§4.7: XUSDP's first usable liquidity *and* first real swap, both read from the chain.

    Returns the :class:`pipeline.TokenStart`. Raises unless the pair's logs at
    ``TOKEN_START_BLOCK`` contain both a ``Mint`` and a ``Swap`` — the two events §4.7 requires
    before a token is deemed to be trading.

    What it does not establish: that this pair is the *first* pool the token ever traded in. That
    is a search over every factory, and this run does not perform one; it establishes that the pool
    this wallet traded in was live twenty-one months before the window, which is what the bucket
    turns on.
    """
    mint = "0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f"
    swap = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
    logs = client.get_logs(
        from_block=TOKEN_START_BLOCK, to_block=TOKEN_START_BLOCK, address=PAIR
    )
    topics = {log["topics"][0] for log in logs}
    missing = [name for name, topic in (("Mint", mint), ("Swap", swap)) if topic not in topics]
    if missing:
        raise TracerBulletRefused(
            "pair {} emitted no {} in block {}, so §4.7's trading start is not established there; "
            "it emitted {} log(s).".format(
                PAIR, " or ".join(missing), TOKEN_START_BLOCK, len(logs)
            )
        )
    header = block_header(client, TOKEN_START_BLOCK)
    return TokenStart(block=header.number, timestamp=header.timestamp)


def read_weth_price(client, block):
    """USD per **raw unit** of WETH, from Chainlink's ETH/USD aggregator at ``block``.

    Two chain reads and one division, all of it in the frozen decimal context. The aggregator's
    answer carries 8 decimals and WETH's own ``decimals()`` is read rather than assumed, so the
    conversion from "dollars per ether" to "dollars per wei" is a measurement in both directions.

    What it does not guarantee: that one price is the right price for a whole window. The seam
    takes one scalar per quote asset, so every trade in this run is sized at the ether price of the
    window's opening block. That is stated, not hidden — see the report.
    """
    answer = _chainlink_answer(client, block)
    weth_decimals = token_decimals(client, WETH, block)
    scale = calc(10) ** (CHAINLINK_DECIMALS + weth_decimals)
    return divide(calc(answer), scale), answer, weth_decimals


# -- the run --------------------------------------------------------------------


def read_population(client):
    """``(population, undecodable)`` — every transaction, and the view of the ones ingestion refused.

    ``population`` holds all seven rows and is what ``run_wallet_window`` is given. A receipt whose
    logs :mod:`ingest.events` cannot decode comes back from :func:`pipeline.observed_transaction`
    as a :class:`pipeline.UndecodableTransaction` rather than as an exception, so it enters the
    population, the census, the quarantine queue and the coverage report like any other row.

    This used to be the sharpest thing the bullet found. The refusal was an exception raised
    *before* ``run_wallet_window`` was called, so the transaction appeared in nothing the run
    published: ``census.total`` read 6 against a real population of 7, every reconciliation
    balanced, and the result type had no field that could have held it. Catching it here and
    printing it was the most an entry point could do. It is no longer an entry point's problem —
    the second return value is a *view* of rows the result already accounts for, kept only so the
    report can print the refusal in the decoder's own words.

    On this population that view is now empty: ticket 20 admitted ``OrderFilled`` and all seven
    receipts decode. The branch stays because the next unlisted event is a matter of which wallet
    is measured, not of whether the registry is finished — and a run whose entry point could not
    represent one would be back where this file started.
    """
    population = []
    undecodable = []
    for tx_hash in TRANSACTIONS:
        item = observed_transaction(
            client, tx_hash, native_settlement=NATIVE_SETTLEMENT.get(tx_hash)
        )
        population.append(item)
        if isinstance(item, UndecodableTransaction):
            undecodable.append(item)
    return tuple(population), tuple(undecodable)


def build_context(client, transactions):
    """The §6.2 address typing, half measured and half stated — and never defaulted.

    Measured: whether each address on a transfer leg carried code at ``CODE_AT_BLOCK``. That is
    ``eth_getCode``, and it is what separates an EOA from a contract without trusting a label.

    Stated: which of the code-bearing ones are venues. Nothing on-chain distinguishes a router from
    a smart-account portfolio, so :data:`INFRASTRUCTURE` supplies that, and an address that carries
    code and is not listed there raises rather than being typed by default. A venue admitted as a
    candidate portfolio is the "phantom mega-wallet" §8 exists to prevent, and a portfolio typed as
    a venue silently deletes a trader.

    Reads only the transfer legs of the transactions that decoded. An
    :class:`pipeline.UndecodableTransaction` carries none — that is what it means — so the
    addresses inside it are typed by nothing here, and that is a real narrowing of this run's §6.2
    evidence rather than an oversight. It is also why the address typing cannot be used as a check
    on the population: it is a statement about the receipts that could be read.

    That narrowing was measured. Before ``OrderFilled`` was admitted this function saw three
    addresses; it now sees six, because the three contracts on the 1inch settlement path were
    inside the one receipt that would not decode. A decoder gap does not only lose a transaction —
    it shrinks the evidence for every judgement made *about* the transactions that remain, and it
    shrinks it invisibly, because the addresses it hides were never asked about.

    Returns ``(context, rows)`` where each row is ``(address, has_code, role)`` for printing.
    """
    decoded = [item for item in transactions if isinstance(item, ObservedTransaction)]
    addresses = sorted({leg.from_addr for item in decoded for leg in item.transfers}
                       | {leg.to_addr for item in decoded for leg in item.transfers})
    rows = []
    eoas = []
    infrastructure = []
    untyped = []
    for address in addresses:
        code = client.call("eth_getCode", [address, _hex_block(CODE_AT_BLOCK)])
        has_code = isinstance(code, str) and code not in ("0x", "0x0", "")
        if not has_code:
            eoas.append(address)
            rows.append((address, False, "EOA (eth_getCode returned no code)"))
        elif address in INFRASTRUCTURE:
            infrastructure.append(address)
            rows.append((address, True, "§6.2 infrastructure — {}".format(INFRASTRUCTURE[address])))
        else:
            untyped.append(address)
    if untyped:
        raise TracerBulletRefused(
            "these addresses carry code at block {} and are not typed in INFRASTRUCTURE: {}. §6.2 "
            "excludes venues from the candidate universe entirely, and nothing in a receipt says "
            "which contract is a venue and which is a smart-account portfolio. Classify each one "
            "deliberately.".format(CODE_AT_BLOCK, ", ".join(untyped))
        )
    return AttributionContext(
        eoas=frozenset(eoas), infrastructure=frozenset(infrastructure)
    ), tuple(rows)


def read_inputs(client):
    """Everything ``run_wallet_window`` consumes, read from the chain through the real seams."""
    window = window_from_blocks(client, WINDOW_INDEX, WINDOW_START_BLOCK, WINDOW_END_BLOCK)
    horizon = block_header(client, HORIZON_BLOCK)
    population, refused = read_population(client)
    context, context_rows = build_context(client, population)
    # The context is per transaction on the entry type and the same for all of them here: none of
    # these receipts carries Safe or ERC-4337 evidence, and the address typing is run-level. An
    # UndecodableTransaction has no context field and takes none — attribution never sees it.
    transactions = tuple(
        replace(item, context=context) if isinstance(item, ObservedTransaction) else item
        for item in population
    )
    price, raw_answer, weth_decimals = read_weth_price(client, WINDOW_START_BLOCK)
    config = WindowConfig(
        horizon_block=horizon.number,
        horizon_ts=horizon.timestamp,
        token_starts={XUSDP: confirm_token_start(client)},
    )
    return (window, transactions, refused, context_rows, {WETH: price}, config,
            (raw_answer, weth_decimals))


def run(client):
    """The whole bullet: confirm the caller's inputs, then run the composition root."""
    edges = confirm_window_edges(client)
    settlements = confirm_native_settlements(client)
    (window, transactions, refused, context_rows, prices, config,
     price_evidence) = read_inputs(client)
    result = run_wallet_window(transactions, {}, prices, window, config)
    return {
        "edges": edges,
        "settlements": settlements,
        "window": window,
        "transactions": transactions,
        "refused": refused,
        "context_rows": context_rows,
        "prices": prices,
        "config": config,
        "price_evidence": price_evidence,
        "result": result,
    }


# -- printing -------------------------------------------------------------------


def report(bullet, client, out=sys.stdout):
    """Print every number this run publishes, and the evidence under the caller's inputs."""
    window, config, result = bullet["window"], bullet["config"], bullet["result"]
    before, start, end, after = bullet["edges"]
    answer, weth_decimals = bullet["price_evidence"]

    write = lambda line="": out.write(line + "\n")  # noqa: E731

    write("=" * 78)
    write("TICKET 19 TRACER BULLET  —  one wallet, one window, the real composition root")
    write("=" * 78)
    write("wallet            {}".format(WALLET))
    write("window index {}    February 2023 — NOT §6.3's window 1, which is Jan-Jun 2023. This is"
          .format(window.index))
    write("                  a window *inside* that period, chosen so the population is small")
    write("                  enough to check by hand.")
    write("window {:<10} blocks {}..{}  ts {}..{}".format(
        window.index, window.start_block, window.end_block, window.start_ts, window.end_ts))
    write("  edge evidence   block {} ts {} < 2023-02-01T00:00:00Z <= block {} ts {}".format(
        before.number, before.timestamp, start.number, start.timestamp))
    write("                  block {} ts {} < 2023-03-01T00:00:00Z <= block {} ts {}".format(
        end.number, end.timestamp, after.number, after.timestamp))
    write("marking horizon   block {} ts {}  (window end + {} s)".format(
        config.horizon_block, config.horizon_ts, config.horizon_ts - window.end_ts))
    write("price book        WETH = {} USD per raw unit".format(bullet["prices"][WETH]))
    write("  evidence        Chainlink ETH/USD answer {} ({} dp) at block {}; WETH decimals {} "
          "read from the chain".format(answer, CHAINLINK_DECIMALS, WINDOW_START_BLOCK,
                                       weth_decimals))
    start_obj = config.token_start(XUSDP)
    write("§4.7 XUSDP start  block {} ts {}  (Mint and Swap both in that block)".format(
        start_obj.block, start_obj.timestamp))
    write("")

    write("-- §6.2 address typing -------------------------------------------------------")
    write("(code or no code is measured at block {}; which contract is a venue is stated)".format(
        CODE_AT_BLOCK))
    for address, has_code, role in bullet["context_rows"]:
        write("  {}  {}".format(address, role))
    write("")

    write("-- native settlements, confirmed against archive balances ---------------------")
    write("(a WETH wrap or unwrap says the amount and the path; the last address is the one thing")
    write(" a trace would add, and each row closes it to the wei without one)")
    for tx_hash, block, bal_before, bal_after, paid_gas, expected, measured in \
            bullet["settlements"]:
        write("  {}".format(tx_hash))
        write("    balance(block {}) - balance(block {}) = {}".format(
            block, block - 1, bal_after - bal_before))
        write("    + gas paid by the wallet              = {}".format(paid_gas))
        write("    = native ETH received                 = {}   (legs sum {})".format(
            measured, "unreadable — ingestion refused this receipt"
            if expected is None else expected))
    write("")

    decoded = [i for i in bullet["transactions"] if isinstance(i, ObservedTransaction)]
    write("-- population: {} transaction(s), {} decoded, {} undecodable ------------------".format(
        len(TRANSACTIONS), len(decoded), len(bullet["refused"])))
    for item in bullet["refused"]:
        write("  UNDECODABLE  {}".format(item.tx_hash))
        write("    block {}  ts {}  sender {}".format(
            item.block_number, item.timestamp, item.tx_sender))
        write("    {} at log {} on {}".format(item.refusal, item.log_index, item.contract))
        write("    topic {}".format(item.topic))
        write("    Counted in the census below and named in the quarantine queue at stage")
        write("    'ingestion'. It is excluded from scoring: a transaction with an unreadable leg")
        write("    has an unknown net position, and netting it as a no-op would leave a closed")
        write("    position open to be marked at the horizon.")
    for item in decoded:
        write("  block {}  ts {}  {}".format(item.block_number, item.timestamp, item.tx_hash))
        write("    sender {}   {} transfer leg(s)".format(item.tx_sender, len(item.transfers)))
        for leg in item.transfers:
            write("      log {:<4} {}  {} -> {}  {}".format(
                leg.log_index, leg.token, leg.from_addr, leg.to_addr, leg.raw_amount))
    write("")

    write("-- reconciliation (every count the result carries) ----------------------------")
    for name, value in result.reconciliation():
        write("  {:<28} {}".format(name, value))
    write("")

    write("-- classification, per transaction -------------------------------------------")
    for row in result.results:
        write("  {}  {}".format(row.tx_hash, row.status.value))
        if row.status.is_trade:
            write("    sold   {} raw {}".format(row.sold_asset, row.sold_raw_amount))
            write("    bought {} raw {}".format(row.bought_asset, row.bought_raw_amount))
            write("    quote  {}  = ${}".format(row.quote_asset, row.quote_usd))
        else:
            write("    quote_usd {}".format(row.quote_usd))
            write("    reason {}".format(row.reason))
    write("")

    write("-- §8 exclusions -------------------------------------------------------------")
    if not result.excluded:
        write("  (none)")
    for record in result.excluded:
        write("  {}  method={} account={}".format(
            record.tx_hash, record.method.value, record.account_type.value))
        write("    {}".format(record.reason))
    write("")

    write("-- quarantine queue ----------------------------------------------------------")
    if not result.quarantine.records:
        write("  (empty)")
    for record in result.quarantine.records:
        write("  stage={} wallet={} asset={} volume={}".format(
            record.stage.value, record.wallet, record.asset, record.volume_usd))
        write("    txs {}".format(", ".join(record.tx_hashes)))
        write("    {}".format(record.reason))
    write("")

    write("-- attribution coverage ------------------------------------------------------")
    coverage = result.attribution
    for field in sorted(vars(coverage)):
        write("  {:<28} {}".format(field, getattr(coverage, field)))
    write("")

    write("-- USD coverage --------------------------------------------------------------")
    for field in sorted(vars(result.coverage)):
        write("  {:<28} {}".format(field, getattr(result.coverage, field)))
    write("")

    write("-- per wallet ----------------------------------------------------------------")
    for outcome in result.wallets:
        write("  {}".format(outcome.wallet))
        write("    buys {}  sells {}  buys quarantined {}  sells quarantined {}".format(
            outcome.n_buys, outcome.n_sells, outcome.n_buys_quarantined,
            outcome.n_sells_quarantined))
        if outcome.quality is None:
            write("    NO SCORE: {}".format(outcome.unscorable_reason))
        else:
            quality = outcome.quality
            write("    buy_quality_30d   {}".format(quality.value))
            write("    n_buys scored     {}".format(quality.n_buys))
            write("    realized share    {}".format(quality.realized_share))
            write("    marked share      {}".format(quality.marked_share))
            write("    dead share        {}".format(quality.dead_share))
            for bucket in sorted(quality.bucket_weights, key=lambda b: b.value):
                write("    bucket {}          weight {}  value {}".format(
                    bucket.value, quality.bucket_weights[bucket],
                    quality.bucket_values.get(bucket)))
        for account in outcome.accounts:
            write("    buy {}".format(account.buy.tx_hash))
            write("      bucket              {}".format(account.bucket.value))
            write("      cost_usd            {}".format(account.cost_usd))
            write("      realized_raw        {}".format(account.realized_raw))
            write("      realized_cost_usd   {}".format(account.realized_cost_usd))
            write("      realized_proceeds   {}".format(account.realized_proceeds_usd))
            write("      open_raw            {}".format(account.open_raw))
            write("      marked_usd          {}".format(account.marked_usd))
            write("      dead_usd            {}".format(account.dead_usd))
            write("      return_pct          {}".format(account.return_pct))
            write("      buy_horizon_ts      {}".format(account.buy_horizon_ts))
            write("      horizon_lag_seconds {}".format(account.horizon_lag_seconds))
    write("")

    replayed, live = client.replayed_count()
    write("-- provenance ----------------------------------------------------------------")
    write("  {} RPC call(s): {} replayed from the snapshot, {} live".format(
        replayed + live, replayed, live))
    write("  snapshot {}".format(os.path.relpath(RECORDINGS, REPO)))
    return result


# -- helpers --------------------------------------------------------------------


def _block_of(client, tx_hash):
    return int(require_receipt(client, tx_hash)["blockNumber"], 16)


def _native_amounts(receipt):
    """``(log_index, signed wei)`` for every WETH wrap/unwrap, signed from the wallet's side.

    A wrap takes ETH off the wallet, an unwrap puts it back, so the sign is decided by which of the
    two the leg is — read from :func:`ingest.native_legs` and the receipt's own logs rather than
    re-derived here.
    """
    logs = logs_of(receipt)
    by_index = {int(log["logIndex"], 16): log for log in logs}
    withdrawal = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"
    out = []
    for index in native_legs(logs):
        log = by_index[index]
        amount = int(log["data"], 16)
        out.append((index, amount if log["topics"][0] == withdrawal else -amount))
    return tuple(out)


def _hex_block(block):
    """A pinned height on the wire. Never a tag: ``latest`` is a different answer tomorrow."""
    return block_parameter(block)


def _chainlink_answer(client, block):
    """The ``int256 answer`` member of ``latestRoundData()`` at ``block``."""
    data = client.call(
        "eth_call",
        [{"to": CHAINLINK_ETH_USD, "data": LATEST_ROUND_DATA}, _hex_block(block)],
    )
    if not isinstance(data, str) or len(data) != 2 + 64 * 5:
        raise TracerBulletRefused(
            "Chainlink {} answered {!r} at block {}, which is not five ABI words; a price read "
            "positionally out of the wrong shape is still a number.".format(
                CHAINLINK_ETH_USD, data, block
            )
        )
    answer = int(data[2 + 64:2 + 128], 16)
    if answer <= 0 or answer >= 2 ** 255:
        raise TracerBulletRefused(
            "Chainlink {} answered {} at block {}; a non-positive ETH/USD price would mark every "
            "position in the book at zero.".format(CHAINLINK_ETH_USD, answer, block)
        )
    return answer


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="tools.tracer_bullet",
        description="Ticket 19: one real wallet, one real window, through pipeline.run_wallet_window.",
    )
    parser.add_argument(
        "--record", action="store_true",
        help="go to the network for any call the snapshot does not hold, and record it. "
             "Without this flag nothing opens a socket.",
    )
    args = parser.parse_args(argv)
    client = build_client(record=args.record)
    bullet = run(client)
    report(bullet, client)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
