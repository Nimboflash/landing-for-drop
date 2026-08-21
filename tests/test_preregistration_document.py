"""The pre-registration document, checked against the freeze it claims.

Everything else in this suite tests the machine. This file tests the *document*, because ticket 11
froze a text and not a program, and two things about a text can go quietly wrong in a way no unit
test would see.

**A sign-off that says less than the record.** §17 carries the freeze date and the commit hash. The
authoritative record is the hash-chained audit log, which is local state and not in git — so these
cases pin the document against the frozen parameter set instead, which *is* in git and was frozen at
the same commit. A §17 that drifted from it would be the one artifact a reader trusts saying
something the machine does not.

**A translation that falls a version behind.** ``phase-0-preregistration.fa.md`` is at v1.0 and the
frozen text is the English v1.1: it does not contain the three conflict resolutions that v1.1
merged, so in three places it describes superseded rules — the random-basket benchmark, the old
null, and an undefined follower order size. That is not a defect in the translation, it is a normal
consequence of one document moving. The defect would be leaving it *unmarked*, because a reader in
Persian would then be reading rules the experiment is not pre-registered on, with nothing on the
page to say so.

So the invariant is not "the translation is current". It is: **a translation is current, or it says
it is not.** Both are fine; the silence between them is not.
"""

import os
import re

import pytest

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

FROZEN_COMMIT = "4bbae13"
FROZEN_ON = "2026-08-16"

#: The three resolutions v1.1 merged, as a phrase that appears in the English text for each. A
#: translation carrying all three is current; one carrying none is a version behind. Checked as
#: presence rather than by parsing, because what matters is whether a reader would meet the rule.
V1_1_RESOLUTIONS = (
    ("§8.2 the null is a within-matched-set permutation", "within each matched set"),
    ("§6.6 benchmarks are matched pairs", "matched set"),
    ("§4.5 follower orders sized to the execution cost cap", "execution cost cap"),
)


def _read(name):
    with open(os.path.join(DOCS, name), encoding="utf-8") as handle:
        return handle.read()


@pytest.fixture(scope="module")
def english():
    return _read("phase-0-preregistration.md")


@pytest.fixture(scope="module")
def persian():
    return _read("phase-0-preregistration.fa.md")


# -- the sign-off says what the freeze recorded ---------------------------------


def test_the_sign_off_block_carries_the_commit_and_the_date(english):
    """§17's two factual lines, filled in from the record rather than left blank."""
    signoff = english.split("## 17. Sign-off", 1)[1]

    assert re.search(r"Pre-registration frozen on:\s+" + FROZEN_ON, signoff)
    assert re.search(r"Frozen at commit:\s+" + FROZEN_COMMIT, signoff)


def test_the_header_no_longer_calls_itself_a_draft(english):
    """A frozen document that still reads 'not yet frozen' is the reader's first and worst signal."""
    header = english.split("---", 1)[0]

    assert "FROZEN" in header
    assert "not yet frozen" not in header


def test_the_sign_off_says_it_was_written_after_the_freeze(english):
    """The one thing about this block that is genuinely confusing, addressed on the page.

    Filling §17 in necessarily makes the document at HEAD differ from the document at the frozen
    commit — by exactly this block. Unexplained, that reads as a document edited after it was
    frozen, which is the accusation the whole §17 protocol exists to be able to answer.
    """
    signoff = english.split("## 17. Sign-off", 1)[1]

    assert "written after the freeze" in signoff
    assert "change no rule above" in signoff
    assert "not HEAD" in signoff


def test_the_unassigned_sign_off_lines_name_the_ticket_that_would_fill_them(english):
    """Three blanks that are blank for a reason, and the reason is checkable."""
    signoff = english.split("## 17. Sign-off", 1)[1]

    assert re.search(r"Primary Builder:.*ticket 01", signoff)
    assert re.search(r"Independent Validator:.*ticket 02", signoff)
    assert "no code path in this repository can" in signoff


def test_the_sign_off_states_the_size_of_the_set_it_froze(english):
    """§17 says how many parameters the freeze covers, and the number has to be the real one.

    Prose in a frozen document goes stale the same way a duplicated threshold does, and this is the
    sentence that would: add a 54th parameter and §17 still claims 53, with nothing to notice. The
    count is read from the module rather than written here for the same reason — a test that
    restated it would agree with itself.
    """
    from phase0.parameters import COMMIT_MIN_LENGTH, PARAMETERS

    signoff = english.split("## 17. Sign-off", 1)[1]

    assert "The {} parameters it fixes".format(len(PARAMETERS)) in signoff, (
        "§17 does not state the current size of the frozen set ({} parameters)".format(
            len(PARAMETERS))
    )
    assert len(FROZEN_COMMIT) >= COMMIT_MIN_LENGTH
    assert set(FROZEN_COMMIT) <= set("0123456789abcdef"), (
        "§17 must name a commit hash; a branch name moves and would record nothing"
    )


# -- the translation is current, or it says it is not ---------------------------


def test_the_translation_is_current_or_declares_that_it_is_not(persian):
    """The invariant, and the only one that survives the translation being maintained later.

    If somebody brings the Persian text up to v1.1, the three resolutions appear and this passes
    on the first branch. Until then it passes only while the warning is there. What it refuses is
    the state in between: a stale translation with nothing on the page saying so.
    """
    missing = [name for name, phrase in V1_1_RESOLUTIONS if phrase not in persian]

    if not missing:
        return

    header = persian.split("---", 1)[0]
    assert "متنِ frozen‌شده نیست" in header, (
        "the translation is missing {} and does not declare itself superseded. A reader in Persian "
        "would meet rules the experiment is not pre-registered on, with nothing on the page to say "
        "so — bring it to v1.1, or mark it.".format(", ".join(missing))
    )
    assert FROZEN_COMMIT in header
    assert "phase-0-preregistration.md" in header


def test_the_translation_does_not_sign_a_freeze_it_did_not_receive(persian):
    """A stale text with a filled-in sign-off block would claim a freeze that never covered it."""
    signoff = persian.split("## 17.", 1)[1]

    assert "عمداً خالی است" in signoff
    assert not re.search(r"Frozen at commit:\s+[0-9a-f]{7}", signoff), (
        "the translation's §17 names a commit as though it were the frozen text; what was frozen "
        "at that commit is the English v1.1"
    )
