"""Native ETH, measured from archive state — the check that replaces a trace here.

:func:`ingest.receipts.transfers_from_logs` refuses to guess where a WETH unwrap's native ETH
settled. This module is how that answer gets *established* rather than asserted: an address's own
ETH balance is readable at any height on an archive node, and the difference across one block is
what that address actually received, gas included.

On the tracer bullet the arithmetic closed exactly:

    balance(wallet, 16308001) - balance(wallet, 16308000)   =  31_705_058_857_740_557
    gasUsed x effectiveGasPrice                             =   2_797_042_500_000_000
                                                            ------------------------
                                                               34_502_101_357_740_557
    Withdrawal(WETH) at log 41                              =  34_502_101_357_740_557

which is the whole of the claim that the router forwarded the ETH to the wallet, made without a
trace and without trusting a block explorer's label.

What this module guarantees
---------------------------

Two numbers: the wei difference in one address's balance across one block, and the wei a receipt
says was spent on gas. Both are arithmetic on values a node returned.

What it does not guarantee — and this is the whole of the residue
-----------------------------------------------------------------

**That the delta belongs to the transaction you are reading.** A balance moves for every reason
inside a block: another transaction from the same wallet, a transfer in, a miner payment, a
withdrawal credit. The identity above holds only when the address had exactly *one* transaction in
that block and received nothing else, and **nothing in this module checks that**. It is
deliberately not checked here rather than checked badly: establishing it needs every transaction
in the block attributed, which is a different and much larger read. A caller who uses the delta
where the precondition does not hold gets a confirmation of the wrong thing, and it will look like
a confirmation.

So this is evidence for a settlement address, offered to a caller who has stated the precondition
— not a decoder that discovers one.
"""

from transport import block_parameter, require_address


class NativeReadRefused(ValueError):
    """A balance or a gas figure could not be read as an integer quantity."""


def native_balance(client, address, block):
    """The address's native-ETH balance at ``block``, in wei, as an int.

    ``eth_getBalance`` at a historical height needs a genuine archive node. A pruned one refuses,
    and that refusal arrives as :class:`transport.RpcRefused` rather than as a zero — which is the
    distinction that matters, because a zero balance is a measurement and a refusal is not.
    """
    account = require_address(address).lower()
    height = block_parameter(block)
    result = client.get_balance(account, height)
    if not isinstance(result, str) or not result.startswith("0x"):
        raise NativeReadRefused(
            "eth_getBalance for {} at {} answered {!r}, which is not a hex quantity.".format(
                account, height, result
            )
        )
    return int(result, 16)


def native_balance_delta(client, address, block):
    """``balance(block) - balance(block - 1)``, in wei. Signed: negative is money leaving.

    Two archive reads. The subtraction is the only interpretation, and it is exact — both operands
    are integers, and wei has no fractional part to lose.

    :raises ValueError: ``block`` is zero or negative; there is no block before the genesis block,
        and defaulting the earlier read to zero would report the whole of an address's balance as
        having arrived in block zero.
    """
    height = _height(block)
    if height <= 0:
        raise ValueError(
            "a balance delta needs the block before {}, and there is none. Reading the earlier "
            "side as zero would report an address's entire balance as a credit in this "
            "block.".format(height)
        )
    return (
        native_balance(client, address, height)
        - native_balance(client, address, height - 1)
    )


def gas_cost(receipt):
    """``gasUsed x effectiveGasPrice`` in wei, as an int — what the sender paid to send it.

    Read from the receipt rather than from the transaction, because ``effectiveGasPrice`` is what
    was actually charged after the base fee: a type-2 transaction's ``maxFeePerGas`` is a ceiling
    and is usually not the price. Using the ceiling would overstate the cost and, in the identity
    at the top of this module, would overstate the credit by the difference.

    Only the sender pays it. Adding it back to another address's delta would be adding a cost that
    address never bore.
    """
    used = _receipt_quantity(receipt, "gasUsed")
    price = _receipt_quantity(receipt, "effectiveGasPrice")
    return used * price


def _receipt_quantity(receipt, name):
    value = receipt.get(name)
    if not isinstance(value, str) or not value.startswith("0x"):
        raise NativeReadRefused(
            "the receipt for {} has no usable {} member (got {!r}). Without it the wei a "
            "transaction cost is unknown, and a native credit computed from a balance delta would "
            "be short by exactly the fee.".format(receipt.get("transactionHash"), name, value)
        )
    return int(value, 16)


def _height(block):
    if isinstance(block, bool) or isinstance(block, int):
        if isinstance(block, bool):
            raise TypeError("a block height must be an int; got a bool.")
        return block
    if isinstance(block, str) and block.startswith("0x"):
        return int(block, 16)
    raise TypeError(
        "a block height must be an int or a hex quantity; got {!r}. A tag such as 'latest' has no "
        "predecessor that will still be its predecessor tomorrow.".format(block)
    )
