"""A breach invalidates the run. Not a caught exception, not a dropped wallet.

The forbidden pattern, written out so it is recognisable in a diff::

    try:
        value = wallet.forward_metric
    except LookAheadViolation:
        continue

It looks like the breach was caught. It is not: the composition of the candidate universe now
depends on which wallets raised, which is post-T0 information deciding membership. The brief
classifies it ``SILENTLY_DROPPED``, and so does this module — along with the other three shapes that
also look like repairs:

===========================  ==========================================================
Contaminated value ignored   ``SILENTLY_DROPPED`` — the universe changed and nobody said
Contaminated wallet dropped  ``SILENTLY_DROPPED``
Post-T0 value -> ``Decimal`` ``COERCED`` — the provenance is gone, the number remains
Post-T0 value -> ``0``       ``ZEROED`` — a dormant wallet and an unreadable one now agree
===========================  ==========================================================

``RAISED_LOOKAHEAD`` counts as a pass only when the whole run is invalidated, no selection artifact
is produced, and no individual wallet is merely dropped. :class:`LookAheadContainment` is what makes
those three the same event: :meth:`LookAheadContainment.guard` converts *any*
:class:`contracts.LookAheadViolation` raised inside it into an invalidation of the run, and once a
run is ``INVALIDATED`` every governed entry point refuses before doing anything.

Wiring to ``phase0``
--------------------

``src/phase0/governance.py`` already has the state this needs: ``GovernanceMachine.invalidate``
marks a run ``INVALIDATED``, refuses every subsequent transition, and can only be cleared by
registering a new code version and redoing the work. :class:`PhaseZeroGovernance` adapts to it, and
``universe`` importing ``phase0`` is lane-legal — ``phase0`` is shared infrastructure and
``tests/test_lane_independence.py`` forbids builder-to-builder edges, not builder-to-shared ones.

The adapter is injected rather than constructed here, and that is deliberate. A
``GovernanceMachine`` is file-backed: constructing one inside a selection function would make every
selection run write to a path this package chose, and would make the package untestable as the leaf
it is. The composition root owns the machine; this module owns the rule about what a breach means.

What this module does not guarantee
-----------------------------------

Containment is per-object, not per-process. Two :class:`LookAheadContainment` instances are two
runs, and nothing here stops a caller from making a fresh one after a breach — that is exactly what
``GovernanceMachine.register_code_version`` exists to make expensive, and it is expensive in the
governance record rather than here. What this closes is the *quiet* path: a breach cannot be
absorbed by the code that met it.
"""

from enum import Enum
from typing import Optional, Tuple

from contracts import ContractError, LookAheadViolation
from phase0.governance import GovernanceMachine


class RunState(str, Enum):
    """Two states. There is no ``DEGRADED``, and that absence is the design.

    A third state would be somewhere for a breach to be filed while the run continued, and the whole
    argument of §6.4 is that there is no such place: a look-ahead breach does not damage part of the
    result, it voids all of it, because the selection the result describes was made on information
    the experiment forbids.
    """

    RUNNING = "RUNNING"
    INVALIDATED = "INVALIDATED"


class RunInvalidated(LookAheadViolation):
    """The run is void. Every governed entry point refuses from here on.

    A subclass of :class:`contracts.LookAheadViolation` so that a caller who catches the general
    class in order to keep going is caught by the same net twice: the second refusal names the run
    rather than the value, and says what it costs.
    """


class ContainmentMisuse(ContractError):
    """Containment was asked for something it must not do — reused across runs, or cleared."""


class GovernanceSink(object):
    """The one thing containment needs from governance: somewhere to say ``INVALIDATED``.

    A base class with one method rather than a structural ``Protocol``. A ``Protocol`` here would be
    a shape anything could satisfy by accident, and the point of this seam is that the composition
    root *declares* what it is wiring.
    """

    def record_invalidation(self, requester: str, reason: str) -> None:
        raise NotImplementedError(
            "a GovernanceSink must implement record_invalidation(requester, reason)"
        )


class UnrecordedGovernance(GovernanceSink):
    """No external record. The containment object's own state is the whole record.

    The default, and honest about what it is: suitable for a test or a leaf-level run, and not
    suitable for the real experiment, where the invalidation has to survive the process that
    discovered it.
    """

    def record_invalidation(self, requester: str, reason: str) -> None:
        return None


class PhaseZeroGovernance(GovernanceSink):
    """Adapter onto ``phase0.governance.GovernanceMachine``'s ``INVALIDATED`` state.

    Constructed by the composition root with an already-configured machine. The machine's refusal is
    the durable half: after this call every transition raises ``InvalidatedError`` until a new code
    version is registered, the validation gate is re-run, the null is rebuilt and the main test is
    re-run — and choosing between the old and the new result is not permitted.
    """

    __slots__ = ("_machine",)

    def __init__(self, machine: GovernanceMachine) -> None:
        if type(machine) is not GovernanceMachine:
            raise ContainmentMisuse(
                "PhaseZeroGovernance needs a phase0.governance.GovernanceMachine, got {}. The "
                "annotation is the real class rather than a structural stand-in: a duck-typed "
                "sink would accept an object that records the invalidation nowhere, and the whole "
                "value of this adapter is that the refusal outlives this process.".format(
                    type(machine).__name__)
            )
        self._machine = machine

    def record_invalidation(self, requester: str, reason: str) -> None:
        self._machine.invalidate(requester, reason)


class LookAheadContainment(object):
    """One run's containment state, and the guard that makes a breach mean what it says.

    Not a dataclass: ``dataclasses.replace`` on a frozen dataclass would rebuild this with
    ``state=RUNNING`` in one line, which is precisely the "artifact mutation after sealing" route
    one layer over. The state is write-once in the ``INVALIDATED`` direction and there is no method
    that clears it.

    The state slot is **name-mangled**, and that is not decoration. With ``_state`` in ``__slots__``
    the reset was one plain line — ``containment._state = RunState.RUNNING`` — and
    :meth:`require_valid` passed immediately afterwards. Mangled, that line raises
    ``AttributeError`` because ``_state`` is not a slot at all; the reset now has to be spelled
    ``containment._LookAheadContainment__state``, which no reviewer reads past. It is friction, not
    a boundary: nothing in one interpreter can be made unreachable, and the durable half of the
    refusal is :class:`PhaseZeroGovernance`, which writes it where this process cannot reach it.

    Who calls it. Every stage of the eight steps runs through
    :class:`universe.ordering.ExecutionOrder`, which calls :meth:`require_valid` at each one — and
    since :func:`universe.select.rank_and_select` and :func:`universe.select.seal_selection` now
    take the mounted workspace rather than a bare universe, ranking and sealing are governed too. An
    earlier version of this docstring claimed "every governed entry point refuses" while the set of
    governed entry points outside the order was empty.
    """

    __slots__ = ("_run_id", "__state", "_reasons", "_sink")

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise ContainmentMisuse(
            "{} derives from LookAheadContainment. A subclass could override require_valid() and "
            "let an invalidated run continue while satisfying every isinstance check written "
            "against the base.".format(cls.__name__)
        )

    def __init__(self, run_id: str, sink: Optional[GovernanceSink] = None) -> None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ContainmentMisuse(
                "containment must name the run it governs; an unnamed invalidation cannot be "
                "matched to the result it voids"
            )
        if sink is None:
            sink = UnrecordedGovernance()
        if not isinstance(sink, GovernanceSink):
            raise ContainmentMisuse(
                "containment needs a GovernanceSink, got {}. The sink is where an invalidation "
                "outlives the process that discovered it.".format(type(sink).__name__)
            )
        self._run_id = run_id.strip()
        self.__state = RunState.RUNNING
        self._reasons = ()
        self._sink = sink

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def state(self) -> RunState:
        return self.__state

    @property
    def reasons(self) -> Tuple[str, ...]:
        """Every reason recorded, in the order they were recorded. Empty while the run is valid."""
        return self._reasons

    def invalidate(self, reason: str, requester: str = "universe.containment") -> None:
        """Mark the run void and record it. Idempotent, and there is no inverse.

        The first invalidation is what reaches the governance sink; later ones are appended to the
        local record but not re-reported, because a second breach in a run that is already void is a
        finding for the post-mortem rather than a second governance event.
        """
        if not isinstance(reason, str) or not reason.strip():
            raise ContainmentMisuse(
                "an invalidation must state its reason. A run marked void with no reason cannot be "
                "distinguished later from one marked void by accident."
            )
        first = self.__state is RunState.RUNNING
        self.__state = RunState.INVALIDATED
        self._reasons = self._reasons + (reason.strip(),)
        if first:
            self._sink.record_invalidation(requester, reason.strip())

    def require_valid(self, what: str) -> None:
        """Refuse ``what`` if the run is already void.

        :raises RunInvalidated: naming the stage and every reason recorded so far.
        """
        if self.__state is RunState.INVALIDATED:
            raise RunInvalidated(
                "run {} is INVALIDATED and {} is refused. Reason(s): {}. No selection artifact is "
                "produced from an invalidated run, and no part of one is salvaged: the selection "
                "this run would describe was made on information the experiment forbids, so there "
                "is nothing in it to keep.".format(
                    self._run_id, what, "; ".join(self._reasons) or "no reason recorded")
            )

    def guard(self, what: str) -> "_Guard":
        """A context manager that turns any look-ahead breach inside it into an invalidation.

        Use it around a whole stage, never around a single wallet. Wrapping one wallet is the
        forbidden pattern with a class attached to it — the breach would be converted into an
        invalidation and then, if the caller continued the loop, into a run that carried on with one
        fewer wallet and a void flag nobody read. :meth:`require_valid` at the next stage boundary
        is what makes that impossible, and it is why the guard invalidates *and re-raises*.
        """
        return _Guard(self, what)


class _Guard(object):
    """The context manager :meth:`LookAheadContainment.guard` returns. Re-raises, always."""

    __slots__ = ("_containment", "_what")

    def __init__(self, containment: LookAheadContainment, what: str) -> None:
        self._containment = containment
        self._what = what

    def __enter__(self) -> LookAheadContainment:
        self._containment.require_valid(self._what)
        return self._containment

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is not None and isinstance(exc, LookAheadViolation) \
                and not isinstance(exc, RunInvalidated):
            self._containment.invalidate(
                "{}: {}".format(self._what, exc),
                requester="universe.containment.guard",
            )
        # Never swallow. Returning True here would be the caught-exception route, and this class
        # exists to make that unwritable rather than to provide a tidier spelling of it.
        return False
