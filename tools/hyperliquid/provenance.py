"""Where the Hyperliquid marker lives, and why it cannot live where mockchain's lives.

The rule this module exists to hold is the same one :mod:`tools.mockchain.provenance` holds — **a
run over this source must be impossible to mistake for the pre-registered measurement** — but the
answer cannot be copied, and the reason is worth stating before the code.

Why the mockchain answer does not transfer
------------------------------------------

mockchain makes the marker **the identifier itself**: every address it mints begins
``0xsynthetic-``, so removing the marker does not yield "the same run without a label", it yields a
different wallet. That works because mockchain invents its wallets. This source does not. A
Hyperliquid ``ethAddress`` is a real 20-byte address; it is what a reader checks against
Hyperliquid's own explorer, and rewriting it would destroy the one thing that makes this source
worth having — that the data is real and nobody chose it. So **wallet addresses pass through
verbatim** (lowercased, which is all ``attribution.normalise_address`` does to them anyway), and
the marker has to live somewhere that is not a wallet.

It lives in three places, and each is justified separately below rather than by one gesture.

1. The dataset snapshot identifier
----------------------------------

:func:`snapshot_id` mints ``NOT-PREREGISTERED-hyperliquid-v1-…-NOT-THE-PREREGISTERED-CHAIN``.

``src/phase0/snapshots.py`` already owns a table, :data:`phase0.snapshots.NOT_REAL_PREFIXES`, of the
prefixes by which a snapshot identifier declares itself not a measurement, and its own docstring
frames the claim as "the data behind it was not read off **the thing the experiment is about**".
That sentence describes this source exactly: the bytes are real, they were read off a real venue,
and the venue is not the one §11.1 selected. So ``NOT-PREREGISTERED-`` was added to that table as a
**data change** — one line, no branch of code, and every enforcement point in ``phase0`` picked it
up without being edited. See :mod:`tools.hyperliquid.governance` for what that buys and what it
does not.

The suffix is ``-NOT-THE-PREREGISTERED-CHAIN`` and deliberately **not** mockchain's
``-NOT-A-MEASUREMENT``. This *is* a measurement — of a real order book, at a real time, with real
numbers. Claiming otherwise would be a different false statement, and the reader who saw
``NOT-A-MEASUREMENT`` on data they could check on an explorer would learn to distrust the marker.

2. The asset identifiers
-------------------------

A Hyperliquid spot token is **not** an Ethereum token, and :func:`hyperliquid_asset` mints
``0xhyperliquid-…`` for it. This is not corrupting a real address; it is refusing to invent one.
The refusal is not a matter of taste, and the measurement that settles it is in ``spotMeta`` itself:

    USDC   weiDecimals 8   evmContract.evm_extra_wei_decimals -2   (so 6 on the EVM side)
    PURR   weiDecimals 5   evmContract.evm_extra_wei_decimals +13
    HFUN   weiDecimals 8   evmContract.evm_extra_wei_decimals +10

The same balance is denominated differently on the two sides, so a raw quantity read off a fill is
not a raw quantity of the EVM contract, and ``contracts.Transfer.raw_amount`` is raw units end to
end (§9.2 requires raw quantities to match a hand trace exactly). Filing an HL fill under the
contract address would produce a number that is off by a power of ten and that reconciles against
nothing. And the EVM contract lives on HyperEVM, not on Ethereum Mainnet: HL's USDC token names
``0x6b9e773128f453f5c2c60935ee2de2cbc5390a24``, which is not
``contracts.USDC`` (``0xa0b86991…``) and never was.

There is a sharper consequence, and :func:`audit_no_mainnet_assets` is the guard for it. §4.6
restricts USD conversion to the four addresses in ``contracts.QUOTE_ASSETS``. The one edit that
would make this source appear to produce §4 numbers is a single line mapping HL's ``USDC`` token
onto ``contracts.USDC`` — after which every HL trade prices, every position marks, and the run
publishes a figure about Ethereum Mainnet that was computed from a Hyperliquid order book. That is
the fabrication this module exists to prevent, so it is checked on the bytes rather than trusted:
a decoded payload containing a §4.6 quote address is refused.

3. The counterparty and the unknown submitter
----------------------------------------------

An order book fill names no counterparty — ``userFills`` reports price, size and side, and nobody
to have traded with. :func:`orderbook_counterparty` mints one identifier standing for "the book",
because ``contracts.Transfer`` needs a ``from_addr`` and a ``to_addr`` and there is no real address
to put there. Inventing a plausible hex counterparty would be inventing a market participant.

:func:`unknown_submitter` is the same shape for a different fact. 377 of the 382 fills in the main
committed recording have ``crossed: false`` — our wallet was the *maker*, so the L1 transaction
carrying that fill was submitted by somebody the payload does not name. Amendment A6.1 requires
``tx_sender`` to be recorded alongside the recovered owner and forbids either standing in for the
other; filling ``tx_sender`` with the wallet's own address for a maker fill would be exactly that
substitution, and on this recording it would be asserted for 233 of the 235 decoded transactions.

What this guarantees, and what it does not
-------------------------------------------

It guarantees that a run over this source carries, on the face of its own dataset snapshot
identifier, the claim that it is not the pre-registered chain — in any letter case, wherever the
identifier travels — and that a decoded payload cannot contain a §4.6 quote asset.

It does **not** guarantee:

* **that a wallet address is marked.** It is not, by design. A reader who sees only an address
  cannot tell this run from an Ethereum one; only the snapshot identifier says. That is the price
  of keeping the addresses checkable, and it is paid deliberately.
* **that nothing rewrites the snapshot identifier after the fact.** ``object.__setattr__`` rewrites
  a field of any Python object, and no class in Python can prevent that.
* **that the numbers are right.** The marker says "not the pre-registered chain". It does not say
  "correct", and it does not say "harmless".
* **that a source which does not declare itself is detected.** ``phase0.snapshots`` says the same
  about its own table, and it is still true here: the declaration is a claim the source makes about
  itself.
"""

import hashlib
import re

from contracts import NATIVE_ETH, QUOTE_ASSETS

#: The marker word. Lowercase because every identifier the seam handles is lowercased and a marker
#: that did not survive ``str.lower()`` would be gone before netting.
MARKER = "hyperliquid"

#: Prefix of every identifier this module mints. ``0x`` so it slots wherever an address goes;
#: ``hyperliquid-`` so it is the same width as one and provably is not one — ``h``, ``y``, ``p``,
#: ``r``, ``l``, ``i``, ``q``, ``u`` and ``-`` are not hex digits.
IDENTIFIER_PREFIX = "0x" + MARKER + "-"

#: Version tag mixed into every digest. Changing it changes every minted identifier, which is the
#: point: two decoder versions must not mint the same identifier for the same label.
STREAM = "hyperliquid-v1"

#: ``0x`` plus 40 hex digits. Minted identifiers are the same width so they are drop-in.
ADDRESS_WIDTH = 40

#: How much of a label survives into the identifier before the digest takes over. Bounded so the
#: digest always gets at least 11 characters, which is 44 bits of collision margin — and
#: ``tests/hyperliquid/test_provenance.py`` mints an identifier for every token in the committed
#: ``spotMeta`` and asserts they are distinct rather than trusting the margin.
SLUG_WIDTH = 16

#: The prefix by which a Hyperliquid dataset snapshot declares itself. One row of
#: :data:`phase0.snapshots.NOT_REAL_PREFIXES`; this module conforms to that table rather than
#: owning the rule — ``src/`` may not import ``tools/``, so a predicate defined only here could
#: never have been the authority.
SNAPSHOT_PREFIX = "NOT-PREREGISTERED-"

#: Suffix, so the string says what it is at both ends and a truncated log line still shows one.
#: Not ``-NOT-A-MEASUREMENT``: this is a measurement, of the wrong venue. See the module docstring.
SNAPSHOT_SUFFIX = "-NOT-THE-PREREGISTERED-CHAIN"

#: What a report's ``chain`` field would say for this source. §11.1 selected Ethereum Mainnet and
#: §11.2 pre-registered Arbitrum as the only secondary; a field reading ``"ethereum"`` here would be
#: the exact confusion this module prevents, and one reading ``"arbitrum"`` would be worse — it
#: would claim a diagnostic that *was* pre-registered.
VENUE_CHAIN = "hyperliquid-l1-orderbook"

#: Addresses that must never appear in anything decoded from this source. §4.6 restricts USD
#: conversion to these four, so their presence in a Hyperliquid payload means somebody mapped an HL
#: token onto an Ethereum one — the single edit that would make this source look like it produces
#: §4 numbers. ``NATIVE_ETH`` is included because ``contracts.Transfer`` collapses it onto WETH and
#: a caller could reach WETH by that route without ever typing it.
MAINNET_ASSETS = frozenset(QUOTE_ASSETS | {NATIVE_ETH})

#: ``0x`` plus exactly 40 lowercase hex digits, anchored at both ends.
_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")


class HyperliquidProvenanceLost(Exception):
    """A payload decoded from this source carries an Ethereum Mainnet asset address.

    Deliberately not a :class:`contracts.ContractError`: it is not a finding about the data and it
    is not a quarantine case. It is a defect in whatever assembled the decode — or a deliberate
    rewrite — and the only safe response is to produce nothing.
    """


class MalformedAddress(ValueError):
    """A value that had to be a 20-byte address is not one.

    Raised rather than carried. A wallet address is the one field of this source that is real and
    checkable, and a run that cannot say which wallet a row is about has no row — there is no
    smaller honest answer to fall back to.
    """


def _digest(*parts):
    """SHA-256 over the stream tag and the parts, joined by a separator none of them contains."""
    for part in parts:
        if "|" in part:
            raise ValueError(
                "digest component {!r} contains the field separator '|'; the join would stop "
                "being injective and two different labels could mint one identifier".format(part)
            )
    return hashlib.sha256("|".join((STREAM,) + parts).encode("utf-8")).hexdigest()


def _slug(label):
    """The readable half of an identifier: lowercase, ``[a-z0-9-]`` only, bounded.

    Readable on purpose: an operator staring at a quarantine record should be able to see *which*
    Hyperliquid token it is without decoding a hash.
    """
    out = []
    for character in str(label).lower():
        out.append(character if character.isalnum() and character.isascii() else "-")
    return "".join(out)[:SLUG_WIDTH].strip("-") or "x"


def _mint(label, readable=None):
    """``0x`` + ``MARKER`` + a readable slug + a digest of ``label``, cut to address width.

    ``readable`` separates *what the identifier is derived from* from *what it shows*. Identity
    comes from ``label`` alone, so it is stable; the slug is only there so a person reading a
    quarantine record can tell which thing it is without decoding a hash. Where the two differ —
    :func:`hyperliquid_asset` derives from ``token:<tokenId>`` and shows the bare tokenId — the
    visible half is a string the reader can grep for in the committed ``spotMeta``.
    """
    body = "{}-{}-{}".format(
        MARKER, _slug(label if readable is None else readable), _digest("id", str(label))
    )
    if len(body) < ADDRESS_WIDTH:                              # pragma: no cover - unreachable
        raise ValueError(
            "identifier body for {!r} is {} characters and {} are needed; the digest is 64 "
            "characters so this cannot happen for the one width this module mints".format(
                label, len(body), ADDRESS_WIDTH
            )
        )
    return "0x" + body[:ADDRESS_WIDTH]


def hyperliquid_asset(label):
    """A 42-character identifier for a Hyperliquid-native token: address-width, and not an address.

    ``label`` is the token's ``tokenId`` from ``spotMeta`` — the venue's own identifier for it,
    which is stable across renames in a way the ``name`` is not. Identity is derived from that alone
    for exactly that reason, and the *visible* half of the identifier is the tokenId's leading hex
    rather than the token's name: ``0xhyperliquid-6d1e7cde53ba9467-…`` is a string a reader can grep
    for in the committed ``spotMeta`` to find out which token it is, and a name would have been a
    label that stops being true when the venue renames one.

    Lowercase and unpadded, so ``contracts.normalise_asset`` returns it unchanged; never equal to
    ``contracts.NATIVE_ETH``, so §4.2's collapse does not touch it; never in
    ``contracts.QUOTE_ASSETS``, so ``netting`` never asks a price book for it — **which is why every
    trade decoded from this source is unpriced.** That is the honest outcome and not a defect; see
    :data:`tools.hyperliquid.decode.NOT_APPLICABLE`.
    """
    shown = str(label)
    return _mint("token:{}".format(label), readable=shown[2:] if shown[:2] == "0x" else shown)


def orderbook_counterparty():
    """The stand-in for the party on the other side of a fill, which the payload does not name.

    One identifier for the whole venue rather than one per fill: the payload supports no finer
    claim, and minting a distinct counterparty per fill would manufacture the appearance of
    distinct market participants.
    """
    return _mint("orderbook-counterparty")


def unknown_submitter():
    """The stand-in for the L1 transaction's submitter when the payload does not name it.

    Used for a fill whose ``crossed`` is false — our wallet rested, somebody else crossed, and the
    transaction hash belongs to their submission. Distinct from the wallet's own address on purpose:
    amendment A6.1 forbids ``tx_sender`` and the recovered owner from standing in for each other.
    """
    return _mint("unknown-submitter")


def is_hyperliquid_identifier(value):
    """True for an identifier this module minted, and for nothing else.

    A prefix test rather than a substring test: a string that *mentions* the marker in the middle of
    an otherwise real-looking address is not the same claim as an identifier that *is* minted.
    """
    return isinstance(value, str) and value.startswith(IDENTIFIER_PREFIX)


def require_real_address(value, described):
    """Return ``value`` lowercased, having refused anything that is not a 20-byte address.

    The one place this source's realness is load-bearing. ``ethAddress`` on a leaderboard row and
    ``user`` on a fills request are checked against Hyperliquid's own explorer by any reader who
    doubts a number, so a malformed one is not a smaller measurement — it is a row about nobody.

    Refused rather than carried, and the boundary matters: this is called on values that go *into* a
    request and on the identity of a sampling row, neither of which is a population being counted.
    A fill that cannot be read is a different case and is carried; see
    :func:`tools.hyperliquid.decode.decode_fills`.

    :raises MalformedAddress: naming the value, where it came from, and what shape was required.
    """
    if not isinstance(value, str):
        raise MalformedAddress(
            "{} must be a str and is a {}. Hyperliquid reports addresses as strings and every "
            "consumer of this one — the request body, contracts.Transfer, "
            "attribution.normalise_address — is written for a string.".format(
                described, type(value).__name__
            )
        )
    lowered = value.strip().lower()
    if not _ADDRESS.match(lowered):
        raise MalformedAddress(
            "{} is {!r}, which is not a 20-byte address: expected '0x' followed by exactly 40 hex "
            "digits, got {} character(s). This value is the only part of a Hyperliquid row that a "
            "reader can check against the venue's own explorer, so a malformed one is not a row "
            "with a missing field — it is a row about nobody. Refused rather than repaired: "
            "padding, truncating or checksum-folding it would produce a well-formed address that "
            "identifies a different wallet, or none.".format(described, value, len(lowered))
        )
    return lowered


# -- the dataset snapshot -------------------------------------------------------


def snapshot_id(recording_digest):
    """The dataset snapshot identifier for a run over a given recording. It names itself.

    The digest is in the string because a Hyperliquid run's dataset *is* its recording — the venue's
    ``userFills`` window moves, so "the same request tomorrow" is not the same data, and there is no
    block height to pin instead. Two runs quoting the same snapshot identifier read the same bytes;
    two quoting different ones did not, whatever else their reports agree about.

    :param recording_digest: hex, from :func:`tools.hyperliquid.recording.RecordingCache.digest`.
    :raises ValueError: on a digest that is not lowercase hex, because a snapshot identifier that
        cannot be matched back to a recording pins nothing.
    """
    if not isinstance(recording_digest, str) or not re.match(r"^[0-9a-f]{8,64}$", recording_digest):
        raise ValueError(
            "recording_digest must be 8-64 lowercase hex characters, got {!r}. The digest is the "
            "only record of which bytes a Hyperliquid run was over — the venue's fills window "
            "moves, so the request alone does not identify the data — and an identifier that "
            "cannot be matched back to a recording pins nothing.".format(recording_digest)
        )
    return "{}{}-{}{}".format(SNAPSHOT_PREFIX, STREAM, recording_digest[:16], SNAPSHOT_SUFFIX)


def is_hyperliquid_snapshot(value):
    """True when a dataset snapshot identifier declares itself off the pre-registered chain.

    Case-insensitive, matching :func:`phase0.snapshots.declared_not_real`, which is the authority.
    This is a convenience for callers inside this package, **not** a second rule: a disagreement
    between the two would be a defect here, and ``tests/hyperliquid/test_governance_refusal.py``
    pins them against each other.
    """
    return isinstance(value, str) and value.strip().upper().startswith(SNAPSHOT_PREFIX)


# -- the publication-time check -------------------------------------------------


def addresses_in(payload):
    """Every address-shaped string reachable in ``payload``, deduplicated and sorted.

    Address-shaped means "starts with ``0x``", which is deliberately looser than "is 40 hex digits":
    a tampered payload is exactly the case where the string is not well formed, and a check that
    only looked at well-formed addresses would wave the malformed one through. Walks dataclasses by
    ``__dict__`` as well as containers, because the decoded product is dataclasses.
    """
    found = set()
    seen = set()

    def walk(value):
        if isinstance(value, str):
            if value.startswith("0x"):
                found.add(value)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                walk(key)
                walk(item)
            return
        if isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                walk(item)
            return
        fields = getattr(value, "__dict__", None)
        if isinstance(fields, dict) and id(value) not in seen:
            seen.add(id(value))
            for item in fields.values():
                walk(item)

    walk(payload)
    return tuple(sorted(found))


def audit_no_mainnet_assets(payload):
    """Refuse a payload decoded from this source that carries an Ethereum Mainnet asset address.

    The one refusal that is not vacuous here. Unlike ``tools.mockchain``, this source's addresses
    are *supposed* to be real, so "every address is marked" would be a check that passes by
    construction and protects nothing. What must never appear is one of the four §4.6 quote assets
    or the native-ETH sentinel — their presence means an HL token was filed under an Ethereum
    address, which is the single edit that would make this source appear to produce §4 numbers.

    :returns: the tuple of address-shaped strings found, so a caller can record what it inspected.
    :raises HyperliquidProvenanceLost: naming the offending strings and what each one is.
    """
    addresses = addresses_in(payload)
    offending = tuple(address for address in addresses if address in MAINNET_ASSETS)
    if offending:
        raise HyperliquidProvenanceLost(
            "a payload decoded from Hyperliquid carries {} Ethereum Mainnet asset address(es): {}. "
            "Those are the four §4.6 quote assets and the native-ETH sentinel ({}), and no "
            "Hyperliquid token is any of them — HL's own USDC is token index 0, tokenId "
            "0x6d1e7cde53ba9467b783cb7c530ce054, carried at weiDecimals 8, whose EVM contract "
            "(0x6b9e773128f453f5c2c60935ee2de2cbc5390a24, on HyperEVM and not on Ethereum) uses "
            "two fewer decimals again. Mapping one onto the other is the single edit that makes "
            "this source appear to produce §4 numbers: every trade would price, every position "
            "would mark, and the published figure would be about Ethereum Mainnet while having "
            "been computed from a Hyperliquid order book. Every Hyperliquid asset must carry an "
            "identifier minted by hyperliquid_asset(), which begins {!r} and is provably not "
            "hex.".format(
                len(offending),
                ", ".join(repr(a) for a in offending),
                ", ".join(sorted(MAINNET_ASSETS)),
                IDENTIFIER_PREFIX,
            )
        )
    return addresses
