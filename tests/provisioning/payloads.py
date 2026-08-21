"""Vendor-shaped payloads for the fake transports, in one place.

Two test files need a Dune execution that returns rows, and three need an archival node that serves
all four capabilities. Building those inline twice invites the two copies to drift, and the copy
that drifts is always the one asserting the happy path — so the shapes live here and the test files
say what they mean.

**Every identifier in this module is synthetic and looks it.** ``0xabab…`` is not a transaction
anybody could mistake for one from a block explorer. That is deliberate, and it is the same
argument :mod:`tools.provisioning.fixtures` makes about the real probe: a plausible-looking hash
pasted into a provisioning check is the evidence the check exists to produce, invented. A fake
transport is allowed to invent, precisely because nothing it returns can ever reach the register of
a real run.

The numbers are chosen to be hand-checkable. The balance delta is 2 ETH before and 1.5 ETH after,
so the probe must report exactly ``-500000000000000000`` wei — a value that is wrong the moment
somebody subtracts in the other direction or lets a float near it.
"""

import csv
import io
import zipfile

from tools.provisioning import fixtures

from conftest import Json, Raw, rpc_method

# -- sequencing -----------------------------------------------------------------


def sequence(*outcomes):
    """Answer a repeated call differently each time, holding the last answer once exhausted.

    ``eth_getBalance`` is called twice at two different heights and the whole point of the balance
    delta is that the two answers differ. A single scripted outcome would make the delta zero and
    hide a probe that asked for the same block twice.
    """
    remaining = list(outcomes)

    def answer(_url):
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return answer


# -- dune ------------------------------------------------------------------------

DUNE_QUERY_ID = 4242
DUNE_EXECUTION_ID = "exec-1"


def dune_rows(dex=3, aggregator=2, first_block=fixtures.BLOCK_RANGE_START):
    """Rows labelled by source table — one execution has to prove both halves.

    ``amount_usd`` arrives as text because the probe's SQL casts it at the warehouse: a JSON double
    in the evidence would be a float in the register, which the numeric policy refuses on sight.
    """
    out = []
    for index in range(dex):
        out.append({"source_table": "dex.trades", "block_number": first_block + index,
                    "project": "uniswap", "amount_usd": "1234.50"})
    for index in range(aggregator):
        out.append({"source_table": "dex_aggregator.trades", "block_number": first_block + index,
                    "project": "1inch", "amount_usd": "999.00"})
    return out


def dune_routes(result_rows=None, state="QUERY_STATE_COMPLETED", results_status=200):
    result_rows = dune_rows() if result_rows is None else result_rows
    return [
        ("/execute", Json({"execution_id": DUNE_EXECUTION_ID, "state": "QUERY_STATE_PENDING"})),
        ("/status", Json({"state": state})),
        ("/results", Json({"result": {"rows": result_rows}}, status=results_status)),
        ("/api/v1/query", Json({"query_id": DUNE_QUERY_ID})),
    ]


# -- coingecko onchain -----------------------------------------------------------

DEAD_POOL = "0x" + "de" * 20
LIVE_POOL = "0x" + "11" * 20
NETWORK = "eth"

SECONDS_PER_DAY = 86400


def ohlcv(last_ts, count=90, step=SECONDS_PER_DAY):
    """A descending ``ohlcv_list``, newest first, exactly as the vendor ships it."""
    rows = []
    for index in range(count):
        stamp = last_ts - index * step
        rows.append([stamp, "1.5", "1.9", "1.4", "1.6", "25000"])
    return {"data": {"attributes": {"ohlcv_list": rows}}}


def pool_metadata(volume_usd_h24="0.0", buys=0, sells=0):
    return {
        "data": {
            "attributes": {
                "volume_usd": {"h24": volume_usd_h24},
                "transactions": {"h24": {"buys": buys, "sells": sells}},
            }
        }
    }


def with_flag(url, _body=None):
    return "include_inactive_source=true" in url


def without_flag(url, _body=None):
    return "include_inactive_source=false" in url


def is_metadata(url, _body=None):
    """The pool metadata call: same pool path, no ``/ohlcv`` on the end."""
    return "/pools/" in url and "/ohlcv/" not in url


def coingecko_routes(last_candle_ts, volume_usd_h24="0.0", buys=0, sells=0,
                     candles_with_flag=90, candles_without_flag=0):
    return [
        (with_flag, Json(ohlcv(last_candle_ts, count=candles_with_flag))),
        (without_flag, Json(ohlcv(last_candle_ts, count=candles_without_flag))),
        (is_metadata, Json(pool_metadata(volume_usd_h24, buys, sells))),
    ]


# -- binance ---------------------------------------------------------------------

#: 2023-01-05T00:00:00Z in milliseconds. Minute bars step by 60,000 from here.
BINANCE_FIRST_OPEN_MS = 1672876800000
BINANCE_FIRST_OPEN_PRICE = "1250.10"


def kline_csv(bars=fixtures.BINANCE_EXPECTED_BARS, header=False):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if header:
        # Binance began shipping a header row on some archives. The probe must drop it by reading
        # it, not by assuming a shape.
        writer.writerow(["open_time", "open", "high", "low", "close", "volume"])
    for index in range(bars):
        writer.writerow([
            BINANCE_FIRST_OPEN_MS + index * 60000,
            BINANCE_FIRST_OPEN_PRICE, "1251.00", "1249.00", "1250.55", "31.4159",
        ])
    return buffer.getvalue()


def kline_zip(bars=fixtures.BINANCE_EXPECTED_BARS, header=False):
    """The daily archive: one CSV inside a zip, which is why responses carry bytes."""
    buffer = io.BytesIO()
    name = "{}-{}-{}.csv".format(
        fixtures.BINANCE_SYMBOL, fixtures.BINANCE_INTERVAL, fixtures.BINANCE_DAY
    )
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, kline_csv(bars=bars, header=header))
    return buffer.getvalue()


def binance_routes(bars=fixtures.BINANCE_EXPECTED_BARS, header=False):
    return [("data.binance.vision", Raw(kline_zip(bars=bars, header=header)))]


# -- archival rpc ----------------------------------------------------------------

TX = "0x" + "ab" * 32
SENDER = "0x" + "5e" * 20
CONTRACT = "0x" + "c0" * 20
BLOCK_HASH = "0x" + "b1" * 32

#: 2 ETH before, 1.5 ETH after. The probe must report the delta as -500000000000000000 wei.
BALANCE_BEFORE_WEI = 2000000000000000000
BALANCE_AFTER_WEI = 1500000000000000000
BALANCE_DELTA_WEI = BALANCE_AFTER_WEI - BALANCE_BEFORE_WEI

TRACE_REFUSAL = "archive requests require a personal token"


def _hex(value):
    return hex(value)


def block_payload(transactions=None):
    if transactions is None:
        transactions = [
            # A bare ETH transfer first, on purpose: it has no logs, so a probe that grabbed index
            # 0 could not prove the event-log capability. The probe must walk past it.
            {"hash": "0x" + "77" * 32, "from": SENDER, "input": "0x"},
            {"hash": TX, "from": SENDER, "input": "0xa9059cbb" + "0" * 128},
        ]
    return {
        "hash": BLOCK_HASH,
        "number": _hex(fixtures.ARCHIVAL_BLOCK),
        "transactions": transactions,
    }


def receipt_payload(log_count=2):
    return {
        "blockNumber": _hex(fixtures.ARCHIVAL_BLOCK),
        "status": "0x1",
        "gasUsed": "0x1d4c0",
        "transactionHash": TX,
        "logs": [
            {"address": CONTRACT, "transactionHash": TX, "logIndex": _hex(index),
             "topics": ["0x" + "dd" * 32], "data": "0x"}
            for index in range(log_count)
        ],
    }


def logs_payload(matching=2, other=1):
    entries = [
        {"address": CONTRACT, "transactionHash": TX, "logIndex": _hex(index)}
        for index in range(matching)
    ]
    entries += [
        {"address": CONTRACT, "transactionHash": "0x" + "99" * 32, "logIndex": _hex(50 + index)}
        for index in range(other)
    ]
    return entries


def trace_payload():
    return {
        "type": "CALL",
        "from": SENDER,
        "to": CONTRACT,
        "value": "0x0",
        "gasUsed": "0x1d4c0",
        "calls": [{"type": "STATICCALL", "from": CONTRACT, "to": CONTRACT}],
    }


def jsonrpc_error(message, code=-32601):
    """A JSON-RPC error arrives inside an HTTP **200**.

    That is the whole reason the archival probe reads the body rather than the status code: the
    observed refusal on public endpoints is a 200 with a refusal inside it, and a status-code check
    would have recorded it as a success.
    """
    return Json({"jsonrpc": "2.0", "id": 1, "error": {"code": code, "message": message}})


def rpc_result(result):
    return Json({"jsonrpc": "2.0", "id": 1, "result": result})


def archival_routes(block=None, receipt=None, logs=None, debug=None, trace=None, balances=None):
    """A node answering all four capabilities — with each one independently replaceable.

    One knob per capability, because the failure this probe exists to catch is *partial*: a node
    that serves receipts and logs and refuses traces. A test has to be able to break exactly one
    thing and watch the whole source come back unprovisioned.
    """
    return [
        (rpc_method("eth_getBlockByNumber"), rpc_result(block_payload()) if block is None else block),
        (rpc_method("eth_getTransactionReceipt"),
         rpc_result(receipt_payload()) if receipt is None else receipt),
        (rpc_method("eth_getLogs"), rpc_result(logs_payload()) if logs is None else logs),
        (rpc_method("debug_traceTransaction"),
         rpc_result(trace_payload()) if debug is None else debug),
        (rpc_method("trace_transaction"),
         rpc_result([trace_payload()]) if trace is None else trace),
        (rpc_method("eth_getBalance"), balances if balances is not None else sequence(
            rpc_result(_hex(BALANCE_BEFORE_WEI)), rpc_result(_hex(BALANCE_AFTER_WEI))
        )),
    ]
