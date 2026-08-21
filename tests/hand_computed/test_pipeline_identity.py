"""A key must identify the entry it points at — worked, with every number computed by hand.

``tests/hand_computed/test_pipeline.py`` pins the half of that rule where **two keys name one
asset**. This file pins the other half, where **one key names the wrong asset**, and the residue
that survives it. The two halves are one rule and neither implies the other: a collision collapses
two entries into one, while a key that disagrees with its value collapses nothing at all — the
mapping has exactly as many entries as the caller wrote, and one of them is filed under the wrong
name.

The pool arithmetic, once, so each case can cite it (identical to the sibling file's, and the fee
is zero so the numbers are exact):

    asset reserve X = 4,000 TOKEN = 4e21 raw     position q = 4,000 TOKEN = 4e21 raw
    exit value      = q * (R / 2X) * 1e-6        = R * 1e-6 / 2

    R = 1e9    -> exit $500     return 500/1000 - 1  = -0.5
    R = 1.5e9  -> exit $750     return 750/1000 - 1  = -0.25
    R = 1,000  -> exit $0.0005  below the $1 minimum — one of the three dead-pool conditions

Every expectation below is one of those four literals. None of them is read back from a run.
"""

from decimal import Decimal

import pytest

from contracts import (
    NATIVE_ETH,
    PoolState,
    Transfer,
    USDC,
    ValueBasis,
    WETH,
)
from attribution import AttributionContext
from marking import DEAD_INACTIVITY_SECONDS
from pipeline import (
    MEASUREMENT_HORIZON_SECONDS,
    ObservedTransaction,
    Stage,
    TokenStart,
    Window,
    WindowConfig,
    run_wallet_window,
)

# -- the world ------------------------------------------------------------------

WALLET = "0x" + "a1" * 20

POOL_R = "0x" + "b1" * 20   # exit $500, live
POOL_M = "0x" + "b2" * 20   # exit $750, live — the migration target
POOL_D = "0x" + "b3" * 20   # exit $0.0005, silent for 30 days
POOL_H = "0x" + "b4" * 20   # exit $750, live

TOKEN_R = "0x" + "c1" * 20
TOKEN_H = "0x" + "c4" * 20

#: TOKEN_R with the last hex digit changed. A valid-looking address: no padding, no collision with
#: any other key, and ``normalise_asset`` has nothing to say about it — which is exactly why the
#: only thing that can catch it is the pool's own ``asset``.
TYPO_R = TOKEN_R[:-1] + "2"

ONE_USDC = 10 ** 6
ONE_TOKEN = 10 ** 18

START_BLOCK = 18_000_000
START_TS = 1_700_000_000
END_BLOCK = START_BLOCK + 7_200
END_TS = START_TS + 86_400
HORIZON_BLOCK = END_BLOCK + 216_000
HORIZON_TS = END_TS + MEASUREMENT_HORIZON_SECONDS

PRICES = {USDC: Decimal("0.000001")}

WINDOW = Window(index=3, start_block=START_BLOCK, start_ts=START_TS,
                end_block=END_BLOCK, end_ts=END_TS)

CONTEXT = AttributionContext(
    infrastructure=frozenset({POOL_R, POOL_M, POOL_D, POOL_H}),
    eoas=frozenset({WALLET}),
)

#: TOKEN_R and TOKEN_H are both old, so every buy here is bucket D and the bucket is never the
#: thing under test — except in the one case that is about the bucket.
OLD = TokenStart(block=START_BLOCK - 100_000, timestamp=START_TS - 1_000_000)
YOUNG = TokenStart(block=START_BLOCK, timestamp=START_TS)
TOKEN_STARTS = {TOKEN_R: OLD, TOKEN_H: OLD}


def pool(address, asset, quote_reserve_raw, last_swap_ts=HORIZON_TS,
         last_swap_block=HORIZON_BLOCK):
    return PoolState(
        address=address, asset=asset, quote=USDC,
        asset_reserve_raw=4_000 * ONE_TOKEN, quote_reserve_raw=quote_reserve_raw,
        last_swap_block=last_swap_block, last_swap_timestamp=last_swap_ts, fee_bps=0,
    )


def dead(asset):
    """The primary pool after the liquidity left: below the minimum exit, quiet for 30 days."""
    return pool(POOL_D, asset, 1_000,
                last_swap_ts=HORIZON_TS - DEAD_INACTIVITY_SECONDS,
                last_swap_block=HORIZON_BLOCK - 216_000)


def buy(tx_hash, token, usdc, tokens, venue=POOL_R, nth=1):
    return ObservedTransaction(
        tx_hash=tx_hash,
        block_number=START_BLOCK + nth,
        timestamp=START_TS + nth * 12,
        success=True,
        tx_sender=WALLET,
        transfers=(
            Transfer(token=USDC, from_addr=WALLET, to_addr=venue, raw_amount=usdc, log_index=0),
            Transfer(token=token, from_addr=venue, to_addr=WALLET, raw_amount=tokens,
                     log_index=1),
        ),
        context=CONTEXT,
    )


def config(token_starts=None, replacement_pools=None):
    return WindowConfig(
        horizon_block=HORIZON_BLOCK,
        horizon_ts=HORIZON_TS,
        token_starts=TOKEN_STARTS if token_starts is None else token_starts,
        replacement_pools={} if replacement_pools is None else replacement_pools,
    )


def run(transactions, pools, prices=None, cfg=None):
    return run_wallet_window(
        transactions, pools, PRICES if prices is None else prices, WINDOW,
        config() if cfg is None else cfg,
    )


def account(result, tx_hash):
    for item in result.accounts:
        if item.buy.tx_hash == tx_hash:
            return item
    raise AssertionError("no account for {}; accounts are {}".format(
        tx_hash, [a.buy.tx_hash for a in result.accounts]))


LOT = [buy("0xr", TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)]


# -- the two numbers the wrong pool sits between --------------------------------


def test_the_two_returns_a_transposed_pool_book_sits_between():
    """The control for everything below, both literals, so the cost is a measured pair.

        POOL_R  R = 1e9    exit $500   500/1000 - 1 = -0.5     the right answer for TOKEN_R
        POOL_H  R = 1.5e9  exit $750   750/1000 - 1 = -0.25    the answer POOL_H would give

    Marking never asks a pool which token it is for, so handing it POOL_H produces a perfectly
    well-formed -0.25. That is the whole difficulty: the wrong number here is not malformed, it is
    another token's correct number.
    """
    right = run(LOT, {TOKEN_R: pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC)})
    assert account(right, "0xr").return_pct == Decimal("-0.5")
    assert account(right, "0xr").marked_usd == Decimal("500")

    other = run([buy("0xh", TOKEN_H, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN, venue=POOL_H)],
                {TOKEN_H: pool(POOL_H, TOKEN_H, 1_500 * ONE_USDC)})
    assert account(other, "0xh").return_pct == Decimal("-0.25")
    assert account(other, "0xh").marked_usd == Decimal("750")


# -- one key, the wrong asset ---------------------------------------------------


def test_a_pool_book_key_that_disagrees_with_the_pool_it_holds_is_refused():
    """``pools[TOKEN_R] = PoolState(asset=TOKEN_H)`` — a transposed join, every key spelled right.

    Nothing collapses: the book has one entry and the lookup for TOKEN_R *succeeds*. It returns
    POOL_H, and the position is marked against another token's pool for $750 — the -0.25 pinned
    above, against the true -0.5. The census, the queue and the coverage report are identical to
    the correct run's, so there is no second field to notice it by; the pool's own ``asset`` is the
    only thing in the input that disagrees with anything.
    """
    with pytest.raises(ValueError) as refusal:
        run(LOT, {TOKEN_R: pool(POOL_H, TOKEN_H, 1_500 * ONE_USDC)})

    message = str(refusal.value)
    assert "pools[{!r}]".format(TOKEN_R) in message
    assert TOKEN_H in message
    assert "two different assets" in message


def test_a_typo_in_a_replacement_pool_key_is_refused_rather_than_published_as_a_dead_zero():
    """The measured-looking zero, and the only reason it was ever reachable.

    The primary is dead and the caller configured the migration, so the honest answer is the
    replacement's:

        POOL_M  R = 1.5e9   exit $750   750/1000 - 1 = -0.25    basis LIQUIDITY_BOUND

    Under a key one hex digit off, the lookup missed and the run published the *dead* answer
    instead — -1, ``DEAD_ZEROED``, the whole $1,000 as §10 dead share, empty queue, census
    ``{VALID_BUY: 1}`` — with the position's evidence asserting ``replacement=none`` about a run
    that had supplied one. Both ends are pinned here: the right number, the number the drop
    published, and the refusal that now stands between them.
    """
    replacement = pool(POOL_M, TOKEN_R, 1_500 * ONE_USDC)

    followed = run(LOT, {TOKEN_R: dead(TOKEN_R)},
                   cfg=config(replacement_pools={TOKEN_R: replacement}))
    assert account(followed, "0xr").return_pct == Decimal("-0.25")
    assert account(followed, "0xr").position.value_basis is ValueBasis.LIQUIDITY_BOUND
    assert account(followed, "0xr").dead_usd == Decimal("0")

    # What the typo published before the key was required to agree with the pool it holds.
    unconfigured = run(LOT, {TOKEN_R: dead(TOKEN_R)})
    assert account(unconfigured, "0xr").return_pct == Decimal("-1")
    assert account(unconfigured, "0xr").position.value_basis is ValueBasis.DEAD_ZEROED
    assert account(unconfigured, "0xr").dead_usd == Decimal("1000")
    assert "replacement=none" in account(unconfigured, "0xr").position.evidence

    with pytest.raises(ValueError) as refusal:
        WindowConfig(horizon_block=HORIZON_BLOCK, horizon_ts=HORIZON_TS,
                     token_starts=TOKEN_STARTS, replacement_pools={TYPO_R: replacement})
    assert "replacement_pools[{!r}]".format(TYPO_R) in str(refusal.value)
    assert TOKEN_R in str(refusal.value)


def test_the_refusal_is_on_the_disagreement_and_not_on_the_key_being_unreadable():
    """A key can be wrong without being unreadable, and the rule is about the mapping, not the run.

    ``TYPO_R`` is a well-formed address that collides with nothing; ``TOKEN_H`` is a real token this
    window never trades. Neither is refusable by looking at the key. Both entries below are refused
    all the same, because the value they hold says which asset it is for and the key does not
    match — and the ordinary case, a book covering a token the run never touched, is still accepted
    and still publishes the answer.
    """
    for key, pool_state in (
        (TYPO_R, pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC)),      # key wrong, value right
        (TOKEN_R, pool(POOL_H, TOKEN_H, 1_500 * ONE_USDC)),     # key right, value wrong
    ):
        with pytest.raises(ValueError):
            run(LOT, {key: pool_state})

    spare = run(LOT, {
        TOKEN_R: pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC),
        TOKEN_H: pool(POOL_H, TOKEN_H, 1_500 * ONE_USDC),       # never traded, agrees with itself
    })
    assert account(spare, "0xr").return_pct == Decimal("-0.5")


def test_the_native_eth_sentinel_and_weth_are_one_asset_on_both_sides_of_the_check():
    """§4.2 governs the comparison, not string equality, or the rule would refuse a correct book.

    A pool keyed by the zero-address sentinel and stating ``asset=WETH`` is the same asset twice,
    and refusing it would be the guard-that-refuses-valid-input shape this rule exists to avoid.
    """
    book = {
        TOKEN_R: pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC),
        NATIVE_ETH: pool(POOL_H, WETH, 1_500 * ONE_USDC),
    }
    assert account(run(LOT, book), "0xr").return_pct == Decimal("-0.5")


# -- the residue, stated in the docstrings and measured here --------------------


def test_a_replacement_key_and_its_pool_mis_spelled_the_same_way_still_publishes_the_zero():
    """The residue :func:`pipeline.inputs.asset_keyed` states, held to its measured consequence.

    The rule asks the mapping to agree with itself, so a caller who makes the *same* mistake in the
    key and in ``PoolState.asset`` satisfies it. The entry is still unreachable, and this is still
    the measured-looking zero: -1, ``DEAD_ZEROED``, $1,000 of §10 dead share, and an empty queue.

    Pinned rather than closed, and pinned so the docstring cannot quietly stop being true. Nothing
    at this boundary can reach it: ``replacement_pools`` is a different argument from the pool book,
    and requiring a replacement key to name a token the run holds would refuse the legal case in
    ``test_the_refusal_is_on_the_disagreement_and_not_on_the_key_being_unreadable``.
    """
    both_wrong = config(replacement_pools={TYPO_R: pool(POOL_M, TYPO_R, 1_500 * ONE_USDC)})
    result = run(LOT, {TOKEN_R: dead(TOKEN_R)}, cfg=both_wrong)

    assert account(result, "0xr").return_pct == Decimal("-1")
    assert account(result, "0xr").position.value_basis is ValueBasis.DEAD_ZEROED
    assert account(result, "0xr").dead_usd == Decimal("1000")
    assert len(result.quarantine.records) == 0


def test_the_same_mis_spelling_in_the_pool_book_is_loud_instead():
    """Why the replacement pools were the half worth closing first, measured against the pool book.

    The identical defect one mapping over produces no number at all: the lookup for TOKEN_R misses,
    marking has nothing to value the open position with, and the buy is quarantined saying so. An
    absent number and a wrong one are not the same failure, and the pool book only ever produced the
    absent one.
    """
    result = run(LOT, {TYPO_R: pool(POOL_R, TYPO_R, 1_000 * ONE_USDC)})

    assert result.stages.buys_scored == 0
    assert len(result.quarantine.records) == 1
    record = result.quarantine.records[0]
    assert record.stage is Stage.MARKING
    assert "no pool state was supplied" in record.reason


def test_a_transposed_token_start_moves_the_bucket_with_nothing_to_check_it_against():
    """The residue :class:`pipeline.inputs.WindowConfig` states: a value that names no asset.

    ``TokenStart`` carries a block and a second and not the token they describe, so a key filed
    against the wrong one is invisible at this boundary — there is nothing for it to disagree with.
    Give TOKEN_R the young start and the §4.7 bucket moves from D to A, which is the first-ten-blocks
    bucket the Edge Origin condition measures, with an empty queue and the same -0.5 return.

    A test that the repository *cannot* currently make go green by fixing something: it pins the
    stated cost so the statement stays honest, and it goes red the day a ``TokenStart`` learns its
    token — which is the day the sentence in the docstring should be deleted.
    """
    from contracts import TokenAgeBucket

    book = {TOKEN_R: pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC)}
    old = run(LOT, book, cfg=config(token_starts={TOKEN_R: OLD}))
    assert account(old, "0xr").bucket is TokenAgeBucket.D

    transposed = run(LOT, book, cfg=config(token_starts={TOKEN_R: YOUNG}))
    assert account(transposed, "0xr").bucket is TokenAgeBucket.A
    assert account(transposed, "0xr").return_pct == Decimal("-0.5")
    assert len(transposed.quarantine.records) == 0


# -- the cost of the collision refusal, chosen rather than overlooked -----------


def test_eth_and_weth_carrying_the_same_price_still_refuses_the_whole_run():
    """The input this repository deliberately stopped accepting, pinned as a decision.

    A vendor price table that quotes ETH and WETH consistently — or any book carrying a
    zero-address placeholder row beside a real WETH row — is two keys naming one asset under §4.2
    even though the two values agree. It ran correctly before the collision refusal existed. It is
    refused now, and admitting it would mean conditioning the guard on the two values disagreeing,
    which closes the traced instance and leaves the class open.

    So this test exists to make the cost visible rather than to celebrate it, and it asserts the
    remedy is in the message: a reader who hits this must be told what to do, or the next person
    deletes the guard.
    """
    with pytest.raises(ValueError) as refusal:
        run(LOT, {TOKEN_R: pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC)},
            prices={USDC: Decimal("0.000001"),
                    WETH: Decimal("0.000000000000003"),
                    NATIVE_ETH: Decimal("0.000000000000003")})

    message = str(refusal.value)
    assert "prices names 1 asset(s) more than once" in message
    assert "Supply exactly one of these spellings" in message


# -- a key that is not an address at all ----------------------------------------


def test_a_non_string_asset_key_is_refused_by_name_and_not_by_the_frozen_seam():
    """``normalise_asset`` lowercases, so a non-string key used to raise ``AttributeError`` from
    inside ``contracts`` — a traceback naming neither the mapping nor the key, in a module that
    cannot be edited to name them. Every other refusal here quotes the caller's own spelling,
    because that is the one they can search for.
    """
    with pytest.raises(TypeError) as refusal:
        WindowConfig(horizon_block=HORIZON_BLOCK, horizon_ts=HORIZON_TS,
                     token_starts={7: OLD})

    message = str(refusal.value)
    assert "token_starts[7]'s key must be a str, and is a int" in message


def test_the_non_string_key_refusal_reaches_the_pool_and_price_books_too():
    """The same rule at the call sites the traced one did not run through.

    ``asset_keyed`` has four callers across two modules, and pinning one of them is how
    ``asset_pairs``' own refusal came to be revertible at three sites with the suite green
    (``e31dc22``). ``pools`` and ``prices`` are reached from ``pipeline.run`` rather than from
    ``WindowConfig``, and each must name its own mapping and its own key.
    """
    with pytest.raises(TypeError) as pools_refusal:
        run(LOT, {7: pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC)})
    assert "pools[7]'s key must be a str, and is a int" in str(pools_refusal.value)

    with pytest.raises(TypeError) as prices_refusal:
        run(LOT, {TOKEN_R: pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC)},
            prices={USDC: Decimal("0.000001"), None: Decimal("1")})
    assert "prices[None]'s key must be a str, and is a NoneType" in str(prices_refusal.value)

    with pytest.raises(TypeError) as replacement_refusal:
        WindowConfig(horizon_block=HORIZON_BLOCK, horizon_ts=HORIZON_TS,
                     token_starts=TOKEN_STARTS,
                     replacement_pools={7: pool(POOL_M, TOKEN_R, 1_500 * ONE_USDC)})
    assert "replacement_pools[7]" in str(replacement_refusal.value)


# -- a value whose type the check has to be able to see -------------------------


class DerivedPool(PoolState):
    """An ordinary subclass. ``isinstance`` admits it everywhere ``PoolState`` is required."""


def test_a_derived_pool_state_still_states_the_asset_it_is_for():
    """``stated_asset`` reads through the MRO, and deleting that walk is invisible to the suite.

    Both pool books type-check with ``isinstance``, so a subclass reaches ``asset_keyed`` exactly
    as the base class does. Looking the reader up by ``type(value)`` instead of walking
    ``__mro__`` leaves every base-class case refused and lets the subclass through — the guard
    disappearing on a type it cannot see, which is the same shape as the collapse it exists to
    refuse. Measured: with the walk replaced by a direct lookup the whole suite stayed green.
    """
    transposed = DerivedPool(
        address=POOL_H, asset=TOKEN_H, quote=USDC,
        asset_reserve_raw=4_000 * ONE_TOKEN, quote_reserve_raw=1_500 * ONE_USDC,
        last_swap_block=HORIZON_BLOCK, last_swap_timestamp=HORIZON_TS, fee_bps=0,
    )

    with pytest.raises(ValueError) as pools_refusal:
        run(LOT, {TOKEN_R: transposed})
    assert "holds a DerivedPool that states it is for" in str(pools_refusal.value)
    assert TOKEN_H in str(pools_refusal.value)

    with pytest.raises(ValueError) as replacement_refusal:
        WindowConfig(horizon_block=HORIZON_BLOCK, horizon_ts=HORIZON_TS,
                     token_starts=TOKEN_STARTS, replacement_pools={TOKEN_R: transposed})
    assert "holds a DerivedPool that states it is for" in str(replacement_refusal.value)

    # And the agreeing case is still accepted, so the check is on the disagreement and not on the
    # class: the same subclass filed under its own asset runs and publishes the honest -0.5 pinned
    # by test_the_two_returns_a_transposed_pool_book_sits_between, not the -0.25 above.
    honest = DerivedPool(
        address=POOL_R, asset=TOKEN_R, quote=USDC,
        asset_reserve_raw=4_000 * ONE_TOKEN, quote_reserve_raw=1_000 * ONE_USDC,
        last_swap_block=HORIZON_BLOCK, last_swap_timestamp=HORIZON_TS, fee_bps=0,
    )
    assert account(run(LOT, {TOKEN_R: honest}), "0xr").return_pct == Decimal("-0.5")
    assert account(run(LOT, {TOKEN_R: honest}), "0xr").marked_usd == Decimal("500")
