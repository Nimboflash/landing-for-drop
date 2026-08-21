"""What one composed run returns.

The shape is chosen so that a reviewer can answer, from this object alone and without re-running
anything: how many transactions went in, how many trades came out, where the difference went, how
much money is sitting in the reconciliation queue, and — for every wallet with a score — how much of
that score is a realized sale and how much is a mark on a pool.

That last one is the §10 requirement that composition is most likely to lose. Each stage carries the
realized / marked / dead mix correctly; the mix disappears at the joins, because a composition root
that returns ``Dict[str, Decimal]`` has thrown it away and nothing downstream can tell. So
:class:`WalletWindowResult` returns :class:`contracts.BuyQuality` — which cannot be constructed
without the three shares summing to one — and :class:`BuyAccount` keeps the per-buy row the shares
were summed from.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional, Tuple

from contracts import (
    BuyQuality,
    ClassificationStatus,
    NetTradeResult,
    PositionValue,
    TokenAgeBucket,
    ValueBasis,
    add,
)

from attribution import AttributionCoverage

from .census import (
    ACCOUNTING_STAGES,
    STAGE_ORDER,
    ClassificationCensus,
    CoverageReport,
    ExclusionRecord,
    QuarantineQueue,
    Stage,
    StageCounts,
)

ZERO = Decimal("0")


def _named_transactions(queue, stage):
    """The transactions ``stage``'s records name, in queue order, **with repeats kept**.

    Repeats survive so that :func:`_require_each_transaction_is_named_once` can see them. They are
    *not* what makes the caller's length comparison meaningful — the opposite, which is worth
    stating because an earlier version of this docstring had it backwards and the hole the mistake
    left was measured. Keeping a repeat makes two records naming one transaction *count as two*,
    which is precisely how a census of two undecodable transactions was published beside a queue in
    which only one transaction could be looked up. Deduplicating would have refused that and
    admitted the other half instead. Neither a set nor a multiset is the answer; the answer is that
    a repeat is itself the defect, and it is refused rather than counted either way.
    """
    return tuple(
        tx_hash for record in queue.by_stage(stage) for tx_hash in record.tx_hashes
    )


def _require_each_transaction_is_named_once(named, stage):
    """No transaction may be named twice under ``stage``. Refuse, rather than count it twice.

    :attr:`~pipeline.census.Stage.NETTING` and :attr:`~pipeline.census.Stage.INGESTION` are the two
    stages whose queue records are one-per-transaction: netting refuses a transaction once, and a
    receipt is undecodable once. (:attr:`~pipeline.census.Stage.FIFO` is not — a lot book goes to
    the queue whole, buys and sells together — which is why this is applied per stage rather than to
    the queue.)

    Without it, the length comparisons below are satisfiable by repetition. Measured on a
    constructed result: two ``Stage.INGESTION`` records both naming ``0x3``, beside
    ``census.undecodable == 2`` and ``stages.transactions_undecodable == 2``. Every count
    reconciled, ``reconciliation()`` printed ``quarantine_records 2`` — and
    ``quarantine.transactions`` held exactly one hash, so the report said two transactions could
    not be read while naming one. The same result with two ``Stage.NETTING`` records published two
    quarantined transactions over one.

    That is the half a length comparison cannot reach on its own, and it is worth refusing rather
    than tolerating for the reason a duplicate ``tx_hash`` is refused at the pipeline's door: there
    is no answer to give it. Whether the census meant two transactions or one is exactly what the
    duplicate destroys the evidence for.
    """
    seen = set()
    for tx_hash in named:
        if tx_hash in seen:
            raise ValueError(
                "the quarantine queue names {} twice under {}, and that stage's records are "
                "one-per-transaction. A repeated hash makes a count of two transactions "
                "satisfiable by one, so the reconciliation balances while the queue holds half of "
                "what it claims — and which of the two readings is the true one is precisely what "
                "the duplicate destroys the evidence for.".format(tx_hash, stage.value)
            )
        seen.add(tx_hash)


def _require_the_census_matches_the_evidence(result):
    """The three-door account, made from the published object's own fields.

    ``run_wallet_window`` already refuses a run that does not conserve its population, and that
    check is the stronger of the two because it compares against the list of transactions the
    caller handed in. This one is weaker on purpose and reaches somewhere the other cannot: it
    holds for **any** :class:`WalletWindowResult`, however assembled, because it needs nothing the
    result does not already carry.

    What it establishes is that the census's three terms are not free integers. Each is counted
    from something this object publishes beside it:

    * ``sum(census.counts.values())`` is the count of ``results`` — the census is built by
      tallying exactly that tuple, so a census claiming more classified transactions than there
      are results is claiming statuses for transactions the reader cannot look up;
    * ``census.quarantined`` is the count of transactions named under
      :attr:`~pipeline.census.Stage.NETTING`, and equals ``stages.netting_quarantined``;
    * ``census.undecodable`` is the count of transactions named under
      :attr:`~pipeline.census.Stage.INGESTION` — checked just above, where the shortfall's message
      belongs.

    and one more, which is the only field left in this object that nothing else could answer:

    * ``coverage.transactions_priced + coverage.transactions_unpriced`` is the population the
      run was handed. A priced/unpriced split over a smaller one reports coverage the run does not
      have, and the coverage report is assembled *after*
      :func:`pipeline.run._require_the_population_is_conserved` has already run, so no check
      anywhere saw it.

    **Four counts, and no fifth, because the rest follow.** Two more statements a reader would
    reasonably want — ``stages.netted == len(results)`` and *results + netting quarantines +
    undecodable == census.total* — are **derived**, not checked, and adding them would be adding a
    guard that can never fire. The derivation, given ``census.total == stages.transactions_in``
    above and :meth:`StageCounts.__post_init__`'s ``netted + netting_quarantined ==
    transactions_in - transactions_undecodable``::

        netted     = transactions_in - undecodable - netting_quarantined
        classified = total           - quarantined - undecodable          (the census's own sum)

    so once ``quarantined == netting_quarantined`` and ``classified == len(results)`` are checked,
    ``netted == len(results)`` is arithmetic and the three-door sum is the census's own invariant
    restated. Both are asserted on real output by
    ``test_the_derived_identities_hold_on_a_real_run`` rather than re-checked here, because a
    positive assertion on a measured result is a pin and an unreachable ``raise`` is not.

    That derivation is only as good as its premises, and the first of them —
    ``quarantined == netting_quarantined`` — was written here and then left standing behind
    ``if False:``, so for the length of two commits the paragraph above derived ``netted ==
    len(results)`` from a check that did not run. What walked through: a result publishing
    ``netted 3`` beside a ``results`` tuple of two and ``netting_quarantined 0`` beside a queue
    naming one quarantined transaction. It constructed, and its ``reconciliation()`` read straight
    down. ``test_a_result_whose_two_netting_quarantine_counts_disagree_is_refused`` is that result,
    kept as a test so the check cannot be disabled again without something going red — which is the
    other thing that was missing: **every check in this function was unpinned**, and deleting the
    whole of it left the suite green.

    **One statement here is not a count**, and it is made last, by
    :func:`_require_the_queue_names_transactions_this_result_knows`. The four above ask *how many*;
    that one asks *which*, which is the question no reconciliation can put — a stray hash in the
    queue is invisible to every sum in this object, including the three-door one.

    **What it does not establish**, and the omission is not closable here: that the population is
    the one the caller supplied. Nothing in this object records which transactions were handed in,
    so a run that dropped a row *and* shrank every count to match is internally perfect. That is
    the failure the tracer bullet found, it is what
    :func:`pipeline.run._require_the_population_is_conserved` exists for, and it can only be
    caught where the argument is still in scope.

    :raises ValueError: a census term is not supported by the evidence published beside it, or the
        queue names a transaction on the wrong side of the three doors.
    """
    census, stages, queue = result.census, result.stages, result.quarantine
    classified = sum(census.counts.values())
    if classified != len(result.results):
        raise ValueError(
            "the census classifies {} transaction(s) and the result carries {} netting result(s). "
            "The census is a tally *of* those results, so a difference means the coverage report "
            "and the §10 mix below it are computed over a population the reader cannot look "
            "up.".format(classified, len(result.results))
        )
    if census.quarantined != stages.netting_quarantined:
        raise ValueError(
            "the census reports {} transaction(s) quarantined at netting and the stage counts "
            "report {}. Both are the same fact, and a result carrying two answers to it publishes "
            "whichever one the reader happens to look at — reconciliation() prints the stage "
            "count.".format(census.quarantined, stages.netting_quarantined)
        )
    netting_named = _named_transactions(queue, Stage.NETTING)
    _require_each_transaction_is_named_once(netting_named, Stage.NETTING)
    if census.quarantined != len(netting_named):
        raise ValueError(
            "{} transaction(s) were quarantined at netting and {} are named in the queue. A count "
            "says money is sitting in the reconciliation queue; only the record says whose and "
            "which, and addendum §8's queue cannot be worked from a number. Counted as "
            "transactions rather than as records, for the reason the ingestion check above "
            "is.".format(census.quarantined, len(netting_named))
        )
    covered = result.coverage.transactions_priced + result.coverage.transactions_unpriced
    if covered != stages.transactions_in:
        raise ValueError(
            "the coverage report splits {} transaction(s) into priced and unpriced against {} "
            "handed to the run. A priced/unpriced split over a smaller population reports "
            "coverage the run does not have, and it is the last field in this object that was "
            "answerable from nothing else in it.".format(covered, stages.transactions_in)
        )
    _require_the_queue_names_transactions_this_result_knows(result)


def _require_the_queue_names_transactions_this_result_knows(result):
    """Each stage's records name transactions on the side of the three doors that stage is on.

    The four checks above are about *how many*. This one is about *which*, and it is the only
    statement in this module that a count cannot make. Two rules, one per side:

    * :attr:`~pipeline.census.Stage.INGESTION` and :attr:`~pipeline.census.Stage.NETTING` are the
      doors a transaction leaves by **instead of** producing a netting result. One of their records
      naming a transaction that *is* in ``results`` is that transaction leaving by two doors;
    * every other stage runs on transactions that already have one. A
      :attr:`~pipeline.census.Stage.FIFO` or :attr:`~pipeline.census.Stage.MARKING` record naming a
      transaction that is in no result names a transaction this object accounts for nowhere.

    The second is not a hypothetical tidying-up. It is the assumption
    :func:`pipeline.run._require_the_population_is_conserved` is built on and does not check: that
    function deliberately excludes the FIFO and MARKING slices from the three-door sum, on the
    stated grounds that they name transactions that already have a netting result. Where that stops
    being true the exclusion stops being a correction and becomes a blind spot — the stray is in no
    door, and the sum still balances because the stage it is in was never counted. Measured on a
    constructed result: a ``Stage.FIFO`` record naming ``0xdeadbeef`` beside a census of two and a
    ``results`` tuple of two published, with ``quarantine.transactions`` reporting a hash that
    appears nowhere else in the object.

    The rule holds by construction in ``run_wallet_window`` — every FIFO and MARKING record is built
    from a netting result's own ``tx_hash`` — which is exactly why it is worth stating: an
    invariant that is true by construction and checked nowhere is one a later edit is free to break
    silently, and the check that would have caught the break is one that was told to look away.
    """
    netted = {row.tx_hash for row in result.results}
    for stage in ACCOUNTING_STAGES:
        named = _named_transactions(result.quarantine, stage)
        if stage in (Stage.INGESTION, Stage.NETTING):
            strays = sorted({tx_hash for tx_hash in named if tx_hash in netted})
            if strays:
                raise ValueError(
                    "the queue names {} under {} and the same transaction(s) carry a netting "
                    "result. {} is a door a transaction leaves by *instead of* being netted, so a "
                    "transaction in both has been accounted for twice and every share below is "
                    "over a denominator larger than the population.".format(
                        ", ".join(strays), stage.value, stage.value
                    )
                )
            continue
        strays = sorted({tx_hash for tx_hash in named if tx_hash not in netted})
        if strays:
            raise ValueError(
                "the queue names {} under {} and no netting result carries that hash. Every stage "
                "after netting runs on transactions netting resolved, so a record here naming one "
                "that is in no result names a transaction this result accounts for nowhere — and "
                "it is invisible to the three-door sum, which excludes this stage precisely "
                "because its records are supposed to name transactions that already have a "
                "result.".format(", ".join(strays), stage.value)
            )


@dataclass(frozen=True)
class BuyAccount:
    """One valid buy's 30-day account: what was sold, what was still held, what it was worth.

    This is the row §4.4 is defined over and the row §10's mix is summed from. It is carried on the
    result rather than reduced away because the aggregate is not auditable without it: "80% of this
    wallet's score rests on marking" is a claim about which buys, on which pools, at which horizon.

    ``open_raw`` is the quantity still held **at this buy's own 30-day horizon**, which is not the
    same as the quantity still held at the end of the window. A sale that happens on day 40 does not
    make the position realized on day 30; ``late_sold_raw`` counts what was sold after the horizon
    and is included in ``open_raw`` for exactly that reason. Folding the late sale into the realized
    leg would be §4.4 Case 1 applied to a position Case 2 governs, and it would flatter every wallet
    that held a loser past the horizon and sold it into a bounce.
    """

    buy: NetTradeResult
    bucket: TokenAgeBucket
    cost_usd: Decimal
    realized_raw: int
    realized_cost_usd: Decimal
    realized_proceeds_usd: Decimal
    open_raw: int
    open_cost_usd: Decimal
    late_sold_raw: int
    position: Optional[PositionValue]
    marked_usd: Decimal
    dead_usd: Decimal
    return_pct: Decimal
    #: This buy's own §4.4 horizon: ``buy.timestamp + 30 days``.
    buy_horizon_ts: int
    #: How far the run's marking horizon sits past this buy's own. Reported rather than assumed
    #: away — a large lag means the mark values a later state than §4.4 asks for, and the reader is
    #: entitled to see by how much rather than to trust that it was small.
    horizon_lag_seconds: int

    def __post_init__(self):
        if self.buy.status is not ClassificationStatus.VALID_BUY:
            raise ValueError(
                "a buy account is built on a VALID_BUY; {} is {}".format(
                    self.buy.tx_hash, self.buy.status.value
                )
            )
        if self.realized_raw < 0 or self.open_raw < 0 or self.late_sold_raw < 0:
            raise ValueError("raw quantities on a buy account are unsigned")
        if self.realized_raw + self.open_raw != self.buy.asset_raw_amount:
            raise ValueError(
                "{}: {} raw realized + {} raw open != {} raw bought. Raw quantities are exact and "
                "carry no tolerance (§9.2); a mismatch here is quantity created or destroyed at the "
                "join between FIFO and marking.".format(
                    self.buy.tx_hash, self.realized_raw, self.open_raw,
                    self.buy.asset_raw_amount,
                )
            )
        if self.late_sold_raw > self.open_raw:
            raise ValueError(
                "{}: {} raw sold after the horizon exceeds the {} raw still open at it".format(
                    self.buy.tx_hash, self.late_sold_raw, self.open_raw
                )
            )
        if self.position is None and self.open_raw != 0:
            raise ValueError(
                "{}: {} raw units are open at the horizon with no PositionValue. An unmarked open "
                "position is a hole in the §10 mix, not a zero.".format(
                    self.buy.tx_hash, self.open_raw
                )
            )
        if self.position is not None and self.open_raw == 0:
            raise ValueError(
                "{}: a fully realized buy carries no open position to mark".format(
                    self.buy.tx_hash
                )
            )

    @property
    def is_dead(self):
        return self.position is not None and self.position.value_basis is ValueBasis.DEAD_ZEROED

    @property
    def marked_value_usd(self):
        """What the open remainder is worth. Zero for a dead pool — that is the §4.4 Case 3 answer,
        and it is distinct from ``dead_usd``, which is the *exposure* the zero verdict decided."""
        return ZERO if self.position is None else self.position.value_usd

    @property
    def accounted_usd(self):
        """The §10 basis total for this buy: realized + marked + dead."""
        return add(add(self.realized_proceeds_usd, self.marked_usd), self.dead_usd)


@dataclass(frozen=True)
class WalletOutcome:
    """One wallet's window: its score if it has one, and the reason if it does not.

    ``quality`` and ``unscorable_reason`` are mutually exclusive and exactly one is set. A wallet
    with no score is a finding — no buys, every buy priced at zero, no value basis anywhere — and it
    is reported as such rather than as a score of zero, which would read as flat performance.
    """

    wallet: str
    quality: Optional[BuyQuality]
    unscorable_reason: Optional[str]
    accounts: Tuple[BuyAccount, ...]
    n_buys: int
    n_sells: int
    n_buys_quarantined: int
    n_sells_quarantined: int

    def __post_init__(self):
        object.__setattr__(self, "accounts", tuple(self.accounts))
        if (self.quality is None) == (self.unscorable_reason is None):
            raise ValueError(
                "wallet {} must carry either a BuyQuality or the reason it has none, and never "
                "both: a score of zero and the absence of a score are different facts".format(
                    self.wallet
                )
            )
        if self.quality is not None and self.quality.n_buys != len(self.accounts):
            raise ValueError(
                "wallet {} scored {} buys but carries {} accounts".format(
                    self.wallet, self.quality.n_buys, len(self.accounts)
                )
            )

    @property
    def is_scored(self):
        return self.quality is not None


@dataclass(frozen=True)
class WalletWindowResult:
    """One window, composed end to end, with its own accounting attached.

    ``stages_run`` is the sequence of stages the run actually entered, and it is checked against
    :data:`pipeline.census.STAGE_ORDER` here. §4's order is not a preference — netting cannot group
    transfers before an owner is known, and marking cannot value a remainder before FIFO says what
    is left — so the constraint is enforced against the run rather than described in prose.
    :attr:`pipeline.census.Stage.INGESTION` is absent from that sequence and belongs absent: it is
    not a §4 stage and nothing runs it, its refusals arrive already made.

    The constructor also refuses a result whose undecodable population is **counted but not
    named**. Two checks, and they are different statements: the census and the stage counts must
    agree on how many transactions ingestion could not read, and the queue must **name** exactly as
    many transactions under :attr:`~pipeline.census.Stage.INGESTION` as the census counts. A count
    alone tells a reader that something was lost; the record tells them which transaction, which
    contract and which event topic — and classifying that topic in ``ingest.events.SIGNATURES`` is
    the entire remedy, so a count without a record is a finding nobody can act on.

    That second check counts **transactions, not records**, and the distinction is not pedantry:
    :class:`~pipeline.census.QuarantineRecord` carries ``tx_hashes`` in the plural precisely because
    one record may hold several transactions (a FIFO lot book goes to the queue whole). A check on
    ``len(records)`` reads as one-per-transaction and is not — one record naming two undecodable
    transactions satisfied it while the census counted one, and two records naming the *same*
    transaction satisfied it while the census counted two. Both were measured on a constructed
    result and both published.

    Counting transactions closed the first of those two and **not** the second, and this paragraph
    said otherwise until the second was constructed again and published again: two
    ``Stage.INGESTION`` records both naming ``0x3``, beside ``census.undecodable == 2``, still
    reconciled — a length comparison cannot tell two transactions from one hash written twice.
    :func:`_require_each_transaction_is_named_once` is what closes it, and it is a refusal rather
    than a deduplication for the reason given there.

    The census is checked against the evidence this object carries
    --------------------------------------------------------------

    :func:`pipeline.run._require_the_population_is_conserved` performs the three-door account —
    every transaction handed in leaves as a netting result, a netting quarantine or an ingestion
    quarantine — but it runs at **assembly**, inside ``run_wallet_window``, against the argument
    list. It cannot run here: the identity of the rows handed in is not a field on this type and
    should not become one.

    What *is* here is the evidence for all three doors — ``results``, and the queue's
    :attr:`~pipeline.census.Stage.NETTING` and :attr:`~pipeline.census.Stage.INGESTION` slices —
    and until :func:`_require_the_census_matches_the_evidence` existed nothing compared the census
    to any of it. Measured, on results constructed by hand: a ``census`` counting seven classified
    transactions published beside ``results=()``; a ``CoverageReport`` describing three
    transactions published beside ``transactions_in=7``; a queue naming a transaction no count
    knew about. Each one constructed, and each one printed a ``reconciliation()`` that read
    straight down and reconciled.

    So the same account is made again here, from this object's own fields, and it is the check that
    survives a caller who assembles a result without going through ``run_wallet_window`` — which
    every published number does go through today, and which nothing in the type system requires.
    """

    window: int
    stages_run: Tuple[Stage, ...]
    stages: StageCounts
    census: ClassificationCensus
    attribution: AttributionCoverage
    coverage: CoverageReport
    wallets: Tuple[WalletOutcome, ...]
    quarantine: QuarantineQueue
    excluded: Tuple[ExclusionRecord, ...]
    results: Tuple[NetTradeResult, ...]

    def __post_init__(self):
        object.__setattr__(self, "stages_run", tuple(self.stages_run))
        object.__setattr__(self, "wallets", tuple(self.wallets))
        object.__setattr__(self, "excluded", tuple(self.excluded))
        object.__setattr__(self, "results", tuple(self.results))
        if self.stages_run != STAGE_ORDER:
            raise ValueError(
                "stages ran as {} but §4 fixes the order at {}. The order is load-bearing: netting "
                "groups signed transfers by owner and cannot start before attribution, and marking "
                "values what FIFO left open.".format(
                    " -> ".join(s.value for s in self.stages_run),
                    " -> ".join(s.value for s in STAGE_ORDER),
                )
            )
        if self.census.total != self.stages.transactions_in:
            raise ValueError(
                "the census covers {} transactions and the run saw {}".format(
                    self.census.total, self.stages.transactions_in
                )
            )
        if self.census.undecodable != self.stages.transactions_undecodable:
            raise ValueError(
                "the census reports {} undecodable transaction(s) and the stage counts report {}. "
                "Both are the same fact and a result carrying two answers to it publishes whichever "
                "one the reader happens to look at".format(
                    self.census.undecodable, self.stages.transactions_undecodable
                )
            )
        named = _named_transactions(self.quarantine, Stage.INGESTION)
        _require_each_transaction_is_named_once(named, Stage.INGESTION)
        if len(named) != self.census.undecodable:
            raise ValueError(
                "{} transaction(s) could not be decoded and {} are named in the queue. Counted is "
                "not enough: a reader who sees a non-zero undecodable count and no queue entry "
                "knows only that something was lost, not which transaction, which contract or "
                "which event — and the whole remedy is to classify a topic in "
                "ingest.events.SIGNATURES, which needs the topic. One record per transaction, "
                "always — and counted here as transactions rather than as records, because "
                "QuarantineRecord.tx_hashes is plural and a record naming two of them would "
                "otherwise satisfy a count of one.".format(self.census.undecodable, len(named))
            )
        if len(self.excluded) != self.stages.attributions_excluded:
            raise ValueError(
                "{} exclusion records against {} excluded attributions; §8 refusals are counted "
                "*and* named, so the two must agree".format(
                    len(self.excluded), self.stages.attributions_excluded
                )
            )
        _require_the_census_matches_the_evidence(self)

    @property
    def qualities(self):
        # type: () -> Dict[str, BuyQuality]
        """Per-wallet :class:`contracts.BuyQuality`, for the wallets that have one."""
        return {w.wallet: w.quality for w in self.wallets if w.quality is not None}

    @property
    def unscorable(self):
        # type: () -> Dict[str, str]
        return {w.wallet: w.unscorable_reason for w in self.wallets if w.quality is None}

    @property
    def accounts(self):
        """Every buy account in the run, wallet order then buy order."""
        return tuple(account for wallet in self.wallets for account in wallet.accounts)

    def reconciliation(self):
        """The N-in / M-out account, as an ordered mapping a reviewer can read straight down.

        Every line is a count this result already carries; the method exists so the reconciliation
        is a thing the result *does* rather than a thing a reader has to reassemble correctly.
        """
        stages = self.stages
        lines = [
            ("transactions_in", stages.transactions_in),
            ("transactions_undecodable", stages.transactions_undecodable),
            ("attribution_excluded", stages.attributions_excluded),
            ("attribution_usable", stages.attributions_usable),
            ("netting_quarantined", stages.netting_quarantined),
            ("netted", stages.netted),
        ]
        for status in ClassificationStatus:
            # ``.format`` rather than ``+``: ``status.value`` is a string, but the frozen-context
            # scanner knows ``value`` as a Decimal-annotated field name on the seam and would read
            # the concatenation as unguarded Decimal arithmetic. Writing round the false positive
            # keeps the check's signal clean, which is worth more than the concatenation.
            lines.append(("status_{}".format(status.value), self.census.counts[status]))
        lines.extend([
            ("buys", stages.buys),
            ("sells", stages.sells),
            ("fifo_books", stages.fifo_books),
            ("fifo_books_quarantined", stages.fifo_books_quarantined),
            ("consumptions", stages.consumptions),
            ("open_positions_marked", stages.open_positions_marked),
            ("buys_quarantined", stages.buys_quarantined),
            ("buys_outside_window", stages.buys_outside_window),
            ("buys_unscored", stages.buys_unscored),
            ("sells_quarantined", stages.sells_quarantined),
            ("buys_scored", stages.buys_scored),
            ("wallets_seen", stages.wallets_seen),
            ("wallets_scored", stages.wallets_scored),
            ("wallets_unscorable", stages.wallets_unscorable),
            ("quarantine_records", len(self.quarantine)),
            ("quarantine_transactions", len(self.quarantine.transactions)),
        ])
        return tuple(lines)
