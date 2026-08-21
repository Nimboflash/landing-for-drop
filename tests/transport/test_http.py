"""The HTTP seam: the honest agent, and the difference between silence and a refusal."""

import json

import pytest

from transport.http import (
    BROWSER_AGENT_FRAGMENTS,
    DishonestUserAgent,
    EndpointUnreachable,
    FloatInChainResponse,
    HttpResponse,
    HttpTransport,
    UrllibHttpTransport,
    assert_honest_user_agent,
    parse_json_bytes,
)

from conftest import FakeHttpTransport, Json, Rpc

HONEST = "phase0-ingest/1.0 (smart-wallet research; contact: product@saraf.app)"


# -- the User-Agent rule ---------------------------------------------------------


def test_the_honest_agent_is_accepted_and_returned():
    assert assert_honest_user_agent(HONEST) == HONEST


@pytest.mark.parametrize("agent", [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Opera/9.80",
    "Mozilla/4.0 (compatible; MSIE 7.0; Trident/5.0)",
])
def test_a_browser_shaped_agent_is_refused_before_anything_is_sent(agent):
    with pytest.raises(DishonestUserAgent) as exc:
        assert_honest_user_agent(agent)
    message = str(exc.value)
    assert "eth.drpc.org" in message, "the refusal must name what this already cost"
    assert "permanently banned" in message


@pytest.mark.parametrize("agent", [None, "", "   ", 7])
def test_an_absent_agent_is_refused(agent):
    with pytest.raises(DishonestUserAgent) as exc:
        assert_honest_user_agent(agent)
    assert "User-Agent" in str(exc.value)


def test_every_declared_fragment_is_actually_refused():
    """Guard the guard: the list is the rule, not decoration."""
    for fragment in BROWSER_AGENT_FRAGMENTS:
        with pytest.raises(DishonestUserAgent):
            assert_honest_user_agent("something " + fragment.upper() + " something")


def test_the_base_class_enforces_the_agent_so_a_fake_inherits_the_rule():
    """The rule lives in ``post_json``, which every transport — live or fake — goes through."""
    with pytest.raises(DishonestUserAgent):
        FakeHttpTransport(user_agent="Mozilla/5.0")


def test_the_agent_is_rechecked_at_send_time_not_only_at_construction():
    """Assigning a browser agent after construction must not slip past."""
    transport = FakeHttpTransport({"https://node": [Rpc("0x1")]}, user_agent=HONEST)
    transport.user_agent = "Mozilla/5.0"
    with pytest.raises(DishonestUserAgent):
        transport.post_json("https://node", {"jsonrpc": "2.0"})
    assert transport.calls == [], "nothing may be sent once the agent is dishonest"


def test_a_dishonest_agent_supplied_as_a_header_override_is_refused_too():
    transport = FakeHttpTransport({"https://node": [Rpc("0x1")]}, user_agent=HONEST)
    with pytest.raises(DishonestUserAgent):
        transport.post_json("https://node", {"jsonrpc": "2.0"},
                            headers={"User-Agent": "Mozilla/5.0"})


def test_post_json_sends_the_agent_and_the_payload():
    transport = FakeHttpTransport({"https://node": [Rpc("0x2a")]}, user_agent=HONEST)
    transport.post_json("https://node", {"jsonrpc": "2.0", "id": 1, "method": "eth_chainId",
                                         "params": []})
    call = transport.calls[0]
    assert call["headers"]["User-Agent"] == HONEST
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["request"]["method"] == "eth_chainId"


def test_the_live_transport_is_constructible_and_refuses_a_browser_agent():
    """Constructed, never called — ``no_network`` guarantees the second half."""
    assert UrllibHttpTransport(user_agent=HONEST).user_agent == HONEST
    with pytest.raises(DishonestUserAgent):
        UrllibHttpTransport(user_agent="Mozilla/5.0")


def test_the_base_perform_is_abstract():
    with pytest.raises(NotImplementedError):
        HttpTransport(user_agent=HONEST)._perform("https://node", {}, b"{}", 1)


# -- responses -------------------------------------------------------------------


def test_ok_is_the_2xx_range():
    assert HttpResponse(200).ok
    assert HttpResponse(204).ok
    assert not HttpResponse(300).ok
    assert not HttpResponse(401).ok
    assert not HttpResponse(429).ok


def test_headers_are_looked_up_case_insensitively():
    response = HttpResponse(429, b"", "u", {"Retry-After": "3"})
    assert response.header("retry-after") == "3"
    assert response.header("RETRY-AFTER") == "3"
    assert response.header("absent", "fallback") == "fallback"


def test_text_truncates_and_never_raises_on_undecodable_bytes():
    response = HttpResponse(500, b"\xff\xfe not utf-8 at all", "u")
    assert response.text(6) == response.text()[:6]
    assert "not utf-8" in response.text()


def test_a_non_json_body_parses_as_none_rather_than_raising():
    """"The endpoint answered with an HTML error page" is a fact to report, not a crash."""
    response = HttpResponse(406, b"<html><title>406 Not Acceptable</title></html>", "u")
    assert response.json() is None
    assert "406 Not Acceptable" in response.text()


def test_a_json_float_from_a_node_is_refused():
    with pytest.raises(FloatInChainResponse) as exc:
        HttpResponse(200, b'{"result": 1.5}', "u").json()
    assert "hex strings" in str(exc.value)


def test_a_json_non_finite_constant_is_refused():
    with pytest.raises(FloatInChainResponse):
        parse_json_bytes(b'{"result": NaN}')


def test_integers_and_the_rest_of_json_pass_through_untouched():
    parsed = parse_json_bytes(json.dumps(
        {"a": 1, "b": True, "c": None, "d": ["0x1"], "e": {"f": "0x2"}}
    ).encode("utf-8"))
    assert parsed == {"a": 1, "b": True, "c": None, "d": ["0x1"], "e": {"f": "0x2"}}


def test_unreachable_carries_the_endpoint_and_the_reason():
    error = EndpointUnreachable("https://node", "timed out")
    assert error.url == "https://node"
    assert "timed out" in str(error)


def test_the_fake_refuses_a_call_it_was_not_scripted_for():
    """A test that has not said what an endpoint does has not finished describing its case."""
    transport = FakeHttpTransport({"https://node": [Json({"jsonrpc": "2.0", "id": 1,
                                                          "result": "0x1"})]},
                                  user_agent=HONEST)
    transport.post_json("https://node", {"id": 1})
    with pytest.raises(AssertionError):
        transport.post_json("https://node", {"id": 2})
