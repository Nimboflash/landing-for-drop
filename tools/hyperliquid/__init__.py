"""A real order book that nobody pre-registered, used as an engineering source and marked as one.

**This is not a Phase 0 data source and must never become one.** §11.1 fixes the chain as Ethereum
Mainnet and §11.2 pre-registers Arbitrum as the single optional secondary diagnostic, in its own
words *"as a secondary diagnostic, not introduced after Ethereum fails"*. Hyperliquid is not on
that list. Nothing here may be an input to a Phase 0 number, and :mod:`tools.hyperliquid.governance`
is where that is refused rather than promised.

**Then why have it.** For the same reason ``tools/mockchain`` exists, plus one difference that makes
this the more useful of the two. mockchain generates data *designed by the person writing the
generator*, so it can only exhibit defects that person already imagined. This is real data nobody
chose: a real venue, real wallets, real fills, with whatever shape the world actually has. That is
the kind of input that found five defects on the first Ethereum contact, one of which was a whole
transaction vanishing from the census.

It earned its keep the same way here. Every claim in this package's docstrings that begins "measured
on the committed recording" is a number taken from the recording after it was captured, not a number
predicted before — and three of the beliefs this package started with did not survive contact:

* a fill was assumed to be a transaction. ``userFills`` returns one row per *fill*: of the 262
  distinct hashes in the main recording, 5 carry more than one fill and one carries 32. Mapping a
  fill to an ``ObservedTransaction`` would have handed ``pipeline.run`` 32 rows under one hash and
  ``pipeline.run._require_one_transaction_per_hash`` would have refused the whole run.
* the zero hash was assumed to be one transaction's identity. 62 fills share it, spanning 48 days
  and mixing 55 spot fills with 7 perpetual ones, each carrying a *distinct* ``tid``. Grouping by
  hash would have fused seven weeks of unrelated trading into a single "transaction".
* the wallet was assumed to be the transaction's sender. 377 of 382 fills have ``crossed: false`` —
  the wallet's order was resting and the L1 transaction belongs to whoever crossed the spread, whom
  the payload does not name. Only 2 of the 235 decoded transactions can honestly claim the wallet
  as ``tx_sender``.

Where the marker lives, and why not where mockchain's lives
------------------------------------------------------------

mockchain makes the marker the identifier itself, because a flag is a field and fields are dropped
by joins. That answer cannot be copied here: a Hyperliquid ``ethAddress`` is a real 20-byte address
and is the one thing a reader can check against the venue's own explorer, so corrupting it would
destroy what makes this source worth having. The marker therefore lives on the **dataset snapshot
identifier** — ``NOT-PREREGISTERED-…-NOT-THE-PREREGISTERED-CHAIN`` — which is one row of
``phase0.snapshots.NOT_REAL_PREFIXES`` and is what every run record and audit entry quotes. Assets
*are* minted, because a Hyperliquid token is not an Ethereum token and filing one under an Ethereum
address would be a quantity error before it was a naming one. :mod:`tools.hyperliquid.provenance`
justifies each placement separately.

Replay is the default and it is not a flag: a client constructed the ordinary way holds no transport
and physically cannot open a connection. Every number in this package is reproducible from the
committed recording with the network unplugged.
"""

from .client import (  # noqa: F401
    HL_API_BASE,
    HL_STATS_BASE,
    USER_AGENT,
    Call,
    HyperliquidClient,
    VendorRefused,
    default_recording_directory,
    replay_client,
)
from .decode import (  # noqa: F401
    NOT_APPLICABLE,
    DecodedFills,
    ExcludedFill,
    HyperliquidRefusal,
    MalformedFill,
    NotADecimal,
    PerpFillPresentedAsSpot,
    PerpUniverse,
    QuantityNotRepresentable,
    SpotUniverse,
    UnknownAsset,
    decode_fills,
    decode_spot_fill,
    leaderboard_addresses,
    run_inputs,
)
from .governance import (  # noqa: F401
    GOVERNANCE_NOTE,
    HYPERLIQUID_MAY_NOT_ADVANCE,
    WHY_NOT_PREREGISTERED,
    HyperliquidRunRefused,
    execute_hyperliquid_stage,
    refuse_if_hyperliquid_would_advance,
)
from .provenance import (  # noqa: F401
    IDENTIFIER_PREFIX,
    MAINNET_ASSETS,
    MARKER,
    SNAPSHOT_PREFIX,
    VENUE_CHAIN,
    HyperliquidProvenanceLost,
    MalformedAddress,
    audit_no_mainnet_assets,
    hyperliquid_asset,
    is_hyperliquid_identifier,
    is_hyperliquid_snapshot,
    require_real_address,
    snapshot_id,
)
from .recording import (  # noqa: F401
    Recording,
    RecordingCache,
    RecordingMissing,
    Reduction,
    RequestSpec,
)

__all__ = [n for n in dir() if not n.startswith("_")]
