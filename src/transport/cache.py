"""A recording cache on disk, keyed by ``(method, params)``.

This is **not** an optimisation. Ticket 26 requires counts that are reproducible from a frozen
snapshot, and a free public endpoint is not a frozen snapshot: it reorgs, it prunes, it rate-limits
differently on a Tuesday, and it may be a different vendor's software next month. A recorded
response *is* a frozen snapshot — bytes that cannot change under a re-run, that travel with the
repository, and that let somebody else reproduce the tracer bullet on a laptop with no network.

What a recording guarantees
---------------------------

That the exact ``result`` a node returned for that exact ``(method, params)`` is what replay hands
back, and that a re-run replays rather than re-asks. The stored key is recomputed on read, so a
file renamed, hand-edited into a different call, or copied from another snapshot is refused rather
than served.

What it does not guarantee
--------------------------

That the recorded answer was *correct*. A node that served a wrong receipt on the day of recording
serves that wrong receipt forever after, silently and reproducibly — reproducibility is not
verification, and ticket 35's cross-source reconciliation is what addresses that. It also
guarantees nothing about calls that were never recorded: a snapshot is a set of answers, not a
node.

On-disk form
------------

One JSON file per call, holding the call, the endpoint that answered, when it answered, and the
result. Object keys are written sorted so a re-recording produces a legible diff; **values are
byte-for-byte what the node sent**, never canonicalised, never renumbered. JSON object key order
carries no meaning, and a stable order is what makes a fixture reviewable.
"""

import errno
import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from contracts.serialization import canonical_hash, format_timestamp

from .http import parse_json_bytes
from .params import assert_wire_safe

#: The two ways a call can have been answered. Every :class:`transport.client.CallRecord` carries
#: one of them, so "did this number come off the wire or out of the snapshot?" is answerable
#: without inspecting logs.
REPLAY = "replay"
LIVE = "live"

MODES = (REPLAY, LIVE)

_SAFE_FILENAME_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)


class RecordingMissing(LookupError):
    """No recording exists for a call, and the caller asked for replay only.

    An exception rather than a status, and deliberately so. "The snapshot does not contain this
    call" is not a disappointing measurement — no measurement was attempted. It is a defect in what
    assembled the run: either the snapshot is the wrong one or the call is new and must be recorded
    deliberately, on purpose, while online.
    """


class RecordingCorrupt(ValueError):
    """A recording file does not hold the call its key says it does.

    Raised on read. A snapshot that quietly serves one call's answer under another call's key is
    worse than no snapshot, because every number derived from it is reproducible and wrong.
    """


def cache_key(method, params):
    """The stable key for a call: SHA-256 over the canonical JSON of ``(method, params)``.

    Uses the frozen canonical form from :mod:`contracts.serialization`, so the key does not move
    with Python's dict ordering, ``json`` defaults, or the ambient locale. Parameters are checked
    with :func:`transport.params.assert_wire_safe` first — an int in the params would give the same
    call two keys, which is the failure mode that makes a frozen snapshot silently go back to the
    network.
    """
    if not isinstance(method, str) or not method:
        raise ValueError("a JSON-RPC method must be a non-empty string; got {!r}.".format(method))
    params = list(params if params is not None else [])
    assert_wire_safe(params)
    return canonical_hash({"method": method, "params": params})


def _safe(name):
    return "".join(char if char in _SAFE_FILENAME_CHARS else "_" for char in name)


@dataclass(frozen=True)
class Recording:
    """One recorded call. ``result`` is the node's ``result`` member, parsed and unmodified."""

    method: str
    params: Tuple[Any, ...]
    key: str
    endpoint: str
    recorded_at: str
    result: Any


class RecordingCache:
    """A directory of recordings.

    ``directory`` is a parameter with no default on purpose: a cache that defaulted to somewhere
    under the user's home would make a run's reproducibility depend on a machine, which is the
    property this class exists to remove.
    """

    def __init__(self, directory, clock=None):
        self.directory = str(directory)
        #: Injected so a test can record a deterministic timestamp. Seconds since the epoch.
        self._clock = clock or time.time

    # -- lookup ---------------------------------------------------------------

    def path_for(self, method, params):
        key = cache_key(method, params)
        return os.path.join(self.directory, "{}.{}.json".format(_safe(method), key[:16]))

    def has(self, method, params):
        return os.path.isfile(self.path_for(method, params))

    def read(self, method, params):
        """Return the :class:`Recording` for a call, or raise :class:`RecordingMissing`."""
        key = cache_key(method, params)
        path = self.path_for(method, params)
        try:
            with open(path, "rb") as handle:
                payload = parse_json_bytes(handle.read())
        except IOError as exc:
            if exc.errno != errno.ENOENT:
                raise
            raise RecordingMissing(
                "no recording for {} {!r} in {} (expected {}). Replay-only was requested, so "
                "nothing was contacted. Either this is the wrong snapshot, or the call is new and "
                "must be recorded deliberately while online.".format(
                    method, list(params or []), self.directory, os.path.basename(path)
                )
            )

        recording = Recording(
            method=payload.get("method"),
            params=tuple(payload.get("params") or ()),
            key=payload.get("key"),
            endpoint=payload.get("endpoint", ""),
            recorded_at=payload.get("recorded_at", ""),
            result=payload.get("result"),
        )
        recomputed = cache_key(recording.method, list(recording.params))
        if recording.key != key or recomputed != key:
            raise RecordingCorrupt(
                "{} holds {} {!r} (key {}), but was read as the recording for {} {!r} (key {}). A "
                "snapshot that serves one call's answer under another call's key produces numbers "
                "that are reproducible and wrong.".format(
                    path, recording.method, list(recording.params), recording.key,
                    method, list(params or []), key,
                )
            )
        return recording

    # -- recording ------------------------------------------------------------

    def write(self, method, params, result, endpoint):
        """Record one answer and return the :class:`Recording`. Overwrites an existing entry.

        Written to a temporary file and renamed, so an interrupted recording leaves the previous
        snapshot intact rather than a truncated file that parses as an empty result.
        """
        key = cache_key(method, params)
        params = list(params if params is not None else [])
        recording = Recording(
            method=method,
            params=tuple(params),
            key=key,
            endpoint=str(endpoint),
            recorded_at=format_timestamp(int(self._clock())),
            result=result,
        )
        body = {
            "method": recording.method,
            "params": params,
            "key": recording.key,
            "endpoint": recording.endpoint,
            "recorded_at": recording.recorded_at,
            "result": recording.result,
        }
        if not os.path.isdir(self.directory):
            os.makedirs(self.directory)
        path = self.path_for(method, params)
        temporary = path + ".partial"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(body, handle, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
        return recording

    # -- inventory ------------------------------------------------------------

    def entries(self):
        """Every recording in the directory, ordered by ``(method, key)``.

        Reads each file, so a corrupt entry is found by listing the snapshot rather than by
        stumbling into it mid-run.
        """
        if not os.path.isdir(self.directory):
            return ()
        found = []
        for name in sorted(os.listdir(self.directory)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(self.directory, name), "rb") as handle:
                payload = parse_json_bytes(handle.read())
            found.append(self.read(payload.get("method"), list(payload.get("params") or ())))
        return tuple(sorted(found, key=lambda item: (item.method, item.key)))

    def fingerprint(self):
        """A single hash over every ``(key, result)`` in the snapshot.

        What a run record cites to say *which* snapshot it read. It covers the calls and their
        answers and deliberately not the endpoint or the timestamp: re-recording the same answers
        from a different vendor on a different day is the same snapshot for the purpose of
        reproducing a number, and a fingerprint that moved with the clock could never be equal
        twice.
        """
        digest = hashlib.sha256()
        for recording in self.entries():
            digest.update(recording.key.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(
                json.dumps(recording.result, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, allow_nan=False).encode("utf-8")
            )
            digest.update(b"\x00")
        return digest.hexdigest()


def optional_cache(directory) -> Optional[RecordingCache]:
    """``RecordingCache(directory)`` or ``None`` when ``directory`` is ``None``.

    A small convenience so a caller can write ``cache=optional_cache(args.snapshot)`` without a
    branch. A ``None`` cache means every call goes to the network and nothing is recorded, which is
    a legitimate mode and not a default anybody should reach by accident.
    """
    return None if directory is None else RecordingCache(directory)
