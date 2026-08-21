"""Deterministic seed derivation.

Pre-registration §9.6 requires the random-seed policy to be part of the freeze manifest, and the
addendum §11 fixes it: *one master random seed with deterministic child seeds*.

Every stochastic step — the 1,000 null runs per window per column, control sampling, any
bootstrap — draws its seed from here rather than from a global RNG. Two consequences that matter:

* The same ``(master_seed, commit)`` pair reproduces every child seed exactly, so a run can be
  replayed on a machine that has never seen it.
* Because ``commit`` is an input, a code change produces different child seeds. That is
  deliberate. A re-run after an invalidation is a genuinely new experiment, not the old one with
  a patch, and it should not silently inherit the old draws.
"""

import hashlib
import hmac

MASTER_SEED_BYTES = 32

#: The field separator in the derivation message. Not an implementation detail: it is recorded
#: verbatim in ``RunRecord.SEED_RULE`` (``msg=f'{commit}|{purpose}|{index}'``), so a reader
#: re-derives a seed from the record with this character, and it is the freeze that fixes it.
FIELD_SEPARATOR = "|"


def _require(name, value):
    if value is None or str(value).strip() == "":
        raise ValueError("{} is required to derive a child seed".format(name))
    return str(value)


def _require_message_field(name, value):
    """``_require``, plus the one restriction that keeps the flattened message unambiguous.

    ``derive_child_seed`` joins three components with ``|`` and hashes the result, which is a
    flattening: an identity of three parts becomes one scalar, and if a component may contain the
    separator the flattening is not injective. Refused rather than escaped, because escaping would
    make the derivation stop matching ``RunRecord.SEED_RULE`` — the sentence a reader re-derives a
    recorded run's seeds from — and that sentence is part of the §9.6 freeze.

    **What was actually reachable, measured.** Within one commit the flattening was already
    injective and no refusal was needed: ``index`` is an ``int``, so ``str(index)`` contains no
    ``|``, so the last separator splits the index off and everything between the first and last
    separators is the purpose, whatever it contains. 180 derivations over purposes including
    ``"p"``, ``"p|1"``, ``"p|1|2"`` and ``"|"`` at 30 indices produced 180 distinct seeds. That
    matters because the invariant a run leans on is the *within-distribution* one —
    ``matching_null.permutation_null_detail`` checks that its 1,000 draws have distinct seeds, and
    all 1,000 share a commit.

    What was reachable was the cross-commit case, and it is reachable through the public API rather
    than in principle: ``RunStore.open_run`` requires a non-empty ``commit`` and does not require a
    hex SHA, so::

        derive_child_seed(master, commit="abc|null.leader", purpose="window1",         index=0)
        derive_child_seed(master, commit="abc",             purpose="null.leader|window1", index=0)

    were one seed — 91057054122863460495179724698494709738616472449431008072485148703461237999389
    for both. What that costs is the guarantee in this module's own header: a re-run pinned to a
    different commit is *deliberately* a new experiment and must not inherit the old draws, and two
    runs sharing a seed share every "independent" draw the permutation null is built from.
    """
    text = _require(name, value)
    if FIELD_SEPARATOR in text:
        raise ValueError(
            "{} may not contain {!r}, got {!r}. The three components are joined with that "
            "character and hashed, so one that carries it moves the field boundary: "
            "commit='abc{sep}null.leader' with purpose='window1' derives the same seed as "
            "commit='abc' with purpose='null.leader{sep}window1'. Two runs that must be separate "
            "experiments would then draw the identical 'independent' numbers, which is the one "
            "thing the permutation null cannot survive. Refused rather than escaped: the "
            "derivation is recorded verbatim as RunRecord.SEED_RULE and a reader must be able to "
            "reproduce it with nothing but that sentence.".format(
                name, FIELD_SEPARATOR, text, sep=FIELD_SEPARATOR)
        )
    return text


def derive_child_seed(master_seed, commit, purpose, index=0):
    """Derive one child seed as a 256-bit integer.

    The three components are flattened into one string before hashing, and
    :func:`_require_message_field` is what makes that flattening injective: neither ``commit`` nor
    ``purpose`` may contain ``|``, and ``index`` is an ``int``, so the message decomposes back into
    exactly the triple it was built from. Distinct triples therefore derive distinct messages, and
    distinct messages derive distinct seeds short of a SHA-256 collision.

    Stated with the residue it has: the components are coerced with ``str()`` first, so the commit
    ``1234`` and the commit ``"1234"`` are one input here and derive one seed. They name one commit,
    which is why this is left rather than refused — but the injectivity above is over the *string*
    forms, not over the Python objects handed in.

    :param master_seed: hex string. The single secret-ish root recorded in the run record. It is
        the HMAC key rather than part of the message, so the separator rule does not apply to it.
    :param commit: the source commit the run is pinned to. May not contain ``|``.
    :param purpose: what the seed is for, e.g. ``"null.leader.window1"``. Distinct purposes must
        never collide, so this string is part of the derivation, not a comment. May not contain
        ``|``.
    :param index: run index within a purpose, e.g. 0..999 for the null runs.
    """
    master_seed = _require("master_seed", master_seed)
    commit = _require_message_field("commit", commit)
    purpose = _require_message_field("purpose", purpose)
    if not isinstance(index, int) or index < 0:
        raise ValueError("index must be a non-negative integer, got {!r}".format(index))

    message = FIELD_SEPARATOR.join((commit, purpose, str(index))).encode("utf-8")
    digest = hmac.new(bytes.fromhex(master_seed), message, hashlib.sha256).digest()
    return int.from_bytes(digest, "big")


def derive_child_seeds(master_seed, commit, purpose, count):
    """Derive ``count`` child seeds for one purpose, indexed ``0..count-1``."""
    if count < 0:
        raise ValueError("count must be non-negative")
    return [derive_child_seed(master_seed, commit, purpose, i) for i in range(count)]


def new_master_seed(entropy=None):
    """Mint a master seed.

    ``entropy`` makes this deterministic for tests and for reproducing a documented run. In
    normal use it is omitted and the seed comes from the OS.
    """
    if entropy is None:
        import os
        return os.urandom(MASTER_SEED_BYTES).hex()
    return hashlib.sha256(str(entropy).encode("utf-8")).hexdigest()
