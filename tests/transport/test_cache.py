"""The recording cache: keys, verbatim round-trips, and the two ways a snapshot can lie."""

import json
import os

import pytest

from transport.cache import (
    RecordingCache,
    RecordingCorrupt,
    RecordingMissing,
    cache_key,
    optional_cache,
)

from conftest import RECORDINGS, TRACER_TX

#: Pinned literals, not recomputed. These are the keys the committed snapshot is filed under, so a
#: change to the canonical form would orphan every fixture in the repository — which is exactly the
#: sort of silent change a hash is supposed to make loud.
RECEIPT_KEY = "8b4f637209ea7b4bb069144084d660d3c885ff26b35a900252084f18491bcb5b"
BALANCE_KEY = "7959b73fb42b42f87cd2b1c56069dd4763e9604de34452eece9b6f344e95e9d2"


def test_the_key_of_the_tracer_bullet_receipt_is_pinned():
    assert cache_key("eth_getTransactionReceipt", [TRACER_TX]) == RECEIPT_KEY


def test_the_key_of_the_archival_balance_call_is_pinned():
    assert cache_key(
        "eth_getBalance", ["0xe15b3d62c2bce51f2a8a8d53d76c36b4fab8721c", "0xf8d721"]
    ) == BALANCE_KEY


def test_the_key_covers_the_method_the_params_and_their_order():
    a = cache_key("eth_getBalance", ["0xa" * 40, "0xf8d721"])
    assert cache_key("eth_getBalance", ["0xa" * 40, "0xf8d722"]) != a
    assert cache_key("eth_getBalance", ["0xf8d721", "0xa" * 40]) != a
    assert cache_key("eth_getBlockByNumber", ["0xa" * 40, "0xf8d721"]) != a


def test_a_tuple_and_a_list_of_the_same_params_are_one_call():
    assert cache_key("m", ("0x1", "0x2")) == cache_key("m", ["0x1", "0x2"])


def test_no_params_and_empty_params_are_one_call():
    assert cache_key("eth_blockNumber", None) == cache_key("eth_blockNumber", [])


def test_an_int_parameter_cannot_reach_a_key():
    """The failure this prevents: one call, two keys, and a frozen snapshot that misses."""
    with pytest.raises(TypeError):
        cache_key("eth_getBlockByNumber", [16308001, False])


def test_an_empty_method_is_refused():
    with pytest.raises(ValueError):
        cache_key("", [])


# -- round trip ------------------------------------------------------------------


@pytest.fixture
def cache(tmp_path):
    return RecordingCache(tmp_path / "snapshot", clock=lambda: 1672534063)


def test_a_result_survives_the_round_trip_unmodified(cache):
    result = {"status": "0x1", "logs": [{"topics": ["0x" + "a" * 64], "removed": False}],
              "contractAddress": None, "count": 8}
    cache.write("eth_getTransactionReceipt", ["0x" + "b" * 64], result, "https://node")
    assert cache.read("eth_getTransactionReceipt", ["0x" + "b" * 64]).result == result


def test_the_recording_carries_its_provenance(cache):
    recording = cache.write("eth_getBalance", ["0xa" * 40, "0x1"], "0x2a", "https://node")
    assert recording.endpoint == "https://node"
    assert recording.recorded_at == "2023-01-01T00:47:43+00:00"
    assert recording.key == cache_key("eth_getBalance", ["0xa" * 40, "0x1"])
    assert cache.read("eth_getBalance", ["0xa" * 40, "0x1"]).endpoint == "https://node"


def test_has_is_false_before_and_true_after(cache):
    assert not cache.has("eth_chainId", [])
    cache.write("eth_chainId", [], "0x1", "https://node")
    assert cache.has("eth_chainId", [])


def test_a_missing_recording_names_the_call_the_directory_and_the_file(cache):
    with pytest.raises(RecordingMissing) as exc:
        cache.read("eth_getTransactionReceipt", [TRACER_TX])
    message = str(exc.value)
    assert "eth_getTransactionReceipt" in message
    assert TRACER_TX in message
    assert RECEIPT_KEY[:16] in message
    assert "nothing was contacted" in message


def test_a_recording_filed_under_another_calls_key_is_refused(cache):
    """A snapshot that serves one answer under another key is worse than no snapshot."""
    cache.write("eth_getBalance", ["0xa" * 40, "0x1"], "0x2a", "https://node")
    path = cache.path_for("eth_getBalance", ["0xa" * 40, "0x1"])
    with open(path, "r", encoding="utf-8") as handle:
        body = json.load(handle)
    body["params"] = ["0xb" * 40, "0x1"]
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(body, handle)

    with pytest.raises(RecordingCorrupt) as exc:
        cache.read("eth_getBalance", ["0xa" * 40, "0x1"])
    assert "reproducible and wrong" in str(exc.value)


def test_a_hand_edited_key_is_refused_even_when_the_call_matches(cache):
    cache.write("eth_chainId", [], "0x1", "https://node")
    path = cache.path_for("eth_chainId", [])
    with open(path, "r", encoding="utf-8") as handle:
        body = json.load(handle)
    body["key"] = "0" * 64
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(body, handle)
    with pytest.raises(RecordingCorrupt):
        cache.read("eth_chainId", [])


def test_writing_twice_overwrites_and_leaves_no_partial_file(cache):
    cache.write("eth_chainId", [], "0x1", "https://a")
    cache.write("eth_chainId", [], "0x5", "https://b")
    assert cache.read("eth_chainId", []).result == "0x5"
    assert [name for name in os.listdir(cache.directory) if name.endswith(".partial")] == []


def test_entries_are_ordered_and_complete(cache):
    cache.write("eth_chainId", [], "0x1", "https://a")
    cache.write("eth_getBalance", ["0xa" * 40, "0x1"], "0x2", "https://a")
    entries = cache.entries()
    assert [entry.method for entry in entries] == ["eth_chainId", "eth_getBalance"]


def test_entries_is_empty_for_a_directory_that_does_not_exist(tmp_path):
    assert RecordingCache(tmp_path / "absent").entries() == ()


# -- fingerprint -----------------------------------------------------------------


def test_the_fingerprint_covers_the_answers(cache):
    cache.write("eth_chainId", [], "0x1", "https://a")
    before = cache.fingerprint()
    cache.write("eth_chainId", [], "0x5", "https://a")
    assert cache.fingerprint() != before


def test_the_fingerprint_ignores_who_answered_and_when(tmp_path):
    """Re-recording the same answers elsewhere is the same snapshot for reproducing a number."""
    first = RecordingCache(tmp_path / "a", clock=lambda: 1000)
    second = RecordingCache(tmp_path / "b", clock=lambda: 9999)
    for cache_, endpoint in ((first, "https://a"), (second, "https://b")):
        cache_.write("eth_chainId", [], "0x1", endpoint)
        cache_.write("eth_getBalance", ["0xa" * 40, "0x1"], "0x2a", endpoint)
    assert first.fingerprint() == second.fingerprint()


def test_the_committed_snapshot_fingerprint_is_pinned():
    """The tracer bullet's thirteen answers, as one number a run record can cite.

    The count is asserted beside the hash on purpose. A fingerprint alone goes red identically
    whether a recorded *answer* changed — which would mean the bytes this repository's literals
    were read off are no longer the bytes on disk, and every hand-computed number in
    ``tests/hand_computed/test_ingest.py`` is in question — or whether a call was merely *added*,
    which is the ordinary consequence of decoding one more thing. Those two need different
    responses, and a bare hash mismatch does not say which happened.

    So: thirteen calls, one receipt, one transaction, five headers, two archival balances, three
    ``eth_call``s for ``decimals()`` and one ``eth_getLogs``. Growing the snapshot moves this hash
    and is expected to; a *changed* answer under an unchanged count is the loud case.
    """
    cache = RecordingCache(RECORDINGS)

    assert len(cache.entries()) == 13
    assert cache.fingerprint() == (
        "70c6948c5a69e7cddb7f91a6a763ac667c785e96afb0fab9ca7ee6429285c88d"
    )


def test_optional_cache_is_none_only_for_none(tmp_path):
    assert optional_cache(None) is None
    assert isinstance(optional_cache(tmp_path), RecordingCache)
