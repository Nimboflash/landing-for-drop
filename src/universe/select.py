"""Ticket 28 — rank and select: ``clamp(1% of Eligible Universe, 250, 1000)``.

    Universe  20,000  ->  250 wallets
    Universe  50,000  ->  500 wallets
    Universe  80,000  ->  800 wallets
    Universe 200,000  ->  1,000 wallets

**The signature of :func:`rank_and_select` is the barrier.** Four parameters — the mounted pre-T0
workspace, the ranking inputs, the seed, the commit. No ``**kwargs``, no ``key=``, no ``filter=``,
no ``min_activity=``, no ``as_of=``. There is no parameter through which a second criterion or a
forward fact could arrive, so adding one is a diff a reviewer has to refuse rather than a default
somebody widened. ``tests/integration/test_universe.py`` pins the signature by
``inspect.signature``, exactly as ``report_churn``'s already is.

The first parameter is a :class:`universe.ordering.PreT0Workspace` and not a
:class:`~universe.freeze.FrozenUniverse`, and that is the whole of the ordering barrier. When it was
the universe, this function could be called at any point in a run — including after the post-T0
dataset had been mounted and read — because it had no way to reach the state machine that knew.
Measured, on a thousand-wallet population: walk the eight steps honestly, read post-T0 activity
through the sanctioned reader, then re-run this function under three hundred and ninety-nine seeds
and keep the one whose ten tie-decided slots held the wallets with the most post-T0 activity. Ten of
two hundred and fifty selected wallets changed, nothing raised, and the audit certified the result.
The universe now arrives through :meth:`universe.ordering.PreT0Workspace.selection_universe`, which
runs :meth:`universe.ordering.ExecutionOrder.require_selection_permitted` before it hands anything
back — so a re-run at that point does not raise *later*, it cannot obtain its first argument.

"On ``buy_quality_30d`` and on nothing else" is carried in two places and neither is a comment:
:class:`~universe.ranking.PreT0Score` has exactly one numeric field, so there is no second
measurement in scope for a future edit to reach for; and :func:`_tiebreak_key` is a function of the
seed and the address and of nothing measured.

The sort is two stable passes
------------------------------

Following ``reporting.diagnostics.profit_ranking`` exactly. Sort by the seeded tiebreak ascending,
then stable-sort by value with ``reverse=True``; Python's sort is stable and ``reverse=True``
preserves the relative order of equal elements, so the seeded order survives inside each tie group.

The one-pass spelling ``sorted(key=lambda s: (-s.value, key))`` needs a unary minus on a Decimal,
which is arithmetic under the ambient 28-digit context — the exact defect class
``tests/test_frozen_context.py`` exists to forbid, which has shipped three times in this repository.
Sorting on ``(value, key)`` with ``reverse=True`` would reverse the *tiebreak* as well as the value,
making the basket depend on the direction of a sort rather than on the seed.

The rounding is a choice, and is recorded as one
-------------------------------------------------

``raw = size // 100`` — floor, in int arithmetic. §6.5's four worked examples are all exact
multiples of 100, so the pre-registration pins nothing about floor versus round-half-even versus
ceiling, and the three disagree for roughly half of all universe sizes. Floor is pinned here with
its reason: a fractional wallet cannot be selected, and rounding down keeps realised selection
pressure at or below the 1% the pre-registration authorises. It is still an unregistered degree of
freedom being fixed after the pre-registration was written, and it belongs in the frozen parameter
set rather than only in this docstring.

What this module does not guarantee: the seed. The hashed tiebreak makes the basket *reproducible*
but not seed-independent — a different child seed gives a genuinely different basket wherever
qualities tie at rank n. At 38 digits exact ties should be rare and the basket reports the fact, but
nothing here can enforce *when* the seed was chosen. That is ``phase0``'s job, and if the seed is
not drawn from the run record's master seed before Step 0 runs, the reproducibility property is real
while the pre-commitment is not.
"""

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Tuple

from contracts import (
    AccountType,
    ENUM_SCHEMA_VERSION,
    NUMERIC_POLICY_VERSION,
    ContractError,
    artifact_envelope,
    canonical_hash,
    divide,
    require_finite,
)

from .artifact import (
    ArtifactRefused,
    SelectedWallet,
    SelectedWalletArtifact,
    artifact_from_snapshot_facts,
    sealed_artifact,
)
from .freeze import FrozenUniverse, require_frozen_membership
from .ordering import PreT0Workspace
from .protocol import (
    ACTIVITY_BAND_BOUNDS,
    SELECTED_MAX,
    SELECTED_MIN,
    SELECTION_PERCENT_DENOMINATOR,
    UNIVERSE_SCHEMA_VERSION,
    WindowKey,
    normalise_selection_account,
    require_pre_t0_int,
)
from .provenance import require_pre_t0_value
from .ranking import RANKING_METRIC, RankingInputMismatch, RankingInputs

ARTIFACT_KIND = "selected_basket"
PRODUCED_BY = "universe"


class SelectionRefused(ContractError):
    """The basket cannot be built from the arguments supplied."""


class ClampState(str, Enum):
    """Whether §6.5's clamp bit, and in which direction.

    A status rather than a bare count, because a clamp that bit is a real property of that window's
    experiment: 250 selected from 18,000 eligible is 1.4%, not 1%, and hiding that behind the
    clamped count is exactly the "those are not the same experiment" problem §6.5 raises.
    """

    CLAMPED_LOW = "CLAMPED_LOW"
    UNCLAMPED = "UNCLAMPED"
    CLAMPED_HIGH = "CLAMPED_HIGH"


class ActivityBandCounts(dict):
    """:attr:`ActivityBandComposition.as_mapping`'s rendered form, as a named type.

    The type with named fields is :class:`ActivityBandComposition` itself — ``b_20_99``,
    ``b_100_499``, ``b_500_1000`` — and that is the shape every caller inside this package reads.
    This exists only because §10's report labels the bands ``"20-99"`` and friends, and a label is
    a string. Giving that rendering a name means a report cannot be handed an arbitrary mapping in
    its place, and that a signature returning one says which mapping it returns.

    What it does not buy, stated rather than glossed: it is a ``dict`` underneath, so its members
    are still addressed by key. It is a rendering on its way out, never an input — nothing in this
    package reads a band count back off one, and :func:`band_composition` derives every count from
    :class:`Selection` fields.
    """


class BasketArtifact(dict):
    """:func:`basket_artifact`'s envelope, as a named type rather than a bare mapping.

    Same reasoning as :class:`ActivityBandCounts`, and the same limit. The envelope is JSON on its
    way to disk: ``gate_validation`` reads the file, never this object, and no value travels back
    into selection through it. :func:`universe.artifact._payload_of_facts` keeps its own payload
    unnamed by keeping it private; this one is returned to callers, so it is named.
    """


def selected_wallet_count(eligible_universe_size: int) -> Tuple[int, ClampState]:
    """§6.5's ``clamp(1% of Eligible Universe, 250, 1000)``, with the clamp state.

    A **pure clamp**: it does not raise on a small universe. The refusal for an insufficient window
    lives in :class:`universe.freeze.FrozenUniverse`, which is the object that would carry it into
    an experiment — and a function that raises at small values is a function nobody can hand-compute
    a table for.

    :returns: ``(count, ClampState)``.
    """
    size = require_pre_t0_int(eligible_universe_size, "eligible_universe_size")
    if size < 0:
        raise SelectionRefused(
            "the eligible universe size is {}; a negative population has no 1%".format(size)
        )
    raw = size // SELECTION_PERCENT_DENOMINATOR
    if raw < SELECTED_MIN:
        return SELECTED_MIN, ClampState.CLAMPED_LOW
    if raw > SELECTED_MAX:
        return SELECTED_MAX, ClampState.CLAMPED_HIGH
    return raw, ClampState.UNCLAMPED



def _tiebreak_key(seed, wallet):
    """A deterministic pseudo-random ordering key for wallets at identical quality.

    ``matching._tiebreak_key``'s exact reasoning, and the same construction. Ties have to be broken
    somehow; breaking them by address would be deterministic but not neutral, because addresses are
    not random and the lowest ones would be selected again and again for a reason unconnected to
    the data.

    Derived from the seed by SHA-256 rather than from ``random``, so the order is reproducible from
    ``(seed, wallet)`` alone on any machine and any Python version, and this module never touches a
    global RNG.
    """
    digest = hashlib.sha256("{}|{}".format(seed, wallet).encode("utf-8")).digest()
    return int.from_bytes(digest, "big")


@dataclass(frozen=True)
class Selection:
    """One selected wallet, its rank, and the pre-T0 facts the diagnostics need.

    ``value`` is a bare ``Decimal``, and that is a deliberate asymmetry with
    :attr:`universe.ranking.PreT0Score.value`, which is a
    :class:`~universe.provenance.PreT0Decimal`. A ``Selection`` is not a selection *input*: by the
    time one exists the ranking has happened, the rank is fixed, and this number is a recorded
    figure that diagnostics render. :func:`rank_and_select` gates the score's provenance and reads
    the digits only after the gate passes, so no unprovenanced number reaches a Selection through
    this package. What that does **not** guarantee: a caller who builds a ``Selection`` by hand may
    put any finite ``Decimal`` in this field. The barrier that matters is one stage earlier — a
    hand-built basket cannot change what ``rank_and_select`` ordered, and
    :class:`universe.artifact.SelectedWalletArtifact` refuses to publish anything whose provenance
    is not ``PRE_T0``.
    """

    wallet: str
    rank: int
    value: Decimal
    valid_buys: int
    account_type: AccountType

    def __post_init__(self) -> None:
        object.__setattr__(self, "wallet", normalise_selection_account(self.wallet))
        require_pre_t0_int(self.rank, "Selection.rank")
        if self.rank < 1:
            raise SelectionRefused("a rank is 1-based; got {}".format(self.rank))
        require_pre_t0_int(self.valid_buys, "Selection.valid_buys")
        if not isinstance(self.account_type, AccountType):
            raise TypeError("Selection.account_type must be a contracts.AccountType")
        object.__setattr__(
            self, "value", require_finite(self.value, "{} {}".format(self.wallet, RANKING_METRIC))
        )

    def __reduce__(self) -> object:
        raise SelectionRefused(
            "a Selection cannot be pickled. Unpickling rebuilds it without running the checks "
            "above, and a basket assembled from such rows is a ranking nobody performed."
        )

    def __setstate__(self, state: object) -> None:
        raise SelectionRefused("a Selection cannot be unpickled; see __reduce__.")


@dataclass(frozen=True)
class ActivityBandComposition:
    """Ticket 28's required diagnostic: the basket across 20-99, 100-499 and 500-1,000 valid buys.

    Refuses unless the three sum to the selected count, so no band gap and no band overlap can be
    published. The bands tile §6.2's eligible range exactly, which is what makes that sum a
    statement rather than a coincidence.
    """

    b_20_99: int
    b_100_499: int
    b_500_1000: int
    selected: int

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = require_pre_t0_int(getattr(self, name), "ActivityBandComposition.{}".format(name))
            if value < 0:
                raise ValueError("ActivityBandComposition.{} is {}".format(name, value))
        counted = self.b_20_99 + self.b_100_499 + self.b_500_1000
        if counted != self.selected:
            raise SelectionRefused(
                "the three activity bands hold {} wallet(s) and the basket holds {}. The bands tile "
                "§6.2's [20, 1000] exactly, so a wallet in none of them or in two of them means a "
                "count outside the eligible range reached the basket — a selection error filed as "
                "a diagnostic.".format(counted, self.selected)
            )

    @property
    def as_mapping(self) -> ActivityBandCounts:
        return ActivityBandCounts(
            (label, count) for (label, _low, _high), count in zip(
                ACTIVITY_BAND_BOUNDS, (self.b_20_99, self.b_100_499, self.b_500_1000)))


def band_composition(selections: Tuple[Selection, ...]) -> ActivityBandComposition:
    """The three-band composition of a basket, from the **frozen** valid-buy counts."""
    counts = [0, 0, 0]
    for selection in selections:
        for index, (_label, low, high) in enumerate(ACTIVITY_BAND_BOUNDS):
            if low <= selection.valid_buys <= high:
                counts[index] += 1
                break
        else:
            raise SelectionRefused(
                "{} carries {} valid buys, which falls in no §10 activity band. The bands tile "
                "§6.2's eligible range exactly, so this is a wallet that should not be in the "
                "population at all.".format(selection.wallet, selection.valid_buys)
            )
    return ActivityBandComposition(
        b_20_99=counts[0], b_100_499=counts[1], b_500_1000=counts[2],
        selected=len(tuple(selections)),
    )


@dataclass(frozen=True)
class SelectedBasket:
    """One window's selected wallets — ticket 28's frozen, versioned, pinnable artefact.

    ``short_by`` and ``unscorable_count`` are **statuses**, carried beside the requested count.
    Fewer scorable wallets than §6.5 derives is an observed outcome of the data: refusing would
    destroy a result, and returning a shorter basket silently would hide one. Whether a large
    shortfall should stop the run is a governance judgement, and nobody pre-registered a threshold
    for it — so the counts travel and the gate, not this package, decides.
    """

    window_key: WindowKey
    snapshot_id: str
    step0_digest: str
    selections: Tuple[Selection, ...]
    eligible_universe_size: int
    requested_count: int
    clamp_state: ClampState
    seed: int
    commit: str
    unscorable_count: int
    short_by: int
    metric: str = RANKING_METRIC
    universe_schema_version: str = UNIVERSE_SCHEMA_VERSION
    numeric_policy_version: str = NUMERIC_POLICY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "selections", tuple(self.selections))
        if not isinstance(self.window_key, WindowKey):
            raise TypeError("SelectedBasket.window_key must be a WindowKey")
        if not isinstance(self.clamp_state, ClampState):
            raise TypeError("SelectedBasket.clamp_state must be a ClampState")
        if self.metric != RANKING_METRIC:
            raise RankingInputMismatch(
                "the basket claims metric {!r}; §6.5 ranks on {!r}".format(
                    self.metric, RANKING_METRIC)
            )
        for name in ("snapshot_id", "step0_digest", "commit"):
            if not getattr(self, name) or not str(getattr(self, name)).strip():
                raise SelectionRefused(
                    "a selected basket must name its {}. Ticket 28 requires selection reproducible "
                    "from the same snapshot, commit and seed, and a basket missing one of the "
                    "three cannot be re-run.".format(name)
                )
        for name in ("eligible_universe_size", "requested_count", "seed", "unscorable_count",
                     "short_by"):
            require_pre_t0_int(getattr(self, name), "SelectedBasket.{}".format(name))
        if self.eligible_universe_size <= 0:
            raise SelectionRefused(
                "a basket over an eligible universe of {}; selection pressure would be a division "
                "by nothing".format(self.eligible_universe_size)
            )

        seen = set()
        previous_value = None
        for index, selection in enumerate(self.selections, start=1):
            if not isinstance(selection, Selection):
                raise TypeError("SelectedBasket.selections holds Selection values")
            if selection.rank != index:
                raise SelectionRefused(
                    "the basket's ranks are {} at position {}; ranks are 1..n and contiguous, or "
                    "the ordering the basket publishes is not the ordering it was built "
                    "with".format(selection.rank, index)
                )
            if selection.wallet in seen:
                raise SelectionRefused(
                    "{} appears twice in the basket; a duplicate occupies a place that belongs to "
                    "another wallet and would enter the benchmark twice under one "
                    "label".format(selection.wallet)
                )
            seen.add(selection.wallet)
            if previous_value is not None and selection.value > previous_value:
                raise SelectionRefused(
                    "{} ranks below a wallet with a lower {} ({} after {}). The basket is the top "
                    "of a descending ranking; an inversion means the published order is not the "
                    "order the metric implies.".format(
                        selection.wallet, RANKING_METRIC, selection.value, previous_value)
                )
            previous_value = selection.value

        if len(self.selections) + self.short_by != self.requested_count:
            raise SelectionRefused(
                "the basket holds {} wallet(s) and reports short_by {} against a requested {}. The "
                "shortfall is a status the report carries, so it has to add up — otherwise a "
                "basket smaller than §6.5 derived would be publishable without saying "
                "so.".format(len(self.selections), self.short_by, self.requested_count)
            )
        # A redundant assertion, in ``ChurnReport.churn_rate == inactive_rate``'s spirit: the two
        # are the same number by construction, so a disagreement means one of the counts is wrong.
        derived, state = selected_wallet_count(self.eligible_universe_size)
        if derived != self.requested_count or state is not self.clamp_state:
            raise SelectionRefused(
                "the basket requests {} wallet(s) in state {} from an eligible universe of {}; "
                "§6.5's clamp derives {} in state {}. The count is derived from the Step 0 "
                "measurement per window and recorded — a fixed 500 could be the top 2.5% in one "
                "window and 0.25% in another, and those are not the same experiment.".format(
                    self.requested_count, self.clamp_state.value, self.eligible_universe_size,
                    derived, state.value)
            )

    @property
    def wallets(self) -> Tuple[str, ...]:
        """The selected wallets in rank order."""
        return tuple(selection.wallet for selection in self.selections)

    @property
    def band_composition(self) -> ActivityBandComposition:
        return band_composition(self.selections)

    @property
    def selection_pressure(self) -> Decimal:
        """Realised selection pressure — selected over eligible, **unquantized**.

        Reported rather than assumed to be 1%: a clamp that bit makes the realised figure something
        else, and §6.5's whole argument is that the pressure is what has to be comparable across
        windows.
        """
        return divide(len(self.selections), self.eligible_universe_size)

    def verify(self) -> "SelectedBasket":
        """Rebuild the basket from the fields it is holding, re-running every invariant."""
        SelectedBasket(**{
            name: getattr(self, name) for name in self.__dataclass_fields__
        })
        return self

    def __reduce__(self) -> object:
        raise SelectionRefused(
            "a SelectedBasket cannot be pickled. Every invariant it has — the contiguous ranks, the "
            "descending values, the clamp that has to re-derive — lives in __post_init__, and "
            "unpickling runs none of them. The crossing to evaluation is seal_selection, which "
            "produces a canonical, schema-versioned, hashed artifact."
        )

    def __setstate__(self, state: object) -> None:
        raise SelectionRefused("a SelectedBasket cannot be unpickled; see __reduce__.")


def rank_and_select(workspace: PreT0Workspace, inputs: RankingInputs, seed: int,
                    commit: str) -> "SelectedBasket":
    """§6.5's basket for one window. Four parameters, and there is no fifth.

    :param workspace: the mounted :class:`universe.ordering.PreT0Workspace` step 1 produced. The
        frozen T0 :class:`~universe.freeze.FrozenUniverse` is obtained from it, and only from it, so
        that the ordering gate runs on every call — see the module docstring. Raw observations are
        not accepted either, so there is no eligibility predicate anywhere on this path: the
        predicate lives in ``eligibility`` and this module does not import it.
    :param inputs: :class:`~universe.ranking.RankingInputs`, whose coverage of the frozen membership
        has already been checked for equality.
    :param seed: an ``int``, drawn from the run record's master seed. Breaks ties in
        :func:`_tiebreak_key` and nowhere else.
    :param commit: the source commit the selection is pinned to.

    :raises universe.ordering.SelectionAfterForwardMount: if the run has reached step 7. The run is
        invalidated before the refusal is raised, so catching it and retrying meets
        :class:`universe.containment.RunInvalidated`.
    """
    if type(workspace) is not PreT0Workspace:
        raise TypeError(
            "rank_and_select needs the PreT0Workspace ExecutionOrder.mount_pre_t0 returned, got "
            "{}. A bare FrozenUniverse is not accepted: it can be ranked at any point in a run, "
            "including after the post-T0 dataset has been mounted and read, and the basket that "
            "comes back is indistinguishable from a legitimate one.".format(
                type(workspace).__name__)
        )
    universe = workspace.selection_universe("rank_and_select")
    if not isinstance(inputs, RankingInputs):
        raise TypeError(
            "rank_and_select needs RankingInputs, got {}. A bare mapping of wallet to score cannot "
            "tell a wallet that scored zero from a wallet whose score never arrived.".format(
                type(inputs).__name__)
        )
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError("seed must be an int, got {}".format(type(seed).__name__))
    if not commit or not str(commit).strip():
        raise SelectionRefused("selection must be pinned to a commit to be reproducible")

    if inputs.window_key is not universe.window.key:
        raise RankingInputMismatch(
            "the ranking inputs are for window {} and the universe is for {}".format(
                inputs.window_key.value, universe.window.key.value)
        )
    if inputs.t0 != universe.window.t0:
        raise RankingInputMismatch(
            "the ranking inputs carry T0 (block {}, second {}) and the universe's window has "
            "(block {}, second {})".format(
                inputs.t0.block, inputs.t0.timestamp,
                universe.window.t0.block, universe.window.t0.timestamp)
        )
    if inputs.covered != len(universe.members):
        raise RankingInputMismatch(
            "the ranking inputs cover {} wallet(s) and the frozen universe holds {}. Coverage is "
            "checked for equality when the inputs are built; a disagreement here means one of the "
            "two was rebuilt in between.".format(inputs.covered, len(universe.members))
        )

    members = {member.wallet: member for member in universe.members}
    requested, clamp_state = selected_wallet_count(len(universe.members))

    # Two stable passes, and there is deliberately no third. Any predicate inserted between them
    # is a second selection criterion, and the only facts a second criterion could be about are
    # ones §6.5 does not rank on.
    candidates = list(inputs.scores)
    candidates.sort(key=lambda score: _tiebreak_key(seed, score.wallet))
    candidates.sort(key=lambda score: score.value, reverse=True)

    # Both passes above sorted on ``score.value``, which is a PreT0Decimal: its ordering operators
    # refuse a peer that is not also PRE_T0, so the comparison that decides the basket cannot be
    # made against a laundered or forward number at all. Only here, once the order is fixed, is the
    # gate run again and the digits read — the recorded figure is downstream of every decision.
    chosen = candidates[:requested]
    selections = tuple(
        Selection(
            wallet=score.wallet,
            rank=index,
            value=require_pre_t0_value(
                score.value, "{} {}".format(score.wallet, RANKING_METRIC)).value,
            valid_buys=members[score.wallet].valid_buys,
            account_type=members[score.wallet].account_type,
        )
        for index, score in enumerate(chosen, start=1)
    )

    require_frozen_membership(
        universe, tuple(s.wallet for s in selections), "the selected basket")

    return SelectedBasket(
        window_key=universe.window.key,
        snapshot_id=universe.snapshot_id,
        step0_digest=_step0_digest(universe),
        selections=selections,
        eligible_universe_size=len(universe.members),
        requested_count=requested,
        clamp_state=clamp_state,
        seed=seed,
        commit=str(commit),
        unscorable_count=len(inputs.unscorable),
        short_by=requested - len(selections),
    )


def seal_selection(workspace: PreT0Workspace, basket: SelectedBasket, inputs: RankingInputs,
                   dataset_hash: str) -> SelectedWalletArtifact:
    """The crossing: a live basket becomes the sealed artifact, or the run is void.

    A :class:`SelectedBasket` is the right shape while selection is running and the wrong shape the
    moment forward data exists — every field on it is a live object, reachable and rewritable
    through ``dataclasses.replace``. :class:`universe.artifact.SelectedWalletArtifact` is the shape
    for afterwards, and this is the only function in the package that produces one from a basket.

    :param workspace: the mounted :class:`universe.ordering.PreT0Workspace`. The verified
        :class:`~universe.snapshot.PreT0Snapshot` selection ran against is read from it rather than
        passed in beside it, so the cutoff the artifact publishes is the cutoff of the census that
        was actually mounted — and, because
        :meth:`universe.ordering.ExecutionOrder.mount_pre_t0` compared that census against the
        universe's own ``T0``, a cutoff that is not ``T0`` is unreachable here. A snapshot supplied
        as an argument is a snapshot a caller may swap for a cleaner one after the fact, which is
        what made every other snapshot finding reachable.
    :param basket: the :class:`SelectedBasket` :func:`rank_and_select` returned.
    :param inputs: the :class:`~universe.ranking.RankingInputs` it was ranked from. Required rather
        than optional, and this is the load-bearing parameter: it is what lets the ``PRE_T0``
        stamp on the artifact be **re-derived** instead of asserted. For every selected wallet the
        score is looked up, put through :func:`~universe.provenance.require_pre_t0_value`, and
        compared digit-for-digit against the figure the basket carries. A contaminated score raises
        :class:`~universe.provenance.ContaminationDetected` — the run is void, and there is no
        branch here that drops the wallet instead.
    :param dataset_hash: the identifier of the dataset the snapshot was taken from.

    What this does not guarantee: it re-derives provenance from the inputs, so it is exactly as good
    as those inputs' own stamps — see :mod:`universe.observation` on what a stamp is worth. What it
    does close is the gap between ranking and sealing: a basket whose ``Selection.value`` was
    rewritten after ``rank_and_select`` returned no longer agrees with the score it was ranked on,
    and this refuses it by name.
    """
    if type(workspace) is not PreT0Workspace:
        raise TypeError(
            "seal_selection takes the PreT0Workspace ExecutionOrder.mount_pre_t0 returned, got {}. "
            "The snapshot the artifact pins comes from the mount, so it is the census selection "
            "actually ran against rather than one handed over at seal time.".format(
                type(workspace).__name__)
        )
    if not isinstance(basket, SelectedBasket):
        raise TypeError("seal_selection takes a SelectedBasket, got {}".format(
            type(basket).__name__))
    if not isinstance(inputs, RankingInputs):
        raise TypeError(
            "seal_selection takes the RankingInputs the basket was ranked from, got {}. Without "
            "them the artifact's PRE_T0 stamp would be a label this function wrote rather than a "
            "claim it re-derived.".format(type(inputs).__name__)
        )
    # Runs the ordering gate: sealing is step 4 and is refused at every phase selection is not
    # permitted at, so an artifact cannot be minted from a basket chosen after step 7 either.
    workspace.selection_universe("seal_selection")
    snapshot = workspace.snapshot()
    basket.verify()
    snapshot_hash, cutoff_block = artifact_from_snapshot_facts(snapshot, basket.window_key.value)

    rows = []
    for selection in basket.selections:
        score = inputs.score(selection.wallet)
        if score is None:
            raise ArtifactRefused(
                "{} is in the basket and has no score in the ranking inputs it was ranked from. "
                "The artifact's provenance is re-derived from those scores, so a wallet with none "
                "is a wallet whose PRE_T0 standing nothing can state.".format(selection.wallet)
            )
        gated = require_pre_t0_value(
            score.value, "{} {} at seal time".format(selection.wallet, RANKING_METRIC))
        if gated.value != selection.value:
            raise ArtifactRefused(
                "{} is published at {} and was ranked on {}. The two are the same measurement; a "
                "disagreement means the basket was edited between ranking and sealing, and the "
                "order the artifact publishes is not the order the metric "
                "produced.".format(selection.wallet, selection.value, gated.value)
            )
        rows.append(SelectedWallet(
            rank=selection.rank,
            wallet=selection.wallet,
            value=str(gated.value),
            valid_buys=selection.valid_buys,
            account_type=selection.account_type.value,
        ))

    return sealed_artifact(
        window_id=basket.window_key.value,
        cutoff_block=cutoff_block,
        dataset_hash=str(dataset_hash),
        snapshot_hash=snapshot_hash,
        step0_digest=basket.step0_digest,
        metric=basket.metric,
        seed=basket.seed,
        commit=basket.commit,
        eligible_universe_size=basket.eligible_universe_size,
        requested_count=basket.requested_count,
        unscorable_count=basket.unscorable_count,
        short_by=basket.short_by,
        selections=tuple(rows),
    )


def _step0_digest(universe: FrozenUniverse) -> str:
    """A digest of the measurement the basket was selected against.

    Pinned on the basket so that a re-run whose Step 0 counts moved produces a basket that says so,
    rather than one that merely happens to differ.
    """
    measurement = universe.measurement
    return canonical_hash({
        "window": measurement.window.key.value,
        "dataset_snapshot": measurement.dataset_snapshot,
        "total_active_accounts": measurement.total_active_accounts,
        "accounts_with_at_least_one_valid_buy":
            measurement.accounts_with_at_least_one_valid_buy,
        "accounts_in_valid_buy_band": measurement.accounts_in_valid_buy_band,
        "eligible_universe_size": measurement.eligible_universe_size,
        "excluded_infrastructure": measurement.excluded_infrastructure,
        "status": measurement.status.value,
    })


def basket_artifact(basket: SelectedBasket) -> BasketArtifact:
    """Ticket 28's frozen, versioned artefact, pinnable by the freeze manifest.

    The payload is the basket's primitives. ``payload_hash`` is what the manifest records, and it
    is what makes "same snapshot, same commit, same seed produces the same basket" checkable by
    somebody who did not run it.
    """
    if not isinstance(basket, SelectedBasket):
        raise TypeError("basket_artifact takes a SelectedBasket, got {}".format(
            type(basket).__name__))
    basket.verify()
    composition = basket.band_composition
    payload = {
        "window_key": basket.window_key.value,
        "snapshot_id": basket.snapshot_id,
        "step0_digest": basket.step0_digest,
        "metric": basket.metric,
        "seed": basket.seed,
        "commit": basket.commit,
        "eligible_universe_size": basket.eligible_universe_size,
        "requested_count": basket.requested_count,
        "clamp_state": basket.clamp_state.value,
        "unscorable_count": basket.unscorable_count,
        "short_by": basket.short_by,
        "selection_pressure": basket.selection_pressure,
        "universe_schema_version": basket.universe_schema_version,
        "numeric_policy_version": basket.numeric_policy_version,
        "enum_schema_version": ENUM_SCHEMA_VERSION,
        "activity_bands": {
            "20-99": composition.b_20_99,
            "100-499": composition.b_100_499,
            "500-1000": composition.b_500_1000,
        },
        "selections": [
            {
                "rank": s.rank,
                "wallet": s.wallet,
                "value": s.value,
                "valid_buys": s.valid_buys,
                "account_type": s.account_type.value,
            }
            for s in basket.selections
        ],
    }
    return BasketArtifact(artifact_envelope(ARTIFACT_KIND, PRODUCED_BY, payload))
