"""The recording cache: what replay guarantees, and the three ways a file stops meaning what it says.

Replay is the whole reason any number in this package is reproducible, so the tests here are about
the *cache's own honesty* rather than about Hyperliquid. Three properties, and each is a separate
failure:

* a request keys to exactly one file, whatever order the caller spelled the body in;
* a file that has been renamed, or whose request has been edited, is refused rather than served to
  the wrong request;
* a reduced recording says so, and cannot claim to be verbatim at the same time.
"""

import json
import os

import pytest

from tools.hyperliquid.recording import (
    FORMAT,
    Recording,
    RecordingCache,
    RecordingMissing,
    Reduction,
    RequestSpec,
    reduce_rows,
)

from conftest import UNKNOWN_WALLET, WALLET, WINDOW_END_MS, WINDOW_START_MS


# -- keys ------------------------------------------------------------------------


def test_key_ignores_body_key_order():
    """The venue does not care about JSON key order and neither may the cache.

    Without this, spelling the same request two ways produces two cache misses and a capture run
    that fetches the identical bytes twice.
    """
    one = RequestSpec("POST", "https://api.hyperliquid.xyz/info",
                      {"type": "userFills", "user": WALLET})
    two = RequestSpec("POST", "https://api.hyperliquid.xyz/info",
                      {"user": WALLET, "type": "userFills"})
    assert one.key() == two.key()
    assert one.filename() == two.filename()


def test_key_distinguishes_the_things_that_change_the_answer():
    base = {"type": "userFillsByTime", "user": WALLET,
            "startTime": WINDOW_START_MS, "endTime": WINDOW_END_MS}
    spec = RequestSpec("POST", "https://api.hyperliquid.xyz/info", base)
    for changed in (
        dict(base, user=UNKNOWN_WALLET),
        dict(base, startTime=WINDOW_START_MS + 1),
        dict(base, endTime=WINDOW_END_MS + 1),
        dict(base, type="userFills"),
    ):
        other = RequestSpec("POST", "https://api.hyperliquid.xyz/info", changed)
        assert other.key() != spec.key()


def test_the_canonical_string_is_recomputable_by_hand():
    """Pinned as a literal so the key can be checked without running this code."""
    spec = RequestSpec("POST", "https://api.hyperliquid.xyz/info", {"type": "meta"})
    assert spec.canonical() == (
        'POST\nhttps://api.hyperliquid.xyz/info\n{"type":"meta"}'
    )


def test_a_get_has_no_body_in_its_key():
    spec = RequestSpec("GET", "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard")
    assert spec.canonical().endswith("\n")
    assert spec.slug() == "leaderboard"


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH", "HEAD"])
def test_a_method_the_package_cannot_make_is_refused(method):
    with pytest.raises(ValueError) as raised:
        RequestSpec(method, "https://api.hyperliquid.xyz/info")
    assert "GET or POST" in str(raised.value)


def test_a_non_https_url_is_refused():
    with pytest.raises(ValueError):
        RequestSpec("GET", "http://api.hyperliquid.xyz/info")


# -- the committed recordings ----------------------------------------------------


def test_every_committed_recording_is_filed_under_its_own_key(cache):
    """The filename is derived from the request, so this catches a rename or an edited request."""
    entries = cache.entries()
    assert len(entries) == 5
    for recording in entries:
        assert os.path.basename(cache.path_for(recording.spec)).endswith(".json")
        assert cache.get(recording.spec) is not None


def test_a_renamed_file_is_invisible_to_lookup_and_harmless_to_the_digest(tmp_path, cache):
    """Identity comes from the recorded request, not from the filename. Both halves pinned.

    A file under the wrong name is **not** served to the request whose name it wears: ``get()``
    derives the path from the spec, so the renamed file is simply not found and the caller gets the
    ``RecordingMissing`` refusal with a capture command. And it does not corrupt the digest either,
    because ``digest()`` reads each file's own ``spec.key()`` rather than its name.

    What is *not* guaranteed, and this is the residue: a renamed file still appears in
    ``entries()``. ``entries()`` does not key-check — it is the "everything in this directory" view
    and the digest is computed from it — so a stray copy of a recording under a second name would be
    counted twice in the digest. That is a defect a reader can see (two files with the same
    ``request``) and is not one this class detects.
    """
    original = cache.entries()[0]
    os.makedirs(str(tmp_path), exist_ok=True)
    with open(os.path.join(str(tmp_path), "renamed-000000000000.json"), "w", encoding="utf-8") as h:
        json.dump(original.as_dict(), h)
    moved = RecordingCache(str(tmp_path))

    # Not served to the request whose name it wears.
    assert moved.get(original.spec) is None
    with pytest.raises(RecordingMissing):
        moved.require(original.spec, "python -m tools.hyperliquid.capture meta")

    # But still readable as an entry, and keyed by its own recorded request.
    assert len(moved.entries()) == 1
    assert moved.entries()[0].spec.key() == original.spec.key()


def test_a_file_whose_request_was_edited_is_refused(tmp_path, cache):
    original = cache.entries()[0]
    edited = original.as_dict()
    edited["request"]["body"] = {"type": "somethingElse"}
    directory = RecordingCache(str(tmp_path))
    os.makedirs(str(tmp_path), exist_ok=True)
    # File it under the ORIGINAL request's filename, so the name and the contents disagree.
    with open(os.path.join(str(tmp_path), original.spec.filename()), "w", encoding="utf-8") as h:
        json.dump(edited, h)

    with pytest.raises(ValueError) as raised:
        directory.get(original.spec)
    message = str(raised.value)
    assert "filed under key" in message
    assert "renamed or its request was edited" in message


def test_an_unknown_envelope_version_is_refused(tmp_path):
    data = {"format": "hyperliquid-recording-v99", "request": {}, "response": {}}
    with pytest.raises(ValueError) as raised:
        Recording.from_dict(data, "somefile.json")
    assert "this reader understands {!r}".format(FORMAT) in str(raised.value)
    assert "interpreted by a rule it was not written under" in str(raised.value)


# -- a miss is a refusal that says how to fix itself ------------------------------


def test_a_miss_names_the_capture_command(tmp_path):
    empty = RecordingCache(str(tmp_path))
    spec = RequestSpec("POST", "https://api.hyperliquid.xyz/info", {"type": "spotMeta"})
    with pytest.raises(RecordingMissing) as raised:
        empty.require(spec, "python -m tools.hyperliquid.capture spot-meta")
    message = str(raised.value)
    assert "python -m tools.hyperliquid.capture spot-meta" in message
    assert spec.key() in message
    assert "Nothing was attempted against the network here" in message


# -- reduction --------------------------------------------------------------------


def test_the_leaderboard_recording_declares_its_reduction(cache):
    """41,456 rows were captured and 50 committed. The file says both, and which rule chose them."""
    board = [r for r in cache.entries() if r.spec.slug() == "leaderboard"]
    assert len(board) == 1
    recording = board[0]
    assert not recording.verbatim
    assert recording.reduction.kept == 50
    assert recording.reduction.original_count == 41456
    assert len(recording.payload["leaderboardRows"]) == 50
    assert "in the order the venue sent them" in recording.reduction.rule
    assert "windowPerformances" in recording.reduction.rule
    # The wire fields still describe the wire, not what was committed.
    assert recording.bytes_len == 34228362


def test_the_fills_recordings_are_verbatim(cache):
    """A subset of a wallet's fills is a different wallet's history, so these may not be reduced."""
    for recording in cache.entries():
        if recording.spec.slug().startswith("userfills"):
            assert recording.verbatim
            assert recording.reduction is None


def test_verbatim_cannot_disagree_with_reduction():
    """``verbatim`` is a property, so a file cannot assert both."""
    reduction = Reduction("first 1", 1, 2, "ab" * 32)
    spec = RequestSpec("GET", "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard")
    recording = Recording(spec, 200, {}, "cd" * 32, 10, 1, "ua", reduction)
    assert recording.verbatim is False
    assert Recording(spec, 200, {}, "cd" * 32, 10, 1, "ua").verbatim is True


def test_a_reduction_cannot_add_rows():
    with pytest.raises(ValueError) as raised:
        Reduction("kept everything and more", 5, 2, "ab" * 32)
    assert "cannot add rows" in str(raised.value)


def test_a_reduction_must_say_how_rows_were_chosen():
    with pytest.raises(ValueError) as raised:
        Reduction("   ", 1, 2, "ab" * 32)
    assert "a reduction nobody can reproduce is a reduction nobody can check" in str(raised.value)


def test_reduce_rows_keeps_rows_verbatim_and_in_order():
    payload = {"leaderboardRows": [{"i": n} for n in range(10)], "other": "kept"}
    reduced, reduction = reduce_rows(payload, "leaderboardRows", 3, "first 3", b"raw")
    assert reduced["leaderboardRows"] == [{"i": 0}, {"i": 1}, {"i": 2}]
    assert reduced["other"] == "kept"
    assert reduction.kept == 3
    assert reduction.original_count == 10


# -- the digest -------------------------------------------------------------------


def test_the_digest_covers_the_responses_and_not_the_session(cache, tmp_path):
    """A re-capture of identical bytes must yield the same snapshot; the snapshot names the data."""
    before = cache.digest()
    copy = RecordingCache(str(tmp_path))
    for recording in cache.entries():
        from dataclasses import replace
        copy.put(replace(recording, captured_at=1, captured_by="somebody-else/9.9"))
    assert copy.digest() == before


def test_the_digest_moves_when_a_recorded_byte_does(cache, tmp_path):
    from dataclasses import replace

    copy = RecordingCache(str(tmp_path))
    entries = cache.entries()
    for recording in entries:
        copy.put(recording)
    assert copy.digest() == cache.digest()

    copy_two = RecordingCache(str(tmp_path / "two"))
    for position, recording in enumerate(entries):
        if position == 0:
            recording = replace(recording, bytes_sha256="0" * 64)
        copy_two.put(recording)
    assert copy_two.digest() != cache.digest()


def test_the_digest_of_an_empty_directory_is_stable(tmp_path):
    assert RecordingCache(str(tmp_path / "nothing")).digest() == RecordingCache(
        str(tmp_path / "also-nothing")
    ).digest()
