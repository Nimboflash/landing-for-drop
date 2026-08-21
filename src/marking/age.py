"""Token age buckets, measured from first usable liquidity — never from contract creation.

§4.7. A contract deployed months before it traded is not a mature token at its first trade, and
counting it as one would erase precisely the first-hour behaviour the Edge Origin condition
exists to detect.
"""

from contracts import QuarantineRequired, TokenAgeBucket
from phase0.parameters import PARAMETERS

#: §4.7's three bucket boundaries, read from the ticket-11 frozen set. They are boundaries of the
#: population the Edge Origin condition is measured over, so a local copy here would be a second
#: definition of "first hour" that could disagree with the frozen one and still look right.

#: §4.7 bucket A. Half-open: block 10 is the first block of B.
BUCKET_A_BLOCKS = PARAMETERS.value("token_age.bucket_a.blocks")

HOUR_SECONDS = PARAMETERS.value("token_age.bucket_b.seconds")
DAY_SECONDS = PARAMETERS.value("token_age.bucket_c.seconds")


def token_age_bucket(trade_block, trade_ts, start_block, start_ts):
    """Which §4.7 age bucket a trade falls in.

    ``start_block`` / ``start_ts`` are the token's **trading start**: the first block at which the
    token had usable liquidity *and* at least one real swap in a covered pool. Not contract
    creation, and not the current pool's creation.

    **Migration does not reset token age.** When a token's liquidity moves to a new pool, the
    trading start stays where it was — the first qualifying pool, per §4.7 and addendum §9.2. So
    this function never sees a pool at all: it takes the token's own start, and a caller that
    passed a migrated pool's first block would be answering a different question. A two-day-old
    token that migrated one block ago is bucket D.

    Buckets, half-open and exhaustive::

        A   block_age  <  10
        B   block_age >=  10  and  time_age  <  3_600
        C                          time_age  <  86_400
        D                          time_age >=  86_400

    The cascade order is the tie-break, and it is deliberate. Bucket A is defined purely in blocks
    and the definitions are listed in increasing-age order, so A is tested first. On a chain that
    stalled for over an hour inside the first 10 blocks, a trade at block-age 3 is still bucket A;
    "first 10 blocks" is the pre-registered wording and reinterpreting it by elapsed time would
    silently redefine ``FIRST_HOUR_BUCKETS`` after the fact.

    Raises :class:`contracts.QuarantineRequired` when the trade precedes the trading start. That
    is real data with a broken derivation behind it, and the honest place for it is the
    reconciliation queue — returning bucket A would hand the wallet a first-hour purchase it
    never made.
    """
    for name, value in (
        ("trade_block", trade_block), ("trade_ts", trade_ts),
        ("start_block", start_block), ("start_ts", start_ts),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(
                "{} must be an int (block numbers and UTC seconds are ints by seam rule), "
                "got {}".format(name, type(value).__name__)
            )

    block_age = trade_block - start_block
    time_age = trade_ts - start_ts

    if block_age < 0 or time_age < 0:
        raise QuarantineRequired(
            "trade at block {} / ts {} precedes the token trading start at block {} / ts {} "
            "(block_age={}, time_age={}). The derived trading start is wrong — a buy cannot "
            "predate first usable liquidity — and this belongs in the reconciliation queue "
            "rather than in bucket A.".format(
                trade_block, trade_ts, start_block, start_ts, block_age, time_age
            )
        )

    if block_age < BUCKET_A_BLOCKS:
        return TokenAgeBucket.A
    if time_age < HOUR_SECONDS:
        return TokenAgeBucket.B
    if time_age < DAY_SECONDS:
        return TokenAgeBucket.C
    return TokenAgeBucket.D
