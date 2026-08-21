"""§4.7's trading start: what the derivation finds, what it refuses, and what it costs.

``pipeline.tokenstart`` had one way of finding a token's pools and it cannot run. Sweeping
``PairCreated`` from block 10,000,835 to the 16,943,478 horizon is roughly 700,000 requests against
endpoints that answer "You can make eth_getLogs requests with up to a 10 block range". The
replacement computes the pool's address instead of searching for it — ``pipeline.pooladdress``,
verified in ``tests/hand_computed/test_pool_address.py`` — and then asks ``eth_getCode`` two
questions: is anything there at the horizon, and from which block.

This file pins the three things that change with that:

* the derivation issues **no log range at all** for discovery, which is the whole reason it can
  run. A test that only checked the answer would pass just as happily on the sweep;
* what the derivation cannot see reaches the **refusal**. Deriving means naming both sides of the
  pair, so a pool against some third token, or at a fee tier ``pooladdress`` does not pin, is
  invisible — and an invisible pool has to read as "unknown age", never as a date;
* the direction of every error stays the same. A start that cannot be established is a quarantine,
  and a start this module does derive can only be **later** than or equal to the truth, so a token
  filed in bucket A or B by it was young on Uniswap.

The chain here is canned rather than recorded, and deliberately: the shapes being tested are a
binary search over ``eth_getCode`` and a pool that never traded, and recording those against a real
endpoint would put six-million-block sweeps into the snapshot to assert something arithmetic. What
is *not* canned is the thing that would be worth faking — the pool addresses are derived from the
real constants, and two of them (``0x8c56b433…``, ``0xd6f6558f…``) are the pairs
``tools/case_survey.py`` read off mainnet.
"""

import ast
import inspect
import os
from dataclasses import replace

import pytest

from contracts import USDC, WETH, normalise_asset
from pipeline import tokenstart
from pipeline.pooladdress import (
    DERIVABLE_VENUES,
    FEE_TIERS,
    NOT_DERIVABLE,
    UNISWAP_V2,
    pool_address,
)
from pipeline.tokenstart import (
    CHUNK_BLOCKS,
    COVERED_FACTORIES,
    CREATE2_DERIVATION,
    DERIVED_COUNTERPARTIES,
    FACTORY_LOG_SWEEP,
    MINT_V2,
    SCAN_BLOCKS,
    SCAN_SLICES,
    UNISWAP_V2_FACTORY,
    UNISWAP_V3_FACTORY,
    V2_GET_RESERVES,
    V3_SLOT0,
    ActivityProbe,
    Factory,
    FactoryNotAtStatedBlock,
    PoolDiscovery,
    PoolStateUnreadable,
    PoolTrade,
    TokenStartDefect,
    UnrecognisedFactory,
    code_length,
    creation_block,
    derive_token_starts,
    first_active_block,
    pool_trading_start,
    pools_by_derivation,
    probe_reading,
    refusals_of,
    token_starts_of,
)
from ingest import SWAP_V2

#: ``tools/case_survey.py``'s SBET and its pair, and the rug token and its pair — read off mainnet
#: there, derived here. The two tokens §4.7's quarantine is actually about.
SBET = "0x14c256e65300026b76247e45554bb645c2c294ff"
SBET_PAIR = "0x8c56b433869ff0b89f9c400db4971d4899f7c465"
DEAD_TOKEN = "0x41d1841fcedabd85eeb91b10fb069e225df67af8"
DEAD_PAIR = "0xd6f6558f1ecba5951b9e09f7ae2aaa507759838b"

#: The horizon ``tools/case_runs.py`` marks at, so the ranges in this file are the real ones.
HORIZON = 16_943_478

#: SBET's pair was created at 16530898 and first traded at 16530948, 50 blocks later, with the
#: first Mint at 16530944. Those are ``tools/case_survey.py``'s measured numbers.
SBET_PAIR_CREATED = 16_530_898
SBET_FIRST_MINT = 16_530_944
SBET_FIRST_SWAP = 16_530_948

#: A block's worth of nothing, and a block's worth of something. Only the length is ever read.
NO_CODE = "0x"
SOME_CODE = "0x6080604052"


def _log(address, topic, block, index):
    return {
        "address": address,
        "topics": [topic],
        "data": "0x",
        "blockNumber": hex(block),
        "logIndex": hex(index),
    }


#: How many 32-byte words each covered venue's :class:`ActivityProbe` answers with, keyed by the
#: selector the module derives. The canned chain has to answer in the right width because the width
#: is one of the things being checked.
PROBE_WORDS = {
    V2_GET_RESERVES.selector: V2_GET_RESERVES.words,
    V3_SLOT0.selector: V3_SLOT0.words,
}


class CannedChain(object):
    """A chain that knows when each address acquired code, when it was first used, and its logs.

    Every call is counted and kept, because half of what this file asserts is about *which* calls
    were made: the derivation's claim is not only that it finds the pool but that it finds it
    without a log range, and a client that did not record the difference could not tell the two
    discoveries apart.

    ``active_from`` is what an :class:`ActivityProbe` reads. Left unset it is **derived from the
    logs** — the first block in which the address emitted anything at all — which is what a real
    pool does: ``getReserves()`` moves in the block of the first ``mint``, ``swap`` or ``sync``,
    and those are the events these logs are. Setting it explicitly is for the cases where the two
    must differ: a pool touched before it emitted anything this filter matches, and a pool that
    answers the probe in the wrong shape.
    """

    def __init__(self, code_from=None, logs=(), timestamps=None, active_from=None,
                 probe_answers=None):
        self.code_from = {normalise_asset(a): b for a, b in (code_from or {}).items()}
        self.logs = list(logs)
        self.timestamps = timestamps or {}
        self.active_from = {normalise_asset(a): b for a, b in (active_from or {}).items()}
        self.probe_answers = {normalise_asset(a): b for a, b in (probe_answers or {}).items()}
        self.calls = []

    # -- the three methods the derivation uses ----------------------------------
    def call(self, method, params=None):
        if method == "eth_call":
            return self._eth_call(params)
        self.calls.append((method,) + tuple(params or ()))
        if method != "eth_getCode":
            raise AssertionError("unexpected method {}".format(method))
        address, block = normalise_asset(params[0]), int(params[1], 16)
        first = self.code_from.get(address)
        return NO_CODE if first is None or block < first else SOME_CODE

    def _eth_call(self, params):
        address = normalise_asset(params[0]["to"])
        selector, block = params[0]["data"], int(params[1], 16)
        self.calls.append(("eth_call", address, selector, params[1]))
        if selector not in PROBE_WORDS:
            raise AssertionError("unexpected selector {}".format(selector))
        code_from = self.code_from.get(address)
        if code_from is None or block < code_from:
            return NO_CODE  # no code, no function to run — what a real node answers
        if address in self.probe_answers:
            return self.probe_answers[address]
        first = self._first_activity(address)
        words = PROBE_WORDS[selector]
        if first is None or block < first:
            return "0x" + "0" * (64 * words)
        # Reserves and a blockTimestampLast, or slot0's price and unlocked flag. Only zero versus
        # non-zero is ever read, so the shape is what matters and the values are placeholders.
        return "0x" + ("0" * 62 + "01") * words

    def _first_activity(self, address):
        if address in self.active_from:
            return self.active_from[address]
        blocks = [int(log["blockNumber"], 16) for log in self.logs
                  if normalise_asset(log["address"]) == address]
        return min(blocks) if blocks else None

    def get_logs(self, from_block=None, to_block=None, address=None, topics=None):
        self.calls.append(("eth_getLogs", from_block, to_block, address))
        wanted = topics[0] if topics else None
        addresses = {normalise_asset(address)} if isinstance(address, str) else {
            normalise_asset(a) for a in (address or [])}
        return [
            log for log in self.logs
            if (not addresses or normalise_asset(log["address"]) in addresses)
            and (wanted is None or log["topics"][0] in wanted)
            and from_block <= int(log["blockNumber"], 16) <= to_block
        ]

    def get_block_by_number(self, block, full_transactions=False):
        height = int(block, 16)
        return {
            "number": hex(height),
            "timestamp": hex(self.timestamps.get(height, 1_675_218_047)),
            "hash": "0x" + "%064x" % height,
        }

    @property
    def log_calls(self):
        return [call for call in self.calls if call[0] == "eth_getLogs"]

    @property
    def code_calls(self):
        return [call for call in self.calls if call[0] == "eth_getCode"]

    @property
    def probe_calls(self):
        return [call for call in self.calls if call[0] == "eth_call"]


def _factories_exist(extra=None):
    """Code at each covered factory's stated creation block and none before — what
    ``confirm_factories`` measures."""
    code = {factory.address: factory.created_block for factory in COVERED_FACTORIES}
    code.update(extra or {})
    return code


# -- eth_getCode as the only instrument ------------------------------------------


def test_code_length_reports_zero_for_an_address_with_none():
    chain = CannedChain(code_from={SBET_PAIR: SBET_PAIR_CREATED})

    assert code_length(chain, SBET_PAIR, SBET_PAIR_CREATED - 1) == 0
    assert code_length(chain, SBET_PAIR, SBET_PAIR_CREATED) > 0


def test_code_length_asks_about_a_height_and_never_a_tag():
    """Whether a pool exists *today* is a different question from whether it existed at the
    horizon, and the second is the one a run that ends in February 2023 is asking."""
    chain = CannedChain(code_from={SBET_PAIR: SBET_PAIR_CREATED})

    code_length(chain, SBET_PAIR, HORIZON)

    assert chain.code_calls == [("eth_getCode", SBET_PAIR, hex(HORIZON))]


def test_the_creation_block_is_found_by_binary_search():
    chain = CannedChain(code_from={SBET_PAIR: SBET_PAIR_CREATED})

    found = creation_block(chain, SBET_PAIR, UNISWAP_V2_FACTORY.created_block, HORIZON)

    assert found == SBET_PAIR_CREATED


def test_the_binary_search_costs_about_two_dozen_calls_and_no_log_range():
    """The number is the point. The sweep this replaces is ~700,000 requests over the same range,
    every one of them a log filter an endpoint caps at 10 blocks."""
    chain = CannedChain(code_from={SBET_PAIR: SBET_PAIR_CREATED})

    creation_block(chain, SBET_PAIR, UNISWAP_V2_FACTORY.created_block, HORIZON)

    assert chain.log_calls == []
    assert len(chain.code_calls) <= 25, "log2(6.9M) is 23, plus the one below the lower bound"


def test_code_before_the_factory_existed_is_refused():
    """A derived address is only meaningful as "where that factory's pool would be". A contract
    there before the factory existed is some other deployment, and dating the token from it would
    put the token's start before the venue's."""
    chain = CannedChain(code_from={SBET_PAIR: UNISWAP_V2_FACTORY.created_block - 100})

    with pytest.raises(FactoryNotAtStatedBlock) as raised:
        creation_block(chain, SBET_PAIR, UNISWAP_V2_FACTORY.created_block, HORIZON)

    assert SBET_PAIR in str(raised.value)


# -- the pool's own storage, as the scan's floor ---------------------------------


def _pool(address=SBET_PAIR, created=SBET_PAIR_CREATED, factory=None):
    factory = factory or UNISWAP_V2_FACTORY
    return tokenstart.CoveredPool(
        address=address, factory=factory.address, venue=factory.label,
        created_block=created, token=SBET, counterparty=WETH,
    )


def test_the_two_probes_are_the_selectors_a_block_explorer_shows():
    """Derived from the signature text beside them rather than written out. ``0x3850c7bd`` is the
    same four bytes ``tools/case_runs.py`` already calls ``V3_SLOT0`` and reads a real pool's price
    with; a derivation that disagreed with it would be reading some other function."""
    assert V2_GET_RESERVES.selector == "0x0902f1ac"
    assert V3_SLOT0.selector == "0x3850c7bd"
    assert UNISWAP_V2_FACTORY.activity_probe is V2_GET_RESERVES
    assert UNISWAP_V3_FACTORY.activity_probe is V3_SLOT0


def test_a_probe_must_carry_both_arguments_for_using_it():
    """``zero_means`` is why the floor is safe and ``monotone_because`` is why the binary search
    finds the first crossing. A probe adopted because it looked right in the cases somebody tried
    is a floor that lands above a swap in the case nobody tried."""
    with pytest.raises(ValueError):
        ActivityProbe(signature="liquidity()", words=1, zero_means="",
                      monotone_because="it goes up")
    with pytest.raises(ValueError):
        ActivityProbe(signature="liquidity()", words=1, zero_means="no liquidity",
                      monotone_because="")
    with pytest.raises(ValueError):
        ActivityProbe(signature="liquidity()", words=0, zero_means="no liquidity",
                      monotone_because="it goes up")


def test_the_whole_returndata_is_compared_against_zero_and_not_one_field():
    """A v2 pair drained back to nothing answers two zero reserves and a non-zero
    ``blockTimestampLast``. Reading only the reserves would call that pair untouched and start the
    scan after every swap it ever served."""
    drained = "0x" + "0" * 64 + "0" * 64 + "0" * 56 + "63e0f000"
    chain = CannedChain(code_from={SBET_PAIR: SBET_PAIR_CREATED},
                        probe_answers={SBET_PAIR: drained})

    assert probe_reading(chain, V2_GET_RESERVES, SBET_PAIR, HORIZON) > 0


def test_an_address_with_no_code_reads_as_zero_rather_than_as_an_error():
    """"Not deployed yet" and "deployed and never touched" are the same statement for a scan floor,
    and a real node answers the first with empty returndata."""
    chain = CannedChain(code_from={SBET_PAIR: SBET_PAIR_CREATED})

    assert probe_reading(chain, V2_GET_RESERVES, SBET_PAIR, SBET_PAIR_CREATED - 1) == 0


def test_returndata_of_the_wrong_width_raises_rather_than_being_read_as_a_number():
    """The init code hash is pinned, so the bytecode at this address has this function. An answer
    of another width is a wrong constant here, not a pool with an opinion."""
    chain = CannedChain(code_from={SBET_PAIR: SBET_PAIR_CREATED},
                        probe_answers={SBET_PAIR: "0x" + "0" * 62 + "01"})

    with pytest.raises(PoolStateUnreadable) as raised:
        probe_reading(chain, V2_GET_RESERVES, SBET_PAIR, HORIZON)

    assert "getReserves()" in str(raised.value)


def test_the_first_active_block_is_found_by_binary_search_over_the_pool_s_own_state():
    chain = CannedChain(
        code_from={SBET_PAIR: SBET_PAIR_CREATED},
        logs=[_log(SBET_PAIR, MINT_V2, SBET_FIRST_MINT, 4)],
    )

    found = first_active_block(chain, _pool(), UNISWAP_V2_FACTORY, HORIZON)

    assert found == SBET_FIRST_MINT
    assert chain.log_calls == []
    assert len(chain.probe_calls) <= 25, "log2(412,580) is 19, and the range is smaller than that"


def test_a_pool_never_touched_by_the_horizon_has_no_active_block():
    """Not an error and not a start: a pool created and never used has no §4.7 date, and neither
    does one first used after the horizon."""
    chain = CannedChain(code_from={SBET_PAIR: SBET_PAIR_CREATED})

    assert first_active_block(chain, _pool(), UNISWAP_V2_FACTORY, HORIZON) is None
    assert len(chain.probe_calls) == 1, "one reading at the horizon settles it"


def test_a_factory_with_no_probe_scans_from_the_pool_s_creation_block():
    """The absence of a probe is a cost, not a default — the budget is then spent on the untouched
    blocks — and it must not be a skip."""
    probeless = replace(UNISWAP_V2_FACTORY, activity_probe=None)
    chain = CannedChain(code_from={SBET_PAIR: SBET_PAIR_CREATED})

    assert first_active_block(chain, _pool(), probeless, HORIZON) == SBET_PAIR_CREATED
    assert chain.probe_calls == []


# -- the scan, and the ten blocks it is allowed to ask for -----------------------


def test_the_slice_is_the_largest_range_every_endpoint_serves():
    """Ten. The first endpoint the client tries answers HTTP 400 above ten, and a run that only
    works while the one uncapped vendor is up is a run whose cost cannot be reproduced."""
    assert CHUNK_BLOCKS == 10
    assert SCAN_BLOCKS == SCAN_SLICES * CHUNK_BLOCKS


def test_no_slice_of_the_scan_is_wider_than_the_cap():
    chain = CannedChain(
        code_from=_factories_exist({SBET_PAIR: SBET_PAIR_CREATED}),
        logs=[
            _log(SBET_PAIR, MINT_V2, SBET_FIRST_MINT, 4),
            _log(SBET_PAIR, SWAP_V2, SBET_FIRST_SWAP, 9),
        ],
    )

    derive_token_starts(chain, [SBET], HORIZON)

    assert chain.log_calls, "the scan has to read some logs; the discovery is what reads none"
    for _method, from_block, to_block, _address in chain.log_calls:
        assert to_block - from_block + 1 <= CHUNK_BLOCKS


def test_the_scan_starts_at_the_first_active_block_and_not_at_the_creation_block():
    """SBET's pair sat untouched for 46 blocks. Real pools in this population sat untouched for
    17,941, which at ten blocks a request is 1,795 requests to reach the first Mint."""
    chain = CannedChain(
        code_from=_factories_exist({SBET_PAIR: SBET_PAIR_CREATED}),
        logs=[
            _log(SBET_PAIR, MINT_V2, SBET_FIRST_MINT, 4),
            _log(SBET_PAIR, SWAP_V2, SBET_FIRST_SWAP, 9),
        ],
    )

    derive_token_starts(chain, [SBET], HORIZON)

    first_range = chain.log_calls[0]
    assert first_range[1] == SBET_FIRST_MINT
    assert len(chain.log_calls) == 1, (
        "the mint and the swap are four blocks apart, so one ten-block slice holds both")


def test_a_scan_that_runs_out_of_budget_refuses_instead_of_taking_a_later_pool():
    """The guard this whole bound turns on. "Did not trade in the blocks I read" and "never traded"
    are different sentences, and only the second permits moving on: a later pool's first swap taken
    as the token's start files the token as younger than it is."""
    early = pool_address(UNISWAP_V2, SBET, USDC)
    quiet_from = SBET_PAIR_CREATED - 100_000
    chain = CannedChain(
        code_from=_factories_exist({early: quiet_from, SBET_PAIR: SBET_PAIR_CREATED}),
        active_from={early: quiet_from},
        logs=[
            _log(SBET_PAIR, MINT_V2, SBET_FIRST_MINT, 4),
            _log(SBET_PAIR, SWAP_V2, SBET_FIRST_SWAP, 9),
        ],
    )

    finding = derive_token_starts(chain, [SBET], HORIZON)[SBET]

    assert finding.start is None
    assert finding.refusal.startswith("first_trade_outside_the_scanned_range")
    assert early in finding.refusal
    assert token_starts_of({SBET: finding}) == {}


def test_a_pool_whose_whole_range_was_read_is_passed_over_rather_than_refused():
    """The other side of the same fence. This pool was searched to the ceiling asked for, so "no
    swap" is a fact about the pool and the next pool may still supply the start."""
    early = pool_address(UNISWAP_V2, SBET, USDC)
    chain = CannedChain(
        code_from=_factories_exist({early: SBET_PAIR_CREATED - 20,
                                    SBET_PAIR: SBET_PAIR_CREATED}),
        logs=[
            _log(SBET_PAIR, MINT_V2, SBET_FIRST_MINT, 4),
            _log(SBET_PAIR, SWAP_V2, SBET_FIRST_SWAP, 9),
        ],
        timestamps={SBET_FIRST_SWAP: 1_675_218_047},
    )

    finding = derive_token_starts(chain, [SBET], HORIZON)[SBET]

    assert finding.start.block == SBET_FIRST_SWAP
    assert any(early in note for note in finding.notes)


def test_a_pool_trade_cannot_be_exhausted_and_answered_at_once():
    """Both together would let a caller read the swap and ignore that the scan stopped early."""
    with pytest.raises(ValueError):
        PoolTrade(swap_block=SBET_FIRST_SWAP, liquidity_first=True,
                  scanned_from=SBET_FIRST_MINT, scanned_to=SBET_FIRST_SWAP, exhausted=True)
    with pytest.raises(ValueError):
        PoolTrade(swap_block=SBET_FIRST_SWAP, liquidity_first=None,
                  scanned_from=SBET_FIRST_MINT, scanned_to=SBET_FIRST_SWAP)


def test_the_scan_reports_where_it_looked_so_a_refusal_can_be_told_from_a_fact():
    chain = CannedChain(
        code_from={SBET_PAIR: SBET_PAIR_CREATED},
        logs=[
            _log(SBET_PAIR, MINT_V2, SBET_FIRST_MINT, 4),
            _log(SBET_PAIR, SWAP_V2, SBET_FIRST_SWAP, 9),
        ],
    )

    trade = pool_trading_start(chain, _pool(), UNISWAP_V2_FACTORY, HORIZON)

    assert trade.swap_block == SBET_FIRST_SWAP
    assert trade.liquidity_first is True
    assert trade.scanned_from == SBET_FIRST_MINT
    assert trade.exhausted is False


# -- discovery without a single log range ----------------------------------------


def test_a_derived_pool_is_found_and_dated():
    chain = CannedChain(code_from=_factories_exist({SBET_PAIR: SBET_PAIR_CREATED}))

    pools = pools_by_derivation(chain, [SBET], HORIZON)

    assert [pool.address for pool in pools[SBET]] == [SBET_PAIR]
    found = pools[SBET][0]
    assert found.created_block == SBET_PAIR_CREATED
    assert found.counterparty == WETH
    assert found.factory == UNISWAP_V2_FACTORY.address
    assert found.venue == "Uniswap v2"


def test_discovery_issues_no_log_range_at_all():
    """The whole reason this exists. An endpoint that caps ``eth_getLogs`` at 10 blocks cannot
    answer the sweep and has nothing to say about this."""
    chain = CannedChain(code_from=_factories_exist({SBET_PAIR: SBET_PAIR_CREATED}))

    pools_by_derivation(chain, [SBET], HORIZON)

    assert chain.log_calls == []


def test_the_number_of_candidates_is_venues_times_tiers_times_counterparties():
    """One ``eth_getCode`` per candidate address: four counterparties, one v2 pool and four v3
    tiers each — twenty, for a token with no pool at all, and then the answer is 'no pool'."""
    chain = CannedChain(code_from=_factories_exist())

    pools = pools_by_derivation(chain, [SBET], HORIZON)

    assert pools == {SBET: ()}
    assert len(chain.code_calls) == len(DERIVED_COUNTERPARTIES) * sum(len(v.fee_tiers) if v.fee_tiers else 1 for v in DERIVABLE_VENUES)


def test_a_token_that_is_itself_a_quote_asset_is_not_paired_with_itself():
    """WETH has no WETH/WETH pool, and the other three counterparties still apply."""
    chain = CannedChain(code_from=_factories_exist())

    pools_by_derivation(chain, [WETH], HORIZON)

    assert len(chain.code_calls) == (len(DERIVED_COUNTERPARTIES) - 1) * sum(len(v.fee_tiers) if v.fee_tiers else 1 for v in DERIVABLE_VENUES)


def test_a_pool_created_after_the_horizon_is_not_found():
    """``to_block`` is the marking horizon, and a pool created after it cannot have served a buy
    inside the run. Asking at the horizon rather than at ``latest`` is what makes that true."""
    chain = CannedChain(code_from=_factories_exist({SBET_PAIR: HORIZON + 1}))

    assert pools_by_derivation(chain, [SBET], HORIZON) == {SBET: ()}


def test_two_tokens_are_two_answers():
    chain = CannedChain(code_from=_factories_exist({
        SBET_PAIR: SBET_PAIR_CREATED, DEAD_PAIR: 16_530_559,
    }))

    pools = pools_by_derivation(chain, [SBET, DEAD_TOKEN], HORIZON)

    assert [p.address for p in pools[SBET]] == [SBET_PAIR]
    assert [p.address for p in pools[DEAD_TOKEN]] == [DEAD_PAIR]


def test_a_duplicate_counterparty_is_refused():
    chain = CannedChain(code_from=_factories_exist())

    with pytest.raises(ValueError) as raised:
        pools_by_derivation(chain, [SBET], HORIZON, counterparties=(WETH, WETH))

    assert "twice" in str(raised.value)


def test_a_counterparty_outside_the_four_quote_assets_is_refused():
    """The list narrows the search; it cannot widen it. ``DERIVED_NOT_COVERED`` names those four
    and is written verbatim into every refusal, so a run that searched a fifth would hand somebody
    working the queue a refusal describing a blind spot the search did not have."""
    chain = CannedChain(code_from=_factories_exist())

    with pytest.raises(UnrecognisedFactory) as raised:
        pools_by_derivation(chain, [SBET], HORIZON, counterparties=(WETH, DEAD_TOKEN))

    assert DEAD_TOKEN in str(raised.value)


def test_no_counterparties_is_refused_rather_than_answered_with_nothing():
    """An empty list would report every token as having no pool — a refusal from a search that
    never ran, which reads exactly like a refusal from one that did."""
    chain = CannedChain(code_from=_factories_exist())

    with pytest.raises(ValueError):
        pools_by_derivation(chain, [SBET], HORIZON, counterparties=())


def test_a_factory_with_no_derivation_venue_is_refused_rather_than_skipped():
    """Searching the remaining factories anyway would report 'no pool' for a token whose only pool
    is on this one."""
    unknown = Factory(
        address="0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac",  # SushiSwap's factory
        label="SushiSwap",
        created_block=10_794_229,
        created_event=UNISWAP_V2_FACTORY.created_event,
        created_topic_count=3,
        pool_data_word=0,
        mint_event=MINT_V2,
        swap_event=SWAP_V2,
    )
    chain = CannedChain(code_from=_factories_exist())

    with pytest.raises(UnrecognisedFactory):
        pools_by_derivation(chain, [SBET], HORIZON, factories=(unknown,))


# -- the two discoveries, and what each one admits it cannot see -----------------


def test_the_default_discovery_is_the_one_that_can_run():
    default = inspect.signature(derive_token_starts).parameters["discovery"].default

    assert default is CREATE2_DERIVATION
    assert CREATE2_DERIVATION.find is not FACTORY_LOG_SWEEP.find


def test_a_discovery_must_declare_what_it_cannot_see():
    """Every search of this chain misses something. A discovery claiming otherwise would put
    'nothing was missed' into a refusal somebody works a queue from."""
    with pytest.raises(ValueError):
        PoolDiscovery(label="everything", find=lambda *a: {}, not_covered=())


def test_derive_token_starts_refuses_a_bare_function_as_a_discovery():
    chain = CannedChain(code_from=_factories_exist())

    with pytest.raises(TokenStartDefect):
        derive_token_starts(chain, [SBET], HORIZON, discovery=pools_by_derivation)


def test_the_refusal_names_the_search_that_ran_and_the_tiers_it_could_not_see():
    """The requirement in one test: a fee tier this module does not cover is a pool it cannot see,
    and that has to reach the refusal rather than a default date."""
    chain = CannedChain(code_from=_factories_exist())

    findings = derive_token_starts(chain, [SBET], HORIZON)
    refusal = refusals_of(findings)[SBET]

    assert refusal.startswith("no_pool_on_covered_factories")
    assert "CREATE2 address derivation" in refusal
    assert "fee tier" in refusal
    assert "0.05%" in refusal and "1.00%" in refusal
    assert "quote assets" in refusal
    assert token_starts_of(findings) == {}


def test_the_sweep_carries_its_own_blind_spots_and_not_the_derivation_s():
    """The two searches do not miss the same things: the sweep sees a pool against any counterparty
    and at any tier. A single module-level list would be quietly wrong about one of them."""
    chain = CannedChain(code_from=_factories_exist())

    findings = derive_token_starts(chain, [SBET], HORIZON, discovery=FACTORY_LOG_SWEEP, chunk=10**9)
    refusal = refusals_of(findings)[SBET]

    assert "factory creation logs" in refusal
    assert "fee tier" not in refusal
    assert "quote assets" not in refusal


def test_the_derivation_s_uncovered_list_is_the_pool_module_s_plus_the_counterparties():
    assert tokenstart.DERIVED_NOT_COVERED[1:] == NOT_DERIVABLE
    assert "quote assets" in tokenstart.DERIVED_NOT_COVERED[0]
    assert CREATE2_DERIVATION.not_covered == tokenstart.DERIVED_NOT_COVERED
    assert FACTORY_LOG_SWEEP.not_covered == tokenstart.NOT_COVERED


# -- end to end, on the two pools §4.7 is actually about -------------------------


def test_the_start_is_the_first_swap_and_not_the_pool_s_creation():
    """SBET's pair was created at 16530898 and first traded at 16530948 — 50 blocks in which the
    token could not be bought. Reading creation as the start would put those 50 blocks inside
    bucket A, the first-ten-blocks bucket, and make the first-hour share read low.
    """
    chain = CannedChain(
        code_from=_factories_exist({SBET_PAIR: SBET_PAIR_CREATED}),
        logs=[
            _log(SBET_PAIR, MINT_V2, SBET_FIRST_MINT, 4),
            _log(SBET_PAIR, SWAP_V2, SBET_FIRST_SWAP, 9),
        ],
        timestamps={SBET_FIRST_SWAP: 1_675_218_047},
    )

    findings = derive_token_starts(chain, [SBET], HORIZON, chunk=10_000)
    finding = findings[SBET]

    assert finding.established
    assert finding.start.block == SBET_FIRST_SWAP
    assert finding.start.timestamp == 1_675_218_047
    assert finding.pool == SBET_PAIR
    assert finding.refusal is None
    assert [pool.created_block for pool in finding.pools] == [SBET_PAIR_CREATED]


def test_a_swap_with_no_mint_before_it_refuses_rather_than_taking_a_later_pool():
    """§4.7's conjunction is 'usable liquidity AND at least one real swap'. Skipping the pool would
    move the start forward and file the token as younger than it is."""
    chain = CannedChain(
        code_from=_factories_exist({SBET_PAIR: SBET_PAIR_CREATED}),
        logs=[_log(SBET_PAIR, SWAP_V2, SBET_FIRST_SWAP, 9)],
    )

    findings = derive_token_starts(chain, [SBET], HORIZON, chunk=10_000)

    assert refusals_of(findings)[SBET].startswith("liquidity_not_established")


def test_a_pool_that_exists_and_never_traded_is_not_a_start():
    """Pool creation alone is not a start: the token has no established age rather than a young
    one."""
    chain = CannedChain(code_from=_factories_exist({SBET_PAIR: SBET_PAIR_CREATED}))

    findings = derive_token_starts(chain, [SBET], HORIZON, chunk=10**9)

    assert refusals_of(findings)[SBET].startswith("no_swap_in_any_covered_pool")


def test_the_earliest_pool_wins_and_the_later_one_is_recorded_as_skipped():
    """Addendum §9.2: migration does not reset token age, so the start is the earliest across every
    covered pool. A buyer on the second pool is not an early buyer of the token."""
    older = pool_address(UNISWAP_V2, SBET, USDC)
    chain = CannedChain(
        code_from=_factories_exist({
            older: SBET_PAIR_CREATED - 5,
            SBET_PAIR: SBET_PAIR_CREATED,
        }),
        logs=[
            _log(older, MINT_V2, SBET_PAIR_CREATED + 2, 2),
            _log(older, SWAP_V2, SBET_PAIR_CREATED + 10, 3),
            _log(SBET_PAIR, MINT_V2, SBET_FIRST_MINT, 4),
            _log(SBET_PAIR, SWAP_V2, SBET_FIRST_SWAP, 9),
        ],
        timestamps={SBET_PAIR_CREATED + 10: 1_675_217_567},
    )

    finding = derive_token_starts(chain, [SBET], HORIZON, chunk=10_000)[SBET]

    assert finding.start.block == SBET_PAIR_CREATED + 10
    assert finding.pool == older
    assert finding.start.block < SBET_FIRST_SWAP
    assert any(SBET_PAIR in note for note in finding.notes), (
        "the pool that lost the comparison is recorded, never silently dropped")


# -- the boundary this module must not cross -------------------------------------


def test_the_start_derivation_does_not_import_the_thing_that_buckets_it():
    """``marking.token_age_bucket`` owns what a bucket is and stays the only thing that does.

    This module supplies the date that function asks for. If it could also read the bucket
    boundaries there would be two authorities on where the clock starts, and the one in this file
    would be the one nobody audits.
    """
    source = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "src", "pipeline", "tokenstart.py",
    )
    with open(source, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=source)

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])

    assert "marking" not in imported
    assert "scoring" not in imported


def test_the_swap_topics_are_the_registry_s_own_spellings():
    """Imported from ``ingest`` rather than copied, so the two cannot drift apart."""
    assert UNISWAP_V2_FACTORY.swap_event == SWAP_V2
    assert UNISWAP_V3_FACTORY.swap_event is not None
    assert UNISWAP_V2_FACTORY.swap_event != UNISWAP_V3_FACTORY.swap_event
