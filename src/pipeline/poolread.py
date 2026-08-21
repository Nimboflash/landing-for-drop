"""Read a :class:`contracts.PoolState` off chain at a pinned height.

``marking`` has been ready since it was written; nothing supplied it a pool. Twenty-eight positions
across the four real wallet populations in ``tools/case_runs.py`` are quarantined with *"no pool
state was supplied to mark it"*, which is now the largest remaining loss in the machine.

This module supplies one. It reads, it does not decide: what a mark is worth, whether a pool is
dead, and which valuation basis applies are :mod:`marking`'s to say, and putting any of that here
would make two modules authorities on one question.

Where the address comes from
----------------------------

:mod:`pipeline.pooladdress` computes it from the token pair with no network call, so a position in a
token nobody listed still has a venue to read. That is the same machinery §4.7's token starts are
derived with, and it is verified against both pool addresses this repository had already printed.

What this guarantees, and what it does not
------------------------------------------

**Guaranteed.** Every reading is an ``eth_call`` at a *pinned block number*, never a tag, so the
answer is about the horizon and not about today. The pool's own ``token0()`` decides which reserve
belongs to the asset — attributing them the wrong way round produces a plausible price wrong by the
ratio of the two, and that is a mark, not an error anyone would notice. A pool whose ``fee()``
disagrees with the tier its address was derived for is refused rather than read, because the address
and the pool would then be about different things.

**Not guaranteed.** That the pool being read is the *right* pool for the position. This module reads
the venue it is handed; whether that venue is where the wallet's exit would actually happen is
:mod:`marking`'s §9.1 question, and a pool with reserves is not the same fact as a pool with a
market. Nor does anything here establish that a reading is *fresh*: an archive node answering about
block *b* is trusted to be answering about block *b*, and nothing in this process can check that.

``last_swap_block``, and why it is the weakest field here
---------------------------------------------------------

§9.1's first dead-pool condition is *no swap for 30 days*, so ``last_swap_block`` is not decoration —
it is the evidence for a ``DEAD_ZEROED`` valuation, and a pool wrongly read as dead publishes −100%
on a position that was fine.

Uniswap v2 exposes ``blockTimestampLast`` from ``getReserves()``. **That is the last block the
reserves changed, not the last block a swap happened**: a mint or a burn moves it too. So it is an
*upper bound* on staleness — if it is old, no swap has happened since, and condition one holds. If
it is recent, the reserves moved, but a mint could have moved them.

The direction of that error is the reason it is usable at all. It can only ever make a pool look
*more* recently active than it was, so it can produce a live reading for a dead pool — never a dead
reading for a live one. The first is a mark that should have been a zero; the second would be a
−100% on a healthy position, and that is the one worth being asymmetric about.

The honest alternative is a log scan back thirty days for ``Swap``. At the ten-block range cap every
free endpoint enforces, that is roughly 21,600 requests per pool. It is not refused on principle,
it is unaffordable, and this module states which reading it took rather than substituting the weaker
one silently. :data:`LAST_SWAP_IS_LAST_RESERVE_CHANGE` carries that sentence to anyone who reads a
``PoolState`` this module built.

Uniswap v3 has no equivalent field at all. ``slot0()`` reports a price and a tick, not a time, so a
v3 pool read here carries ``last_swap_block`` from the only place it can be known cheaply — and
where that is nowhere, the read is refused rather than filled with the horizon block, which would
assert perfect freshness about a pool nobody looked at.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from contracts.core import ContractError, normalise_asset
from contracts.metrics import PoolState
from transport.client import block_parameter

from .keccak import function_selector
from .pooladdress import (
    FEE_TIERS,
    UNISWAP_V2,
    UNISWAP_V3,
    Create2Venue,
    pool_address,
    sorted_pair,
)

__all__ = [
    "PoolReadDefect",
    "PoolHasNoCode",
    "PoolSidesDisagree",
    "PoolFeeDisagrees",
    "ReturndataWidth",
    "LastSwapUnknowable",
    "LAST_SWAP_IS_LAST_RESERVE_CHANGE",
    "PoolReading",
    "read_v2_pool",
    "read_pool_for",
]


#: Carried on every ``PoolState`` this module builds for a v2 pool, and quoted in the refusal when
#: a caller asks for something this reading cannot support. Written once, here, so the two places
#: that describe it cannot drift.
LAST_SWAP_IS_LAST_RESERVE_CHANGE = (
    "last_swap_block is getReserves().blockTimestampLast, which is the last block the RESERVES "
    "changed rather than the last block a SWAP happened -- a mint or a burn moves it too. It is an "
    "upper bound on staleness: old means no swap since, recent means the reserves moved and a mint "
    "could have moved them. So it can read a dead pool as live, never a live pool as dead, and the "
    "second error is the one that would publish -100% on a healthy position. The exact reading is "
    "a Swap log scan back 30 days, which is ~21,600 requests per pool at the 10-block range cap "
    "every free endpoint enforces"
)

TOKEN0 = function_selector("token0()")
TOKEN1 = function_selector("token1()")
GET_RESERVES = function_selector("getReserves()")
V3_FEE = function_selector("fee()")
V3_SLOT0 = function_selector("slot0()")
V3_LIQUIDITY = function_selector("liquidity()")

_WORD = 32


class PoolReadDefect(ContractError):
    """A pool reading that cannot be trusted, refused rather than returned."""


class PoolHasNoCode(PoolReadDefect):
    """No contract at the derived address at that height.

    An ``eth_call`` to an address with no code returns empty returndata, which is not the same fact
    as a zero reserve and must never be read as one: an empty answer means *there is no pool here*,
    and a zero reserve means *there is a pool and it is drained*. The first is a position that
    cannot be marked; the second is a position worth nothing.
    """


class PoolSidesDisagree(PoolReadDefect):
    """The pool's own ``token0``/``token1`` are not the pair this read is about."""


class PoolFeeDisagrees(PoolReadDefect):
    """The pool reports a fee tier other than the one its address was derived for."""


class ReturndataWidth(PoolReadDefect):
    """A call returned a different number of words than the ABI says.

    A selector that is right about the name and wrong about the arguments still returns *something*,
    and reading that as a number reads whatever happened to land there.
    """


class LastSwapUnknowable(PoolReadDefect):
    """A pool shape with no cheap reading of when it last traded.

    Refused rather than filled with the horizon block. Defaulting it would assert perfect freshness
    about a pool nobody looked at, and §9.1's first condition would then never fire.
    """


@dataclass(frozen=True)
class PoolReading:
    """A pool as it was at one height, and the evidence for each field.

    ``evidence`` is what a reader checks against an explorer. It is a tuple of sentences rather than
    a formatted blob because each one is a separate claim and a reader may disbelieve one without
    disbelieving the rest.
    """

    state: PoolState
    venue: Create2Venue
    block: int
    evidence: Tuple[str, ...]

    def __post_init__(self):
        # type: () -> None
        if not isinstance(self.state, PoolState):
            raise TypeError("PoolReading.state must be a contracts.PoolState")
        if not isinstance(self.block, int) or isinstance(self.block, bool) or self.block < 0:
            raise ValueError(
                "PoolReading.block must be the height the call was pinned to, got {!r}. A reading "
                "with no height is a reading about no particular time.".format(self.block)
            )


def _words(returndata, expected, what, address):
    # type: (str, int, str, str) -> Tuple[int, ...]
    """Split returndata into ``expected`` 32-byte words, or refuse."""
    if not isinstance(returndata, str) or not returndata.startswith("0x"):
        raise PoolReadDefect(
            "{} on pool {} answered {!r}, which is not returndata.".format(what, address, returndata)
        )
    body = returndata[2:]
    if body == "":
        raise PoolHasNoCode(
            "{} on {} returned empty returndata: there is no contract at that address at this "
            "height. An empty answer is not a zero reserve -- it means there is no pool here, and "
            "the position cannot be marked rather than being worth nothing.".format(what, address)
        )
    if len(body) != expected * _WORD * 2:
        raise ReturndataWidth(
            "{} on pool {} returned {} byte(s); the ABI says {} word(s) = {}. Reading a number out "
            "of the wrong width reads whatever landed there.".format(
                what, address, len(body) // 2, expected, expected * _WORD
            )
        )
    return tuple(
        int(body[i * _WORD * 2:(i + 1) * _WORD * 2], 16) for i in range(expected)
    )


def _address_word(word, what, address):
    # type: (int, str, str) -> str
    """A 32-byte word read as an address, refusing a word whose top 12 bytes are not zero."""
    if word >> 160:
        raise PoolSidesDisagree(
            "{} on pool {} returned a word whose top 12 bytes are not zero; that is not an "
            "address.".format(what, address)
        )
    return normalise_asset("0x{:040x}".format(word))


def _call(client, address, selector, block):
    # type: (object, str, str, int) -> str
    return client.call("eth_call", [{"to": address, "data": selector}, block_parameter(block)])


def _oriented(client, address, asset, quote, block, reserve0, reserve1):
    # type: (object, str, str, str, int, int, int) -> Tuple[int, int, str, str]
    """Which reserve is the asset's, decided by the pool rather than by the caller.

    The pool's own ``token0()`` is the authority. Attributing the two the wrong way round produces
    a plausible price that is wrong by the ratio of the two reserves -- a mark, not an error.
    """
    side0 = _address_word(_words(_call(client, address, TOKEN0, block), 1, "token0()", address)[0],
                          "token0()", address)
    side1 = _address_word(_words(_call(client, address, TOKEN1, block), 1, "token1()", address)[0],
                          "token1()", address)
    asset_n, quote_n = normalise_asset(asset), normalise_asset(quote)
    if (side0, side1) == (asset_n, quote_n):
        return reserve0, reserve1, side0, side1
    if (side1, side0) == (asset_n, quote_n):
        return reserve1, reserve0, side0, side1
    raise PoolSidesDisagree(
        "pool {} holds token0={} token1={}; this read is about a pool of {} quoted in {}. The "
        "address was derived for that pair, so either the derivation is wrong or the address was "
        "supplied by hand for a different pool -- and reading it anyway would mark the position "
        "against reserves belonging to two other tokens.".format(
            address, side0, side1, asset_n, quote_n
        )
    )


def read_v2_pool(client, asset, quote, block, address=None, fee_bps=30):
    # type: (object, str, str, int, Optional[str], int) -> PoolReading
    """The Uniswap v2 pair for ``(asset, quote)`` as it stood at ``block``.

    :param address: the pool, when a caller already knows it. Omitted, it is computed by CREATE2 --
        no lookup, no search, and no dependence on a list of pools somebody maintained.
    :returns: a :class:`PoolReading` whose ``state.last_swap_block`` carries the limitation stated
        in :data:`LAST_SWAP_IS_LAST_RESERVE_CHANGE`.

    Four ``eth_call``\\ s: ``getReserves``, ``token0``, ``token1``, and nothing else. The fee is not
    read because a v2 pair has no ``fee()`` -- 30 bps is the protocol constant, and it is a
    parameter here so a fork with another constant is a caller's statement rather than this
    module's assumption.
    """
    if address is None:
        address = pool_address(UNISWAP_V2, asset, quote, None)

    reserve0, reserve1, ts_last = _words(
        _call(client, address, GET_RESERVES, block), 3, "getReserves()", address
    )
    asset_raw, quote_raw, side0, side1 = _oriented(
        client, address, asset, quote, block, reserve0, reserve1
    )

    state = PoolState(
        address=address,
        asset=normalise_asset(asset),
        quote=normalise_asset(quote),
        asset_reserve_raw=asset_raw,
        quote_reserve_raw=quote_raw,
        # getReserves() reports a TIMESTAMP, not a block. The block is what the call was pinned to;
        # the timestamp is what the pool recorded. Both are carried because §9.1 compares an age
        # and a caller that had only one of them would have to invent the other.
        last_swap_block=block,
        last_swap_timestamp=ts_last,
        fee_bps=fee_bps,
    )
    return PoolReading(
        state=state,
        venue=UNISWAP_V2,
        block=block,
        evidence=(
            "venue={} address={}".format(UNISWAP_V2.label, address),
            "getReserves() at block {} -> reserve0={} reserve1={} blockTimestampLast={}".format(
                block, reserve0, reserve1, ts_last
            ),
            "token0={} token1={}; asset side is {}".format(
                side0, side1, "token0" if side0 == normalise_asset(asset) else "token1"
            ),
            LAST_SWAP_IS_LAST_RESERVE_CHANGE,
        ),
    )


def read_pool_for(client, asset, quote, block, fee=None):
    # type: (object, str, str, int, Optional[int]) -> PoolReading
    """A pool for ``(asset, quote)``, v2 today.

    ``fee`` selects a v3 tier when one is wanted. It refuses rather than reading, because a v3 pool
    has no cheap ``last_swap`` reading of any kind: ``slot0()`` reports a price and a tick, not a
    time. Filling that field with the horizon block would assert perfect freshness about a pool
    nobody looked at, and §9.1's first condition would then never fire on a v3 venue.

    That refusal is the honest state of this module and not a design position -- the v3 branch is
    reachable the moment there is an affordable reading, and :mod:`marking` already models
    concentrated liquidity through ``active_liquidity`` and ``sqrt_price_x96``.
    """
    if fee is None:
        return read_v2_pool(client, asset, quote, block)
    if fee not in FEE_TIERS:
        raise PoolFeeDisagrees(
            "fee tier {} is not one of the four this repository can derive an address for ({}). "
            "A tier outside them is a pool whose address cannot be computed, and guessing one "
            "would read a different pool's reserves.".format(fee, ", ".join(map(str, FEE_TIERS)))
        )
    raise LastSwapUnknowable(
        "pool {} is a Uniswap v3 {}bp pool and this module will not read one yet. slot0() reports "
        "a price and a tick, not a time, so last_swap_block cannot be established cheaply; "
        "defaulting it to the horizon would assert perfect freshness about a pool nobody looked "
        "at, and §9.1's no-swap-for-30-days condition would then never fire here.".format(
            pool_address(UNISWAP_V3, asset, quote, fee), fee
        )
    )
