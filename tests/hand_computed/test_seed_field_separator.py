"""``derive_child_seed`` flattens three components into one string. Is the flattening injective?

The seed derivation is the one place in this repository where a compound identity — ``(commit,
purpose, index)`` — is deliberately collapsed into a scalar. That is fine only if the collapse is
injective, and joining with ``|`` is injective only if no component can contain ``|``.

What was measured, and it is two different answers:

* **Within one commit it was already injective, and no refusal was needed.** ``index`` is an
  ``int``, so ``str(index)`` carries no ``|``; the last separator therefore splits the index off
  and everything between the first and the last is the purpose, whatever it contains. That is the
  case the permutation null depends on — ``matching_null.permutation_null_detail`` checks that its
  1,000 runs carry distinct seeds, and all 1,000 share a commit — so the null was never at risk.
  ``test_within_one_commit_...`` below pins it over purposes that deliberately contain separators.

* **Across commits it collided, and the path is open at the public API.** ``RunStore.open_run``
  requires a non-empty commit and does not require a hex SHA, so a commit of ``"abc|null.leader"``
  with purpose ``"window1"`` derived exactly the seed of commit ``"abc"`` with purpose
  ``"null.leader|window1"``. Two runs that must be separate experiments would draw the identical
  "independent" numbers — against the guarantee this module's own header gives, that a re-run at a
  new commit does not inherit the old draws.

Closed by refusing the separator rather than by re-encoding. Length-prefixing would have been the
more thorough fix and would have changed **every** seed ever derived, including the one recorded
verbatim as ``RunRecord.SEED_RULE`` (``msg=f'{commit}|{purpose}|{index}'``) — the sentence a reader
reproduces a frozen run from. The literal in ``test_the_derivation_is_unchanged`` is what pins that
nothing moved.
"""

import pytest

from phase0.seeds import FIELD_SEPARATOR, derive_child_seed, derive_child_seeds

MASTER = "00" * 32


def test_the_derivation_is_unchanged():
    """A literal, computed independently of this code, so a re-encoding cannot pass unnoticed.

    ``int.from_bytes(hmac.new(bytes.fromhex("00"*32), b"abc1234|null.leader.window1|0",
    sha256).digest(), "big")``. Every recorded run's seeds, and the pinned expectation in
    ``tests/hand_computed/test_execution.py``, depend on this value not moving.
    """
    assert derive_child_seed(MASTER, "abc1234", "null.leader.window1", 0) == (
        92736452766257121398302297772483599402759848303582408804064807584757315031642
    )


def test_the_separator_is_the_one_recorded_in_the_run_record():
    assert FIELD_SEPARATOR == "|"


# -- what was reachable, and is now refused ---------------------------------------


def test_the_two_constructions_that_derived_one_seed_are_both_refused():
    """Before the refusal both of these returned
    91057054122863460495179724698494709738616472449431008072485148703461237999389."""
    with pytest.raises(ValueError) as commit_side:
        derive_child_seed(MASTER, "abc|null.leader", "window1", 0)
    assert "commit may not contain" in str(commit_side.value)

    with pytest.raises(ValueError) as purpose_side:
        derive_child_seed(MASTER, "abc", "null.leader|window1", 0)
    assert "purpose may not contain" in str(purpose_side.value)


def test_the_refusal_says_what_a_collision_would_cost():
    message = str(pytest.raises(
        ValueError, derive_child_seed, MASTER, "abc|x", "purpose", 0).value)
    assert "the identical 'independent' numbers" in message
    assert "RunRecord.SEED_RULE" in message


def test_derive_child_seeds_refuses_the_same_way():
    """The plural form is what a null distribution actually calls; it must not have its own door."""
    with pytest.raises(ValueError):
        derive_child_seeds(MASTER, "abc", "null.leader|window1", 3)


def test_an_ordinary_purpose_and_a_hex_commit_are_untouched():
    seeds = derive_child_seeds(MASTER, "3f1c9a" + "0" * 34, "null.follower_adjusted.window4", 4)
    assert len(set(seeds)) == 4
    assert seeds[0] == derive_child_seed(MASTER, "3f1c9a" + "0" * 34,
                                         "null.follower_adjusted.window4", 0)


# -- what was never reachable, pinned so the claim above is checked ---------------


def test_within_one_commit_the_flattening_was_already_injective():
    """The evidence for *not* re-encoding: the null's invariant never depended on the refusal.

    Purposes carrying separators are used here on purpose. They are refused at the public entry
    point now, so this walks the same domain the old code accepted by joining the message the same
    way the module does, and asserts no two triples land on one message. A collision here would
    mean two of a distribution's 1,000 "independent" draws were the same numbers.
    """
    commit = "abc"
    messages = {}
    for purpose in ("p", "p|1", "p|1|2", "null.leader.window1", "null.leader.window1|0", "|"):
        for index in range(30):
            message = FIELD_SEPARATOR.join((commit, purpose, str(index)))
            assert message not in messages, (
                "{!r} and {!r} flatten onto the same message".format(
                    messages.get(message), (purpose, index))
            )
            messages[message] = (purpose, index)
    assert len(messages) == 180


def test_distinct_purposes_indices_and_commits_still_derive_distinct_seeds():
    base = derive_child_seed(MASTER, "abc1234", "null.leader.window1", 0)
    assert base != derive_child_seed(MASTER, "abc1234", "null.leader.window1", 1)
    assert base != derive_child_seed(MASTER, "abc1234", "null.follower.window1", 0)
    assert base != derive_child_seed(MASTER, "def5678", "null.leader.window1", 0)


def test_the_str_coercion_residue_is_real_and_is_stated():
    """``_require`` coerces with ``str()``, so ``1234`` and ``"1234"`` are one input here.

    Left rather than refused: they name one commit. Pinned rather than left silent, because the
    injectivity claim in the docstring is over the *string* forms and this is exactly where that
    qualification bites.
    """
    assert (derive_child_seed(MASTER, 1234, "p", 0)
            == derive_child_seed(MASTER, "1234", "p", 0))
