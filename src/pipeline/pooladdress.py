"""A Uniswap pool's address, computed from the token pair instead of searched for.

    pool_address(UNISWAP_V2, token, WETH)          -> "0x…"
    pool_address(UNISWAP_V3, token, WETH, fee=500) -> "0x…"
    derived_pools(token, counterparty)             -> (DerivedPool, …) — v2 plus every covered tier

The problem this closes
-----------------------

:mod:`pipeline.tokenstart` needs the pools a token has ever had, and its first way of getting them
was to read ``PairCreated`` / ``PoolCreated`` off the two factories. That search is not slow, it is
**unavailable**: the v2 factory was created in block 10,000,835, the marking horizon is 16,943,478,
and every free endpoint in :data:`transport.endpoints.DEFAULT_ENDPOINTS` now caps ``eth_getLogs``
at 10 or 50 blocks — "You can make eth_getLogs requests with up to a 10 block range" is roughly
700,000 requests for one sweep.

Both factories deploy with ``CREATE2``, which means the address is not a fact to be discovered at
all. It is a hash of the deployer, the pair, and the pool's init code::

    v2 pair   keccak(0xff ++ factory ++ keccak(token0 ++ token1) ++ init_code_hash)[12:]
    v3 pool   keccak(0xff ++ factory ++ keccak(abi(token0, token1, fee)) ++ init_code_hash)[12:]

with ``token0 < token1`` compared as 20-byte addresses — the ordering the factories themselves
impose, and the reason ``pair(A,B)`` and ``pair(B,A)`` are one pool rather than two. Every address
this module returns is arithmetic on constants: no endpoint is contacted, no range is scanned, and
the answer for a token first seen a minute ago costs exactly what the answer for WETH costs.

What a derived address is, and what it is not
---------------------------------------------

It is **where the pool would be if it exists**. That is the whole of the claim. CREATE2 fixes the
address before the pool is deployed, so this module returns an address for every pair including the
overwhelming majority that were never created; whether code lives there is a question for the chain
(:mod:`pipeline.tokenstart` asks it with ``eth_getCode``), and this module answers no part of it.

It is also not "the pool this run observed". A buy receipt names the pool it settled through, and
§4.7 wants the *earliest* pool across all of them — a buyer on the second pool is not an early
buyer of the token. Using an observed pool as the start's source yields a later start, which makes
the buy look earlier, which moves it towards bucket A: a wrong number in the direction that
flatters. Nothing here reads a receipt.

Which venues and tiers are covered, and what an uncovered one costs
-------------------------------------------------------------------

:data:`DERIVABLE_VENUES` is the whole of the coverage: Uniswap v2, and Uniswap v3 at the four fee
tiers in :data:`FEE_TIERS` — 0.01%, 0.05%, 0.30% and 1.00%, the tiers the mainnet v3 factory has
enabled. A venue or a tier that is not in those tuples is a pool this module **cannot see**, and it
must reach the caller's refusal rather than a default: a token whose only market is a 0.02% pool on
some fork has no derived pool at all, and "no pool found" quarantines the buy while a default date
would file an unknown age as a fact. :data:`NOT_DERIVABLE` is that statement in words, and
:mod:`pipeline.tokenstart` carries it into the refusal text.

Asking for a tier outside :data:`FEE_TIERS` **raises** rather than returning an address, because
the address would be perfectly well-formed. A fork with its own init code hash is a different
constant and therefore a different module-level entry, never a parameter.

How the constants were verified
--------------------------------

An init code hash is 32 bytes nobody can eyeball. Both are checked at import
(:func:`_require_the_pinned_pools_derive`) by deriving two pool addresses that already appear in
this repository's own output: the USDC/WETH v2 pair ``0xB4e16d01…`` and the USDC/WETH 0.05% v3 pool
``0x88e6A0c2…``. A derivation that cannot reproduce those two is not ready to be trusted on a token
nobody knows, and the check runs at import rather than in a test because a wrong constant here
produces plausible addresses rather than an error.
"""

from dataclasses import dataclass
from typing import Optional, Tuple  # noqa: F401  (3.9-compatible annotations)

from contracts import USDC, WETH, normalise_asset

from .keccak import keccak256

#: Uniswap v2's factory. The same address :data:`pipeline.tokenstart.UNISWAP_V2_FACTORY` carries;
#: a test pins the two spellings together so they cannot drift apart.
UNISWAP_V2_FACTORY_ADDRESS = "0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f"

#: Uniswap v3's factory, likewise.
UNISWAP_V3_FACTORY_ADDRESS = "0x1f98431c8ad98523631ae4a59f267346ea31f984"

#: SushiSwap's factory. A Uniswap-v2 fork: the same CREATE2 shape, a different factory and a
#: different init code hash, so the same pair has a different address here. It is covered because
#: two tokens in the real case runs have their earliest pool on it and were refused for want of it
#: -- ``no_pool_on_covered_factories`` -- and a token whose earliest market this module cannot see
#: gets a §4.7 start that is too late, which buckets its buys as younger than they are.
SUSHISWAP_FACTORY_ADDRESS = "0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac"

#: ``keccak256(type(UniswapV2Pair).creationCode)`` — the constant ``UniswapV2Library.pairFor``
#: hard-codes in ``@uniswap/v2-periphery``, and the one the router itself uses to address a pair
#: without calling the factory. Verified at import against the USDC/WETH pair; see
#: :func:`_require_the_pinned_pools_derive`.
V2_INIT_CODE_HASH = "0x96e8ac4277198ff8b6f785478aa9a39f403cb768dd02cbee326c3e7da348845f"

#: SushiSwap's, which differs from Uniswap's because the pair bytecode differs. Verified at import
#: against two pairs whose addresses are checkable on any explorer -- WETH/USDT at
#: ``0x06da0fd4…`` and USDC/WETH at ``0x397ff154…`` -- for the same reason Uniswap's is: an init
#: code hash that is wrong produces a well-formed address for a contract that does not exist, and
#: every pool read against it would then refuse with "no code", which reads as "this token has no
#: market" rather than as "this constant is wrong".
SUSHI_INIT_CODE_HASH = "0xe18a34eb0e04b04f7a0ac29a6e80748dca96319b42c54d679cb821dca90c6303"

#: ``POOL_INIT_CODE_HASH`` from ``PoolAddress.sol`` in ``@uniswap/v3-periphery`` — the constant
#: ``PoolAddress.computeAddress`` uses. Verified at import against the USDC/WETH 0.05% pool.
V3_INIT_CODE_HASH = "0xe34f199b19b2b4f47f68442619d555527d244f78a3297ea89325f843f87b8b54"

#: The v3 fee tiers this module derives, in hundredths of a basis point — 0.01%, 0.05%, 0.30% and
#: 1.00%. These are the four the Ethereum mainnet ``UniswapV3Factory`` has enabled: three at
#: deployment and 100 added later by governance.
#:
#: The tuple is the coverage, and narrowing or widening it is a change to what can be seen rather
#: than a change to a search's cost. A tier enabled after this was written is a pool this module
#: derives no address for, which is why :data:`NOT_DERIVABLE` says so out loud.
FEE_TIERS = (100, 500, 3000, 10000)

#: What each tier is called where a human reads it. Presentation only; nothing branches on it.
FEE_TIER_LABELS = {
    100: "0.01%",
    500: "0.05%",
    3000: "0.30%",
    10000: "1.00%",
}

#: The honest size of the gap, carried into :mod:`pipeline.tokenstart`'s refusal text. Each line is
#: a pool a derivation cannot produce an address for, and therefore a token whose age may be
#: unknown rather than old.
NOT_DERIVABLE = (
    "ShibaSwap and every other Uniswap-v2 fork except SushiSwap — a different factory and a "
    "different "
    "init code hash, so a different address for the same pair",
    "any Uniswap v3 fee tier outside {} — an address is only derivable for a tier this module "
    "pins".format(", ".join(FEE_TIER_LABELS[tier] for tier in FEE_TIERS)),
    "Curve, Balancer, Bancor and any other pool shape",
    "Uniswap v4 and any singleton-pool AMM, which has no per-pair address to derive at all",
    "any venue on a chain other than Ethereum mainnet",
    "a relaunch under a new token contract, which is simply a different token",
)


class PoolAddressDefect(ValueError):
    """A defect in what assembled the derivation, never a limit on what the chain would say.

    Everything in this module is arithmetic, so there is no measurement to be limited: an address
    is either derivable from the inputs or the inputs are wrong. The limits that *are* measurement
    limits — an uncovered venue, an uncovered tier — are :data:`NOT_DERIVABLE`, and they belong to
    the caller's refusal rather than to an exception here.
    """


class MalformedAddress(PoolAddressDefect):
    """A token or factory address is not 20 bytes of hex.

    Raised rather than coerced. ``normalise_asset`` lowercases and collapses native ETH onto WETH,
    and it is happy to hand back a 19-byte string; hashing that produces a well-formed pool address
    for a token that does not exist, and nothing downstream could tell it from a real one.
    """


class NotAPair(PoolAddressDefect):
    """Both sides of the pair are the same token. No factory creates such a pool."""


class UncoveredFeeTier(PoolAddressDefect):
    """A v3 fee asked for that this module does not pin, or a fee asked of a venue that has none.

    A defect and not a refusal, because the caller named the tier: :func:`derived_pools` enumerates
    only :data:`FEE_TIERS`, so reaching this means somebody passed a number. The *measurement*
    limit — that a pool at an unpinned tier is invisible — is carried by :data:`NOT_DERIVABLE`.
    """


class DerivationInconsistent(Exception):
    """A pinned init code hash does not reproduce a pool this repository already knows. At import.

    Deliberately not a :class:`PoolAddressDefect`: those are statements about a caller's arguments,
    and this is a statement about this file's constants. It is raised at import, before anything has
    been derived, because a wrong init code hash produces well-formed addresses for every pair —
    there is no input that would make it fail later, and no downstream check that would notice.
    """


# -- what an address has to be made of -------------------------------------------


def _require_address(value, what):
    if not isinstance(value, str):
        raise MalformedAddress("{} must be a 20-byte hex address, got {}".format(
            what, type(value).__name__))
    normalised = normalise_asset(value)
    if not normalised.startswith("0x") or len(normalised) != 42:
        raise MalformedAddress(
            "{} is {!r}, which is not 0x followed by 40 hex digits. A short or long address hashes "
            "to a well-formed pool address for a token that does not exist.".format(what, value)
        )
    try:
        int(normalised[2:], 16)
    except ValueError:
        raise MalformedAddress(
            "{} is {!r} — the 40 characters after 0x are not all hex digits.".format(what, value)
        )
    return normalised


def _require_hash32(value, what):
    if not isinstance(value, str) or not value.startswith("0x") or len(value) != 66:
        raise DerivationInconsistent(
            "{} is {!r}, which is not 0x followed by 64 hex digits.".format(what, value))
    try:
        int(value[2:], 16)
    except ValueError:
        raise DerivationInconsistent("{} is {!r} and is not hex.".format(what, value))
    return value


def _bytes_of(address):
    return bytes.fromhex(address[2:])


@dataclass(frozen=True)
class Create2Venue:
    """A factory whose pool addresses are ``CREATE2`` and whose salt this module knows how to build.

    ``fee_tiers`` empty means the venue has one pool per pair (v2); non-empty means the fee is part
    of the salt (v3) and only the listed tiers are covered. The distinction is a field rather than
    a branch on the label, so adding a venue is adding a value.
    """

    label: str
    factory: str
    init_code_hash: str
    fee_tiers: Tuple[int, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "factory", _require_address(self.factory, "factory"))
        object.__setattr__(self, "fee_tiers", tuple(self.fee_tiers))
        _require_hash32(self.init_code_hash, "{} init code hash".format(self.label))

    @property
    def has_fee_tiers(self):
        return bool(self.fee_tiers)


UNISWAP_V2 = Create2Venue(
    label="Uniswap v2",
    factory=UNISWAP_V2_FACTORY_ADDRESS,
    init_code_hash=V2_INIT_CODE_HASH,
)

SUSHISWAP = Create2Venue(
    label="SushiSwap",
    factory=SUSHISWAP_FACTORY_ADDRESS,
    init_code_hash=SUSHI_INIT_CODE_HASH,
)

UNISWAP_V3 = Create2Venue(
    label="Uniswap v3",
    factory=UNISWAP_V3_FACTORY_ADDRESS,
    init_code_hash=V3_INIT_CODE_HASH,
    fee_tiers=FEE_TIERS,
)

#: The venues an address can be derived for, in the order candidates are enumerated. Everything
#: else is in :data:`NOT_DERIVABLE`.
DERIVABLE_VENUES = (UNISWAP_V2, SUSHISWAP, UNISWAP_V3)


@dataclass(frozen=True)
class DerivedPool:
    """Where a pool would be, and what it would be a pool of.

    Carries no creation block and no liquidity, and that absence is the point: this is arithmetic
    on an address, not an observation. ``fee`` is ``None`` for a venue with one pool per pair.
    """

    address: str
    venue: str
    factory: str
    token0: str
    token1: str
    fee: Optional[int] = None

    @property
    def label(self):
        if self.fee is None:
            return self.venue
        return "{} {}".format(self.venue, FEE_TIER_LABELS.get(self.fee, "{} ppm".format(self.fee)))


# -- the addresses ---------------------------------------------------------------


def sorted_pair(token_a, token_b):
    """``(token0, token1)`` in the order the factory stores them: ascending by 20-byte address.

    Both factories sort the pair before hashing it, which is what makes ``pair(A,B)`` and
    ``pair(B,A)`` the same pool. Deriving with the caller's order instead would produce a second,
    entirely fictitious address for every pair given the wrong way round.

    :raises NotAPair: the two sides are the same token — including the case where one is native ETH
        and the other WETH, which ``normalise_asset`` collapses onto one address.
    """
    first = _require_address(token_a, "token_a")
    second = _require_address(token_b, "token_b")
    if first == second:
        raise NotAPair(
            "both sides of the pair are {}. No factory creates a pool of a token against itself, "
            "so this is a caller that has lost track of which asset is the counterparty — note "
            "that native ETH and WETH are one address here.".format(first)
        )
    return (first, second) if first < second else (second, first)


def _v2_salt(token0, token1):
    return keccak256(_bytes_of(token0) + _bytes_of(token1))


def _v3_salt(token0, token1, fee):
    # abi.encode(address,address,uint24): three 32-byte words, each left-padded.
    return keccak256(
        _bytes_of(token0).rjust(32, b"\x00")
        + _bytes_of(token1).rjust(32, b"\x00")
        + int(fee).to_bytes(32, "big")
    )


def _create2(deployer, salt, init_code_hash):
    digest = keccak256(b"\xff" + _bytes_of(deployer) + salt + bytes.fromhex(init_code_hash[2:]))
    return "0x" + digest[12:].hex()


def _require_fee(venue, fee):
    if not venue.has_fee_tiers:
        if fee is not None:
            raise UncoveredFeeTier(
                "{} has one pool per pair and no fee in its salt, so fee={!r} names nothing. "
                "Passing a fee here would be silently ignored and the caller would believe it had "
                "asked for a tier.".format(venue.label, fee)
            )
        return None
    if fee is None:
        raise UncoveredFeeTier(
            "{} pools are one per (pair, fee) and the fee is part of the salt, so there is no "
            "address without one. Covered tiers: {}.".format(
                venue.label,
                ", ".join("{} ({})".format(FEE_TIER_LABELS[t], t) for t in venue.fee_tiers),
            )
        )
    if isinstance(fee, bool) or not isinstance(fee, int):
        raise UncoveredFeeTier(
            "a fee tier is an integer number of hundredths of a basis point, got {}".format(
                type(fee).__name__)
        )
    if fee not in venue.fee_tiers:
        raise UncoveredFeeTier(
            "{} is not one of the {} fee tiers this module covers on {} ({}). An uncovered tier is "
            "a pool that cannot be seen, and that has to reach the caller's refusal — see "
            "NOT_DERIVABLE — rather than be answered with an address from some default "
            "tier.".format(
                fee, len(venue.fee_tiers), venue.label,
                ", ".join("{} ({})".format(FEE_TIER_LABELS[t], t) for t in venue.fee_tiers),
            )
        )
    return fee


def pool_address(venue, token_a, token_b, fee=None):
    """The ``CREATE2`` address of ``venue``'s pool for the pair. A string, never a lookup.

    Guarantees the address the factory would deploy to, for the venue and tier named. Guarantees
    **nothing** about whether a pool is there: every pair has an address and almost none have a
    pool. The caller establishes existence against the chain.

    :raises MalformedAddress: a side is not a 20-byte hex address.
    :raises NotAPair: both sides are the same token.
    :raises UncoveredFeeTier: the venue has tiers and this is not one of them, or has none and one
        was passed.
    """
    if not isinstance(venue, Create2Venue):
        raise PoolAddressDefect(
            "venue must be a Create2Venue naming its factory and init code hash; got {}. An "
            "address alone does not say what salt the factory hashes.".format(type(venue).__name__)
        )
    token0, token1 = sorted_pair(token_a, token_b)
    checked = _require_fee(venue, fee)
    salt = (_v2_salt(token0, token1) if checked is None
            else _v3_salt(token0, token1, checked))
    return _create2(venue.factory, salt, venue.init_code_hash)


def derive_pool(venue, token_a, token_b, fee=None):
    """:func:`pool_address` as a :class:`DerivedPool`, carrying what it was derived from."""
    token0, token1 = sorted_pair(token_a, token_b)
    checked = _require_fee(venue, fee)
    return DerivedPool(
        address=pool_address(venue, token0, token1, fee=checked),
        venue=venue.label,
        factory=venue.factory,
        token0=token0,
        token1=token1,
        fee=checked,
    )


def derived_pools(token, counterparty, venues=DERIVABLE_VENUES):
    """Every address a covered venue would hold a ``token``/``counterparty`` pool at.

    One entry per v2-shaped venue plus one per covered fee tier — five with the defaults. The order
    is ``venues`` order then ascending fee, so a caller that searches them in order searches the
    same order every run.

    Guarantees an address for every covered (venue, tier). Guarantees nothing about existence, and
    covers nothing outside :data:`DERIVABLE_VENUES` — see :data:`NOT_DERIVABLE`, which is the list
    a refusal has to carry.
    """
    found = []
    for venue in venues:
        if venue.has_fee_tiers:
            for fee in sorted(venue.fee_tiers):
                found.append(derive_pool(venue, token, counterparty, fee=fee))
        else:
            found.append(derive_pool(venue, token, counterparty))
    return tuple(found)


# -- the constants, confirmed rather than asserted -------------------------------


#: Pools this repository's own output already names, with what they are a pool of. The check that
#: the two init code hashes above are the right 32 bytes: derive these from their tokens and
#: compare. ``0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc`` appears in ``tests/hand_computed``'s
#: ingest fixtures and in the case-run recordings; ``0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640``
#: is ``tools/case_runs.py``'s ``V3_POOL``.
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"

PINNED_POOLS = (
    (UNISWAP_V2, USDC, WETH, None, "0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc"),
    (UNISWAP_V3, USDC, WETH, 500, "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640"),
    # Two for SushiSwap rather than one: a single pair could agree by coincidence of the pair
    # ordering, and two that differ in which token sorts first cannot.
    (SUSHISWAP, WETH, USDT, None, "0x06da0fd433c1a5d7a4faa01111c044910a184553"),
    (SUSHISWAP, USDC, WETH, None, "0x397ff1542f962076d0bfe58ea045ffa2d347aca0"),
)


def _require_the_pinned_pools_derive():
    """Both init code hashes reproduce a known pool, or this module refuses to import.

    A wrong init code hash is the failure this module cannot detect any other way. It does not
    raise, it does not return something malformed, and it does not disagree with itself: it returns
    a different well-formed address for every pair, forever, and a caller that asks the chain
    whether code lives there is told "no" — which is indistinguishable from the truthful answer for
    a token that genuinely has no pool. The entire §4.7 population would then read as
    ``no_pool_on_covered_factories`` and the run would look like a coverage problem rather than a
    constant that is wrong by one byte.

    So it is checked here, at import, against two addresses this repository already committed to in
    fixtures and in ``tools/case_runs.py`` — values a reader can look up on an explorer rather than
    re-derive with the code being checked.
    """
    for venue, token_a, token_b, fee, expected in PINNED_POOLS:
        derived = pool_address(venue, token_a, token_b, fee=fee)
        if derived != expected:
            raise DerivationInconsistent(
                "{} derives {} for {}/{}{}, and this repository's own recordings say that pool is "
                "{}. Either the init code hash {} is not this factory's, or the CREATE2 assembly "
                "is wrong; both produce a well-formed address for every pair and neither would "
                "raise anywhere else.".format(
                    venue.label, derived, token_a, token_b,
                    "" if fee is None else " at {}".format(FEE_TIER_LABELS.get(fee, fee)),
                    expected, venue.init_code_hash,
                )
            )
    return PINNED_POOLS


_require_the_pinned_pools_derive()
