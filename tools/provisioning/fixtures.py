"""The named things each probe must prove *against*.

A probe is only as good as the thing it asks for. "Did the API answer?" is answered by any URL;
"did it return trades for blocks 16,308,190–16,309,190?" is answered only by a warehouse that has
actually decoded those blocks. So the targets live here, named, with the reason each was chosen.

**Why block numbers and not transaction hashes.** A block number inside window 1 is a fact that can
be derived and checked from the chain itself — 16,308,190 is the first block of 1 Jan 2023 UTC to
within a few blocks, and any thousand-block span of Ethereum mainnet in 2023 contains DEX trades and
aggregator settlements. A transaction *hash* cannot be derived; it can only be copied from a block
explorer. Pasting one from memory into a provisioning check would be inventing the very evidence the
check exists to produce, so the archival probe instead names its transaction **by construction** —
"the first transaction in block N carrying event logs" — and records the hash it actually found in
the evidence. The result is the same single named historical transaction, arrived at without anyone
asserting a hash they had not looked up. ``ETH_ARCHIVAL_PROBE_TX`` pins an explicit hash when an
operator does have one in hand.

**Why the dead pool is not hardcoded.** The CoinGecko probe must prove candles come back for a pool
*known to be dead* — a live pool proves nothing, since live pools return candles with or without
``include_inactive_source``. Deadness is a property of the world on the day the probe runs, not a
constant, so the probe **verifies it from the pool's own metadata** (no 24h volume, no 24h
transactions) before treating the candles as proof, and reports INSUFFICIENT if the candidate turns
out to be alive. Candidates are supplied by the operator via ``COINGECKO_DEAD_POOL_CANDIDATES``
because naming one requires looking at a chain explorer, which is exactly the work this module
refuses to fake. The probe tells you so, by name, when none is configured.
"""

import os

# -- window 1 -------------------------------------------------------------------
#
# Window 1 trains on Jan–Jun 2023 (§6.3). The range below is ~1,000 blocks (about 3.4 hours) from
# the first day of the window: wide enough that both dex.trades and the aggregator tables certainly
# contain settlements, narrow enough that the query is cheap and its result is legible.

WINDOW_1_LABEL = "window 1 train (Jan-Jun 2023)"
BLOCK_RANGE_START = 16308190
BLOCK_RANGE_END = 16309190
BLOCK_RANGE_NOTE = (
    "first ~1,000 blocks of 2023-01-01 UTC on Ethereum mainnet, inside window 1's training half"
)

# -- binance --------------------------------------------------------------------
#
# The quote-asset USD reference. ETH is the quote asset for the large majority of Ethereum DEX
# pools, so ETHUSDT minute klines are what converts a WETH-denominated fill into USD.

BINANCE_SYMBOL = "ETHUSDT"
BINANCE_INTERVAL = "1m"
BINANCE_DAY = "2023-01-05"
#: A full UTC day of minute bars. Fewer than this means the archive is partial for that day, which
#: matters: a missing minute is a missing FX rate for every fill inside it.
BINANCE_EXPECTED_BARS = 1440
BINANCE_MIN_BARS = 1380  # allow for a short venue outage without calling the archive unusable

# -- archival rpc ---------------------------------------------------------------

ARCHIVAL_BLOCK = BLOCK_RANGE_START
ARCHIVAL_BLOCK_NOTE = (
    "state at this height is ~3.5 years old, so serving it requires a genuine archive node and "
    "not a pruned one with a 128-block state window"
)

# -- coingecko ------------------------------------------------------------------

COINGECKO_NETWORK = "eth"
#: How the operator names a candidate: ``network:address``, comma separated.
DEAD_POOL_ENV = "COINGECKO_DEAD_POOL_CANDIDATES"
#: §9.1 marks a pool dead after 30 days without trading. The probe reuses the same threshold rather
#: than inventing a second definition of "dead" that could disagree with the marking rule.
DEAD_INACTIVITY_DAYS = 30


def dead_pool_candidates(env=None):
    """Parse ``network:address`` candidates from the environment. Empty tuple when unset."""
    env = os.environ if env is None else env
    raw = (env.get(DEAD_POOL_ENV) or "").strip()
    if not raw:
        return ()
    out = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            network, address = item.split(":", 1)
        else:
            network, address = COINGECKO_NETWORK, item
        network, address = network.strip(), address.strip()
        if network and address:
            out.append((network, address))
    return tuple(out)


def pinned_archival_tx(env=None):
    """An explicit transaction hash, when the operator has one. ``None`` otherwise."""
    env = os.environ if env is None else env
    value = (env.get("ETH_ARCHIVAL_PROBE_TX") or "").strip()
    return value or None
