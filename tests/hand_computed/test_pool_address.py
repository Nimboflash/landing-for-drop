"""CREATE2 pool addresses, pinned against five pools this repository already named.

``pipeline.pooladdress`` replaces a search nobody can run. Reading ``PairCreated`` off the Uniswap
v2 factory means sweeping from block 10,000,835 to the 16,943,478 horizon, and every free endpoint
now caps ``eth_getLogs`` at 10 or 50 blocks — roughly 700,000 requests. Both factories deploy with
``CREATE2``, so the address is not a fact to be discovered at all; it is a hash of the deployer, the
sorted pair, and the pool's init code.

The whole of that derivation rests on two 32-byte constants nobody can eyeball, so the constants are
checked the only way they can be: derive pools whose addresses are already committed in this
repository, from bytes Ethereum mainnet returned, and compare.

The five anchors, and why these five
------------------------------------

    v2   USDC/WETH   0xb4e16d01…   in the ingest fixtures and the case-run recordings
    v2   USDT/WETH   0x0d4a11d5…   tools/case_runs.py's DEPTH_PAIR, the depth case's first hop
    v2   SBET/WETH   0x8c56b433…   tools/case_survey.py's SBET_PAIR
    v2   DEAD/WETH   0xd6f6558f…   tools/case_survey.py's DEAD_PAIR, the rug
    v3   USDC/WETH   0x88e6a0c2…   tools/case_runs.py's V3_POOL, at the 0.05% tier

The last two are the point. USDC/WETH is the pair every implementation is tested on and its address
is memorable; SBET and the rug token are exactly the kind of token §4.7 exists for — created inside
the measured window, known to nobody, and the reason 82 buys are quarantined. A derivation that
reproduces the famous pair and not those two would be a derivation that works on tokens whose
addresses somebody could have remembered.

What this file does not establish
---------------------------------

That a derived address holds a pool. It never can: CREATE2 fixes the address before deployment, so
every pair has one and almost none have a pool. Existence is ``eth_getCode``, and it belongs to
``pipeline.tokenstart``.
"""

import pytest

from contracts import NATIVE_ETH, USDC, USDT, WETH
from pipeline import tokenstart
from pipeline.pooladdress import (
    DERIVABLE_VENUES,
    FEE_TIERS,
    FEE_TIER_LABELS,
    NOT_DERIVABLE,
    PINNED_POOLS,
    UNISWAP_V2,
    UNISWAP_V3,
    Create2Venue,
    DerivationInconsistent,
    MalformedAddress,
    NotAPair,
    PoolAddressDefect,
    UncoveredFeeTier,
    _require_the_pinned_pools_derive,
    derive_pool,
    derived_pools,
    pool_address,
    sorted_pair,
)

#: ``tools/case_survey.py``'s SBET and the rug token, with the pairs that file records for them.
#: Copied rather than imported: this test is about the arithmetic reproducing a committed address,
#: and importing the survey would drag its recordings and its RPC client in to prove nothing extra.
SBET = "0x14c256e65300026b76247e45554bb645c2c294ff"
SBET_PAIR = "0x8c56b433869ff0b89f9c400db4971d4899f7c465"
DEAD_TOKEN = "0x41d1841fcedabd85eeb91b10fb069e225df67af8"
DEAD_PAIR = "0xd6f6558f1ecba5951b9e09f7ae2aaa507759838b"

#: ``tools/case_runs.py``'s DEPTH_PAIR and V3_POOL.
USDT_WETH_PAIR = "0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852"
USDC_WETH_PAIR = "0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc"
USDC_WETH_V3_5BP = "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640"

V2_ANCHORS = (
    (USDC, WETH, USDC_WETH_PAIR),
    (USDT, WETH, USDT_WETH_PAIR),
    (SBET, WETH, SBET_PAIR),
    (DEAD_TOKEN, WETH, DEAD_PAIR),
)


# -- the anchors -----------------------------------------------------------------


@pytest.mark.parametrize("token,counterparty,expected", V2_ANCHORS)
def test_a_v2_pair_this_repository_already_named_is_derived(token, counterparty, expected):
    assert pool_address(UNISWAP_V2, token, counterparty) == expected


def test_the_v3_pool_this_repository_already_named_is_derived():
    assert pool_address(UNISWAP_V3, USDC, WETH, fee=500) == USDC_WETH_V3_5BP


def test_the_count_of_pools_reproduced():
    """The verification as a number: four v2 pairs and one v3 pool, all from committed addresses."""
    reproduced = [
        pool_address(UNISWAP_V2, token, counterparty) == expected
        for token, counterparty, expected in V2_ANCHORS
    ] + [pool_address(UNISWAP_V3, USDC, WETH, fee=500) == USDC_WETH_V3_5BP]

    assert reproduced == [True] * 5
    assert len({address for _t, _c, address in V2_ANCHORS} | {USDC_WETH_V3_5BP}) == 5


def test_the_pair_order_does_not_change_the_address():
    """Both factories sort before hashing, which is what makes pair(A,B) and pair(B,A) one pool.

    Deriving with the caller's order instead would invent a second address for every pair handed
    over the wrong way round — well-formed, and holding nothing.
    """
    for token, counterparty, expected in V2_ANCHORS:
        assert pool_address(UNISWAP_V2, counterparty, token) == expected
    assert pool_address(UNISWAP_V3, WETH, USDC, fee=500) == USDC_WETH_V3_5BP


def test_sorted_pair_orders_by_address_and_not_by_argument():
    assert sorted_pair(WETH, USDC) == (USDC, WETH)
    assert sorted_pair(USDC, WETH) == (USDC, WETH)
    assert USDC < WETH


def test_native_eth_derives_the_weth_pool():
    """``normalise_asset`` collapses native ETH onto WETH before §4.2's netting, and a derivation
    that did not would produce a pool address for the zero address — which is not a token."""
    assert pool_address(UNISWAP_V2, USDC, NATIVE_ETH) == USDC_WETH_PAIR


# -- the fee tiers ---------------------------------------------------------------


def test_the_covered_tiers_are_the_four_mainnet_uniswap_v3_has_enabled():
    assert FEE_TIERS == (100, 500, 3000, 10000)
    assert UNISWAP_V3.fee_tiers == FEE_TIERS
    assert sorted(FEE_TIER_LABELS) == sorted(FEE_TIERS)
    assert [FEE_TIER_LABELS[tier] for tier in FEE_TIERS] == ["0.01%", "0.05%", "0.30%", "1.00%"]


def test_each_tier_is_a_different_pool():
    """The fee is inside the v3 salt, so the four tiers of one pair are four addresses. A
    derivation that dropped the fee would return one address for all four and call whichever pool
    happens to be at it 'the' pool for the pair."""
    addresses = {fee: pool_address(UNISWAP_V3, USDC, WETH, fee=fee) for fee in FEE_TIERS}

    assert len(set(addresses.values())) == len(FEE_TIERS)
    assert addresses[500] == USDC_WETH_V3_5BP


@pytest.mark.parametrize("fee", [1, 200, 2500, 20000, 1_000_000])
def test_an_uncovered_tier_is_refused_rather_than_defaulted(fee):
    """A tier this module does not pin is a pool it cannot see, and that must reach the caller as a
    refusal. Answering with the nearest covered tier would hand back a real pool that is not the
    one asked about — a plausible address, and the wrong market."""
    with pytest.raises(UncoveredFeeTier) as raised:
        pool_address(UNISWAP_V3, USDC, WETH, fee=fee)

    assert "0.05%" in str(raised.value), "the refusal names what is covered"


def test_the_uncovered_tiers_reach_the_refusal_text():
    """``NOT_DERIVABLE`` is what ``pipeline.tokenstart`` writes into a no-pool refusal, and the fee
    tiers have to be in it: a token whose only market is a 0.02% pool is unknown, not old."""
    joined = " ".join(NOT_DERIVABLE)

    assert "fee tier" in joined
    for label in FEE_TIER_LABELS.values():
        assert label in joined
    assert tokenstart.DERIVED_NOT_COVERED[1:] == NOT_DERIVABLE


def test_a_venue_with_no_tiers_refuses_a_fee_and_one_with_tiers_refuses_none():
    with pytest.raises(UncoveredFeeTier):
        pool_address(UNISWAP_V2, USDC, WETH, fee=3000)
    with pytest.raises(UncoveredFeeTier):
        pool_address(UNISWAP_V3, USDC, WETH)


def test_a_bool_is_not_a_fee_tier():
    """``True == 1`` in Python, and 1 is not a covered tier either — but a bool reaching here is a
    caller that has lost track of what it is passing, and that is worth saying separately."""
    with pytest.raises(UncoveredFeeTier):
        pool_address(UNISWAP_V3, USDC, WETH, fee=True)


# -- enumerating candidates ------------------------------------------------------


def test_every_covered_venue_and_tier_gets_one_candidate():
    candidates = derived_pools(SBET, WETH)

    # Derived from the venue table rather than restated. Written as ``1 + len(FEE_TIERS)`` when
    # there were two venues, it broke the day SushiSwap was added -- correctly, but by pinning the
    # shape of the table rather than the rule, so the failure said "6 != 5" and not "a venue was
    # added and nobody re-checked what depends on the count".
    assert len(candidates) == sum(len(v.fee_tiers) if v.fee_tiers else 1 for v in DERIVABLE_VENUES)
    # One None per single-pool venue, then the tiers of each tiered venue -- read off the table
    # rather than written out, so adding a venue changes the expectation with the code.
    expected_fees = []
    for venue in DERIVABLE_VENUES:
        expected_fees.extend(venue.fee_tiers if venue.fee_tiers else (None,))
    assert [candidate.fee for candidate in candidates] == expected_fees
    assert candidates[0].address == SBET_PAIR
    assert len({candidate.address for candidate in candidates}) == len(candidates)


def test_the_candidate_order_is_the_same_every_run():
    """The order is the order the calls are recorded in, and a snapshot that reorders itself is a
    snapshot that cannot be diffed."""
    assert derived_pools(SBET, WETH) == derived_pools(SBET, WETH)


def test_a_candidate_says_which_venue_and_tier_it_came_from():
    pool = derive_pool(UNISWAP_V3, USDC, WETH, fee=500)

    assert pool.address == USDC_WETH_V3_5BP
    assert pool.label == "Uniswap v3 0.05%"
    assert (pool.token0, pool.token1) == (USDC, WETH)
    assert pool.factory == UNISWAP_V3.factory


def test_narrowing_the_venues_narrows_the_candidates():
    assert len(derived_pools(SBET, WETH, venues=(UNISWAP_V2,))) == 1
    assert len(derived_pools(SBET, WETH, venues=(UNISWAP_V3,))) == len(FEE_TIERS)


# -- what is refused -------------------------------------------------------------


@pytest.mark.parametrize("token", [
    "0xdead",                                          # too short
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2ff",    # too long
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756ccz",      # not hex
    "c02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",        # no 0x
    "",
    None,
])
def test_an_address_that_is_not_twenty_bytes_is_refused(token):
    """Hashing a malformed address returns a perfectly well-formed pool address for a token that
    does not exist, and nothing downstream could tell it from a real one."""
    with pytest.raises(MalformedAddress):
        pool_address(UNISWAP_V2, token, WETH)


def test_a_token_against_itself_is_not_a_pair():
    with pytest.raises(NotAPair):
        pool_address(UNISWAP_V2, WETH, WETH)


def test_native_eth_against_weth_is_the_same_token():
    """The collapse happens before the comparison, so this is one token twice rather than a pair."""
    with pytest.raises(NotAPair):
        pool_address(UNISWAP_V2, NATIVE_ETH, WETH)


def test_a_venue_that_is_not_a_venue_is_refused():
    with pytest.raises(PoolAddressDefect):
        pool_address(UNISWAP_V2.factory, USDC, WETH)


# -- the constants, and the guard on them ----------------------------------------


def test_the_import_time_check_covers_both_init_code_hashes():
    # One pinned pool per derivable venue, and two for SushiSwap: a single pair could agree by
    # coincidence of the token ordering, and two that sort opposite ways cannot.
    assert len(PINNED_POOLS) == len(DERIVABLE_VENUES) + 1
    # Every derivable venue has at least one pinned pool. Stated as a subset relation rather than
    # a literal set, because the failure that matters is "a venue was added and nothing pins its
    # init code hash", and a literal set fails for that reason and also for the harmless one.
    pinned = {venue.label for venue, _a, _b, _fee, _expected in PINNED_POOLS}
    assert pinned == {venue.label for venue in DERIVABLE_VENUES}
    assert _require_the_pinned_pools_derive() == PINNED_POOLS


def test_a_wrong_init_code_hash_is_caught_by_the_import_time_check(monkeypatch):
    """Guard the guard, on the exact failure the check exists for.

    A wrong init code hash never raises on its own: it returns a different well-formed address for
    every pair, forever, and the chain truthfully answers that no code lives there. The whole §4.7
    population would read as ``no_pool_on_covered_factories`` and look like a coverage problem.
    """
    wrong = Create2Venue(
        label="Uniswap v2",
        factory=UNISWAP_V2.factory,
        init_code_hash="0x" + "11" * 32,
    )
    monkeypatch.setattr(
        "pipeline.pooladdress.PINNED_POOLS",
        ((wrong, USDC, WETH, None, USDC_WETH_PAIR),),
    )

    with pytest.raises(DerivationInconsistent) as raised:
        _require_the_pinned_pools_derive()

    assert USDC_WETH_PAIR in str(raised.value)
    assert "init code hash" in str(raised.value)


def test_an_init_code_hash_that_is_not_32_bytes_is_refused_when_the_venue_is_built():
    with pytest.raises(DerivationInconsistent):
        Create2Venue(label="broken", factory=UNISWAP_V2.factory, init_code_hash="0xabcd")


def test_the_factory_addresses_are_the_ones_the_pool_search_uses():
    """One address, not two spellings of one address. The CREATE2 preimage contains the deployer,
    so a derivation against one factory and a log sweep against another are two different searches
    that would be reported as one."""
    by_address = {v.factory: v for v in DERIVABLE_VENUES}
    for factory in tokenstart.COVERED_FACTORIES:
        assert factory.address in by_address, (
            "{} is searched for pools and has no derivable venue: the sweep would find a pool the "
            "derivation cannot address, and the two searches would be reported as one".format(
                factory.label)
        )
        assert factory.label == by_address[factory.address].label

    # And the reverse, which is the direction that loses a market: a venue whose address can be
    # derived but whose factory is never swept has its pools found only when a position happens to
    # name one, so a token whose EARLIEST pool is there gets a §4.7 start that is too late.
    swept = {f.address for f in tokenstart.COVERED_FACTORIES}
    assert {v.factory for v in DERIVABLE_VENUES} == swept
