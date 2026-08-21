"""One wallet is one entry: the identity rules in ``matching_null``, and what they buy.

Every expected value below is a literal, measured on commit 2672eed's code before the repair and
recorded here. Nothing in this file recomputes an expression the implementation also computes.

The defect class: *an identity key that a boundary collapses silently, so two distinct inputs
become one entry and which one survives depends on iteration order.* Two sites in this package had
it.

**The universe.** Seven wallets, nine numeric dimensions, eight of them held at 0 so
``capital_deployed`` is the only one that moves::

    selected   0xs1 = 0     0xs2 = 1     0xs3 = 2
    controls   0xc2 = 0     0xc3 = 2     0xc4 = 3     0xc1 = 1 *or* 1000

``0xc1`` is the wallet described twice. Spelled ``"0xC1"`` it carries ``capital_deployed = 1`` and
sits exactly on ``0xs2``; spelled ``"0xc1"`` it carries ``1000`` and is nowhere near anything.
Both records lowercase their own address in ``WalletFeatures.__post_init__``, so both agreed with
their key and the mapping branch of ``_resolve_features`` accepted both, keeping whichever the
caller's ``dict`` yielded last. With ``n_primary=1``, the two survivors publish::

    surviving 0xc1   matched sets                             SMD capital_deployed        ESS
    capital 1        0xs1->0xc2  0xs2->0xc1  0xs3->0xc3       0                           3     balanced
    capital 1000     0xs1->0xc2  0xs2->0xc2  0xs3->0xc3       0.37796447300922722721...   1.8   not balanced

Those two rows are pinned below as ``test_the_two_survivors_publish_different_evidence``. They are
what the refusal buys: without it, a caller's ordering chose between them.
"""

from decimal import Decimal as D

import pytest

from contracts import (
    AccountType,
    EdgeOriginStatus,
    LookAheadViolation,
    MatchedSet,
    WindowScore,
)
from matching_null import (
    NUMERIC_DIMENSIONS,
    WalletFeatures,
    build_matched_sets,
    permutation_null_detail,
)
from matching_null.features import MATCHING_DIMENSIONS, require_pre_t0

T0_BLOCK = 18_000_000
SEED = 20260731

UNIVERSE = ["0xs1", "0xs2", "0xs3", "0xc1", "0xc2", "0xc3", "0xc4"]
SELECTED = ["0xs1", "0xs2", "0xs3"]


def features(wallet, capital):
    """One record whose only moving dimension is ``capital_deployed``."""
    values = {dimension: D("0") for dimension in NUMERIC_DIMENSIONS}
    values["capital_deployed"] = D(str(capital))
    return WalletFeatures(
        wallet=wallet,
        account_type=AccountType.EOA,
        values=values,
        as_of_block=T0_BLOCK - 1,
    )


def rest():
    return [
        features("0xs1", 0), features("0xs2", 1), features("0xs3", 2),
        features("0xc2", 0), features("0xc3", 2), features("0xc4", 3),
    ]


NEAR = ("0xC1", 1)      # spelling one: sits exactly on 0xs2
FAR = ("0xc1", 1000)    # spelling two: nowhere near anything


def both_spellings(first, second):
    """A features mapping carrying both spellings of 0xc1, in the given insertion order."""
    mapping = {}
    for spelling, capital in (first, second):
        mapping[spelling] = features(spelling, capital)
    for record in rest():
        mapping[record.wallet] = record
    return mapping


# -- the mapping branch now refuses what the iterable branch always refused -----


def test_a_mapping_that_spells_one_wallet_two_ways_is_refused():
    """The site of the defect. Two keys, one wallet, and no way to say which is the wallet."""
    with pytest.raises(ValueError) as excinfo:
        build_matched_sets(
            SELECTED, UNIVERSE, both_spellings(NEAR, FAR), T0_BLOCK, SEED,
            n_primary=1, n_robustness=0,
        )
    assert "duplicate feature record for wallet 0xc1" in str(excinfo.value)


def test_the_refusal_does_not_depend_on_which_spelling_came_first():
    """A guard conditioned on the ordering the reviewer happened to use is not a guard."""
    with pytest.raises(ValueError) as excinfo:
        build_matched_sets(
            SELECTED, UNIVERSE, both_spellings(FAR, NEAR), T0_BLOCK, SEED,
            n_primary=1, n_robustness=0,
        )
    assert "duplicate feature record for wallet 0xc1" in str(excinfo.value)


def test_both_input_shapes_of_features_now_apply_one_rule():
    """The tell was two branches of one function disagreeing about the same five records.

    The iterable branch always raised on this input. The mapping branch resolved it by iteration
    order. They share a collector now, so they cannot drift apart again.
    """
    mapping = both_spellings(NEAR, FAR)
    records = list(mapping.values())

    with pytest.raises(ValueError) as from_mapping:
        build_matched_sets(SELECTED, UNIVERSE, mapping, T0_BLOCK, SEED,
                           n_primary=1, n_robustness=0)
    with pytest.raises(ValueError) as from_iterable:
        build_matched_sets(SELECTED, UNIVERSE, records, T0_BLOCK, SEED,
                           n_primary=1, n_robustness=0)

    assert str(from_mapping.value) == str(from_iterable.value)


def test_two_identical_records_for_one_wallet_are_still_refused():
    """Refuse on the *collision*, not on the two records disagreeing.

    A guard that fires only when the duplicates differ closes the case a reviewer happened to
    construct and leaves the rule — one wallet is one entry — unstated. It would also put the two
    branches back into disagreement: the iterable branch has never cared whether the duplicates
    agree.
    """
    mapping = both_spellings(("0xC1", 1), ("0xc1", 1))
    assert mapping["0xC1"] == mapping["0xc1"]

    with pytest.raises(ValueError) as excinfo:
        build_matched_sets(SELECTED, UNIVERSE, mapping, T0_BLOCK, SEED,
                           n_primary=1, n_robustness=0)
    assert "duplicate feature record for wallet 0xc1" in str(excinfo.value)


def test_a_case_varying_key_that_is_not_a_duplicate_is_still_accepted():
    """The refusal is on the collision, not on the spelling. ``0xC2`` alone is simply ``0xc2``."""
    mapping = {}
    for record in rest():
        mapping[record.wallet.upper() if record.wallet == "0xc2" else record.wallet] = record
    mapping["0xc1"] = features("0xc1", 1)

    sets, _balance = build_matched_sets(
        SELECTED, UNIVERSE, mapping, T0_BLOCK, SEED, n_primary=1, n_robustness=0
    )
    assert [s.primary_controls for s in sets] == [("0xc2",), ("0xc1",), ("0xc3",)]


# -- what the refusal buys -----------------------------------------------------


@pytest.mark.parametrize(
    "capital,expected_controls,expected_smd,expected_unique,expected_reuse,expected_ess,balanced",
    [
        (1, [("0xc2",), ("0xc1",), ("0xc3",)],
         "0E+38", 3, "0", "3", True),
        (1000, [("0xc2",), ("0xc2",), ("0xc3",)],
         "0.37796447300922722721451653623418006082", 2,
         "0.33333333333333333333333333333333333333", "1.8", False),
    ],
)
def test_the_two_survivors_publish_different_evidence(
    capital, expected_controls, expected_smd, expected_unique, expected_reuse,
    expected_ess, balanced,
):
    """The measured cost of letting iteration order pick the survivor.

    Same seven wallets, same selected list, same seed. Only which ``0xc1`` record survived
    differs, and the published §6.6 balance table flips from *not balanced* to *perfectly
    balanced* while the effective sample size moves from 1.8 to 3.
    """
    mapping = {record.wallet: record for record in rest()}
    mapping["0xc1"] = features("0xc1", capital)

    sets, balance = build_matched_sets(
        SELECTED, UNIVERSE, mapping, T0_BLOCK, SEED, n_primary=1, n_robustness=0
    )

    assert [s.selected for s in sets] == ["0xs1", "0xs2", "0xs3"]
    assert [s.primary_controls for s in sets] == expected_controls
    assert str(balance.smd["capital_deployed"]) == expected_smd
    assert balance.unique_controls == expected_unique
    assert str(balance.control_reuse_rate) == expected_reuse
    assert str(balance.effective_sample_size) == expected_ess
    assert balance.balanced is balanced


# -- the two wallet lists obey the same rule -----------------------------------
#
# ``_distinct_lower`` already refused a repeated address. Nothing pinned it: the whole 96-test
# ``matching_null`` selection stayed green with the refusal disabled, which is how a guard becomes
# the next refactor's casualty.


def test_a_universe_that_names_one_wallet_twice_is_refused():
    """Deduplicating would shrink the control pool without reporting it."""
    mapping = {record.wallet: record for record in rest()}
    mapping["0xc1"] = features("0xc1", 1)

    with pytest.raises(ValueError) as excinfo:
        build_matched_sets(
            SELECTED, UNIVERSE + ["0xC1"], mapping, T0_BLOCK, SEED,
            n_primary=1, n_robustness=0,
        )
    assert "universe contains 0xc1 twice" in str(excinfo.value)


def test_a_selected_list_that_names_one_wallet_twice_is_refused():
    """A duplicate would enter the benchmark twice under one label."""
    mapping = {record.wallet: record for record in rest()}
    mapping["0xc1"] = features("0xc1", 1)

    with pytest.raises(ValueError) as excinfo:
        build_matched_sets(
            SELECTED + ["0XS1"], UNIVERSE, mapping, T0_BLOCK, SEED,
            n_primary=1, n_robustness=0,
        )
    assert "selected contains 0xs1 twice" in str(excinfo.value)


def test_a_forward_per_dimension_timestamp_is_named_by_its_provenance_field():
    """The per-dimension timestamps are checked, and named so they cannot collide.

    ``require_pre_t0`` merges the per-dimension stamps with the wallet-level one before checking
    them. Merged bare, a dimension called ``as_of_timestamp`` would displace the wallet's own
    stamp and one of the four look-ahead checks would disappear on a key collision; the bracketed
    key makes that unwritable. The path had no test at all before this one.
    """
    values = {dimension: D("0") for dimension in NUMERIC_DIMENSIONS}
    record = WalletFeatures(
        wallet="0xc1",
        account_type=AccountType.EOA,
        values=values,
        as_of_block=T0_BLOCK - 1,
        as_of_timestamp=1_695_000_000 - 1,
        dimension_timestamps={"capital_deployed": 1_695_000_000 + 5},
    )
    mapping = {r.wallet: r for r in rest()}
    mapping["0xc1"] = record

    with pytest.raises(LookAheadViolation) as excinfo:
        build_matched_sets(
            SELECTED, UNIVERSE, mapping, T0_BLOCK, SEED,
            n_primary=1, n_robustness=0, t0_timestamp=1_695_000_000,
        )
    message = str(excinfo.value)
    assert "dimension_timestamps[capital_deployed]" in message
    assert "second 1695000005" in message


def test_the_unverifiable_stamp_refusal_names_its_provenance_field_too():
    """The namespacing's second branch, which the test above never reaches.

    ``require_pre_t0`` has two refusals that read the pooled ``stamps`` mapping: the forward-stamp
    one above, and this one — a stamp supplied with no ``t0_timestamp`` to check it against. Merged
    bare, this message says ``capital_deployed``, which in a report reads as a *dimension value*
    rather than as the provenance stamp for one.
    """
    values = {dimension: D("0") for dimension in NUMERIC_DIMENSIONS}
    record = WalletFeatures(
        wallet="0xc1",
        account_type=AccountType.EOA,
        values=values,
        as_of_block=T0_BLOCK - 1,
        dimension_timestamps={"capital_deployed": 1_695_000_005},
    )

    with pytest.raises(LookAheadViolation) as excinfo:
        require_pre_t0(record, T0_BLOCK, None)

    message = str(excinfo.value)
    assert "carries timestamp(s) (dimension_timestamps[capital_deployed])" in message
    assert "no t0_timestamp was supplied" in message


def test_a_provenance_key_that_could_collide_cannot_be_constructed():
    """The residue the namespacing comment used to assert away, pinned as a fact.

    The comment claimed the bare merge would let a dimension named ``as_of_timestamp`` displace the
    wallet's own stamp. It cannot: ``dimension_timestamps`` keys are checked against the ten §6.6
    dimensions, and ``as_of_timestamp`` is not one of them, so the colliding record is refused a
    layer earlier. The namespacing buys message legibility, not that refusal — and this test is
    what stops the stronger claim being written back in.
    """
    assert "as_of_timestamp" not in MATCHING_DIMENSIONS

    values = {dimension: D("0") for dimension in NUMERIC_DIMENSIONS}
    with pytest.raises(ValueError) as excinfo:
        WalletFeatures(
            wallet="0xc1",
            account_type=AccountType.EOA,
            values=values,
            as_of_block=T0_BLOCK - 1,
            as_of_timestamp=1_695_000_000 - 1,
            dimension_timestamps={"as_of_timestamp": 1_695_000_000 + 5},
        )
    assert "not §6.6 dimensions: as_of_timestamp" in str(excinfo.value)


# -- the same class in the permutation null ------------------------------------

#: Two sets of deliberately different size, so a swapped position draws from a different range.
SET_A = MatchedSet(selected="0xs1", primary_controls=("0xc1", "0xc2"))
SET_B = MatchedSet(selected="0xs2", primary_controls=("0xd0", "0xd1", "0xd2", "0xd3", "0xd4"))


def statistic(labelled):
    """One point per set whose label has landed on a ``0xd`` control. Asymmetric on purpose."""
    total = sum(1 for s in labelled if s.selected.startswith("0xd"))
    return WindowScore(
        column="leader",
        window=1,
        mean_advantage=D(total),
        median_advantage=D(total),
        first_hour_edge_share=D("0.5"),
        positive_edge_contribution=D("1"),
        edge_origin_status=EdgeOriginStatus.VALID,
    )


def seed_fn(purpose, index):
    return 7000 + index


def test_the_null_is_a_function_of_the_sets_not_of_their_order():
    """``_uniform_index`` keys the draw on a set's position, so the order was load-bearing.

    Measured before the repair: the same two sets handed over in the two possible orders published
    a null pass rate of 0.9 and of 0.8. 0.9 is the value both orders give now.
    """
    forward = permutation_null_detail(
        [SET_A, SET_B], statistic, 20, seed_fn, "leader", 1
    ).to_contract()
    reversed_ = permutation_null_detail(
        [SET_B, SET_A], statistic, 20, seed_fn, "leader", 1
    ).to_contract()

    assert str(forward.null_pass_rate) == "0.9"
    assert str(reversed_.null_pass_rate) == "0.9"
    assert forward == reversed_


def test_two_matched_sets_for_one_wallet_are_refused():
    """A duplicate is relabelled twice and enters the null twice under one label.

    Measured before the repair: admitting it published a null pass rate of 0.75 where the honest
    two-set null publishes 0.9.
    """
    with pytest.raises(ValueError) as excinfo:
        permutation_null_detail([SET_A, SET_A, SET_B], statistic, 20, seed_fn, "leader", 1)
    assert "both name 0xs1 as the selected wallet" in str(excinfo.value)


def test_a_duplicate_spelled_two_ways_is_the_same_duplicate():
    """``MatchedSet`` is seam-frozen and folds no case, so the rule is applied here."""
    shouty = MatchedSet(selected="0xS1", primary_controls=("0xc1", "0xc2"))
    with pytest.raises(ValueError) as excinfo:
        permutation_null_detail([SET_A, shouty, SET_B], statistic, 20, seed_fn, "leader", 1)
    assert "both name 0xs1 as the selected wallet" in str(excinfo.value)


def test_a_selected_wallet_that_is_not_an_address_is_a_typed_refusal():
    """Two sets are the same set when they name the same address; that has to be comparable."""
    with pytest.raises(TypeError) as excinfo:
        permutation_null_detail(
            [MatchedSet(selected=7, primary_controls=("0xc1",))],
            statistic, 5, seed_fn, "leader", 1,
        )
    assert "must be a wallet address string" in str(excinfo.value)


def test_the_non_address_refusal_names_the_set_and_precedes_every_draw():
    """The second half of the same guard: *which* set, and *before* anything was computed.

    Deleting the ``isinstance`` check leaves the input refused all the same — ``.lower()`` raises
    ``AttributeError`` from the very next line — so a test that only asserts "it raises" does not
    pin the guard. What the guard adds is a message naming ``sets[1]`` rather than a traceback
    naming nothing, and a sweep that finishes before ``statistic_fn`` is called once. The counter
    below is the evidence for the second half: an ``AttributeError`` from inside the draw loop
    would arrive with runs already scored.
    """
    calls = []

    def counted(labelled):
        calls.append(labelled)
        return statistic(labelled)

    with pytest.raises(TypeError) as excinfo:
        permutation_null_detail(
            [SET_A, MatchedSet(selected=7, primary_controls=("0xc1", "0xc2")), SET_B],
            counted, 5, seed_fn, "leader", 1,
        )
    assert "sets[1].selected must be a wallet address string, got int" in str(excinfo.value)
    assert calls == []


# -- the sort key is case-folded, and that is a §8.3 input ----------------------

#: Two sets whose selected addresses order differently under ``str`` than under ``str.lower``:
#: ``"0xB1" < "0xa2"`` because ``B`` is 0x42 and ``a`` is 0x61, while ``"0xb1" > "0xa2"``.
MIXED = MatchedSet(selected="0xB1", primary_controls=("0xc1", "0xc2"))
FOLDED = MatchedSet(selected="0xb1", primary_controls=("0xc1", "0xc2"))
OTHER = MatchedSet(selected="0xa2", primary_controls=("0xd0", "0xd1", "0xd2", "0xd3", "0xd4"))


def test_respelling_one_selected_address_does_not_move_the_null():
    """``0xB1`` and ``0xb1`` are one wallet, so they must draw the same null.

    ``_uniform_index`` keys the draw on a set's *position*, and the entry point puts the sets in
    address order before anything is drawn. Sorting on the raw string instead of the case-folded
    one is order-independent but wallet-*spelling*-dependent, which is worse than it sounds:
    measured on these two sets, a raw sort publishes a null pass rate of 0.9 for ``0xB1`` and 0.8
    for ``0xb1``. Both are 0.8 under the case-folded sort, and 0.8 is the value the honest ordering
    gives. §8.3 locks the threshold against this rate.
    """
    shouty = permutation_null_detail(
        [MIXED, OTHER], statistic, 20, seed_fn, "leader", 1
    ).to_contract()
    quiet = permutation_null_detail(
        [FOLDED, OTHER], statistic, 20, seed_fn, "leader", 1
    ).to_contract()

    assert str(shouty.null_pass_rate) == "0.8"
    assert str(quiet.null_pass_rate) == "0.8"
    assert shouty.null_statistics == quiet.null_statistics


def test_mixed_case_sets_are_still_a_function_of_the_sets_and_not_their_order():
    """The ordering rule and the case-folding rule are two guards, and this pins them together.

    ``test_the_null_is_a_function_of_the_sets_not_of_their_order`` uses two already-lowercase
    addresses, so it goes red when the ``sorted`` disappears and stays green when only the
    ``.lower()`` does. These addresses discriminate both.
    """
    forward = permutation_null_detail(
        [MIXED, OTHER], statistic, 20, seed_fn, "leader", 1
    ).to_contract()
    backward = permutation_null_detail(
        [OTHER, MIXED], statistic, 20, seed_fn, "leader", 1
    ).to_contract()

    assert str(forward.null_pass_rate) == "0.8"
    assert forward == backward
