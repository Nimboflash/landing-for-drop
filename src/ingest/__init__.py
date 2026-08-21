"""Builder-lane decoding: raw receipts and logs to the values the pipeline is written against.

:mod:`transport` moves bytes and interprets none of them. This package is where they acquire
meaning for the builder lane — which log is a transfer, which leg is native ETH, what scale a
token's amounts are in — and it is **not** shared. ``tests/test_lane_independence.py`` declares it
``BUILDER``, and the validator lane (tickets 13 and 36) must derive the same answers from the same
bytes without importing a line of it. If both lanes shared a decoder they would share its bug, and
a shared bug is invisible to the comparison the validation gate depends on: both sides compute the
same wrong answer and agree.

It is a **leaf**. It imports the frozen seam and the transport, and no sibling builder package.
Only ``pipeline`` composes, which is why the type ``pipeline.inputs.ObservedTransaction`` is
assembled in :mod:`pipeline.chain` from what this package returns rather than here — this package
produces ``contracts.Transfer`` values, the raw fields around them, and refusals.

The four things it refuses rather than guesses
----------------------------------------------

* **an unknown event.** :data:`ingest.events.SIGNATURES` is a short, explicit list. A log whose
  signature is not on it raises; there is no branch that skips one. A silently-skipped log is a
  wrong number that looks plausible. :data:`ingest.events.DECLINED` names the events that were
  looked at and refused anyway, with the reason — ERC-1155's two, whose asset is the pair
  ``(contract, id)`` and cannot be spelled in a ``contracts.Transfer``.
* **a log the ABI does not match.** Wrong topic count, wrong data width, an address word with a
  non-zero prefix. The case worth naming is ERC-721, which shares ERC-20's ``Transfer`` topic and
  would hand over a token id where an amount belongs.
* **a token whose ``decimals()`` cannot be read.** No default of 18, no table. Getting a scale
  wrong moves every USD figure by a power of ten and changes nothing else.
* **a receipt whose status is failure**, or that states no status at all.

And one more, which is this package's answer to the fact that traces are unobtainable on free
endpoints: **where a WETH unwrap's native ETH settled**. WETH9 pays the withdrawer, and any onward
hop is a plain call that writes no log. :func:`ingest.receipts.transfers_from_logs` requires the
caller to state it per leg. :mod:`ingest.settlement` is how a caller establishes it by measurement
instead of by assertion.

What this package does not do
-----------------------------

It does not decide who owns a transaction (``attribution`` does), does not net, does not price,
and does not derive a §4.7 token trading start or a §6.3 window from a calendar date — mapping a
date to a block height is a search, not a decode, and it is not here.
"""

from .blocks import (  # noqa: F401
    BlockHeader,
    BlockRefused,
    block_header,
    require_block_of_receipt,
)
from .events import (  # noqa: F401
    APPROVAL,
    DECLINED,
    DEPOSIT,
    ORDER_FILLED,
    PERMIT2_PERMIT,
    SIGNATURES,
    SWAP_V2,
    SWAP_V3,
    SYNC,
    TOKEN_EXCHANGE,
    TRANSFER,
    TRANSFER_BATCH,
    TRANSFER_SINGLE,
    WITHDRAWAL,
    Declined,
    LogRefused,
    LogShapeMismatch,
    MalformedLog,
    NativeUnwrap,
    NativeWrap,
    NoValueEvent,
    RegistryInconsistent,
    Signature,
    TokenTransfer,
    UnknownEvent,
    decode_log,
    decode_logs,
    log_address,
    log_index,
    signature_for,
)
from .receipts import (  # noqa: F401
    FAILURE,
    SUCCESS,
    NativeSettlementUnknown,
    ReceiptMissing,
    ReceiptRefused,
    StatusUnstated,
    TransactionReverted,
    block_number,
    logs_of,
    native_legs,
    receipt_log_indices,
    require_receipt,
    require_success,
    sender,
    transaction_hash,
    transfers_from_logs,
)
from .settlement import (  # noqa: F401
    NativeReadRefused,
    gas_cost,
    native_balance,
    native_balance_delta,
)
from .tokens import (  # noqa: F401
    DECIMALS_SELECTOR,
    DecimalsReader,
    TokenDecimalsUnreadable,
    token_decimals,
)

__all__ = [
    "TRANSFER", "WITHDRAWAL", "DEPOSIT", "SYNC", "SWAP_V2", "APPROVAL",
    "ORDER_FILLED", "SWAP_V3", "TOKEN_EXCHANGE",
    "TRANSFER_SINGLE", "TRANSFER_BATCH",
    "SIGNATURES", "Signature", "DECLINED", "Declined",
    "TokenTransfer", "NativeUnwrap", "NativeWrap", "NoValueEvent",
    "decode_log", "decode_logs", "signature_for", "log_address", "log_index",
    "LogRefused", "MalformedLog", "UnknownEvent", "LogShapeMismatch", "RegistryInconsistent",
    "SUCCESS", "FAILURE",
    "require_receipt", "require_success", "sender", "block_number", "transaction_hash",
    "transfers_from_logs", "native_legs", "logs_of", "receipt_log_indices",
    "ReceiptRefused", "ReceiptMissing", "TransactionReverted", "StatusUnstated",
    "NativeSettlementUnknown",
    "BlockHeader", "BlockRefused", "block_header", "require_block_of_receipt",
    "DECIMALS_SELECTOR", "token_decimals", "DecimalsReader", "TokenDecimalsUnreadable",
    "gas_cost", "native_balance", "native_balance_delta", "NativeReadRefused",
]
