"""Ticket 27's freeze: the T0 snapshot later stages pin, and the membership refusals.

§6.4 in one sentence: *the candidate universe is frozen at ``T0``, and after ``T0`` a wallet is
never removed for exceeding 1,000 buys, sharply increasing activity, reducing activity, or going
fully inactive.*

Three things make that hold here.

**There is no removal API.** No ``filter``, no ``exclude``, no ``with_members``, no ``drop``, no
``add``. :class:`FrozenUniverse` has one membership accessor and one membership operation:
construction. §6.4's four motives all produce the same N−1 list and meet the same
motive-independent refusal, because the refusal does not ask why.

**The refusal is an arithmetic cross-check, not an inability to express the removal**, and the
difference is worth stating plainly rather than blurring. ``len(members)`` must equal the Step 0
measurement's eligible universe size, so dropping a wallet requires *also* falsifying the Step 0
count — and the Step 0 digest is itself pinned. What that catches is a net change. **Substitution
keeps the count**, and what catches substitution is :attr:`FrozenUniverse.snapshot_id` moving,
which is a *detection* visible in every downstream artefact rather than a refusal. A caller who
drops a dormant wallet *and* edits the measurement to match passes every check in this package;
only the freeze manifest's hash of the Step 0 artefact catches that, one layer up.

**``INSUFFICIENT CANDIDATE UNIVERSE`` becomes a refusal here and not in ``step0``.** That split is
load-bearing. Measuring a small universe is a finding (a status); freezing one for ranking is a
governance violation (an error). Collapsing it either way breaks something: all-status lets a
caller proceed to ranking on an invalid window with a comment attached, and all-error crashes the
measurement stage on its most informative possible result. The error is avoidable exactly one way —
a :class:`DesignRevision`, four required non-empty facts somebody had to write down, hashed into
the snapshot identifier.

The matching handoff
--------------------

``matching_null.build_matched_sets(selected, universe, ...)`` is a seam that is called today with
arguments no code produces. :func:`matching_inputs` produces both **from one object**, so the
failure mode when the seam finally has a producer — the two arguments coming from different
snapshots — is not merely detected, it is unobtainable. ``universe_wallets`` is a tuple of
lowercased address strings, which is exactly what ``build_matched_sets._distinct_lower`` consumes
today: matching is not asked to change.

What this module does not guarantee: ``verify()`` rebuilds every record from the fields it is
currently holding, which closes the *consequence* of ``object.__setattr__`` at artefact time. It
closes nothing about the act, and a field rewritten between construction and verification is
invisible.
"""

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Optional, Tuple

from contracts import AccountType, ContractError, ENUM_SCHEMA_VERSION, NUMERIC_POLICY_VERSION, canonical_hash

from .eligibility import ADMISSIBLE_ACCOUNT_TYPES, EligibilityPolicy, EligibilityVerdict
from .protocol import (
    MINIMUM_ELIGIBLE_UNIVERSE,
    POTENTIAL_BUY_CEILING,
    POTENTIAL_BUY_FLOOR,
    UNIVERSE_SCHEMA_VERSION,
    VALID_BUY_CEILING,
    VALID_BUY_FLOOR,
    TrainingWindow,
    normalise_selection_account,
    require_pre_t0_int,
)
from .provenance import require_pre_t0_value
from .step0 import Step0Measurement, Step0Report, WindowStatus

if TYPE_CHECKING:  # pragma: no cover - import cycle: select imports freeze, never the reverse.
    from .select import SelectedBasket

#: §6.4's four, quoted so the refusal says what it is refusing rather than describing a count.
REMOVAL_REASONS_REFUSED = (
    "exceeding 1,000 buys after T0",
    "sharply increasing activity after T0",
    "reducing activity after T0",
    "going fully inactive after T0",
)


class UniverseFreezeViolation(ContractError):
    """The frozen membership does not match what Step 0 measured, or what a later stage claims.

    Raised motive-independently: this refusal does not ask why a wallet is missing, because §6.4's
    four reasons are all refused and a fifth would be too.
    """


class InsufficientCandidateUniverse(ContractError):
    """A window below §6.1's floor was frozen for ranking without an explicit design revision.

    The measurement itself is a finding and carries a status. This is the governance line: §6.1
    says such a window *is not valid* and the four-window design must be revised **before** the main
    test, so advancing past it silently is the thing the stopping condition exists to prevent.
    """


class Step0Incomplete(ContractError):
    """Ranking was authorised for a window Step 0 has not cleared across all four slots."""


class DuplicateMember(ContractError):
    """A wallet appears twice in a universe, a score set, or a basket.

    Refused rather than deduped, on ``matching._distinct_lower``'s ground — a duplicate would be
    selected twice and enter the benchmark twice under one label — and on ``asset_keyed``'s: nobody
    can say which entry is *the* entry, and supplying both is the evidence that nobody does.
    """


@dataclass(frozen=True)
class DesignRevision:
    """The explicit revision §6.1 requires before an insufficient window may be advanced.

    Four facts, all required and all non-empty, all hashed into the snapshot identifier. "Explicitly
    revised" becomes four things somebody had to write down, rather than a flag somebody set.
    """

    rule_id: str
    revised_by: str
    reason: str
    recorded_at_commit: str

    def __post_init__(self) -> None:
        for name in ("rule_id", "revised_by", "reason", "recorded_at_commit"):
            if not getattr(self, name) or not str(getattr(self, name)).strip():
                raise ValueError(
                    "a design revision must state its {}. §6.1 requires the four-window design to "
                    "be *explicitly* revised; a revision with a blank field is a flag rather than "
                    "a decision anybody owns.".format(name)
                )


@dataclass(frozen=True)
class UniverseMember:
    """One frozen wallet, and the three pre-T0 facts every later stage needs.

    Membership; the exact-match dimension §6.6 matches on; and the valid-buy count ticket 28's band
    composition is computed from. Carrying ``valid_buys`` **here** is what stops the band
    composition being recomputed later against a count that has since moved.

    There is no field of any post-T0 type, and no field whose type could carry one.
    """

    wallet: str
    account_type: AccountType
    valid_buys: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "wallet", normalise_selection_account(self.wallet))
        if self.account_type not in ADMISSIBLE_ACCOUNT_TYPES:
            raise UniverseFreezeViolation(
                "{} is frozen as {}; only {} may be members. INFRASTRUCTURE and UNKNOWN are "
                "excluded by definition, and a member nobody could type would enter §6.6's exact "
                "account-type match as a category of its own.".format(
                    self.wallet, self.account_type.value,
                    ", ".join(t.value for t in ADMISSIBLE_ACCOUNT_TYPES))
            )
        require_pre_t0_int(self.valid_buys, "UniverseMember.valid_buys")
        if not (VALID_BUY_FLOOR <= self.valid_buys <= VALID_BUY_CEILING):
            raise UniverseFreezeViolation(
                "{} is frozen with {} valid buys, outside §6.2's [{}, {}]. The bound applies to the "
                "*baseline* count measured before T0; §6.4 forbids applying it to anything measured "
                "after.".format(self.wallet, self.valid_buys, VALID_BUY_FLOOR, VALID_BUY_CEILING)
            )


@dataclass(frozen=True)
class FrozenUniverse:
    """One window's universe, frozen at ``T0``, with no way to take a wallet out of it.

    Validation lives in ``__post_init__`` rather than in the :func:`freeze_universe` factory
    precisely so that direct construction is as safe as the factory. Python has no private
    constructor, so an invariant enforced only by a factory is an invariant a caller can walk
    around by naming the class.
    """

    window: TrainingWindow
    members: Tuple[UniverseMember, ...]
    measurement: Step0Measurement
    dataset_snapshot: str
    revision: Optional[DesignRevision] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "members", tuple(self.members))
        if type(self.window) is not TrainingWindow:
            raise TypeError("FrozenUniverse.window must be a TrainingWindow")
        if not isinstance(self.measurement, Step0Measurement):
            raise TypeError("FrozenUniverse.measurement must be a Step0Measurement")
        if self.revision is not None and not isinstance(self.revision, DesignRevision):
            raise TypeError("FrozenUniverse.revision must be a DesignRevision or None")
        if not self.dataset_snapshot or not str(self.dataset_snapshot).strip():
            raise ValueError("a frozen universe must name its dataset snapshot")

        seen = set()
        previous = None
        for member in self.members:
            if type(member) is not UniverseMember:
                raise TypeError(
                    "FrozenUniverse.members holds UniverseMember values, got {}".format(
                        type(member).__name__)
                )
            if member.wallet in seen:
                raise DuplicateMember(
                    "{} appears twice in the frozen universe for window {}. Refused rather than "
                    "deduped: a duplicate would be ranked twice, could be selected twice, and "
                    "would enter the benchmark twice under one label — and nobody can say which of "
                    "the two entries is the entry.".format(member.wallet, self.window.key.value)
                )
            seen.add(member.wallet)
            if previous is not None and member.wallet < previous:
                raise UniverseFreezeViolation(
                    "the frozen membership is not in wallet order ({} follows {}). The snapshot "
                    "identifier is a hash over the ordered members, so an unordered membership "
                    "would hash differently for the same universe and every downstream pin would "
                    "read as a different experiment.".format(member.wallet, previous)
                )
            previous = member.wallet

        if self.measurement.window != self.window:
            raise UniverseFreezeViolation(
                "the universe is frozen for window {} and its measurement is of {}".format(
                    self.window.key.value, self.measurement.window.key.value)
            )
        if self.measurement.dataset_snapshot != self.dataset_snapshot:
            raise UniverseFreezeViolation(
                "the universe claims snapshot {!r} and its Step 0 measurement was taken from {!r}. "
                "Ticket 26 requires the counts reproducible from the frozen snapshot; a universe "
                "frozen from a different one is reproducible from neither.".format(
                    self.dataset_snapshot, self.measurement.dataset_snapshot)
            )
        if len(self.members) != self.measurement.eligible_universe_size:
            raise UniverseFreezeViolation(
                "window {} freezes {} member(s) against a measured eligible universe of {}. §6.4: "
                "after T0 a wallet is never removed for {}. This refusal is motive-independent — "
                "it does not ask why the membership disagrees with the measurement, because all "
                "four of those reasons produce exactly this disagreement. Note what it does and "
                "does not catch: a net change in the membership, yes; a substitution that keeps "
                "the count, no — that one is caught by the snapshot identifier "
                "moving.".format(
                    self.window.key.value, len(self.members),
                    self.measurement.eligible_universe_size,
                    "; ".join(REMOVAL_REASONS_REFUSED),
                )
            )
        if (self.measurement.status is WindowStatus.INSUFFICIENT_CANDIDATE_UNIVERSE
                and self.revision is None):
            raise InsufficientCandidateUniverse(
                "window {} measured {} eligible accounts, below §6.1's floor of {}, and its status "
                "is {!r}. Measuring that is a finding and the measurement carries it as a status. "
                "Freezing it for ranking is not: §6.1 says the window is not valid and the "
                "four-window design must be revised *before* the main test. The one door through "
                "this is an explicit DesignRevision naming a rule, a person, a reason and a "
                "commit.".format(
                    self.window.key.value, self.measurement.eligible_universe_size,
                    MINIMUM_ELIGIBLE_UNIVERSE,
                    WindowStatus.INSUFFICIENT_CANDIDATE_UNIVERSE.value,
                )
            )

    # -- identity ---------------------------------------------------------------

    @property
    def wallets(self) -> Tuple[str, ...]:
        """The frozen membership, in wallet order. The only membership accessor there is."""
        return tuple(member.wallet for member in self.members)

    @property
    def snapshot_id(self) -> str:
        """The identifier later stages pin, over an explicit ordered payload.

        Deliberately **not** over the distributions: they are derived, and including them would
        make the identity of the universe move with a reporting change. What is in it is what a
        later stage would be wrong to disagree with — the membership, the calendar, the policy the
        membership was decided under, the buffer bounds, the snapshot, any revision, and the three
        schema versions.
        """
        return canonical_hash(self._payload())

    def _payload(self):
        policy = self.measurement.policy
        return {
            "schema_version": UNIVERSE_SCHEMA_VERSION,
            "numeric_policy_version": NUMERIC_POLICY_VERSION,
            "enum_schema_version": ENUM_SCHEMA_VERSION,
            "window_key": self.window.key.value,
            "t0_block": self.window.t0.block,
            "t0_timestamp": self.window.t0.timestamp,
            "baseline_start_block": self.window.baseline_start_block,
            "baseline_start_ts": self.window.baseline_start_ts,
            "replaced_from": (None if self.window.replaced_from is None
                              else self.window.replaced_from.value),
            "dataset_snapshot": self.dataset_snapshot,
            "buffer": [POTENTIAL_BUY_FLOOR, POTENTIAL_BUY_CEILING,
                       VALID_BUY_FLOOR, VALID_BUY_CEILING],
            "policy": _policy_payload(policy),
            "revision": (None if self.revision is None else {
                "rule_id": self.revision.rule_id,
                "revised_by": self.revision.revised_by,
                "reason": self.revision.reason,
                "recorded_at_commit": self.revision.recorded_at_commit,
            }),
            "members": [
                [member.wallet, member.account_type.value, member.valid_buys]
                for member in self.members
            ],
        }

    def member(self, wallet: str) -> Optional[UniverseMember]:
        key = normalise_selection_account(wallet)
        for candidate in self.members:
            if candidate.wallet == key:
                return candidate
        return None

    def verify(self) -> "FrozenUniverse":
        """Rebuild every member and the measurement from stored fields, and return ``self``.

        ``DiagnosticPack.verify``'s pattern. Re-running each ``__post_init__`` at the point of
        publication is what makes "the invariants held" mean something after construction — handing
        an already-built object back to a constructor runs none of its checks, so each record is
        rebuilt from ``getattr`` of every field.

        It closes the *consequence* of a rewrite at artefact time. It closes nothing about the act.
        """
        rebuilt = tuple(
            UniverseMember(wallet=m.wallet, account_type=m.account_type, valid_buys=m.valid_buys)
            for m in self.members
        )
        measurement = type(self.measurement)(**{
            f.name: getattr(self.measurement, f.name)
            for f in fields(self.measurement) if f.init
        })
        FrozenUniverse(
            window=self.window,
            members=rebuilt,
            measurement=measurement,
            dataset_snapshot=self.dataset_snapshot,
            revision=self.revision,
        )
        return self


def _policy_payload(policy: EligibilityPolicy):
    """The §6.2 thresholds, in the form the snapshot identifier hashes.

    Two of the fields are :class:`~universe.provenance.PreT0Decimal` rather than bare ``Decimal``,
    and a provenance-carrying value is not JSON. Each one is gated by
    :func:`~universe.provenance.require_pre_t0_value` and *then* unwrapped, so a threshold that has
    somehow become ``CONTAMINATED`` voids the identity here rather than being hashed in under its
    digits alone. The origin is written beside the digits because two thresholds with the same
    number and different standing are not the same parameter, and a hash that could not tell them
    apart would let one be substituted for the other without the universe's identity moving.

    Anything that is not an ``int``, ``bool`` or ``str`` must present a provenance; there is no
    pass-through for a value whose origin nobody stated.
    """
    payload = {}
    for name in sorted(policy.__dataclass_fields__):
        value = getattr(policy, name)
        if isinstance(value, (bool, int, str)):
            payload[name] = value
            continue
        gated = require_pre_t0_value(value, "EligibilityPolicy.{}".format(name))
        payload[name] = [gated.origin.value, gated.value]
    return payload


def freeze_universe(measurement: Step0Measurement,
                    verdicts: Tuple[EligibilityVerdict, ...],
                    dataset_snapshot: str,
                    revision: Optional[DesignRevision] = None) -> FrozenUniverse:
    """Freeze one window's admitted accounts at ``T0``.

    :param measurement: the window's :class:`~universe.step0.Step0Measurement`. Its eligible
        universe size is what the membership is cross-checked against.
    :param verdicts: the same :class:`~universe.eligibility.EligibilityVerdict` values the census
        was built from. Only the admissions become members; every exclusion is already attributed.
    :param revision: required when the window's status is ``INSUFFICIENT CANDIDATE UNIVERSE``.
    """
    members = []
    for verdict in verdicts:
        if not isinstance(verdict, EligibilityVerdict):
            raise TypeError(
                "freeze_universe takes EligibilityVerdict values, got {}".format(
                    type(verdict).__name__)
            )
        if not verdict.is_admitted:
            continue
        admission = verdict.admitted
        members.append(UniverseMember(
            wallet=admission.account,
            account_type=admission.account_type,
            valid_buys=admission.valid_buys,
        ))
    members.sort(key=lambda member: member.wallet)
    return FrozenUniverse(
        window=measurement.window,
        members=tuple(members),
        measurement=measurement,
        dataset_snapshot=str(dataset_snapshot),
        revision=revision,
    )


def require_step0_complete(report: Step0Report, universe: FrozenUniverse) -> bool:
    """Ticket 26's governance precondition: Step 0 clears **all four** windows before any ranking.

    :class:`~universe.freeze.FrozenUniverse` already refuses one window whose own measurement is
    short. This is the other half of §6.1, which is about the *design* rather than the window: the
    four-window design must be revised before the main test, so a slot measured at 8,400 blocks
    ranking on the other three until somebody writes the revision down.

    Four refusals:

    1. the arguments are not a :class:`~universe.step0.Step0Report` and a :class:`FrozenUniverse`;
    2. the report does not measure the window being ranked;
    3. the report and the universe name different dataset snapshots, so the counts authorising the
       ranking were taken from a different frozen dataset than the membership;
    4. **any** window in the report is ``INSUFFICIENT CANDIDATE UNIVERSE`` and the universe carries
       no :class:`DesignRevision`.

    What this does **not** do, stated because the difference decides how much it is worth: it is a
    call, not a shape. :func:`universe.select.rank_and_select` takes four parameters and the report
    is not one of them, so a composition root that never calls this function ranks a window whose
    three siblings were never measured, and nothing in this package notices. What makes that
    survivable rather than decorative is that the omission is visible in one place — the
    composition root — and ``tests/integration/test_universe.py`` pins the call there. A structural
    version would put the report on :class:`FrozenUniverse` itself, and it is the honest next step
    for whoever composes ticket 29.

    :returns: ``True``.
    """
    if not isinstance(report, Step0Report):
        raise TypeError(
            "require_step0_complete needs a Step0Report, got {}. The report is the type that "
            "carries all four windows; a single measurement cannot answer whether the other three "
            "were taken at all.".format(type(report).__name__)
        )
    if not isinstance(universe, FrozenUniverse):
        raise TypeError("require_step0_complete needs a FrozenUniverse, got {}".format(
            type(universe).__name__))

    key = universe.window.key
    try:
        measurement = report.measurement(key)
    except KeyError:
        raise Step0Incomplete(
            "the Step 0 report does not measure window {}, and ranking it would run the stage on a "
            "window Step 0 never covered. Ticket 26: Step 0 completion is a governance "
            "precondition for ranking, so ranking cannot run first by accident.".format(key.value)
        )
    if report.dataset_snapshot != universe.dataset_snapshot:
        raise Step0Incomplete(
            "the Step 0 report was measured from snapshot {!r} and window {} is frozen from {!r}. "
            "The counts that authorise the ranking and the membership that is ranked would come "
            "from two different frozen datasets.".format(
                report.dataset_snapshot, key.value, universe.dataset_snapshot)
        )
    if measurement != universe.measurement:
        raise Step0Incomplete(
            "the Step 0 report's measurement of window {} is not the one this universe was frozen "
            "against. One of the two was re-measured, and the eligible universe size §6.5 derives "
            "the selected wallet count from is whichever of them a reader happens to "
            "open.".format(key.value)
        )

    short = report.insufficient_windows
    if short and universe.revision is None:
        raise InsufficientCandidateUniverse(
            "window(s) {} measured below §6.1's floor of {} eligible accounts, and ranking window "
            "{} was authorised with no design revision recorded. §6.1 says such a window is not "
            "valid and the four-window design must be revised *before* the main test — that is a "
            "statement about the design, so a short slot blocks the whole report and not only its "
            "own window.".format(
                ", ".join(k.value for k in short), MINIMUM_ELIGIBLE_UNIVERSE, key.value)
        )
    return True


def require_frozen_membership(universe: FrozenUniverse,
                              wallets: Tuple[str, ...],
                              what: str) -> None:
    """Refuse any wallet that is not in the frozen membership, naming the first five.

    §6.4 draws both the selected wallets and their controls from the frozen T0 universe. A wallet
    from outside it was chosen on information the universe does not contain.
    """
    members = set(universe.wallets)
    outside = []
    seen = set()
    for wallet in wallets:
        key = normalise_selection_account(wallet)
        if key in seen:
            raise DuplicateMember(
                "{} appears twice in {}; a duplicate occupies a place that belongs to another "
                "wallet and is invisible in the result".format(key, what)
            )
        seen.add(key)
        if key not in members:
            outside.append(key)
    if outside:
        raise UniverseFreezeViolation(
            "{}: {} wallet(s) are not in the frozen universe for window {}: {}{}. §6.4 freezes the "
            "universe at T0 and draws both the selected wallets and their controls from it.".format(
                what, len(outside), universe.window.key.value, ", ".join(sorted(outside)[:5]),
                "" if len(outside) <= 5 else " (+{} more)".format(len(outside) - 5),
            )
        )


@dataclass(frozen=True)
class MatchingHandoff:
    """The pair ``matching_null.build_matched_sets`` wants, obtainable only together.

    ``universe_wallets`` is a tuple of lowercased address strings — exactly what
    ``build_matched_sets._distinct_lower`` consumes today, so nothing in ``matching_null`` changes.

    The two arguments cannot come from different snapshots because they are no longer separately
    obtainable: :func:`matching_inputs` derives both from one :class:`FrozenUniverse`, and the
    snapshot identifier travels with them.
    """

    selected: Tuple[str, ...]
    universe_wallets: Tuple[str, ...]
    snapshot_id: str
    t0_block: int
    t0_timestamp: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected", tuple(self.selected))
        object.__setattr__(self, "universe_wallets", tuple(self.universe_wallets))
        require_pre_t0_int(self.t0_block, "MatchingHandoff.t0_block")
        require_pre_t0_int(self.t0_timestamp, "MatchingHandoff.t0_timestamp")
        if not self.selected:
            raise UniverseFreezeViolation("a matching handoff with no selected wallets")
        outside = sorted(set(self.selected) - set(self.universe_wallets))
        if outside:
            raise UniverseFreezeViolation(
                "selected wallet(s) outside the handed-over universe: {}".format(
                    ", ".join(outside[:5]))
            )


def matching_inputs(universe: FrozenUniverse, basket: "SelectedBasket") -> MatchingHandoff:
    """The one door to a control pool: ``(selected, universe_wallets)`` from a single object.

    Benchmark baskets are drawn from the same frozen T0 universe (ticket 27), so the control is
    subject to exactly the same survivorship constraints as the selected set. That is not a
    convention here — there is no other function in this package that produces a control pool, and
    this one's only source of wallets is ``universe.wallets``.

    What it does not stop: a later ticket's author hand-building a list and passing it to
    ``build_matched_sets`` directly. That is a cross-package concern the barrier does not reach, and
    an integration test asserting the pool equals the frozen membership is the only control on it.
    """
    if not isinstance(universe, FrozenUniverse):
        raise TypeError("matching_inputs needs a FrozenUniverse, got {}".format(
            type(universe).__name__))
    snapshot_id = universe.snapshot_id
    if basket.snapshot_id != snapshot_id:
        raise UniverseFreezeViolation(
            "the basket was selected from snapshot {} and this universe is {}. The two arguments "
            "to matched-set construction must describe one universe; supplying a basket from "
            "another snapshot is the failure this handoff exists to make "
            "unobtainable.".format(basket.snapshot_id, snapshot_id)
        )
    require_frozen_membership(universe, basket.wallets, "the selected basket")
    return MatchingHandoff(
        selected=tuple(basket.wallets),
        universe_wallets=universe.wallets,
        snapshot_id=snapshot_id,
        t0_block=universe.window.t0.block,
        t0_timestamp=universe.window.t0.timestamp,
    )
