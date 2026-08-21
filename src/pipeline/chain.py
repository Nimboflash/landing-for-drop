"""Chain bytes to a run's entry types. The composition root's half of ticket 19.

:mod:`ingest` decodes and refuses; it may not import ``pipeline``, because it is a leaf builder and
only this package composes. So the last step — putting a decoded receipt into
:class:`pipeline.inputs.ObservedTransaction` and a pair of block heights into
:class:`pipeline.inputs.Window` — happens here, where the entry types are defined.

There is deliberately nothing else in this module. It reads, it assembles, and every refusal it can
produce comes from ``ingest`` or from the entry type's own constructor. If a rule about what a
receipt *means* appears here, it is in the wrong package.

What it guarantees
------------------

* the transaction returned carries the node's own hash, its block's own timestamp, and the sender
  the receipt named, with the header checked against the receipt so the two calls cannot be about
  two different blocks;
* **every transaction asked for comes back**, as one of two types. Where every log decoded, that is
  an :class:`pipeline.inputs.ObservedTransaction` whose transfers are the whole of the receipt's
  value movement — nothing skipped. Where a log carried an event ``ingest.events.SIGNATURES`` does
  not list, or a shape contradicting the signature it claims, it is an
  :class:`pipeline.inputs.UndecodableTransaction` naming the topic, the contract and the log index.
  Where the transaction reverted, it is an ``ObservedTransaction`` with ``success=False`` and no
  transfers — the receipt was read and the chain says nothing happened, which is a different
  statement from *we could not read this* and lands in a different census bucket;
* the ``context`` is the caller's, and defaults to an empty :class:`attribution.AttributionContext`
  — the spelling for "nothing is known about these addresses", which is what a raw read knows.

What it does not guarantee
--------------------------

That the transaction is a trade, that its owner is its sender, or that a window built from two
heights corresponds to any particular calendar period. Mapping a date to a block height is a
search over headers, not a decode, and it is not done here or in ``ingest``: both edges are
supplied by the caller and the timestamps that come back are what the chain says they are.

And, for an ``UndecodableTransaction``, nothing whatever about what the transaction did. It is the
statement *we could not read this*, carried so the run can count it — not a transaction that moved
nothing.

Which refusals become a value, and which still raise
----------------------------------------------------

The line is the one the house rules draw: a defect in *what assembled the call* raises, a
limitation of *what we can measure* becomes a carried status.

* :class:`ingest.UnknownEvent` and :class:`ingest.LogShapeMismatch` become a value. The chain is
  allowed to contain events nobody has enumerated and encodings this decoder has chosen not to
  read; the caller did nothing wrong, and the transaction exists whether or not we can read it.
* :class:`ingest.TransactionReverted` becomes a value: an ``ObservedTransaction`` with
  ``success=False`` and no transfers. A revert is what the chain did, not what the caller got
  wrong, and the pipeline already had the vocabulary for it — netting reads ``success`` before
  anything else and answers ``ClassificationStatus.FAILED_TRANSACTION``, which
  ``pipeline.census`` counts among its seven. Raising here made that status unreachable through
  this reader and dropped the transaction out of ``census.total`` altogether, which is the exact
  failure ``UndecodableTransaction`` exists to prevent. It is not rare: 46 of 548 transactions on
  four real February-2023 wallets reverted.
* :class:`ingest.MalformedLog` still raises. It says the dict is not a log — a member missing, a
  field that is not the hex the schema requires — which is a defect in the bytes that reached this
  function, not a fact about Ethereum. Nothing was measured, so there is no measurement to qualify.
* the rest of :mod:`ingest.receipts` still raises: a missing receipt, a receipt with no status at
  all, and a native leg whose settlement the caller did not state. The last is the sharpest of
  them — it is a fact the caller is required to supply, and turning it into a carried status would
  let a run silently stop supplying it.
"""

from typing import Mapping, Optional

from attribution import AttributionContext

from ingest import (
    LogShapeMismatch,
    TransactionReverted,
    UnknownEvent,
    block_header,
    logs_of,
    require_block_of_receipt,
    require_receipt,
    require_success,
    sender,
    transaction_hash,
    transfers_from_logs,
)

from .inputs import ObservedTransaction, UndecodableTransaction, Window


def observed_transaction(client, tx_hash, native_settlement=None, context=None):
    # type: (object, str, Optional[Mapping[int, str]], Optional[AttributionContext]) -> object
    """One transaction, read from the chain, as the pipeline's entry type — or as the status.

    Three calls at most: the receipt, and the header of the block it names.

    **A reverted transaction comes back with ``success=False`` and no transfers.** It is not
    skipped and it is not raised on. The difference a reverted transaction makes *is* a
    denominator — which is the argument for carrying the flag, not for dropping the row: netting
    reads ``success`` first and classifies it ``ClassificationStatus.FAILED_TRANSACTION``,
    ``pipeline.census`` carries that status among the seven it counts whether or not it occurred,
    and the census then totals the population the wallet actually has. Raising here left
    ``FAILED_TRANSACTION`` unreachable through the composed pipeline's own reader, and put the
    transaction in no census, no queue and no coverage report — the same hole
    :class:`~pipeline.inputs.UndecodableTransaction` was built to close, one door along. Measured
    on four real mainnet wallets over February 2023 and its §4.8 tail: 46 of 548 transactions
    (8.4%) reverted, and every one of them was invisible to the run.

    ``transfers`` is empty because the EVM discards a reverted transaction's logs, not because this
    function chose to skip them. A receipt claiming ``status=0`` while carrying logs is a
    contradiction in the bytes rather than a fact about Ethereum, and it raises.

    **Returns one of two types, and never ``None``.** Where a log carries an event
    ``ingest.events.SIGNATURES`` does not list, or a shape contradicting the signature it claims,
    this returns an :class:`~pipeline.inputs.UndecodableTransaction` instead of raising. The
    identity, the block, the timestamp and the sender are still measurements — they come from the
    receipt and its header, which decoded fine — and the refusal is carried alongside them naming
    the topic, the contract and the log index.

    Why here and not in ``ingest``: the decode genuinely failed, and ``ingest`` is right to refuse
    it. What changes at this boundary is what a refusal *means* to a run. ``ingest`` has no result
    type to carry a status in and must not acquire one — it is a leaf builder and may not import
    ``pipeline``. This module is the composition root's half, it already owns the entry types, and
    it is the last place where "this transaction cannot be read" can still become a row rather than
    an absence. One layer up, in :func:`pipeline.run.run_wallet_window`, an absence is
    unrecoverable: the transaction is simply not in the population, and no field on the result
    could hold it.

    The other receipt-level refusals are unchanged and still raise — see this module's docstring
    for the line between the two, and for the one case (an unstated native settlement) where
    turning a refusal into a status would quietly let a required input stop being supplied. A
    receipt with **no** status member still raises as well: pre-Byzantium receipts carry a state
    root instead, and ``success=False`` would be a claim the bytes do not make.

    :param native_settlement: log index -> the address on the other side of that WETH wrap or
        unwrap's native-ETH leg. Required for each such leg; see
        :func:`ingest.receipts.transfers_from_logs` for why it is not inferred.
    """
    receipt = require_receipt(client, tx_hash)
    try:
        require_success(receipt)
        reverted = False
    except TransactionReverted:
        reverted = True
    header = require_block_of_receipt(
        block_header(client, int(receipt["blockNumber"], 16)), receipt
    )
    identity = transaction_hash(receipt)
    if reverted:
        if logs_of(receipt):
            raise ValueError(
                "{} carries status {} and {} log(s). The EVM discards a reverted transaction's "
                "logs, so a receipt asserting both is a contradiction in the bytes that reached "
                "this function rather than a fact about Ethereum — and admitting it would let a "
                "transaction be counted as having moved nothing while carrying the evidence that "
                "it did.".format(identity, receipt.get("status"), len(logs_of(receipt)))
            )
        return ObservedTransaction(
            tx_hash=identity,
            block_number=header.number,
            timestamp=header.timestamp,
            success=False,
            tx_sender=sender(receipt),
            transfers=(),
            context=context if context is not None else AttributionContext(),
        )
    try:
        transfers = transfers_from_logs(logs_of(receipt), native_settlement)
    except (UnknownEvent, LogShapeMismatch) as refusal:
        return UndecodableTransaction(
            tx_hash=identity,
            block_number=header.number,
            timestamp=header.timestamp,
            tx_sender=sender(receipt),
            topic=refusal.topic,
            contract=refusal.address,
            log_index=refusal.log_index,
            refusal=type(refusal).__name__,
            detail=str(refusal),
        )
    return ObservedTransaction(
        tx_hash=identity,
        block_number=header.number,
        timestamp=header.timestamp,
        success=True,
        tx_sender=sender(receipt),
        transfers=transfers,
        context=context if context is not None else AttributionContext(),
    )


def window_from_blocks(client, index, start_block, end_block):
    """A §6.3 window whose two edges carry the heights given and the chain's own seconds.

    Both edges are read, so the window's ``start_ts``/``end_ts`` are measurements rather than a
    caller's arithmetic on an average block time. The heights themselves are the caller's: which
    block a calendar boundary falls on is a search, and this function does not perform one.
    """
    start = block_header(client, start_block)
    end = block_header(client, end_block)
    return Window(
        index=index,
        start_block=start.number,
        start_ts=start.timestamp,
        end_block=end.number,
        end_ts=end.timestamp,
    )
