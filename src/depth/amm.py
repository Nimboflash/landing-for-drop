"""Pool depth and the copier penalty, on constructed pool states.

Pre-registration §4.5, addendum §9.6, ticket 30. This module answers one question — *what does the
pool do to a trade of size S* — and answers it with closed-form constant-product algebra so that
every number can be reproduced by hand before the code runs.

The three formulas, verified numerically:

    average slippage   S/x                    what the trader pays above mid
    marginal impact    (1 + S/x)^2 - 1        where the *next* trader starts
    copier slippage    (1+a)(1+a+s) - 1       arriving after A traded, a = A/x, s = S/x

``x`` is the **quote-side** reserve. Nothing here needs a price for the asset being bought, which
is §4.6's robustness decision expressed in code: long-tail price data was measured at 21.6%
coverage on one vendor and forward-filled for 30 days on another, so the model must not depend on
it. Only the quote asset carries a USD price.

**The copier penalty is a theorem, not an estimate.** Expand the third formula:

    (1+a)(1+a+s) - 1  =  2a + s + a^2 + as

The leader's size enters at **double weight**, because the follower eats the leader's *marginal*
impact and not their average. At equal size (a = s) the ratio to the leader's own slippage is
exactly ``3 + 2a`` — 3.1x at a leader slippage of 5%, which is the reference case this module is
required to reproduce exactly.

**TVL understates near-spot depth for concentrated pools; it does not overstate it.** Measured at
5-23x. Inside the active band a Uniswap v3/v4 pool is exactly a constant-product pool over its
*virtual* reserves ``x_v = L/sqrt(P)``, ``y_v = L*sqrt(P)``, and those exceed the real reserves the
TVL is computed from. Using TVL as the depth proxy therefore under-sizes every order — the opposite
of the usual assumption, and the reason a naive capacity model looks conservative while being
wrong in the dangerous direction.

**That measurement is a band, and a band has two edges.** The virtual and the real quote reserve
are two independent readings of one pool at one block; the 5-23x is everything that is known about
how far apart they may legitimately sit. A state below 1x is quarantined because the evidence rules
that direction out, and a state above :data:`MAX_TVL_UNDERSTATEMENT_FACTOR` is quarantined because
at that distance the two numbers are no longer describing the same pool — they are a stale
liquidity snapshot divided by a reserve that has since moved. Neither edge is about the *size* of
the reserve: a pool holding a hundredth of a cent against a proportionate liquidity read is priced,
and its depth is a real, tiny number.

Beyond roughly 1% the single-band model breaks as ticks cross. The model's own 10%/1% size ratio is
exactly 10; the measured ratios were 7.6x for USDC/WETH and 507x for PEPE. Neither is 10, and they
disagree with each other by two orders of magnitude, so there is no correction factor to apply —
only a validity band to refuse outside of.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from enum import Enum
from typing import Optional

from contracts import (
    CALCULATION_CONTEXT,
    ContractError,
    PoolState,
    QuarantineRequired,
    calc,
    divide,
    is_quote_asset,
    normalise_asset,
    quantize_pp,
    require_finite,
)

ZERO = Decimal(0)
ONE = Decimal(1)
ONE_PERCENT = Decimal("0.01")
TEN_PERCENT = Decimal("0.10")

#: Uniswap's fixed-point scale for ``sqrt_price_x96``.
Q96 = 2 ** 96

# -- pinned measurements --------------------------------------------------------
# Recorded as constants rather than prose so a test can assert against them and a future change to
# the model has to argue with a number.

#: What the single-band constant-product model predicts for size(10% slippage) / size(1%).
MODEL_SIZE_RATIO_10PCT_OVER_1PCT = Decimal("10")

#: What was actually measured (addendum §9.6). Neither equals 10, and they differ from each other
#: by ~67x, which is why the model is banded rather than corrected.
MEASURED_SIZE_RATIO_10PCT_OVER_1PCT = {
    "USDC/WETH": Decimal("7.6"),
    "PEPE": Decimal("507"),
}

#: Range over which total TVL was measured to *understate* near-spot depth on concentrated pools.
MEASURED_TVL_UNDERSTATEMENT = (Decimal("5"), Decimal("23"))

#: The ceiling on virtual/real above which the two readings are not describing the same pool.
#:
#: Ten times the measured maximum of 23x. **Ten and not one**, because 5-23x is a sample of
#: concentrated pools and not a census: a pool one notch tighter than anything measured would be
#: quarantined by a ceiling set at the sample maximum, and the quarantine rate would then be a
#: function of how many pools happened to be measured rather than of the data. **Ten and not a
#: hundred**, because the ceiling only has to separate two populations that sit ten orders of
#: magnitude apart — the tightest plausible unmeasured concentrated pool on one side, and a stale
#: liquidity read against a drained reserve, traced at 5x10^12, on the other. Any bound between
#: ~50x and ~10^6x classifies both correctly; this one is stated in terms of the measurement so
#: that moving it means arguing with the measurement.
MAX_TVL_UNDERSTATEMENT_FACTOR = Decimal("230")

#: §4.5 capacity note: PEPE 1% size, single pool versus routed through an aggregator. The 240x
#: spread is the reason aggregator quotes may not underwrite capacity.
MEASURED_PEPE_1PCT_SINGLE_POOL_USD = Decimal("471")
MEASURED_PEPE_1PCT_ROUTED_USD = Decimal("114000")

#: The slippage beyond which the single-band virtual-reserve model is not trusted.
CONCENTRATED_BAND_MAX_SLIPPAGE = ONE_PERCENT


class DepthModel(str, Enum):
    """Which depth model priced a trade. Emitted with every quote.

    A number produced by the concentrated model inside its band and a number produced by the
    constant-product model carry different warranties, and a reader who cannot tell them apart
    cannot weigh the result.
    """

    CONSTANT_PRODUCT = "CONSTANT_PRODUCT"
    CONCENTRATED_VIRTUAL_RESERVES = "CONCENTRATED_VIRTUAL_RESERVES"


class OutsideValidityBand(ContractError):
    """A size was requested that the depth model does not support.

    Deliberately an exception. "This pool cannot absorb your order" is a *measured* outcome and is
    reported as ``copyable=False`` with a reason; "this model stops being true past here" is a
    **modelling limit**, and returning a number for it would publish an extrapolation as a
    measurement.
    """


# -- inputs ---------------------------------------------------------------------


@dataclass(frozen=True)
class QuoteAsset:
    """The one asset in the model that carries a USD price (§4.6).

    Refuses any token outside :data:`contracts.QUOTE_ASSETS`. The single most important robustness
    decision in the metric is that no oracle is required for the token being bought; accepting an
    arbitrary token here would quietly undo it.
    """

    address: str
    decimals: int
    usd_price: Decimal

    def __post_init__(self):
        object.__setattr__(self, "address", normalise_asset(self.address))
        object.__setattr__(self, "usd_price", require_finite(calc(self.usd_price), "usd_price"))
        if not is_quote_asset(self.address):
            raise ValueError(
                "{} is not a liquid quote asset; §4.6 permits USD prices only for USDC, USDT, "
                "WETH/ETH and WBTC — pricing the bought token would reintroduce the long-tail "
                "oracle the metric was designed to avoid".format(self.address)
            )
        if not isinstance(self.decimals, int) or isinstance(self.decimals, bool):
            raise TypeError("decimals must be int, got {}".format(type(self.decimals).__name__))
        if not 0 <= self.decimals <= 36:
            raise ValueError("implausible token decimals: {}".format(self.decimals))
        if self.usd_price <= 0:
            raise ValueError("a quote asset must carry a positive USD price")


@dataclass(frozen=True)
class PricedPool:
    """A :class:`contracts.PoolState` plus the quote-side pricing needed to express depth in USD.

    The pairing is checked rather than assumed: a pool whose quote leg is not the supplied quote
    asset would produce a depth figure denominated in the wrong token, and every downstream USD
    comparison would be silently off by the price ratio.
    """

    state: PoolState
    quote: QuoteAsset

    def __post_init__(self):
        if not isinstance(self.state, PoolState):
            raise TypeError(
                "PricedPool.state must be a contracts.PoolState, got {}".format(
                    type(self.state).__name__
                )
            )
        if normalise_asset(self.state.quote) != self.quote.address:
            raise ValueError(
                "pool quote leg is {} but the supplied quote asset is {}; a mismatched pair would "
                "denominate depth in the wrong token".format(
                    normalise_asset(self.state.quote), self.quote.address
                )
            )
        if self.state.quote_reserve_raw < 0 or self.state.asset_reserve_raw < 0:
            raise ValueError("pool reserves are unsigned raw quantities")


# -- outputs --------------------------------------------------------------------


@dataclass(frozen=True)
class ValidityBand:
    """The size range over which the depth model is trusted, and why it stops there.

    ``max_size_usd is None`` means unbounded: constant product is exact at any size, so the *model*
    imposes no ceiling and the cost cap does all the bounding. For concentrated liquidity the
    ceiling is real — past roughly 1% the price leaves the active tick range and the single-band
    virtual reserves stop describing the pool.
    """

    model: DepthModel
    max_size_usd: Optional[Decimal]
    max_own_slippage: Optional[Decimal]
    reason: str

    def contains(self, size_usd):
        size = require_finite(calc(size_usd), "size_usd")
        if size < 0:
            raise ValueError("an order size cannot be negative")
        return self.max_size_usd is None or size <= self.max_size_usd

    def require(self, size_usd, what="order"):
        """Refuse rather than extrapolate. Names the rule in the message."""
        if not self.contains(size_usd):
            raise OutsideValidityBand(
                "{} of ${} exceeds the ${} validity band of the {} model — {}. Refusing to "
                "extrapolate: the model's own 10%/1% size ratio is {}, while the measured ratios "
                "were {} (USDC/WETH) and {} (PEPE), so no single correction factor exists.".format(
                    what,
                    _fmt(size_usd),
                    _fmt(self.max_size_usd),
                    self.model.value,
                    self.reason,
                    MODEL_SIZE_RATIO_10PCT_OVER_1PCT,
                    MEASURED_SIZE_RATIO_10PCT_OVER_1PCT["USDC/WETH"],
                    MEASURED_SIZE_RATIO_10PCT_OVER_1PCT["PEPE"],
                )
            )


@dataclass(frozen=True)
class DepthMeasurement:
    """Quote-side depth for one pool at one block, and how it was arrived at.

    ``tvl_understatement_factor`` is the headline number of addendum §9.6 made explicit: how much
    deeper the pool is near spot than its total value locked suggests. It is ``None`` for constant
    product, where the two coincide by construction, and for a concentrated pool it lies in
    ``[1, MAX_TVL_UNDERSTATEMENT_FACTOR]`` — a state outside that band on either side is
    quarantined rather than used.
    """

    pool_address: str
    model: DepthModel
    quote_reserve_raw: int
    quote_reserve_usd: Decimal
    effective_depth_usd: Decimal
    s1_usd: Decimal
    validity_band: ValidityBand
    virtual_quote_reserve_raw: Optional[int] = None
    virtual_quote_reserve_usd: Optional[Decimal] = None
    tvl_understatement_factor: Optional[Decimal] = None

    def __post_init__(self):
        if self.effective_depth_usd <= 0:
            raise ValueError("effective depth must be positive to price any trade")


# -- helpers --------------------------------------------------------------------


def _fmt(value):
    """Percentage-point-legible rendering for refusal messages only, never for a returned value.

    Falls back to exponential notation rather than raising. ``Decimal.quantize`` raises
    ``InvalidOperation`` when the quantized result would need more digits than the context allows —
    28 in the ambient context, 38 in the frozen one — and every caller here is *already inside a
    refusal*. A formatter that raised would replace a typed :class:`contracts.QuarantineRequired`
    or :class:`OutsideValidityBand` with an untyped arithmetic error at exactly the sizes where
    the refusal matters most: a pool whose virtual reserve is 10^45 raw units is $10^39 of claimed
    depth, which is the shape being refused, and it must arrive as a refusal.
    """
    if value is None:
        return "unbounded"
    d = calc(value)
    with localcontext(CALCULATION_CONTEXT):
        try:
            return format(quantize_pp(d), "f")
        except InvalidOperation:
            return format(d, "E")


def _usd(value, field):
    d = require_finite(calc(value), field)
    if d < 0:
        raise ValueError("{} cannot be negative, got {}".format(field, d))
    return d


def _positive_usd(value, field):
    d = _usd(value, field)
    if d == 0:
        raise ValueError(
            "{} must be positive; a zero here would make every ratio it feeds either a silent "
            "zero or a division by zero, and neither is a measurement".format(field)
        )
    return d


def raw_to_usd(raw_amount, quote):
    """Raw quote units -> USD. Raw quantities stay ``int`` right up to this boundary."""
    if not isinstance(raw_amount, int) or isinstance(raw_amount, bool):
        raise TypeError(
            "raw quantities are int by seam rule, got {}".format(type(raw_amount).__name__)
        )
    with localcontext(CALCULATION_CONTEXT):
        return +(divide(raw_amount, 10 ** quote.decimals) * quote.usd_price)


# -- depth ----------------------------------------------------------------------


def virtual_reserves(active_liquidity, sqrt_price_x96):
    """``(x_v, y_v) = (L/sqrt(P), L*sqrt(P))`` in raw units.

    Convention, pinned here because :class:`contracts.PoolState` does not pin it: ``sqrt_price_x96``
    is ``sqrt(quote_raw / asset_raw) * 2**96`` — the price of the pool's *asset* leg denominated in
    its *quote* leg, in raw units. ``x_v`` is therefore the asset-side virtual reserve and ``y_v``
    the quote-side one.

    Both are floored to ``int``. Flooring understates depth, which understates executable size,
    which is the conservative direction for a capacity model — an error here should shrink capacity,
    never inflate it.
    """
    for name, value in (("active_liquidity", active_liquidity), ("sqrt_price_x96", sqrt_price_x96)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError("{} must be int, got {}".format(name, type(value).__name__))
        if value <= 0:
            raise ValueError("{} must be positive, got {}".format(name, value))
    asset_virtual = active_liquidity * Q96 // sqrt_price_x96
    quote_virtual = active_liquidity * sqrt_price_x96 // Q96
    return asset_virtual, quote_virtual


def measure_depth(pool):
    """Quote-side depth for a pool, using virtual reserves when the pool is concentrated.

    Active-tick liquidity alone is rejected as a depth proxy (ticket 30): the returned measurement
    carries the validity band that says where the single-band model stops being true, and every
    caller must pass a size through it.
    """
    if not isinstance(pool, PricedPool):
        raise TypeError(
            "depth needs the quote asset's decimals and USD price; pass a depth.PricedPool, not a "
            "bare {}".format(type(pool).__name__)
        )
    state, quote = pool.state, pool.quote

    has_liquidity = state.active_liquidity is not None
    has_price = state.sqrt_price_x96 is not None
    if has_liquidity != has_price:
        raise ValueError(
            "a concentrated pool state needs both active_liquidity and sqrt_price_x96; got "
            "active_liquidity={!r}, sqrt_price_x96={!r}. Half a state would be priced by the "
            "constant-product branch and silently understate depth by the 5-23x measured "
            "factor".format(state.active_liquidity, state.sqrt_price_x96)
        )

    real_usd = raw_to_usd(state.quote_reserve_raw, quote)

    if real_usd <= 0:
        # One rule, checked before the branch, because the concentrated branch could not reach it.
        #
        # That branch's consistency check is ``virtual_usd < real_usd`` further down, which can
        # never fire when ``real_usd`` is zero. A drained pool carrying stale ``active_liquidity``
        # and ``sqrt_price_x96`` was therefore priced off its virtual reserves alone: $5,000,000 of
        # effective depth and $35,000 of copyable capacity against a pool holding $0 of the quote
        # asset — while the constant-product branch refused the identical input. Same input, same
        # classification.
        #
        # Quarantine rather than ValueError: a drained pool is real chain data (pools do get
        # emptied), it is simply data this model cannot turn into a number. That is the definition
        # of the reconciliation queue, and the failure policy prohibits dropping it silently.
        raise QuarantineRequired(
            "pool {} has no quote-side reserve; there is no depth to price a trade against, and a "
            "stale active_liquidity/sqrt_price_x96 on a drained pool is a real but unsupported "
            "state — it belongs in the reconciliation queue rather than being converted into "
            "executable capacity".format(state.address)
        )

    if not has_liquidity:
        band = ValidityBand(
            model=DepthModel.CONSTANT_PRODUCT,
            max_size_usd=None,
            max_own_slippage=None,
            reason=(
                "constant product is exact at every size — x*y=k has no ticks to cross, so the "
                "cost cap and not the model is what bounds the order"
            ),
        )
        with localcontext(CALCULATION_CONTEXT):
            return DepthMeasurement(
                pool_address=state.address,
                model=DepthModel.CONSTANT_PRODUCT,
                quote_reserve_raw=state.quote_reserve_raw,
                quote_reserve_usd=real_usd,
                effective_depth_usd=real_usd,
                s1_usd=+(real_usd * ONE_PERCENT),
                validity_band=band,
            )

    _asset_virtual, quote_virtual_raw = virtual_reserves(
        state.active_liquidity, state.sqrt_price_x96
    )
    virtual_usd = raw_to_usd(quote_virtual_raw, quote)

    # ``virtual_usd`` and ``real_usd`` are two independent readings of the same pool at the same
    # block — one through ``active_liquidity``/``sqrt_price_x96``, one through
    # ``quote_reserve_raw`` — and the measured 5-23x band is the whole of what is known about how
    # far apart they may legitimately sit. **That band has two edges and only the lower one was
    # installed**, so the ratio was bounded below by 1 and unbounded above.
    #
    # Guarding ``real_usd == 0`` closed a single point on an open ray. One raw unit of USDC to the
    # right of it, a stale ``active_liquidity`` of 5x10^12 against a reserve holding a millionth of
    # a dollar reproduced the whole original failure: a ratio of 5x10^12, $5,000,000 of effective
    # depth, a $50,000 band and $35,000 of copyable capacity. Ten raw units gave 5x10^11 and the
    # same capacity. The dangerous condition was never "the reserve is zero", nor even "the reserve
    # is small" — a pool holding a hundredth of a cent against a proportionate liquidity read is
    # priced below, and its depth is a real, tiny number. The condition is that **the two readings
    # disagree by more than the evidence allows**, which is a statement about their ratio and about
    # nothing else.
    #
    # The ratio is computed once, here, and the value that is guarded is the value that is
    # published as ``tvl_understatement_factor``. Guarding one expression and emitting another
    # would let a record show a factor the guard never saw.
    factor = divide(virtual_usd, real_usd)

    if virtual_usd < real_usd:
        # The lower edge. Either the sqrt_price orientation is inverted for this pool or the
        # reserves and the liquidity were read at different blocks; both are real inputs the model
        # does not support, which is the definition of quarantine.
        #
        # Compared directly rather than as ``factor < 1``: the edge is exactly one by definition,
        # and a virtual reserve a single 38th digit below the real one must not round onto it —
        # ``effective_depth_usd >= quote_reserve_usd`` is asserted downstream as an exact
        # inequality.
        raise QuarantineRequired(
            "pool {}: virtual quote depth ${} is below the real quote reserve ${}. TVL was "
            "measured to *understate* near-spot depth on concentrated pools by 5-23x, never to "
            "overstate it, so this state is inconsistent with the model — it belongs in the "
            "reconciliation queue rather than being priced".format(
                state.address, _fmt(virtual_usd), _fmt(real_usd)
            )
        )

    if factor > MAX_TVL_UNDERSTATEMENT_FACTOR:
        # The upper edge, at ten times the measured maximum — see
        # :data:`MAX_TVL_UNDERSTATEMENT_FACTOR` for why ten.
        raise QuarantineRequired(
            "pool {}: virtual quote depth ${} is {}x the real quote reserve ${}, past the {}x "
            "ceiling on the 5-23x measured understatement band. A ratio this far above anything "
            "measured does not describe a concentrated pool; it describes an active_liquidity / "
            "sqrt_price_x96 read that no longer belongs to the reserve it is being divided by — a "
            "drained or migrated pool carrying a stale liquidity snapshot, or two reads taken at "
            "different blocks. Pricing it converts the staleness into executable capacity: the "
            "traced case turned a pool holding $0.000001 into $5,000,000 of depth and $35,000 of "
            "copyable order. It belongs in the reconciliation queue.".format(
                state.address,
                _fmt(virtual_usd),
                factor,
                _fmt(real_usd),
                MAX_TVL_UNDERSTATEMENT_FACTOR,
            )
        )

    with localcontext(CALCULATION_CONTEXT):
        band_max = +(virtual_usd * CONCENTRATED_BAND_MAX_SLIPPAGE)
        band = ValidityBand(
            model=DepthModel.CONCENTRATED_VIRTUAL_RESERVES,
            max_size_usd=band_max,
            max_own_slippage=CONCENTRATED_BAND_MAX_SLIPPAGE,
            reason=(
                "past roughly 1% the price leaves the active tick range and single-band virtual "
                "reserves stop describing the pool"
            ),
        )
        # ``factor`` is the guarded quantity from above, unmodified. ``None`` is reserved for
        # constant product, where TVL and near-spot depth coincide by construction (see
        # DepthMeasurement's docstring) — it used to double as "the denominator was zero",
        # collapsing "TVL is the depth" and "there is no TVL" onto one value that nothing
        # downstream could tell apart.
        return DepthMeasurement(
            pool_address=state.address,
            model=DepthModel.CONCENTRATED_VIRTUAL_RESERVES,
            quote_reserve_raw=state.quote_reserve_raw,
            quote_reserve_usd=real_usd,
            effective_depth_usd=virtual_usd,
            s1_usd=band_max,  # 1% of depth is both S1 and, here, the band edge
            validity_band=band,
            virtual_quote_reserve_raw=quote_virtual_raw,
            virtual_quote_reserve_usd=virtual_usd,
            tvl_understatement_factor=factor,
        )


# -- the formulas ---------------------------------------------------------------


def average_slippage(depth_usd, size_usd):
    """``S/x`` — the average price paid above mid on a constant-product pool.

    On a balanced pool (TVL = 2x) this is 1% at 0.5% of TVL, 3% at 1.5%, and 10% at 5.0%.
    """
    x = _positive_usd(depth_usd, "depth_usd")
    s = _usd(size_usd, "size_usd")
    return divide(s, x)


def marginal_impact(depth_usd, size_usd):
    """``(1 + S/x)^2 - 1`` — where the *next* trader starts, not what this one paid.

    The square is the whole copier penalty in miniature: the price the follower inherits has moved
    by the leader's marginal impact, while the leader only paid their average.
    """
    with localcontext(CALCULATION_CONTEXT):
        s = average_slippage(depth_usd, size_usd)
        return +((ONE + s) ** 2 - ONE)


def size_for_slippage(depth_usd, target_slippage):
    """Inverse of :func:`average_slippage`. ``S1`` is this at 1%."""
    x = _positive_usd(depth_usd, "depth_usd")
    target = require_finite(calc(target_slippage), "target_slippage")
    if target < 0:
        raise ValueError("a slippage target cannot be negative")
    with localcontext(CALCULATION_CONTEXT):
        return +(x * target)


def copier_slippage(depth_usd, leader_clip_usd, copier_usd):
    """``(1+a)(1+a+s) - 1`` — total slippage against the pre-leader mid, for a follower arriving
    after the leader's clip of ``A`` on the same pool state.

    Expanded: ``2a + s + a^2 + as``. The leader's size enters at double weight. At equal size the
    ratio to the leader's own slippage is exactly ``3 + 2a`` — the required reference case is a
    leader at 5.000% and a copier at 15.500%, i.e. 3.1x.
    """
    x = _positive_usd(depth_usd, "depth_usd")
    a = divide(_usd(leader_clip_usd, "leader_clip_usd"), x)
    s = divide(_usd(copier_usd, "copier_usd"), x)
    with localcontext(CALCULATION_CONTEXT):
        return +((ONE + a) * (ONE + a + s) - ONE)


def own_price_impact(depth_usd, copier_usd):
    """The follower's own footprint: what they would have paid on an untouched pool.

    Kept separate from the leader's footprint so that a destroyed edge can be attributed. "The copy
    lost 15%" is not actionable; "10.5 of those points were the leader's footprint, 5 were mine" is.
    """
    return average_slippage(depth_usd, copier_usd)


def copier_penalty(depth_usd, leader_clip_usd, copier_usd):
    """The part of the follower's slippage caused by the *leader's* trade: ``2a + a^2 + as``.

    Evaluated in closed form rather than as ``copier_slippage - own_price_impact``. The subtraction
    is algebraically identical and numerically treacherous: with no leader it cancels two 38-digit
    quantities and lands on ``-4.4E-38``, a *negative execution cost*, which would read downstream
    as a subsidy. The closed form is non-negative by construction for any non-negative inputs.
    """
    x = _positive_usd(depth_usd, "depth_usd")
    a = divide(_usd(leader_clip_usd, "leader_clip_usd"), x)
    s = divide(_usd(copier_usd, "copier_usd"), x)
    with localcontext(CALCULATION_CONTEXT):
        return +(2 * a + a * a + a * s)


def linear_copier_slippage(leader_clip_usd, copier_usd, s1_usd):
    """``(2 * S_leader + C) / S1`` — the general form from §4.5, as a ratio rather than points.

    The first-order truncation of :func:`copier_slippage`: it drops the ``a^2 + as`` terms, so it
    under-reports (15.0% against the exact 15.500% for the reference case). Its value is that the
    double weight on the leader's size is visible in the algebra — doubling the leader's clip moves
    this number exactly twice as far as doubling the copier's.
    """
    s1 = _positive_usd(s1_usd, "s1_usd")
    leader = _usd(leader_clip_usd, "leader_clip_usd")
    copier = _usd(copier_usd, "copier_usd")
    with localcontext(CALCULATION_CONTEXT):
        return +(ONE_PERCENT * divide(2 * leader + copier, s1))


def execution_price_ratio(depth_usd, leader_clip_usd, size_usd):
    """Execution price as a multiple of the pre-leader mid: ``(1+a)(1+a+s)``.

    Monotone non-decreasing in ``size_usd``. That is the invariant the whole module rests on: no
    pool state and no size may ever produce a better price for a larger order.
    """
    with localcontext(CALCULATION_CONTEXT):
        return +(ONE + copier_slippage(depth_usd, leader_clip_usd, size_usd))
