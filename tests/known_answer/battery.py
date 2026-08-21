"""The sixteen frozen known-answer cases, their inputs, their answers, and the harness (§9.3).

Every expected value in this file was derived from the §4 definitions **before** the modules were
run, by evaluating the pre-registered formulas directly under
:data:`contracts.CALCULATION_CONTEXT`. The arithmetic is written out in each case's ``derivation``
so a reviewer can check the number without executing anything. Where a value has no exact decimal
form the derivation names the digit count, because at 38 significant digits several of these
answers are *not* the tidy number the algebra suggests and pretending otherwise would hide a real
property of the frozen numeric policy.

Two of those surprises are worth naming here, since they look like defects and are not:

* a **single-element weighted mean is not the identity**. ``Sum(w*r)/Sum(w)`` for one pair rounds
  ``w*r`` to 38 digits and then divides, so ``r = 0.5`` comes back as
  ``0.50000000000000000000000000000000000001``. The battery pins the value that the frozen policy
  actually produces, not the one the algebra promises;
* a bucket carrying exactly half the weight has share ``0.49999999999999999999999999999999999999``,
  for the same reason in the other direction.

**Composition.** This module calls the leaf modules itself, in the §4 order:

    §4.1/§4.2/§4.3  netting.net_transaction      transfers        -> NetTradeResult
    §4.7            marking.token_age_bucket     block/ts + start -> TokenAgeBucket
    §4.4 FIFO       fifo.match_fifo              buys + sells     -> FifoResult
    §4.4 case 2/3   marking.mark_position        open lot + pool  -> PositionValue
    §4.4 aggregate  scoring.buy_quality_detail   outcomes         -> BuyQuality

It does **not** route through ``src/pipeline``, and that is a decision rather than an omission.
§9.3's answers are fixed before the code runs, so the battery has to be able to say that a
composition root is wrong — and it cannot say that about the only thing it consults. Composing the
leaves keeps the battery an independent cross-check that ``pipeline`` can be validated against:
the five :func:`stage_net`-shaped functions below are exactly the seam where a
``run_wallet_window`` comparison test belongs, once its answers can be required to equal these.

Half the sixteen are sub-module facts in any case — the three legs of the dead conjunction, the
§4.7 bucket boundaries at the block and the second, netting's three refusals — and a composition
root that returns a wallet's score has nowhere to put them.

**No waiver mechanism.** §9.3 says "no failing test may be waived as an edge case", so there is no
skip, no xfail, and no expected-failure state anywhere in this package.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from contracts import (
    USDC,
    WETH,
    AccountType,
    Attribution,
    AttributionMethod,
    ClassificationStatus,
    LookAheadViolation,
    PoolState,
    PoolStatus,
    TokenAgeBucket,
    Transaction,
    Transfer,
    ValueBasis,
    add,
    canonical_hash,
    divide,
    mul,
    sub,
)
from fifo import match_fifo
from marking import mark_position, token_age_bucket
from netting import net_transaction
from scoring import buy_outcome, buy_quality_detail

# -- addresses and assets --------------------------------------------------------

OWNER = "0x1111111111111111111111111111111111111111"
OWNER_SECOND = "0x1111111111111111111111111111111111111112"
POOL_A = "0x2222222222222222222222222222222222222222"
POOL_B = "0x3333333333333333333333333333333333333333"
POOL_MIGRATED = "0x4444444444444444444444444444444444444444"
TAX_COLLECTOR = "0x5555555555555555555555555555555555555555"

#: A long-tail 18-decimal ERC-20. It never carries a USD price — §4.6 permits one only for the
#: liquid quote assets, and the battery would not be testing the pre-registered metric if the
#: bought token had an oracle.
TOKEN = "0x6982508145454ce325ddbe47a25d4ec3d2311933"

#: A second long-tail token, 9 decimals, used only by the circular-arbitrage round trip.
WSOL = "0xd31a59c85ae9d8edefec411d448f90841571b89c"

ONE_TOKEN = 10 ** 18
ONE_USDC = 10 ** 6
ONE_WETH = 10 ** 18
ONE_WSOL = 10 ** 9

#: USD per **raw** unit. USDC has 6 decimals at $1.00; WETH has 18 at an assumed $3,000. Exact
#: Decimals, never floats, and only quote assets appear.
PRICES = {
    USDC: Decimal("0.000001"),
    WETH: Decimal("0.000000000000003"),
}

#: USD per raw unit of the quote asset a mark is priced in. Same convention as ``PRICES[USDC]``;
#: ``mark_position`` takes exactly one price and it is the venue's quote asset's.
QUOTE_USD_PER_RAW_USDC = PRICES[USDC]

# -- time and blocks -------------------------------------------------------------

#: §4.4 measures the return over the following 30 days. Written as an absolute literal rather than
#: as ``30 * DAY_SECONDS`` derived from anything the modules export: a horizon that moves with a
#: constant somewhere else pins nothing about the horizon.
HORIZON_SECONDS = 2_592_000
DAY_SECONDS = 86_400
HOUR_SECONDS = 3_600

#: Twelve-second blocks, so 30 days is 216,000 blocks. Only used to build plausible fixtures; every
#: assertion is against a stated block number, never against a rate.
BLOCKS_PER_30_DAYS = 216_000

#: The token's §4.7 trading start: first usable liquidity plus one real swap, in POOL_A.
TOKEN_START_BLOCK = 18_000_000
TOKEN_START_TS = 1_700_000_000

#: A buy made well after the token matured — bucket D, so age never confounds a case that is not
#: about age.
MATURE_BUY_BLOCK = TOKEN_START_BLOCK + 100
MATURE_BUY_TS = TOKEN_START_TS + 200_000

HORIZON_BLOCK = MATURE_BUY_BLOCK + BLOCKS_PER_30_DAYS
HORIZON_TS = MATURE_BUY_TS + HORIZON_SECONDS


# -- fixture helpers -------------------------------------------------------------


def attribution(tx_hash, owner=OWNER):
    """A resolved, usable, non-fallback attribution. Attribution itself is exercised by ticket 20;
    the battery holds it fixed so that a netting answer is never really an attribution answer."""
    return Attribution(
        tx_hash=tx_hash,
        tx_sender=owner,
        portfolio_owner=owner,
        account_type=AccountType.EOA,
        method=AttributionMethod.DIRECT_EOA,
        confidence=Decimal("1"),
        evidence=("known-answer fixture",),
    )


def transfer(token, from_addr, to_addr, raw, log_index, is_fee=False):
    return Transfer(token=token, from_addr=from_addr, to_addr=to_addr,
                    raw_amount=raw, log_index=log_index, is_fee=is_fee)


def transaction(tx_hash, transfers, block_number, timestamp, success=True, owner=OWNER):
    return Transaction(
        tx_hash=tx_hash,
        block_number=block_number,
        timestamp=timestamp,
        success=success,
        attribution=attribution(tx_hash, owner),
        transfers=tuple(transfers),
    )


def pool(address, asset_reserve_raw, quote_reserve_raw, last_swap_block, last_swap_timestamp,
         asset=TOKEN, quote=USDC, fee_bps=30):
    return PoolState(
        address=address,
        asset=asset,
        quote=quote,
        asset_reserve_raw=asset_reserve_raw,
        quote_reserve_raw=quote_reserve_raw,
        last_swap_block=last_swap_block,
        last_swap_timestamp=last_swap_timestamp,
        fee_bps=fee_bps,
    )


# -- the §4-order composition ----------------------------------------------------


def stage_net(transactions, prices=None):
    """§4.1, §4.2, §4.3 — one :class:`NetTradeResult` per transaction, in input order."""
    book = PRICES if prices is None else prices
    return tuple(net_transaction(tx, book) for tx in transactions)


def stage_age(results, start_block, start_ts):
    """§4.7 — one bucket per trade, from the token's own trading start.

    Migration does not reset the start, which is why the start is passed rather than read off a
    pool: a caller holding a migrated pool's first block would be answering a different question.
    """
    return tuple(
        token_age_bucket(r.block_number, r.timestamp, start_block, start_ts) for r in results
    )


def stage_fifo(results):
    """§4.4 — lot assignment across the buys and sells in ``results``, oldest lot first."""
    buys = [r for r in results if r.status is ClassificationStatus.VALID_BUY]
    sells = [r for r in results if r.status is ClassificationStatus.VALID_SELL]
    return match_fifo(buys, sells)


def stage_mark(remaining_raw, pool_state, horizon_block=HORIZON_BLOCK, horizon_ts=HORIZON_TS,
               quote_usd=QUOTE_USD_PER_RAW_USDC, replacement_pool=None):
    """§4.4 cases 2 and 3 — the value of what is still open at the horizon."""
    return mark_position(remaining_raw, pool_state, horizon_block, horizon_ts, quote_usd,
                         replacement_pool=replacement_pool)


def stage_score(outcomes, wallet=OWNER):
    """§4.4 aggregation — the log-weighted wallet score plus the §10 value-basis mix."""
    return buy_quality_detail(outcomes, wallet)


# -- the case record -------------------------------------------------------------


@dataclass(frozen=True)
class KnownAnswerCase:
    """One scenario, its typed inputs, and the answer fixed before the code ran.

    ``inputs`` holds the **actual** values the runner consumes — the Transactions, PoolStates, and
    price books themselves, not a description of them. That is what makes the fixture hash worth
    computing: changing what is fed in changes the hash, and a summary that drifted from the real
    fixture could not.

    ``derivation`` is prose and is deliberately **outside** the hash (see
    :func:`canonical_battery`). It explains the number; it is not the number.
    """

    name: str
    spec: str
    derivation: Tuple[str, ...]
    inputs: Dict[str, Any]
    expected: Dict[str, Any]
    #: Facts the case pins that are not equality assertions — a raised exception, mostly.
    raises: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "derivation", tuple(self.derivation))
        if not self.derivation:
            raise ValueError(
                "{}: a known-answer case must show its arithmetic. An expected value with no "
                "derivation cannot be checked by a reviewer, only re-run.".format(self.name)
            )
        if not self.expected:
            raise ValueError("{}: a case with no expected answer answers nothing".format(self.name))


# -- helpers used by the runners -------------------------------------------------


def _evidence_map(position_value):
    """``PositionValue.evidence`` as ``{key: value}``, for the ``k=v`` entries.

    Entries without an ``=`` (the ``replacement_rejected:...`` shapes) are dropped; the cases that
    care about those assert on the tuple directly.
    """
    out = {}
    for item in position_value.evidence:
        if "=" in item:
            key, value = item.split("=", 1)
            out[key] = value
    return out


def _leg(result, token):
    for delta in result.residuals:
        if delta.token == token:
            return delta
    return None


# ================================================================================
# 1. Simple Buy + Full Sell
# ================================================================================


def _build_simple_buy_full_sell():
    buy = transaction(
        "0x01a",
        [
            transfer(USDC, OWNER, POOL_A, 1_000 * ONE_USDC, 0),
            transfer(TOKEN, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
        ],
        MATURE_BUY_BLOCK, MATURE_BUY_TS,
    )
    sell = transaction(
        "0x01b",
        [
            transfer(TOKEN, OWNER, POOL_A, 500 * ONE_TOKEN, 0),
            transfer(USDC, POOL_A, OWNER, 1_500 * ONE_USDC, 1),
        ],
        MATURE_BUY_BLOCK + 100, MATURE_BUY_TS + 10 * DAY_SECONDS,
    )

    case = KnownAnswerCase(
        name="Simple Buy + Full Sell",
        spec="§4.1, §4.2, §4.4 case 1",
        derivation=(
            "Buy:  owner pays 1,000,000,000 raw USDC and receives 500e18 raw TOKEN.",
            "      USDC net = -1,000,000,000 raw; at $0.000001 per raw unit the quote leg is $1,000.",
            "      TOKEN net = +500e18 raw, unpriceable (long-tail, and §4.6 forbids an oracle).",
            "      Two surviving legs, one quote and one asset, opposite signs, quote negative",
            "      => VALID_BUY. Notional = the one priceable endpoint = $1,000, so the residual",
            "      tolerance is max($0.01, 0.01% x 1000) = $0.10 and neither leg is negligible.",
            "Sell: 500e18 raw TOKEN out, 1,500,000,000 raw USDC in => VALID_SELL, quote $1,500.",
            "FIFO: one lot of 500e18 at a $1,000 basis, fully consumed by a 500e18 sell.",
            "      The closing slice takes the lot's exact remaining basis, $1,000, and the sell's",
            "      exact remaining proceeds, $1,500 — both agree with the pro-rata share to 0 drift.",
            "Return = 1500/1000 - 1 = 0.5 exactly.",
            "Score: w = ln(1 + 1000) = ln(1001) = 6.9087547793152205852207837629736276343 (38 dig).",
            "      buy_quality = (w x 0.5)/w. NOT 0.5: w x 0.5 is rounded to 38 digits before the",
            "      division, giving 0.50000000000000000000000000000000000001 (38 digits).",
            "      realized_share = 1500/1500 = 1; marked and dead shares are 0.",
        ),
        inputs={"buy": buy, "sell": sell, "prices": dict(PRICES)},
        expected={
            "buy_status": ClassificationStatus.VALID_BUY,
            "buy_sold_asset": USDC,
            "buy_bought_asset": TOKEN,
            "buy_sold_raw_amount": 1_000_000_000,
            "buy_bought_raw_amount": 500 * ONE_TOKEN,
            "buy_quote_usd": Decimal("1000"),
            "buy_pool": None,
            "sell_status": ClassificationStatus.VALID_SELL,
            "sell_sold_raw_amount": 500 * ONE_TOKEN,
            "sell_quote_usd": Decimal("1500"),
            "n_consumptions": 1,
            "n_open_lots": 0,
            "consumed_raw": 500 * ONE_TOKEN,
            "allocated_cost_usd": Decimal("1000"),
            "proceeds_usd": Decimal("1500"),
            "realized_return": Decimal("0.5"),
            "weight": Decimal("6.9087547793152205852207837629736276343"),
            "buy_quality": Decimal("0.50000000000000000000000000000000000001"),
            "realized_share": Decimal("1"),
            "marked_share": Decimal("0"),
            "dead_share": Decimal("0"),
        },
    )

    def run(inputs):
        buy_r, sell_r = stage_net((inputs["buy"], inputs["sell"]), inputs["prices"])
        book = stage_fifo((buy_r, sell_r))
        consumption = book.consumptions[0]
        score = stage_score([
            buy_outcome(
                buy_r,
                trade_value_usd=buy_r.quote_usd,
                return_pct=consumption.realized_return,
                realized_usd=consumption.proceeds_usd,
                bucket=TokenAgeBucket.D,
            )
        ])
        quality = score.quality
        return {
            "buy_status": buy_r.status,
            "buy_sold_asset": buy_r.sold_asset,
            "buy_bought_asset": buy_r.bought_asset,
            "buy_sold_raw_amount": buy_r.sold_raw_amount,
            "buy_bought_raw_amount": buy_r.bought_raw_amount,
            "buy_quote_usd": buy_r.quote_usd,
            "buy_pool": buy_r.pool,
            "sell_status": sell_r.status,
            "sell_sold_raw_amount": sell_r.sold_raw_amount,
            "sell_quote_usd": sell_r.quote_usd,
            "n_consumptions": len(book.consumptions),
            "n_open_lots": len(book.open_lots),
            "consumed_raw": consumption.consumed_raw,
            "allocated_cost_usd": consumption.allocated_cost_usd,
            "proceeds_usd": consumption.proceeds_usd,
            "realized_return": consumption.realized_return,
            "weight": score.total_weight,
            "buy_quality": quality.value,
            "realized_share": quality.realized_share,
            "marked_share": quality.marked_share,
            "dead_share": quality.dead_share,
        }

    return case, run


# ================================================================================
# 2. Multiple Buys + Partial Sell
# ================================================================================


def _build_multiple_buys_partial_sell():
    buy1 = transaction(
        "0x02a",
        [
            transfer(USDC, OWNER, POOL_A, 1_000 * ONE_USDC, 0),
            transfer(TOKEN, POOL_A, OWNER, 1_000 * ONE_TOKEN, 1),
        ],
        MATURE_BUY_BLOCK, MATURE_BUY_TS,
    )
    buy2 = transaction(
        "0x02b",
        [
            transfer(USDC, OWNER, POOL_A, 3_000 * ONE_USDC, 0),
            transfer(TOKEN, POOL_A, OWNER, 1_000 * ONE_TOKEN, 1),
        ],
        MATURE_BUY_BLOCK + 100, MATURE_BUY_TS + DAY_SECONDS,
    )
    sell = transaction(
        "0x02c",
        [
            transfer(TOKEN, OWNER, POOL_A, 1_500 * ONE_TOKEN, 0),
            transfer(USDC, POOL_A, OWNER, 4_500 * ONE_USDC, 1),
        ],
        MATURE_BUY_BLOCK + 200, MATURE_BUY_TS + 2 * DAY_SECONDS,
    )

    case = KnownAnswerCase(
        name="Multiple Buys + Partial Sell",
        spec="§4.4 FIFO, §9.2 deterministic fields",
        derivation=(
            "Lot 1: 1,000e18 raw TOKEN for $1,000.  Lot 2: 1,000e18 raw TOKEN for $3,000.",
            "Sell:  1,500e18 raw TOKEN for $4,500. FIFO takes 1,000e18 from lot 1, then 500e18",
            "       from lot 2 — 1,500 exactly, so nothing is left unmatched.",
            "Slice 1 closes lot 1: cost = the lot's remaining basis = $1,000.",
            "        proceeds = pro rata = 4500 x 1000/1500 = $3,000 exactly.",
            "        return = 3000/1000 - 1 = 2 exactly.",
            "Slice 2 is the closing slice of the sell: proceeds = 4500 - 3000 = $1,500,",
            "        which equals the pro-rata share 4500 x 500/1500, so drift is 0.",
            "        cost = pro rata within lot 2 = 3000 x 500/1000 = $1,500.",
            "        return = 1500/1500 - 1 = 0 exactly. A break-even slice, not a missing one.",
            "Open:   lot 2 keeps 500e18 raw and $1,500 of basis (3000 - 1500).",
            "Raw units close exactly: consumed 1500e18 = sold 1500e18; opened 2000e18 minus",
            "consumed 1500e18 = remaining 500e18. §9.2 allows no tolerance on either.",
        ),
        inputs={"buy1": buy1, "buy2": buy2, "sell": sell, "prices": dict(PRICES)},
        expected={
            "n_consumptions": 2,
            "n_open_lots": 1,
            "c0_buy_tx": "0x02a",
            "c0_consumed_raw": 1_000 * ONE_TOKEN,
            "c0_allocated_cost_usd": Decimal("1000"),
            "c0_proceeds_usd": Decimal("3000"),
            "c0_realized_return": Decimal("2"),
            "c1_buy_tx": "0x02b",
            "c1_consumed_raw": 500 * ONE_TOKEN,
            "c1_allocated_cost_usd": Decimal("1500"),
            "c1_proceeds_usd": Decimal("1500"),
            "c1_realized_return": Decimal("0"),
            "open_lot_buy_tx": "0x02b",
            "open_lot_remaining_raw": 500 * ONE_TOKEN,
            "total_consumed_raw": 1_500 * ONE_TOKEN,
            "total_proceeds_usd": Decimal("4500"),
            "total_allocated_cost_usd": Decimal("2500"),
        },
    )

    def run(inputs):
        results = stage_net((inputs["buy1"], inputs["buy2"], inputs["sell"]), inputs["prices"])
        book = stage_fifo(results)
        first, second = book.consumptions
        return {
            "n_consumptions": len(book.consumptions),
            "n_open_lots": len(book.open_lots),
            "c0_buy_tx": first.buy.tx_hash,
            "c0_consumed_raw": first.consumed_raw,
            "c0_allocated_cost_usd": first.allocated_cost_usd,
            "c0_proceeds_usd": first.proceeds_usd,
            "c0_realized_return": first.realized_return,
            "c1_buy_tx": second.buy.tx_hash,
            "c1_consumed_raw": second.consumed_raw,
            "c1_allocated_cost_usd": second.allocated_cost_usd,
            "c1_proceeds_usd": second.proceeds_usd,
            "c1_realized_return": second.realized_return,
            "open_lot_buy_tx": book.open_lots[0].buy.tx_hash,
            "open_lot_remaining_raw": book.open_lots[0].remaining_raw,
            # int addition — raw quantities are exact and no decimal context is involved.
            "total_consumed_raw": sum(c.consumed_raw for c in book.consumptions),
            "total_proceeds_usd": add(first.proceeds_usd, second.proceeds_usd),
            "total_allocated_cost_usd": add(first.allocated_cost_usd, second.allocated_cost_usd),
        }

    return case, run


# ================================================================================
# 3. Multi-hop Buy
# ================================================================================


def _build_multi_hop_buy():
    tx = transaction(
        "0x03a",
        [
            transfer(USDC, OWNER, POOL_A, 3_000 * ONE_USDC, 0),
            transfer(WETH, POOL_A, OWNER, 1 * ONE_WETH, 1),
            transfer(WETH, OWNER, POOL_B, 1 * ONE_WETH, 2),
            transfer(TOKEN, POOL_B, OWNER, 200 * ONE_TOKEN, 3),
        ],
        MATURE_BUY_BLOCK, MATURE_BUY_TS,
    )

    case = KnownAnswerCase(
        name="Multi-hop Buy",
        spec="§4.2",
        derivation=(
            "Route USDC -> WETH -> TOKEN in one transaction. dex.trades would emit two rows and a",
            "phantom 'bought 1 WETH' event that never represented intent.",
            "Netting by (transaction, owner, token):",
            "  USDC  : -3,000,000,000 raw            -> $3,000 endpoint",
            "  WETH  : +1e18 received, -1e18 sent    -> net 0, an intermediate, drops out",
            "  TOKEN : +200e18 raw                   -> the asset endpoint",
            "Exactly one buy, of TOKEN, for $3,000. The WETH leg survives as a residual with raw 0",
            "so the transaction still reconciles to the owner's balance change: nothing vanished.",
            "pool is None: a split or multi-hop route touches several pools and netting will not",
            "guess one (§4.1 wants a real pool, not a plausible one).",
        ),
        inputs={"tx": tx, "prices": dict(PRICES)},
        expected={
            "status": ClassificationStatus.VALID_BUY,
            "sold_asset": USDC,
            "bought_asset": TOKEN,
            "sold_raw_amount": 3_000_000_000,
            "bought_raw_amount": 200 * ONE_TOKEN,
            "quote_usd": Decimal("3000"),
            "pool": None,
            "weth_residual_raw": 0,
            "weth_residual_usd": Decimal("0"),
            "n_residuals": 1,
        },
    )

    def run(inputs):
        result = stage_net((inputs["tx"],), inputs["prices"])[0]
        weth_leg = _leg(result, WETH)
        return {
            "status": result.status,
            "sold_asset": result.sold_asset,
            "bought_asset": result.bought_asset,
            "sold_raw_amount": result.sold_raw_amount,
            "bought_raw_amount": result.bought_raw_amount,
            "quote_usd": result.quote_usd,
            "pool": result.pool,
            "weth_residual_raw": weth_leg.raw,
            "weth_residual_usd": weth_leg.usd,
            "n_residuals": len(result.residuals),
        }

    return case, run


# ================================================================================
# 4. FIFO Allocation  (§4.4's own worked example)
# ================================================================================


def _build_fifo_allocation():
    buy1 = transaction(
        "0x04a",
        [
            transfer(USDC, OWNER, POOL_A, 100 * ONE_USDC, 0),
            transfer(TOKEN, POOL_A, OWNER, 100 * ONE_TOKEN, 1),
        ],
        MATURE_BUY_BLOCK, MATURE_BUY_TS,
    )
    buy2 = transaction(
        "0x04b",
        [
            transfer(USDC, OWNER, POOL_A, 200 * ONE_USDC, 0),
            transfer(TOKEN, POOL_A, OWNER, 100 * ONE_TOKEN, 1),
        ],
        MATURE_BUY_BLOCK + 10, MATURE_BUY_TS + HOUR_SECONDS,
    )
    sell = transaction(
        "0x04c",
        [
            transfer(TOKEN, OWNER, POOL_A, 150 * ONE_TOKEN, 0),
            transfer(USDC, POOL_A, OWNER, 450 * ONE_USDC, 1),
        ],
        MATURE_BUY_BLOCK + 20, MATURE_BUY_TS + 2 * HOUR_SECONDS,
    )

    case = KnownAnswerCase(
        name="FIFO Allocation",
        spec="§4.4 partial sells",
        derivation=(
            "The pre-registration's own example, in raw units:",
            "  Buy 1: 100 tokens @ $1  -> 100e18 raw for $100",
            "  Buy 2: 100 tokens @ $2  -> 100e18 raw for $200",
            "  Sell:  150 tokens @ $3  -> 150e18 raw for $450",
            "  => 100 from Buy 1, 50 from Buy 2.",
            "Slice 1: closes lot 1, cost = $100 (its whole basis).",
            "         proceeds = 450 x 100/150 = $300 exactly. Return = 300/100 - 1 = 2.",
            "Slice 2: 50e18 of lot 2, cost = 200 x 50/100 = $100.",
            "         closing slice of the sell: proceeds = 450 - 300 = $150, which equals the",
            "         pro-rata share 450 x 50/150. Return = 150/100 - 1 = 0.5.",
            "Open:    lot 2 keeps 50e18 raw and $100 of basis.",
            "The allocation is the assertion. A LIFO or average-cost rule would produce the same",
            "150e18 consumed and a different pairing, which is why the buy tx hash of each slice",
            "is pinned and not only the totals.",
        ),
        inputs={"buy1": buy1, "buy2": buy2, "sell": sell, "prices": dict(PRICES)},
        expected={
            "allocation": (("0x04a", 100 * ONE_TOKEN), ("0x04b", 50 * ONE_TOKEN)),
            "c0_allocated_cost_usd": Decimal("100"),
            "c0_proceeds_usd": Decimal("300"),
            "c0_realized_return": Decimal("2"),
            "c1_allocated_cost_usd": Decimal("100"),
            "c1_proceeds_usd": Decimal("150"),
            "c1_realized_return": Decimal("0.5"),
            "open_lot_remaining_raw": 50 * ONE_TOKEN,
            "n_open_lots": 1,
            "unmatched_sell_raw": {},
        },
    )

    def run(inputs):
        results = stage_net((inputs["buy1"], inputs["buy2"], inputs["sell"]), inputs["prices"])
        book = stage_fifo(results)
        first, second = book.consumptions
        return {
            "allocation": tuple((c.buy.tx_hash, c.consumed_raw) for c in book.consumptions),
            "c0_allocated_cost_usd": first.allocated_cost_usd,
            "c0_proceeds_usd": first.proceeds_usd,
            "c0_realized_return": first.realized_return,
            "c1_allocated_cost_usd": second.allocated_cost_usd,
            "c1_proceeds_usd": second.proceeds_usd,
            "c1_realized_return": second.realized_return,
            "open_lot_remaining_raw": book.open_lots[0].remaining_raw,
            "n_open_lots": len(book.open_lots),
            "unmatched_sell_raw": dict(book.unmatched_sell_raw),
        }

    return case, run


# ================================================================================
# 5. Open Position at Day 30
# ================================================================================

#: Reserves: 1,000,000 TOKEN (18dp) against $2,000,000 of USDC (6dp). Deep relative to the
#: position, so the liquidity bound is real but small — which is what makes this the *control* for
#: cases 7 and 8 rather than a repeat of them.
OPEN_POOL_ASSET_RESERVE = 1_000_000 * ONE_TOKEN
OPEN_POOL_QUOTE_RESERVE = 2_000_000 * ONE_USDC
OPEN_POSITION_RAW = 1_000 * ONE_TOKEN

#: exit_value_usd for OPEN_POSITION_RAW against the pool above, at 30bps. 38 significant digits;
#: 1.994e16 / 1.000997e28 does not terminate.
OPEN_POSITION_MARK = Decimal("1992.0139620798064329863126462916472277")


def _build_open_position_at_day_30():
    live_pool = pool(
        POOL_A, OPEN_POOL_ASSET_RESERVE, OPEN_POOL_QUOTE_RESERVE,
        last_swap_block=HORIZON_BLOCK - 300,
        last_swap_timestamp=HORIZON_TS - HOUR_SECONDS,
    )

    case = KnownAnswerCase(
        name="Open Position at Day 30",
        spec="§4.4 case 2",
        derivation=(
            "Position 1,000e18 raw TOKEN still open at the horizon. Pool holds 1,000,000e18 raw",
            "TOKEN against 2,000,000,000,000 raw USDC, fee 30bps, last swap one hour before the",
            "horizon.",
            "Spot exit price   = 2e12 / 1e24 = 2e-12 raw quote per raw asset (exact).",
            "Spot value        = 1e21 x 2e-12 x 1e-6 USD/raw = $2,000 exactly.",
            "Average exit price= (10000-30) x 2e12 / (10000 x 1e24 + (10000-30) x 1e21)",
            "                  = 1.994e16 / 1.000997e28",
            "                  = 1.9920139620798064329863126462916472277e-12 (38 digits).",
            "Extractable value = 1e21 x that x 1e-6 = 1992.0139620798064329863126462916472277.",
            "Marked value      = min($2,000, $1,992.0139...) = the extractable term.",
            "Shortfall vs spot = (2000 - 1992.0139...)/2000 = 0.00399301896... = 0.399%,",
            "                    below the 0.5% MARKING_TOLERANCE, so the basis is POOL_MARKED",
            "                    rather than LIQUIDITY_BOUND, and below 10% so the pool is LIVE.",
            "Not dead: the pool traded an hour ago, so §9.1 condition 1 already fails and the",
            "conjunction cannot hold however small the exit is.",
        ),
        inputs={
            "pool": live_pool,
            "remaining_raw": OPEN_POSITION_RAW,
            "horizon_block": HORIZON_BLOCK,
            "horizon_ts": HORIZON_TS,
            "quote_usd": QUOTE_USD_PER_RAW_USDC,
        },
        expected={
            "value_usd": OPEN_POSITION_MARK,
            "value_basis": ValueBasis.POOL_MARKED,
            "pool_status": PoolStatus.LIVE,
            "executable_quantity": OPEN_POSITION_RAW,
            "spot_usd": Decimal("2000"),
            "dead_pool": "false",
            "cond1_no_swap_for_30d": "false",
            "cond2_exit_below_minimum": "false",
            "cond3_no_validated_replacement": "true",
            "model": "constant_product_reserves",
            "venue": POOL_A,
        },
    )

    def run(inputs):
        value = stage_mark(
            inputs["remaining_raw"], inputs["pool"], inputs["horizon_block"],
            inputs["horizon_ts"], inputs["quote_usd"],
        )
        evidence = _evidence_map(value)
        return {
            "value_usd": value.value_usd,
            "value_basis": value.value_basis,
            "pool_status": value.pool_status,
            "executable_quantity": value.executable_quantity,
            "spot_usd": Decimal(evidence["spot_usd"]),
            "dead_pool": evidence["dead_pool"],
            "cond1_no_swap_for_30d": evidence["cond1_no_swap_for_30d"],
            "cond2_exit_below_minimum": evidence["cond2_exit_below_minimum"],
            "cond3_no_validated_replacement": evidence["cond3_no_validated_replacement"],
            "model": evidence["model"],
            "venue": evidence["venue"],
        }

    return case, run


# ================================================================================
# 6. Dead Pool
# ================================================================================

#: A pool holding one whole dollar of quote against a million tokens. Its exit is $0.000996, three
#: orders of magnitude below the $1.00 minimum.
DEAD_POOL_QUOTE_RESERVE = 1 * ONE_USDC
DEAD_POOL_EXIT_IF_ALIVE = Decimal("0.00099600698103990321649315632314582361386")


def _build_dead_pool():
    dead = pool(
        POOL_A, OPEN_POOL_ASSET_RESERVE, DEAD_POOL_QUOTE_RESERVE,
        last_swap_block=HORIZON_BLOCK - BLOCKS_PER_30_DAYS,
        last_swap_timestamp=HORIZON_TS - HORIZON_SECONDS,
    )
    #: The same pool, one second less silent. Every other input is identical, so anything that
    #: differs between the two is caused by the inactivity window and nothing else.
    alive_by_one_second = pool(
        POOL_A, OPEN_POOL_ASSET_RESERVE, DEAD_POOL_QUOTE_RESERVE,
        last_swap_block=HORIZON_BLOCK - BLOCKS_PER_30_DAYS,
        last_swap_timestamp=HORIZON_TS - HORIZON_SECONDS + 1,
    )

    case = KnownAnswerCase(
        name="Dead Pool",
        spec="§4.4 case 3, addendum §9.1",
        derivation=(
            "All three §9.1 conditions hold at once, and only together do they zero anything:",
            "  1. last swap is exactly 2,592,000 s before the horizon — 30 days, half-open at the",
            "     top, so exactly 30 days of silence satisfies 'no swap for 30 days';",
            "  2. the extractable exit is 1e21 x (9970 x 1e6)/(10000 x 1e24 + 9970 x 1e21) x 1e-6",
            "     = $0.00099600698103990321649315632314582361386 (38 digits), below $1.00;",
            "  3. no replacement pool was supplied.",
            "Marked value = 0 exactly. Not the last observed price and not a forward fill: Dune",
            "carries a daily price forward for up to 30 days, which renders a rugged token flat",
            "instead of -100% and flatters every wallet that bought garbage.",
            "The control moves the last swap one second later, changing nothing else. Condition 1",
            "fails, the conjunction fails, and the position marks at $0.000996 as POOL_MARKED.",
            "That is the class being closed rather than the instance: a pool this thin is *still*",
            "not zeroed while it is trading.",
        ),
        inputs={
            "dead_pool": dead,
            "alive_by_one_second": alive_by_one_second,
            "remaining_raw": OPEN_POSITION_RAW,
            "horizon_block": HORIZON_BLOCK,
            "horizon_ts": HORIZON_TS,
            "quote_usd": QUOTE_USD_PER_RAW_USDC,
        },
        expected={
            "value_usd": Decimal("0"),
            "value_basis": ValueBasis.DEAD_ZEROED,
            "pool_status": PoolStatus.DEAD,
            "executable_quantity": 0,
            "cond1_no_swap_for_30d": "true",
            "cond2_exit_below_minimum": "true",
            "cond3_no_validated_replacement": "true",
            "primary_inactivity_s": str(HORIZON_SECONDS),
            "control_value_usd": DEAD_POOL_EXIT_IF_ALIVE,
            "control_value_basis": ValueBasis.POOL_MARKED,
            "control_pool_status": PoolStatus.LIVE,
            "control_cond1_no_swap_for_30d": "false",
        },
    )

    def run(inputs):
        value = stage_mark(
            inputs["remaining_raw"], inputs["dead_pool"], inputs["horizon_block"],
            inputs["horizon_ts"], inputs["quote_usd"],
        )
        evidence = _evidence_map(value)
        control = stage_mark(
            inputs["remaining_raw"], inputs["alive_by_one_second"], inputs["horizon_block"],
            inputs["horizon_ts"], inputs["quote_usd"],
        )
        control_evidence = _evidence_map(control)
        return {
            "value_usd": value.value_usd,
            "value_basis": value.value_basis,
            "pool_status": value.pool_status,
            "executable_quantity": value.executable_quantity,
            "cond1_no_swap_for_30d": evidence["cond1_no_swap_for_30d"],
            "cond2_exit_below_minimum": evidence["cond2_exit_below_minimum"],
            "cond3_no_validated_replacement": evidence["cond3_no_validated_replacement"],
            "primary_inactivity_s": evidence["primary_inactivity_s"],
            "control_value_usd": control.value_usd,
            "control_value_basis": control.value_basis,
            "control_pool_status": control.pool_status,
            "control_cond1_no_swap_for_30d": control_evidence["cond1_no_swap_for_30d"],
        }

    return case, run


# ================================================================================
# 7. Thin but Live Pool
# ================================================================================

THIN_POOL_ASSET_RESERVE = 10_000 * ONE_TOKEN
THIN_POOL_QUOTE_RESERVE = 20_000 * ONE_USDC
THIN_POSITION_RAW = 5_000 * ONE_TOKEN
THIN_POSITION_MARK = Decimal("6653.3199866533199866533199866533199865")


def _build_thin_but_live_pool():
    thin = pool(
        POOL_A, THIN_POOL_ASSET_RESERVE, THIN_POOL_QUOTE_RESERVE,
        last_swap_block=HORIZON_BLOCK - 50,
        last_swap_timestamp=HORIZON_TS - 600,
    )

    case = KnownAnswerCase(
        name="Thin but Live Pool",
        spec="§4.4 case 2, addendum §9.1",
        derivation=(
            "The position is half the pool's asset reserve, and the pool traded ten minutes ago.",
            "Spot value        = 5e21 x (2e10/1e22) x 1e-6 = 5e21 x 2e-12 x 1e-6 = $10,000 exactly.",
            "Average exit price= 9970 x 2e10 / (10000 x 1e22 + 9970 x 5e21)",
            "                  = 1.994e14 / 1.4985e26 (does not terminate).",
            "Extractable value = $6,653.3199866533199866533199866533199865 (38 digits).",
            "Shortfall vs spot = 0.33466800133466800133466800133466800135 = 33.5%.",
            "  > 10% THIN_SHORTFALL_RATIO  -> PoolStatus.THIN",
            "  >  0.5% MARKING_TOLERANCE   -> ValueBasis.LIQUIDITY_BOUND",
            "The point of the case is what does NOT happen: a thin pool is not a dead pool. The",
            "value is $6,653, not $10,000 and not $0, and the position is still fully executable.",
        ),
        inputs={
            "pool": thin,
            "remaining_raw": THIN_POSITION_RAW,
            "horizon_block": HORIZON_BLOCK,
            "horizon_ts": HORIZON_TS,
            "quote_usd": QUOTE_USD_PER_RAW_USDC,
        },
        expected={
            "value_usd": THIN_POSITION_MARK,
            "value_basis": ValueBasis.LIQUIDITY_BOUND,
            "pool_status": PoolStatus.THIN,
            "executable_quantity": THIN_POSITION_RAW,
            "spot_usd": Decimal("10000"),
            "shortfall_vs_spot": Decimal("0.33466800"),
            "dead_pool": "false",
        },
    )

    def run(inputs):
        value = stage_mark(
            inputs["remaining_raw"], inputs["pool"], inputs["horizon_block"],
            inputs["horizon_ts"], inputs["quote_usd"],
        )
        evidence = _evidence_map(value)
        return {
            "value_usd": value.value_usd,
            "value_basis": value.value_basis,
            "pool_status": value.pool_status,
            "executable_quantity": value.executable_quantity,
            "spot_usd": Decimal(evidence["spot_usd"]),
            "shortfall_vs_spot": Decimal(evidence["shortfall_vs_spot"]),
            "dead_pool": evidence["dead_pool"],
        }

    return case, run


# ================================================================================
# 8. Liquidity-Bound Marking
# ================================================================================

#: §4.4's own illustration: "A wallet holding $50,000 of a token whose pool has $2,000 of
#: liquidity does not hold $50,000."
BOUND_POOL_QUOTE_RESERVE = 2_000 * ONE_USDC
BOUND_POSITION_RAW = 25_000_000 * ONE_TOKEN
BOUND_POSITION_MARK = Decimal("1922.8543876567020250723240115718418515")


def _build_liquidity_bound_marking():
    shallow = pool(
        POOL_A, OPEN_POOL_ASSET_RESERVE, BOUND_POOL_QUOTE_RESERVE,
        last_swap_block=HORIZON_BLOCK - 10,
        last_swap_timestamp=HORIZON_TS - 120,
    )

    case = KnownAnswerCase(
        name="Liquidity-Bound Marking",
        spec="§4.4 case 2 — the bound is mandatory",
        derivation=(
            "Spot price     = 2e9 / 1e24 = 2e-15 raw quote per raw asset (exact).",
            "Spot value     = 2.5e25 x 2e-15 x 1e-6 = $50,000 exactly — the fiction the bound",
            "                 exists to refuse.",
            "Extractable    = 2.5e25 x [9970 x 2e9 / (10000 x 1e24 + 9970 x 2.5e25)] x 1e-6",
            "               = $1,922.8543876567020250723240115718418515 (38 digits).",
            "Marked value   = min($50,000, $1,922.85...) = $1,922.85...",
            "Shortfall      = 0.96154291224686595949855351976856316296 = 96.2%.",
            "The extractable value is necessarily below the pool's whole $2,000 quote reserve: a",
            "constant-product curve cannot be drained. Marking at spot would have claimed 25x the",
            "money that exists in the pool.",
        ),
        inputs={
            "pool": shallow,
            "remaining_raw": BOUND_POSITION_RAW,
            "horizon_block": HORIZON_BLOCK,
            "horizon_ts": HORIZON_TS,
            "quote_usd": QUOTE_USD_PER_RAW_USDC,
        },
        expected={
            "value_usd": BOUND_POSITION_MARK,
            "value_basis": ValueBasis.LIQUIDITY_BOUND,
            "pool_status": PoolStatus.THIN,
            "spot_usd": Decimal("50000"),
            "pool_quote_reserve_usd": Decimal("2000"),
            "mark_is_below_whole_pool": True,
            "shortfall_vs_spot": Decimal("0.96154291"),
        },
    )

    def run(inputs):
        value = stage_mark(
            inputs["remaining_raw"], inputs["pool"], inputs["horizon_block"],
            inputs["horizon_ts"], inputs["quote_usd"],
        )
        evidence = _evidence_map(value)
        reserve_usd = mul(inputs["pool"].quote_reserve_raw, inputs["quote_usd"])
        return {
            "value_usd": value.value_usd,
            "value_basis": value.value_basis,
            "pool_status": value.pool_status,
            "spot_usd": Decimal(evidence["spot_usd"]),
            "pool_quote_reserve_usd": reserve_usd,
            "mark_is_below_whole_pool": value.value_usd < reserve_usd,
            "shortfall_vs_spot": Decimal(evidence["shortfall_vs_spot"]),
        }

    return case, run


# ================================================================================
# 9. Fee-on-Transfer Token
# ================================================================================


def _build_fee_on_transfer_token():
    buy = transaction(
        "0x09a",
        [
            transfer(USDC, OWNER, POOL_A, 1_000 * ONE_USDC, 0),
            # The token contract taxes the transfer: the pool sends 1,000 but 50 is diverted.
            transfer(TOKEN, POOL_A, OWNER, 950 * ONE_TOKEN, 1),
            transfer(TOKEN, POOL_A, TAX_COLLECTOR, 50 * ONE_TOKEN, 2),
        ],
        MATURE_BUY_BLOCK, MATURE_BUY_TS,
    )
    sell = transaction(
        "0x09b",
        [
            transfer(TOKEN, OWNER, POOL_A, 950 * ONE_TOKEN, 0),
            transfer(USDC, POOL_A, OWNER, 1_900 * ONE_USDC, 1),
        ],
        MATURE_BUY_BLOCK + 100, MATURE_BUY_TS + 5 * DAY_SECONDS,
    )

    case = KnownAnswerCase(
        name="Fee-on-Transfer Token",
        spec="§4.2 (transfers touching the owner), §9.2",
        derivation=(
            "The pool debits 1,000e18 raw TOKEN but the token contract diverts 50e18 of it to a",
            "tax collector, so the owner's balance rises by 950e18 and not 1,000e18.",
            "§4.2 step 3 filters to transfers touching the owner *first*, so the tax transfer",
            "(pool -> collector) never enters the sum. The owner's net is +950e18.",
            "The position is 950 tokens. Booking 1,000 would overstate every later quantity: the",
            "FIFO lot, the sell that closes it, and the day-30 mark.",
            "Sell: the owner sends the 950e18 they actually hold and receives 1,900,000,000 raw",
            "USDC. Net TOKEN = -950e18, net USDC = +1,900,000,000 -> VALID_SELL at $1,900.",
            "FIFO: one lot of 950e18 at a $1,000 basis, closed in full for $1,900 of proceeds.",
            "Return = 1900/1000 - 1 = 0.9 exactly. Nothing is left unmatched, which is the check",
            "that the buy and the sell agree about how many tokens ever existed.",
        ),
        inputs={"buy": buy, "sell": sell, "prices": dict(PRICES)},
        expected={
            "buy_status": ClassificationStatus.VALID_BUY,
            "buy_bought_raw_amount": 950 * ONE_TOKEN,
            "buy_quote_usd": Decimal("1000"),
            "sell_status": ClassificationStatus.VALID_SELL,
            "sell_sold_raw_amount": 950 * ONE_TOKEN,
            "sell_quote_usd": Decimal("1900"),
            "n_consumptions": 1,
            "consumed_raw": 950 * ONE_TOKEN,
            "allocated_cost_usd": Decimal("1000"),
            "proceeds_usd": Decimal("1900"),
            "realized_return": Decimal("0.9"),
            "n_open_lots": 0,
            "unmatched_sell_raw": {},
        },
    )

    def run(inputs):
        buy_r, sell_r = stage_net((inputs["buy"], inputs["sell"]), inputs["prices"])
        book = stage_fifo((buy_r, sell_r))
        consumption = book.consumptions[0]
        return {
            "buy_status": buy_r.status,
            "buy_bought_raw_amount": buy_r.bought_raw_amount,
            "buy_quote_usd": buy_r.quote_usd,
            "sell_status": sell_r.status,
            "sell_sold_raw_amount": sell_r.sold_raw_amount,
            "sell_quote_usd": sell_r.quote_usd,
            "n_consumptions": len(book.consumptions),
            "consumed_raw": consumption.consumed_raw,
            "allocated_cost_usd": consumption.allocated_cost_usd,
            "proceeds_usd": consumption.proceeds_usd,
            "realized_return": consumption.realized_return,
            "n_open_lots": len(book.open_lots),
            "unmatched_sell_raw": dict(book.unmatched_sell_raw),
        }

    return case, run


# ================================================================================
# 10. Failed Transaction
# ================================================================================


def _build_failed_transaction():
    transfers = [
        transfer(USDC, OWNER, POOL_A, 1_000 * ONE_USDC, 0),
        transfer(TOKEN, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
    ]
    reverted = transaction("0x10a", transfers, MATURE_BUY_BLOCK, MATURE_BUY_TS, success=False)
    succeeded = transaction("0x10b", transfers, MATURE_BUY_BLOCK, MATURE_BUY_TS, success=True)

    case = KnownAnswerCase(
        name="Failed Transaction",
        spec="§4.1 (meta.err == null)",
        derivation=(
            "Two transactions carrying byte-identical transfers. One reverted, one did not.",
            "The reverted one is FAILED_TRANSACTION with no legs at all: sold_asset, bought_asset,",
            "the raw amounts and the quote asset are all None, because a reverted transaction",
            "moved nothing however convincing its logs look.",
            "The successful one is a VALID_BUY of 500e18 raw TOKEN for $1,000.",
            "The pair is the assertion. A test that only showed the reverted case would pass",
            "against an implementation that classified everything as FAILED_TRANSACTION.",
            "No lot is opened by the reverted transaction, so the FIFO book over both sees exactly",
            "one lot and 500e18 raw open — not 1,000e18.",
        ),
        inputs={"reverted": reverted, "succeeded": succeeded, "prices": dict(PRICES)},
        expected={
            "reverted_status": ClassificationStatus.FAILED_TRANSACTION,
            "reverted_sold_asset": None,
            "reverted_bought_asset": None,
            "reverted_sold_raw_amount": None,
            "reverted_bought_raw_amount": None,
            "reverted_quote_asset": None,
            "reverted_quote_usd": None,
            "reverted_is_trade": False,
            "reverted_has_reason": True,
            "succeeded_status": ClassificationStatus.VALID_BUY,
            "succeeded_bought_raw_amount": 500 * ONE_TOKEN,
            "succeeded_quote_usd": Decimal("1000"),
            "n_open_lots_over_both": 1,
            "open_raw_over_both": 500 * ONE_TOKEN,
        },
    )

    def run(inputs):
        reverted_r, succeeded_r = stage_net(
            (inputs["reverted"], inputs["succeeded"]), inputs["prices"]
        )
        book = stage_fifo((reverted_r, succeeded_r))
        return {
            "reverted_status": reverted_r.status,
            "reverted_sold_asset": reverted_r.sold_asset,
            "reverted_bought_asset": reverted_r.bought_asset,
            "reverted_sold_raw_amount": reverted_r.sold_raw_amount,
            "reverted_bought_raw_amount": reverted_r.bought_raw_amount,
            "reverted_quote_asset": reverted_r.quote_asset,
            "reverted_quote_usd": reverted_r.quote_usd,
            "reverted_is_trade": reverted_r.status.is_trade,
            "reverted_has_reason": reverted_r.reason is not None,
            "succeeded_status": succeeded_r.status,
            "succeeded_bought_raw_amount": succeeded_r.bought_raw_amount,
            "succeeded_quote_usd": succeeded_r.quote_usd,
            "n_open_lots_over_both": len(book.open_lots),
            "open_raw_over_both": sum(lot.remaining_raw for lot in book.open_lots),
        }

    return case, run


# ================================================================================
# 11. Circular Arbitrage
# ================================================================================


def _build_circular_arbitrage():
    round_trip = transaction(
        "0x11a",
        [
            transfer(USDC, OWNER, POOL_A, 956_000_000, 0),
            transfer(WSOL, POOL_A, OWNER, 5_000 * ONE_WSOL, 1),
            transfer(WSOL, OWNER, POOL_B, 5_000 * ONE_WSOL, 2),
            transfer(USDC, POOL_B, OWNER, 956_050_000, 3),
        ],
        MATURE_BUY_BLOCK, MATURE_BUY_TS,
    )
    #: The same route, but $56 does not come back. That is not a round trip and must not be
    #: excluded as one — it is money nobody can explain, and §8 sends it to the queue.
    incomplete = transaction(
        "0x11b",
        [
            transfer(USDC, OWNER, POOL_A, 956_000_000, 0),
            transfer(WSOL, POOL_A, OWNER, 5_000 * ONE_WSOL, 1),
            transfer(WSOL, OWNER, POOL_B, 5_000 * ONE_WSOL, 2),
            transfer(USDC, POOL_B, OWNER, 900_000_000, 3),
        ],
        MATURE_BUY_BLOCK + 1, MATURE_BUY_TS + 12,
    )

    case = KnownAnswerCase(
        name="Circular Arbitrage",
        spec="§4.3",
        derivation=(
            "§4.3's own example: USDC -> WSOL -> USDC for $0.05 of profit on a $956 route.",
            "  WSOL : +5,000e9 then -5,000e9 -> net 0, an intermediate.",
            "  USDC : 956,000,000 raw out, 956,050,000 raw in -> net +50,000 raw = $0.05.",
            "The USDC leg is judged against its own one-way flow, not against a fixed floor:",
            "  gross            = max(956,000,000, 956,050,000) raw = $956.05",
            "  leg tolerance    = max($0.01, 0.01% x 956.05) = $0.095605",
            "  $0.05 <= $0.095605, so the leg came back and sets no endpoint.",
            "Nothing stayed, so the notional falls back to the route: $956.05. The transaction",
            "tolerance is $0.095605, every leg is negligible, nothing survives",
            "  => CIRCULAR_ARBITRAGE, quote_usd = the $956.05 of phantom volume removed.",
            "Sizing the tolerance by the *net* $0.05 instead would give a $0.01 tolerance, the",
            "$0.05 would survive alone, and the round trip would be filed as a residual instead.",
            "The control returns only $900 of the $956. The USDC net is -$56, which is 5.9% of",
            "its own flow and far outside the $0.095605 the leg would have to clear:",
            "  => ABOVE_TOLERANCE_RESIDUAL, not CIRCULAR_ARBITRAGE and not a trade.",
            "That is the class rather than the instance: 'nets to approximately zero' has to mean",
            "approximately zero *relative to what moved*, at every size.",
        ),
        inputs={"round_trip": round_trip, "incomplete": incomplete, "prices": dict(PRICES)},
        expected={
            "status": ClassificationStatus.CIRCULAR_ARBITRAGE,
            "quote_usd": Decimal("956.05"),
            "is_trade": False,
            "usdc_residual_raw": 50_000,
            "usdc_residual_usd": Decimal("0.05"),
            "wsol_residual_raw": 0,
            "n_residuals": 2,
            "control_status": ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL,
            "control_quote_usd": Decimal("956"),
            "control_is_trade": False,
        },
    )

    def run(inputs):
        result, control = stage_net(
            (inputs["round_trip"], inputs["incomplete"]), inputs["prices"]
        )
        usdc_leg = _leg(result, USDC)
        wsol_leg = _leg(result, WSOL)
        return {
            "status": result.status,
            "quote_usd": result.quote_usd,
            "is_trade": result.status.is_trade,
            "usdc_residual_raw": usdc_leg.raw,
            "usdc_residual_usd": usdc_leg.usd,
            "wsol_residual_raw": wsol_leg.raw,
            "n_residuals": len(result.residuals),
            "control_status": control.status,
            "control_quote_usd": control.quote_usd,
            "control_is_trade": control.status.is_trade,
        }

    return case, run


# ================================================================================
# 12. Internal Transfer
# ================================================================================


def _build_internal_transfer():
    to_own_wallet = transaction(
        "0x12a",
        [transfer(USDC, OWNER, OWNER_SECOND, 1_000 * ONE_USDC, 0)],
        MATURE_BUY_BLOCK, MATURE_BUY_TS,
    )
    alongside_a_swap = transaction(
        "0x12b",
        [
            transfer(USDC, OWNER, POOL_A, 1_000 * ONE_USDC, 0),
            transfer(TOKEN, POOL_A, OWNER, 500 * ONE_TOKEN, 1),
            transfer(WETH, OWNER, OWNER_SECOND, 2 * ONE_WETH, 2),
        ],
        MATURE_BUY_BLOCK + 1, MATURE_BUY_TS + 12,
    )
    self_transfer_and_swap = transaction(
        "0x12c",
        [
            transfer(USDC, OWNER, OWNER, 1_000 * ONE_USDC, 0),
            transfer(USDC, OWNER, POOL_A, 1_000 * ONE_USDC, 1),
            transfer(TOKEN, POOL_A, OWNER, 500 * ONE_TOKEN, 2),
        ],
        MATURE_BUY_BLOCK + 2, MATURE_BUY_TS + 24,
    )

    case = KnownAnswerCase(
        name="Internal Transfer",
        spec="§4.2, addendum §8",
        derivation=(
            "(a) Owner moves 1,000,000,000 raw USDC to a second address they control. One leg",
            "    survives, $1,000, with nothing on the other side of it. There is no counterparty",
            "    leg, so there is no trade to express: ABOVE_TOLERANCE_RESIDUAL, quote_usd is the",
            "    $1,000 of volume that moved, and it goes to the reconciliation queue. Booking a",
            "    wallet-to-wallet move as a sell would invent a disposal that never happened.",
            "(b) The same move alongside a genuine swap. Three legs survive: USDC -$1,000,",
            "    TOKEN +500e18, WETH -$6,000. A trade has two endpoints and picking two of three",
            "    would be a guess, so: NO_CLEAR_ENDPOINT with quote_usd = the largest priceable",
            "    one-way flow, $6,000. Refused, not approximated.",
            "(c) A transfer from the owner to the owner. It moves nothing, so it is dropped before",
            "    the sum: adding it to both sides nets to zero but inflates the one-way flow, and a",
            "    large enough self-move makes a real endpoint look like a vanishing fraction of its",
            "    own gross. The accompanying swap is still a clean VALID_BUY for $1,000 — not",
            "    $2,000, which is what counting the self-move would have produced.",
        ),
        inputs={
            "to_own_wallet": to_own_wallet,
            "alongside_a_swap": alongside_a_swap,
            "self_transfer_and_swap": self_transfer_and_swap,
            "prices": dict(PRICES),
        },
        expected={
            "a_status": ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL,
            "a_quote_usd": Decimal("1000"),
            "a_is_trade": False,
            "b_status": ClassificationStatus.NO_CLEAR_ENDPOINT,
            "b_quote_usd": Decimal("6000"),
            "b_is_trade": False,
            "c_status": ClassificationStatus.VALID_BUY,
            "c_sold_raw_amount": 1_000_000_000,
            "c_quote_usd": Decimal("1000"),
            "c_bought_raw_amount": 500 * ONE_TOKEN,
        },
    )

    def run(inputs):
        a, b, c = stage_net(
            (inputs["to_own_wallet"], inputs["alongside_a_swap"],
             inputs["self_transfer_and_swap"]),
            inputs["prices"],
        )
        return {
            "a_status": a.status,
            "a_quote_usd": a.quote_usd,
            "a_is_trade": a.status.is_trade,
            "b_status": b.status,
            "b_quote_usd": b.quote_usd,
            "b_is_trade": b.status.is_trade,
            "c_status": c.status,
            "c_sold_raw_amount": c.sold_raw_amount,
            "c_quote_usd": c.quote_usd,
            "c_bought_raw_amount": c.bought_raw_amount,
        }

    return case, run


# ================================================================================
# 13. Multiple Pools for One Token
# ================================================================================

#: POOL_B opens 100,000 blocks after the token started trading in POOL_A. A trade in POOL_B is
#: therefore a trade in a *new pool* and an *old token*, and §4.7 measures the token.
SECOND_POOL_START_BLOCK = TOKEN_START_BLOCK + 100_000
SECOND_POOL_START_TS = TOKEN_START_TS + 399_000
SPLIT_ROUTE_BLOCK = SECOND_POOL_START_BLOCK + 50
SPLIT_ROUTE_TS = TOKEN_START_TS + 400_000


def _build_multiple_pools_for_one_token():
    split_route = transaction(
        "0x13a",
        [
            transfer(USDC, OWNER, POOL_A, 600 * ONE_USDC, 0),
            transfer(TOKEN, POOL_A, OWNER, 300 * ONE_TOKEN, 1),
            transfer(USDC, OWNER, POOL_B, 400 * ONE_USDC, 2),
            transfer(TOKEN, POOL_B, OWNER, 180 * ONE_TOKEN, 3),
        ],
        SPLIT_ROUTE_BLOCK, SPLIT_ROUTE_TS,
    )

    case = KnownAnswerCase(
        name="Multiple Pools for One Token",
        spec="§4.2 (split routes), §4.7 (first qualifying pool)",
        derivation=(
            "One transaction fills the same token across two pools: 600 USDC into POOL_A for",
            "300e18, 400 USDC into POOL_B for 180e18.",
            "Per-hop reading would book two buys of one token, double-counting the wallet's",
            "activity and halving each trade's size. Netting by (transaction, owner, token) gives",
            "one buy: USDC -1,000,000,000 raw = $1,000, TOKEN +480e18 raw.",
            "pool is None, deliberately: the buy has no single pool, and naming one would satisfy",
            "§4.1's 'attributable to a specific pool' with a fiction.",
            "Age: the token's trading start is POOL_A's, block 18,000,000 / ts 1,700,000,000, and",
            "§4.7 says the *first* qualifying pool. The trade is at block 18,100,050 / ts",
            "1,700,400,000: block age 100,050 and time age 400,000 s >= 86,400 -> bucket D.",
            "Measured from POOL_B's own start instead (block 18,100,000 / ts 1,700,399,000) the",
            "block age would be 50 and the time age 1,000 s, giving bucket B — a first-hour",
            "purchase the wallet never made, and one that feeds the Edge Origin condition.",
        ),
        inputs={
            "split_route": split_route,
            "prices": dict(PRICES),
            "token_start_block": TOKEN_START_BLOCK,
            "token_start_ts": TOKEN_START_TS,
            "second_pool_start_block": SECOND_POOL_START_BLOCK,
            "second_pool_start_ts": SECOND_POOL_START_TS,
        },
        expected={
            "status": ClassificationStatus.VALID_BUY,
            "bought_raw_amount": 480 * ONE_TOKEN,
            "sold_raw_amount": 1_000_000_000,
            "quote_usd": Decimal("1000"),
            "pool": None,
            "n_results": 1,
            "bucket_from_token_start": TokenAgeBucket.D,
            "bucket_if_measured_from_second_pool": TokenAgeBucket.B,
        },
    )

    def run(inputs):
        results = stage_net((inputs["split_route"],), inputs["prices"])
        result = results[0]
        correct = stage_age(results, inputs["token_start_block"], inputs["token_start_ts"])[0]
        wrong = stage_age(
            results, inputs["second_pool_start_block"], inputs["second_pool_start_ts"]
        )[0]
        return {
            "status": result.status,
            "bought_raw_amount": result.bought_raw_amount,
            "sold_raw_amount": result.sold_raw_amount,
            "quote_usd": result.quote_usd,
            "pool": result.pool,
            "n_results": len(results),
            "bucket_from_token_start": correct,
            "bucket_if_measured_from_second_pool": wrong,
        }

    return case, run


# ================================================================================
# 14. Pool Migration
# ================================================================================


def _build_pool_migration():
    drained_primary = pool(
        POOL_A, OPEN_POOL_ASSET_RESERVE, DEAD_POOL_QUOTE_RESERVE,
        last_swap_block=HORIZON_BLOCK - BLOCKS_PER_30_DAYS,
        last_swap_timestamp=HORIZON_TS - HORIZON_SECONDS,
    )
    replacement = pool(
        POOL_MIGRATED, OPEN_POOL_ASSET_RESERVE, OPEN_POOL_QUOTE_RESERVE,
        last_swap_block=HORIZON_BLOCK - 300,
        last_swap_timestamp=HORIZON_TS - HOUR_SECONDS,
    )

    case = KnownAnswerCase(
        name="Pool Migration",
        spec="§4.7 (migration does not reset age), addendum §9.1 condition 3, §9.2",
        derivation=(
            "The token's liquidity has moved. The original pool is drained ($1 of quote) and has",
            "not traded for exactly 30 days; a new pool holding $2,000,000 traded an hour ago,",
            "quotes the same token, and quotes it in the same asset.",
            "Conditions 1 and 2 both hold on the primary, so the *only* thing between this",
            "position and a -100% is condition 3 — and a validated replacement exists.",
            "  same asset, different address, an observed swap, trading within 30 days, and a",
            "  modellable reserve pair  -> replacement_validated",
            "The exit is priced where the liquidity actually is: 1e21 x [9970 x 2e12 /",
            "(10000 x 1e24 + 9970 x 1e21)] x 1e-6 = $1,992.0139620798064329863126462916472277.",
            "Status MIGRATED, basis POOL_MARKED, and value_usd equal to the day-30 mark of case 5",
            "— the same geometry priced at the same horizon, which is the check that the venue",
            "switch changed the venue and nothing else.",
            "The control drops the replacement and changes nothing else: all three conditions now",
            "hold and the position is DEAD_ZEROED at exactly $0.",
            "Age: the trade sits at block 18,100,050 / ts 1,700,400,000 against the token's",
            "original start — bucket D. The migration does not reset it, so the token does not",
            "re-enter the first hour by changing pools.",
        ),
        inputs={
            "primary": drained_primary,
            "replacement": replacement,
            "remaining_raw": OPEN_POSITION_RAW,
            "horizon_block": HORIZON_BLOCK,
            "horizon_ts": HORIZON_TS,
            "quote_usd": QUOTE_USD_PER_RAW_USDC,
            "trade_block": SPLIT_ROUTE_BLOCK,
            "trade_ts": SPLIT_ROUTE_TS,
            "token_start_block": TOKEN_START_BLOCK,
            "token_start_ts": TOKEN_START_TS,
        },
        expected={
            "value_usd": OPEN_POSITION_MARK,
            "value_basis": ValueBasis.POOL_MARKED,
            "pool_status": PoolStatus.MIGRATED,
            "executable_quantity": OPEN_POSITION_RAW,
            "venue": POOL_MIGRATED,
            "venue_is_replacement": "true",
            "cond1_no_swap_for_30d": "true",
            "cond2_exit_below_minimum": "false",
            "cond3_no_validated_replacement": "false",
            "replacement_validated": True,
            "control_value_usd": Decimal("0"),
            "control_value_basis": ValueBasis.DEAD_ZEROED,
            "control_pool_status": PoolStatus.DEAD,
            "bucket_after_migration": TokenAgeBucket.D,
        },
    )

    def run(inputs):
        value = stage_mark(
            inputs["remaining_raw"], inputs["primary"], inputs["horizon_block"],
            inputs["horizon_ts"], inputs["quote_usd"], replacement_pool=inputs["replacement"],
        )
        evidence = _evidence_map(value)
        control = stage_mark(
            inputs["remaining_raw"], inputs["primary"], inputs["horizon_block"],
            inputs["horizon_ts"], inputs["quote_usd"],
        )
        return {
            "value_usd": value.value_usd,
            "value_basis": value.value_basis,
            "pool_status": value.pool_status,
            "executable_quantity": value.executable_quantity,
            "venue": evidence["venue"],
            "venue_is_replacement": evidence["venue_is_replacement"],
            "cond1_no_swap_for_30d": evidence["cond1_no_swap_for_30d"],
            "cond2_exit_below_minimum": evidence["cond2_exit_below_minimum"],
            "cond3_no_validated_replacement": evidence["cond3_no_validated_replacement"],
            "replacement_validated": any(
                item == "replacement_validated:{}".format(POOL_MIGRATED)
                for item in value.evidence
            ),
            "control_value_usd": control.value_usd,
            "control_value_basis": control.value_basis,
            "control_pool_status": control.pool_status,
            "bucket_after_migration": token_age_bucket(
                inputs["trade_block"], inputs["trade_ts"],
                inputs["token_start_block"], inputs["token_start_ts"],
            ),
        }

    return case, run


# ================================================================================
# 15. First-Hour Classification
# ================================================================================


def _build_first_hour_classification():
    first_hour_buy = transaction(
        "0x15a",
        [
            transfer(USDC, OWNER, POOL_A, 1_000 * ONE_USDC, 0),
            transfer(TOKEN, POOL_A, OWNER, 1_000 * ONE_TOKEN, 1),
        ],
        TOKEN_START_BLOCK + 3, TOKEN_START_TS + 30,
    )
    mature_buy = transaction(
        "0x15b",
        [
            transfer(USDC, OWNER, POOL_A, 1_000 * ONE_USDC, 0),
            transfer(TOKEN, POOL_A, OWNER, 200 * ONE_TOKEN, 1),
        ],
        TOKEN_START_BLOCK + 50_000, TOKEN_START_TS + 600_000,
    )

    #: Every §4.7 boundary, from both sides, against the absolute literals 10 blocks / 3,600 s /
    #: 86,400 s. A probe expressed as ``BUCKET_A_BLOCKS - 1`` would move with the constant.
    probes = (
        (TOKEN_START_BLOCK + 0, TOKEN_START_TS + 0),
        (TOKEN_START_BLOCK + 9, TOKEN_START_TS + 5),
        (TOKEN_START_BLOCK + 9, TOKEN_START_TS + 90_000),
        (TOKEN_START_BLOCK + 10, TOKEN_START_TS + 120),
        (TOKEN_START_BLOCK + 10, TOKEN_START_TS + 3_599),
        (TOKEN_START_BLOCK + 10, TOKEN_START_TS + 3_600),
        (TOKEN_START_BLOCK + 10, TOKEN_START_TS + 86_399),
        (TOKEN_START_BLOCK + 10, TOKEN_START_TS + 86_400),
    )

    case = KnownAnswerCase(
        name="First-Hour Classification",
        spec="§4.7",
        derivation=(
            "Buckets are half-open and exhaustive, measured from the token's trading start:",
            "  A  block age  < 10",
            "  B  block age >= 10 and time age <  3,600",
            "  C                    time age <  86,400",
            "  D                    time age >= 86,400",
            "The probes sit on each boundary from both sides at the exact block and the exact",
            "second: 9 vs 10 blocks, 3,599 vs 3,600 s, 86,399 vs 86,400 s.",
            "(block age 9, time age 90,000 s) is A and not D. Bucket A is defined in blocks and",
            "tested first, so a chain that stalled for 25 hours inside the first ten blocks does",
            "not silently redefine FIRST_HOUR_BUCKETS after the fact.",
            "Scoring: two buys of $1,000 each. The first is in bucket A and returned +0.5; the",
            "second is in bucket D and returned -0.1.",
            "  w = ln(1001) = 6.9087547793152205852207837629736276343 for both.",
            "  buy_quality = (w x 0.5 + w x -0.1)/(w + w) = 0.2 exactly.",
            "  bucket A weight share = w/(w+w) = 0.49999999999999999999999999999999999999.",
            "    Not 0.5: w + w carries 39 digits and is rounded to 38 before the division.",
            "  bucket A value = (w x 0.5)/w = 0.50000000000000000000000000000000000001, the same",
            "    rounding in the other direction. A single-element weighted mean is not the",
            "    identity at 38 digits and the battery pins what the frozen policy produces.",
            "  bucket D value = (w x -0.1)/w = -0.1 exactly.",
            "  realized 1,500 of 2,400 = 0.625; marked 900 of 2,400 = 0.375; dead 0.",
            "First-hour weight share = bucket A + bucket B = A alone here, since B is empty.",
        ),
        inputs={
            "first_hour_buy": first_hour_buy,
            "mature_buy": mature_buy,
            "probes": probes,
            "token_start_block": TOKEN_START_BLOCK,
            "token_start_ts": TOKEN_START_TS,
            "prices": dict(PRICES),
            "first_hour_return": Decimal("0.5"),
            "mature_return": Decimal("-0.1"),
            "first_hour_realized_usd": Decimal("1500"),
            "mature_marked_usd": Decimal("900"),
        },
        expected={
            "probe_buckets": (
                TokenAgeBucket.A, TokenAgeBucket.A, TokenAgeBucket.A, TokenAgeBucket.B,
                TokenAgeBucket.B, TokenAgeBucket.C, TokenAgeBucket.C, TokenAgeBucket.D,
            ),
            "first_hour_bucket": TokenAgeBucket.A,
            "mature_bucket": TokenAgeBucket.D,
            "buy_quality": Decimal("0.2"),
            "bucket_a_weight_share": Decimal("0.49999999999999999999999999999999999999"),
            "bucket_a_value": Decimal("0.50000000000000000000000000000000000001"),
            "bucket_d_value": Decimal("-0.1"),
            "bucket_b_present": False,
            "bucket_c_present": False,
            "realized_share": Decimal("0.625"),
            "marked_share": Decimal("0.375"),
            "dead_share": Decimal("0"),
            "n_buys": 2,
        },
    )

    def run(inputs):
        buys = stage_net((inputs["first_hour_buy"], inputs["mature_buy"]), inputs["prices"])
        buckets = stage_age(buys, inputs["token_start_block"], inputs["token_start_ts"])
        probe_buckets = tuple(
            token_age_bucket(block, ts, inputs["token_start_block"], inputs["token_start_ts"])
            for block, ts in inputs["probes"]
        )
        outcomes = (
            buy_outcome(
                buys[0], trade_value_usd=buys[0].quote_usd,
                return_pct=inputs["first_hour_return"],
                realized_usd=inputs["first_hour_realized_usd"], bucket=buckets[0],
            ),
            buy_outcome(
                buys[1], trade_value_usd=buys[1].quote_usd,
                return_pct=inputs["mature_return"],
                marked_usd=inputs["mature_marked_usd"], bucket=buckets[1],
            ),
        )
        quality = stage_score(outcomes).quality
        return {
            "probe_buckets": probe_buckets,
            "first_hour_bucket": buckets[0],
            "mature_bucket": buckets[1],
            "buy_quality": quality.value,
            "bucket_a_weight_share": quality.bucket_weights[TokenAgeBucket.A],
            "bucket_a_value": quality.bucket_values[TokenAgeBucket.A],
            "bucket_d_value": quality.bucket_values[TokenAgeBucket.D],
            "bucket_b_present": TokenAgeBucket.B in quality.bucket_values,
            "bucket_c_present": TokenAgeBucket.C in quality.bucket_values,
            "realized_share": quality.realized_share,
            "marked_share": quality.marked_share,
            "dead_share": quality.dead_share,
            "n_buys": quality.n_buys,
        }

    return case, run


# ================================================================================
# 16. End-of-Window 30-Day Extension
# ================================================================================

#: A four-week evaluation window. The buy lands five days before it closes, so its 30-day horizon
#: falls 25 days *outside* the window.
WINDOW_START_TS = TOKEN_START_TS
WINDOW_END_TS = TOKEN_START_TS + 28 * DAY_SECONDS
LATE_BUY_TS = WINDOW_END_TS - 5 * DAY_SECONDS
LATE_BUY_BLOCK = TOKEN_START_BLOCK + 165_600
LATE_HORIZON_TS = LATE_BUY_TS + HORIZON_SECONDS
LATE_HORIZON_BLOCK = LATE_BUY_BLOCK + BLOCKS_PER_30_DAYS

#: Deliberately the same pool geometry and the same position size as case 5, so the mark is the
#: same number arrived at through a different rule. If the two ever disagree, something other than
#: the horizon moved.
LATE_POSITION_RAW = OPEN_POSITION_RAW
LATE_POSITION_MARK = OPEN_POSITION_MARK
LATE_POSITION_RETURN = Decimal("0.9920139620798064329863126462916472277")


def _build_end_of_window_extension():
    late_buy = transaction(
        "0x16a",
        [
            transfer(USDC, OWNER, POOL_A, 1_000 * ONE_USDC, 0),
            transfer(TOKEN, POOL_A, OWNER, LATE_POSITION_RAW, 1),
        ],
        LATE_BUY_BLOCK, LATE_BUY_TS,
    )
    pool_at_horizon = pool(
        POOL_A, OPEN_POOL_ASSET_RESERVE, OPEN_POOL_QUOTE_RESERVE,
        last_swap_block=LATE_HORIZON_BLOCK - 100,
        last_swap_timestamp=LATE_HORIZON_TS - 1_200,
    )
    #: One second past the horizon. §4.8 permits measurement to run past the window; it permits
    #: nothing to run past the *horizon*, and the two are different rules.
    pool_after_horizon = pool(
        POOL_A, OPEN_POOL_ASSET_RESERVE, OPEN_POOL_QUOTE_RESERVE,
        last_swap_block=LATE_HORIZON_BLOCK,
        last_swap_timestamp=LATE_HORIZON_TS + 1,
    )

    case = KnownAnswerCase(
        name="End-of-Window 30-Day Extension",
        spec="§4.8",
        derivation=(
            "Window: ts 1,700,000,000 to 1,702,419,200 (28 days). The buy is at 1,701,987,200,",
            "five days before the window closes.",
            "§4.8: the 30-day measurement is permitted to extend past the end of the window. No",
            "sample is dropped and no partial return is used.",
            "  horizon_ts        = 1,701,987,200 + 2,592,000 = 1,704,579,200",
            "  horizon - window  = 2,160,000 s = 25 days *outside* the window",
            "  buy is retained: n_outcomes = 1.",
            "Marking at that horizon uses case 5's pool and position exactly, so the mark is the",
            "same number reached by a different route:",
            "  spot        = 1e21 x (2e12/1e24) x 1e-6 = $2,000 exactly",
            "  extractable = $1,992.0139620798064329863126462916472277 (38 digits)",
            "  return      = 1992.0139620798064329863126462916472277/1000 - 1",
            "              = 0.9920139620798064329863126462916472277 (37 digits)",
            "  buy_quality = (ln(1001) x return)/ln(1001)",
            "              = 0.99201396207980643298631264629164722770 (38 digits). The extra",
            "                trailing zero is scale, not value: the two compare equal, and the",
            "                canonical form normalises it away.",
            "A truncated 25-day measurement would have marked against a different pool state and",
            "produced a different number, which is exactly the incomparability §4.8 removes.",
            "The look-ahead control dates the pool one second after the horizon. §4.8 extends the",
            "measurement window, not the horizon, so that raises LookAheadViolation.",
        ),
        inputs={
            "late_buy": late_buy,
            "pool_at_horizon": pool_at_horizon,
            "pool_after_horizon": pool_after_horizon,
            "prices": dict(PRICES),
            "window_start_ts": WINDOW_START_TS,
            "window_end_ts": WINDOW_END_TS,
            "horizon_seconds": HORIZON_SECONDS,
            "horizon_block": LATE_HORIZON_BLOCK,
            "quote_usd": QUOTE_USD_PER_RAW_USDC,
        },
        expected={
            "buy_status": ClassificationStatus.VALID_BUY,
            "buy_ts": LATE_BUY_TS,
            "buy_is_inside_window": True,
            "horizon_ts": LATE_HORIZON_TS,
            "horizon_seconds_past_window_end": 2_160_000,
            "horizon_is_past_window_end": True,
            "n_outcomes": 1,
            "value_usd": LATE_POSITION_MARK,
            "value_basis": ValueBasis.POOL_MARKED,
            "pool_status": PoolStatus.LIVE,
            "spot_usd": Decimal("2000"),
            "return_pct": LATE_POSITION_RETURN,
            "buy_quality": LATE_POSITION_RETURN,
            "marked_share": Decimal("1"),
            "realized_share": Decimal("0"),
            "look_ahead_refused": True,
        },
        raises={
            "look_ahead_refused": "contracts.LookAheadViolation — a pool snapshot dated after the "
                                  "30-day horizon may not price the mark",
        },
    )

    def run(inputs):
        buy = stage_net((inputs["late_buy"],), inputs["prices"])[0]
        horizon_ts = buy.timestamp + inputs["horizon_seconds"]
        value = stage_mark(
            buy.bought_raw_amount, inputs["pool_at_horizon"], inputs["horizon_block"],
            horizon_ts, inputs["quote_usd"],
        )
        evidence = _evidence_map(value)
        return_pct = _return_against_cost(value.value_usd, buy.quote_usd)
        outcomes = (
            buy_outcome(
                buy, trade_value_usd=buy.quote_usd, return_pct=return_pct,
                marked_usd=value.value_usd, bucket=TokenAgeBucket.D,
            ),
        )
        quality = stage_score(outcomes).quality

        look_ahead_refused = False
        try:
            stage_mark(
                buy.bought_raw_amount, inputs["pool_after_horizon"], inputs["horizon_block"],
                horizon_ts, inputs["quote_usd"],
            )
        except LookAheadViolation:
            look_ahead_refused = True

        return {
            "buy_status": buy.status,
            "buy_ts": buy.timestamp,
            "buy_is_inside_window": inputs["window_start_ts"] <= buy.timestamp
                                    <= inputs["window_end_ts"],
            "horizon_ts": horizon_ts,
            "horizon_seconds_past_window_end": horizon_ts - inputs["window_end_ts"],
            "horizon_is_past_window_end": horizon_ts > inputs["window_end_ts"],
            "n_outcomes": len(outcomes),
            "value_usd": value.value_usd,
            "value_basis": value.value_basis,
            "pool_status": value.pool_status,
            "spot_usd": Decimal(evidence["spot_usd"]),
            "return_pct": return_pct,
            "buy_quality": quality.value,
            "marked_share": quality.marked_share,
            "realized_share": quality.realized_share,
            "look_ahead_refused": look_ahead_refused,
        }

    return case, run


def _return_against_cost(value_usd, cost_usd):
    """§4.4 case 2's return: marked value over allocated buy cost, minus one.

    Routed through the seam's primitives. ``divide(...) - 1`` would run the subtraction in the
    caller's ambient context against a value carried at 38 digits, which is the defect
    ``contracts.numeric.sub`` exists to remove — and it is the defect that shipped in
    ``LotConsumption.realized_return``, so writing it here would reintroduce it on the one path
    that has no seam type to catch it.
    """
    return sub(divide(value_usd, cost_usd), Decimal("1"))


# ================================================================================
# the battery
# ================================================================================

#: The §9.3 list, verbatim and in the order the pre-registration prints it. This tuple is the
#: definition of completeness: :mod:`tests.known_answer.test_integration` requires the battery to
#: hold exactly these sixteen, so a battery cannot quietly shrink.
REQUIRED_CASE_NAMES = (
    "Simple Buy + Full Sell",
    "Multiple Buys + Partial Sell",
    "Multi-hop Buy",
    "FIFO Allocation",
    "Open Position at Day 30",
    "Dead Pool",
    "Thin but Live Pool",
    "Liquidity-Bound Marking",
    "Fee-on-Transfer Token",
    "Failed Transaction",
    "Circular Arbitrage",
    "Internal Transfer",
    "Multiple Pools for One Token",
    "Pool Migration",
    "First-Hour Classification",
    "End-of-Window 30-Day Extension",
)

_BUILDERS = (
    _build_simple_buy_full_sell,
    _build_multiple_buys_partial_sell,
    _build_multi_hop_buy,
    _build_fifo_allocation,
    _build_open_position_at_day_30,
    _build_dead_pool,
    _build_thin_but_live_pool,
    _build_liquidity_bound_marking,
    _build_fee_on_transfer_token,
    _build_failed_transaction,
    _build_circular_arbitrage,
    _build_internal_transfer,
    _build_multiple_pools_for_one_token,
    _build_pool_migration,
    _build_first_hour_classification,
    _build_end_of_window_extension,
)

_BUILT = tuple(builder() for builder in _BUILDERS)

BATTERY = tuple(case for case, _runner in _BUILT)
RUNNERS = {case.name: runner for case, runner in _BUILT}


def case_named(name):
    for case in BATTERY:
        if case.name == name:
            return case
    raise KeyError("no known-answer case named {!r}".format(name))


# -- the harness -----------------------------------------------------------------


@dataclass(frozen=True)
class CaseResult:
    """One case's verdict. There is no third state: a case passed or it did not."""

    name: str
    passed: bool
    failures: Tuple[str, ...] = ()
    error: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "failures", tuple(self.failures))
        if self.passed and (self.failures or self.error):
            raise ValueError(
                "{} is recorded as passed while carrying failures; a verdict and its explanation "
                "cannot disagree".format(self.name)
            )
        if not self.passed and not (self.failures or self.error):
            raise ValueError(
                "{} failed without saying why. §9.3 forbids waiving a failing case, and an "
                "unexplained failure is the easiest thing in the world to waive".format(self.name)
            )


def run_case(case):
    """Execute one case's composition and return the observed facts, keyed like ``expected``."""
    return RUNNERS[case.name](case.inputs)


def evaluate_case(case):
    """Compare observed against the frozen answer, key by key."""
    try:
        observed = run_case(case)
    except Exception as exc:  # noqa: BLE001 — a crash is a failed case, never a skipped one
        return CaseResult(
            name=case.name, passed=False,
            error="{}: {}".format(type(exc).__name__, exc),
        )

    failures = []
    for key in sorted(case.expected):
        if key not in observed:
            failures.append("{}: not produced by the pipeline".format(key))
            continue
        expected, actual = case.expected[key], observed[key]
        if not _answers_match(expected, actual):
            failures.append("{}: expected {!r}, observed {!r}".format(key, expected, actual))
    for key in sorted(observed):
        if key not in case.expected:
            failures.append("{}: produced but not pre-registered".format(key))

    return CaseResult(name=case.name, passed=not failures, failures=tuple(failures))


def _answers_match(expected, actual):
    """Equality, with booleans held apart from the integers they compare equal to.

    ``Decimal("2000.000000") == Decimal("2000")`` is True and is the same answer — the scale is
    cosmetic and the canonical form normalises it away. ``True == 1`` is also True and is *not* the
    same answer: a case expecting ``mark_is_below_whole_pool`` to be a fact would otherwise be
    satisfied by a count of one.
    """
    if isinstance(expected, bool) != isinstance(actual, bool):
        return False
    return expected == actual


def battery_report():
    """Pass/fail per case, plus the ``known_answer_pass_rate`` §9.8 gates on.

    The rate is a fraction of the **required** sixteen, not of whatever happens to be registered,
    so a battery that lost a case reports a rate below 1 rather than a perfect score over fifteen.
    """
    results = tuple(evaluate_case(case) for case in BATTERY)
    passed = sum(1 for r in results if r.passed)
    return {
        "results": results,
        "passed": passed,
        "total": len(REQUIRED_CASE_NAMES),
        "known_answer_pass_rate": divide(passed, len(REQUIRED_CASE_NAMES)),
        "fixture_hash": known_answer_fixture_hash(),
    }


# -- the freeze manifest entry ---------------------------------------------------


def canonical_battery(battery=None):
    """The battery's canonical form: name, spec reference, inputs, and the frozen answers.

    ``derivation`` is excluded. It is prose explaining a number, and re-freezing the experiment
    because a comment was reworded would make the hash mean less, not more — §9.6 pins the inputs
    and the answers, which is what a later run has to reproduce.

    The inputs are the real fixture objects, so this hash moves when a Transaction, a PoolState, a
    price, or an expected value moves. That is the property :func:`known_answer_fixture_hash`
    exists to have.
    """
    cases = BATTERY if battery is None else tuple(battery)
    return tuple(
        {
            "name": case.name,
            "spec": case.spec,
            "inputs": case.inputs,
            "expected": case.expected,
            "raises": case.raises,
        }
        for case in cases
    )


def known_answer_fixture_hash(battery=None):
    """§9.6's ``known_answer_fixture_hash``. Recorded in the freeze manifest and checked there."""
    return canonical_hash(canonical_battery(battery))
