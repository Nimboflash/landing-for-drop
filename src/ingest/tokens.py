"""``decimals()``, read from the chain, refused when it cannot be read.

Decimals are a property of a token contract and of nothing else. They are not in a log, not in a
receipt, and not derivable from an amount: ``41407684`` is a plausible quantity of any token at
any scale. Getting one wrong multiplies or divides every USD figure derived from that token by a
power of ten — quietly, because the resulting number is still a number and every ratio built from
one token alone is unchanged.

Measured on the tracer bullet: its WETH leg is ``34502101357740557`` raw units. At the correct 18
decimals that is 0.0345 ETH, worth about $41 in January 2023. Read at 6 — USDC's — it becomes
34,502,101,357 ETH, which is roughly 285 times every ether that has ever existed, and it would be
priced, ranked, and published without a single check anywhere in the pipeline objecting.

So this module asks the chain and takes no default. There is no fallback to 18, no table of
well-known tokens, and no inference from the size of an amount.

What it guarantees
------------------

* the value returned is the ``uint8`` an ``eth_call`` to ``decimals()`` returned at the height
  asked for, as an int;
* a token that does not answer, answers empty, or answers something that is not a ``uint8``, is
  refused by name.

What it does not guarantee
--------------------------

That the token *is* an ERC-20, that the value is the one the token's own front end displays, or
that it is the same at another height. A proxy may return one value today and another tomorrow,
which is why the height is a required argument rather than "latest": a run reproduces the number
it recorded, at the block it recorded it for.
"""

from transport import RpcRefused, block_parameter, require_address

#: ``keccak256("decimals()")[:4]``. Written out rather than computed: this package holds no keccak,
#: and the constant is what a reader checks against a block explorer's "Read Contract" tab.
DECIMALS_SELECTOR = "0x313ce567"

#: ``decimals()`` returns ``uint8``, so the ABI word is 31 zero bytes and one value byte.
_UINT8_PREFIX = "0" * 62


class TokenDecimalsUnreadable(ValueError):
    """A token's ``decimals()`` could not be read, or did not answer with a ``uint8``.

    A refusal rather than a status. The caller asked what scale a number is in and has no answer;
    every figure derived from that token would be wrong by a power of ten, and there is no
    partially-correct version of it to carry forward.
    """


def token_decimals(client, token, block):
    """``decimals()`` for ``token`` at ``block``, as an int.

    ``token`` is lowercased before the call, deliberately and unlike
    :func:`transport.params.require_address`. The recording cache keys on the exact spelling, so a
    checksummed address and its lowercase twin would be two snapshot entries and two live calls
    for one token — while ``contracts.normalise_asset`` has already made the lowercase spelling
    the only one anything downstream will ever hold.

    :param block: a height, as an int or an already-encoded quantity. Not a tag: ``"latest"``
        makes the answer unrepeatable, and a proxy that changes its implementation would then
        rescale a historical run.
    :raises TokenDecimalsUnreadable: every endpoint refused, or the answer is not a ``uint8``.
    """
    address = require_address(token).lower()
    height = block_parameter(block)
    try:
        result = client.call("eth_call", [{"to": address, "data": DECIMALS_SELECTOR}, height])
    except RpcRefused as refused:
        raise TokenDecimalsUnreadable(
            "decimals() for {} at {} was refused by every endpoint, so the scale of every amount "
            "denominated in this token is unknown. Refused rather than defaulted to 18: a wrong "
            "scale is silent — the number stays plausible and every figure built from it moves by "
            "a power of ten. The endpoints said:\n{}".format(address, height, refused.report())
        )
    return _uint8(result, address, height)


def _uint8(result, address, height):
    if not isinstance(result, str) or not result.startswith("0x"):
        raise TokenDecimalsUnreadable(
            "decimals() for {} at {} answered {!r}, which is not hex returndata.".format(
                address, height, result
            )
        )
    body = result[2:].lower()
    if not body:
        raise TokenDecimalsUnreadable(
            "decimals() for {} at {} returned empty returndata. That is what an address with no "
            "code, or a contract with no decimals() function, answers — the call did not revert, "
            "it simply had nothing to run. Reading 0x as zero decimals would make every raw "
            "amount its own USD quantity.".format(address, height)
        )
    if len(body) != 64 or any(char not in "0123456789abcdef" for char in body):
        raise TokenDecimalsUnreadable(
            "decimals() for {} at {} returned {} hex digit(s): {!r}. The ABI encodes a uint8 as "
            "one 32-byte word; returndata of another width is a different encoding, and reading "
            "its last byte would be reading whatever field happens to land there.".format(
                address, height, len(body), result
            )
        )
    if body[:62] != _UINT8_PREFIX:
        raise TokenDecimalsUnreadable(
            "decimals() for {} at {} returned {!r}, whose top 31 bytes are not zero. A uint8 is "
            "left-padded with zeros, so this word holds some other type — truncating it to its "
            "last byte would produce a scale between 0 and 255 that nothing in the contract ever "
            "stated.".format(address, height, result)
        )
    return int(body[62:], 16)


class DecimalsReader:
    """``decimals()`` for many tokens at one height, asked once per token.

    The height is fixed at construction because a scale read at two heights is two answers, and a
    run that mixed them would be scaling one token's amounts by one number and another's by
    another with nothing recording which. Caching is per reader, so "how many calls did this cost"
    stays answerable from ``client.calls``.
    """

    def __init__(self, client, block):
        self.client = client
        self.block = block
        self._known = {}

    def for_token(self, token):
        """The token's decimals, from this reader's cache or from the chain."""
        address = require_address(token).lower()
        if address not in self._known:
            self._known[address] = token_decimals(self.client, address, self.block)
        return self._known[address]

    def for_transfers(self, transfers):
        """``{token: decimals}`` covering every token in ``transfers``, refusing on the first gap.

        Every token, not the ones that happen to be priced later: a transfer whose scale nobody
        established is a leg that will be netted, matched and marked in units nobody named.
        """
        found = {}
        for transfer in transfers:
            found[transfer.token] = self.for_token(transfer.token)
        return found
