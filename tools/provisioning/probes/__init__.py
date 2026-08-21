"""The four probes, in the order the register reports them.

Order is the order of the source table in pre-registration §5, and it ends with the archival RPC on
purpose: it is the one with no invoice, the one whose failure is a design problem rather than a
purchasing one, and therefore the one a reader should be left looking at.

``run_all`` never raises for a vendor's behaviour — every state of the world it can meet is one of
the five outcomes. It *will* raise for a
:class:`~tools.provisioning.prohibited.ProhibitedSourceError`, because that is a defect in this
package and must not be laundered into a status.
"""

from .archival import ArchivalRpcProbe
from .binance import BinanceKlinesProbe
from .coingecko import CoinGeckoOnchainProbe
from .dune import DuneProbe

#: Source id -> probe instance. The keys are the register's per-source keys and the budget's line
#: names, deliberately: a source that has a cost but no probe, or a probe but no cost line, is a
#: mismatch the register refuses to publish.
PROBES = (
    DuneProbe(),
    CoinGeckoOnchainProbe(),
    BinanceKlinesProbe(),
    ArchivalRpcProbe(),
)

PROBE_SOURCES = tuple(probe.source for probe in PROBES)


def run_all(transport=None, env=None, probes=PROBES):
    """Run every probe and return ``{source: ProbeResult}``.

    ``transport`` is passed through so the whole set can be driven by a fake. Each probe builds its
    own live transport when none is supplied — and does so only *after* its credential check, so an
    empty environment contacts nothing at all.
    """
    return {probe.source: probe.run(transport=transport, env=env) for probe in probes}


def capabilities(probes=PROBES):
    """What each probe claims to demonstrate. Recorded in the register next to the outcome, so a
    reader can see what ``PROVEN`` was proven *of*."""
    return {probe.source: probe.capability for probe in probes}


__all__ = [
    "PROBES",
    "PROBE_SOURCES",
    "run_all",
    "capabilities",
    "DuneProbe",
    "CoinGeckoOnchainProbe",
    "BinanceKlinesProbe",
    "ArchivalRpcProbe",
]
