"""Binance klines — a status code is not a file.

The free source, and the one whose failure mode is quietest. ``data.binance.vision`` is a static
file host: it answers 200 for things that are not archives, and a probe that stopped at the status
code would call an HTML error page a provisioned quote-asset reference. So the proof here is that
the zip opened, the CSV inside it was read, and the day contains very nearly its full 1,440 minute
bars — because a missing minute is a missing FX rate for every fill inside it.

There is no ABSENT case in this file. The source is unauthenticated, so there is no credential to
be missing, and :attr:`credential_env` is empty by design rather than by omission — pinned below,
since adding a credential requirement here would silently make the one source that can be proven
today report ABSENT forever.
"""

import pytest

from tools.provisioning import fixtures
from tools.provisioning.outcomes import INSUFFICIENT, PROVEN, REFUSED, UNREACHABLE
from tools.provisioning.probes.binance import BinanceKlinesProbe, archive_url

from conftest import Boom, FakeTransport, Raw
from payloads import BINANCE_FIRST_OPEN_MS, BINANCE_FIRST_OPEN_PRICE, binance_routes, kline_zip


def probe():
    return BinanceKlinesProbe()


# -- what is asked for -----------------------------------------------------------

def test_the_url_names_one_symbol_one_interval_and_one_historical_day():
    url = archive_url()
    assert url.startswith("https://data.binance.vision/")
    assert "ETHUSDT" in url and "/1m/" in url
    assert fixtures.BINANCE_DAY in url
    assert url.endswith(".zip")


def test_this_source_needs_no_credential_and_says_so():
    """Empty by design. A credential requirement here would make the one provable source ABSENT."""
    assert probe().credential_env == ()


# -- UNREACHABLE -----------------------------------------------------------------

def test_a_host_that_does_not_answer_is_unreachable_not_worked_around(clean_env):
    transport = FakeTransport(default=Boom("[Errno 8] nodename nor servname provided"))
    result = probe().run(transport=transport, env=clean_env)
    assert result.status == UNREACHABLE
    assert "nodename" in result.detail


# -- REFUSED ---------------------------------------------------------------------

def test_a_declining_host_is_refused_with_its_own_words(clean_env):
    transport = FakeTransport(default=Raw(b"<Error><Code>AccessDenied</Code></Error>", status=403))
    result = probe().run(transport=transport, env=clean_env)
    assert result.status == REFUSED
    assert "AccessDenied" in result.verbatim
    assert result.evidence["http_status"] == 403


# -- INSUFFICIENT ----------------------------------------------------------------

def test_a_200_that_is_not_an_archive_is_not_a_pass(clean_env):
    """The exact case a status-code check calls success."""
    transport = FakeTransport(default=Raw(b"<html><body>404 not found</body></html>"))
    result = probe().run(transport=transport, env=clean_env)
    assert result.status == INSUFFICIENT
    assert "A status code is not a file" in result.detail


def test_a_partial_day_is_a_missing_fx_rate_not_a_rounding_error(clean_env):
    transport = FakeTransport(routes=binance_routes(bars=400))
    result = probe().run(transport=transport, env=clean_env)
    assert result.status == INSUFFICIENT
    assert result.evidence["bars"] == 400
    assert result.evidence["bars_expected"] == 1440
    assert "missing FX rate" in result.detail


def test_the_bar_floor_is_below_a_full_day_but_not_far_below(clean_env):
    """A short venue outage must not fail the archive; half a day must."""
    assert fixtures.BINANCE_MIN_BARS == 1380
    assert fixtures.BINANCE_EXPECTED_BARS == 1440
    result = probe().run(transport=FakeTransport(routes=binance_routes(bars=1380)), env=clean_env)
    assert result.status == PROVEN


# -- PROVEN ----------------------------------------------------------------------

def test_a_full_day_of_minute_bars_is_proof(clean_env):
    result = probe().run(transport=FakeTransport(routes=binance_routes()), env=clean_env)
    assert result.status == PROVEN
    assert result.evidence["bars"] == 1440
    assert result.evidence["symbol"] == "ETHUSDT"
    assert result.evidence["day"] == "2023-01-05"
    assert result.evidence["first_open_time_ms"] == BINANCE_FIRST_OPEN_MS
    # 1,439 minutes after the first open, to the millisecond. Hand-computed.
    assert result.evidence["last_open_time_ms"] == BINANCE_FIRST_OPEN_MS + 1439 * 60000


def test_a_header_row_is_dropped_by_reading_it_not_by_assuming_it(clean_env):
    transport = FakeTransport(routes=binance_routes(header=True))
    result = probe().run(transport=transport, env=clean_env)
    assert result.status == PROVEN
    assert result.evidence["bars"] == 1440


def test_the_price_is_recorded_as_the_vendors_own_text(clean_env):
    """A JSON double in the evidence would be a float in the register."""
    result = probe().run(transport=FakeTransport(routes=binance_routes()), env=clean_env)
    assert result.evidence["first_open_price"] == BINANCE_FIRST_OPEN_PRICE
    assert isinstance(result.evidence["first_open_price"], str)


@pytest.mark.parametrize("bars", [0, 1, 1379])
def test_anything_short_of_a_day_is_unproven(clean_env, bars):
    transport = FakeTransport(routes=[("data.binance.vision", Raw(kline_zip(bars=bars)))])
    result = probe().run(transport=transport, env=clean_env)
    assert result.status == INSUFFICIENT
