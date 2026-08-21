"""A client over Hyperliquid's two bases, whose default mode cannot reach the network.

The two bases, and what was measured against them
--------------------------------------------------

::

    HL_API_BASE    https://api.hyperliquid.xyz          POST /info, no key
    HL_STATS_BASE  https://stats-data.hyperliquid.xyz   GET, no key

    {"type":"spotMeta"}                484 tokens, 324 spot pairs
    {"type":"meta"}                    232 perp markets
    {"type":"userFills","user":ADDR}   up to 2000 records, no cursor
    {"type":"userFillsByTime",...}     millisecond bounds
    GET /Mainnet/leaderboard           41,456 wallets, 34,228,362 bytes

Those counts are what the committed recordings hold, not a standing fact about the venue: the
universes grow as markets are deployed and the leaderboard is a running competition. That is the
whole reason the recordings exist.

Neither base needs a credential, which removes the whole class of problem
``tools.provisioning.redaction`` exists for — there is no key in a URL here to leak. The transport
is still ``tools.provisioning.transport``'s, unchanged, so the §5 prohibition on coin-level
aggregator price endpoints is enforced on this client's calls too. That is not decoration: a client
that could reach ``api.coingecko.com`` because it happened to be written in a different package
would be a second way past a refusal the instrument only has one of.

Replay is the default, and it is not a flag
--------------------------------------------

``userFills`` returns "the last 2000 fills" and the leaderboard is a running competition, so the
same request tomorrow is different data and a number taken from a live call is reproducible by
nobody. **A client constructed the ordinary way holds no transport and physically cannot open a
connection** — the opt-in is supplying one, not setting a boolean, because a boolean defaults and a
constructor argument does not.

Live calls are observable in two ways that do not depend on anyone remembering to look:
:attr:`HyperliquidClient.mode` is ``"live"`` for the client's whole life, and every call — replayed
or live — appends a :class:`Call` to :attr:`HyperliquidClient.calls` recording which mode served it,
how many attempts it took and how long it waited. :meth:`HyperliquidClient.assert_no_live_calls`
turns that into a refusal a test can make.

The back-off, and what "honest" means about it
-----------------------------------------------

Retries happen on exactly two conditions: the endpoint did not answer (:class:`TransportError`), or
it answered with one of :data:`RETRY_STATUSES` — 429 and the five-hundreds, which mean "ask again".
Every other status is an *answer*, including every other 4xx, and retrying an answer is how a client
turns one vendor refusal into five. Waits are :data:`BACKOFF_SECONDS`, in whole seconds, capped, and
a ``Retry-After`` header is honoured when it is an integer no larger than :data:`MAX_RETRY_AFTER`.

What the back-off does **not** do, stated rather than implied: it holds no rate budget. Hyperliquid
publishes a weight-per-minute limit on ``/info`` and this client counts nothing against it, so two
processes sharing a recording directory can between them earn a 429 that neither one's back-off
predicted. The back-off reacts; it does not plan. A capture run that needs to plan should sleep
between calls itself, and :mod:`tools.hyperliquid.capture` does.

What this module does not do
-----------------------------

It does not interpret. Every method returns the parsed JSON verbatim, exactly as recorded, with no
field renamed, dropped, coerced or reordered. Interpretation is :mod:`tools.hyperliquid.decode`'s,
and the separation is load-bearing: a client that "helpfully" turned ``px`` into a float would have
destroyed the numbers before the decimal policy ever saw them.
"""

import time as _time
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from tools.provisioning.transport import Response, Transport, TransportError  # noqa: F401

from .provenance import require_real_address
from .recording import Recording, RecordingCache, RequestSpec, digest_bytes

HL_API_BASE = "https://api.hyperliquid.xyz"
HL_STATS_BASE = "https://stats-data.hyperliquid.xyz"

INFO_URL = HL_API_BASE + "/info"
LEADERBOARD_URL = HL_STATS_BASE + "/Mainnet/leaderboard"

#: Sent on every request. Honest and identifying: it names the software and what it is doing, and
#: it does not claim to be a browser. A probe on another vendor once sent a fabricated browser
#: User-Agent and had its signature permanently blocked by that vendor's edge; the cost of being
#: recognisable is that a vendor can throttle you, and the cost of not being is that a vendor can
#: ban you without ever being able to tell you why.
USER_AGENT = (
    "phase0-wallet-research/0.1 "
    "(Phase 0 pre-registration engineering diagnostic; read-only; not a browser)"
)

#: Whole seconds. Integers on purpose — this package's house rule routes decimal arithmetic through
#: ``contracts.numeric``, and a float here would be a float in a package that has none.
BACKOFF_SECONDS = (1, 2, 4, 8, 16)

#: Statuses that mean "ask again". Everything else the endpoint returns is an answer.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

#: The longest ``Retry-After`` this client will honour. A larger one is treated as a refusal to
#: serve rather than an instruction to sleep: a capture that blocks for an hour is a capture nobody
#: is watching when it finally runs.
MAX_RETRY_AFTER = 120

MAX_ATTEMPTS = len(BACKOFF_SECONDS) + 1


class VendorRefused(Exception):
    """The endpoint answered and said no. Carries the vendor's own words.

    Distinct from :class:`~tools.provisioning.transport.TransportError`, which means the endpoint
    did not answer at all. Collapsing the two would lose the only part of a failure that says who
    has to fix it.
    """

    def __init__(self, spec, status, body):
        self.spec = spec
        self.status = status
        self.body = body
        super(VendorRefused, self).__init__(
            "{} answered {} and the answer was a refusal: {}".format(
                spec.describe(), status, body[:400] if body else "(empty body)"
            )
        )


@dataclass(frozen=True)
class Call:
    """One request this client served, and how.

    Appended for replayed calls as well as live ones. A log that only recorded the live ones would
    answer "did this touch the network?" and not "what did this run read?", and the second question
    is the one a reader of a number asks.
    """

    mode: str
    slug: str
    key: str
    attempts: int
    waited_seconds: int
    status: int

    @property
    def was_live(self):
        return self.mode == "live"


class HyperliquidClient(object):
    """Replay by default; live only when handed a transport.

    :param cache: a :class:`~tools.hyperliquid.recording.RecordingCache`.
    :param transport: a :class:`~tools.provisioning.transport.Transport`. **Supplying one is the
        opt-in to live network access**, and it is a constructor argument rather than a flag because
        a flag has a default and this must not have one.
    :param sleeper: ``callable(seconds)``, defaulting to :func:`time.sleep`. Injected so the
        back-off can be exercised without a suite that takes half a minute to run.
    :param user_agent: sent verbatim. Defaults to :data:`USER_AGENT`.
    """

    def __init__(self, cache, transport=None, sleeper=None, user_agent=USER_AGENT):
        if not isinstance(cache, RecordingCache):
            raise TypeError(
                "cache must be a RecordingCache, got {}. There is no such thing as a client "
                "without one: replay is the default mode and a client with nowhere to replay from "
                "would have to fall back to the network, which is exactly the fallback this "
                "package refuses to have.".format(type(cache).__name__)
            )
        if not isinstance(user_agent, str) or not user_agent.strip():
            raise ValueError(
                "user_agent must be a non-empty identifying string. An anonymous client is one a "
                "vendor can only respond to by blocking it."
            )
        self.cache = cache
        self.transport = transport
        self.user_agent = user_agent
        self._sleep = sleeper if sleeper is not None else _time.sleep
        self._calls = []

    # -- observability ---------------------------------------------------------

    @property
    def mode(self):
        """``"replay"`` or ``"live"``. Fixed at construction; there is no way to switch."""
        return "replay" if self.transport is None else "live"

    @property
    def calls(self):
        """Every call this client served, in order."""
        return tuple(self._calls)

    @property
    def live_calls(self):
        return tuple(call for call in self._calls if call.was_live)

    def assert_no_live_calls(self):
        """Raise if this client has touched the network. Returns the replayed calls otherwise."""
        live = self.live_calls
        if live:
            raise AssertionError(
                "this client made {} live call(s): {}. A run whose numbers came off the wire is "
                "reproducible by nobody — Hyperliquid's fills window and leaderboard both "
                "move.".format(len(live), ", ".join(call.slug for call in live))
            )
        return self.calls

    # -- the four calls --------------------------------------------------------

    def spot_meta(self):
        """``{"type":"spotMeta"}``, parsed verbatim: ``{"tokens": [...], "universe": [...]}``.

        The universe of spot markets. Note that ``index`` on a token and on a universe entry is
        **not** its position in the list — measured on the committed recording, both differ — so a
        consumer must key by ``index`` and not by enumeration order. :mod:`tools.hyperliquid.decode`
        does.
        """
        return self._info({"type": "spotMeta"}, "spot-meta")

    def meta(self):
        """``{"type":"meta"}``, parsed verbatim: the perpetual markets.

        Fetched not to decode but to **refuse**: a perp fill has no lot to hold, so it must be told
        apart from a spot fill before anything runs FIFO over it, and the only way to tell is to
        know both universes. See :func:`tools.hyperliquid.decode.decode_fills`.
        """
        return self._info({"type": "meta"}, "meta")

    def user_fills(self, address):
        """``{"type":"userFills","user":ADDR}``, parsed verbatim: a list of fill objects.

        Bounded by the venue at 2000 records with no cursor, so this is "the most recent fills" and
        not "the fills" — a wallet at the cap has an unknown amount of history the call cannot
        reach. :meth:`user_fills_by_time` is the addressable one and is what the committed
        recordings use.
        """
        user = require_real_address(address, "user_fills(address)")
        return self._info({"type": "userFills", "user": user}, "user-fills")

    def user_fills_by_time(self, address, start_ms, end_ms):
        """``{"type":"userFillsByTime",...}``, parsed verbatim. Bounds are **milliseconds**.

        Milliseconds, not seconds: the seam's ``timestamp`` is UTC seconds everywhere else in this
        repository and passing one here silently asks for a window in 1970. Refused rather than
        guessed at — a bound below :data:`_MS_FLOOR` is far more likely to be seconds than to be a
        genuine request for the Unix epoch.
        """
        user = require_real_address(address, "user_fills_by_time(address)")
        for name, value in (("start_ms", start_ms), ("end_ms", end_ms)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    "{} must be an int of UTC milliseconds, got {}".format(
                        name, type(value).__name__
                    )
                )
            if value < _MS_FLOOR:
                raise ValueError(
                    "{} is {}, which is below {} — that is almost certainly UTC *seconds*. This "
                    "endpoint takes milliseconds, and the rest of this repository carries UTC "
                    "seconds (contracts: 'timestamps -> UTC seconds, always paired with a block "
                    "number'), so the mistake is one keystroke away and silently returns a window "
                    "in 1970 rather than an error.".format(name, value, _MS_FLOOR)
                )
        if end_ms < start_ms:
            raise ValueError(
                "user_fills_by_time window ends before it starts: {} .. {}".format(
                    start_ms, end_ms
                )
            )
        return self._info(
            {"type": "userFillsByTime", "user": user, "startTime": start_ms, "endTime": end_ms},
            "user-fills-by-time",
        )

    def leaderboard(self):
        """``GET /Mainnet/leaderboard``, parsed verbatim: ``{"leaderboardRows": [...]}``.

        **A row's ``windowPerformances`` is a vendor-computed return, and §3 forbids a vendor number
        from being the metric.** The whole design rebuilds the metric from raw trades, so this
        endpoint has exactly one legitimate use: deciding *which wallets to pull fills for*. Nothing
        it returns may be an input to anything scored, compared against anything scored, or used to
        weight anything scored. The recording committed here is a declared subset of the full
        capture for that reason among others — a sample of a sample is still a sample, and the file
        says so in its ``reduction`` field.

        The committed recording's rows are byte-for-byte what the venue sent; what was dropped is
        stated. See :mod:`tools.hyperliquid.recording`.
        """
        spec = RequestSpec("GET", LEADERBOARD_URL)
        return self._fetch(spec, "leaderboard", "python -m tools.hyperliquid.capture leaderboard")

    # -- plumbing --------------------------------------------------------------

    def _info(self, body, slug):
        spec = RequestSpec("POST", INFO_URL, body)
        return self._fetch(spec, slug, _capture_command(body))

    def _fetch(self, spec, slug, how_to_capture):
        if self.transport is None:
            recording = self.cache.require(spec, how_to_capture)
            self._calls.append(
                Call("replay", slug, spec.key(), 0, 0, recording.status)
            )
            if not 200 <= recording.status < 300:
                raise VendorRefused(spec, recording.status, _brief(recording.payload))
            return recording.payload
        recording, attempts, waited = self._perform(spec)
        self._calls.append(
            Call("live", slug, spec.key(), attempts, waited, recording.status)
        )
        if not 200 <= recording.status < 300:
            raise VendorRefused(spec, recording.status, _brief(recording.payload))
        return recording.payload

    def _perform(self, spec):
        """Call the endpoint with back-off. Returns ``(recording, attempts, waited_seconds)``.

        The recording is built but **not written**: writing is
        :meth:`tools.hyperliquid.recording.RecordingCache.put`'s, and keeping the decision to commit
        bytes out of the fetch path is what lets :mod:`tools.hyperliquid.capture` reduce a 34 MB
        leaderboard before it lands in the repository.
        """
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        waited = 0
        last = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                if spec.method == "GET":
                    response = self.transport.get(spec.url, headers=headers)
                else:
                    response = self.transport.post_json(spec.url, spec.body, headers=headers)
                last = response
                if response.status not in RETRY_STATUSES:
                    return self._record(spec, response), attempt, waited
            except TransportError as error:
                last = error
            if attempt == MAX_ATTEMPTS:
                break
            pause = _pause_for(last, BACKOFF_SECONDS[attempt - 1])
            waited += pause
            self._sleep(pause)
        if isinstance(last, TransportError):
            raise last
        return self._record(spec, last), MAX_ATTEMPTS, waited

    def _record(self, spec, response):
        import json as _json

        body = response.body
        try:
            payload = _json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = response.text()
        return Recording(
            spec=spec,
            status=response.status,
            payload=payload,
            bytes_sha256=digest_bytes(body),
            bytes_len=len(body),
            captured_at=int(_time.time() * 1000),
            captured_by=self.user_agent,
            reduction=None,
        )


#: Below this, a "millisecond" bound is far more likely to be seconds. 10^12 ms is 2001-09-09;
#: 10^12 s is the year 33658, so nothing that is genuinely milliseconds and genuinely about
#: Hyperliquid (mainnet launched in 2023) falls below it.
_MS_FLOOR = 1_000_000_000_000


def _pause_for(last, default):
    """The wait before the next attempt: ``Retry-After`` when the vendor named one, else the schedule.

    Only whole-second ``Retry-After`` values are honoured, and only up to :data:`MAX_RETRY_AFTER`.
    The HTTP-date form is not parsed — it would need a clock this package otherwise does not read,
    and mis-parsing it would produce a wait derived from a clock skew.
    """
    headers = getattr(last, "headers", None) or {}
    for name, value in headers.items():
        if str(name).lower() != "retry-after":
            continue
        try:
            seconds = int(str(value).strip())
        except ValueError:
            return default
        if 0 < seconds <= MAX_RETRY_AFTER:
            return seconds
        return default
    return default


def _brief(payload):
    import json as _json

    if isinstance(payload, str):
        return payload
    try:
        return _json.dumps(payload)[:400]
    except (TypeError, ValueError):                            # pragma: no cover - defensive
        return repr(payload)[:400]


def _capture_command(body):
    kind = body.get("type")
    if kind == "spotMeta":
        return "python -m tools.hyperliquid.capture spot-meta"
    if kind == "meta":
        return "python -m tools.hyperliquid.capture meta"
    if kind == "userFills":
        return "python -m tools.hyperliquid.capture user-fills {}".format(body.get("user"))
    if kind == "userFillsByTime":
        return "python -m tools.hyperliquid.capture user-fills-by-time {} {} {}".format(
            body.get("user"), body.get("startTime"), body.get("endTime")
        )
    return "python -m tools.hyperliquid.capture --help"       # pragma: no cover - defensive


def replay_client(directory, **kwargs):
    """A client that cannot reach the network, over the recordings in ``directory``."""
    return HyperliquidClient(RecordingCache(directory), **kwargs)


def default_recording_directory():
    """The recordings committed with this package."""
    import os

    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "recording")
