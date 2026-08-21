"""Every guard the accounting rests on, pinned by deleting it and watching this file go red.

Ticket 20's two halves added a fourth reconciliation term (``undecodable``), a conservation check
over the argument list, and a second, weaker account made from the published object's own fields.
The arithmetic was right. What was missing is the only thing a guard is worth anything for: a test
that fails when the guard is gone.

Measured before this file existed, by rewriting each guard out and running the **whole** suite
(2857 passed, 59 skipped, unchanged in every one of these):

* ``pipeline.result._require_the_census_matches_the_evidence`` — **the entire function**. Removing
  its call from ``WalletWindowResult.__post_init__`` changed no test's outcome. All four of its
  checks were unreachable from any test in the repository;
* one of those four had been *written and then disabled*: ``if False:`` stood where
  ``census.quarantined != stages.netting_quarantined`` belonged, and the function's own docstring
  went on deriving two further identities from it;
* ``census.total != stages.transactions_in`` on ``WalletWindowResult`` — green when deleted;
* the **call site** of ``pipeline.run._require_the_population_is_conserved``. That function's own
  refusals are pinned four times over, every one by calling it directly; nothing pinned that
  ``run_wallet_window`` calls it at all. Deleting the call left the suite green, which is the
  brief's question — *is there a path from assembly to publication that skips it* — answered by
  measurement rather than by reading;
* ``ClassificationCensus``'s non-negative-integer loop, whose own docstring argues at length that a
  negative count does not *fail* the reconciliation below it but *satisfies* it by cancelling
  another term;
* ``StageCounts``'s ``transactions_undecodable <= transactions_in`` bound, and the two §4
  invariants ticket 20 rewrote to reconcile against the decodable population rather than against
  ``transactions_in``;
* ``ingest.events._naming``, which is the whole of what stops a queue record reading "on log
  (unstated) of contract (unstated), topic (unstated)" — a count wearing a record's clothes, in
  that function's own words.

And one hole that the deletions turned up rather than closed: a length comparison against
``census.undecodable`` is satisfiable by naming one transaction twice, so a census of two
undecodable transactions published beside a queue holding one hash reconciled perfectly.
:func:`pipeline.result._require_each_transaction_is_named_once` closes it and is pinned here in
both stages.

What this file does not do
--------------------------

Re-check arithmetic that is already pinned. ``tests/hand_computed/test_undecodable_population.py``
covers what the checks say on the paths it exercises. Every test here exists because rewriting a
guard out changed no test's outcome, and each is written so that putting the guard back is what
turns it green.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from attribution import AttributionContext
from contracts import USDC, ClassificationStatus, Transfer
from ingest import TRANSFER
from pipeline import (
    MEASUREMENT_HORIZON_SECONDS,
    STAGE_ORDER,
    ClassificationCensus,
    CoverageReport,
    ObservedTransaction,
    QuarantineQueue,
    QuarantineRecord,
    Stage,
    StageCounts,
    TokenStart,
    UndecodableTransaction,
    Window,
    WindowConfig,
    observed_transaction,
    run_wallet_window,
)
from pipeline.result import WalletWindowResult

# -- the world ------------------------------------------------------------------
#
# The same shape as tests/hand_computed/test_undecodable_population.py, restated rather than
# imported: a file about what happens when a guard is removed must not depend on another test
# module's fixtures keeping the shape it assumed.

WALLET = "0x" + "a1" * 20
POOL = "0x" + "b1" * 20
TOKEN = "0x" + "c1" * 20
EMITTER = "0x" + "d1" * 20

ONE_USDC = 10 ** 6
ONE_TOKEN = 10 ** 18

START_BLOCK = 18_000_000
START_TS = 1_700_000_000
END_BLOCK = START_BLOCK + 7_200
END_TS = START_TS + 86_400

WINDOW = Window(index=3, start_block=START_BLOCK, start_ts=START_TS,
                end_block=END_BLOCK, end_ts=END_TS)

CONFIG = WindowConfig(
    horizon_block=END_BLOCK + 216_000,
    horizon_ts=END_TS + MEASUREMENT_HORIZON_SECONDS,
    token_starts={TOKEN: TokenStart(block=START_BLOCK - 100_000,
                                    timestamp=START_TS - 1_000_000)},
)

PRICES = {USDC: Decimal("0.000001")}

CONTEXT = AttributionContext(infrastructure=frozenset({POOL}), eoas=frozenset({WALLET}))

ZERO = Decimal("0")


def _transfer(token, from_addr, to_addr, raw, index):
    return Transfer(token=token, from_addr=from_addr, to_addr=to_addr, raw_amount=raw,
                    log_index=index)


def a_buy(tx_hash, nth):
    """1,000 USDC out, 4,000 TOKEN in."""
    return ObservedTransaction(
        tx_hash=tx_hash, block_number=START_BLOCK + nth, timestamp=START_TS + nth * 12,
        success=True, tx_sender=WALLET,
        transfers=(_transfer(USDC, WALLET, POOL, 1_000 * ONE_USDC, 0),
                   _transfer(TOKEN, POOL, WALLET, 4_000 * ONE_TOKEN, 1)),
        context=CONTEXT,
    )


def a_sell(tx_hash, nth):
    """4,000 TOKEN out, 1,500 USDC in — the other half of a +50% round trip."""
    return ObservedTransaction(
        tx_hash=tx_hash, block_number=START_BLOCK + nth, timestamp=START_TS + nth * 12,
        success=True, tx_sender=WALLET,
        transfers=(_transfer(TOKEN, WALLET, POOL, 4_000 * ONE_TOKEN, 0),
                   _transfer(USDC, POOL, WALLET, 1_500 * ONE_USDC, 1)),
        context=CONTEXT,
    )


def run(transactions):
    return run_wallet_window(transactions, {}, PRICES, WINDOW, CONFIG)


#: One honest run, kept so the one field a hand-built result cannot invent — the attribution
#: coverage — comes from the composition root rather than from this file.
HONEST = run([a_buy("0x1", 1), a_sell("0x2", 2)])


def census(total, classified=2, quarantined=0, undecodable=0):
    counts = {status: 0 for status in ClassificationStatus}
    counts[ClassificationStatus.VALID_BUY] = classified
    return ClassificationCensus(counts=counts, quarantined=quarantined,
                                unsupported_from_attribution=0, total=total,
                                undecodable=undecodable)


def stages(transactions_in=3, undecodable=0, netted=None, netting_quarantined=0,
           attributions_resolved=None, attributions_usable=None, attributions_excluded=0):
    decodable = transactions_in - undecodable
    return StageCounts(
        transactions_in=transactions_in,
        transactions_undecodable=undecodable,
        attributions_resolved=(decodable if attributions_resolved is None
                               else attributions_resolved),
        attributions_usable=(decodable - attributions_excluded if attributions_usable is None
                             else attributions_usable),
        attributions_excluded=attributions_excluded,
        netted=(decodable - netting_quarantined if netted is None else netted),
        netting_quarantined=netting_quarantined,
        buys=0, sells=0, fifo_books=0, fifo_books_quarantined=0, consumptions=0,
        open_positions_marked=0, buys_scored=0, buys_quarantined=0, buys_outside_window=0,
        buys_unscored=0, sells_quarantined=0, wallets_seen=0, wallets_scored=0,
        wallets_unscorable=0,
    )


def coverage(priced=0, unpriced=3):
    return CoverageReport(
        notional_usd_total=ZERO, notional_usd_trades=ZERO, notional_usd_quarantined=ZERO,
        notional_usd_scored=ZERO, transactions_priced=priced, transactions_unpriced=unpriced,
    )


class _Row:
    """A netting result as the two self-checks read it: a hash, and one place in the tally."""

    def __init__(self, tx_hash):
        self.tx_hash = tx_hash


def published(census_, stages_, queue=None, coverage_=None, results=()):
    return WalletWindowResult(
        window=3, stages_run=STAGE_ORDER, stages=stages_, census=census_,
        attribution=HONEST.attribution,
        coverage=coverage(unpriced=stages_.transactions_in) if coverage_ is None else coverage_,
        wallets=(),
        quarantine=QuarantineQueue(records=()) if queue is None else queue,
        excluded=(), results=results,
    )


# -- the guard that was written and disabled ------------------------------------


def test_a_result_whose_two_netting_quarantine_counts_disagree_is_refused():
    """``if False:`` stood here, and this is the result that walked through the hole.

    Constructed and published before the guard was restored: three transactions in, two netting
    results, one transaction named in the queue as quarantined by netting — and stage counts saying
    ``netted 3, netting_quarantined 0``. ``reconciliation()`` printed

        transactions_in 3 / netted 3 / netting_quarantined 0 / quarantine_records 1

    beside a ``results`` tuple of length two. Every other check in the object passed: the census
    totals three, its three terms add up, ``census.quarantined`` equals the one transaction the
    queue names, and the coverage split covers three.

    It is also the premise the function's own docstring derives ``netted == len(results)`` from.
    Disabled, that derivation rested on nothing, which is how ``netted`` came to say three about
    two.
    """
    with pytest.raises(ValueError, match="quarantined at netting and the stage counts report 0"):
        published(
            census(total=3, classified=2, quarantined=1),
            stages(transactions_in=3, netted=3, netting_quarantined=0),
            queue=QuarantineQueue(records=(
                QuarantineRecord(stage=Stage.NETTING, reason="no clear endpoint",
                                 tx_hashes=("0x3",)),
            )),
            results=(_Row("0x1"), _Row("0x2")),
        )


def test_the_honest_shape_of_that_same_run_still_constructs():
    """The counterpart, so the test above pins a *distinction* rather than merely a raise."""
    result = published(
        census(total=3, classified=2, quarantined=1),
        stages(transactions_in=3, netted=2, netting_quarantined=1),
        queue=QuarantineQueue(records=(
            QuarantineRecord(stage=Stage.NETTING, reason="no clear endpoint", tx_hashes=("0x3",)),
        )),
        results=(_Row("0x1"), _Row("0x2")),
    )
    lines = dict(result.reconciliation())
    assert (lines["netted"], lines["netting_quarantined"]) == (2, 1)


# -- the other three checks in the same function --------------------------------


def test_a_census_claiming_statuses_for_results_that_are_not_there_is_refused():
    """The census is a tally *of* ``results``; a larger tally names rows nobody can look up."""
    with pytest.raises(ValueError, match=r"census classifies 2 transaction\(s\) and the result "
                                         r"carries 0"):
        published(census(total=2, classified=2), stages(transactions_in=2), results=())


def test_a_netting_quarantine_count_with_nothing_named_in_the_queue_is_refused():
    """A count says money is in the queue. Only the record says which transaction, and §8's queue
    is worked from records."""
    with pytest.raises(ValueError, match=r"1 transaction\(s\) were quarantined at netting and 0 "
                                         r"are named"):
        published(
            census(total=3, classified=2, quarantined=1),
            stages(transactions_in=3, netted=2, netting_quarantined=1),
            results=(_Row("0x1"), _Row("0x2")),
        )


def test_a_coverage_report_split_over_a_smaller_population_is_refused():
    """The last field in this object that nothing else could answer.

    The coverage report is assembled *after*
    :func:`pipeline.run._require_the_population_is_conserved` has run, so this constructor is the
    only place it is ever compared to anything.
    """
    with pytest.raises(ValueError, match=r"coverage report splits 2 transaction\(s\) into priced "
                                         r"and unpriced against 3"):
        published(
            census(total=3, classified=3),
            stages(transactions_in=3),
            coverage_=coverage(priced=1, unpriced=1),
            results=(_Row("0x1"), _Row("0x2"), _Row("0x3")),
        )


def test_a_census_covering_a_different_population_from_the_run_is_refused():
    """``census.total`` and ``stages.transactions_in`` are one fact with two spellings."""
    with pytest.raises(ValueError, match="census covers 2 transactions and the run saw 3"):
        published(census(total=2, classified=2), stages(transactions_in=3),
                  results=(_Row("0x1"), _Row("0x2")))


# -- a count of transactions is satisfiable by one hash written twice -----------


def test_one_record_naming_two_undecodable_transactions_does_not_satisfy_a_count_of_one():
    """``QuarantineRecord.tx_hashes`` is plural, so ``len(records)`` is not a count of rows."""
    with pytest.raises(ValueError, match=r"1 transaction\(s\) could not be decoded and 2 are "
                                         r"named"):
        published(
            census(total=3, classified=2, undecodable=1),
            stages(transactions_in=3, undecodable=1),
            queue=QuarantineQueue(records=(
                QuarantineRecord(stage=Stage.INGESTION, reason="unknown event",
                                 tx_hashes=("0x3", "0x4")),
            )),
            results=(_Row("0x1"), _Row("0x2")),
        )


def test_two_ingestion_records_naming_one_transaction_do_not_satisfy_a_count_of_two():
    """The other half, and the one counting transactions does *not* close.

    Measured on a constructed result before ``_require_each_transaction_is_named_once`` existed:
    ``census.undecodable == 2``, ``stages.transactions_undecodable == 2``, two ``Stage.INGESTION``
    records both naming ``0x3`` — ``len(named) == 2`` with repeats kept, so the length comparison
    passed. It published, and ``quarantine.transactions`` held exactly one hash: a report saying
    two transactions could not be read while naming one.
    """
    with pytest.raises(ValueError, match="names 0x3 twice under ingestion"):
        published(
            census(total=4, classified=2, undecodable=2),
            stages(transactions_in=4, undecodable=2),
            queue=QuarantineQueue(records=(
                QuarantineRecord(stage=Stage.INGESTION, reason="unknown event",
                                 tx_hashes=("0x3",)),
                QuarantineRecord(stage=Stage.INGESTION, reason="unknown event",
                                 tx_hashes=("0x3",)),
            )),
            results=(_Row("0x1"), _Row("0x2")),
        )


def test_two_netting_records_naming_one_transaction_do_not_satisfy_a_count_of_two():
    """The same hole one stage along, and it published the same way."""
    with pytest.raises(ValueError, match="names 0x3 twice under netting"):
        published(
            census(total=4, classified=2, quarantined=2),
            stages(transactions_in=4, netted=2, netting_quarantined=2),
            queue=QuarantineQueue(records=(
                QuarantineRecord(stage=Stage.NETTING, reason="no clear endpoint",
                                 tx_hashes=("0x3",)),
                QuarantineRecord(stage=Stage.NETTING, reason="no clear endpoint",
                                 tx_hashes=("0x3",)),
            )),
            results=(_Row("0x1"), _Row("0x2")),
        )


def test_a_lot_book_naming_several_transactions_is_not_touched_by_that_rule():
    """FIFO records are not one-per-transaction, and the refusal above is applied per stage.

    A lot book goes to the queue whole, buys and sells together, because a book missing half its
    events is not a smaller book but a wrong one. Applying the distinctness rule to the queue rather
    than to the two one-per-transaction stages would refuse that.
    """
    result = published(
        census(total=2, classified=2),
        stages(transactions_in=2),
        queue=QuarantineQueue(records=(
            QuarantineRecord(stage=Stage.FIFO, reason="unmatched book",
                             tx_hashes=("0x1", "0x2", "0x1")),
        )),
        results=(_Row("0x1"), _Row("0x2")),
    )
    assert len(result.quarantine.by_stage(Stage.FIFO)) == 1


# -- which transactions the queue names, not only how many ----------------------


def test_a_lot_book_naming_a_transaction_no_result_carries_is_refused():
    """The assumption the three-door sum is built on, and did not check.

    ``pipeline.run._require_the_population_is_conserved`` excludes the FIFO and MARKING slices from
    its sum on the stated grounds that they name transactions which already have a netting result.
    Where that stops being true the exclusion is not a correction but a blind spot: the stray is
    behind no door, and the sum still balances because the stage holding it was never counted.

    Measured before the check existed: this exact result published, with
    ``quarantine.transactions`` reporting ``0xdeadbeef`` — a hash that appears nowhere else in the
    object, in no census term and in no stage count.
    """
    with pytest.raises(ValueError, match="names 0xdeadbeef under fifo and no netting result"):
        published(
            census(total=2, classified=2),
            stages(transactions_in=2),
            queue=QuarantineQueue(records=(
                QuarantineRecord(stage=Stage.FIFO, reason="unmatched book",
                                 tx_hashes=("0xdeadbeef",)),
            )),
            results=(_Row("0x1"), _Row("0x2")),
        )


def test_a_marking_record_naming_a_stranger_is_refused_the_same_way():
    """Marking's records are built from a buy's own hash, so a stranger there is the same break."""
    with pytest.raises(ValueError, match="names 0xdeadbeef under marking and no netting result"):
        published(
            census(total=2, classified=2),
            stages(transactions_in=2),
            queue=QuarantineQueue(records=(
                QuarantineRecord(stage=Stage.MARKING, reason="no pool state",
                                 tx_hashes=("0xdeadbeef",)),
            )),
            results=(_Row("0x1"), _Row("0x2")),
        )


def test_an_ingestion_record_naming_a_transaction_that_was_netted_is_refused():
    """The other side of the same rule: ingestion is a door taken *instead of* being netted.

    A transaction both unreadable and classified has left by two doors. The conservation check at
    assembly sees it because it compares sorted lists; this is the twin that holds for a result
    assembled by any other route.
    """
    with pytest.raises(ValueError, match="names 0x1 under ingestion and the same transaction"):
        published(
            census(total=3, classified=2, undecodable=1),
            stages(transactions_in=3, undecodable=1),
            queue=QuarantineQueue(records=(
                QuarantineRecord(stage=Stage.INGESTION, reason="unknown event",
                                 tx_hashes=("0x1",)),
            )),
            results=(_Row("0x1"), _Row("0x2")),
        )


def test_a_netting_record_naming_a_transaction_that_was_netted_is_refused():
    """Netting refuses a transaction *or* returns a result for it. Never both."""
    with pytest.raises(ValueError, match="names 0x1 under netting and the same transaction"):
        published(
            census(total=3, classified=2, quarantined=1),
            stages(transactions_in=3, netted=2, netting_quarantined=1),
            queue=QuarantineQueue(records=(
                QuarantineRecord(stage=Stage.NETTING, reason="no clear endpoint",
                                 tx_hashes=("0x1",)),
            )),
            results=(_Row("0x1"), _Row("0x2")),
        )


# -- the conservation check is reached from the composition root ----------------


def test_the_run_refuses_a_result_a_stage_relabelled(monkeypatch):
    """The call site, not the function. Nothing pinned that ``run_wallet_window`` calls it.

    The four existing tests of ``_require_the_population_is_conserved`` all call it directly, so
    deleting its one call from ``run_wallet_window`` left the whole suite green — a path from
    assembly to publication that skips it would have been introduced silently.

    A stage that relabels a row is what the check exists to see, and no honest input can produce
    one, so it is injected: netting returns a result carrying ``0x9`` for the transaction handed in
    as ``0x3``. Every count downstream is unchanged, because ``0x9`` is as good a key as ``0x3``
    everywhere except in the one place the argument list is still in scope. The census totals three
    because it is built from ``len(handed_in)``; ``StageCounts`` reconciles because netting returned
    three results; every check on ``WalletWindowResult`` passes because ``classified`` is three and
    ``results`` is three long. Only the comparison against the argument sees that ``0x3`` left by
    no door and ``0x9`` by one it never entered.
    """
    from netting import net_transaction as real_net_transaction

    import pipeline.run

    def relabelling(tx, prices):
        result = real_net_transaction(tx, prices)
        if tx.tx_hash == "0x3":
            return replace(result, tx_hash="0x9")
        return result

    monkeypatch.setattr(pipeline.run, "net_transaction", relabelling)

    with pytest.raises(ValueError) as refusal:
        run([a_buy("0x1", 1), a_sell("0x2", 2), a_buy("0x3", 3)])
    assert "the run was handed 3 transaction(s) and accounts for 3" in str(refusal.value)
    assert "Unaccounted for: 0x3" in str(refusal.value)
    assert "Accounted for but never handed in: 0x9" in str(refusal.value)


def test_the_same_population_without_the_relabelling_publishes():
    """The control. Three transactions, three doors, one door each."""
    result = run([a_buy("0x1", 1), a_sell("0x2", 2), a_buy("0x3", 3)])
    assert result.census.total == 3
    assert sorted(row.tx_hash for row in result.results) == ["0x1", "0x2", "0x3"]


# -- a negative count satisfies the reconciliation rather than failing it -------


@pytest.mark.parametrize("field,value,shape", [
    ("quarantined", -2, dict(total=0, classified=2, quarantined=-2)),
    ("undecodable", -2, dict(total=0, classified=2, undecodable=-2)),
    ("total", -1, dict(total=-1, classified=0, quarantined=0, undecodable=-1)),
])
def test_a_negative_count_cannot_cancel_another_term_in_the_census(field, value, shape):
    """The reconciliation is an equation, and an equation is satisfiable by a negative term.

    ``quarantined=-2`` beside two classified transactions totals zero and reconciles perfectly — a
    census that has classified two transactions while reporting a population of none. The check
    that refuses it is the type check on every count, and nothing exercised it.
    """
    with pytest.raises(ValueError, match="a count of transactions is a non-negative int"):
        census(**shape)


def test_a_count_that_is_a_bool_is_not_a_count():
    """``True`` is an ``int`` in Python and would tally as one transaction. It is refused by name."""
    counts = {status: 0 for status in ClassificationStatus}
    counts[ClassificationStatus.VALID_BUY] = True
    with pytest.raises(ValueError, match="a count of transactions is a non-negative int"):
        ClassificationCensus(counts=counts, quarantined=0, unsupported_from_attribution=0,
                             total=1)


# -- the stage counts, over the decodable population ----------------------------


def test_more_undecodable_transactions_than_were_handed_in_is_refused():
    """The bound the other three §4 invariants subtract against.

    ``decodable = transactions_in - transactions_undecodable`` is what each of them reconciles
    against, so an undecodable count larger than the population makes the subtrahend negative and
    every one of the three satisfiable by a negative term. Written out field by field rather than
    through this module's ``stages`` helper, because the helper's derived counts would go negative
    first and the refusal would be about the wrong thing.
    """
    with pytest.raises(ValueError, match="2 transactions could not be decoded out of 1 handed in"):
        StageCounts(
            transactions_in=1, transactions_undecodable=2, attributions_resolved=0,
            attributions_usable=0, attributions_excluded=0, netted=0, netting_quarantined=0,
            buys=0, sells=0, fifo_books=0, fifo_books_quarantined=0, consumptions=0,
            open_positions_marked=0, buys_scored=0, buys_quarantined=0, buys_outside_window=0,
            buys_unscored=0, sells_quarantined=0, wallets_seen=0, wallets_scored=0,
            wallets_unscorable=0,
        )


def test_the_usable_and_excluded_split_is_over_the_decodable_population():
    """Three handed in, one unreadable: attribution splits two, not three.

    A ``StageCounts`` that still measured this against ``transactions_in`` would force the caller
    to shrink ``transactions_in``, which is how the population was lost in the first place.
    """
    stages(transactions_in=3, undecodable=1)  # the honest shape constructs
    with pytest.raises(ValueError, match=r"1 \+ 0 != 2 decodable of 3 handed in"):
        stages(transactions_in=3, undecodable=1, attributions_usable=1, attributions_excluded=0)


def test_netting_accounts_for_every_decodable_transaction():
    """One result per transaction or one refusal, over the two ingestion could read."""
    with pytest.raises(ValueError, match=r"1 \+ 0 != 2 decodable of 3 handed in"):
        stages(transactions_in=3, undecodable=1, netted=1, netting_quarantined=0)


# -- a refusal that names no log is a count wearing a record's clothes ----------


class _StubClient:
    """The two calls :func:`pipeline.observed_transaction` makes, answered from a dict."""

    def __init__(self, logs):
        self._logs = logs

    def get_transaction_receipt(self, tx_hash):
        return {"transactionHash": "0x" + "11" * 32, "blockNumber": "0x1",
                "blockHash": "0x" + "22" * 32, "status": "0x1", "from": WALLET,
                "logs": self._logs}

    def get_block_by_number(self, height):
        return {"number": "0x1", "timestamp": "0x64", "hash": "0x" + "22" * 32}


#: An ERC-20 ``Transfer`` whose indexed ``from`` word carries a ``bytes32`` where an address
#: belongs — the top twelve bytes are not zero. Ordinary mainnet bytes, not adversarial ones, and
#: every other log in such a receipt may decode perfectly.
_BYTES32_WHERE_AN_ADDRESS_BELONGS = "0x" + "ff" * 12 + "a1" * 20


def test_a_refusal_raised_from_a_word_still_names_the_log_it_came_out_of():
    """``_address_word`` is handed 32 bytes and a label; it cannot name the log by itself.

    ``ingest.events._naming`` is what puts the topic, the contract and the log index back on the
    refusal before it leaves the decoder, and without it the queue record reads "on log (unstated)
    of contract (unstated), topic (unstated)" — which
    :class:`pipeline.inputs.UndecodableTransaction` is explicit cannot be worked, because the whole
    remedy is to look the topic up. Removing the annotation changed no test's outcome.
    """
    log = {"address": EMITTER,
           "topics": [TRANSFER, _BYTES32_WHERE_AN_ADDRESS_BELONGS, "0x" + "00" * 32],
           "data": "0x" + "00" * 32, "logIndex": "0x2a"}
    item = observed_transaction(_StubClient([log]), "0x" + "11" * 32)

    assert isinstance(item, UndecodableTransaction)
    assert item.refusal == "LogShapeMismatch"
    assert (item.topic, item.contract, item.log_index) == (TRANSFER, EMITTER, 42)
    assert "(unstated)" not in item.describe()


def test_that_named_refusal_reaches_the_queue_record():
    """And the queue is where a reader meets it, so the naming has to survive the composition."""
    log = {"address": EMITTER,
           "topics": [TRANSFER, _BYTES32_WHERE_AN_ADDRESS_BELONGS, "0x" + "00" * 32],
           "data": "0x" + "00" * 32, "logIndex": "0x2a"}
    item = observed_transaction(_StubClient([log]), "0x" + "11" * 32)
    in_window = replace(item, tx_hash="0x3", block_number=START_BLOCK + 3,
                        timestamp=START_TS + 36)

    result = run([a_buy("0x1", 1), a_sell("0x2", 2), in_window])

    record, = result.quarantine.by_stage(Stage.INGESTION)
    assert TRANSFER in record.reason
    assert EMITTER in record.reason
    assert "log 42" in record.reason
    assert "(unstated)" not in record.reason


# -- the reconciliation queue's age, and the RECONCILIATION stage -----------------


def test_a_quarantine_record_carries_its_age_and_refuses_a_bad_one():
    """Ticket 21 requires the queue to make age visible: a residual that has waited a month must
    not be indistinguishable from one that arrived this morning. ``block_number`` is that age."""
    dated = QuarantineRecord(stage=Stage.RECONCILIATION, reason="residual",
                             tx_hashes=("0x1",), volume_usd=Decimal("1"), block_number=18_000_000)
    assert dated.block_number == 18_000_000

    undated = QuarantineRecord(stage=Stage.NETTING, reason="refused", tx_hashes=("0x2",))
    assert undated.block_number is None, "None means no single block, distinct from block zero"

    with pytest.raises(ValueError):
        QuarantineRecord(stage=Stage.NETTING, reason="x", tx_hashes=("0x3",), block_number=-1)
    with pytest.raises(ValueError):
        QuarantineRecord(stage=Stage.NETTING, reason="x", tx_hashes=("0x4",), block_number=True)


def test_the_queue_orders_oldest_first_with_undated_records_last():
    """A queue is work to be done, oldest first; an entry whose age is unknown is not evidence of a
    long wait, so it sorts last rather than jumping the head of the line."""
    younger = QuarantineRecord(stage=Stage.RECONCILIATION, reason="r", tx_hashes=("0xbb",),
                               volume_usd=Decimal("1"), block_number=200)
    older = QuarantineRecord(stage=Stage.RECONCILIATION, reason="r", tx_hashes=("0xaa",),
                             volume_usd=Decimal("1"), block_number=100)
    undated = QuarantineRecord(stage=Stage.NETTING, reason="refused", tx_hashes=("0xcc",))

    queue = QuarantineQueue(records=(younger, undated, older))
    ordered = queue.oldest_first

    assert [r.tx_hashes for r in ordered] == [("0xaa",), ("0xbb",), ("0xcc",)]
    assert ordered[-1] is undated, "an undated record cannot mask a genuinely-waiting one"


def test_reconciliation_is_a_distinct_stage_from_netting():
    """A NETTING record means 'netting refused this and produced no result'; a RECONCILIATION record
    names a residual that HAS a result. Three invariants read the first meaning, so the two must not
    be the same stage. ``ACCOUNTING_STAGES`` includes RECONCILIATION so the queue can sort it; it is
    absent from ``STAGE_ORDER`` because it is not a §4 stage."""
    assert Stage.RECONCILIATION not in STAGE_ORDER
    assert Stage.RECONCILIATION is not Stage.NETTING

    queue = QuarantineQueue(records=(
        QuarantineRecord(stage=Stage.RECONCILIATION, reason="residual", tx_hashes=("0x1",),
                         volume_usd=Decimal("1"), block_number=5),
    ))
    assert len(queue.by_stage(Stage.RECONCILIATION)) == 1
    assert len(queue.by_stage(Stage.NETTING)) == 0
