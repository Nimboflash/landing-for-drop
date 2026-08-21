"""Checking the precondition the balance identity rests on.

``ingest/settlement.py`` establishes where a WETH unwrap settled by arithmetic on two node answers,
and states that the identity holds only when the wallet had exactly one transaction in that block
and received nothing else — and that it does not check it, because doing so "needs every transaction
in the block attributed, which is a different and much larger read".

That is true of a full attribution and false of the check that matters: one ``eth_getBlockByNumber``
answers it for every native leg in the block at once.

Every block number and hash here is real Ethereum mainnet, replayed from the committed snapshot in
``tests/fixtures/case_runs/recordings`` and checkable against an explorer.
"""

import pytest

from ingest.blockscan import (
    RESIDUE,
    BlockOccupancy,
    BlockScanRefused,
    SoleMoverUnestablished,
    block_occupancy,
    sole_mover_of_balance,
)
from tools.case_runs import AUTO, RECORDINGS
from transport.cache import RecordingCache
from transport.client import RpcClient

WALLET = "0xe15b3d62c2bce51f2a8a8d53d76c36b4fab8721c"

#: The tracer bullet's four native legs. The first three were submitted by the wallet; the fourth
#: was submitted by a third party and reached the wallet through an internal call.
SUBMITTED_BY_WALLET = (
    ("0x10ab9b812107769650f6661c164a5bcfeca80caf67528aebde33090ab63ffc60", 16530343),
    ("0xce4e2048a41ae098cdfd93131895e16d57bd41f6fe1a748bf264178894a1ef42", 16535133),
    ("0xa51f7010a2ddb12a5d3cb45ed6084c569b85d834141cf078e69e20a4dcfbdef4", 16744492),
)
REACHED_BY_INTERNAL_CALL = (
    "0x559e18c0d5cd7704369dfbbe4a9520ad6d4b3e172000460b481e8ec9065e76de", 16758317
)


@pytest.fixture
def client():
    return RpcClient(cache=RecordingCache(RECORDINGS), mode=AUTO)


class _Block(object):
    """A client answering one hand-built block, for the shapes a real snapshot cannot supply."""

    def __init__(self, **block):
        self._block = block

    def call(self, method, params):
        assert method == "eth_getBlockByNumber"
        return self._block


def _tx(hash_, sender=None, to=None):
    return {"hash": hash_, "from": sender, "to": to}


# -- the three the wallet submitted ----------------------------------------------


@pytest.mark.parametrize("tx_hash,block", SUBMITTED_BY_WALLET)
def test_a_leg_the_wallet_submitted_establishes_its_sole_mover(client, tx_hash, block):
    reading = sole_mover_of_balance(client, WALLET, block, tx_hash)
    assert reading.tx_hashes == (tx_hash,)
    assert reading.is_miner is False
    assert reading.withdrawal_wei == 0


# -- the one it did not, which is the interesting case ---------------------------


def test_a_leg_reached_by_an_internal_call_is_refused_not_confirmed(client):
    """The check is conservative, and this is where that costs something real.

    This leg is the tracer bullet's strongest piece of evidence: the wallet paid no gas because a
    third party submitted the transaction, and the traceless balance identity gave
    31,288,840,359,330,406 wei — identical to the explorer's *trace-derived* internal-transfer list.

    It still refuses. The transaction does not appear as a top-level transaction of this address at
    all, so the identity is the only evidence there is and nothing here can corroborate it.
    Corroborating it is exactly what a trace would do, and no free endpoint serves traces.

    Refusing a case that happened to be right is the correct trade. The alternative is confirming
    on faith, and a wrong confirmation here looks exactly like a right one.
    """
    tx_hash, block = REACHED_BY_INTERNAL_CALL

    with pytest.raises(SoleMoverUnestablished) as caught:
        sole_mover_of_balance(client, WALLET, block, tx_hash)

    message = str(caught.value)
    assert "does not appear as a top-level transaction" in message
    assert "cannot be corroborated" in message
    assert RESIDUE in message


def test_that_block_really_holds_no_top_level_transaction_of_the_wallet(client):
    """The fact the refusal rests on, pinned separately so the refusal is not self-certifying."""
    tx_hash, block = REACHED_BY_INTERNAL_CALL
    reading = block_occupancy(client, WALLET, block)
    assert reading.tx_hashes == ()
    assert reading.sole_mover_is(tx_hash) is False


# -- each mover the precondition names -------------------------------------------


def test_a_second_transaction_of_the_same_wallet_refuses():
    mine = "0x" + "a" * 64
    other = "0x" + "b" * 64
    scan = _Block(transactions=[_tx(mine, sender=WALLET), _tx(other, sender=WALLET)], miner="0x" + "9" * 40)

    with pytest.raises(SoleMoverUnestablished) as caught:
        sole_mover_of_balance(scan, WALLET, 1, mine)
    assert other in str(caught.value)
    assert "1 other top-level transaction" in str(caught.value)


def test_a_transfer_in_from_somebody_else_refuses():
    mine = "0x" + "a" * 64
    inbound = "0x" + "c" * 64
    scan = _Block(
        transactions=[_tx(mine, sender=WALLET), _tx(inbound, sender="0x" + "1" * 40, to=WALLET)],
        miner="0x" + "9" * 40,
    )
    with pytest.raises(SoleMoverUnestablished) as caught:
        sole_mover_of_balance(scan, WALLET, 1, mine)
    assert inbound in str(caught.value)


def test_the_wallet_being_the_miner_refuses():
    mine = "0x" + "a" * 64
    scan = _Block(transactions=[_tx(mine, sender=WALLET)], miner=WALLET)
    with pytest.raises(SoleMoverUnestablished) as caught:
        sole_mover_of_balance(scan, WALLET, 1, mine)
    assert "block's miner" in str(caught.value)


def test_a_consensus_withdrawal_refuses_and_reports_wei_not_gwei():
    """Withdrawal ``amount`` is in gwei. Read as wei it would be a billion times too small.

    0x1 gwei is 1,000,000,000 wei; a check that compared the raw 1 against zero would still refuse
    here, but a caller reading the figure would be wrong by nine orders of magnitude.
    """
    mine = "0x" + "a" * 64
    scan = _Block(
        transactions=[_tx(mine, sender=WALLET)],
        miner="0x" + "9" * 40,
        withdrawals=[{"address": WALLET, "amount": "0x1"}],
    )
    with pytest.raises(SoleMoverUnestablished) as caught:
        sole_mover_of_balance(scan, WALLET, 1, mine)

    reading = block_occupancy(scan, WALLET, 1)
    assert reading.withdrawal_wei == 1_000_000_000
    assert "1000000000 wei" in str(caught.value)


# -- an answer that cannot say is not an answer that says no ---------------------


def test_transaction_hashes_rather_than_objects_are_refused():
    """The distinction the refusal exists for.

    A block fetched without full transaction objects has no ``from`` or ``to`` to match, so nothing
    matches — and "nothing matched" would read as "nothing touched the wallet". One is a finding and
    the other is the absence of one.
    """
    scan = _Block(transactions=["0x" + "a" * 64], miner="0x" + "9" * 40)
    with pytest.raises(BlockScanRefused) as caught:
        block_occupancy(scan, WALLET, 1)
    assert "cannot tell" in str(caught.value)


def test_an_absent_block_is_refused_rather_than_read_as_empty():
    class _Nothing(object):
        def call(self, method, params):
            return None

    with pytest.raises(BlockScanRefused) as caught:
        block_occupancy(_Nothing(), WALLET, 1)
    assert "must not read as an empty one" in str(caught.value)


# -- the read is paid for once per block, not once per leg -----------------------


def test_one_block_read_serves_every_leg_in_it():
    mine = "0x" + "a" * 64

    class _Counting(_Block):
        calls = 0

        def call(self, method, params):
            _Counting.calls += 1
            return _Block.call(self, method, params)

    scan = _Counting(transactions=[_tx(mine, sender=WALLET)], miner="0x" + "9" * 40)
    reading = block_occupancy(scan, WALLET, 1)
    for _ in range(5):
        sole_mover_of_balance(scan, WALLET, 1, mine, occupancy=reading)

    assert _Counting.calls == 1


# -- the residue is carried, not left in a docstring -----------------------------


def test_the_residue_names_the_internal_transfer_it_cannot_see():
    assert "INTERNAL transfer" in RESIDUE
    assert "no free endpoint serves traces" in RESIDUE
    assert "narrower than" in RESIDUE


def test_occupancy_reports_what_it_found_rather_than_a_verdict():
    reading = BlockOccupancy(block=1, address=WALLET, tx_hashes=(), is_miner=False,
                             withdrawal_wei=0)
    assert reading.why_not("0x" + "a" * 64).startswith("the transaction being read does not appear")
