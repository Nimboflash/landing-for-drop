"""Fixtures for the ticket-03 provisioning suite.

Two jobs, and the second one matters more than it looks.

**Make ``tools`` importable.** ``pyproject`` sets ``pythonpath = ["src"]``, which is right — the
pipeline lives under ``src/`` and nothing else should be on the path by default. ``tools/`` is
deliberately outside that, so this suite puts the repository root on ``sys.path`` itself. It
*appends* rather than inserting at position 0: ``tests/test_shared_purity.py`` records what an
insert at 0 cost last time — it silently overrode PYTHONPATH for every test sharing the process and
made a whole mutation run report false negatives. An import hack that quietly redirects imports is
indistinguishable from a passing suite.

**Guarantee the tests are honest about credentials.** ``clean_env`` is autouse: every test in this
directory runs with the three credential variables removed from the *fixture* environment it is
given, and no test reads ``os.environ``. The suite therefore proves what the ticket asks it to
prove — that with nothing configured the probes report ABSENT, the register says PENDING, and the
CLI exits non-zero naming what is missing — rather than proving it on the maintainer's laptop and
failing in CI, or the reverse.

No test in this directory opens a socket. Every probe is driven through a fake transport.
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from tools.provisioning.redaction import CREDENTIAL_ENV_VARS  # noqa: E402
from tools.provisioning.transport import Response, Transport, TransportError  # noqa: E402


# -- fake transports ------------------------------------------------------------
#
# Subclassing the real :class:`Transport` rather than duck-typing one is the whole point.
# ``request()`` is a template method that checks the prohibition before delegating to
# ``_perform()``, so a fake refuses a coin-level aggregator URL exactly as the live transport does.
# A hand-rolled stub would quietly opt out of the rule the suite is supposed to be proving.


class Json(object):
    """A JSON answer."""

    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status


class Raw(object):
    """A bytes answer — the Binance archive is a zip file, not JSON."""

    def __init__(self, body, status=200):
        self.body = body
        self.status = status


class Boom(object):
    """The endpoint did not answer at all: DNS, TLS, reset, timeout."""

    def __init__(self, reason="connection reset by peer"):
        self.reason = reason


class FakeTransport(Transport):
    """Routes a request to a scripted outcome.

    ``routes`` is a sequence of ``(match, outcome)``. ``match`` is either a substring of the URL or
    a callable ``(url, body) -> bool`` — the JSON-RPC probe needs the second form, because all four
    of its capabilities are POSTed to the same URL and only the body distinguishes them.
    """

    def __init__(self, routes=(), default=None, override=None):
        super(FakeTransport, self).__init__(override=override)
        self.routes = list(routes)
        self.default = default
        self.calls = []

    def _perform(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        for match, outcome in self.routes:
            hit = match(url, body) if callable(match) else match in url
            if hit:
                return _materialise(outcome, url)
        if self.default is not None:
            return _materialise(self.default, url)
        raise AssertionError(
            "no fake route for {} {} — the test has not said what this endpoint does".format(
                method, url
            )
        )

    def urls(self):
        return [call["url"] for call in self.calls]


def _materialise(outcome, url):
    if callable(outcome):
        outcome = outcome(url)
    if isinstance(outcome, Boom):
        raise TransportError(url, outcome.reason)
    if isinstance(outcome, Raw):
        return Response(outcome.status, outcome.body, url)
    if isinstance(outcome, Json):
        return Response(outcome.status, json.dumps(outcome.payload).encode("utf-8"), url)
    if isinstance(outcome, Response):
        return outcome
    raise AssertionError("unusable fake outcome: {!r}".format(outcome))


def rpc_method(name):
    """Match a JSON-RPC request by its ``method``."""

    def match(url, body):
        if not body:
            return False
        try:
            return json.loads(body.decode("utf-8")).get("method") == name
        except (ValueError, AttributeError):
            return False

    return match


@pytest.fixture
def clean_env():
    """An environment with no credentials in it. The default state of the world."""
    return {}


@pytest.fixture(autouse=True)
def no_ambient_credentials(monkeypatch):
    """Remove real credentials from the process for the duration of every test.

    Belt and braces behind ``clean_env``: if a probe or the CLI ever falls back to
    ``os.environ`` — which would be a defect — it must not accidentally find a working key and
    turn a red test green by contacting a vendor.
    """
    for name in CREDENTIAL_ENV_VARS + ("DUNE_QUERY_ID", "COINGECKO_DEAD_POOL_CANDIDATES",
                                       "ETH_ARCHIVAL_PROBE_TX"):
        monkeypatch.delenv(name, raising=False)
