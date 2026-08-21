"""A receipt to the movements it records — and a refusal where the logs stop short.

:mod:`ingest.events` reads one log. This module reads a receipt: it decides whether the
transaction is one whose movements may be read at all, and turns its logs into
:class:`contracts.Transfer` values — the seam type, so §4.2's ETH/WETH collapse and the address
lowercasing happen in the frozen constructor rather than here.

The hole this module refuses to fill
------------------------------------

A WETH ``Withdrawal`` says how much native ETH was released and to whom it was released *first*:
WETH9 pays ``msg.sender``. In the ordinary router shape that first recipient is the router, which
immediately forwards the ETH to the wallet that called it — by a plain call, which emits no log at
all. So the logs carry the amount and the path and not the last address, and that is exactly and
only what a trace would add.

:func:`transfers_from_logs` therefore requires the caller to *state* where each native leg
settled, per log index, and refuses when it is not stated. The alternatives were both measured on
the tracer bullet and both are worse:

* **drop the leg.** The wallet's own transaction then reads as tokens sent out for nothing —
  0.0345 ETH of proceeds vanish, a sale becomes a giveaway, and the receipt still parses cleanly;
* **assume the withdrawer kept it.** The router nets to zero and the wallet again receives
  nothing, with the same result and an extra appearance of rigour.

Stating it is cheap and checkable: :mod:`ingest.settlement` measures the recipient's own native
balance across the block from archive state, which confirmed the tracer bullet's settlement to the
wei without a trace.

What this module guarantees
---------------------------

* every log in the receipt is decoded or explicitly recognised as moving no value — nothing is
  skipped;
* the transfers come back ordered by log index, with each leg's own log index on it;
* amounts are raw integers, and the tokens are whatever the emitting contract was.

What it does not guarantee
--------------------------

That the receipt describes the transaction you meant, that the node's copy is the canonical one,
that native ETH moved by a plain call is visible anywhere (it is not), or that a settlement
address the caller supplied is the right one. It checks that one was supplied, not that it is true.
"""

from typing import Mapping, Optional, Tuple

from contracts import NATIVE_ETH, Transfer

from .events import (
    NativeUnwrap,
    NativeWrap,
    NoValueEvent,
    TokenTransfer,
    decode_logs,
    log_index,
)

#: What a successful receipt's ``status`` member says. Byzantium onwards; see
#: :func:`require_success` for what a receipt without one costs.
SUCCESS = "0x1"
FAILURE = "0x0"


class ReceiptRefused(ValueError):
    """Base for this module's refusals. A defect in the input or a state nothing may be read from."""


class ReceiptMissing(ReceiptRefused):
    """The node returned ``null`` for the hash."""


class TransactionReverted(ReceiptRefused):
    """The receipt says the transaction failed."""


class StatusUnstated(ReceiptRefused):
    """The receipt carries no ``status``, so success cannot be established from it."""


class NativeSettlementUnknown(ReceiptRefused):
    """A native-ETH leg is present and the caller did not say where it settled."""


def require_receipt(client, tx_hash):
    """The receipt dict for ``tx_hash``, verbatim, or raise :class:`ReceiptMissing`.

    ``None`` from a public endpoint is genuinely ambiguous — an unknown hash and a not-yet-indexed
    one are indistinguishable — and this function does not resolve it; it refuses, because there
    is nothing to decode either way. Resolving it means asking a second endpoint, which is the
    caller's decision to make and to record.
    """
    receipt = client.get_transaction_receipt(tx_hash)
    if receipt is None:
        raise ReceiptMissing(
            "no receipt for {} at the endpoint that answered. On a public node that means either "
            "the hash names no transaction on this chain or the node has not indexed it yet, and "
            "the two are indistinguishable from here. Treating it as 'no transfers' would drop a "
            "real trade and leave a wallet's window one buy short with nothing to say "
            "so.".format(tx_hash)
        )
    return receipt


def require_success(receipt):
    """Refuse a receipt that is not a successful transaction. Returns the receipt.

    A reverted transaction moves nothing and emits no logs, so decoding one yields an empty
    transfer list — which reads downstream as a transaction that happened and did nothing, rather
    than as one that did not happen. That difference is a denominator: it changes how many
    transactions a wallet is counted as having made.

    A receipt with **no** ``status`` at all is refused rather than assumed successful. Pre-Byzantium
    receipts carry ``root`` instead, and there is no rule that recovers success from it.
    """
    if "status" not in receipt or receipt.get("status") is None:
        raise StatusUnstated(
            "the receipt for {} carries no status member (it has {}). Pre-Byzantium receipts state "
            "a post-transaction state root instead, and success cannot be recovered from it. "
            "Assuming success would admit a reverted transaction as a completed trade; assuming "
            "failure would drop a real one.".format(
                receipt.get("transactionHash"), ", ".join(sorted(receipt))
            )
        )
    status = str(receipt["status"]).lower()
    if status in (SUCCESS, "0x01"):
        return receipt
    if status in (FAILURE, "0x00"):
        raise TransactionReverted(
            "the transaction {} reverted (status {}). A reverted transaction moves nothing and "
            "emits no logs, so decoding it produces an empty transfer list that is "
            "indistinguishable from a transaction that succeeded and moved nothing — and that "
            "difference is a denominator, not a rounding: it changes how many trades the wallet "
            "is counted as having made.".format(receipt.get("transactionHash"), receipt["status"])
        )
    raise StatusUnstated(
        "the receipt for {} carries a status of {!r}, which is neither {} nor {}. A status this "
        "decoder cannot read is refused rather than mapped onto the nearer of the two.".format(
            receipt.get("transactionHash"), receipt["status"], SUCCESS, FAILURE
        )
    )


def sender(receipt):
    """The transaction's ``from``, lowercased. Not the portfolio owner — attribution decides that."""
    value = receipt.get("from")
    if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
        raise ReceiptRefused(
            "the receipt for {} has no usable 'from' member (got {!r}). tx_sender is recorded "
            "alongside the recovered owner under amendment A6.1 and neither may stand in for the "
            "other, so there is nothing to fall back on.".format(
                receipt.get("transactionHash"), value
            )
        )
    return value.lower()


def block_number(receipt):
    """The receipt's ``blockNumber`` as an int."""
    value = receipt.get("blockNumber")
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ReceiptRefused(
            "the receipt for {} has no usable blockNumber (got {!r}). Every window test and every "
            "token-age bucket is decided against it.".format(receipt.get("transactionHash"), value)
        )
    return int(value, 16)


def transaction_hash(receipt):
    """The receipt's own ``transactionHash``, lowercased."""
    value = receipt.get("transactionHash")
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        raise ReceiptRefused(
            "the receipt has no usable transactionHash (got {!r}). A transaction with no identity "
            "cannot be quarantined, counted, or reconciled against raw chain data "
            "afterwards.".format(value)
        )
    return value.lower()


def native_legs(logs):
    """The log indices of every WETH wrap or unwrap in ``logs``, in order.

    What a caller inspects to learn which entries :func:`transfers_from_logs` will require of
    ``native_settlement``.
    """
    return tuple(
        event.log_index for event in decode_logs(logs)
        if isinstance(event, (NativeUnwrap, NativeWrap))
    )


def transfers_from_logs(logs, native_settlement=None):
    # type: (list, Optional[Mapping[int, str]]) -> Tuple[Transfer, ...]
    """Every value movement in ``logs``, as :class:`contracts.Transfer`, ordered by log index.

    ``native_settlement`` maps the **log index** of a WETH ``Withdrawal`` or ``Deposit`` to the
    address on the other side of its native-ETH leg: for an unwrap, where the ETH ended up after
    WETH9 paid the withdrawer; for a wrap, where the ETH came from before the withdrawer sent it.
    Keyed per leg rather than per transaction, so a transaction with two unwraps settling to two
    different addresses is expressible and a missing one is named by position.

    The synthesised leg is spelled with ``token=contracts.NATIVE_ETH`` on purpose, so §4.2's
    collapse onto WETH happens inside ``Transfer.__post_init__`` — the frozen seam — rather than
    being asserted here. The unwrap itself contributes no leg of its own: burning WETH to receive
    ETH is one asset becoming itself under §4.2, and the only movement is the ETH leaving the
    withdrawer.

    :raises NativeSettlementUnknown: a native leg has no entry, or an entry names a log index that
        is not a native leg.
    :raises ingest.events.LogRefused: any log could not be decoded. Nothing is skipped.
    """
    settlement = dict(native_settlement or {})
    events = decode_logs(logs)
    legs = [event.log_index for event in events
            if isinstance(event, (NativeUnwrap, NativeWrap))]

    unexpected = sorted(set(settlement) - set(legs))
    if unexpected:
        raise NativeSettlementUnknown(
            "native_settlement names log index(es) {} that carry no WETH wrap or unwrap; the "
            "native legs in this receipt are at {}. An entry filed against the wrong index is an "
            "entry that will never be read, so the leg it was meant for is still "
            "unstated.".format(
                ", ".join(str(index) for index in unexpected),
                ", ".join(str(index) for index in legs) or "(none)",
            )
        )

    transfers = []
    for event in events:
        if isinstance(event, TokenTransfer):
            transfers.append(Transfer(
                token=event.token,
                from_addr=event.from_addr,
                to_addr=event.to_addr,
                raw_amount=event.raw_amount,
                log_index=event.log_index,
            ))
        elif isinstance(event, (NativeUnwrap, NativeWrap)):
            counterparty = settlement.get(event.log_index)
            if not counterparty:
                raise NativeSettlementUnknown(
                    "log {} is a WETH {} of {} raw units by {}, and native_settlement does not say "
                    "which address the native ETH {}. WETH9 credits the withdrawer itself and any "
                    "onward hop is a plain call, which writes no log — so the amount and the path "
                    "are in these bytes and the last address is not. That is the one fact a trace "
                    "would add here. Refused rather than guessed: dropping the leg turns a sale "
                    "into a giveaway, and assuming the withdrawer kept it does the same thing "
                    "while looking deliberate. Supply {{{}: \"0x...\"}}, and confirm it if you "
                    "can — ingest.settlement.native_balance_delta established the tracer bullet's "
                    "recipient to the wei from archive state alone.".format(
                        event.log_index,
                        "unwrap" if isinstance(event, NativeUnwrap) else "wrap",
                        event.raw_amount, event.holder,
                        "settled on" if isinstance(event, NativeUnwrap) else "came from",
                        event.log_index,
                    )
                )
            if isinstance(event, NativeUnwrap):
                from_addr, to_addr = event.holder, counterparty
            else:
                from_addr, to_addr = counterparty, event.holder
            transfers.append(Transfer(
                token=NATIVE_ETH,
                from_addr=from_addr,
                to_addr=to_addr,
                raw_amount=event.raw_amount,
                log_index=event.log_index,
            ))
        elif isinstance(event, NoValueEvent):
            continue
        else:  # pragma: no cover - decode_log returns nothing else
            raise ReceiptRefused(
                "ingest.events.decode_log returned a {}, which this module does not classify as "
                "moving value or not moving it. A decoded event with no home here would be "
                "dropped, and a dropped movement is the failure this package "
                "exists to prevent.".format(type(event).__name__)
            )

    return tuple(sorted(transfers, key=lambda leg: leg.log_index))


def logs_of(receipt):
    """The receipt's ``logs`` list, verbatim."""
    logs = receipt.get("logs")
    if not isinstance(logs, list):
        raise ReceiptRefused(
            "the receipt for {} has no logs list (got {!r}). An absent list is not an empty one: "
            "a receipt whose logs a vendor omitted decodes to no movements at all, which reads as "
            "a transaction that traded nothing.".format(receipt.get("transactionHash"), logs)
        )
    return logs


def receipt_log_indices(receipt):
    """Every log index in the receipt, in order. Used to check nothing went unaccounted for."""
    return tuple(log_index(log) for log in logs_of(receipt))
