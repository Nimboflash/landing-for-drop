"""§4.7's Token Trading Start, derived from the chain rather than supplied by a caller.

    derive_token_starts(client, tokens, to_block) -> {token: TokenStartFinding}

§4.7 defines it exactly once and the wording is the whole specification::

    Token Trading Start =
      the first block at which the token had usable liquidity
      AND at least one real swap in a covered pool

Everything in this module follows from that sentence and from the one that comes after it: *if a
token has multiple pools, the first qualifying pool is used*.

Why this module exists
----------------------

``pipeline.run`` quarantines a buy whose token has no ``WindowConfig.token_start`` entry, and it is
right to — bucketing an unknown age as D would file an unknown as a fact, and D is the bucket the
Edge Origin condition is measuring *against*. But on four real February-2023 wallets that refusal
was firing on 82 buys, two and a half times the whole undecodable population, for a date that is
on chain and that nothing in this repository derived. This is the derivation.

Which signal is the start, and why the three obvious alternatives are wrong
--------------------------------------------------------------------------

**The signal is the pool's first swap, admitted only if minted liquidity precedes it in log
order.** Both halves are load-bearing:

* **not ``PairCreated`` / ``PoolCreated``.** A pool address exists from the factory call onward and
  can hold nothing at all. Both worked examples in ``tools/case_runs.py`` are exactly this case:
  the rug pair was created at block 16530559 and first traded 15 blocks later, and SBET's pair was
  created at 16530898 and first traded 50 blocks later. Reading creation as the start puts blocks
  the token could not be bought in inside bucket A — the first-ten-blocks bucket — which moves
  buys out of it and makes the first-hour share read low;
* **not the first ``Mint``.** Liquidity with nobody trading against it is not a market. The
  pre-registration says "usable liquidity **AND** at least one real swap", the conjunction is
  written in capitals in §4.7, and ``tools/case_survey.py`` already pins a case where the two are
  four blocks apart;
* **not the token contract's deployment.** §4.7 opens by saying so: "Token age is **not** measured
  from contract creation." A contract deployed months before it traded is not a mature token at
  its first trade, and this is the error the whole section exists to prevent. Nothing in this
  module reads a token's deployment block, and no branch falls back to one;
* **not the pool the position is being marked at, and not the newest pool.** Addendum §9.2:
  migration does not reset token age. The start is the **earliest** across every covered pool,
  because a buyer on the second pool is not an early buyer of the token.

The mint guard is stated as *precedes it in log order*, not *in an earlier block*: a pair funded
and swapped inside one block is a real and common launch pattern, and comparing block numbers
alone would refuse it. Comparing ``(block, logIndex)`` accepts it and still refuses the case that
matters — a swap this derivation cannot tie to any liquidity event it saw.

The earliest across pools, and how few queries that takes
---------------------------------------------------------

Pools are resolved in creation order, and two facts make the search cheap without making it
weaker. A pool's first swap can never precede the block the factory created it in; so once one
pool has produced a start at block ``S``, a pool created at or after ``S`` cannot beat it and is
never queried at all, and a pool created before ``S`` is searched only up to ``S``. What the
finding reports is therefore "the earliest start over every covered pool", and its ``notes`` name
each pool that was skipped and why — a skipped pool is recorded, never silently dropped.

Why the log scan starts at the pool's first *activity* and not at its creation
-------------------------------------------------------------------------------

An endpoint that serves ten blocks of logs at a time turns "read this pool's history" into one
request per ten blocks, and a pool's history is not short. Measured on the thirty tokens
``tools/case_runs.py`` needs a start for: pools were created and then sat untouched for as long as
17,941 blocks — two and a half days — before anyone put liquidity in them. Scanning that from the
creation block is 1,795 requests for one pool, to find a ``Mint`` that a handful of requests would
have found if the scan had begun in the right place.

So the scan begins at the pool's **first active block**, found the same way its creation block was:
a monotone reading of the pool's own storage, binary-searched over height, with no log range
anywhere. :class:`ActivityProbe` is that reading — ``getReserves()`` on a v2 pair, ``slot0()`` on a
v3 pool — and what makes it usable is not that it is a good heuristic but that it is a *proof of
absence*: a v2 pair's three reserve fields are all zero until its first ``_update``, which every
``mint``, ``burn``, ``swap`` and ``sync`` performs, and ``blockTimestampLast`` never returns to
zero afterwards. A block where the reading is zero is therefore a block by which the pair has
emitted no ``Mint`` and no ``Swap`` — not "probably none". About 24 ``eth_call``\\ s replace up to
1,800 log requests, and the answer is the same one.

Deliberately *not* ``totalSupply()`` of the pair's LP token, which is the more obvious reading and
is also monotone. It marks the first ``Mint`` rather than the first anything, and a pair can be
force-fed tokens, ``sync``\\ ed and swapped against with no LP ever minted — rare, but a scan
anchored on the first ``Mint`` would step over such a swap and report a *later* start, which files
the token as younger than it is. The reserve reading has no such gap: it moves at the first
interaction of any kind.

The scan is then bounded — :data:`SCAN_BLOCKS` blocks from where it started, which is
:data:`SCAN_SLICES` requests — and **running out is a refusal, never a skip**. "This pool did not
trade in the range I searched" and "this pool never traded" are different sentences, and only the
second one permits moving on to a later pool: treating the first as the second would take a later
pool's first swap as the token's start and file the token as younger than it is.

How the pools are found, and why the obvious way is not available
------------------------------------------------------------------

Two discoveries exist, they answer the same question, and the default is the second one:

* :data:`FACTORY_LOG_SWEEP` reads ``PairCreated`` / ``PoolCreated`` off the two factories with
  :func:`covered_pools`. It is the direct reading of the question and **it cannot run here.** The
  v2 factory was created in block 10,000,835 and the horizon is 16,943,478; every free endpoint in
  :data:`transport.endpoints.DEFAULT_ENDPOINTS` now caps ``eth_getLogs`` at 10 or 50 blocks
  ("You can make eth_getLogs requests with up to a 10 block range"), which is on the order of
  700,000 requests for one sweep. It stays in this module, unremoved and unrecommended, because on
  a node with no range cap it is the wider search: it sees a pool against *any* counterparty;
* :data:`CREATE2_DERIVATION` computes the address instead of searching for it. Both factories
  deploy with ``CREATE2``, so a pool's address is a hash of the factory, the sorted token pair and
  the pool's init code — see :mod:`pipeline.pooladdress`, which pins the two init code hashes and
  verifies them at import against two pools this repository's own recordings already name. The
  chain is then asked one ``eth_getCode`` per candidate address, and each address that carries code
  gets its creation block by binary search over ``eth_getCode`` (:func:`creation_block`) — about 25
  calls per real pool, none of them a log range. A second binary search, over the pool's own state
  rather than its code, then says when it was first *used* (:func:`first_active_block`); that is the
  next section, and it is what keeps the log scan short enough for a ten-block cap.

The derivation buys that with a narrower question, and the narrowing is the honest cost: it can
only derive an address for a pair it can *name*, so it searches ``token`` against the four §4 quote
assets in :data:`DERIVED_COUNTERPARTIES` and against the fee tiers
:data:`pipeline.pooladdress.FEE_TIERS` pins. A pool against some third token, or at a fee tier not
on that list, has no address derived and is therefore invisible — and that reaches the refusal
through :attr:`PoolDiscovery.not_covered`, never a default date.

Which factories are covered, and which are not
----------------------------------------------

Covered, by address, with its creation block measured rather than remembered
(:func:`confirm_factories`):

* Uniswap v2, ``0x5c69…aa6f``, created in block 10,000,835 — ``PairCreated``
* Uniswap v3, ``0x1f98…f984``, created in block 12,369,621 — ``PoolCreated``

Not covered, and this list is the honest size of the gap: ShibaSwap and every other
Uniswap-v2 fork; Curve, Balancer and any other pool shape; Uniswap v4 and any singleton-pool AMM;
any venue on a chain other than Ethereum mainnet; and a relaunch under a **new token contract**,
which no factory search can see because the new contract is simply a different token. Under
:data:`CREATE2_DERIVATION` two more lines join that list, and they are in
:data:`DERIVED_NOT_COVERED` rather than here because they are the *derivation's* limits and not the
factories': a counterparty outside :data:`DERIVED_COUNTERPARTIES`, and a v3 fee tier outside
:data:`pipeline.pooladdress.FEE_TIERS`.

A token whose only market is on an uncovered venue therefore gets a refusal, never a date. That is
the direction that matters: a missing pool reported as "no pool found" quarantines the buy, while a
missing pool reported as "old" would file a first-hour buy as bucket D, and a missing pool reported
as the first *covered* pool would file a mature token as a first-hour launch.

What it refuses rather than guesses
-----------------------------------

Each of these returns a :class:`TokenStartFinding` with ``start=None`` and a ``refusal`` — a
carried status, because it is a limit on what could be measured. The caller then leaves the token
out of ``WindowConfig.token_starts`` and ``pipeline.run`` quarantines the buy in the words it
already uses:

* ``no_pool_on_covered_factories`` — no covered factory ever created a pool for this token;
* ``no_swap_in_any_covered_pool`` — pools exist and none of them ever served a swap;
* ``liquidity_not_established`` — a pool served a swap with no ``Mint`` before it in log order, and
  that swap is early enough that it could be the token's start. §4.7's conjunction cannot be
  established, and this pool is not quietly skipped: skipping it would move the start *later* and
  make the token look younger than it is;
* ``first_trade_outside_the_scanned_range`` — a pool was used and the scan reached its
  :data:`SCAN_BLOCKS` bound without finding a swap. What the run knows is that the pool did not
  trade in the blocks it looked at, which is not the same as never having traded, so this pool
  cannot be passed over in favour of a later one.

And one that is not this module's to return, because the buy is not this module's to see: a buy in
a block *before* the derived start. ``marking.token_age_bucket`` already raises
``contracts.QuarantineRequired`` for it and must keep doing so — a buy that predates the earliest
covered pool's first swap is a wallet that bought somewhere this derivation does not cover, and
turning that into a silent adjustment here would replace a signal with a number.

And what raises instead, because it is a defect in what assembled the call rather than a limit on
what the chain will say: a factory whose event layout this module does not know
(:class:`UnrecognisedFactory`), a factory whose code is not where its constant says it is
(:class:`FactoryNotAtStatedBlock`), a log whose shape contradicts the signature it claims
(:class:`FactoryLogMismatch`), and the ordinary input defects — a malformed address, a duplicate
token, a ``to_block`` before a covered factory existed.

What this module does not do
----------------------------

**It does not decide a bucket.** ``marking.token_age_bucket`` owns that and stays the only thing
that does; this module supplies the date that function asks for and imports nothing from
``marking``. ``tests/hand_computed/test_token_start.py`` holds that from the outside. It also does
not decide whether a buy predates the start it derived: that is
``marking.token_age_bucket``'s existing :class:`contracts.QuarantineRequired`, and a buy earlier
than the earliest covered pool's first swap is a real signal — it says the wallet bought at a venue
this derivation does not cover — which is exactly why it must stay a quarantine there rather than
become a silent adjustment here.

**It does not guarantee that a derived start is the token's true first trade.** It guarantees the
earliest first-swap block over the pools the covered factories created, searched from each
factory's own creation block to ``to_block``, with one recorded answer per block slice behind the
claim. Everything in the not-covered list above is outside that guarantee, and a start derived here
can therefore only ever be **later** than or equal to the truth — so a token filed in bucket A or B
by this date is a token that was young on Uniswap, which is a narrower statement than "young".

Why it lives here
-----------------

In the composition root, beside :mod:`pipeline.chain`, and for the same reason that module gives:
``ingest`` is a leaf builder that may not import ``pipeline``, so the step that puts chain bytes
into a :class:`pipeline.inputs.TokenStart` happens where that type is defined. It is also a
*search* rather than a decode — ``ingest``'s own docstring rules searches out by name — and it must
not be in ``marking``, which owns what a bucket is and would become a second authority the moment
it also owned where the clock starts.
"""

from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional, Tuple  # noqa: F401  (3.9-compatible annotations)

from contracts import QUOTE_ASSETS, normalise_asset

from ingest import SWAP_V2, SWAP_V3, block_header
from transport import block_parameter

from .inputs import TokenStart
from .keccak import function_selector
from .pooladdress import (
    NOT_DERIVABLE,
    SUSHISWAP as SUSHISWAP_VENUE,
    UNISWAP_V2 as UNISWAP_V2_VENUE,
    UNISWAP_V3 as UNISWAP_V3_VENUE,
    derived_pools,
)

#: Blocks per ``eth_getLogs`` slice. **Ten**, because ten is the largest range *every* endpoint in
#: :data:`transport.endpoints.DEFAULT_ENDPOINTS` serves, and the client tries them in order rather
#: than shopping for the most generous one. Re-probed on 2026-08-13: the first endpoint answers
#: HTTP 400 "You can make eth_getLogs requests with up to a 10 block range" above ten, the second
#: answers JSON-RPC -32001 above fifty, the third served ten thousand that day and was
#: "service temporarily unavailable" on another.
#:
#: A larger slice is not faster here, it is *conditional*: it works only while the one uncapped
#: vendor is up, and a run that silently depends on which vendor answered is a run whose cost
#: cannot be reproduced. Ten always works on the first endpoint asked.
CHUNK_BLOCKS = 10

#: How many ``eth_getLogs`` slices :func:`pool_trading_start` will spend narrowing one pool's first
#: trade, and therefore how many blocks past the pool's first activity it looks:
#: :data:`SCAN_BLOCKS` = ``SCAN_SLICES * CHUNK_BLOCKS``.
#:
#: 720 slices is one day of Ethereum at twelve seconds a block. The number is a *budget* and the
#: budget is visible in the answer: a pool first used and still not traded a day later reaches
#: ``first_trade_outside_the_scanned_range`` and the token is quarantined, rather than the run
#: pretending the pool never traded and taking a later pool's swap instead. Widening it buys more
#: resolved tokens at ten more requests per ten blocks; narrowing it buys speed and more
#: quarantines. Neither direction can change a start that was already established, because the
#: bound only ever decides whether there is an answer, never which answer.
#:
#: Measured on the thirty tokens ``tools/case_runs.py`` needs: the longest gap between a pool's
#: first state change and its first trade is 3,972 blocks, which is 398 slices.
SCAN_SLICES = 720
SCAN_BLOCKS = SCAN_SLICES * CHUNK_BLOCKS

#: ``PairCreated(address indexed token0, address indexed token1, address pair, uint)`` on the
#: Uniswap v2 factory, and
#: ``PoolCreated(address indexed token0, address indexed token1, uint24 indexed fee, int24,
#: address)`` on the v3 factory. Both were established by reading a factory's logs with no topic
#: filter and taking the topic that came back, the way ``tools/case_survey.py`` established them;
#: neither is a remembered constant.
PAIR_CREATED = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"
POOL_CREATED = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"

#: ``Mint(address indexed sender, uint amount0, uint amount1)`` on a v2 pair, and
#: ``Mint(address sender, address indexed owner, int24 indexed tickLower, int24 indexed tickUpper,
#: uint128 amount, uint256 amount0, uint256 amount1)`` on a v3 pool.
#:
#: Deliberately **not** added to :data:`ingest.events.SIGNATURES`. That registry decides which logs
#: a receipt can be decoded from, and adding two events to it would make transactions the census
#: currently counts as undecodable decode instead — a change to a published number, made as a side
#: effect of needing a topic string here. The two swap topics below are imported from ``ingest``
#: precisely because they are already in that registry, and a test pins the import so the two
#: spellings cannot drift apart.
MINT_V2 = "0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f"
MINT_V3 = "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde"

#: Both creation events carry exactly two 32-byte data words: v2's are ``(pair, allPairsLength)``
#: and v3's are ``(tickSpacing, pool)``. The width is checked before either is read, because a log
#: that is one word short would otherwise hand back a pool address assembled from whatever followed.
CREATED_DATA_WORDS = 2


class TokenStartDefect(ValueError):
    """A defect in what assembled the derivation, never a limit on what the chain would say.

    The house rule the three subclasses divide on: a limitation of what can be measured is a
    carried status — a :class:`TokenStartFinding` with a ``refusal`` — and a defect in what
    assembled the call raises, naming the rule, the input and the cost.
    """


class UnrecognisedFactory(TokenStartDefect):
    """A factory whose creation event and pool-address layout this module does not know.

    Raised rather than skipped, and rather than searched anyway. Skipping it would return a start
    derived from the factories that *are* covered while the caller believed a wider set had been
    searched, which is the one error in this module that produces a plausible date instead of a
    refusal. Guessing that an unknown factory emits ``PairCreated`` with the pool in data word 0
    would read some other event's second word as an address.
    """


class FactoryNotAtStatedBlock(TokenStartDefect):
    """A covered factory's code is not where :attr:`Factory.created_block` says it appeared.

    The sweep's lower bound is that block, so the constant being wrong is not a cosmetic error: a
    factory that in fact existed earlier would leave pools created before the bound unsearched, and
    the derived start would be the earliest pool *this run happened to look at*.
    """


class FactoryLogMismatch(TokenStartDefect):
    """A creation log's shape contradicts the signature it claims.

    Wrong topic count, wrong data width, or an address word with a non-zero prefix. The same class
    of check ``ingest.events`` applies to a transfer, and for the same reason: the bytes are
    well-formed hex either way, so nothing downstream could notice.
    """


class PoolStateUnreadable(TokenStartDefect):
    """A pool that carries code did not answer its own venue's :class:`ActivityProbe` in shape.

    A defect and not a carried status, and the init code hash is what makes that the right call:
    :mod:`pipeline.pooladdress` derives this address from a pinned hash, so the only bytecode that
    can be here is the pair's or the pool's, and that bytecode has the function. Returndata of some
    other width is therefore a statement about *this module* — a wrong init code hash, a wrong
    selector, or an endpoint answering something else — and reading it as a number anyway would
    hand the binary search a monotone-looking answer assembled from the wrong bytes.
    """


@dataclass(frozen=True)
class ActivityProbe:
    """A pool's own storage, read as one number, that is zero until the pool is first used.

    ``signature`` is the canonical function text; ``selector`` is derived from it by
    :func:`pipeline.keccak.function_selector`, so the four bytes and the text cannot drift apart.
    ``words`` is how many 32-byte words the function returns, checked before the answer is read —
    a selector that is right about the name and wrong about the arguments returns a different
    width, and reading that as a number is reading whatever landed there.

    Two properties are required of the reading, and both are arguments rather than observations:

    * ``zero_means`` — that a zero reading at height ``b`` **proves** the pool emitted no ``Mint``
      and no ``Swap`` at or before ``b``. This is the one that matters. A probe that were merely a
      good indicator would let the scan's floor land past a swap, which reports a later start and
      files the token as younger than it is;
    * ``monotone_because`` — that the reading crosses zero exactly once and never returns. A binary
      search over a predicate that flickers finds *some* crossing rather than the first one.

    The whole returndata is compared against zero, not one field of it: for ``getReserves()`` the
    third word is ``blockTimestampLast``, which is what makes the reading non-zero even for a pool
    whose reserves were later drained back to nothing.
    """

    signature: str
    words: int
    zero_means: str
    monotone_because: str

    def __post_init__(self):
        if isinstance(self.words, bool) or not isinstance(self.words, int) or self.words < 1:
            raise ValueError(
                "{} must say how many 32-byte words it returns, as a positive int; got {!r}. "
                "Without it the width check is not a check.".format(self.signature, self.words)
            )
        for name in ("zero_means", "monotone_because"):
            if not getattr(self, name):
                raise ValueError(
                    "{} declares no {}. Both are the argument that this reading may be used as a "
                    "scan floor at all — a probe adopted because it looked right in the cases "
                    "somebody tried is a floor that lands above a swap in the case nobody "
                    "tried.".format(self.signature, name)
                )

    @property
    def selector(self):
        return function_selector(self.signature)


#: Uniswap v2's probe. ``getReserves()`` returns ``(uint112 reserve0, uint112 reserve1,
#: uint32 blockTimestampLast)`` as three words, all three zero from the block the factory created
#: the pair in until its first ``_update``.
V2_GET_RESERVES = ActivityProbe(
    signature="getReserves()",
    words=3,
    zero_means=(
        "UniswapV2Pair.mint, burn, swap and sync all call _update, and _update writes "
        "blockTimestampLast; a pair whose three reserve fields are all still zero has run none of "
        "them, so it has emitted no Mint and no Swap"
    ),
    monotone_because=(
        "blockTimestampLast is set to the block's own timestamp and is only ever overwritten with "
        "a later one — never cleared — so the reading crosses zero once and stays non-zero even "
        "if every last unit of both reserves is withdrawn"
    ),
)

#: Uniswap v3's probe. ``slot0()`` returns seven words — ``sqrtPriceX96``, ``tick``,
#: ``observationIndex``, ``observationCardinality``, ``observationCardinalityNext``,
#: ``feeProtocol``, ``unlocked`` — all zero until ``initialize()`` sets the price and the
#: cardinality and unlocks the pool.
V3_SLOT0 = ActivityProbe(
    signature="slot0()",
    words=7,
    zero_means=(
        "UniswapV3Pool.mint and swap both take the lock, which initialize() is what sets; an "
        "uninitialised pool reverts both, so a pool whose slot0 is still all zeros has emitted no "
        "Mint and no Swap"
    ),
    monotone_because=(
        "initialize() may be called once — it requires sqrtPriceX96 == 0 — and neither the price "
        "nor the observation cardinality nor the unlocked flag is ever returned to zero afterwards"
    ),
)


@dataclass(frozen=True)
class Factory:
    """A pool factory this module knows how to read, and where it starts.

    ``pool_data_word`` is which 32-byte data word holds the created pool's address — 0 for v2's
    ``PairCreated``, 1 for v3's ``PoolCreated``, whose first word is the tick spacing. Getting it
    wrong yields a well-formed address that is not a pool, so it is a field rather than a slice
    written into the parser.

    ``activity_probe`` is optional and its absence is a real cost rather than a default: a venue
    with no such reading has its log scan start at each pool's creation block, and the
    :data:`SCAN_BLOCKS` budget is then spent on the untouched blocks between creation and first
    use. It is a field for the same reason ``pool_data_word`` is — adding a venue is adding a
    value, and a venue that has such a reading but does not declare one would be searched more
    expensively and resolved less often with nothing saying why.
    """

    address: str
    label: str
    created_block: int
    created_event: str
    created_topic_count: int
    pool_data_word: int
    mint_event: str
    swap_event: str
    activity_probe: Optional[ActivityProbe] = None

    def __post_init__(self):
        object.__setattr__(self, "address", normalise_asset(self.address))
        for name in ("created_block", "created_topic_count", "pool_data_word"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    "Factory.{} must be an int, got {}".format(name, type(value).__name__)
                )
        if self.created_block < 0:
            raise ValueError("Factory.created_block must be a height, got {}".format(
                self.created_block))
        if not 0 <= self.pool_data_word < CREATED_DATA_WORDS:
            raise ValueError(
                "Factory.pool_data_word must index one of the {} data words a creation event "
                "carries, got {}".format(CREATED_DATA_WORDS, self.pool_data_word)
            )


#: The factory addresses are taken from :mod:`pipeline.pooladdress` rather than written again here.
#: They have to be the same address in both files — the CREATE2 preimage contains the deployer, so
#: a derivation against one factory and a log sweep against another would be two different searches
#: reported as one — and one literal cannot drift from itself.
UNISWAP_V2_FACTORY = Factory(
    address=UNISWAP_V2_VENUE.factory,
    label=UNISWAP_V2_VENUE.label,
    created_block=10_000_835,
    created_event=PAIR_CREATED,
    created_topic_count=3,
    pool_data_word=0,
    mint_event=MINT_V2,
    swap_event=SWAP_V2,
    activity_probe=V2_GET_RESERVES,
)

#: SushiSwap's pair factory. Same v2 event shapes and the same probe -- a fork of the code, so the
#: signatures are identical; only the factory address and the init code hash differ. Created at
#: 10,794,229, which is later than Uniswap v2's, so a token that existed on both has its earliest
#: market on Uniswap unless it was launched after this block.
SUSHISWAP_FACTORY = Factory(
    address=SUSHISWAP_VENUE.factory,
    label=SUSHISWAP_VENUE.label,
    created_block=10_794_229,
    created_event=PAIR_CREATED,
    created_topic_count=3,
    pool_data_word=0,
    mint_event=MINT_V2,
    swap_event=SWAP_V2,
    activity_probe=V2_GET_RESERVES,
)

#: The probe is ``slot0()`` and not ``liquidity()``, which is the reading a reader would expect and
#: is the wrong one: ``liquidity()`` is the liquidity *in the active tick range*, so it falls to
#: zero whenever the price leaves every position's range and rises again when it returns. It
#: crosses zero repeatedly, and a binary search over a predicate that flickers returns whichever
#: crossing the halving happened to land on — which here would be a scan floor above the swap it
#: was looking for.
UNISWAP_V3_FACTORY = Factory(
    address=UNISWAP_V3_VENUE.factory,
    label=UNISWAP_V3_VENUE.label,
    created_block=12_369_621,
    created_event=POOL_CREATED,
    created_topic_count=4,
    pool_data_word=1,
    mint_event=MINT_V3,
    swap_event=SWAP_V3,
    activity_probe=V3_SLOT0,
)

#: The default coverage. A tuple rather than a module-level lookup the functions reach for, so a
#: caller can narrow it — and so a test can prove that narrowing it turns a derived start into a
#: refusal rather than into a different date.
COVERED_FACTORIES = (UNISWAP_V2_FACTORY, SUSHISWAP_FACTORY, UNISWAP_V3_FACTORY)

#: What a ``no_pool_on_covered_factories`` refusal is a refusal *about*. Carried in the refusal
#: text, because "no pool found" and "no pool found on two Uniswap factories, out of these venues"
#: are read differently by whoever works the queue.
NOT_COVERED = (
    "ShibaSwap and every other Uniswap-v2 fork except SushiSwap, which is covered",
    "Curve, Balancer, Bancor and any other pool shape",
    "Uniswap v4 and any singleton-pool AMM",
    "any venue on a chain other than Ethereum mainnet",
    "a relaunch under a new token contract, which no factory search can see",
)

#: The counterparties :data:`CREATE2_DERIVATION` derives addresses against, in a fixed order.
#:
#: A derived address is a hash of the *pair*, so the derivation can only look where it can name
#: both sides. §4 already fixes the set of assets a trade may be quoted in —
#: :data:`contracts.QUOTE_ASSETS`, which is WETH, USDC, USDT and WBTC — and a buy quoted in
#: anything else is out of scope upstream of this module, so searching those four is searching the
#: pools a §4 buy could have settled through. Sorted rather than left as the frozenset it comes
#: from: the sweep's cost and its recorded calls must be the same on every run.
DERIVED_COUNTERPARTIES = tuple(sorted(QUOTE_ASSETS))

#: What :data:`CREATE2_DERIVATION` cannot see that a log sweep could, plus what neither can.
#:
#: The first line is the price of deriving rather than searching, and it is the one a reader of a
#: refusal most needs: a token whose only market is against some third token has no derived address
#: at all, so it is reported as having no pool. That is "unknown", not "old" — and the whole reason
#: this reaches the refusal text is that an unknown age filed as bucket D is an unknown filed as a
#: fact.
DERIVED_NOT_COVERED = (
    "a pool whose other side is not one of the {} quote assets this derivation names ({})".format(
        len(DERIVED_COUNTERPARTIES), ", ".join(DERIVED_COUNTERPARTIES)
    ),
) + NOT_DERIVABLE


@dataclass(frozen=True)
class CoveredPool:
    """One pool a covered factory created for a token.

    Built either from the creation log (:func:`covered_pools`) or from a derived address whose
    creation block was measured with ``eth_getCode`` (:func:`pools_by_derivation`). For the same
    pool the two agree on ``address``, ``factory``, ``created_block``, ``token`` and
    ``counterparty`` — which is what lets :func:`derive_token_starts` take either — and differ in
    ``venue``: the derivation knows which fee tier it derived and says so, and the log sweep read
    the tier off nothing and does not.
    """

    address: str
    factory: str
    venue: str
    created_block: int
    token: str
    counterparty: str

    def __post_init__(self):
        for name in ("address", "factory", "token", "counterparty"):
            object.__setattr__(self, name, normalise_asset(getattr(self, name)))


@dataclass(frozen=True)
class TokenStartFinding:
    """What the derivation established for one token, or why it could not.

    Exactly one of ``start`` and ``refusal`` is set. That is an invariant rather than a convention:
    a finding carrying both would let a caller read the date and ignore the reason, and a finding
    carrying neither is a token nothing was ever decided about.

    ``searched_from`` / ``searched_to`` are the sweep's own bounds, carried so a reader can tell a
    refusal that searched every block a covered factory has existed for from one that searched a
    slice of it.
    """

    token: str
    start: Optional[TokenStart]
    pool: Optional[str]
    pools: Tuple[CoveredPool, ...]
    searched_from: int
    searched_to: int
    refusal: Optional[str] = None
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        object.__setattr__(self, "token", normalise_asset(self.token))
        object.__setattr__(self, "pools", tuple(self.pools))
        object.__setattr__(self, "notes", tuple(self.notes))
        if (self.start is None) == (self.refusal is None):
            raise ValueError(
                "a finding for {} must carry either a start or a refusal and not both; got "
                "start={!r} refusal={!r}. Both would let the date be read past the reason; "
                "neither is a token nothing decided anything about.".format(
                    self.token, self.start, self.refusal
                )
            )
        if self.start is not None and self.pool is None:
            raise ValueError(
                "the start derived for {} names no pool. A date with no venue behind it cannot be "
                "re-derived from the record, which is the whole point of carrying "
                "it.".format(self.token)
            )

    @property
    def established(self):
        return self.start is not None


# -- reading the bytes -----------------------------------------------------------


def topic_word(address):
    """An address as a 32-byte topic, left-padded. What ``eth_getLogs`` matches an indexed arg on."""
    return "0x" + "0" * 24 + normalise_asset(address)[2:]


def _log_block(log):
    return int(log["blockNumber"], 16)


def _log_index(log):
    return int(log["logIndex"], 16)


def _data_words(log, factory):
    body = log["data"][2:] if log["data"].startswith("0x") else log["data"]
    if len(body) != 64 * CREATED_DATA_WORDS:
        raise FactoryLogMismatch(
            "a {} creation log in block {} carries {} hex digits of data; {} claims {} 32-byte "
            "words. A short log read as though it were the right width hands back a pool address "
            "assembled out of whatever followed it.".format(
                factory.label, _log_block(log), len(body), factory.created_event,
                CREATED_DATA_WORDS,
            )
        )
    return [body[index * 64:(index + 1) * 64] for index in range(CREATED_DATA_WORDS)]


def _address_of_word(word, what, factory):
    if word[:24] != "0" * 24:
        raise FactoryLogMismatch(
            "{} in a {} creation log is {} — the top 12 bytes of the word are not zero, so it is "
            "not an address. Truncating it to the low 20 bytes would produce a well-formed address "
            "that is not the one the event encoded.".format(what, factory.label, word)
        )
    return "0x" + word[24:]


def _pool_from_created_log(log, factory):
    """The ``CoveredPool`` a creation log describes, checked against the factory's own layout."""
    topics = log["topics"]
    if topics[0] != factory.created_event:
        raise FactoryLogMismatch(
            "a log from {} ({}) in block {} carries topic {}; this module reads that factory's "
            "{}.".format(factory.label, factory.address, _log_block(log), topics[0],
                         factory.created_event)
        )
    if len(topics) != factory.created_topic_count:
        raise FactoryLogMismatch(
            "a {} creation log in block {} carries {} topic(s); {} indexes {}. A log with the "
            "wrong topic count is a different event that happens to share a signature "
            "hash.".format(factory.label, _log_block(log), len(topics), factory.created_event,
                           factory.created_topic_count)
        )
    side0 = _address_of_word(topics[1][2:], "token0", factory)
    side1 = _address_of_word(topics[2][2:], "token1", factory)
    words = _data_words(log, factory)
    pool = _address_of_word(words[factory.pool_data_word], "the pool address", factory)
    return side0, side1, pool


# -- the covered factories, confirmed rather than asserted -----------------------


def factory_code_lengths(client, factory):
    """``(before, at)`` — the length of the factory's code in the block before and of its creation.

    Two ``eth_getCode`` calls, and the pair is the measurement: code at ``created_block`` and none
    at the block before it is what says the contract was created *in* that block. One call could
    only say it exists by then.
    """
    before = client.call(
        "eth_getCode", [factory.address, block_parameter(factory.created_block - 1)]
    )
    at = client.call("eth_getCode", [factory.address, block_parameter(factory.created_block)])
    return len(before or "0x"), len(at or "0x")


def confirm_factories(client, factories=COVERED_FACTORIES, to_block=None):
    """Each factory carries code from its stated creation block and not before. Returns the tuple.

    :raises FactoryNotAtStatedBlock: the constant is wrong in either direction, or ``to_block``
        precedes a factory's existence — a sweep that ends before its own lower bound searched
        nothing and must not report a refusal as though it had.
    """
    for factory in factories:
        before, at = factory_code_lengths(client, factory)
        if before != len("0x") or at <= len("0x"):
            raise FactoryNotAtStatedBlock(
                "{} ({}) has {} hex digits of code at block {} and {} at {}. This module sweeps "
                "from {} because that is the block the factory was created in; if it existed "
                "earlier, every pool created before that height went unsearched and a derived "
                "start is the earliest pool this run happened to look at rather than the "
                "earliest that exists.".format(
                    factory.label, factory.address, before - 2, factory.created_block - 1,
                    at - 2, factory.created_block, factory.created_block,
                )
            )
        if to_block is not None and to_block < factory.created_block:
            raise FactoryNotAtStatedBlock(
                "the sweep would end at block {}, before {} was created at {}. Nothing would be "
                "searched on that factory, and a refusal from a search that never ran reads "
                "exactly like a refusal from one that did.".format(
                    to_block, factory.label, factory.created_block
                )
            )
    return tuple(factories)


def _factory_for(address, factories):
    for factory in factories:
        if factory.address == normalise_asset(address):
            return factory
    raise UnrecognisedFactory(
        "a creation log came back from {}, which is not one of the {} covered "
        "factories ({}).".format(
            normalise_asset(address), len(factories),
            ", ".join("{} {}".format(f.label, f.address) for f in factories),
        )
    )


def _require_covered(factories):
    known = {f.address: f for f in COVERED_FACTORIES}
    for factory in factories:
        if not isinstance(factory, Factory):
            raise UnrecognisedFactory(
                "factories must be Factory values naming their creation event and pool data word; "
                "got {}. An address alone does not say how to read the factory's "
                "logs.".format(type(factory).__name__)
            )
        declared = known.get(factory.address)
        if declared != factory:
            raise UnrecognisedFactory(
                "{} ({}) is not a factory this module knows how to read, or is one whose declared "
                "event layout differs from the covered one. Covered: {}. Not "
                "covered: {}. An unrecognised venue must produce a refusal and therefore a "
                "quarantine — never a default date, and never a pool address read out of an "
                "event layout nobody confirmed.".format(
                    factory.label, factory.address,
                    ", ".join("{} {}".format(f.label, f.address) for f in COVERED_FACTORIES),
                    "; ".join(NOT_COVERED),
                )
            )
    return tuple(factories)


# -- the sweep, which needs a node with no range cap ------------------------------


def covered_pools(client, tokens, to_block, factories=COVERED_FACTORIES, chunk=CHUNK_BLOCKS):
    """Every pool a covered factory created for any of ``tokens``, at or before ``to_block``.

    Returns ``{token: (CoveredPool, ...)}`` in creation order, with an entry — possibly empty — for
    every token asked about.

    **This is not the default discovery, and on the endpoints this repository has it cannot run.**
    The sweep runs from the earliest covered factory's creation block to ``to_block`` in ``chunk``
    slices — 6.9 million blocks — and every free endpoint in
    :data:`transport.endpoints.DEFAULT_ENDPOINTS` now caps a log range at 10 or 50 blocks, which
    makes one sweep hundreds of thousands of requests. :data:`CREATE2_DERIVATION` is what
    :func:`derive_token_starts` uses instead.

    It is kept, and kept correct, because on a node without that cap it is the **wider** search:
    two calls per slice — an indexed token argument can be matched in one position at a time, and a
    pool holds its token as either ``token0`` or ``token1`` — and it therefore finds a pool against
    *any* counterparty, which is the one thing the derivation cannot do. Every token is in one
    filter, so the cost is the range and not the number of tokens.

    The recorded empty answers are the evidence for the negative half of that: "no covered factory
    created a pool for this token in 6.9 million blocks" is one recorded refusal to produce a log
    per slice, not a sentence in a docstring.
    """
    factories = _require_covered(factories)
    if not isinstance(chunk, int) or isinstance(chunk, bool) or chunk < 1:
        raise ValueError(
            "chunk must be a positive number of blocks, got {!r}. Zero or negative would advance "
            "the sweep nowhere and report every token as having no pool.".format(chunk)
        )
    wanted = _normalised_tokens(tokens)
    found = {token: [] for token in wanted}
    words = sorted(topic_word(token) for token in wanted)
    addresses = [factory.address for factory in factories]
    signatures = [factory.created_event for factory in factories]
    lower = min(factory.created_block for factory in factories)

    at = lower
    while at <= to_block:
        upper = min(at + chunk - 1, to_block)
        for position in (1, 2):
            topics = ([signatures, words, None] if position == 1
                      else [signatures, None, words])
            for log in client.get_logs(from_block=at, to_block=upper,
                                       address=addresses, topics=topics):
                factory = _factory_for(log["address"], factories)
                side0, side1, pool = _pool_from_created_log(log, factory)
                for token, counterparty in ((side0, side1), (side1, side0)):
                    if token in found:
                        found[token].append(CoveredPool(
                            address=pool,
                            factory=factory.address,
                            venue=factory.label,
                            created_block=_log_block(log),
                            token=token,
                            counterparty=counterparty,
                        ))
        at = upper + 1

    return {
        token: tuple(sorted(set(pools), key=lambda p: (p.created_block, p.address)))
        for token, pools in found.items()
    }


# -- the derivation, which needs no range at all ----------------------------------


#: Which :class:`pipeline.pooladdress.Create2Venue` derives a given covered factory's addresses,
#: keyed by factory address. A covered factory with no entry here raises
#: :class:`UnrecognisedFactory` rather than contributing no pools: a factory silently searched by
#: nothing looks exactly like a factory that created nothing, and the second is a date.
DERIVATION_VENUES = {
    UNISWAP_V2_FACTORY.address: UNISWAP_V2_VENUE,
    SUSHISWAP_FACTORY.address: SUSHISWAP_VENUE,
    UNISWAP_V3_FACTORY.address: UNISWAP_V3_VENUE,
}


def code_length(client, address, block):
    """Hex digits of code at ``address`` as of ``block`` — ``0`` for an address with none.

    A height, never a tag: whether a pool exists *today* is a different question from whether it
    existed at the marking horizon, and answering the first would let a pool created after the
    horizon contribute a start to a run that ends before it.
    """
    code = client.call("eth_getCode", [address, block_parameter(block)])
    return len(code or "0x") - len("0x")


def creation_block(client, address, lower, upper):
    """The first block in ``[lower, upper]`` at which ``address`` carries code. Binary search.

    ``upper`` must already be known to carry code — the caller establishes that when it decides the
    pool exists at all — and ``lower`` is the block its factory was created in, because a pool
    cannot precede its own factory. Roughly 24 ``eth_getCode`` calls over the two factories' range,
    none of them a log filter and none of them subject to a range cap.

    Guarantees the earliest block at which code was present **assuming code, once present, stays
    present**. That is not true of contracts in general and it is true of these: the address is a
    CREATE2 address whose init code hash is pinned in :mod:`pipeline.pooladdress`, so the code that
    can be there is the pair's or the pool's, and neither contains ``SELFDESTRUCT``.

    :raises FactoryNotAtStatedBlock: code is already present at ``lower - 1``, before the factory
        existed. Whatever is at that address, this factory did not deploy it, and taking its
        creation block would date the token from a contract that is not the pool.
    """
    if code_length(client, address, lower - 1):
        raise FactoryNotAtStatedBlock(
            "{} carries code at block {}, before the factory that would have created it existed "
            "at {}. A derived address is only meaningful as 'where that factory's pool would be'; "
            "a contract there beforehand is some other deployment, and dating the token from it "
            "would put the start before the venue.".format(address, lower - 1, lower)
        )
    low, high = lower, upper
    while low < high:
        middle = (low + high) // 2
        if code_length(client, address, middle):
            high = middle
        else:
            low = middle + 1
    return low


def _venue_for(factory):
    venue = DERIVATION_VENUES.get(factory.address)
    if venue is None:
        raise UnrecognisedFactory(
            "{} ({}) has no CREATE2 venue in DERIVATION_VENUES, so no address can be derived for "
            "its pools. Searching the remaining factories anyway would report 'no pool' for a "
            "token whose only pool is on this one — a refusal from a search that never "
            "ran.".format(factory.label, factory.address)
        )
    return venue


def pools_by_derivation(client, tokens, to_block, factories=COVERED_FACTORIES,
                        counterparties=DERIVED_COUNTERPARTIES):
    """Every covered pool for ``tokens`` that carries code at ``to_block``, found by CREATE2.

    Returns ``{token: (CoveredPool, ...)}`` in creation order, with an entry — possibly empty — for
    every token asked about, exactly as :func:`covered_pools` does. The two are interchangeable at
    that boundary and are not interchangeable in what they cover: this one looks only where it can
    name both sides of the pair and only at the fee tiers
    :data:`pipeline.pooladdress.FEE_TIERS` pins, which is :data:`DERIVED_NOT_COVERED`.

    Cost, and why this one can actually run: one ``eth_getCode`` per candidate address — five per
    (token, counterparty) with the default venues, so twenty per token — plus about 25 more for
    each candidate that turns out to exist, to date it. No log range anywhere, so no endpoint's
    range cap applies.

    Guarantees that every returned pool is a contract that existed at ``to_block`` at the address
    the named factory's CREATE2 puts its pool for that pair. Guarantees nothing about a pool it did
    not derive an address for, and nothing about liquidity or trading — that is
    :func:`pool_trading_start`.
    """
    factories = _require_covered(factories)
    wanted = _normalised_tokens(tokens)
    quotes = _normalised_counterparties(counterparties)

    found = {}
    for token in wanted:
        pools = []
        for factory in factories:
            venue = _venue_for(factory)
            for counterparty in quotes:
                if counterparty == token:
                    # A token is not its own counterparty, and a token that *is* a quote asset is
                    # an ordinary case rather than an error: WETH has no WETH/WETH pool and the
                    # other three counterparties still apply.
                    continue
                for candidate in derived_pools(token, counterparty, venues=(venue,)):
                    if not code_length(client, candidate.address, to_block):
                        continue
                    pools.append(CoveredPool(
                        address=candidate.address,
                        factory=factory.address,
                        venue=candidate.label,
                        created_block=creation_block(
                            client, candidate.address, factory.created_block, to_block
                        ),
                        token=token,
                        counterparty=counterparty,
                    ))
        found[token] = tuple(sorted(set(pools), key=lambda p: (p.created_block, p.address)))
    return found


def _normalised_counterparties(counterparties):
    quotes = []
    for counterparty in counterparties:
        normalised = normalise_asset(counterparty)
        if normalised in quotes:
            raise ValueError(
                "{} appears twice in the counterparty list (spelled {!r}). One counterparty is "
                "one entry: the duplicate costs a second eth_getCode per venue and per tier and "
                "answers the same question.".format(normalised, counterparty)
            )
        if normalised not in QUOTE_ASSETS:
            raise UnrecognisedFactory(
                "{} is not one of the {} §4 quote assets this derivation covers ({}). The list is "
                "a way to *narrow* the search, not to widen it: DERIVED_NOT_COVERED — which is "
                "written verbatim into every refusal — names those four, so a run that searched a "
                "fifth would hand somebody working the queue a refusal describing a blind spot the "
                "search did not have.".format(
                    normalised, len(DERIVED_COUNTERPARTIES), ", ".join(DERIVED_COUNTERPARTIES)
                )
            )
        quotes.append(normalised)
    if not quotes:
        raise ValueError(
            "no counterparties were given, so no pair can be named and no address can be derived. "
            "An empty list would report every token as having no pool — a refusal from a search "
            "that never ran, which reads exactly like a refusal from one that did."
        )
    return tuple(quotes)


# -- when a pool was first used, without reading a single log ---------------------


def probe_reading(client, probe, address, block):
    """The whole of the pool's :class:`ActivityProbe` returndata at ``block``, as one int.

    Empty returndata is ``0``, and that is the ordinary answer rather than an error: an address
    with no code has no function to run, and "no code yet" and "deployed but never touched" are the
    same statement for this search's purpose — the pool had emitted nothing by that block.

    The words are compared as one number because each of them is part of the evidence.
    ``getReserves()`` on a pair drained back to nothing has two zero reserves and a non-zero
    ``blockTimestampLast``, and reading only the reserves would call that pair untouched.

    :raises PoolStateUnreadable: the answer is neither empty nor exactly ``probe.words`` 32-byte
        words of hex. See that class for why an address whose init code hash is pinned makes a
        wrong width a defect here rather than a limit on what could be measured.
    """
    result = client.call(
        "eth_call", [{"to": address, "data": probe.selector}, block_parameter(block)]
    )
    body = result[2:] if isinstance(result, str) and result.startswith("0x") else None
    if body is None or (body and (len(body) != 64 * probe.words or any(
            character not in "0123456789abcdefABCDEF" for character in body))):
        raise PoolStateUnreadable(
            "{}.{} at block {} answered {!r}. That function returns {} 32-byte word(s), and this "
            "address holds a contract whose init code hash this module pinned — so an answer of "
            "another width is a wrong selector or a wrong constant here, not a pool with an "
            "opinion. Reading it as a number anyway would give the binary search a "
            "monotone-looking answer assembled from the wrong bytes.".format(
                address, probe.signature, block, result, probe.words)
        )
    return int(body, 16) if body else 0


def first_active_block(client, pool, factory, to_block):
    """The first block in ``[created_block, to_block]`` at which ``pool``'s own storage has moved.

    ``None`` when it has not moved by ``to_block`` — which is not an error: a pool created and
    never used has no §4.7 start, and neither does one first used after the horizon.

    Returns the pool's ``created_block`` unchanged for a factory that declares no
    :class:`ActivityProbe`, so a venue with no such reading is scanned from creation rather than
    skipped. About 24 ``eth_call``\\ s where there is a probe, none of them a log range.

    Guarantees, by :attr:`ActivityProbe.zero_means`, that the pool emitted no ``Mint`` and no
    ``Swap`` before the block returned — which is what makes starting the log scan there a
    narrowing rather than a gamble. Guarantees the **first** such block only because
    :attr:`ActivityProbe.monotone_because` holds: a binary search over a predicate that flickers
    returns some crossing rather than the earliest one, and a later crossing would put the scan's
    floor above the swap it is looking for. Guarantees nothing about what happened *in* that block
    — the ``Mint`` and the ``Swap`` are read from the logs, by :func:`pool_trading_start`.
    """
    probe = factory.activity_probe
    if probe is None:
        return pool.created_block
    if not probe_reading(client, probe, pool.address, to_block):
        return None
    low, high = pool.created_block, to_block
    while low < high:
        middle = (low + high) // 2
        if probe_reading(client, probe, pool.address, middle):
            high = middle
        else:
            low = middle + 1
    return low


# -- what a pool traded, once it is known where it is -----------------------------


@dataclass(frozen=True)
class PoolTrade:
    """What one pool's logs said about §4.7, and how far this run actually looked.

    ``swap_block`` is the first swap found and ``liquidity_first`` whether a ``Mint`` precedes it in
    ``(block, logIndex)`` order; both are ``None`` when no swap was found.

    ``exhausted`` is the field this type exists for. Without it "no swap" is one value covering two
    statements — *this pool never traded* and *this pool did not trade in the blocks I read* — and
    a caller has to treat them differently: the first lets it move on to a later pool, the second
    does not, because moving on would take a later pool's swap as the token's start and file the
    token as younger than it is. A bare ``(None, None)`` return could not tell the caller which one
    it had.
    """

    swap_block: Optional[int]
    liquidity_first: Optional[bool]
    scanned_from: Optional[int]
    scanned_to: Optional[int]
    exhausted: bool = False

    def __post_init__(self):
        if (self.swap_block is None) != (self.liquidity_first is None):
            raise ValueError(
                "a swap and whether liquidity preceded it are one answer; got swap_block={!r} "
                "liquidity_first={!r}. A swap with no liquidity verdict would be admitted as a "
                "start with §4.7's conjunction unchecked.".format(
                    self.swap_block, self.liquidity_first)
            )
        if self.exhausted and self.swap_block is not None:
            raise ValueError(
                "a scan that found a swap in block {} is not exhausted: it stopped because it had "
                "the answer.".format(self.swap_block)
            )


def pool_trading_start(client, pool, factory, to_block, chunk=CHUNK_BLOCKS,
                       scan_blocks=SCAN_BLOCKS):
    """§4.7 for one pool, as a :class:`PoolTrade`.

    The scan runs from the pool's first active block (:func:`first_active_block`) — not from its
    creation, see the module docstring — to the lower of ``to_block`` and ``scan_blocks`` past that
    floor, in ``chunk``-block slices. It stops at the slice holding the first swap.

    Mints and swaps come back in one filter per slice, so the mint that established the liquidity is
    read from the same answer as the swap that used it. ``to_block`` is what the caller lowers to a
    start it has already established, because a swap later than that one cannot be the earliest.

    Guarantees that a returned ``swap_block`` is the pool's **first** swap at or before
    ``to_block`` — not merely the first one in the range scanned — because the floor is a block the
    pool had emitted nothing before. Guarantees, when ``exhausted`` is false and no swap was found,
    that the pool served none at all by ``to_block``. Guarantees nothing whatever about the blocks
    past the budget when ``exhausted`` is true, which is what that flag is for.
    """
    floor = first_active_block(client, pool, factory, to_block)
    if floor is None:
        return PoolTrade(swap_block=None, liquidity_first=None,
                         scanned_from=None, scanned_to=None)
    ceiling = min(to_block, floor + scan_blocks - 1)

    seen = []
    at = floor
    while at <= ceiling:
        upper = min(at + chunk - 1, ceiling)
        seen.extend(client.get_logs(
            from_block=at, to_block=upper, address=pool.address,
            topics=[[factory.mint_event, factory.swap_event]],
        ))
        if any(log["topics"][0] == factory.swap_event for log in seen):
            break
        at = upper + 1

    ordered = sorted(seen, key=lambda log: (_log_block(log), _log_index(log)))
    minted = False
    for log in ordered:
        if log["topics"][0] == factory.swap_event:
            return PoolTrade(swap_block=_log_block(log), liquidity_first=minted,
                             scanned_from=floor, scanned_to=ceiling)
        minted = True
    return PoolTrade(swap_block=None, liquidity_first=None, scanned_from=floor,
                     scanned_to=ceiling, exhausted=ceiling < to_block)


# -- which of the two searches ran, and what it could not see ---------------------


@dataclass(frozen=True)
class PoolDiscovery:
    """One way of finding a token's pools, carrying its own honest list of what it cannot find.

    ``not_covered`` is the field this type exists for. The two discoveries do not have the same
    blind spots — the derivation cannot see a pool against a token it cannot name, the log sweep
    can — so a single module-level list would describe whichever one somebody wrote it for and
    would be quietly wrong about the other. Pairing the list with the search means the refusal a
    caller reads names the gaps of the search that actually ran.
    """

    label: str
    find: Callable
    not_covered: Tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "not_covered", tuple(self.not_covered))
        if not self.not_covered:
            raise ValueError(
                "{} declares no uncovered venues. Every search of this chain has some — a "
                "discovery claiming otherwise would put 'nothing was missed' into a refusal that "
                "somebody works a queue from.".format(self.label)
            )


def _find_by_factory_logs(client, tokens, to_block, factories, chunk):
    return covered_pools(client, tokens, to_block, factories=factories, chunk=chunk)


def _find_by_derivation(client, tokens, to_block, factories, chunk):
    # ``chunk`` is a log-range size and this search reads no log ranges. Accepted and ignored so
    # both discoveries have one signature; the parameter still bounds pool_trading_start, which
    # runs after either of them.
    return pools_by_derivation(client, tokens, to_block, factories=factories)


#: Read the factories' creation logs. The direct search, and the one the endpoints refuse.
FACTORY_LOG_SWEEP = PoolDiscovery(
    label="factory creation logs",
    find=_find_by_factory_logs,
    not_covered=NOT_COVERED,
)

#: Compute the addresses and ask whether they hold code. The default, because it is the one that
#: can run — see this module's docstring for the range caps that decided it.
CREATE2_DERIVATION = PoolDiscovery(
    label="CREATE2 address derivation",
    find=_find_by_derivation,
    not_covered=DERIVED_NOT_COVERED,
)


def derive_token_starts(client, tokens, to_block, factories=COVERED_FACTORIES,
                        chunk=CHUNK_BLOCKS, discovery=CREATE2_DERIVATION,
                        scan_blocks=SCAN_BLOCKS):
    """§4.7's trading start for each token, or a refusal saying why there is none.

    Returns ``{token: TokenStartFinding}`` with an entry for every token asked about. ``to_block``
    is the marking horizon: a pool created after it cannot have produced a buy inside the run.

    Guarantees the earliest first-swap block over the pools ``discovery`` found, with minted
    liquidity before that swap in log order, and the timestamp the chain gives that block.
    Guarantees nothing about venues outside :data:`COVERED_FACTORIES`, and nothing about the pools
    the chosen discovery cannot see — ``discovery.not_covered`` is that list and it is written into
    every refusal this function returns. See the module docstring for why the resulting bias can
    only be towards *older*, and never towards a token looking younger than it is.

    ``scan_blocks`` bounds how far past a pool's first activity the log scan runs. It decides whether a
    token gets an answer, never which answer: a start established inside the bound is the same
    block at any bound, and a pool the bound cut short refuses rather than yielding to a later
    pool.
    """
    if not isinstance(discovery, PoolDiscovery):
        raise TokenStartDefect(
            "discovery must be a PoolDiscovery pairing a search with the venues it cannot see; got "
            "{}. A bare function would leave the refusal describing some other search's blind "
            "spots.".format(type(discovery).__name__)
        )
    factories = confirm_factories(client, _require_covered(factories), to_block=to_block)
    pools_by_token = discovery.find(client, tokens, to_block, factories, chunk)
    searched_from = min(factory.created_block for factory in factories)

    findings = {}
    for token, pools in sorted(pools_by_token.items()):
        findings[token] = _finding_for(
            client, token, pools, factories, searched_from, to_block, chunk, discovery,
            scan_blocks,
        )
    return findings


def _finding_for(client, token, pools, factories, searched_from, to_block, chunk, discovery,
                 scan_blocks):
    notes = []
    best_block = None
    best_pool = None

    for pool in pools:
        if best_block is not None and pool.created_block >= best_block:
            notes.append(
                "not_searched:{}:created_at_{}_at_or_after_the_start_{}".format(
                    pool.address, pool.created_block, best_block
                )
            )
            continue
        ceiling = to_block if best_block is None else best_block
        factory = _factory_for(pool.factory, factories)
        trade = pool_trading_start(
            client, pool, factory, ceiling, chunk=chunk, scan_blocks=scan_blocks
        )
        swap_block, liquidity_first = trade.swap_block, trade.liquidity_first
        if swap_block is None and trade.exhausted:
            return TokenStartFinding(
                token=token, start=None, pool=None, pools=pools,
                searched_from=searched_from, searched_to=to_block,
                refusal=(
                    "first_trade_outside_the_scanned_range: {} was first used in block {} and served "
                    "no swap through block {}, where this run's budget of {} blocks past that "
                    "ran out — {} was the ceiling asked for. That is 'not seen', not "
                    "'never traded', and the two are not interchangeable here: passing this pool "
                    "over would take a later pool's first swap as the token's start and file the "
                    "token as younger than it is.".format(
                        pool.address, trade.scanned_from, trade.scanned_to, scan_blocks, ceiling,
                    )
                ),
                notes=tuple(notes),
            )
        if swap_block is None:
            notes.append("no_swap_by_{}:{}".format(ceiling, pool.address))
            continue
        if best_block is not None and swap_block >= best_block:
            # It cannot be the earliest, so its liquidity is not this run's business: a pool that
            # loses the comparison must not be able to refuse the token.
            notes.append(
                "not_earlier:{}:first_swap_{}_at_or_after_{}".format(
                    pool.address, swap_block, best_block
                )
            )
            continue
        if not liquidity_first:
            return TokenStartFinding(
                token=token, start=None, pool=None, pools=pools,
                searched_from=searched_from, searched_to=to_block,
                refusal=(
                    "liquidity_not_established: {} served a swap in block {} with no Mint before "
                    "it in log order, so §4.7's 'usable liquidity AND at least one real swap' "
                    "cannot be established there. Skipping this pool and taking a later one would "
                    "move the token's start forward and file it as younger than it is, which is "
                    "the direction the Edge Origin condition is measuring — refused "
                    "instead.".format(pool.address, swap_block)
                ),
                notes=tuple(notes),
            )
        best_block, best_pool = swap_block, pool

    if best_block is None:
        return TokenStartFinding(
            token=token, start=None, pool=None, pools=pools,
            searched_from=searched_from, searched_to=to_block,
            refusal=_no_start_refusal(
                token, pools, factories, searched_from, to_block, discovery
            ),
            notes=tuple(notes),
        )

    header = block_header(client, best_block)
    if header.number != best_block:
        raise FactoryLogMismatch(
            "the header read for block {} reports number {}. The start's timestamp would be "
            "another block's second.".format(best_block, header.number)
        )
    return TokenStartFinding(
        token=token,
        start=TokenStart(block=best_block, timestamp=header.timestamp),
        pool=best_pool.address,
        pools=pools,
        searched_from=searched_from,
        searched_to=to_block,
        notes=tuple(notes),
    )


def _no_start_refusal(token, pools, factories, searched_from, to_block, discovery):
    venues = ", ".join("{} {}".format(f.label, f.address) for f in factories)
    if not pools:
        return (
            "no_pool_on_covered_factories: no pool for {} was found on {} between blocks {} and "
            "{}, searched by {}. That is not 'old', it is unknown — the token's market may be "
            "somewhere that search does not cover ({}) — and an unknown age filed as bucket D is "
            "an unknown filed as a fact.".format(
                token, venues, searched_from, to_block, discovery.label,
                "; ".join(discovery.not_covered),
            )
        )
    return (
        "no_swap_in_any_covered_pool: {} has {} covered pool(s) — {} — and none of them served a "
        "swap by block {}; some may never have been used at all. §4.7 needs liquidity **and** a "
        "real trade, so pool creation alone is not a start; the token has no established age "
        "rather than a young one.".format(
            token, len(pools), ", ".join(pool.address for pool in pools), to_block
        )
    )


def _normalised_tokens(tokens):
    wanted = []
    for token in tokens:
        normalised = normalise_asset(token)
        if normalised in wanted:
            raise ValueError(
                "{} appears twice in the token list (spelled {!r}). One token is one entry: two "
                "would have the sweep's cost counted twice and would make the returned mapping "
                "smaller than the list asked about, which is how a token silently goes "
                "underived.".format(normalised, token)
            )
        wanted.append(normalised)
    if not wanted:
        raise ValueError(
            "no tokens were asked about. An empty sweep costs every one of its recorded calls and "
            "answers nothing; a caller with no tokens should not be calling this."
        )
    return tuple(wanted)


def token_starts_of(findings):
    """The ``{token: TokenStart}`` mapping ``WindowConfig`` takes — established findings only.

    A refused token is **absent**, not present with a placeholder. That absence is what
    ``pipeline.run`` turns into the §4.7 quarantine it already raises, and it is the whole reason
    this function is a filter rather than a default: any date invented here would be indistinguishable
    downstream from one the chain supplied.
    """
    return {
        token: finding.start
        for token, finding in sorted(findings.items())
        if finding.established
    }


def refusals_of(findings):
    """``{token: refusal}`` for the tokens with no derived start. The other half of the answer."""
    return {
        token: finding.refusal
        for token, finding in sorted(findings.items())
        if not finding.established
    }
