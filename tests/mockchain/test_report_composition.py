"""The report is a real published report over synthetic inputs, not an object that resembles one.

The distinction is the whole value of this package. A hand-assembled ``RunReport`` — fields filled
with plausible Decimals — would exercise nothing: no netting, no lot matching, no marking horizon,
no ``depth`` simulation, no boundary quantization, and no refusal from any of them. What is checked
here is that every §10 block came out of ``src/`` reading generated inputs, that the publication
route is the audited one, and that the four refusals ``report.py`` owns actually refuse.

The §10 figures are pinned as literals measured from the seed-7 run. They are not recomputed from
the code that produced them: a test that re-derives a number from the implementation under test
agrees with it by construction, including when both are wrong.
"""

import types

import pytest

from contracts import add, calc, sub
from reporting import (
    CAPITAL_LEVELS,
    DIAGNOSTIC_ONLY,
    GATE_RELEVANCE_STATEMENT,
    NOT_TESTED,
    ARTIFACT_KIND,
    PRODUCED_BY,
    RunReport,
)
from reporting.diagnostics import DIAGNOSTIC_NAMES, DiagnosticPromotionRefused

from tools.mockchain import generate_chain, run_synthetic_window
from tools.mockchain import report as report_module
from tools.mockchain.provenance import SYNTHETIC_CHAIN, is_synthetic_snapshot

from conftest import SEED


# -- the four refusals report.py owns -------------------------------------------


def test_running_a_window_refuses_a_seed_where_a_chain_belongs():
    """``run_synthetic_window(7)`` would hide the generation step a run's record consists of."""
    with pytest.raises(TypeError) as raised:
        run_synthetic_window(SEED)
    assert "SyntheticChain" in str(raised.value)
    assert "generate_chain" in str(raised.value)


def test_running_a_window_refuses_a_look_alike_object():
    """Duck typing is the failure here: the wrong five arguments produce a plausible result."""
    chain = generate_chain(SEED)
    look_alike = types.SimpleNamespace(
        transactions=chain.transactions, pools=chain.pools, prices=chain.prices,
        window=chain.window, config=chain.config,
    )
    with pytest.raises(TypeError):
        run_synthetic_window(look_alike)


def test_assembling_a_report_over_a_run_that_scored_nothing_names_the_actual_problem():
    """``report_basket`` would refuse the empty basket anyway, describing an aggregate instead."""
    chain = generate_chain(SEED)
    empty = types.SimpleNamespace(wallets=())
    with pytest.raises(ValueError) as raised:
        report_module._assemble(chain, empty)
    message = str(raised.value)
    assert "scored no wallet" in message
    assert "20 and 1,000 valid buys" in message


def test_a_report_for_a_non_int_seed_is_refused_before_anything_is_generated():
    """And the refusal is ``seeds.draw``'s, on the first draw — not a duplicate check in report.py.

    Where it comes from is asserted, not incidental. ``synthetic_report`` used to repeat the type
    check; deleting that copy left every test green, which is the definition of a guard nothing
    pins. The behaviour is what matters and it is pinned here: a float, a string, ``None`` and a
    ``bool`` are all refused before a single transaction, pool or identifier is constructed.
    """
    import traceback

    for bad in (7.0, "7", None, True):
        with pytest.raises(TypeError) as raised:
            report_module.synthetic_report(bad)
        frame = traceback.extract_tb(raised.value.__traceback__)[-1]
        assert frame.filename.endswith("seeds.py"), (
            "the seed refusal moved to {}; if report.py has grown its own check again it must be "
            "distinguishable from this one".format(frame.filename)
        )
        assert "seed must be an int" in str(raised.value)


# -- the report came out of src/ ------------------------------------------------


def test_the_report_is_a_reporting_run_report_and_says_what_it_ran_on(run):
    assert isinstance(run.report, RunReport)
    assert run.report.chain == SYNTHETIC_CHAIN == "synthetic-mockchain-v1"
    assert "ethereum" not in run.report.chain, (
        "§11.1 selected Ethereum Mainnet. This ran on nothing, and a report that said 'ethereum' "
        "would be the exact confusion the marker exists to prevent."
    )
    assert is_synthetic_snapshot(run.snapshot)
    assert run.report.gate_relevance == GATE_RELEVANCE_STATEMENT
    assert run.report.not_tested == NOT_TESTED
    assert len(run.report.not_tested) == 4


def test_the_basket_is_the_measured_one(run):
    """Whatever fell out of the seed. Two of these five numbers are unflattering, and both stay."""
    basket = run.report.basket
    assert basket.n_wallets == 9
    assert basket.mean_buy_quality == calc("-0.07887967")
    assert basket.median_buy_quality == calc("-0.00308878")
    assert basket.realized_usd == calc("9735.647773")
    assert basket.marked_usd == calc("3365391.690419")
    assert basket.dead_usd == calc("2212.359007")
    assert basket.total_usd == calc("3377339.697198")
    assert basket.marked_share == calc("0.99646230")


def test_almost_the_whole_basket_rests_on_marking_and_the_report_says_so(run):
    """A §10 finding about this fixture, recorded rather than smoothed.

    99.6% of the basket's value is an open position marked against a pool at the horizon, not a
    realized sale. That is what makes the headline number fragile, and it is exactly the fact
    §10 requires beside it.
    """
    basket = run.report.basket
    assert basket.marked_share > calc("0.99")
    assert basket.realized_share < calc("0.01")
    assert add(add(basket.realized_share, basket.marked_share), basket.dead_share) == calc(
        "1.00000000"
    )


def test_the_published_usd_components_do_not_sum_to_the_published_total(run):
    """Measured, and recorded here so it is a known property rather than a later surprise.

    Each of the four figures goes through ``reporting.boundary`` exactly once — that is the
    quantize-once policy — so they are four independent roundings of four unrounded quantities, and
    the three components add to 3377339.697199 against a published total of 3377339.697198. One
    microdollar on $3.38M. A consumer that re-adds the published components and compares them to the
    published total must use a tolerance; §9.2's 0.5% swallows this by twelve orders of magnitude.
    """
    basket = run.report.basket
    summed = add(add(basket.realized_usd, basket.marked_usd), basket.dead_usd)
    assert summed == calc("3377339.697199")
    assert basket.total_usd == calc("3377339.697198")
    assert sub(summed, basket.total_usd) == calc("0.000001")


def test_all_five_capital_levels_are_simulated_through_depth(run):
    """Every scored buy is simulated at every level, and two wallets leave the ladder's mean.

    ``n_wallets`` is 7 against a §10 basket of 9, and the gap is not a defect: ``follower.adjust``
    drops a wallet none of whose buys the follower could place, because a follower who placed no
    order has no buy quality and a zero there would read as a measured flat result. The two are
    ``wallet-dead-pool`` and ``wallet-migrated``, whose horizon reserves cannot absorb the leader's
    own clip. ``CapitalLevelReport`` has no field for them, which is why the reason is on
    ``run.follower`` — see :func:`test_the_wallets_the_ladder_dropped_are_named_on_the_run`.
    """
    ladder = run.report.capital_ladder
    assert tuple(level.capital_level for level in ladder.levels) == CAPITAL_LEVELS
    assert len(CAPITAL_LEVELS) == 5
    for level in ladder.levels:
        assert level.n_wallets == 7
        assert level.n_simulated == 1041
        assert level.n_executable == 1037
        assert level.n_retention_reported + level.n_retention_suppressed == level.n_wallets
    # The follower's adjusted quality is a different number from the leader's raw one at every
    # level, which is what shows the §4.5 simulation actually reached the score.
    for level in ladder.levels:
        assert level.mean_follower_adjusted_buy_quality != level.mean_raw_buy_quality


def test_the_wallets_the_ladder_dropped_are_named_on_the_run(run):
    """The §10 block loses them; the run does not.

    ``run.follower`` is the whole ``FollowerAdjustment`` the ladder was taken from, so the two
    wallets missing from every level's ``n_wallets`` are named with the reason they were dropped.
    Without it, a reader comparing a 9-wallet basket to a 7-wallet ladder has a discrepancy and no
    explanation anywhere in the artifact.
    """
    assert run.follower is not None
    assert run.follower.ladder is run.report.capital_ladder
    for level in run.follower.levels:
        dropped = dict(level.unscorable_wallets)
        assert sorted(dropped) == [
            "0xsynthetic-wallet-dead-pool-01e11fa4e74a3",
            "0xsynthetic-wallet-migrated-831d713dae9441",
        ]
        for reason in dropped.values():
            assert "none of 2 buy(s) could be placed" in reason
        assert level.report.n_wallets + len(dropped) == len(run.report.basket.wallets)


def test_the_ladder_is_the_stages_composition_and_not_a_second_one(run, chain, result):
    """§4.5 at five capital levels is implemented once, in ``src/``, and the fixture calls it.

    Pinned because the fixture used to implement it a second time and the two disagreed: this
    module entered an uncopyable buy at a return of zero and ``follower.adjust`` drops it. At seed
    7 that published 0.01932769 where the stage publishes 0.02484988 at the $100k level — a 28%
    difference in a §10 headline figure, in a block with no field saying which convention produced
    it. The stage is the authority because it is the code a real run executes.
    """
    from pipeline.stages.benchmark import follower_adjust_runner

    class _Context(object):
        run_id = "recomputed-here"
        commit = report_module.SYNTHETIC_COMMIT

    scored = report_module._scored(result)
    recomputed = follower_adjust_runner(
        leader_buys=report_module.leader_buys(chain, scored, report_module._quote_assets()),
        value_basis_by_level={
            level: report_module._basket_basis(scored) for level in CAPITAL_LEVELS
        },
    )(_Context())

    assert recomputed.ladder == run.report.capital_ladder
    assert run.report.capital_ladder.levels[0].mean_follower_adjusted_buy_quality == calc(
        "0.02484988"
    )


def test_every_diagnostic_is_diagnostic_only_and_cannot_be_promoted(run):
    items = run.report.diagnostics.items
    assert len(items) == 9
    names = [item.name for item in items]
    assert set(names) <= set(DIAGNOSTIC_NAMES)
    assert names.count("activity_band_sensitivity") == 3, "one per non-empty §10 activity band"
    for item in items:
        assert item.gate_relevance == DIAGNOSTIC_ONLY
        assert item.scope.chain == SYNTHETIC_CHAIN
    with pytest.raises(DiagnosticPromotionRefused):
        _ = items[1] > calc("0")


def test_bucket_a_is_reported_because_a_buy_landed_there(run):
    """Omitted entirely when empty — a zero there would say the first-block buys broke even."""
    assert "bucket_a_isolated" in [item.name for item in run.report.diagnostics.items]


def test_the_reason_the_gating_columns_are_absent_is_carried_as_a_constant():
    """An empty column list with no stated reason is what a broken run looks like."""
    assert "§6.6" in report_module.NO_BENCHMARK
    assert "no control universe" in report_module.NO_BENCHMARK
    assert "describe nothing" in report_module.NO_BENCHMARK


# -- the publication route ------------------------------------------------------


def test_the_envelope_is_the_real_artifact_envelope(run):
    assert sorted(run.envelope) == [
        "kind", "payload", "payload_hash", "produced_by", "schema_version",
    ]
    assert run.envelope["kind"] == ARTIFACT_KIND == "phase0_required_outputs"
    assert run.envelope["produced_by"] == PRODUCED_BY == "reporting"
    assert run.envelope["schema_version"] == 1
    assert sorted(run.payload) == [
        "basket", "capital_ladder", "chain", "churn", "diagnostics", "gate_relevance",
        # §10's four standing integrity figures, required on every report since 2026-08-16. They
        # are all `null` on this synthetic run, which is the true statement about it — four
        # packages computed these and, until the block existed, nothing published any of them.
        "integrity",
        "missing_windows", "not_tested", "numeric_policy_version", "reporting_schema_version",
        "run_id", "windows",
    ]
    assert sorted(run.payload["integrity"]) == [
        "attribution_fallback_rate", "decoder_coverage_gap",
        "reconciliation_queue_volume_usd", "unexplained_reconciliation_difference",
    ]
    assert all(v is None for v in run.payload["integrity"].values()), (
        "None means not measured and never zero; a synthetic run measures none of these, and "
        "reporting a zero here would claim somebody looked"
    )
    # The payload is canonicalised: every Decimal is a string, and no float exists anywhere in it.
    assert run.payload["basket"]["mean_buy_quality"] == "-0.07887967"
    assert isinstance(run.payload["basket"]["n_wallets"], str)


def test_the_run_keeps_every_intermediate_stage_for_audit(run):
    """A reader handed only the envelope cannot say which wallets were quarantined. This one can."""
    assert run.chain.seed == SEED
    assert run.result.window == 1
    assert len(run.result.wallets) == 9
    assert run.report.run_id == run.run_id
    assert run.addresses == tuple(sorted(run.addresses))
