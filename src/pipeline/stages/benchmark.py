"""Runners for ``benchmark.match`` and ``follower.adjust``.

``phase0.execute_stage`` authorises a stage, opens its run record, calls a ``runner(context)`` and
records the outcome. It takes the runner as an argument because ``phase0`` is SHARED and must not
know what a stage does. This module is the other half of that arrangement for two stages: it lives
in ``pipeline``, the composition root, which is the one builder package permitted to import other
builder packages, and it is therefore allowed to know exactly what these two stages compute.

    benchmark.match    matching_null.build_matched_sets_detail    §6.6
    follower.adjust    depth sizing -> scoring -> reporting.capital   §4.5 · §10

Both runners are built by a **factory**: the stage inputs are bound once, at wiring time, and the
returned closure takes nothing but the :class:`phase0.execution.StageContext`. Nothing here imports
``phase0`` — the context is read for four attributes (``stage``, ``run_id``, ``commit``,
``child_seed``) and never for a governance handle, because a runner that could move the state
machine would be a runner that could authorise itself.

What each runner raises, and what it carries
--------------------------------------------

The line is the house rule: *a disappointing measurement is a carried status; a defect in what
assembled the call raises.* Applied here:

* a matched set that fails the §6.6 balance target is **carried** — :attr:`BenchmarkMatch.balanced`
  is ``False`` and the whole balance table travels with it;
* selected wallets that could not be matched are **carried** in ``unmatched``;
* ``MatchingInfeasible`` — *no* selected wallet could be matched — is **not** caught. ``matching_null``
  already ruled that an empty match must never be reduced to an empty balance table, because
  ``CovariateBalance.balanced`` is ``all(())`` and would report perfect balance. Catching it here to
  return a ``balance=None`` would rebuild that hazard one layer up;
* a capital level at which nothing could be traded is **carried** as
  :attr:`LevelOutcome.unreportable_reason`, and the ladder that cannot be built from it is carried
  as :attr:`FollowerAdjustment.ladder_refusal`;
* ``LongTailExcludedError`` from :func:`depth.cost_cap_for`, ``OutsideValidityBand`` from a leader
  clip beyond the depth model, a capital level with no value basis, and a wallet with no scorable
  buys at all **raise**. Each says the call was assembled wrongly — an out-of-scope asset, an
  unmodelled pool state, a missing input, a wallet that has no §4.4 score to be a denominator.

Neither runner catches a broad exception and returns a plausible-looking ``None``. The two ``None``
fields that exist (:attr:`LevelOutcome.report`, :attr:`FollowerAdjustment.ladder`) are each paired
with a reason field, and each dataclass refuses at construction unless exactly one of the pair is
set — so there is no value of these types that says "nothing measured" without saying why.

Ordering
--------

Wallets are processed in sorted address order and a wallet's buys in sorted ``tx_hash`` order,
never in the caller's order. Decimal addition at 38 digits is not associative, so the same basket
supplied in a different order would produce means differing in their last digits; sorting makes the
published figures a function of the data alone. This is the argument ``matching_null.matching``
makes about its universe, applied to the basket. The ordering is numerical hygiene only and carries
no chronological meaning: each buy is priced against its own pool state, so nothing here depends on
sequence.
"""

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Optional, Tuple

from contracts import AssetTier, BuyOutcome, CopySimulation, calc, require_finite
from depth import PricedPool, size_to_cost_cap_detail
from matching_null import (
    PRIMARY_CONTROLS,
    ROBUSTNESS_CONTROLS,
    MatchingResult,
    build_matched_sets_detail,
)
from reporting import (
    CAPITAL_LEVELS,
    CapitalLadderReport,
    CapitalLevelReport,
    ValueBasisAmounts,
    WalletCapitalOutcome,
    level_key,
    report_capital_ladder,
    report_capital_level,
)
from scoring import UnscorableWallet, buy_quality

ZERO = Decimal("0")

#: The seed purpose for ``benchmark.match``. Pinned as a constant rather than spelled at the call
#: site: the child seed is ``HMAC(master_seed, commit | purpose | index)``, so this string is part
#: of the derivation and changing it changes every matched set the run produces.
BENCHMARK_MATCH_SEED_PURPOSE = "benchmark.match"


# -- benchmark.match ------------------------------------------------------------


@dataclass(frozen=True)
class BenchmarkMatch:
    """What ``benchmark.match`` publishes: the §6.6 matched sets and the balance table.

    The run identity travels with the result because the pre-registration's reproducibility claim
    is about a triple, not about a number: the same dataset snapshot, the same commit and the same
    master seed must produce the same matched set. ``commit`` and ``seed`` are two thirds of that
    triple; the third is the dataset snapshot, which is on the run record rather than here.

    ``balanced`` being ``False`` is a *result*. It says the ten §6.6 dimensions could not all be
    brought inside the 0.10 target by the frozen universe, which is a fact about the population and
    a reason to distrust the contrast — not a failure of this stage.
    """

    run_id: str
    commit: str
    seed: int
    n_selected: int
    result: MatchingResult

    @property
    def sets(self):
        """The :class:`contracts.MatchedSet` per successfully matched selected wallet."""
        return self.result.sets

    @property
    def balance(self):
        """The primary controls' :class:`contracts.CovariateBalance`. Never ``None``."""
        return self.result.balance

    @property
    def robustness_balance(self):
        """The robustness controls' balance, or ``None`` when none were requested.

        Reported, and unable to move the gate: §6.6 makes the primary set the benchmark and the
        robustness set a report.
        """
        return self.result.robustness_balance

    @property
    def balanced(self):
        """§6.6: every one of the ten SMDs inside :data:`contracts.SMD_BALANCE_TARGET`."""
        return self.result.balance.balanced

    @property
    def worst_dimension(self):
        """``(dimension, smd)`` for the least balanced dimension — the one to argue about."""
        return self.result.balance.worst_dimension

    @property
    def effective_sample_size(self):
        """Kish's ESS over control *reuse*.

        Matching is with replacement, so the nominal control count overstates the benchmark. This
        is the number that says by how much, and it is the one to quote — not ``len(sets)``.
        """
        return self.result.balance.effective_sample_size

    @property
    def unmatched(self):
        """Selected wallets given no full primary control set, each with the reason it was not."""
        return self.result.unmatched

    @property
    def n_matched(self):
        return len(self.result.matches)


def benchmark_match_runner(selected, universe, features, t0_block, t0_timestamp=None,
                           n_primary=PRIMARY_CONTROLS, n_robustness=ROBUSTNESS_CONTROLS,
                           caliper=None):
    """Build the ``benchmark.match`` runner over one frozen T0 snapshot.

    The arguments are ``matching_null.build_matched_sets_detail``'s, minus ``seed``. The seed is
    deliberately not an argument: it is derived inside the runner from
    ``context.child_seed("benchmark.match", 0)``, so it is a function of the run's master seed and
    the pinned commit and of nothing else. Nothing here touches ``random`` or the clock, and a
    caller cannot supply a seed of their own — which is what makes the §6.6 claim that the same
    snapshot, commit and seed reproduce the same matched set checkable rather than asserted.

    :param selected: the wallets chosen at T0 (§6.5). Materialised here, so a generator is safe.
    :param universe: the frozen T0 universe (§6.4).
    :param features: ``wallet -> WalletFeatures``, or an iterable of them. Copied here for the same
        reason — the factory may be called long before the runner is.
    :param caliper: defaults to ``None``, i.e. **no caliper**, matching ``matching_null``'s own
        default. §6.6 pre-registers none, and a default one here would be an unregistered threshold
        deciding which selected wallets leave the analysis.

    :returns: ``runner(context) -> BenchmarkMatch``.

    What this does not do: it does not check that ``features`` was computed pre-T0 — ``matching_null``
    does that, on every supplied record rather than only the used ones, and doing it here as well
    would be a second implementation of the one rule that must not be duplicated.
    """
    selected = tuple(selected)
    universe = tuple(universe)
    features = dict(features) if hasattr(features, "items") else tuple(features)

    def runner(context):
        seed = context.child_seed(BENCHMARK_MATCH_SEED_PURPOSE, 0)
        result = build_matched_sets_detail(
            selected, universe, features, t0_block, seed,
            t0_timestamp=t0_timestamp,
            n_primary=n_primary,
            n_robustness=n_robustness,
            caliper=caliper,
        )
        return BenchmarkMatch(
            run_id=context.run_id,
            commit=context.commit,
            seed=seed,
            n_selected=len(selected),
            result=result,
        )

    return runner


# -- follower.adjust ------------------------------------------------------------


@dataclass(frozen=True)
class LeaderBuy:
    """One leader buy, plus everything ``depth`` needs to price a follower's copy of it.

    ``outcome`` is the leader-side §4.4 atom, already carrying the log trade weight, the §4.7
    bucket, the realized / marked / dead basis, and the leader's own 30-day return. The
    follower-adjusted score is that same atom with the return replaced, so the two columns are
    weighted identically and their ratio is a statement about returns rather than about weights.

    ``leader_clip_usd`` is the leader's own size, and it is an input rather than something derived
    here: §4.5's copier penalty puts the leader's size in at double weight, so a wrong clip moves
    the follower's cost by twice its own error.
    """

    outcome: BuyOutcome
    pool: PricedPool
    tier: AssetTier
    leader_clip_usd: Decimal
    gas_usd: Decimal = ZERO

    def __post_init__(self):
        if not isinstance(self.outcome, BuyOutcome):
            raise TypeError(
                "LeaderBuy.outcome must be a contracts.BuyOutcome built by scoring.buy_outcome, "
                "got {}. Building it there is what computes log(1 + trade_value_usd) once instead "
                "of at every call site.".format(type(self.outcome).__name__)
            )
        if not isinstance(self.pool, PricedPool):
            raise TypeError(
                "LeaderBuy.pool must be a depth.PricedPool — sizing needs the quote asset's "
                "decimals and USD price — got {}".format(type(self.pool).__name__)
            )
        if not isinstance(self.tier, AssetTier):
            raise TypeError(
                "LeaderBuy.tier must be a contracts.AssetTier, got {}".format(
                    type(self.tier).__name__
                )
            )
        for name in ("leader_clip_usd", "gas_usd"):
            amount = require_finite(calc(getattr(self, name)), name)
            if amount < 0:
                raise ValueError(
                    "{} is {}; a negative {} would show up as a follower subsidy and inflate "
                    "every return at every capital level".format(name, amount, name)
                )
            object.__setattr__(self, name, amount)
        if not self.wallet:
            raise ValueError(
                "buy {} names no portfolio owner, so it cannot be attributed to a wallet and the "
                "follower-adjusted score has no basket to belong to".format(self.tx_hash)
            )

    @property
    def wallet(self):
        """The owning wallet, case-folded. Read from the trade, never supplied separately."""
        return (self.outcome.buy.portfolio_owner or "").lower()

    @property
    def tx_hash(self):
        return self.outcome.buy.tx_hash


@dataclass(frozen=True)
class LevelOutcome:
    """One capital level: §10's block, or the reason there is not one.

    Exactly one of ``report`` and ``unreportable_reason`` is set, and the constructor refuses
    anything else. That is what keeps ``report is None`` from ever being read as "measured zero" —
    a level with no block always says, in the same object, why there is none.

    ``unscorable_wallets`` is the capacity cliff made visible at wallet granularity: it names every
    wallet in the basket that could not place a single executable order at this level, with the
    reason. Those wallets are absent from ``report``, so ``report.n_wallets`` falls as the level
    rises and the raw column is **not** constant across the ladder. Comparing two levels' means
    without reading this tuple compares two different baskets.

    The per-order simulations travel with the block, in the same spirit as
    ``matching_null.MatchingResult`` carrying every candidate's distance: they are the evidence
    behind the aggregated figures, and they carry one number the §10 block has no field for —
    ``CopySimulation.fill_ratio``, the share of *this* capital level the signal could absorb. See
    :func:`follower_adjust_runner` for why that number is the one to look at when the ladder is
    flat.
    """

    capital_level: Decimal
    report: Optional[CapitalLevelReport]
    unreportable_reason: Optional[str]
    simulations: Tuple[CopySimulation, ...] = ()
    scored_wallets: Tuple[str, ...] = ()
    unscorable_wallets: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "simulations", tuple(self.simulations))
        object.__setattr__(self, "scored_wallets", tuple(self.scored_wallets))
        object.__setattr__(self, "unscorable_wallets", tuple(self.unscorable_wallets))
        if (self.report is None) == (self.unreportable_reason is None):
            raise ValueError(
                "a capital level carries either §10's block or the reason it has none, never both "
                "and never neither; got report={} reason={}".format(
                    self.report, self.unreportable_reason
                )
            )

    @property
    def reported(self):
        return self.report is not None

    @property
    def n_simulated(self):
        return len(self.simulations)

    @property
    def n_executable(self):
        """Derived rather than stored, so it cannot disagree with the simulations it counts."""
        return sum(1 for sim in self.simulations if sim.copyable)


@dataclass(frozen=True)
class FollowerAdjustment:
    """What ``follower.adjust`` publishes: all five levels, and the ladder if it exists.

    Exactly one of ``ladder`` and ``ladder_refusal`` is set. ``reporting.capital`` refuses a
    partial :class:`~reporting.capital.CapitalLadderReport` — ``IncompleteCapitalLadder``, because
    the ladder is how the capacity cliff is located and a gap in it is exactly where the cliff would
    hide — so a level that could not be reported means there is no ladder, and the refusal says
    which levels and why. ``levels`` is always all five regardless, in ascending order.
    """

    run_id: str
    commit: str
    levels: Tuple[LevelOutcome, ...]
    ladder: Optional[CapitalLadderReport] = None
    ladder_refusal: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "levels", tuple(self.levels))
        if (self.ladder is None) == (self.ladder_refusal is None):
            raise ValueError(
                "follower.adjust carries either the five-level ladder or the reason it has none, "
                "never both and never neither"
            )
        present = [outcome.capital_level for outcome in self.levels]
        if present != list(CAPITAL_LEVELS):
            raise ValueError(
                "every one of §3.1's five capital levels is computed, in ascending order; got "
                "{}. A level dropped from this tuple would be a rung nobody can see is "
                "missing.".format(present)
            )

    @property
    def complete(self):
        return self.ladder is not None

    def at(self, level):
        """The :class:`LevelOutcome` at one level, reported or not."""
        key = level_key(level)
        for outcome in self.levels:
            if outcome.capital_level == key:
                return outcome
        raise KeyError("no outcome at capital level {}".format(key))


def follower_adjust_runner(leader_buys, value_basis_by_level):
    """Build the ``follower.adjust`` runner over one basket of leader buys.

    §4.5, at §3.1's five capital levels. For each buy, at each level:

        1. ``depth.size_to_cost_cap_detail`` sizes the follower's order to the largest amount whose
           total execution cost stays within the tier cap, bounded by the level as ``strategy_aum``,
           and prices it with the copier penalty — the leader's size at double weight, because the
           follower eats the leader's *marginal* impact and not their average;
        2. the resulting :class:`contracts.CopySimulation` joins the level's simulation set, which
           is where §10's unexecutable trade share and positive trade rate come from;
        3. an executable order's ``follower_return`` replaces the leader's return on the §4.4 atom,
           and ``scoring.buy_quality`` rescores the wallet from those.

    Then :func:`reporting.report_capital_level` per level and
    :func:`reporting.report_capital_ladder` over the five.

    No seed is drawn. Nothing in this stage is stochastic: depth sizing bisects a convex cost curve
    to a fixed tolerance and scoring is a weighted mean, so ``context`` is read only for the run
    identity carried on the result.

    **A buy the follower could not execute is excluded from their score, not entered as a zero.**
    §4.5 does not settle this and it changes the published number, so the reasoning is written
    down rather than assumed. ``depth`` refuses to name a ``follower_return`` for a rejected order
    at all — ``copyable=False`` carries a reason and ``follower_return is None`` — and §4.4's buy
    quality is a weighted mean of buy returns, which for a follower who placed no buy has no term
    to contribute. Entering a ``0`` would say the follower made a trade that broke even. Ticket 63
    settles the reading independently: the unexecutable trade share is reported *separately* so
    that "the edge survived" is distinguishable from "most of the edge could not be traded at all",
    and that separation only carries information if the follower-adjusted quality is measured on
    the trades that happened. Under a zero-fill rule the share would already be inside the number.

    What that costs, stated plainly: Copy Retention at a level with unexecutable trades is **not**
    like-for-like. Its numerator is the follower's experience of the executable subset and its
    denominator is the leader's experience of the whole basket, so it overstates retention exactly
    when execution was hardest. ``LevelOutcome.unscorable_wallets`` and the report's
    ``unexecutable_trade_share`` are what make that readable; neither is optional decoration.

    **A flat ladder is a result about the pools, not a wiring failure.** §4.5 sizes every order to
    the cost cap, and the cap, the leader's footprint and the validity band are all functions of
    the pool rather than of the capital level. So whenever the cap-limited size falls below
    $100,000, the same order is placed at all five levels: every figure in
    :class:`~reporting.capital.CapitalLevelReport` is then identical across the ladder except the
    value-basis shares, which are an input. The five levels separate only in the regime where
    ``strategy_aum`` is the binding constraint. What still distinguishes them in the flat regime is
    ``CopySimulation.fill_ratio`` — the share of the level's capital the signal absorbed, which is
    1 at $100k and 0.05 at $2M for a $100k order — and §10's block has no field for it. That is why
    :attr:`LevelOutcome.simulations` is carried: without it the ladder can look identical at five
    levels that absorbed twenty-fold different amounts of capital.

    :param leader_buys: :class:`LeaderBuy` per simulated leader buy, across all wallets in the
        basket. Grouped by wallet here — a wallet is never supplied separately from its trades, so
        the two cannot disagree.
    :param value_basis_by_level: ``level -> reporting.ValueBasisAmounts``, all five levels. The
        realized / marked / dead split is the follower's at that level, so it is an input from the
        marking lane rather than something this composition can derive. **A missing level raises**:
        §10 fixes the ladder at five rungs, so an absent one is a defect in the call, not a level
        with nothing in it. Zero measured capacity at a level is the opposite case and is carried.

    :returns: ``runner(context) -> FollowerAdjustment``.
    """
    buys = tuple(leader_buys)
    for buy in buys:
        if not isinstance(buy, LeaderBuy):
            raise TypeError(
                "follower.adjust consumes LeaderBuy, got {}. The wrapper is what pairs a §4.4 "
                "outcome with the pool state its copy is priced against, so the two cannot drift "
                "apart.".format(type(buy).__name__)
            )
    if not buys:
        raise ValueError(
            "no leader buys were supplied. §10's block over an empty basket would report an "
            "unexecutable share of zero, which reads as 'everything was executable' — the "
            "opposite of what no data means."
        )

    by_wallet = _group_by_wallet(buys)
    value_basis = _resolve_value_basis(value_basis_by_level)

    def runner(context):
        raw_quality = {
            wallet: buy_quality([b.outcome for b in wallet_buys], wallet).value
            for wallet, wallet_buys in by_wallet.items()
        }

        levels = tuple(
            _level_outcome(level, by_wallet, raw_quality, value_basis[level])
            for level in CAPITAL_LEVELS
        )

        unreported = [outcome for outcome in levels if not outcome.reported]
        if unreported:
            return FollowerAdjustment(
                run_id=context.run_id,
                commit=context.commit,
                levels=levels,
                ladder=None,
                ladder_refusal=(
                    "§10 requires all five capital levels and {} could not be reported: {}. The "
                    "ladder is how the capacity cliff is located, so it is refused rather than "
                    "published with a gap — the per-level outcomes above carry what was "
                    "measured.".format(
                        len(unreported),
                        "; ".join(
                            "${}: {}".format(o.capital_level, o.unreportable_reason)
                            for o in unreported
                        ),
                    )
                ),
            )

        return FollowerAdjustment(
            run_id=context.run_id,
            commit=context.commit,
            levels=levels,
            ladder=report_capital_ladder([outcome.report for outcome in levels]),
            ladder_refusal=None,
        )

    return runner


def _group_by_wallet(buys):
    """``wallet -> buys``, both orderings fixed by the data rather than by the caller.

    Wallets sorted by address, each wallet's buys sorted by ``tx_hash``, and a repeated ``tx_hash``
    refused **across the whole basket** rather than only within a wallet. Netting produces one
    ``NetTradeResult`` per transaction and attribution gives it one owner, so a second buy under the
    same hash is the caller disagreeing with itself — and it is worse when the two name different
    wallets, because one leader trade would then be simulated for two followers and the pool state
    it is priced against would be reused as though it were untouched.

    The refusal is not pedantry either way: a duplicate is simulated twice against its pool,
    counted twice in the unexecutable trade share, and weighted twice in the wallet's buy quality —
    three plausible-looking wrong numbers from one repeated input.
    """
    owner_of = {}
    for buy in buys:
        previous = owner_of.get(buy.tx_hash)
        if previous is not None:
            raise ValueError(
                "tx_hash {} appears twice, for {} and {}. One transaction nets to one trade with "
                "one portfolio owner; a repeat is simulated twice against the same pool state, "
                "counted twice in the unexecutable trade share, and weighted twice in a buy "
                "quality.".format(buy.tx_hash, previous, buy.wallet)
            )
        owner_of[buy.tx_hash] = buy.wallet

    grouped = {}
    for buy in buys:
        grouped.setdefault(buy.wallet, []).append(buy)
    return {
        wallet: tuple(sorted(grouped[wallet], key=lambda b: b.tx_hash))
        for wallet in sorted(grouped)
    }


def _resolve_value_basis(value_basis_by_level):
    """``level -> ValueBasisAmounts`` on the five pre-registered rungs, or a refusal naming the gap.

    Keys go through :func:`reporting.level_key`, so ``Decimal("1.5E+6")`` and ``Decimal("1500000")``
    are one level rather than two — and a sixth rung is refused there rather than silently carried.
    """
    if not hasattr(value_basis_by_level, "items"):
        raise TypeError(
            "value_basis_by_level must be a mapping of capital level to "
            "reporting.ValueBasisAmounts, got {}".format(type(value_basis_by_level).__name__)
        )

    resolved = {}
    for level, basis in value_basis_by_level.items():
        key = level_key(level)
        if key in resolved:
            raise ValueError(
                "two value bases were supplied for ${}; nothing here can say which one describes "
                "the level, and picking by iteration order would let the caller's ordering choose "
                "§10's realized / marked / dead mix".format(key)
            )
        if not isinstance(basis, ValueBasisAmounts):
            raise TypeError(
                "the value basis at ${} must be a reporting.ValueBasisAmounts, got {}".format(
                    key, type(basis).__name__
                )
            )
        resolved[key] = basis

    missing = [level for level in CAPITAL_LEVELS if level not in resolved]
    if missing:
        raise ValueError(
            "no value basis for capital level(s) {}. §10 fixes the ladder at five rungs, so a "
            "level with no input is a defect in the call — not a level at which nothing was "
            "measured, which is carried as a status instead.".format(
                ", ".join("${}".format(level) for level in missing)
            )
        )
    return resolved


def _level_outcome(level, by_wallet, raw_quality, value_basis):
    """§10's block at one capital level, or the reason there is none.

    Every wallet is simulated at every level even when earlier levels already exhausted the pool:
    the cost cap and the validity band are functions of the level, so a wallet unscorable at $500k
    may well be scorable at $100k, and skipping would decide the shape of the cliff in advance.
    """
    simulations = []
    outcomes = []
    scored = []
    unscorable = []

    for wallet, wallet_buys in by_wallet.items():
        follower_outcomes = []
        for buy in wallet_buys:
            sizing = size_to_cost_cap_detail(
                buy.pool, buy.tier, level, buy.leader_clip_usd, buy.gas_usd,
                leader_return=buy.outcome.return_pct,
            )
            simulations.append(sizing.simulation)
            if sizing.copyable:
                follower_outcomes.append(replace(
                    buy.outcome,
                    return_pct=require_finite(
                        sizing.follower_return,
                        "follower_return for {} at ${}".format(buy.tx_hash, level),
                    ),
                ))

        if not follower_outcomes:
            unscorable.append((wallet, (
                "none of {} buy(s) could be placed within the execution cost cap at ${}; a "
                "follower who placed no order has no buy quality here, and a zero would read as a "
                "measured flat result".format(len(wallet_buys), level)
            )))
            continue

        try:
            follower = buy_quality(follower_outcomes, wallet).value
        except UnscorableWallet as refusal:
            # Caught by type, and recorded as an absence with its own reason attached — not
            # converted into a number. ``scoring`` raises this for a basket whose entire weight or
            # entire value basis is zero, which is a pricing failure to find rather than a score.
            unscorable.append((wallet, str(refusal)))
            continue

        outcomes.append(WalletCapitalOutcome(
            wallet=wallet,
            raw_buy_quality=raw_quality[wallet],
            follower_adjusted_buy_quality=follower,
        ))
        scored.append(wallet)

    if not outcomes:
        return LevelOutcome(
            capital_level=level_key(level),
            report=None,
            unreportable_reason=(
                "not one of the {} wallet(s) in the basket could be scored at ${}: {} simulated "
                "order(s), {} executable. §10's block needs at least one wallet's buy quality and "
                "there is none — which is a measured capacity cliff, not an empty row. Per "
                "wallet: {}".format(
                    len(by_wallet), level, len(simulations),
                    sum(1 for sim in simulations if sim.copyable),
                    "; ".join("{} — {}".format(w, why) for w, why in unscorable),
                )
            ),
            simulations=simulations,
            scored_wallets=(),
            unscorable_wallets=tuple(unscorable),
        )

    return LevelOutcome(
        capital_level=level_key(level),
        report=report_capital_level(level, outcomes, simulations, value_basis),
        unreportable_reason=None,
        simulations=simulations,
        scored_wallets=tuple(scored),
        unscorable_wallets=tuple(unscorable),
    )
