"""The pre-T0 evidence record, and the look-ahead guard that makes it one.

Every fact selection is ever allowed to see enters through :class:`AccountWindowObservation`, and
that type **cannot be constructed carrying a post-T0 stamp**: ``t0`` is a required field and
:func:`require_pre_t0` runs in ``__post_init__``.

That is the one place this design goes further than the pattern it imitates.
``matching_null.features`` got it as right as it could — ``WalletFeatures`` carries its provenance
and ``require_pre_t0`` refuses a forward-looking record — but a caller who forgets the call gets a
perfectly valid forward-looking record, which is why ``build_matched_sets`` has to re-check every
supplied record and says so in its own docstring. Making ``t0`` a field converts *the wrong program
is refused when someone remembers to ask* into *the wrong program cannot be written*.

``>=`` and not ``>``, on ``features.py``'s stated ground: a feature computed **at** T0 has already
seen T0, and T0 is the instant the decision is made. Half a block of hindsight is still hindsight.

Two different things called provenance
--------------------------------------

Ticket 28 requires the audit to cover "any vendor field whose value is recomputed over time". A
field whose source recomputes it has no knowable value *at* T0, so the claim that it is pre-T0 is
unverifiable — and :func:`require_pre_t0`'s third refusal already establishes that an unverifiable
claim is not a passing one. :class:`VendorMutability` makes that a value the record must carry, and
``MUTABLE_VENDOR_FIELD`` on a selection record is refused.

That enum used to be called ``Provenance`` and it is **not** the pre-T0 lattice. Where a value came
from relative to ``T0`` is :class:`universe.provenance.Origin`; it travels with the *value* through
arithmetic, and it is what catches a number laundered into an ordinary ``Decimal`` before any
selection type sees it. A record-level enum can never catch that, and the old name invited a reader
to think it had.

What this module does not guarantee
-----------------------------------

``as_of_block``, ``as_of_timestamp`` and ``provenance`` are **claims the caller makes**. Nothing
here can see the warehouse query that produced ``potential_buys``; if it used ``now()`` against a
continuously backfilled table, every record built from it is stamped pre-T0 and is not. The guard
binds what a record *says about itself*, and every guarantee downstream is conditional on the
caller's stamps being true.

``object.__setattr__`` rewrites any field of any Python object. A record whose ``as_of_block`` is
rewritten after construction passes nothing again until something rebuilds it; ``verify()`` on the
frozen universe closes that consequence at artefact time and closes nothing about the act.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from contracts import AccountType, LookAheadViolation

from .protocol import (
    PreT0Sealed,
    T0Instant,
    WindowKey,
    normalise_selection_account,
    pre_t0_sealed,
    require_pre_t0_int,
)
from .provenance import PRE_T0_ZERO, PreT0Decimal, require_pre_t0_value  # noqa: F401


class VendorMutability(str, Enum):
    """Whether a vendor recomputes a field, which is **not** the pre-T0/post-T0 lattice.

    Renamed from ``Provenance``. The old name was the audit's finding in miniature: a reader met
    ``provenance=POINT_IN_TIME`` on a selection record and reasonably concluded the record's
    provenance had been established, when what had been established was only that the *vendor* does
    not recompute the field. Where a value came from relative to ``T0`` is
    :class:`universe.provenance.Origin`, it travels with the value rather than with the record, and
    the two must never again be mistaken for each other.

    Two values, and the second exists to be refused on the selection path. There is no third,
    because "probably point-in-time" is the claim this enum exists to stop anybody making.
    """

    #: Computed from state as it stood at a stated block, and not recomputed since.
    POINT_IN_TIME = "POINT_IN_TIME"

    #: A vendor field whose source recomputes it. Its value at T0 is unknowable, so the claim that
    #: it is pre-T0 cannot be checked — and an unverifiable claim is not a passing one.
    MUTABLE_VENDOR_FIELD = "MUTABLE_VENDOR_FIELD"


@dataclass(frozen=True)
class FieldBlock:
    """Per-field provenance for one field of one observation: the field's name and its block.

    A nominal pair rather than a ``Dict[str, int]``. The audit named ``Mapping``-shaped inputs as the
    most dangerous container tunnel on a selection path, and this one is on the path that decides
    whether a record is refused for look-ahead — a dict accepts any key, so an entry naming a field
    the record does not have used to be caught only by a separate scan.
    """

    field_name: str
    block: int

    def __post_init__(self) -> None:
        if not isinstance(self.field_name, str) or not self.field_name.strip():
            raise ValueError(
                "a per-field provenance entry must name the field it covers; an unnamed entry is "
                "provenance nobody is checking and it reads as though the field were covered"
            )
        object.__setattr__(self, "field_name", self.field_name.strip())
        require_pre_t0_int(self.block, "FieldBlock[{}].block".format(self.field_name))


@dataclass(frozen=True)
class LabelHit:
    """Membership of one §6.2 labelled set, with the provenance of the label itself.

    §6.2's labelled sets — ``labels.mev_ethereum``, ``labels.sandwich_attackers``,
    ``labels.arbitrage_traders``, ``dex.sandwiches``, ``dex.atomic_arbitrages`` — are all
    continuously recomputed. This type is where that fact becomes visible rather than implicit: a
    wallet excluded on today's label may be excluded for something it did *after* T0, which is
    look-ahead in the exclusion direction.

    It is counted and reported rather than refused, and that is the weakest joint in this package.
    Refusing it outright would make ticket 25 unbuildable against the only label data that exists.
    :attr:`universe.census.UniverseCensus.mutable_label_exclusions` carries the exposure per window.
    """

    set_name: str
    snapshot_block: int
    provenance: VendorMutability

    def __post_init__(self) -> None:
        if not self.set_name or not str(self.set_name).strip():
            raise ValueError(
                "a label hit must name the set it came from; an unnamed label is an exclusion "
                "nobody can reproduce or contest"
            )
        object.__setattr__(self, "set_name", str(self.set_name).strip())
        require_pre_t0_int(self.snapshot_block, "LabelHit.snapshot_block")
        if not isinstance(self.provenance, VendorMutability):
            raise TypeError(
                "LabelHit.provenance must be a VendorMutability, got {}. A label with no stated "
                "provenance would be counted beside a point-in-time one and the bias exposure "
                "would read as zero.".format(type(self.provenance).__name__)
            )


@dataclass(frozen=True)
class AccountEvidence:
    """The measured inputs to §6.2's infrastructure test, and nothing else.

    **Every ``Optional`` means UNMEASURED, never zero.** A rule whose evidence is ``None`` does not
    fire, and the account is recorded as *unassessed* for that rule rather than as passing it. A
    ``None`` treated as a pass is how "we did not test independence" becomes "independence is
    fine" — and it flatters the universe, because an unassessed router is admitted.

    The ratios are :class:`universe.provenance.PreT0Decimal`, never bare ``Decimal``. Each of them
    fires an eligibility rule, so each of them influences the composition of the candidate universe
    — which is exactly the set of values the invariant says may not originate after ``T0``. A bare
    ``Decimal`` here would be a laundered forward ratio arriving in the one place nothing checks.
    ``PreT0Decimal`` refuses a float on sight and refuses NaN, because a NaN compares ``False``
    against every bound and would read as an ordinary non-firing rule.
    """

    #: Distinct addresses that funded this account.
    distinct_funding_sources: Optional[int] = None

    #: Distinct addresses that received value this account settled. More than one principal is the
    #: single measurable consequence of "infrastructure passing through other people's
    #: transactions", and it is what routers, aggregators, relayers, bundlers, bridges and CEX hot
    #: wallets have in common. They are not six rules; they are one.
    distinct_beneficiaries: Optional[int] = None

    #: Direct evidence of settlement on behalf of others, where the data layer can state it.
    settles_for_other_principals: Optional[bool] = None

    #: Holders of a share token issued against this account's capital. ``None`` is *no share
    #: token*, which is not the same fact as a share token nobody holds.
    share_token_holders: Optional[int] = None

    #: Tokens this account deployed and also traded. §6.2's "deployers trading their own token".
    deployed_tokens_traded: Optional[int] = None

    #: Share of blocks in which the account quoted both sides. Market-making inventory.
    two_sided_quote_share: Optional[PreT0Decimal] = None

    #: Dune's ``likely_bots``: failed / total > 0.9.
    failed_tx_share: Optional[PreT0Decimal] = None

    #: Dune's ``likely_bots``: >= 25 tx/hour alongside >= 100 tx.
    max_tx_per_hour: Optional[int] = None

    total_tx: Optional[int] = None

    #: Dune's ``likely_bots``: >= 2,500 tx with <= 30 distinct senders.
    distinct_senders: Optional[int] = None

    #: The inverse "human" filter: a retail trader takes weekends off, a bot has zero skew.
    day_of_week_skewness: Optional[PreT0Decimal] = None

    #: The inverse "human" filter: mean inter-trade gap > 60 minutes.
    mean_inter_trade_gap_seconds: Optional[int] = None

    #: Whether the economic controller could be identified at all. ``False`` fires §6.2's catch-all;
    #: ``None`` means nobody looked, which is not the same claim.
    controller_identified: Optional[bool] = None

    #: Whether netting completed for this account. ``False`` fires ``ENRICHMENT_INCOMPLETE``, which
    #: is a named coverage rule rather than a residual bucket.
    netting_complete: bool = True

    labels: Tuple[LabelHit, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "labels", tuple(self.labels))
        for name in ("distinct_funding_sources", "distinct_beneficiaries", "share_token_holders",
                     "deployed_tokens_traded", "max_tx_per_hour", "total_tx", "distinct_senders",
                     "mean_inter_trade_gap_seconds"):
            value = getattr(self, name)
            if value is None:
                continue
            require_pre_t0_int(value, "AccountEvidence.{}".format(name))
            if value < 0:
                raise ValueError(
                    "AccountEvidence.{} is {}; a count is a magnitude, and a negative one would "
                    "compare below every threshold and read as a rule that did not "
                    "fire".format(name, value)
                )
        for name in ("settles_for_other_principals", "controller_identified"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise TypeError(
                    "AccountEvidence.{} must be a bool or None (unmeasured), got {}".format(
                        name, type(value).__name__
                    )
                )
        if not isinstance(self.netting_complete, bool):
            raise TypeError(
                "AccountEvidence.netting_complete must be a bool; it decides a named coverage "
                "exclusion and there is no unmeasured state for it — either the account was netted "
                "or it was not"
            )
        for name in ("two_sided_quote_share", "failed_tx_share", "day_of_week_skewness"):
            value = getattr(self, name)
            if value is None:
                continue
            object.__setattr__(
                self, name, require_pre_t0_value(value, "AccountEvidence.{}".format(name))
            )
        for hit in self.labels:
            if not isinstance(hit, LabelHit):
                raise TypeError(
                    "AccountEvidence.labels holds LabelHit values, got {}. A bare set name would "
                    "reach an exclusion with no provenance, and the mutable-label bias exposure "
                    "would be uncountable.".format(type(hit).__name__)
                )

    def label_names(self) -> Tuple[str, ...]:
        return tuple(hit.set_name for hit in self.labels)

    def label_provenance(self, set_name: str) -> Optional[VendorMutability]:
        for hit in self.labels:
            if hit.set_name == set_name:
                return hit.provenance
        return None


@pre_t0_sealed
@dataclass(frozen=True)
class AccountWindowObservation(PreT0Sealed):
    """One account, measured over one training window, entirely before ``T0``.

    ``t0`` is a **field**, not an argument to a checker. :func:`require_pre_t0` runs in
    ``__post_init__``, so a post-T0 observation is not constructible at all — there is no window
    between building one and checking it in which a forward-looking record exists.

    ``as_of_timestamp`` is **required**, unlike ``WalletFeatures.as_of_timestamp``. This record is
    always window-scoped and a timestamp-free record cannot be checked against T0's second edge; the
    optionality that is right for a generic feature record is a hole here.

    ``field_blocks`` is optional per-field provenance, for the "one forward-looking field among
    fifteen" case that a single record-level ``as_of_block`` cannot express. Its keys are restricted
    to this record's own field names, so a typo is a refusal rather than an unchecked entry.

    The type is **sealed**. A subclass overriding ``__post_init__`` would drop the T0 check while
    remaining an ``isinstance`` — ``pipeline/inputs.py``'s ``type(item) is Transfer`` argument, one
    type over. Selection entry points therefore check ``type(x) is AccountWindowObservation``.
    """

    account: str
    window_key: WindowKey
    account_type: AccountType
    potential_buys: int
    valid_buys: int
    buy_volume_usd: PreT0Decimal
    active_days: int
    first_activity_block: int
    first_activity_ts: int
    wallet_age_days: int
    evidence: AccountEvidence
    as_of_block: int
    as_of_timestamp: int
    t0: T0Instant
    field_blocks: Tuple[FieldBlock, ...] = ()
    provenance: VendorMutability = VendorMutability.POINT_IN_TIME

    def __post_init__(self) -> None:
        object.__setattr__(self, "account", normalise_selection_account(self.account))
        if not isinstance(self.window_key, WindowKey):
            raise TypeError(
                "an observation must be keyed by a WindowKey, got {}".format(
                    type(self.window_key).__name__
                )
            )
        if not isinstance(self.account_type, AccountType):
            raise TypeError(
                "account_type must be a contracts.AccountType, got {}. §6.6 matches on it exactly, "
                "so a bare string would become an unmatchable category rather than an "
                "error.".format(type(self.account_type).__name__)
            )
        for name in ("potential_buys", "valid_buys", "active_days", "first_activity_block",
                     "first_activity_ts", "wallet_age_days", "as_of_block", "as_of_timestamp"):
            value = require_pre_t0_int(getattr(self, name), "{}.{}".format(self.account, name))
            if value < 0:
                raise ValueError(
                    "{}.{} is {}; every count and stamp on this record is a magnitude".format(
                        self.account, name, value
                    )
                )
        object.__setattr__(
            self, "buy_volume_usd",
            require_pre_t0_value(self.buy_volume_usd, "{}.buy_volume_usd".format(self.account)),
        )
        if self.buy_volume_usd < PRE_T0_ZERO:
            raise ValueError(
                "{} has buy_volume_usd {}; buy volume is a magnitude and a negative one would "
                "enter a distribution as an ordinary small value".format(
                    self.account, self.buy_volume_usd
                )
            )
        if not isinstance(self.evidence, AccountEvidence):
            raise TypeError(
                "{} must carry an AccountEvidence, got {}. §6.2's test is applied to measured "
                "evidence; a duck-typed object would let a rule read a value nobody "
                "measured.".format(self.account, type(self.evidence).__name__)
            )
        if type(self.t0) is not T0Instant:
            raise TypeError(
                "{} must carry a T0Instant, got {}. The T0 check runs here rather than at a call "
                "site, so the record cannot be built without the instant to check it "
                "against.".format(self.account, type(self.t0).__name__)
            )
        if not isinstance(self.provenance, VendorMutability):
            raise TypeError(
                "{}.provenance must be a VendorMutability, got {}".format(
                    self.account, type(self.provenance).__name__
                )
            )

        object.__setattr__(self, "field_blocks", tuple(self.field_blocks))
        own_fields = set(self.__dataclass_fields__)
        for entry in self.field_blocks:
            if type(entry) is not FieldBlock:
                raise TypeError(
                    "{}.field_blocks holds FieldBlock values, got {}. A mapping here would accept "
                    "any key and any value, which is the container tunnel the barrier exists to "
                    "close.".format(self.account, type(entry).__name__)
                )
        stray = sorted({e.field_name for e in self.field_blocks} - own_fields)
        if stray:
            raise ValueError(
                "{}.field_blocks names field(s) this record does not have: {}. A per-field "
                "provenance entry that matches no field is provenance nobody is checking, and it "
                "reads as though the field were covered.".format(self.account, ", ".join(stray))
            )

        # There is deliberately **no** ``valid_buys <= potential_buys`` invariant, and the first
        # draft of this file had one. It reads as obviously true — netting turns potential buys
        # into valid ones, so how could there be more of them? — and it makes ticket 25's lower
        # buffer unreachable: the buffer admits 10-19 potential buys precisely so that an account
        # the warehouse decoder *under*-counts can still net to 20 or more. That is the whole
        # reason the floor is 10 rather than 20, and it is the direction §6.2 says to expect,
        # because the vendors decode Safes, 4337 accounts and exotic routes worst. A warehouse
        # "potential buy" is one coarse row per transaction; a transaction that buys two tokens
        # nets to two valid buys.
        #
        # So the two counts are measurements from two different passes and neither bounds the
        # other. What bounds them is the census, which has to reconcile either way.

        require_pre_t0(self, self.t0)


def require_pre_t0(record: "AccountWindowObservation", t0: T0Instant) -> None:
    """Refuse a selection record that carries any stamp at or after ``T0``.

    Five refusals. The first four mirror ``matching_null.features.require_pre_t0``; the fifth is
    this package's addition.

    1. a record-level block at or after T0;
    2. any ``field_blocks`` entry at or after T0 — the "one forward field among many" case;
    3. a timestamp with no T0 second to check it against. An unverifiable claim is not a passing
       one, and a guard a caller can switch off by omitting an argument is not a guard;
    4. a timestamp at or after T0;
    5. :attr:`VendorMutability.MUTABLE_VENDOR_FIELD`. A field whose source recomputes it has no knowable
       value at T0, so refusal (3)'s reasoning applies to it one step further out.

    ``>=`` and not ``>``: a value computed *at* T0 has already seen T0.

    :raises contracts.LookAheadViolation: on any of the five.
    """
    if type(t0) is not T0Instant:
        raise TypeError(
            "require_pre_t0 needs a T0Instant to check against, got {}. A bare block would leave "
            "the second edge unchecked, which is refusal (3) arriving through the "
            "argument.".format(type(t0).__name__)
        )

    subject = getattr(record, "account", None) or getattr(record, "wallet", "<unnamed>")

    def refuse(what: str, observed: int, boundary: int, unit: str) -> None:
        raise LookAheadViolation(
            "{} carries {} at {} {}, at or after T0 {} {}. Selection uses pre-T0 information only "
            "(§6.4): a value computed at T0 has already seen T0, so the boundary is >= and not >. "
            "A forward-period input does not crash and does not look wrong — it makes the "
            "selection fit the outcome and voids every number downstream of it.".format(
                subject, what, unit, observed, unit, boundary
            )
        )

    if getattr(record, "provenance", VendorMutability.POINT_IN_TIME) is VendorMutability.MUTABLE_VENDOR_FIELD:
        raise LookAheadViolation(
            "{} is stamped {}. Its source recomputes it, so its value at T0 is not knowable and "
            "the claim that it is pre-T0 cannot be checked. An unverifiable claim is not a passing "
            "one: the field is refused on the selection path rather than accepted with a "
            "caveat.".format(subject, VendorMutability.MUTABLE_VENDOR_FIELD.value)
        )

    as_of_block = getattr(record, "as_of_block")
    if as_of_block >= t0.block:
        refuse("as_of_block", as_of_block, t0.block, "block")

    for entry in sorted(getattr(record, "field_blocks", ()), key=lambda e: e.field_name):
        if entry.block >= t0.block:
            refuse("field_blocks[{}]".format(entry.field_name), entry.block, t0.block, "block")

    as_of_timestamp = getattr(record, "as_of_timestamp", None)
    if as_of_timestamp is None:
        raise LookAheadViolation(
            "{} carries no as_of_timestamp, so T0's second edge cannot be checked against it. This "
            "record is always window-scoped; a timestamp-free one is refused rather than half "
            "checked.".format(subject)
        )
    if as_of_timestamp >= t0.timestamp:
        refuse("as_of_timestamp", as_of_timestamp, t0.timestamp, "second")
