"""The typed input by which ``scoring``'s ``buy_quality_30d`` reaches a package that may not import it.

``universe`` is a **leaf** builder package: ``tests/test_lane_independence.py`` forbids it from
importing ``scoring``, because only the composition root composes. So the scores arrive as *data*.

That constraint turned out to be the thing that made the input honest, which is why this is not a
workaround. The naive reading of "pass the scores in" is ``Dict[str, Decimal]``. A dict cannot
distinguish *this wallet scored zero* from *this wallet's score never arrived* — and score
computation fails precisely for wallets whose buys all priced at zero, which correlates with going
quiet. That is survivorship entering through an exception handler, and in a dict it is invisible.

So :class:`RankingInputs` demands **equality** of coverage against the frozen membership, and every
absence must be an explicit :class:`UnscorableMember` carrying a reason. The count then travels on
the basket, so the denominator gap is visible rather than inferred.

Ranking on ``buy_quality_30d`` and on nothing else
--------------------------------------------------

That is a property of :class:`PreT0Score`'s **field list**, not of a function body: the type carries
exactly one measurement and its provenance. There is no volume field, no return field, no
active-days field — no second number in scope for a future edit to reach for. A record naming any
other metric is refused by name.

What this module does not guarantee: it checks that the caller's stamps place the score before T0
and that its baseline start matches the pre-registered calendar. It cannot see how the score was
computed, and a score computed correctly over the wrong six months with a correct-looking
``baseline_start_block`` is refused by nothing here.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from contracts import ContractError, LookAheadViolation

from .freeze import FrozenUniverse
from .observation import AccountWindowObservation, VendorMutability
from .protocol import (
    VALID_BUY_CEILING,
    VALID_BUY_FLOOR,
    PreT0Sealed,
    T0Instant,
    WindowKey,
    normalise_selection_account,
    require_pre_t0_int,
    pre_t0_sealed,
)
from .provenance import PreT0Decimal, require_pre_t0_value

#: §6.5: "Ranking is by ``buy_quality_30d`` computed on the six months before T0." One metric, and
#: a record naming any other is refused by name — a second metric arriving here is a second
#: experiment.
RANKING_METRIC = "buy_quality_30d"


class IncompleteRankingInputs(ContractError):
    """A frozen member is covered by neither a score nor an explicit unscorable record."""


class RankingInputMismatch(ContractError):
    """The supplied scores do not describe the universe they claim to rank."""


@pre_t0_sealed
@dataclass(frozen=True)
class PreT0Score(PreT0Sealed):
    """One wallet's ``buy_quality_30d``, measured over the six months before ``T0``.

    PreT0Sealed and checked at construction, for the same reason
    :class:`~universe.observation.AccountWindowObservation` is: a subclass overriding
    ``__post_init__`` would skip the provenance check while remaining an ``isinstance``, so
    :func:`for_universe` checks ``type(r) is PreT0Score``.

    Five refusals in ``__post_init__``:

    * ``metric`` is not ``buy_quality_30d``;
    * ``provenance`` is :attr:`~universe.observation.VendorMutability.MUTABLE_VENDOR_FIELD`;
    * ``as_of_block`` or ``as_of_timestamp`` at or after T0;
    * a ``value`` that is not a :class:`~universe.provenance.PreT0Decimal`;
    * ``n_buys`` outside §6.2's ``[20, 1000]`` — a score computed over an ineligible baseline is a
      score computed over the wrong period, whatever it says about the wallet.

    ``value`` is a :class:`~universe.provenance.PreT0Decimal` and never a bare ``Decimal``. This is
    the one number §6.5 ranks on, so it is the one number a laundered forward return would most
    profitably become — and ``pre_t0_score / (1 + forward_return)`` reads as an ordinary ``Decimal``
    with no forward object touched anywhere. The record-level stamps below cannot see that; only a
    provenance the arithmetic carried can. The float and NaN refusals are still made, one layer
    down, by ``PreT0Decimal``'s own constructor.
    """

    wallet: str
    metric: str
    value: PreT0Decimal
    n_buys: int
    as_of_block: int
    as_of_timestamp: int
    t0: T0Instant
    baseline_start_block: int
    baseline_start_ts: int
    source: str
    provenance: VendorMutability = VendorMutability.POINT_IN_TIME

    def __post_init__(self) -> None:
        object.__setattr__(self, "wallet", normalise_selection_account(self.wallet))
        if self.metric != RANKING_METRIC:
            raise RankingInputMismatch(
                "{} carries metric {!r}; §6.5 ranks on {!r} and on nothing else. A second metric "
                "arriving here is a second experiment, and the two would be indistinguishable in "
                "the basket.".format(self.wallet, self.metric, RANKING_METRIC)
            )
        if not isinstance(self.provenance, VendorMutability):
            raise TypeError("PreT0Score.provenance must be a VendorMutability")
        if type(self.t0) is not T0Instant:
            raise TypeError(
                "{} must carry a T0Instant, got {}".format(self.wallet, type(self.t0).__name__)
            )
        if not self.source or not str(self.source).strip():
            raise RankingInputMismatch(
                "{} carries no source. A ranking input with no stated origin cannot be "
                "re-derived, and §6.5's ranking is the one number the whole selection turns "
                "on.".format(self.wallet)
            )
        for name in ("n_buys", "as_of_block", "as_of_timestamp", "baseline_start_block",
                     "baseline_start_ts"):
            require_pre_t0_int(getattr(self, name), "{}.{}".format(self.wallet, name))
        object.__setattr__(
            self, "value",
            require_pre_t0_value(self.value, "{}.{}".format(self.wallet, RANKING_METRIC)),
        )
        if not (VALID_BUY_FLOOR <= self.n_buys <= VALID_BUY_CEILING):
            raise RankingInputMismatch(
                "{} was scored over {} buys, outside §6.2's [{}, {}]. A score computed over an "
                "ineligible baseline is a score computed over the wrong period, and it would rank "
                "against scores that were not.".format(
                    self.wallet, self.n_buys, VALID_BUY_FLOOR, VALID_BUY_CEILING)
            )
        if self.baseline_start_block >= self.t0.block:
            raise LookAheadViolation(
                "{} claims a baseline starting at block {}, at or after T0 block {}".format(
                    self.wallet, self.baseline_start_block, self.t0.block)
            )
        _require_pre_t0_score(self)


def _require_pre_t0_score(score: "PreT0Score") -> None:
    """The same five refusals ``observation.require_pre_t0`` applies, for a score record.

    Kept beside the type rather than reused from ``observation`` because a score has no
    ``field_blocks`` and a different vocabulary for what it is: sharing the function would mean
    sharing its message, and the message is what a reader acts on.
    """
    if score.provenance is VendorMutability.MUTABLE_VENDOR_FIELD:
        raise LookAheadViolation(
            "{}'s {} is stamped {}. Its source recomputes it, so its value at T0 is not knowable "
            "and the claim that it is pre-T0 cannot be checked. Ticket 28's audit covers 'any "
            "vendor field whose value is recomputed over time', and an unverifiable claim is not a "
            "passing one.".format(score.wallet, RANKING_METRIC,
                                  VendorMutability.MUTABLE_VENDOR_FIELD.value)
        )
    for name, boundary, unit in (("as_of_block", score.t0.block, "block"),
                                 ("as_of_timestamp", score.t0.timestamp, "second")):
        observed = getattr(score, name)
        if observed >= boundary:
            raise LookAheadViolation(
                "{} carries {} at {} {}, at or after T0 {} {}. §6.5 ranks on the six months "
                "*before* T0: a score computed at T0 has already seen T0, so the boundary is >= "
                "and not >. A forward-looking score does not crash — it ranks the wallets that "
                "went on to do well, which is the result the experiment is trying to "
                "test.".format(score.wallet, name, unit, observed, unit, boundary)
            )


@dataclass(frozen=True)
class UnscorableMember:
    """A frozen member for which no score could be computed, and why.

    The explicit absence. Without it a missing score is indistinguishable from a score of zero, and
    the ranked population shrinks silently in a direction that correlates with going quiet.
    """

    wallet: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "wallet", normalise_selection_account(self.wallet))
        if not self.reason or not str(self.reason).strip():
            raise IncompleteRankingInputs(
                "{} is recorded unscorable with no reason. An unexplained absence from the ranked "
                "population is the survivorship bug this type exists to make visible.".format(
                    self.wallet)
            )


@dataclass(frozen=True)
class RankingInputs:
    """Every frozen member covered exactly once, by a score or by a stated absence."""

    window_key: WindowKey
    t0: T0Instant
    scores: Tuple[PreT0Score, ...]
    unscorable: Tuple[UnscorableMember, ...] = ()
    metric: str = RANKING_METRIC

    def __post_init__(self) -> None:
        object.__setattr__(self, "scores", tuple(self.scores))
        object.__setattr__(self, "unscorable", tuple(self.unscorable))
        if not isinstance(self.window_key, WindowKey):
            raise TypeError("RankingInputs.window_key must be a WindowKey")
        if type(self.t0) is not T0Instant:
            raise TypeError("RankingInputs.t0 must be a T0Instant")
        if self.metric != RANKING_METRIC:
            raise RankingInputMismatch(
                "RankingInputs.metric is {!r}; §6.5 ranks on {!r}".format(
                    self.metric, RANKING_METRIC)
            )

    @property
    def covered(self) -> int:
        return len(self.scores) + len(self.unscorable)

    def score(self, wallet: str) -> Optional[PreT0Score]:
        key = normalise_selection_account(wallet)
        for record in self.scores:
            if record.wallet == key:
                return record
        return None


def for_universe(
    universe: FrozenUniverse,
    scores: Tuple[PreT0Score, ...],
    unscorable: Tuple[UnscorableMember, ...] = (),
) -> RankingInputs:
    """Bind scores to a frozen universe, refusing anything that does not cover it exactly.

    Six refusals, and the third is the one that matters most:

    1. anything but ``type(r) is PreT0Score`` — a subclass overriding ``__post_init__`` would skip
       the provenance and T0 checks while satisfying every ``isinstance``;
    2. a wallet appearing twice across ``scores`` and ``unscorable``;
    3. **coverage that is not exactly the frozen membership, in either direction.** A missing score
       silently shrinks the ranked population, which is the pre-filter route to survivorship; an
       extra score ranks a wallet the universe does not contain, which is selection on information
       the universe was not frozen with. Equality, not subset;
    4. a score whose ``n_buys`` disagrees with that member's frozen ``valid_buys`` — the two are the
       same measurement, and a disagreement means the score was computed over a different period
       from the one the member was admitted on;
    5. a score whose baseline start disagrees with the window's, so "the six months before T0" is
       checked against the pre-registered calendar rather than against an invented duration;
    6. a score whose ``t0`` disagrees with the universe's window T0.

    Every record is checked, not only the ones that end up used — ``matching.py``'s stated ground:
    a mapping containing one bad record came from a pipeline that cannot be trusted for the others.
    """
    if not isinstance(universe, FrozenUniverse):
        raise TypeError("for_universe needs a FrozenUniverse, got {}".format(
            type(universe).__name__))

    window = universe.window
    scores = tuple(scores)
    unscorable = tuple(unscorable)

    seen = {}
    for record in scores:
        if type(record) is not PreT0Score:
            raise TypeError(
                "ranking inputs hold PreT0Score values, got {}. The exact type is what guarantees "
                "the record ran the metric, provenance and T0 checks; a subclass overriding "
                "__post_init__ is an isinstance and runs none of them.".format(
                    type(record).__name__)
            )
        if record.wallet in seen:
            raise RankingInputMismatch(
                "{} is scored twice. Two answers to one ranking question means something must "
                "choose between them, and nothing is permitted to.".format(record.wallet)
            )
        seen[record.wallet] = record
    for record in unscorable:
        if not isinstance(record, UnscorableMember):
            raise TypeError("unscorable holds UnscorableMember values, got {}".format(
                type(record).__name__))
        if record.wallet in seen:
            raise RankingInputMismatch(
                "{} is both scored and recorded unscorable; the two claims cannot both be about "
                "the same wallet".format(record.wallet)
            )
        seen[record.wallet] = record

    members = {member.wallet: member for member in universe.members}
    missing = sorted(set(members) - set(seen))
    extra = sorted(set(seen) - set(members))
    if missing or extra:
        raise IncompleteRankingInputs(
            "the ranking inputs do not cover the frozen universe for window {} exactly: {} member(s) "
            "have neither a score nor a stated absence ({}{}), and {} scored wallet(s) are not "
            "members ({}{}). The rule is equality and not subset, and that is the whole reason this "
            "type exists rather than a dict: a dict cannot tell a wallet that scored zero from a "
            "wallet whose score never arrived, and score computation fails precisely for wallets "
            "whose buys all priced at zero — which correlates with going quiet. A missing score "
            "shrinks the ranked population silently; an extra one ranks a wallet the universe does "
            "not contain.".format(
                window.key.value,
                len(missing), ", ".join(missing[:5]),
                "" if len(missing) <= 5 else " (+{} more)".format(len(missing) - 5),
                len(extra), ", ".join(extra[:5]),
                "" if len(extra) <= 5 else " (+{} more)".format(len(extra) - 5),
            )
        )

    for wallet in sorted(seen):
        record = seen[wallet]
        if not isinstance(record, PreT0Score):
            continue
        member = members[wallet]
        if record.n_buys != member.valid_buys:
            raise RankingInputMismatch(
                "{} was scored over {} buys and is frozen with {} valid buys. They are the same "
                "measurement; a disagreement means the score describes a different period from the "
                "one the member was admitted on, and the band composition computed from the frozen "
                "count would describe a basket ranked on the other.".format(
                    wallet, record.n_buys, member.valid_buys)
            )
        if (record.baseline_start_block != window.baseline_start_block
                or record.baseline_start_ts != window.baseline_start_ts):
            raise RankingInputMismatch(
                "{} was scored over a baseline starting at block {} / second {}, and window {} "
                "starts at block {} / second {}. §6.5's 'six months before T0' is the "
                "pre-registered calendar, not a duration the scorer chose.".format(
                    wallet, record.baseline_start_block, record.baseline_start_ts,
                    window.key.value, window.baseline_start_block, window.baseline_start_ts)
            )
        if record.t0 != window.t0:
            raise RankingInputMismatch(
                "{} was scored against T0 (block {}, second {}) and window {} has T0 (block {}, "
                "second {})".format(
                    wallet, record.t0.block, record.t0.timestamp, window.key.value,
                    window.t0.block, window.t0.timestamp)
            )

    return RankingInputs(
        window_key=window.key,
        t0=window.t0,
        scores=scores,
        unscorable=unscorable,
    )


#: The record types the look-ahead audit expects to meet on the selection path. A new input type
#: added later is not in this tuple, so :func:`universe.audit.look_ahead_audit` raises
#: ``UndeclaredSelectionInput`` until somebody declares it — the run-time complement to the AST
#: rule in ``tests/test_post_t0_barrier.py``.
SELECTION_INPUT_CLASSES = (AccountWindowObservation, PreT0Score)
