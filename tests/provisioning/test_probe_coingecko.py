"""CoinGecko Onchain — the load-bearing probe. A live pool proves nothing.

§9.1 marks a dead pool's positions at zero, and that rule is only implementable because pool-level
history survives after a token stops trading — ``include_inactive_source=true`` is what keeps the
door open. So the capability under test is not "does the OHLCV endpoint answer?". Every live pool
answers, on every tier, with or without the flag. The capability is "does it answer for a pool that
is *dead*", and this file exists to make sure the probe cannot be satisfied by anything less.

Deadness is a property of the world on the day the probe runs, so it is established from the
vendor's own payload — a last candle older than the §9.1 30-day window, and no 24-hour volume or
transactions — rather than asserted in a source file where it would rot. ``now`` is injected here
so the suite can ask "is this pool dead today?" without waiting thirty days for the answer.
"""

import pytest

from tools.provisioning import fixtures
from tools.provisioning.outcomes import ABSENT, INSUFFICIENT, PROVEN, REFUSED, UNREACHABLE
from tools.provisioning.probes.coingecko import CoinGeckoOnchainProbe

from conftest import Boom, FakeTransport, Json
from payloads import (
    DEAD_POOL,
    LIVE_POOL,
    SECONDS_PER_DAY,
    coingecko_routes,
    is_metadata,
    ohlcv,
    pool_metadata,
    with_flag,
    without_flag,
)

#: An arbitrary fixed "today". Nothing depends on the wall clock.
NOW = 1770000000

KEY = "cg-pro-key-xyz"
ENV = {
    "COINGECKO_API_KEY": KEY,
    fixtures.DEAD_POOL_ENV: "eth:{}".format(DEAD_POOL),
}


def probe():
    return CoinGeckoOnchainProbe(now=lambda: NOW)


def days_ago(days):
    return NOW - days * SECONDS_PER_DAY


# -- ABSENT ----------------------------------------------------------------------

def test_no_key_is_absent_and_contacts_nothing(clean_env):
    transport = FakeTransport()
    result = probe().run(transport=transport, env=clean_env)
    assert result.status == ABSENT
    assert "COINGECKO_API_KEY" in result.detail
    assert transport.calls == []


# -- the candidate the probe refuses to invent -----------------------------------

def test_with_no_candidate_named_the_capability_is_unproven_not_assumed():
    """Naming a dead pool means looking at a chain explorer. This package will not fake that."""
    transport = FakeTransport()
    result = probe().run(transport=transport, env={"COINGECKO_API_KEY": KEY})
    assert result.status == INSUFFICIENT
    assert fixtures.DEAD_POOL_ENV in result.detail
    assert transport.calls == []


# -- UNREACHABLE -----------------------------------------------------------------

def test_an_endpoint_that_does_not_answer_is_unreachable():
    result = probe().run(transport=FakeTransport(default=Boom("TLS handshake timeout")), env=ENV)
    assert result.status == UNREACHABLE
    assert "TLS handshake timeout" in result.detail


# -- REFUSED ---------------------------------------------------------------------

def test_a_tier_that_declines_the_flag_is_refused_with_its_own_words():
    message = "This endpoint is available on the Analyst plan and above"
    transport = FakeTransport(default=Json({"status": {"error_message": message}}, status=401))
    result = probe().run(transport=transport, env=ENV)
    assert result.status == REFUSED
    assert message in result.verbatim
    assert result.evidence["http_status"] == 401
    assert result.evidence["pool"] == DEAD_POOL


# -- INSUFFICIENT ----------------------------------------------------------------

def test_no_candles_with_the_flag_is_the_failure_the_marking_rule_cannot_survive():
    transport = FakeTransport(routes=[(with_flag, Json(ohlcv(days_ago(400), count=0)))])
    result = probe().run(transport=transport, env=ENV)
    assert result.status == INSUFFICIENT
    assert result.evidence["candles_with_flag"] == 0
    assert "dead-pool marking rule cannot survive" in result.detail


def test_a_live_pool_proves_nothing():
    """The whole point. Candles for a pool that traded yesterday demonstrate no capability."""
    transport = FakeTransport(routes=coingecko_routes(days_ago(2), volume_usd_h24="0.0"))
    result = probe().run(transport=transport, env=ENV)
    assert result.status == INSUFFICIENT
    assert "a live pool proves nothing" in result.detail


def test_an_old_last_candle_is_not_enough_if_the_pool_is_still_trading():
    """Two independent signals, both required. A stale candle feed on a trading pool is a feed
    problem, and treating it as deadness would prove the capability against the wrong pool."""
    transport = FakeTransport(
        routes=coingecko_routes(days_ago(400), volume_usd_h24="125000.42", buys=18, sells=12)
    )
    result = probe().run(transport=transport, env=ENV)
    assert result.status == INSUFFICIENT
    assert "still live" in result.detail


def test_a_failed_metadata_call_cannot_promote_a_live_pool():
    """Corroboration is allowed to be missing. It is never allowed to manufacture deadness."""
    transport = FakeTransport(routes=[
        (with_flag, Json(ohlcv(days_ago(2)))),
        (is_metadata, Boom("connection reset")),
    ])
    result = probe().run(transport=transport, env=ENV)
    assert result.status == INSUFFICIENT


def test_the_inactivity_threshold_is_the_marking_rules_own_thirty_days():
    """A second definition of "dead" here could disagree with §9.1, which is the rule this proves."""
    assert fixtures.DEAD_INACTIVITY_DAYS == 30
    transport = FakeTransport(routes=coingecko_routes(days_ago(29)))
    assert probe().run(transport=transport, env=ENV).status == INSUFFICIENT


# -- PROVEN ----------------------------------------------------------------------

def test_candles_for_a_dead_pool_with_the_flag_are_proof():
    transport = FakeTransport(routes=coingecko_routes(days_ago(400), candles_with_flag=90))
    result = probe().run(transport=transport, env=ENV)
    assert result.status == PROVEN
    assert result.evidence["pool"] == DEAD_POOL
    assert result.evidence["include_inactive_source"] is True
    assert result.evidence["candles_with_flag"] == 90
    assert result.evidence["days_since_last_candle"] == 400
    assert result.evidence["inactivity_threshold_days"] == 30


def test_the_evidence_shows_the_flag_is_what_did_the_work():
    """Same pool, same key, flag off: nothing. That line is the register's most convincing one."""
    transport = FakeTransport(
        routes=coingecko_routes(days_ago(400), candles_with_flag=90, candles_without_flag=0)
    )
    result = probe().run(transport=transport, env=ENV)
    assert result.evidence["candles_without_flag"] == 0
    assert result.evidence["candles_with_flag"] == 90


def test_missing_metadata_does_not_block_a_pool_that_is_already_stale():
    """The asymmetry, stated: a failed corroboration cannot promote a live pool, but it must not
    veto one whose candle feed has been silent for more than a year either."""
    transport = FakeTransport(routes=[
        (with_flag, Json(ohlcv(days_ago(400)))),
        (without_flag, Json(ohlcv(days_ago(400), count=0))),
        (is_metadata, Boom("connection reset")),
    ])
    result = probe().run(transport=transport, env=ENV)
    assert result.status == PROVEN
    assert result.evidence["volume_usd_h24"] is None


def test_a_live_candidate_does_not_stop_a_dead_one_being_found():
    def flagged(pool):
        return lambda url, body=None: pool in url and with_flag(url)

    def metadata(pool):
        return lambda url, body=None: pool in url and is_metadata(url)

    transport = FakeTransport(routes=[
        (flagged(LIVE_POOL), Json(ohlcv(days_ago(1)))),
        (metadata(LIVE_POOL), Json(pool_metadata("90000.00", buys=40, sells=40))),
        (flagged(DEAD_POOL), Json(ohlcv(days_ago(500)))),
        (metadata(DEAD_POOL), Json(pool_metadata("0.0"))),
        (without_flag, Json(ohlcv(days_ago(500), count=0))),
    ])
    env = dict(ENV)
    env[fixtures.DEAD_POOL_ENV] = "eth:{},eth:{}".format(LIVE_POOL, DEAD_POOL)
    result = probe().run(transport=transport, env=env)
    assert result.status == PROVEN
    assert result.evidence["pool"] == DEAD_POOL


# -- the URL, and the key that must not be in it ---------------------------------

def test_the_flag_is_actually_sent_and_the_surface_is_the_pool_level_one():
    transport = FakeTransport(routes=coingecko_routes(days_ago(400)))
    probe().run(transport=transport, env=ENV)
    flagged = [url for url in transport.urls() if "include_inactive_source=true" in url]
    assert flagged, "the capability under test is the flag; it must appear in the request"
    assert all("/onchain/networks/" in url for url in transport.urls())


def test_the_key_travels_in_a_header_and_never_in_a_url():
    transport = FakeTransport(routes=coingecko_routes(days_ago(400)))
    probe().run(transport=transport, env=ENV)
    assert all(KEY not in url for url in transport.urls())
    assert transport.calls[0]["headers"]["x-cg-pro-api-key"] == KEY


@pytest.mark.parametrize("evidence_key", [
    "network", "pool", "include_inactive_source", "candles_with_flag",
    "last_candle_unix", "days_since_last_candle", "inactivity_threshold_days",
])
def test_the_evidence_records_what_made_it_proof(evidence_key):
    transport = FakeTransport(routes=coingecko_routes(days_ago(400)))
    result = probe().run(transport=transport, env=ENV)
    assert evidence_key in result.evidence
