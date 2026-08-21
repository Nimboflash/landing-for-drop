"""The recording cache: what was asked, what came back, and what was done to it afterwards.

Why a recording rather than a live call
---------------------------------------

Hyperliquid's ``userFills`` returns "the last 2000 fills", and the leaderboard is a snapshot of a
running competition. Neither is addressable: the same request tomorrow is a different answer, and
there is no block height to pin instead. So a number derived from a live call is reproducible by
nobody, including the person who derived it ten minutes later. **Replay is therefore the default
and live is opt-in**, and the opt-in is not a flag — a client constructed the ordinary way holds no
transport at all and physically cannot open a connection. See :mod:`tools.hyperliquid.client`.

What a recording file holds, and why each field is there
---------------------------------------------------------

::

    format        the envelope version, so a reader knows what the rest means
    request       method, url and body -- what would have to be sent to get this again
    response      status, and the parsed JSON
    bytes_sha256  digest of the exact response body as it came off the wire
    bytes_len     its length
    captured_at   UTC milliseconds, from the recorder's clock
    captured_by   the User-Agent that was sent, verbatim
    reduction     null for a verbatim capture; otherwise what was dropped and by what rule

``response.json`` is the *parsed* value and not the bytes. That is a deliberate, stated loss: the
files are meant to be read and diffed by a person, and a 132 KB single-line escaped string is not.
So the guarantee is exact about what it covers — **replay reproduces the parsed value, not the
bytes** — and ``bytes_sha256`` is kept so a re-capture can be compared against the original at the
one place where byte-exactness is checkable.

Why ``reduction`` exists, and why it is not a lie
-------------------------------------------------

The leaderboard was 34,228,362 bytes and 41,456 rows when it was captured. Committing it is not
reasonable, and quietly
committing a slice of it as though it were the response *is* the failure this whole instrument is
about. So a reduced recording says so, in the file, in a field every reader of the file sees:
which rule selected the rows, how many were kept, how many there were, and the digest of the full
capture the rows were taken from. Every kept row is byte-for-byte what the venue sent; what is lost
is stated rather than implied.

A reduced recording is legitimate for the leaderboard for one specific reason and no other:
:func:`tools.hyperliquid.client.HyperliquidClient.leaderboard` exists to *sample which wallets to
pull*, and a sample of a sample is still a sample. It would not be legitimate for a fills response,
because a subset of a wallet's fills is a different wallet's history — and the fills recordings
committed here are ``userFillsByTime`` windows, which are verbatim and complete for their window.

What this module does not guarantee
------------------------------------

That a recording is what the venue actually sent. Nothing here can check that: the file is written
by the recorder and read by the replayer, and a hand-edited file replays exactly like a captured
one. ``reduction`` is a claim the recorder makes about itself, in the same way
``phase0.snapshots.NOT_REAL_PREFIXES`` is a claim a source makes about itself. What it does buy is
that a *silent* reduction requires editing a file that says ``"reduction": null``, which is an act
rather than an omission.
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

#: Envelope version. Bumped when the meaning of a field changes, never when one is added.
FORMAT = "hyperliquid-recording-v1"

#: Characters permitted in the readable half of a recording's filename.
_SLUG_SAFE = re.compile(r"[^a-z0-9]+")


class RecordingMissing(LookupError):
    """Replay was asked for a request that has not been recorded.

    A ``LookupError`` and not a network error: nothing was attempted. The message carries the exact
    capture command, because the reader's next action is always the same one and making them
    reconstruct it is how a replay-only suite acquires an accidental network dependency.
    """


@dataclass(frozen=True)
class RequestSpec:
    """What would have to be sent to obtain a response. The cache key is a function of this alone.

    ``body`` is the parsed JSON body for a POST, or ``None`` for a GET. It is keyed with
    ``sort_keys=True`` so that two callers who spelled the same request with their keys in a
    different order hit the same recording — the venue does not care about key order and neither
    should the cache.
    """

    method: str
    url: str
    body: Optional[Mapping[str, Any]] = None

    def __post_init__(self):
        object.__setattr__(self, "method", str(self.method).upper())
        if self.method not in ("GET", "POST"):
            raise ValueError(
                "method must be GET or POST, got {!r}. Hyperliquid's two bases use exactly those "
                "two and a recording key that admitted more would be keying requests this package "
                "cannot make.".format(self.method)
            )
        if not isinstance(self.url, str) or not self.url.startswith("https://"):
            raise ValueError(
                "url must be an https:// string, got {!r}".format(self.url)
            )

    def canonical(self):
        """The exact string the key is taken over. Written out so a key can be recomputed by hand."""
        encoded = "" if self.body is None else json.dumps(
            self.body, sort_keys=True, separators=(",", ":")
        )
        return "{}\n{}\n{}".format(self.method, self.url, encoded)

    def key(self):
        """SHA-256 of :meth:`canonical`. The cache key."""
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()

    def slug(self):
        """A readable filename half: the request ``type`` if there is one, else the URL's last part."""
        if self.body is not None and isinstance(self.body.get("type"), str):
            label = self.body["type"]
        else:
            label = self.url.rstrip("/").rsplit("/", 1)[-1] or "request"
        return _SLUG_SAFE.sub("-", label.lower()).strip("-") or "request"

    def filename(self):
        return "{}-{}.json".format(self.slug(), self.key()[:12])

    def describe(self):
        return "{} {}{}".format(
            self.method, self.url,
            "" if self.body is None else " " + json.dumps(self.body, sort_keys=True),
        )


@dataclass(frozen=True)
class Reduction:
    """What was dropped from a capture before it was committed, and by what rule.

    Every field is required. A reduction with no ``rule`` is one nobody can reproduce, and a
    reduction with no ``original_count`` is one nobody can size.
    """

    rule: str
    kept: int
    original_count: int
    original_bytes_sha256: str

    def __post_init__(self):
        if not isinstance(self.rule, str) or not self.rule.strip():
            raise ValueError(
                "Reduction.rule must say which rows were kept and how they were chosen; a "
                "reduction nobody can reproduce is a reduction nobody can check"
            )
        for name in ("kept", "original_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise TypeError(
                    "Reduction.{} must be a non-negative int, got {!r}".format(name, value)
                )
        if self.kept > self.original_count:
            raise ValueError(
                "Reduction kept {} rows out of {}: a reduction cannot add rows, and a file "
                "claiming it did is not describing the capture it came from".format(
                    self.kept, self.original_count
                )
            )

    def as_dict(self):
        return {
            "rule": self.rule,
            "kept": self.kept,
            "original_count": self.original_count,
            "original_bytes_sha256": self.original_bytes_sha256,
        }


@dataclass(frozen=True)
class Recording:
    """One recorded exchange.

    ``payload`` is the parsed JSON. ``verbatim`` is a property rather than a field so that it cannot
    disagree with ``reduction`` — a file asserting both would be a file asserting nothing.
    """

    spec: RequestSpec
    status: int
    payload: Any
    bytes_sha256: str
    bytes_len: int
    captured_at: int
    captured_by: str
    reduction: Optional[Reduction] = None

    @property
    def verbatim(self):
        """True when nothing was dropped between the wire and this file."""
        return self.reduction is None

    def as_dict(self):
        return {
            "format": FORMAT,
            "request": {
                "method": self.spec.method,
                "url": self.spec.url,
                "body": self.spec.body,
            },
            "response": {"status": self.status, "json": self.payload},
            "bytes_sha256": self.bytes_sha256,
            "bytes_len": self.bytes_len,
            "captured_at": self.captured_at,
            "captured_by": self.captured_by,
            "reduction": None if self.reduction is None else self.reduction.as_dict(),
        }

    @classmethod
    def from_dict(cls, data, filename):
        found = data.get("format")
        if found != FORMAT:
            raise ValueError(
                "{} declares format {!r}; this reader understands {!r}. Refusing to guess: a "
                "recording read under the wrong envelope version is a payload interpreted by a "
                "rule it was not written under.".format(filename, found, FORMAT)
            )
        request = data["request"]
        reduction = data.get("reduction")
        return cls(
            spec=RequestSpec(request["method"], request["url"], request.get("body")),
            status=int(data["response"]["status"]),
            payload=data["response"]["json"],
            bytes_sha256=data["bytes_sha256"],
            bytes_len=int(data["bytes_len"]),
            captured_at=int(data["captured_at"]),
            captured_by=data["captured_by"],
            reduction=None if reduction is None else Reduction(
                rule=reduction["rule"],
                kept=int(reduction["kept"]),
                original_count=int(reduction["original_count"]),
                original_bytes_sha256=reduction["original_bytes_sha256"],
            ),
        )


class RecordingCache(object):
    """A directory of recordings, addressed by :meth:`RequestSpec.key`.

    Reads are lazy and cached in memory. Nothing here touches the network; a cache handed to a
    client with no transport is the whole of what that client can see.
    """

    def __init__(self, directory):
        self.directory = str(directory)
        self._loaded = {}

    # -- reading ---------------------------------------------------------------

    def path_for(self, spec):
        return os.path.join(self.directory, spec.filename())

    def get(self, spec):
        """The recording for ``spec``, or ``None``. Never raises on a miss; the client decides."""
        key = spec.key()
        if key in self._loaded:
            return self._loaded[key]
        path = self.path_for(spec)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as handle:
            recording = Recording.from_dict(json.load(handle), path)
        if recording.spec.key() != key:
            raise ValueError(
                "{} is filed under key {} but the request it records keys to {}. The filename is "
                "derived from the request, so a mismatch means the file was renamed or its request "
                "was edited — either way replay would serve one request's answer to another "
                "request.".format(path, key, recording.spec.key())
            )
        self._loaded[key] = recording
        return recording

    def entries(self):
        """Every recording in the directory, ordered by key. Ordered so the digest is stable."""
        if not os.path.isdir(self.directory):
            return ()
        found = []
        for name in sorted(os.listdir(self.directory)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(self.directory, name)
            with open(path, "r", encoding="utf-8") as handle:
                found.append(Recording.from_dict(json.load(handle), path))
        return tuple(sorted(found, key=lambda r: r.spec.key()))

    def digest(self):
        """SHA-256 over every recording's ``(key, bytes_sha256)``, in key order.

        This is what :func:`tools.hyperliquid.provenance.snapshot_id` names, so a run's dataset
        snapshot identifier moves the moment any recorded byte does. It covers the *responses* and
        the requests that produced them; it does not cover ``captured_at`` or ``captured_by``, so
        re-capturing identical bytes yields the same snapshot — which is the intended behaviour:
        the snapshot names the data, not the session that fetched it.
        """
        accumulator = hashlib.sha256()
        for recording in self.entries():
            accumulator.update(recording.spec.key().encode("ascii"))
            accumulator.update(b"|")
            accumulator.update(recording.bytes_sha256.encode("ascii"))
            accumulator.update(b"\n")
        return accumulator.hexdigest()

    # -- writing ---------------------------------------------------------------

    def put(self, recording):
        """Write a recording, creating the directory if needed. Returns the path written."""
        if not os.path.isdir(self.directory):
            os.makedirs(self.directory)
        path = self.path_for(recording.spec)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(recording.as_dict(), handle, indent=1, sort_keys=False)
            handle.write("\n")
        self._loaded[recording.spec.key()] = recording
        return path

    def require(self, spec, how_to_capture):
        """The recording for ``spec``, or a refusal that says exactly how to obtain it.

        :raises RecordingMissing: naming the request, the key, the file that would hold it, and the
            command that would capture it.
        """
        recording = self.get(spec)
        if recording is not None:
            return recording
        raise RecordingMissing(
            "no recording for {}.\n"
            "  key:      {}\n"
            "  expected: {}\n"
            "  capture:  {}\n"
            "Replay is the default because Hyperliquid's fills window and leaderboard both move — "
            "the same request tomorrow is different data, so a number taken from a live call is "
            "reproducible by nobody. Nothing was attempted against the network here: a client "
            "built without an explicit transport holds none.".format(
                spec.describe(), spec.key(), self.path_for(spec), how_to_capture,
            )
        )


def digest_bytes(payload):
    """SHA-256 of a response body exactly as it came off the wire."""
    return hashlib.sha256(payload).hexdigest()


def reduce_rows(payload, container_key, keep, rule, original_bytes):
    # type: (Any, Optional[str], int, str, bytes) -> Tuple[Any, Reduction]
    """Keep the first ``keep`` rows of a row-shaped payload, verbatim, and describe what was dropped.

    ``container_key`` names the key holding the rows (``"leaderboardRows"``), or ``None`` when the
    payload is itself a list. Rows are kept in the order the venue sent them and are not touched:
    the reduction is a truncation of a sequence, never an edit of a row, so every row that survives
    is byte-for-byte what the venue sent.

    :returns: ``(reduced_payload, reduction)``.
    """
    rows = payload if container_key is None else payload[container_key]
    if not isinstance(rows, list):
        raise TypeError(
            "reduce_rows expected a list of rows{}, got {}".format(
                "" if container_key is None else " under {!r}".format(container_key),
                type(rows).__name__,
            )
        )
    kept = rows[:keep]
    reduction = Reduction(
        rule=rule,
        kept=len(kept),
        original_count=len(rows),
        original_bytes_sha256=digest_bytes(original_bytes),
    )
    if container_key is None:
        return kept, reduction
    reduced = dict(payload)
    reduced[container_key] = kept
    return reduced, reduction
