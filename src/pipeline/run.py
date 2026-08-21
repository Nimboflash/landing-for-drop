"""The composition root: the §4 stages, one window, one accounted answer.

    attribution  ->  netting  ->  fifo  ->  marking  ->  scoring

**What this composes, and what it does not.** These five are the stages §4 defines over one wallet
and one window, and they are the whole of ``run_wallet_window``. The other three builder modules
answer questions at a different granularity and are deliberately absent from this function rather
than folded into it: ``depth`` prices a *follower's* order at each of five capital levels (§4.5),
``matching_null`` shuffles within matched sets *across* wallets (§8), and ``gate_validation`` is the
arbiter and may not be imported by the code it judges at all. Composing them here would put a
per-follower and a cross-wallet computation inside a per-wallet loop, which is the wrong shape and
would make the wallet score depend on which other wallets happened to be in the call.

The order is §4's and is not rearrangeable. Netting groups signed transfers by
``(transaction, owner, token)`` and therefore cannot start before the owner is known; FIFO cannot
assign a lot before a trade exists; marking values what FIFO left open; scoring weights a return
that needs both legs. :data:`pipeline.census.STAGE_ORDER` records that sequence and
:class:`~pipeline.result.WalletWindowResult` refuses to be built if a run entered the stages in any
other one.

**What composition is for, and what it loses if nobody watches.** Every module here already refuses
correctly on its own. What no module can do alone is account for the population *between* them: each
stage hands back fewer rows than it received, for a reason that is right in isolation, and the
composed run is where those reasons either add up to a statement or turn into a shrug. Four rules,
each of which this module exists to hold:

* **A non-trade is still a transaction.** ``NetTradeResult`` is total — every transaction gets
  exactly one ``ClassificationStatus`` — and the full census travels to the result, zeroes included.
  A coverage report over the transactions that succeeded is not a coverage report.
* **A transaction nobody could read is still a transaction.** ``ingest.events.SIGNATURES`` is a
  closed registry, so an unlisted event refuses a whole receipt — correctly, since a partly-read
  transaction is a wrong answer rather than a small one. That refusal arrives here as a value
  (:class:`~pipeline.inputs.UndecodableTransaction`), is counted in the census, and is named in the
  queue with its topic and contract. Left as an exception it removed the transaction from the
  population *before the population was counted*, and then every reconciliation in this file held
  perfectly over a denominator the run had shrunk itself.
* **An §8 exclusion is counted and named.** An attribution that is not usable for the primary
  metric leaves the population by a rule, so the rule is recorded per transaction
  (:class:`~pipeline.census.ExclusionRecord`) and the count is reconciled against the exclusion list
  in the result's constructor.
* **A quarantine is a number, not an omission.** ``QuarantineRequired`` from any stage routes to a
  queue that carries its volume, and the volume is ``None`` when nobody could price it rather than
  ``$0``.
* **The §10 mix survives the joins.** Per-wallet results are :class:`contracts.BuyQuality`, which
  cannot exist without realized / marked / dead shares that sum to one, and the per-buy rows they
  were summed from are carried alongside.
* **One transaction is one row.** Every count above is keyed by ``tx_hash`` somewhere — the census
  split, the four sets recording which buys left the population, the map from a buy to the
  consumptions that realized it, the transactions each queue record names. None of those is a set
  *of transactions* unless the key identifies one, and no stage upstream establishes that it does,
  so this module establishes it at the boundary before any stage runs
  (:func:`_require_one_transaction_per_hash`). Two rows under one hash do not make the population
  smaller; they hand one lot book's sale to a different book's buy, and every rule above still
  reconciles over the result.
* **One spelling is one asset.** The hash was not the only identity key here. The pool book, the
  price book and the two mappings on :class:`~pipeline.inputs.WindowConfig` are all read through
  ``normalise_asset``, so their key space is the normalised one whether the caller spelled it that
  way or not, and two keys naming one asset arrive as two entries and leave as one — with the
  survivor decided by the order the caller's mapping iterates in. Refused at the same boundary
  (:func:`~pipeline.inputs.asset_keyed`), because a position marked against whichever pool arrived
  last is a different published return for the same input, and nothing in the census, the queue or
  the coverage report would say a choice had been made. The other half of the same rule: where the
  value names its own asset — a ``PoolState`` does — a key that disagrees with it is refused too.
  That one does not collapse anything; the lookup simply succeeds under the wrong name and marks
  the position against another token's pool, publishing -25% against a true -50% with an identical
  census and an empty queue.

**The one modelling choice this file makes, stated plainly.** §4.4 measures each buy over *its own*
following 30 days, so strictly every buy has a different horizon and therefore wants its own pool
snapshot. The seam supplies one :class:`contracts.PoolState` per pool, so this runs a single
window-level marking horizon and reports, per buy, how far that horizon sits past the buy's own
(``BuyAccount.horizon_lag_seconds``). The lag is a published number rather than an assumption,
because a mark taken well after day 30 is a different measurement and the reader is entitled to see
by how much. The run refuses a horizon *earlier* than ``window.end_ts + 30 days`` outright: §4.8
permits measurement to extend past the window edge precisely so that no sample is dropped and no
partial return is used, and a short horizon would produce partial returns that look like whole ones.

**Where that lag bites hardest, which is not the valuation.** The sentence above says a later mark is
a different *measurement*, and that undersells one case. Addendum §9.1's dead-pool conjunction is
evaluated on the same later pool state, so a venue that was exitable at a buy's own day 30 and drained
afterwards zeroes that position outright. The error is therefore not a small drift in a price; it is
the difference between a holding and a total loss, and it runs in one direction only — a pool can go
quiet between day 30 and the run horizon, and cannot un-quiet. ``horizon_lag_seconds`` is the number
that bounds how much later the verdict was taken, and a reader comparing a ``DEAD_ZEROED`` basis
against a large lag is looking at exactly this. Closing it needs a ``PoolState`` per buy horizon,
which is a change to the seam and not to this file.

Nothing here reads a clock, a file, a network, or an unseeded random source. The caller supplies the
transactions, the pool states, the quote prices, the window, and the horizon — all of them values a
run must be able to reproduce from its own record.
"""

from decimal import Decimal
from typing import Mapping  # noqa: F401  (3.9-compatible annotations)

from contracts import (
    ClassificationStatus,
    PoolState,
    QuarantineRequired,
    Transaction,
    ValueBasis,
    add,
    calc,
    divide,
    normalise_asset,
    sub,
)

from attribution import attribution_coverage, resolve_attribution
from fifo import match_fifo
from marking import mark_position, token_age_bucket
from netting import net_transaction, reconciliation_queue
from scoring import UnscorableWallet, buy_outcome, buy_quality_detail

from .census import (
    CoverageReport,
    ExclusionRecord,
    QuarantineQueue,
    QuarantineRecord,
    Stage,
    StageCounts,
    classification_census,
    stage_rank,
)
from .inputs import (
    MEASUREMENT_HORIZON_SECONDS,
    ObservedTransaction,
    UndecodableTransaction,
    Window,
    WindowConfig,
    asset_keyed,
    asset_pairs,
)
from .result import BuyAccount, WalletOutcome, WalletWindowResult

ZERO = Decimal("0")
ONE = Decimal("1")

__all__ = ["run_wallet_window"]


def run_wallet_window(transactions, pools, prices, window, config):
    """Run one evaluation window end to end and return the accounted result.

    :param transactions: :class:`~pipeline.inputs.ObservedTransaction` values — transfers and a
        sender, with the owner slot still empty, because attribution is the first stage and a
        pre-attributed input would have answered its question for it. A
        :class:`~pipeline.inputs.UndecodableTransaction` is accepted in the same sequence and is
        the carried status for a receipt ingestion could not read; see below for what happens to
        it.
    :param pools: ``{token: PoolState}`` — the pool snapshot each token's exit is walked along at the
        marking horizon. Keys are normalised; native ETH collapses onto WETH.
    :param prices: ``{quote_asset: Decimal}`` — **USD per raw unit** of a §4.6 quote asset. A
        mapping, deliberately not a callable: marking needs the per-raw-unit price itself and not
        only a value for a quantity, and a callable would have to be probed with a quantity of one
        to recover it.
    :param window: the :class:`~pipeline.inputs.Window` being evaluated.
    :param config: the :class:`~pipeline.inputs.WindowConfig` — marking horizon, §4.7 token trading
        starts, and any migration replacement pools.

    Every transaction supplied must lie between the window's start and the marking horizon. Anything
    earlier or later is a caller error and raises: it is not a data finding, and admitting it would
    silently widen or narrow the population the score is computed over. Transactions *after* the
    window's end but before the horizon are the §4.8 measurement tail — their sells are matched, and
    a buy among them opens a lot but is not scored, since it belongs to the next window.

    Every transaction supplied must also carry a ``tx_hash`` no other one carries, and that is a
    caller error of the same kind rather than a data finding — no block issues one hash twice. See
    :func:`_require_one_transaction_per_hash` for what a duplicate does to the answer and why it is
    refused here rather than held in the reconciliation queue.

    An undecodable transaction is counted and never scored
    ------------------------------------------------------

    A :class:`~pipeline.inputs.UndecodableTransaction` is counted in ``census.total``, counted in
    ``stages.transactions_undecodable``, and named in the quarantine queue under
    :attr:`~pipeline.census.Stage.INGESTION` with the topic, the contract and the log index that
    could not be read. It enters **no** §4 stage: attribution never sees it, netting assigns it no
    :class:`contracts.ClassificationStatus`, no lot book holds it, nothing marks it and nothing
    scores it.

    That exclusion is a decision, not a consequence of the plumbing, and the alternative is worth
    naming because it is the one that looks reasonable. A transaction whose legs are partly
    unreadable could be handed to netting with the legs that *did* decode, or with none — and both
    spellings say the same false thing: *this transaction moved no position we do not know about*.
    The tracer bullet holds the counterexample. Its 1inch limit-order fill closes a position opened
    nineteen days earlier; netted as a no-op, FIFO would leave that lot open, §4.4 Case 2 would
    mark it as *held at the horizon* against a pool state, and the run would publish a marked
    return on a position that had already been sold, with ``realized_share`` understated and an
    empty queue. A wrong number with a clean census beats no number in exactly the wrong direction.

    **What the exclusion costs, stated rather than assumed away.** It is a real loss, not a free
    win. The wallet's sells in that transaction are invisible, so a position it closed still reads
    as open and *will* be marked at the horizon — the same §4.4 Case 2 defect, arriving through the
    other half of the transaction. The difference is that it is now loud: the queue names the
    transaction and the topic, ``census.undecodable`` is non-zero, and the coverage report counts
    the transaction as unpriced. The run publishes a number it can be argued with, instead of one
    that looks complete. The remedy is not in this function: classify the topic in
    ``ingest.events.SIGNATURES``, with ``moves_value`` stated and a written reason.
    """
    if not isinstance(window, Window):
        raise TypeError("window must be a pipeline.Window, got {}".format(type(window).__name__))
    if not isinstance(config, WindowConfig):
        raise TypeError(
            "config must be a pipeline.WindowConfig, got {}".format(type(config).__name__)
        )

    prices = _normalised_prices(prices)
    pools = _normalised_pools(pools)
    _require_a_measurable_horizon(window, config)

    handed_in = tuple(transactions)
    for item in handed_in:
        if not isinstance(item, (ObservedTransaction, UndecodableTransaction)):
            raise TypeError(
                "run_wallet_window consumes ObservedTransaction values, or an "
                "UndecodableTransaction where ingestion could not read the receipt; got {}. The "
                "pipeline resolves attribution itself; a contracts.Transaction would already carry "
                "the answer the first stage exists to produce.".format(type(item).__name__)
            )
        _require_inside_the_measurement_period(item, window, config)
    # After the per-item checks, because a cross-item invariant over rows that are not yet
    # well-formed is a statement about the wrong thing. Over *both* kinds: an undecodable
    # transaction sharing a hash with a decoded one would put the same transaction in the census
    # twice, once as read and once as unreadable.
    _require_one_transaction_per_hash(handed_in)

    observed = tuple(i for i in handed_in if isinstance(i, ObservedTransaction))
    undecodable = tuple(i for i in handed_in if isinstance(i, UndecodableTransaction))

    stages_run = []
    quarantine = []

    # -- stage 0: what ingestion could not read ---------------------------------
    #
    # Not a §4 stage and not appended to ``stages_run``: nothing runs here. These rows arrived
    # already refused, and this loop is the accounting for them — one queue record each, naming the
    # topic, the contract and the log index, with volume None because a transaction nobody could
    # decode is a transaction nobody could price. ``None``, not zero: the cost of this entry is
    # unknown rather than nil.
    for item in undecodable:
        quarantine.append(QuarantineRecord(
            stage=Stage.INGESTION,
            reason=item.describe(),
            tx_hashes=(item.tx_hash,),
            volume_usd=None,
        ))

    # -- stage 1: attribution ---------------------------------------------------
    stages_run.append(Stage.ATTRIBUTION)
    attributions = []
    excluded = []
    txs = []
    for item in observed:
        attribution = resolve_attribution(
            item.tx_hash, item.tx_sender, item.transfers, item.context
        )
        attributions.append(attribution)
        txs.append(Transaction(
            tx_hash=item.tx_hash,
            block_number=item.block_number,
            timestamp=item.timestamp,
            success=item.success,
            attribution=attribution,
            transfers=item.transfers,
        ))
        if not attribution.is_usable_for_primary_metric:
            excluded.append(ExclusionRecord(
                tx_hash=item.tx_hash,
                method=attribution.method,
                account_type=attribution.account_type,
                reason=(
                    "§8 excludes this transaction from the primary metric: method={}, "
                    "account_type={}, owner={}. {}".format(
                        attribution.method.value,
                        attribution.account_type.value,
                        attribution.portfolio_owner,
                        " ".join(attribution.evidence),
                    )
                ),
            ))
    coverage = attribution_coverage(attributions)

    # -- stage 2: netting -------------------------------------------------------
    stages_run.append(Stage.NETTING)
    results = []
    netting_quarantined = 0
    for tx in txs:
        try:
            results.append(net_transaction(tx, prices))
        except QuarantineRequired as refusal:
            netting_quarantined += 1
            quarantine.append(QuarantineRecord(
                stage=Stage.NETTING,
                reason=str(refusal),
                tx_hashes=(tx.tx_hash,),
                wallet=tx.attribution.portfolio_owner,
                # Netting refused before it produced a result, so nothing priced this transaction.
                # None, not zero: the cost of this queue entry is unknown, not nil.
                volume_usd=None,
            ))
    # Canonical order, not the caller's. Every aggregate below accumulates over this tuple, and at
    # 38 digits each addition rounds — so a total that followed the order a list happened to be
    # assembled in would move when the same transactions arrived shuffled. §9.2 requires the number
    # to be reproducible, and "reproducible" cannot depend on how a caller sorted its input.
    results = tuple(sorted(results, key=lambda r: (r.block_number, r.tx_hash)))

    # An ABOVE_TOLERANCE_RESIDUAL result is not a refusal — netting produced it, priced it, and then
    # found its residual over the addendum §8 tolerance. It is not a trade, so the primary metric
    # never counts it (`trades` below filters on `is_trade`). Until this loop it landed nowhere else
    # either: no quarantine record, no volume total, no report. `netting.reconciliation_queue` had
    # no caller in the whole tree, so the residual was excluded from the headline number and then
    # made invisible — which is the silent exclusion ticket 21 exists to prevent. Routed here, its
    # volume (the notional netting DID price) and its age (block) travel into the queue.
    # Only ABOVE_TOLERANCE_RESIDUAL is routed here, not all of netting's QUEUED_STATUSES. The other
    # two — NO_CLEAR_ENDPOINT and UNSUPPORTED — are already accounted for elsewhere: UNSUPPORTED
    # from a §8 attribution exclusion carries an ExclusionRecord and is counted in
    # `unsupported_from_attribution`, so re-routing it would record the same transaction twice.
    # A residual is the one queued status the audit found genuinely unrecorded: it is excluded from
    # the primary metric and, until this loop, surfaced in no queue, total or report.
    #
    # Stage.RECONCILIATION, not NETTING, and `netting_quarantined` is not incremented. A residual
    # has a result and is already counted among the census statuses as ABOVE_TOLERANCE_RESIDUAL;
    # three invariants read a NETTING record as "netting refused this and produced no result",
    # which is the opposite of a residual. The queue record adds visibility of the residual's volume
    # and age — it does not add a transaction to the population or a refusal to netting's count.
    for residual in [r for r in reconciliation_queue(results)
                     if r.status is ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL]:
        quarantine.append(QuarantineRecord(
            stage=Stage.RECONCILIATION,
            reason=(
                "residual above the addendum §8 tolerance: excluded from the primary metric and "
                "routed here so the volume it represents is not lost. {}".format(residual.status)
            ),
            tx_hashes=(residual.tx_hash,),
            wallet=residual.portfolio_owner,
            # A residual straddles a swap, so it names both legs where it has them: the asset field
            # takes whichever it knows rather than pretending a residual is one-sided.
            asset=residual.sold_asset or residual.bought_asset,
            volume_usd=residual.quote_usd,
            block_number=residual.block_number,
        ))

    # Split UNSUPPORTED by *which* transactions §8 excluded, not by what netting's message says
    # about them. Matching on the reason string would make the split depend on wording nothing
    # enforces: reword netting's refusal and this quietly reports zero attribution exclusions
    # against a census that still validates, because a smaller count is always a legal one. The
    # exclusion set is the fact; the message is a description of it.
    excluded_hashes = {record.tx_hash for record in excluded}
    census = classification_census(
        results,
        quarantined=netting_quarantined,
        unsupported_from_attribution=sum(
            1 for r in results
            if r.status is ClassificationStatus.UNSUPPORTED and r.tx_hash in excluded_hashes
        ),
        # The population handed in, not the part of it that decoded. This is the line the tracer
        # bullet found wrong: with ``len(observed)`` here the census totalled six against a real
        # population of seven and every invariant below still reconciled, because they all
        # reconciled against the smaller number.
        total=len(handed_in),
        undecodable=len(undecodable),
    )

    trades = tuple(r for r in results if r.status.is_trade)
    buys = tuple(r for r in trades if r.status is ClassificationStatus.VALID_BUY)
    sells = tuple(r for r in trades if r.status is ClassificationStatus.VALID_SELL)

    # -- stage 3: fifo ----------------------------------------------------------
    stages_run.append(Stage.FIFO)
    books, book_quarantines = _match_books(trades)
    quarantine.extend(book_quarantines)

    quarantined_txs = set()
    for record in book_quarantines:
        quarantined_txs.update(record.tx_hashes)

    consumptions_by_buy = {}
    n_consumptions = 0
    for book in books.values():
        for consumption in book.consumptions:
            consumptions_by_buy.setdefault(consumption.buy.tx_hash, []).append(consumption)
            n_consumptions += 1

    # -- stage 4: marking -------------------------------------------------------
    stages_run.append(Stage.MARKING)
    accounts_by_wallet = {}
    outcomes_by_wallet = {}
    buys_outside_window = 0
    positions_marked = 0
    # Every buy that left the population, by hash rather than by count. A counter alone would have
    # let the per-wallet figures below be assembled from the FIFO refusals only, and a wallet whose
    # buys were all refused at *marking* would have reported none quarantined while reporting no
    # score — the shape of an unexplained drop, in the very field that exists to explain it.
    quarantined_buys = set()
    deferred_buys = set()
    for buy in sorted(buys, key=lambda b: (b.block_number, b.tx_hash)):
        if buy.tx_hash in quarantined_txs:
            quarantined_buys.add(buy.tx_hash)
            continue
        if not window.contains(buy.block_number, buy.timestamp):
            # The §4.8 measurement tail. The buy opened a lot so the tail's sells match against the
            # right basis, but it belongs to a later window and is not scored here. Counted, never
            # silently dropped.
            buys_outside_window += 1
            deferred_buys.add(buy.tx_hash)
            continue
        try:
            account = _account_for(
                buy, consumptions_by_buy.get(buy.tx_hash, ()), pools, prices, config
            )
        except QuarantineRequired as refusal:
            quarantined_buys.add(buy.tx_hash)
            quarantine.append(QuarantineRecord(
                stage=Stage.MARKING,
                reason=str(refusal),
                tx_hashes=(buy.tx_hash,),
                wallet=buy.portfolio_owner,
                asset=buy.asset,
                volume_usd=buy.quote_usd,
            ))
            continue
        if account.position is not None:
            positions_marked += 1
        accounts_by_wallet.setdefault(buy.portfolio_owner, []).append(account)
        outcomes_by_wallet.setdefault(buy.portfolio_owner, []).append(
            buy_outcome(
                buy=buy,
                trade_value_usd=account.cost_usd,
                return_pct=account.return_pct,
                realized_usd=account.realized_proceeds_usd,
                marked_usd=account.marked_usd,
                dead_usd=account.dead_usd,
                bucket=account.bucket,
            )
        )

    # -- stage 5: scoring -------------------------------------------------------
    stages_run.append(Stage.SCORING)
    wallets_seen = sorted({r.portfolio_owner for r in trades if r.portfolio_owner is not None})
    wallet_outcomes = []
    scored = 0
    unscorable = 0
    buys_scored = 0
    for wallet in wallets_seen:
        accounts = tuple(accounts_by_wallet.get(wallet, ()))
        outcomes = tuple(outcomes_by_wallet.get(wallet, ()))
        wallet_buys = tuple(b for b in buys if b.portfolio_owner == wallet)
        wallet_sells = tuple(s for s in sells if s.portfolio_owner == wallet)
        quality = None
        reason = None
        wallet_quarantined = sum(1 for b in wallet_buys if b.tx_hash in quarantined_buys)
        wallet_deferred = sum(1 for b in wallet_buys if b.tx_hash in deferred_buys)
        if not outcomes:
            reason = (
                "wallet {} has {} valid buy(s) in this window, none of which reached scoring: {} "
                "quarantined, {} deferred to a later window. A score of zero would read as flat "
                "performance.".format(
                    wallet, len(wallet_buys), wallet_quarantined, wallet_deferred,
                )
            )
        else:
            try:
                quality = buy_quality_detail(outcomes, wallet).quality
            except UnscorableWallet as refusal:
                reason = str(refusal)
        if quality is None:
            unscorable += 1
        else:
            scored += 1
            buys_scored += len(accounts)
        wallet_outcomes.append(WalletOutcome(
            wallet=wallet,
            quality=quality,
            unscorable_reason=reason,
            accounts=accounts,
            n_buys=len(wallet_buys),
            n_sells=len(wallet_sells),
            n_buys_quarantined=wallet_quarantined,
            n_sells_quarantined=sum(1 for s in wallet_sells if s.tx_hash in quarantined_txs),
        ))

    # Same reason as the results tuple: the queue's total is a published number and must not depend
    # on the order the stages happened to append to it, nor on the caller's input order.
    queue = QuarantineQueue(records=tuple(sorted(
        quarantine, key=lambda r: (stage_rank(r.stage), r.tx_hashes)
    )))

    # A buy that produced an account inside a wallet nobody could score is neither scored nor
    # quarantined, so it is counted here rather than left to fall between the two.
    unscored_accounted = sum(
        len(w.accounts) for w in wallet_outcomes if w.quality is None
    )

    stages = StageCounts(
        transactions_in=len(handed_in),
        transactions_undecodable=len(undecodable),
        attributions_resolved=len(attributions),
        attributions_usable=sum(1 for a in attributions if a.is_usable_for_primary_metric),
        attributions_excluded=len(excluded),
        netted=len(results),
        netting_quarantined=netting_quarantined,
        buys=len(buys),
        sells=len(sells),
        fifo_books=len(books) + len(book_quarantines),
        fifo_books_quarantined=len(book_quarantines),
        consumptions=n_consumptions,
        open_positions_marked=positions_marked,
        buys_scored=buys_scored,
        buys_quarantined=len(quarantined_buys),
        buys_outside_window=buys_outside_window,
        buys_unscored=unscored_accounted,
        sells_quarantined=sum(1 for s in sells if s.tx_hash in quarantined_txs),
        wallets_seen=len(wallets_seen),
        wallets_scored=scored,
        wallets_unscorable=unscorable,
    )

    _require_the_population_is_conserved(handed_in, results, queue, census)
    _require_every_residual_reached_the_queue(results, queue)

    return WalletWindowResult(
        window=window.index,
        stages_run=tuple(stages_run),
        stages=stages,
        census=census,
        attribution=coverage,
        coverage=_coverage_report(results, queue, wallet_outcomes),
        wallets=tuple(wallet_outcomes),
        quarantine=queue,
        excluded=tuple(sorted(excluded, key=lambda e: e.tx_hash)),
        results=results,
    )


# -- input validation -----------------------------------------------------------


def _normalised_prices(prices):
    """``{quote_asset: USD per raw unit}``, keyed the way the seam spells an address.

    A callable is refused rather than adapted. Netting would accept one, but marking needs the
    per-raw-unit price itself, and recovering that from a callable means probing it with a quantity
    of one and trusting the answer to scale — an assumption about somebody else's price book that
    nothing here could check.

    Two spellings of one quote asset are refused rather than collapsed; see :func:`asset_keyed`.
    Each price is checked before the collision across prices is, so a caller reading the message
    sees their own spelling of the offending key rather than the normalised one.
    """
    if callable(prices):
        raise TypeError(
            "prices must be a mapping {quote_asset: Decimal USD per raw unit}, not a callable. "
            "Marking multiplies a pool's raw quote reserve by this price directly, so a function "
            "of (token, quantity) would have to be probed at quantity 1 and assumed linear."
        )
    checked = []
    for token, price in asset_pairs(prices):
        value = calc(price)
        if value <= 0:
            raise ValueError(
                "price for {} is {}; a quote asset price must be strictly positive. §4.6 restricts "
                "USD conversion to liquid quote assets precisely so one is always available, and a "
                "zero would mark every position in it as worthless.".format(token, value)
            )
        checked.append((token, value))
    return asset_keyed(checked, "prices")


def _normalised_pools(pools):
    """``{token: PoolState}``, keyed the way the seam spells an address.

    Two refusals, both from :func:`asset_keyed`, and neither subsumes the other:

    * two spellings of one token collapse into one entry, so the position is marked against
      whichever the caller's mapping yielded last — a different published return for the same
      input, decided by iteration order;
    * one key naming a *different* token from the ``PoolState`` it holds — the shape of a
      mis-assembled join, with every key correctly spelled and nothing collapsing. The lookup
      succeeds and marks the position against the wrong pool: measured, a $1,000 lot publishes
      ``-0.25`` against a true ``-0.5``, with an identical census, an empty queue and an identical
      coverage report. The collision refusal does nothing about this one, which is why it is its
      own rule and not a second reading of the first.

    Both are checks on the caller's mapping agreeing with itself. Neither validates that a key is
    an address, and a pool book covering tokens the run never touched stays legal.
    """
    if callable(pools):
        raise TypeError("pools must be a mapping {token: PoolState}, not a callable")
    supplied = asset_pairs(pools)
    for token, pool in supplied:
        if not isinstance(pool, PoolState):
            raise TypeError(
                "pools[{!r}] must be a PoolState, got {}".format(token, type(pool).__name__)
            )
    return asset_keyed(supplied, "pools")


def _require_a_measurable_horizon(window, config):
    """§4.8: the measurement runs to 30 days past the window's end, for every sample.

    A horizon short of that produces partial returns wearing whole ones' clothes — §4.8 forbids both
    dropping the sample and using the partial return, so the only remaining option is to refuse the
    configuration. Refused on the *condition* (is every buy in this window given its full 30 days?)
    rather than on the horizon's distance from any particular buy, because the last buy of the
    window is the one that binds and it is the one a caller is least likely to have in mind.
    """
    required_ts = window.end_ts + MEASUREMENT_HORIZON_SECONDS
    if config.horizon_ts < required_ts:
        raise ValueError(
            "the marking horizon is ts {} but window {} ends at ts {}, so a buy at the window's "
            "last second gets {} of its 30 days. §4.8 permits the measurement to run up to 30 days "
            "past the window end exactly so that no sample is dropped and no partial return is "
            "used; a horizon before ts {} produces partial returns that are indistinguishable from "
            "whole ones.".format(
                config.horizon_ts, window.index, window.end_ts,
                config.horizon_ts - window.end_ts, required_ts,
            )
        )
    if config.horizon_block < window.end_block:
        raise ValueError(
            "the marking horizon is block {} but window {} ends at block {}; the seam pairs a "
            "timestamp with a block and a horizon that precedes the window in one dimension and "
            "follows it in the other cannot be reconciled against chain state".format(
                config.horizon_block, window.index, window.end_block
            )
        )


def _require_one_transaction_per_hash(observed):
    """One ``tx_hash``, one transaction — established here, and relied on everywhere below.

    ``tx_hash`` is the identity key this run counts with, and it is used as one in five places:
    ``excluded_hashes`` splits the census by which transactions §8 refused, ``quarantined_txs``
    and ``quarantined_buys`` and ``deferred_buys`` record which left the population and how,
    ``consumptions_by_buy`` gathers a buy's FIFO consumptions, and every
    :class:`~pipeline.census.QuarantineRecord` names its transactions. None of those is a set *of
    transactions* unless the key identifies one, and no stage upstream of this function establishes
    that it does — netting returns one result per transaction it is given, whatever it is given.

    Two rows under one hash do not make the answer smaller, they make it wrong in the direction
    that looks plausible. ``consumptions_by_buy`` is the sharpest: a sale in one lot book is handed
    to a buy in a *different* book, so an unsold position publishes another position's proceeds as
    its own realized leg. §10's realized / marked / dead mix then reports its highest credibility —
    fully realized, nothing resting on a mark — on a return that was assembled at a join. Every
    other keyed structure fails the same way more quietly: a quarantine on one transaction removes
    a healthy one, a deferral to the next window is counted against a buy that was scored in this
    one.

    Refused, not quarantined, and refused here rather than deeper:

    * **the input is wrong, not the chain.** No block issues one hash to two transactions, so a
      duplicate is a defect in whatever assembled the call — an overlapping page fetch, a re-org
      replay, a join that fanned out. Addendum §8's queue is for real inputs nobody can support;
      this is an input that cannot be real.
    * **there is no answer to give it.** Quarantining, deduplicating or keeping the first would each
      require knowing which of the rows is *the* transaction, and the duplicate is precisely the
      evidence that nobody does.
    * **here is the only place one check reaches every shape.** Downstream the rows are already
      apart: two tokens land in different lot books, a buy and a sell in the same book reach FIFO,
      and a pair straddling the window edge is separated by the §4.8 filter before anything
      compares them. A guard at any one of those sites closes that site.

    The hashes compared are the normalised ones — both entry types strip and lowercase in
    ``__post_init__`` — so ``"0xDUP  "`` and ``"0xdup"`` are one hash here for the same reason they
    are one hash to every stage that follows.

    Both kinds are compared together, decoded and undecodable in one pass. A hash arriving as both
    would be counted twice in the census, once classified and once undecodable, and the total would
    then be exactly right about a population that does not exist — which is the one failure mode
    the conservation check downstream cannot distinguish from a correct run, because it too would
    reconcile.

    **What that rests on, and what it therefore does not cover.** The normalisation is the entry
    type's, not this function's, and ``run_wallet_window`` admits any ``isinstance`` of
    ``ObservedTransaction`` — so a subclass overriding ``__post_init__``, or an
    ``object.__setattr__`` on a constructed row, can put an un-normalised hash past this check:
    ``"0xDUP"`` and ``"0xdup"`` arrive as two keys and neither is refused. Stated rather than
    closed, and for a reason worth the sentence: re-normalising here would make this the *second*
    authority on what a hash is, and one half of a key space normalising while the other half does
    not is precisely the defect ``WindowConfig`` carried against its asset keys.

    Both bypasses were constructed and run, because the residue is only tolerable if it is known
    rather than assumed. Neither reproduces what this refusal exists to stop: the two rows stay
    apart in every hash-keyed structure below, so the run publishes the answer two genuinely
    distinct hashes would have published (the traced case scores 0.75, not 2), and where the two
    land in one lot book ``fifo._require_a_total_order`` lowercases, refuses, and the book goes to
    the queue naming both spellings. A correct answer about an input that lied, or a loud
    quarantine — not a silent double-count. ``test_a_bypassed_hash_normalisation_does_not_reach
    _the_double_count`` holds that, so the paragraph is a checked fact rather than a claim.
    """
    positions = {}
    for index, item in enumerate(observed):
        positions.setdefault(item.tx_hash, []).append(index)
    repeated = [tx_hash for tx_hash in sorted(positions) if len(positions[tx_hash]) > 1]
    if not repeated:
        return
    raise ValueError(
        "run_wallet_window was given {} transactions under {} distinct tx_hash values: {}. A "
        "transaction hash identifies one transaction, and this run keys a buy's FIFO consumptions, "
        "its §8 exclusion, its quarantine and its deferral to the next window by that hash — so "
        "two rows sharing one are pooled rather than counted, and a position nobody sold is "
        "published carrying another position's proceeds. The input is wrong rather than the chain: "
        "no block issues one hash twice, so this is a defect in whatever assembled the call. "
        "Refused rather than quarantined, because holding it in a queue would still require "
        "deciding which of the rows is the transaction, and the duplicate is the evidence that "
        "nobody can.".format(
            len(observed),
            len(positions),
            "; ".join(
                "{} appears {} times, at input positions {}".format(
                    tx_hash,
                    len(positions[tx_hash]),
                    ", ".join(str(index) for index in positions[tx_hash]),
                )
                for tx_hash in repeated
            ),
        )
    )


def _require_the_population_is_conserved(handed_in, results, queue, census):
    """Every transaction handed in leaves by exactly one of three doors. Refuse, never publish.

    The three doors are disjoint and together they are all of them:

    * netting produced a result for it — it is in ``results``, with a status;
    * netting refused it — it is named by a :attr:`~pipeline.census.Stage.NETTING` queue record;
    * ingestion could not read it — it is named by a :attr:`~pipeline.census.Stage.INGESTION` queue
      record.

    The FIFO and MARKING records are deliberately not counted: they name transactions that already
    have a netting result, so counting them would report the same transaction twice. That is not an
    incidental detail of the implementation, it is what makes this check able to see a *duplicate*
    as well as a *drop* — the comparison below is on sorted lists, not on sets, so a transaction
    accounted for twice fails just as loudly as one accounted for not at all.

    **Why a check and not a comment.** Every count in ``StageCounts`` and ``ClassificationCensus``
    reconciles against ``transactions_in`` and ``total``, and both of those are numbers this
    function's caller computes. A run that loses a transaction *before* it computes them loses it
    from the denominator too, and then every invariant in the result holds perfectly over a
    population the run shrank itself. That is precisely what happened: ``census.total`` read 6
    against a real population of 7, ``StageCounts`` balanced, ``WalletWindowResult`` constructed,
    and no field anywhere could have held the seventh. So this compares the accounting against the
    **argument**, which is the only thing in the function that no stage can quietly redefine.

    Refused rather than reported, and that refusal is the right behaviour rather than a harsh one.
    A census that does not add up is the one number nobody can act on: every share below it —
    coverage, the §10 mix, the realized share — is a ratio whose denominator is now unknown, so
    publishing them alongside a note would put five plausible numbers next to one caveat. There is
    also no answer to give: the difference between the two lists says a transaction was lost, and
    says nothing about which stage owes an account for it.

    :raises ValueError: the accounted-for transactions are not exactly the ones handed in, or the
        census totals a different population from the one supplied.
    """
    handed = sorted(item.tx_hash for item in handed_in)
    accounted = sorted(
        [result.tx_hash for result in results]
        + [tx_hash for record in queue.by_stage(Stage.NETTING) for tx_hash in record.tx_hashes]
        + [tx_hash for record in queue.by_stage(Stage.INGESTION) for tx_hash in record.tx_hashes]
    )
    if accounted == handed and census.total == len(handed):
        return

    missing = _multiset_difference(handed, accounted)
    extra = _multiset_difference(accounted, handed)
    raise ValueError(
        "the run was handed {} transaction(s) and accounts for {}; a census that does not add up "
        "is the one number nobody can act on, so this refuses rather than publishes. Every "
        "transaction leaves by exactly one door — a netting result, a netting quarantine, or an "
        "ingestion quarantine — and {}{}the census totals {}. Unaccounted for: {}. Accounted for "
        "but never handed in: {}.".format(
            len(handed), len(accounted),
            "" if accounted == handed else "the two lists disagree; ",
            "" if census.total == len(handed) else "worse, ",
            census.total,
            ", ".join(missing) or "(none)",
            ", ".join(extra) or "(none)",
        )
    )


def _require_every_residual_reached_the_queue(results, queue):
    """Every ABOVE_TOLERANCE_RESIDUAL result is a reconciliation-queue record, and no more.

    This is the invariant the reconciliation queue was missing: it had a producer and no consumer,
    so a residual could be excluded from the primary metric and then surface in no queue, no total
    and no report. The wiring that routes residuals to the queue is a loop above, and a loop can be
    deleted — so this refuses a run in which the two counts disagree, exactly the way
    ``_require_the_population_is_conserved`` refuses a run that loses a transaction. Without it the
    wiring is a habit; with it, it is a rule.

    Counts, not the specific transactions, because a residual result carries the same ``tx_hash`` as
    its queue record and the population check above already proves the hashes line up. What this
    adds is that *every* residual made it and none was invented: an equal count with the set already
    verified is one-to-one.

    :raises ValueError: the residual results and the residual queue records are not the same number.
    """
    residual_results = [r for r in results
                        if r.status is ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL]
    residual_records = queue.by_stage(Stage.RECONCILIATION)
    if len(residual_results) == len(residual_records):
        return
    raise ValueError(
        "{} transaction(s) netted to a residual above tolerance, but {} reached the reconciliation "
        "queue. A residual excluded from the primary metric and absent from the queue is the "
        "silent exclusion ticket 21 exists to prevent: its volume would appear in no total and no "
        "report. This refuses rather than publishes a headline number that quietly drops the "
        "difference.".format(len(residual_results), len(residual_records))
    )


def _multiset_difference(left, right):
    """``left`` minus ``right`` counting repeats, so a double-count is visible as well as a drop."""
    remaining = list(right)
    out = []
    for item in left:
        if item in remaining:
            remaining.remove(item)
        else:
            out.append(item)
    return out


def _require_inside_the_measurement_period(item, window, config):
    """Every input lies in ``[window start, marking horizon]`` — the §4.8 measurement period."""
    if item.block_number < window.start_block or item.timestamp < window.start_ts:
        raise ValueError(
            "{} is at block {} / ts {}, before window {} starts at block {} / ts {}. A transaction "
            "outside the window silently widens the population the score is computed over, which "
            "is a caller error rather than a data finding.".format(
                item.tx_hash, item.block_number, item.timestamp, window.index,
                window.start_block, window.start_ts,
            )
        )
    if item.block_number > config.horizon_block or item.timestamp > config.horizon_ts:
        raise ValueError(
            "{} is at block {} / ts {}, after the marking horizon block {} / ts {}. Marking may "
            "only use state visible at the horizon, and a trade the horizon cannot see would enter "
            "the metric as look-ahead.".format(
                item.tx_hash, item.block_number, item.timestamp,
                config.horizon_block, config.horizon_ts,
            )
        )


# -- stage 3 --------------------------------------------------------------------


def _match_books(trades):
    """One FIFO lot book per ``(owner, asset)``, in a deterministic order.

    A book that cannot be matched goes to the queue **whole** — every buy and every sell in it.
    Keeping the matchable half would be worse than dropping the book: the surviving consumptions
    would be assigned against a lot history that is missing events, which is not a smaller answer
    but a wrong one.
    """
    grouped = {}
    for trade in trades:
        if trade.portfolio_owner is None:
            # Unreachable through netting, which refuses an unusable attribution at step 2. Kept as
            # a refusal rather than a filter so that a future caller assembling results by hand
            # cannot pool two wallets' lots under a None key.
            raise ValueError(
                "{} is a trade with no portfolio_owner; a lot book belongs to one "
                "wallet".format(trade.tx_hash)
            )
        grouped.setdefault(
            (trade.portfolio_owner, normalise_asset(trade.asset)), []
        ).append(trade)

    books = {}
    quarantines = []
    for key in sorted(grouped):
        owner, asset = key
        events = grouped[key]
        book_buys = [e for e in events if e.status is ClassificationStatus.VALID_BUY]
        book_sells = [e for e in events if e.status is ClassificationStatus.VALID_SELL]
        try:
            books[key] = match_fifo(book_buys, book_sells)
        except QuarantineRequired as refusal:
            volume = None
            for event in events:
                if event.quote_usd is not None:
                    volume = event.quote_usd if volume is None else add(volume, event.quote_usd)
            quarantines.append(QuarantineRecord(
                stage=Stage.FIFO,
                reason=str(refusal),
                tx_hashes=tuple(sorted(e.tx_hash for e in events)),
                wallet=owner,
                asset=asset,
                volume_usd=volume,
            ))
    return books, quarantines


# -- stage 4 --------------------------------------------------------------------


def _account_for(buy, consumptions, pools, prices, config):
    """One buy's §4.4 account: Case 1 on what was sold in time, Case 2/3 on what was not.

    A consumption whose sell lands after ``buy.timestamp + 30 days`` does **not** realize the buy.
    The quantity was still held at day 30, so §4.4 Case 2 governs it and it is marked. The
    alternative — folding a day-40 sale into a day-30 return — reads every late recovery as though
    the wallet had captured it inside the horizon, and it flatters precisely the wallets that hold
    losers.

    Raises :class:`contracts.QuarantineRequired` (including its marking subclasses) for a buy this
    module cannot account for: no §4.7 trading start, no pool, no price for the pool's quote asset,
    an unmodellable pool, or a migration across quote assets.
    """
    asset = normalise_asset(buy.asset)
    bucket = _bucket_for(buy, asset, config)

    horizon_ts = buy.timestamp + MEASUREMENT_HORIZON_SECONDS
    cost_usd = calc(buy.quote_usd)

    realized_raw = 0
    late_raw = 0
    realized_cost = ZERO
    realized_proceeds = ZERO
    for consumption in sorted(consumptions, key=lambda c: (c.sell.block_number, c.sell.tx_hash)):
        if consumption.sell.timestamp <= horizon_ts:
            realized_raw += consumption.consumed_raw
            realized_cost = add(realized_cost, consumption.allocated_cost_usd)
            realized_proceeds = add(realized_proceeds, consumption.proceeds_usd)
        else:
            late_raw += consumption.consumed_raw

    open_raw = buy.asset_raw_amount - realized_raw
    open_cost = sub(cost_usd, realized_cost)
    if open_raw < 0 or open_cost < 0:
        raise ValueError(
            "{}: FIFO allocated {} raw units and ${} of basis against a lot of {} raw units and "
            "${}. A lot cannot hand out more than it holds. These consumptions were gathered under "
            "this buy's tx_hash, and run_wallet_window refuses two transactions sharing a hash "
            "before any stage runs (_require_one_transaction_per_hash) — so they are this lot's "
            "own and not a second lot's arriving under a shared key. What is left is a defect in "
            "FIFO or in this join, and no different input would avoid it.".format(
                buy.tx_hash, realized_raw, realized_cost, buy.asset_raw_amount, cost_usd
            )
        )

    position = None
    marked_usd = ZERO
    dead_usd = ZERO
    if open_raw > 0:
        pool = _pool_for(asset, pools, buy)
        position = mark_position(
            remaining_raw=open_raw,
            pool=pool,
            horizon_block=config.horizon_block,
            horizon_ts=config.horizon_ts,
            quote_usd=_quote_price_for(pool, prices, buy),
            replacement_pool=config.replacement_pool(asset),
        )
        if position.value_basis is ValueBasis.DEAD_ZEROED:
            # §10's dead share is the exposure the zero verdict decided, not the resulting value.
            # Reading it as the value would make the dead share structurally zero and delete the one
            # basis §10 most wants visible.
            dead_usd = open_cost
        else:
            marked_usd = position.value_usd

    value_usd = ZERO if position is None else position.value_usd
    return_pct = sub(divide(add(realized_proceeds, value_usd), cost_usd), ONE)

    return BuyAccount(
        buy=buy,
        bucket=bucket,
        cost_usd=cost_usd,
        realized_raw=realized_raw,
        realized_cost_usd=realized_cost,
        realized_proceeds_usd=realized_proceeds,
        open_raw=open_raw,
        open_cost_usd=open_cost,
        late_sold_raw=late_raw,
        position=position,
        marked_usd=marked_usd,
        dead_usd=dead_usd,
        return_pct=return_pct,
        buy_horizon_ts=horizon_ts,
        horizon_lag_seconds=config.horizon_ts - horizon_ts,
    )


def _bucket_for(buy, asset, config):
    start = config.token_start(asset)
    if start is None:
        raise QuarantineRequired(
            "{} buys {}, for which no §4.7 token trading start was supplied. Bucketing it as D "
            "would file an unknown-age buy outside the first hour, which is the exact "
            "classification the Edge Origin condition is testing; quarantined "
            "instead.".format(buy.tx_hash, asset)
        )
    return token_age_bucket(buy.block_number, buy.timestamp, start.block, start.timestamp)


def _pool_for(asset, pools, buy):
    pool = pools.get(asset)
    if pool is None:
        raise QuarantineRequired(
            "{} leaves an open position in {} and no pool state was supplied to mark it. An "
            "unmarked position is not a zero — zero because a pool is dead is a measurement, and "
            "this is the absence of one.".format(buy.tx_hash, asset)
        )
    return pool


def _quote_price_for(pool, prices, buy):
    quote = normalise_asset(pool.quote)
    price = prices.get(quote)
    if price is None:
        raise QuarantineRequired(
            "{} would be marked at pool {}, quoted in {}, for which the price book carries no USD "
            "price per raw unit. §4.6 restricts USD conversion to liquid quote assets, so a "
            "missing one is a gap in the book rather than a long-tail asset to be "
            "estimated.".format(buy.tx_hash, pool.address, quote)
        )
    return price


# -- coverage -------------------------------------------------------------------


def _coverage_report(results, queue, wallet_outcomes):
    """USD-weighted coverage, accumulated in result order so the total is reproducible.

    Scored notional counts the buys inside wallets that produced a :class:`contracts.BuyQuality`.
    A buy that reached an account inside a wallet nobody could score contributed to no published
    number, so counting it here would report coverage the run does not have.

    ``transactions_unpriced`` counts three populations and not one: a netting result with no
    ``quote_usd``, a transaction netting refused outright, and a transaction ingestion could not
    read. The third is the surest of the three — nothing about it was decoded, so there is not even
    a leg to attempt a price on — and leaving it out would let the run report a priced/unpriced
    split over a population smaller than the one it was given, which is the same understatement one
    field along.
    """
    total = ZERO
    trade_total = ZERO
    priced = 0
    unpriced = 0
    for result in results:
        if result.quote_usd is None:
            unpriced += 1
            continue
        priced += 1
        total = add(total, result.quote_usd)
        if result.status.is_trade:
            trade_total = add(trade_total, result.quote_usd)

    scored = ZERO
    for outcome in wallet_outcomes:
        if outcome.quality is None:
            continue
        for account in outcome.accounts:
            scored = add(scored, account.cost_usd)

    return CoverageReport(
        notional_usd_total=total,
        notional_usd_trades=trade_total,
        notional_usd_quarantined=queue.total_volume_usd,
        notional_usd_scored=scored,
        transactions_priced=priced,
        transactions_unpriced=(unpriced + len(queue.by_stage(Stage.NETTING))
                               + len(queue.by_stage(Stage.INGESTION))),
    )
