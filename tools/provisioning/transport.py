"""HTTP as a seam, so the five outcomes can be exercised without a network or a credential.

Two rules shape this module.

**The prohibition is enforced in the base class, not in the real transport.** ``request()`` is a
template method: it checks the URL against :mod:`tools.provisioning.prohibited` and only then
delegates to ``_perform()``. A fake transport in a test therefore refuses a prohibited URL exactly
as the live one does — which is the difference between a rule the suite proves and a rule the
suite would happily let you delete.

**Network failure is a value, not a traceback.** Anything that means "the endpoint did not answer"
becomes :class:`TransportError`, and the probe turns it into ``UNREACHABLE``. Anything that means
"the endpoint answered and said no" comes back as a :class:`Response` with a non-2xx status, and
the probe turns it into ``REFUSED`` carrying the vendor's own words. Collapsing the two would lose
the only part of a failure that tells you who has to fix it.

Every URL recorded or raised from here is redacted first. The archival RPC credential *is* a URL.
"""

import json

from .prohibited import assert_not_prohibited
from .redaction import redact, redact_url

DEFAULT_TIMEOUT = 30


class TransportError(Exception):
    """The endpoint did not answer. DNS, TLS, connection reset, timeout.

    Never carries an un-redacted URL: the RPC endpoint's own hostname-plus-key is the credential.
    """

    def __init__(self, url, reason):
        self.url = redact_url(url)
        self.reason = redact(str(reason))
        super(TransportError, self).__init__("{} did not answer: {}".format(self.url, self.reason))


class Response(object):
    """What came back. ``body`` is bytes, because one of the four sources ships a zip file."""

    __slots__ = ("status", "body", "url", "headers")

    def __init__(self, status, body=b"", url="", headers=None):
        self.status = int(status)
        self.body = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.url = redact_url(url)
        self.headers = dict(headers or {})

    @property
    def ok(self):
        return 200 <= self.status < 300

    def text(self, limit=None):
        """Decoded body, redacted. A vendor error body can echo the key that was sent."""
        decoded = self.body.decode("utf-8", errors="replace")
        if limit is not None:
            decoded = decoded[:limit]
        return redact(decoded)

    def json(self):
        """Parsed body, or ``None`` if it is not JSON.

        Returns ``None`` rather than raising: "the endpoint answered with something that is not
        JSON" is an INSUFFICIENT-shaped fact about the endpoint, not a crash in the probe.
        """
        try:
            return json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None


class Transport(object):
    """Base transport. Enforces the prohibition; subclasses implement ``_perform``."""

    def __init__(self, override=None):
        #: An explicit :class:`~tools.provisioning.prohibited.SourceOverride`, or ``None``.
        self.override = override

    def request(self, method, url, headers=None, body=None, timeout=DEFAULT_TIMEOUT):
        assert_not_prohibited(url, self.override)
        return self._perform(method, url, headers or {}, body, timeout)

    def _perform(self, method, url, headers, body, timeout):  # pragma: no cover - abstract
        raise NotImplementedError

    # -- convenience ----------------------------------------------------------

    def get(self, url, headers=None, timeout=DEFAULT_TIMEOUT):
        return self.request("GET", url, headers=headers, timeout=timeout)

    def post_json(self, url, payload, headers=None, timeout=DEFAULT_TIMEOUT):
        merged = {"Content-Type": "application/json", "Accept": "application/json"}
        merged.update(headers or {})
        encoded = json.dumps(payload).encode("utf-8")
        return self.request("POST", url, headers=merged, body=encoded, timeout=timeout)


class UrllibTransport(Transport):
    """The live transport. Standard library only — this package adds no dependency to the freeze."""

    def _perform(self, method, url, headers, body, timeout):
        import urllib.error
        import urllib.request

        request = urllib.request.Request(url=url, data=body, method=method)
        for key, value in headers.items():
            request.add_header(key, value)
        try:
            handle = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            # An HTTP error status is an *answer*. "401 archive requests require a personal token"
            # is the single most valuable thing this whole package can produce, and urllib raises
            # it. Turning it back into a Response is what keeps REFUSED distinct from UNREACHABLE.
            try:
                payload = exc.read()
            except Exception:                                  # pragma: no cover - defensive
                payload = b""
            return Response(exc.code, payload, url, dict(getattr(exc, "headers", {}) or {}))
        except Exception as exc:                               # URLError, socket.timeout, ssl, ...
            raise TransportError(url, exc)

        with handle:
            return Response(
                getattr(handle, "status", handle.getcode()),
                handle.read(),
                url,
                dict(handle.headers.items()),
            )
