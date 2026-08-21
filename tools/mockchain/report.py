"""One synthetic window, run through the real pipeline and published as a real §10 report.

What this module actually does
------------------------------

It composes. Every number below is produced by ``src/`` code reading generated inputs:

    generate_chain(seed)                      tools.mockchain.chain
      -> pipeline.run_wallet_window(...)      attribution · netting · fifo · marking · scoring
      -> depth.size_to_cost_cap(...)          §4.5's follower simulation, at all five levels
      -> reporting.report_basket / _capital_ladder / _churn / diagnostic_pack / report_run
      -> tools.mockchain.provenance.publish_synthetic_artifact

Nothing here assembles a :class:`reporting.RunReport` field by field from numbers it made up. The
one exception is stated below and is an *absence* rather than a figure.

**It is not tuned so the answer looks good.** Whatever falls out of the seed is the answer for that
seed. A wallet that scores -1 because its pool rugged, a capital level at which nothing is
copyable, a basket whose value rests almost entirely on marking — each is a result about the
fixture and none of them is a reason to change the fixture.

The three things this module owes the other two
-----------------------------------------------

1. **Publication goes through** :func:`tools.mockchain.provenance.publish_synthetic_artifact` **and
   nowhere else.** ``reporting.run_artifact`` is public and importable and this module never calls
   it, so there is exactly one route from a synthetic run to a hashed artifact and that route
   re-reads the payload about to be hashed. :class:`SyntheticRun` runs the same audit again on the
   payload it is holding, so the object cannot be constructed around a laundered one either.
2. **Nothing here can advance Phase 0.** This module imports no ``phase0`` name — not
   ``execute_stage``, not ``GovernanceMachine``, not ``transition``. A caller who wants a synthetic
   run under governance goes through :func:`tools.mockchain.governance.execute_synthetic_stage`,
   which refuses the transition on both sides of the runner. What this module can promise is only
   that it does not itself reach the state machine; the gap that remains is
   :data:`tools.mockchain.governance.GOVERNANCE_GAP`, and it is not this module's to close.
3. **The fixture last.** The §10 blocks below exist to exercise the reporting layer over a run that
   really happened, not to make the synthetic run look like a measurement.

What is measured, and what is absent — stated rather than filled in
-------------------------------------------------------------------

**The two §7.1 gating columns are absent, and the window report says so.**
``reporting.report_window`` renders :class:`contracts.WindowScore` results, and a window score is a
*per-wallet advantage over a matched benchmark* (§6.6: ten covariates, an SMD target, a control
universe). :mod:`tools.mockchain.chain` generates ten selected wallets and no control universe at
all, so there is no benchmark, no advantage, and no edge decomposition. The honest report of that
is :class:`reporting.WindowReport` with both columns in ``missing_columns`` — which is the state
that type defines for exactly this case: *"a report has the opposite duty — to show that the column
is missing, so that nobody reads a one-column table as a complete one."* Inventing a benchmark out
of the other synthetic wallets would produce a mean advantage, a median advantage and a first-hour
edge share that describe nothing, and they would be published beside figures that describe
something.

**Three modelling choices the copy simulation needs, none of them free.** §4.5 is a function of a
pool, a tier, a capital level, the leader's clip and gas. The generated chain fixes the first and
the fourth; the other three are chosen here, once, and named so they are arguable:

* :data:`SYNTHETIC_TIER` — ``MID_CAP``. ``depth.cost_cap_for`` raises
  :class:`contracts.LongTailExcludedError` for ``LONG_TAIL``, so a fixture that called its tokens
  long-tail would produce no simulation at any level and no capital ladder at all. ``MID_CAP``'s
  2% cap is the weaker of the two admissible caps and the generated pools are mid-cap sized
  ($3M and $10M of quote at the window's start).
* :data:`GAS_USD` — a flat $15 per copied buy, the same at every capital level, because gas is a
  cost per transaction and not per dollar. **It binds nothing in this fixture, and the sentence
  that used to sit here said it did.** Measured at seed 7, against the same ladder run with
  ``gas_usd=0``: the same four buys are uncopyable at every level either way, and the largest
  amount gas adds to any surviving buy's total execution cost is ``0.00015`` — at the $100k level,
  where the follower's order is bounded by the AUM rather than by the cost cap, so $15 of gas on a
  $100,000 order is exactly ``15/100000``. At the four higher levels the cost cap binds instead,
  the sizing search absorbs the gas by trading marginally smaller, and the difference is at the
  thirteenth decimal. ``tests/mockchain/test_hard_paths.py`` pins both numbers, so the day a
  fixture change makes gas bind, the claim here is re-derived rather than re-asserted.
* **The pool is the horizon snapshot, not the pool as it stood at the buy.** The seam supplies one
  :class:`contracts.PoolState` per pool — the same limitation ``pipeline.run`` records about its own
  marking horizon — so the follower's order is sized against the pool at the horizon. For
  ``token-dead`` and ``token-migrated`` that is deliberately the drained state, and both come back
  ``copyable=False`` with a measured reason. That is a real §10 figure about a fixture whose
  liquidity left, not an error.

**The follower-adjusted quality counts an uncopyable buy as a zero return**, rather than dropping
it. Dropping it would compute the follower's metric over exactly the trades that were executable,
which is the confusion ticket 63 names in one sentence: *"so that 'the edge survived' is
distinguishable from 'most of the edge could not be traded at all'."* The count is published beside
it either way — ``n_simulated`` against ``n_executable`` — so a reader can undo the choice.

**The §10 value-basis mix is the leader's, at every capital level.** ``report_capital_level`` takes
a :class:`reporting.ValueBasisAmounts` per level; a follower's own realized / marked / dead split
would need the follower's positions marked at their own horizons, which this fixture does not
model. The same basket mix is therefore reported at all five levels, and it is the leader's.

Determinism
-----------

Same seed, byte-identical output, including :attr:`SyntheticRun.payload_hash`. Everything varying
comes from :mod:`tools.mockchain.seeds`; every aggregation runs over an explicitly ordered
sequence; no ``set`` iteration order reaches a number. ``tests/mockchain/test_determinism.py`` runs
the whole path under several ``PYTHONHASHSEED`` values and compares the canonical JSON byte for
byte.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional, Tuple  # noqa: F401  (3.9-compatible annotations)

from contracts import (
    AssetTier,
    TokenAgeBucket,
    add,
    calc,
    divide,
    normalise_asset,
    sub,
)

from depth import PricedPool, QuoteAsset, size_to_cost_cap

from pipeline import run_wallet_window
from pipeline.result import WalletWindowResult
from pipeline.stages.benchmark import FollowerAdjustment, LeaderBuy, follower_adjust_runner

from reporting import (
    CAPITAL_LEVELS,
    GATING_COLUMNS,
    RATIO,
    DiagnosticScope,
    RunReport,
    WalletActivity,
    WalletCapitalOutcome,
    WindowReport,
    diagnostic,
    diagnostic_pack,
    mean,
    median,
    profit_ranking,
    report_basket,
    report_capital_ladder,
    report_capital_level,
    report_churn,
    report_run,
    total,
    value_basis,
)

from scoring import buy_outcome, buy_quality, weighted_mean

from .chain import (
    SELECTED_WALLETS,
    USDC_DECIMALS,
    USDC_USD,
    WETH_DECIMALS,
    WETH_USD,
    SyntheticChain,
    generate_chain,
)
from .provenance import (
    SYNTHETIC_CHAIN,
    SyntheticProvenanceLost,
    audit_payload_provenance,
    is_synthetic_snapshot,
    publish_synthetic_artifact,
    run_id,
)

ZERO = calc("0")

#: What tier the generated tokens are simulated at. See the module docstring: ``LONG_TAIL`` raises
#: rather than returning a capacity, so a fixture cannot use it and still have a capital ladder.
SYNTHETIC_TIER = AssetTier.MID_CAP

#: Flat gas cost per copied buy, in USD. Per transaction, not per dollar, which is why it binds at
#: the low capital levels and vanishes at the high ones.
GAS_USD = calc("15")

#: What a synthetic run pins as its source commit, wherever one is required.
#:
#: Not a forty-hex SHA and deliberately not one: that field is a claim that some real revision
#: produced these numbers. It is here rather than in :mod:`tools.mockchain.stages` because
#: :func:`_capital_ladder` needs one before any stage register is involved, and two spellings of a
#: synthetic run's commit would be two runs claiming to be the same one.
SYNTHETIC_COMMIT = "synthetic-mockchain-v1-not-a-commit"

#: What every diagnostic in this run says its population is. One spelling, because
#: :class:`reporting.DiagnosticScope` keys on it and two spellings would be two measurements.
POPULATION = "synthetic selected basket"

#: Why the §7.1 columns are absent. Carried as a constant so a test can pin the *reason* and not
#: only the emptiness — an empty column list with no stated reason is what a broken run looks like.
NO_BENCHMARK = (
    "tools.mockchain.chain generates ten selected wallets and no control universe, so there is no "
    "§6.6 matched benchmark, no per-wallet advantage and no §7.1 edge decomposition. Both gating "
    "columns are therefore reported as missing rather than computed against a benchmark assembled "
    "out of the other synthetic wallets, which would publish a mean advantage, a median advantage "
    "and a first-hour edge share that describe nothing."
)


# -- the run --------------------------------------------------------------------


def run_synthetic_window(chain):
    """Run one generated chain through ``pipeline.run_wallet_window`` and nothing else.

    :param chain: a :class:`tools.mockchain.chain.SyntheticChain`.
    :returns: the :class:`pipeline.result.WalletWindowResult` the real composition root produced.

    This is deliberately thin. It exists so that "the fixture reaches the pipeline" is one call a
    test can make without also building a report, and so that the five §4 stages are entered
    through the same public entry point a real reader would use. It adds no validation of its own:
    every refusal a caller can trip here is ``run_wallet_window``'s, which is the point — a wrapper
    that pre-checked the inputs would be a wrapper that could hide a defect in the generator behind
    a friendlier message.

    A seed is refused rather than accepted as a convenience. ``run_synthetic_window(7)`` and
    ``run_synthetic_window(generate_chain(7))`` would be two spellings of one call, and the first
    would hide the generation step that the second makes a caller record.
    """
    if not isinstance(chain, SyntheticChain):
        raise TypeError(
            "run_synthetic_window consumes a SyntheticChain, got {}. Build one with "
            "tools.mockchain.generate_chain(seed): the generation step is what a synthetic run's "
            "reproducibility record consists of, and a function that took the seed itself would "
            "hide it inside this call.".format(type(chain).__name__)
        )
    return run_wallet_window(
        chain.transactions, chain.pools, chain.prices, chain.window, chain.config
    )


@dataclass(frozen=True)
class SyntheticRun:
    """One synthetic seed, all the way to a published artifact, with every stage kept.

    The intermediate values are fields rather than locals because the whole purpose of this package
    is that a synthetic run is auditable: a reader who is handed only the envelope cannot tell which
    wallets were quarantined, how many buys were deferred to the next window, or which pool the dead
    share came from. All of that is on :attr:`result`.

    **The provenance audit runs again here**, on the payload this object is holding, so that a
    ``SyntheticRun`` cannot be constructed around an envelope whose addresses were rewritten between
    :func:`publish_synthetic_artifact` and this constructor.

    What that does not guarantee, and it is the same residue
    :mod:`tools.mockchain.provenance` records: ``object.__setattr__`` rewrites a field of any Python
    object, so the ``envelope`` on a *constructed* ``SyntheticRun`` can still be replaced afterwards.
    The check is on the way in. Nothing in Python can make it a lock.
    """

    seed: int
    snapshot: str
    run_id: str
    chain: SyntheticChain
    result: WalletWindowResult
    report: RunReport
    envelope: Dict[str, object]
    #: Every address-shaped string the published payload carried, as
    #: :func:`tools.mockchain.provenance.audit_payload_provenance` found them.
    addresses: Tuple[str, ...] = ()
    #: The whole :class:`pipeline.stages.benchmark.FollowerAdjustment` the §10 capital ladder was
    #: taken from. Carried because the published block loses two things the stage measured: the
    #: per-level ``unscorable_wallets`` — the wallets none of whose buys the follower could place,
    #: which is why the ladder's ``n_wallets`` is below the basket's — and every level's
    #: ``simulations``, which carry the fill ratio §10 has no field for. ``None`` only on a run
    #: assembled by a caller that did not compute one.
    follower: Optional[FollowerAdjustment] = None

    def __post_init__(self):
        object.__setattr__(self, "addresses", tuple(self.addresses))
        if not is_synthetic_snapshot(self.snapshot):
            raise SyntheticProvenanceLost(
                "this run's dataset snapshot is {!r}, which does not declare itself synthetic. The "
                "snapshot identifier is the only record of what a run was over, and every "
                "phase0.runs.RunRecord and run.open audit entry quotes it verbatim — a synthetic "
                "run whose snapshot does not say so is a run a later reader cannot tell from a "
                "measurement.".format(self.snapshot)
            )
        if not isinstance(self.envelope, dict) or "payload" not in self.envelope:
            raise SyntheticProvenanceLost(
                "a synthetic run must carry the artifact envelope it published; got {!r}".format(
                    type(self.envelope).__name__
                )
            )
        # Re-run, not trusted. See the class docstring.
        audit_payload_provenance(self.envelope["payload"])

    @property
    def payload_hash(self):
        """The canonical hash ``reporting.run_artifact`` recorded for this run's payload."""
        return self.envelope["payload_hash"]

    @property
    def payload(self):
        return self.envelope["payload"]


def synthetic_report(seed):
    """One seed, end to end: generate, run, report, publish.

    :param seed: an ``int``. No default — a generator with a default seed is one whose output
        nobody records.
    :returns: a :class:`SyntheticRun`.

    :raises TypeError: for a seed that is not an ``int``, including ``bool``. The refusal is
        :func:`tools.mockchain.seeds.draw`'s, raised on the first draw ``generate_chain`` makes and
        therefore before any transaction, pool or identifier exists. This function deliberately does
        **not** repeat the check: a duplicate here would be a guard no test could distinguish from
        the one below it, and a guard nothing can pin is a guard nothing protects. What is pinned is
        the behaviour — ``tests/mockchain/test_report_composition.py`` asserts the refusal and that
        it comes from ``seeds.py``.
    :raises tools.mockchain.provenance.SyntheticProvenanceLost: when the payload about to be hashed
        carries an address with no synthetic marker, or carries no synthetic identifier at all.
    """
    chain = generate_chain(seed)
    result = run_synthetic_window(chain)
    scored = _scored(result)
    adjustment = (
        _capital_ladder(chain, scored, _basket_basis(scored), _quote_assets()) if scored else None
    )
    report = _assemble(chain, result, adjustment=adjustment)
    envelope = publish_synthetic_artifact(report)
    return SyntheticRun(
        seed=seed,
        snapshot=chain.snapshot,
        run_id=report.run_id,
        chain=chain,
        result=result,
        report=report,
        envelope=envelope,
        addresses=audit_payload_provenance(envelope["payload"]),
        follower=adjustment,
    )


# -- §10's blocks ---------------------------------------------------------------


def _scored(result):
    """The wallets that produced a :class:`contracts.BuyQuality`, in address order.

    Address order rather than the caller's: every aggregate below accumulates over this sequence and
    §9.2 requires the published number to be reproducible. ``run_wallet_window`` already sorts, and
    this restates the requirement locally rather than depending on it.
    """
    return tuple(sorted(
        (w for w in result.wallets if w.quality is not None), key=lambda w: w.wallet
    ))


def _basis_for(accounts):
    """One wallet's §10 amounts, summed in the order ``scoring`` summed them.

    Order matters and is not decoration: ``scoring.buy_quality_detail`` accumulates the same three
    amounts over the same accounts in the same order, and ``reporting.report_wallet`` refuses a
    score whose shares disagree with the amounts by more than ``COMPARISON_TOLERANCE``. Summing
    these in a different order would put the disagreement in the 38th digit — under the tolerance,
    invisible, and a habit that stops being invisible the first time a basket is large enough.
    """
    return value_basis(
        realized_usd=total((a.realized_proceeds_usd for a in accounts), "realized_usd"),
        marked_usd=total((a.marked_usd for a in accounts), "marked_usd"),
        dead_usd=total((a.dead_usd for a in accounts), "dead_usd"),
    )


def _basket_basis(scored):
    """The whole basket's §10 amounts, summed wallet by wallet in address order.

    One function rather than two summations, because :func:`_assemble` reports it and
    :func:`_capital_ladder` sizes every capital level's value-basis shares from it: two
    accumulations of one quantity are two numbers that can differ in the last place, and §9.2 fixes
    the published figure rather than the way it was reached.
    """
    per_wallet = tuple(_basis_for(wallet.accounts) for wallet in scored)
    return value_basis(
        realized_usd=total((b.realized_usd for b in per_wallet), "realized_usd"),
        marked_usd=total((b.marked_usd for b in per_wallet), "marked_usd"),
        dead_usd=total((b.dead_usd for b in per_wallet), "dead_usd"),
    )


def _quote_assets():
    """The two §4.6 quote assets this fixture prices, with their decimals.

    Built here rather than in ``chain`` because it is a *depth* input: ``chain.PRICES`` is USD per
    raw unit, which is what ``marking`` multiplies a reserve by, and ``depth.QuoteAsset`` wants the
    whole-token price and the decimals separately. The two are the same fact spelled for two
    consumers; both are derived from the same constants so they cannot drift.
    """
    from contracts import USDC, WETH

    return {
        WETH: QuoteAsset(address=WETH, decimals=WETH_DECIMALS, usd_price=WETH_USD),
        USDC: QuoteAsset(address=USDC, decimals=USDC_DECIMALS, usd_price=USDC_USD),
    }


def _priced_pool(chain, asset, quotes):
    """The pool a follower's copy of a buy in ``asset`` would be sized against.

    The horizon snapshot, deliberately — see the module docstring.
    """
    pool = chain.pools[normalise_asset(asset)]
    return PricedPool(state=pool, quote=quotes[normalise_asset(pool.quote)])


def _simulate(chain, account, level, quotes):
    """§4.5 for one buy at one capital level, through ``depth`` and nothing else.

    ``leader_clip`` is the leader's own USD cost for this buy, so the follower is displaced by the
    trade they are copying rather than quoting into an untouched pool. ``leader_return`` is the
    leader's measured 30-day return on it, so ``follower_return`` is that return net of the
    execution drag rather than the drag alone.
    """
    return size_to_cost_cap(
        _priced_pool(chain, account.buy.asset, quotes),
        SYNTHETIC_TIER,
        level,
        account.cost_usd,
        GAS_USD,
        leader_return=account.return_pct,
    )


def leader_buys(chain, scored, quotes):
    """One :class:`pipeline.stages.benchmark.LeaderBuy` per scored buy, in wallet then buy order.

    The wrapper is what pairs a §4.4 outcome with the pool its copy is priced against, so the two
    cannot drift apart. Public because :mod:`tools.mockchain.stages` hands the identical sequence to
    the ``follower.adjust`` stage: one construction, so the stage and the §10 report cannot disagree
    about what was simulated.
    """
    buys = []
    for wallet in scored:
        for account in wallet.accounts:
            buys.append(LeaderBuy(
                outcome=buy_outcome(
                    buy=account.buy,
                    trade_value_usd=account.cost_usd,
                    return_pct=account.return_pct,
                    realized_usd=account.realized_proceeds_usd,
                    marked_usd=account.marked_usd,
                    dead_usd=account.dead_usd,
                    bucket=account.bucket,
                ),
                pool=_priced_pool(chain, account.buy.asset, quotes),
                tier=SYNTHETIC_TIER,
                leader_clip_usd=account.cost_usd,
                gas_usd=GAS_USD,
            ))
    return tuple(buys)


class _LadderContext(object):
    """The two fields ``follower_adjust_runner`` reads off a ``StageContext``, and nothing else.

    A real :class:`phase0.execution.StageContext` is a ``phase0`` type, and rule 2 of this module's
    header is that nothing here imports a ``phase0`` name — a module that could reach the state
    machine is a module that could be asked to move it. The runner reads ``run_id`` and ``commit``
    to stamp its result and reads nothing else, so this is the whole of what it needs. Driving the
    stage *under governance* is :func:`tools.mockchain.stages.drive_synthetic_phase0`'s job, and it
    hands the same runner the same buys through ``phase0.execution.execute_stage``.
    """

    __slots__ = ("run_id", "commit")

    def __init__(self, run_id_, commit):
        self.run_id = run_id_
        self.commit = commit


def _capital_ladder(chain, scored, basket_basis, quotes):
    """All five §3.1 levels, through the ``follower.adjust`` stage runner and nothing else.

    **This composition is not repeated here, and that is the repair.** ``§4.5 at five capital
    levels`` is implemented once, in :func:`pipeline.stages.benchmark.follower_adjust_runner`, and
    this fixture used to implement it a second time — with the opposite convention for a buy the
    follower could not execute. The stage *drops* such a buy from the follower's score; this module
    entered it at a return of zero. Both cited ticket 63. Measured at seed 7, where four of 1,041
    buys are uncopyable, the two conventions published a mean follower-adjusted buy quality of
    ``0.02484988`` and ``0.01932769`` at the $100k level — a 28% difference in a §10 headline
    figure, in a block with no field that says which convention produced it. The stage is the
    authority: it is the code a real run executes.

    What that costs, stated because it is real: two wallets — every one of whose buys was
    uncopyable — leave the ladder's mean entirely, so ``n_wallets`` on each level is 7 against a
    §10 basket of 9. ``CapitalLevelReport`` has no field for the difference, which is why
    :attr:`SyntheticRun.follower` carries the whole :class:`~pipeline.stages.benchmark.FollowerAdjustment`
    and its per-level ``unscorable_wallets``. A reader of the published payload alone sees the
    smaller ``n_wallets`` and not the reason.

    :returns: the :class:`~pipeline.stages.benchmark.FollowerAdjustment`, not the ladder. The
        caller takes ``.ladder`` for the report and keeps the rest.
    """
    adjustment = follower_adjust_runner(
        leader_buys=leader_buys(chain, scored, quotes),
        value_basis_by_level={level: basket_basis for level in CAPITAL_LEVELS},
    )(_LadderContext(run_id(chain.seed), SYNTHETIC_COMMIT))
    if adjustment.ladder is None:
        raise ValueError(
            "the synthetic run at seed {} produced no §10 capital ladder: {}".format(
                chain.seed, adjustment.ladder_refusal
            )
        )
    return adjustment


def _churn(chain):
    """§10's churn block over the **selected** population, including the wallets that never traded.

    The counts come from :class:`tools.mockchain.chain.SyntheticChain` rather than from the run
    result, and that is the whole point of the block: the result knows only about wallets that
    produced a transaction, so a churn rate computed from it would be a churn rate over the
    survivors — the survivorship error §10's churn block exists to make impossible. The silent
    wallet has zero forward buys and appears here as `Inactive`.
    """
    return report_churn(tuple(
        WalletActivity(
            wallet=wallet,
            baseline_valid_buys=chain.baseline_valid_buys[wallet],
            baseline_days=chain.baseline_days,
            forward_valid_buys=chain.forward_valid_buys[wallet],
            forward_days=chain.forward_days,
        )
        for wallet in SELECTED_WALLETS
    ))


def _profit_usd(accounts):
    """Realized proceeds plus the marked value of what is still open, less cost.

    ``marked_value_usd`` and not ``dead_usd``: a dead position is worth zero, and §10's dead *share*
    carries the exposure the zero verdict decided, which is a different question from what the
    wallet made. Using the exposure here would report a rugged wallet as having lost nothing.
    """
    gross = ZERO
    cost = ZERO
    for account in accounts:
        gross = add(gross, add(account.realized_proceeds_usd, account.marked_value_usd))
        cost = add(cost, account.cost_usd)
    return sub(gross, cost), cost


def _scope(chain, band=None):
    return DiagnosticScope(
        chain=SYNTHETIC_CHAIN,
        window=chain.window.index,
        population=POPULATION,
        band=band,
    )


def _diagnostics(chain, scored):
    """§10's diagnostics, computed from the run — every one of them DIAGNOSTIC_ONLY by type.

    Only diagnostics this run can actually measure are emitted. ``bucket_a_isolated`` is omitted
    entirely when no buy landed in bucket A, rather than reported as zero: a zero there would say
    the first-block buys broke even, which is a finding, and "there were none" is not one.
    """
    accounts = tuple(a for wallet in scored for a in wallet.accounts)
    scope = _scope(chain)
    items = []

    profit, cost = _profit_usd(accounts)
    items.append(profit_ranking(scope, tuple(
        (wallet.wallet, _profit_usd(wallet.accounts)[0]) for wallet in scored
    )))
    items.append(diagnostic("simple_wallet_return", scope, divide(profit, cost), RATIO))
    items.append(diagnostic(
        "buy_win_rate",
        scope,
        divide(sum(1 for a in accounts if a.return_pct > 0), len(accounts)),
        RATIO,
    ))
    items.append(diagnostic(
        "median_return", scope, median((a.return_pct for a in accounts), "return_pct"), RATIO
    ))

    # The mean return of the worst tenth of buys, at least one buy. §10 names ``tail_loss`` and
    # does not define the tail, so the definition is here, once, and in the message a reader gets.
    worst = sorted((a.return_pct for a in accounts))[: max(1, len(accounts) // 10)]
    items.append(diagnostic("tail_loss", scope, mean(worst, "tail return"), RATIO))

    bucket_a = tuple(a for a in accounts if a.bucket is TokenAgeBucket.A)
    if bucket_a:
        items.append(diagnostic(
            "bucket_a_isolated",
            scope,
            weighted_mean((_weight_of(a), a.return_pct) for a in bucket_a),
            RATIO,
        ))

    for band, wallets in _by_activity_band(chain, scored):
        items.append(diagnostic(
            "activity_band_sensitivity",
            _scope(chain, band=band),
            mean((w.quality.value for w in wallets), "buy_quality"),
            RATIO,
        ))

    return diagnostic_pack(tuple(items))


def _weight_of(account):
    """§4.4's log weight for one buy, computed by ``scoring`` rather than restated here."""
    from scoring import trade_weight

    return trade_weight(account.cost_usd)


def _by_activity_band(chain, scored):
    """Scored wallets grouped by §10's activity band, in band order, empty bands omitted.

    The band is taken from the **baseline** valid-buy count, which is what §6 selects on and what
    ``reporting.activity_band`` bounds at [20, 1000]. Taking it from the forward count would put a
    wallet with one forward buy outside every band and raise, which would file a fixture property as
    a selection error.
    """
    from reporting import ACTIVITY_BAND_BOUNDS, activity_band

    grouped = {}
    for wallet in scored:
        band = activity_band(chain.baseline_valid_buys[wallet.wallet])
        grouped.setdefault(band, []).append(wallet)
    return tuple(
        (band, tuple(grouped[band]))
        for band in ACTIVITY_BAND_BOUNDS
        if band in grouped
    )


def _assemble(chain, result, adjustment=None):
    """§10's required outputs for one synthetic window, through ``reporting`` and nothing else.

    :param adjustment: the :class:`~pipeline.stages.benchmark.FollowerAdjustment` the capital
        ladder comes from, when the caller has already computed it. Built here when omitted. It is
        an argument so that :func:`synthetic_report` can keep the whole adjustment on the run —
        §10's block drops the per-level ``unscorable_wallets`` — without simulating 1,041 buys at
        five capital levels twice.
    """
    scored = _scored(result)
    if not scored:
        # ``report_basket`` would refuse the empty basket anyway; refusing here names the actual
        # problem — the generator produced no scorable wallet — instead of describing an aggregate.
        raise ValueError(
            "the synthetic run at seed {} scored no wallet, so there is no §10 basket to report. "
            "That is a defect in the generator or in the pipeline rather than a finding: the plan "
            "in tools.mockchain.chain places 20 and 1,000 valid buys in the window on "
            "purpose.".format(chain.seed)
        )

    pairs = tuple((w.quality, _basis_for(w.accounts)) for w in scored)
    basket = report_basket(pairs)
    basket_basis = _basket_basis(scored)

    if adjustment is None:
        adjustment = _capital_ladder(chain, scored, basket_basis, _quote_assets())

    return report_run(
        run_id=run_id(chain.seed),
        chain=SYNTHETIC_CHAIN,
        basket=basket,
        windows=(
            WindowReport(
                window=chain.window.index,
                columns=(),
                missing_columns=GATING_COLUMNS,
            ),
        ),
        capital_ladder=adjustment.ladder,
        churn=_churn(chain),
        diagnostics=_diagnostics(chain, scored),
    )
