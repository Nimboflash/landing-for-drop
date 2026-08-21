"""keccak-256, in pure Python, so a pool address can be computed instead of observed.

    keccak256(data) -> bytes
    keccak256_hex(data) -> "0x…" (64 hex digits)
    event_topic("Transfer(address,address,uint256)") -> "0xddf252ad…"
    function_selector("totalSupply()") -> "0x18160ddd"

Why this tree did not have one, and why it now does
---------------------------------------------------

:mod:`ingest.events` writes its topic constants as literals and says why: "computing them would
need a keccak implementation in this package and the constant is what a reader checks against a
block explorer". ``tools/case_survey.py`` says the same thing in its own words. **Those reasons are
about topics and they still stand** — nothing here changes a single constant in that module, and
:mod:`ingest.events` imports nothing from here.

A CREATE2 pool address cannot be a literal, because it is a function of the token pair: the address
of the pool for a token nobody has heard of yet does not exist to be looked up. That is the one
thing in this repository that a hash function is *required* for rather than convenient for, and it
is why :mod:`pipeline.pooladdress` exists and why this module sits under it.

What makes this implementation trustworthy rather than merely present
----------------------------------------------------------------------

A hash function that is subtly wrong does not crash — it returns 32 plausible bytes, and a pool
address derived from them is a well-formed address that is not a pool. So it is verified twice
over, from two directions, before anything uses it:

* **against the standard library, at every length.** :func:`sha3_256` is this same sponge with
  SHA-3's domain byte instead of Keccak's, and ``hashlib.sha3_256`` is a reference implementation
  this repository did not write. ``tests/hand_computed/test_keccak.py`` compares the two over every
  input length from 0 to 400 bytes, which crosses the 136-byte rate boundary three times and so
  exercises multi-block absorption and both padding cases. That check covers the permutation, the
  absorption and the padding — everything except the domain byte;
* **against the topic constants this repository already committed to.** Every constant in
  :mod:`ingest.events` and :mod:`pipeline.tokenstart` is keccak-256 of the canonical signature text
  written beside it, and each was pinned against a real log or a block explorer long before this
  module existed. Recomputing them here is an independent check with an answer a reader can look
  up, and it is the one that pins the domain byte.

The two together are why :mod:`pipeline.pooladdress` may treat a derived address as a fact.

What it does not claim
----------------------

It is not fast — measured at about 0.3 ms per short input on the machine this was written on, which
is nothing against a network call and would be unacceptable in a loop over a block's worth of logs. It is not constant time, and nothing
here should ever hash a secret. It implements exactly one rate (1088 bits / 136 bytes) and one
output width (256 bits); there is no SHAKE, no other Keccak variant, and no incremental update
interface, because the only inputs this repository hashes are a signature text of a few dozen bytes
and a CREATE2 preimage of exactly 85.
"""

#: 64-bit lane mask. Python ints are unbounded, so every rotation and complement must be masked
#: back down or the state silently grows extra high bits that no shift ever clears.
_LANE = (1 << 64) - 1

#: Keccak-f[1600] round constants, FIPS 202 table. Written as literals rather than generated from
#: the LFSR that defines them for the same reason the topics are literals: 24 values a reader can
#: check against the standard, instead of a generator whose own correctness is the question.
_ROUND_CONSTANTS = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)

#: Rotation offsets for ρ, in the order the ρ/π walk visits the lanes.
_RHO = (1, 3, 6, 10, 15, 21, 28, 36, 45, 55, 2, 14, 27, 41, 56, 8, 25, 43, 62, 18, 39, 61, 20, 44)

#: Lane destinations for π, in the same order. ``_RHO[i]`` and ``_PI[i]`` describe one step.
_PI = (10, 7, 11, 17, 18, 3, 5, 16, 8, 21, 24, 4, 15, 23, 19, 13, 12, 2, 20, 14, 22, 9, 6, 1)

#: 24 rounds for a 1600-bit state, and 25 lanes of 64 bits. Fixed by the permutation, not by us.
_ROUNDS = 24
_LANES = 25

#: The sponge rate for a 256-bit capacity-512 sponge: 1088 bits. Both Keccak-256 and SHA3-256 use
#: it, which is what lets one function serve both and lets ``hashlib`` check this one.
RATE_BYTES = 136

#: Digest width. 32 bytes — this module offers no other.
DIGEST_BYTES = 32

#: The domain-separation byte, and the *only* difference between the two functions below.
#:
#: Ethereum uses original Keccak (``0x01``); SHA-3 as standardised appends two domain bits first
#: and so pads with ``0x06``. Same permutation, same rate, same everything else — which is exactly
#: what makes ``hashlib.sha3_256`` a usable reference for the parts these two share, and why the
#: topic constants are needed to pin the part they do not.
KECCAK_PAD = 0x01
SHA3_PAD = 0x06


def _rotl(value, count):
    return ((value << count) | (value >> (64 - count))) & _LANE


def _keccak_f1600(state):
    """The permutation, in place, on 25 little-endian 64-bit lanes."""
    for round_index in range(_ROUNDS):
        # θ — parity of each column, folded back into every lane of the two neighbouring columns.
        parity = [
            state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
            for x in range(5)
        ]
        delta = [parity[(x + 4) % 5] ^ _rotl(parity[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(0, _LANES, 5):
                state[x + y] ^= delta[x]

        # ρ and π — one walk: rotate each lane by its offset and move it to its destination.
        carried = state[1]
        for step in range(24):
            target = _PI[step]
            carried, state[target] = state[target], _rotl(carried, _RHO[step])

        # χ — the only non-linear step, applied row by row.
        for y in range(0, _LANES, 5):
            row = state[y:y + 5]
            for x in range(5):
                state[y + x] = row[x] ^ ((~row[(x + 1) % 5] & _LANE) & row[(x + 2) % 5])

        # ι — break the symmetry the other three steps preserve.
        state[0] ^= _ROUND_CONSTANTS[round_index]
    return state


def _sponge(data, pad_byte):
    """Absorb ``data`` at :data:`RATE_BYTES` with ``pad_byte``, squeeze :data:`DIGEST_BYTES`.

    One squeeze is enough because the digest is shorter than the rate; a wider output would need a
    second permutation and this module does not offer one.
    """
    if isinstance(data, str):
        raise TypeError(
            "keccak hashes bytes, not str; got {!r}. A str has an encoding and the digest depends "
            "on it, so encoding it here would pick one silently — use event_topic() for a "
            "signature text, which states that it is ASCII and refuses anything else.".format(data)
        )
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(
            "keccak hashes bytes, not {}.".format(type(data).__name__)
        )

    padded = bytearray(data)
    padded.append(pad_byte)
    while len(padded) % RATE_BYTES != 0:
        padded.append(0x00)
    # The last byte of the last block always carries the closing bit, including the case where the
    # pad byte was itself the last byte of a full block.
    padded[-1] ^= 0x80

    state = [0] * _LANES
    for offset in range(0, len(padded), RATE_BYTES):
        block = padded[offset:offset + RATE_BYTES]
        for lane in range(RATE_BYTES // 8):
            state[lane] ^= int.from_bytes(block[lane * 8:(lane + 1) * 8], "little")
        _keccak_f1600(state)

    squeezed = b"".join(lane.to_bytes(8, "little") for lane in state[:RATE_BYTES // 8])
    return squeezed[:DIGEST_BYTES]


def keccak256(data):
    """keccak-256 of ``data`` as 32 bytes. The hash Ethereum means when it says "keccak"."""
    return _sponge(data, KECCAK_PAD)


def keccak256_hex(data):
    """keccak-256 as ``0x`` + 64 lowercase hex digits — the spelling every constant here uses."""
    return "0x" + keccak256(data).hex()


def sha3_256(data):
    """SHA3-256 of ``data``. Present so ``hashlib`` can check the permutation, not for use.

    Nothing in this repository hashes with SHA-3, and nothing should: Ethereum's ``keccak256``
    opcode, its event topics and its CREATE2 addresses are all original Keccak. This function
    exists because it differs from :func:`keccak256` in exactly one byte — the domain separator —
    so agreeing with ``hashlib.sha3_256`` at every input length is evidence about the permutation,
    the absorption and the padding of :func:`keccak256` itself, from an implementation this
    repository did not write. It says nothing about the domain byte; the topic constants do that.
    """
    return _sponge(data, SHA3_PAD)


def event_topic(text):
    """``topics[0]`` for a canonical event signature text, as an ``0x``-prefixed hex string.

    The text is the ABI's canonical form — name, then parameter types comma-separated with no
    spaces, no parameter names and no ``indexed`` markers, e.g.
    ``Transfer(address,address,uint256)``. Getting that form wrong is not detectable here: any
    string hashes to something, and a topic derived from ``Transfer(address, address, uint256)``
    is a perfectly well-formed hash of a signature no contract emits.

    :raises ValueError: the text is not ASCII, or does not have the shape ``name(types)``. Both are
        defects in the caller rather than limits on what can be measured: a signature text with a
        non-ASCII character is not a canonical signature, and encoding it would produce a digest
        that depends on which encoding was picked.
    """
    return keccak256_hex(_canonical_signature(text))


def function_selector(text):
    """The 4-byte ``eth_call`` selector for a canonical function signature, as ``0x`` + 8 hex.

    The same canonical form and the same refusals as :func:`event_topic` — a function signature and
    an event signature are hashed identically and differ only in how many bytes of the digest are
    kept. ``function_selector("totalSupply()")`` is ``0x18160ddd``, which is what a reader checks
    against a block explorer's "Read Contract" tab.

    Derived rather than written out, and that is a deliberate difference from
    :data:`ingest.tokens.DECIMALS_SELECTOR`, whose module holds no keccak and says so. Here the
    hash function is already present and already verified, so the signature text and the four bytes
    cannot drift apart: there is only one of them.
    """
    return "0x" + keccak256(_canonical_signature(text))[:4].hex()


def _canonical_signature(text):
    """``text`` as ASCII bytes, refused unless it has the shape the ABI hashes."""
    if not isinstance(text, str):
        raise TypeError("an event signature is text, got {}".format(type(text).__name__))
    try:
        encoded = text.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError(
            "an event signature must be ASCII; {!r} is not. The canonical form the ABI hashes has "
            "no non-ASCII character in it, so this is a mistyped signature and not an encoding "
            "question to be answered here.".format(text)
        )
    if not text.endswith(")") or "(" not in text or text.startswith("("):
        raise ValueError(
            "an event signature is name(types) with no spaces and no parameter names; got {!r}. "
            "Any string hashes to something, so a malformed signature produces a well-formed topic "
            "that matches no log ever emitted.".format(text)
        )
    if " " in text:
        raise ValueError(
            "the canonical signature form has no spaces; got {!r}. "
            "'Transfer(address, address, uint256)' hashes to a different topic than "
            "'Transfer(address,address,uint256)', and only the second one is the event.".format(
                text
            )
        )
    return encoded
