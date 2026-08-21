"""Coin-level aggregator price endpoints are a PROHIBITED source — enforced, not documented.

Pre-registration §5 makes the rule: marks come from *pool-level* on-chain OHLCV, and ground truth
comes from raw chain data. A coin-level aggregator price — CoinGecko ``/simple/price``,
``/coins/{id}/market_chart``, a CoinMarketCap quote — is a cross-venue composite. Using one to
mark a position silently answers a different question ("what was this token worth somewhere?")
than the one being asked ("what was this position worth in the pool it was actually held in?"),
and it does so with a number that looks entirely reasonable.

The failure mode this module exists to prevent is not disagreement. Nobody proposes switching the
marking rule to an aggregator. The failure mode is a *convenience call*: a gap in pool coverage,
a deadline, and a two-line helper that fills the hole from an endpoint that is already
authenticated and already in the dependency list. By the time anyone reads the diff, the number is
in a result.

So the prohibition is a refusal in code. Every transport in this package routes through
:func:`assert_not_prohibited` before it opens a connection, which means a prohibited URL cannot be
called by writing it out by hand, by copying it from a vendor doc, or by templating it — and it
cannot be called by a *fake* transport in a test either, so the rule is exercised by the suite
rather than trusted.

Getting past it requires constructing a :class:`SourceOverride` naming an approver, a reason and a
ticket, and passing it explicitly at the call site. That is deliberately more work than finding
another way to answer the question, and it leaves an artefact behind.
"""

import re


class ProhibitedSourceError(Exception):
    """A call was attempted against a source the pre-registration prohibits."""

    def __init__(self, source_id, url_shape, why):
        self.source_id = source_id
        self.why = why
        super(ProhibitedSourceError, self).__init__(
            "PROHIBITED source {}: {}\n"
            "  matched: {}\n"
            "  This is a refusal, not a warning. Pre-registration §5 marks positions from "
            "pool-level on-chain OHLCV and validates against raw chain data; a coin-level "
            "aggregator price answers a different question with a plausible-looking number.\n"
            "  If it must be called anyway, pass an explicit SourceOverride(source_id={!r}, "
            "approver=..., reason=..., ticket=...) at the call site — the point is that it costs "
            "a decision and leaves a record, not a convenience call.".format(
                source_id, why, url_shape, source_id
            )
        )


class SourceOverride(object):
    """An explicit, attributed decision to call a prohibited source once.

    Every field is required and must be non-empty. An override with no approver is an override
    nobody made, and an override with no ticket is one nobody can find later.
    """

    __slots__ = ("source_id", "approver", "reason", "ticket")

    def __init__(self, source_id, approver, reason, ticket):
        for name, value in (
            ("source_id", source_id),
            ("approver", approver),
            ("reason", reason),
            ("ticket", ticket),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    "SourceOverride.{} must be a non-empty string — an override with a blank {} "
                    "is one nobody made".format(name, name)
                )
        self.source_id = source_id.strip()
        self.approver = approver.strip()
        self.reason = reason.strip()
        self.ticket = ticket.strip()

    def permits(self, source_id):
        """An override unlocks exactly the source it names, and nothing else."""
        return self.source_id == source_id

    def as_dict(self):
        return {
            "source_id": self.source_id,
            "approver": self.approver,
            "reason": self.reason,
            "ticket": self.ticket,
        }


class ProhibitedSource(object):
    __slots__ = ("source_id", "pattern", "shape", "why")

    def __init__(self, source_id, pattern, shape, why):
        self.source_id = source_id
        self.pattern = re.compile(pattern, re.IGNORECASE)
        self.shape = shape
        self.why = why

    def matches(self, url):
        return bool(self.pattern.search(url or ""))

    def as_dict(self):
        return {"source_id": self.source_id, "url_shape": self.shape, "why": self.why}


#: The prohibited set. Each entry names the URL shape rather than a vendor, because the objection
#: is to the *kind* of number, not to the company selling it.
PROHIBITED_SOURCES = (
    ProhibitedSource(
        "coingecko_simple_price",
        r"/api/v3/simple/price|/api/v3/simple/token_price",
        "https://*.coingecko.com/api/v3/simple/price?ids=...",
        "coin-level composite spot price; not the pool the position was held in",
    ),
    ProhibitedSource(
        "coingecko_market_chart",
        r"/api/v3/coins/[^/]+/market_chart",
        "https://*.coingecko.com/api/v3/coins/{id}/market_chart",
        "coin-level composite history; cross-venue aggregation hides the venue that filled",
    ),
    ProhibitedSource(
        "coingecko_coins_markets",
        r"/api/v3/coins/markets",
        "https://*.coingecko.com/api/v3/coins/markets",
        "coin-level ranked market snapshot; a composite mark by another name",
    ),
    ProhibitedSource(
        "coinmarketcap_quotes",
        r"coinmarketcap\.com/.*/cryptocurrency/(quotes|listings)",
        "https://pro-api.coinmarketcap.com/v*/cryptocurrency/quotes/*",
        "coin-level composite quote; same objection, different vendor",
    ),
    ProhibitedSource(
        "coinpaprika_tickers",
        r"api\.coinpaprika\.com/v\d+/tickers",
        "https://api.coinpaprika.com/v1/tickers/*",
        "coin-level composite ticker; same objection, different vendor",
    ),
)

#: The permitted CoinGecko surface, stated next to the prohibition so the boundary is legible:
#: ``/onchain/networks/{network}/pools/{address}/ohlcv/...`` is pool-level and is the source the
#: dead-pool marking rule depends on. Same vendor, same key, different question.
PERMITTED_COINGECKO_SHAPE = "/api/v3/onchain/networks/{network}/pools/{address}/ohlcv/{timeframe}"


def classify_prohibited(url):
    """Return the :class:`ProhibitedSource` this URL falls under, or ``None``."""
    for source in PROHIBITED_SOURCES:
        if source.matches(url):
            return source
    return None


def assert_not_prohibited(url, override=None):
    """Refuse a prohibited URL unless an override explicitly naming that source is supplied.

    Called by every transport in this package before a connection is opened.
    """
    source = classify_prohibited(url)
    if source is None:
        return None
    if override is not None and override.permits(source.source_id):
        return source
    raise ProhibitedSourceError(source.source_id, source.shape, source.why)


def prohibited_register_entries():
    """The prohibition as it appears in the machine-readable register."""
    return [source.as_dict() for source in PROHIBITED_SOURCES]
