"""The hash, verified before anything is allowed to depend on it.

``pipeline.keccak`` is the first hash function in this tree, and it exists for one reason: a
CREATE2 pool address is a function of the token pair, so it cannot be a literal the way every event
topic here is. That makes it the one place where a wrong implementation is invisible — keccak does
not fail loudly, it returns 32 plausible bytes, and an address derived from them is a well-formed
address that no pool is at. A run would then report ``no_pool_on_covered_factories`` for every token
on earth and look like a coverage problem.

So it is checked from two directions before use, and this file is that check.

**Against the standard library, at every length.** ``pipeline.keccak.sha3_256`` is the same sponge
with SHA-3's domain byte, and ``hashlib.sha3_256`` is an implementation this repository did not
write. Comparing them over every input length from 0 to 400 bytes crosses the 136-byte rate
boundary three times, so it exercises single-block and multi-block absorption, the ordinary padding
case and the one where the pad byte lands on the last byte of a full block. That covers the
permutation, the absorption and the padding — everything the two functions share.

**Against the constants this repository already committed to.** Every topic in ``ingest.events``
and ``pipeline.tokenstart`` is keccak-256 of the canonical signature text written beside it, and
each was pinned against a real log or a block explorer before this module existed. Recomputing them
is the check on the one thing hashlib cannot see — the domain byte — and every one of them is a
value a reader can look up independently.

What this file does **not** do: change a single constant in ``ingest.events``. That module writes
its topics as literals and says why, ``tools/case_survey.py`` says the same, and those reasons are
about topics rather than about addresses. The literals stay literals; this file only proves they
are what they claim to be.
"""

import hashlib

import pytest

from ingest import events
from pipeline import tokenstart
from pipeline.keccak import (
    DIGEST_BYTES,
    KECCAK_PAD,
    RATE_BYTES,
    SHA3_PAD,
    event_topic,
    function_selector,
    keccak256,
    keccak256_hex,
    sha3_256,
)
from ingest.tokens import DECIMALS_SELECTOR

#: Published keccak-256 digests. Not derived from anything in this repository — the first is the
#: empty-input digest quoted in every Ethereum client, and the other two are the standard Keccak
#: test vectors.
KNOWN_DIGESTS = (
    (b"", "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"),
    (b"abc", "0x4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"),
    (b"The quick brown fox jumps over the lazy dog",
     "0x4d741b6f1eb29cb2a9b9911c82f56fa8d73b04959d3d9d222895df6c0b28aa15"),
)

#: The two ERC-1155 topics ``ingest.events`` measured and deliberately did not admit. Their
#: canonical texts live in that module's comments rather than in a ``Signature``, so they are
#: written out here — the same texts, copied, and the assertion is that they hash to the committed
#: constants.
DECLINED_TEXTS = {
    "TransferSingle(address,address,address,uint256,uint256)": events.TRANSFER_SINGLE,
    "TransferBatch(address,address,address,uint256[],uint256[])": events.TRANSFER_BATCH,
}

#: ``pipeline.tokenstart``'s four topics, whose comments carry the same canonical texts. These were
#: established by reading a factory's logs with no topic filter and taking what came back — an
#: observation, and this is the independent confirmation of it.
TOKENSTART_TEXTS = {
    "PairCreated(address,address,address,uint256)": tokenstart.PAIR_CREATED,
    "PoolCreated(address,address,uint24,int24,address)": tokenstart.POOL_CREATED,
    "Mint(address,uint256,uint256)": tokenstart.MINT_V2,
    "Mint(address,address,int24,int24,uint128,uint256,uint256)": tokenstart.MINT_V3,
}

#: The longest input this module is asked to hash in production is the 96-byte v3 salt preimage,
#: and the shortest is a 40-byte pair. 400 covers all of that and three rate boundaries besides.
CROSS_CHECK_LENGTHS = 400


def _sample(length):
    """A deterministic byte string of the given length, with no period that divides the rate."""
    return bytes((index * 7 + 11) % 251 for index in range(length))


# -- the published answers -------------------------------------------------------


@pytest.mark.parametrize("data,expected", KNOWN_DIGESTS)
def test_a_published_digest_is_reproduced(data, expected):
    assert keccak256_hex(data) == expected
    assert len(keccak256(data)) == DIGEST_BYTES


def test_the_two_domain_bytes_are_the_only_difference_and_they_do_differ():
    """If these agreed, the hashlib cross-check below would be checking keccak against keccak."""
    assert KECCAK_PAD != SHA3_PAD
    assert keccak256(b"abc") != sha3_256(b"abc")
    assert sha3_256(b"abc") == hashlib.sha3_256(b"abc").digest()


# -- against the standard library, at every length -------------------------------


def test_the_sponge_agrees_with_hashlib_at_every_length_to_400():
    """The permutation, the absorption and both padding cases, against an outside implementation."""
    mismatches = [
        length for length in range(CROSS_CHECK_LENGTHS + 1)
        if sha3_256(_sample(length)) != hashlib.sha3_256(_sample(length)).digest()
    ]
    assert mismatches == [], (
        "sha3_256 disagrees with hashlib at input length(s) {}. The two share a permutation, a "
        "rate and a padding rule, so a disagreement is a defect in this module's Keccak-f, its "
        "absorption or its padding — all of which keccak256 also uses.".format(mismatches)
    )


@pytest.mark.parametrize("length", [
    RATE_BYTES - 2, RATE_BYTES - 1, RATE_BYTES, RATE_BYTES + 1, 2 * RATE_BYTES,
])
def test_the_rate_boundary_is_handled(length):
    """Called out separately because ``len(data) % 136 == 135`` and ``== 0`` are the two cases a
    padding implementation gets wrong: the first leaves no room for the closing bit in the same
    block as the pad byte, the second needs a whole extra block."""
    assert sha3_256(_sample(length)) == hashlib.sha3_256(_sample(length)).digest()


# -- against the topics this repository already committed to ----------------------


@pytest.mark.parametrize("signature", sorted(events.SIGNATURES.values(), key=lambda s: s.topic))
def test_every_admitted_topic_is_the_keccak_of_its_own_signature_text(signature):
    assert event_topic(signature.text) == signature.topic, (
        "{} is committed as {} and keccak-256 of {!r} is {}. Either the hash is wrong or the topic "
        "is, and both matter: a wrong topic decodes the wrong event and a wrong hash derives the "
        "wrong pool address.".format(
            signature.name, signature.topic, signature.text, event_topic(signature.text)
        )
    )


@pytest.mark.parametrize("text,topic", sorted(DECLINED_TEXTS.items()))
def test_every_declined_topic_is_the_keccak_of_its_own_signature_text(text, topic):
    """The two ERC-1155 events are refused rather than decoded, and are still checked here.

    A constant nothing decodes is a constant nothing would notice being wrong, and it is named in
    ``ingest.events`` precisely so the decision to decline is legible in code.
    """
    assert event_topic(text) == topic


@pytest.mark.parametrize("text,topic", sorted(TOKENSTART_TEXTS.items()))
def test_every_pool_search_topic_is_the_keccak_of_its_own_signature_text(text, topic):
    assert event_topic(text) == topic


def test_the_curve_crypto_pool_exchange_is_a_different_topic():
    """``ingest.events`` says Curve's crypto pools emit a *different* ``TokenExchange`` whose ids
    are ``uint256``, that it hashes to ``0xb2e76ae9…``, and that it is therefore not admitted by
    the StableSwap entry. That is a claim about a hash, and here is the hash."""
    crypto = event_topic("TokenExchange(address,uint256,uint256,uint256,uint256)")

    assert crypto.startswith("0xb2e76ae9")
    assert crypto != events.TOKEN_EXCHANGE
    assert crypto not in events.SIGNATURES


def test_erc2612_permit_is_not_the_permit2_permit():
    """The other collision ``ingest.events`` names: two events called ``Permit``, one topic each."""
    erc2612 = event_topic("Permit(address,address,uint256,uint256,uint8,bytes32,bytes32)")

    assert erc2612 != events.PERMIT2_PERMIT
    assert erc2612 not in events.SIGNATURES


def test_the_two_swap_signatures_share_only_a_name():
    assert event_topic("Swap(address,uint256,uint256,uint256,uint256,address)") == events.SWAP_V2
    assert (event_topic("Swap(address,address,int256,int256,uint160,uint128,int24)")
            == events.SWAP_V3)
    assert events.SWAP_V2 != events.SWAP_V3


def test_the_count_of_constants_this_file_reproduces():
    """The verification stated as a number, because "verified" is an adjective and this is not.

    Twelve topics committed in ``ingest.events`` — ten in ``SIGNATURES`` and the two ERC-1155
    events it declined — plus the four ``pipeline.tokenstart`` reads factories with.
    """
    assert len(events.SIGNATURES) == 10
    assert len(DECLINED_TEXTS) == 2
    assert len(TOKENSTART_TEXTS) == 4

    reproduced = {signature.text: signature.topic for signature in events.SIGNATURES.values()}
    reproduced.update(DECLINED_TEXTS)
    reproduced.update(TOKENSTART_TEXTS)

    assert len(reproduced) == 16, "a text appearing twice would make one check two"
    assert all(event_topic(text) == topic for text, topic in reproduced.items())


# -- guard the guard -------------------------------------------------------------


def test_a_broken_permutation_would_be_caught(monkeypatch):
    """A check that cannot fail is theatre.

    One round constant is perturbed by a single bit — the smallest defect the permutation can carry
    — and every claim above has to break: the published digests, the hashlib cross-check and the
    topics. If any of them survived, it would be checking something other than this hash.
    """
    from pipeline.keccak import _ROUND_CONSTANTS

    perturbed = (_ROUND_CONSTANTS[0] ^ 0x2,) + _ROUND_CONSTANTS[1:]
    monkeypatch.setattr("pipeline.keccak._ROUND_CONSTANTS", perturbed)

    assert keccak256_hex(b"") != KNOWN_DIGESTS[0][1]
    assert sha3_256(b"abc") != hashlib.sha3_256(b"abc").digest()
    assert event_topic("Transfer(address,address,uint256)") != events.TRANSFER


# -- what the module refuses -----------------------------------------------------


def test_a_str_is_refused_rather_than_encoded():
    """Encoding it here would pick an encoding silently, and the digest depends on which."""
    with pytest.raises(TypeError) as raised:
        keccak256("abc")

    assert "encoding" in str(raised.value)


@pytest.mark.parametrize("text", [
    "Transfer(address, address, uint256)",   # the canonical form has no spaces
    "Transfer(address,address,uint256",      # unclosed
    "Transfer",                              # no parameter list at all
    "(address,address)",                     # no name
    "Tränsfer(address)",                     # not ASCII
])
def test_a_signature_that_is_not_canonical_is_refused(text):
    """Any string hashes to something, so a malformed signature yields a well-formed topic that
    matches no log ever emitted. That is the failure this refusal exists to prevent."""
    with pytest.raises(ValueError):
        event_topic(text)


def test_the_space_refusal_is_not_pedantry():
    """The two spellings really are different topics, which is why one of them is refused."""
    spaced = keccak256_hex(b"Transfer(address, address, uint256)")

    assert spaced != events.TRANSFER


# -- the four-byte half of the same hash -----------------------------------------


def test_a_selector_reproduces_a_constant_this_repository_already_committed_to():
    """``ingest.tokens`` writes ``decimals()``'s selector out as a literal and says why — that
    package holds no keccak. This one does, and it agrees, which is what makes it safe to derive
    the pool probes' selectors instead of writing four more bytes nobody can eyeball."""
    assert function_selector("decimals()") == DECIMALS_SELECTOR


@pytest.mark.parametrize("text,expected", [
    ("totalSupply()", "0x18160ddd"),
    ("balanceOf(address)", "0x70a08231"),
    ("getReserves()", "0x0902f1ac"),
    ("slot0()", "0x3850c7bd"),
    ("token0()", "0x0dfe1681"),
    ("token1()", "0xd21220a7"),
])
def test_a_selector_is_the_first_four_bytes_of_the_topic(text, expected):
    """Six selectors a reader can check on a block explorer's "Read Contract" tab. Four of the six
    — ``balanceOf``, ``slot0``, ``token0``, ``token1`` — are literals ``tools/case_runs.py`` reads
    real pools with, so this is a check against a spelling already in use rather than against
    itself."""
    assert function_selector(text) == expected
    assert event_topic(text).startswith(expected)


def test_a_selector_refuses_exactly_what_a_topic_refuses():
    """One canonical form and one set of refusals. A selector taken from a signature with a space
    in it is four well-formed bytes that call no function."""
    with pytest.raises(ValueError):
        function_selector("transfer(address, uint256)")
    with pytest.raises(ValueError):
        function_selector("totalSupply")
    with pytest.raises(TypeError):
        function_selector(b"totalSupply()")
