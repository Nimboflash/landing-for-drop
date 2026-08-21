"""Physical access ordering: forward data becomes reachable only after the artifact is sealed.

The eight steps, from the brief, in the order they are enforced here::

    1. Mount only pre-T0 snapshot
    2. Run selection process
    3. Produce canonical selected-wallet artifact
    4. Hash and seal artifact
    5. Terminate selection process
    6. Unmount pre-T0 workspace
    7. Mount forward dataset
    8. Run evaluation in a new process

The audit's finding was not that these were in the wrong order. It was that they were not an order
at all: five ``ForwardActivity`` records were constructed *before* any ``FrozenUniverse``, any
basket and any hash existed, stayed live in memory through ``freeze_universe`` and
``rank_and_select``, and were then read during selection and ranked on. ``snapshot_id`` was a string
the caller typed, and nothing validated it against a produced artifact.

:class:`ExecutionOrder` is the state machine that makes that unwritable. Its two load-bearing
properties:

* **A forward dataset cannot be mounted before an artifact is sealed and the pre-T0 workspace
  unmounted.** :meth:`ExecutionOrder.mount_forward` refuses at every earlier phase.
* **Selection cannot run after a forward dataset is mounted.**
  :meth:`ExecutionOrder.require_selection_permitted` raises ``LookAheadViolation`` *and* invalidates
  the run through :class:`universe.containment.LookAheadContainment`, so the refusal is not a thing
  the caller can retry past.

The gate is an argument, not a machine standing beside one
-----------------------------------------------------------

The first version of this module had both properties and enforced neither, for one reason: nothing
called :meth:`ExecutionOrder.require_selection_permitted`. ``rank_and_select`` took a
:class:`universe.freeze.FrozenUniverse` and had no way to reach an order, so an attacker could walk
all eight steps honestly, read post-T0 activity through the sanctioned reader, and then simply call
``rank_and_select`` again with a different seed — measured: ten of two hundred and fifty selected
wallets swapped for wallets with higher post-T0 activity, nothing raised, phase still
``FORWARD_MOUNTED``.

What closes that is not another check. It is that **the ranked universe is only obtainable from a
mounted workspace**: :meth:`ExecutionOrder.mount_pre_t0` takes the snapshot *and* the universe and
hands back a :class:`PreT0Workspace`, and :meth:`PreT0Workspace.selection_universe` — the one route
to the :class:`~universe.freeze.FrozenUniverse` — runs the gate on every call. A selection function
therefore cannot be written without an order in scope, because it cannot obtain its own first
argument without one.

The same reasoning applies at the other end. :class:`PreT0Workspace` and :class:`ForwardMount` both
refuse construction without a module-private token that only :class:`ExecutionOrder` holds, so
naming the class is not a way around the phase machine.

Step 8, honestly
----------------

This is one interpreter. A state machine inside it is not an OS process boundary, and saying
otherwise would be the overclaim this codebase's docstrings are written to avoid. What is enforced:

* the process id at seal time is recorded, and :meth:`ExecutionOrder.mount_forward` **refuses to
  mount in that same process** unless the caller passed ``same_process_evaluation_declared=True``
  when constructing the order. The escape exists because the test suite and any single-process
  composition root need it; it is a constructor argument rather than a default so that using it is
  a decision visible in the call, not an omission;
* on :meth:`ExecutionOrder.unmount_pre_t0` the order **drops its references** to the workspace and
  the snapshot, and :class:`PreT0Workspace` raises on every read afterwards. So "both datasets in
  memory at once" is at least not true *through this seam*.

What remains outside it: a caller that kept its own reference to a ``FrozenUniverse`` before
unmounting still holds it. Closing that needs two processes and a file, and the file is ticket 29's
composition root to write. What this module buys is that the handoff has exactly one shape and that
shape has an order.
"""

import os
from enum import Enum
from typing import Optional, Tuple

from contracts import ContractError, LookAheadViolation

from .artifact import SelectedWalletArtifact, artifact_hash_of, require_sealed_artifact
from .containment import LookAheadContainment
from .freeze import FrozenUniverse
from .snapshot import PreT0Snapshot, require_verified_snapshot


class _OrderToken(object):
    """The type of the one key :class:`ExecutionOrder` holds. One instance, compared by identity.

    A nominal type rather than a bare ``object()`` sentinel so that the two constructors it gates
    can *say* what they take: ``token: _OrderToken`` is a signature a reader can check, and
    ``tests/test_signature_barrier.py`` refuses ``object`` in a parameter slot for exactly the
    reason that makes it right here — a slot annotated ``object`` accepts everything.
    """

    __slots__ = ()


#: The key :class:`ExecutionOrder` holds and nobody else is handed.
#:
#: :class:`PreT0Workspace` and :class:`ForwardMount` are the two objects whose *existence* is the
#: proof that a step happened — the workspace proves step 1, the mount proves steps 1-6 — and a
#: proof anybody can construct by naming a class proves nothing. Both refuse a caller that does not
#: present this object, compared by identity, so the only route to either is through the phase
#: machine that maintains them.
#:
#: An in-process token is not a capability boundary and this module does not claim it is: anything
#: running in this interpreter can import a private name. What it buys is that the two classes
#: cannot be constructed by *ordinary* code — the spelling ``ForwardMount(artifact, id, hash)``,
#: which was the measured bypass, no longer exists.
_ORDER_TOKEN = _OrderToken()


class Phase(str, Enum):
    """Where a run is in the eight steps. Monotone: there is no transition that goes back."""

    UNMOUNTED = "UNMOUNTED"
    PRE_T0_MOUNTED = "PRE_T0_MOUNTED"
    ARTIFACT_SEALED = "ARTIFACT_SEALED"
    SELECTION_TERMINATED = "SELECTION_TERMINATED"
    PRE_T0_UNMOUNTED = "PRE_T0_UNMOUNTED"
    FORWARD_MOUNTED = "FORWARD_MOUNTED"


#: The order the phases may be entered in. Index in this tuple is the only ordering that exists —
#: ``phase0.governance.ORDER``'s pattern, one layer down and for one run's data access.
PHASE_ORDER = (
    Phase.UNMOUNTED,
    Phase.PRE_T0_MOUNTED,
    Phase.ARTIFACT_SEALED,
    Phase.SELECTION_TERMINATED,
    Phase.PRE_T0_UNMOUNTED,
    Phase.FORWARD_MOUNTED,
)


class OrderingViolation(ContractError):
    """A step was taken out of order, or a mount was asked for that the phase does not permit."""


class WorkspaceUnmounted(LookAheadViolation):
    """The pre-T0 workspace was read after it was unmounted.

    A :class:`contracts.LookAheadViolation` rather than a plain error: reading selection data after
    the forward dataset is available is the shape the ordering exists to stop, and the run that did
    it is void.
    """


class SelectionAfterForwardMount(LookAheadViolation):
    """Selection was asked to run once the forward dataset was reachable.

    The single most valuable refusal in this file. A re-run after the forward dataset is available
    produces a basket that *looks* identical to a legitimate one and was chosen by somebody who had
    already seen the answer.
    """


class PreT0Workspace(object):
    """The mounted pre-T0 data — the snapshot **and** the universe — that stops answering on unmount.

    Not a dataclass and not frozen-with-a-flag: both references are dropped on unmount, so there is
    nothing left to read rather than a boolean somebody could flip back.

    It holds the :class:`~universe.freeze.FrozenUniverse` because that is what makes the ordering
    barrier load-bearing. :meth:`selection_universe` is the only route to the universe anywhere in
    this package, and it runs :meth:`ExecutionOrder.require_selection_permitted` first — so
    "selection ran after the forward dataset was mounted" is not a rule a selection function has to
    remember to check, it is a value it cannot obtain.

    Constructible only by :meth:`ExecutionOrder.mount_pre_t0`, which is the only holder of
    :data:`_ORDER_TOKEN`.
    """

    __slots__ = ("_snapshot", "_universe", "_window_id", "_order")

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise OrderingViolation(
            "{} derives from PreT0Workspace. A subclass could keep the snapshot alive across an "
            "unmount while remaining an isinstance of the handle everything else "
            "checks.".format(cls.__name__)
        )

    def __init__(self, token: _OrderToken, order: "ExecutionOrder", snapshot: PreT0Snapshot,
                 universe: FrozenUniverse) -> None:
        if token is not _ORDER_TOKEN:
            raise OrderingViolation(
                "PreT0Workspace cannot be constructed directly. A workspace is the proof that step "
                "1 happened, and a proof anybody can build by naming the class proves nothing — "
                "the measured bypass was exactly this shape one class over. Obtain one from "
                "ExecutionOrder.mount_pre_t0(snapshot, universe)."
            )
        if type(snapshot) is not PreT0Snapshot:
            raise OrderingViolation(
                "a pre-T0 workspace mounts a verified PreT0Snapshot, got {}. Mounting anything "
                "else would make step 1 a name rather than a check.".format(
                    type(snapshot).__name__)
            )
        if type(universe) is not FrozenUniverse:
            raise OrderingViolation(
                "a pre-T0 workspace mounts the FrozenUniverse selection will rank, got {}. The "
                "universe is mounted here rather than passed to the ranking function so that the "
                "ranking function cannot be called without an order in scope.".format(
                    type(universe).__name__)
            )
        self._snapshot = snapshot
        self._universe = universe
        self._window_id = snapshot.window_id
        self._order = order

    @property
    def window_id(self) -> str:
        """Readable after unmount: it names *which* workspace this was, not what was in it."""
        return self._window_id

    @property
    def mounted(self) -> bool:
        return self._snapshot is not None

    def snapshot(self) -> PreT0Snapshot:
        """The mounted snapshot.

        :raises WorkspaceUnmounted: after :meth:`unmount`. The run is void if anything reads here
            once the forward dataset can exist.
        """
        if self._snapshot is None:
            raise WorkspaceUnmounted(
                "the pre-T0 workspace for window {} was unmounted and cannot be read. Step 6 comes "
                "before step 7 precisely so that no code path holds both datasets: a read here is "
                "selection-side data being reached for at a point in the run where forward data "
                "exists.".format(self._window_id)
            )
        return self._snapshot

    def selection_universe(self, what: str) -> FrozenUniverse:
        """The frozen universe, **after** the ordering gate. The only route to it in this package.

        :raises universe.ordering.SelectionAfterForwardMount: if the forward dataset is mounted.
        :raises OrderingViolation: at any phase other than ``PRE_T0_MOUNTED``.
        :raises WorkspaceUnmounted: after step 6.

        Both refusals invalidate the run first, so a caller who catches one and retries meets
        :class:`universe.containment.RunInvalidated` instead of a second chance.
        """
        self._order.require_selection_permitted(what)
        if self._universe is None:
            raise WorkspaceUnmounted(
                "the pre-T0 workspace for window {} was unmounted and its universe cannot be "
                "ranked. Selection runs between step 1 and step 4; a ranking asked for here is one "
                "asked for at a point in the run where forward data can exist.".format(
                    self._window_id)
            )
        return self._universe

    def unmount(self) -> None:
        """Drop both references. Idempotent, and there is no remount."""
        self._snapshot = None
        self._universe = None


class ForwardMount(object):
    """Proof that steps 1-6 happened, and the only route by which forward data may be opened.

    Carries the sealed artifact rather than a reference to anything selection-side. The evaluation
    entry point takes one of these, so "the forward dataset opened after the artifact was sealed" is
    an argument it cannot be called without.

    Constructible only by :meth:`ExecutionOrder.mount_forward`. It was not, and the consequence was
    measured: ``ForwardMount(artifact, dataset_id, dataset_hash)`` written out at phase
    ``ARTIFACT_SEALED`` ran evaluation with the pre-T0 workspace still live, and the order never
    learned a mount existed.

    ``sealed_hash`` is the hash :meth:`ExecutionOrder.seal` **saw**, kept separately from the
    artifact. :attr:`artifact` compares the two on every read, so the gate is "this is the artifact
    step 4 sealed" rather than "this artifact is internally consistent" — the second is satisfiable
    by anybody who edits a row and recomputes the hash with this package's own public function, and
    that too was measured.
    """

    __slots__ = ("_artifact", "_dataset_id", "_dataset_hash", "_pid", "_sealed_hash")

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise OrderingViolation(
            "{} derives from ForwardMount. A subclass could hand back an artifact that never went "
            "through require_sealed_artifact.".format(cls.__name__)
        )

    def __init__(self, token: _OrderToken, artifact: SelectedWalletArtifact, dataset_id: str,
                 dataset_hash: str, sealed_hash: str) -> None:
        if token is not _ORDER_TOKEN:
            raise OrderingViolation(
                "ForwardMount cannot be constructed directly. A mount is the proof that steps 1-6 "
                "happened; one built by naming the class proves only that somebody named the class, "
                "and evaluation would run with the pre-T0 workspace still mounted. Obtain one from "
                "ExecutionOrder.mount_forward(dataset_id, dataset_hash)."
            )
        require_sealed_artifact(artifact, "mounting a forward dataset")
        for name, value in (("dataset_id", dataset_id), ("dataset_hash", dataset_hash)):
            if not isinstance(value, str) or not value.strip():
                raise OrderingViolation(
                    "a forward mount must name its {}; an unnamed forward dataset cannot be "
                    "matched to the evaluation it produced".format(name)
                )
        if not isinstance(sealed_hash, str) or sealed_hash != artifact.artifact_hash:
            raise OrderingViolation(
                "the mount was given sealed hash {!r} and the artifact claims {!r}. The mount "
                "carries the hash step 4 recorded so that the artifact reaching evaluation is the "
                "one that was sealed, not merely one that hashes to its own "
                "contents.".format(sealed_hash, artifact.artifact_hash)
            )
        self._artifact = artifact
        self._dataset_id = dataset_id.strip()
        self._dataset_hash = dataset_hash.strip()
        self._sealed_hash = sealed_hash
        self._pid = os.getpid()

    @property
    def artifact(self) -> SelectedWalletArtifact:
        """The sealed artifact, re-checked against the hash step 4 recorded, on every read.

        :raises OrderingViolation: if the artifact's contents no longer hash to what step 4 saw.
            Checked here rather than once at construction because the mount holds a live object:
            an edit made *after* the mount was built, with ``artifact_hash`` recomputed by
            :func:`universe.artifact.artifact_hash_of`, is self-consistent and would otherwise pass
            every gate downstream.
        """
        artifact = self._artifact
        require_sealed_artifact(artifact, "reading the sealed artifact from a forward mount")
        current = artifact_hash_of(artifact)
        if current != self._sealed_hash or artifact.artifact_hash != self._sealed_hash:
            raise OrderingViolation(
                "the artifact on this mount hashes to {} and step 4 sealed {}. A sealed artifact "
                "that changed after it was mounted is a re-rank wearing the first selection's "
                "identity; recomputing artifact_hash restores self-consistency and does not restore "
                "the seal. The run must be re-run, not patched.".format(
                    current, self._sealed_hash)
            )
        return artifact

    @property
    def dataset_id(self) -> str:
        return self._dataset_id

    @property
    def dataset_hash(self) -> str:
        return self._dataset_hash

    @property
    def process_id(self) -> int:
        """The process the forward dataset was mounted in. Recorded so step 8 is checkable."""
        return self._pid


class ExecutionOrder(object):
    """The eight steps as a monotone state machine, bound to one run's containment.

    Every refusal here also **invalidates the run**, because every one of them describes a program
    that has already seen something it must not have. A refusal that merely raised would leave the
    caller free to try a different spelling.
    """

    __slots__ = ("_containment", "_phase", "_workspace", "_artifact", "_mount",
                 "_seal_pid", "_same_process_declared", "_sealed_hash")

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise OrderingViolation(
            "{} derives from ExecutionOrder. A subclass could override "
            "require_selection_permitted() and let a re-run happen after the forward dataset was "
            "mounted, which is the one thing this class exists to refuse.".format(cls.__name__)
        )

    def __init__(self, containment: LookAheadContainment,
                 same_process_evaluation_declared: bool = False) -> None:
        if type(containment) is not LookAheadContainment:
            raise OrderingViolation(
                "an execution order is bound to a LookAheadContainment, got {}. Without one a "
                "breach would raise and stop nothing: the point is that the run is "
                "void.".format(type(containment).__name__)
            )
        if not isinstance(same_process_evaluation_declared, bool):
            raise TypeError("same_process_evaluation_declared must be a bool")
        self._containment = containment
        self._phase = Phase.UNMOUNTED
        self._workspace = None
        self._artifact = None
        self._mount = None
        self._seal_pid = None
        self._same_process_declared = same_process_evaluation_declared
        self._sealed_hash = None

    # -- queries --

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def containment(self) -> LookAheadContainment:
        return self._containment

    @property
    def forward_reachable(self) -> bool:
        """Whether forward data may be opened at all. False until step 7 has happened."""
        return self._phase is Phase.FORWARD_MOUNTED

    def _advance(self, to_phase: Phase) -> None:
        here = PHASE_ORDER.index(self._phase)
        target = PHASE_ORDER.index(to_phase)
        if target != here + 1:
            self._containment.invalidate(
                "execution order: {} -> {} is not the next step".format(
                    self._phase.value, to_phase.value)
            )
            raise OrderingViolation(
                "the run is at {} and was asked to move to {}. The eight steps run in one order and "
                "the order is the barrier: {}. The run is invalidated rather than nudged into "
                "place.".format(
                    self._phase.value, to_phase.value,
                    " -> ".join(phase.value for phase in PHASE_ORDER))
            )
        self._phase = to_phase

    # -- steps 1 and 2 --

    def mount_pre_t0(self, snapshot: PreT0Snapshot,
                     universe: FrozenUniverse) -> PreT0Workspace:
        """Step 1. Mount the verified pre-T0 snapshot and the universe it truncates, and nothing else.

        The two arrive together and are **compared here**, which is the earliest point both exist:

        * ``snapshot.window_id`` must be the universe's window, and
        * ``snapshot.t0_block`` must be that window's ``T0`` block.

        Without the second comparison the whole ``max_block < t0_block`` apparatus proves only that
        a snapshot is self-consistent about a cutoff the caller chose. Measured: a snapshot built
        from rows at ``T0 + 500,000`` and ``T0 + 999,999``, declaring ``t0_block = T0 + 1,000,000``,
        reported ``VERIFIED`` and sealed an artifact publishing that cutoff for a window whose ``T0``
        is a million blocks earlier. Both refusals invalidate the run: a cutoff that is not ``T0`` is
        not a paperwork error, it is a selection made against data from after the decision instant.
        """
        self._containment.require_valid("mounting the pre-T0 snapshot")
        try:
            require_verified_snapshot(snapshot, "step 1, mounting the pre-T0 snapshot")
        except Exception:
            self._containment.invalidate(
                "the pre-T0 mount was handed evidence that never ran its own checks")
            raise
        if type(universe) is not FrozenUniverse:
            self._containment.invalidate(
                "the pre-T0 mount was handed a {} rather than a FrozenUniverse".format(
                    type(universe).__name__))
            raise OrderingViolation(
                "step 1 mounts the FrozenUniverse selection will rank, got {}".format(
                    type(universe).__name__))
        if snapshot.window_id != universe.window.key.value:
            self._containment.invalidate(
                "the mounted snapshot is for window {} and the universe is for {}".format(
                    snapshot.window_id, universe.window.key.value))
            raise OrderingViolation(
                "the snapshot is for window {!r} and the universe is for {!r}. Evidence about one "
                "window's census says nothing about another window's population.".format(
                    snapshot.window_id, universe.window.key.value)
            )
        if snapshot.t0_block != universe.window.t0.block:
            self._containment.invalidate(
                "the mounted snapshot declares t0_block {} and window {} has T0 block {}".format(
                    snapshot.t0_block, universe.window.key.value, universe.window.t0.block))
            raise OrderingViolation(
                "the snapshot declares its cutoff at block {} and window {}'s T0 is block {}. A "
                "snapshot proves 'every row is before the number I was given'; unless that number "
                "is T0 the proof is about an instant the experiment does not recognise, and a "
                "cutoff inside the forward period passes every self-consistency check there "
                "is.".format(snapshot.t0_block, universe.window.key.value,
                             universe.window.t0.block)
            )
        self._advance(Phase.PRE_T0_MOUNTED)
        self._workspace = PreT0Workspace(_ORDER_TOKEN, self, snapshot, universe)
        return self._workspace

    def require_selection_permitted(self, what: str) -> PreT0Workspace:
        """Step 2's gate. Every selection entry point calls this before it does anything.

        :raises SelectionAfterForwardMount: once the forward dataset has been mounted — and the run
            is invalidated first, so a caller who catches this and retries meets
            :class:`universe.containment.RunInvalidated` instead.
        """
        self._containment.require_valid(what)
        if self._phase is Phase.FORWARD_MOUNTED:
            self._containment.invalidate(
                "{} was attempted after the forward dataset was mounted".format(what))
            raise SelectionAfterForwardMount(
                "{} was attempted with the forward dataset mounted. A selection re-run at this "
                "point is chosen by somebody who has already seen the outcome, and it produces a "
                "basket indistinguishable from a legitimate one. The run is INVALIDATED: there is "
                "no artifact to keep and no partial result to salvage.".format(what)
            )
        if self._phase is not Phase.PRE_T0_MOUNTED:
            self._containment.invalidate(
                "{} was attempted at phase {}".format(what, self._phase.value))
            raise OrderingViolation(
                "{} was attempted at phase {}. Selection runs only between step 1 (the pre-T0 "
                "snapshot is mounted) and step 4 (the artifact is sealed); afterwards the artifact "
                "is the result and re-running is a second selection wearing the first one's "
                "identity.".format(what, self._phase.value)
            )
        return self._workspace

    # -- steps 3 and 4 --

    def seal(self, artifact: SelectedWalletArtifact) -> SelectedWalletArtifact:
        """Steps 3 and 4 together, because they are not separable.

        Producing an artifact and hashing it are one act: an artifact that exists un-hashed for even
        one statement is an artifact somebody can edit before the hash is taken.
        :class:`~universe.artifact.SelectedWalletArtifact` enforces that by recomputing its hash in
        ``__post_init__``, and this method re-verifies it at the seam.
        """
        self._containment.require_valid("sealing the selection artifact")
        if self._phase is not Phase.PRE_T0_MOUNTED:
            self._containment.invalidate(
                "sealing was attempted at phase {}".format(self._phase.value))
            raise OrderingViolation(
                "sealing was attempted at phase {}; the artifact is sealed once, immediately after "
                "selection runs".format(self._phase.value)
            )
        require_sealed_artifact(artifact, "sealing the selection artifact")
        if self._workspace.snapshot().snapshot_hash != artifact.snapshot_hash:
            self._containment.invalidate(
                "the sealed artifact names snapshot {} and the mounted workspace is {}".format(
                    artifact.snapshot_hash, self._workspace.snapshot().snapshot_hash))
            raise OrderingViolation(
                "the artifact was sealed against snapshot {} and the mounted pre-T0 workspace is "
                "{}. The two must be one snapshot, or the cutoff the artifact publishes is not the "
                "cutoff its data was truncated at.".format(
                    artifact.snapshot_hash, self._workspace.snapshot().snapshot_hash)
            )
        self._advance(Phase.ARTIFACT_SEALED)
        self._artifact = artifact
        # The hash **as seen at step 4**, recorded beside the object rather than read back off it.
        # ``artifact_hash`` is a field on a live object and ``artifact_hash_of`` is public, so an
        # editor can restore self-consistency in two lines; this copy is what they cannot reach.
        self._sealed_hash = artifact.artifact_hash
        self._seal_pid = os.getpid()
        return artifact

    @property
    def artifact(self) -> Optional[SelectedWalletArtifact]:
        """The sealed artifact, or ``None`` before step 4."""
        return self._artifact

    # -- steps 5 and 6 --

    def terminate_selection(self) -> None:
        """Step 5. No further selection work is accepted on this order."""
        self._containment.require_valid("terminating the selection process")
        self._advance(Phase.SELECTION_TERMINATED)

    def unmount_pre_t0(self) -> None:
        """Step 6. Drop the workspace and the snapshot reference; reads afterwards raise."""
        self._containment.require_valid("unmounting the pre-T0 workspace")
        self._advance(Phase.PRE_T0_UNMOUNTED)
        if self._workspace is not None:
            self._workspace.unmount()

    # -- step 7 --

    def mount_forward(self, dataset_id: str, dataset_hash: str) -> ForwardMount:
        """Step 7. The first and only moment forward data becomes reachable.

        :raises OrderingViolation: at any earlier phase, and in the same process the artifact was
            sealed in unless ``same_process_evaluation_declared=True`` was passed to the
            constructor.
        """
        self._containment.require_valid("mounting the forward dataset")
        if self._phase is not Phase.PRE_T0_UNMOUNTED:
            self._containment.invalidate(
                "the forward dataset was mounted at phase {}".format(self._phase.value))
            raise OrderingViolation(
                "the forward dataset was asked for at phase {}. Steps 1-6 come first: the artifact "
                "is produced, hashed and sealed, selection terminates, and the pre-T0 workspace is "
                "unmounted. Opening forward data before that is the audit's finding — five post-T0 "
                "records existed before any universe, any basket and any hash "
                "did.".format(self._phase.value)
            )
        if self._seal_pid == os.getpid() and not self._same_process_declared:
            raise OrderingViolation(
                "the forward dataset was asked for in process {}, which is the process the "
                "artifact was sealed in. Step 8 runs evaluation in a new process: selection and "
                "evaluation must not be two functions in one memory space with both datasets "
                "live. If this composition root genuinely runs single-process, construct the "
                "ExecutionOrder with same_process_evaluation_declared=True — the escape is a "
                "constructor argument so that using it is visible in the call rather than in an "
                "omission.".format(os.getpid())
            )
        if self._workspace is not None and self._workspace.mounted:
            self._containment.invalidate(
                "the forward dataset was mounted with the pre-T0 workspace still readable")
            raise OrderingViolation(
                "the forward dataset was asked for while the pre-T0 workspace is still readable. "
                "Step 6 drops it precisely so that no code path holds both datasets."
            )
        self._advance(Phase.FORWARD_MOUNTED)
        self._mount = ForwardMount(
            _ORDER_TOKEN, self._artifact, dataset_id, dataset_hash, self._sealed_hash)
        return self._mount

    @property
    def forward_mount(self) -> Optional[ForwardMount]:
        return self._mount

    def steps_taken(self) -> Tuple[str, ...]:
        """Every phase entered so far, in order. For the run record, not for a decision."""
        here = PHASE_ORDER.index(self._phase)
        return tuple(phase.value for phase in PHASE_ORDER[: here + 1])
