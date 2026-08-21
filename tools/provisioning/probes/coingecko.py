"""CoinGecko Onchain — candles for a pool that is *dead*. A live pool proves nothing.

This is the load-bearing probe. §9.1 marks a dead pool's positions at **zero**, and the only reason
that rule is implementable is that pool-level history survives after a token stops trading, where
coin-level listings are auto-deactivated after 30 days and then deny historical access entirely
(§13.4). ``include_inactive_source=true`` is the flag that keeps the pool-level door open. If it
does not work on the tier we buy, the dead-pool marking rule has no data underneath it — and that
is a fact worth discovering now, for $129, rather than after the parameters are frozen.

Which is why a live pool is not acceptable evidence. Every live pool returns candles with the flag,
without the flag, and on the free tier; asking one and getting candles back demonstrates nothing
about the capability under test. The probe therefore establishes deadness **from the response
itself** before it will call anything proven:

* the most recent candle is older than the §9.1 30-day inactivity window, and
* the pool reports no 24-hour volume and no 24-hour transactions.

Both, from the vendor's own payload, on the day the probe runs. Deadness is a property of the world
and not a constant, so it cannot be asserted in a source file and left to rot.

The candidate pools come from ``COINGECKO_DEAD_POOL_CANDIDATES`` (``network:address``, comma
separated) because choosing one means looking at a chain explorer, and this package will not
manufacture an address it has not looked up. With none configured the probe says exactly that, and
the status is INSUFFICIENT — the capability is unproven, which is the truth.

The same key opens ``/api/v3/simple/price`` and ``/api/v3/coins/{id}/market_chart``. Those are
PROHIBITED (see :mod:`tools.provisioning.prohibited`) and the transport refuses them before a
connection is opened, so the convenient wrong call cannot be made from here even by accident.
"""

import time

from contracts.numeric import calc

from .. import fixtures
from ..outcomes import insufficient, proven
from ..transport import TransportError
from .base import Probe


def _is_zero(value):
    """Zero-or-unknown 24h volume. The vendor sends it as a *string*, which is the good case.

    ``None`` (metadata unavailable) counts as quiet on purpose: the binding test for deadness is
    the age of the last candle, and a metadata call that failed must not be able to *promote* a
    live pool — only to fail to contradict a stale one.
    """
    if value is None:
        return True
    try:
        return calc(str(value)) == 0
    except (ValueError, TypeError):
        return False

PRO_ROOT = "https://pro-api.coingecko.com/api/v3/onchain"
OHLCV_TIMEFRAME = "day"
OHLCV_LIMIT = 200

SECONDS_PER_DAY = 86400


class CoinGeckoOnchainProbe(Probe):

    source = "coingecko_onchain"
    capability = (
        "pool-level OHLCV returns candles for a pool known to be dead, with "
        "include_inactive_source=true"
    )
    credential_env = ("COINGECKO_API_KEY",)

    def __init__(self, now=None):
        #: Injected so "is this pool dead today?" is testable without waiting thirty days.
        self._now = now if now is not None else time.time

    def _headers(self, env):
        return {
            "x-cg-pro-api-key": env["COINGECKO_API_KEY"].strip(),
            "Accept": "application/json",
        }

    def _ohlcv_url(self, network, address, include_inactive):
        return (
            "{root}/networks/{network}/pools/{address}/ohlcv/{tf}"
            "?aggregate=1&limit={limit}&include_inactive_source={flag}".format(
                root=PRO_ROOT,
                network=network,
                address=address,
                tf=OHLCV_TIMEFRAME,
                limit=OHLCV_LIMIT,
                flag="true" if include_inactive else "false",
            )
        )

    def _probe(self, transport, env):
        candidates = fixtures.dead_pool_candidates(env)
        if not candidates:
            return insufficient(
                self.source,
                "no dead-pool candidate named, so the capability cannot be proven — a live pool "
                "returns candles with or without the flag and demonstrates nothing. Set {}="
                "eth:0x<pair address> for a pool whose last trade predates the §9.1 {}-day "
                "inactivity window.".format(fixtures.DEAD_POOL_ENV, fixtures.DEAD_INACTIVITY_DAYS),
            )

        headers = self._headers(env)
        live_seen = []

        for network, address in candidates:
            response = transport.get(
                self._ohlcv_url(network, address, include_inactive=True), headers=headers
            )
            if not response.ok:
                return self.refusal(
                    response,
                    "pool OHLCV with include_inactive_source=true",
                    evidence={"network": network, "pool": address},
                )

            candles = self._candles(response.json())
            if not candles:
                return insufficient(
                    self.source,
                    "the pool answered but returned no candles with include_inactive_source=true. "
                    "That is the exact failure the dead-pool marking rule cannot survive.",
                    evidence={"network": network, "pool": address, "candles_with_flag": 0},
                )

            last_ts = max(int(c[0]) for c in candles)
            age_days = int((self._now() - last_ts) // SECONDS_PER_DAY)
            metadata = self._metadata(transport, headers, network, address)

            evidence = {
                "network": network,
                "pool": address,
                "include_inactive_source": True,
                "candles_with_flag": len(candles),
                "first_candle_unix": min(int(c[0]) for c in candles),
                "last_candle_unix": last_ts,
                "days_since_last_candle": age_days,
                "inactivity_threshold_days": fixtures.DEAD_INACTIVITY_DAYS,
                "volume_usd_h24": metadata["volume_usd_h24"],
                "transactions_h24": metadata["transactions_h24"],
            }

            quiet = (
                _is_zero(metadata["volume_usd_h24"])
                and metadata["transactions_h24"] in (None, 0)
            )
            dead = age_days >= fixtures.DEAD_INACTIVITY_DAYS and quiet
            if not dead:
                live_seen.append("{}:{} (last candle {}d ago, 24h volume {})".format(
                    network, address, age_days, metadata["volume_usd_h24"]))
                continue

            # Not fatal, and not required for the proof — but the single most convincing line in
            # the register is the one showing the flag is what did the work.
            try:
                without = transport.get(
                    self._ohlcv_url(network, address, include_inactive=False), headers=headers
                )
            except TransportError:
                without = None
            evidence["candles_without_flag"] = (
                len(self._candles(without.json())) if (without is not None and without.ok) else None
            )
            evidence["without_flag_http_status"] = None if without is None else without.status

            return proven(
                self.source,
                "{} daily candles for {}:{}, a pool whose last trade was {} days ago (threshold "
                "{}), with include_inactive_source=true. Same pool without the flag: {}.".format(
                    len(candles), network, address, age_days,
                    fixtures.DEAD_INACTIVITY_DAYS, evidence["candles_without_flag"],
                ),
                evidence=evidence,
            )

        return insufficient(
            self.source,
            "every candidate pool is still live, and a live pool proves nothing — it returns "
            "candles with or without the flag. Name a pool whose last trade predates the §9.1 "
            "{}-day window. Seen: {}".format(
                fixtures.DEAD_INACTIVITY_DAYS, "; ".join(live_seen)
            ),
            evidence={"live_candidates": live_seen},
        )

    # -- payload reading -------------------------------------------------------

    @staticmethod
    def _candles(payload):
        attributes = ((payload or {}).get("data") or {}).get("attributes") or {}
        rows = attributes.get("ohlcv_list") or []
        return [row for row in rows if isinstance(row, (list, tuple)) and row]

    def _metadata(self, transport, headers, network, address):
        """24h volume and transaction count, as strings/ints. Never floats — see outcomes."""
        blank = {"volume_usd_h24": None, "transactions_h24": None}
        try:
            response = transport.get(
                "{}/networks/{}/pools/{}".format(PRO_ROOT, network, address), headers=headers
            )
        except TransportError:
            # Corroboration, not proof. A failed metadata call must not turn a pool that already
            # answered with candles into an UNREACHABLE source.
            return blank
        if not response.ok:
            return blank
        attributes = (((response.json() or {}).get("data") or {}).get("attributes")) or {}
        volume = (attributes.get("volume_usd") or {}).get("h24")
        transactions = (attributes.get("transactions") or {}).get("h24") or {}
        try:
            count = int(transactions.get("buys") or 0) + int(transactions.get("sells") or 0)
        except (TypeError, ValueError):
            count = None
        return {
            "volume_usd_h24": None if volume is None else str(volume),
            "transactions_h24": count,
        }
