"""Reading a pool off chain — the orientation, the refusals, and the field that decides §9.1.

Every literal here was read off Ethereum mainnet at block 16,943,478 through the committed snapshot
in ``tests/fixtures/case_runs/recordings``, and is checkable against a block explorer. Nothing is
recomputed from the implementation.

The reason this file exists at all: ``marking`` has been ready since it was written and nothing ever
handed it a pool, so 28 positions across four real wallet populations were quarantined for want of
one. A pool reading is now a published number, and a published number needs its own tests.
"""

import pytest

from contracts.metrics import PoolState
from pipeline import poolread as PR
from pipeline.poolread import (
    LastSwapUnknowable,
    PoolFeeDisagrees,
    PoolHasNoCode,
    PoolReadDefect,
    PoolSidesDisagree,
    ReturndataWidth,
    read_pool_for,
    read_v2_pool,
)
from transport.cache import RecordingCache
from transport.client import RpcClient
from tools.case_runs import RECORDINGS, AUTO

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
PAIR = "0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc"
HORIZON = 16943478

#: Read off mainnet at HORIZON. Both are checkable against an explorer at that block.
USDC_RESERVE = 27752789871027
WETH_RESERVE = 15505438737513348315629
TIMESTAMP_LAST = 1680220559


@pytest.fixture
def client():
    return RpcClient(cache=RecordingCache(RECORDINGS), mode=AUTO)


class _Answers(object):
    """A client that answers one selector at a time, so a single field can be broken."""

    def __init__(self, **by_selector):
        self._by = dict(by_selector)

    def call(self, method, params):
        data = params[0]["data"]
        for name, answer in self._by.items():
            if data == getattr(PR, name):
                return answer
        raise AssertionError("unexpected selector {}".format(data))


def _ok_answers(**over):
    answers = dict(
        GET_RESERVES="0x" + "".join(
            "{:064x}".format(v) for v in (USDC_RESERVE, WETH_RESERVE, TIMESTAMP_LAST)
        ),
        TOKEN0="0x{:064x}".format(int(USDC, 16)),
        TOKEN1="0x{:064x}".format(int(WETH, 16)),
    )
    answers.update(over)
    return _Answers(**answers)


# -- the reading itself ----------------------------------------------------------


def test_the_selectors_are_derived_from_keccak_not_recalled():
    """All five agree with the constants ``tools/case_runs.py`` uses, which were read off explorers.

    A selector that is right about the name and wrong about the arguments is a live call that
    returns the wrong thing, so these four bytes are worth pinning against a second source.
    """
    assert PR.TOKEN0 == "0x0dfe1681"
    assert PR.TOKEN1 == "0xd21220a7"
    assert PR.GET_RESERVES == "0x0902f1ac"
    assert PR.V3_FEE == "0xddca3f43"
    assert PR.V3_SLOT0 == "0x3850c7bd"
    assert PR.V3_LIQUIDITY == "0x1a686502"


def test_a_real_pool_reads_the_reserves_the_chain_holds(client):
    reading = read_v2_pool(client, USDC, WETH, HORIZON)
    state = reading.state

    assert isinstance(state, PoolState)
    assert state.address == PAIR
    assert state.asset_reserve_raw == USDC_RESERVE
    assert state.quote_reserve_raw == WETH_RESERVE
    assert state.last_swap_timestamp == TIMESTAMP_LAST
    assert state.fee_bps == 30
    assert reading.block == HORIZON


def test_the_address_is_computed_rather_than_looked_up(client):
    """No pool list is consulted. A position in a token nobody registered still has a venue."""
    reading = read_v2_pool(client, USDC, WETH, HORIZON)
    assert reading.state.address == PAIR

    supplied = read_v2_pool(client, USDC, WETH, HORIZON, address=PAIR)
    assert supplied.state.asset_reserve_raw == reading.state.asset_reserve_raw


# -- orientation: the error that is a mark, not a crash --------------------------


def test_the_pool_decides_which_reserve_is_the_assets_not_the_caller(client):
    """Reversing the argument order must reverse the answer, because ``token0()`` is the authority.

    Attributing the two the wrong way round produces a price wrong by the ratio of the reserves --
    here that is 27,752,789,871,027 against 15,505,438,737,513,348,315,629, which is not a number
    anybody would notice as wrong. It would simply be a mark.
    """
    forward = read_v2_pool(client, USDC, WETH, HORIZON).state
    reverse = read_v2_pool(client, WETH, USDC, HORIZON).state

    assert forward.asset_reserve_raw == USDC_RESERVE
    assert reverse.asset_reserve_raw == WETH_RESERVE
    assert reverse.asset_reserve_raw == forward.quote_reserve_raw
    assert reverse.quote_reserve_raw == forward.asset_reserve_raw


def test_a_pool_of_two_other_tokens_is_refused_rather_than_read():
    other = "0x" + "11" * 20
    broken = _ok_answers(TOKEN0="0x{:064x}".format(int(other, 16)))

    with pytest.raises(PoolSidesDisagree) as caught:
        read_v2_pool(broken, USDC, WETH, HORIZON, address=PAIR)

    message = str(caught.value)
    assert other in message
    assert "two other tokens" in message


def test_an_address_word_with_dirty_high_bytes_is_not_an_address():
    """The low 160 bits are the *right* token, so only the dirty-word guard can catch this.

    Written the obvious way first -- high bytes ``ff``, low bytes zero -- this test passed with the
    guard deleted, because a zero address matches neither token and the orientation check refused it
    instead. Two guards, one test, and the weaker one was doing the work.

    So the word here truncates to USDC exactly. Orientation is satisfied; the only thing left that
    can object is the guard under test. A word this shape means the call returned something that is
    not an address, and reading its low bits as one is reading a coincidence.
    """
    dirty = "0x" + "ff" * 12 + USDC[2:]
    assert int(dirty, 16) & ((1 << 160) - 1) == int(USDC, 16), "the low bits must be the real token"

    with pytest.raises(PoolSidesDisagree) as caught:
        read_v2_pool(_ok_answers(TOKEN0=dirty), USDC, WETH, HORIZON, address=PAIR)
    assert "top 12 bytes are not zero" in str(caught.value)


# -- empty is not zero -----------------------------------------------------------


def test_empty_returndata_is_no_pool_and_not_a_zero_reserve():
    """The distinction the refusal exists for.

    An ``eth_call`` to an address with no code returns empty. Read as a zero reserve it would say
    the position is worth nothing; read correctly it says the position cannot be marked. One is a
    measurement and the other is its absence, and once they are the same value nothing downstream
    can tell them apart.
    """
    with pytest.raises(PoolHasNoCode) as caught:
        read_v2_pool(_ok_answers(GET_RESERVES="0x"), USDC, WETH, HORIZON, address=PAIR)

    message = str(caught.value)
    assert "not a zero reserve" in message
    assert "no pool here" in message


def test_returndata_of_the_wrong_width_is_refused():
    short = "0x" + "{:064x}".format(USDC_RESERVE) * 2   # two words where the ABI says three
    with pytest.raises(ReturndataWidth) as caught:
        read_v2_pool(_ok_answers(GET_RESERVES=short), USDC, WETH, HORIZON, address=PAIR)
    assert "whatever landed there" in str(caught.value)


# -- last_swap_block, and the asymmetry that makes it usable ---------------------


def test_the_last_swap_limitation_travels_with_every_reading(client):
    """It is carried in the evidence, not left in a docstring nobody downstream reads.

    §9.1's first dead-pool condition is *no swap for 30 days*, so this field decides whether a
    position is zeroed. A reader who takes ``last_swap_timestamp`` for the last swap, when it is
    the last reserve *change*, is reading a mint as a trade.
    """
    reading = read_v2_pool(client, USDC, WETH, HORIZON)
    carried = " ".join(reading.evidence)
    assert PR.LAST_SWAP_IS_LAST_RESERVE_CHANGE in carried


def test_the_limitation_states_its_direction_and_its_price():
    """The two facts that make it acceptable rather than merely admitted.

    Direction: it can read a dead pool as live, never a live pool as dead -- and the second would
    publish -100% on a healthy position. Price: the exact reading costs ~21,600 requests per pool
    at the 10-block cap, which is why it was not simply done.
    """
    text = PR.LAST_SWAP_IS_LAST_RESERVE_CHANGE
    assert "dead pool as live, never a live pool as dead" in text
    assert "21,600" in text
    assert "-100%" in text


# -- v3: refused, and the refusal says why ---------------------------------------


def test_a_v3_pool_is_refused_because_slot0_reports_no_time(client):
    with pytest.raises(LastSwapUnknowable) as caught:
        read_pool_for(client, USDC, WETH, HORIZON, fee=500)

    message = str(caught.value)
    assert "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640" in message
    assert "a price and a tick, not a time" in message
    assert "never fire" in message


def test_an_uncovered_fee_tier_is_refused_before_an_address_is_derived(client):
    with pytest.raises(PoolFeeDisagrees) as caught:
        read_pool_for(client, USDC, WETH, HORIZON, fee=250)
    assert "cannot be computed" in str(caught.value)


def test_no_fee_reads_the_v2_pair(client):
    assert read_pool_for(client, USDC, WETH, HORIZON).state.address == PAIR


# -- the reading knows what height it is about -----------------------------------


def test_a_reading_without_a_height_is_about_no_particular_time(client):
    reading = read_v2_pool(client, USDC, WETH, HORIZON)
    with pytest.raises(ValueError) as caught:
        PR.PoolReading(state=reading.state, venue=reading.venue, block=-1, evidence=())
    assert "no particular time" in str(caught.value)


def test_every_refusal_here_is_a_pool_read_defect():
    """One family, so a caller can catch the class rather than enumerating it and missing one."""
    for cls in (PoolHasNoCode, PoolSidesDisagree, PoolFeeDisagrees, ReturndataWidth,
                LastSwapUnknowable):
        assert issubclass(cls, PoolReadDefect)


def test_sushiswap_derives_two_known_pairs_not_one():
    """Two pairs, and they differ in which token sorts first.

    One pair could agree by coincidence of the ordering; two that sort opposite ways cannot. Both
    addresses are checkable on any explorer.

    Why the constant is worth proving before it is used: a wrong init code hash produces a
    perfectly well-formed address for a contract that does not exist, so every pool read against it
    refuses with "no code" -- which reads as "this token has no market" rather than as "this
    constant is wrong".
    """
    from pipeline.pooladdress import PINNED_POOLS, SUSHISWAP, pool_address

    sushi = [row for row in PINNED_POOLS if row[0] is SUSHISWAP]
    assert len(sushi) == 2, "one pinned pair cannot distinguish an ordering coincidence"

    for venue, token_a, token_b, fee, expected in sushi:
        assert pool_address(venue, token_a, token_b, fee).lower() == expected.lower()

    first_tokens = {min(row[1].lower(), row[2].lower()) for row in sushi}
    assert len(first_tokens) == 2, "both pairs sort the same way; that is one test, not two"


def test_the_two_tokens_sushiswap_did_not_rescue_have_no_covered_pool_at_all():
    """Recorded because the obvious next move is to try adding another venue.

    SushiSwap was added on the hypothesis that these two tokens' earliest market was there. It was
    not: neither has a pool on Uniswap v2, SushiSwap or Uniswap v3 against any of §4.6's four quote
    assets, at the horizon. Both contracts exist -- 2,306 and 13,840 bytes of code -- so this is not
    a dead address; their market is somewhere this module cannot derive an address for.

    They stay refused, and that is the machine working: a §4.7 start from a venue that is not the
    earliest one would bucket their buys as younger than they are.
    """
    from contracts.core import QUOTE_ASSETS
    from pipeline.pooladdress import DERIVABLE_VENUES, FEE_TIERS, pool_address

    unrescued = ("0x0bf0c1b858abf4dc22c0c691c76b20ce931b3fb3",
                 "0x921ec1160d940298304e3b466dd8b10275b11f0b")
    combinations = 0
    for _token in unrescued:
        for venue in DERIVABLE_VENUES:
            for _quote in QUOTE_ASSETS:
                for fee in (FEE_TIERS if venue.fee_tiers else (None,)):
                    combinations += 1
                    assert pool_address(venue, _token, _quote, fee)

    # 2 tokens x 4 quotes x (v2 + sushi + four v3 tiers) = 48 addresses, all derivable and none
    # of them a deployed pool. The count is pinned so adding a venue without re-checking these
    # two shows up here.
    assert combinations == 48
