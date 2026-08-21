"""Vendor terms that constrain the freeze — recorded, because a term you learn later is a term
you learn after the parameters are frozen.

Ticket 03 asks for three specific classes of fact, and each is here for a different reason.

**Rate limits** decide whether Step 0 (the mandatory candidate-universe census) is a two-day job or
a two-week one. A limit discovered halfway through is a schedule problem; a limit discovered before
the budget is approved is a plan.

**Historical depth** decides whether a source can answer for window 1 at all. Window 1 trains on
Jan–Jun 2023. CoinGecko Onchain's pool-level history goes back to Sept 2021 (§5), so it covers the
window with room; a source whose depth started in 2024 would be useless for three of the four
windows no matter how good it was, and that is a fact about the *plan*, not about a request that
failed.

**Coverage constraints that cannot be closed on a useful timescale** are the ones that actually
change the design. Dune restricted community contributions in October 2025: the median age of an
open contribution request is ~156 days and enterprise customers get priority (§5). Combined with
the measured 8.2% of Ethereum tracked DEX volume that has no matching spellbook model, this means a
decoder gap found in month two of Phase 0 **cannot be fixed by us**, on any timescale that matters.
The pre-registration's answer is to report it as an explicit caveat on every result rather than to
pretend it will be closed — and that answer is only available to someone who knew the term before
committing.

Every fact carries where it came from. ``PREREG`` facts are transcribed from the frozen
pre-registration and are as reliable as it is. ``CONFIRM_AT_PURCHASE`` facts are the vendor's
published terms as understood at writing, and are exactly the kind of number that changes between
tiers and quarters — so they are marked rather than asserted. A register that cannot tell those two
apart invites someone to plan against a figure nobody ever checked.
"""

#: Provenance of a recorded term.
PREREG = "pre-registration §5"
PREREG_13 = "pre-registration §13.4"
VENDOR_DOC = "vendor documentation"
CONFIRM_AT_PURCHASE = "confirm against the invoice/contract at purchase"

#: Window 1 opens here. A source whose history starts after this cannot answer for window 1.
WINDOW_1_START = "2023-01-01"


class Term(object):
    """One recorded fact about what a vendor will and will not do.

    ``blocks_gap_closure`` is the field that earns this module its place. It marks a term that
    means *a gap discovered later cannot be closed on a useful timescale* — the class of constraint
    that has to be designed around rather than managed.
    """

    __slots__ = ("kind", "statement", "provenance", "blocks_gap_closure")

    def __init__(self, kind, statement, provenance, blocks_gap_closure=False):
        if kind not in ("rate_limit", "historical_depth", "coverage", "access"):
            raise ValueError(
                "unknown term kind {!r}; expected rate_limit, historical_depth, coverage or "
                "access".format(kind)
            )
        if not statement or not str(statement).strip():
            raise ValueError("a term must say something; {!r} does not".format(statement))
        if not provenance:
            raise ValueError(
                "a term must record where it came from — an unattributed vendor term is one "
                "nobody can re-check when the tier changes"
            )
        self.kind = kind
        self.statement = str(statement).strip()
        self.provenance = provenance
        self.blocks_gap_closure = bool(blocks_gap_closure)

    @property
    def confirmed(self):
        """True when the fact comes from the frozen pre-registration rather than a vendor page."""
        return self.provenance in (PREREG, PREREG_13)

    def as_dict(self):
        return {
            "kind": self.kind,
            "statement": self.statement,
            "provenance": self.provenance,
            "confirmed": self.confirmed,
            "blocks_gap_closure": self.blocks_gap_closure,
        }


class VendorTerms(object):
    __slots__ = ("source", "vendor", "history_starts", "terms")

    def __init__(self, source, vendor, history_starts, terms):
        self.source = source
        self.vendor = vendor
        #: ISO date the usable history begins, or ``None`` when it depends on the node/provider
        #: chosen rather than on a published policy.
        self.history_starts = history_starts
        self.terms = tuple(terms)

    @property
    def covers_window_1(self):
        """Does published depth reach window 1? ``None`` when depth is provider-dependent.

        ``None`` is not a hedge. For the archival RPC it is the honest answer: depth is a property
        of the node someone provisions, so it is settled by the probe, not by a term sheet.
        """
        if self.history_starts is None:
            return None
        return self.history_starts <= WINDOW_1_START

    @property
    def gap_closure_blockers(self):
        return tuple(t for t in self.terms if t.blocks_gap_closure)

    def as_dict(self):
        return {
            "source": self.source,
            "vendor": self.vendor,
            "history_starts": self.history_starts,
            "covers_window_1": self.covers_window_1,
            "terms": [t.as_dict() for t in self.terms],
            "gap_closure_blockers": [t.statement for t in self.gap_closure_blockers],
        }


VENDOR_TERMS = {
    "dune": VendorTerms(
        "dune",
        "Dune Analytics (Plus tier)",
        history_starts="2015-07-30",  # Ethereum genesis; the decoders, not the chain, are the limit
        terms=(
            Term(
                "rate_limit",
                "API access is credit-metered per month and execution-concurrency limited on the "
                "Plus tier; a full Step-0 census must be planned as batched executions with "
                "result pagination, not as one query per wallet",
                CONFIRM_AT_PURCHASE,
            ),
            Term(
                "historical_depth",
                "dex.trades covers Ethereum from genesis, but only for venues with a spellbook "
                "decoder — depth is not the binding constraint, coverage is",
                PREREG,
            ),
            Term(
                "coverage",
                "8.2% of DefiLlama-tracked Ethereum DEX volume has no matching spellbook model. "
                "Those trades are invisible, not merely mislabelled, and must be reported as an "
                "explicit caveat on every result",
                PREREG,
                blocks_gap_closure=True,
            ),
            Term(
                "coverage",
                "Dune restricted community contributions in October 2025; median age of an open "
                "contribution request is ~156 days and enterprise customers receive priority. A "
                "decoder gap found during Phase 0 cannot be closed by us on a useful timescale",
                PREREG,
                blocks_gap_closure=True,
            ),
            Term(
                "coverage",
                "prices_dex.minute is interpolated from hourly VWAP anchors and forward-filled up "
                "to 48h, closed-source, and per-block prices are no longer exposed — so Dune is "
                "the netting input under test, never the price source",
                PREREG_13,
            ),
        ),
    ),
    "coingecko_onchain": VendorTerms(
        "coingecko_onchain",
        "CoinGecko Onchain / GeckoTerminal (Analyst tier)",
        history_starts="2021-09-01",
        terms=(
            Term(
                "rate_limit",
                "Pro key is per-minute rate limited and monthly-call metered; pool OHLCV is one "
                "call per pool per timeframe page, so the mark set must be fetched per pool and "
                "cached, never per position",
                CONFIRM_AT_PURCHASE,
            ),
            Term(
                "historical_depth",
                "Pool-level OHLCV back to Sept 2021 — covers all four windows, window 1 included",
                PREREG,
            ),
            Term(
                "coverage",
                "include_inactive_source=true is what keeps rugged pools readable: the coin-level "
                "API auto-deactivates after 30 days without trading and then denies historical "
                "access, which is survivorship bias exactly where the losses are",
                PREREG,
            ),
            Term(
                "access",
                "the Onchain/pool surface is permitted; the same key also opens the coin-level "
                "endpoints, which are PROHIBITED — one credential, two questions, only one of "
                "them ours",
                PREREG,
            ),
        ),
    ),
    "binance_klines": VendorTerms(
        "binance_klines",
        "Binance public data (data.binance.vision)",
        history_starts="2017-08-17",
        terms=(
            Term(
                "rate_limit",
                "static file host, unauthenticated, no API key and no documented per-key quota; "
                "fetch daily zips and cache locally rather than re-downloading per lookup",
                VENDOR_DOC,
            ),
            Term(
                "historical_depth",
                "daily minute-kline archives from the listing date of each symbol; ETHUSDT from "
                "Aug 2017, so window 1 is comfortably covered",
                VENDOR_DOC,
            ),
            Term(
                "coverage",
                "quote-asset USD reference only. It is not a token price source and must never be "
                "used as one",
                PREREG,
            ),
        ),
    ),
    "archival_rpc": VendorTerms(
        "archival_rpc",
        "Ethereum archival RPC (provider not yet chosen)",
        history_starts=None,
        terms=(
            Term(
                "rate_limit",
                "provider-dependent; trace calls are typically metered far more heavily than "
                "eth_call and are the calls this project actually needs",
                CONFIRM_AT_PURCHASE,
            ),
            Term(
                "historical_depth",
                "must serve state at arbitrary historical blocks, not just the last 128. This is "
                "the definition of archival and it is settled by the probe, not by a price page",
                VENDOR_DOC,
            ),
            Term(
                "access",
                "debug_traceTransaction / trace_transaction are commonly gated behind a paid or "
                "personal token even where receipts and logs are free. A node that serves "
                "receipts but refuses traces is the observed failure mode on three public "
                "endpoints — REFUSED, not UNREACHABLE",
                PREREG,
            ),
            Term(
                "coverage",
                "no invoice is attached to this source. That is precisely why it is the one most "
                "likely to be assumed rather than provisioned",
                PREREG,
            ),
        ),
    ),
}

#: Every term that means a gap cannot be closed later, flattened for the register.
def gap_closure_blockers(terms=None):
    terms = VENDOR_TERMS if terms is None else terms
    out = []
    for source in sorted(terms):
        for term in terms[source].gap_closure_blockers:
            out.append({"source": source, "statement": term.statement,
                        "provenance": term.provenance})
    return out


def as_dict(terms=None):
    terms = VENDOR_TERMS if terms is None else terms
    return {
        "window_1_start": WINDOW_1_START,
        "sources": {name: terms[name].as_dict() for name in sorted(terms)},
        "gap_closure_blockers": gap_closure_blockers(terms),
    }
