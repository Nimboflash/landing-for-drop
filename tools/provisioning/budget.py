"""The projected data cost for Phase 0, and the ceiling it is measured against.

Pre-registration §5, transcribed. Money is ``Decimal`` under the frozen context — every value here
goes through :func:`contracts.numeric.calc`, which rejects a float on sight. That is not ceremony
for three-digit numbers: it is the same rule as the rest of the repository, and the moment budget
arithmetic gets an exemption is the moment someone writes ``349.0`` and the register starts
carrying doubles.

The entry that matters is the one with no number. The archival RPC is **unpriced** — the source
table records "—", not "$0". Those are different claims: $0 says someone checked and it is free;
"—" says nobody has bought anything, which is precisely why ticket 03 calls it "the one source
with no invoice attached and therefore the one most likely to be assumed rather than provisioned".
So an unpriced source contributes nothing to the total *and* is reported separately, and it can
still block approval by failing its probe — cost and provisioning are independent facts.

    dune               $349/mo    Dune Plus — dex.trades + aggregator tables
    coingecko_onchain  $129/mo    CoinGecko Onchain, Analyst tier
    binance_klines     $0/mo      data.binance.vision, free and unauthenticated
    archival_rpc       unpriced   no invoice attached — the thing this ticket exists to catch
    -----------------------------------------------------------------------------
    projected total    $478/mo    against a $1,000/mo ceiling; headroom $522/mo
"""

from contracts.numeric import add, calc, divide, sub

#: The ceiling from pre-registration §5. Monthly, in USD.
CEILING_USD = calc("1000")

CURRENCY = "USD"
PERIOD = "monthly"


class BudgetLine(object):
    """One source's recurring cost, or the explicit absence of one.

    ``monthly_usd=None`` means unpriced — no invoice attached. It is not zero, and it must not be
    summed as though it were.
    """

    __slots__ = ("source", "monthly_usd", "tier", "note")

    def __init__(self, source, monthly_usd, tier, note):
        self.source = source
        # calc() refuses float; a money literal is a str or an int, here as everywhere.
        self.monthly_usd = None if monthly_usd is None else calc(monthly_usd)
        self.tier = tier
        self.note = note

    @property
    def is_priced(self):
        return self.monthly_usd is not None

    def as_dict(self):
        return {
            "source": self.source,
            "monthly_usd": None if self.monthly_usd is None else str(self.monthly_usd),
            "tier": self.tier,
            "note": self.note,
        }


BUDGET_LINES = (
    BudgetLine(
        "dune",
        "349",
        "Plus",
        "dex.trades plus aggregator tables, as netting input",
    ),
    BudgetLine(
        "coingecko_onchain",
        "129",
        "Analyst",
        "pool-level OHLCV and dead-token marks, include_inactive_source=true",
    ),
    BudgetLine(
        "binance_klines",
        "0",
        "public",
        "quote-asset USD reference; free and unauthenticated, data.binance.vision",
    ),
    BudgetLine(
        "archival_rpc",
        None,
        "unpriced",
        "no invoice attached: the source most likely to be assumed rather than provisioned",
    ),
)


def priced_lines(lines=BUDGET_LINES):
    return tuple(line for line in lines if line.is_priced)


def unpriced_sources(lines=BUDGET_LINES):
    return tuple(line.source for line in lines if not line.is_priced)


def projected_total(lines=BUDGET_LINES):
    """Sum of the priced lines. 349 + 129 + 0 = 478."""
    total = calc(0)
    for line in priced_lines(lines):
        total = add(total, line.monthly_usd)
    return total


def headroom(lines=BUDGET_LINES, ceiling=CEILING_USD):
    """Ceiling minus projected total. 1000 - 478 = 522."""
    return sub(ceiling, projected_total(lines))


def utilisation(lines=BUDGET_LINES, ceiling=CEILING_USD):
    """Fraction of the ceiling committed. 478 / 1000 = 0.478.

    Not quantized: §"reporting" is the only place quantization is permitted, and the register is
    not a report — it is the input to one.
    """
    return divide(projected_total(lines), ceiling)


def within_ceiling(lines=BUDGET_LINES, ceiling=CEILING_USD):
    return projected_total(lines) <= calc(ceiling)


def as_dict(lines=BUDGET_LINES, ceiling=CEILING_USD):
    return {
        "currency": CURRENCY,
        "period": PERIOD,
        "ceiling": str(calc(ceiling)),
        "projected_total": str(projected_total(lines)),
        "headroom": str(headroom(lines, ceiling)),
        "utilisation": str(utilisation(lines, ceiling)),
        "within_ceiling": within_ceiling(lines, ceiling),
        "unpriced_sources": list(unpriced_sources(lines)),
        "lines": [line.as_dict() for line in lines],
    }
