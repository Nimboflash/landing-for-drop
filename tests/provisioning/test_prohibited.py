"""The PROHIBITED rule, pinned as a refusal rather than a comment.

Pre-registration §9.1 marks positions from *pool-level* on-chain OHLCV and never from coin-level
aggregator data, because a coin listing is auto-deactivated after 30 days without trading and then
denies historical access — survivorship bias precisely where the losses are. The rule is not
controversial and nobody will propose breaking it. It will be broken by a convenience call: one
gap, one deadline, and two lines against an endpoint the same API key already opens.

So these tests exist to make weakening the rule expensive. If the prohibition is downgraded to a
warning, if a transport stops routing through it, or if an override stops being required, something
here goes red.
"""

import pytest

from tools.provisioning.prohibited import (
    PERMITTED_COINGECKO_SHAPE,
    PROHIBITED_SOURCES,
    ProhibitedSourceError,
    SourceOverride,
    assert_not_prohibited,
    classify_prohibited,
    prohibited_register_entries,
)

from conftest import FakeTransport, Json

COIN_LEVEL_URLS = [
    "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd",
    "https://pro-api.coingecko.com/api/v3/simple/token_price/ethereum?contract_addresses=0xabc",
    "https://pro-api.coingecko.com/api/v3/coins/ethereum/market_chart?days=90",
    "https://pro-api.coingecko.com/api/v3/coins/markets?vs_currency=usd",
    "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest?symbol=ETH",
    "https://api.coinpaprika.com/v1/tickers/eth-ethereum",
]

POOL_LEVEL_URL = (
    "https://pro-api.coingecko.com/api/v3/onchain/networks/eth/pools/0xdead/ohlcv/day"
    "?include_inactive_source=true"
)


@pytest.mark.parametrize("url", COIN_LEVEL_URLS)
def test_every_coin_level_endpoint_is_refused(url):
    with pytest.raises(ProhibitedSourceError):
        assert_not_prohibited(url)


def test_the_refusal_says_what_to_do_instead():
    with pytest.raises(ProhibitedSourceError) as excinfo:
        assert_not_prohibited(COIN_LEVEL_URLS[0])
    message = str(excinfo.value)
    assert "PROHIBITED source" in message
    assert "refusal, not a warning" in message
    assert "SourceOverride" in message


def test_the_pool_level_endpoint_is_permitted():
    """Same vendor, same key, different question — and the boundary has to be legible."""
    assert classify_prohibited(POOL_LEVEL_URL) is None
    assert assert_not_prohibited(POOL_LEVEL_URL) is None
    assert "/onchain/networks/" in PERMITTED_COINGECKO_SHAPE
    assert "ohlcv" in PERMITTED_COINGECKO_SHAPE


# -- the override is deliberately expensive --------------------------------------

def test_an_override_unlocks_exactly_the_source_it_names():
    override = SourceOverride(
        source_id="coingecko_simple_price",
        approver="Research Owner",
        reason="one-off reconciliation against a vendor invoice",
        ticket="03",
    )
    assert assert_not_prohibited(COIN_LEVEL_URLS[0], override).source_id == \
        "coingecko_simple_price"

    # ...and nothing else. An override is not a skeleton key.
    with pytest.raises(ProhibitedSourceError):
        assert_not_prohibited(COIN_LEVEL_URLS[2], override)


@pytest.mark.parametrize("blank_field", ["approver", "reason", "ticket", "source_id"])
def test_an_override_missing_any_field_is_not_an_override(blank_field):
    fields = {
        "source_id": "coingecko_simple_price",
        "approver": "someone",
        "reason": "because",
        "ticket": "03",
    }
    fields[blank_field] = "   "
    with pytest.raises(ValueError) as excinfo:
        SourceOverride(**fields)
    assert blank_field in str(excinfo.value)


# -- enforced in the transport, including the fake one ---------------------------

@pytest.mark.parametrize("url", COIN_LEVEL_URLS)
def test_no_transport_will_open_a_prohibited_url(url):
    """The check lives in the base class, so a *fake* transport refuses too.

    That is the difference between a rule the suite proves and a rule the suite would happily let
    someone delete: if enforcement moved into the live transport only, every test would keep
    passing while the prohibition quietly stopped applying to anything anyone wrote.
    """
    transport = FakeTransport(default=Json({"price": 1}))
    with pytest.raises(ProhibitedSourceError):
        transport.get(url)
    assert transport.calls == [], "the request must be refused before it is performed"


def test_a_transport_carrying_an_override_performs_the_call():
    override = SourceOverride("coingecko_simple_price", "Research Owner", "audit", "03")
    transport = FakeTransport(default=Json({"ethereum": {"usd": "1234"}}), override=override)
    response = transport.get(COIN_LEVEL_URLS[0])
    assert response.ok
    assert len(transport.calls) == 1


def test_the_permitted_pool_url_passes_through_a_transport():
    transport = FakeTransport(default=Json({"data": {"attributes": {"ohlcv_list": []}}}))
    assert transport.get(POOL_LEVEL_URL).ok


# -- and it is published in the register -----------------------------------------

def test_the_prohibition_appears_in_the_machine_readable_register():
    entries = prohibited_register_entries()
    assert len(entries) == len(PROHIBITED_SOURCES) >= 5
    for entry in entries:
        assert entry["source_id"] and entry["url_shape"] and entry["why"]
    ids = {entry["source_id"] for entry in entries}
    assert {"coingecko_simple_price", "coingecko_market_chart"} <= ids
