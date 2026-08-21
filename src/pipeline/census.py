"""The accounting a composed run owes its reader.

Composition is where a population quietly shrinks. Each stage has a legitimate reason to hand back
fewer rows than it received — an owner that cannot be established, a transaction that is not a
trade, a lot book that cannot be divided, a pool nothing can price — and every one of those reasons
is correct in isolation. What is not correct is the sum of them arriving as a smaller number with no
statement of what happened to the difference.

So every type in this module exists to make one sentence checkable: **N transactions went in, M
trades came out, and here is the account of N − M.** The reconciliation is enforced in
``__post_init__`` rather than asserted in a report, because a report is written once and a
constructor runs on every result.

Four distinctions are load-bearing and are kept apart deliberately:

* **excluded** — the transaction was seen, attributed, and refused entry to the primary metric by
  §8. It is a decision with a rule behind it.
* **quarantined** — the input is real and unsupported, and someone has to look at it (addendum §8).
  It is an open question.
* **classified as a non-trade** — netting reached a settled finding: reverted, round trip, no clear
  endpoint. It is an answer.
* **undecodable** — the receipt carried an event ``ingest.events.SIGNATURES`` does not list, so
  nothing about what the transaction *did* is known. It is not an open question about a value; it
  is the absence of a value, and the work it calls for is to classify a topic rather than to price
  a leg.

Collapsing any two of them produces a coverage number that cannot be acted on, because "we refused
it", "we could not support it", "it was not a trade" and "we could not read it at all" call for
four different responses. The fourth is the one that was missing, and its absence was worse than a
collapse: an undecodable transaction did not reach this module at all, so it was not merged into
another bucket, it was subtracted from the denominator. ``total`` counted the population the
decoder could read and called it the population.

``None`` is never a zero here. A quarantine record with ``volume_usd=None`` is one nobody could
price, and reporting it as ``$0`` of quarantined volume would say the queue is cheap when what is
true is that its cost is unknown.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Dict, Optional, Tuple

from contracts import (
    AccountType,
    AttributionMethod,
    ClassificationStatus,
    add,
    divide,
    sub,
)

ZERO = Decimal("0")


class Stage(str, Enum):
    """Where in a run a transaction was lost — the five §4 stages, and the one before them.

    The §4 order is fixed by the specification and is not a scheduling detail: netting cannot group
    signed transfers before it knows whose they are, FIFO cannot assign a lot before a trade exists,
    marking cannot value a remainder before FIFO says what is left, and scoring cannot weight a
    return before both legs are accounted for.

    :attr:`INGESTION` is not one of them and is deliberately not pretending to be. It names the
    step *before* §4 begins — turning a receipt's logs into transfers — and a transaction can be
    lost there too: ``ingest.events.SIGNATURES`` is a closed registry, so an event nobody has
    enumerated refuses the whole receipt. Before this stage existed such a transaction did not
    reach the pipeline at all and therefore appeared in no census, no queue and no coverage report;
    the population a run measured was silently defined by what the decoder happened to know. It is
    listed here so the loss has a name, and :data:`ACCOUNTING_STAGES` rather than
    :data:`STAGE_ORDER` is what a queue is sorted by, because a stage that is not a §4 stage must
    not creep into the sequence ``WalletWindowResult`` checks the run against.
    """

    INGESTION = "ingestion"
    ATTRIBUTION = "attribution"
    NETTING = "netting"
    FIFO = "fifo"
    MARKING = "marking"
    SCORING = "scoring"
    #: Not a §4 stage and not a door out of the population. A RECONCILIATION record names a
    #: transaction that **has a result** — an addendum §8 residual above tolerance — routed to the
    #: reconciliation queue so its volume and age are visible, having been excluded from the primary
    #: metric. It is deliberately distinct from :attr:`NETTING`, whose records mean "netting refused
    #: this and produced no result": three invariants read a NETTING record as exactly that, and a
    #: residual is the opposite — present, not lost. See ``pipeline.run`` where residuals are routed.
    RECONCILIATION = "reconciliation"


#: The binding order of the **§4 stages**. ``run_wallet_window`` records the stages it actually
#: entered and the result refuses to be constructed if they arrived in any other sequence — the
#: constraint is checked against the run rather than left in a docstring.
#:
#: :attr:`Stage.INGESTION` is absent on purpose. It is not a §4 stage, ``run_wallet_window`` does
#: not enter it (its refusals arrive already made, as values), and admitting it here would make
#: every existing run's ``stages_run`` wrong for a reason that has nothing to do with §4's order.
STAGE_ORDER = (
    Stage.ATTRIBUTION,
    Stage.NETTING,
    Stage.FIFO,
    Stage.MARKING,
    Stage.SCORING,
)

#: Every stage a :class:`QuarantineRecord` may carry, in the order a reader meets them. This — not
#: :data:`STAGE_ORDER` — is what the queue is sorted by, so that an ingestion refusal has a defined
#: position rather than raising ``ValueError`` out of a sort key.
ACCOUNTING_STAGES = (Stage.INGESTION,) + STAGE_ORDER + (Stage.RECONCILIATION,)


def stage_rank(stage):
    """Where ``stage`` sits in :data:`ACCOUNTING_STAGES`. The queue's sort key."""
    return ACCOUNTING_STAGES.index(stage)


# -- the two ways a transaction leaves the population ---------------------------


@dataclass(frozen=True)
class ExclusionRecord:
    """One transaction refused entry to the primary metric by §8, with the rule that refused it.

    An exclusion is *not* a quarantine. The owner question was answered — with "not confidently
    enough" — and the answer is a rule applied, not a gap in the data. Recording it separately is
    what lets a reviewer see the §8 population shrink for the reason §8 gives, rather than
    discovering later that the shrinkage was a decoder gap wearing an exclusion's clothes.
    """

    tx_hash: str
    method: AttributionMethod
    account_type: AccountType
    reason: str

    def __post_init__(self):
        if not self.reason:
            raise ValueError(
                "an exclusion must name the rule that excluded it; an unexplained dropped event is "
                "prohibited outright by the failure policy"
            )


@dataclass(frozen=True)
class QuarantineRecord:
    """One real, unsupported input routed to the reconciliation queue (addendum §8).

    ``volume_usd`` is ``Optional`` and ``None`` means *unpriceable*, never *nothing*. A queue whose
    unpriceable entries report ``$0`` looks cheap for exactly the entries that are hardest to
    dismiss.

    ``tx_hashes`` is plural because the unit of quarantine is not always one transaction: a lot book
    that cannot be divided goes to the queue whole, buys and sells together, because a book missing
    half its events is not a smaller book, it is a wrong one.

    ``block_number`` is the age. Ticket 21 requires the queue to make age visible, "so a residual
    that has waited a month is not indistinguishable from one that arrived this morning" — a queue
    without it is a pile, not a queue. ``None`` means the entry has no single block: a book
    quarantine spanning several, or a refusal that happened before a block was known. Distinct from
    a block of zero, which no mainnet transaction has.
    """

    stage: Stage
    reason: str
    tx_hashes: Tuple[str, ...]
    wallet: Optional[str] = None
    asset: Optional[str] = None
    volume_usd: Optional[Decimal] = None
    block_number: Optional[int] = None

    def __post_init__(self):
        object.__setattr__(self, "tx_hashes", tuple(self.tx_hashes))
        if not self.tx_hashes:
            raise ValueError(
                "a quarantine record must name the transaction(s) it holds, or the queue cannot be "
                "worked and the volume it reports cannot be traced back to anything"
            )
        if not self.reason:
            raise ValueError("a quarantine record must say why")
        if self.volume_usd is not None and self.volume_usd < 0:
            raise ValueError(
                "quarantined volume is a magnitude; got {}".format(self.volume_usd)
            )
        if self.block_number is not None and (
            isinstance(self.block_number, bool) or not isinstance(self.block_number, int)
            or self.block_number < 0
        ):
            raise ValueError(
                "a quarantine record's block_number is an age, so it is a non-negative int or "
                "None; got {!r}".format(self.block_number)
            )


@dataclass(frozen=True)
class QuarantineQueue:
    """The queue, with its volume — the number §10 will not let be an omission.

    ``unpriced`` counts the records carrying no volume. Without it, ``total_volume_usd`` reads as the
    whole cost of the queue when it is only the part of it anyone could price.
    """

    records: Tuple[QuarantineRecord, ...]

    def __post_init__(self):
        object.__setattr__(self, "records", tuple(self.records))

    def __len__(self):
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    @property
    def transactions(self):
        """Every transaction in the queue, deduplicated — a book quarantine names several."""
        seen = []
        for record in self.records:
            for tx_hash in record.tx_hashes:
                if tx_hash not in seen:
                    seen.append(tx_hash)
        return tuple(seen)

    @property
    def unpriced(self):
        return sum(1 for record in self.records if record.volume_usd is None)

    @property
    def total_volume_usd(self):
        """Summed under the frozen context, in record order. ``$0`` over an empty queue is honest —
        there is nothing in it — and is a different statement from :attr:`unpriced`."""
        total = ZERO
        for record in self.records:
            if record.volume_usd is not None:
                total = add(total, record.volume_usd)
        return total

    def by_stage(self, stage):
        return tuple(record for record in self.records if record.stage is stage)

    @property
    def oldest_first(self):
        """The queue as work to be done, oldest entry first. Ticket 21's "visible age", ordered.

        A record with no ``block_number`` sorts last rather than first: an entry whose age is
        unknown is not evidence of a long wait, and putting it at the head would let an unpriceable,
        undatable refusal mask the residual that has genuinely been waiting. The tx-hash tiebreak
        keeps the order total, so two runs over the same queue produce the same worklist.
        """
        undated = [r for r in self.records if r.block_number is None]
        dated = [r for r in self.records if r.block_number is not None]
        dated.sort(key=lambda r: (r.block_number, r.tx_hashes))
        undated.sort(key=lambda r: r.tx_hashes)
        return tuple(dated) + tuple(undated)


# -- the census -----------------------------------------------------------------


@dataclass(frozen=True)
class ClassificationCensus:
    """Every transaction netting saw, by the status it landed in — including the zeroes.

    §10 asks the coverage question of the whole population, not of the part that produced a trade.
    ``counts`` therefore carries all seven statuses whether or not they occurred, so this run's
    census can be differenced against the next one's.

    ``unsupported_from_attribution`` splits the one bucket that carries two different findings.
    ``UNSUPPORTED`` is netting's status both for a transaction whose owner §8 refused and for a
    trade whose quote leg carries no price, and those call for entirely different work: the first is
    an attribution problem, the second a price-book gap. A single number covering both is the shape
    of a coverage report that cannot be acted on.

    ``undecodable`` is the fourth term and the newest, and it is kept apart from ``quarantined``
    for the same reason the three above are kept apart from each other. A quarantined transaction
    was read and could not be *supported*; an undecodable one was never read at all, because
    ``ingest.events.SIGNATURES`` is a closed registry and the receipt carried an event nobody has
    enumerated. The work each calls for is different — price the leg, versus classify the topic —
    and the second used to be invisible: the transaction never reached the pipeline, so ``total``
    counted a population one smaller than the one that existed and every share below was a share of
    the wrong denominator.
    """

    counts: Dict[ClassificationStatus, int]
    quarantined: int
    unsupported_from_attribution: int
    total: int
    #: Transactions ingestion could not decode. Counted here, named in the queue under
    #: :attr:`Stage.INGESTION`, and classified by nothing — netting never saw them.
    undecodable: int = 0

    def __post_init__(self):
        object.__setattr__(self, "counts", dict(self.counts))
        missing = [s for s in ClassificationStatus if s not in self.counts]
        if missing:
            raise ValueError(
                "the census omits {}; a coverage report that leaves out the statuses it never saw "
                "cannot be compared against the next run's".format(
                    ", ".join(s.value for s in missing)
                )
            )
        # Every count, not only ``undecodable``. A guard on one field of a set of four closes the
        # instance somebody traced and leaves the class open, and here the class is the whole
        # point: the reconciliation below is an *equation*, and a negative term satisfies it by
        # cancelling a positive one. ``quarantined=-2`` beside two classified transactions totals
        # zero and reconciles perfectly — a census that has classified two transactions while
        # reporting a population of none, which is the defect this type exists to refuse arriving
        # through the sign rather than through the arithmetic.
        for name, value in [("total", self.total),
                            ("quarantined", self.quarantined),
                            ("undecodable", self.undecodable),
                            ("unsupported_from_attribution", self.unsupported_from_attribution)] \
                + [("counts[{}]".format(s.value), n) for s, n in sorted(
                        self.counts.items(), key=lambda pair: pair[0].value)]:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    "the census reports {} = {!r}; a count of transactions is a non-negative int, "
                    "and a negative one does not fail the reconciliation below — it satisfies it "
                    "by cancelling another term, so the total comes out right about a population "
                    "that does not exist.".format(name, value)
                )
        classified = sum(self.counts.values())
        accounted = classified + self.quarantined + self.undecodable
        if accounted != self.total:
            raise ValueError(
                "the census accounts for {} classified + {} quarantined + {} undecodable = {} of "
                "{} transactions; the difference is an unexplained dropped event, which the "
                "failure policy prohibits. A transaction ingestion could not read is still a "
                "transaction: it belongs in `undecodable`, not outside the total.".format(
                    classified, self.quarantined, self.undecodable, accounted, self.total
                )
            )
        if self.unsupported_from_attribution > self.counts[ClassificationStatus.UNSUPPORTED]:
            raise ValueError(
                "{} UNSUPPORTED results are attributed to §8 exclusion but only {} exist".format(
                    self.unsupported_from_attribution,
                    self.counts[ClassificationStatus.UNSUPPORTED],
                )
            )

    @property
    def trades(self):
        return (self.counts[ClassificationStatus.VALID_BUY]
                + self.counts[ClassificationStatus.VALID_SELL])

    @property
    def unsupported_from_pricing(self):
        """The other half of ``UNSUPPORTED``: a trade whose quote leg had no price."""
        return (self.counts[ClassificationStatus.UNSUPPORTED]
                - self.unsupported_from_attribution)


@dataclass(frozen=True)
class StageCounts:
    """How many rows entered and left each of the five stages.

    Every field is a count of *events*, and the invariants below are the reconciliation the ticket
    asks a reviewer to be able to perform from the result alone. They are checked here so that a
    result which does not reconcile cannot be constructed, let alone published.

    ``transactions_in`` means **handed in**, not *decoded*, and the difference is the whole of why
    ``transactions_undecodable`` exists. The three §4 stage invariants below used to read
    ``resolved == transactions_in``; if ``transactions_in`` had been quietly redefined as "the ones
    ingestion could read" they would all still hold, and a run that lost a transaction before §4
    began would still reconcile perfectly against a population it had shrunk itself. So the
    undecodable count appears as a term in each of them instead: what went in equals what each
    stage handled *plus* what never reached it.
    """

    transactions_in: int
    #: Handed in, and never decoded. Subtracted from ``transactions_in`` in each of the three §4
    #: stage invariants below, because attribution, netting and their counts never saw these rows.
    transactions_undecodable: int
    attributions_resolved: int
    attributions_usable: int
    attributions_excluded: int
    netted: int
    netting_quarantined: int
    buys: int
    sells: int
    fifo_books: int
    fifo_books_quarantined: int
    consumptions: int
    open_positions_marked: int
    buys_scored: int
    buys_quarantined: int
    #: The §4.8 measurement tail: a buy after the window's end opens a lot so that the tail's sells
    #: match against the right basis, and belongs to the next window rather than to this score.
    buys_outside_window: int
    #: Buys that produced a complete account inside a wallet nobody could score. Neither scored nor
    #: quarantined, and therefore the one population that would otherwise fall between the two.
    buys_unscored: int
    sells_quarantined: int
    wallets_seen: int
    wallets_scored: int
    wallets_unscorable: int

    def __post_init__(self):
        for name, value in sorted(vars(self).items()):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    "StageCounts.{} must be a non-negative int, got {!r}".format(name, value)
                )
        self._require(
            self.transactions_undecodable <= self.transactions_in,
            "{} transactions could not be decoded out of {} handed in".format(
                self.transactions_undecodable, self.transactions_in
            ),
        )
        decodable = self.transactions_in - self.transactions_undecodable
        self._require(
            self.attributions_resolved + self.transactions_undecodable == self.transactions_in,
            "attribution returns a result for every transaction it is given — an UNRESOLVED owner "
            "is a typed status, not a dropped row — and it is given every transaction ingestion "
            "could decode, so {} resolved + {} undecodable against {} handed in is a hole".format(
                self.attributions_resolved, self.transactions_undecodable, self.transactions_in
            ),
        )
        self._require(
            self.attributions_usable + self.attributions_excluded == decodable,
            "every attribution is either usable for the primary metric or excluded and counted; "
            "{} + {} != {} decodable of {} handed in".format(
                self.attributions_usable, self.attributions_excluded, decodable,
                self.transactions_in,
            ),
        )
        self._require(
            self.netted + self.netting_quarantined == decodable,
            "netting returns exactly one result per transaction or refuses it outright; "
            "{} + {} != {} decodable of {} handed in".format(
                self.netted, self.netting_quarantined, decodable, self.transactions_in
            ),
        )
        accounted = (self.buys_scored + self.buys_quarantined + self.buys_outside_window
                     + self.buys_unscored)
        self._require(
            accounted == self.buys,
            "every valid buy is scored, quarantined, deferred to the next window, or left "
            "unscored with its wallet; {} + {} + {} + {} = {} against {} buys. A buy in none of "
            "the four has been dropped without a record, and §10's coverage report would then "
            "describe a smaller population than it claims".format(
                self.buys_scored, self.buys_quarantined, self.buys_outside_window,
                self.buys_unscored, accounted, self.buys,
            ),
        )
        self._require(
            self.sells_quarantined <= self.sells,
            "more sells quarantined ({}) than seen ({})".format(
                self.sells_quarantined, self.sells
            ),
        )
        self._require(
            self.fifo_books_quarantined <= self.fifo_books,
            "more lot books quarantined ({}) than built ({})".format(
                self.fifo_books_quarantined, self.fifo_books
            ),
        )
        self._require(
            self.wallets_scored + self.wallets_unscorable <= self.wallets_seen,
            "{} scored + {} unscorable exceeds the {} wallets seen".format(
                self.wallets_scored, self.wallets_unscorable, self.wallets_seen
            ),
        )

    @staticmethod
    def _require(condition, message):
        if not condition:
            raise ValueError(message)

    @property
    def trades(self):
        return self.buys + self.sells


# -- coverage -------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageReport:
    """Coverage as a share of notional, plus the population the share is silent about.

    A count-based coverage number is the one a reader most wants and the one that misleads most
    cheaply: ninety-nine dust transactions and one $2m transaction give 99% coverage while missing
    almost all of the money. So the headline here is USD-weighted.

    ``notional_usd_unpriced_transactions`` is the honest counterweight. A transaction netting could
    not price contributes to neither numerator nor denominator, so a population that is mostly
    unpriceable can report 100% coverage of the sliver that was. The count travels with the share
    for that reason, and :attr:`is_reportable` refuses the share outright when nothing was priced.
    """

    notional_usd_total: Decimal
    notional_usd_trades: Decimal
    notional_usd_quarantined: Decimal
    notional_usd_scored: Decimal
    transactions_priced: int
    transactions_unpriced: int

    def __post_init__(self):
        for name in ("notional_usd_total", "notional_usd_trades", "notional_usd_quarantined",
                     "notional_usd_scored"):
            value = getattr(self, name)
            if not isinstance(value, Decimal):
                raise TypeError(
                    "CoverageReport.{} must be a Decimal, never a float (seam rule), got "
                    "{}".format(name, type(value).__name__)
                )
            if value < 0:
                raise ValueError("CoverageReport.{} is negative: {}".format(name, value))
        if self.notional_usd_trades > self.notional_usd_total:
            raise ValueError(
                "trade notional {} exceeds the total notional {} it is a part of".format(
                    self.notional_usd_trades, self.notional_usd_total
                )
            )
        if self.notional_usd_scored > self.notional_usd_trades:
            raise ValueError(
                "scored notional {} exceeds the trade notional {} it is a part of".format(
                    self.notional_usd_scored, self.notional_usd_trades
                )
            )

    @property
    def is_reportable(self):
        """False when nothing was priceable. A share over a zero denominator is not 100%."""
        return self.notional_usd_total > 0

    @property
    def notional_usd_non_trades(self):
        return sub(self.notional_usd_total, self.notional_usd_trades)

    @property
    def trade_share(self):
        """Share of priced notional that netting resolved into a trade. ``None`` when unmeasurable.

        ``None`` rather than ``Decimal("1")`` or ``Decimal("0")``: a run in which nothing could be
        priced has no coverage to report, and either constant would read as a measurement.
        """
        if not self.is_reportable:
            return None
        return divide(self.notional_usd_trades, self.notional_usd_total)

    @property
    def scored_share(self):
        """Share of priced notional that reached a wallet score. ``None`` when unmeasurable."""
        if not self.is_reportable:
            return None
        return divide(self.notional_usd_scored, self.notional_usd_total)

    @property
    def quarantined_share(self):
        """Share of priced notional sitting in the reconciliation queue. ``None`` when unmeasurable.

        Deliberately a share of the same denominator as :attr:`trade_share`, so the two can be read
        against each other. It is not a partition of it — a quarantined lot book's volume was
        counted as trade notional first, which is exactly the point: the money was classified and
        then found unusable.
        """
        if not self.is_reportable:
            return None
        return divide(self.notional_usd_quarantined, self.notional_usd_total)


def classification_census(results, quarantined, unsupported_from_attribution, total,
                          undecodable=0):
    """Build the census from netting's results, with every status present.

    ``total`` is the population **handed to the run**, which is larger than ``len(results)`` by the
    transactions netting refused *and* by the ones ingestion could not read. Passing a ``total``
    that counts only what was decoded is the defect this signature exists to make awkward: the
    constructor reconciles the three terms against it and refuses, so a shrunken denominator cannot
    be published as a whole one.
    """
    counts = {status: 0 for status in ClassificationStatus}
    for result in results:
        counts[result.status] += 1
    return ClassificationCensus(
        counts=counts,
        quarantined=quarantined,
        unsupported_from_attribution=unsupported_from_attribution,
        total=total,
        undecodable=undecodable,
    )
