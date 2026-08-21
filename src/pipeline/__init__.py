"""The composition root — the one builder package permitted to import other builder packages.

    run_wallet_window(transactions, pools, prices, window, config) -> WalletWindowResult

Eight builder modules exist and each is correct on its own. This is the package that makes them one
run. ``run_wallet_window`` composes the five §4 stages, in the order §4 fixes:

    attribution   ->  who owns this transaction, and is it usable at all
    netting       ->  what economic trade happened
    fifo          ->  which sells consumed which buys
    marking       ->  what the open remainder is worth at the horizon
    scoring       ->  buy_quality per wallet, with the §10 mix attached

``depth``, ``matching_null`` and ``gate_validation`` are not in that list and are not missing from
it: they answer questions about a follower, about a set of wallets, and about the run as a whole
respectively, so none of them belongs inside a per-wallet, per-window function. See
:mod:`pipeline.run` for why folding them in would change what the wallet score means.

The leaf modules stay leaves — none of them imports a sibling — so the dependency graph has exactly
one node that knows what order things happen in, and it is this one.
``tests/test_lane_independence.py`` holds that from the outside.

The whole surface is five entry types and one result type. What the result is *for* is stated in
:mod:`pipeline.census`: a reviewer must be able to get from "N transactions in" to "M trades out"
from the returned object alone, with every transaction in the difference accounted for by a rule, a
status, or a queue entry.
"""

from .chain import observed_transaction, window_from_blocks  # noqa: F401
from .census import (  # noqa: F401
    ACCOUNTING_STAGES,
    STAGE_ORDER,
    ClassificationCensus,
    CoverageReport,
    ExclusionRecord,
    QuarantineQueue,
    QuarantineRecord,
    Stage,
    StageCounts,
    classification_census,
    stage_rank,
)
from .inputs import (  # noqa: F401
    MEASUREMENT_HORIZON_SECONDS,
    ObservedTransaction,
    TokenStart,
    UndecodableTransaction,
    Window,
    WindowConfig,
)
from .keccak import (  # noqa: F401
    event_topic,
    function_selector,
    keccak256,
    keccak256_hex,
)
from .pooladdress import (  # noqa: F401
    DERIVABLE_VENUES,
    FEE_TIERS,
    FEE_TIER_LABELS,
    NOT_DERIVABLE,
    PINNED_POOLS,
    V2_INIT_CODE_HASH,
    V3_INIT_CODE_HASH,
    Create2Venue,
    DerivationInconsistent,
    DerivedPool,
    MalformedAddress,
    NotAPair,
    PoolAddressDefect,
    UNISWAP_V2,
    UNISWAP_V3,
    UncoveredFeeTier,
    derive_pool,
    derived_pools,
    pool_address,
    sorted_pair,
)
from .tokenstart import (  # noqa: F401
    CHUNK_BLOCKS,
    COVERED_FACTORIES,
    CREATE2_DERIVATION,
    DERIVATION_VENUES,
    DERIVED_COUNTERPARTIES,
    DERIVED_NOT_COVERED,
    FACTORY_LOG_SWEEP,
    NOT_COVERED,
    SCAN_BLOCKS,
    SCAN_SLICES,
    V2_GET_RESERVES,
    V3_SLOT0,
    ActivityProbe,
    CoveredPool,
    Factory,
    FactoryLogMismatch,
    FactoryNotAtStatedBlock,
    PoolDiscovery,
    PoolStateUnreadable,
    PoolTrade,
    TokenStartDefect,
    TokenStartFinding,
    UNISWAP_V2_FACTORY,
    UNISWAP_V3_FACTORY,
    UnrecognisedFactory,
    code_length,
    confirm_factories,
    covered_pools,
    creation_block,
    derive_token_starts,
    first_active_block,
    pool_trading_start,
    pools_by_derivation,
    probe_reading,
    refusals_of,
    token_starts_of,
)
from .result import (  # noqa: F401
    BuyAccount,
    WalletOutcome,
    WalletWindowResult,
)
from .run import run_wallet_window  # noqa: F401

__all__ = [n for n in dir() if not n.startswith("_")]
