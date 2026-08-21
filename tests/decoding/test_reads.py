"""Chain reads: ``decimals()``, block headers, and native balances.

Each is a place where a bad answer arrives looking like a good one. ``decimals()`` returning
nothing is not zero decimals; a header from the wrong block is still a well-formed header; a
pruned node's refusal on ``eth_getBalance`` is not a balance of zero.
"""

import pytest

from contracts import WETH
from ingest import (
    BlockRefused,
    DecimalsReader,
    NativeReadRefused,
    TokenDecimalsUnreadable,
    block_header,
    gas_cost,
    native_balance,
    native_balance_delta,
    require_block_of_receipt,
    require_receipt,
    token_decimals,
)
from transport import RpcRefused

from .conftest import BLOCK, TX, WALLET

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"


# -- decimals --------------------------------------------------------------------


def test_the_two_decimals_worth_knowing_are_read_from_the_chain(client):
    """WETH 18 and USDC 6, from the committed snapshot rather than from a table in the source."""
    assert token_decimals(client, WETH, BLOCK) == 18
    assert token_decimals(client, USDC, BLOCK) == 6


def test_a_checksummed_spelling_reads_the_same_recording(client):
    """Lowercased before the call, so one token is one snapshot entry and not two."""
    checksummed = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"

    assert token_decimals(client, checksummed, BLOCK) == 18
    assert client.replayed_count() == (1, 0)


def test_empty_returndata_is_refused_rather_than_read_as_zero(scripted):
    """``0x`` is what an address with no code answers. Zero decimals would make raw units USD."""
    with pytest.raises(TokenDecimalsUnreadable) as refusal:
        token_decimals(scripted("0x"), WETH, BLOCK)

    assert "no code" in str(refusal.value)


def test_returndata_of_the_wrong_width_is_refused(scripted):
    with pytest.raises(TokenDecimalsUnreadable) as refusal:
        token_decimals(scripted("0x12"), WETH, BLOCK)

    assert "32-byte word" in str(refusal.value)


def test_a_word_that_is_not_a_uint8_is_refused(scripted):
    """Truncating to the last byte would produce a scale the contract never stated."""
    not_a_uint8 = "0x" + "ff" * 32

    with pytest.raises(TokenDecimalsUnreadable) as refusal:
        token_decimals(scripted(not_a_uint8), WETH, BLOCK)

    assert "left-padded" in str(refusal.value)


def test_an_endpoint_refusal_is_carried_verbatim_into_the_decimals_refusal(scripted):
    """The node's own words survive, because that text is what a vendor conversation runs on."""
    client = scripted(error={"code": -32000, "message": "archive requests require a token"})

    with pytest.raises(TokenDecimalsUnreadable) as refusal:
        token_decimals(client, WETH, BLOCK)

    assert "archive requests require a token" in str(refusal.value)
    assert "power of ten" in str(refusal.value)


def test_a_tag_is_not_a_height(client):
    """``latest`` makes the answer unrepeatable; a proxy could rescale a historical run."""
    with pytest.raises(ValueError):
        token_decimals(client, WETH, "yesterday")


def test_the_reader_asks_once_per_token(client):
    reader = DecimalsReader(client, BLOCK)

    assert [reader.for_token(WETH) for _ in range(3)] == [18, 18, 18]
    assert client.replayed_count() == (1, 0)


def test_the_reader_covers_every_token_in_the_transfers(client):
    from ingest import logs_of, transfers_from_logs

    transfers = transfers_from_logs(
        logs_of(require_receipt(client, TX)), native_settlement={41: WALLET}
    )
    covered = DecimalsReader(client, BLOCK).for_transfers(transfers)

    assert set(covered) == {t.token for t in transfers}
    assert covered[WETH] == 18 and covered[USDC] == 6


# -- block headers ----------------------------------------------------------------


def test_a_header_carries_the_three_fields_anything_downstream_reads(client):
    header = block_header(client, BLOCK)

    assert header.number == BLOCK
    assert header.timestamp == 1672528943
    assert header.block_hash == (
        "0x87add6e0e83d92f3ed41e260380b44693a74ec03fb5388c0f767fc1a778edbf5"
    )


def test_a_header_that_is_not_the_receipts_block_is_refused(client):
    """Two calls to a pool of endpoints are two answers, and a reorg sits between them."""
    receipt = dict(require_receipt(client, TX))
    receipt["blockHash"] = "0x" + "99" * 32

    with pytest.raises(BlockRefused) as refusal:
        require_block_of_receipt(block_header(client, BLOCK), receipt)

    assert "two different blocks" in str(refusal.value)


def test_a_header_matching_its_receipt_is_returned(client):
    receipt = require_receipt(client, TX)
    header = block_header(client, BLOCK)

    assert require_block_of_receipt(header, receipt) is header


def test_a_node_with_no_such_block_is_refused(scripted):
    with pytest.raises(BlockRefused) as refusal:
        block_header(scripted(None), BLOCK)

    assert "no UTC second" in str(refusal.value)


def test_a_header_missing_its_timestamp_is_refused(scripted):
    with pytest.raises(BlockRefused):
        block_header(scripted({"number": hex(BLOCK), "hash": "0x" + "11" * 32}), BLOCK)


# -- native balances ---------------------------------------------------------------


def test_a_balance_is_read_as_an_int_in_wei(client):
    assert native_balance(client, WALLET, BLOCK) == 59935328005065188
    assert native_balance(client, WALLET, BLOCK - 1) == 28230269147324631


def test_the_delta_is_the_difference_across_one_block(client):
    assert native_balance_delta(client, WALLET, BLOCK) == 31705058857740557


def test_there_is_no_block_before_genesis(client):
    with pytest.raises(ValueError) as refusal:
        native_balance_delta(client, WALLET, 0)

    assert "entire balance as a credit" in str(refusal.value)


def test_a_pruned_node_refuses_rather_than_answering_zero(scripted):
    client = scripted(error={"code": -32000, "message": "missing trie node"})

    with pytest.raises(RpcRefused) as refusal:
        native_balance(client, WALLET, BLOCK)

    assert "missing trie node" in str(refusal.value)


def test_gas_cost_uses_the_price_actually_charged(client):
    """``effectiveGasPrice``, not a type-2 transaction's ceiling."""
    assert gas_cost(require_receipt(client, TX)) == 190275 * 14700000000


def test_a_receipt_missing_a_gas_field_is_refused(client):
    receipt = dict(require_receipt(client, TX))
    del receipt["effectiveGasPrice"]

    with pytest.raises(NativeReadRefused) as refusal:
        gas_cost(receipt)

    assert "short by exactly the fee" in str(refusal.value)
