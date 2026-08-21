"""A deterministic synthetic chain: transactions, pools and prices the pipeline will accept.

What this is for
----------------

The pipeline has never run end to end, because there is no data: ticket 03 (an authenticated
archival node) is unmet and so are the other three §15.4 preconditions. Unit tests reach every
module and reach *between* none of them, so the defects that live in the joins — a key space that
normalises on one side and not the other, a census that stops reconciling, a status that never
occurs in a fixture — cannot be found. This generator produces input that satisfies the existing
contracts in ``pipeline.inputs`` exactly, so the whole machine executes and those joins are
exercised today.

What it is not for
------------------

**It is not tuned so the answer looks good, and it must never be.** The pool curve is walked
honestly: a wallet that buys a thousand times into one pool moves the price it is later marked
against, a wallet holding a rugged token is zeroed, a wallet that bought late is flat after fees.
Whatever falls out is the answer for this seed. If a generated wallet scores terribly that is a
result about the fixture, not a bug in it, and adjusting the fixture to improve it would be
building the exact instrument this repository exists to prevent.

**Nothing here interprets a chain byte, and it is not in the lane graph.** It does not decode a
log, filter a transfer, detect an endpoint, match a lot or price an exit — it *constructs* inputs
whose shapes ``contracts`` already names, and hands them to the builder lane through the same
public entry point a real reader would use. That is why it lives under ``tools/`` and not under
``src/``: ``tests/test_lane_independence.py`` classifies every package under ``src/`` into a lane,
and a synthetic source is neither a builder nor a validator — it is a fixture, and a fixture that
appeared in the lane graph would be a fixture the metric could import.

Determinism
-----------

Same seed, byte-identical output. Every varying quantity comes from
:mod:`tools.mockchain.seeds`, which is HMAC over the caller's seed; there is no ``random`` import,
no clock, no ``os.urandom``, and no dependence on dict iteration order — the transaction stream is
built from an explicitly ordered plan and then executed in **block order**, so the pool curve sees
events in the order the chain would have.

Provenance
----------

Every wallet, token, pool and transaction hash is minted by
:mod:`tools.mockchain.provenance`, so it begins ``0xsynthetic-`` and cannot be read as a mainnet
address. The four §4.6 quote assets are the necessary exception and are the only one; see that
module for why, and for what the marker does and does not guarantee.

What is generated, and which path each case exists to reach
-----------------------------------------------------------

============================  ====================================================================
``band-low``                  exactly 20 valid buys — §6's lower selection edge
``band-high``                 exactly 1,000 valid buys — §6's upper edge, and the wallet whose own
                              flow moves the pool it is later marked against
``partial-seller``            six buys and three sells sized to cut *across* lots, so FIFO
                              produces multi-lot consumptions and partially consumed lots; one
                              sell and one buy land in the §4.8 measurement tail, so the tail sell
                              matches and the tail buy is deferred rather than scored
``dormant``                   three buys early in the window and nothing after — `Reduced
                              Activity` in §10's churn block
``one-trade``                 a single buy
``dead-pool``                 holds a token whose pool satisfies all three §9.1 conditions at the
                              horizon: no swap for 30 days, exit below $1, no replacement. The
                              position is ``DEAD_ZEROED`` and lands in §10's dead share
``migrated``                  holds a token whose liquidity moved: the primary is quiet and drained,
                              a validated replacement in the *same* quote asset is live, so the
                              exit is walked at the replacement (``PoolStatus.MIGRATED``)
``eth-route``                 pays in native ETH and takes a WETH refund in the same transaction —
                              two legs that are one asset only after §4.2's collapse. Without the
                              collapse this nets to three surviving legs and classifies
                              ``NO_CLEAR_ENDPOINT``
``fresh-token``               four buys of a token whose §4.7 trading start is *inside* the window,
                              placed to land one buy in each of buckets A, B, C and D
``silent``                    selected, but with no transaction at all — `Inactive` in the churn
                              block and absent from the basket, which is the survivorship gap
                              ``reporting.run`` exists to make visible
============================  ====================================================================

The dead pool's and the migrated primary's reserves at the horizon are **not** the state the
trades left behind, and that is the point rather than an inconsistency: a rug pull and a migration
are precisely the events that move reserves after the trading is over. The trades are priced on
the pool as it was; the horizon snapshot is the pool as it ended.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional, Tuple

from contracts import NATIVE_ETH, PoolState, Transfer, USDC, WETH, calc

from attribution import AttributionContext

from pipeline import ObservedTransaction, TokenStart, Window, WindowConfig

from .provenance import snapshot_id, synthetic_address, synthetic_tx_hash
from .seeds import draw_between

# -- the clock and the calendar -------------------------------------------------
#
# Blocks and seconds are paired by one constant, and every timestamp in the run is derived from a
# block through :func:`timestamp_of`. The seam pairs a stamp with a block everywhere; deriving one
# from the other here is what keeps the pairing consistent across ten thousand transactions
# without anyone maintaining two lists.

BLOCK_SECONDS = 12

WINDOW_INDEX = 1
WINDOW_START_BLOCK = 18_000_000
WINDOW_START_TS = 1_700_000_000

#: 90 days of window (§6.3 walk-forward), in blocks.
WINDOW_BLOCKS = 90 * 24 * 60 * 60 // BLOCK_SECONDS

#: 30 days of §4.8 measurement tail past the window end, in blocks. ``run_wallet_window`` refuses
#: a horizon short of this, so it is the minimum rather than a choice.
TAIL_BLOCKS = 30 * 24 * 60 * 60 // BLOCK_SECONDS

DAY_SECONDS = 24 * 60 * 60


def timestamp_of(block):
    """The UTC second paired with ``block``. One constant block time, applied everywhere."""
    return WINDOW_START_TS + (block - WINDOW_START_BLOCK) * BLOCK_SECONDS


WINDOW_END_BLOCK = WINDOW_START_BLOCK + WINDOW_BLOCKS
HORIZON_BLOCK = WINDOW_END_BLOCK + TAIL_BLOCKS
HORIZON_TS = timestamp_of(HORIZON_BLOCK)


# -- prices ---------------------------------------------------------------------
#
# USD per **raw** unit, which is what ``marking.mark_position`` multiplies a raw reserve by. No
# type in ``contracts`` carries token decimals, so the price book is the only place the scale is
# expressed and it is expressed here once: WETH at 18 decimals and $3,000, USDC at 6 decimals and
# $1. The native-ETH sentinel is deliberately absent — §4.2 makes it and WETH one asset, so a
# second row for it is what ``pipeline.inputs.asset_keyed`` refuses as two keys naming one asset.

WETH_DECIMALS = 18
USDC_DECIMALS = 6

WETH_USD = calc("3000")
USDC_USD = calc("1")

PRICES = {
    WETH: calc("0.000000000000003"),   # $3,000 / 1e18 raw
    USDC: calc("0.000001"),            # $1 / 1e6 raw
}


# -- identifiers ----------------------------------------------------------------

TOKEN_ALPHA = synthetic_address("token-alpha")
TOKEN_BRAVO = synthetic_address("token-bravo")
TOKEN_DEAD = synthetic_address("token-dead")
TOKEN_MIGRATED = synthetic_address("token-migrated")
TOKEN_FRESH = synthetic_address("token-fresh")

POOL_ALPHA = synthetic_address("pool-alpha")
POOL_BRAVO = synthetic_address("pool-bravo")
POOL_DEAD = synthetic_address("pool-dead")
POOL_MIGRATED = synthetic_address("pool-migrated-primary")
POOL_MIGRATED_NEW = synthetic_address("pool-migrated-replacement")
POOL_FRESH = synthetic_address("pool-fresh")

#: A router the ``eth-route`` wallet's ETH passes through. §6.2 excludes routers from the candidate
#: universe entirely, so it is typed as infrastructure and can never become a portfolio owner.
ROUTER = synthetic_address("router-aggregator")

#: Takes the referral fee on ``band-low``'s buys. Its legs are ``is_fee=True`` and netting drops
#: them at step 4 — a fee is not an endpoint, and a fee collector is not a trader.
FEE_COLLECTOR = synthetic_address("fee-collector")

WALLET_BAND_LOW = synthetic_address("wallet-band-low")
WALLET_BAND_HIGH = synthetic_address("wallet-band-high")
WALLET_PARTIAL = synthetic_address("wallet-partial-seller")
WALLET_DORMANT = synthetic_address("wallet-dormant")
WALLET_ONE_TRADE = synthetic_address("wallet-one-trade")
WALLET_DEAD_POOL = synthetic_address("wallet-dead-pool")
WALLET_MIGRATED = synthetic_address("wallet-migrated")
WALLET_ETH_ROUTE = synthetic_address("wallet-eth-route")
WALLET_FRESH = synthetic_address("wallet-fresh-token")
WALLET_SILENT = synthetic_address("wallet-silent")

#: Every address §6.2 excludes from the candidate universe. Shared by every transaction's context.
INFRASTRUCTURE = frozenset({
    POOL_ALPHA, POOL_BRAVO, POOL_DEAD, POOL_MIGRATED, POOL_MIGRATED_NEW, POOL_FRESH,
    ROUTER, FEE_COLLECTOR,
})

#: Selected wallets, in the order every deterministic aggregation over them runs in. Not a set:
#: §9.2 requires the published number to be reproducible, and a total accumulated in set order is
#: not.
SELECTED_WALLETS = (
    WALLET_BAND_HIGH,
    WALLET_BAND_LOW,
    WALLET_DEAD_POOL,
    WALLET_DORMANT,
    WALLET_ETH_ROUTE,
    WALLET_FRESH,
    WALLET_MIGRATED,
    WALLET_ONE_TRADE,
    WALLET_PARTIAL,
    WALLET_SILENT,
)


# -- the pool curve -------------------------------------------------------------


class _Curve(object):
    """A constant-product pool the generated trades are actually walked along.

    Integer arithmetic throughout: reserves and trade legs are raw token quantities and the seam
    rule is that those are ``int`` and nothing else. The fee is taken on the way in, which is
    where a v2-style pool takes it, so the fee stays in the pool and the invariant grows.

    This exists so that the generated trades and the generated pool states are *consistent with
    each other*. A fixture whose quantities were drawn independently of its reserves would make
    ``marking`` price exits that the trades could never have happened at, and every integration
    defect found against it would be a defect about an impossible pool.
    """

    __slots__ = ("asset_raw", "quote_raw", "fee_bps")

    def __init__(self, asset_raw, quote_raw, fee_bps=30):
        self.asset_raw = asset_raw
        self.quote_raw = quote_raw
        self.fee_bps = fee_bps

    def buy(self, spend_quote_raw):
        """Spend ``spend_quote_raw`` of the quote asset; return the raw asset quantity out."""
        effective = spend_quote_raw * (10_000 - self.fee_bps) // 10_000
        invariant = self.asset_raw * self.quote_raw
        new_asset = invariant // (self.quote_raw + effective)
        out = self.asset_raw - new_asset
        if out <= 0:
            raise ValueError(
                "a buy of {} raw quote units out of a pool holding {} produced no asset; the "
                "generator sized a trade the pool cannot serve".format(
                    spend_quote_raw, self.quote_raw
                )
            )
        self.asset_raw -= out
        self.quote_raw += spend_quote_raw
        return out

    def sell(self, send_asset_raw):
        """Send ``send_asset_raw`` of the asset; return the raw quote quantity out."""
        effective = send_asset_raw * (10_000 - self.fee_bps) // 10_000
        invariant = self.asset_raw * self.quote_raw
        new_quote = invariant // (self.asset_raw + effective)
        out = self.quote_raw - new_quote
        if out <= 0:
            raise ValueError(
                "a sell of {} raw asset units into a pool holding {} produced no quote; the "
                "generator sized a trade the pool cannot serve".format(
                    send_asset_raw, self.quote_raw
                )
            )
        self.asset_raw += send_asset_raw
        self.quote_raw -= out
        return out


# -- the token table ------------------------------------------------------------


@dataclass(frozen=True)
class _Token:
    """One generated token: which pool it trades in, and what its pool looks like at the horizon.

    ``horizon_override`` is how a rug and a migration are expressed. For a live token it is
    ``None`` and the horizon snapshot is whatever the trades left behind. For ``token-dead`` and
    ``token-migrated`` the reserves at the horizon are *not* the post-trade state, because the
    event those tokens exist to model happens after the trading stops.
    """

    address: str
    pool_address: str
    quote: str
    start_asset_raw: int
    start_quote_raw: int
    #: Seconds of silence at the horizon. ``marking.pools.DEAD_INACTIVITY_SECONDS`` is 30 days and
    #: the comparison is ``>=``, so anything at or above that is §9.1 condition 1.
    horizon_silence_seconds: int
    horizon_override: Optional[Tuple[int, int]] = None


TOKENS = (
    _Token(
        address=TOKEN_ALPHA, pool_address=POOL_ALPHA, quote=WETH,
        start_asset_raw=5_000_000 * 10 ** 18, start_quote_raw=1_000 * 10 ** 18,
        horizon_silence_seconds=20 * 60,
    ),
    _Token(
        address=TOKEN_BRAVO, pool_address=POOL_BRAVO, quote=USDC,
        start_asset_raw=100_000_000 * 10 ** 18, start_quote_raw=10_000_000 * 10 ** 6,
        horizon_silence_seconds=20 * 60,
    ),
    _Token(
        # Rugged. The horizon reserves hold 9M tokens against 30,000 wei of WETH, so every exit
        # prices below ``marking.pools.MINIMUM_EXIT_VALUE_USD`` — §9.1 condition 2 — while the
        # trades themselves happened on a pool that was alive.
        address=TOKEN_DEAD, pool_address=POOL_DEAD, quote=WETH,
        start_asset_raw=8_000_000 * 10 ** 18, start_quote_raw=400 * 10 ** 18,
        horizon_silence_seconds=35 * DAY_SECONDS,
        horizon_override=(9_000_000 * 10 ** 18, 30_000),
    ),
    _Token(
        # Migrated. The primary is quiet and drained; the replacement below is live, holds the same
        # token, and is quoted in the same asset — which is what ``marking.pools`` requires before
        # it will follow a migration rather than refuse it.
        address=TOKEN_MIGRATED, pool_address=POOL_MIGRATED, quote=WETH,
        start_asset_raw=4_000_000 * 10 ** 18, start_quote_raw=800 * 10 ** 18,
        horizon_silence_seconds=33 * DAY_SECONDS,
        horizon_override=(4_500_000 * 10 ** 18, 2 * 10 ** 18),
    ),
    _Token(
        address=TOKEN_FRESH, pool_address=POOL_FRESH, quote=WETH,
        start_asset_raw=2_000_000 * 10 ** 18, start_quote_raw=300 * 10 ** 18,
        horizon_silence_seconds=20 * 60,
    ),
)

TOKENS_BY_ADDRESS = {token.address: token for token in TOKENS}

#: §4.7 trading starts. Four tokens started long before the window, so every buy of them is bucket
#: D; ``token-fresh`` starts *inside* it, which is what puts a buy in buckets A, B and C.
TOKEN_START_BLOCKS = {
    TOKEN_ALPHA: WINDOW_START_BLOCK - 1_000_000,
    TOKEN_BRAVO: WINDOW_START_BLOCK - 1_500_000,
    TOKEN_DEAD: WINDOW_START_BLOCK - 900_000,
    TOKEN_MIGRATED: WINDOW_START_BLOCK - 2_000_000,
    TOKEN_FRESH: WINDOW_START_BLOCK + 100_000,
}


# -- the event plan -------------------------------------------------------------
#
# Blocks are allocated explicitly rather than drawn, because two events sharing a block inside one
# lot book is a ``QuarantineRequired`` from ``fifo._require_a_total_order`` — the seam carries no
# transaction index, so FIFO refuses to guess an order. :func:`_plan` asserts global uniqueness
# rather than relying on the arithmetic staying disjoint.

_BUY = "buy"
_SELL = "sell"
_ETH_BUY = "eth_buy"


@dataclass(frozen=True)
class _Event:
    block: int
    kind: str
    wallet: str
    token: str
    #: Raw quote units to spend, for a buy.
    spend_quote_raw: int = 0
    #: ``(numerator, denominator)`` of the wallet's current holding, for a sell. A fraction rather
    #: than a quantity because the holding is only known once the curve has been walked, and a
    #: fixed quantity would either exceed the position or stop crossing lots when the seed changes.
    sell_fraction: Tuple[int, int] = (0, 1)
    #: Whether the buy carries a referral fee leg. Netting drops it at step 4.
    with_fee: bool = False


def _weth_spend(seed, label, index):
    """0.05 to 1.5 WETH — $150 to $4,500 at the price book above."""
    return draw_between(seed, label, 5 * 10 ** 16, 15 * 10 ** 17, index)


def _usdc_spend(seed, label, index):
    """$200 to $5,000."""
    return draw_between(seed, label, 200 * 10 ** 6, 5_000 * 10 ** 6, index)


def _plan(seed):
    """Every event, in block order, for one seed."""
    events = []

    # band-low: exactly 20 valid buys, the lower edge of §6's 20-1,000 band. Carries the fee legs.
    for i in range(20):
        events.append(_Event(
            block=WINDOW_START_BLOCK + 1_000 + i * 307,
            kind=_BUY, wallet=WALLET_BAND_LOW, token=TOKEN_ALPHA,
            spend_quote_raw=_weth_spend(seed, "band-low/spend", i),
            with_fee=True,
        ))

    # dormant: three buys in the first two hours of the window, then silence.
    for i in range(3):
        events.append(_Event(
            block=WINDOW_START_BLOCK + 500 + i * 97,
            kind=_BUY, wallet=WALLET_DORMANT, token=TOKEN_ALPHA,
            spend_quote_raw=_weth_spend(seed, "dormant/spend", i),
        ))

    # fresh-token: one buy in each §4.7 bucket. The offsets are the bucket boundaries, not drawn:
    # block age < 10 is A, then time age < 1h is B, < 24h is C, and beyond is D.
    for i, offset in enumerate((3, 60, 700, 40_000)):
        events.append(_Event(
            block=TOKEN_START_BLOCKS[TOKEN_FRESH] + offset,
            kind=_BUY, wallet=WALLET_FRESH, token=TOKEN_FRESH,
            spend_quote_raw=_weth_spend(seed, "fresh/spend", i),
        ))

    # band-high: exactly 1,000 valid buys, the upper edge of the band — and enough of one pool's
    # own flow that the price it is later marked against is a price it moved.
    for i in range(1_000):
        events.append(_Event(
            block=WINDOW_START_BLOCK + 200_000 + i * 401,
            kind=_BUY, wallet=WALLET_BAND_HIGH, token=TOKEN_BRAVO,
            spend_quote_raw=_usdc_spend(seed, "band-high/spend", i),
        ))

    # partial-seller: buys and sells interleaved so a sell closes one lot and opens into the next.
    partial_kinds = (_BUY, _BUY, _SELL, _BUY, _BUY, _SELL, _BUY, _BUY)
    partial_fractions = {2: (3, 4), 5: (1, 2)}
    for i, kind in enumerate(partial_kinds):
        events.append(_Event(
            block=WINDOW_START_BLOCK + 610_000 + i * 911,
            kind=kind, wallet=WALLET_PARTIAL, token=TOKEN_ALPHA,
            spend_quote_raw=(
                _weth_spend(seed, "partial/spend", i) if kind == _BUY else 0
            ),
            sell_fraction=partial_fractions.get(i, (0, 1)),
        ))

    events.append(_Event(
        block=WINDOW_START_BLOCK + 620_000,
        kind=_BUY, wallet=WALLET_ONE_TRADE, token=TOKEN_BRAVO,
        spend_quote_raw=_usdc_spend(seed, "one-trade/spend", 0),
    ))

    for i in range(2):
        events.append(_Event(
            block=WINDOW_START_BLOCK + 622_000 + i * 1_013,
            kind=_BUY, wallet=WALLET_DEAD_POOL, token=TOKEN_DEAD,
            spend_quote_raw=_weth_spend(seed, "dead-pool/spend", i),
        ))

    for i in range(2):
        events.append(_Event(
            block=WINDOW_START_BLOCK + 624_000 + i * 1_013,
            kind=_BUY, wallet=WALLET_MIGRATED, token=TOKEN_MIGRATED,
            spend_quote_raw=_weth_spend(seed, "migrated/spend", i),
        ))

    for i in range(3):
        events.append(_Event(
            block=WINDOW_START_BLOCK + 626_000 + i * 1_013,
            kind=_ETH_BUY, wallet=WALLET_ETH_ROUTE, token=TOKEN_ALPHA,
            spend_quote_raw=_weth_spend(seed, "eth-route/spend", i),
        ))

    # The §4.8 measurement tail: past the window's end, inside the marking horizon. The sell
    # matches against the right basis; the buy opens a lot and is deferred to the next window
    # rather than scored in this one.
    events.append(_Event(
        block=WINDOW_END_BLOCK + 20_000,
        kind=_SELL, wallet=WALLET_PARTIAL, token=TOKEN_ALPHA, sell_fraction=(1, 3),
    ))
    events.append(_Event(
        block=WINDOW_END_BLOCK + 21_013,
        kind=_BUY, wallet=WALLET_PARTIAL, token=TOKEN_ALPHA,
        spend_quote_raw=_weth_spend(seed, "partial/tail-spend", 0),
    ))

    events.sort(key=lambda event: event.block)
    blocks = [event.block for event in events]
    if len(set(blocks)) != len(blocks):
        repeated = sorted({b for b in blocks if blocks.count(b) > 1})
        raise ValueError(
            "the generator allocated block(s) {} to more than one event. Two events in one block "
            "of one lot book is a QuarantineRequired from fifo._require_a_total_order — the seam "
            "carries no transaction index, so FIFO refuses to guess an order — and it would show "
            "up as a mysteriously quarantined book rather than as a generator "
            "bug.".format(", ".join(str(b) for b in repeated))
        )
    if blocks[0] < WINDOW_START_BLOCK or blocks[-1] > HORIZON_BLOCK:
        raise ValueError(
            "events span blocks {}..{} but the measurement period is {}..{}; run_wallet_window "
            "refuses anything outside it as a caller error rather than a data "
            "finding".format(blocks[0], blocks[-1], WINDOW_START_BLOCK, HORIZON_BLOCK)
        )
    return tuple(events)


# -- transaction construction ---------------------------------------------------


def _context(wallet):
    """What is known about the addresses in one transaction.

    ``wallet`` is typed as a codeless EOA and every venue is typed infrastructure, so
    ``attribution`` resolves ``DIRECT_EOA`` at confidence 1: the sender is a known EOA and is an
    economic endpoint of the transfers, and the only other two-sided address is excluded from the
    candidate universe by §6.2. Nothing here is a fallback — a ``TX_SENDER_FALLBACK`` would be
    excluded from the primary metric by §8 and no wallet would ever be scored.
    """
    return AttributionContext(
        eoas=frozenset({wallet}),
        infrastructure=INFRASTRUCTURE,
    )


def _observed(label, block, wallet, transfers):
    return ObservedTransaction(
        tx_hash=synthetic_tx_hash(label),
        block_number=block,
        timestamp=timestamp_of(block),
        success=True,
        tx_sender=wallet,
        transfers=transfers,
        context=_context(wallet),
    )


def _buy_transaction(label, event, token, asset_out, fee_raw):
    transfers = [
        Transfer(token=token.quote, from_addr=event.wallet, to_addr=token.pool_address,
                 raw_amount=event.spend_quote_raw, log_index=0),
        Transfer(token=token.address, from_addr=token.pool_address, to_addr=event.wallet,
                 raw_amount=asset_out, log_index=1),
    ]
    if fee_raw:
        transfers.append(Transfer(
            token=token.quote, from_addr=event.wallet, to_addr=FEE_COLLECTOR,
            raw_amount=fee_raw, log_index=2, is_fee=True,
        ))
    return _observed(label, event.block, event.wallet, tuple(transfers))


def _eth_buy_transaction(label, event, token, asset_out):
    """A buy paid in native ETH with a WETH refund — §4.2's collapse, exercised rather than named.

    The wallet sends twice the intended spend as native ETH and the router returns half of it as
    WETH. ``Transfer.__post_init__`` collapses the sentinel onto WETH, so the two legs net to a
    single quote leg of ``-spend``. Without that collapse they are two endpoints in two assets, a
    third leg is the token, and netting classifies ``NO_CLEAR_ENDPOINT`` — which is exactly the
    failure §4.2 exists to prevent, and exactly what this transaction shape is here to reach.
    """
    transfers = (
        Transfer(token=NATIVE_ETH, from_addr=event.wallet, to_addr=ROUTER,
                 raw_amount=event.spend_quote_raw * 2, log_index=0),
        Transfer(token=WETH, from_addr=ROUTER, to_addr=event.wallet,
                 raw_amount=event.spend_quote_raw, log_index=1),
        Transfer(token=token.address, from_addr=token.pool_address, to_addr=event.wallet,
                 raw_amount=asset_out, log_index=2),
    )
    return _observed(label, event.block, event.wallet, transfers)


def _sell_transaction(label, event, token, asset_in, quote_out):
    transfers = (
        Transfer(token=token.address, from_addr=event.wallet, to_addr=token.pool_address,
                 raw_amount=asset_in, log_index=0),
        Transfer(token=token.quote, from_addr=token.pool_address, to_addr=event.wallet,
                 raw_amount=quote_out, log_index=1),
    )
    return _observed(label, event.block, event.wallet, transfers)


# -- the generated chain --------------------------------------------------------


@dataclass(frozen=True)
class SyntheticChain:
    """Everything one synthetic window needs, and the record of what produced it.

    The first five fields are exactly ``pipeline.run.run_wallet_window``'s parameters. The rest is
    the record: the seed, the snapshot identifier that names itself synthetic, and the per-wallet
    counts a §10 churn block is computed from — carried here rather than recomputed from the
    result, because churn asks about a *selected* population and the result only knows about the
    wallets that traded.
    """

    seed: int
    snapshot: str
    transactions: Tuple[ObservedTransaction, ...]
    pools: Dict[str, PoolState]
    prices: Dict[str, Decimal]
    window: Window
    config: WindowConfig
    #: ``{wallet: valid buys inside the window}``, including the wallets with none.
    forward_valid_buys: Dict[str, int]
    #: ``{wallet: valid buys in the pre-``T0`` baseline}``. Synthetic, in §6's 20-1,000 band, and
    #: drawn from the seed — there is no baseline period in this fixture to count.
    baseline_valid_buys: Dict[str, int]
    baseline_days: int
    forward_days: int


def generate_chain(seed):
    """One synthetic window. Same seed, byte-identical output.

    :param seed: an ``int``, supplied by the caller. There is no default: a generator with a
        default seed is a generator whose output nobody records, and the seed is the whole of a
        synthetic run's reproducibility record.
    """
    events = _plan(seed)

    curves = {
        token.address: _Curve(token.start_asset_raw, token.start_quote_raw)
        for token in TOKENS
    }
    holdings = {}
    transactions = []
    forward_valid_buys = {wallet: 0 for wallet in SELECTED_WALLETS}

    for position, event in enumerate(events):
        token = TOKENS_BY_ADDRESS[event.token]
        curve = curves[token.address]
        label = "{}/{}/{}/{}".format(event.wallet, event.token, event.kind, event.block)
        key = (event.wallet, event.token)

        if event.kind in (_BUY, _ETH_BUY):
            asset_out = curve.buy(event.spend_quote_raw)
            holdings[key] = holdings.get(key, 0) + asset_out
            fee_raw = event.spend_quote_raw // 200 if event.with_fee else 0
            if event.kind == _BUY:
                transactions.append(_buy_transaction(label, event, token, asset_out, fee_raw))
            else:
                transactions.append(_eth_buy_transaction(label, event, token, asset_out))
            if event.block <= WINDOW_END_BLOCK:
                forward_valid_buys[event.wallet] += 1
        else:
            numerator, denominator = event.sell_fraction
            held = holdings.get(key, 0)
            asset_in = held * numerator // denominator
            if asset_in <= 0:
                raise ValueError(
                    "the plan sells {}/{} of a position of {} raw units at block {}, which is "
                    "nothing. A sell of zero is not a trade and the seam refuses it; the plan is "
                    "wrong rather than the data.".format(
                        numerator, denominator, held, event.block
                    )
                )
            quote_out = curve.sell(asset_in)
            holdings[key] = held - asset_in
            transactions.append(_sell_transaction(label, event, token, asset_in, quote_out))

        del position

    pools = {}
    for token in TOKENS:
        curve = curves[token.address]
        asset_reserve, quote_reserve = (
            token.horizon_override if token.horizon_override is not None
            else (curve.asset_raw, curve.quote_raw)
        )
        silence_blocks = token.horizon_silence_seconds // BLOCK_SECONDS
        pools[token.address] = PoolState(
            address=token.pool_address,
            asset=token.address,
            quote=token.quote,
            asset_reserve_raw=asset_reserve,
            quote_reserve_raw=quote_reserve,
            last_swap_block=HORIZON_BLOCK - silence_blocks,
            last_swap_timestamp=HORIZON_TS - token.horizon_silence_seconds,
        )

    #: Where ``token-migrated``'s liquidity went. Same token, same quote asset, a different pool,
    #: traded minutes before the horizon — the four things ``marking.pools.validate_replacement``
    #: checks before it will let a migration block the §9.1 dead conjunction.
    replacement = PoolState(
        address=POOL_MIGRATED_NEW,
        asset=TOKEN_MIGRATED,
        quote=WETH,
        asset_reserve_raw=3_000_000 * 10 ** 18,
        quote_reserve_raw=600 * 10 ** 18,
        last_swap_block=HORIZON_BLOCK - 50,
        last_swap_timestamp=HORIZON_TS - 600,
    )

    window = Window(
        index=WINDOW_INDEX,
        start_block=WINDOW_START_BLOCK,
        start_ts=WINDOW_START_TS,
        end_block=WINDOW_END_BLOCK,
        end_ts=timestamp_of(WINDOW_END_BLOCK),
    )
    config = WindowConfig(
        horizon_block=HORIZON_BLOCK,
        horizon_ts=HORIZON_TS,
        token_starts={
            address: TokenStart(block=block, timestamp=timestamp_of(block))
            for address, block in TOKEN_START_BLOCKS.items()
        },
        replacement_pools={TOKEN_MIGRATED: replacement},
    )

    baseline = {
        wallet: draw_between(seed, "baseline/valid-buys", 20, 1_000, index)
        for index, wallet in enumerate(SELECTED_WALLETS)
    }

    return SyntheticChain(
        seed=seed,
        snapshot=snapshot_id(seed),
        transactions=tuple(transactions),
        pools=pools,
        prices=dict(PRICES),
        window=window,
        config=config,
        forward_valid_buys=forward_valid_buys,
        baseline_valid_buys=baseline,
        baseline_days=365,
        forward_days=90,
    )
