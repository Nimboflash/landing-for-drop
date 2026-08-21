"""The sealed selection artifact — the only thing that crosses from selection to evaluation.

Ticket 28's basket is a live Python object holding live Python objects. That is the right shape
while selection is running and the wrong shape the moment forward data exists, because every field
on it is still reachable, re-rankable and — through ``dataclasses.replace`` — rewritable in one
line.

:class:`SelectedWalletArtifact` is the shape for afterwards. It carries

    ``provenance`` · ``window_id`` · ``cutoff_block`` · ``dataset_hash``

as required fields, is checked for all four before anything may rank against it, is canonical and
schema-versioned, and **cannot be pickled**. ``__reduce__`` raises on both the artifact and its
rows, because unpickling reconstructs an object without running a single ``__post_init__`` — every
refusal in this file is bypassed by ``pickle.loads`` unless the type refuses to be pickled at all.
The audit demonstrated exactly that: a ``PreT0Score`` whose ``as_of_block`` was 99,999 blocks past
``T0`` round-tripped through pickle with nothing raising.

Values are strings, and that is the point
------------------------------------------

``SelectedWallet.value`` is the canonical decimal *string*, not a ``Decimal`` and not a
:class:`universe.provenance.PreT0Decimal`. An artifact is a serialization boundary: the thing on the
other side of it must be re-derivable from bytes, and a live numeric object crossing that boundary
would mean the evaluation side holds selection-side machinery.

The provenance that mattered was enforced on the way *in*, and it is worth being exact about where,
because this module cannot enforce it: :func:`universe.select.seal_selection` re-reads each selected
wallet's :class:`universe.ranking.PreT0Score`, puts it through
:func:`universe.provenance.require_pre_t0_value`, and refuses to seal if the digits on the basket
disagree with the digits the score carries. By the time a value reaches :class:`SelectedWallet` it is
a string and every check that could be made has been. What is recorded here is the *outcome* of
that, as :attr:`SelectedWalletArtifact.provenance` — which is why :func:`sealed_artifact` does not
offer ``provenance`` as a parameter for a caller to assert.

Every check runs again at every gate
------------------------------------

An invariant enforced only in ``__post_init__`` is an invariant that binds objects which ran it.
``object.__new__(SelectedWallet)`` followed by ``__dict__.update`` produces something that satisfies
``type(row) is SelectedWallet`` and ran nothing, and the first version of this module let one
through :func:`sealed_artifact` and out of :func:`require_sealed_artifact` carrying
``valid_buys = 1,000,000,000`` at rank 1 for a wallet the ranking never selected. So:

* :meth:`SelectedWalletArtifact.verify` rebuilds **every row through its own constructor** rather
  than handing the existing instances back — ``universe.freeze.FrozenUniverse.verify``'s pattern,
  which the two had no business disagreeing about;
* :data:`REQUIRED_ARTIFACT_FACTS` and the row checks are joined by a *witness*: ``__post_init__``
  stamps :data:`_CONSTRUCTED`, and :func:`require_sealed_artifact` refuses an object that does not
  carry it, so an artifact assembled by any route that skipped construction is refused by name
  rather than by whether its fields happen to look plausible;
* ``__setstate__`` raises on both types, because ``__reduce__`` binds the ``dumps`` direction only
  and the attack arrives as bytes.

What this module does not guarantee
-----------------------------------

Sealing is a property of the type, not of the file system. ``object.__setattr__`` still rewrites any
field of any Python object, and ``artifact_hash`` is recomputable by whoever holds the fields — so
"this artifact is internally consistent" is not "this artifact is the one that was sealed". That
second claim is not made here and cannot be: it is made by
:class:`universe.ordering.ForwardMount`, which carries the hash :meth:`ExecutionOrder.seal
<universe.ordering.ExecutionOrder.seal>` recorded and re-checks the artifact against it on every
read. What this module does close is every ordinary spelling: the dataclass is frozen, subclassing
is refused at class-definition time, ``dataclasses.replace`` with a stale hash is refused, a
re-ranked row order is refused whatever the hash says, and pickle raises in both directions.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple

from contracts import ContractError, canonical_hash, to_canonical_json

from .protocol import (
    UNIVERSE_SCHEMA_VERSION,
    VALID_BUY_CEILING,
    VALID_BUY_FLOOR,
    PreT0Sealed,
    normalise_selection_account,
    pre_t0_sealed,
    require_pre_t0_int,
)
from .provenance import Origin
from .snapshot import PreT0Snapshot, require_verified_snapshot

#: The witness ``__post_init__`` stamps on every row and every artifact it actually ran on.
#:
#: Compared by identity in :func:`require_sealed_artifact`. Its whole job is to be a thing that
#: **cannot be derived from the fields**: an attacker who assembles an object out of plausible
#: values still has to produce this exact object, and no arrangement of ``rank``, ``wallet``,
#: ``value``, ``valid_buys`` and ``account_type`` yields it.
#:
#: It is not a capability boundary and this module does not claim it is — any code running in this
#: interpreter can import a private name, and unpickling untrusted bytes is arbitrary code execution
#: before it is anything else. What it closes is the route that was measured: ``object.__new__`` and
#: a dict update, which produce an object every ``type(x) is`` check accepts.
_CONSTRUCTED = object()

#: Bump when the artifact payload changes shape. Hashed into ``artifact_hash``, so an artifact
#: written under an older version fails verification rather than being reinterpreted by a reader
#: that expects the new shape.
ARTIFACT_SCHEMA_VERSION = "selected-wallet-artifact-v1"

#: The four facts every artifact must carry and be checked for before ranking. Named as data so the
#: test that asserts the requirement and the code that enforces it read from one list.
REQUIRED_ARTIFACT_FACTS = ("provenance", "window_id", "cutoff_block", "dataset_hash")


class ArtifactRefused(ContractError):
    """An artifact was assembled without valid provenance, or does not hash to what it claims."""


class ArtifactSealed(ContractError):
    """A sealed artifact was asked to change, or to be re-ranked.

    Raised for ``dataclasses.replace``, for a rebuilt copy whose hash disagrees, and for any attempt
    to reorder the selections. §6.4's basket is the top of a ranking that has already happened; a
    re-rank after the fact is a second selection wearing the first one's identity.
    """


class PickleRefused(ContractError):
    """Pickle is not a serialization format for anything in this package.

    ``pickle.loads`` reconstructs an object by writing its ``__dict__`` or calling ``__setstate__``.
    Neither runs ``__post_init__``, so every construction invariant in this package — the T0 checks,
    the provenance checks, the hash checks — is bypassed by a round trip. The refusal is on the type
    rather than in a code-review rule because ``pickle`` appeared nowhere in ``src/`` or ``tests/``
    before this file, which meant it was *unforbidden* rather than forbidden.
    """


def _decimal_text(text: str) -> Decimal:
    """A published ``value`` string as a number, for the ordering check and for nothing else.

    A string comparison would be wrong the moment two values have different digit counts, and no
    arithmetic happens here: ``Decimal.__gt__`` is exact and consults no context, which is why
    ``tests/test_frozen_context.py`` does not flag comparisons.
    """
    try:
        return Decimal(text)
    except Exception:
        raise ArtifactRefused(
            "a published value must be a canonical decimal string; got {!r}. The rows carry "
            "strings because an artifact is a serialization boundary, and a string nobody can read "
            "back as a number is not a measurement.".format(text)
        )


def require_constructed_row(row: "SelectedWallet", what: str) -> "SelectedWallet":
    """Refuse a row that never ran :meth:`SelectedWallet.__post_init__`.

    ``object.__new__(SelectedWallet)`` followed by ``__dict__.update`` satisfies ``type(x) is
    SelectedWallet`` and every ``getattr`` a reader makes, and it ran none of the bounds. This is
    the check that tells the two apart, and it is stated as a function so the artifact's own
    ``__post_init__`` and :func:`require_sealed_artifact` cannot come to disagree about it.
    """
    if getattr(row, "_construction_witness", None) is not _CONSTRUCTED:
        raise ArtifactRefused(
            "{} holds a SelectedWallet that was never constructed: it carries no construction "
            "witness, so none of its bounds ran. An object assembled with object.__new__ and a "
            "dict update satisfies every type check in this file and can publish any rank, any "
            "wallet and any count at all.".format(what)
        )
    return row


@pre_t0_sealed
@dataclass(frozen=True)
class SelectedWallet(PreT0Sealed):
    """One row of the sealed artifact, in primitives only.

    ``value`` is a canonical decimal string. ``account_type`` is the enum's frozen ``value`` rather
    than the enum, for the same reason: an artifact that carried live objects would let the
    evaluation side import the selection side to read them.
    """

    rank: int
    wallet: str
    value: str
    valid_buys: int
    account_type: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "wallet", normalise_selection_account(self.wallet))
        for name in ("rank", "valid_buys"):
            value = require_pre_t0_int(getattr(self, name), "SelectedWallet.{}".format(name))
            if value < 0:
                raise ArtifactRefused("SelectedWallet.{} is {}".format(name, value))
        if self.rank < 1:
            raise ArtifactRefused("a rank is 1-based; got {}".format(self.rank))
        if not VALID_BUY_FLOOR <= self.valid_buys <= VALID_BUY_CEILING:
            raise ArtifactRefused(
                "SelectedWallet.valid_buys is {} and §6.2's eligible band is [{}, {}]. A published "
                "row cannot claim a count no member of the universe could hold: the bound is on "
                "universe.freeze.UniverseMember and on universe.ranking.PreT0Score, and its absence "
                "here is what let a forged rank-1 row carry a billion buys.".format(
                    self.valid_buys, VALID_BUY_FLOOR, VALID_BUY_CEILING)
            )
        for name in ("value", "account_type"):
            text = getattr(self, name)
            if not isinstance(text, str) or not text.strip():
                raise ArtifactRefused(
                    "SelectedWallet.{} must be a non-empty string in the sealed artifact; a live "
                    "Decimal or enum here would mean the evaluation side holds selection-side "
                    "machinery".format(name)
                )
            object.__setattr__(self, name, text.strip())
        object.__setattr__(self, "_construction_witness", _CONSTRUCTED)

    def __reduce__(self) -> object:
        raise PickleRefused(
            "SelectedWallet cannot be pickled. Unpickling would rebuild this row without running "
            "the checks above, which is the whole of what those checks are."
        )

    def __setstate__(self, state: object) -> None:
        raise PickleRefused(
            "SelectedWallet cannot be unpickled. __reduce__ binds the dumps direction only, and the "
            "attack arrives as bytes: a payload written by hand names this class and hands it a "
            "state dictionary, and no check in this file has run by the time it does."
        )


@pre_t0_sealed
@dataclass(frozen=True)
class SelectedWalletArtifact(PreT0Sealed):
    """The sealed, hashed, schema-versioned selection result.

    The four required facts are fields, so an artifact missing one is not constructible.
    ``artifact_hash`` is recomputed in ``__post_init__`` and compared, so an artifact whose rows were
    edited after sealing — including by ``dataclasses.replace``, which re-runs ``__post_init__`` with
    the old hash — is refused at the point somebody tries to use it.
    """

    provenance: Origin
    window_id: str
    cutoff_block: int
    dataset_hash: str
    snapshot_hash: str
    step0_digest: str
    metric: str
    seed: int
    commit: str
    eligible_universe_size: int
    requested_count: int
    unscorable_count: int
    short_by: int
    selections: Tuple[SelectedWallet, ...]
    artifact_hash: str
    schema_version: str = ARTIFACT_SCHEMA_VERSION
    universe_schema_version: str = UNIVERSE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "selections", tuple(self.selections))

        if type(self.provenance) is not Origin:
            raise ArtifactRefused(
                "the artifact's provenance must be a universe.provenance.Origin, got {}. A bare "
                "string here would let 'PRE_T0' be written by anybody, which is a label rather "
                "than a claim the lattice made.".format(type(self.provenance).__name__)
            )
        if self.provenance is not Origin.PRE_T0:
            raise ArtifactRefused(
                "the artifact carries provenance {} and is refused before ranking. Only PRE_T0 is "
                "publishable: POST_T0 and CONTAMINATED both describe a selection decided on "
                "information after T0, and neither is repaired by being recorded.".format(
                    self.provenance.value)
            )
        for name in ("window_id", "dataset_hash", "snapshot_hash", "step0_digest", "metric",
                     "commit", "schema_version", "universe_schema_version", "artifact_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ArtifactRefused(
                    "a sealed artifact must state its {}. The four required facts are {}, and the "
                    "hashes beside them are what make an artifact checkable by somebody who did "
                    "not run it.".format(name, ", ".join(REQUIRED_ARTIFACT_FACTS))
                )
            object.__setattr__(self, name, value.strip())
        for name in ("cutoff_block", "seed", "eligible_universe_size", "requested_count",
                     "unscorable_count", "short_by"):
            require_pre_t0_int(getattr(self, name), "SelectedWalletArtifact.{}".format(name))
        if self.cutoff_block <= 0:
            raise ArtifactRefused(
                "the artifact's cutoff_block is {}; a non-positive cutoff is not an instant on this "
                "chain and every isolation claim is measured against it".format(self.cutoff_block)
            )
        if self.schema_version != ARTIFACT_SCHEMA_VERSION:
            raise ArtifactRefused(
                "the artifact is schema {!r} and this code writes {!r}. An artifact from another "
                "schema is re-derived, never reinterpreted.".format(
                    self.schema_version, ARTIFACT_SCHEMA_VERSION)
            )

        seen = set()
        previous = None
        for index, row in enumerate(self.selections, start=1):
            if type(row) is not SelectedWallet:
                raise ArtifactRefused(
                    "the artifact holds SelectedWallet rows, got {}. type(...) is, not isinstance: "
                    "a subclass carrying an extra field is exactly how a forward return entered a "
                    "published basket in the audit.".format(type(row).__name__)
                )
            require_constructed_row(row, "the sealed artifact")
            if row.rank != index:
                raise ArtifactSealed(
                    "the artifact's ranks are {} at position {}. Ranks are 1..n and contiguous; a "
                    "gap or a repeat means the order published is not the order selected, which is "
                    "a re-rank.".format(row.rank, index)
                )
            if row.wallet in seen:
                raise ArtifactRefused(
                    "{} appears twice in the sealed artifact".format(row.wallet))
            seen.add(row.wallet)
            # §6.4's basket is the top of a descending ranking. ``universe.select.SelectedBasket``
            # has held this check since ticket 28; the artifact — the only object that crosses to
            # evaluation — did not, so two rows could be swapped, re-hashed with this module's own
            # public factory, and published in an order contradicting their own values.
            if previous is not None and _decimal_text(row.value) > _decimal_text(previous.value):
                raise ArtifactSealed(
                    "{} is published at rank {} with {} above the {} at rank {}. The artifact is "
                    "the top of a descending ranking; an inversion means the order published is "
                    "not the order the metric produced, and re-hashing the rows does not make it "
                    "one.".format(row.wallet, row.rank, row.value, previous.value, previous.rank)
                )
            previous = row

        if len(self.selections) + self.short_by != self.requested_count:
            raise ArtifactRefused(
                "the artifact holds {} wallet(s) and reports short_by {} against a requested {}; "
                "the shortfall is a status that has to add up".format(
                    len(self.selections), self.short_by, self.requested_count)
            )

        recomputed = artifact_hash_of(self)
        if self.artifact_hash != recomputed:
            raise ArtifactSealed(
                "the artifact claims hash {} and its own contents hash to {}. Something changed "
                "after it was sealed — dataclasses.replace, an object.__setattr__, or a rebuilt "
                "copy with one field edited. A sealed artifact cannot be modified or re-ranked; the "
                "run that produced it must be re-run, not patched.".format(
                    self.artifact_hash, recomputed)
            )
        object.__setattr__(self, "_construction_witness", _CONSTRUCTED)

    @property
    def wallets(self) -> Tuple[str, ...]:
        """The selected wallets in rank order."""
        return tuple(row.wallet for row in self.selections)

    def canonical_json(self) -> str:
        """The artifact as deterministic JSON — the one serialization format it has.

        A ``str`` rather than a mapping, deliberately: handing back a live ``dict`` would give a
        caller a mutable copy of the payload the hash was taken over, and the next edit would be to
        that copy rather than to the artifact that refuses it.
        """
        return to_canonical_json(_artifact_payload(self))

    def verify(self) -> "SelectedWalletArtifact":
        """Re-run every invariant against the fields currently held, and return ``self``.

        Each row is rebuilt **through its own constructor** rather than handed back as the instance
        it already is. Passing built objects into a constructor re-runs none of their checks, and
        that is what let a row assembled with ``object.__new__`` reach publication carrying a count
        no member of the universe could hold. ``universe.freeze.FrozenUniverse.verify`` has rebuilt
        its members this way since ticket 26; the two had no business disagreeing.
        """
        rebuilt = tuple(
            SelectedWallet(rank=row.rank, wallet=row.wallet, value=row.value,
                           valid_buys=row.valid_buys, account_type=row.account_type)
            for row in self.selections
        )
        fields = {name: getattr(self, name) for name in self.__dataclass_fields__}
        fields["selections"] = rebuilt
        SelectedWalletArtifact(**fields)
        return self

    def __reduce__(self) -> object:
        raise PickleRefused(
            "SelectedWalletArtifact cannot be pickled. A pickled artifact is an artifact whose "
            "provenance check, hash check and rank check are all performed by the attacker's own "
            "bytes. Write it with contracts.to_canonical_json and read it back through "
            "universe.artifact — canonical, schema-versioned, and hashed."
        )

    def __setstate__(self, state: object) -> None:
        raise PickleRefused(
            "SelectedWalletArtifact cannot be unpickled. __reduce__ refuses the dumps direction and "
            "the attack arrives as bytes: a hand-written payload names this class and hands it a "
            "state dictionary, at which point nothing in this file has run."
        )


def _payload_of_facts(provenance: Origin, window_id: str, cutoff_block: int, dataset_hash: str,
                      snapshot_hash: str, step0_digest: str, metric: str, seed: int, commit: str,
                      eligible_universe_size: int, requested_count: int, unscorable_count: int,
                      short_by: int, selections: Tuple[SelectedWallet, ...], schema_version: str,
                      universe_schema_version: str):
    """The hashed payload, from the facts rather than from an assembled artifact.

    Written this way so :func:`sealed_artifact` and :func:`artifact_hash_of` hash the *same*
    expression. Two spellings of one payload is how a factory and a verifier come to disagree, and
    the disagreement would present as an artifact that refuses itself at construction.

    The parameters are annotated even though the function is private, because rule 5 of
    ``tests/test_signature_barrier.py`` exempts a private helper from *saying* what it takes without
    changing what it takes. The **return** deliberately carries no annotation: it is the JSON
    payload on its way into :func:`contracts.canonical_hash`, and every honest spelling of it is a
    keyed container — which rule 4 forbids on a selection path, and rightly, since a value addressed
    by a string is not a value addressed by a type. The mapping never escapes this module:
    both callers hand it straight to a ``contracts`` serializer, and the two public functions built
    on it, :func:`artifact_hash_of` and :meth:`SelectedWalletArtifact.canonical_json`, return ``str``.
    :mod:`universe.snapshot` writes the same shape as an unnamed literal inside
    :func:`universe.snapshot.snapshot_evidence_hash` for the same reason.
    """
    return {
        "schema_version": schema_version,
        "universe_schema_version": universe_schema_version,
        "provenance": provenance.value,
        "window_id": window_id,
        "cutoff_block": cutoff_block,
        "dataset_hash": dataset_hash,
        "snapshot_hash": snapshot_hash,
        "step0_digest": step0_digest,
        "metric": metric,
        "seed": seed,
        "commit": commit,
        "eligible_universe_size": eligible_universe_size,
        "requested_count": requested_count,
        "unscorable_count": unscorable_count,
        "short_by": short_by,
        "selections": [
            [row.rank, row.wallet, row.value, row.valid_buys, row.account_type]
            for row in selections
        ],
    }


def _artifact_payload(artifact: SelectedWalletArtifact):
    """Everything the hash covers, excluding the hash itself.

    Returns whatever :func:`_payload_of_facts` returns, and carries no return annotation for the
    reason stated there.

    Excluding it is not a convenience: a hash that covered itself would have no fixed point, and one
    that covered a *stored* copy of itself would be trivially satisfiable by writing the same wrong
    value in both places.
    """
    return _payload_of_facts(
        artifact.provenance, artifact.window_id, artifact.cutoff_block, artifact.dataset_hash,
        artifact.snapshot_hash, artifact.step0_digest, artifact.metric, artifact.seed,
        artifact.commit, artifact.eligible_universe_size, artifact.requested_count,
        artifact.unscorable_count, artifact.short_by, artifact.selections,
        artifact.schema_version, artifact.universe_schema_version,
    )


def artifact_hash_of(artifact: SelectedWalletArtifact) -> str:
    """The canonical hash of an artifact's contents. What ``artifact_hash`` must equal."""
    return canonical_hash(_artifact_payload(artifact))


def sealed_artifact(window_id: str, cutoff_block: int, dataset_hash: str, snapshot_hash: str,
                    step0_digest: str, metric: str, seed: int, commit: str,
                    eligible_universe_size: int, requested_count: int, unscorable_count: int,
                    short_by: int,
                    selections: Tuple[SelectedWallet, ...]) -> SelectedWalletArtifact:
    """Produce the artifact **and** its hash in one act — steps 3 and 4, which do not separate.

    An artifact that exists un-hashed for even one statement is an artifact somebody can edit before
    the hash is taken, so there is deliberately no way to build one and hash it later: the only
    ``artifact_hash`` this module will accept is the one over its own contents, and
    ``__post_init__`` recomputes it.

    Explicit keyword parameters rather than a payload mapping, on
    :func:`universe.snapshot.snapshot_evidence_hash`'s ground: adding a fact to a sealed artifact
    should be a signature change every caller has to acknowledge, not a key somebody forgot.

    ``provenance`` is not a parameter. :attr:`universe.provenance.Origin.PRE_T0` is the only value
    :class:`SelectedWalletArtifact` accepts, so offering the field here would be offering a slot for
    a claim the type refuses anyway — and a caller who could pass it could pass the other two.

    What this does **not** check: whether the ``value`` strings describe pre-T0 measurements. This
    function sees primitives. The provenance gate lives one call earlier, in
    :func:`universe.select.seal_selection`, which holds the ranking inputs and can re-derive it.
    """
    rows = tuple(selections)
    return SelectedWalletArtifact(
        provenance=Origin.PRE_T0,
        window_id=window_id,
        cutoff_block=cutoff_block,
        dataset_hash=dataset_hash,
        snapshot_hash=snapshot_hash,
        step0_digest=step0_digest,
        metric=metric,
        seed=seed,
        commit=commit,
        eligible_universe_size=eligible_universe_size,
        requested_count=requested_count,
        unscorable_count=unscorable_count,
        short_by=short_by,
        selections=rows,
        artifact_hash=canonical_hash(_payload_of_facts(
            Origin.PRE_T0, window_id, cutoff_block, dataset_hash, snapshot_hash, step0_digest,
            metric, seed, commit, eligible_universe_size, requested_count, unscorable_count,
            short_by, rows, ARTIFACT_SCHEMA_VERSION, UNIVERSE_SCHEMA_VERSION,
        )),
    )


def require_sealed_artifact(artifact: SelectedWalletArtifact,
                            what: str) -> SelectedWalletArtifact:
    """The gate every consumer runs: exact type, four facts present, hash re-derived.

    ``type(x) is`` rather than ``isinstance``: a subclass is refused at class-definition time, so
    the two agree today — and "they agree today" is the property this package has already been
    burned by.

    The type check alone is not enough and was measured not to be: ``object.__new__`` satisfies it
    exactly, and a payload written by hand rebuilt a two-hundred-and-fifty-row artifact that this
    function accepted. So the construction witness is checked too, on the artifact and on every row.
    """
    if type(artifact) is not SelectedWalletArtifact:
        raise ArtifactRefused(
            "{} needs a sealed SelectedWalletArtifact, got {}. A live SelectedBasket is not "
            "accepted here: it is re-rankable, its fields are live objects, and it carries no "
            "hash anybody can check it against.".format(what, type(artifact).__name__)
        )
    if getattr(artifact, "_construction_witness", None) is not _CONSTRUCTED:
        raise ArtifactRefused(
            "{}: the artifact carries no construction witness, so SelectedWalletArtifact."
            "__post_init__ never ran on it. Every refusal in this file lives in that method, and an "
            "object built around it — by object.__new__, or by bytes naming this class — satisfies "
            "type(x) is SelectedWalletArtifact while having been checked for nothing.".format(what)
        )
    for row in getattr(artifact, "selections", ()):
        if type(row) is not SelectedWallet:
            raise ArtifactRefused(
                "{}: the artifact holds a {} where a SelectedWallet belongs".format(
                    what, type(row).__name__))
        require_constructed_row(row, what)
    missing = [name for name in REQUIRED_ARTIFACT_FACTS if not getattr(artifact, name, None)]
    if missing:
        raise ArtifactRefused(
            "{}: the artifact is missing required fact(s) {}".format(what, ", ".join(missing)))
    artifact.verify()
    return artifact


def artifact_from_snapshot_facts(snapshot: PreT0Snapshot, window_id: str) -> Tuple[str, int]:
    """The two facts an artifact inherits from the snapshot it was selected against.

    :returns: ``(snapshot_hash, cutoff_block)``.

    A function rather than two attribute reads at the call site, so that an artifact built against a
    snapshot for a *different* window is refused here instead of carrying a cutoff nobody compared.
    """
    require_verified_snapshot(snapshot, "sealing an artifact")
    if snapshot.window_id != window_id:
        raise ArtifactRefused(
            "the snapshot is for window {!r} and the artifact is for {!r}. The cutoff an artifact "
            "publishes has to be the cutoff its own data was truncated at.".format(
                snapshot.window_id, window_id)
        )
    return snapshot.snapshot_hash, snapshot.cutoff_block
