"""Append-only, tamper-evident audit log.

Ticket 05 requires "an append-only audit log that the skeleton cannot rewrite". Nothing in a
process can truly prevent a determined operator with filesystem access from editing a file, so
"cannot rewrite" is implemented as **cannot rewrite undetectably**: every entry carries the hash
of the entry before it, so altering or removing any entry breaks the chain from that point on and
:meth:`AuditLog.verify` reports exactly where.

The writer only ever opens the file in append mode. There is no update and no delete.
"""

import hashlib
import json
import os
from datetime import datetime, timezone

from .errors import AuditChainError

GENESIS_HASH = "0" * 64


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _canonical(payload):
    """Deterministic serialisation, so a hash depends on values and not on key order."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _digest(payload):
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


class AuditEntry(object):
    __slots__ = ("seq", "ts", "requester", "action", "detail", "prev_hash", "hash")

    def __init__(self, seq, ts, requester, action, detail, prev_hash, hash_):
        self.seq = seq
        self.ts = ts
        self.requester = requester
        self.action = action
        self.detail = detail
        self.prev_hash = prev_hash
        self.hash = hash_

    def body(self):
        """The hashed part of the entry — everything except the hash itself."""
        return {
            "seq": self.seq,
            "ts": self.ts,
            "requester": self.requester,
            "action": self.action,
            "detail": self.detail,
            "prev_hash": self.prev_hash,
        }

    def to_dict(self):
        d = self.body()
        d["hash"] = self.hash
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(
            d["seq"], d["ts"], d["requester"], d["action"],
            d.get("detail", {}), d["prev_hash"], d["hash"],
        )

    def __repr__(self):
        return "<AuditEntry {} {} by {}>".format(self.seq, self.action, self.requester)


class AuditLog(object):
    """A hash-chained JSONL log.

    :param path: file path; created on first append.
    :param clock: callable returning an ISO-8601 timestamp. Injected for tests.
    """

    def __init__(self, path, clock=_utc_now):
        self.path = str(path)
        self._clock = clock

    # -- reading ---------------------------------------------------------------

    def entries(self):
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(AuditEntry.from_dict(json.loads(line)))
        return out

    def head_hash(self):
        entries = self.entries()
        return entries[-1].hash if entries else GENESIS_HASH

    def __len__(self):
        return len(self.entries())

    # -- writing ---------------------------------------------------------------

    def append(self, requester, action, detail=None):
        """Append one entry. The only mutating operation this class has.

        :param requester: who asked — a human name or an agent identifier. Required; an
            unattributed state change is not permitted.
        """
        if not requester or not str(requester).strip():
            raise ValueError("every audit entry must name its requester")

        existing = self.entries()
        entry = AuditEntry(
            seq=len(existing),
            ts=self._clock(),
            requester=str(requester),
            action=str(action),
            detail=detail or {},
            prev_hash=existing[-1].hash if existing else GENESIS_HASH,
            hash_=None,
        )
        entry.hash = _digest(entry.body())

        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # Append mode only. This class has no code path that truncates or rewrites.
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.to_dict(), sort_keys=True) + "\n")
        return entry

    # -- integrity -------------------------------------------------------------

    def verify(self):
        """Walk the chain. Raises :class:`AuditChainError` naming the first bad entry.

        Detects: an altered entry, a removed entry, a reordered entry, and an appended entry
        that does not chain onto the previous head.
        """
        prev = GENESIS_HASH
        for i, entry in enumerate(self.entries()):
            if entry.seq != i:
                raise AuditChainError(
                    "audit log broken at position {}: seq is {}, expected {} "
                    "(an entry was removed or reordered)".format(i, entry.seq, i)
                )
            if entry.prev_hash != prev:
                raise AuditChainError(
                    "audit log broken at seq {}: prev_hash does not match the preceding "
                    "entry (an entry was altered or removed)".format(entry.seq)
                )
            recomputed = _digest(entry.body())
            if recomputed != entry.hash:
                raise AuditChainError(
                    "audit log broken at seq {}: contents do not match the recorded hash "
                    "(this entry was altered)".format(entry.seq)
                )
            prev = entry.hash
        return True
