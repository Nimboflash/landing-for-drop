"""Log topics, and the one place a raw log becomes something with a name.

Every function here takes a log dict exactly as ``eth_getTransactionReceipt`` or ``eth_getLogs``
returned it and hands back a typed value, or refuses. Nothing here opens a socket and nothing here
decides what a *transaction* means — that is :mod:`ingest.receipts`.

The rule this module exists to enforce
--------------------------------------

**Every log in a receipt is accounted for.** A decoder that recognises three signatures and
quietly ignores the rest produces a number that is plausible, reproducible and wrong: the buy that
settled through a fourth event reads as a smaller buy, or as a giveaway, and nothing anywhere says
a log went unread. So there is no "skip" path. A log is either

* a **value movement**, decoded into one of :class:`TokenTransfer`, :class:`NativeUnwrap`,
  :class:`NativeWrap`; or
* a signature this module has been told, in :data:`SIGNATURES`, moves no value — returned as
  :class:`NoValueEvent`, which is an acknowledgement rather than an omission; or
* refused.

:data:`SIGNATURES` is deliberately short, and adding to it is meant to be a deliberate act with a
written reason. A signature admitted as ``moves_value=False`` because "it looked harmless" is the
silent skip wearing a different hat. Every entry in it was pinned against a *real* log before it
was written down: a signature added from an ABI a human remembered is a guess, and this registry is
exactly where a guess becomes a wrong number that looks plausible.

What refusing costs, and why refusing is still right
----------------------------------------------------

A refusal here is no longer a hole in the population. :mod:`pipeline.chain` turns
:class:`UnknownEvent` and :class:`LogShapeMismatch` into a carried status, and
:func:`pipeline.run.run_wallet_window` counts it — so an event this module has never heard of costs
one transaction that is *named* in the census and the quarantine queue rather than one that is
absent from both. That is what makes the conservative choice affordable: an event that cannot be
classified honestly is left unclassified, and the cost of leaving it shows up in a published number.

:data:`DECLINED` is the other half of that. It records the events this module has looked at and
deliberately refused to admit, with the reason — so a reader working the quarantine queue can tell
"nobody has looked at this topic" from "somebody looked and concluded it cannot be read correctly
here", and :func:`signature_for` says which in the refusal itself.

What this module guarantees
---------------------------

* the amounts it returns are the ``uint256`` words the node sent, as Python ints in **raw units** —
  no scaling, no ``Decimal``, no float;
* an address it returns came out of a 32-byte word whose top 12 bytes were zero, lowercased;
* an unrecognised ``topics[0]``, or a log whose shape contradicts the signature it claims, raises.
  The shape check covers **every** signature, not only the ones whose amounts are read: a log
  claiming a topic with the wrong number of topics or the wrong data width is not that event, and
  answering "no value moved" about it would be a statement about a different log.

What it does not guarantee
--------------------------

That the token is real, that the amount is economically meaningful, that the counterparty is who
you think, or that a contract emitting ``Transfer`` follows ERC-20 in any other respect. A
contract may emit any event it likes with any values it likes; this module reads bytes, and a
lying contract lies through it. It also says nothing about *native* ETH moved by a plain call —
that leaves no log at all, which is the hole :mod:`ingest.receipts` makes the caller fill rather
than guess at.

The exposure a restatement leaves open
--------------------------------------

``Signature.only_on`` pins a signature to one contract, and it is set on **no** ``moves_value=False``
entry. That asymmetry is deliberate — see :class:`Signature` for why pinning a restatement would
refuse the same protocol's other deployments, and 1inch alone emits ``OrderFilled`` from more than
one — but it leaves a real hole, and this is the paragraph the rest of this file points at rather
than one a reader should reconstruct.

A topic is the hash of a *name*. Any contract may emit any hash. So a contract that emits one of
the admitted restatements — ``Sync``, ``Swap`` in either version, ``Approval``, ``OrderFilled``,
``TokenExchange`` — with the right topic count and the right data width, and settles its value
movement by some mechanism that is **not** an ERC-20 ``Transfer`` in the same receipt, is read here
as an acknowledgement: no value moved. Nothing in the receipt then says a leg went unread, because
by this module's own rule the log *was* read. It is the one shape of silent skip that survives the
no-skip rule, and it survives because the rule is enforced per log and the claim being made is
about the receipt.

What bounds it is that each entry was pinned against a real receipt in which the ``Transfer`` legs
carrying the same amounts are present — that is the falsification attempt, and it is what
``tests/hand_computed/test_event_registry.py`` performs. One real log per entry is one real log; it
is evidence about the deployments measured, not a proof about every contract that will ever emit
these hashes. **This is not closed, and no field in this module closes it.**
"""

from dataclasses import dataclass
from typing import Optional

from contracts import WETH

# -- topics ---------------------------------------------------------------------
#
# Each is keccak256 of the canonical signature text carried beside it. They are written out as
# literals rather than computed, because computing them would need a keccak implementation in this
# package and the constant is what a reader checks against a block explorer.

#: ``Transfer(address indexed from, address indexed to, uint256 value)`` — ERC-20.
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

#: ``Withdrawal(address indexed src, uint256 wad)`` on WETH. The native-ETH leg.
WITHDRAWAL = "0x7fcf532c15f0a6db0bd6d0e038bea71d30d808c7d98cb3bf7268a95bf5081b65"

#: ``Deposit(address indexed dst, uint256 wad)`` on WETH.
DEPOSIT = "0xe1fffcc4923d04b559f4d29a8bfc6cda04eb5b0d3c460751c2402c5c5cc9109c"

#: ``Sync(uint112 reserve0, uint112 reserve1)`` — Uniswap V2 pair.
SYNC = "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"

#: ``Swap(address indexed sender, uint256 amount0In, uint256 amount1In, uint256 amount0Out,
#: uint256 amount1Out, address indexed to)`` — Uniswap V2 pair.
SWAP_V2 = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"

#: ``Approval(address indexed owner, address indexed spender, uint256 value)`` — ERC-20.
APPROVAL = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"

#: ``OrderFilled(address indexed maker, bytes32 orderHash, uint256 remaining)`` — 1inch Limit
#: Order Protocol v3, as embedded in the v5 aggregation router. The event ticket 19's tracer bullet
#: ran into: it made one of seven real transactions unreadable end to end.
ORDER_FILLED = "0xb9ed0243fdf00f0545c63a0af8850c090d86bb46682baec4bf3c496814fe4f02"

#: ``Swap(address indexed sender, address indexed recipient, int256 amount0, int256 amount1,
#: uint160 sqrtPriceX96, uint128 liquidity, int24 tick)`` — Uniswap v3 pool. A different signature
#: from :data:`SWAP_V2` and therefore a different topic; the two share only a name.
SWAP_V3 = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"

#: ``TokenExchange(address indexed buyer, int128 sold_id, uint256 tokens_sold, int128 bought_id,
#: uint256 tokens_bought)`` — Curve StableSwap. Curve's crypto pools emit a *different*
#: ``TokenExchange`` whose ids are ``uint256``; that is the hash of a different signature text
#: (``0xb2e76ae9…``) and it is not this one, so it is not admitted by this entry.
TOKEN_EXCHANGE = "0x8b3e96f2b889fa771c53c981b40daf005f63f637f1869f707052d15a3dd97140"

#: ``Permit(address indexed owner, address indexed token, address indexed spender, uint160 amount,
#: uint48 expiration, uint48 nonce)`` — Uniswap Permit2. Not the ERC-2612 ``Permit``, which has a
#: different signature text and therefore a different topic; these two share only a name, as the
#: two ``Swap`` entries do.
#:
#: 43 of the 548 transactions on ``tools/case_runs.py``'s four real wallets carried this topic and
#: nothing else unreadable — 7.8% of the population, refused end to end for an event that grants an
#: allowance.
PERMIT2_PERMIT = "0xc6a377bfc4eb120024a8ac08eef205be16b817020812c73223e81d1bdb9708ec"


# -- topics measured, and deliberately not admitted -----------------------------
#
# Named here so the decision is legible in code rather than being an absence somebody re-derives.
# They are NOT in SIGNATURES; a log carrying one is refused exactly as an unheard-of topic is,
# because the alternative to refusing it is a wrong number, not a smaller one.

#: ``TransferSingle(address indexed operator, address indexed from, address indexed to,
#: uint256 id, uint256 value)`` — ERC-1155.
TRANSFER_SINGLE = "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"

#: ``TransferBatch(address indexed operator, address indexed from, address indexed to,
#: uint256[] ids, uint256[] values)`` — ERC-1155.
TRANSFER_BATCH = "0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07e595d983b8c0526c8f7fb"


# -- refusals -------------------------------------------------------------------


class LogRefused(ValueError):
    """Base for every refusal in this module, with the three facts that identify the log.

    ``topic``, ``address`` and ``log_index`` are carried as attributes as well as being written
    into the message, and that is not duplication for its own sake. The message is prose and its
    wording is enforced by nothing; a caller that had to recover "which event, on which contract,
    at which position" by matching a substring would be reading a description of the fact rather
    than the fact, and would start reporting ``None`` the day somebody reworded a sentence. The
    composition root turns an unreadable log into a *carried status* on the result
    (:class:`pipeline.inputs.UndecodableTransaction`) and that status has to name the log; these
    three fields are what it names it with.

    Each is ``Optional`` because not every refusal knows all three — a dict that is not a log has
    no address to report, and that absence is a different statement from a wrong answer.

    **What this class is, and what the subclasses below are not.** A refusal here is a defect in
    the *input* — bytes that are not the log they claim to be — for every subclass except
    :class:`UnknownEvent` and :class:`LogShapeMismatch`. Those two are limitations of *this
    decoder*: the chain is allowed to contain events nobody has enumerated, and an ERC-721
    ``Transfer`` is a perfectly valid log this module has chosen not to read. They are raised the
    same way because this module has no result type to carry a status in; deciding which of the two
    a refusal is belongs to the caller, and :mod:`pipeline.chain` is where that decision is made.
    """

    def __init__(self, message, topic=None, address=None, log_index=None):
        super().__init__(message)
        self.topic = topic
        self.address = address
        self.log_index = log_index


class MalformedLog(LogRefused):
    """The log dict is not a log: a member is missing, or is not the hex the schema requires."""


class UnknownEvent(LogRefused):
    """``topics[0]`` is not in :data:`SIGNATURES`, or the signature is not known on this contract."""


class LogShapeMismatch(LogRefused):
    """The signature is known and the log contradicts it — wrong topic count, wrong data length."""


class RegistryInconsistent(Exception):
    """:data:`SIGNATURES` says something this module does not do. Raised at import.

    **Deliberately not a** :class:`LogRefused`. Every ``LogRefused`` is a statement about a log, and
    two of them are turned into a carried status by :mod:`pipeline.chain` — so a registry defect
    wearing that type would be reported as "the chain contained something we could not read", which
    is the opposite of true and would be counted as a measurement limitation in a published number.
    This is a defect in this file, and it is raised where a defect in this file belongs: at import,
    before anything has been decoded, so it cannot wait dormant for a log that happens to match.

    See :func:`_require_the_registry_agrees_with_this_module` for the two ways it can happen and
    what each one costs.
    """


# -- the registry ---------------------------------------------------------------


@dataclass(frozen=True)
class Signature:
    """One event this module is willing to see, and what it is willing to say about it.

    ``moves_value`` is the whole of the classification. ``True`` means the event *is* a movement
    of value and is decoded into one; ``False`` means the event restates a movement carried by
    some other log, and ``restates`` says which — decoding it too would double count.

    ``only_on`` pins a signature to one contract. It is set for the WETH legs, because a topic is
    a hash of a *name* and any contract may emit any hash: an arbitrary token emitting
    ``Withdrawal(address,uint256)`` is not an unwrap of native ETH, and treating it as one would
    credit somebody with ETH that never moved. It is set on **no restatement**, and that asymmetry
    is the point: the failure ``only_on`` exists to prevent is *inventing* a movement out of a
    topic collision, which only a ``moves_value=True`` entry can do. A restatement pinned to one
    address would instead refuse the same protocol's other deployments, and a refusal is now a
    counted row rather than a wrong number — see this module's docstring for the exposure that
    leaves, which is real and is not this field's to close.

    The converse does **not** hold and the difference is load-bearing: ERC-20 ``Transfer`` is a
    mover with no ``only_on`` at all. There is no address to pin it to — any contract may be a
    token, and that is the whole of what an ERC-20 is — so the field is set on two of the three
    movers and a reader must not take its presence on those two as a promise that every movement
    this module decodes has been checked against a known contract. What ``Transfer`` rests on
    instead is that it names its own asset: the token *is* ``log.address``, so a collision invents
    a movement of a token nobody holds rather than a movement of ETH somebody does. ``Withdrawal``
    and ``Deposit`` have no such property — they name an amount of *native ETH* and nothing else —
    which is exactly why those two, and only those two, are pinned.

    ``topics`` is the total length of the log's ``topics`` list — one for the signature hash plus
    one per indexed parameter — and ``data_words`` the number of 32-byte ABI words in ``data``.
    Both are stated for every entry and both are enforced for every entry, including the ones whose
    amounts are never read. A log that claims a signature and does not have its shape is some other
    event, and "this event moves no value" said about some other event is the silent skip again.
    """

    name: str
    topic: str
    text: str
    moves_value: bool
    topics: int
    data_words: int
    only_on: Optional[str] = None
    restates: str = ""


SIGNATURES = {
    TRANSFER: Signature(
        name="Transfer", topic=TRANSFER, text="Transfer(address,address,uint256)",
        moves_value=True, topics=3, data_words=1,
    ),
    WITHDRAWAL: Signature(
        name="Withdrawal", topic=WITHDRAWAL, text="Withdrawal(address,uint256)",
        moves_value=True, topics=2, data_words=1, only_on=WETH,
    ),
    DEPOSIT: Signature(
        name="Deposit", topic=DEPOSIT, text="Deposit(address,uint256)",
        moves_value=True, topics=2, data_words=1, only_on=WETH,
    ),
    SYNC: Signature(
        name="Sync", topic=SYNC, text="Sync(uint112,uint112)",
        moves_value=False, topics=1, data_words=2,
        restates="a pair's reserves after the swap. The tokens that moved to produce those "
                 "reserves each emitted their own Transfer; reading the reserve delta as a "
                 "movement as well would count the same hop twice.",
    ),
    SWAP_V2: Signature(
        name="Swap", topic=SWAP_V2,
        text="Swap(address,uint256,uint256,uint256,uint256,address)",
        moves_value=False, topics=3, data_words=4,
        restates="the amounts of the two Transfers the pair has already emitted, from the pair's "
                 "point of view. Both legs of the hop are in those Transfers; the Swap is the "
                 "pair's own summary of them.",
    ),
    APPROVAL: Signature(
        name="Approval", topic=APPROVAL, text="Approval(address,address,uint256)",
        moves_value=False, topics=3, data_words=1,
        restates="nothing. An allowance is permission to move tokens later; no balance changes "
                 "when it is granted, and a spend that follows emits its own Transfer.",
    ),
    ORDER_FILLED: Signature(
        name="OrderFilled", topic=ORDER_FILLED, text="OrderFilled(address,bytes32,uint256)",
        moves_value=False, topics=2, data_words=2,
        restates="a limit order fill whose two asset legs are ordinary ERC-20 Transfers in the "
                 "same receipt — the maker's asset out and the taker's asset in. This event "
                 "carries no fill amount at all: its two data words are the order hash and the "
                 "*remaining* maker amount, a residual quantity on an order rather than a "
                 "movement. Reading either as an amount would credit somebody with a token nobody "
                 "sent, and in the second word's case the number would even shrink as the order "
                 "filled. Pinned against log 96 of 0x559e18c0… on the 1inch v5 aggregation "
                 "router, where the maker's XUSDP leaves at log 97 and the WETH arrives at 99.",
    ),
    SWAP_V3: Signature(
        name="Swap", topic=SWAP_V3,
        text="Swap(address,address,int256,int256,uint160,uint128,int24)",
        moves_value=False, topics=3, data_words=5,
        restates="the two ERC-20 Transfers the pool has already emitted, one in each direction, "
                 "from the pool's point of view. Both legs of the hop are in those Transfers. "
                 "amount0 and amount1 are int256 in two's complement and the outgoing leg is "
                 "negative: on log 347 of 0xf4be8ef8… the word carrying -456067932 — the USDC the "
                 "pool paid out, and log 344's Transfer amount to the digit — is "
                 "0xffff…e4d0f4a4, which read as a uint256 is about 1.16e77 — an ordinary-looking "
                 "integer some 10^50 times the supply of any real token, and one that would pass "
                 "every unsigned check in this module. Nothing here reads these words, which is "
                 "the only reason that misreading has no path into a number.",
    ),
    PERMIT2_PERMIT: Signature(
        name="Permit", topic=PERMIT2_PERMIT,
        text="Permit(address,address,address,uint160,uint48,uint48)",
        moves_value=False, topics=4, data_words=3,
        restates="nothing, in the same way ERC-20 Approval restates nothing: an allowance is "
                 "permission to move tokens later, no balance changes when it is granted, and the "
                 "spend that follows emits its own Transfer. Uniswap's Permit2 sits between a "
                 "wallet and a router, so this event appears in ordinary swap receipts and not "
                 "only in approval transactions — which is why refusing it cost whole trades "
                 "rather than whole approvals. Pinned against log 195 of 0x4efd2616… on "
                 "0x000000000022d473030f116ddee9f6b43ac78ba3, where the three indexed words are "
                 "the owner, the SBET token and the router it is being approved for, and the "
                 "three data words are a uint160 allowance of 2^160-1, an expiry of 1677818028 "
                 "and a nonce of 0. Not one of the six is an amount that moved: the same receipt "
                 "carries the wallet's SBET out as ordinary Transfers, and that transaction is "
                 "wallet_b's five-lot FIFO sell — the case this registry entry was found by, "
                 "because refusing the receipt left all five lots marked as though never sold.",
    ),
    TOKEN_EXCHANGE: Signature(
        name="TokenExchange", topic=TOKEN_EXCHANGE,
        text="TokenExchange(address,int128,uint256,int128,uint256)",
        moves_value=False, topics=2, data_words=4,
        restates="tokens_sold and tokens_bought, which are the amounts of the two ERC-20 Transfers "
                 "the pool emitted in the same receipt — measured equal, word for word, on log 12 "
                 "of 0x2a569c2f… against logs 10 and 11. What this entry does NOT fix: a Curve "
                 "pool holding native ETH rather than WETH settles one of those two legs by plain "
                 "call, which emits no log at all, so that leg is invisible in the receipt and "
                 "this event does not make it visible. Admitting the event as a mover would not "
                 "recover it either — it would double count the leg that *is* logged. The missing "
                 "one is the trace-shaped hole ingest.receipts already names and refuses to fill.",
    ),
}


#: The topics :func:`decode_log` turns into a movement type. Written out beside the registry rather
#: than derived from ``decode_log``'s branches, because deriving it would make the check compare the
#: code to itself. Every ``moves_value=True`` entry must be here and nothing else may be.
MOVEMENT_DECODERS = frozenset({TRANSFER, WITHDRAWAL, DEPOSIT})


def _require_the_registry_agrees_with_this_module():
    """``moves_value`` is a claim, and this is what makes it one the code has to honour.

    Until this existed the field was read by nothing: :func:`decode_log` branches on ``topic``, so
    an entry could declare anything and the decoder would carry on. That is the field the whole
    discipline of this registry rests on, and a declaration nothing enforces drifts silently in both
    directions:

    * **declared a mover with no branch.** ``decode_log`` falls through to :class:`NoValueEvent`,
      the log is acknowledged, and the movement is gone. The registry documents a leg that the
      decoder does not produce, so a reader auditing the list sees the event handled;
    * **decoded as a movement without declaring it.** The entry's ``restates`` prose says the amount
      is carried elsewhere and the decoder emits it anyway, so the hop is counted twice.

    Both produce a trade nobody made, which is the failure this module exists to prevent, and
    neither shows up as an error at the point it happens. Checked at import: a registry that lies is
    not a decoding problem to be discovered by the right log turning up, and there is no log at all
    for the first case if the event is rare.

    Also checked here, because it is the same kind of claim: a ``moves_value=False`` entry must say
    what it restates. An entry admitted as harmless with no written reason is the silent skip with a
    comment, and the module docstring promises it cannot happen.
    """
    declared = {topic for topic, item in SIGNATURES.items() if item.moves_value}
    if declared != MOVEMENT_DECODERS:
        raise RegistryInconsistent(
            "SIGNATURES declares {} as moving value and decode_log builds a movement for {}. Every "
            "entry on one side must be on the other: a declared mover with no branch is decoded as "
            "an acknowledgement and its leg is lost, and a branch with no declaration emits a "
            "movement the entry's own restates prose says is carried by another log — counting the "
            "hop twice. Neither raises where it happens.".format(
                ", ".join(sorted(declared)) or "(nothing)",
                ", ".join(sorted(MOVEMENT_DECODERS)),
            )
        )
    silent = sorted(
        item.name for item in SIGNATURES.values() if not item.moves_value and not item.restates
    )
    if silent:
        raise RegistryInconsistent(
            "these entries are admitted as moving no value and do not say what they restate: {}. "
            "The written reason is the entry: without it there is nothing to check the claim "
            "against, and admitting a signature because it looked harmless is the silent skip "
            "wearing a different hat.".format(", ".join(silent))
        )


_require_the_registry_agrees_with_this_module()


@dataclass(frozen=True)
class Declined:
    """An event this module has read real bytes of and refused to admit, with the reason.

    Kept because "we have never seen this topic" and "we looked at this topic and concluded it
    cannot be read correctly here" are different facts, and the second one is the more useful of
    the two to whoever is working the quarantine queue: it says the next step is not *classify this
    event* but *decide whether the seam should be able to hold this asset at all*.

    Declining is not free and this type does not pretend otherwise — every transaction carrying one
    of these is a transaction the run cannot score. It is cheaper than the alternative only because
    the cost is counted: see :class:`pipeline.inputs.UndecodableTransaction`.
    """

    name: str
    topic: str
    text: str
    reason: str


DECLINED = {
    TRANSFER_SINGLE: Declined(
        name="TransferSingle", topic=TRANSFER_SINGLE,
        text="TransferSingle(address,address,address,uint256,uint256)",
        reason="ERC-1155 moves value, so this cannot be admitted as a restatement without losing a "
               "real leg — and it cannot be admitted as a mover either, because the asset it moves "
               "is the pair (contract, id) and contracts.Transfer names an asset with one address "
               "and has no second field. Admitted with token=contract, netting would offset two "
               "ids of one contract against each other as though they were one fungible balance, "
               "and price the difference. The positional trap is sharper still: data word 1 is the "
               "id and word 2 is the value, so a decoder reading data[0:32] as the amount would "
               "have taken 0x61896f8e…0001 — about 4.4e76 raw units — off a real log whose actual "
               "value is 1. Measured on log 311 of 0x8ed9a26a…, which is where those digits come "
               "from.",
    ),
    TRANSFER_BATCH: Declined(
        name="TransferBatch", topic=TRANSFER_BATCH,
        text="TransferBatch(address,address,address,uint256[],uint256[])",
        reason="Everything that disqualifies TransferSingle, once per element: one log carries two "
               "dynamic arrays and moves an arbitrary number of distinct assets at once. Log 531 "
               "of 0x4634f021… moves seven ids in eighteen data words, so the entry could not even "
               "state a data_words width. There is no honest single Transfer to decode it into.",
    ),
}


# -- what a decoded log is ------------------------------------------------------


@dataclass(frozen=True)
class TokenTransfer:
    """An ERC-20 ``Transfer``. ``raw_amount`` is the token's own raw unit, unscaled."""

    token: str
    from_addr: str
    to_addr: str
    raw_amount: int
    log_index: int


@dataclass(frozen=True)
class NativeUnwrap:
    """A WETH ``Withdrawal``: ``holder``'s WETH was burned and it was paid native ETH.

    WETH9 credits the withdrawer itself and nobody else, so ``holder`` is where the native ETH
    landed **first**. Where it went after that — a router forwarding it to the wallet that called
    it — is an internal call, and an internal call writes no log. That is the one fact in this
    transaction shape that a trace would supply and these bytes do not; see
    :func:`ingest.receipts.transfers_from_logs`, which refuses to invent it.
    """

    holder: str
    raw_amount: int
    log_index: int


@dataclass(frozen=True)
class NativeWrap:
    """A WETH ``Deposit``: ``holder`` was credited WETH against native ETH it sent.

    The mirror of :class:`NativeUnwrap`, with the same hole on the other side: WETH9 credits
    ``msg.sender``, and where that ETH came from before it reached ``holder`` is not in the logs.
    """

    holder: str
    raw_amount: int
    log_index: int


@dataclass(frozen=True)
class NoValueEvent:
    """A signature :data:`SIGNATURES` records as moving no value, returned rather than dropped.

    This type is the difference between "we read every log" and "we read the ones we liked". It
    carries no amount because there is no movement to carry.
    """

    name: str
    topic: str
    address: str
    log_index: int


# -- word decoding ---------------------------------------------------------------

_HEX_DIGITS = frozenset("0123456789abcdef")


def _hex_body(value, what, digits=None):
    """The digits of a ``0x``-prefixed lowercase hex string, or raise :class:`MalformedLog`."""
    if not isinstance(value, str) or not value.startswith("0x"):
        raise MalformedLog(
            "{} must be a 0x-prefixed hex string; got {!r} ({}). Chain bytes cross JSON-RPC as "
            "hex strings, and a member that is not one means this dict is not the log it claims "
            "to be — decoding on would read some other vendor's field layout as amounts.".format(
                what, value, type(value).__name__
            )
        )
    body = value[2:].lower()
    if not all(char in _HEX_DIGITS for char in body):
        raise MalformedLog(
            "{} is not hex: {!r}.".format(what, value)
        )
    if digits is not None and len(body) != digits:
        raise LogShapeMismatch(
            "{} must be {} hex digits ({} bytes) and is {}: {!r}. The ABI fixes this width; a "
            "value of another width is a different encoding, and reading it as this one shifts "
            "every field after it.".format(what, digits, digits // 2, len(body), value)
        )
    return body


def _address_word(word, what):
    """The 20-byte address in a 32-byte ABI word, lowercased.

    The top 12 bytes must be zero. They are padding in ``abi.encode(address)``, so a word with
    anything in them is not an address — it is a ``bytes32``, a ``uint256`` or another type
    entirely, and truncating it to its last 20 bytes would produce an address that looks perfectly
    ordinary and belongs to nobody.
    """
    body = _hex_body(word, what, 64)
    if body[:24] != "0" * 24:
        raise LogShapeMismatch(
            "{} is not an ABI-encoded address: the top 12 bytes are {!r}, not zero, in {!r}. "
            "abi.encode(address) left-pads with zeros, so a word with a non-zero prefix holds "
            "some other type. Truncating it to the last 20 bytes would yield a well-formed "
            "address owned by nobody, and every balance filed against it would be "
            "lost.".format(what, body[:24], word)
        )
    return "0x" + body[24:]


def _uint256_word(word, what):
    """The unsigned integer in a 32-byte ABI word, as a Python int in raw units."""
    return int(_hex_body(word, what, 64), 16)


# -- decoding one log ------------------------------------------------------------


def _member(log, name):
    if not isinstance(log, dict):
        raise MalformedLog(
            "a log must be the dict the node returned; got {}.".format(type(log).__name__)
        )
    if name not in log:
        raise MalformedLog(
            "the log has no {!r} member: {!r}. Every JSON-RPC log carries address, topics, data "
            "and logIndex; a dict without them is not a log, and guessing a default for the "
            "missing one would file a real movement against the wrong address or the wrong "
            "position in the receipt.".format(name, sorted(log))
        )
    return log[name]


def log_index(log):
    """The log's position in its block, as an int. ``contracts.Transfer.log_index`` wants this."""
    return int(_hex_body(_member(log, "logIndex"), "logIndex"), 16)


def log_address(log):
    """The emitting contract, lowercased. For an ERC-20 ``Transfer`` this is the token."""
    value = _member(log, "address")
    if not isinstance(value, str) or len(value) != 42:
        raise MalformedLog(
            "a log's address must be 0x followed by 40 hex digits; got {!r}. Every amount in this "
            "receipt is denominated by it, so a malformed one denominates them in "
            "nothing.".format(value)
        )
    return "0x" + _hex_body(value, "the log's address", 40)


def _topics(log):
    value = _member(log, "topics")
    if not isinstance(value, (list, tuple)) or not value:
        raise MalformedLog(
            "a log's topics must be a non-empty list; got {!r}. topics[0] is the event signature, "
            "so a log without one names no event and nothing can be said about its "
            "data.".format(value)
        )
    return [_hex_body(topic, "topics[{}]".format(index), 64)
            for index, topic in enumerate(value)]


def signature_for(log):
    """The :class:`Signature` this log claims, or raise :class:`UnknownEvent`.

    The refusal is the point. A log whose signature nobody has classified may or may not have
    moved value, and there is no safe default: treating it as a movement invents one, and treating
    it as noise loses one.

    A topic listed in :data:`DECLINED` is refused with the same exception and a different message.
    It has to be the same exception: :mod:`pipeline.chain` turns :class:`UnknownEvent` into the
    carried status that gets the transaction counted, and a declined event needs counting for
    exactly the reason an unheard-of one does. What changes is what the reader is told to do next.
    """
    topic0 = "0x" + _topics(log)[0]
    signature = SIGNATURES.get(topic0)
    if signature is None:
        declined = DECLINED.get(topic0)
        if declined is not None:
            raise UnknownEvent(
                "log {} on {} carries {} ({}), which this decoder has read real bytes of and "
                "deliberately does not admit. {} Nothing about this transaction is being asserted: "
                "it is refused whole, counted as undecodable, and named in the quarantine queue. "
                "Admitting the event would take a seam that can name the asset it moves, not an "
                "entry in ingest.events.SIGNATURES.".format(
                    log_index(log), log_address(log), declined.name, declined.text, declined.reason,
                ),
                topic=topic0, address=log_address(log), log_index=log_index(log),
            )
        raise UnknownEvent(
            "log {} on {} carries an unknown event signature {}. This decoder recognises {} "
            "signature(s) — {} — and refuses everything else rather than assuming it moved no "
            "value. What the assumption costs: a settlement that happens through an unlisted "
            "event reads as a smaller trade or as no trade at all, reproducibly, with nothing in "
            "the census, the queue or the coverage report to say a log went unread. To admit it, "
            "add it to ingest.events.SIGNATURES with moves_value stated and a written reason — "
            "deliberately, not by widening this check.".format(
                log_index(log), log_address(log), topic0, len(SIGNATURES),
                ", ".join(sorted(item.text for item in SIGNATURES.values())),
            ),
            topic=topic0, address=log_address(log), log_index=log_index(log),
        )
    address = log_address(log)
    if signature.only_on is not None and address != signature.only_on:
        raise UnknownEvent(
            "log {} on {} carries {} ({}), which this decoder recognises only on {}. A topic is "
            "the hash of a name, and any contract may emit any hash: an arbitrary token emitting "
            "this signature is not an unwrap of native ETH. Decoding it as one would credit an "
            "address with ETH that never moved, and the credit would net against a real sale to "
            "produce a trade nobody made.".format(
                log_index(log), address, signature.name, signature.text, signature.only_on
            ),
            topic=topic0, address=address, log_index=log_index(log),
        )
    return signature


def _naming(refusal, topic, address, index):
    """``refusal``, carrying the log it is about, when it was raised without one.

    :func:`_address_word` and :func:`_uint256_word` are handed 32 bytes and a label. They know
    nothing about the log the bytes came out of, so a refusal from either arrives with ``topic``,
    ``address`` and ``log_index`` all ``None``.

    That was survivable while every refusal ended the run — the message named the *word*, and the
    reader had a traceback. It stopped being survivable when :mod:`pipeline.chain` began turning
    :class:`UnknownEvent` and :class:`LogShapeMismatch` into a **carried status** whose entire job
    is to name the log: the queue record then reads *"LogShapeMismatch on log (unstated) of
    contract (unstated), topic (unstated)"*, which is a count wearing a record's clothes.
    :class:`pipeline.inputs.UndecodableTransaction` is explicit that a queue entry saying only
    "could not decode" cannot be worked, and that is exactly what one of these produced.

    It is reachable on ordinary mainnet bytes rather than on adversarial ones: an ERC-20
    ``Transfer`` whose indexed ``from`` word carries anything in its top twelve bytes — a
    ``bytes32`` where an address belongs — refuses inside :func:`_address_word` with no facts at
    all, and every other log in that receipt may decode perfectly.

    A **new instance** rather than a mutation, so a refusal stays immutable and the caller's
    ``from`` clause keeps the original. The class and the message are preserved exactly: what a
    refusal *is* is not this function's to change, only what it names — so a :class:`MalformedLog`
    annotated here is still a :class:`MalformedLog` and still raises past the composition root.

    A refusal that already names a log is returned untouched. Those come from
    :func:`signature_for`, :func:`_require_topics` and :func:`_require_data_words`, which know the
    log and say so; overwriting them here would let this function become a second authority on
    which log a refusal is about.
    """
    if (refusal.topic, refusal.address, refusal.log_index) != (None, None, None):
        return refusal
    return type(refusal)(str(refusal), topic=topic, address=address, log_index=index)


def decode_log(log):
    """One log dict to one typed event. Never returns ``None``; refuses instead.

    The shape is checked once, up front, for every signature — including the ones that decode to
    :class:`NoValueEvent` and therefore never have a word read out of them. "This event moved no
    value" is a claim about *this* event, and a log with the wrong topic count or the wrong data
    width is not the event it claims to be.

    Every refusal raised out of the word decoders below is re-raised naming this log; see
    :func:`_naming` for why a refusal that names nothing is worse now than it used to be.

    :raises MalformedLog: the dict is not a log.
    :raises UnknownEvent: ``topics[0]`` is unclassified or declined, or the signature is not known
        on this contract.
    :raises LogShapeMismatch: the signature is known and the log's shape contradicts it.
    """
    signature = signature_for(log)
    topics = _topics(log)
    index = log_index(log)
    address = log_address(log)
    _require_topics(signature, log, topics, signature.topics)
    _require_data_words(signature, log, signature.data_words)

    try:
        if signature.topic == TRANSFER:
            return TokenTransfer(
                token=address,
                from_addr=_address_word("0x" + topics[1], "Transfer.from"),
                to_addr=_address_word("0x" + topics[2], "Transfer.to"),
                raw_amount=_uint256_word(_member(log, "data"), "Transfer.value"),
                log_index=index,
            )

        if signature.topic in (WITHDRAWAL, DEPOSIT):
            holder = _address_word(
                "0x" + topics[1], "{}.{}".format(signature.name,
                                                 "src" if signature.topic == WITHDRAWAL else "dst")
            )
            amount = _uint256_word(_member(log, "data"), "{}.wad".format(signature.name))
            if signature.topic == WITHDRAWAL:
                return NativeUnwrap(holder=holder, raw_amount=amount, log_index=index)
            return NativeWrap(holder=holder, raw_amount=amount, log_index=index)
    except LogRefused as refusal:
        named = _naming(refusal, signature.topic, address, index)
        if named is refusal:
            raise
        raise named from refusal

    # Unreachable while the registry and MOVEMENT_DECODERS agree, which is checked at import. Kept
    # as a belt-and-braces refusal rather than dropped, because the cost of being wrong here is a
    # movement silently reported as an acknowledgement — and this is the exact line it would happen
    # on. It is not a LogRefused: nothing is wrong with the log.
    if signature.moves_value:  # pragma: no cover - _require_the_registry_agrees_... forbids it
        raise RegistryInconsistent(
            "{} ({}) is declared moves_value=True and reached the acknowledgement branch of "
            "decode_log, so its movement would be reported as a log that moved nothing.".format(
                signature.name, signature.text
            )
        )
    return NoValueEvent(
        name=signature.name, topic=signature.topic, address=address, log_index=index
    )


def _require_topics(signature, log, topics, expected):
    """Refuse a log whose indexed-parameter count contradicts the signature it claims.

    The case worth naming is ERC-721: it shares ``Transfer``'s topic and indexes a third parameter,
    the token id. A decoder that read ``topics`` positionally without counting them would read an
    NFT's *token id* as an ERC-20 *amount* — an integer, plausible, in raw units, and pure fiction.
    """
    if len(topics) == expected:
        return
    extra = ""
    if signature.topic == TRANSFER and len(topics) == 4:
        extra = (
            " Four topics on this signature is ERC-721: the third indexed parameter is a token id, "
            "not an amount. Read positionally it would arrive as a raw quantity of a token that "
            "has no quantity, and the position built from it would be priced."
        )
    raise LogShapeMismatch(
        "log {} on {} claims {} ({}), which has {} indexed parameter(s) and therefore {} topic(s); "
        "the log has {}.{}".format(
            log_index(log), log_address(log), signature.name, signature.text,
            expected - 1, expected, len(topics), extra,
        ),
        topic=signature.topic, address=log_address(log), log_index=log_index(log),
    )


def _require_data_words(signature, log, expected):
    """Refuse a log whose unindexed-parameter width contradicts the signature it claims.

    The ABI fixes the width of every entry in :data:`SIGNATURES`, so a ``data`` of another width is
    a different encoding. For a mover this shifts every field after the bad one; for a *non*-mover
    nothing would be read at all, and the refusal is worth more there rather than less — the whole
    output of decoding a non-mover is the sentence "no value moved here", and that sentence has to
    be about the event the log actually carries.

    Only signatures with a fixed width can be stated this way, and that is a real limit rather than
    an oversight: an ERC-1155 ``TransferBatch`` carries two dynamic arrays and has no width to
    state. It is in :data:`DECLINED`, for that reason among others.
    """
    body = _hex_body(_member(log, "data"), "the log's data")
    if len(body) == expected * 64:
        return
    raise LogShapeMismatch(
        "log {} on {} claims {} ({}), whose unindexed parameter(s) are {} ABI word(s) — 64 hex "
        "digits each, {} in total — and the log's data is {} digit(s). The ABI fixes this width, "
        "so data of another width is a different encoding: read as this one it shifts every field "
        "after the first, and read as nothing at all it would let some other event be reported as "
        "this one moving no value.".format(
            log_index(log), log_address(log), signature.name, signature.text,
            expected, expected * 64, len(body),
        ),
        topic=signature.topic, address=log_address(log), log_index=log_index(log),
    )


def decode_logs(logs):
    """Every log, in the order given, each as a typed event. No log is dropped.

    :raises LogRefused: on the first log that cannot be decoded, naming its index.
    """
    if not isinstance(logs, (list, tuple)):
        raise MalformedLog(
            "logs must be the list the node returned; got {}.".format(type(logs).__name__)
        )
    return tuple(decode_log(log) for log in logs)
