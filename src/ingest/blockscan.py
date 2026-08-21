"""Check the precondition :mod:`ingest.settlement` states about itself and does not check.

The balance identity

    balance(block) - balance(block - 1) + gas paid by the wallet = native ETH received

is exact arithmetic on two node answers, and it establishes where a WETH unwrap settled without a
trace. The tracer bullet closed four native legs with it, all four to the wei, including one where
a third party submitted the transaction and the wallet paid no gas at all — and that one matches
the explorer's *trace-derived* internal-transfer list exactly.

It holds only when the wallet had **exactly one transaction in that block and received nothing
else**. ``settlement.py`` says so plainly and refuses to check it, on the ground that establishing
it "needs every transaction in the block attributed, which is a different and much larger read".

That is true of a full attribution and false of the check that matters. One
``eth_getBlockByNumber`` with full transaction objects answers it for **every** native leg in that
block at once — one call, not one per leg — and the free endpoints serve it.

What this establishes, and what it does not
-------------------------------------------

**Established.** That no *top-level transaction* in the block other than the one being read has the
wallet as ``from`` or ``to``, that the wallet is not the block's ``miner``, and that no consensus
withdrawal credited it. Those are the movers ``settlement.py``'s own list names: another
transaction from the same wallet, a transfer in, a miner payment.

**Not established, and this is the whole residue.** An *internal* transfer to the wallet, inside
some other transaction in the same block, moves the balance and appears in no top-level field. Only
a trace shows it, and no free endpoint serves traces — which is the constraint this entire ingestion
path is built around.

So the check narrows the precondition from "nothing else touched this wallet" to "no top-level
transaction and no protocol credit touched this wallet". A caller who wants the stronger claim needs
traces, and :data:`RESIDUE` is the sentence that says so wherever a settlement established this way
is published.

Why that narrowing is worth having anyway: the unchecked failure is silent and looks like a
confirmation. A residue that is named and bounded can be reasoned about; one that is neither is what
the machine publishes as a number.
"""

from typing import Optional, Tuple

from contracts.core import ContractError, normalise_asset
from transport import block_parameter

__all__ = [
    "BlockScanRefused",
    "SoleMoverUnestablished",
    "RESIDUE",
    "BlockOccupancy",
    "block_occupancy",
    "sole_mover_of_balance",
]


#: Carried wherever a settlement established through the balance identity is published. Written
#: once so the two places that describe the limit cannot drift apart.
RESIDUE = (
    "the sole-mover check reads top-level transactions, the block's miner and its consensus "
    "withdrawals. An INTERNAL transfer to this wallet inside another transaction in the same block "
    "moves the balance and appears in none of those -- only a trace shows it, and no free endpoint "
    "serves traces. So this establishes 'no top-level transaction and no protocol credit touched "
    "the wallet', which is narrower than 'nothing did'"
)


class BlockScanRefused(ContractError):
    """A block could not be read in the shape this check needs."""


class SoleMoverUnestablished(ContractError):
    """Something else in the block could have moved this wallet's balance.

    Raised rather than reported false, because the caller's next step is to *use* a balance delta
    as a measurement. A boolean would be checked by whoever remembered to; a refusal is checked by
    everyone.
    """


class BlockOccupancy(object):
    """Which top-level facts in one block could have moved one address's balance.

    Deliberately not a dataclass of counts: a caller that received counts would compare them to
    numbers it chose, and the comparison this supports is against *one specific transaction hash*.
    """

    __slots__ = ("block", "address", "tx_hashes", "is_miner", "withdrawal_wei")

    def __init__(self, block, address, tx_hashes, is_miner, withdrawal_wei):
        # type: (int, str, Tuple[str, ...], bool, int) -> None
        self.block = block
        self.address = address
        self.tx_hashes = tuple(tx_hashes)
        self.is_miner = bool(is_miner)
        self.withdrawal_wei = int(withdrawal_wei)

    def sole_mover_is(self, tx_hash):
        # type: (str) -> bool
        """True when ``tx_hash`` is the only top-level thing here that touched the address."""
        wanted = str(tx_hash).strip().lower()
        return (
            self.tx_hashes == (wanted,)
            and not self.is_miner
            and self.withdrawal_wei == 0
        )

    def why_not(self, tx_hash):
        # type: (str) -> str
        """The sentence a refusal needs: what else was in the block, named."""
        wanted = str(tx_hash).strip().lower()
        others = tuple(h for h in self.tx_hashes if h != wanted)
        parts = []
        if wanted not in self.tx_hashes:
            parts.append(
                "the transaction being read does not appear as a top-level transaction of this "
                "address in block {} at all -- it reached the wallet through an internal call, so "
                "the balance identity is the only evidence there is and it cannot be "
                "corroborated".format(self.block)
            )
        if others:
            parts.append(
                "{} other top-level transaction(s) of this address in the same block: {}".format(
                    len(others), ", ".join(others)
                )
            )
        if self.is_miner:
            parts.append("the address is the block's miner and was paid the block reward")
        if self.withdrawal_wei:
            parts.append(
                "a consensus withdrawal credited {} wei in this block".format(self.withdrawal_wei)
            )
        return "; ".join(parts) or "nothing found"

    def __repr__(self):
        return "<BlockOccupancy block={} address={} txs={} miner={} withdrawal={}>".format(
            self.block, self.address, len(self.tx_hashes), self.is_miner, self.withdrawal_wei
        )


def _hex_int(value, what, block):
    # type: (object, str, int) -> int
    if value is None:
        return 0
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    try:
        return int(str(value), 16)
    except (TypeError, ValueError):
        raise BlockScanRefused(
            "block {} reported {} as {!r}, which is not a quantity.".format(block, what, value)
        )


def block_occupancy(client, address, block):
    # type: (object, str, int) -> BlockOccupancy
    """Everything in ``block`` that could have moved ``address``'s balance at the top level.

    One ``eth_getBlockByNumber`` with full transaction objects. The answer covers **every** native
    leg in that block, so a run with several legs in one block pays for the read once.

    :raises BlockScanRefused: when the block is absent, or its transactions came back as hashes
        rather than objects -- which would make an empty result mean "nothing touched the wallet"
        when it means "this answer cannot say".
    """
    wanted = normalise_asset(address)
    answer = client.call("eth_getBlockByNumber", [block_parameter(block), True])
    if not isinstance(answer, dict):
        raise BlockScanRefused(
            "eth_getBlockByNumber for block {} answered {!r}. No block, no check -- and an absent "
            "block must not read as an empty one.".format(block, answer)
        )

    transactions = answer.get("transactions")
    if not isinstance(transactions, list):
        raise BlockScanRefused(
            "block {} returned no transactions list.".format(block)
        )
    if transactions and not isinstance(transactions[0], dict):
        raise BlockScanRefused(
            "block {} returned transaction hashes rather than objects; this check needs `from` and "
            "`to`. Reading an empty match off hashes would say nothing touched the wallet when it "
            "means the answer cannot tell.".format(block)
        )

    touching = []
    for tx in transactions:
        sender = tx.get("from")
        recipient = tx.get("to")
        if (sender and normalise_asset(sender) == wanted) or (
            recipient and normalise_asset(recipient) == wanted
        ):
            touching.append(str(tx.get("hash", "")).strip().lower())

    miner = answer.get("miner")
    withdrawn = 0
    for w in answer.get("withdrawals") or ():
        if isinstance(w, dict) and w.get("address") and normalise_asset(w["address"]) == wanted:
            withdrawn += _hex_int(w.get("amount"), "a withdrawal amount", block) * 10 ** 9

    return BlockOccupancy(
        block=block,
        address=wanted,
        tx_hashes=tuple(touching),
        is_miner=bool(miner) and normalise_asset(miner) == wanted,
        withdrawal_wei=withdrawn,
    )


def sole_mover_of_balance(client, address, block, tx_hash, occupancy=None):
    # type: (object, str, int, str, Optional[BlockOccupancy]) -> BlockOccupancy
    """Refuse unless ``tx_hash`` is the only top-level mover of ``address`` in ``block``.

    :param occupancy: a reading already taken for this ``(address, block)``. Supplied, no call is
        made -- a run with several legs in one block reads the block once.
    :returns: the occupancy, so a caller can carry it as evidence rather than re-deriving it.
    :raises SoleMoverUnestablished: naming what else was there.

    Note the case that refuses and should: a transaction that reached the wallet only through an
    internal call does not appear as a top-level transaction of the address at all. The balance
    identity is then the *only* evidence, uncorroborated, and this refuses rather than confirming
    it -- which is the honest answer, because confirming it is exactly what a trace would do and
    there is no trace.
    """
    reading = occupancy if occupancy is not None else block_occupancy(client, address, block)
    if reading.sole_mover_is(tx_hash):
        return reading
    raise SoleMoverUnestablished(
        "the balance delta of {} across block {} cannot be attributed to {} alone: {}. Using it "
        "anyway would confirm the wrong thing and look like a confirmation. {}".format(
            reading.address, block, tx_hash, reading.why_not(tx_hash), RESIDUE
        )
    )
