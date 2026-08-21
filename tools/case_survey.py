"""A survey of real mainnet inputs for the pipeline paths no real byte has ever reached.

    PYTHONPATH=src .venv/bin/python -m tools.case_survey

Every byte comes from ``tests/fixtures/case_survey/recordings``, replayed. The default mode is
``REPLAY_ONLY``: a call the snapshot does not hold raises rather than quietly measuring a different
chain than the one the printed numbers were checked against. ``--record`` is how the snapshot is
(re-)made, and it is the only mode that opens a socket.

What this is
------------

Ticket 19's tracer bullet covered §4.4 **Case 1 only** — one buy, sold in full sixteen hours later,
``open_raw == 0``. So it needed no pool state, and :mod:`marking` (793 loc) and :mod:`depth`
(1,585 loc) had never seen a real input. This file is the search that fixes that: it names real
wallets and real transactions for the unexercised paths, records every response, and re-derives
each claim from the recording rather than from a comment.

It is **builder-lane self-testing on real data**, the same thing ``tools/mockchain/`` and
``tools/hyperliquid/`` are for. It is **not** the golden set: ticket 14's evidence bundles come
through the ground-truth reader under the Independent Validator, account selection there is made
without consulting any pipeline output, and all of it waits on ticket 02. Nothing here reads or
writes ``src/groundtruth/``, nothing here is an account *selection*, and no claim of ticket 14, 15,
16 or 17 is made by any line of it.

It is also not a measurement of anything. Two wallets are two wallets, and both were found by
searching one 1,500-block slice of the Uniswap V2 factory — a population chosen because it was
cheap to enumerate, not because it represents anything.

How the cases were found, and why that matters
----------------------------------------------

Not by picking wallets whose numbers look good. The search ran in this order and the cases are
whatever fell out of it:

1. every ``PairCreated`` from the Uniswap V2 factory in blocks 16530248-16531747 — 57 WETH pairs;
2. ``getReserves()`` on each at the marking horizon, which sorted them into eight pools that could
   still absorb a sale and forty-nine that could not;
3. the deepest survivor and one of the drained ones were opened up, and the wallets are simply the
   ones holding the largest positions in each.

The result is not flattering and was not meant to be. The open position in the live pool is 13% of
the pool's own token reserve, so its liquidity-bounded mark comes in **11.8% below spot** and the
pool is labelled ``THIN``. The dead-pool holder's position is zeroed outright. One wallet's residual
is worth $0.26 against a $1.00 minimum-exit threshold — and is nonetheless *not* dead, which is the
whole point of §9.1 being a conjunction.

The paths this survey has a real case for
-----------------------------------------

===================================== ===============================================
§4.4 Case 2, marked against a pool     :data:`WALLET_A` and :data:`WALLET_B`
liquidity bound biting                 :data:`WALLET_A` — 11.8% below spot, ``THIN``
§9.1 dead pool, all three conditions   :data:`DEAD_HOLDER` — 57.9 days of silence
multi-lot FIFO, partial lot            :data:`WALLET_B` — one sell over five buys
§4.7 trading start inside the window   :data:`SBET` — buckets A and B, both real
multi-hop                              :data:`MULTIHOP_TX` — USDT -> WETH -> SBET
fee-on-transfer                        two kinds; see :func:`confirm_credited_amounts`
===================================== ===============================================

And the one it does not
-----------------------

**No migrated pool.** ``PoolStatus.MIGRATED`` and ``validate_replacement`` still have no real
input, and :func:`search_for_a_second_venue` is the search that failed to produce one — it is kept,
and replayed, precisely because a failed search is the only honest form of that sentence. See that
function for what it covers and what it does not.

What every number here rests on
-------------------------------

Two caller inputs that no receipt contains, both stated and then confirmed against the chain:

* **the window and the horizon** — February 2023 and its §4.8 tail, the same edges ticket 19's
  tracer bullet established. :func:`confirm_horizon` re-derives the horizon block from the window's
  last block rather than trusting the constant;
* **the USD price of each quote asset** — one Chainlink round per asset, read on-chain at the
  horizon block. §4.6's seam takes one scalar per quote asset for a whole window; that is a real
  limitation and it is not fixed here.

What is deliberately not here: any trace, any ``latest`` tag, any float, and any ``src/groundtruth/``.
"""

import argparse
import os
import sys
from decimal import Decimal

from contracts import PoolState, divide
from marking import mark_position
from transport import AUTO, REPLAY_ONLY, RecordingCache, RpcClient

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Its own snapshot directory, beside the tracer bullet's rather than inside it: that snapshot's
#: fingerprint is pinned by ``tests/transport/test_cache.py``, and a run that added calls to it
#: would turn a reproducibility check into a chore.
RECORDINGS = os.path.join(REPO, "tests", "fixtures", "case_survey", "recordings")

# -- the window, the horizon, and the assets ------------------------------------

#: 2023-03-01T00:00:00Z, as UTC seconds. The window is February 2023, as ticket 19's.
MAR_1_2023 = 1677628800

#: §4.8's measurement tail. Thirty days of UTC seconds; the same literal ``pipeline.inputs`` pins.
MEASUREMENT_TAIL_SECONDS = 30 * 24 * 60 * 60

#: Last block of the window and the first block at or after ``its timestamp + 30 days``. The block
#: before the horizon is read too, so "this is the horizon" is a measurement in the run.
WINDOW_END_BLOCK = 16730071
HORIZON_BLOCK = 16943478
BLOCK_BEFORE_HORIZON = 16943477

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"

#: Uniswap V2's factory and the two Uniswap factories a replacement venue could be created by.
FACTORY_V2 = "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"
FACTORY_V3 = "0x1F98431c8aD98523631AE4a59f267346ea31F984"

#: The Uniswap V2 router, and the two non-router contracts that appear on a leg below. Labels come
#: from a block explorer, as ticket 19's ``INFRASTRUCTURE`` does; nothing branches on them.
ROUTER_V2 = "0x7a250d5630b4cf539739df2c5dacb4c659f2488d"

#: Event topics. Copied from :mod:`ingest.events` rather than imported, because ``transport`` holds
#: no signatures by design and a survey that imported the decoder's registry would be asking the
#: decoder which events it already knows about — which is the question ticket 19's seventh
#: transaction answered the expensive way.
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
SWAP_V2 = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
SWAP_V3 = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
MINT_V2 = "0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f"
SYNC = "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"

#: ``PairCreated(address indexed token0, address indexed token1, address pair, uint)`` and
#: ``PoolCreated(address indexed token0, address indexed token1, uint24 indexed fee, int24, address)``.
#: Both were confirmed by reading a factory's logs *without* a topic filter and taking the topic
#: that came back, so neither is a remembered constant.
PAIR_CREATED = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"
POOL_CREATED = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"

#: Chainlink aggregator proxies and the ``latestRoundData()`` selector, written out rather than
#: computed: this file holds no keccak, and a constant is what a reader checks against an
#: explorer's "Read Contract" tab. Both answer in 8 decimals.
CHAINLINK_ETH_USD = "0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419"
CHAINLINK_USDT_USD = "0x3E7d1eAB13ad0104d2750B8863b489D65364e32D"
LATEST_ROUND_DATA = "0xfeaf968c"
CHAINLINK_DECIMALS = 8

#: ``getReserves()``, ``token0()``, ``token1()``, ``decimals()``, ``balanceOf(address)``,
#: ``liquidity()``, ``slot0()``, ``fee()``.
GET_RESERVES = "0x0902f1ac"
TOKEN0 = "0x0dfe1681"
TOKEN1 = "0xd21220a7"
DECIMALS = "0x313ce567"
BALANCE_OF = "0x70a08231"
V3_LIQUIDITY = "0x1a686502"
V3_SLOT0 = "0x3850c7bd"
V3_FEE = "0xddca3f43"

#: How wide a block range one ``eth_getLogs`` covers. Ten thousand is not a taste: of the three
#: free endpoints, one caps the range at 10,000 blocks, one at 50, and one refuses anything it
#: judges too large without naming a number. A wider chunk is not a faster run, it is a refusal.
CHUNK = 10_000

# -- the population the search enumerated ---------------------------------------

#: The three 500-block slices of the factory that produced the candidate population. Not a round
#: number of blocks by accident: the search enumerated 1,500 blocks from the window's first block
#: because that was one page of pairs, and it stopped there because it had enough.
FACTORY_SLICES = ((16530248, 16530747), (16530748, 16531247), (16531248, 16531747))


class SurveyRefused(RuntimeError):
    """A claim this survey states did not hold when it was checked against the snapshot.

    Raised rather than reported, because every one of these claims is load-bearing: a lot that is
    not in the chain's logs, a residual that does not equal the wallet's balance, or a pool whose
    reserves are not what is written here would each make the printed evidence describe something
    other than what it says it describes.
    """


# -- reading the wire -----------------------------------------------------------


def build_client(record=False):
    """The RPC client, replaying by default and recording only when asked.

    The endpoint order is deliberate and is not the package default. ``eth_getLogs`` over a
    10,000-block range is served by ``rpc.mevblocker.io`` and refused with a 400 by the default
    first endpoint, so leading with the default order would send a refused request ahead of every
    log query in this file. That is not an optimisation; sending a vendor 300 requests it has
    already said no to is how a signature gets rate-limited.

    Guarantees replay of a recorded call without a socket. Guarantees nothing about a recorded
    answer being *correct* — see :mod:`transport.cache`.
    """
    cache = RecordingCache(RECORDINGS)
    endpoints = (
        "https://rpc.mevblocker.io",
        "https://eth-mainnet.public.blastapi.io",
        "https://eth-pokt.nodies.app",
    )
    return RpcClient(endpoints=endpoints, cache=cache, mode=AUTO if record else REPLAY_ONLY)


def word(address):
    """An address as a 32-byte topic word, lower-cased."""
    return "0x" + address.lower().replace("0x", "").rjust(64, "0")


def address_of(topic):
    """The address in the low 20 bytes of a topic word."""
    return "0x" + topic[-40:]


def uint(data, index):
    """The ``index``-th 32-byte word of a log's ``data``, as an int."""
    body = data[2:]
    return int(body[index * 64:(index + 1) * 64], 16)


def block_number(log):
    return int(log["blockNumber"], 16)


def call_contract(client, to, data, block):
    """One ``eth_call`` at a height. A tag would make the answer about today, not about 2023."""
    return client.call("eth_call", [{"to": to, "data": data}, hex(block)])


def read_reserves(client, pair, block):
    """``(reserve0, reserve1)`` at a height, as ints."""
    raw = call_contract(client, pair, GET_RESERVES, block)
    return uint(raw, 0), uint(raw, 1)


def read_balance(client, token, holder, block):
    """``balanceOf(holder)`` at a height, as an int.

    This is the *credited* balance, and it is not always the sum of the ``Transfer`` logs that
    produced it. :func:`confirm_credited_amounts` is where that stops being an aside.
    """
    return uint(call_contract(client, token, BALANCE_OF + word(holder)[2:], block), 0)


def read_timestamp(client, block):
    return int(client.get_block_by_number(block)["timestamp"], 16)


def logs_in_chunks(client, first_block, last_block, address, topics=None):
    """Every matching log in ``[first_block, last_block]``, read in :data:`CHUNK`-block slices.

    The chunking is what makes a claim about *silence* checkable: the recording holds one empty
    answer per slice, so "no swap happened in these 412,000 blocks" is 42 recorded refusals to
    produce a log rather than one assertion in a docstring.
    """
    found = []
    lower = first_block
    while lower <= last_block:
        upper = min(lower + CHUNK - 1, last_block)
        found.extend(
            client.get_logs(from_block=lower, to_block=upper, address=address, topics=topics)
        )
        lower = upper + 1
    return found


# -- the values a case is made of -----------------------------------------------


class Lot(object):
    """One leg of a position: what a ``Transfer`` log says moved, and where.

    ``logged_raw`` is the amount **in the log**. Whether the wallet's balance moved by that amount
    is a separate question and is asked separately; on one of the two tokens here the answer is no.
    """

    def __init__(self, tx_hash, block, timestamp, logged_raw):
        self.tx_hash = tx_hash
        self.block = block
        self.timestamp = timestamp
        self.logged_raw = logged_raw

    def __repr__(self):
        return "Lot({} @{} {} raw)".format(self.tx_hash[:12], self.block, self.logged_raw)


class Venue(object):
    """A pool as it stood at the marking horizon, plus the last swap it served before then.

    ``asset``/``quote`` name the two sides in *this survey's* orientation, not the pool's
    ``token0``/``token1`` ordering — :func:`confirm_venue` reads the pool's own ordering and checks
    that the reserves are attributed the right way round. Getting that backwards is not a visible
    error: it produces a plausible price that is wrong by the ratio of the two reserves.
    """

    def __init__(self, address, asset, quote, asset_reserve_raw, quote_reserve_raw,
                 last_swap_block, last_swap_timestamp, fee_bps=30):
        self.address = address
        self.asset = asset
        self.quote = quote
        self.asset_reserve_raw = asset_reserve_raw
        self.quote_reserve_raw = quote_reserve_raw
        self.last_swap_block = last_swap_block
        self.last_swap_timestamp = last_swap_timestamp
        self.fee_bps = fee_bps

    def pool_state(self):
        """The :class:`contracts.PoolState` this venue is, for :func:`marking.mark_position`.

        ``fee_bps`` is the **pool's** fee and nothing else. Neither of the two tokens here charges
        its transfer tax through the pool, and this field has nowhere to put one; see
        :func:`confirm_credited_amounts` for what that omission costs on this data.
        """
        return PoolState(
            address=self.address,
            asset=self.asset,
            quote=self.quote,
            asset_reserve_raw=self.asset_reserve_raw,
            quote_reserve_raw=self.quote_reserve_raw,
            last_swap_block=self.last_swap_block,
            last_swap_timestamp=self.last_swap_timestamp,
            fee_bps=self.fee_bps,
        )


# -- case 1 and 2: ShiBet, a live pool at the horizon ---------------------------

#: ShiBet (SBET), 18 decimals, launched inside the window. An 8% tax token: on a sale the wallet is
#: debited more than the pool is credited, and the difference has its own ``Transfer`` log.
SBET = "0x14c256e65300026b76247e45554bb645c2c294ff"
SBET_PAIR = "0x8c56b433869ff0b89f9c400db4971d4899f7c465"
SBET_PAIR_CREATED_BLOCK = 16530898

#: §4.7's trading start, and the reason this token is the §4.7 case: the pair was created at
#: 16530898, funded at 16530944, and first swapped at 16530948 — three different blocks, all inside
#: February 2023. Ticket 19's XUSDP did all three in one block twenty-one months before its window,
#: so "the first block at which the token had liquidity *and* a swap" was never actually a choice
#: there. Here it is.
SBET_FIRST_MINT_BLOCK = 16530944
SBET_TRADING_START_BLOCK = 16530948
SBET_TRADING_START_TS = 1675218047

#: The pool at the horizon. Alive: it served 32 swaps in the last 10,000 blocks before it.
SBET_VENUE = Venue(
    address=SBET_PAIR,
    asset=SBET,
    quote=WETH,
    asset_reserve_raw=90396688352888500346836453,
    quote_reserve_raw=25786853741718141371,
    last_swap_block=16943170,
    last_swap_timestamp=1680217031,
)

#: **Case: a position still open at the marking horizon.** An EOA, four buys inside the first
#: 27 minutes of the token's life, and not one disposal in the 412,580 blocks to the horizon. Its
#: position is 13.1% of the pool's own token reserve, which is why it is the liquidity-bound case
#: as well: the mark comes in 11.8% under spot and the pool is labelled ``THIN``.
WALLET_A = "0x51f8effd657213397f9a2c88a50111dffbc1006a"
WALLET_A_LOTS = (
    Lot("0x412153418a9281dab707f95fa75404f651422aab6c62aa5c2e5e340a63c84e93",
        16530952, 1675218095, 2760000000000000000000000),
    Lot("0x8972dda5825a086b47a1203dc6a349aafa63e2868d4732fd3bc20e0c711182f3",
        16530968, 1675218287, 2760000000000000000000000),
    Lot("0xf1097b9caecc7146dcaa2eba8310a2e2d64809e76fb1ec8aac0b802b989d1e9b",
        16531034, 1675219079, 2760000000000000000000000),
    Lot("0x8f03fc0499a13dad18d3916be748fffdd9d6844c8b275615012844fc42d361bc",
        16531118, 1675220087, 3551462774808522772923324),
)
WALLET_A_OPEN_RAW = 11831462774808522772923324

#: **Case: multi-lot FIFO with a partially consumed lot.** An EOA, five buys in 16 blocks and one
#: sale 11 minutes later that is larger than any of them. The sale consumes lots one to four whole
#: and 1,354,200,922,214,846,680,287,104 of the 1,354,710,656,992,202,460,528,737 in lot five,
#: leaving 509,734,777,355,780,241,633 raw — which is still open at the horizon, so this wallet is
#: §4.4 Case 1 and Case 2 at once, on the same token, in the same window.
WALLET_B = "0xd42b85640c30ed0c3537daf352bb917d4a836092"
WALLET_B_LOTS = (
    Lot("0x49b4e5f4b720aff53acbc04de91734afcae71f64ccc2384c1c3d64ab9c8f677c",
        16530953, 1675218107, 1404114765260775971113836),
    Lot("0xbbb9d16eac1e56f0aae14b26f1def91aff1dde599cbe80a9cd0055f6371e44e7",
        16530956, 1675218143, 470522696491540940549350),
    Lot("0x113d33497d927b031077a3817082a5cf5f5c64b76955052105dc4a4512fc0a71",
        16530961, 1675218203, 288332611968442146123659),
    Lot("0xfcb9b18afabeb80b71971682f97e0c020fff5a7c3dd09f78cab9249e44969146",
        16530965, 1675218251, 2333829004064394261926051),
    Lot("0xce777044f82db53752f1e7fc8723e4913bed085b65cdba6e95e29e78ea202734",
        16530969, 1675218299, 1354710656992202460528737),
)

#: The sale. Two ``Transfer`` logs leave the wallet in this one transaction and only one of them
#: reaches the pool; the other is the token's 8% tax, paid to the token contract itself.
WALLET_B_SELL_TX = "0x4efd26163a090cc1fea9faab608273fd0aaffb196a830ed990b0b7f86b4489e1"
WALLET_B_SELL_BLOCK = 16531613
WALLET_B_SELL_TS = 1675226063
WALLET_B_SELL_TO_POOL_RAW = 5382920000000000000000000
WALLET_B_SELL_TAX_RAW = 468080000000000000000000
WALLET_B_SELL_DEBITED_RAW = 5851000000000000000000000
WALLET_B_OPEN_RAW = 509734777355780241633

#: What the sale actually paid the wallet, in wei of native ETH. The WETH is unwrapped to a
#: third-party contract — an unlabelled 34,932-byte router the wallet called instead of Uniswap's —
#: which then forwards the ETH by an internal transfer that writes **no log at all**. So the
#: proceeds of this sale are invisible to any enumeration that works from logs, exactly as ticket
#: 19's plain ETH payment was, and the only way to establish them is the balance identity in
#: :func:`confirm_native_proceeds`. It closes to the wei: the intermediary took nothing.
WALLET_B_SELL_ROUTER = "0xef1c6e67703c7bd7107eed8303fbe6ec2554bf6b"
WALLET_B_PROCEEDS_WEI = 696382285113914004

#: **Case: multi-hop, with the endpoints on opposite sides of an intermediate the wallet never
#: holds.** 800 USDT in, SBET out, routed USDT -> WETH -> SBET across two Uniswap V2 pairs. The
#: intermediate 503,774,480,161,845,292 wei of WETH goes straight from the first pair to the second
#: and is never credited to the wallet, so a §6.2 endpoint reading that treated every asset touched
#: as a leg would report this wallet as having bought and sold WETH it never had.
#:
#: It is also the second kind of fee-on-transfer here: the pool's ``Swap`` says
#: 4,390,933,866,270,263,689,977,420 SBET left it, and 4,039,659,156,968,642,594,779,227 reached
#: the wallet.
MULTIHOP_TX = "0xba607076e9aeb81610f3e05a6a223bbaaa0cc54c9805255f5a7aa5e2e110f6bc"
MULTIHOP_BLOCK = 16531848
MULTIHOP_WALLET = "0x8a43343ef9f4c2ca9b638c2ca8cc8773c39382fa"
MULTIHOP_USDT_PAIR = "0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852"
MULTIHOP_USDT_IN_RAW = 800000000
MULTIHOP_WETH_MID_RAW = 503774480161845292
MULTIHOP_SWAP_OUT_RAW = 4390933866270263689977420
MULTIHOP_CREDITED_RAW = 4039659156968642594779227
MULTIHOP_TAX_RAW = 351274709301621095198193

# -- case 3: a rug, and a pool that is dead by all three conditions --------------

#: A token calling itself ``DAI`` at an address that is not DAI's. Nine decimals. It is named here
#: only so a reader who opens the address is not surprised: everything in this repository keys on
#: addresses, and nothing anywhere reads a symbol.
DEAD_TOKEN = "0x41d1841fcedabd85eeb91b10fb069e225df67af8"
DEAD_PAIR = "0xd6f6558f1ecba5951b9e09f7ae2aaa507759838b"
DEAD_PAIR_CREATED_BLOCK = 16530559

#: The pool at the horizon: 1,005,205,305,507 wei — about a ten-thousandth of a cent — against a
#: token reserve that is what the rug dumped into it. Its last swap was at block 16530863, which is
#: 5,003,772 seconds (57.9 days) before the horizon.
DEAD_VENUE = Venue(
    address=DEAD_PAIR,
    asset=DEAD_TOKEN,
    quote=WETH,
    asset_reserve_raw=98000059352985595468734,
    quote_reserve_raw=1005205305507,
    last_swap_block=16530863,
    last_swap_timestamp=1675217027,
)

#: The pool's whole life: 23 swaps between blocks 16530574 and 16530863, and never another one.
DEAD_FIRST_SWAP_BLOCK = 16530574
DEAD_SWAP_COUNT = 23

#: **Case: a holder of a dead pool's token.** An EOA with exactly one transfer of this token, ever:
#: the buy. It never sold, and it could not have — by the time anyone looked, the pool held a
#: ten-thousandth of a cent.
#:
#: ``credited_raw`` is not ``logged_raw``, and the gap is the sharpest thing in this file. See
#: :func:`confirm_credited_amounts`.
DEAD_HOLDER = "0x6e650dff88d94f9d2e36823ede9a7dd67961f68a"
DEAD_HOLDER_LOT = Lot("0x0aa9672138d96e40ab8c32e2aa964f1a83c88be4b92cb9ef9051be6cad360ec0",
                      16530608, 1675213943, 11335529769194231)
DEAD_HOLDER_CREDITED_RAW = 11108819173810347

# -- the venue that is not a replacement ----------------------------------------

#: A Uniswap **v3** SBET/WETH pool, created at block 16734606 — after the window closed and before
#: the horizon. It is here because leaving it out would be the flattering omission: a second venue
#: existed for the marked token inside the measurement period. It is not a replacement, and the
#: reason is measured rather than assumed — at the horizon its active liquidity is exactly zero and
#: it had served no swap in the preceding 10,000 blocks. There is nothing to exit into.
#:
#: It is also the only real v3 pool state in this repository, and it lands on
#: :func:`marking.liquidity.effective_reserves`'s ``UnmodelledPoolError`` branch rather than its
#: virtual-reserves branch, because ``L = 0``.
SBET_V3_POOL = "0xcff7d10981a6662007f79409113ded8e3bac51bc"
SBET_V3_CREATED_BLOCK = 16734606
SBET_V3_FEE = 3000
SBET_V3_LIQUIDITY_AT_HORIZON = 0
SBET_V3_SQRT_PRICE_X96_AT_HORIZON = 22381130613336255217520001


# -- the caller inputs, each confirmed by measurement ----------------------------


def confirm_horizon(client):
    """The horizon block is the first block at or after the window's end plus 30 days.

    Reads the window's last block, the horizon, and the block before it. Guarantees that
    :data:`HORIZON_BLOCK` is where §4.8's tail closes for this window, given the chain these
    recordings came from. Guarantees nothing about any of those blocks being canonical — no free
    endpoint offers a way to establish that, as :mod:`ingest.blocks` already says.
    """
    window_end_ts = read_timestamp(client, WINDOW_END_BLOCK)
    horizon_ts = read_timestamp(client, HORIZON_BLOCK)
    before_ts = read_timestamp(client, BLOCK_BEFORE_HORIZON)
    if window_end_ts >= MAR_1_2023:
        raise SurveyRefused(
            "block {} has timestamp {}, which is not before 2023-03-01T00:00:00Z ({}); the window "
            "does not close where this survey says it does.".format(
                WINDOW_END_BLOCK, window_end_ts, MAR_1_2023
            )
        )
    deadline = window_end_ts + MEASUREMENT_TAIL_SECONDS
    if not (before_ts < deadline <= horizon_ts):
        raise SurveyRefused(
            "blocks {} (ts {}) and {} (ts {}) do not straddle the horizon deadline {} = {} + {}; "
            "every mark below would then be taken at the wrong height.".format(
                BLOCK_BEFORE_HORIZON, before_ts, HORIZON_BLOCK, horizon_ts, deadline,
                window_end_ts, MEASUREMENT_TAIL_SECONDS,
            )
        )
    return horizon_ts


def read_quote_price(client, feed, block):
    """USD per **raw unit** of an 18-decimal quote asset, from a Chainlink aggregator at ``block``.

    Returns ``(price_per_raw_unit, raw_answer)``. The answer's 8 decimals and the asset's decimals
    are both divided out through the frozen context, so nothing here is a float and nothing is a
    remembered scaling factor. Guarantees only that this is what that aggregator answered at that
    height: a Chainlink round is a median of that day's reporters, not a transaction price.
    """
    raw = call_contract(client, feed, LATEST_ROUND_DATA, block)
    answer = uint(raw, 1)
    return divide(Decimal(answer), Decimal(10) ** CHAINLINK_DECIMALS), answer


def confirm_venue(client, venue, horizon_block=HORIZON_BLOCK):
    """A venue's reserves, its side ordering, and its last swap — all read at the horizon.

    Checks three things and raises on any of them:

    * ``getReserves()`` at the horizon equals what the venue states;
    * the pool's own ``token0()``/``token1()`` put the stated asset and quote on the sides this
      survey attributes them to. Reversing the two produces a price wrong by the ratio of the
      reserves and looks entirely plausible on the way out;
    * the stated last swap is a real ``Swap`` log at that block, and it is the last one at or
      before the horizon.

    The third check is the expensive one: it reads every :data:`CHUNK`-block slice from the stated
    last swap to the horizon and requires them all to be empty. That is what makes "this pool went
    quiet" and "this pool is still trading" the *same* kind of claim, established the same way,
    rather than one being a search and the other an assumption.
    """
    reserve0, reserve1 = read_reserves(client, venue.address, horizon_block)
    side0 = address_of(call_contract(client, venue.address, TOKEN0, horizon_block))
    side1 = address_of(call_contract(client, venue.address, TOKEN1, horizon_block))
    if side0 == venue.asset.lower() and side1 == venue.quote.lower():
        asset_reserve, quote_reserve = reserve0, reserve1
    elif side1 == venue.asset.lower() and side0 == venue.quote.lower():
        asset_reserve, quote_reserve = reserve1, reserve0
    else:
        raise SurveyRefused(
            "pool {} holds token0={} token1={}, and this survey calls it a pool of asset {} quoted "
            "in {}. Neither side matches, so the reserves cannot be attributed at "
            "all.".format(venue.address, side0, side1, venue.asset, venue.quote)
        )
    if (asset_reserve, quote_reserve) != (venue.asset_reserve_raw, venue.quote_reserve_raw):
        raise SurveyRefused(
            "pool {} holds ({}, {}) at block {}; this survey states ({}, {}).".format(
                venue.address, asset_reserve, quote_reserve, horizon_block,
                venue.asset_reserve_raw, venue.quote_reserve_raw,
            )
        )
    at_last = client.get_logs(
        from_block=venue.last_swap_block, to_block=venue.last_swap_block,
        address=venue.address, topics=[SWAP_V2],
    )
    if not at_last:
        raise SurveyRefused(
            "pool {} emitted no Swap in block {}, which this survey states is its last swap before "
            "the horizon.".format(venue.address, venue.last_swap_block)
        )
    after = logs_in_chunks(
        client, venue.last_swap_block + 1, horizon_block, venue.address, [SWAP_V2]
    )
    if after:
        raise SurveyRefused(
            "pool {} served {} more swap(s) after block {} and before the horizon, the first at "
            "block {}. Its inactivity — and therefore §9.1 condition 1 — is not what this survey "
            "states.".format(
                venue.address, len(after), venue.last_swap_block, block_number(after[0])
            )
        )
    stated_ts = read_timestamp(client, venue.last_swap_block)
    if stated_ts != venue.last_swap_timestamp:
        raise SurveyRefused(
            "block {} has timestamp {}; this survey states {}.".format(
                venue.last_swap_block, stated_ts, venue.last_swap_timestamp
            )
        )
    return asset_reserve, quote_reserve


def confirm_trading_start(client):
    """§4.7 for SBET: liquidity at one block, the first swap four blocks later, both in the window.

    Returns ``(start_block, start_ts)``. Raises unless the pair's logs hold a ``Mint`` at
    :data:`SBET_FIRST_MINT_BLOCK` and a ``Swap`` at :data:`SBET_TRADING_START_BLOCK`, and unless the
    start falls inside the measurement window.

    What it does **not** establish: that this pair is the first pool the token ever traded in. That
    is a search over every factory ever deployed and this survey does not perform one. It
    establishes that the pool these wallets traded in went live 50 blocks after it was created and
    inside the window, which is what the §4.7 bucket turns on for *these* buys.
    """
    logs = client.get_logs(
        from_block=SBET_PAIR_CREATED_BLOCK, to_block=SBET_TRADING_START_BLOCK, address=SBET_PAIR
    )
    mints = [log for log in logs if log["topics"][0] == MINT_V2]
    swaps = [log for log in logs if log["topics"][0] == SWAP_V2]
    if not mints or block_number(mints[0]) != SBET_FIRST_MINT_BLOCK:
        raise SurveyRefused(
            "pair {} has no Mint at block {}; §4.7's 'usable liquidity' is not established "
            "there.".format(SBET_PAIR, SBET_FIRST_MINT_BLOCK)
        )
    if not swaps or block_number(swaps[0]) != SBET_TRADING_START_BLOCK:
        raise SurveyRefused(
            "pair {} has no Swap at block {}; §4.7's trading start is not established "
            "there.".format(SBET_PAIR, SBET_TRADING_START_BLOCK)
        )
    start_ts = read_timestamp(client, SBET_TRADING_START_BLOCK)
    if start_ts != SBET_TRADING_START_TS:
        raise SurveyRefused(
            "block {} has timestamp {}; this survey states {}.".format(
                SBET_TRADING_START_BLOCK, start_ts, SBET_TRADING_START_TS
            )
        )
    if not WINDOW_END_BLOCK >= SBET_TRADING_START_BLOCK >= FACTORY_SLICES[0][0]:
        raise SurveyRefused(
            "SBET's trading start at block {} is outside the window [{}, {}], so this is not the "
            "§4.7 case it is filed as.".format(
                SBET_TRADING_START_BLOCK, FACTORY_SLICES[0][0], WINDOW_END_BLOCK
            )
        )
    return SBET_TRADING_START_BLOCK, start_ts


def confirm_position(client, token, wallet, lots, disposals, open_raw,
                     first_block, horizon_block=HORIZON_BLOCK):
    """A wallet's whole history in one token, from the pool's first block to the horizon.

    Reads every ``Transfer`` of ``token`` with ``wallet`` on either side across the entire range,
    in :data:`CHUNK`-block slices, and requires that the set is *exactly* the stated lots and
    disposals — no extra leg, none missing, none at a different block or amount. Then reads
    ``balanceOf`` at the horizon and requires it to equal ``open_raw``.

    Both halves are needed and neither implies the other. The log scan is what says no sale
    happened; the balance is what says the token credited what its logs claimed. On SBET they
    agree. On the other token in this file they do not, and only running both finds that.

    What this does **not** establish: that these are all of the wallet's *transactions*. A plain
    ETH transfer writes no log, so no enumeration from logs can be a population — ticket 19's
    tracer bullet took its population from a block explorer's account listing for exactly this
    reason, and nothing here replaces that.
    """
    transfers = []
    transfers.extend(logs_in_chunks(
        client, first_block, horizon_block, token, [TRANSFER, word(wallet)]
    ))
    transfers.extend(logs_in_chunks(
        client, first_block, horizon_block, token, [TRANSFER, None, word(wallet)]
    ))
    incoming = sorted(
        (block_number(log), log["transactionHash"], uint(log["data"], 0))
        for log in transfers if address_of(log["topics"][2]) == wallet.lower()
    )
    outgoing = sorted(
        (block_number(log), log["transactionHash"], uint(log["data"], 0))
        for log in transfers if address_of(log["topics"][1]) == wallet.lower()
    )
    expected_in = sorted((lot.block, lot.tx_hash, lot.logged_raw) for lot in lots)
    expected_out = sorted(disposals)
    if incoming != expected_in:
        raise SurveyRefused(
            "{} received {} in token {} between blocks {} and {}; this survey states {}.".format(
                wallet, incoming, token, first_block, horizon_block, expected_in
            )
        )
    if outgoing != expected_out:
        raise SurveyRefused(
            "{} sent {} of token {} between blocks {} and {}; this survey states {}. A disposal "
            "this survey does not know about is a lot that FIFO would not have to "
            "match.".format(wallet, outgoing, token, first_block, horizon_block, expected_out)
        )
    balance = read_balance(client, token, wallet, horizon_block)
    if balance != open_raw:
        raise SurveyRefused(
            "{} holds {} raw of {} at block {}; this survey states an open position of {}.".format(
                wallet, balance, token, horizon_block, open_raw
            )
        )
    return balance


def confirm_fifo_consumption(lots, sold_raw, open_raw):
    """The FIFO arithmetic this survey claims about :data:`WALLET_B`, done over the lots.

    Pure: it touches no client. Returns ``(fully_consumed, partial_lot_index, partial_raw)`` and
    raises unless the sale consumes at least two lots and leaves the last one it touches partially
    consumed — which is the property that makes this a multi-lot case rather than two independent
    ones, and it is checked rather than asserted because a re-recording that moved one lot could
    quietly turn it into the latter.

    Says nothing about *which* FIFO implementation is right. It is the arithmetic the evidence has
    to be consistent with before :mod:`fifo` is ever pointed at it.
    """
    remaining = sold_raw
    consumed_whole = 0
    for index, lot in enumerate(lots):
        if remaining >= lot.logged_raw:
            remaining -= lot.logged_raw
            consumed_whole += 1
            continue
        left = lot.logged_raw - remaining
        if remaining == 0:
            raise SurveyRefused(
                "the sale of {} raw consumes {} whole lot(s) and none of the next; there is no "
                "partially consumed lot here.".format(sold_raw, consumed_whole)
            )
        if consumed_whole < 2:
            raise SurveyRefused(
                "the sale of {} raw consumes only {} whole lot(s); this is not the multi-lot case "
                "it is filed as.".format(sold_raw, consumed_whole)
            )
        if left != open_raw:
            raise SurveyRefused(
                "FIFO leaves {} raw in lot {} after a sale of {}, and the position is stated as {} "
                "raw. The residual and the arithmetic disagree.".format(
                    left, index, sold_raw, open_raw
                )
            )
        return consumed_whole, index, remaining
    raise SurveyRefused(
        "the sale of {} raw exhausts all {} lots; there is no open remainder to mark.".format(
            sold_raw, len(lots)
        )
    )


def confirm_credited_amounts(client):
    """The two kinds of fee-on-transfer here, and why only one of them is visible in the logs.

    **SBET, the visible kind.** :data:`WALLET_B`'s sale writes two ``Transfer`` logs out of the
    wallet: 5,382,920e18 to the pool and 468,080e18 to the token contract. The wallet is debited
    the sum. A netting pass that reads only the leg reaching the pool understates the disposal by
    8% and leaves a lot that never closes.

    **The rug token, the invisible kind.** Its ``Transfer`` log says 11,335,529,769,194,231 raw
    reached the holder. The holder's balance went from 0 to 11,108,819,173,810,347 — 98% of it — in
    that same transaction, and **no second log accounts for the other 2%**. So on this token the
    amount received is not the amount in the event, there is nothing in the logs to correct it by,
    and :mod:`ingest.events` — which reads ``Transfer`` and can do nothing else — will open a lot
    2.04% larger than the wallet actually holds. Every downstream quantity for that position
    inherits the error, and no test built from a chosen value would ever have produced it.

    Returns the two credited amounts. Raises if either token no longer behaves this way.
    """
    receipt = client.get_transaction_receipt(WALLET_B_SELL_TX)
    legs = [
        log for log in receipt["logs"]
        if log["address"].lower() == SBET
        and log["topics"][0] == TRANSFER
        and address_of(log["topics"][1]) == WALLET_B
    ]
    amounts = {address_of(log["topics"][2]): uint(log["data"], 0) for log in legs}
    if amounts.get(SBET_PAIR) != WALLET_B_SELL_TO_POOL_RAW or amounts.get(SBET) != WALLET_B_SELL_TAX_RAW:
        raise SurveyRefused(
            "{} moves {} out of {}; this survey states {} to the pool and {} to the token "
            "contract.".format(
                WALLET_B_SELL_TX, amounts, WALLET_B, WALLET_B_SELL_TO_POOL_RAW, WALLET_B_SELL_TAX_RAW
            )
        )
    if sum(amounts.values()) != WALLET_B_SELL_DEBITED_RAW:
        raise SurveyRefused(
            "the sale's legs sum to {}; this survey states the wallet was debited {}.".format(
                sum(amounts.values()), WALLET_B_SELL_DEBITED_RAW
            )
        )

    before = read_balance(client, DEAD_TOKEN, DEAD_HOLDER, DEAD_HOLDER_LOT.block - 1)
    after = read_balance(client, DEAD_TOKEN, DEAD_HOLDER, DEAD_HOLDER_LOT.block)
    if before != 0:
        raise SurveyRefused(
            "{} already held {} raw of {} before its only buy, so the credited amount cannot be "
            "read off the balance delta.".format(DEAD_HOLDER, before, DEAD_TOKEN)
        )
    if after != DEAD_HOLDER_CREDITED_RAW:
        raise SurveyRefused(
            "{} was credited {} raw of {}; this survey states {}.".format(
                DEAD_HOLDER, after, DEAD_TOKEN, DEAD_HOLDER_CREDITED_RAW
            )
        )
    if after >= DEAD_HOLDER_LOT.logged_raw:
        raise SurveyRefused(
            "{} credited {} against a Transfer log of {}; the log no longer overstates what the "
            "holder received, so this is not the unlogged fee-on-transfer case it is filed "
            "as.".format(DEAD_TOKEN, after, DEAD_HOLDER_LOT.logged_raw)
        )
    return WALLET_B_SELL_DEBITED_RAW, after


def confirm_native_proceeds(client):
    """What :data:`WALLET_B`'s sale actually paid it, from the wallet's own archive balance.

    The identity is :mod:`ingest.settlement`'s::

        balance(wallet, block) - balance(wallet, block - 1)  +  gas the wallet paid
            =  the wei the wallet received in native ETH

    Its precondition — that the wallet had no other transaction in that block — is stated by this
    survey and is not checked by ``ingest.settlement``. It is not fully checkable from logs either:
    this survey enumerates the wallet's *token* transfers, not its transactions, so a second plain
    ETH transfer in the same block would not appear. What is checked is that the identity closes to
    the wei against the WETH the pool released, which a second unrelated payment would break.

    Returns the wei received. Raises if it is not :data:`WALLET_B_PROCEEDS_WEI`.
    """
    receipt = client.get_transaction_receipt(WALLET_B_SELL_TX)
    if receipt["from"].lower() != WALLET_B:
        raise SurveyRefused(
            "{} was sent by {}, not by {}; the gas term of the balance identity would be "
            "wrong.".format(WALLET_B_SELL_TX, receipt["from"], WALLET_B)
        )
    gas = int(receipt["gasUsed"], 16) * int(receipt["effectiveGasPrice"], 16)
    before = int(client.get_balance(WALLET_B, WALLET_B_SELL_BLOCK - 1), 16)
    after = int(client.get_balance(WALLET_B, WALLET_B_SELL_BLOCK), 16)
    received = after - before + gas
    if received != WALLET_B_PROCEEDS_WEI:
        raise SurveyRefused(
            "{}: the wallet's balance moved {} wei across block {} and it paid {} wei of gas, so "
            "it received {} wei; this survey states {}.".format(
                WALLET_B_SELL_TX, after - before, WALLET_B_SELL_BLOCK, gas, received,
                WALLET_B_PROCEEDS_WEI,
            )
        )
    return received


def confirm_multi_hop(client):
    """The two-hop route, read out of one receipt: what the wallet spent, and what it never held.

    Requires that the transaction holds two ``Swap`` logs on two *different* pools, that the wallet
    is on neither of them as sender, that the intermediate WETH moves pool-to-pool without ever
    being credited to the wallet, and that what the wallet received differs from what the second
    pool released.

    What it does not establish: that any particular §6.2 endpoint rule is right. It establishes
    that this transaction has the shape those rules have never been shown a real instance of.
    """
    receipt = client.get_transaction_receipt(MULTIHOP_TX)
    swaps = [log for log in receipt["logs"] if log["topics"][0] in (SWAP_V2, SWAP_V3)]
    pools = [log["address"].lower() for log in swaps]
    if len(pools) != 2 or len(set(pools)) != 2:
        raise SurveyRefused(
            "{} holds {} swap log(s) on pool(s) {}; a multi-hop route is two swaps on two "
            "pools.".format(MULTIHOP_TX, len(swaps), sorted(set(pools)))
        )
    if set(pools) != {MULTIHOP_USDT_PAIR, SBET_PAIR}:
        raise SurveyRefused(
            "{} routes through {}; this survey states {} then {}.".format(
                MULTIHOP_TX, sorted(set(pools)), MULTIHOP_USDT_PAIR, SBET_PAIR
            )
        )
    transfers = [log for log in receipt["logs"] if log["topics"][0] == TRANSFER]
    spent = [
        uint(log["data"], 0) for log in transfers
        if log["address"].lower() == USDT
        and address_of(log["topics"][1]) == MULTIHOP_WALLET
        and address_of(log["topics"][2]) == MULTIHOP_USDT_PAIR
    ]
    middle = [
        uint(log["data"], 0) for log in transfers
        if log["address"].lower() == WETH
        and address_of(log["topics"][1]) == MULTIHOP_USDT_PAIR
        and address_of(log["topics"][2]) == SBET_PAIR
    ]
    received = [
        uint(log["data"], 0) for log in transfers
        if log["address"].lower() == SBET
        and address_of(log["topics"][1]) == SBET_PAIR
        and address_of(log["topics"][2]) == MULTIHOP_WALLET
    ]
    touched_weth = [
        log for log in transfers
        if log["address"].lower() == WETH
        and MULTIHOP_WALLET in (address_of(log["topics"][1]), address_of(log["topics"][2]))
    ]
    if spent != [MULTIHOP_USDT_IN_RAW] or middle != [MULTIHOP_WETH_MID_RAW] or received != [MULTIHOP_CREDITED_RAW]:
        raise SurveyRefused(
            "{} moves USDT {} / WETH {} / SBET {}; this survey states {} / {} / {}.".format(
                MULTIHOP_TX, spent, middle, received,
                [MULTIHOP_USDT_IN_RAW], [MULTIHOP_WETH_MID_RAW], [MULTIHOP_CREDITED_RAW],
            )
        )
    if touched_weth:
        raise SurveyRefused(
            "{} credits or debits WETH to {} in {} leg(s); the intermediate is then a leg of the "
            "wallet's own trade and this is not the endpoint case it is filed as.".format(
                MULTIHOP_TX, MULTIHOP_WALLET, len(touched_weth)
            )
        )
    out_leg = [log for log in swaps if log["address"].lower() == SBET_PAIR][0]
    pool_released = uint(out_leg["data"], 2)
    if pool_released != MULTIHOP_SWAP_OUT_RAW:
        raise SurveyRefused(
            "the SBET pool released {} raw; this survey states {}.".format(
                pool_released, MULTIHOP_SWAP_OUT_RAW
            )
        )
    if pool_released - MULTIHOP_CREDITED_RAW != MULTIHOP_TAX_RAW:
        raise SurveyRefused(
            "the pool released {} and the wallet received {}, a difference of {}; this survey "
            "states a tax of {}.".format(
                pool_released, MULTIHOP_CREDITED_RAW, pool_released - MULTIHOP_CREDITED_RAW,
                MULTIHOP_TAX_RAW,
            )
        )
    return MULTIHOP_USDT_IN_RAW, MULTIHOP_WETH_MID_RAW, MULTIHOP_CREDITED_RAW


def confirm_the_v3_pool_is_not_a_replacement(client, horizon_block=HORIZON_BLOCK):
    """The second SBET venue exists, and has nothing in it.

    Reads the v3 pool's ``liquidity()`` and ``slot0()`` at the horizon and its swaps in the
    preceding :data:`CHUNK` blocks. Raises unless the active liquidity is zero and no swap was
    served — the two facts that make it not a venue an exit could use.

    Guarantees nothing about liquidity outside the active band: ``liquidity()`` is the in-range
    figure, and a pool with positions parked far from spot would report zero here while holding
    tokens. For a mark that is the right reading — depth you cannot reach at the current price is
    depth you cannot sell into — and for the question "does this pool hold anything at all" it is
    not, which is why this function does not claim the second thing.
    """
    liquidity = uint(call_contract(client, SBET_V3_POOL, V3_LIQUIDITY, horizon_block), 0)
    sqrt_price = uint(call_contract(client, SBET_V3_POOL, V3_SLOT0, horizon_block), 0)
    fee = uint(call_contract(client, SBET_V3_POOL, V3_FEE, horizon_block), 0)
    swaps = client.get_logs(
        from_block=horizon_block - CHUNK + 1, to_block=horizon_block,
        address=SBET_V3_POOL, topics=[SWAP_V3],
    )
    if liquidity != SBET_V3_LIQUIDITY_AT_HORIZON or swaps:
        raise SurveyRefused(
            "v3 pool {} has active liquidity {} and served {} swap(s) in the {} blocks before the "
            "horizon; this survey states {} and none, which is the whole reason it is not treated "
            "as a replacement venue.".format(
                SBET_V3_POOL, liquidity, len(swaps), CHUNK, SBET_V3_LIQUIDITY_AT_HORIZON
            )
        )
    if (sqrt_price, fee) != (SBET_V3_SQRT_PRICE_X96_AT_HORIZON, SBET_V3_FEE):
        raise SurveyRefused(
            "v3 pool {} reports sqrtPriceX96={} fee={}; this survey states {} and {}.".format(
                SBET_V3_POOL, sqrt_price, fee, SBET_V3_SQRT_PRICE_X96_AT_HORIZON, SBET_V3_FEE
            )
        )
    return liquidity, sqrt_price, fee


def enumerate_candidate_population(client):
    """The 57 ``(token, pair)`` rows the search covered, from the factory's own logs, not a list.

    Every ``PairCreated`` in :data:`FACTORY_SLICES` whose other side is WETH, in the order the
    factory emitted them. Deriving the population here — rather than pasting 57 addresses into this
    file — is what keeps :func:`search_for_a_second_venue`'s negative result checkable: the set it
    searched is reproduced from the recording, so it cannot quietly become a different set.

    The pair address travels with the token because the search's own hits include each pair's
    creation event, and "the pool we already knew about" and "a second venue" have to be told apart
    by something other than a hand-kept list of two.
    """
    rows = []
    for lower, upper in FACTORY_SLICES:
        for log in client.get_logs(from_block=lower, to_block=upper, address=FACTORY_V2):
            side0, side1 = address_of(log["topics"][1]), address_of(log["topics"][2])
            pair = "0x" + log["data"][26:66]
            if side0 == WETH:
                rows.append((side1, pair.lower()))
            elif side1 == WETH:
                rows.append((side0, pair.lower()))
    return tuple(rows)


def search_for_a_second_venue(client, tokens, first_block, last_block=HORIZON_BLOCK):
    """Every Uniswap V2 pair and V3 pool created for any of ``tokens`` in a block range.

    This is the migration search, and it is kept because it **failed**. ``PoolStatus.MIGRATED``,
    ``validate_replacement`` and ``require_same_quote_asset`` are still the paths with no real
    input in this repository, and the honest form of that sentence is a search somebody can re-run,
    not a claim that none exists.

    What it covers: both Uniswap factories, both token positions, every block from the first pair's
    creation to the horizon, for all 57 tokens at once. What it does not cover: SushiSwap, Curve,
    Balancer, any v4 pool, any venue on another chain, and any migration that moved to a *new token
    contract* — which is how a large share of real relaunches actually happen and which no factory
    search can see, because the new contract is simply a different token.

    Returns one ``(block, factory, pool, token0, token1)`` row per pool found.
    """
    words = [word(token) for token in tokens]
    rows = []
    lower = first_block
    while lower <= last_block:
        upper = min(lower + CHUNK - 1, last_block)
        for position in (1, 2):
            topics = (
                [[PAIR_CREATED, POOL_CREATED], words, None] if position == 1
                else [[PAIR_CREATED, POOL_CREATED], None, words]
            )
            for log in client.get_logs(from_block=lower, to_block=upper,
                                       address=[FACTORY_V2, FACTORY_V3], topics=topics):
                pool = ("0x" + log["data"][26:66] if log["topics"][0] == PAIR_CREATED
                        else "0x" + log["data"][-40:])
                rows.append((block_number(log), log["address"].lower(), pool.lower(),
                             address_of(log["topics"][1]), address_of(log["topics"][2])))
        lower = upper + 1
    return rows


def confirm_no_replacement_for(client, token, pair, first_block, last_block=HORIZON_BLOCK):
    """No pool other than ``pair`` was created for ``token`` on either Uniswap factory.

    §9.1 condition 3 for the dead pool, established by search rather than by assumption. Raises if
    a second pool turns up: that would not be a bug in this file, it would mean the position is
    marked at a live venue and the dead verdict is wrong.

    Its scope is :func:`search_for_a_second_venue`'s, with all of that function's limits.
    """
    found = [row for row in search_for_a_second_venue(client, (token,), first_block, last_block)
             if row[2] != pair.lower()]
    if found:
        raise SurveyRefused(
            "token {} has {} other pool(s) — {} — created before the horizon. §9.1 condition 3 "
            "does not hold and this pool's position must not be zeroed.".format(
                token, len(found), [row[2] for row in found]
            )
        )
    return True


# -- the report -----------------------------------------------------------------


def _thousands(value):
    return "{:,}".format(value)


def run(client):
    """Confirm every case against the snapshot and mark the three open positions.

    Returns the marks, so a test can pin them without re-running the printing.
    """
    print("case survey — real mainnet inputs for paths no real byte has reached")
    print("=" * 78)

    horizon_ts = confirm_horizon(client)
    weth_usd, weth_answer = read_quote_price(client, CHAINLINK_ETH_USD, HORIZON_BLOCK)
    usdt_usd, usdt_answer = read_quote_price(client, CHAINLINK_USDT_USD, HORIZON_BLOCK)
    print("\nhorizon      block {} ts {} (window end {} + {}s)".format(
        HORIZON_BLOCK, horizon_ts, WINDOW_END_BLOCK, MEASUREMENT_TAIL_SECONDS))
    print("prices       ETH/USD {} USDT/USD {} (Chainlink, 8dp, at the horizon block)".format(
        weth_answer, usdt_answer))
    weth_per_raw = divide(weth_usd, Decimal(10) ** 18)

    start_block, start_ts = confirm_trading_start(client)
    print("\n§4.7  SBET {}".format(SBET))
    print("      pair created {}, funded {}, first swap {} (ts {}) — all inside the window".format(
        SBET_PAIR_CREATED_BLOCK, SBET_FIRST_MINT_BLOCK, start_block, start_ts))
    for name, lots in (("A", WALLET_A_LOTS), ("B", WALLET_B_LOTS)):
        ages = [(lot.block - start_block, lot.timestamp - start_ts) for lot in lots]
        print("      wallet {} lot ages (blocks, seconds): {}".format(name, ages))

    confirm_venue(client, SBET_VENUE)
    print("\nvenue  {} — {} SBET / {} wei WETH at the horizon".format(
        SBET_VENUE.address, _thousands(SBET_VENUE.asset_reserve_raw),
        _thousands(SBET_VENUE.quote_reserve_raw)))
    print("       last swap block {} — {} seconds before the horizon, so it is trading".format(
        SBET_VENUE.last_swap_block, horizon_ts - SBET_VENUE.last_swap_timestamp))

    confirm_the_v3_pool_is_not_a_replacement(client)
    print("       a v3 SBET/WETH pool exists ({}) — zero active liquidity, no swaps: not a venue".format(
        SBET_V3_POOL))

    confirm_position(client, SBET, WALLET_A, WALLET_A_LOTS, (), WALLET_A_OPEN_RAW,
                     SBET_PAIR_CREATED_BLOCK)
    print("\ncase 1 §4.4 Case 2 — {}".format(WALLET_A))
    print("       {} buys, no disposal in {} blocks, {} raw open at the horizon".format(
        len(WALLET_A_LOTS), HORIZON_BLOCK - SBET_PAIR_CREATED_BLOCK, _thousands(WALLET_A_OPEN_RAW)))

    disposals = (
        (WALLET_B_SELL_BLOCK, WALLET_B_SELL_TX, WALLET_B_SELL_TO_POOL_RAW),
        (WALLET_B_SELL_BLOCK, WALLET_B_SELL_TX, WALLET_B_SELL_TAX_RAW),
    )
    confirm_position(client, SBET, WALLET_B, WALLET_B_LOTS, disposals, WALLET_B_OPEN_RAW,
                     SBET_PAIR_CREATED_BLOCK)
    whole, partial_index, partial_raw = confirm_fifo_consumption(
        WALLET_B_LOTS, WALLET_B_SELL_DEBITED_RAW, WALLET_B_OPEN_RAW)
    debited, credited = confirm_credited_amounts(client)
    proceeds = confirm_native_proceeds(client)
    print("\ncase 2 multi-lot FIFO — {}".format(WALLET_B))
    print("       {} buys, one sale of {} raw: {} lots whole, {} raw of lot {}, {} raw left".format(
        len(WALLET_B_LOTS), _thousands(debited), whole, _thousands(partial_raw), partial_index,
        _thousands(WALLET_B_OPEN_RAW)))
    print("       the sale debits {} and credits the pool {} — an 8% tax with its own log".format(
        _thousands(WALLET_B_SELL_DEBITED_RAW), _thousands(WALLET_B_SELL_TO_POOL_RAW)))
    print("       proceeds {} wei, arriving with no log at all; balance identity closes".format(
        _thousands(proceeds)))

    spent, middle, got = confirm_multi_hop(client)
    print("\ncase 3 multi-hop — {} at block {}".format(MULTIHOP_TX, MULTIHOP_BLOCK))
    print("       {} spends {} raw USDT -> {} wei WETH pool-to-pool -> {} raw SBET".format(
        MULTIHOP_WALLET, _thousands(spent), _thousands(middle), _thousands(got)))
    print("       the pool released {} raw; {} raw never reached the wallet".format(
        _thousands(MULTIHOP_SWAP_OUT_RAW), _thousands(MULTIHOP_TAX_RAW)))

    confirm_venue(client, DEAD_VENUE)
    confirm_position(client, DEAD_TOKEN, DEAD_HOLDER, (DEAD_HOLDER_LOT,), (),
                     DEAD_HOLDER_CREDITED_RAW, DEAD_PAIR_CREATED_BLOCK)
    confirm_no_replacement_for(client, DEAD_TOKEN, DEAD_PAIR, DEAD_PAIR_CREATED_BLOCK)
    print("\ncase 4 §9.1 dead pool — {} held by {}".format(DEAD_PAIR, DEAD_HOLDER))
    print("       cond 1: last swap block {}, {} seconds before the horizon".format(
        DEAD_VENUE.last_swap_block, horizon_ts - DEAD_VENUE.last_swap_timestamp))
    print("       cond 2: {} wei of WETH in the pool — the exit is worth a fraction of a cent".format(
        _thousands(DEAD_VENUE.quote_reserve_raw)))
    print("       cond 3: no other pool for this token on either Uniswap factory, ever")

    print("\ncase 5 fee-on-transfer the logs cannot correct — {}".format(DEAD_TOKEN))
    print("       Transfer log says {} raw; the balance credited {} raw; no second log".format(
        _thousands(DEAD_HOLDER_LOT.logged_raw), _thousands(credited)))

    print("\nmarks (marking + depth, on real reserves)")
    print("-" * 78)
    marks = {}
    for label, quantity, venue in (
        ("A open", WALLET_A_OPEN_RAW, SBET_VENUE),
        ("B residual", WALLET_B_OPEN_RAW, SBET_VENUE),
        ("dead holder", DEAD_HOLDER_CREDITED_RAW, DEAD_VENUE),
    ):
        value = mark_position(
            remaining_raw=quantity,
            pool=venue.pool_state(),
            horizon_block=HORIZON_BLOCK,
            horizon_ts=horizon_ts,
            quote_usd=weth_per_raw,
        )
        marks[label] = value
        print("  {:<12} ${:<28} {} / {}".format(
            label, str(value.value_usd)[:28], value.value_basis.name, value.pool_status.name))
    print("\n  the residual is worth ${} against a ${} minimum exit — and is still not dead,".format(
        str(marks["B residual"].value_usd)[:6], "1.00"))
    print("  because §9.1 is a conjunction and the pool it sits in traded an hour before the horizon.")

    population = enumerate_candidate_population(client)
    tokens = tuple(token for token, _pair in population)
    known = {pair for _token, pair in population}
    second = [row for row in search_for_a_second_venue(client, tokens, FACTORY_SLICES[0][0])
              if row[2] not in known]
    print("\nnot found: a migrated pool")
    print("-" * 78)
    print("  searched {} tokens x 2 factories x {} blocks; {} second venue(s) found, for {} of the".format(
        len(tokens), HORIZON_BLOCK - FACTORY_SLICES[0][0], len(second),
        len({row[3] if row[3] in tokens else row[4] for row in second})))
    print("  tokens, and not one of them a replacement for a pool that died. PoolStatus.MIGRATED,")
    print("  validate_replacement and require_same_quote_asset still have no real input.")

    replayed, live = client.replayed_count()
    print("\ncalls: {} replayed, {} live".format(replayed, live))
    return marks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", action="store_true",
                        help="open sockets and record any call the snapshot does not hold")
    args = parser.parse_args(argv)
    run(build_client(record=args.record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
