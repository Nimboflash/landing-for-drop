"""Four real wallets, four whole populations, driven through ``pipeline.run_wallet_window``.

    PYTHONPATH=src .venv/bin/python -m tools.case_runs

Every byte comes from ``tests/fixtures/case_runs/recordings``, replayed. The default mode is
``REPLAY_ONLY``: a call the snapshot does not hold raises rather than quietly measuring a different
chain than the one the printed numbers were checked against. ``--record`` is the only mode that
opens a socket, and ``--record-population`` is the only thing here that talks to a block explorer.

What this is
------------

``tools/case_survey.py`` found real inputs for the paths no real byte had reached and marked three
positions by calling :func:`marking.mark_position` directly. That is a unit call, not a run: it
skips attribution, netting, FIFO and scoring, it needs no census, and it cannot be wrong about a
denominator. This file is the other half — the same four wallets' **whole populations**, every
transaction they made in February 2023 and its §4.8 tail, through the real composition root with no
stage skipped and no stub anywhere.

It is **builder-lane self-testing on real data**, the same thing ``tools/mockchain/`` and
``tools/hyperliquid/`` are for. It is **not** the golden set: ticket 14's evidence bundles come
through the ground-truth reader under the Independent Validator, account selection there is made
without consulting any pipeline output, and all of it waits on ticket 02. Nothing here reads or
writes ``src/groundtruth/``, nothing here is an account *selection*, and no claim of ticket 14, 15,
16 or 17 is made by any line of it.

It is also not a measurement of anything. Four wallets are four wallets, and all four were found by
searching one 1,500-block slice of the Uniswap V2 factory — a population chosen because it was
cheap to enumerate, not because it represents anything.

The four cases
--------------

===================== ==== ==============================================================
:data:`WALLET_A`        12 §4.4 Case 2 — a position still open at the horizon, marked
                           against a real pool, with the liquidity bound biting
:data:`WALLET_B`       160 five open lots on one token, and the sale that should have
                           consumed them — which does **not** reach FIFO; see below
:data:`DEAD_HOLDER`    149 §9.1 — all three conditions, ``ValueBasis.DEAD_ZEROED``
:data:`MULTIHOP`       227 a two-hop route whose intermediate the wallet never holds
===================== ==== ==============================================================

548 transactions. Not 4 buys and 3 sells: the *whole* of what each wallet did, because a census is
a statement about a population and a population is not a selection of the interesting rows.

**The multi-lot FIFO case does not run, and this table says so rather than describing the case as
it was hoped to be.** ``wallet_b``'s five-lot sale and ``multihop``'s exit each sit in the
ingestion queue: each receipt carries two WETH ``Withdrawal`` legs, the wallet's own archive
balance accounts for exactly one of them, and the seam takes ``{log_index: address}`` with no way
to say "this leg I established, that one I did not". So both are refused whole — and both wallets'
marks are therefore of tokens they had already sold. ``multihop``'s to the raw unit; ``wallet_b``'s
to within 0.0087%. :func:`report_asset_conservation` is what makes that visible, and it is the
sharpest thing in this file: **the census conserves over transactions, and nothing conserves over
assets.**

The three caller inputs, and how each is established here
---------------------------------------------------------

* **the population** — every transaction touching the wallet between the window's first block and
  the marking horizon, from a block explorer's account listing (external, internal and token
  transfers unioned). It is a caller input because nothing in this repository enumerates a wallet's
  transactions, and 42 of these 548 are the reason: they touch the wallet only through an internal
  ETH transfer, which writes no log at all. Recorded under
  ``tests/fixtures/case_runs/population/`` with the URL that produced it and the date;
* **the native settlements** — where each WETH wrap or unwrap's native ETH came from or went to.
  ``ingest`` refuses to guess this and is right to. Here every one of them is *measured*, against
  the wallet's own archive balance, by :func:`establish_native_settlements` — and where the
  identity does not close, the settlement is **not** stated, because the alternative is to invent
  the one fact a trace would have supplied. See that function for what happens to the transaction
  then; it is the sharpest thing this file found;
* **the price book** — one USD price per §4.6 quote asset, from Chainlink aggregators read on-chain
  at the horizon block. The pipeline's seam takes one scalar per quote asset for a whole window;
  that is a real limitation and it is not fixed here.

The §6.2 address typing is the fourth, and this file takes a different stance from the tracer
bullet's on purpose: see :func:`build_context`.

**The §4.7 token trading starts used to be a fifth, and are not any more.** Two of them were
written into this file by hand, and every other token a wallet bought was quarantined for want of
one — 82 buys across the four cases, two and a half times the whole undecodable population, and the
largest single loss in the machine. :func:`report_token_starts` now derives them from the chain
with :func:`pipeline.derive_token_starts`, and the two hand-established dates have changed sides:
:func:`confirm_the_known_starts` checks the derivation against them and refuses the run if it
disagrees. Nothing here reads the pool a buy settled through — that pool would give a *later* start
than the earliest one §4.7 asks for, which makes the buy look earlier, which moves it towards
bucket A.

What is deliberately not here: any trace, any ``latest`` tag, any float, and any
``src/groundtruth/``.
"""

import argparse
import collections
import datetime
import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import replace
from decimal import Decimal

from attribution import AttributionContext
from contracts import (
    AssetTier,
    PoolState,
    USDC,
    USDT,
    WBTC,
    WETH,
    calc,
    divide,
    normalise_asset,
)
from depth import PricedPool, QuoteAsset, measure_depth, size_to_cost_cap_detail
from ingest import (
    LogRefused,
    block_header,
    gas_cost,
    logs_of,
    native_balance,
    native_legs,
    require_receipt,
    token_decimals,
)
from marking import token_age_bucket
from pipeline import (
    ObservedTransaction,
    Stage,
    UndecodableTransaction,
    WindowConfig,
    derive_token_starts,
    observed_transaction,
    refusals_of,
    run_wallet_window,
    token_starts_of,
    window_from_blocks,
)
from pipeline.poolread import PoolReadDefect, read_v2_pool
from ingest.blockscan import RESIDUE as SOLE_MOVER_RESIDUE
from ingest.blockscan import (
    BlockScanRefused,
    SoleMoverUnestablished,
    block_occupancy,
    sole_mover_of_balance,
)
from transport import AUTO, REPLAY_ONLY, RecordingCache, RpcClient, block_parameter
from transport.endpoints import USER_AGENT

from tools.case_survey import (
    DEAD_HOLDER,
    DEAD_PAIR,
    DEAD_TOKEN,
    DEAD_VENUE,
    HORIZON_BLOCK,
    MULTIHOP_WALLET,
    SBET,
    SBET_PAIR,
    SBET_TRADING_START_BLOCK,
    SBET_VENUE,
    WALLET_A,
    WALLET_B,
    address_of,
    read_reserves,
    uint,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Its own snapshot directory. 548 receipts, 471 archive balances and one block header per
#: transaction do not belong in the survey's snapshot, whose fingerprint answers a different
#: question.
RECORDINGS = os.path.join(REPO, "tests", "fixtures", "case_runs", "recordings")

#: The four account listings, one JSON document each, with the URL and the date that produced them.
POPULATIONS = os.path.join(REPO, "tests", "fixtures", "case_runs", "population")

# -- the window ------------------------------------------------------------------

#: February 2023, the same edges ticket 19's tracer bullet established and
#: ``tools.case_survey.confirm_horizon`` re-derived the horizon from.
WINDOW_INDEX = 1
WINDOW_START_BLOCK = 16530248
WINDOW_END_BLOCK = 16730071
BLOCK_BEFORE_WINDOW = 16530247
BLOCK_AFTER_WINDOW = 16730072

FEB_1_2023 = 1675209600
MAR_1_2023 = 1677628800

# -- §4.6: the price book --------------------------------------------------------

#: Chainlink aggregator proxies, one per §4.6 quote asset, written out rather than computed: a
#: constant is what a reader checks against an explorer's "Read Contract" tab. All four answer in
#: 8 decimals. WBTC is priced from the BTC/USD feed and that is *stated* rather than pretended —
#: WBTC's own feed is a WBTC/BTC ratio, and no wallet here ever touches WBTC, so the entry exists
#: only so a quote asset cannot be silently unpriced.
CHAINLINK = {
    WETH: "0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419",
    USDC: "0x8fffffd4afb6115b954bd326cbe7b4ba576818f6",
    USDT: "0x3E7d1eAB13ad0104d2750B8863b489D65364e32D",
    WBTC: "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c",
}
LATEST_ROUND_DATA = "0xfeaf968c"
CHAINLINK_DECIMALS = 8

# -- §6.2: the addresses this run states rather than measures --------------------

#: The venues on the case legs, and nothing else. Labels come from a block explorer, as ticket
#: 19's ``INFRASTRUCTURE`` does. See :func:`build_context` for why this list is four entries long
#: rather than four hundred, and what that costs.
INFRASTRUCTURE = {
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap v2 router 02",
    SBET_PAIR: "Uniswap v2 pair SBET/WETH — the venue both marked positions are exited at",
    DEAD_PAIR: "Uniswap v2 pair for the rug token — the dead venue",
    "0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852": "Uniswap v2 pair USDT/WETH — the first hop of "
                                                  "the multi-hop route",
}

#: The height every ``eth_getCode`` is taken at. The horizon rather than the window's first block,
#: and deliberately: a contract deployed *during* the period carries code at the horizon and none
#: at the window's open, and the only direction that matters is the conservative one. "Has code"
#: keeps an address out of the EOA set, and an address out of the EOA set cannot become a phantom
#: portfolio; "no code" is the reading that admits one.
CODE_AT_BLOCK = HORIZON_BLOCK

# -- the four cases --------------------------------------------------------------

MULTIHOP = MULTIHOP_WALLET

#: ``(case name, wallet, population file)``. The order is the order the report prints in.
CASES = (
    ("wallet_a", WALLET_A, "wallet_a.json"),
    ("wallet_b", WALLET_B, "wallet_b.json"),
    ("dead_holder", DEAD_HOLDER, "dead_holder.json"),
    ("multihop", MULTIHOP, "multihop.json"),
)

# -- §4.5: the one pool in this data that depth is allowed to price --------------

#: Uniswap v2 USDT/WETH. It is here because :mod:`depth` refuses ``AssetTier.LONG_TAIL`` outright
#: (§9.5) and every *other* pool in this file is long-tail by any honest reading — so driving depth
#: on SBET would mean filing a four-day-old rug as a mid-cap to get a number out. USDT quoted in
#: WETH is a defensible ``MAJOR``, and the leader clip below is a real trade through this exact
#: pool: the first hop of the multi-hop transaction.
DEPTH_PAIR = "0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852"
DEPTH_TIER = AssetTier.MAJOR

#: The multi-hop wallet's 800 USDT, as the leader clip, and a flat per-copy gas cost in USD. The
#: gas figure is an assumption and is not measured here; ``tools/mockchain/report.py`` uses the
#: same $15.
DEPTH_LEADER_CLIP_USD = "800"
DEPTH_GAS_USD = "15"

#: The follower's capital. $1,000,000 against a pool this deep makes the *cost cap* the binding
#: constraint rather than the follower's own wallet, which is the branch §4.5 exists to exercise.
DEPTH_AUM_USD = "1000000"

#: Event topics, copied from :mod:`ingest.events` rather than imported for the reason
#: ``tools.case_survey`` gives: a survey that asked the decoder's own registry what it knows would
#: be asking the question the seventh tracer-bullet transaction answered the expensive way.
WITHDRAWAL = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"
SWAP_V2 = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"

#: The rug token's §4.7 start: its pair was created at 16530559 and first traded 15 blocks later,
#: both inside the window. Read off mainnet by ``tools/case_survey.py``, and no longer *supplied*
#: to this run — :func:`confirm_the_known_starts` checks the derivation against it, which is the
#: opposite direction and the only external check the derivation has.
DEAD_TRADING_START_BLOCK = 16530574

BALANCE_OF = "0x70a08231"
TOKEN0 = "0x0dfe1681"
TOKEN1 = "0xd21220a7"
V3_LIQUIDITY = "0x1a686502"
V3_SLOT0 = "0x3850c7bd"
V3_FEE = "0xddca3f43"

#: The deepest real v3 pool in this window — USDC/WETH at 5bp. It is here for one reason: the
#: virtual-reserves branch of :func:`marking.liquidity.effective_reserves` and :mod:`depth`'s
#: concentrated validity band have never seen a real ``(liquidity, sqrtPriceX96)`` pair. The
#: survey's v3 pool has ``L=0`` and lands on the refusal branch instead.
V3_POOL = "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640"


class CaseRunRefused(RuntimeError):
    """A precondition this run states did not hold when it was measured.

    Raised rather than reported, because each is a claim the printed numbers rest on: a window edge
    that is not an edge, a pool whose reserves are not what the survey confirmed, or a population
    file whose wallet is not the wallet being run would each make this file publish a number about
    something other than what it says it is about.
    """


# -- the client and the snapshot -------------------------------------------------


def build_client(record=False):
    """The RPC client, replaying by default and recording only when asked.

    Guarantees replay of a recorded call without a socket. Guarantees nothing about a recorded
    answer being *correct* — see :mod:`transport.cache`.
    """
    return RpcClient(cache=RecordingCache(RECORDINGS), mode=AUTO if record else REPLAY_ONLY)


def hex_block(block):
    return block_parameter(block)


def call_contract(client, to, data, block):
    """One ``eth_call`` at a height. A tag would make the answer about today, not about 2023."""
    return client.call("eth_call", [{"to": to, "data": data}, hex_block(block)])


# -- the population --------------------------------------------------------------


def load_population(filename):
    """One wallet's account listing, as ``(wallet, tuple of tx hashes, document)``.

    The document carries the URL template, the three explorer actions it unions, the block range
    and the date it was retrieved, so "this is the wallet's population" is checkable by re-running
    the same query rather than by trusting this file.

    What it guarantees: that these are the transactions the explorer listed for that address in
    that range on that date. What it does not: that the explorer's listing is complete. No
    enumeration from logs could replace it — 42 of these 548 touch their wallet only through an
    internal ETH transfer — and nothing here cross-checks it against a second explorer.
    """
    path = os.path.join(POPULATIONS, filename)
    with open(path) as handle:
        document = json.load(handle)
    hashes = tuple(row["tx_hash"] for row in document["transactions"])
    if len(set(hashes)) != len(hashes):
        raise CaseRunRefused(
            "{} lists {} transactions under {} distinct hashes; a population with a repeated hash "
            "would be counted twice in the census.".format(path, len(hashes), len(set(hashes)))
        )
    return document["wallet"].lower(), hashes, document


def record_populations():
    """Re-fetch the four account listings from the block explorer. The only GET in this package.

    Blockscout answers an honest User-Agent, and the one sent is
    :data:`transport.endpoints.USER_AGENT` — the same string every RPC call in this repository
    carries. Etherscan returns 403 to it, and a probe that once sent a browser-shaped one got its
    signature permanently banned at another vendor.
    """
    template = ("https://eth.blockscout.com/api?module=account&action={action}&address={address}"
                "&startblock={first}&endblock={last}&sort=asc")
    actions = ("txlist", "txlistinternal", "tokentx")
    retrieved = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    stamp = retrieved.isoformat().replace("+00:00", "Z")
    if not os.path.isdir(POPULATIONS):
        os.makedirs(POPULATIONS)
    for name, wallet, filename in CASES:
        rows = collections.OrderedDict()
        for action in actions:
            url = template.format(action=action, address=wallet,
                                  first=WINDOW_START_BLOCK, last=HORIZON_BLOCK)
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=90) as answer:
                payload = json.loads(answer.read())
            for row in payload.get("result") or []:
                tx_hash = (row.get("hash") or row.get("transactionHash") or "").lower()
                entry = rows.setdefault(
                    tx_hash,
                    {"tx_hash": tx_hash, "block": int(row["blockNumber"]), "listings": []},
                )
                if action not in entry["listings"]:
                    entry["listings"].append(action)
            time.sleep(1)
        items = sorted(rows.values(), key=lambda row: (row["block"], row["tx_hash"]))
        document = {
            "wallet": wallet,
            "case": name,
            "first_block": WINDOW_START_BLOCK,
            "last_block": HORIZON_BLOCK,
            "source": "eth.blockscout.com etherscan-compatible API",
            "url_template": template,
            "actions": list(actions),
            "retrieved_at": stamp,
            "count": len(items),
            "transactions": items,
        }
        with open(os.path.join(POPULATIONS, filename), "w") as handle:
            json.dump(document, handle, indent=1, sort_keys=True)
        print("{:<12} {} {} transactions".format(name, wallet, len(items)))


# -- the caller inputs, each confirmed by measurement ----------------------------


def confirm_window_edges(client):
    """The two blocks outside the window straddle the calendar boundary. Returns their headers.

    Guarantees that :data:`WINDOW_START_BLOCK` is the first block of February 2023 and
    :data:`WINDOW_END_BLOCK` the last, given the chain these recordings came from. Guarantees
    nothing about either block being canonical — no free endpoint offers a way to establish that,
    as :mod:`ingest.blocks` already says.
    """
    before = block_header(client, BLOCK_BEFORE_WINDOW)
    after = block_header(client, BLOCK_AFTER_WINDOW)
    start = block_header(client, WINDOW_START_BLOCK)
    end = block_header(client, WINDOW_END_BLOCK)
    if not (before.timestamp < FEB_1_2023 <= start.timestamp):
        raise CaseRunRefused(
            "blocks {} (ts {}) and {} (ts {}) do not straddle 2023-02-01T00:00:00Z ({}).".format(
                BLOCK_BEFORE_WINDOW, before.timestamp, WINDOW_START_BLOCK, start.timestamp,
                FEB_1_2023,
            )
        )
    if not (end.timestamp < MAR_1_2023 <= after.timestamp):
        raise CaseRunRefused(
            "blocks {} (ts {}) and {} (ts {}) do not straddle 2023-03-01T00:00:00Z ({}).".format(
                WINDOW_END_BLOCK, end.timestamp, BLOCK_AFTER_WINDOW, after.timestamp, MAR_1_2023,
            )
        )
    return before, start, end, after


def read_prices(client, block=HORIZON_BLOCK):
    """USD per **raw unit** of each §4.6 quote asset, from Chainlink at ``block``.

    Returns ``{asset: (usd_per_raw_unit, raw_answer, decimals)}``. Both the aggregator's 8 decimals
    and the token's own are divided out through the frozen context, so nothing here is a float and
    nothing is a remembered scaling factor — ``decimals()`` is read from each token contract.

    Guarantees only that this is what that aggregator answered at that height. A Chainlink round is
    a median of that day's reporters, not a transaction price, and one scalar stands for a whole
    window.
    """
    prices = {}
    for asset, feed in sorted(CHAINLINK.items()):
        answer = uint(call_contract(client, feed, LATEST_ROUND_DATA, block), 1)
        decimals = token_decimals(client, asset, block)
        usd = divide(Decimal(answer), Decimal(10) ** CHAINLINK_DECIMALS)
        prices[asset] = (divide(usd, Decimal(10) ** decimals), answer, decimals)
    return prices


def confirm_venues(client, block=HORIZON_BLOCK):
    """Re-read both marking venues' reserves and side ordering at the horizon.

    ``tools.case_survey`` confirmed these against its own snapshot; a mark published by *this* run
    against reserves nobody read in *this* run would be a number resting on another file's cache.
    So the two ``getReserves()`` calls are made again here, and the pool's own ``token0()`` decides
    which reserve is the asset's — attributing them the wrong way round produces a plausible price
    that is wrong by the ratio of the two.
    """
    for venue in (SBET_VENUE, DEAD_VENUE):
        reserve0, reserve1 = read_reserves(client, venue.address, block)
        side0 = address_of(call_contract(client, venue.address, TOKEN0, block))
        side1 = address_of(call_contract(client, venue.address, TOKEN1, block))
        if side0 == venue.asset.lower() and side1 == venue.quote.lower():
            asset_reserve, quote_reserve = reserve0, reserve1
        elif side1 == venue.asset.lower() and side0 == venue.quote.lower():
            asset_reserve, quote_reserve = reserve1, reserve0
        else:
            raise CaseRunRefused(
                "pool {} holds token0={} token1={}; this run calls it a pool of {} quoted in "
                "{}.".format(venue.address, side0, side1, venue.asset, venue.quote)
            )
        if (asset_reserve, quote_reserve) != (venue.asset_reserve_raw, venue.quote_reserve_raw):
            raise CaseRunRefused(
                "pool {} holds ({}, {}) at block {}; this run marks against ({}, {}).".format(
                    venue.address, asset_reserve, quote_reserve, block,
                    venue.asset_reserve_raw, venue.quote_reserve_raw,
                )
            )
    return {
        normalise_asset(SBET): SBET_VENUE.pool_state(),
        normalise_asset(DEAD_TOKEN): DEAD_VENUE.pool_state(),
    }


#: The two §4.7 starts this file used to *supply* and now uses to *check*: SBET's pair and the rug
#: token's, each read off mainnet by ``tools/case_survey.py`` with a block explorer beside it. They
#: are the derivation's only externally-known answers, so a run whose derivation disagrees with
#: either is refused rather than published — see :func:`confirm_the_known_starts`.
KNOWN_TOKEN_STARTS = {
    normalise_asset(SBET): (SBET_PAIR, SBET_TRADING_START_BLOCK),
    normalise_asset(DEAD_TOKEN): (DEAD_PAIR, DEAD_TRADING_START_BLOCK),
}


def tokens_needing_starts(client, pools, price_book, window, horizon):
    """Which assets this run needs a §4.7 start for — asked of the run, never guessed.

    Every case is driven once with ``token_starts={}``. ``pipeline.run`` computes a buy's bucket
    before anything else about it, so with no starts supplied *every* buy that reaches marking is
    quarantined there, and the marking queue's ``asset`` field is then exactly the set of assets a
    start is wanted for. That field is read rather than the queue's prose: the reasons are
    sentences written at each refusal site and a tool that parsed them would go quiet the first
    time one was reworded.

    Why not simply every asset the population ever bought: 54 assets are bought across these four
    wallets and 30 of them reach marking. The other 24 belong to buys in §4.8's measurement tail,
    deferred to a later window and never bucketed here, and deriving a start for one costs about
    seventy recorded RPC calls to produce a date nothing in this run reads.

    Guarantees the set of assets whose buys this window would quarantine for want of §4.7.
    Guarantees nothing about the assets themselves — that a start *exists* for one is
    :func:`pipeline.derive_token_starts`'s question and it answers a good many of them with a
    refusal.
    """
    empty = WindowConfig(horizon_block=horizon.number, horizon_ts=horizon.timestamp,
                         token_starts={})
    wanted = set()
    for _name, wallet, filename in CASES:
        _listed, population, _document = load_population(filename)
        result, _items, _unestablished, _rows = run_case(
            client, wallet, population, pools, price_book, window, empty
        )
        for record in result.quarantine.by_stage(Stage.MARKING):
            if record.asset:
                wanted.add(normalise_asset(record.asset))
    return tuple(sorted(wanted))


def assets_needing_pools(client, pools, price_book, window, config):
    """Which assets this run leaves an open position in — asked of the run, never guessed.

    The same shape as :func:`tokens_needing_starts` and for the same reason: every case is driven
    once with the pools already known, and the marking queue's ``asset`` field is then exactly the
    set an open position was left in. The field is read rather than the prose, because the reasons
    are sentences written at each refusal site and a tool that parsed them would go quiet the first
    time one was reworded.

    Guarantees the set of assets a mark is wanted for. Guarantees nothing about a pool existing for
    one — that is :func:`derive_open_position_pools`\ 's question, and it answers some of them with
    a refusal.
    """
    wanted = set()
    for _name, wallet, filename in CASES:
        _listed, population, _document = load_population(filename)
        result, _items, _unestablished, _rows = run_case(
            client, wallet, population, pools, price_book, window, config
        )
        for record in result.quarantine.by_stage(Stage.MARKING):
            if record.asset and "no pool state was supplied" in record.reason:
                wanted.add(normalise_asset(record.asset))
    return tuple(sorted(wanted - set(pools)))


def derive_open_position_pools(client, assets, price_book, block=HORIZON_BLOCK):
    """A :class:`contracts.PoolState` per asset, read at the horizon, or a refusal per asset.

    The address is computed by CREATE2 rather than looked up, so an asset nobody registered still
    has a venue to read. Each asset is tried against every §4.6 quote in the price book, deepest
    first is *not* attempted — the first quote that answers is taken, and the pool's own
    ``token0()`` decides the orientation.

    Refusals are returned rather than raised. An asset with no readable pool must stay quarantined,
    and that is the machine working: an unmarked position is not a zero, and turning one into the
    other is exactly the §4.4 Case 2 error this run exists to avoid publishing.
    """
    found, refused = {}, {}
    for asset in assets:
        reasons = []
        for quote in sorted(price_book):
            try:
                reading = read_v2_pool(client, asset, quote, block)
            except PoolReadDefect as exc:
                reasons.append("{}: {}".format(quote[:10], str(exc).split(".")[0]))
                continue
            if reading.state.asset_reserve_raw == 0 or reading.state.quote_reserve_raw == 0:
                reasons.append("{}: pool exists and holds nothing".format(quote[:10]))
                continue
            found[normalise_asset(asset)] = reading
            break
        else:
            refused[normalise_asset(asset)] = tuple(reasons)
    return found, refused


def confirm_the_known_starts(findings):
    """The derivation reproduces the two starts that were established some other way, or this run
    refuses to publish.

    SBET's 16530948 and the rug token's 16530574 were read off mainnet by
    ``tools/case_survey.py``, pair by pair, with the ``Mint`` and the ``Swap`` looked at
    individually. They are the only two §4.7 dates in this repository that did not come out of
    :mod:`pipeline.tokenstart`, so they are the only external check there is on it — and a
    derivation that disagreed with either would still hand back a plausible date for the other
    twenty-eight, which nobody could check at all.

    Also checks the *pool*: the same block reached through a different pair would mean the
    derivation had found some other market that happened to open in the same block.
    """
    for token, (pair, start_block) in sorted(KNOWN_TOKEN_STARTS.items()):
        finding = findings.get(token)
        if finding is None or not finding.established:
            raise CaseRunRefused(
                "the derivation returned no §4.7 start for {}, whose start is known to be block "
                "{} in pair {}: {}".format(
                    token, start_block, pair,
                    "no finding at all" if finding is None else finding.refusal,
                )
            )
        if finding.start.block != start_block or normalise_asset(finding.pool) != pair:
            raise CaseRunRefused(
                "the derivation puts {}'s §4.7 start at block {} in pool {}; it was measured off "
                "mainnet at block {} in pair {}. The derivation is wrong — do not adjust this "
                "expectation to match it.".format(
                    token, finding.start.block, finding.pool, start_block, pair,
                )
            )
        if not WINDOW_START_BLOCK <= start_block <= WINDOW_END_BLOCK:
            raise CaseRunRefused(
                "{} started trading at block {}, outside the window [{}, {}].".format(
                    token, start_block, WINDOW_START_BLOCK, WINDOW_END_BLOCK
                )
            )
    return KNOWN_TOKEN_STARTS


# -- the native settlements, measured rather than stated -------------------------

#: What :func:`establish_native_settlements` could not establish, and why.
Unestablished = collections.namedtuple(
    "Unestablished", "tx_hash block legs measured_wei expected_wei reason"
)


def establish_native_settlements(client, wallet, population):
    """Where each WETH wrap or unwrap's native ETH went, from the wallet's own archive balance.

    The identity is :mod:`ingest.settlement`'s::

        balance(wallet, block) - balance(wallet, block - 1)  +  gas the wallet paid
            =  the wei the wallet received in native ETH

    A wrap takes ETH off the wallet and an unwrap puts it back, so the receipt's legs have a signed
    sum from the wallet's side. Where that sum equals the measured wei, **every leg in the receipt
    settled on the wallet** and the settlement is stated with that as its evidence. Where it does
    not, nothing is stated: the ETH went somewhere these bytes do not name, and the only ways to
    produce an address anyway are to guess one or to assume the withdrawer kept it — which
    :func:`ingest.receipts.transfers_from_logs` refuses by name, and rightly.

    Returns ``(settlements, unestablished)``:

    * ``settlements`` — ``{tx_hash: {log_index: address}}``, ready for
      :func:`pipeline.observed_transaction`;
    * ``unestablished`` — one :class:`Unestablished` per transaction whose legs could not be
      attributed, with the two wei figures that disagree.

    **The precondition, stated and checked.** The identity holds only where the wallet had exactly
    one transaction in that block and received nothing else. The population is every transaction
    touching the wallet in the period, so a second one in the same block is visible here and is
    refused — but a block reward or a beacon withdrawal credit is not in any listing, and no
    enumeration in this repository would show one. That residue is real and is not closed here.

    **What an unestablished settlement costs.** :func:`pipeline.observed_transaction` raises
    ``NativeSettlementUnknown`` for it, so the transaction reaches no census, no queue and no
    coverage report — the same hole ``UndecodableTransaction`` was built to close for an unlisted
    event and ticket 21 closed for a revert, one door further along. This file therefore carries it
    as an :class:`pipeline.UndecodableTransaction` naming the WETH leg, which is what keeps the
    census total equal to the population. That conversion is done **here, by the caller**, and not
    in ``src``: the reader cannot tell "the caller could not establish this" from "the caller
    forgot to supply it", and only one of those is a measurement limitation. See
    :func:`read_population`.
    """
    blocks = collections.Counter()
    receipts = {}
    for tx_hash in population:
        receipt = require_receipt(client, tx_hash)
        receipts[tx_hash] = receipt
        blocks[int(receipt["blockNumber"], 16)] += 1

    settlements = {}
    unestablished = []
    occupancy = {}
    for tx_hash in population:
        receipt = receipts[tx_hash]
        logs = logs_of(receipt)
        try:
            legs = native_legs(logs)
        except LogRefused:
            # The receipt holds a log this decoder will not read at all. That refusal is
            # ingestion's to carry, and it carries it whole; there is no settlement to establish
            # for a receipt that produces no legs.
            continue
        if not legs:
            continue
        block = int(receipt["blockNumber"], 16)
        if blocks[block] > 1:
            unestablished.append(Unestablished(
                tx_hash, block, tuple(legs), None, None,
                "the wallet has {} transactions in block {}, so its balance delta across that "
                "block is not this transaction's".format(blocks[block], block),
            ))
            continue
        # The population listing shows transactions somebody indexed for this wallet. The block
        # itself shows what was actually in it -- a transaction the listing missed, the wallet
        # being the block's miner, a consensus withdrawal. ingest.blockscan reads the block once
        # and answers for every leg in it, which is the residue the paragraph above named and did
        # not close.
        if block not in occupancy:
            try:
                occupancy[block] = block_occupancy(client, wallet, block)
            except BlockScanRefused as exc:
                unestablished.append(Unestablished(
                    tx_hash, block, tuple(legs), None, None,
                    "the sole-mover precondition could not be read for block {}: {}".format(
                        block, exc
                    ),
                ))
                continue
        try:
            sole_mover_of_balance(client, wallet, block, tx_hash, occupancy=occupancy[block])
        except SoleMoverUnestablished:
            unestablished.append(Unestablished(
                tx_hash, block, tuple(legs), None, None,
                "the balance delta across block {} cannot be attributed to this transaction "
                "alone: {}".format(block, occupancy[block].why_not(tx_hash)),
            ))
            continue
        after = native_balance(client, wallet, block)
        before = native_balance(client, wallet, block - 1)
        paid = gas_cost(receipt) if receipt["from"].lower() == wallet else 0
        measured = after - before + paid
        by_index = {int(log["logIndex"], 16): log for log in logs}
        expected = 0
        for index in legs:
            log = by_index[index]
            amount = int(log["data"], 16)
            expected += amount if log["topics"][0] == WITHDRAWAL else -amount
        if expected == 0:
            unestablished.append(Unestablished(
                tx_hash, block, tuple(legs), measured, expected,
                "the receipt's wrap and unwrap legs cancel, so an identity that closes at zero is "
                "evidence for nothing: it holds equally if none of the ETH was the wallet's",
            ))
            continue
        if measured != expected:
            unestablished.append(Unestablished(
                tx_hash, block, tuple(legs), measured, expected,
                "the wallet's balance moved {} wei across block {} once gas is added back, and "
                "the receipt's {} native leg(s) sum to {}; the difference of {} wei went to an "
                "address these logs do not name".format(
                    measured, block, len(legs), expected, expected - measured,
                ),
            ))
            continue
        settlements[tx_hash] = {index: wallet for index in legs}
    return settlements, tuple(unestablished)


# -- reading the population through the real seam --------------------------------


def read_population(client, wallet, population, settlements, unestablished):
    """Every transaction, through :func:`pipeline.observed_transaction`. One row per hash, always.

    Three kinds of row come back, and the count is the population's:

    * an :class:`pipeline.ObservedTransaction` — decoded, with ``success`` carrying whether the
      chain executed it;
    * an :class:`pipeline.UndecodableTransaction` produced by ``observed_transaction`` itself,
      where a log carried an event the registry does not list or a shape contradicting the one it
      claims;
    * an :class:`pipeline.UndecodableTransaction` produced **here**, where
      :func:`establish_native_settlements` could not establish where a wrap or unwrap's native ETH
      went. ``observed_transaction`` raises for that case, and a raise at this boundary is a
      transaction that leaves the population before the population is counted.

    The third is the caller's judgement and is not ``src``'s to make: "I could not establish this"
    and "I did not supply this" arrive at the reader as the same argument, and turning the refusal
    into a status inside ``pipeline.chain`` would let a run that simply stopped supplying
    settlements report every WETH transaction as unreadable. The distinction lives with whoever
    tried, so the conversion lives here — with the measurement that failed written into the queue
    entry's detail.
    """
    unestablished_by_hash = {row.tx_hash: row for row in unestablished}
    items = []
    for tx_hash in population:
        row = unestablished_by_hash.get(tx_hash)
        if row is not None:
            receipt = require_receipt(client, tx_hash)
            header = block_header(client, int(receipt["blockNumber"], 16))
            items.append(UndecodableTransaction(
                tx_hash=tx_hash,
                block_number=header.number,
                timestamp=header.timestamp,
                tx_sender=receipt["from"],
                topic=WITHDRAWAL,
                contract=WETH,
                log_index=row.legs[0],
                refusal="NativeSettlementUnknown",
                detail=(
                    "log {} of {} is a WETH wrap or unwrap and where its native ETH settled was "
                    "not established: {}. No address was supplied, because the two ways to supply "
                    "one anyway are to guess it and to assume the withdrawer kept it.".format(
                        row.legs[0], tx_hash, row.reason,
                    )
                ),
            ))
            continue
        items.append(observed_transaction(
            client, tx_hash, native_settlement=settlements.get(tx_hash)
        ))
    return tuple(items)


def build_context(client, items):
    """The §6.2 address typing: measured where it can be, and stated for four venues.

    Measured: whether each address on a transfer leg carried code at :data:`CODE_AT_BLOCK`. That is
    ``eth_getCode``, and it is what separates an EOA from a contract without trusting a label.

    **This file does not refuse an untyped contract, and the tracer bullet does.** That difference
    is the point rather than a relaxation. Seven transactions have six code-bearing addresses on
    their legs and every one of them can be classified by hand; 548 transactions have 687 addresses
    on theirs, and a hand-written label for each would be a list nobody checked wearing the
    authority of one somebody did. So the four venues the *cases* run through are stated, and every
    other contract is left untyped — which is not a default typing: :func:`attribution.resolve` puts
    an untyped two-sided address in the candidate set, refuses to count it as evidence of a
    portfolio, and records it in the evidence as "read as a venue rather than an owner".

    What that costs, stated rather than assumed away: §6.2's positive exclusion of venues from the
    candidate universe is doing no work for those 683 addresses. The resolver's weaker fallback is,
    and it is weaker in a specific way — an *EOA* market maker on both sides of a transfer set is
    typed by ``eth_getCode`` as an EOA, becomes a second evidenced owner, and takes the whole
    transaction to ``UNRESOLVED``. The report prints how many landed there.

    Returns ``(context, rows)`` where each row is ``(address, has_code, role)``.
    """
    decoded = [item for item in items if isinstance(item, ObservedTransaction)]
    addresses = sorted({leg.from_addr for item in decoded for leg in item.transfers}
                       | {leg.to_addr for item in decoded for leg in item.transfers})
    rows = []
    eoas = []
    infrastructure = []
    for address in addresses:
        code = client.call("eth_getCode", [address, hex_block(CODE_AT_BLOCK)])
        has_code = isinstance(code, str) and code not in ("0x", "0x0", "")
        if not has_code:
            eoas.append(address)
            rows.append((address, False, "EOA (eth_getCode returned no code)"))
        elif address in INFRASTRUCTURE:
            infrastructure.append(address)
            rows.append((address, True, "§6.2 infrastructure — {}".format(INFRASTRUCTURE[address])))
        else:
            rows.append((address, True, "contract, untyped — read as a venue, never as an owner"))
    return AttributionContext(
        eoas=frozenset(eoas), infrastructure=frozenset(infrastructure)
    ), tuple(rows)


# -- the run ---------------------------------------------------------------------


def run_case(client, wallet, population, pools, prices, window, config):
    """One wallet's whole population through ``run_wallet_window``. Returns the result and inputs.

    Every transaction the explorer listed is handed in. Nothing is filtered for being
    uninteresting, and nothing is dropped for being unreadable — an unreadable one arrives as the
    carried status, which is what makes ``census.total`` the population's size rather than the
    decoder's.
    """
    settlements, unestablished = establish_native_settlements(client, wallet, population)
    items = read_population(client, wallet, population, settlements, unestablished)
    context, rows = build_context(client, items)
    items = tuple(
        replace(item, context=context) if isinstance(item, ObservedTransaction) else item
        for item in items
    )
    result = run_wallet_window(items, pools, prices, window, config)
    return result, items, unestablished, rows


def conservation(result, population):
    """What went in, and what each row is accounted for as. Returns ``(total, doors, ok)``.

    Recomputed here from the published result rather than read off ``census.total``:
    ``run_wallet_window`` checks its own conservation, and a check that consulted the same field
    twice would be a check on nothing. The three doors are netting's results, netting's queue
    records and ingestion's queue records — the same three
    :func:`pipeline.run._require_the_population_is_conserved` names, counted independently here.
    """
    from pipeline import Stage

    netted = {row.tx_hash for row in result.results}
    netting_queue = {tx for record in result.quarantine.by_stage(Stage.NETTING)
                     for tx in record.tx_hashes}
    ingestion_queue = {tx for record in result.quarantine.by_stage(Stage.INGESTION)
                       for tx in record.tx_hashes}
    doors = (len(netted), len(netting_queue), len(ingestion_queue))
    accounted = netted | netting_queue | ingestion_queue
    ok = (
        len(accounted) == len(population)
        and sum(doors) == len(population)
        and accounted == set(population)
        and result.census.total == len(population)
        and result.stages.transactions_in == len(population)
    )
    return len(population), doors, ok


# -- §4.5: depth, on the one pool in this data it is allowed to price ------------


def read_depth_pool(client, prices, block=HORIZON_BLOCK):
    """The USDT/WETH v2 pair at the horizon, as a :class:`depth.PricedPool`.

    The pool's own ``token0()`` decides which reserve is which; the last swap it served is read
    from its logs, because a :class:`contracts.PoolState` that claimed a swap it did not serve
    would pass the look-ahead guard on a fiction.
    """
    reserve0, reserve1 = read_reserves(client, DEPTH_PAIR, block)
    side0 = address_of(call_contract(client, DEPTH_PAIR, TOKEN0, block))
    if side0 == USDT:
        asset_reserve, quote_reserve = reserve0, reserve1
    else:
        asset_reserve, quote_reserve = reserve1, reserve0
    swaps = client.get_logs(from_block=block - 500, to_block=block,
                            address=DEPTH_PAIR, topics=[SWAP_V2])
    if not swaps:
        raise CaseRunRefused(
            "pool {} served no swap in the 500 blocks before {}; a MAJOR-tier pool that quiet is "
            "not the pool this run says it is.".format(DEPTH_PAIR, block)
        )
    last = max(int(log["blockNumber"], 16) for log in swaps)
    header = block_header(client, last)
    state = PoolState(
        address=DEPTH_PAIR,
        asset=USDT,
        quote=WETH,
        asset_reserve_raw=asset_reserve,
        quote_reserve_raw=quote_reserve,
        last_swap_block=last,
        last_swap_timestamp=header.timestamp,
        fee_bps=30,
    )
    weth_usd, _answer, decimals = prices[WETH]
    quote = QuoteAsset(address=WETH, decimals=decimals,
                       usd_price=calc(weth_usd) * (Decimal(10) ** decimals))
    return PricedPool(state=state, quote=quote), state


def erc20_balance_of(client, token, holder, block):
    """``balanceOf(holder)`` on ``token`` at a height. Raw units, int."""
    data = BALANCE_OF + "0" * 24 + holder.lower().replace("0x", "")
    return uint(call_contract(client, token, data, block), 0)


def read_v3_pool(client, prices, block=HORIZON_BLOCK):
    """USDC/WETH 5bp at the horizon, as the one real concentrated pool state in this repository.

    Returns ``(PoolState, liquidity, sqrt_price_x96, fee)``.

    **Both readings of the pool are filled, and that is the point.** A concentrated pool has two
    independent depth readings at one block — the token balances it actually holds, and
    ``L``/``sqrt(P)`` in the active band — and :func:`depth.measure_depth` will not price one
    without the other: it bounds their ratio against the measured 5-23x TVL-understatement band
    and quarantines a state outside it. An earlier shape of this function left both reserve fields
    at zero, reasoning that a zero reserve is what sends
    :func:`marking.liquidity.effective_reserves` down its virtual-reserves branch. It does — and
    that is exactly the state ``depth`` refuses by name as a drained pool carrying a stale
    liquidity snapshot. Handing the same fabricated state to both modules would have measured the
    fabrication rather than the pool, so the balances are read.

    ``marking``'s branch is still exercised on this pool, deliberately and separately, by
    :func:`report_depth` — which asks ``effective_reserves`` for the virtual pair and prints it
    beside the real one.
    """
    liquidity = uint(call_contract(client, V3_POOL, V3_LIQUIDITY, block), 0)
    sqrt_price = uint(call_contract(client, V3_POOL, V3_SLOT0, block), 0)
    fee = uint(call_contract(client, V3_POOL, V3_FEE, block), 0)
    side0 = address_of(call_contract(client, V3_POOL, TOKEN0, block))
    if side0 != USDC:
        raise CaseRunRefused(
            "v3 pool {} has token0={}; this run reads it as USDC/WETH.".format(V3_POOL, side0)
        )
    asset_reserve = erc20_balance_of(client, USDC, V3_POOL, block)
    quote_reserve = erc20_balance_of(client, WETH, V3_POOL, block)
    state = PoolState(
        address=V3_POOL,
        asset=USDC,
        quote=WETH,
        asset_reserve_raw=asset_reserve,
        quote_reserve_raw=quote_reserve,
        active_liquidity=liquidity,
        # sqrt_price_x96 in this seam is sqrt(quote raw per asset raw) — the pool's own
        # (asset, quote) orientation, which for USDC=token0 is what slot0 reports unchanged.
        sqrt_price_x96=sqrt_price,
        last_swap_block=block,
        last_swap_timestamp=0,
        fee_bps=fee // 100,
    )
    return state, liquidity, sqrt_price, fee


# -- the report ------------------------------------------------------------------


def _thousands(value):
    return "{:,}".format(value)


def _usd(value):
    return "${:,.2f}".format(value)


#: Any 0x-hex run of four or more digits, so a quarantine reason can be counted as a class rather
#: than once per transaction. Deliberately not a parse of the message: the queue's reasons are
#: prose written at each refusal site, and a report that depended on their shape would go quiet the
#: first time one was reworded.
HEXISH = re.compile(r"0x[0-9a-fA-F]{4,}")


def _reason_class(reason):
    """A quarantine reason with its identifiers blanked, for counting. Never for display alone."""
    return HEXISH.sub("0x…", reason.split(";")[0])


def report_case(client, name, wallet, result, items, unestablished, rows, population,
                pools, prices):
    """Everything this run published for one wallet, and every row that did not reach a number."""
    from pipeline import Stage

    print("\n" + "=" * 78)
    print("case {}  —  {}".format(name, wallet))
    print("=" * 78)
    total, doors, ok = conservation(result, population)
    stages = result.stages
    census = result.census

    print("population   {} transactions from the explorer listing".format(total))
    print("stages run   {}".format(" -> ".join(stage.value for stage in result.stages_run)))
    print("census       total {}  undecodable {}".format(census.total, census.undecodable))
    for status, count in sorted(census.counts.items(), key=lambda kv: kv[0].value):
        if count:
            print("             {:<22} {}".format(status.value, count))
    print("conserved    {} = netted {} + netting-queue {} + ingestion-queue {}   [{}]".format(
        total, doors[0], doors[1], doors[2], "OK" if ok else "REFUSED"))
    print("stages       in {}  undecodable {}  attributions usable {}/{}  netted {}".format(
        stages.transactions_in, stages.transactions_undecodable, stages.attributions_usable,
        stages.attributions_resolved, stages.netted))
    print("             buys {}  sells {}  books {}  consumptions {}".format(
        stages.buys, stages.sells, stages.fifo_books, stages.consumptions))
    print("             positions marked {}  buys scored {}  quarantined {}  deferred {}".format(
        stages.open_positions_marked, stages.buys_scored, stages.buys_quarantined,
        stages.buys_outside_window))
    print("             wallets seen {}  scored {}  unscorable {}".format(
        stages.wallets_seen, stages.wallets_scored, stages.wallets_unscorable))

    contracts = sum(1 for _address, has_code, _role in rows if has_code)
    print("§6.2 typing  {} addresses on transfer legs: {} EOA by eth_getCode, {} with code "
          "({} stated)".format(len(rows), len(rows) - contracts, contracts,
                               sum(1 for _a, _c, role in rows if role.startswith("§6.2"))))
    if unestablished:
        print("native ETH   {} transaction(s) whose wrap/unwrap settlement could not be "
              "established".format(len(unestablished)))
        for row in unestablished:
            print("             {} block {} legs {} — {}".format(
                row.tx_hash[:18], row.block, list(row.legs), row.reason[:96]))

    for outcome in result.wallets:
        print("\nwallet outcome {}".format(outcome.wallet))
        print("   buys {} (quarantined {})  sells {} (quarantined {})".format(
            outcome.n_buys, outcome.n_buys_quarantined, outcome.n_sells,
            outcome.n_sells_quarantined))
        if outcome.quality is None:
            print("   unscorable: {}".format(outcome.unscorable_reason))
        else:
            quality = outcome.quality
            print("   buy_quality_30d {} over {} buy(s)".format(quality.value, quality.n_buys))
            print("   §10 mix: realized {}  marked {}  dead {}".format(
                quality.realized_share, quality.marked_share, quality.dead_share))
            for bucket, weight in sorted(quality.bucket_weights.items(),
                                         key=lambda kv: kv[0].value):
                print("   bucket {} weight {} value {}".format(
                    bucket.value, weight, quality.bucket_values.get(bucket)))
        for account in outcome.accounts:
            print("   buy {} {} at block {}".format(
                account.buy.tx_hash[:18], account.buy.asset, account.buy.block_number))
            print("       cost {}  return {}  realized {}  marked {}  dead {}".format(
                _usd(account.cost_usd), account.return_pct, _usd(account.realized_proceeds_usd),
                _usd(account.marked_usd), _usd(account.dead_usd)))
            print("       bucket {}  horizon lag {}s  bought {} raw  open {} raw".format(
                account.bucket.value, account.horizon_lag_seconds,
                account.buy.asset_raw_amount, account.open_raw))
            if account.position is not None:
                position = account.position
                print("       mark {} / {} / {}".format(
                    position.value_usd, position.value_basis.name, position.pool_status.name))
                for line in position.evidence:
                    print("           {}".format(line))

    queue = result.quarantine
    by_stage = collections.Counter()
    for record in queue.records:
        by_stage[record.stage] += 1
    if queue.records:
        print("\nquarantine   {} record(s): {}".format(
            len(queue.records),
            ", ".join("{} {}".format(count, stage.value)
                      for stage, count in sorted(by_stage.items(), key=lambda kv: kv[0].value))))
        # Reason *classes*, per stage. Two things had to change before this line was readable.
        # The ranking was over all stages at once, and the ingestion queue is one class repeated
        # once per hash, so a top-eight was eight ingestion rows and nothing else — the marking and
        # FIFO reasons, which are what this run exists to look at, fell off the bottom unread. And
        # every reason names its own transaction, so counting raw strings counts one of each: 51
        # marking records on wallet_b are 51 "distinct" reasons and one actual class. Hex runs are
        # replaced before counting, and the count is what says how big the class is.
        for stage in sorted(by_stage, key=lambda s: s.value):
            classes = collections.Counter()
            for record in queue.by_stage(stage):
                classes[_reason_class(record.reason)] += 1
            for reason, count in sorted(classes.items(), key=lambda kv: (-kv[1], kv[0]))[:6]:
                print("   {:>4}x {:<10} {}".format(count, stage.value, reason[:104]))
            if len(classes) > 6:
                print("        {:<10} ... and {} further class(es)".format("", len(classes) - 6))
    report_liquidity_double_count(result, pools, prices)
    unread = report_asset_conservation(client, wallet, result)
    coverage = result.coverage
    print("\ncoverage     {} transactions priced, {} unpriced".format(
        coverage.transactions_priced, coverage.transactions_unpriced))
    print("             notional {} total / {} trades / {} quarantined / {} scored".format(
        coverage.notional_usd_total, coverage.notional_usd_trades,
        coverage.notional_usd_quarantined, coverage.notional_usd_scored))
    return ok


def report_asset_conservation(client, wallet, result):
    """The conservation check the census does not make: does anything unread touch a marked asset?

    ``run_wallet_window`` conserves over **transactions** — every row in equals netted plus the two
    queues, and this file re-derives that in :func:`conservation`. Nothing conserves over
    **assets**, and the two are not the same statement. A transaction ingestion could not read is
    counted, named and queued; what is *not* said anywhere is that one of those unread rows moved
    the very token a marked position is denominated in, so the mark is of a quantity the wallet may
    no longer have held.

    This is not hypothetical and it is not small. ``wallet_b``'s five-lot SBET sale sits in the
    ingestion queue — its receipt carries two WETH ``Withdrawal`` legs and the wallet's archive
    balance accounts for exactly one of them, so where the other 76,603,490,814,551,675 wei settled
    is not established and the whole receipt is refused. All five lots are therefore marked at
    their full purchased quantity. The wallet actually held 509,734,777,355,780,241,633 raw at the
    horizon against 5,851,509,734,777,355,780,241,633 marked: **0.0087%**. The published
    ``buy_quality_30d`` for that wallet has ``realized_share = 0`` and ``marked_share = 1``, and it
    is a score for a wallet that had sold almost everything.

    So this reads the **raw logs** of every ingestion-queue receipt — which the caller has, because
    the caller fetched them — and reports any ERC-20 ``Transfer`` on a marked asset with the wallet
    on either side. Raw logs and not decoded ones, deliberately: the receipt is in the queue
    precisely because it could not be decoded, and a check that needed it decoded would be silent
    exactly when it matters.

    What it guarantees: that an unread transfer of a marked asset involving this wallet is named.
    What it does not: that a mark with no such row is *correct*. A transfer settled by a mechanism
    that writes no ERC-20 ``Transfer`` at all — an internal call, an ERC-1155 leg, a rebasing
    balance — is invisible here as it is everywhere else in this repository.

    Returns the rows it printed, so a test can pin them.
    """
    from contracts import ValueBasis
    from ingest import TRANSFER
    from pipeline import Stage

    marked = {}
    for outcome in result.wallets:
        for account in outcome.accounts:
            if account.position is None or account.open_raw <= 0:
                continue
            if account.position.value_basis is ValueBasis.DEAD_ZEROED:
                continue
            marked.setdefault(normalise_asset(account.buy.asset), []).append(account)
    if not marked:
        return ()

    queued = sorted({tx for record in result.quarantine.by_stage(Stage.INGESTION)
                     for tx in record.tx_hashes})
    padded = "0x" + "0" * 24 + wallet.lower().replace("0x", "")

    unread = []
    for tx_hash in queued:
        receipt = require_receipt(client, tx_hash)
        for log in logs_of(receipt):
            topics = log.get("topics") or []
            if not topics or topics[0].lower() != TRANSFER or len(topics) != 3:
                continue
            asset = normalise_asset(log["address"])
            if asset not in marked:
                continue
            sides = [topic.lower() for topic in topics[1:3]]
            if padded not in sides:
                continue
            direction = "out of" if sides[0] == padded else "into"
            unread.append((tx_hash, asset, direction, int(log["data"], 16)))

    if not unread:
        return ()

    print("\nUNREAD MOVES  {} transfer(s) of a marked asset, in transactions ingestion could not "
          "read".format(len(unread)))
    for tx_hash, asset, direction, amount in unread:
        open_raw = sum(account.open_raw for account in marked[asset])
        print("             {} moved {} raw of {} {} the wallet".format(
            tx_hash[:18], amount, asset, direction))
        print("             against {} raw marked open across {} lot(s) — the mark stands on a "
              "quantity".format(open_raw, len(marked[asset])))
        print("             this run cannot confirm the wallet still held.")
    return tuple(unread)


def report_liquidity_double_count(result, pools, prices):
    """What the §4.4 liquidity bound cannot see: one wallet's lots share one pool.

    §4.4 Case 2 bounds each *buy's* remaining quantity by what the pool could absorb, and FIFO
    makes a buy a lot. A wallet holding four lots of one token therefore gets four marks, each
    computed as though its lot were the only thing being sold — while all four would in fact go
    down the same curve.

    This reprices, per wallet and token, the lots' **combined** remaining quantity as one sale,
    through the same :func:`marking.liquidity.exit_value_usd` and the same pool state the marks
    were taken against, and prints the gap. It **states** a limitation of the pre-registered
    metric; it does not correct one. §4.4 says "for each valid buy", and which quantity the bound
    applies to is a pre-registration question, not a defect — but the section's own justification
    for the bound ("a wallet holding $50,000 of a token whose pool has $2,000 of liquidity does
    not hold $50,000") is an argument about a *wallet*, and per-lot application is exactly where
    that argument stops being enforced.

    Nothing is printed where a wallet's open lots are one per token: there is no shared curve to
    double-count, which is the tracer bullet's case and every case in the suite.

    Skipped for a mark taken at a replacement venue, and for a dead-zeroed one. The first is not
    this venue's curve; the second is a zero and has no curve at all.
    """
    from contracts import ValueBasis
    from marking.liquidity import exit_value_usd

    for outcome in result.wallets:
        lots = collections.OrderedDict()
        for account in outcome.accounts:
            position = account.position
            if position is None or position.value_basis is ValueBasis.DEAD_ZEROED:
                continue
            if account.open_raw <= 0:
                continue
            evidence = [line for line in position.evidence]
            if "venue_is_replacement=true" in evidence:
                continue
            lots.setdefault(normalise_asset(account.buy.asset), []).append((account, position))

        for asset, rows in lots.items():
            if len(rows) < 2:
                continue
            pool = pools[asset]
            quote_usd = prices[normalise_asset(pool.quote)]
            combined_raw = sum(account.open_raw for account, _position in rows)
            separate = sum(position.value_usd for _account, position in rows)
            together = exit_value_usd(
                combined_raw, pool.asset_reserve_raw, pool.quote_reserve_raw,
                pool.fee_bps, quote_usd,
            )
            print("\nliquidity    {} open lots of {} at one venue {}".format(
                len(rows), asset, pool.address))
            print("             marked lot by lot {}".format(separate))
            print("             sold as one {} raw sale {}".format(combined_raw, together))
            print("             the §4.4 bound is applied per buy, so this wallet's marked value "
                  "is {}x".format(divide(separate, together)))
            print("             what that one sale down the same curve would realise.")


def report_token_starts(client, pools, price_book, window, horizon):
    """Derive §4.7 for every asset this window needs one for, and print what came back.

    Returns ``{token: TokenStartFinding}``. Two things are printed per token and both matter: the
    established ones with the pool the date came from, and the refused ones by *class*, because a
    refusal is what keeps a buy in the quarantine queue and a reader has to be able to see which
    limit is doing it.

    Nothing here reads a buy receipt, and that is the one temptation this function exists to avoid.
    Every one of these buys names the pool it settled through, so a start could be had for free by
    taking that pool's first swap — and §4.7 wants the *earliest* pool, so the observed one gives a
    later start, which makes the buy look earlier, which moves it towards bucket A. A wrong number
    in the direction that flatters.
    """
    print("\n" + "=" * 78)
    print("§4.7 — token trading starts, derived rather than supplied")
    print("=" * 78)
    tokens = tokens_needing_starts(client, pools, price_book, window, horizon)
    print("demand       {} asset(s) whose buys reach marking in this window".format(len(tokens)))
    before = client.replayed_count()
    findings = derive_token_starts(client, tokens, HORIZON_BLOCK)
    after = client.replayed_count()
    confirm_the_known_starts(findings)

    established = token_starts_of(findings)
    refusals = refusals_of(findings)
    print("derived      {} start(s), {} refusal(s), in {} RPC call(s) "
          "({} replayed, {} live)".format(
              len(established), len(refusals),
              (after[0] + after[1]) - (before[0] + before[1]),
              after[0] - before[0], after[1] - before[1]))
    print("             the two known answers reproduce: {} at {} and {} at {}".format(
        SBET, SBET_TRADING_START_BLOCK, DEAD_TOKEN, DEAD_TRADING_START_BLOCK))
    for token, start_at in sorted(established.items()):
        bucket = token_age_bucket(start_at.block, start_at.timestamp,
                                  start_at.block, start_at.timestamp)
        known = " (known)" if token in KNOWN_TOKEN_STARTS else ""
        print("§4.7 start   {} block {} ts {} pool {} (a buy in that block is bucket {}){}".format(
            token, start_at.block, start_at.timestamp, findings[token].pool, bucket.value, known))
    if refusals:
        classes = collections.Counter(reason.split(":")[0] for reason in refusals.values())
        print("§4.7 refused {} asset(s), no date filed for any of them:".format(len(refusals)))
        for name, count in sorted(classes.items(), key=lambda kv: (-kv[1], kv[0])):
            print("   {:>4}x {}".format(count, name))
        for token, reason in sorted(refusals.items()):
            print("             {} {}".format(token, reason.split(":")[0]))
    return findings


def report_depth(client, prices):
    """§4.5 on a real pool, and the one real concentrated pool state in this repository."""
    print("\n" + "=" * 78)
    print("depth — §4.5 on real reserves")
    print("=" * 78)
    priced, state = read_depth_pool(client, prices)
    print("pool         {} USDT/WETH v2".format(state.address))
    print("             reserves {} raw USDT / {} raw WETH at block {}".format(
        _thousands(state.asset_reserve_raw), _thousands(state.quote_reserve_raw), HORIZON_BLOCK))
    measured = measure_depth(priced)
    print("depth        model {}  quote reserve {} raw -> {} USD".format(
        measured.model.value, _thousands(measured.quote_reserve_raw),
        measured.quote_reserve_usd))
    print("             effective depth {}  S1 {}".format(
        measured.effective_depth_usd, measured.s1_usd))
    print("             validity band max {}  ({})".format(
        measured.validity_band.max_size_usd, measured.validity_band.reason))
    print("             tvl understatement {}".format(measured.tvl_understatement_factor))
    detail = size_to_cost_cap_detail(
        pool=priced, tier=DEPTH_TIER, strategy_aum=calc(DEPTH_AUM_USD),
        leader_clip=calc(DEPTH_LEADER_CLIP_USD), gas_usd=calc(DEPTH_GAS_USD),
    )
    print("sizing       tier {}  cap {}  aum ${}  leader clip ${}  gas ${}".format(
        detail.tier.value, detail.cost_cap, DEPTH_AUM_USD, DEPTH_LEADER_CLIP_USD, DEPTH_GAS_USD))
    print("             order {}  binding constraint {}  copyable {}".format(
        detail.order_usd, detail.binding_constraint, detail.copyable))
    if detail.rejection_reason:
        print("             rejected: {}".format(detail.rejection_reason))
    costs = detail.costs
    print("             total priced cost {}  = fee {} + gas {} + own impact {} + copier {}".format(
        costs.total_priced_cost_pct, costs.dex_fee_pct, costs.gas_pct,
        costs.price_impact_pct, costs.copier_penalty_pct))
    print("             liquidity limitation {}  capital absorption {}".format(
        costs.liquidity_limitation_pct, detail.capital_absorption))
    print("             pool depth at trade {}  S1 at trade {}".format(
        detail.pool_depth_at_trade_usd, detail.s1_at_trade_usd))

    state3, liquidity, sqrt_price, fee = read_v3_pool(client, prices)
    from marking.liquidity import effective_reserves

    virtual_asset, virtual_quote, model = effective_reserves(state3)
    print("\nv3 pool      {} USDC/WETH".format(state3.address))
    print("             liquidity {}  sqrtPriceX96 {}  fee {} ({} bps)".format(
        _thousands(liquidity), _thousands(sqrt_price), fee, state3.fee_bps))
    print("             {} -> virtual reserves {} raw USDC / {} raw WETH".format(
        model, _thousands(virtual_asset), _thousands(virtual_quote)))
    usdc_usd, _answer3, usdc_decimals = prices[USDC]
    priced3 = PricedPool(
        state=state3,
        quote=QuoteAsset(address=WETH, decimals=prices[WETH][2],
                         usd_price=calc(prices[WETH][0]) * (Decimal(10) ** prices[WETH][2])),
    )
    measured3 = measure_depth(priced3)
    print("             model {}  effective depth {}  S1 {}".format(
        measured3.model.value, measured3.effective_depth_usd, measured3.s1_usd))
    print("             validity band max {}  max own slippage {}".format(
        measured3.validity_band.max_size_usd, measured3.validity_band.max_own_slippage))
    print("             tvl understatement {}  (quote reserve {} raw / virtual {} raw)".format(
        measured3.tvl_understatement_factor, _thousands(measured3.quote_reserve_raw),
        _thousands(measured3.virtual_quote_reserve_raw or 0)))
    del usdc_usd, usdc_decimals
    return detail, state3, measured, measured3


def run(client):
    """Every case, in order, and then §4.5. Returns the results so a test can pin them."""
    print("case runs — four real populations through pipeline.run_wallet_window")
    print("=" * 78)

    before, start, end, after = confirm_window_edges(client)
    window = window_from_blocks(client, WINDOW_INDEX, WINDOW_START_BLOCK, WINDOW_END_BLOCK)
    horizon = block_header(client, HORIZON_BLOCK)
    print("window       blocks {}..{}  ts {}..{}".format(
        window.start_block, window.end_block, window.start_ts, window.end_ts))
    print("             edges: {} ts {} < 2023-02-01 <= {} ts {}".format(
        before.number, before.timestamp, start.number, start.timestamp))
    print("             edges: {} ts {} < 2023-03-01 <= {} ts {}".format(
        end.number, end.timestamp, after.number, after.timestamp))
    print("horizon      block {} ts {} (+{}s past the window end)".format(
        horizon.number, horizon.timestamp, horizon.timestamp - window.end_ts))

    prices = read_prices(client)
    for asset, (usd, answer, decimals) in sorted(prices.items()):
        print("price        {} {} raw answer, {} decimals -> {} USD per raw unit".format(
            asset, answer, decimals, usd))
    price_book = {asset: usd for asset, (usd, _answer, _decimals) in prices.items()}

    pools = confirm_venues(client)
    findings = report_token_starts(client, pools, price_book, window, horizon)
    starts = token_starts_of(findings)
    config = WindowConfig(
        horizon_block=horizon.number, horizon_ts=horizon.timestamp, token_starts=starts
    )

    # -- §4.4 Case 2: a pool for every open position, read rather than supplied ----
    print()
    print("=" * 78)
    print("§4.4 Case 2 — pools for open positions, read rather than supplied")
    print("=" * 78)
    wanted = assets_needing_pools(client, pools, price_book, window, config)
    print("demand       {} asset(s) left open with no pool supplied".format(len(wanted)))
    readings, refused = derive_open_position_pools(client, wanted, price_book)
    print("read         {} pool(s), {} refusal(s)".format(len(readings), len(refused)))
    for asset, reading in sorted(readings.items()):
        st = reading.state
        print("pool         {} -> {} quoted in {}".format(asset, st.address, st.quote))
        print("             reserves {:,} raw asset / {:,} raw quote at block {}".format(
            st.asset_reserve_raw, st.quote_reserve_raw, reading.block))
    for asset, reasons in sorted(refused.items()):
        print("refused      {} — {}".format(asset, "; ".join(reasons) or "no quote tried"))
    pools = dict(pools)
    pools.update({a: r.state for a, r in readings.items()})

    results = {}
    conserved = True
    for name, wallet, filename in CASES:
        listed_wallet, population, document = load_population(filename)
        if listed_wallet != wallet:
            raise CaseRunRefused(
                "{} is the population of {}, and this case runs {}.".format(
                    filename, listed_wallet, wallet
                )
            )
        result, items, unestablished, rows = run_case(
            client, wallet, population, pools, price_book, window, config
        )
        results[name] = (result, items, unestablished, rows, population, document)
        conserved &= report_case(client, name, wallet, result, items, unestablished, rows,
                                 population, pools, price_book)

    # ``prices``, not ``price_book``: :func:`read_depth_pool` needs the quote asset's *decimals*
    # to build a :class:`depth.QuoteAsset`, and ``price_book`` is the pipeline's seam — one scalar
    # per asset, decimals already divided out. Passing the seam's shape here raised
    # ``TypeError: cannot unpack non-iterable decimal.Decimal object`` and took the whole §4.5
    # section down after the four cases had already printed, so a run that had crashed still
    # looked like a run that had finished.
    depth_detail, v3_state, v2_depth, v3_depth = report_depth(client, prices)

    replayed, live = client.replayed_count()
    print("\n" + "=" * 78)
    print("census conserves on all four cases: {}".format("yes" if conserved else "NO"))
    print("calls: {} replayed, {} live".format(replayed, live))
    return results, depth_detail, v3_state, v2_depth, v3_depth


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", action="store_true",
                        help="open sockets and record any call the snapshot does not hold")
    parser.add_argument("--record-population", action="store_true",
                        help="re-fetch the four account listings from the block explorer")
    args = parser.parse_args(argv)
    if args.record_population:
        record_populations()
        return 0
    run(build_client(record=args.record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
