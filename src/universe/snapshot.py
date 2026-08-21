"""The cutoff, proven at the snapshot rather than asserted at the record.

Every guard in ``observation`` and ``ranking`` binds what a *record says about itself*. None of them
can see the query that produced it. That leaves one large route open, and it is the one Python
cannot detect at all::

    SELECT wallet, SUM(volume) AS pre_t0_volume
    FROM trades
    WHERE block_time <= :t0

The ``WHERE`` may be wrong. A join may pull in a forward table. The aggregation may run before the
cutoff is applied. An intermediary view may itself hold post-T0 rows. And once the sum has been
taken, the contamination is *inside* a number that carries a perfectly pre-T0 stamp. **It does not
matter that ranking never read that column.**

So a selection snapshot has to carry evidence about itself, and the evidence has to be checked:

    ``min_block`` · ``max_block`` · ``row_count`` · ``window_id`` · ``t0_block``
    · ``source_query_hash`` · ``source_table_versions`` · ``snapshot_hash``

with ``max_block < t0_block``. The boundary is strict, and it is strict in **both** spellings: the
type and :func:`pre_t0_snapshot` used to disagree by exactly one block, so a census whose last row
was written at ``T0`` was refused by the factory and accepted by the constructor the package
exports. A row written at ``T0`` has already seen the instant the selection decision is made.

Where the evidence binds
------------------------

There is no live database in this repository, so what is built here is the abstraction the package
already uses — a snapshot identifier the caller supplies — with the evidence made **structural** at
the one seam that can carry it: :meth:`universe.ordering.ExecutionOrder.mount_pre_t0` takes the
snapshot and the :class:`universe.freeze.FrozenUniverse` **together**, checks that they name the
same window and that ``t0_block`` is that window's real ``T0``, and hands back the workspace that
:func:`universe.select.rank_and_select` cannot run without. So a snapshot that cannot be constructed
is a selection that cannot execute, and ``Selection Execution: BLOCKED`` describes the mechanism
rather than an intention.

An earlier version of this docstring said :class:`PreT0Snapshot` was a required field of
:class:`universe.freeze.FrozenUniverse`. It was not, and no selection stage required snapshot
evidence at all — the snapshot appeared only at seal time, after the basket had already been chosen.
That sentence has been replaced by the paragraph above, which describes what the code does.

Isolation is a refusal, not a filter
-------------------------------------

:func:`pre_t0_snapshot` takes the block heights of the rows it was built from and **raises** on one
at or after ``T0``. It does not drop the row. Dropping it would change the composition of the
candidate universe on post-T0 information, which is ``SILENTLY_DROPPED`` — the outcome that looks
like a caught breach and is not one. One post-T0 record present means::

    Isolation Status: FAILED
    Selection Execution: BLOCKED

What this module does not guarantee
-----------------------------------

``source_query_hash`` and ``source_table_versions`` are claims the caller makes, exactly like every
other stamp in this package. Nothing here executes SQL, opens a warehouse connection, or can tell
you that the hash names the query that actually ran. What the evidence buys is that the claim is
**recorded, hashed, and travels with every artifact downstream** — so a re-run under a different
query or a re-versioned table produces a different ``snapshot_hash`` and every pin disagrees, rather
than the two runs being quietly interchangeable.

``row_count`` is likewise a caller's number when a snapshot is constructed directly rather than
through :func:`pre_t0_snapshot`, which measures it. What is *not* a caller's number any more is
``t0_block``: it is compared against the window's own ``T0`` at step 1.

``max_block < t0_block`` is also checked in blocks only. A row whose block is pre-T0 but whose
vendor-recomputed columns are not is refused one layer up, by
:attr:`universe.observation.VendorMutability.MUTABLE_VENDOR_FIELD`.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple

from contracts import ContractError, LookAheadViolation, canonical_hash

from .protocol import (
    UNIVERSE_SCHEMA_VERSION,
    PreT0Sealed,
    pre_t0_sealed,
    require_pre_t0_int,
)

#: Bump when the evidence payload changes shape. It is hashed into ``snapshot_hash``, so a snapshot
#: written under an older version fails verification rather than being reinterpreted.
SNAPSHOT_SCHEMA_VERSION = "pre-t0-snapshot-v1"

#: The witness ``__post_init__`` stamps on evidence it actually checked.
#:
#: Measured, on the version of this file without it: 404 bytes of hand-written pickle produced an
#: object for which ``type(x) is PreT0Snapshot`` was true, whose ``max_block`` was 99,999 blocks
#: past ``T0``, whose ``snapshot_hash`` was the string ``'not a hash of anything'`` and whose
#: ``isolation_status`` read ``VERIFIED`` — because ``isolation_status`` is a property that returns a
#: constant on the argument that a failing snapshot raised at construction, and this one never
#: reached construction. ``__reduce__`` cannot close that: it binds the ``dumps`` direction, and the
#: payload was written by hand.
#:
#: Compared by identity in :func:`require_verified_snapshot`, which every consumer of a snapshot in
#: this package runs.
_VERIFIED = object()


class SelectionExecutionBlocked(LookAheadViolation):
    """Isolation failed: at least one post-``T0`` record was present in a selection snapshot.

    Raised at snapshot construction, so selection cannot execute against it. The wording of the two
    lines this produces is fixed by the brief and is not a stylistic choice: ``Isolation Status:
    FAILED`` and ``Selection Execution: BLOCKED`` describe the run, not the row.
    """


class SnapshotEvidenceMissing(ContractError):
    """A snapshot was assembled without one of the eight required facts, or with an unusable one."""


class IsolationStatus(str, Enum):
    """Two states, and :attr:`FAILED` is not constructible on a :class:`PreT0Snapshot`.

    The enum exists so that the *report* can name the state; the type system is what enforces it. A
    snapshot whose isolation failed raises :class:`SelectionExecutionBlocked` at construction, so
    there is no object in the system carrying ``FAILED`` — which is the difference between a status
    a reader has to notice and a refusal they cannot proceed past.
    """

    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class TableVersion:
    """One source table and the version of it the snapshot was taken from.

    A nominal pair rather than a ``Dict[str, str]``. A mapping is a tunnel: it accepts any key, so a
    forward table added to the query is a new entry nobody has to declare, and the type says nothing
    about what it holds.
    """

    table: str
    version: str

    def __post_init__(self) -> None:
        for name in ("table", "version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SnapshotEvidenceMissing(
                    "a source table version must state its {}; an unnamed table is a source nobody "
                    "can re-derive the snapshot from".format(name)
                )
            object.__setattr__(self, name, value.strip())

    def __reduce__(self) -> object:
        raise SnapshotEvidenceMissing(
            "a TableVersion cannot be pickled. It is one of the eight facts a snapshot hashes, and "
            "unpickling rebuilds it without running the check above."
        )

    def __setstate__(self, state: object) -> None:
        raise SnapshotEvidenceMissing(
            "a TableVersion cannot be unpickled; see __reduce__.")


@pre_t0_sealed
@dataclass(frozen=True)
class PreT0Snapshot(PreT0Sealed):
    """The eight facts, verified, and a hash over them that every downstream artifact pins.

    Sealed. A subclass overriding ``__post_init__`` would carry a ``max_block`` past ``T0`` while
    remaining an ``isinstance`` of the base — the exact shape the rest of this package switched to
    ``type(x) is`` to close.

    ``snapshot_hash`` is **recomputed here and compared**, not stored and trusted. A hash a caller
    supplies and nobody checks is a field, and a field that names itself a hash is worse than no
    hash at all because a reader stops looking.
    """

    window_id: str
    t0_block: int
    min_block: int
    max_block: int
    row_count: int
    source_query_hash: str
    source_table_versions: Tuple[TableVersion, ...]
    snapshot_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_table_versions", tuple(self.source_table_versions))
        for name in ("window_id", "source_query_hash", "snapshot_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SnapshotEvidenceMissing(
                    "a pre-T0 snapshot must state its {}. All eight facts are required: a snapshot "
                    "missing one is evidence nobody can check, and an unchecked snapshot is the "
                    "aggregation route this type exists to close.".format(name)
                )
            object.__setattr__(self, name, value.strip())
        for name in ("t0_block", "min_block", "max_block", "row_count"):
            value = require_pre_t0_int(getattr(self, name), "PreT0Snapshot.{}".format(name))
            if value < 0:
                raise SnapshotEvidenceMissing(
                    "PreT0Snapshot.{} is {}; a block height and a row count are both "
                    "magnitudes".format(name, value)
                )
        if not self.source_table_versions:
            raise SnapshotEvidenceMissing(
                "a pre-T0 snapshot must name at least one source table and its version. A snapshot "
                "with no declared sources cannot be shown to have excluded a forward table, and "
                "the join that pulls one in is invisible in the resulting numbers."
            )
        for entry in self.source_table_versions:
            if type(entry) is not TableVersion:
                raise TypeError(
                    "PreT0Snapshot.source_table_versions holds TableVersion values, got {}. A bare "
                    "tuple or a mapping entry would let a source be declared in a shape nothing "
                    "validates.".format(type(entry).__name__)
                )
        if self.row_count <= 0:
            raise SnapshotEvidenceMissing(
                "a pre-T0 snapshot over {} row(s). An empty snapshot reads as 'nobody traded before "
                "T0', which is a finding no window in this design has produced and is far more "
                "likely to be a query that returned nothing.".format(self.row_count)
            )
        if self.min_block > self.max_block:
            raise SnapshotEvidenceMissing(
                "the snapshot's min_block {} is above its max_block {}; the two describe the same "
                "row set and cannot cross".format(self.min_block, self.max_block)
            )

        # The requirement, stated once and enforced here. ``>=`` and not ``>``: a row written at T0
        # has already seen the instant the selection decision is made, which is the rule
        # ``pre_t0_snapshot`` states in its own refusal message. The two spellings disagreed by one
        # block, and the type was the lenient one — so a census ending exactly at T0 was refused by
        # the factory and accepted by the class this package exports.
        if self.max_block >= self.t0_block:
            raise SelectionExecutionBlocked(
                "Isolation Status: FAILED\nSelection Execution: BLOCKED\n"
                "the selection snapshot for window {} holds a record at block {}, at or after T0 "
                "block {}. It does not matter whether ranking read that column: a post-T0 row inside the "
                "snapshot can already have entered an aggregation, and Python cannot detect "
                "contamination that was buried before it saw a value. The run is blocked rather "
                "than the row being dropped — dropping it would change the composition of the "
                "candidate universe on post-T0 information.".format(
                    self.window_id, self.max_block, self.t0_block)
            )

        recomputed = snapshot_evidence_hash(
            window_id=self.window_id,
            t0_block=self.t0_block,
            min_block=self.min_block,
            max_block=self.max_block,
            row_count=self.row_count,
            source_query_hash=self.source_query_hash,
            source_table_versions=self.source_table_versions,
        )
        if self.snapshot_hash != recomputed:
            raise SnapshotEvidenceMissing(
                "the snapshot claims hash {} and its own evidence hashes to {}. The hash is "
                "recomputed here rather than trusted, because a stored hash nobody recomputes is a "
                "field — and a field named 'hash' stops a reader looking any further.".format(
                    self.snapshot_hash, recomputed)
            )
        object.__setattr__(self, "_evidence_witness", _VERIFIED)

    def __reduce__(self) -> object:
        raise SnapshotEvidenceMissing(
            "a PreT0Snapshot cannot be pickled. Every check above — the T0 cutoff, the eight facts, "
            "the hash recompute — lives in __post_init__, and unpickling runs none of them."
        )

    def __setstate__(self, state: object) -> None:
        raise SnapshotEvidenceMissing(
            "a PreT0Snapshot cannot be unpickled; see __reduce__. The refusal is on both directions "
            "because the payload that mattered was written by hand rather than dumped."
        )

    @property
    def isolation_status(self) -> IsolationStatus:
        """:attr:`IsolationStatus.VERIFIED` for a snapshot that ran its own checks, and nothing else.

        A snapshot whose isolation failed raised at construction and does not exist. One that never
        *reached* construction is a different animal, and this property used to answer ``VERIFIED``
        for it: it returned a constant on the argument that the constructor was the only way in,
        which stopped being true the moment somebody wrote the bytes by hand. It now reads the
        witness, so an unconstructed object says ``FAILED`` rather than lying, and
        :func:`require_verified_snapshot` is what refuses it.
        """
        if getattr(self, "_evidence_witness", None) is not _VERIFIED:
            return IsolationStatus.FAILED
        return IsolationStatus.VERIFIED

    @property
    def cutoff_block(self) -> int:
        """The block the snapshot is truncated at. The same number ``t0_block`` holds, named for
        what it does to the data rather than for what it is in the calendar."""
        return self.t0_block


def require_verified_snapshot(snapshot: PreT0Snapshot, what: str) -> PreT0Snapshot:
    """The gate every consumer of snapshot evidence runs: exact type, and the checks actually ran.

    ``type(x) is PreT0Snapshot`` is satisfied by ``object.__new__``, and by a pickle payload that
    names this class — both produce an object carrying whatever the writer chose, including a
    ``max_block`` past ``T0`` and a ``snapshot_hash`` that is not a hash. The witness is what tells
    a verified snapshot from an assembled one, and it is checked here rather than at each call site
    so the two cannot come to disagree.
    """
    if type(snapshot) is not PreT0Snapshot:
        raise SnapshotEvidenceMissing(
            "{} needs a verified PreT0Snapshot, got {}".format(what, type(snapshot).__name__))
    if getattr(snapshot, "_evidence_witness", None) is not _VERIFIED:
        raise SelectionExecutionBlocked(
            "Isolation Status: FAILED\nSelection Execution: BLOCKED\n"
            "{}: the snapshot carries no evidence witness, so PreT0Snapshot.__post_init__ never "
            "ran on it — the T0 cutoff was not applied, the eight facts were not checked and the "
            "hash was not recomputed. An object of the right type whose checks never ran is the "
            "shape a hand-written pickle payload produces, and it reports every isolation claim "
            "this run publishes.".format(what)
        )
    return snapshot


def snapshot_evidence_hash(window_id: str, t0_block: int, min_block: int, max_block: int,
                           row_count: int, source_query_hash: str,
                           source_table_versions: Tuple[TableVersion, ...]) -> str:
    """The canonical hash over the seven stated facts. The eighth *is* this hash.

    Explicit keyword parameters rather than a payload mapping, so that adding a fact to the evidence
    is a signature change every caller has to acknowledge instead of a key somebody forgot.
    """
    return canonical_hash({
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "universe_schema_version": UNIVERSE_SCHEMA_VERSION,
        "window_id": window_id,
        "t0_block": t0_block,
        "min_block": min_block,
        "max_block": max_block,
        "row_count": row_count,
        "source_query_hash": source_query_hash,
        "source_table_versions": [
            [entry.table, entry.version] for entry in source_table_versions
        ],
    })


def pre_t0_snapshot(window_id: str, t0_block: int, row_blocks: Tuple[int, ...],
                    source_query_hash: str,
                    source_table_versions: Tuple[TableVersion, ...]) -> PreT0Snapshot:
    """Build a verified snapshot from the block heights of the rows it holds.

    :param row_blocks: one block height per row in the snapshot. This is the census the evidence is
        derived from, so ``min_block``, ``max_block`` and ``row_count`` are **measured** rather than
        asserted — a caller cannot state a max that disagrees with the rows.

    :raises SelectionExecutionBlocked: if any row is at or after ``t0_block``. The row is not
        filtered out. Filtering would leave a smaller snapshot whose composition depended on which
        rows were post-T0, which is selection on post-T0 information wearing a repair's clothes.
    """
    require_pre_t0_int(t0_block, "pre_t0_snapshot t0_block")
    blocks = tuple(row_blocks)
    if not blocks:
        raise SnapshotEvidenceMissing(
            "pre_t0_snapshot was given no rows. An empty census cannot show a cutoff held, and a "
            "snapshot built from it would carry evidence about nothing."
        )
    for index, block in enumerate(blocks):
        require_pre_t0_int(block, "pre_t0_snapshot row {} block".format(index))
    offending = sorted({block for block in blocks if block >= t0_block})
    if offending:
        raise SelectionExecutionBlocked(
            "Isolation Status: FAILED\nSelection Execution: BLOCKED\n"
            "{} row(s) in the snapshot for window {} are at or after T0 block {} (first: {}). The "
            "boundary is >= and not >: a row written at T0 has already seen the instant the "
            "selection decision is made. These rows are refused, not dropped — a snapshot that "
            "silently excluded them would have a composition decided by post-T0 "
            "information.".format(len(offending), window_id, t0_block, offending[0])
        )
    min_block = min(blocks)
    max_block = max(blocks)
    row_count = len(blocks)
    return PreT0Snapshot(
        window_id=window_id,
        t0_block=t0_block,
        min_block=min_block,
        max_block=max_block,
        row_count=row_count,
        source_query_hash=source_query_hash,
        source_table_versions=tuple(source_table_versions),
        snapshot_hash=snapshot_evidence_hash(
            window_id=window_id,
            t0_block=t0_block,
            min_block=min_block,
            max_block=max_block,
            row_count=row_count,
            source_query_hash=source_query_hash,
            source_table_versions=tuple(source_table_versions),
        ),
    )
