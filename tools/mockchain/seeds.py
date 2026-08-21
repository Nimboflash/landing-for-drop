"""Every varying quantity in a synthetic run, derived from the caller's seed and nothing else.

No ``random`` module, no clock, no ``os.urandom``, no dict iteration order. ``random.Random(seed)``
would have been explicitly seeded and therefore permitted by the rule, and it is still avoided
here for a narrower reason: the Mersenne Twister's *mapping* from a seed to a sequence is a CPython
implementation detail, so "same seed, byte-identical output" would be a promise about an
interpreter rather than about this file. HMAC-SHA256 is a promise about the algorithm.

The derivation is ``phase0.seeds``' shape, reused rather than reinvented::

    draw = HMAC-SHA256(key=str(seed), msg='label|index') as a big-endian integer

with the same restriction ``phase0.seeds`` applies for the same reason: a label may not contain
the field separator, or the flattening from ``(label, index)`` to one message stops being
injective and two different draws collapse into one.
"""

import hashlib
import hmac

#: The field separator in the derivation message, and the one character a label may not contain.
FIELD_SEPARATOR = "|"


def draw(seed, label, index=0):
    """A deterministic 256-bit integer for ``(seed, label, index)``.

    :param seed: the caller's seed. An ``int``; a string seed would make ``seed=1`` and
        ``seed="1"`` two different runs that print the same way.
    :param label: what is being drawn, e.g. ``"band-low/buy/quote_raw"``. Must not contain ``|``.
    :param index: which draw of that kind.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError(
            "seed must be an int, got {}. The seed is the whole of a synthetic run's "
            "reproducibility record, and two spellings of one seed would be two runs that claim "
            "to be the same one.".format(type(seed).__name__)
        )
    if FIELD_SEPARATOR in label:
        raise ValueError(
            "draw label {!r} contains the field separator {!r}. The message flattens (label, "
            "index) into one string, and a label carrying the separator makes that flattening "
            "non-injective — two different draws would return the same value, silently.".format(
                label, FIELD_SEPARATOR
            )
        )
    if isinstance(index, bool) or not isinstance(index, int):
        raise TypeError("index must be an int, got {}".format(type(index).__name__))
    message = "{}{}{}".format(label, FIELD_SEPARATOR, index)
    digest = hmac.new(
        str(seed).encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return int(digest, 16)


def draw_between(seed, label, low, high, index=0):
    """A deterministic int in ``[low, high]``, both ends inclusive.

    Modulo bias is real and irrelevant here: this generator's job is to reach code paths
    reproducibly, not to be a statistically sound sampler, and pretending otherwise by rejection
    sampling would make the output depend on how many rejections happened.
    """
    if high < low:
        raise ValueError("draw_between({!r}) has high {} below low {}".format(label, high, low))
    return low + draw(seed, label, index) % (high - low + 1)
