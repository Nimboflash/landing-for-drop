"""Fixtures for the Hyperliquid suite, and the recording every literal in it belongs to.

**Make ``tools`` importable.** ``pyproject`` sets ``pythonpath = ["src"]``, which is right: the
pipeline lives under ``src/`` and nothing else belongs on the path by default. ``tools/`` is
deliberately outside it — ``tests/test_lane_independence.py`` classifies every package under ``src/``
into a lane and an engineering source is none of them — so this suite puts the repository root on
``sys.path`` itself. It *appends* rather than inserting at position 0, for the reason
``tests/provisioning/conftest.py`` records: an insert at 0 silently overrode ``PYTHONPATH`` for every
test sharing the process and turned a whole mutation run into false negatives.

**No network, and the suite proves it rather than promising it.** Every client here is built without
a transport, so it physically cannot open a connection, and :func:`no_live_calls` asserts on the
client's own call log at the end of the tests that use it. If the recordings were deleted, this
suite would go red with ``RecordingMissing`` naming the capture command — not green with silently
different numbers, and not slow with real HTTP.

**Every literal in this directory was measured from the committed recording, then written down.**
Not predicted, and not recomputed by the code under test — a test that recomputes the implementation
pins nothing about it. The two wallets and their windows are named once here so that a re-capture
moves one file and goes red everywhere at once.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from tools.hyperliquid import default_recording_directory, replay_client  # noqa: E402
from tools.hyperliquid.decode import (  # noqa: E402
    PerpUniverse,
    SpotUniverse,
    decode_fills,
)
from tools.hyperliquid.recording import RecordingCache  # noqa: E402

#: The wallet the main recording is of. A real leaderboard address; every number in this suite that
#: says "the recording" without qualification is about this one.
WALLET = "0x9f84ee298a33cf4304af318e18cd23ac5fcf5648"

#: Its window, in UTC **milliseconds**. Addressable on purpose: ``userFills`` returns "the last
#: 2000" and is reproducible by nobody, whereas this window is the same window tomorrow.
WINDOW_START_MS = 1780428669789
WINDOW_END_MS = 1784671328658

#: A second wallet over a 30-minute window, kept because it is the only committed data that
#: exercises :class:`~tools.hyperliquid.decode.UnknownAsset` — it trades builder-deployed markets
#: (``#870``, ``#881``) that appear in neither ``spotMeta`` nor ``meta``.
UNKNOWN_WALLET = "0x41e73386692f9e6e29edc4fa7b685370de3c429e"
UNKNOWN_START_MS = 1779530884433
UNKNOWN_END_MS = 1779532684433

#: What the committed ``spotMeta`` and ``meta`` hold. Not standing facts about the venue — the
#: universes grow as markets are deployed, which is the whole reason the recordings exist.
SPOT_TOKENS = 484
SPOT_MARKETS = 324
PERP_MARKETS = 232

#: The main recording's shape, measured.
FILLS = 382
DISTINCT_HASHES = 262
ZERO_HASH_FILLS = 62
TRANSACTIONS = 235
EXCLUDED = 144


@pytest.fixture(scope="session")
def cache():
    return RecordingCache(default_recording_directory())


@pytest.fixture
def client():
    """A client that holds no transport and therefore cannot reach the network."""
    return replay_client(default_recording_directory())


@pytest.fixture(scope="session")
def spot():
    return SpotUniverse.from_spot_meta(replay_client(default_recording_directory()).spot_meta())


@pytest.fixture(scope="session")
def perps():
    return PerpUniverse.from_meta(replay_client(default_recording_directory()).meta())


@pytest.fixture(scope="session")
def fills():
    """The main wallet's 382 fills, verbatim as the venue sent them."""
    return replay_client(default_recording_directory()).user_fills_by_time(
        WALLET, WINDOW_START_MS, WINDOW_END_MS
    )


@pytest.fixture(scope="session")
def unknown_fills():
    return replay_client(default_recording_directory()).user_fills_by_time(
        UNKNOWN_WALLET, UNKNOWN_START_MS, UNKNOWN_END_MS
    )


@pytest.fixture(scope="session")
def decoded(fills, spot, perps):
    return decode_fills(fills, spot, perps, WALLET)


@pytest.fixture(scope="session")
def leaderboard():
    return replay_client(default_recording_directory()).leaderboard()
