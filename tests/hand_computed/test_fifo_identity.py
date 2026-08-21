"""One ``tx_hash`` is one transaction inside a lot book, whatever case it arrives in.

``fifo._require_a_total_order`` compares ``(event.tx_hash or "").lower()``. That ``.lower()`` had
exactly one behavioural test behind it anywhere in the suite, and it was a *composed pipeline* test
three modules away: ``hand_computed/test_pipeline.py::
test_a_bypassed_hash_normalisation_does_not_reach_the_double_count``, which reaches this branch only
because the entry type's normalisation has been bypassed on the way in. Delete that one test and
dropping the fold goes silent.

It should not be silent, and the reason is a number. ``match_fifo`` is a public entry point — the
known-answer battery calls it directly, and nothing in ``contracts.NetTradeResult`` normalises a
hash — so a caller assembling a book from two sources that spell one hash differently gets *two
lots for one buy*. The whole quantity is then doubled: the position that was 4,000 tokens is 8,000,
half of it invented, and FIFO's own arithmetic stays perfectly consistent over the invented book.
Every expectation below is written out rather than derived.
"""

from decimal import Decimal

import pytest

from contracts import ClassificationStatus, NetTradeResult, QuarantineRequired, USDC
from fifo import match_fifo

WALLET = "0x" + "11" * 20
TOKEN = "0x" + "aa" * 20
POOL = "0x" + "cc" * 20

ONE_USDC = 10 ** 6
ONE_TOKEN = 10 ** 18


def buy(block, tx_hash, qty_raw=4_000 * ONE_TOKEN, usd="1000"):
    return NetTradeResult(
        tx_hash=tx_hash,
        portfolio_owner=WALLET,
        status=ClassificationStatus.VALID_BUY,
        sold_asset=USDC,
        bought_asset=TOKEN,
        sold_raw_amount=1_000 * ONE_USDC,
        bought_raw_amount=qty_raw,
        quote_asset=USDC,
        quote_usd=Decimal(usd),
        block_number=block,
        timestamp=1_600_000_000 + block * 12,
        pool=POOL,
    )


def test_two_buys_under_genuinely_different_hashes_are_two_lots():
    """The control, and the number the case-fold is protecting.

    4,000 + 4,000 = 8,000 raw tokens across two lots, $1,000 + $1,000 of basis. This is the right
    answer for two transactions and the wrong answer for one transaction spelled two ways, and
    nothing in the result distinguishes those two inputs — which is why the refusal has to happen
    before the book is built rather than be noticed afterwards.
    """
    result = match_fifo([buy(100, "0xaaa"), buy(101, "0xbbb")], [])

    assert len(result.open_lots) == 2
    assert sum(lot.remaining_raw for lot in result.open_lots) == 8_000 * ONE_TOKEN


@pytest.mark.parametrize("respelling", ("upper", "checksummed", "mixed"))
def test_one_hash_spelled_two_ways_is_one_transaction_and_refuses_the_book(respelling):
    """The book is quarantined rather than opened, in every spelling a caller can arrive with.

    Refused rather than deduplicated: ``match_fifo`` sees only the book, so it cannot tell a caller
    who supplied one transaction twice from a merge that went wrong — and it must not pick one row
    to open the lot, because whichever it dropped, every sell that followed would be assigned
    against a basis the other row also claims.
    """
    lower = "0xabcdef"
    other = {"upper": lower.upper(),
             "checksummed": lower[:2] + lower[2:].upper(),
             "mixed": "0xAbCdEf"}[respelling]
    assert other != lower and other.lower() == lower

    with pytest.raises(QuarantineRequired) as refusal:
        match_fifo([buy(100, lower), buy(101, other)], [])

    message = str(refusal.value)
    assert "appears twice in the same lot book" in message
    assert "blocks 100 and 101" in message


def test_the_refusal_is_the_hash_and_not_the_two_rows_being_alike():
    """Two rows that agree in nothing but their hash are still one transaction.

    Stated separately because the cheap repair — refuse when the duplicate rows *disagree* — would
    pass the case above and let this one through, and this is the shape a real merge produces: the
    same hash carrying two different quantities because one source netted it and the other did not.
    """
    with pytest.raises(QuarantineRequired):
        match_fifo(
            [buy(100, "0xdup", qty_raw=4_000 * ONE_TOKEN, usd="1000"),
             buy(140, "0xDUP", qty_raw=9 * ONE_TOKEN, usd="7")],
            [],
        )
