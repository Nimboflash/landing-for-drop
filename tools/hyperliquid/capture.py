"""The one entry point in this package that touches the network, and the only one.

Everything else replays. This module is where a recording comes from, and it is deliberately a
separate command rather than a fallback inside the client: a client that fetched on a cache miss
would make "did this number come off the wire?" a question nobody can answer after the fact, and the
answer to that question is the whole reason the recordings are committed.

Why this plans its rate and the client does not
------------------------------------------------

:mod:`tools.hyperliquid.client`'s back-off *reacts* — it retries a 429 and honours a ``Retry-After``
— and it holds no rate budget, which its own docstring says. Hyperliquid publishes a weight-based
limit on ``/info`` and nothing here counts against it. So the planning lives at the only layer that
knows how many calls are about to be made: this one sleeps :data:`PAUSE_SECONDS` between requests.
That is a courtesy to the vendor, not a guarantee about their limit.

The leaderboard, and the only reduction this package performs
--------------------------------------------------------------

``GET /Mainnet/leaderboard`` was 34,228,362 bytes and 41,456 rows when it was captured. Committing
that is not reasonable, and quietly committing a slice of it *as though it were the response* is the
exact failure this instrument exists to prevent. So the committed leaderboard recording is reduced,
and it says so in a ``reduction`` field naming the rule, the rows kept, the rows there were, and the
digest of the full capture — see :mod:`tools.hyperliquid.recording`.

The reduction is legitimate for this endpoint and no other. The leaderboard's one permitted use is
choosing *which wallets to pull fills for*, and a sample of a sample is still a sample. It would not
be legitimate for a fills response, because a subset of a wallet's fills is a different wallet's
history — so the fills captures here are ``userFillsByTime`` windows, verbatim and complete for the
window they name.

Usage::

    python -m tools.hyperliquid.capture spot-meta
    python -m tools.hyperliquid.capture meta
    python -m tools.hyperliquid.capture user-fills 0xADDR
    python -m tools.hyperliquid.capture user-fills-by-time 0xADDR START_MS END_MS
    python -m tools.hyperliquid.capture leaderboard [--keep N]

Every subcommand writes into :func:`tools.hyperliquid.client.default_recording_directory` unless
``--into`` names another, and prints the path it wrote and the digest of the bytes it wrote it from.
"""

import argparse
import sys
import time

from tools.provisioning.transport import UrllibTransport

from .client import (
    INFO_URL,
    LEADERBOARD_URL,
    USER_AGENT,
    HyperliquidClient,
    default_recording_directory,
)
from .provenance import require_real_address
from .recording import RecordingCache, RequestSpec, reduce_rows

#: Seconds between requests in a multi-call capture. See the module docstring: the client reacts to
#: a 429 and this is the only layer that can avoid earning one.
PAUSE_SECONDS = 1

#: How many leaderboard rows the committed recording keeps by default. Enough to exercise
#: :func:`tools.hyperliquid.decode.leaderboard_addresses` over real rows and to sample wallets from;
#: small enough to read and diff by hand.
DEFAULT_KEEP = 50

#: The rule the committed leaderboard reduction records. Written out rather than formatted from the
#: arguments so the file states a rule a reader can *reproduce*, not a sentence describing one.
LEADERBOARD_RULE = (
    "the first {} rows of leaderboardRows, in the order the venue sent them, taken verbatim. No "
    "row was edited, reordered or selected on any property of its contents — in particular not on "
    "windowPerformances, which is a vendor-computed return that §3 forbids from being the metric. "
    "The venue's order is itself a ranking, so this is the top of that ranking and is not a random "
    "sample of Hyperliquid wallets; whoever samples from it owns that bias."
)


def _client(into, live):
    cache = RecordingCache(into or default_recording_directory())
    return HyperliquidClient(cache, transport=UrllibTransport() if live else None), cache


def _report(path, recording):
    print("wrote {}".format(path))
    print("  status {}  bytes {}  sha256 {}".format(
        recording.status, recording.bytes_len, recording.bytes_sha256
    ))
    if recording.reduction is not None:
        print("  reduced: kept {} of {} rows".format(
            recording.reduction.kept, recording.reduction.original_count
        ))


def _capture(client, cache, spec):
    """Perform one live request and write it verbatim. Returns the recording."""
    recording, attempts, waited = client._perform(spec)
    if not 200 <= recording.status < 300:
        raise SystemExit(
            "{} answered {} — nothing written. The vendor's answer: {}".format(
                spec.describe(), recording.status, str(recording.payload)[:400]
            )
        )
    path = cache.put(recording)
    _report(path, recording)
    if attempts > 1:
        print("  took {} attempts, waited {}s".format(attempts, waited))
    return recording


def capture_info(kind, body, into=None):
    client, cache = _client(into, live=True)
    return _capture(client, cache, RequestSpec("POST", INFO_URL, body))


def capture_leaderboard(keep=DEFAULT_KEEP, into=None):
    """Capture the leaderboard and commit a **declared** subset of it.

    The full response is fetched — there is no partial request to make — and the digest recorded in
    the ``reduction`` is of those full bytes, so a re-capture can be compared against what this one
    actually saw even though what it committed is smaller.
    """
    import json

    client, cache = _client(into, live=True)
    spec = RequestSpec("GET", LEADERBOARD_URL)
    recording, _attempts, _waited = client._perform(spec)
    if not 200 <= recording.status < 300:
        raise SystemExit(
            "{} answered {} — nothing written.".format(spec.describe(), recording.status)
        )
    full_bytes = json.dumps(recording.payload, separators=(",", ":")).encode("utf-8")
    reduced, reduction = reduce_rows(
        recording.payload, "leaderboardRows", keep, LEADERBOARD_RULE.format(keep), full_bytes,
    )
    # The committed recording keeps the *original* capture's bytes_sha256 and bytes_len, because
    # those describe what came off the wire and that is what they are for. What was committed
    # instead is stated in ``reduction`` rather than by rewriting the fields that mean "the wire".
    from dataclasses import replace

    committed = replace(recording, payload=reduced, reduction=reduction)
    path = cache.put(committed)
    _report(path, committed)
    return committed


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m tools.hyperliquid.capture",
        description=(
            "Capture Hyperliquid responses into the replay cache. This is the only code in the "
            "package that opens a connection."
        ),
    )
    parser.add_argument("--into", default=None, help="recording directory (default: the committed one)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("spot-meta")
    sub.add_parser("meta")

    fills = sub.add_parser("user-fills")
    fills.add_argument("address")

    by_time = sub.add_parser("user-fills-by-time")
    by_time.add_argument("address")
    by_time.add_argument("start_ms", type=int)
    by_time.add_argument("end_ms", type=int)

    board = sub.add_parser("leaderboard")
    board.add_argument("--keep", type=int, default=DEFAULT_KEEP)

    args = parser.parse_args(argv)
    print("User-Agent: {}".format(USER_AGENT))

    if args.command == "spot-meta":
        capture_info("spotMeta", {"type": "spotMeta"}, args.into)
    elif args.command == "meta":
        capture_info("meta", {"type": "meta"}, args.into)
    elif args.command == "user-fills":
        user = require_real_address(args.address, "user-fills <address>")
        capture_info("userFills", {"type": "userFills", "user": user}, args.into)
    elif args.command == "user-fills-by-time":
        user = require_real_address(args.address, "user-fills-by-time <address>")
        capture_info(
            "userFillsByTime",
            {
                "type": "userFillsByTime",
                "user": user,
                "startTime": args.start_ms,
                "endTime": args.end_ms,
            },
            args.into,
        )
    elif args.command == "leaderboard":
        capture_leaderboard(args.keep, args.into)
    time.sleep(PAUSE_SECONDS)
    return 0


if __name__ == "__main__":                                     # pragma: no cover - entry point
    sys.exit(main())
