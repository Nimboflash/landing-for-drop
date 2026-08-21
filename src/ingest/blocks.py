"""A block header, reduced to the three fields anything downstream reads.

A receipt says which block a transaction is in and not when that block was. §4.7 buckets a buy by
token age in seconds, §4.4 measures a return over thirty days of them, and §6.3 puts a window's
edges on both a height and a second — so every one of those needs the header this module reads.

What it guarantees
------------------

The number, the timestamp and the hash are the ones the node returned for the height asked for,
as ints and a lowercase string. Nothing is defaulted; a header missing any of the three is
refused.

What it does not guarantee
--------------------------

That the block is canonical. A node answering from a side chain returns a well-formed header, and
nothing here can tell. :func:`ingest.blocks.require_block_of_receipt` closes the narrow version of
that — the header actually belongs to the receipt being read — and no more.
"""

from dataclasses import dataclass

from transport import block_parameter


class BlockRefused(ValueError):
    """A block could not be read, or the header does not describe the block that was asked for."""


@dataclass(frozen=True)
class BlockHeader:
    """The three fields of a block anything in this repository reads."""

    number: int
    timestamp: int
    block_hash: str


def block_header(client, block):
    """The header at ``block``. ``block`` is a height, not a tag.

    :raises BlockRefused: the node has no such block, or the header is missing a field.
    """
    height = block_parameter(block)
    header = client.get_block_by_number(height)
    if header is None:
        raise BlockRefused(
            "the endpoint that answered has no block at {}. A missing header is not a missing "
            "timestamp: without it a transaction in that block has no UTC second, so it cannot be "
            "placed in a §6.3 window or aged against a §4.7 trading start, and every horizon "
            "measured from it would be measured from nothing.".format(height)
        )
    return BlockHeader(
        number=_quantity(header, "number", height),
        timestamp=_quantity(header, "timestamp", height),
        block_hash=_block_hash(header, height),
    )


def _quantity(header, name, height):
    value = header.get(name)
    if not isinstance(value, str) or not value.startswith("0x"):
        raise BlockRefused(
            "the header at {} has no usable {} member (got {!r}).".format(height, name, value)
        )
    return int(value, 16)


def _block_hash(header, height):
    value = header.get("hash")
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        raise BlockRefused(
            "the header at {} has no usable hash member (got {!r}).".format(height, value)
        )
    return value.lower()


def require_block_of_receipt(header, receipt):
    """Refuse a header that is not the block the receipt says it is in. Returns the header.

    Two calls to a pool of public endpoints are two answers from two machines, and they may be
    separated by a reorg, by a pruning boundary, or by one vendor being an hour behind. A
    transaction dated by the wrong block gets the wrong UTC second, which moves it across a §6.3
    window edge or into a different §4.7 age bucket — a misclassification, with no missing value
    anywhere to make it loud.
    """
    stated = receipt.get("blockHash")
    if not isinstance(stated, str) or stated.lower() != header.block_hash:
        raise BlockRefused(
            "the header read at height {} hashes to {}, and the receipt for {} says it is in "
            "block {}. Two endpoints answered about two different blocks, so the timestamp about "
            "to be attached to this transaction is not its own.".format(
                header.number, header.block_hash, receipt.get("transactionHash"), stated
            )
        )
    if _receipt_height(receipt) != header.number:
        raise BlockRefused(
            "the header read is number {} and the receipt for {} says {}.".format(
                header.number, receipt.get("transactionHash"), receipt.get("blockNumber")
            )
        )
    return header


def _receipt_height(receipt):
    value = receipt.get("blockNumber")
    if not isinstance(value, str) or not value.startswith("0x"):
        raise BlockRefused(
            "the receipt for {} has no usable blockNumber (got {!r}).".format(
                receipt.get("transactionHash"), value
            )
        )
    return int(value, 16)
