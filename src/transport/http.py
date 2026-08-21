"""HTTP as a seam, so every response shape can be exercised without a socket.

Two rules shape this module, and both are enforced in the **base class** rather than in the live
transport.

**The honest User-Agent is enforced where the fake inherits it.** ``post_json()`` is a template
method: it checks the agent against :func:`assert_honest_user_agent` and only then delegates to
``_perform()``. A fake transport in a test therefore refuses a browser-shaped agent exactly as the
live one does, which is the difference between a rule the suite proves and a rule the suite would
happily let someone delete. The cost of getting this wrong is already paid: a fake agent got the
signature permanently banned by Cloudflare at eth.drpc.org.

**"The endpoint did not answer" and "the endpoint answered and said no" stay different.** Anything
meaning the former raises :class:`EndpointUnreachable`; the latter comes back as an
:class:`HttpResponse` with a non-2xx status and the body intact. They have different owners — one
is a network, the other is a vendor policy someone must be shown — and collapsing them into one
failure loses the only part that says who has to fix it.

What this module does not do
----------------------------

It knows nothing about JSON-RPC, blocks, receipts, logs, or Ethereum. It moves bytes and parses
JSON. Anything that gives those bytes meaning belongs to the lane that consumes them, never here.
"""

import json

from .endpoints import USER_AGENT

DEFAULT_TIMEOUT = 30

#: Substrings that make a User-Agent browser-shaped. Matched case-insensitively.
#:
#: This is not a heuristic about politeness. Cloudflare fingerprints an agent claiming to be a
#: browser while behaving like a script, and the ban that follows is on the signature rather than
#: on a session — it survives a restart, a new process, and a different IP, and it cannot be lifted
#: from here.
BROWSER_AGENT_FRAGMENTS = (
    "mozilla", "chrome", "safari", "applewebkit", "gecko", "edg/", "opera", "trident",
)


class DishonestUserAgent(ValueError):
    """A browser-shaped User-Agent was assembled. A defect in the caller, refused before sending.

    Deliberately an exception and not a status: there is no measurement here to report. Sending it
    would be the mistake, and the mistake is not undoable.
    """


def assert_honest_user_agent(agent):
    """Refuse an absent or browser-shaped agent, naming what it costs.

    Guarantees only that the agent is a non-empty string containing none of
    :data:`BROWSER_AGENT_FRAGMENTS`. It does **not** guarantee the agent identifies a real contact,
    and it cannot: an agent that merely looks honest still gets rate-limited on its merits.
    """
    if not isinstance(agent, str) or not agent.strip():
        raise DishonestUserAgent(
            "no User-Agent was set. A public endpoint is entitled to know who is calling; an "
            "anonymous script is the first thing an operator blocks. Pass "
            "user_agent={!r}.".format(USER_AGENT)
        )
    lowered = agent.lower()
    for fragment in BROWSER_AGENT_FRAGMENTS:
        if fragment in lowered:
            raise DishonestUserAgent(
                "User-Agent {!r} claims to be a browser (matched {!r}). This is refused before "
                "anything is sent: an earlier probe did it and Cloudflare permanently banned the "
                "signature at eth.drpc.org — a ban on the signature, not on a session, which "
                "cannot be undone from here. Identify honestly instead, e.g. {!r}.".format(
                    agent, fragment, USER_AGENT
                )
            )
    return agent


class EndpointUnreachable(Exception):
    """The endpoint did not answer at all: DNS, TLS, connection reset, timeout.

    Distinct from a non-2xx answer, which is an answer. Carries the URL because failover across
    several endpoints is meaningless evidence unless each reason names the endpoint it came from.
    """

    def __init__(self, url, reason):
        self.url = url
        self.reason = str(reason)
        super(EndpointUnreachable, self).__init__(
            "{} did not answer: {}".format(self.url, self.reason)
        )


class FloatInChainResponse(TypeError):
    """A JSON number with a fractional part arrived from a node.

    Ethereum JSON-RPC encodes every quantity as a hex string precisely so this cannot happen. One
    appearing means either the endpoint is not what it claims to be or something rewrote the body
    on the way. Refused here rather than downstream, because by the time a float reaches a
    comparison the precision it lost is unrecoverable and the value still looks reasonable.
    """


def _refuse_float(literal):
    raise FloatInChainResponse(
        "a JSON float ({}) arrived in a chain response. Ethereum encodes quantities as hex "
        "strings; a float here has already lost precision before this package saw it, and "
        "accepting it would launder the loss into every number derived from it.".format(literal)
    )


def _refuse_constant(name):
    raise FloatInChainResponse(
        "a JSON non-finite constant ({}) arrived in a chain response. Nothing in the Ethereum "
        "JSON-RPC schema can produce one.".format(name)
    )


def parse_json_bytes(body):
    """Parse a response body with floats and non-finite constants refused on sight.

    Guarantees the returned structure contains no ``float``. Guarantees nothing about the
    structure otherwise — a well-formed JSON document that is not a JSON-RPC envelope parses
    happily here and is rejected one layer up.
    """
    text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
    return json.loads(text, parse_float=_refuse_float, parse_constant=_refuse_constant)


class HttpResponse:
    """What came back: a status, the body as bytes, and the headers.

    The body is kept as bytes and parsed on demand, so a refusal that is not JSON — an HTML error
    page from a proxy, say — is still quotable verbatim rather than lost to a parse error.
    """

    __slots__ = ("status", "body", "url", "headers")

    def __init__(self, status, body=b"", url="", headers=None):
        self.status = int(status)
        self.body = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.url = url
        #: Header lookup is case-insensitive in HTTP; this dict is not. Use :meth:`header`.
        self.headers = dict(headers or {})

    @property
    def ok(self):
        return 200 <= self.status < 300

    def header(self, name, default=None):
        """Case-insensitive header lookup. ``Retry-After`` arrives spelled several ways."""
        wanted = name.lower()
        for key, value in self.headers.items():
            if str(key).lower() == wanted:
                return value
        return default

    def text(self, limit=None):
        """The body decoded for quoting. Never re-encoded, never reformatted.

        Undecodable bytes become replacement characters rather than raising: a refusal that cannot
        be decoded is still evidence, and losing it to a ``UnicodeDecodeError`` would hide the
        message this package exists to preserve.
        """
        decoded = self.body.decode("utf-8", errors="replace")
        if limit is not None:
            decoded = decoded[:limit]
        return decoded

    def json(self):
        """Parsed body, or ``None`` when it is not JSON.

        ``None`` rather than an exception: "the endpoint answered with something that is not JSON"
        is a fact about the endpoint that the caller must be able to report, not a crash in the
        client. A JSON float still raises — see :class:`FloatInChainResponse`.
        """
        try:
            return parse_json_bytes(self.body)
        except (ValueError, UnicodeDecodeError):
            return None


class HttpTransport:
    """Base transport. Enforces the honest agent; subclasses implement ``_perform``.

    Subclassing this — rather than duck-typing a stand-in — is what makes a test fake obey the
    User-Agent rule. A hand-rolled stub would quietly opt out of the one rule this seam exists to
    hold.
    """

    def __init__(self, user_agent=USER_AGENT):
        self.user_agent = assert_honest_user_agent(user_agent)

    def post_json(self, url, payload, headers=None, timeout=DEFAULT_TIMEOUT):
        """POST a JSON document. Returns an :class:`HttpResponse` for any answer at all.

        Raises :class:`EndpointUnreachable` when there was no answer, and
        :class:`DishonestUserAgent` before sending anything when the agent is browser-shaped.
        """
        merged = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": assert_honest_user_agent(self.user_agent),
        }
        merged.update(headers or {})
        assert_honest_user_agent(merged["User-Agent"])
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
        return self._perform(url, merged, body, timeout)

    def _perform(self, url, headers, body, timeout):  # pragma: no cover - abstract
        raise NotImplementedError


class UrllibHttpTransport(HttpTransport):
    """The live transport. Standard library only — this package adds no dependency to the freeze."""

    def _perform(self, url, headers, body, timeout):
        import urllib.error
        import urllib.request

        request = urllib.request.Request(url=url, data=body, method="POST")
        for key, value in headers.items():
            request.add_header(key, value)
        try:
            handle = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            # An HTTP error status is an *answer*, and for this package it is often the most
            # valuable answer there is: "401 archive requests require a personal token" is exactly
            # the evidence a vendor conversation needs. urllib raises it; turning it back into a
            # response is what keeps a refusal distinct from an outage.
            try:
                payload = exc.read()
            except Exception:                                  # pragma: no cover - defensive
                payload = b""
            return HttpResponse(exc.code, payload, url, dict(getattr(exc, "headers", {}) or {}))
        except Exception as exc:                               # URLError, timeout, ssl, ...
            raise EndpointUnreachable(url, exc)

        with handle:
            return HttpResponse(
                getattr(handle, "status", handle.getcode()),
                handle.read(),
                url,
                dict(handle.headers.items()),
            )
