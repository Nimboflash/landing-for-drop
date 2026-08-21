"""Never echo a credential — not into a log, an error message, or the register.

The dangerous case is not the API key header. It is the archival RPC, where the credential *is
part of the URL*: ``https://eth-mainnet.example.com/v2/<key>``. That URL wants to appear in every
useful diagnostic — the UNREACHABLE detail, the connection error, the evidence of which node
answered — and each of those places is somewhere a register gets committed to a repository.

So the rule here is that a URL is redacted on the way *in* to any record, not filtered on the way
out. Two independent mechanisms, because either alone fails:

1. **Structural.** Strip userinfo, drop the query string wholesale, and replace any path segment
   that looks like a key. This catches credentials whose value we were never told.
2. **By value.** Scrub the actual strings of the configured environment variables out of any text.
   This catches a key echoed back inside a vendor's JSON error body, which no structural rule
   would recognise.

``<redacted>`` is deliberately not a hash or a prefix. A first-four-characters preview is a
convenience that becomes a leak the moment the key space is small.
"""

import os
import re

try:                                     # pragma: no cover - trivial import shim
    from urllib.parse import urlsplit, urlunsplit
except ImportError:                      # pragma: no cover - Python 2 never runs here
    raise

REDACTED = "<redacted>"

#: Environment variables that hold a secret. Read-only: nothing in this package writes them, and
#: nothing outside this module is permitted to read their *values* into a record.
CREDENTIAL_ENV_VARS = ("DUNE_API_KEY", "COINGECKO_API_KEY", "ETH_ARCHIVAL_RPC_URL")

#: A path segment that is long and opaque is assumed to be a key. False positives are harmless —
#: a redacted path segment costs a diagnostic; a leaked one costs a rotation.
_KEYISH_SEGMENT = re.compile(r"^[A-Za-z0-9_\-]{16,}$")


def secret_values(env=None):
    """The credential strings currently configured, longest first.

    Longest first matters: if one variable's value is a substring of another's, scrubbing the
    short one first would leave a recognisable tail of the long one behind.
    """
    env = os.environ if env is None else env
    values = []
    for name in CREDENTIAL_ENV_VARS:
        raw = env.get(name)
        if raw:
            values.append(raw.strip())
            # An RPC URL is itself a secret, but the interesting part is the key inside it. Scrub
            # the whole URL and each of its opaque path segments, so a partial echo is caught too.
            for segment in urlsplit(raw.strip()).path.split("/"):
                if _KEYISH_SEGMENT.match(segment or ""):
                    values.append(segment)
    return tuple(sorted(set(values), key=len, reverse=True))


def scrub(text, env=None):
    """Remove any configured credential value from ``text`` by literal replacement."""
    if text is None:
        return None
    out = str(text)
    for value in secret_values(env):
        if value:
            out = out.replace(value, REDACTED)
    return out


def redact_url(url, env=None):
    """Reduce a URL to something safe to record: scheme, host, and a de-keyed path.

    The query string goes entirely. Vendors put keys there (``?api_key=``), and there is no
    parameter worth keeping in a register that justifies parsing the rest to find out.
    """
    if not url:
        return url
    try:
        parts = urlsplit(str(url))
    except ValueError:                                   # pragma: no cover - defensive
        return REDACTED

    netloc = parts.netloc
    if "@" in netloc:                                    # strip user:password@host
        netloc = REDACTED + "@" + netloc.rsplit("@", 1)[1]

    segments = []
    for segment in parts.path.split("/"):
        segments.append(REDACTED if _KEYISH_SEGMENT.match(segment or "") else segment)
    path = "/".join(segments)

    query = REDACTED if parts.query else ""
    cleaned = urlunsplit((parts.scheme, netloc, path, query, ""))
    return scrub(cleaned, env)


def redact(text, env=None):
    """Redact free text: de-key any URL it contains, *then* scrub credential values.

    The order is load-bearing, and it is the opposite of the obvious one. ``ETH_ARCHIVAL_RPC_URL``
    is a secret whose value is an entire URL, so scrubbing first replaces the whole thing with
    ``<redacted>`` and the message becomes "failed to reach <redacted>" — which is safe, useless,
    and indistinguishable from every other failure. Structural redaction first removes the key from
    inside the URL, leaving ``https://host/v2/<redacted>``: a diagnostic that still names the host.

    Scrubbing afterwards is what keeps that safe rather than merely tidy. It catches a loose key
    echoed in a vendor's error body, and it catches the case where structural redaction found
    nothing to strip — a short key in a path, say — because the untouched URL then still matches
    the configured value literally and is replaced wholesale.
    """
    if text is None:
        return None
    out = re.sub(r"https?://\S+", lambda m: redact_url(m.group(0), env), str(text))
    return scrub(out, env)
