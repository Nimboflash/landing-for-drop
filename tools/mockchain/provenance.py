"""Where the synthetic marker lives, and what it does and does not guarantee.

The rule this module exists to hold: **a synthetic run must be impossible to mistake for a
measurement.** The obvious way to do that is a boolean — ``synthetic=True`` on some record — and
it is the wrong way, for one reason: a flag is a field, fields are dropped by every join,
projection and serialization step between here and a published artifact, and the record that
loses it looks exactly like a record that never had it.

So there is no flag. The marker is carried in the **identifiers themselves**.

What the seam actually carries end to end
-----------------------------------------

Reading ``src/contracts/`` and ``src/pipeline/inputs.py`` for a value that survives attribution,
netting, FIFO, marking, scoring and reporting, exactly one class of value does: the **address and
hash strings**. ``contracts.Transfer.__post_init__`` lowercases ``token``/``from_addr``/``to_addr``
and collapses the native-ETH sentinel onto WETH; ``pipeline.ObservedTransaction.__post_init__``
strips and lowercases ``tx_hash`` and normalises ``tx_sender``; ``contracts.normalise_asset``
lowercases and collapses the sentinel; ``attribution.normalise_address`` strips and lowercases.
That is the whole of what the seam does to an identifier — no truncation, no re-encoding, no
checksum. A lowercase, unpadded, non-sentinel string therefore arrives at the far end byte for
byte, and it arrives there as the *key everything is grouped by*: the netting owner, the FIFO lot
book's ``(owner, asset)``, the marked pool's ``asset``, ``BuyQuality.wallet``,
``reporting.wallet.WalletReport.wallet``, ``reporting.churn.ChurnReport.states``, and from there
into ``contracts.canonicalise`` and the payload hash ``reporting.run_artifact`` records.

So every identifier this generator mints begins ``0xsynthetic-``. ``synthetic`` is not hexadecimal
— ``s``, ``y``, ``n``, ``t``, ``i`` are not hex digits, and neither is the ``-`` — so a minted
address is the same *length* as an Ethereum address and provably is not one. Nothing can collide
with a real address, and nothing has to consult a registry to tell the two apart.

Why that is indelible in the only sense that matters
----------------------------------------------------

The marker is not attached to the value; it **is** part of the value. Removing it does not yield
"the same run without a label" — it yields a different wallet, a different token, a different pool
and a different transaction. The lot book regroups, the pool lookup misses or hits a different
entry, the census keys change, and the published payload hashes to something else.
``tests/mockchain/test_marker_cannot_be_stripped.py`` performs each of those rewrites and pins
that outcome, because "indelible" is worth nothing as an adjective.

**What this does not guarantee, stated rather than claimed away.** Four residues, all measured:

* ``object.__setattr__`` rewrites a field of any Python object, so a
  :class:`reporting.wallet.WalletReport` assembled from a synthetic run can have its ``wallet``
  rewritten to a bare hex address after the fact. No class in Python can prevent that, and
  ``reporting.run_artifact`` re-verifies only the diagnostics pack. That is exactly why
  :func:`publish_synthetic_artifact` exists: it re-reads the *payload that is about to be hashed*
  and refuses one whose addresses are not marked. It is a publication-time check on the bytes,
  not a trust in the objects.
* **The four §4.6 quote assets are necessarily real.** ``contracts.QUOTE_ASSETS`` is a frozen
  whitelist of WETH/USDC/USDT/WBTC and ``netting._usd_value`` short-circuits every other token to
  ``None``, so a synthetic run that minted its own quote asset would produce no priced trade and
  therefore no metric at all. The quote leg of every synthetic trade is a real mainnet address,
  and :data:`PERMITTED_UNMARKED` is the list, spelled out so the exception is auditable rather
  than incidental. Everything that identifies *whose* trade it was, and *what* was traded, is
  marked.
* **Two seam types carry no string at all.** ``pipeline.inputs.Window`` and
  ``pipeline.inputs.TokenStart`` hold only ints. There is nothing on them to mark. Their keys are
  marked (``token_starts`` is keyed by the synthetic token), which is the same asymmetry
  ``pipeline.inputs.asset_keyed`` already records for ``TokenStart``: the key can be checked, the
  value states nothing about itself.
* **The marker says "synthetic". It does not say "harmless".** A synthetic run can still compute
  a wrong number; what it cannot do is publish one that reads as a measurement of the chain.

The snapshot identifier
-----------------------

:func:`snapshot_id` names itself on its face — ``SYNTHETIC-mockchain-…-NOT-A-MEASUREMENT`` — so
every ``phase0.runs.RunRecord`` and every audit entry that quotes ``dataset_snapshot`` says so
without anyone having to look it up. :func:`is_synthetic_snapshot` is the predicate governance
would need; see :mod:`tools.mockchain.governance` for where that refusal belongs.
"""

import hashlib

from contracts import NATIVE_ETH, QUOTE_ASSETS

#: The marker itself, lowercase because every identifier the seam handles is lowercased and a
#: marker that did not survive ``str.lower()`` would be gone before netting.
MARKER = "synthetic"

#: Prefix of every minted identifier. ``0x`` so it slots wherever an address or a hash goes;
#: ``synthetic-`` so it is the same width as one and cannot be parsed as one.
IDENTIFIER_PREFIX = "0x" + MARKER + "-"

#: Version tag mixed into every digest. Changing it changes every identifier, which is the point:
#: two generator versions must not mint the same address for the same label.
STREAM = "mockchain-v1"

#: ``0x`` plus 40 hex digits. Minted identifiers are the same width so they are drop-in, and the
#: same width is what makes "this is not hexadecimal" the only difference.
ADDRESS_WIDTH = 40

#: ``0x`` plus 64 hex digits.
TX_HASH_WIDTH = 64

#: How much of a label survives into the identifier before the digest takes over. Bounded so the
#: digest always gets at least 11 characters of an address, which is 44 bits of collision margin —
#: and :func:`tools.mockchain.chain.generate_chain` asserts uniqueness anyway rather than trusting
#: the margin.
SLUG_WIDTH = 18

#: Addresses a synthetic run may legitimately carry unmarked, and the whole list. §4.6 restricts
#: USD conversion to four liquid quote assets and ``contracts.QUOTE_ASSETS`` is a frozen whitelist,
#: so a synthetic quote asset would be priced by nothing and no trade would ever be valued. The
#: native-ETH sentinel is here because §4.2 collapses it onto WETH before anything downstream sees
#: it — it can appear in a generated ``Transfer`` argument and never in a generated result.
PERMITTED_UNMARKED = frozenset(QUOTE_ASSETS | {NATIVE_ETH})

#: What the run report's ``chain`` field says. §11.1 selected Ethereum Mainnet; this ran on
#: nothing, and a report that said "ethereum" would be the exact confusion this module prevents.
SYNTHETIC_CHAIN = "synthetic-mockchain-v1"

#: Prefix of a synthetic dataset snapshot identifier.
SNAPSHOT_PREFIX = "SYNTHETIC-"

#: Suffix, so the string says what it is at both ends and a truncated log line still shows one.
SNAPSHOT_SUFFIX = "-NOT-A-MEASUREMENT"


class SyntheticProvenanceLost(Exception):
    """A synthetic artifact reached publication without its provenance intact.

    Deliberately not a :class:`contracts.ContractError`: it is not a finding about the data and it
    is not a quarantine case. It is a defect in whatever assembled the artifact — or a deliberate
    rewrite — and the only safe response is to publish nothing.
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

    Readable on purpose. An operator staring at a quarantine record or a canonical JSON payload
    should be able to see *which* synthetic wallet it is without decoding a hash.
    """
    out = []
    for character in str(label).lower():
        out.append(character if character.isalnum() and character.isascii() else "-")
    return "".join(out)[:SLUG_WIDTH].strip("-") or "x"


def _mint(label, width):
    body = "{}-{}-{}".format(MARKER, _slug(label), _digest("id", str(label)))
    if len(body) < width:
        raise ValueError(
            "identifier body for {!r} is {} characters and {} are needed; the digest is 64 "
            "characters so this is unreachable for the two widths this module mints".format(
                label, len(body), width
            )
        )
    return "0x" + body[:width]


def synthetic_address(label):
    """A 42-character identifier that is the width of an address and is not one.

    Lowercase and unpadded, so ``contracts.normalise_asset`` and ``attribution.normalise_address``
    return it unchanged; never equal to :data:`contracts.NATIVE_ETH`, so §4.2's collapse does not
    touch it; never in ``contracts.QUOTE_ASSETS``, so ``netting`` never asks a price book for it.
    """
    return _mint(label, ADDRESS_WIDTH)


def synthetic_tx_hash(label):
    """A 66-character identifier that is the width of a transaction hash and is not one."""
    return _mint(label, TX_HASH_WIDTH)


def is_synthetic_identifier(value):
    """True for an identifier this module minted, and for nothing else.

    A prefix test rather than a substring test: ``"0x…synthetic…"`` buried in the middle of an
    otherwise real-looking address would be a string that *mentions* the marker, which is not the
    same claim as an identifier that *is* synthetic.
    """
    return isinstance(value, str) and value.startswith(IDENTIFIER_PREFIX)


def snapshot_id(seed):
    """The dataset snapshot identifier for a run at ``seed``. It names itself synthetic.

    Every ``phase0.runs.RunRecord`` stores this verbatim and every ``run.open`` audit entry quotes
    it, so the run record and the hash-chained log both say what the run was over without anyone
    having to consult a second file. The seed is in the string because a synthetic run's dataset
    *is* its seed — there is nothing else to pin.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError(
            "seed must be an int; the snapshot identifier is the only record of what a synthetic "
            "run was over, and a float seed would not reproduce it. Got {}.".format(
                type(seed).__name__
            )
        )
    return "{}{}-seed-{}-{}{}".format(
        SNAPSHOT_PREFIX, STREAM, seed, _digest("snapshot", str(seed))[:12], SNAPSHOT_SUFFIX
    )


def is_synthetic_snapshot(value):
    """True when a dataset snapshot identifier declares itself synthetic."""
    return isinstance(value, str) and value.startswith(SNAPSHOT_PREFIX)


def run_id(seed):
    """The run identifier a synthetic report carries. Marked, because it reaches the payload."""
    return "{}{}-run-seed-{}".format(SNAPSHOT_PREFIX, STREAM, seed)


# -- the publication-time check -------------------------------------------------


def addresses_in(payload):
    """Every address-shaped string in an already-canonicalised payload, deduplicated and sorted.

    Address-shaped means "starts with ``0x``", which is deliberately looser than "is 42 characters
    of hex": a tampered payload is exactly the case where the string will not be well formed, and
    a check that only looked at well-formed addresses would wave through the malformed one.
    """
    found = set()

    def walk(value):
        if isinstance(value, str):
            if value.startswith("0x"):
                found.add(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(key)
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(payload)
    return tuple(sorted(found))


def audit_payload_provenance(payload):
    """Refuse a canonicalised payload whose synthetic provenance is not intact.

    Two refusals, and neither subsumes the other:

    * **an unmarked address.** Every address-shaped string must either be one this module minted
      or be on :data:`PERMITTED_UNMARKED`. This is what catches a post-construction rewrite: the
      check reads the bytes that are about to be hashed, not the objects that produced them.
    * **no marked address at all.** A payload carrying zero synthetic identifiers passes the first
      rule vacuously, and "vacuously clean" is precisely how a check like this stops working. A
      synthetic run has wallets in its basket and its churn block; a payload with none of them is
      not a synthetic run's payload.

    :returns: the tuple of addresses found, so a caller can record what it published.
    :raises SyntheticProvenanceLost: on either condition, naming the offending strings.
    """
    addresses = addresses_in(payload)
    unmarked = tuple(
        address for address in addresses
        if not is_synthetic_identifier(address) and address not in PERMITTED_UNMARKED
    )
    if unmarked:
        raise SyntheticProvenanceLost(
            "this artifact was produced by a synthetic run but {} address(es) in the payload "
            "about to be hashed carry no synthetic marker: {}. Every identifier a synthetic "
            "source mints begins {!r}; the only addresses permitted without it are the four §4.6 "
            "quote assets and the native-ETH sentinel ({}), because contracts.QUOTE_ASSETS is a "
            "frozen whitelist and a minted quote asset would be priced by nothing. An unmarked "
            "address here means either the payload was rewritten after the run — "
            "object.__setattr__ rewrites a field of any Python object and reporting.run_artifact "
            "re-verifies only the diagnostics pack — or the source stopped marking. Publishing "
            "nothing: an artifact that has lost its provenance is indistinguishable from a "
            "measurement, which is the one thing this instrument exists to prevent.".format(
                len(unmarked),
                ", ".join(repr(a) for a in unmarked),
                IDENTIFIER_PREFIX,
                ", ".join(sorted(PERMITTED_UNMARKED)),
            )
        )
    if not any(is_synthetic_identifier(address) for address in addresses):
        raise SyntheticProvenanceLost(
            "this artifact was produced by a synthetic run and carries no synthetic identifier at "
            "all ({} address-shaped string(s) found). The unmarked-address rule above is "
            "satisfied vacuously by such a payload, so it is checked separately: a synthetic run "
            "puts its wallets in the §10 basket and its churn block, and a payload with none of "
            "them is not this run's payload.".format(len(addresses))
        )
    return addresses


def publish_synthetic_artifact(report):
    """``reporting.run_artifact``, with the provenance of the hashed bytes checked first.

    This is the only route by which a synthetic run may produce an artifact, and the check is here
    rather than at assembly for the reason ``reporting.run.run_artifact`` gives about its own
    diagnostics check: the rewrite that matters lands *after* a report has been assembled, so a
    check that ran only at assembly closes the window that does not matter.

    What it guarantees: the payload that was hashed carried a synthetic marker on every
    identifier that is not a §4.6 quote asset. What it does not: that the numbers are right, that
    the report is complete, or that a caller who bypasses this function and calls
    ``reporting.run_artifact`` directly is stopped — nothing in ``src/`` knows this rule, which is
    the governance gap :mod:`tools.mockchain.governance` records.
    """
    from reporting import run_artifact

    envelope = run_artifact(report)
    audit_payload_provenance(envelope["payload"])
    return envelope
