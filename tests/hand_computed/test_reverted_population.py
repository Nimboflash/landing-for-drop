"""A transaction that reverted is still a transaction, and the census has to count it.

Ticket 19 found that a receipt ``ingest`` could not decode left the run entirely: the refusal was
an exception raised *before* ``run_wallet_window`` was called, ``census.total`` counted a smaller
population than the wallet had, and every share below it reconciled against the wrong denominator.
``pipeline.inputs.UndecodableTransaction`` closed that door.

**The reverted transaction was the same hole, one door along, and it was open until ticket 21.**
``pipeline.chain.observed_transaction`` called ``ingest.receipts.require_success`` on the way in, so
a reverted receipt raised ``TransactionReverted`` and the transaction reached no census, no queue
and no coverage report — while ``netting`` had carried a ``ClassificationStatus.FAILED_TRANSACTION``
for exactly this case all along, and ``pipeline.census`` had counted that status among its seven.
The vocabulary existed; the reader would not produce it.

It is not a corner. Driving four real mainnet wallets over February 2023 and its §4.8 measurement
tail through the pipeline (``tools/case_runs.py``), **46 of 548 transactions — 8.4% — reverted**,
including one of wallet ``0x51f8effd…``'s twelve. Every one of them was invisible.

What is pinned here
-------------------

* the boundary: a reverted receipt becomes a **value** with ``success=False`` and no transfers,
  while a receipt with no status member and a receipt claiming ``status=0`` *with logs* both still
  raise — the first because success cannot be recovered from a pre-Byzantium state root, the second
  because the EVM discards a reverted transaction's logs and a receipt asserting both is a
  contradiction in the bytes;
* the accounting: the transaction is in ``census.total``, lands in ``FAILED_TRANSACTION``, is
  counted by ``StageCounts.transactions_in``, opens no lot, marks no position and scores nothing;
* the guard: with the carried status removed, the run cannot represent the transaction at all.

Every literal is written out. Nothing here re-derives an expectation by calling the code under test
with a different spelling of the same expression.
"""

from decimal import Decimal

import pytest

from attribution import AttributionContext
from contracts import USDC, ClassificationStatus
from contracts import Transfer
from ingest import StatusUnstated
from pipeline import (
    MEASUREMENT_HORIZON_SECONDS,
    ObservedTransaction,
    Stage,
    TokenStart,
    Window,
    WindowConfig,
    observed_transaction,
    run_wallet_window,
)

# -- the world ------------------------------------------------------------------

WALLET = "0x" + "a1" * 20
POOL = "0x" + "b1" * 20
TOKEN = "0x" + "c1" * 20

ONE_USDC = 10 ** 6
ONE_TOKEN = 10 ** 18

START_BLOCK = 18_000_000
START_TS = 1_700_000_000
END_BLOCK = START_BLOCK + 7_200
END_TS = START_TS + 86_400
HORIZON_BLOCK = END_BLOCK + 216_000
HORIZON_TS = END_TS + MEASUREMENT_HORIZON_SECONDS

WINDOW = Window(index=3, start_block=START_BLOCK, start_ts=START_TS,
                end_block=END_BLOCK, end_ts=END_TS)

CONFIG = WindowConfig(
    horizon_block=HORIZON_BLOCK, horizon_ts=HORIZON_TS,
    token_starts={TOKEN: TokenStart(block=START_BLOCK - 100_000,
                                    timestamp=START_TS - 1_000_000)},
)

PRICES = {USDC: Decimal("0.000001")}

CONTEXT = AttributionContext(
    infrastructure=frozenset({POOL}), eoas=frozenset({WALLET}),
)

RECEIPT_HASH = "0x" + "11" * 32
BLOCK_HASH = "0x" + "22" * 32


def transfer(token, from_addr, to_addr, raw, index):
    return Transfer(token=token, from_addr=from_addr, to_addr=to_addr, raw_amount=raw,
                    log_index=index)


def a_buy(tx_hash, nth):
    """1,000 USDC out, 4,000 TOKEN in. Fully sold by ``a_sell``, so nothing is marked."""
    return ObservedTransaction(
        tx_hash=tx_hash,
        block_number=START_BLOCK + nth,
        timestamp=START_TS + nth * 12,
        success=True,
        tx_sender=WALLET,
        transfers=(
            transfer(USDC, WALLET, POOL, 1_000 * ONE_USDC, 0),
            transfer(TOKEN, POOL, WALLET, 4_000 * ONE_TOKEN, 1),
        ),
        context=CONTEXT,
    )


def a_sell(tx_hash, nth):
    """4,000 TOKEN out, 1,500 USDC in — a +50% round trip inside the horizon."""
    return ObservedTransaction(
        tx_hash=tx_hash,
        block_number=START_BLOCK + nth,
        timestamp=START_TS + nth * 12,
        success=True,
        tx_sender=WALLET,
        transfers=(
            transfer(TOKEN, WALLET, POOL, 4_000 * ONE_TOKEN, 0),
            transfer(USDC, POOL, WALLET, 1_500 * ONE_USDC, 1),
        ),
        context=CONTEXT,
    )


def a_revert(tx_hash, nth):
    """A transaction that reverted: it exists, it moved nothing, and it has no transfers."""
    return ObservedTransaction(
        tx_hash=tx_hash,
        block_number=START_BLOCK + nth,
        timestamp=START_TS + nth * 12,
        success=False,
        tx_sender=WALLET,
        transfers=(),
        context=CONTEXT,
    )


def run(transactions):
    return run_wallet_window(transactions, {}, PRICES, WINDOW, CONFIG)


class _StubClient:
    """The two calls :func:`pipeline.observed_transaction` makes, answered from a dict."""

    def __init__(self, status, logs=(), omit_status=False):
        self._status = status
        self._logs = list(logs)
        self._omit_status = omit_status

    def get_transaction_receipt(self, tx_hash):
        receipt = {
            "transactionHash": RECEIPT_HASH,
            "blockNumber": "0x1",
            "blockHash": BLOCK_HASH,
            "from": WALLET,
            "logs": self._logs,
        }
        if not self._omit_status:
            receipt["status"] = self._status
        return receipt

    def get_block_by_number(self, height):
        return {"number": "0x1", "timestamp": "0x64", "hash": BLOCK_HASH}


# -- the boundary ---------------------------------------------------------------


def test_a_reverted_receipt_comes_back_as_a_value_rather_than_raising():
    """The whole of ticket 21's ``src`` change, from the outside.

    Before it, this call raised ``ingest.TransactionReverted`` and the transaction was gone.
    """
    item = observed_transaction(_StubClient("0x0"), RECEIPT_HASH)

    assert isinstance(item, ObservedTransaction)
    assert item.success is False
    assert item.transfers == ()
    assert item.tx_hash == RECEIPT_HASH
    assert item.tx_sender == WALLET
    # The header and the receipt were read; only the transaction did not happen.
    assert (item.block_number, item.timestamp) == (1, 100)


def test_the_long_form_status_zero_is_the_same_answer():
    """``0x00`` and ``0x0`` are one status. Nodes spell it both ways."""
    item = observed_transaction(_StubClient("0x00"), RECEIPT_HASH)
    assert isinstance(item, ObservedTransaction)
    assert item.success is False


def test_a_successful_receipt_is_unchanged():
    item = observed_transaction(_StubClient("0x1"), RECEIPT_HASH)
    assert isinstance(item, ObservedTransaction)
    assert item.success is True
    assert item.transfers == ()


def test_a_receipt_with_no_status_member_still_raises():
    """Pre-Byzantium receipts carry a state root, and ``success=False`` would be a claim the bytes
    do not make. Assuming either way is a denominator decided by a guess."""
    with pytest.raises(StatusUnstated):
        observed_transaction(_StubClient("0x0", omit_status=True), RECEIPT_HASH)


def test_a_reverted_receipt_carrying_logs_still_raises():
    """The EVM discards a reverted transaction's logs.

    A receipt asserting ``status=0`` *and* a log is not a fact about Ethereum; it is a defect in
    whatever assembled the bytes. Admitting it would file the transaction as having moved nothing
    while it carried the evidence that it did — which is the direction that reads as a clean run.
    """
    log = {"address": POOL, "topics": ["0x" + "ab" * 32], "data": "0x", "logIndex": "0x3"}
    with pytest.raises(ValueError, match="EVM discards a reverted transaction's logs"):
        observed_transaction(_StubClient("0x0", logs=[log]), RECEIPT_HASH)


# -- the accounting -------------------------------------------------------------


def test_a_reverted_transaction_is_counted_classified_and_never_scored():
    """Two real transactions and one revert. Every literal below is written out.

    The buy and the sell are a +50% round trip: 1,000 USDC in, 1,500 USDC out, nothing left open.
    The revert changes none of that and must change none of it — what it changes is how many
    transactions the wallet is counted as having made.
    """
    result = run([a_buy("0x1", 1), a_sell("0x2", 2), a_revert("0x3", 3)])

    assert result.census.total == 3
    assert result.census.undecodable == 0
    assert result.census.counts[ClassificationStatus.FAILED_TRANSACTION] == 1
    assert result.census.counts[ClassificationStatus.VALID_BUY] == 1
    assert result.census.counts[ClassificationStatus.VALID_SELL] == 1

    assert result.stages.transactions_in == 3
    assert result.stages.netted == 3
    assert result.stages.buys == 1
    assert result.stages.sells == 1
    assert result.stages.open_positions_marked == 0

    # It is not a queue entry: the receipt was read and the chain answered. Nothing is pending.
    assert result.quarantine.by_stage(Stage.INGESTION) == ()
    assert result.quarantine.records == ()

    # And it did not move the score. One wallet, one buy, +50%.
    outcome, = result.wallets
    assert outcome.wallet == WALLET
    assert outcome.n_buys == 1
    assert outcome.n_sells == 1
    assert len(outcome.accounts) == 1
    assert outcome.accounts[0].return_pct == Decimal("0.5")


def test_the_same_run_without_the_revert_publishes_the_same_score_and_a_smaller_census():
    """The cost of the old behaviour, stated as a difference rather than as a claim.

    Dropping the revert leaves every published *ratio* looking healthy and the *population* wrong —
    which is precisely why it survived: nothing in the result contradicted itself.
    """
    with_revert = run([a_buy("0x1", 1), a_sell("0x2", 2), a_revert("0x3", 3)])
    without = run([a_buy("0x1", 1), a_sell("0x2", 2)])

    assert without.census.total == 2
    assert with_revert.census.total == 3
    assert without.census.counts[ClassificationStatus.FAILED_TRANSACTION] == 0

    assert without.wallets[0].accounts[0].return_pct == Decimal("0.5")
    assert with_revert.wallets[0].accounts[0].return_pct == Decimal("0.5")


def test_a_revert_reaches_no_lot_book_and_no_mark():
    """Six transactions: a buy that stays open, a revert beside it, and nothing else.

    The open lot is marked against no pool, so it quarantines at MARKING — and the revert is not in
    that record, because a transaction that did not happen has no position to mark.
    """
    result = run([a_buy("0x1", 1), a_revert("0x2", 2)])

    record, = result.quarantine.by_stage(Stage.MARKING)
    assert record.tx_hashes == ("0x1",)
    assert result.census.counts[ClassificationStatus.FAILED_TRANSACTION] == 1
    assert result.stages.buys_quarantined == 1


# -- the guard ------------------------------------------------------------------


def test_without_the_carried_status_the_transaction_cannot_enter_the_run_at_all():
    """Delete ``success=False`` from the population and there is nowhere else to put the row.

    ``run_wallet_window`` takes ``ObservedTransaction`` and ``UndecodableTransaction`` and nothing
    else, and an ``UndecodableTransaction`` would be a lie: the receipt decoded perfectly, and the
    queue entry would send a reader to classify a topic that is not there. So the alternative to
    this status is not a different row — it is no row, which is the state ticket 21 found.
    """
    with pytest.raises(TypeError, match="run_wallet_window consumes ObservedTransaction values"):
        run([a_buy("0x1", 1), {"tx_hash": "0x3", "reverted": True}])
