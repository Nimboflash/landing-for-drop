"""Ticket 03 — prove the data is actually reachable, rather than assume it.

**This package is not pipeline code and must never become any.** It interprets no chain bytes and
computes no metric: it asks four vendors whether they will serve the data Phase 0 depends on, and
records what they answered. That is why it lives in ``tools/`` and not in ``src/`` — it is not a
builder module, not a validator module, and not shared seam code, so it must not appear in the
lane graph at all. ``tests/test_lane_independence.py`` classifies every top-level package under
``src/``; a provisioning probe placed there would have to be given a lane, and it has none.

The one thing it does borrow from ``src`` is :mod:`contracts.numeric`. Money is Decimal under the
frozen context, here as everywhere — ``calc()`` rejects a float on sight — because a budget total
computed in floats is exactly the kind of "it's only reporting" arithmetic that later turns out to
have been load-bearing.

What the ticket actually demands, and what this package therefore refuses to fake:

* **Reaching an endpoint is not proof.** Each probe names a capability and must demonstrate *that
  capability*: rows for a named block range, candles for a pool known to be dead, a full day of
  minute klines, and all four archival RPC calls for one named transaction. Anything less is
  ``INSUFFICIENT``, which is a status, not an error.
* **A missing credential is a normal state of the world.** It is ``ABSENT``, reported and moved
  past. But the reverse does not hold: ``PROVEN`` is earned by evidence recorded in the register,
  never by the absence of an error. :class:`~tools.provisioning.outcomes.ProbeResult` refuses to
  construct a ``PROVEN`` result with no evidence attached.
* **Coin-level aggregator price endpoints are prohibited**, and the prohibition is a refusal in
  code rather than a comment: every transport in this package checks the URL before it is opened
  (see :mod:`tools.provisioning.prohibited`).
* **``data_budget: APPROVED`` needs two keys** — a human's recorded approval *and* every source
  ``PROVEN``. It is a computed property with no setter, so it cannot be written by hand, by the
  CLI, or by a probe that merely failed to fail.

Credentials come from environment variables only. Nothing here reads a file of secrets, writes a
credential anywhere, or echoes one — URLs are redacted before they reach a log, an error message,
or the register.

Entry point::

    provisioning-probe            # or: python -m tools.provisioning.cli

Exit is non-zero for as long as ``data_budget`` is ``PENDING``. A green exit means provisioned.
"""

from .budget import BUDGET_LINES, CEILING_USD, headroom, projected_total, utilisation
from .outcomes import ABSENT, INSUFFICIENT, PROVEN, REFUSED, UNREACHABLE, ProbeResult
from .prohibited import (
    ProhibitedSourceError,
    SourceOverride,
    assert_not_prohibited,
    classify_prohibited,
)
from .register import APPROVED, PENDING, HumanApproval, ProvisioningRegister, build
from .probes import PROBES, capabilities, run_all
from .terms import VENDOR_TERMS

__all__ = [
    "ABSENT",
    "UNREACHABLE",
    "REFUSED",
    "INSUFFICIENT",
    "PROVEN",
    "ProbeResult",
    "PROBES",
    "run_all",
    "capabilities",
    "APPROVED",
    "PENDING",
    "build",
    "ProvisioningRegister",
    "HumanApproval",
    "ProhibitedSourceError",
    "SourceOverride",
    "assert_not_prohibited",
    "classify_prohibited",
    "BUDGET_LINES",
    "CEILING_USD",
    "projected_total",
    "headroom",
    "utilisation",
    "VENDOR_TERMS",
]
