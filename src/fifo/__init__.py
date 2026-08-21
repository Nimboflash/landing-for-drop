"""FIFO position accounting (§4.4, ticket 22).

Builder lane. Consumes and returns frozen seam types only.

    from fifo import match_fifo
    result = match_fifo(buys, sells)   # one owner, one asset, per call

The single public name is deliberate. Lot assignment is a deterministic field that must match the
golden set exactly, and the rule exists precisely so that nobody can select a different one after
seeing a result.
"""

from .matching import match_fifo  # noqa: F401

__all__ = ["match_fifo"]
