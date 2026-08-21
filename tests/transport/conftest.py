"""Fixtures for the transport suite. Nothing in this directory opens a socket.

Two jobs.

**Make "no network" a guarantee rather than a habit.** ``no_network`` is autouse and replaces
``urllib.request.urlopen`` for every test here. A test that reached the chain would pass on a
laptop and fail in CI — or worse, pass in CI and quietly measure a *different* chain state than the
committed snapshot, which is the exact failure the recording cache exists to prevent. With the
socket poisoned, a test that needs a real answer has only one place to get it: the fixtures.

**Give the response shapes a fake to come from.** :class:`FakeHttpTransport` subclasses the real
:class:`transport.http.HttpTransport` rather than duck-typing one. ``post_json()`` is a template
method that asserts the honest User-Agent before delegating, so the fake refuses a browser-shaped
agent exactly as the live transport does. A hand-rolled stub would opt out of the one rule this
seam exists to hold — the rule whose violation permanently banned a signature at eth.drpc.org.
"""

import json
import os

import pytest

from transport.http import EndpointUnreachable, HttpResponse, HttpTransport

HERE = os.path.dirname(os.path.abspath(__file__))

#: The committed tracer-bullet snapshot. Real bytes from Ethereum mainnet, recorded through the
#: real client on 2026-08-09 and checked against two independent endpoints.
RECORDINGS = os.path.join(os.path.dirname(HERE), "fixtures", "transport", "recordings")

#: How each default endpoint refuses a trace, measured on the same day. Evidence, not a recording.
TRACE_REFUSALS = os.path.join(
    os.path.dirname(HERE), "fixtures", "transport", "trace_refusals.observed.json"
)

#: The tracer bullet, from the ticket brief. Block 16308001 == 0xf8d721.
TRACER_TX = "0xb8681e7a43edca5fe12d5fc0183b901d73255f86e4188715e3d556ba57f269e3"
TRACER_WALLET = "0xe15b3d62c2bce51f2a8a8d53d76c36b4fab8721c"
TRACER_BLOCK = 16308001
TRACER_BLOCK_HEX = "0xf8d721"


# -- scripted outcomes ----------------------------------------------------------


class Json:
    """A JSON answer with a status."""

    def __init__(self, payload, status=200, headers=None):
        self.payload = payload
        self.status = status
        self.headers = dict(headers or {})


class Text:
    """A non-JSON answer — an HTML error page from a proxy, say."""

    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = dict(headers or {})


class Rpc:
    """A JSON-RPC success envelope. ``id`` is echoed from the request unless overridden."""

    def __init__(self, result, status=200, id=None):
        self.result = result
        self.status = status
        self.id = id


class RpcError:
    """A JSON-RPC error envelope, carrying a node's own words."""

    def __init__(self, message, code=-32601, status=200):
        self.message = message
        self.code = code
        self.status = status


class Boom:
    """The endpoint did not answer at all."""

    def __init__(self, reason="connection reset by peer"):
        self.reason = reason


class FakeHttpTransport(HttpTransport):
    """Routes a POST to a scripted outcome, in order, per endpoint URL.

    ``script`` maps a URL to a list of outcomes consumed one per call, so back-off across repeated
    attempts on one endpoint is expressible. A URL with an exhausted or absent script is an
    assertion failure rather than a default: a test that has not said what an endpoint does has not
    finished describing its case.
    """

    def __init__(self, script=None, user_agent="phase0-test/1.0 (contact: product@saraf.app)"):
        super(FakeHttpTransport, self).__init__(user_agent=user_agent)
        self.script = {url: list(outcomes) for url, outcomes in (script or {}).items()}
        self.calls = []

    def _perform(self, url, headers, body, timeout):
        request = json.loads(body.decode("utf-8"))
        self.calls.append({"url": url, "headers": headers, "request": request,
                           "timeout": timeout})
        queue = self.script.get(url)
        if not queue:
            raise AssertionError(
                "no scripted outcome left for {} (call {} of this test, method {!r})".format(
                    url, len(self.calls), request.get("method")
                )
            )
        return _materialise(queue.pop(0), url, request)

    def requests_to(self, url):
        return [call["request"] for call in self.calls if call["url"] == url]


def _materialise(outcome, url, request):
    if isinstance(outcome, Boom):
        raise EndpointUnreachable(url, outcome.reason)
    if isinstance(outcome, Rpc):
        payload = {"jsonrpc": "2.0",
                   "id": request.get("id") if outcome.id is None else outcome.id,
                   "result": outcome.result}
        return HttpResponse(outcome.status, json.dumps(payload).encode("utf-8"), url)
    if isinstance(outcome, RpcError):
        payload = {"jsonrpc": "2.0", "id": request.get("id"),
                   "error": {"code": outcome.code, "message": outcome.message}}
        return HttpResponse(outcome.status, json.dumps(payload).encode("utf-8"), url)
    if isinstance(outcome, Json):
        return HttpResponse(outcome.status, json.dumps(outcome.payload).encode("utf-8"), url,
                            outcome.headers)
    if isinstance(outcome, Text):
        return HttpResponse(outcome.status, outcome.body.encode("utf-8"), url, outcome.headers)
    if isinstance(outcome, HttpResponse):
        return outcome
    raise AssertionError("unusable fake outcome: {!r}".format(outcome))


# -- guards ---------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Poison the socket for every test in this directory."""

    def refuse(*args, **kwargs):
        raise AssertionError(
            "a test in tests/transport opened a real connection. Every response shape here comes "
            "from FakeHttpTransport and every real one from the committed recordings; a test that "
            "needs the network is a test that will measure a different chain tomorrow."
        )

    monkeypatch.setattr("urllib.request.urlopen", refuse)


@pytest.fixture
def sleeps():
    """A recording stand-in for ``time.sleep``. Back-off is asserted, never waited for."""
    recorded = []
    return recorded, recorded.append


@pytest.fixture
def recordings():
    return RECORDINGS


@pytest.fixture
def trace_refusals():
    with open(TRACE_REFUSALS, "r", encoding="utf-8") as handle:
        return json.load(handle)
