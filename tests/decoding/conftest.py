"""Fixtures for the ingest suite. Nothing here opens a socket.

Two kinds of input.

**Hand-built logs.** :func:`log` assembles a log dict in the shape a node returns, so a test can
state exactly one deviation from a well-formed log and assert on the refusal it earns. Built by a
helper rather than copied between tests, because a test that hand-writes 64 hex digits is a test
whose failure is as likely to be a typo as a defect.

**The committed snapshot.** The tracer bullet's real bytes, replayed. Anything asserting on real
chain data belongs in ``tests/hand_computed/test_ingest.py``; what is here uses the snapshot only
where a refusal needs a real receipt to deviate from.
"""

import json
import os
import urllib.request

import pytest

from transport import REPLAY_ONLY, RecordingCache, RpcClient
from transport.http import HttpResponse, HttpTransport

HERE = os.path.dirname(os.path.abspath(__file__))
RECORDINGS = os.path.join(os.path.dirname(HERE), "fixtures", "transport", "recordings")

TX = "0xb8681e7a43edca5fe12d5fc0183b901d73255f86e4188715e3d556ba57f269e3"
WALLET = "0xe15b3d62c2bce51f2a8a8d53d76c36b4fab8721c"
ROUTER = "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
BLOCK = 16308001


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """A test here that reached the chain would measure a different chain tomorrow."""

    def refuse(*args, **kwargs):
        raise AssertionError("a test in tests/ingest opened a real connection")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture
def client():
    """The committed snapshot, replay-only. An unrecorded call raises rather than dialling out."""
    return RpcClient(cache=RecordingCache(RECORDINGS), mode=REPLAY_ONLY)


def word(value):
    """A 32-byte ABI word holding a non-negative int."""
    return "0x" + format(value, "064x")


def address_word(address):
    """A 32-byte ABI word holding a 20-byte address, zero-padded on the left."""
    return "0x" + address[2:].rjust(64, "0").lower()


def log(topics, data="0x" + "0" * 64, address=WETH, index=0, **extra):
    """One log dict in the shape ``eth_getTransactionReceipt`` returns."""
    entry = {
        "address": address,
        "topics": list(topics),
        "data": data,
        "logIndex": hex(index),
        "blockNumber": hex(BLOCK),
        "transactionHash": TX,
    }
    entry.update(extra)
    return entry


class ScriptedTransport(HttpTransport):
    """Answers every POST with one scripted JSON-RPC envelope, whatever was asked.

    Enough for the ``eth_call`` refusals: what is under test is how a *returndata shape* is read,
    not which endpoint produced it. Subclasses the real transport so the honest User-Agent rule
    still applies — a hand-rolled stub would opt out of the one rule that seam exists to hold.
    """

    def __init__(self, envelope, status=200,
                 user_agent="phase0-test/1.0 (contact: product@saraf.app)"):
        super(ScriptedTransport, self).__init__(user_agent=user_agent)
        self.envelope = envelope
        self.status = status
        self.requests = []

    def _perform(self, url, headers, body, timeout):
        request = json.loads(body.decode("utf-8"))
        self.requests.append(request)
        payload = dict(self.envelope)
        payload.setdefault("jsonrpc", "2.0")
        payload["id"] = request.get("id")
        return HttpResponse(self.status, json.dumps(payload).encode("utf-8"), url)


@pytest.fixture
def scripted():
    """``scripted(result) -> RpcClient`` answering every call with that ``result``."""

    def build(result=None, error=None, status=200):
        envelope = {"error": error} if error is not None else {"result": result}
        return RpcClient(
            endpoints=["https://scripted.invalid"],
            transport=ScriptedTransport(envelope, status=status),
            attempts_per_endpoint=1,
            sleep=lambda seconds: None,
        )

    return build
