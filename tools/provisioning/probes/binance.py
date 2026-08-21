"""Binance public data — minute klines for one quote asset on one historical day.

The free source, and the only one this package can prove without anyone buying anything. It is also
the least interesting to get wrong and the easiest to get wrong quietly: ETH is the quote asset for
most Ethereum DEX pools, so ETHUSDT minute bars are what turn a WETH-denominated fill into a USD
number. A missing minute is a missing FX rate for every fill inside it.

``data.binance.vision`` serves a **zip per symbol per day**, not JSON, which is why
:class:`~tools.provisioning.transport.Response` carries bytes. Proof is therefore stricter than
"200 OK": the archive is opened, the CSV inside it is counted, and the day must contain very nearly
a full 1,440 bars. A 200 that returns an HTML error page, a truncated file, or a day with four
hundred rows in it all fail here, and each of those is a thing a status-code check would have
called success.

No credential exists for this source and none is required. That makes it the one probe whose
``PROVEN`` should be reachable from this sandbox today — and if the host is not reachable from
here, that is UNREACHABLE and gets reported, not worked around.
"""

import csv
import io
import zipfile

from .. import fixtures
from ..outcomes import insufficient, proven
from .base import Probe

ARCHIVE_ROOT = "https://data.binance.vision/data/spot/daily/klines"


def archive_url(symbol=fixtures.BINANCE_SYMBOL, interval=fixtures.BINANCE_INTERVAL,
                day=fixtures.BINANCE_DAY):
    return "{root}/{symbol}/{interval}/{symbol}-{interval}-{day}.zip".format(
        root=ARCHIVE_ROOT, symbol=symbol, interval=interval, day=day
    )


class BinanceKlinesProbe(Probe):

    source = "binance_klines"
    capability = "minute klines for {} on {} ({} bars expected)".format(
        fixtures.BINANCE_SYMBOL, fixtures.BINANCE_DAY, fixtures.BINANCE_EXPECTED_BARS
    )
    #: Free and unauthenticated. Nothing to be ABSENT.
    credential_env = ()

    def _probe(self, transport, env):
        url = archive_url()
        response = transport.get(url)
        if not response.ok:
            return self.refusal(response, "the daily kline archive",
                                evidence={"day": fixtures.BINANCE_DAY,
                                          "symbol": fixtures.BINANCE_SYMBOL})

        try:
            rows = _read_klines(response.body)
        except (zipfile.BadZipFile, KeyError, IndexError, UnicodeDecodeError) as exc:
            return insufficient(
                self.source,
                "the host answered 200 but the body is not a readable kline archive ({}: {}). "
                "A status code is not a file.".format(type(exc).__name__, exc),
                evidence={"bytes": len(response.body), "endpoint": response.url},
            )

        evidence = {
            "symbol": fixtures.BINANCE_SYMBOL,
            "interval": fixtures.BINANCE_INTERVAL,
            "day": fixtures.BINANCE_DAY,
            "bars": len(rows),
            "bars_expected": fixtures.BINANCE_EXPECTED_BARS,
            "endpoint": response.url,
            # Open times are millisecond integers and the open price is kept as the vendor's own
            # text. Neither becomes a float on the way into the register.
            "first_open_time_ms": int(rows[0][0]) if rows else None,
            "last_open_time_ms": int(rows[-1][0]) if rows else None,
            "first_open_price": str(rows[0][1]) if rows else None,
        }

        if len(rows) < fixtures.BINANCE_MIN_BARS:
            return insufficient(
                self.source,
                "only {} minute bars for {} on {}; a complete UTC day is {}. A partial day is a "
                "missing FX rate for every fill inside the gap.".format(
                    len(rows), fixtures.BINANCE_SYMBOL, fixtures.BINANCE_DAY,
                    fixtures.BINANCE_EXPECTED_BARS
                ),
                evidence=evidence,
            )

        return proven(
            self.source,
            "{} minute bars for {} on {}, read out of the daily zip archive.".format(
                len(rows), fixtures.BINANCE_SYMBOL, fixtures.BINANCE_DAY
            ),
            evidence=evidence,
        )


def _read_klines(body):
    """Rows of the single CSV inside the daily zip.

    Binance began shipping a header row on some archives; it is dropped by checking whether the
    first field parses as an integer open time, rather than by assuming either shape.
    """
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        name = archive.namelist()[0]
        raw = archive.read(name).decode("utf-8")
    rows = [row for row in csv.reader(io.StringIO(raw)) if row]
    if rows:
        try:
            int(rows[0][0])
        except (ValueError, IndexError):
            rows = rows[1:]
    return rows
