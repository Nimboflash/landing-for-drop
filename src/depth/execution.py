"""Itemised execution cost, and the largest order that stays inside the cap.

§4.5 (as amended 2026-07-31) sizes each simulated follower order to the **largest amount whose
total execution cost stays within the cap**, bounded by ``strategy_aum``:

    Order size = min( largest size whose total execution cost <= cap , strategy_aum )
    Cost caps (addendum §9.5):  major 1%   ·   mid-cap 2%   ·   long-tail excluded

Total execution cost means everything in §4.5 step 4 — DEX fee, historical gas, price impact,
slippage, and liquidity limitation — not price impact alone. Each is reported separately, because a
result that says only "the edge was destroyed" cannot be acted on, while one that says "8.0 of the
9.4 points were the leader's own footprint" can.

**The baseline is the pre-leader mid, and the leader's footprint counts against the follower's
budget.** That is not a stylistic choice: addendum §9.5 justifies excluding Ethereum long-tail by
observing that "the leader's own footprint consumes the entire slippage budget before a single
copier trades, with median long-tail S1 at $698". A cost model that measured the follower against
the *post-leader* price could never produce that finding, because the leader's footprint would have
vanished from the arithmetic.

The cost curve, with ``x`` the quote-side depth, ``a`` the leader's clip as a fraction of it, and
``z`` the follower's order in USD:

    cost(z) = fee + gas/z + (2a + a^2) + z(1+a)/x

It is **convex, not monotone**. Gas falls as ``1/z`` while impact rises linearly, so there is a
minimum viable order size as well as a maximum — a $150 order pays ~0.04% in gas, but a $5 order
pays 1%. Bisection therefore brackets the minimum first and only then searches for the upper root;
a naive single bisection on a "monotone" cost would silently return the wrong root for small caps.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Dict, Optional

from contracts import (
    CALCULATION_CONTEXT,
    EXECUTION_COST_CAP,
    AssetTier,
    ContractError,
    CopySimulation,
    LongTailExcludedError,
    add,
    calc,
    divide,
    quantize_pp,
    require_finite,
)

from .amm import (
    ONE,
    ZERO,
    DepthModel,
    PricedPool,
    ValidityBand,
    _fmt,
    _positive_usd,
    _usd,
    copier_penalty,
    measure_depth,
    own_price_impact,
)
from .orderbook import MIN_FILL_RATIO

#: Bisection stops when the bracket is this wide. One micro-dollar — :data:`contracts.SCALE_USD`,
#: the finest USD scale the reporting boundary can express, so the tolerance cannot be the thing
#: that loses a cent. A coarser tolerance would be invisible in the output and therefore unfalsifiable.
BISECTION_TOLERANCE_USD = Decimal("0.000001")

#: Halving a $2,000,000 bracket down to a micro-dollar takes ~41 steps. This ceiling exists only so
#: a non-terminating search raises instead of spinning.
MAX_BISECTION_ITERATIONS = 512

BPS = Decimal("10000")


class SizingDidNotConverge(ContractError):
    """The bisection hit its iteration ceiling. Refuses rather than returning the last guess."""


def cost_cap_for(tier):
    """§9.5. ``LONG_TAIL`` raises — it does not return zero.

    Measured Ethereum long-tail capacity really was $0 at every assumed edge level, so a returned
    zero would be indistinguishable from that finding while actually meaning "out of scope".
    **Zero capacity is a measured result; excluded scope is a modelling decision.**
    """
    if not isinstance(tier, AssetTier):
        raise TypeError("tier must be an AssetTier, got {}".format(type(tier).__name__))
    if tier is AssetTier.LONG_TAIL:
        raise LongTailExcludedError(
            "long-tail assets are excluded from Ethereum Phase 0 (addendum §9.5). Refusing to "
            "return a capacity of zero: measured long-tail capacity really was $0 at every edge "
            "level, so a zero here would be read downstream as that finding rather than as an "
            "out-of-scope modelling decision."
        )
    try:
        return EXECUTION_COST_CAP[tier]
    except KeyError:
        raise LongTailExcludedError(
            "no execution cost cap is registered for tier {}".format(tier)
        )


# -- itemised cost --------------------------------------------------------------


@dataclass(frozen=True)
class CostBreakdown:
    """The five §4.5 step-4 deductions, kept apart.

    ``price_impact_pct`` is the follower's *own* footprint — what they would have paid alone on an
    untouched pool. ``copier_penalty_pct`` is the leader's footprint, inherited by arriving after
    them. The split is the entire point of the module: the two respond to completely different
    remedies, and a single "slippage" figure hides which one is binding.

    ``liquidity_limitation_pct`` is a **quantity** shortfall, not a price, and is therefore reported
    beside the priced components rather than summed into them. Adding an unfilled share to a price
    cost would make the cap compare two different units and quietly change what "1%" means.
    """

    dex_fee_pct: Decimal
    gas_pct: Decimal
    price_impact_pct: Decimal
    copier_penalty_pct: Decimal
    liquidity_limitation_pct: Decimal = ZERO

    def __post_init__(self):
        for name in ("dex_fee_pct", "gas_pct", "price_impact_pct", "copier_penalty_pct",
                     "liquidity_limitation_pct"):
            value = require_finite(calc(getattr(self, name)), name)
            if value < 0:
                raise ValueError(
                    "{} is negative ({}); a negative execution cost would read as a subsidy "
                    "and inflate every downstream return".format(name, value)
                )
            object.__setattr__(self, name, value)

    @property
    def total_priced_cost_pct(self):
        """Everything charged against the order's notional. This is what the cap bounds."""
        with localcontext(CALCULATION_CONTEXT):
            return +(
                self.dex_fee_pct
                + self.gas_pct
                + self.price_impact_pct
                + self.copier_penalty_pct
            )

    @property
    def total_amm_slippage_pct(self):
        """``(1+a)(1+a+s) - 1`` recovered from its two halves."""
        with localcontext(CALCULATION_CONTEXT):
            return +(self.price_impact_pct + self.copier_penalty_pct)

    def deductions(self):
        """Every component, named, in the §4.5 step-4 order."""
        return {
            "dex_fee_pct": self.dex_fee_pct,
            "gas_pct": self.gas_pct,
            "price_impact_pct": self.price_impact_pct,
            "copier_penalty_pct": self.copier_penalty_pct,
            "liquidity_limitation_pct": self.liquidity_limitation_pct,
        }

    def usd(self, order_usd):
        """The same components in dollars, for an order of ``order_usd``."""
        notional = _positive_usd(order_usd, "order_usd")
        with localcontext(CALCULATION_CONTEXT):
            return {name: +(value * notional) for name, value in self.deductions().items()}


@dataclass(frozen=True)
class ExecutionQuote:
    """One priced follower order against one pool state.

    ``s1_at_trade_usd`` and ``pool_depth_at_trade_usd`` are emitted per simulated trade (ticket 30)
    so that a capacity claim can be re-derived from the pool it came from, without re-running this
    code.
    """

    pool_address: str
    model: DepthModel
    order_usd: Decimal
    filled_usd: Decimal
    leader_clip_usd: Decimal
    gas_usd: Decimal
    pool_depth_at_trade_usd: Decimal
    s1_at_trade_usd: Decimal
    costs: CostBreakdown
    validity_band: ValidityBand
    band_limited: bool = False

    @property
    def fill_ratio(self):
        if self.order_usd == 0:
            return ZERO
        return divide(self.filled_usd, self.order_usd)

    @property
    def fills(self):
        """§9.4: at least 90% order fill, or it is not a fill."""
        return self.fill_ratio >= MIN_FILL_RATIO

    @property
    def execution_cost_pct(self):
        return self.costs.total_priced_cost_pct

    @property
    def execution_price_ratio(self):
        """Execution price as a multiple of the pre-leader mid."""
        with localcontext(CALCULATION_CONTEXT):
            return +(ONE + self.costs.total_amm_slippage_pct)


def quote_execution(pool, order_usd, leader_clip_usd=ZERO, gas_usd=ZERO, allow_partial_fill=False):
    """Price one follower order arriving after ``leader_clip_usd`` on the same pool state.

    Simulates the §9.4 entry: the first full block after the leader, best deterministic public
    single-pool execution, no future information. The leader's clip is an input, never something
    this function looks forward to discover.

    With ``allow_partial_fill`` left False, an order beyond the depth model's validity band is
    **refused** rather than extrapolated. With it True, the order is filled only to the band edge
    and the shortfall is recorded as liquidity limitation — still no extrapolation, but the caller
    gets a measured partial instead of an exception.
    """
    depth = measure_depth(pool)
    order = _positive_usd(order_usd, "order_usd")
    leader = _usd(leader_clip_usd, "leader_clip_usd")
    gas = _usd(gas_usd, "gas_usd")
    band = depth.validity_band

    # The leader's own clip has to be inside the band before the follower's can be priced at all:
    # if the leader already left the modelled range, the price the follower inherits is unknown.
    band.require(leader, what="leader clip")

    ceiling = _band_ceiling(band, leader)
    band_limited = False
    filled = order
    if ceiling is not None and order > ceiling:
        if not allow_partial_fill:
            # ``add`` and not ``+``. The bare addition ran in the caller's ambient 28-digit
            # context while ``ceiling`` was computed under the frozen 38-digit one, so an order
            # carrying more than 28 significant digits could be rounded back onto the band edge:
            # ``order > ceiling`` said "outside", ``contains(leader + order)`` said "inside", and
            # a call that explicitly refused partial fills got one anyway — band-limited, with a
            # 2E-32 liquidity limitation and no exception.
            band.require(add(leader, order), what="leader clip plus follower order")
        filled = ceiling
        band_limited = True

    if filled <= 0:
        raise ValueError(
            "the leader's clip alone fills the validity band of pool {}; there is no in-band size "
            "left to price for a follower".format(depth.pool_address)
        )

    fee_bps = pool.state.fee_bps
    if not isinstance(fee_bps, int) or isinstance(fee_bps, bool) or fee_bps < 0:
        raise ValueError("fee_bps must be a non-negative int, got {!r}".format(fee_bps))

    with localcontext(CALCULATION_CONTEXT):
        costs = CostBreakdown(
            dex_fee_pct=divide(fee_bps, BPS),
            gas_pct=divide(gas, filled),
            price_impact_pct=own_price_impact(depth.effective_depth_usd, filled),
            copier_penalty_pct=copier_penalty(depth.effective_depth_usd, leader, filled),
            liquidity_limitation_pct=+(ONE - divide(filled, order)),
        )

    return ExecutionQuote(
        pool_address=depth.pool_address,
        model=depth.model,
        order_usd=order,
        filled_usd=filled,
        leader_clip_usd=leader,
        gas_usd=gas,
        pool_depth_at_trade_usd=depth.effective_depth_usd,
        s1_at_trade_usd=depth.s1_usd,
        costs=costs,
        validity_band=band,
        band_limited=band_limited,
    )


def _band_ceiling(band, leader_clip_usd):
    """How much room the follower has left inside the band after the leader's displacement."""
    if band.max_size_usd is None:
        return None
    with localcontext(CALCULATION_CONTEXT):
        return +(band.max_size_usd - leader_clip_usd)


# -- sizing ---------------------------------------------------------------------


@dataclass(frozen=True)
class SizingResult:
    """The full answer, of which :class:`contracts.CopySimulation` is the seam-shaped summary.

    The seam type carries what the rest of the pipeline consumes; this carries what a reviewer
    needs to reproduce it — the depth it was measured against, ``S1`` at trade time, the itemised
    deductions, and which constraint actually bound.
    """

    pool_address: str
    model: DepthModel
    tier: AssetTier
    capital_level: Decimal
    leader_clip_usd: Decimal
    gas_usd: Decimal
    cost_cap: Decimal
    order_usd: Decimal
    binding_constraint: str
    costs: CostBreakdown
    pool_depth_at_trade_usd: Decimal
    s1_at_trade_usd: Decimal
    validity_band: ValidityBand
    copyable: bool
    follower_return: Optional[Decimal]
    rejection_reason: Optional[str] = None

    @property
    def execution_cost_pct(self):
        return self.costs.total_priced_cost_pct

    @property
    def simulation(self):
        """The frozen-seam view. Every field the rest of the pipeline is allowed to read.

        ``intended_order_usd`` is ``strategy_aum`` — the capital the follower brought to this buy —
        and ``filled_order_usd`` is what §4.5's ``min(cost-cap size, strategy_aum)`` actually let
        them deploy. The seam requires ``intended_order_usd > 0`` even for a rejected simulation,
        which settles the reading: intent is the capital, not the sized order, and
        ``CopySimulation.fill_ratio`` is therefore **capital absorption** — the share of this
        capital level the signal can carry.

        §9.4's "at least 90% order fill" is a different ratio and is not this one. It applies to
        the route that fills the placed order (:attr:`depth.OrderBookFill.fills`); here the order
        is sized to what the pool can do, so it fills completely by construction and a 90% test
        against ``strategy_aum`` would contradict §4.5's own ``min(...)``.
        """
        return CopySimulation(
            capital_level=self.capital_level,
            tier=self.tier,
            intended_order_usd=self.capital_level,
            filled_order_usd=self.order_usd,
            execution_cost_pct=self.execution_cost_pct,
            follower_return=self.follower_return,
            copyable=self.copyable,
            rejection_reason=self.rejection_reason,
        )

    @property
    def capital_absorption(self):
        """Share of ``strategy_aum`` the signal could actually take at this buy."""
        return divide(self.order_usd, self.capital_level)


def size_to_cost_cap(pool, tier, strategy_aum, leader_clip, gas_usd, leader_return=None):
    """Largest order whose **total** cost stays within the tier cap, bounded by ``strategy_aum``.

    Returns a :class:`contracts.CopySimulation`. Use :func:`size_to_cost_cap_detail` for the
    itemised breakdown, ``S1``, and the binding constraint.

    ``leader_return`` is the leader's own 30-day return on this buy, if the caller has it. It is
    optional because this module owns execution physics and not outcomes: with it omitted the
    reported ``follower_return`` is the **execution drag alone**, i.e. what the copy returns when
    the leader's edge is exactly zero. That is a real number about this trade, not a placeholder.
    """
    return size_to_cost_cap_detail(
        pool, tier, strategy_aum, leader_clip, gas_usd, leader_return=leader_return
    ).simulation


def size_to_cost_cap_detail(pool, tier, strategy_aum, leader_clip, gas_usd, leader_return=None):
    """:func:`size_to_cost_cap`, with everything a reviewer needs to reproduce the number."""
    cap = cost_cap_for(tier)  # raises LongTailExcludedError before anything is measured
    if not isinstance(pool, PricedPool):
        raise TypeError(
            "sizing needs the quote asset's decimals and USD price; pass a depth.PricedPool, not a "
            "bare {}".format(type(pool).__name__)
        )

    aum = _positive_usd(strategy_aum, "strategy_aum")
    leader = _usd(leader_clip, "leader_clip")
    gas = _usd(gas_usd, "gas_usd")
    leader_ret = (
        ZERO if leader_return is None else require_finite(calc(leader_return), "leader_return")
    )

    depth = measure_depth(pool)
    band = depth.validity_band
    band.require(leader, what="leader clip")

    fee_bps = pool.state.fee_bps
    if not isinstance(fee_bps, int) or isinstance(fee_bps, bool) or fee_bps < 0:
        raise ValueError("fee_bps must be a non-negative int, got {!r}".format(fee_bps))

    with localcontext(CALCULATION_CONTEXT):
        x = depth.effective_depth_usd
        a = divide(leader, x)
        fee = divide(fee_bps, BPS)
        leader_footprint = +(2 * a + a * a)          # 2a + a^2 — the double-weighted leader term
        marginal = divide(ONE + a, x)                # d(cost)/dz for the follower's own size
        budget = +(cap - fee - leader_footprint)     # what is left for the follower

        if budget <= 0:
            return _rejected(
                depth, tier, aum, leader, gas, cap, band,
                CostBreakdown(
                    dex_fee_pct=fee,
                    gas_pct=ZERO,
                    price_impact_pct=ZERO,
                    copier_penalty_pct=leader_footprint,
                ),
                binding_constraint="leader_footprint",
                reason=(
                    "the leader's own footprint of {}pp plus the {}pp DEX fee already reaches the "
                    "{}pp total execution cost cap for {} assets; the copier's budget is consumed "
                    "before they trade".format(
                        _fmt(leader_footprint * 100), _fmt(fee * 100), _fmt(cap * 100), tier.value
                    )
                ),
            )

        cap_limited_max = divide(budget, marginal)   # where the priced curve alone reaches the cap
        band_ceiling = _band_ceiling(band, leader)

        upper = min([v for v in (cap_limited_max, aum, band_ceiling) if v is not None])
        if upper <= 0:
            return _rejected(
                depth, tier, aum, leader, gas, cap, band,
                CostBreakdown(
                    dex_fee_pct=fee, gas_pct=ZERO, price_impact_pct=ZERO,
                    copier_penalty_pct=leader_footprint,
                ),
                binding_constraint="validity_band",
                reason=(
                    "the leader's clip of ${} already fills the ${} validity band of the {} depth "
                    "model; no in-band size remains for a follower".format(
                        _fmt(leader), _fmt(band.max_size_usd), band.model.value
                    )
                ),
            )

        def cost_at(z):
            """The reported breakdown, at size ``z``.

            The search optimises the *same* expression the result publishes. Bisecting a
            simplified surrogate — ``fee + gas/z + 2a + a^2 + z(1+a)/x``, which is algebraically
            identical — would let the returned size sit a rounding step outside the cap it claims
            to respect, and the claim is the whole product.
            """
            return CostBreakdown(
                dex_fee_pct=fee,
                gas_pct=ZERO if gas == 0 else divide(gas, z),
                price_impact_pct=own_price_impact(x, z),
                copier_penalty_pct=copier_penalty(x, leader, z),
            )

        def total_cost(z):
            return cost_at(z).total_priced_cost_pct

        if total_cost(upper) <= cap:
            size = upper
        else:
            size = _largest_within_cap(total_cost, cap, upper, gas, marginal)

        if size <= 0:
            return _rejected(
                depth, tier, aum, leader, gas, cap, band,
                CostBreakdown(
                    dex_fee_pct=fee, gas_pct=ZERO, price_impact_pct=ZERO,
                    copier_penalty_pct=leader_footprint,
                ),
                binding_constraint="cost_cap",
                reason=(
                    "no order size keeps total execution cost within the {}pp cap for {} assets: "
                    "at the cheapest size the ${} gas charge alone still breaches it".format(
                        _fmt(cap * 100), tier.value, _fmt(gas)
                    )
                ),
            )

        binding = _binding_constraint(size, cap_limited_max, aum, band_ceiling)

        # The order is sized to what the pool can actually do, so there is nothing left unfilled.
        costs = cost_at(size)
        total = costs.total_priced_cost_pct
        follower_return = +(divide(ONE + leader_ret, ONE + total) - ONE)

    return SizingResult(
        pool_address=depth.pool_address,
        model=depth.model,
        tier=tier,
        capital_level=aum,
        leader_clip_usd=leader,
        gas_usd=gas,
        cost_cap=cap,
        order_usd=size,
        binding_constraint=binding,
        costs=costs,
        pool_depth_at_trade_usd=x,
        s1_at_trade_usd=depth.s1_usd,
        validity_band=band,
        copyable=True,
        follower_return=follower_return,
        rejection_reason=None,
    )


def _binding_constraint(size, cap_limited_max, aum, band_ceiling):
    """Which of the three ceilings actually decided the size. Reported, never inferred later.

    The block is here rather than at the one call site on purpose. Every ceiling arrives at the
    frozen 38 digits, and each test is a difference against a $0.000001 tolerance — so under the
    ambient 28-digit context a difference of ``1.0000000000000000000000000001e-6`` rounds to
    exactly the tolerance, the ``<=`` flips, and the same order is published as having been capped
    by the validity band rather than by the cost cap. That the current caller happens to have a
    frozen block open is a property of the caller, not of this function, and the next caller will
    not know it has to.
    """
    tol = BISECTION_TOLERANCE_USD
    with localcontext(CALCULATION_CONTEXT):
        if band_ceiling is not None and abs(size - band_ceiling) <= tol:
            return "validity_band"
        if abs(size - aum) <= tol:
            return "strategy_aum"
        if size <= cap_limited_max + tol:
            return "cost_cap"
        return "cost_cap"


def _rejected(depth, tier, aum, leader, gas, cap, band, costs, binding_constraint, reason):
    """A pool too thin for any order is a **measured** outcome: ``copyable=False`` plus a reason.

    Contrast with :class:`contracts.LongTailExcludedError`, which is raised for an out-of-scope
    asset. One says "we looked and there is no room"; the other says "we do not model this". Only
    the first may ever appear in a result table.
    """
    return SizingResult(
        pool_address=depth.pool_address,
        model=depth.model,
        tier=tier,
        capital_level=aum,
        leader_clip_usd=leader,
        gas_usd=gas,
        cost_cap=cap,
        order_usd=ZERO,
        binding_constraint=binding_constraint,
        costs=costs,
        pool_depth_at_trade_usd=depth.effective_depth_usd,
        s1_at_trade_usd=depth.s1_usd,
        validity_band=band,
        copyable=False,
        follower_return=None,
        rejection_reason=reason,
    )


def _largest_within_cap(total_cost, cap, upper, gas, marginal):
    """Bisection for the largest ``z <= upper`` with ``total_cost(z) <= cap``.

    The cost curve is convex, so the feasible set is an interval ``[z_lo, z_hi]`` and not a ray.
    The search therefore runs twice: first for the cost-minimising size, then for the upper root
    above it. Both halves bisect to :data:`BISECTION_TOLERANCE_USD` and both return the **feasible**
    end of the final bracket, so the reported size never exceeds the cap it claims to respect.
    """
    with localcontext(CALCULATION_CONTEXT):
        if gas == 0:
            # cost is fee + K + M*z: monotone increasing, feasible from zero upward.
            low, high = ZERO, upper
        else:
            minimiser = _cost_minimiser(gas, marginal, upper)
            if minimiser is None or total_cost(minimiser) > cap:
                # Even at its cheapest the order breaches the cap: gas dominates below the
                # minimiser and impact above it, and nothing in between fits.
                return ZERO
            low, high = minimiser, upper

        for _ in range(MAX_BISECTION_ITERATIONS):
            if high - low <= BISECTION_TOLERANCE_USD:
                return low
            mid = +((low + high) / 2)
            if mid <= 0:
                return ZERO
            if total_cost(mid) <= cap:
                low = mid
            else:
                high = mid
        raise SizingDidNotConverge(
            "bisection did not close a ${} bracket within {} iterations; refusing to return the "
            "last guess as a sized order".format(_fmt(high - low), MAX_BISECTION_ITERATIONS)
        )


def _cost_minimiser(gas, marginal, upper):
    """The size at which the convex cost curve bottoms out, by bisecting its derivative.

    ``d(cost)/dz = marginal - gas/z^2`` is increasing in ``z``, so its sign change is found the same
    way as any other root. Returns ``None`` when the curve is still falling at ``upper`` — meaning
    the cheapest available size *is* ``upper``, which the caller has already tested.
    """
    with localcontext(CALCULATION_CONTEXT):
        def derivative(z):
            return +(marginal - divide(gas, z * z))

        if derivative(upper) <= 0:
            return None

        low = upper
        for _ in range(MAX_BISECTION_ITERATIONS):
            low = +(low / 2)
            if low <= 0:
                return None
            if derivative(low) < 0:
                break
        else:
            return None

        high = upper
        for _ in range(MAX_BISECTION_ITERATIONS):
            if high - low <= BISECTION_TOLERANCE_USD:
                return high  # the feasible-side end: cost is falling below it
            mid = +((low + high) / 2)
            if derivative(mid) < 0:
                low = mid
            else:
                high = mid
        raise SizingDidNotConverge(
            "the cost-minimising size did not converge; refusing to bracket the cap search on a "
            "guess"
        )
