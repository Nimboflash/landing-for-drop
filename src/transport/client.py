"""The JSON-RPC client: failover, honest back-off, replay, and refusals worth quoting.

This module returns what a node returned and interprets none of it. It knows the *names* of five
``eth_*`` methods and the *shape* of their parameters, and nothing about what comes back beyond
"the envelope had a ``result`` member". A receipt is a dict here. A log is a dict here. Which log
is a transfer, which leg is a swap, which address is a pool — none of that may ever be decided in
this package, because both the builder lane and the validator lane import it and a shared
interpretation is a shared bug that the validation gate cannot see.

Three behaviours are worth reading before use.

**Failover is across endpoints, back-off is within one.** A ``429`` means "you, slow down" and is
answered by waiting on that endpoint; anything else — no answer, a non-2xx status, a JSON-RPC
error, a malformed envelope — moves to the next endpoint immediately. Retrying a ``401`` would
just be asking the same vendor the same question faster.

**Replay is the default when a recording exists.** With a cache configured, a call that has been
recorded never touches the network, and :attr:`RpcClient.calls` says so per call. This is what
makes a run reproducible from a frozen snapshot; see :mod:`transport.cache` for why that matters
and what it does not promise.

**A refusal names the endpoint and quotes the node.** When every endpoint declines, the exception
carries one :class:`Refusal` per endpoint with the node's own words intact. That text is the
evidence a vendor conversation runs on: "the method trace_transaction does not exist/is not
available" is a different problem from "401 archive requests require a personal token", and a
single "RPC failed" would lose the instruction.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional, Tuple

from .cache import LIVE, REPLAY, cache_key
from .endpoints import DEFAULT_ENDPOINTS, USER_AGENT, as_endpoints
from .http import DEFAULT_TIMEOUT, EndpointUnreachable, UrllibHttpTransport, assert_honest_user_agent
from .params import assert_wire_safe, block_parameter, require_address, require_hash

# -- modes ----------------------------------------------------------------------

#: Replay a recorded call; go to the network and record when there is no recording. The default.
AUTO = "auto"

#: Replay only. A call with no recording raises :class:`transport.cache.RecordingMissing` and
#: nothing is contacted. This is the mode a reproducibility claim is made under.
REPLAY_ONLY = "replay_only"

#: Ignore any recording, call the network, and overwrite. How a snapshot gets refreshed on purpose.
REFRESH = "refresh"

MODES = (AUTO, REPLAY_ONLY, REFRESH)

# -- why an endpoint declined ---------------------------------------------------

#: No answer at all: DNS, TLS, reset, timeout.
UNREACHABLE = "unreachable"
#: An answer, with a non-2xx status.
HTTP_STATUS = "http_status"
#: A 2xx answer carrying a JSON-RPC ``error`` member.
RPC_ERROR = "rpc_error"
#: A 2xx answer that is not a usable JSON-RPC envelope.
MALFORMED = "malformed"

REFUSAL_REASONS = (UNREACHABLE, HTTP_STATUS, RPC_ERROR, MALFORMED)

#: How much of a node's message is kept. Long enough for a real refusal ("archive requests require
#: a personal token"), short enough that an HTML error page does not fill a run record.
VERBATIM_LIMIT = 600

#: Statuses answered by waiting rather than by moving on. Only ``429``: it is the one status that
#: means "ask again later" rather than "the answer is no".
RATE_LIMIT_STATUSES = frozenset({429})

#: Default waits between attempts on one endpoint, in whole seconds. Ints, not floats — the
#: repository forbids floats in the numeric path, and a sleep is not important enough to be the
#: exception that teaches otherwise.
DEFAULT_BACKOFF_SECONDS = (1, 2, 5)

#: A ``Retry-After`` larger than this is not honoured as written; the endpoint is abandoned instead.
#: A node asking for an hour is telling you to come back tomorrow, not to block the run.
MAX_HONOURED_RETRY_AFTER = 120


@dataclass(frozen=True)
class Refusal:
    """One endpoint's reason for not answering a call, with its own words kept intact."""

    endpoint: str
    reason: str
    verbatim: str
    http_status: Optional[int] = None
    rpc_code: Optional[int] = None
    attempts: int = 1

    def describe(self):
        if self.reason == UNREACHABLE:
            head = "did not answer"
        elif self.reason == HTTP_STATUS:
            head = "answered HTTP {}".format(self.http_status)
        elif self.reason == RPC_ERROR:
            head = "answered a JSON-RPC error{}".format(
                "" if self.rpc_code is None else " {}".format(self.rpc_code)
            )
        else:
            head = "answered something that is not a JSON-RPC envelope"
        suffix = "" if self.attempts == 1 else " after {} attempts".format(self.attempts)
        return "{} {}{}: {!r}".format(self.endpoint, head, suffix, self.verbatim)


class RpcRefused(Exception):
    """Every endpoint declined a call. Carries one :class:`Refusal` per endpoint, verbatim.

    An exception rather than a status because the caller asked for bytes and has none: there is no
    partial answer to carry forward. Callers who are *probing* a capability — "does any free
    endpoint serve traces?" — want the same information without a traceback and should use
    :meth:`RpcClient.attempt`, which returns the refusals as data.
    """

    def __init__(self, method, params, refusals):
        self.method = method
        self.params = tuple(params or ())
        self.refusals = tuple(refusals)
        super(RpcRefused, self).__init__(self.report())

    def report(self):
        lines = [
            "{} {} was refused by all {} endpoint(s):".format(
                self.method, list(self.params), len(self.refusals)
            )
        ]
        for refusal in self.refusals:
            lines.append("  - " + refusal.describe())
        lines.append(
            "Each message above is the endpoint's own text, unmodified. If one of them is a "
            "commercial refusal rather than a fault, that sentence is what a vendor conversation "
            "needs."
        )
        return "\n".join(lines)


@dataclass(frozen=True)
class CallRecord:
    """What happened on one call. This is how "which mode did that number come from?" is answered.

    ``mode`` is :data:`transport.cache.REPLAY` or :data:`transport.cache.LIVE`. ``endpoint`` is the
    URL that answered — for a replay, the URL that answered *on the day it was recorded*, which is
    provenance rather than a claim about now.
    """

    method: str
    params: Tuple[Any, ...]
    key: str
    mode: str
    endpoint: str
    recorded_at: str = ""
    refusals: Tuple[Refusal, ...] = field(default_factory=tuple)

    @property
    def replayed(self):
        return self.mode == REPLAY


@dataclass(frozen=True)
class Attempt:
    """A call's outcome as a value: either a result or the reasons there is none."""

    ok: bool
    result: Any
    record: Optional[CallRecord]
    refusals: Tuple[Refusal, ...] = field(default_factory=tuple)

    def raise_for_refusal(self, method, params):
        if not self.ok:
            raise RpcRefused(method, params, self.refusals)
        return self.result


class RpcClient:
    """Raw Ethereum JSON-RPC over an ordered list of endpoints, with replay.

    Guarantees: the parsed ``result`` member is returned **verbatim**; a recorded call is replayed
    without a socket; every call appends a :class:`CallRecord` to :attr:`calls`; a call that no
    endpoint answers raises :class:`RpcRefused` quoting each of them.

    Does not guarantee: that any answer is correct, that two endpoints agree, that a method exists
    anywhere (traces were refused by every free endpoint measured), or that a replayed answer still
    matches the chain today. Reproducible is not the same as verified.
    """

    def __init__(
        self,
        endpoints=DEFAULT_ENDPOINTS,
        cache=None,
        transport=None,
        mode=AUTO,
        user_agent=USER_AGENT,
        timeout=DEFAULT_TIMEOUT,
        attempts_per_endpoint=3,
        backoff_seconds=DEFAULT_BACKOFF_SECONDS,
        sleep=None,
    ):
        if mode not in MODES:
            raise ValueError(
                "unknown mode {!r}; expected one of {}.".format(mode, ", ".join(MODES))
            )
        if mode == REPLAY_ONLY and cache is None:
            raise ValueError(
                "mode={!r} was requested with cache=None. Replay-only means 'answer every call "
                "from the frozen snapshot'; with no snapshot there is nothing to answer from, and "
                "silently falling back to the network would produce exactly the unreproducible "
                "number this mode exists to prevent.".format(REPLAY_ONLY)
            )
        if not isinstance(attempts_per_endpoint, int) or attempts_per_endpoint < 1:
            raise ValueError(
                "attempts_per_endpoint must be a positive int; got {!r}. Zero would skip every "
                "endpoint and report a refusal nobody made.".format(attempts_per_endpoint)
            )
        backoff = tuple(backoff_seconds)
        for value in backoff:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    "backoff_seconds must be non-negative ints; got {!r}.".format(value)
                )

        self.endpoints = as_endpoints(endpoints)
        self.cache = cache
        self.mode = mode
        self.user_agent = assert_honest_user_agent(user_agent)
        self.timeout = timeout
        self.attempts_per_endpoint = attempts_per_endpoint
        self.backoff_seconds = backoff
        self._sleep = sleep or time.sleep
        self._transport = transport
        self._calls = []
        self._next_id = 1

    # -- observability --------------------------------------------------------

    @property
    def calls(self):
        """Every call this client has made, in order, as :class:`CallRecord`."""
        return tuple(self._calls)

    @property
    def last_call(self):
        return self._calls[-1] if self._calls else None

    def replayed_count(self):
        """How many calls came from the snapshot. ``(replayed, live)``."""
        replayed = len([record for record in self._calls if record.mode == REPLAY])
        return replayed, len(self._calls) - replayed

    # -- the wire -------------------------------------------------------------

    def transport(self):
        """The live transport, built on first use.

        Lazy so that a replay-only run never constructs one: "no socket was opened" is easier to
        believe when there is no object capable of opening one.
        """
        if self._transport is None:
            self._transport = UrllibHttpTransport(user_agent=self.user_agent)
        return self._transport

    def attempt(self, method, params=None):
        """Make a call and return an :class:`Attempt` — refusals as data, no traceback.

        Still raises for defects in what assembled the call: bad parameters, an unknown mode, or a
        missing recording under :data:`REPLAY_ONLY`. Those are not measurements.
        """
        params = list(params if params is not None else [])
        key = cache_key(method, params)

        if self.mode != REFRESH and self.cache is not None and self.cache.has(method, params):
            recording = self.cache.read(method, params)
            record = CallRecord(
                method=method, params=tuple(params), key=key, mode=REPLAY,
                endpoint=recording.endpoint, recorded_at=recording.recorded_at,
            )
            self._calls.append(record)
            return Attempt(True, recording.result, record)

        if self.mode == REPLAY_ONLY:
            # Raises RecordingMissing, naming the snapshot, the call, and the file it looked for.
            self.cache.read(method, params)

        result, endpoint, refusals = self._call_live(method, params)
        if endpoint is None:
            record = CallRecord(
                method=method, params=tuple(params), key=key, mode=LIVE, endpoint="",
                refusals=tuple(refusals),
            )
            self._calls.append(record)
            return Attempt(False, None, record, tuple(refusals))

        recorded_at = ""
        if self.cache is not None:
            recorded_at = self.cache.write(method, params, result, endpoint).recorded_at
        record = CallRecord(
            method=method, params=tuple(params), key=key, mode=LIVE, endpoint=endpoint,
            recorded_at=recorded_at, refusals=tuple(refusals),
        )
        self._calls.append(record)
        return Attempt(True, result, record, tuple(refusals))

    def call(self, method, params=None):
        """Make a call and return the node's ``result`` verbatim, or raise :class:`RpcRefused`.

        ``None`` is a legitimate result — an unknown transaction hash returns ``null`` — and is
        returned as ``None``, distinct from a refusal.
        """
        params = list(params if params is not None else [])
        return self.attempt(method, params).raise_for_refusal(method, params)

    def _call_live(self, method, params):
        """Try each endpoint in order. Returns ``(result, endpoint_url, refusals)``.

        ``endpoint_url`` is ``None`` when every endpoint declined; ``refusals`` then holds one
        entry per endpoint. On success it may still be non-empty — that is the interesting case,
        because "the first two refused and the third served it" is a fact about those endpoints
        that a capability question needs.
        """
        assert_wire_safe(params)
        refusals = []
        for endpoint in self.endpoints:
            outcome, refusal = self._call_endpoint(endpoint, method, params)
            if refusal is None:
                return outcome, endpoint.url, tuple(refusals)
            refusals.append(refusal)
        return None, None, tuple(refusals)

    def _call_endpoint(self, endpoint, method, params):
        """One endpoint, with back-off on 429. Returns ``(result, None)`` or ``(None, Refusal)``."""
        transport = self.transport()
        attempts = 0
        last = None
        for index in range(self.attempts_per_endpoint):
            attempts = index + 1
            envelope = {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": method,
                "params": params,
            }
            self._next_id += 1
            try:
                response = transport.post_json(
                    endpoint.url, envelope, timeout=self.timeout
                )
            except EndpointUnreachable as exc:
                return None, Refusal(endpoint.url, UNREACHABLE, exc.reason[:VERBATIM_LIMIT],
                                     attempts=attempts)

            if response.status in RATE_LIMIT_STATUSES:
                last = Refusal(
                    endpoint.url, HTTP_STATUS, response.text(VERBATIM_LIMIT).strip()
                    or "HTTP {} with an empty body".format(response.status),
                    http_status=response.status, attempts=attempts,
                )
                wait = None
                if index + 1 < self.attempts_per_endpoint:
                    wait = self._wait_for(response, index)
                if wait is None:
                    break
                self._sleep(wait)
                continue

            if not response.ok:
                return None, Refusal(
                    endpoint.url, HTTP_STATUS,
                    response.text(VERBATIM_LIMIT).strip()
                    or "HTTP {} with an empty body".format(response.status),
                    http_status=response.status, attempts=attempts,
                )

            payload = response.json()
            if not isinstance(payload, dict):
                return None, Refusal(
                    endpoint.url, MALFORMED, response.text(VERBATIM_LIMIT).strip(),
                    http_status=response.status, attempts=attempts,
                )
            if "error" in payload:
                error = payload["error"] or {}
                message = error.get("message") if isinstance(error, dict) else None
                code = error.get("code") if isinstance(error, dict) else None
                return None, Refusal(
                    endpoint.url, RPC_ERROR,
                    str(message if message is not None else error)[:VERBATIM_LIMIT],
                    http_status=response.status,
                    rpc_code=code if isinstance(code, int) else None,
                    attempts=attempts,
                )
            if "result" not in payload:
                return None, Refusal(
                    endpoint.url, MALFORMED,
                    "a 2xx JSON body with neither a result nor an error member: {}".format(
                        response.text(VERBATIM_LIMIT).strip()
                    ),
                    http_status=response.status, attempts=attempts,
                )
            if payload.get("id") != envelope["id"]:
                return None, Refusal(
                    endpoint.url, MALFORMED,
                    "answered id {!r} to request id {!r}; the response cannot be matched to the "
                    "request that asked for it".format(payload.get("id"), envelope["id"]),
                    http_status=response.status, attempts=attempts,
                )
            return payload["result"], None

        return None, last

    def _wait_for(self, response, index):
        """Seconds to wait after a 429, or ``None`` to give up on this endpoint.

        ``Retry-After`` is honoured when the endpoint gives one in seconds, because it is the
        endpoint telling you what it wants and guessing shorter is how a soft limit becomes a hard
        ban. A value beyond :data:`MAX_HONOURED_RETRY_AFTER`, or an HTTP-date the endpoint sent
        instead of a count, is not honoured as written: the endpoint is abandoned and the next one
        tried, which is what failover is for.
        """
        header = response.header("Retry-After")
        if header is not None:
            try:
                requested = int(str(header).strip())
            except ValueError:
                requested = None
            if requested is not None:
                if requested < 0 or requested > MAX_HONOURED_RETRY_AFTER:
                    return None
                return requested
        if not self.backoff_seconds:
            return None
        return self.backoff_seconds[min(index, len(self.backoff_seconds) - 1)]

    # -- the five methods -----------------------------------------------------
    #
    # Each returns the node's ``result`` unchanged. The dicts that come back are chain bytes: this
    # package neither reads a field of them nor promises which fields a given vendor includes.

    def get_transaction_receipt(self, tx_hash):
        """``eth_getTransactionReceipt``. The receipt dict, or ``None`` if the node has no such tx.

        ``None`` is genuinely ambiguous on a public endpoint — an unknown hash and a
        not-yet-indexed one look identical — and this package does not resolve that. A caller who
        needs to distinguish them must ask a second endpoint.
        """
        return self.call("eth_getTransactionReceipt", [require_hash(tx_hash)])

    def get_transaction_by_hash(self, tx_hash):
        """``eth_getTransactionByHash``. The transaction dict, or ``None``."""
        return self.call("eth_getTransactionByHash", [require_hash(tx_hash)])

    def get_block_by_number(self, block, full_transactions=False):
        """``eth_getBlockByNumber``. The block dict, or ``None``.

        ``full_transactions=False`` returns hashes only, which is the smaller recording and what a
        caller wanting a timestamp needs.
        """
        if not isinstance(full_transactions, bool):
            raise TypeError(
                "full_transactions must be a bool; got {!r}. The wire takes a JSON boolean and a "
                "truthy int would silently become a different call with a different cache "
                "key.".format(full_transactions)
            )
        return self.call(
            "eth_getBlockByNumber", [block_parameter(block), full_transactions]
        )

    def get_logs(self, from_block=None, to_block=None, address=None, topics=None,
                 block_hash=None):
        """``eth_getLogs``. The list of log dicts the node returned.

        The filter is assembled from what you pass and nothing is defaulted: no implicit "latest",
        because an unbounded filter is the request public endpoints refuse, and an implicit bound
        would make the refusal look like an empty result.

        ``topics`` is passed through verbatim — this package holds no event signatures and will not
        name one. Which topic identifies which event is a decoding question, and decoding is
        exactly what may not be shared between the two lanes.
        """
        filter_params = {}
        if block_hash is not None:
            filter_params["blockHash"] = require_hash(block_hash, "blockHash")
            if from_block is not None or to_block is not None:
                raise ValueError(
                    "blockHash cannot be combined with fromBlock/toBlock; the JSON-RPC schema "
                    "treats them as alternatives and a node given both answers for one of them "
                    "without saying which."
                )
        if from_block is not None:
            filter_params["fromBlock"] = block_parameter(from_block)
        if to_block is not None:
            filter_params["toBlock"] = block_parameter(to_block)
        if address is not None:
            if isinstance(address, str):
                filter_params["address"] = require_address(address)
            else:
                filter_params["address"] = [require_address(item) for item in address]
        if topics is not None:
            filter_params["topics"] = _wire_topics(topics)
        if not filter_params:
            raise ValueError(
                "eth_getLogs was called with an empty filter. That asks for every log on the "
                "chain; every public endpoint refuses it, and the refusal would read as though "
                "the query itself were unsupported."
            )
        return self.call("eth_getLogs", [filter_params])

    def get_balance(self, address, block):
        """``eth_getBalance`` at a height. The hex quantity string the node returned, unconverted.

        Left as the node's string on purpose: converting to an int here would be this package
        deciding what the value *is*, and an int would then be indistinguishable from one somebody
        computed. ``int(value, 16)`` is one line in the lane that needs a number.

        A height in the distant past requires a genuine archive node. A pruned node answers with a
        refusal, which arrives as :class:`RpcRefused` quoting it — not as a zero balance.
        """
        return self.call(
            "eth_getBalance", [require_address(address), block_parameter(block)]
        )


def _wire_topics(topics):
    """Validate the *shape* of a topic filter. Says nothing about what any topic means."""
    if not isinstance(topics, (list, tuple)):
        raise TypeError(
            "topics must be a list; got {}. Position in that list is what the filter means, so a "
            "bare string would be read as position 0 by some vendors and rejected by "
            "others.".format(type(topics).__name__)
        )
    out = []
    for index, entry in enumerate(topics):
        if entry is None:
            out.append(None)
        elif isinstance(entry, str):
            out.append(require_hash(entry, "topic {}".format(index)))
        elif isinstance(entry, (list, tuple)):
            out.append([
                require_hash(item, "topic {} alternative".format(index)) for item in entry
            ])
        else:
            raise TypeError(
                "topic {} must be a 32-byte hex string, a list of them, or None; got {}.".format(
                    index, type(entry).__name__
                )
            )
    return out
