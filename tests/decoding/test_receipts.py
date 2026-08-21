"""Receipt-level refusals, and the one input the decoder makes the caller state.

The native-settlement cases are the heart of this file. They are the difference between "the logs
are the whole story" and "the logs are the whole story except for the last address, and we made
that bit up".
"""

import pytest

from contracts import WETH
from ingest import (
    DEPOSIT,
    SYNC,
    TRANSFER,
    WITHDRAWAL,
    NativeSettlementUnknown,
    ReceiptMissing,
    ReceiptRefused,
    StatusUnstated,
    TransactionReverted,
    native_legs,
    require_receipt,
    require_success,
    transfers_from_logs,
)

from .conftest import ROUTER, TX, WALLET, address_word, log, word

TOKEN = "0x97e6e31afb2d93d437301e006d9da714616766a5"


def transfer(index, sender=WALLET, recipient=ROUTER, amount=7, address=TOKEN):
    return log([TRANSFER, address_word(sender), address_word(recipient)],
               data=word(amount), address=address, index=index)


def unwrap(index, holder=ROUTER, amount=500):
    return log([WITHDRAWAL, address_word(holder)], data=word(amount), address=WETH, index=index)


def wrap(index, holder=ROUTER, amount=500):
    return log([DEPOSIT, address_word(holder)], data=word(amount), address=WETH, index=index)


class Stub:
    """A client that answers ``eth_getTransactionReceipt`` with whatever it was handed."""

    def __init__(self, receipt):
        self.receipt = receipt

    def get_transaction_receipt(self, tx_hash):
        return self.receipt


# -- the receipt as a whole ------------------------------------------------------


def test_a_missing_receipt_is_refused_not_read_as_no_transfers():
    with pytest.raises(ReceiptMissing) as refusal:
        require_receipt(Stub(None), TX)

    assert TX in str(refusal.value)
    assert "not indexed" in str(refusal.value) or "not indexed it yet" in str(refusal.value)


def test_a_reverted_receipt_is_refused():
    """An empty transfer list from a revert is indistinguishable from a real no-op trade."""
    with pytest.raises(TransactionReverted) as refusal:
        require_success({"transactionHash": TX, "status": "0x0", "logs": []})

    assert "denominator" in str(refusal.value)


def test_a_receipt_with_no_status_is_refused_rather_than_assumed_successful():
    with pytest.raises(StatusUnstated) as refusal:
        require_success({"transactionHash": TX, "root": "0x" + "11" * 32, "logs": []})

    assert "Pre-Byzantium" in str(refusal.value)


def test_a_status_that_is_neither_is_refused_rather_than_rounded():
    with pytest.raises(StatusUnstated):
        require_success({"transactionHash": TX, "status": "0x2", "logs": []})


def test_a_successful_receipt_comes_back_unchanged():
    receipt = {"transactionHash": TX, "status": "0x1", "logs": []}

    assert require_success(receipt) is receipt


def test_the_committed_receipt_is_successful(client):
    assert require_success(require_receipt(client, TX))["status"] == "0x1"


# -- the native leg --------------------------------------------------------------


def test_an_unwrap_with_no_settlement_is_refused():
    """The refusal names the leg, the amount, the holder, and what guessing would cost."""
    with pytest.raises(NativeSettlementUnknown) as refusal:
        transfers_from_logs([transfer(0), unwrap(1)])

    message = str(refusal.value)
    assert "log 1" in message and ROUTER in message and "500" in message
    assert "writes no log" in message
    assert "giveaway" in message, "the refusal must say what dropping the leg costs"


def test_a_wrap_with_no_settlement_is_refused_the_same_way():
    with pytest.raises(NativeSettlementUnknown) as refusal:
        transfers_from_logs([wrap(3)])

    assert "came from" in str(refusal.value)


def test_a_settlement_entry_against_a_log_that_is_not_a_native_leg_is_refused():
    """An entry filed against the wrong index is one that will never be read."""
    with pytest.raises(NativeSettlementUnknown) as refusal:
        transfers_from_logs([transfer(0), unwrap(1)], native_settlement={0: WALLET, 1: WALLET})

    assert "log index(es) 0" in str(refusal.value)


def test_an_unwrap_becomes_one_leg_from_the_holder_to_the_settlement_address():
    legs = transfers_from_logs([unwrap(1, amount=500)], native_settlement={1: WALLET})

    assert [(leg.token, leg.from_addr, leg.to_addr, leg.raw_amount, leg.log_index)
            for leg in legs] == [(WETH, ROUTER, WALLET, 500, 1)]


def test_a_wrap_becomes_one_leg_into_the_holder():
    legs = transfers_from_logs([wrap(2, amount=500)], native_settlement={2: WALLET})

    assert [(leg.from_addr, leg.to_addr) for leg in legs] == [(WALLET, ROUTER)]


def test_two_unwraps_settle_independently():
    """Keyed per leg, so a transaction paying two addresses is expressible rather than averaged."""
    legs = transfers_from_logs(
        [unwrap(1, amount=100), unwrap(2, amount=200)],
        native_settlement={1: WALLET, 2: ROUTER},
    )

    assert [(leg.to_addr, leg.raw_amount) for leg in legs] == [(WALLET, 100), (ROUTER, 200)]


def test_an_unwrap_the_holder_keeps_nets_to_nothing():
    """Settling on the holder itself is legal and correct: under §4.2 it is one asset unchanged."""
    legs = transfers_from_logs([unwrap(1)], native_settlement={1: ROUTER})

    assert legs[0].from_addr == legs[0].to_addr == ROUTER


def test_native_legs_lists_what_the_caller_must_supply():
    assert native_legs([transfer(0), unwrap(1), wrap(2), transfer(3)]) == (1, 2)
    assert native_legs([transfer(0)]) == ()


# -- what is and is not a movement ------------------------------------------------


def test_a_recognised_non_movement_contributes_no_leg_and_blocks_nothing():
    legs = transfers_from_logs([transfer(0), log([SYNC], data=word(1) + format(2, "064x"),
                                                 address=ROUTER, index=1)])

    assert len(legs) == 1 and legs[0].log_index == 0


def test_legs_come_back_in_log_order_whatever_order_the_logs_arrived_in():
    """Ordering is asserted because a node is not obliged to sort, and FIFO reads the order."""
    legs = transfers_from_logs([transfer(9), transfer(2), transfer(5)])

    assert [leg.log_index for leg in legs] == [2, 5, 9]


def test_no_settlement_is_needed_when_there_is_no_native_leg():
    assert len(transfers_from_logs([transfer(0), transfer(1)])) == 2


# -- receipt fields ---------------------------------------------------------------


def test_a_receipt_without_a_from_is_refused():
    from ingest import sender

    with pytest.raises(ReceiptRefused) as refusal:
        sender({"transactionHash": TX})

    assert "A6.1" in str(refusal.value)


def test_a_receipt_without_logs_is_not_a_receipt_with_no_logs():
    from ingest import logs_of

    with pytest.raises(ReceiptRefused) as refusal:
        logs_of({"transactionHash": TX})

    assert "traded nothing" in str(refusal.value)


def test_the_committed_receipts_log_indices_are_contiguous(client):
    from ingest import receipt_log_indices

    assert receipt_log_indices(require_receipt(client, TX)) == (34, 35, 36, 37, 38, 39, 40, 41)
