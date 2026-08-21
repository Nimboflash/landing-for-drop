"""Hyperliquid fills, read into the types ``src/pipeline/inputs.py`` already defines.

This is an **order book, not an AMM**, and the difference is not cosmetic. A fill has a price and a
size; it does not have a pool, reserves, a curve, or a counterparty anybody names. Several things
§4 is written around therefore have no referent here at all, and they are listed in
:data:`NOT_APPLICABLE` rather than approximated — an approximation of a concept that does not exist
is a number with nothing behind it, and this repository's own vocabulary already has the word for
what that produces: a measured-looking zero.

What is produced
----------------

:func:`decode_fills` returns a :class:`DecodedFills` with three buckets and one law:

    transactions   pipeline.inputs.ObservedTransaction   -- readable, with a net position
    undecodable    pipeline.inputs.UndecodableTransaction -- real, and unreadable, and counted
    excluded       ExcludedFill                          -- real, readable, and outside §4's scope

**Every input fill lands in exactly one bucket, and the constructor refuses a bundle where that is
not true.** That is not tidiness. ``UndecodableTransaction``'s own docstring gives the reason: a
refusal that removes a transaction from the run *before the population is counted* leaves no census,
no queue and no coverage report able to say a transaction went missing, and the population a run
measures would be silently defined by what the decoder happens to know. The conservation check is
that rule made mechanical.

The grouping question, which real data answered
-----------------------------------------------

``userFills`` returns one row per *fill*, not per transaction, and one transaction fills as many
resting orders as it crosses. The main committed recording is one wallet's 382 fills over an
addressable window; they carry 262 distinct hashes, 5 of which hold more than one fill and one of
which holds **32**. So a decoder that mapped a fill to an ``ObservedTransaction`` would hand
``pipeline.run_wallet_window`` 32 rows under one hash, and ``_require_one_transaction_per_hash``
would refuse the whole run.

So fills are grouped by hash and a group becomes one transaction with many legs. That in turn makes
the group, not the fill, the unit of refusal: if any fill in a group cannot be read, the **whole
group** becomes one ``UndecodableTransaction``. This is ``ingest.events``' rule one venue over — a
partly-read transaction is not a smaller answer, it is a wrong one.

**Two things about that 32 are worth stating rather than leaving to be assumed.** It is a
*perpetual* group, so it is excluded before it could ever reach the pipeline; the largest group that
becomes a transaction on this recording carries 3 fills and 9 transfer legs. And the argument above
survives that either way — a fill-per-transaction decoder that excluded perpetuals first would still
have produced 3 rows under one hash, and 3 is as refused as 32.

**No group in either committed recording mixes markets.** The all-or-nothing rule is therefore
exercised by a hand-built case in ``tests/hyperliquid/test_decode.py`` and not by this data, and
saying so is the point: a rule whose only evidence is the example written to demonstrate it is a
rule about that example. What the data *does* show is the mixture one bucket over — the zero-hash
group below mixes 55 spot fills with 7 perpetual ones, which is why identity is checked first.

The zero hash, which is not an identity
----------------------------------------

62 of those 382 fills carry ``hash`` = ``0x0000…0000``. They are not one transaction, and the
recording says so three ways: their timestamps span 48 days, they mix 55 spot fills with 7
perpetual ones, and each carries a **distinct** ``tid`` — 62 different trade ids under one hash.
Grouping by hash would fuse seven weeks of unrelated trading into a single "transaction".
``ObservedTransaction.tx_hash`` requires an identity so a row can be "reconciled against raw chain
data afterwards"; the zero hash reconciles against nothing.

They are therefore :class:`ExcludedFill` and not ``UndecodableTransaction``, and the distinction is
forced rather than chosen: ``UndecodableTransaction`` *also* requires a ``tx_hash``, and admitting
these under the zero hash would reproduce the same fusion in the quarantine queue. They are counted,
named by ``(coin, time, oid, tid)``, and returned — nothing is dropped.

What ``tx_sender`` may honestly say
------------------------------------

377 of the 382 fills have ``crossed: false``. Our wallet's order was resting; somebody else crossed
the spread, and the transaction hash on the row is *their* submission. Amendment A6.1 records
``tx_sender`` alongside the recovered owner and forbids either standing in for the other, so writing
the wallet's own address into ``tx_sender`` for a maker fill would assert that substitution — for
233 of the 235 decoded transactions on this recording. A group every one of whose fills is
``crossed`` gets the wallet, and 2 of them do; every other group gets
:func:`tools.hyperliquid.provenance.unknown_submitter`, which is address-width, provably not hex,
and not equal to the wallet.

Where refusals raise and where they are carried
------------------------------------------------

Both, on purpose, and the boundary is the one this repository already draws:

* :func:`decode_spot_fill` **raises**. A caller who names one fill as spot and hands a perpetual, or
  a number that will not parse as a ``Decimal``, has a defect in what assembled the call.
* :func:`decode_fills` **carries**. A stream from ``userFills`` legitimately mixes markets and
  legitimately contains rows this decoder has never seen; that is a limitation of what can be
  measured, and a limitation is a status the report publishes. It does not guess: it calls the
  raising primitive and files the refusal's own class name and message, verbatim, into
  ``UndecodableTransaction.refusal`` and ``.detail`` — which is exactly what those two fields are
  for.
* :func:`leaderboard_addresses` **raises** on a malformed ``ethAddress``. A leaderboard row is a
  sampling input, not a population being counted; there is no census for it to go missing from, and
  a row whose address is not an address is a row about nobody.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Tuple

from contracts import Transfer
from contracts.numeric import calc, mul

from attribution import AttributionContext
from pipeline.inputs import (
    MEASUREMENT_HORIZON_SECONDS,
    ObservedTransaction,
    UndecodableTransaction,
    Window,
    WindowConfig,
)

from .provenance import (
    hyperliquid_asset,
    orderbook_counterparty,
    require_real_address,
    unknown_submitter,
)

#: ``0x`` plus 64 hex digits.
_TX_HASH = re.compile(r"^0x[0-9a-f]{64}$")

#: What Hyperliquid puts in ``hash`` for a fill with no L1 transaction behind it.
ZERO_HASH = "0x" + "0" * 64

#: The block number every decoded transaction carries.
#:
#: **It is not a block number.** ``userFills`` reports ``time`` in milliseconds and no height, and
#: this decoder will not manufacture one. The value is the *same* for every transaction precisely so
#: that it cannot be read as an ordering: a per-fill counter, or ``time`` folded into this field,
#: would look like a height and would be used like one.
#:
#: It has a measured consequence, and it is the reason :func:`run_inputs` supplies no §4.7 token
#: trading starts. ``pipeline.run`` orders its results by ``(block_number, tx_hash)``; with the
#: first component constant that degenerates to lexicographic **hash order**, which is not time
#: order, so FIFO would consume lots in an order with no meaning. ``token_age_bucket`` reads it too,
#: and §4.7's bucket A is "the first ten blocks" — a bucket that cannot exist where there are no
#: blocks. Supplying no ``TokenStart`` makes ``pipeline.run`` quarantine such a buy as unknown-age
#: instead of filing it as D, which is the loud outcome rather than the wrong one.
BLOCK_NUMBER_NOT_CARRIED = 0

#: Concepts §4 is written around that have no referent on an order book. Data, with the reason
#: stored beside each, so a refusal can say what is missing rather than only that something is.
#: Pinned by ``tests/hyperliquid/test_decode.py`` so it cannot rot into a stale note.
NOT_APPLICABLE = {
    "pool state": (
        "§4.5 marks an open position by walking an exit along a constant-product pool and capping "
        "execution cost by asset tier. An order book has price levels and a queue, not reserves "
        "and not a curve, so there is no PoolState to supply and no depth to simulate. The venue's "
        "l2Book endpoint returns the book *now*, which is not the book at a past marking horizon, "
        "so it is not a substitute either."
    ),
    "§4.6 quote asset": (
        "contracts.QUOTE_ASSETS is a frozen whitelist of four Ethereum Mainnet addresses. "
        "Hyperliquid's USDC is a Hyperliquid-native token (index 0, tokenId "
        "0x6d1e7cde53ba9467b783cb7c530ce054, weiDecimals 8) whose EVM contract lives on HyperEVM "
        "with two fewer decimals again. No HL asset is a §4.6 quote asset, so netting prices none "
        "of these trades and every one of them is UNSUPPORTED for USD. Mapping one onto the other "
        "is refused by provenance.audit_no_mainnet_assets."
    ),
    "block number": (
        "userFills carries a millisecond timestamp and no height. See BLOCK_NUMBER_NOT_CARRIED."
    ),
    "§4.7 token trading start": (
        "§4.7 defines it as first usable liquidity plus one real swap. A spot market here goes live "
        "by deployment and auction, with no pool to become usable and no swap to be the first. The "
        "two events are not the same event, and calling the listing a trading start would file a "
        "buy in a §4.7 age bucket derived from a different phenomenon."
    ),
    "migration replacement pool": (
        "A migration is liquidity moving from one pool to another. There are no pools."
    ),
    "§4.1 attribution": (
        "This source cannot exercise the attribution stage *at all*, and the reason is the opposite "
        "of a gap: userFills is keyed by the wallet you asked about, so the venue has already "
        "answered the question §4.1 exists to ask. There are no logs, no router or aggregator "
        "addresses, no Safe execution and no ERC-4337 UserOperation to reason from. The "
        "AttributionContext produced here is empty, which is how a caller says nothing is known."
    ),
    "event signatures and the undecodable-log census": (
        "ingest.events refuses a receipt whose logs it cannot decode. There are no receipts and no "
        "logs; a fill is a JSON object. UndecodableTransaction.topic, .contract and .log_index are "
        "therefore None on everything this module produces, and its .refusal names a Hyperliquid "
        "refusal rather than an unknown event signature."
    ),
    "perpetual lot": (
        "A perpetual position is margin and a signed size; there is no unit of the asset to hold, "
        "so there is no lot for FIFO to open or consume and no cost basis to carry. Perpetual "
        "fills are excluded and counted, never netted."
    ),
    "counterparty address": (
        "A fill names price, size and side, and nobody to have traded with. Transfer needs a "
        "from_addr and a to_addr, so both non-wallet ends carry "
        "provenance.orderbook_counterparty() — one identifier for the venue, not one per fill, "
        "because minting a distinct counterparty per fill would manufacture the appearance of "
        "distinct market participants."
    ),
    "gas and the native fee": (
        "There is no gas on this path and no native token leaving the wallet to pay for one. The "
        "only fee is the venue's, in feeToken, and it is carried as a Transfer with is_fee=True."
    ),
}


# -- refusals -------------------------------------------------------------------


class HyperliquidRefusal(Exception):
    """Base for every refusal this module raises about one fill.

    Deliberately not a :class:`contracts.ContractError`. These are not findings about a chain's
    data being unusual; they are this decoder declining to invent something. :func:`decode_fills`
    converts each one into a carried status by copying its class name and message verbatim, so the
    text of every subclass below is read by a person working a quarantine queue.
    """


class UnknownAsset(HyperliquidRefusal):
    """A fill's ``coin`` is in neither ``spotMeta`` nor ``meta``."""


class PerpFillPresentedAsSpot(HyperliquidRefusal):
    """A perpetual fill was handed to the spot decoder."""


class NotADecimal(HyperliquidRefusal):
    """A field that must be a number will not parse as a :class:`decimal.Decimal`."""


class QuantityNotRepresentable(HyperliquidRefusal):
    """An exact quantity does not fit the token's raw-unit precision."""


class MalformedFill(HyperliquidRefusal):
    """A fill is missing a field this decoder needs, or one has an unexpected shape."""


class UniverseUnreadable(ValueError):
    """``spotMeta`` or ``meta`` could not be read into a universe.

    Raised, not carried, and the boundary is deliberate: the universe is a *precondition* of reading
    any fill, not a row in a population. A broken universe does not make one fill unreadable, it
    makes every classification arbitrary, and there is no census for it to go missing from.
    """


# -- the universes --------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    """One Hyperliquid-native token, as ``spotMeta`` describes it.

    ``asset`` is the identifier every ``Transfer`` produced from this token carries. It is minted by
    :func:`tools.hyperliquid.provenance.hyperliquid_asset` from ``token_id`` and is provably not an
    Ethereum address; see that module for why filing these under ``evmContract.address`` would be a
    quantity error and not merely a naming one.
    """

    name: str
    index: int
    wei_decimals: int
    sz_decimals: int
    token_id: str
    asset: str


@dataclass(frozen=True)
class SpotPair:
    """One spot market: the ``coin`` a fill names, and the two tokens it is between."""

    coin: str
    base: Token
    quote: Token


class SpotUniverse(object):
    """``spotMeta`` read into pairs, keyed by the ``coin`` string a fill actually carries.

    Two traps in the payload, both measured on the committed recording:

    * **``index`` is not the list position.** Neither ``tokens`` nor ``universe`` is ordered by its
      own ``index`` field, so a consumer that enumerated the list would resolve pair ``@107`` to the
      wrong tokens. Everything here keys by ``index``.
    * **the ``coin`` on a fill is the universe entry's ``name``,** which is ``"PURR/USDC"`` for a
      canonical market and ``"@107"`` for every other one. There is no second spelling to fall back
      to, so lookup is by that string exactly.
    """

    def __init__(self, tokens, pairs):
        self._tokens_by_index = dict(tokens)
        self._tokens_by_name = {}
        for token in self._tokens_by_index.values():
            self._tokens_by_name.setdefault(token.name, []).append(token)
        self._pairs = dict(pairs)

    @classmethod
    def from_spot_meta(cls, payload):
        if not isinstance(payload, Mapping) or "tokens" not in payload or "universe" not in payload:
            raise UniverseUnreadable(
                "spotMeta must be an object with 'tokens' and 'universe'; got {}. Refusing to "
                "guess: every fill's asset identity is resolved through this payload, so a shape "
                "this reader does not recognise makes every classification "
                "arbitrary.".format(type(payload).__name__)
            )
        tokens = {}
        for position, entry in enumerate(payload["tokens"]):
            token = _token_from(entry, position)
            if token.index in tokens:
                raise UniverseUnreadable(
                    "spotMeta lists two tokens at index {} ({!r} and {!r}). The index is what a "
                    "universe entry points at, so two tokens claiming one index means a pair "
                    "resolves to whichever was read last.".format(
                        token.index, tokens[token.index].name, token.name
                    )
                )
            tokens[token.index] = token
        pairs = {}
        for position, entry in enumerate(payload["universe"]):
            coin = entry.get("name")
            if not isinstance(coin, str) or not coin:
                raise UniverseUnreadable(
                    "spotMeta universe entry {} has no usable 'name'; that string is the only key "
                    "a fill's 'coin' can be matched against".format(position)
                )
            members = entry.get("tokens")
            if not isinstance(members, list) or len(members) != 2:
                raise UniverseUnreadable(
                    "spotMeta universe entry {!r} names {} token(s); a spot market is a pair, and "
                    "a decoder that took the first two of three would be choosing which market "
                    "this is".format(coin, "no" if members is None else len(members))
                )
            try:
                base, quote = tokens[members[0]], tokens[members[1]]
            except KeyError as missing:
                raise UniverseUnreadable(
                    "spotMeta universe entry {!r} refers to token index {} which the tokens list "
                    "does not contain".format(coin, missing)
                )
            if coin in pairs:
                raise UniverseUnreadable(
                    "spotMeta names two universe entries {!r}; a fill carrying that coin would "
                    "resolve to whichever was read last".format(coin)
                )
            pairs[coin] = SpotPair(coin=coin, base=base, quote=quote)
        return cls(tokens, pairs)

    def pair(self, coin):
        """The market a fill's ``coin`` names, or ``None``."""
        return self._pairs.get(coin)

    def token_named(self, name):
        """The token called ``name``, or ``None``; ``None`` too when the name is ambiguous.

        Ambiguity collapses to "not found" on purpose. ``feeToken`` is a *name*, and if two tokens
        ever share one, the correct answer is that the fee's asset is unknown — not whichever token
        happened to be read first.
        """
        found = self._tokens_by_name.get(name) or []
        return found[0] if len(found) == 1 else None

    @property
    def coins(self):
        return frozenset(self._pairs)

    @property
    def tokens(self):
        return tuple(self._tokens_by_index[index] for index in sorted(self._tokens_by_index))


def _token_from(entry, position):
    try:
        name = entry["name"]
        index = entry["index"]
        wei_decimals = entry["weiDecimals"]
        sz_decimals = entry["szDecimals"]
        token_id = entry["tokenId"]
    except (KeyError, TypeError) as missing:
        raise UniverseUnreadable(
            "spotMeta token at position {} is missing {}; name, index, weiDecimals, szDecimals and "
            "tokenId are all required — weiDecimals converts a size into raw units and tokenId is "
            "what the asset identifier is minted from".format(position, missing)
        )
    for label, value in (("index", index), ("weiDecimals", wei_decimals),
                         ("szDecimals", sz_decimals)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise UniverseUnreadable(
                "spotMeta token {!r} has {} = {!r}, which is not an int".format(name, label, value)
            )
    return Token(
        name=name,
        index=index,
        wei_decimals=wei_decimals,
        sz_decimals=sz_decimals,
        token_id=token_id,
        asset=hyperliquid_asset(token_id),
    )


class PerpUniverse(object):
    """``meta`` read into the set of perpetual market names.

    Fetched to **refuse**, not to decode. A perpetual has no lot, so the only thing this universe is
    used for is telling a perpetual fill apart from a spot fill before anything runs FIFO over it.
    """

    def __init__(self, names):
        self._names = frozenset(names)

    @classmethod
    def from_meta(cls, payload):
        if not isinstance(payload, Mapping) or not isinstance(payload.get("universe"), list):
            raise UniverseUnreadable(
                "meta must be an object with a 'universe' list; got {}".format(
                    type(payload).__name__
                )
            )
        names = []
        for position, entry in enumerate(payload["universe"]):
            name = entry.get("name") if isinstance(entry, Mapping) else None
            if not isinstance(name, str) or not name:
                raise UniverseUnreadable(
                    "meta universe entry {} has no usable 'name'".format(position)
                )
            names.append(name)
        return cls(names)

    @property
    def names(self):
        return self._names

    def holds(self, coin):
        return coin in self._names


# -- numbers --------------------------------------------------------------------


def parse_decimal(text, described):
    """Hyperliquid's string numbers, straight to :class:`decimal.Decimal`. Never through ``float``.

    The venue sends every number as a JSON string — ``"px": "54.571"`` — which is the one thing that
    makes this safe: the value reaches ``contracts.numeric.calc`` with every digit it was sent with.
    A JSON *number* would already have been through ``float`` inside ``json.loads`` before this
    function could object, so one is refused here rather than laundered: ``calc`` rejects floats on
    sight and this turns that into a message naming the field.

    :raises NotADecimal: on anything that is not a string parsing to a finite Decimal.
    """
    if isinstance(text, float):
        raise NotADecimal(
            "{} arrived as a float ({!r}). Hyperliquid sends numbers as JSON strings and this "
            "decoder parses them straight to Decimal; a float has already lost precision inside "
            "json.loads, before anything here could refuse it, so accepting it would launder the "
            "loss.".format(described, text)
        )
    if not isinstance(text, str):
        raise NotADecimal(
            "{} must be a string number and is a {} ({!r}).".format(
                described, type(text).__name__, text
            )
        )
    try:
        value = calc(text)
    except (ValueError, InvalidOperation):
        raise NotADecimal("{} is {!r}, which is not a decimal number".format(described, text))
    if not value.is_finite():
        raise NotADecimal(
            "{} is {!r}, which parses but is not finite. A non-finite value reaching a gate "
            "comparison evaluates False against every threshold and reads as an ordinary "
            "failure.".format(described, text)
        )
    return value


def raw_units(amount, wei_decimals, described):
    """``amount`` in the token's raw integer units, refusing anything that does not fit exactly.

    §9.2 requires raw quantities to match a hand trace exactly and ``contracts.Transfer.raw_amount``
    is an ``int``, so a quantity that needs more precision than the token has cannot be carried at
    all — not rounded, because a rounded raw quantity is a different quantity and the difference
    does not show up anywhere downstream.

    **Nothing in either committed recording reaches this refusal**, and that is stated rather than
    glossed. All 238 decodable spot fills scale exactly: the traded pair is HYPE/USDC, both tokens
    carry ``weiDecimals`` 8, and ``px * sz`` lands on a whole number of raw units every time. So the
    guard is exercised only by a hand-built case in ``tests/hyperliquid/test_decode.py``, and a
    reader should weigh it accordingly — a guard whose only evidence is the example written to
    demonstrate it is a guard about that example. It is kept because the venue's own ``szDecimals``
    and ``weiDecimals`` differ per token (USDC is 8 and 8; PURR is 0 and 5), so a pair whose quote
    carries fewer decimals than the product needs is an ordinary market rather than a contrived one.

    :raises QuantityNotRepresentable: when the scaled value is not an integer.

    **The scale factor is built with integer arithmetic, not Decimal exponentiation.**
    ``calc(10) ** wei_decimals`` would be the obvious spelling and is the one this repository has a
    whole structural test about: ``Decimal.__pow__`` rounds its result to whatever context happens
    to be current, which is the ambient 28 digits and not the frozen 38, and ``**`` is not one of
    the ``contracts.numeric`` primitives that hold the context internally. ``10 ** wei_decimals`` is
    exact Python ``int`` arithmetic at any width, and ``calc`` then coerces it without loss. A
    negative ``weiDecimals`` is refused rather than handled for the same reason: ``10 ** -2`` in
    Python is a **float**, and a float is precisely what ``calc`` exists to reject on sight.
    """
    if isinstance(wei_decimals, bool) or not isinstance(wei_decimals, int) or wei_decimals < 0:
        raise QuantityNotRepresentable(
            "{}: the token's weiDecimals is {!r}, which is not a non-negative int. The raw-unit "
            "scale is built as 10 ** weiDecimals in integer arithmetic — exact at any width — and a "
            "negative exponent there produces a Python float, which contracts.numeric.calc refuses "
            "on sight because it has already lost precision.".format(described, wei_decimals)
        )
    scaled = mul(amount, calc(10 ** wei_decimals))
    truncated = int(scaled)
    if scaled != truncated:
        raise QuantityNotRepresentable(
            "{} is {} which, scaled by the token's weiDecimals of {}, is {} — not a whole number of "
            "raw units. contracts.Transfer.raw_amount is an int and §9.2 requires raw quantities to "
            "match a hand trace exactly, so this cannot be rounded: a rounded raw quantity is a "
            "different quantity, and nothing downstream would ever say so.".format(
                described, amount, wei_decimals, scaled
            )
        )
    if truncated < 0:
        raise QuantityNotRepresentable(
            "{} is {}, which is negative. Transfer.raw_amount is unsigned and direction lives in "
            "from/to, so a negative quantity has to be turned into a direction by the caller "
            "rather than carried as a sign.".format(described, amount)
        )
    return truncated


# -- the carried statuses -------------------------------------------------------

#: A fill whose ``hash`` is absent, malformed, or the zero hash.
NO_TRANSACTION_IDENTITY = "NO_TRANSACTION_IDENTITY"

#: A fill on a perpetual market.
PERP_NO_LOT = "PERP_NO_LOT"


@dataclass(frozen=True)
class ExcludedFill:
    """A fill that is real and readable and that §4 has no place for.

    Distinct from ``UndecodableTransaction``, which is for a fill whose *net position is unknown*.
    A perpetual fill is perfectly legible — filing it as undecodable would claim this decoder could
    not read it, which is false, and would put it in a quarantine queue whose remedy ("widen the
    decoder") does not apply. And a zero-hash fill cannot be an ``UndecodableTransaction`` at all,
    because that type requires a ``tx_hash`` too.

    Every field here is what a reader needs to find the row again on the venue: the market, the
    millisecond, the order id and the trade id.
    """

    reason: str
    why: str
    coin: str
    time_ms: Optional[int]
    oid: Optional[int]
    tid: Optional[int]

    def describe(self):
        return "{}: {} (coin {}, time {}, oid {}, tid {})".format(
            self.reason, self.why, self.coin, self.time_ms, self.oid, self.tid
        )


@dataclass(frozen=True)
class DecodedFills:
    """The three buckets, and the conservation law over them.

    ``sources`` maps a transaction hash to the fills that produced it, for both the decoded and the
    undecodable transactions, so a reader can get from a published row back to the venue's own rows.

    :raises ValueError: when the buckets do not account for every input fill. That refusal is the
        mechanical form of ``UndecodableTransaction``'s reason for existing — a fill that leaves the
        decoder unaccounted for is a fill no census can report missing.
    """

    transactions: Tuple[ObservedTransaction, ...]
    undecodable: Tuple[UndecodableTransaction, ...]
    excluded: Tuple[ExcludedFill, ...]
    sources: Mapping[str, Tuple[Mapping[str, Any], ...]]
    fills_in: int
    wallet: str = ""
    context: AttributionContext = field(default_factory=AttributionContext)

    def __post_init__(self):
        object.__setattr__(self, "transactions", tuple(self.transactions))
        object.__setattr__(self, "undecodable", tuple(self.undecodable))
        object.__setattr__(self, "excluded", tuple(self.excluded))
        object.__setattr__(self, "sources", dict(self.sources))
        accounted = len(self.excluded)
        for item in tuple(self.transactions) + tuple(self.undecodable):
            accounted += len(self.sources.get(item.tx_hash, ()))
        if accounted != self.fills_in:
            raise ValueError(
                "decoding accounted for {} of {} fills. Every fill must land in exactly one bucket "
                "— a transaction, a carried undecodable status, or a named exclusion. A fill that "
                "leaves the decoder unaccounted for is one no census can report missing, and the "
                "population a run measures would then be silently defined by what this decoder "
                "happens to know.".format(accounted, self.fills_in)
            )

    @property
    def census(self):
        """Counts by bucket and, within the exclusions, by reason. For a coverage report."""
        counts = {
            "transactions": len(self.transactions),
            "undecodable": len(self.undecodable),
            "excluded": len(self.excluded),
            "fills_in": self.fills_in,
        }
        for item in self.excluded:
            key = "excluded:" + item.reason
            counts[key] = counts.get(key, 0) + 1
        for item in self.undecodable:
            key = "undecodable:" + item.refusal
            counts[key] = counts.get(key, 0) + 1
        return counts


# -- decoding -------------------------------------------------------------------


def decode_spot_fill(fill, spot, perps, wallet, log_index=0):
    """The legs of one spot fill. **Raises** on anything it will not guess at.

    :param fill: one object from ``userFills``.
    :param spot: a :class:`SpotUniverse`.
    :param perps: a :class:`PerpUniverse`, consulted only so a perpetual can be named as such
        instead of being reported as an unknown asset.
    :param wallet: the address the fills were requested for, already validated.
    :param log_index: the index the first leg carries; legs are numbered from it.
    :returns: a tuple of :class:`contracts.Transfer`.

    :raises PerpFillPresentedAsSpot: the coin is a perpetual market. A perpetual position is margin
        and a signed size, so there is no lot to open and FIFO over it is meaningless.
    :raises UnknownAsset: the coin is in neither universe.
    :raises NotADecimal: a number will not parse.
    :raises QuantityNotRepresentable: a quantity does not fit the token's raw units.
    :raises MalformedFill: a required field is missing or ``side`` is neither ``"A"`` nor ``"B"``.

    **What the legs claim.** A buy is the base arriving from the book and the quote leaving to it;
    a sell is the reverse; the fee is a third leg with ``is_fee=True``. A zero fee produces no leg,
    because a transfer of nothing is not a transfer. A *negative* fee is a maker rebate and produces
    a leg in the opposite direction — ``Transfer.raw_amount`` is unsigned and direction lives in
    from/to, so a rebate cannot be carried as a negative fee. There are none in the committed
    recording; the branch exists because the venue pays them and a decoder that crashed on the first
    one would be a decoder that had never met a maker.

    **What they do not claim.** ``log_index`` is the leg's position among the legs *this decoder
    assembled*, not a position in a receipt — there is no receipt. It is stable for a given
    recording and ordering, and it is not a fact about the venue.
    """
    coin = fill.get("coin")
    if not isinstance(coin, str) or not coin:
        raise MalformedFill("fill has no 'coin'; there is nothing to identify the market by")
    pair = spot.pair(coin)
    if pair is None:
        if perps.holds(coin):
            raise PerpFillPresentedAsSpot(
                "coin {!r} is a perpetual market, not a spot market. A perpetual position is "
                "margin and a signed size: there is no unit of an asset to hold, so there is no "
                "lot for FIFO to open or consume and no cost basis to carry. Decoding it as spot "
                "would mint a lot of a token the wallet never held, and §4's whole measurement is "
                "over lots.".format(coin)
            )
        raise UnknownAsset(
            "coin {!r} is in neither spotMeta ({} markets) nor meta ({} perpetuals). Refusing to "
            "guess what asset moved: the recorded universes are the only description of this "
            "venue's markets this decoder has, and a coin outside both is a market it has never "
            "been told about. This is an ordinary condition rather than a corrupt payload — the "
            "second committed recording contains real fills on '#870' and '#881', and the wallet "
            "they came from carries 1,918 such fills in its last 2,000, on markets named like "
            "'xyz:SP500' and '#8310'. They are builder-deployed markets that neither universe "
            "endpoint lists, so no wider fetch would admit them.".format(
                coin, len(spot.coins), len(perps.names)
            )
        )
    for required in ("px", "sz", "side"):
        if required not in fill:
            raise MalformedFill(
                "fill on {!r} has no {!r}; price, size and side are the whole of what an order "
                "book fill says moved".format(coin, required)
            )
    side = fill["side"]
    if side not in ("A", "B"):
        raise MalformedFill(
            "fill on {!r} has side {!r}; Hyperliquid uses 'B' for a bid (the wallet bought the "
            "base) and 'A' for an ask (it sold). Refusing to guess: the two produce opposite "
            "transfers, so a wrong guess reverses the trade rather than "
            "losing it.".format(coin, side)
        )
    price = parse_decimal(fill["px"], "fill on {!r}: px".format(coin))
    size = parse_decimal(fill["sz"], "fill on {!r}: sz".format(coin))
    base_raw = raw_units(size, pair.base.wei_decimals, "fill on {!r}: sz".format(coin))
    notional = mul(price, size)
    quote_raw = raw_units(
        notional, pair.quote.wei_decimals, "fill on {!r}: px*sz".format(coin)
    )
    book = orderbook_counterparty()
    bought = side == "B"
    legs = [
        Transfer(
            token=pair.base.asset,
            from_addr=book if bought else wallet,
            to_addr=wallet if bought else book,
            raw_amount=base_raw,
            log_index=log_index,
        ),
        Transfer(
            token=pair.quote.asset,
            from_addr=wallet if bought else book,
            to_addr=book if bought else wallet,
            raw_amount=quote_raw,
            log_index=log_index + 1,
        ),
    ]
    fee_leg = _fee_leg(fill, spot, wallet, book, log_index + 2)
    if fee_leg is not None:
        legs.append(fee_leg)
    return tuple(legs)


def _fee_leg(fill, spot, wallet, book, log_index):
    if "fee" not in fill:
        return None
    fee = parse_decimal(fill["fee"], "fill on {!r}: fee".format(fill.get("coin")))
    if fee == 0:
        return None
    name = fill.get("feeToken")
    token = spot.token_named(name) if isinstance(name, str) else None
    if token is None:
        raise UnknownAsset(
            "fill on {!r} pays a fee of {} in {!r}, which spotMeta does not name exactly once. The "
            "fee is a real movement of a real token out of the wallet; filing it under the traded "
            "asset, or dropping it, would both change the wallet's net position by the fee "
            "amount.".format(fill.get("coin"), fee, name)
        )
    rebate = fee < 0
    amount = raw_units(
        -fee if rebate else fee, token.wei_decimals,
        "fill on {!r}: fee".format(fill.get("coin")),
    )
    return Transfer(
        token=token.asset,
        from_addr=book if rebate else wallet,
        to_addr=wallet if rebate else book,
        raw_amount=amount,
        log_index=log_index,
        is_fee=True,
    )


def decode_fills(fills, spot, perps, wallet):
    """Read a ``userFills`` stream into the seam's types, losing no fill.

    :param fills: the list ``userFills`` or ``userFillsByTime`` returned, verbatim.
    :param spot: a :class:`SpotUniverse`; :param perps: a :class:`PerpUniverse`.
    :param wallet: the address the stream was requested for.
    :returns: :class:`DecodedFills`.

    The order of the checks is forced and worth stating, because it decides which refusal a fill
    that fails two of them is reported under:

    1. **identity**, because neither ``ObservedTransaction`` nor ``UndecodableTransaction`` can
       exist without a ``tx_hash``. A fill with no usable hash cannot be carried by either type, so
       it is excluded and named.
    2. **market**, per fill, because a group may in principle mix them. No non-zero-hash group in
       either committed recording does; the zero-hash bucket does (55 spot, 7 perpetual), which is
       exactly why identity is checked before market rather than after.
    3. **numbers**, last, because they are the only check that needs the market resolved.

    A group is all-or-nothing: any fill in it that cannot be read makes the whole group one
    ``UndecodableTransaction``. A group that is entirely perpetual is excluded fill by fill.

    **What this does not do.** It does not deduplicate across calls, it does not sort, and it does
    not ask whether the stream is complete — ``userFills`` is capped at 2000 rows with no cursor, so
    a wallet at the cap has history this function will never see and cannot detect. Use
    ``userFillsByTime``, whose window is addressable, if completeness matters.
    """
    wallet = require_real_address(wallet, "decode_fills(wallet)")
    order = []
    groups = {}
    excluded = []
    for position, fill in enumerate(fills):
        tx_hash = fill.get("hash") if isinstance(fill, Mapping) else None
        if not isinstance(tx_hash, str) or not _TX_HASH.match(tx_hash.lower()):
            excluded.append(_no_identity(fill, position, tx_hash, "not a 32-byte hash"))
            continue
        if tx_hash.lower() == ZERO_HASH:
            excluded.append(_no_identity(fill, position, tx_hash, "the zero hash"))
            continue
        key = tx_hash.lower()
        if key not in groups:
            order.append(key)
            groups[key] = []
        groups[key].append(fill)

    transactions = []
    undecodable = []
    sources = {}
    for key in order:
        members = groups[key]
        kinds = {_market_of(fill, spot, perps) for fill in members}
        if kinds == {"perp"}:
            for fill in members:
                excluded.append(
                    ExcludedFill(
                        reason=PERP_NO_LOT,
                        why=NOT_APPLICABLE["perpetual lot"],
                        coin=fill.get("coin"),
                        time_ms=fill.get("time"),
                        oid=fill.get("oid"),
                        tid=fill.get("tid"),
                    )
                )
            continue
        sources[key] = tuple(members)
        try:
            transactions.append(_transaction_from(key, members, spot, perps, wallet))
        except HyperliquidRefusal as refusal:
            undecodable.append(
                UndecodableTransaction(
                    tx_hash=key,
                    block_number=BLOCK_NUMBER_NOT_CARRIED,
                    timestamp=_timestamp_of(members),
                    tx_sender=_sender_of(members, wallet),
                    topic=None,
                    contract=None,
                    log_index=None,
                    refusal=type(refusal).__name__,
                    detail=str(refusal),
                )
            )
    return DecodedFills(
        transactions=tuple(transactions),
        undecodable=tuple(undecodable),
        excluded=tuple(excluded),
        sources=sources,
        fills_in=len(fills),
        wallet=wallet,
    )


def _market_of(fill, spot, perps):
    coin = fill.get("coin")
    if spot.pair(coin) is not None:
        return "spot"
    if perps.holds(coin):
        return "perp"
    return "unknown"


def _no_identity(fill, position, tx_hash, what):
    coin = fill.get("coin") if isinstance(fill, Mapping) else None
    return ExcludedFill(
        reason=NO_TRANSACTION_IDENTITY,
        why=(
            "fill {} carries {!r} as its transaction hash, which is {}. ObservedTransaction and "
            "UndecodableTransaction both require a tx_hash, and both require it for the same "
            "reason — a transaction with no identity cannot be quarantined, counted in the census, "
            "or reconciled against the venue afterwards. Grouping these together would be worse "
            "than dropping them: in the main committed recording 62 fills share the zero hash, "
            "their timestamps span 48 days, they mix 55 spot fills with 7 perpetual ones, and each "
            "carries a distinct tid — 62 different trade ids under one hash. They would have become "
            "one 'transaction'. Excluded and counted instead — nothing here is "
            "dropped.".format(position, tx_hash, what)
        ),
        coin=coin,
        time_ms=fill.get("time") if isinstance(fill, Mapping) else None,
        oid=fill.get("oid") if isinstance(fill, Mapping) else None,
        tid=fill.get("tid") if isinstance(fill, Mapping) else None,
    )


def _transaction_from(key, members, spot, perps, wallet):
    legs = []
    for fill in members:
        legs.extend(decode_spot_fill(fill, spot, perps, wallet, log_index=len(legs)))
    return ObservedTransaction(
        tx_hash=key,
        block_number=BLOCK_NUMBER_NOT_CARRIED,
        timestamp=_timestamp_of(members),
        # A fill exists, so the transaction that produced it did not revert: the venue reports no
        # fills for a rejected order. This is the one field here that is a claim about the L1 rather
        # than a copy of a field, and it is the weakest kind of claim — an inference from the
        # existence of the row.
        success=True,
        tx_sender=_sender_of(members, wallet),
        transfers=tuple(legs),
        context=AttributionContext(),
    )


def _timestamp_of(members):
    """UTC **seconds** for a group, from the earliest fill's millisecond ``time``.

    Milliseconds are floored to seconds because ``contracts`` carries UTC seconds everywhere. That
    loses sub-second ordering between two transactions in the same second, and it is worth naming:
    it is not recoverable later, and ``pipeline.run`` cannot use it to order anything because it
    orders by ``(block_number, tx_hash)`` and this source carries no block number.
    """
    times = [fill.get("time") for fill in members if isinstance(fill.get("time"), int)]
    if not times:
        raise MalformedFill(
            "no fill in this group carries an integer 'time'; a transaction with no position in "
            "time cannot be placed in a §6.3 window or measured over a §4.4 horizon"
        )
    return min(times) // 1000


def _sender_of(members, wallet):
    """The wallet when every fill in the group crossed; the unnamed submitter otherwise."""
    if all(fill.get("crossed") is True for fill in members):
        return wallet
    return unknown_submitter()


# -- assembling a run's inputs --------------------------------------------------


def observed_window(decoded, index=0):
    """A :class:`pipeline.inputs.Window` over ``decoded``, ending 30 days before its last fill.

    **Not the full span of the data, and the reason is a rule the machine enforced rather than one
    this module chose.** An earlier version of this function returned ``[min_ts, max_ts]`` and
    :func:`window_config` set the horizon to ``end_ts``; ``pipeline.run`` refused the whole
    configuration on the first contact with real data::

        the marking horizon is ts 1784671328 but window 0 ends at ts 1784671328, so a buy at the
        window's last second gets 0 of its 30 days

    §4.8 runs the measurement to 30 days past the window's end *for every sample*, and forbids both
    dropping the late sample and using its partial return — so the only configuration that is not a
    lie is one where the data itself funds the tail. The window therefore ends
    ``MEASUREMENT_HORIZON_SECONDS`` before the last observed fill, and everything after that edge is
    the §4.8 measurement tail: those sells still match against lots opened inside the window, and a
    buy among them opens a lot without being scored, because it belongs to the next window.

    Both block edges are :data:`BLOCK_NUMBER_NOT_CARRIED`, matching the transactions, so
    ``Window.contains`` reduces to its timestamp test. That is the honest shape and not a trick: the
    window has no block extent because the source reports no blocks.

    :raises ValueError: when the decode is empty, or spans less than 30 days. A recording shorter
        than the horizon cannot give a single buy its full measurement, and the honest answer is
        that this window is not measurable — not a window quietly narrowed to nothing.
    """
    stamps = [item.timestamp for item in decoded.transactions] + [
        item.timestamp for item in decoded.undecodable
    ]
    if not stamps:
        raise ValueError(
            "cannot build a window over a decode that produced no transactions at all; there is no "
            "start and no end to state, and a window invented around an empty set would define the "
            "population rather than describe it"
        )
    first, last = min(stamps), max(stamps)
    end_ts = last - MEASUREMENT_HORIZON_SECONDS
    if end_ts < first:
        raise ValueError(
            "these fills span {} seconds ({} to {}) and §4.8 measures every buy over the following "
            "{} seconds, so a window over them would have to end at ts {} — before it starts. There "
            "is no sample here that could be given its full 30 days, and narrowing the window to "
            "the empty set would report 'no scored buys' as though it were a measurement rather "
            "than a window too short to make one. Capture a longer userFillsByTime "
            "window.".format(
                last - first, first, last, MEASUREMENT_HORIZON_SECONDS, end_ts,
            )
        )
    return Window(
        index=index,
        start_block=BLOCK_NUMBER_NOT_CARRIED,
        start_ts=first,
        end_block=BLOCK_NUMBER_NOT_CARRIED,
        end_ts=end_ts,
    )


def window_config(window):
    """A :class:`pipeline.inputs.WindowConfig` whose §4.7 and migration mappings are **empty**.

    Empty is the finding, not an omission. §4.7's token trading start is "first usable liquidity
    plus one real swap" and a migration is liquidity moving between pools; neither event exists on
    an order book, and :data:`NOT_APPLICABLE` says so at length. Supplying a fabricated start would
    file every buy in a §4.7 age bucket derived from a different phenomenon — and supplying none
    makes ``pipeline.run`` quarantine the buy as unknown-age, which is the loud outcome instead.

    The marking horizon is exactly 30 days past the window's end, which is what §4.8 requires and
    what :func:`observed_window` sized the window to afford. ``horizon_block`` equals the window's
    end block because both are :data:`BLOCK_NUMBER_NOT_CARRIED`; ``_require_a_measurable_horizon``
    checks that the horizon does not *precede* the window in the block dimension, and equality
    satisfies it. A horizon block invented to look later would be the fabricated ordering
    :data:`BLOCK_NUMBER_NOT_CARRIED` exists to refuse.
    """
    return WindowConfig(
        horizon_block=window.end_block,
        horizon_ts=window.end_ts + MEASUREMENT_HORIZON_SECONDS,
        token_starts={},
        replacement_pools={},
    )


def run_inputs(decoded, index=0):
    """The five arguments of ``pipeline.run_wallet_window``, with two of them deliberately empty.

    :returns: ``(transactions, pools, prices, window, config)``.

    ``pools`` and ``prices`` are ``{}``, and that is the whole result of this exercise stated as
    data. There is no pool to snapshot and no §4.6 quote asset to price against; see
    :data:`NOT_APPLICABLE` for both, at length.

    **What the machine actually does with it, measured rather than argued.** Both routes below are
    run in ``tests/hyperliquid/test_pipeline_contact.py`` against the committed recording, and an
    earlier version of this paragraph asserted a third thing that turned out to be false — it said
    every position is *quarantined for want of a pool*. Nothing reaches marking at all:

    * **as this module hands it over** (an empty ``AttributionContext``, which is how a caller says
      nothing is known): ``run_wallet_window`` runs all five stages, the census counts all 235
      transactions, and attribution reports ``unresolved_rate = 1`` — every one is ``UNSUPPORTED``,
      excluded before netting. That is :data:`NOT_APPLICABLE`'s "§4.1 attribution" entry confirmed
      by running it: the venue already answered the ownership question, so §4.1 has no logs, no
      router, no Safe and no UserOperation to reason from, and it says so instead of assuming.
    * **with the maximum charity a caller could extend** — the wallet declared an EOA and
      ``permit_tx_sender_fallback`` on — attribution resolves all 235 and calls all 235 usable, and
      then **netting** classifies every one of them ``NO_CLEAR_ENDPOINT``. 0 buys, 0 sells, 0
      wallets, 0 scored. This is the deeper barrier and the honest one: a trade's endpoint is a §4.6
      quote asset, ``contracts.QUOTE_ASSETS`` is a frozen whitelist of four Ethereum Mainnet
      addresses, and no Hyperliquid token is any of them.

    So the queue is empty, the coverage report reads ``transactions_unpriced = 235`` and
    ``notional_usd_total = 0``, and **no §4 number is available from this source by either route**.
    The way to know that is to run it, which is why this function exists at all: the defence against
    a §4 number coming out of Hyperliquid is not a lock, it is that there is no such number in the
    data, demonstrated end to end.

    A caller who wants a number from this data has to supply a pool book and a price book of their
    own, and this function will not help them do it silently: the two empty mappings are returned
    positionally, so substituting one is a visible edit at the call site rather than a keyword
    default nobody reads. Substituting a *§4.6* one is refused outright — see
    :func:`tools.hyperliquid.provenance.audit_no_mainnet_assets`.
    """
    transactions = tuple(decoded.transactions) + tuple(decoded.undecodable)
    window = observed_window(decoded, index=index)
    return transactions, {}, {}, window, window_config(window)


# -- the leaderboard ------------------------------------------------------------


def leaderboard_addresses(payload):
    """The ``ethAddress`` of every leaderboard row, in order, validated.

    **This is the point at which the vendor's numbers are read, and they are not returned.**
    A row carries ``windowPerformances`` — the venue's own pnl, roi and volume per period — and §3
    forbids a vendor-computed return from being the metric; the whole design rebuilds the metric
    from raw trades. So this function's return type is the answer to the temptation: addresses and
    nothing else. ``windowPerformances`` cannot be an input to anything scored here because it does
    not leave this function.

    The one legitimate use of this endpoint is deciding *which wallets to pull fills for*. That is
    a selection, and a selection made on a vendor's performance number is a **biased** selection —
    every wallet here is on a leaderboard, so the sample is of active, surviving, high-volume
    traders and of nobody else. Whoever samples from it owns that bias; this function only refuses
    to hand the number along.

    :raises MalformedAddress: on a row whose ``ethAddress`` is not a 20-byte address, naming the
        row's position. Raised rather than skipped: a leaderboard row is a sampling input, not a
        population being counted, so there is no census for it to go missing from — and a silently
        skipped row makes the sample a function of which rows this reader happened to like.
    :raises ValueError: when the payload has no ``leaderboardRows``.
    """
    if not isinstance(payload, Mapping) or not isinstance(payload.get("leaderboardRows"), list):
        raise ValueError(
            "leaderboard payload must be an object with a 'leaderboardRows' list, got {}".format(
                type(payload).__name__
            )
        )
    found = []
    for position, row in enumerate(payload["leaderboardRows"]):
        if not isinstance(row, Mapping):
            raise ValueError(
                "leaderboard row {} is a {}, not an object".format(position, type(row).__name__)
            )
        found.append(
            require_real_address(
                row.get("ethAddress"), "leaderboard row {}'s ethAddress".format(position)
            )
        )
    return tuple(found)
