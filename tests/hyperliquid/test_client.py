"""The client: that replay is the default, that live is visible, and that back-off is honest.

The property this file exists for is the first one. "Replay by default" is worth nothing as a
sentence — the question is whether a client built the ordinary way *can* reach the network, and the
answer has to be no by construction rather than by a flag nobody set. So the first test reaches into
the client and asserts there is no transport there at all.

The back-off tests use a fake transport, which is the only way to exercise a 429 without earning
one, and a fake sleeper, so the suite does not spend 31 seconds proving it waits.
"""

import pytest

from tools.provisioning.prohibited import ProhibitedSourceError
from tools.provisioning.transport import Response, Transport, TransportError

from tools.hyperliquid.client import (
    BACKOFF_SECONDS,
    INFO_URL,
    LEADERBOARD_URL,
    MAX_ATTEMPTS,
    MAX_RETRY_AFTER,
    RETRY_STATUSES,
    USER_AGENT,
    HyperliquidClient,
    VendorRefused,
    replay_client,
)
from tools.hyperliquid.recording import RecordingCache, RecordingMissing

from conftest import (
    PERP_MARKETS,
    SPOT_MARKETS,
    SPOT_TOKENS,
    WALLET,
    WINDOW_END_MS,
    WINDOW_START_MS,
)


class FakeTransport(Transport):
    """Scripted responses. Subclasses ``Transport`` so the §5 prohibition still applies to it."""

    def __init__(self, script):
        super(FakeTransport, self).__init__()
        self.script = list(script)
        self.sent = []

    def _perform(self, method, url, headers, body, timeout):
        self.sent.append((method, url, dict(headers), body))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _response(status, payload=b'{"ok":true}', headers=None):
    return Response(status, payload, "https://api.hyperliquid.xyz/info", headers or {})


# -- replay is the default, by construction --------------------------------------


def test_the_ordinary_client_holds_no_transport(client):
    """Not a flag. There is nothing here that could open a connection."""
    assert client.transport is None
    assert client.mode == "replay"


def test_a_client_cannot_be_switched_to_live_after_construction(client):
    """``mode`` is a read-only property derived from the transport, so there is no setter to find.

    This is the half that makes "opt-in at construction" mean something: a mode that could be
    assigned would be a flag with extra steps.
    """
    assert isinstance(type(client).mode, property)
    assert type(client).mode.fset is None
    with pytest.raises(AttributeError):
        client.mode = "live"


def test_every_committed_call_replays_and_none_is_live(client):
    client.spot_meta()
    client.meta()
    client.user_fills_by_time(WALLET, WINDOW_START_MS, WINDOW_END_MS)
    client.leaderboard()
    assert [call.mode for call in client.calls] == ["replay"] * 4
    assert client.live_calls == ()
    assert len(client.assert_no_live_calls()) == 4


def test_replayed_calls_are_logged_too(client):
    """A log of only the live calls answers 'did this touch the network?' and not 'what did it read?'."""
    client.meta()
    call = client.calls[0]
    assert call.slug == "meta"
    assert call.status == 200
    assert call.attempts == 0
    assert call.waited_seconds == 0
    assert call.was_live is False


def test_a_missing_recording_refuses_rather_than_falling_back(tmp_path):
    """The fallback this package refuses to have."""
    empty = replay_client(str(tmp_path))
    with pytest.raises(RecordingMissing) as raised:
        empty.spot_meta()
    assert "python -m tools.hyperliquid.capture spot-meta" in str(raised.value)


def test_a_client_without_a_cache_is_refused():
    with pytest.raises(TypeError) as raised:
        HyperliquidClient(cache=None)
    assert "no such thing as a client without one" in str(raised.value)


def test_an_anonymous_user_agent_is_refused(tmp_path):
    with pytest.raises(ValueError) as raised:
        HyperliquidClient(RecordingCache(str(tmp_path)), user_agent="  ")
    assert "one a vendor can only respond to by blocking it" in str(raised.value)


def test_the_user_agent_is_identifying_and_does_not_claim_to_be_a_browser():
    """A probe once sent a fabricated browser UA and had its signature permanently banned."""
    assert "phase0-wallet-research" in USER_AGENT
    assert "not a browser" in USER_AGENT
    for impersonation in ("Mozilla", "Chrome", "Safari", "AppleWebKit", "Gecko"):
        assert impersonation not in USER_AGENT


def test_assert_no_live_calls_names_what_it_found(tmp_path):
    transport = FakeTransport([_response(200, b'{"universe":[]}')])
    live = HyperliquidClient(RecordingCache(str(tmp_path)), transport=transport, sleeper=lambda s: None)
    live.meta()
    with pytest.raises(AssertionError) as raised:
        live.assert_no_live_calls()
    assert "made 1 live call(s): meta" in str(raised.value)
    assert "reproducible by nobody" in str(raised.value)


# -- what the recordings actually contain -----------------------------------------


def test_the_recorded_universes_are_returned_verbatim(client):
    spot = client.spot_meta()
    assert sorted(spot) == ["tokens", "universe"]
    assert len(spot["tokens"]) == SPOT_TOKENS
    assert len(spot["universe"]) == SPOT_MARKETS
    assert len(client.meta()["universe"]) == PERP_MARKETS
    # Verbatim means verbatim: numbers are still strings, nothing was coerced.
    assert spot["tokens"][0]["name"] == "USDC"
    assert spot["tokens"][0]["tokenId"] == "0x6d1e7cde53ba9467b783cb7c530ce054"
    assert isinstance(spot["tokens"][0]["deployerTradingFeeShare"], str)


def test_the_leaderboard_row_shape_is_what_the_sampling_code_expects(client, leaderboard):
    rows = leaderboard["leaderboardRows"]
    assert len(rows) == 50
    row = rows[0]
    assert sorted(row) == ["accountValue", "displayName", "ethAddress", "prize",
                           "windowPerformances"]
    # A vendor-computed return. It is here, it is a string, and §3 forbids it being the metric.
    periods = [period for period, _ in row["windowPerformances"]]
    assert periods == ["day", "week", "month", "allTime"]
    assert sorted(row["windowPerformances"][0][1]) == ["pnl", "roi", "vlm"]


# -- millisecond bounds -----------------------------------------------------------


@pytest.mark.parametrize("bad", [1780428669, 0, 999_999_999_999])
def test_seconds_where_milliseconds_belong_are_refused(client, bad):
    """One keystroke away, and it silently returns a window in 1970 rather than an error."""
    with pytest.raises(ValueError) as raised:
        client.user_fills_by_time(WALLET, bad, WINDOW_END_MS)
    assert "almost certainly UTC *seconds*" in str(raised.value)


def test_a_backwards_window_is_refused(client):
    with pytest.raises(ValueError) as raised:
        client.user_fills_by_time(WALLET, WINDOW_END_MS, WINDOW_START_MS)
    assert "ends before it starts" in str(raised.value)


@pytest.mark.parametrize("bad", [1.5, "1780428669789", None, True])
def test_a_non_int_bound_is_refused(client, bad):
    with pytest.raises(TypeError):
        client.user_fills_by_time(WALLET, bad, WINDOW_END_MS)


def test_a_malformed_address_never_reaches_a_request(client):
    from tools.hyperliquid.provenance import MalformedAddress

    with pytest.raises(MalformedAddress):
        client.user_fills("0xnothex")
    assert client.calls == ()


# -- back-off ---------------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(RETRY_STATUSES))
def test_a_retryable_status_is_retried_then_returned(tmp_path, status):
    waits = []
    transport = FakeTransport([_response(status)] * MAX_ATTEMPTS)
    live = HyperliquidClient(RecordingCache(str(tmp_path)), transport=transport,
                             sleeper=waits.append)
    with pytest.raises(VendorRefused):
        live.meta()
    assert len(transport.sent) == MAX_ATTEMPTS
    assert waits == list(BACKOFF_SECONDS)
    assert live.calls[0].attempts == MAX_ATTEMPTS
    assert live.calls[0].waited_seconds == sum(BACKOFF_SECONDS)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_every_other_status_is_an_answer_and_is_not_retried(tmp_path, status):
    """Retrying an answer is how a client turns one vendor refusal into five."""
    transport = FakeTransport([_response(status, b'{"error":"no"}')])
    live = HyperliquidClient(RecordingCache(str(tmp_path)), transport=transport,
                             sleeper=lambda s: None)
    with pytest.raises(VendorRefused) as raised:
        live.meta()
    assert len(transport.sent) == 1
    assert raised.value.status == status
    assert "the answer was a refusal" in str(raised.value)


def test_a_recovery_after_one_retry_returns_the_payload(tmp_path):
    transport = FakeTransport([_response(429), _response(200, b'{"universe":[]}')])
    waits = []
    live = HyperliquidClient(RecordingCache(str(tmp_path)), transport=transport,
                             sleeper=waits.append)
    assert live.meta() == {"universe": []}
    assert waits == [BACKOFF_SECONDS[0]]
    assert live.calls[0].attempts == 2


def test_a_transport_error_is_retried_and_finally_raised(tmp_path):
    """The endpoint did not answer; that is a different fact from it answering no."""
    transport = FakeTransport([TransportError("https://x", "reset")] * MAX_ATTEMPTS)
    live = HyperliquidClient(RecordingCache(str(tmp_path)), transport=transport,
                             sleeper=lambda s: None)
    with pytest.raises(TransportError):
        live.meta()
    assert len(transport.sent) == MAX_ATTEMPTS


def test_retry_after_is_honoured_when_it_is_a_sane_whole_number(tmp_path):
    waits = []
    transport = FakeTransport([
        _response(429, headers={"Retry-After": "7"}),
        _response(200, b'{"universe":[]}'),
    ])
    live = HyperliquidClient(RecordingCache(str(tmp_path)), transport=transport,
                             sleeper=waits.append)
    live.meta()
    assert waits == [7]


@pytest.mark.parametrize("value", ["0", "-1", str(MAX_RETRY_AFTER + 1),
                                   "Wed, 21 Oct 2026 07:28:00 GMT", "soon"])
def test_an_unusable_retry_after_falls_back_to_the_schedule(tmp_path, value):
    """The HTTP-date form is not parsed: it needs a clock, and mis-parsing yields a skew-derived wait."""
    waits = []
    transport = FakeTransport([
        _response(429, headers={"Retry-After": value}),
        _response(200, b'{"universe":[]}'),
    ])
    live = HyperliquidClient(RecordingCache(str(tmp_path)), transport=transport,
                             sleeper=waits.append)
    live.meta()
    assert waits == [BACKOFF_SECONDS[0]]


def test_the_backoff_schedule_is_whole_seconds():
    """A float here would be a float in a package whose house rule has none."""
    assert all(isinstance(s, int) and not isinstance(s, bool) for s in BACKOFF_SECONDS)
    assert list(BACKOFF_SECONDS) == sorted(BACKOFF_SECONDS)


# -- the §5 prohibition still applies ---------------------------------------------


def test_the_prohibition_reaches_this_clients_transport_too(tmp_path):
    """A client that could call an aggregator because it lives in another package would be a second
    way past a refusal the instrument only has one of."""
    transport = FakeTransport([_response(200)])
    live = HyperliquidClient(RecordingCache(str(tmp_path)), transport=transport,
                             sleeper=lambda s: None)
    with pytest.raises(ProhibitedSourceError):
        live.transport.get("https://api.coingecko.com/api/v3/simple/price?ids=hype")


def test_the_two_bases_are_the_ones_that_were_probed():
    assert INFO_URL == "https://api.hyperliquid.xyz/info"
    assert LEADERBOARD_URL == "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"


def test_headers_sent_live_identify_the_caller(tmp_path):
    transport = FakeTransport([_response(200, b'{"universe":[]}')])
    live = HyperliquidClient(RecordingCache(str(tmp_path)), transport=transport,
                             sleeper=lambda s: None)
    live.meta()
    _method, _url, headers, _body = transport.sent[0]
    assert headers["User-Agent"] == USER_AGENT
