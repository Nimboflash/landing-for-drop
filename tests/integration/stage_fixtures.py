"""Inputs for the thirteen stage runners, small enough to read and real enough to run.

Not a test module — pytest collects ``test_*.py``, and this is imported by
``test_stage_registry.py`` and ``test_stage_runners.py`` as ``from . import stage_fixtures``.

Everything here is a *fixture*, not a measurement. The universes are toy: thirteen wallets on a
ladder, one buy against one pool, a null of forty runs rather than §8.2's thousand. Nothing below
is evidence about the hypothesis and nothing below should ever be read as such. What it is evidence
about is the wiring: that each stage's factory, given inputs of the shape it documents, produces a
runner ``phase0.execution.execute_stage`` can call, and that the value it returns is the type the
next stage in the chain expects.

Two things are deliberately *not* toy, because making them toy would make the tests prove nothing:

* the master seed is pinned (:data:`MASTER_SEED`), so every ``context.child_seed`` derivation, every
  relabelling and therefore every calibrated threshold is the same on every machine and the tests
  can pin literals rather than ranges;
* the chain is real. ``threshold.calibrate`` is handed the values ``null.leader`` and
  ``null.follower`` actually produced, ``main_test`` is evaluated at the threshold calibration
  actually locked, and ``decision.emit`` receives the main test's own result and the nulls' own
  ``PermutationResult``s. Nothing in the sequence is hand-fed a number a previous stage was supposed
  to compute.
"""

from decimal import Decimal

from attribution import AttributionContext
from contracts import (
    AccountType,
    AssetTier,
    ClassificationStatus,
    EdgeOriginStatus,
    NUMERIC_POLICY_VERSION,
    NetTradeResult,
    PoolState,
    REPORTING_SCHEMA_VERSION,
    TokenAgeBucket,
    Transfer,
    USDC,
    ValidationStatus,
    WindowScore,
)
from depth import PricedPool, QuoteAsset
from gate_validation import (
    DESIGN_CAPITAL_LEVELS,
    FOLLOWER_COLUMN,
    GOVERNANCE_ORDER,
    LEADER_COLUMN,
    REQUIRED_MODULES,
    RunEvidence,
    RunStatus,
)
from matching_null import NUMERIC_DIMENSIONS, WalletFeatures, build_matched_sets
from phase0.execution import wire
from phase0.preconditions import PRECONDITION_KEYS
from phase0.seeds import new_master_seed
from pipeline import (
    MEASUREMENT_HORIZON_SECONDS,
    ObservedTransaction,
    TokenStart,
    Window,
    WindowConfig,
)
from pipeline.stages import benchmark, inference
from pipeline.stages.step0 import Step0WindowInputs  # noqa: F401  (re-exported for the tests)
from reporting import CAPITAL_LEVELS, ValueBasisAmounts
from scoring import buy_outcome

import universe_fixtures as U

D = Decimal

#: The commit every run below is pinned to, and the ``source_commit`` the freeze manifest carries.
#: One value for both so the §9.6 manifest check and ``decision.emit``'s own run-record check are
#: looking at the same experiment rather than at two coincidences.
COMMIT = "a" * 40

DATASET_SNAPSHOT = "fixture-snapshot-0001"

#: Pinned so the whole chain is reproducible. ``phase0`` mints a random one when this is omitted,
#: and a random master seed would make the calibrated threshold a different number on every run.
MASTER_SEED = new_master_seed("phase0-stage-wiring-fixtures")

REQUESTER = "primary-builder"

T0_BLOCK = 18_000_000
ONE_USDC = 10 ** 6
ONE_TOKEN = 10 ** 18


# -- the governed run -----------------------------------------------------------


def wired(root):
    """A :class:`phase0.execution.Wiring` with the §15.4 preconditions already recorded.

    The start gate is not what these tests are about — ``tests/integration/test_execution.py``
    fixes it — and a run that cannot get past it cannot exercise a runner at all.
    """
    state = wire(str(root))
    for key, who in zip(PRECONDITION_KEYS, ("A. Builder", "V. Alidator, contract #7",
                                            "PO-1234", "capacity reserved, weeks 1-12")):
        state.preconditions.record(key, who, "Research Owner")
    return state


# -- step0.universe -------------------------------------------------------------
#
# §6.1 measured in the four §6.3 windows. The calendars, the observations and the eligibility
# machinery are ``tests/universe_fixtures``' — the same builders every ``universe`` test uses — so
# that what this file adds is only the *stage wiring*: four windows' worth of inputs grouped the way
# ``pipeline.stages.step0`` wants them, under the design those windows belong to.

#: The parameter freeze the four-window design and any replacement rule were registered under. A
#: literal because nothing in this tree computes one; ``Step0Report`` only requires that the report
#: names it and that a replacement registry claiming a different one is refused.
PARAMETER_FREEZE_HASH = "p" * 64

#: How many eligible accounts each window's fixture universe holds. Four different sizes, so a test
#: reading the report can tell the four measurements apart, and every one of them **far** below
#: §6.1's floor of 10,000.
#:
#: That is not laziness and it cannot be fixed by trying harder: an eligible universe of 10,000 is
#: 10,000 constructed observations put through the two-stage eligibility screen, which takes about
#: eleven seconds per window on the machine this was written on. So every window these fixtures
#: measure carries ``INSUFFICIENT CANDIDATE UNIVERSE``, and that is exactly the status the stage
#: has to carry rather than crash on — see ``test_stage_runners.py``.
STEP0_ELIGIBLE = ((U.W1, 3), (U.W2, 4), (U.W3, 5), (U.W4, 6))


def step0_window(window, eligible):
    """One window's Step 0 inputs: ``eligible`` ordinary retail accounts, all admitted."""
    observations = [U.observation(U.address(n), window=window) for n in range(1, eligible + 1)]
    return Step0WindowInputs(**U.step0_inputs(observations, window=window))


def step0_window_admitting_nobody(window, screened=3):
    """One window whose accounts all pass the warehouse screen and none of which is eligible.

    Every account's economic controller is unidentified, which §6.2 excludes. The window therefore
    has observations to measure and an eligible universe of *nothing* — which is a measurement that
    could not be taken rather than a small one, and ``measure_window`` says so.
    """
    observations = [
        U.observation(U.address(n), window=window,
                      evidence=U.human_evidence(controller_identified=False))
        for n in range(1, screened + 1)
    ]
    return Step0WindowInputs(**U.step0_inputs(observations, window=window))


def step0_universe_inputs(windows=None, design=None, dataset_snapshot=DATASET_SNAPSHOT):
    """Ticket 26's four windows, the design that registers them, and the frozen snapshot.

    ``windows`` defaults to all four. A test that wants the report's coverage refusal passes a
    subset; one that wants the honest no-data refusal passes ``inputs=None`` to ``run_stage`` and
    gets ``StageBlocked`` instead.
    """
    return {
        "windows": ([step0_window(window, eligible) for window, eligible in STEP0_ELIGIBLE]
                    if windows is None else windows),
        "design": U.DESIGN if design is None else design,
        "parameter_freeze_hash": PARAMETER_FREEZE_HASH,
        "dataset_snapshot": dataset_snapshot,
    }


# -- known_answer.battery -------------------------------------------------------
#
# No inputs. The runner locates tests/known_answer/battery.py from the checkout.


# -- pipeline.buy_quality -------------------------------------------------------

TRADER = "0x" + "a1" * 20
POOL = "0x" + "b1" * 20
TOKEN = "0x" + "c1" * 20

START_BLOCK = 18_000_000
START_TS = 1_700_000_000
END_BLOCK = START_BLOCK + 7_200
END_TS = START_TS + 86_400
HORIZON_BLOCK = END_BLOCK + 216_000
HORIZON_TS = END_TS + MEASUREMENT_HORIZON_SECONDS

ATTRIBUTION = AttributionContext(
    infrastructure=frozenset({POOL}), eoas=frozenset({TRADER}),
)

WINDOW = Window(index=1, start_block=START_BLOCK, start_ts=START_TS,
                end_block=END_BLOCK, end_ts=END_TS)

WINDOW_CONFIG = WindowConfig(
    horizon_block=HORIZON_BLOCK,
    horizon_ts=HORIZON_TS,
    token_starts={TOKEN: TokenStart(block=START_BLOCK - 100_000, timestamp=START_TS - 1_000_000)},
    replacement_pools={},
)

#: One buy: $1,000 of USDC for 4,000 TOKEN, at a pool holding 4,000 TOKEN against $1,500.
#:
#: The exit value of the whole position is q * (R / 2X) = 4,000 * (1,500 / 8,000) = $750 on a
#: $1,000 cost, so the buy's return is -0.25 exactly. Worked here rather than read back from a run,
#: and pinned as a literal in ``test_stage_runners.py``.
BUY_TRANSACTIONS = (
    ObservedTransaction(
        tx_hash="0x" + "11" * 32,
        block_number=START_BLOCK + 1,
        timestamp=START_TS + 12,
        success=True,
        tx_sender=TRADER,
        transfers=(
            Transfer(token=USDC, from_addr=TRADER, to_addr=POOL,
                     raw_amount=1_000 * ONE_USDC, log_index=0),
            Transfer(token=TOKEN, from_addr=POOL, to_addr=TRADER,
                     raw_amount=4_000 * ONE_TOKEN, log_index=1),
        ),
        context=ATTRIBUTION,
    ),
)

POOL_BOOK = {
    TOKEN: PoolState(
        address=POOL, asset=TOKEN, quote=USDC,
        asset_reserve_raw=4_000 * ONE_TOKEN, quote_reserve_raw=1_500 * ONE_USDC,
        last_swap_block=HORIZON_BLOCK, last_swap_timestamp=HORIZON_TS, fee_bps=0,
    ),
}

#: USD per raw unit. USDC has 6 decimals, so one raw unit is $0.000001.
PRICES = {USDC: D("0.000001")}


def buy_quality_inputs():
    return {
        "transactions": BUY_TRANSACTIONS,
        "pools": POOL_BOOK,
        "prices": PRICES,
        "window": WINDOW,
        "config": WINDOW_CONFIG,
    }


# -- benchmark.match ------------------------------------------------------------


def features(wallet, capital):
    """A feature record whose only varying dimension is ``capital_deployed``.

    The other eight numeric dimensions are still matched on; a constant dimension has zero variance
    across the universe, so every wallet's standardised coordinate on it is 0.
    """
    values = {dimension: D("0") for dimension in NUMERIC_DIMENSIONS}
    values["capital_deployed"] = D(str(capital))
    return WalletFeatures(
        wallet=wallet, account_type=AccountType.EOA, values=values, as_of_block=T0_BLOCK - 1,
    )


def ladder():
    """Thirteen wallets at ``capital_deployed`` 0..12. The one at 0 is selected."""
    return {"0xw{:02d}".format(v): features("0xw{:02d}".format(v), v) for v in range(13)}


SELECTED = ("0xw00",)


def benchmark_match_inputs():
    records = ladder()
    return {
        "selected": SELECTED,
        "universe": sorted(records),
        "features": records,
        "t0_block": T0_BLOCK,
    }


# -- follower.adjust ------------------------------------------------------------

QUOTE = QuoteAsset(address=USDC, decimals=6, usd_price=D("1"))


def priced_pool():
    """A deep constant-product pool: 4,000,000 TOKEN against $1,000,000, 30bps."""
    return PricedPool(
        state=PoolState(
            address=POOL, asset=TOKEN, quote=USDC,
            asset_reserve_raw=4_000_000 * ONE_TOKEN,
            quote_reserve_raw=1_000_000 * ONE_USDC,
            last_swap_block=END_BLOCK, last_swap_timestamp=END_TS, fee_bps=30,
        ),
        quote=QUOTE,
    )


def a_valid_buy(n, owner=TRADER):
    """A minimal ``VALID_BUY``. Only the fields scoring and depth read carry meaning."""
    return NetTradeResult(
        tx_hash="0x{:064x}".format(n),
        portfolio_owner=owner,
        status=ClassificationStatus.VALID_BUY,
        sold_asset=USDC,
        bought_asset=TOKEN,
        sold_raw_amount=1_000 * ONE_USDC,
        bought_raw_amount=ONE_TOKEN,
        quote_asset=USDC,
        quote_usd=D("1000"),
        block_number=START_BLOCK + n,
        timestamp=START_TS + 12 * n,
        token_age_bucket=TokenAgeBucket.D,
    )


def leader_buys():
    """Two leader buys, both realized, at +40% and +20%."""
    out = []
    for n, return_pct in ((1, "0.4"), (2, "0.2")):
        out.append(benchmark.LeaderBuy(
            outcome=buy_outcome(
                a_valid_buy(n),
                trade_value_usd=D("1000"),
                return_pct=D(return_pct),
                realized_usd=D("1000"),
            ),
            pool=priced_pool(),
            tier=AssetTier.MAJOR,
            leader_clip_usd=D("1000"),
            gas_usd=D("5"),
        ))
    return out


def value_basis_by_level():
    """§10's mix per capital level. All five rungs, because §10 fixes the ladder at five."""
    return {
        level: ValueBasisAmounts(realized_usd=D("1000"), marked_usd=D("0"), dead_usd=D("0"))
        for level in CAPITAL_LEVELS
    }


def follower_adjust_inputs():
    return {"leader_buys": leader_buys(), "value_basis_by_level": value_basis_by_level()}


# -- null.leader / null.follower ------------------------------------------------

#: The one matched set the null permutes: the selected wallet plus its five nearest controls.
#: ``build_matched_sets`` is called with a fixed seed so the set is the same on every machine.
MATCHING_SEED = 20260731

#: The §6.3 windows the null covers. Two rather than four: the number of windows is not what these
#: tests are about, and each extra window is another forty statistic evaluations.
NULL_WINDOWS = (1, 2)

#: Forty runs, not §8.2's thousand. Recorded in every ``NullDistribution`` the runner produces, so a
#: short null cannot later pass as the pre-registered one — which is the property that makes it safe
#: to use a short one here.
NULL_RUNS = 40

#: The only wallet carrying any signal. Every relabelling that moves the label onto a control
#: scores zero, which is what a null with no signal in the labels looks like.
SIGNAL = {"0xw00": D("0.40")}


def matched_sets():
    records = ladder()
    sets, _balance = build_matched_sets(
        list(SELECTED), sorted(records), records, T0_BLOCK, MATCHING_SEED,
    )
    return sets


def statistic_for(column, window):
    """A stand-in for §7.1's three-condition gate on the relabelled population.

    The real one is the pipeline — ``pipeline.run_wallet_window`` over the relabelled selected and
    control populations, follower-adjusted for the follower column — and it is the integrator's to
    supply, per window, because the null cannot be built before the metric it permutes. This one
    sums the signal carried by whichever wallets wear the label, which is enough to make the
    distribution move when the labels move and nothing more.
    """
    def statistic(labelled):
        total = D("0")
        for matched in labelled:
            total = total + SIGNAL.get(matched.selected, D("0"))
        return WindowScore(
            window=window,
            column=column,
            mean_advantage=total,
            median_advantage=D("1"),
            first_hour_edge_share=D("0.20"),
            positive_edge_contribution=D("10"),
            edge_origin_status=EdgeOriginStatus.VALID,
        )
    return statistic


def null_inputs(column):
    sets = matched_sets()
    return {
        "windows": [
            inference.NullWindowInputs(
                window=window, matched_sets=sets, statistic_fn=statistic_for(column, window),
            )
            for window in NULL_WINDOWS
        ],
        "n_runs": NULL_RUNS,
    }


# -- threshold.calibrate --------------------------------------------------------

#: The candidate grid, in the units of ``WindowScore.mean_advantage``. The observed statistic is
#: 0.40 whenever the label sits on ``0xw00``, so no candidate at or below 0.40 can hold the null
#: pass rate under 5% and 0.41 is the smallest that can.
CANDIDATES = ("0.05", "0.10", "0.20", "0.30", "0.40", "0.41", "0.50")


def calibrate_inputs(leader_result, follower_result):
    return {"nulls": [leader_result, follower_result], "candidates": CANDIDATES}


# -- main_test ------------------------------------------------------------------


def score(window, column, mean, median="0.05"):
    return WindowScore(
        window=window, column=column, mean_advantage=D(mean), median_advantage=D(median),
        first_hour_edge_share=D("0.20"), positive_edge_contribution=D("0.30"),
        edge_origin_status=EdgeOriginStatus.VALID,
    )


def window_scores():
    """Four windows, both columns, every mean below the threshold calibration will lock.

    Fixed here rather than derived from the calibrated threshold, and that is the point: choosing
    the scores after seeing the threshold is the thing §8.4's ordering exists to prevent, and a
    fixture that did it would demonstrate the opposite of the property under test. The consequence
    is that the run these fixtures walk ends in a STOP, which is a result and not a failure.
    """
    out = []
    for window in (1, 2, 3, 4):
        out.append(score(window, LEADER_COLUMN, "0.30"))
        out.append(score(window, FOLLOWER_COLUMN, "0.26", median="0.02"))
    return out


def excess_by_level():
    """Follower-adjusted excess buy quality at the two design capital levels, §7.2.

    A sequence of pairs rather than a dict, because ``main_test_runner`` passes it through
    unconverted so ``CapitalFeasibility`` can refuse two spellings of one level itself.
    """
    return [(DESIGN_CAPITAL_LEVELS[0], D("0.05")), (DESIGN_CAPITAL_LEVELS[1], D("0.03"))]


def main_test_inputs(locked_threshold):
    return {
        "window_scores": window_scores(),
        "excess_by_level": excess_by_level(),
        "locked_threshold": locked_threshold,
    }


# -- decision.emit --------------------------------------------------------------


def manifest(**overrides):
    pinned = {
        "source_commit": COMMIT,
        "dataset_snapshot": DATASET_SNAPSHOT,
        "golden_set_version": "golden-v3",
        "protocol_coverage_version": "coverage-v2",
        "decoder_version": "decoder-v7",
        "model_version": "model-v1",
        "config_hash": "c" * 64,
        "master_seed": MASTER_SEED,
        "known_answer_fixture_hash": "k" * 64,
        "validation_report_hash": "v" * 64,
        "numeric_policy_version": NUMERIC_POLICY_VERSION,
        "reporting_schema_version": REPORTING_SCHEMA_VERSION,
    }
    pinned.update(overrides)
    return pinned


def module_versions(**overrides):
    versions = {name: "{}-{}".format(name, "0" * 8) for name in REQUIRED_MODULES}
    versions.update(overrides)
    return versions


def evidence(locked_threshold, **overrides):
    """The nine fields ``gate_validation`` needs, none of which a runner may assemble for itself.

    Built here, in a test, exactly because nothing in the tree assembles one: the freeze manifest,
    the module pins, the validation status, the governance sequence and the run status belong to
    whoever holds those artifacts. That gap is real and is stated in the report rather than papered
    over by a helper in ``src/``.
    """
    fields = dict(
        manifest=manifest(),
        observed=manifest(),
        pinned_module_versions=module_versions(),
        observed_module_versions=module_versions(),
        validation_status=ValidationStatus.EXTERNALLY_REVIEWED,
        governance_states=GOVERNANCE_ORDER[:GOVERNANCE_ORDER.index("MAIN_TEST_EXECUTED") + 1],
        locked_threshold=locked_threshold,
        run_status=RunStatus(code_version=COMMIT),
        result_code_version=COMMIT,
    )
    fields.update(overrides)
    return RunEvidence(**fields)


def decision_inputs(main_test_result, leader_result, follower_result, locked_threshold):
    """``decision.emit``'s four inputs, every one of them a previous stage's own value.

    The nulls are taken as ``PermutationResult`` — the lossy seam view — for window 1. §8.2 builds
    one distribution per window per column and §7.3 tests one result against one null, so which
    window the decision is bound to is the integrator's choice and not something a runner can
    infer; window 1 is this fixture's, stated rather than defaulted.
    """
    return {
        "main_test": main_test_result,
        "leader_null": leader_result.to_contracts()[0],
        "follower_null": follower_result.to_contracts()[0],
        "evidence": evidence(locked_threshold),
    }
