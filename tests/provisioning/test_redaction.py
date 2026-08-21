"""Credentials never appear in a log, an error message, or the register.

The dangerous credential here is not the API key header — it is ``ETH_ARCHIVAL_RPC_URL``, where the
secret *is* the URL. That string wants to appear in every useful diagnostic: which endpoint was
contacted, what the connection error was, which node answered. Each of those places ends up in a
file somebody commits.

Two mechanisms, tested separately because either alone fails. Structural redaction catches a key
whose value we were never told; value scrubbing catches a key echoed back inside a vendor's own
error body, which no structural rule would recognise.
"""

from tools.provisioning.redaction import (
    CREDENTIAL_ENV_VARS,
    REDACTED,
    redact,
    redact_url,
    scrub,
    secret_values,
)
from tools.provisioning.transport import Response, TransportError

KEY = "sk_live_9f2b7c4d1e6a8b3c5d7e"
RPC = "https://eth-mainnet.example.com/v2/{}".format(KEY)


def test_the_credential_variables_are_the_three_named_by_the_ticket():
    assert CREDENTIAL_ENV_VARS == ("DUNE_API_KEY", "COINGECKO_API_KEY", "ETH_ARCHIVAL_RPC_URL")


# -- structural ------------------------------------------------------------------

def test_a_key_in_the_path_is_replaced():
    redacted = redact_url(RPC, env={})
    assert KEY not in redacted
    assert redacted == "https://eth-mainnet.example.com/v2/{}".format(REDACTED)


def test_the_query_string_goes_entirely():
    redacted = redact_url("https://api.example.com/v1/data?api_key={}&x=1".format(KEY), env={})
    assert KEY not in redacted
    assert "api_key" not in redacted


def test_userinfo_is_stripped():
    redacted = redact_url("https://user:hunter2@rpc.example.com/v1", env={})
    assert "hunter2" not in redacted
    assert REDACTED in redacted


def test_a_hostname_survives_because_a_diagnostic_needs_one():
    assert "data.binance.vision" in redact_url(
        "https://data.binance.vision/data/spot/daily/klines/ETHUSDT/1m/x.zip", env={}
    )


def test_redaction_is_not_a_preview():
    """No first-four-characters convenience. A prefix is a leak once the key space is small."""
    assert REDACTED == "<redacted>"
    assert KEY[:4] not in redact_url(RPC, env={})


# -- by value --------------------------------------------------------------------

def test_a_key_echoed_in_a_vendor_error_body_is_scrubbed():
    """No structural rule would catch this: the key is loose text in someone else's JSON."""
    env = {"DUNE_API_KEY": KEY}
    body = '{{"error": "invalid API key: {}"}}'.format(KEY)
    assert KEY not in scrub(body, env=env)
    assert REDACTED in scrub(body, env=env)


def test_secret_values_puts_the_longest_first():
    """A short value scrubbed first would leave a recognisable tail of a longer one behind."""
    env = {"DUNE_API_KEY": "abcd", "COINGECKO_API_KEY": "abcdefghij"}
    assert secret_values(env)[0] == "abcdefghij"


def test_free_text_gets_both_treatments():
    env = {"ETH_ARCHIVAL_RPC_URL": RPC}
    text = "failed to reach {} (key {} rejected)".format(RPC, KEY)
    cleaned = redact(text, env=env)
    assert KEY not in cleaned
    assert "eth-mainnet.example.com" in cleaned


# -- the objects that carry them -------------------------------------------------

def test_a_transport_error_never_carries_the_key():
    error = TransportError(RPC, "connection reset")
    assert KEY not in str(error)
    assert KEY not in error.url
    assert "eth-mainnet.example.com" in error.url


def test_a_response_records_a_redacted_url():
    response = Response(200, b"{}", RPC)
    assert KEY not in response.url


def test_a_response_body_echoing_the_key_is_redacted_on_read(monkeypatch):
    monkeypatch.setenv("DUNE_API_KEY", KEY)
    response = Response(401, 'key {} is invalid'.format(KEY).encode("utf-8"), "https://x.test/a")
    assert KEY not in response.text()
    assert REDACTED in response.text()
