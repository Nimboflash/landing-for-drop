"""Encoding and validating JSON-RPC parameters. No meaning is attached to any of them.

Everything here is about the *wire*: is this a well-formed 32-byte hash, is this quantity encoded
the way the JSON-RPC schema requires. Nothing here knows what a transaction is for, what an
address holds, or what a log means — that is the decoder's job in whichever lane needs it, and it
is deliberately not shared.

Why the checks exist at all
---------------------------

A malformed hash does not fail loudly at a node. ``eth_getTransactionReceipt`` with a truncated
hash returns ``null`` on some vendors and an error on others, and ``null`` is indistinguishable
from "this transaction does not exist". Catching the shape here turns a silent wrong answer into a
refusal that names the input.

What they do not guarantee
--------------------------

Only shape. A well-formed hash may name nothing on any chain; a well-formed address may be a
typo one character away from the wallet you meant. Nothing here can tell you that.
"""

_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")

#: Block tags the JSON-RPC schema accepts in place of a quantity. Passed through verbatim.
#:
#: Note for the caller, not enforced here: every one of these except an explicit height makes a
#: call **unrepeatable**, so a recording made with ``"latest"`` replays a block that was latest on
#: the day it was recorded. Ticket 26 wants counts reproducible from a frozen snapshot; that means
#: heights, not tags.
BLOCK_TAGS = frozenset({"latest", "earliest", "pending", "safe", "finalized"})


def _is_hex_string(value, length=None):
    if not isinstance(value, str) or not value.startswith("0x"):
        return False
    digits = value[2:]
    if length is not None and len(digits) != length:
        return False
    if not digits:
        return False
    return all(char in _HEX_DIGITS for char in digits)


def require_hash(value, what="transaction hash"):
    """A 32-byte hex string, ``0x`` + 64 digits. Returned unchanged."""
    if not _is_hex_string(value, 64):
        raise ValueError(
            "{} must be 0x followed by 64 hex digits; got {!r}. A malformed hash does not fail "
            "loudly at a node — several vendors answer null, which reads downstream as 'no such "
            "transaction' and silently drops the very case being investigated.".format(
                what, value
            )
        )
    return value


def require_address(value, what="address"):
    """A 20-byte hex string, ``0x`` + 40 digits. Returned **unchanged, including its case**.

    Deliberately not lower-cased. The cache key follows the exact string passed, so silently
    normalising here would make two spellings of one address share a recording while a caller
    reading the fixture saw only one of them. Pass addresses in one consistent case; this function
    guarantees the shape and nothing about the spelling.
    """
    if not _is_hex_string(value, 40):
        raise ValueError(
            "{} must be 0x followed by 40 hex digits; got {!r}.".format(what, value)
        )
    return value


def hex_quantity(value):
    """Encode a non-negative int as a JSON-RPC quantity: minimal hex, ``0`` as ``"0x0"``.

    Refuses ``bool`` even though Python calls it an int: ``hex_quantity(True)`` would encode
    ``0x1`` and mean "block one", which is never what anybody wrote.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            "a quantity must be an int; got {!r} ({}).".format(value, type(value).__name__)
        )
    if value < 0:
        raise ValueError("a quantity must be non-negative; got {}.".format(value))
    return hex(value)


def block_parameter(value):
    """Normalise a block argument to what the wire accepts: a quantity or a tag.

    Accepts an ``int`` height, an already-encoded ``"0x..."`` string, or one of
    :data:`BLOCK_TAGS`. Anything else is refused rather than passed through, because a node
    handed an unrecognised block parameter answers with an error whose text names JSON-RPC
    internals rather than the caller's mistake.
    """
    if isinstance(value, bool):
        raise TypeError("a block parameter must be an int, a hex quantity, or a tag; got a bool.")
    if isinstance(value, int):
        return hex_quantity(value)
    if isinstance(value, str):
        if value in BLOCK_TAGS or _is_hex_string(value):
            return value
        raise ValueError(
            "unusable block parameter {!r}. Give a height as an int, an already-encoded hex "
            "quantity, or one of {}.".format(value, ", ".join(sorted(BLOCK_TAGS)))
        )
    raise TypeError(
        "a block parameter must be an int, a hex quantity, or a tag; got {}.".format(
            type(value).__name__
        )
    )


def assert_wire_safe(params, path="params"):
    """Refuse anything that cannot cross the wire as written, naming where it sits.

    Permitted: ``str``, ``bool``, ``None``, ``list``/``tuple``, and ``dict`` with string keys.

    ``int`` is **refused**, which is the surprising one and the point. Every ``eth_*`` quantity is
    a hex string; an int in the params reaches the node as a JSON number, which some vendors
    accept and others reject — and worse, it makes two spellings of the same call
    (``16308001`` and ``"0xf8d0a1"``) hash to two different cache keys, so a recorded snapshot
    would silently miss on replay and go back to the network. Encode with :func:`hex_quantity`.

    ``float`` is refused for the reason the whole repository refuses floats.
    """
    if params is None or isinstance(params, (str, bool)):
        return params
    if isinstance(params, float):
        raise TypeError(
            "float at {}: {!r}. Nothing in the JSON-RPC schema is a float, and a float that "
            "reaches a key has already changed what the key means.".format(path, params)
        )
    if isinstance(params, int):
        raise TypeError(
            "int at {}: {!r}. Quantities cross the wire as hex strings — encode it with "
            "hex_quantity({!r}) -> {!r}. An int here also splits the cache: the same call written "
            "two ways would hash to two keys, and a frozen snapshot would miss and silently go "
            "back to the network.".format(path, params, params, hex(params))
        )
    if isinstance(params, (list, tuple)):
        for index, item in enumerate(params):
            assert_wire_safe(item, "{}[{}]".format(path, index))
        return params
    if isinstance(params, dict):
        for key, item in params.items():
            if not isinstance(key, str):
                raise TypeError(
                    "non-string key at {}: {!r}. JSON object keys are strings, and a key coerced "
                    "on the way out would change the canonical form the cache key is built "
                    "from.".format(path, key)
                )
            assert_wire_safe(item, "{}[{!r}]".format(path, key))
        return params
    raise TypeError(
        "unusable parameter at {}: {!r} ({}).".format(path, params, type(params).__name__)
    )
