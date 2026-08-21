"""Tickets 25-28 end to end: four windows measured, frozen, ranked, audited, handed over.

The composition here is the whole of tickets 25-28, and it is longer than what ``pipeline`` holds.
``src/pipeline/stages/step0.py`` now wires the first half of it — ``step0.universe`` composes
``measure_window`` over the design's four windows and returns the report — so the *measurement* step
has a composition root in ``src``. Everything after it does not: freezing, ranking, sealing and the
look-ahead audit are ticket 29's work, and this module is still the only place they are composed at
all. That is worth stating plainly rather than implying the wiring exists:

    ``universe.freeze.require_step0_complete`` is a **call**, not a shape.
    :func:`universe.select.rank_and_select` takes four parameters and the Step 0 report is not one
    of them, so a composition root that never calls it ranks a window whose three siblings were
    never measured and nothing in the package notices. What makes that survivable rather than
    decorative is that the omission is visible in one place, and the sequence below is where it is
    pinned. When ``pipeline`` grows the step, the same pin belongs there too.

The stage order is the ticket order and it is not a matter of taste:

    screen -> classify -> census -> measure -> report -> freeze -> bind scores -> rank -> audit

Nothing after ``freeze`` can widen the population and nothing before ``rank`` can see past ``T0``.
"""

import inspect

import pytest

from contracts import AccountType

import universe_fixtures as F
from universe import (
    MINIMUM_ELIGIBLE_UNIVERSE,
    ARTIFACT_KIND,
    PRODUCED_BY,
    ClampState,
    InsufficientCandidateUniverse,
    PreRegisteredReplacementRule,
    PreT0Workspace,
    ReplacementRegistry,
    ReplacementSelector,
    Step0Incomplete,
    T0Instant,
    TrainingWindow,
    UniverseFreezeViolation,
    UnregisteredReplacement,
    WindowStatus,
    basket_artifact,
    for_universe,
    freeze_universe,
    look_ahead_audit,
    matching_inputs,
    rank_and_select,
    replace_window,
    require_frozen_membership,
    require_step0_complete,
    step0_report,
)
from universe.forward import (
    BaselineFact,
    disclose_for_churn,
    forward_ledger,
    forward_period_days,
    forward_report,
    ForwardActivity,
    ForwardCount,
    ForwardT0Instant,
    ForwardWindowKey,
)


def forward_key(window=F.W1):
    """§6.3's window as the **post-T0 side** names it.

    ``ForwardWindowKey`` and ``WindowKey`` have equal member names and are not interchangeable: a
    forward record keyed by the selection side's enum would be a record keyed by an object every
    selection function also accepts. Converting through ``.value`` is the whole of the crossing,
    and it is spelled out here rather than hidden in a fixture so the two families stay visible.
    """
    return ForwardWindowKey(window.key.value)


def forward_t0(window=F.W1):
    """The selection instant, restated in the post-T0 side's own value type."""
    return ForwardT0Instant(block=window.t0.block, timestamp=window.t0.timestamp)

PARAMETER_FREEZE = "params-2026-07-31-abcdef"

#: Five accounts per window, with distinct valid-buy counts so the activity bands are non-trivial
#: and no two scores tie.
ACCOUNTS = (
    (1, 120, 25, AccountType.EOA),
    (2, 15, 30, AccountType.SAFE),          # carried in by the lower buffer
    (3, 240, 200, AccountType.ERC4337),
    (4, 1_100, 700, AccountType.EOA),       # carried in by the upper buffer
    (5, 300, 900, AccountType.OTHER_CONTRACT),
)


def _window_observations(window):
    return [
        F.observation(F.address(index), potential_buys=potential, valid_buys=valid,
                      window=window, account_type=account_type)
        for index, potential, valid, account_type in ACCOUNTS
    ]


def _measure_all_four():
    """Step 0 for every §6.3 window, from one dataset snapshot."""
    measurements = {}
    verdicts = {}
    for window in (F.W1, F.W2, F.W3, F.W4):
        measurement, window_verdicts, _census, _screen = F.measured(
            _window_observations(window), window=window)
        measurements[window.key] = measurement
        verdicts[window.key] = window_verdicts
    return measurements, verdicts


def _report(measurements):
    return step0_report(F.DESIGN, tuple(measurements.values()), PARAMETER_FREEZE, F.SNAPSHOT)


def _scores(universe, window):
    """One ``buy_quality_30d`` per frozen member, all distinct so ranking is unambiguous."""
    return [
        F.score(member.wallet, str(member.valid_buys), member.valid_buys, window=window)
        for member in universe.members
    ]


def _compose(window=F.W1, seed=F.SEED):
    """The whole sequence, in the order the tickets impose."""
    measurements, verdicts = _measure_all_four()
    report = _report(measurements)
    universe = freeze_universe(measurements[window.key], verdicts[window.key], F.SNAPSHOT,
                               revision=F.REVISION)
    require_step0_complete(report, universe)
    inputs = for_universe(universe, _scores(universe, window))
    basket = F.basket(universe, inputs, seed)
    audit = look_ahead_audit(universe, inputs, basket)
    return report, universe, inputs, basket, audit


# -- ticket 26: the four-window measurement --------------------------------------


def test_step_0_measures_every_count_the_pre_registration_names():
    measurements, _verdicts = _measure_all_four()
    measurement = measurements[F.W1.key]

    assert measurement.total_active_accounts == 50
    assert measurement.accounts_with_at_least_one_valid_buy == 5
    assert measurement.accounts_in_valid_buy_band == 5
    assert measurement.eligible_eoas == 2
    assert measurement.eligible_safes == 1
    assert measurement.eligible_erc4337 == 1
    assert measurement.eligible_other_contracts == 1
    assert measurement.excluded_infrastructure == 0
    assert measurement.eligible_universe_size == 5


def test_the_report_covers_all_four_windows_from_one_snapshot():
    measurements, _verdicts = _measure_all_four()
    report = _report(measurements)
    assert sorted(k.value for k in F.DESIGN.keys) == [
        "W1_2023H1", "W2_2023H2", "W3_2024H1", "W4_2024H2"]
    assert len(report.measurements) == 4
    assert report.dataset_snapshot == F.SNAPSHOT


def test_a_report_over_three_windows_is_refused():
    """A subset would let the design advance on the windows that happened to look healthy."""
    measurements, _verdicts = _measure_all_four()
    with pytest.raises(ValueError):
        step0_report(F.DESIGN, tuple(measurements.values())[:3], PARAMETER_FREEZE, F.SNAPSHOT)


def test_the_counts_are_reproducible_from_the_frozen_snapshot():
    """Ticket 26: a re-run returns identical numbers. Compared by digest, not by eyeball."""
    first, _ = _measure_all_four()
    second, _ = _measure_all_four()
    assert _report(first).digest == _report(second).digest


def test_a_report_mixing_two_snapshots_is_refused():
    measurements, _verdicts = _measure_all_four()
    other, _verdicts_other = _measure_all_four()
    mixed = list(measurements.values())[:3]
    replacement, _v, _c, _s = F.measured(_window_observations(F.W4), window=F.W4,
                                         snapshot="dune-2026-08-01")
    with pytest.raises(ValueError):
        step0_report(F.DESIGN, tuple(mixed) + (replacement,), PARAMETER_FREEZE, F.SNAPSHOT)
    assert other is not measurements


def test_the_base_rate_comparison_is_reported_rather_than_left_implicit():
    """§13.7: the target population may simply not exist at the size assumed."""
    measurements, _verdicts = _measure_all_four()
    base_rate = measurements[F.W1.key].base_rate
    assert base_rate.statement.strip()
    assert base_rate.source.strip()
    assert base_rate.measured_size == 5


def test_the_section_6_1_and_6_2_conflict_over_contract_accounts_is_reported():
    """It moves the eligible universe size, so it is raised rather than settled silently."""
    measurements, _verdicts = _measure_all_four()
    measurement = measurements[F.W1.key]
    assert "eligible_other_contracts" in measurement.spec_discrepancy
    assert measurement.eligible_other_contracts == 1


def test_step_0_produces_no_ranking_of_its_own():
    """Ticket 26's last criterion: no wallet ranking and no forward number in this stage."""
    measurements, _verdicts = _measure_all_four()
    measurement = measurements[F.W1.key]
    fields = set(measurement.__dataclass_fields__)
    for forbidden in ("rank", "ranking", "selected", "basket", "forward", "score"):
        assert not any(forbidden in name for name in fields), fields


# -- ticket 26: the stopping condition and the replacement rule ------------------


def test_every_fixture_window_carries_the_insufficient_status():
    measurements, _verdicts = _measure_all_four()
    report = _report(measurements)
    assert report.permits_ranking is False
    assert sorted(k.value for k in report.insufficient_windows) == [
        "W1_2023H1", "W2_2023H2", "W3_2024H1", "W4_2024H2"]
    for measurement in report.measurements:
        assert measurement.status is WindowStatus.INSUFFICIENT_CANDIDATE_UNIVERSE
        assert measurement.eligible_universe_size < MINIMUM_ELIGIBLE_UNIVERSE


def test_ranking_a_short_window_without_a_revision_is_refused():
    """§6.1 is a statement about the *design*, so a short slot blocks the whole report."""
    measurements, verdicts = _measure_all_four()
    report = _report(measurements)
    with pytest.raises(InsufficientCandidateUniverse):
        freeze_universe(measurements[F.W1.key], verdicts[F.W1.key], F.SNAPSHOT, revision=None)

    revised = freeze_universe(measurements[F.W1.key], verdicts[F.W1.key], F.SNAPSHOT,
                              revision=F.REVISION)
    assert require_step0_complete(report, revised) is True


def test_ranking_against_a_report_from_another_snapshot_is_refused():
    """The counts that authorise the ranking and the membership that is ranked must be one dataset."""
    measurements, _verdicts = _measure_all_four()
    report = _report(measurements)

    elsewhere, elsewhere_verdicts, _census, _screen = F.measured(
        _window_observations(F.W1), window=F.W1, snapshot="dune-2026-08-01")
    universe = freeze_universe(elsewhere, elsewhere_verdicts, "dune-2026-08-01",
                               revision=F.REVISION)
    with pytest.raises(Step0Incomplete) as raised:
        require_step0_complete(report, universe)
    assert "two different frozen datasets" in str(raised.value)


def test_ranking_a_window_that_was_re_measured_is_refused():
    """One of the two was re-measured, and the eligible universe size is now whichever a reader opens."""
    measurements, _verdicts = _measure_all_four()
    report = _report(measurements)

    smaller = _window_observations(F.W1)[:3]
    remeasured, remeasured_verdicts, _census, _screen = F.measured(smaller, window=F.W1)
    universe = freeze_universe(remeasured, remeasured_verdicts, F.SNAPSHOT, revision=F.REVISION)
    assert universe.measurement.eligible_universe_size == 3
    with pytest.raises(Step0Incomplete) as raised:
        require_step0_complete(report, universe)
    assert "re-measured" in str(raised.value)


#: The pre-registered rule, and the window it derives. W1 runs 2023-01-01 -> 2023-07-01, so its
#: baseline is 15,638,400 seconds; the immediately preceding period therefore starts at
#: 2022-07-01 and ends at 2023-01-01. Both figures are written out rather than derived.
REPLACEMENT_RULE = PreRegisteredReplacementRule(
    rule_id="replace-with-preceding-half",
    statement=("if a window's eligible universe is below §6.1's floor, the slot is re-measured "
               "over the immediately preceding period of equal length"),
    parameter_freeze_hash=PARAMETER_FREEZE,
    selector=ReplacementSelector.IMMEDIATELY_PRECEDING_PERIOD,
    registered_at_commit="0000abc",
    registered_before_block=16_000_000,
)

REGISTRY = ReplacementRegistry(rules=(REPLACEMENT_RULE,),
                               parameter_freeze_hash=PARAMETER_FREEZE)

DERIVED_REPLACEMENT = TrainingWindow(
    key=F.W1.key,
    t0=T0Instant(block=16_308_190, timestamp=1_672_531_200),   # 2023-01-01T00:00:00Z
    baseline_start_block=15_000_000,
    baseline_start_ts=1_656_892_800,                            # 2022-07-01T00:00:00Z
    forward_end_block=17_600_000,
    forward_end_ts=1_688_169_600,
)


def test_a_replacement_window_the_pre_registered_rule_derives_is_accepted():
    measurements, _verdicts = _measure_all_four()
    report = _report(measurements)
    revised = replace_window(F.DESIGN, report, REPLACEMENT_RULE.rule_id, REGISTRY,
                             DERIVED_REPLACEMENT)
    slot = revised.window(F.W1.key)
    assert slot.t0.timestamp == 1_672_531_200
    assert slot.replaced_from is F.W1.key
    assert len(revised.replacements) == 1
    assert revised.replacements[0].rule_id == REPLACEMENT_RULE.rule_id


def test_an_unregistered_replacement_window_is_a_raise():
    """Ticket 26's own sentence: the system refuses an unregistered replacement.

    A raise and not a status, and the difference is the whole point. Choosing a window after seeing
    the data is not a measurement outcome the run may carry — it is a defect in what assembled the
    call, and it names the rule, the input and what it costs.
    """
    measurements, _verdicts = _measure_all_four()
    report = _report(measurements)
    with pytest.raises(UnregisteredReplacement) as raised:
        replace_window(F.DESIGN, report, "chosen-this-morning", REGISTRY, DERIVED_REPLACEMENT)
    message = str(raised.value)
    assert "pre-registered" in message
    assert "chosen-this-morning" in message


def test_a_replacement_that_is_not_the_window_the_rule_derives_is_refused():
    """The rule is what was pre-registered, so the window it derives is the only one it authorises."""
    measurements, _verdicts = _measure_all_four()
    report = _report(measurements)
    somewhere_else = TrainingWindow(
        key=F.W1.key,
        t0=T0Instant(block=16_000_000, timestamp=1_670_000_000),
        baseline_start_block=15_000_000,
        baseline_start_ts=1_650_000_000,
        forward_end_block=17_600_000,
        forward_end_ts=1_688_169_600,
    )
    with pytest.raises(UnregisteredReplacement):
        replace_window(F.DESIGN, report, REPLACEMENT_RULE.rule_id, REGISTRY, somewhere_else)


def test_a_rule_registered_under_another_parameter_freeze_is_not_registered():
    measurements, _verdicts = _measure_all_four()
    report = _report(measurements)
    other_freeze = "params-2026-08-02-999999"
    elsewhere = ReplacementRegistry(
        rules=(PreRegisteredReplacementRule(
            rule_id=REPLACEMENT_RULE.rule_id,
            statement=REPLACEMENT_RULE.statement,
            parameter_freeze_hash=other_freeze,
            selector=REPLACEMENT_RULE.selector,
            registered_at_commit=REPLACEMENT_RULE.registered_at_commit,
            registered_before_block=REPLACEMENT_RULE.registered_before_block,
        ),),
        parameter_freeze_hash=other_freeze,
    )
    with pytest.raises(UnregisteredReplacement):
        replace_window(F.DESIGN, report, REPLACEMENT_RULE.rule_id, elsewhere,
                       DERIVED_REPLACEMENT)


def test_a_rule_registered_after_t0_had_passed_is_not_pre_registered():
    measurements, _verdicts = _measure_all_four()
    report = _report(measurements)
    too_late = PreRegisteredReplacementRule(
        rule_id="registered-after-the-fact",
        statement=REPLACEMENT_RULE.statement,
        parameter_freeze_hash=PARAMETER_FREEZE,
        selector=ReplacementSelector.IMMEDIATELY_PRECEDING_PERIOD,
        registered_at_commit="0000abc",
        registered_before_block=F.W1.t0.block + 1,
    )
    registry = ReplacementRegistry(rules=(too_late,), parameter_freeze_hash=PARAMETER_FREEZE)
    with pytest.raises(UnregisteredReplacement) as raised:
        replace_window(F.DESIGN, report, too_late.rule_id, registry, DERIVED_REPLACEMENT)
    assert "already see" in str(raised.value)


def test_a_fresher_replacement_window_is_refused_even_under_a_registered_rule():
    measurements, _verdicts = _measure_all_four()
    report = _report(measurements)
    fresher = TrainingWindow(
        key=F.W1.key,
        t0=T0Instant(block=18_000_000, timestamp=1_700_000_000),
        baseline_start_block=16_308_190,
        baseline_start_ts=1_684_000_000,
        forward_end_block=18_900_000,
        forward_end_ts=1_703_980_800,
    )
    with pytest.raises(UnregisteredReplacement) as raised:
        replace_window(F.DESIGN, report, REPLACEMENT_RULE.rule_id, REGISTRY, fresher)
    assert "fresher" in str(raised.value)


# -- ticket 27: the freeze -------------------------------------------------------


def test_the_universe_is_frozen_under_an_identifier_later_stages_pin():
    _report_, universe, _inputs, basket, audit = _compose()
    assert universe.snapshot_id == basket.snapshot_id == audit.snapshot_id
    assert len(universe.snapshot_id) == 64


def test_the_snapshot_identifier_moves_when_the_membership_does():
    """Substitution keeps the count; what catches it is the identity moving."""
    measurements, verdicts = _measure_all_four()
    original = freeze_universe(measurements[F.W1.key], verdicts[F.W1.key], F.SNAPSHOT,
                               revision=F.REVISION)
    substituted = tuple(
        m if index else type(m)(wallet=F.address(99), account_type=m.account_type,
                                valid_buys=m.valid_buys)
        for index, m in enumerate(original.members)
    )
    replaced = type(original)(window=original.window,
                              members=tuple(sorted(substituted, key=lambda m: m.wallet)),
                              measurement=original.measurement,
                              dataset_snapshot=F.SNAPSHOT, revision=F.REVISION)
    assert len(replaced.members) == len(original.members)
    assert replaced.snapshot_id != original.snapshot_id


def test_a_wallet_from_outside_the_frozen_universe_is_refused():
    _report_, universe, _inputs, _basket, _audit = _compose()
    with pytest.raises(UniverseFreezeViolation):
        require_frozen_membership(universe, [F.address(999)], "a hand-built control pool")


def test_the_benchmark_pool_is_the_frozen_universe_and_comes_from_one_object():
    """Ticket 27: controls are subject to exactly the same survivorship constraints.

    The two arguments ``matching_null.build_matched_sets`` wants cannot come from different
    snapshots, because there is no way to obtain them separately: this is the only function in the
    package that produces a control pool, and its only source of wallets is the frozen membership.
    """
    _report_, universe, _inputs, basket, _audit = _compose()
    handoff = matching_inputs(universe, basket)

    assert handoff.universe_wallets == universe.wallets
    assert handoff.selected == basket.wallets
    assert handoff.snapshot_id == universe.snapshot_id
    assert handoff.t0_block == F.W1.t0.block
    assert all(isinstance(w, str) and w == w.lower() for w in handoff.universe_wallets)


def test_a_basket_from_another_snapshot_cannot_be_handed_over():
    _report_, universe, _inputs, basket, _audit = _compose()
    _r2, other_universe, _i2, other_basket, _a2 = _compose(window=F.W2)
    assert other_universe.snapshot_id != universe.snapshot_id
    with pytest.raises(UniverseFreezeViolation):
        matching_inputs(universe, other_basket)
    assert basket.window_key is F.W1.key


# -- ticket 28: the basket -------------------------------------------------------


def test_rank_and_select_has_exactly_four_parameters_and_no_fifth():
    """The signature is the barrier.

    No ``**kwargs``, no ``key=``, no ``filter=``, no ``min_activity=``, no ``as_of=``. There is no
    parameter through which a second criterion or a forward fact could arrive, so adding one is a
    diff a reviewer has to refuse rather than a default somebody widened.
    """
    signature = inspect.signature(rank_and_select)
    assert list(signature.parameters) == ["workspace", "inputs", "seed", "commit"]
    assert signature.parameters["workspace"].annotation is PreT0Workspace
    for parameter in signature.parameters.values():
        assert parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert parameter.default is inspect.Parameter.empty


def test_the_selected_count_is_derived_per_window_and_recorded():
    _report_, universe, _inputs, basket, _audit = _compose()
    assert basket.eligible_universe_size == 5
    assert basket.requested_count == 250
    assert basket.clamp_state is ClampState.CLAMPED_LOW
    assert basket.short_by == 245
    assert basket.metric == "buy_quality_30d"


def test_the_basket_is_ranked_on_buy_quality_and_on_nothing_else():
    """Valid-buy counts 25, 30, 200, 700, 900 — and the scores are those same numbers.

    So the ranking is 900, 700, 200, 30, 25, descending. If anything else entered the ranking, the
    order would differ from the score order and this literal would move.
    """
    _report_, _universe, _inputs, basket, _audit = _compose()
    assert [str(s.value) for s in basket.selections] == ["900", "700", "200", "30", "25"]
    assert [s.rank for s in basket.selections] == [1, 2, 3, 4, 5]
    assert [s.valid_buys for s in basket.selections] == [900, 700, 200, 30, 25]


def test_the_activity_band_composition_of_the_basket_is_reported():
    """§10's three bands, from the **frozen** valid-buy counts: 25 and 30; 200; 700 and 900."""
    _report_, _universe, _inputs, basket, _audit = _compose()
    composition = basket.band_composition
    assert (composition.b_20_99, composition.b_100_499, composition.b_500_1000) == (2, 1, 2)
    assert composition.selected == 5


def test_selection_is_reproducible_from_the_same_snapshot_commit_and_seed():
    """Ticket 28's criterion, checked on the artefact hash rather than on the object."""
    first = basket_artifact(_compose(seed=F.SEED)[3])
    second = basket_artifact(_compose(seed=F.SEED)[3])
    assert first["payload_hash"] == second["payload_hash"]
    assert first["kind"] == ARTIFACT_KIND
    assert first["produced_by"] == PRODUCED_BY


def test_the_basket_artefact_is_versioned_and_pinnable():
    """The payload is canonical form, so every number is a string — that is the seam's rule, not a
    convenience: a canonical artefact has one spelling per value and no float anywhere in it."""
    _report_, universe, _inputs, basket, _audit = _compose()
    artifact = basket_artifact(basket)
    payload = artifact["payload"]
    assert payload["snapshot_id"] == universe.snapshot_id
    assert payload["step0_digest"] == basket.step0_digest
    assert payload["metric"] == "buy_quality_30d"
    assert payload["seed"] == "42"
    assert payload["commit"] == F.COMMIT
    assert payload["eligible_universe_size"] == "5"
    assert payload["requested_count"] == "250"
    assert payload["clamp_state"] == "CLAMPED_LOW"
    assert payload["activity_bands"] == {"20-99": "2", "100-499": "1", "500-1000": "2"}
    assert payload["universe_schema_version"] == "universe-v1"
    assert len(payload["selections"]) == 5
    assert payload["selections"][0]["rank"] == "1"
    assert payload["selections"][0]["value"] == "900"


def test_the_basket_artefact_moves_when_the_step_0_measurement_does():
    """A re-run whose counts moved produces a basket that says so, not one that merely differs."""
    _r1, _u1, _i1, w1_basket, _a1 = _compose(window=F.W1)
    _r2, _u2, _i2, w2_basket, _a2 = _compose(window=F.W2)
    assert w1_basket.step0_digest != w2_basket.step0_digest


def test_the_basket_artefact_is_pinnable_but_the_manifest_has_nowhere_to_pin_it():
    """Half of ticket 28's criterion holds today, and the other half is a frozen-seam change.

    What holds: the artefact carries a ``payload_hash`` in exactly the form every hash field on
    :class:`contracts.FreezeManifest` carries, so a reviewer who did not run the selection can
    check that a basket is the basket.

    What does not: ``FreezeManifest`` has no field for it. §9.6's manifest pins the golden set, the
    validation report, the config and the seed, and there is no ``selected_basket_hash``. Adding
    one is an edit to ``src/contracts/``, which is the frozen seam and is not this ticket's to
    make. Recorded here rather than asserted away — a test claiming the basket is manifest-pinned
    would be claiming a field that does not exist.
    """
    from contracts import FreezeManifest

    _report_, _universe, _inputs, basket, _audit = _compose()
    artifact = basket_artifact(basket)
    digest = artifact["payload_hash"]
    assert len(digest) == 64 and int(digest, 16) >= 0

    manifest_fields = set(FreezeManifest.__dataclass_fields__)
    assert "known_answer_fixture_hash" in manifest_fields
    assert not any("basket" in name or "universe" in name for name in manifest_fields), (
        "if the seam has grown a slot for the selected basket, pin it here and delete this "
        "assertion — the residue this test records would then be closed")


def test_no_forward_window_number_is_computed_for_the_basket():
    """Ticket 28's last criterion. Selection is a pre-T0 operation, stated as a field list."""
    from universe import Selection, SelectedBasket
    for cls in (Selection, SelectedBasket):
        for name in cls.__dataclass_fields__:
            assert "forward" not in name and "return" not in name, (cls.__name__, name)


# -- ticket 27 and 28: the look-ahead audit --------------------------------------


def test_the_look_ahead_audit_reports_zero_post_t0_inputs():
    _report_, _universe, inputs, _basket, audit = _compose()
    assert audit.post_t0_values_found == 0
    assert audit.undeclared_input_classes == ()
    assert audit.scores_checked == len(inputs.scores) == 5
    assert all(check.passed for check in audit.checks)
    assert len(audit.checks) == 7
    assert [check.name for check in audit.checks][-1] == \
        "every_walked_block_is_before_t0_or_declared"


def test_the_audit_reports_the_figures_a_reviewer_actually_reads():
    """``post_t0_values_found == 0`` is near-tautological; the block figures are not."""
    _report_, _universe, _inputs, _basket, audit = _compose()
    assert audit.latest_input_block == F.W1.t0.block - 1
    assert audit.latest_input_timestamp == F.W1.t0.timestamp - 1
    assert audit.earliest_gap_blocks == 1
    assert sorted(audit.input_classes_examined) == ["AccountWindowObservation", "PreT0Score"]
    assert "near-tautological" not in audit.barrier_statement
    assert "in-degree zero" in audit.barrier_statement


# -- ticket 27: the post-T0 output path ------------------------------------------


def test_the_post_t0_output_is_produced_after_selection_and_covers_it_exactly():
    """The required output. Reached by its own name — ``from universe.forward import ...``.

    Note the import at the top of this file: the post-T0 side is not reachable through
    ``from universe import ...`` at all, and that absence is what the cross-package half of
    ``tests/test_post_t0_barrier.py`` keys on.
    """
    _report_, universe, inputs, basket, _audit = _compose()
    days = forward_period_days(F.W1.forward_end_ts, F.W1.t0.timestamp)
    assert days == 183

    mount = F.mounted(universe, basket, inputs)
    activities = [
        ForwardActivity(
            wallet=wallet,
            window_key=forward_key(),
            snapshot_id=mount.artifact.artifact_hash,
            forward_valid_buys=ForwardCount(count),
            forward_days=days,
            first_forward_block=F.W1.t0.block + 1,
            measured_at_block=F.W1.forward_end_block,
            t0=forward_t0(),
        )
        for wallet, count in zip(basket.wallets, (0, 1, 40, 0, 2_500))
    ]
    ledger = forward_ledger(mount, activities)
    report = forward_report(ledger)

    assert report.n_wallets == 5
    assert report.n_dormant == 2
    assert report.n_with_forward_activity == 3
    assert report.max_forward_valid_buys == 2_500
    assert report.total_forward_valid_buys == 2_541

    baseline = [BaselineFact(wallet=member.wallet,
                             baseline_valid_buys=member.valid_buys,
                             baseline_days=F.W1.baseline_days)
                for member in universe.members]
    disclosures = disclose_for_churn(ledger, baseline)
    assert len(disclosures) == 5
    assert [d.wallet for d in disclosures] == sorted(basket.wallets)
    assert all(d.baseline_days == 181 for d in disclosures)


def test_a_missing_post_t0_record_is_refused_rather_than_flattering_the_churn_rate():
    """Absence here improves the number, which is why it raises instead of defaulting to zero."""
    from universe.forward import ForwardCoverageGap
    _report_, universe, inputs, basket, _audit = _compose()
    mount = F.mounted(universe, basket, inputs)
    activities = [
        ForwardActivity(wallet=wallet, window_key=forward_key(),
                        snapshot_id=mount.artifact.artifact_hash,
                        forward_valid_buys=ForwardCount(0), forward_days=183,
                        first_forward_block=F.W1.t0.block + 1,
                        measured_at_block=F.W1.forward_end_block, t0=forward_t0())
        for wallet in basket.wallets[:-1]
    ]
    with pytest.raises(ForwardCoverageGap):
        forward_ledger(mount, activities)


def test_the_churn_block_is_computed_from_the_disclosed_post_t0_counts():
    """Ticket 27's churn output, through the one-line adaptation the composition root does.

    ``universe.forward.ForwardDisclosure`` carries exactly ``reporting.WalletActivity``'s five
    constructor arguments, in this package's own type because ``universe`` is a leaf and may not
    import ``reporting``. That adaptation is the visible seam between the two packages, and it is
    this loop.

    The population is chosen so all three §10 states appear, and one wallet is the case §10's prose
    is specifically about: 200 baseline buys down to 1. It is **Reduced Activity**, not Active.
    """
    from reporting.churn import ChurnState, WalletActivity, report_churn

    _report_, universe, inputs, basket, _audit = _compose()
    days = forward_period_days(F.W1.forward_end_ts, F.W1.t0.timestamp)
    forward_counts = {900: 900, 700: 0, 200: 1, 30: 30, 25: 0}

    mount = F.mounted(universe, basket, inputs)
    members = {member.wallet: member for member in universe.members}
    activities = [
        ForwardActivity(
            wallet=wallet, window_key=forward_key(),
            snapshot_id=mount.artifact.artifact_hash,
            forward_valid_buys=ForwardCount(forward_counts[members[wallet].valid_buys]),
            forward_days=days, first_forward_block=F.W1.t0.block + 1,
            measured_at_block=F.W1.forward_end_block, t0=forward_t0(),
        )
        for wallet in basket.wallets
    ]
    ledger = forward_ledger(mount, activities)
    baseline = [BaselineFact(wallet=m.wallet, baseline_valid_buys=m.valid_buys,
                             baseline_days=F.W1.baseline_days)
                for m in universe.members]

    churn = report_churn([
        WalletActivity(wallet=d.wallet, baseline_valid_buys=d.baseline_valid_buys,
                       baseline_days=d.baseline_days,
                       forward_valid_buys=d.forward_valid_buys, forward_days=d.forward_days)
        for d in disclose_for_churn(ledger, baseline)
    ])

    assert churn.n_wallets == 5
    assert churn.n_active == 2
    assert churn.n_reduced_activity == 1
    assert churn.n_inactive == 2
    assert churn.churn_rate == churn.inactive_rate

    states = dict(churn.states)
    collapsed = next(m.wallet for m in universe.members if m.valid_buys == 200)
    assert states[collapsed] is ChurnState.REDUCED_ACTIVITY, (
        "a wallet that fell from 200 trades to 1 is effectively dead, not active")


def test_account_typing_agrees_with_the_golden_sets_expectation():
    """Ticket 25's spot-check — and it is narrower than the criterion asks for.

    The golden set (``tests/known_answer/battery.py``) holds **one** account-type expectation: its
    portfolio owner is an ``EOA``, resolved by ``DIRECT_EOA``. There is no case matrix of Safes,
    ERC-4337 accounts, routers or vaults to check a window's typing against, so what this test can
    check is agreement on that one expectation: the address the battery types ``EOA`` is admitted
    by this package as an ``EOA`` and not as anything else.

    Stated rather than dressed up. A wider spot-check needs golden-set cases that do not exist yet,
    and inventing expectations here and checking them against ourselves would be the shape of
    agreement that means nothing.
    """
    from known_answer import battery

    expected = battery.attribution("0xfeed").account_type
    assert expected is AccountType.EOA

    observation = F.observation(battery.OWNER, potential_buys=120, valid_buys=100,
                                account_type=expected)
    universe = F.frozen([observation])
    member = universe.member(battery.OWNER)
    assert member is not None
    assert member.account_type is AccountType.EOA
    assert member.wallet == battery.OWNER.lower()


def test_the_post_t0_ledger_cannot_answer_a_membership_test():
    """The container-level version of ``ForwardCount``'s argument."""
    from universe.forward import ForwardLedger
    surface = {name for name in dir(ForwardLedger) if not name.startswith("_")}
    for forbidden in ("keys", "wallets", "get", "contains", "items"):
        assert forbidden not in surface
    assert not hasattr(ForwardLedger, "__contains__")
    assert not hasattr(ForwardLedger, "__iter__")
    assert not hasattr(ForwardLedger, "__getitem__")
