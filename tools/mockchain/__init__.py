"""A synthetic chain source, so the machine can run end to end before there is any data.

**This package is not in ``src/`` and must not move there.** It interprets no chain bytes — it
decodes no log, filters no transfer, detects no endpoint, matches no lot and prices no exit. It
*constructs* values whose shapes ``contracts`` already names and hands them to the builder lane
through ``pipeline.run_wallet_window``, the same public entry point a real reader would use.
``tests/test_lane_independence.py`` requires every package under ``src/`` to be classified builder,
validator or shared, and a fixture is none of the three: a synthetic source that appeared in the
lane graph would be a synthetic source the metric could import.

Three things this package is for, in the order they matter:

1. **A synthetic run must be impossible to mistake for a measurement.** Every identifier it mints
   carries the marker in its own text (:mod:`tools.mockchain.provenance`), the dataset snapshot
   names itself synthetic, and publication re-reads the bytes about to be hashed and refuses one
   whose provenance is gone.
2. **Governance must not advance on synthetic data.** :mod:`tools.mockchain.governance` refuses
   any stage that would complete a Phase 0 transition, and records exactly where in ``src/phase0/``
   that refusal belongs — this package cannot put it there, and a refusal that only lives in the
   harness is a refusal anyone can route around.
3. **Then, and only then, the fixture.** :mod:`tools.mockchain.chain` generates the wallets, pools
   and prices; :mod:`tools.mockchain.report` runs the window and assembles §10's blocks.

Determinism is a property of the whole package: same seed, byte-identical output. No ``random``,
no clock, no ``os.urandom``, no dependence on iteration order.
"""

from .chain import SyntheticChain, generate_chain  # noqa: F401
from .governance import (  # noqa: F401
    GOVERNANCE_GAP,
    SYNTHETIC_MAY_NOT_ADVANCE,
    SyntheticRunRefused,
    execute_synthetic_stage,
    refuse_if_synthetic_would_advance,
)
from .provenance import (  # noqa: F401
    IDENTIFIER_PREFIX,
    MARKER,
    PERMITTED_UNMARKED,
    SYNTHETIC_CHAIN,
    SyntheticProvenanceLost,
    audit_payload_provenance,
    is_synthetic_identifier,
    is_synthetic_snapshot,
    publish_synthetic_artifact,
    snapshot_id,
    synthetic_address,
    synthetic_tx_hash,
)
from .report import (  # noqa: F401
    SyntheticRun,
    run_synthetic_window,
    synthetic_report,
)

__all__ = [n for n in dir() if not n.startswith("_")]
