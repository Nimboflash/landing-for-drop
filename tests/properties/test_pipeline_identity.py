"""Guards on identity, each pinned by construction rather than by the one input somebody traced.

Two kinds of test live here, and both exist because of the same measured failure: a guard with
exactly one behavioural test behind it is one tidy-up away from silent. A verification pass over
this repository found six such guards, and found that the mutation harness overstated their
coverage — a mutation that moves an anchor makes ``tests/mutations`` fail whether or not any
behaviour is pinned, so "fifteen failures" was fourteen textual complaints and one real test.

* **the four asset-keyed call sites.** ``pipeline.inputs.asset_pairs`` exists so a caller who
  supplies a mapping as a *sequence of pairs* cannot have a repeated key collapsed by ``dict()``
  before the collision check sees it. It is used four times — the pool book, the price book, the
  §4.7 starts and the migration replacements — and only the price book had a test. Weakening any of
  the other three to ``tuple(dict(x).items())`` left the whole suite green while the published
  return became a function of the caller's pair order. Every call site is covered here by
  parametrisation, so a fifth mapping is covered the day it is added to the list.
* **the seam-type and one-row-per-hash guards**, each given a second pin at a different level from
  its existing one.

Nothing here recomputes an implementation expression: the returns are the two hand-computed
literals from ``hand_computed/test_pipeline_identity.py`` (-0.5 for a pool holding 1e9 raw USDC,
-0.25 for one holding 1.5e9), and they are stated so that a collapse is visible as a *number* and
not only as a missing exception.
"""

import dataclasses as dc
from decimal import Decimal

import pytest

from contracts import PoolState, Transfer, USDC, normalise_asset
from attribution import AttributionContext
from pipeline import (
    MEASUREMENT_HORIZON_SECONDS,
    ObservedTransaction,
    TokenStart,
    Window,
    WindowConfig,
    run_wallet_window,
)

WALLET = "0x" + "a1" * 20
POOL_R = "0x" + "b1" * 20
POOL_H = "0x" + "b4" * 20
TOKEN_R = "0x" + "c1" * 20
TOKEN_H = "0x" + "c4" * 20
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
WINDOW = Window(index=1, start_block=START_BLOCK, start_ts=START_TS,
                end_block=END_BLOCK, end_ts=END_TS)
CONTEXT = AttributionContext(
    infrastructure=frozenset({POOL_R, POOL_H}), eoas=frozenset({WALLET}),
)
OLD = TokenStart(block=START_BLOCK - 100_000, timestamp=START_TS - 1_000_000)


def pool(address, asset, quote_reserve_raw):
    return PoolState(
        address=address, asset=asset, quote=USDC,
        asset_reserve_raw=4_000 * ONE_TOKEN, quote_reserve_raw=quote_reserve_raw,
        last_swap_block=HORIZON_BLOCK, last_swap_timestamp=HORIZON_TS, fee_bps=0,
    )


class DerivedPoolState(PoolState):
    """An ordinary subclass. Every ``isinstance(x, PoolState)`` in the pipeline admits it."""


def derived(address, asset, quote_reserve_raw):
    return DerivedPoolState(
        address=address, asset=asset, quote=USDC,
        asset_reserve_raw=4_000 * ONE_TOKEN, quote_reserve_raw=quote_reserve_raw,
        last_swap_block=HORIZON_BLOCK, last_swap_timestamp=HORIZON_TS, fee_bps=0,
    )


SHALLOW = pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC)    # exit $500  -> return -0.5
DEEP = pool(POOL_H, TOKEN_R, 1_500 * ONE_USDC)       # exit $750  -> return -0.25


def legs(token, usdc, tokens, venue=POOL_R):
    return (
        Transfer(token=USDC, from_addr=WALLET, to_addr=venue, raw_amount=usdc, log_index=0),
        Transfer(token=token, from_addr=venue, to_addr=WALLET, raw_amount=tokens, log_index=1),
    )


def buy(tx_hash, nth=1, token=TOKEN_R, transfers=None, block=None, timestamp=None):
    return ObservedTransaction(
        tx_hash=tx_hash,
        block_number=START_BLOCK + nth if block is None else block,
        timestamp=START_TS + nth * 12 if timestamp is None else timestamp,
        success=True,
        tx_sender=WALLET,
        transfers=legs(token, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)
        if transfers is None else transfers,
        context=CONTEXT,
    )


def config(token_starts=None, replacement_pools=None):
    return WindowConfig(
        horizon_block=HORIZON_BLOCK, horizon_ts=HORIZON_TS,
        token_starts={TOKEN_R: OLD} if token_starts is None else token_starts,
        replacement_pools={} if replacement_pools is None else replacement_pools,
    )


def run(transactions=None, pools=None, prices=None, cfg=None):
    return run_wallet_window(
        [buy("0xr")] if transactions is None else transactions,
        {TOKEN_R: SHALLOW} if pools is None else pools,
        PRICES if prices is None else prices,
        WINDOW,
        config() if cfg is None else cfg,
    )


def only_account(result):
    assert len(result.accounts) == 1
    return result.accounts[0]


# -- asset_pairs, at every call site --------------------------------------------
#
# Each entry is (mapping name, the two pairs to supply, the runner). The pairs deliberately carry
# *different* values under one key, so a ``dict()`` collapse is not merely undetected — it publishes
# one of two different answers depending on which pair came last.

REPEATED_PAIRS = {
    "pools": lambda first: run(pools=[(TOKEN_R, SHALLOW), (TOKEN_R, DEEP)][:: 1 if first else -1]),
    "prices": lambda first: run(prices=[(USDC, Decimal("0.000001")), (USDC, Decimal("1"))][
        :: 1 if first else -1]),
    "token_starts": lambda first: run(cfg=config(token_starts=[
        (TOKEN_R, OLD), (TOKEN_R, TokenStart(block=START_BLOCK, timestamp=START_TS)),
    ][:: 1 if first else -1])),
    "replacement_pools": lambda first: run(cfg=config(replacement_pools=[
        (TOKEN_R, SHALLOW), (TOKEN_R, DEEP),
    ][:: 1 if first else -1])),
}


@pytest.mark.parametrize("which", sorted(REPEATED_PAIRS))
@pytest.mark.parametrize("first", (True, False))
def test_a_repeated_key_supplied_as_pairs_is_refused_at_every_call_site(which, first):
    """``dict([(k, a), (k, b)])`` keeps ``b`` and says nothing, and the mapping was built by us.

    A ``Mapping`` cannot repeat a key, so this is the only shape in which the collision check can be
    defeated by the *spelling of the call* rather than by the caller's data — and it is defeated
    silently, because the entry disappears before ``asset_keyed`` is handed anything.

    Both orders are drawn, since the whole defect is that the two orders answer differently.
    """
    with pytest.raises(ValueError) as refusal:
        REPEATED_PAIRS[which](first)
    message = str(refusal.value)
    assert message.startswith(which + " names 1 asset(s) more than once")
    assert (USDC if which == "prices" else TOKEN_R) in message


def test_the_pool_book_pairs_case_would_otherwise_publish_two_different_numbers():
    """Why the refusal above is worth having, as a number rather than as an exception type.

    The two pools in the repeated-key pair are the hand-computed -0.5 and -0.25 books. If ``dict()``
    ever collapses the pair again, the surviving entry is whichever came last and the published
    return is one of these two — with an identical census, an empty queue and an identical coverage
    report. The literals are stated here so the consequence is pinned even in the runs that are
    perfectly legal.
    """
    assert only_account(run(pools={TOKEN_R: SHALLOW})).return_pct == Decimal("-0.5")
    assert only_account(run(pools={TOKEN_R: DEEP})).return_pct == Decimal("-0.25")


# -- a key that disagrees with the value it points at ---------------------------

DISAGREEING = {
    # the key is the wrong half — an ordinary typo, no collision, nothing unspellable
    "typo'd key": (TYPO_R, lambda: pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC)),
    # the value is the wrong half — a transposed join, every key correctly spelled
    "transposed value": (TOKEN_R, lambda: pool(POOL_H, TOKEN_H, 1_500 * ONE_USDC)),
    # the key is a spelling of another token rather than a mis-spelling of this one
    "another token's key": (TOKEN_H, lambda: pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC)),
    # the value's own asset is unreachable, which is a disagreement like any other
    "padded value asset": (TOKEN_R, lambda: pool(POOL_R, "  " + TOKEN_R + "  ",
                                                 1_000 * ONE_USDC)),
    # the value is a *subclass* of PoolState. Both books type-check with ``isinstance``, so this
    # arrives exactly as the base class does — and ``stated_asset`` only sees it because it reads
    # the asset through ``type(value).__mro__``. A direct ``type(value)`` lookup leaves every case
    # above refused and lets this one publish another token's number.
    "derived value type": (TOKEN_R, lambda: derived(POOL_H, TOKEN_H, 1_500 * ONE_USDC)),
}


@pytest.mark.parametrize("case", sorted(DISAGREEING))
@pytest.mark.parametrize("which", ("pools", "replacement_pools"))
def test_a_key_that_disagrees_with_the_pool_it_holds_is_refused_in_both_pool_books(case, which):
    """One rule, both mappings that carry a ``PoolState``, four ways of writing the disagreement.

    The rule is a question about the caller's mapping — does it agree with itself? — and not about
    the world, so it does not care which half is wrong, whether the key is well-formed, or whether
    the run would ever have looked the entry up.
    """
    key, make = DISAGREEING[case]
    if which == "pools":
        with pytest.raises(ValueError) as refusal:
            run(pools={TOKEN_R: SHALLOW, key: make()} if key != TOKEN_R else {key: make()})
    else:
        with pytest.raises(ValueError) as refusal:
            run(cfg=config(replacement_pools={key: make()}))
    assert "two different assets" in str(refusal.value)
    assert which in str(refusal.value)


@pytest.mark.parametrize("style", ("as supplied", "upper", "checksummed"))
def test_a_key_that_merely_spells_the_asset_differently_is_not_a_disagreement(style):
    """The other side of the rule, or it would be a guard that refuses valid input.

    §4.2 decides what "the same asset" means, and the comparison is made after
    ``normalise_asset`` on both sides. A checksummed key over a lowercased ``pool.asset`` is one
    asset named twice in two spellings, and the run must answer normally. The native-ETH sentinel
    against a WETH pool is the same claim through the other half of ``normalise_asset``; it is
    pinned on a worked run in ``hand_computed/test_pipeline_identity.py``.
    """
    key = {"as supplied": TOKEN_R,
           "upper": TOKEN_R.upper(),
           "checksummed": TOKEN_R[:2] + TOKEN_R[2:].upper()}[style]
    book = {key: pool(POOL_R, TOKEN_R, 1_000 * ONE_USDC)}
    assert normalise_asset(key) == TOKEN_R
    assert only_account(run(pools=book)).return_pct == Decimal("-0.5")


# -- second pins: the seam type ------------------------------------------------


@dc.dataclass(frozen=True)
class _Skips(Transfer):
    def __post_init__(self):
        pass                                    # §4.2's ETH->WETH collapse never runs


@dc.dataclass(frozen=True)
class _Correct(Transfer):
    """A subclass that does everything ``Transfer`` does. Refused all the same."""


class _Mixin(object):
    pass


@dc.dataclass(frozen=True)
class _FirstBase(Transfer, _Mixin):
    pass


@dc.dataclass(frozen=True)
class _SecondBase(_Mixin, Transfer):
    pass


class _DuckTyped(object):
    token = TOKEN_R
    from_addr = WALLET
    to_addr = POOL_R
    raw_amount = 1
    log_index = 0
    is_fee = False


def _leg(kind):
    if kind is _DuckTyped:
        return _DuckTyped()
    return kind(token=TOKEN_R, from_addr=WALLET, to_addr=POOL_R, raw_amount=ONE_TOKEN,
                log_index=0)


@pytest.mark.parametrize("kind", (_Skips, _Correct, _FirstBase, _SecondBase, _DuckTyped),
                         ids=lambda k: k.__name__)
def test_only_the_seam_type_itself_may_carry_a_leg(kind):
    """``type(item) is Transfer`` refuses every derivation, in any base order — and a well-behaved
    one too.

    The existing pin uses a subclass whose ``__post_init__`` is a no-op, which leaves the guard
    readable as "refuse a subclass that misbehaves". It is not: ``_Correct`` inherits the seam's
    normalisation unchanged and is refused just the same, because what this check bounds is what
    *type* of thing may enter and not what that thing happens to do today. A subclass that behaves
    now is a subclass someone edits later, and ``contracts`` is frozen, so there is no
    ``__init_subclass__`` to seal it there.
    """
    with pytest.raises(TypeError) as refusal:
        buy("0xr", transfers=(_leg(kind),))
    message = str(refusal.value)
    assert "transfers[0] is a {}".format(kind.__name__) in message
    assert "not a contracts.Transfer" in message


def test_the_seam_type_refusal_names_the_leg_that_is_wrong():
    """A second level: the position, not just the fact. A transaction carrying eight legs with one
    derived leg in the middle has to say *which*, or the message sends the reader to the wrong row.
    """
    good = legs(TOKEN_R, 1_000 * ONE_USDC, 4_000 * ONE_TOKEN)
    with pytest.raises(TypeError) as refusal:
        buy("0xr", transfers=(good[0], good[1], _leg(_Skips)))
    assert "transfers[2]" in str(refusal.value)


# -- second pins: one tx_hash, one transaction ----------------------------------


DUPLICATES = {
    "two identical rows": lambda: [buy("0xdup"), buy("0xdup")],
    "one object listed twice": lambda: [buy("0xdup")] * 2,
    "rows that disagree": lambda: [buy("0xdup", nth=1), buy("0xdup", nth=2)],
    "a pair inside a triple": lambda: [buy("0xdup"), buy("0xother", nth=2), buy("0xdup", nth=3)],
    "spellings the entry type normalises": lambda: [buy("0xDUP  "), buy("0xdup")],
}


@pytest.mark.parametrize("case", sorted(DUPLICATES))
def test_two_rows_under_one_hash_are_refused_whatever_they_carry(case):
    """The refusal is on the collision, not on the two rows disagreeing — and not on a *third* row.

    Its existing behavioural pin is the same object listed twice, which is the shape a reviewer
    traces and the shape a bound on the traced instance still catches. Two of the cases here are
    the ones that a papered-over repair would let through: rows that agree in every field while
    being two objects, and a duplicated pair sitting inside a longer list.
    """
    with pytest.raises(ValueError) as refusal:
        run(DUPLICATES[case]())
    assert "0xdup" in str(refusal.value)
    assert "appears 2 times" in str(refusal.value)


def test_a_malformed_row_is_refused_before_the_duplicate_hash_is():
    """The ordering the comment claims, pinned behaviourally rather than by the mutation anchor.

    ``_require_one_transaction_per_hash`` runs after the per-item checks because a cross-item
    invariant over rows that are not yet well-formed is a statement about the wrong thing. Nothing
    tested that: a run whose input is *both* duplicated and outside the measurement period has two
    true complaints, and which one the caller is told about is the whole content of the rule.
    """
    outside = buy("0xdup", block=START_BLOCK - 1, timestamp=START_TS - 12)
    with pytest.raises(ValueError) as refusal:
        run([outside, buy("0xdup")])
    message = str(refusal.value)
    assert "appears 2 times" not in message
    assert "window" in message

    with pytest.raises(TypeError) as wrong_type:
        run([buy("0xdup"), "0xdup"])
    assert "run_wallet_window consumes ObservedTransaction values" in str(wrong_type.value)
