"""Transaction-level balance netting — pre-registration §4.2, §4.3; addendum §8.

What this module reconstructs is *economic intent*, not swap rows. ``dex.trades`` emits one row per
pool hop, so the route ``USDC -> WETH -> PEPE`` produces a phantom "bought WETH" event that never
represented anything the user wanted. Summing signed balance changes per ``(transaction, owner,
token)`` makes the intermediate cancel arithmetically, which is why netting exists rather than a
first-hop/last-hop heuristic — the latter also mis-reads split routes, which are common.

The sequence is fixed and its order is load-bearing (ticket 21):

    1. successful transactions only          — a reverted transaction moved nothing
    2. attribution must be usable            — addendum §8, uncertain ownership is excluded
    3. transfers touching the owner only     — MEV bundles and multicalls share the transaction
    4. drop fee and referral transfers       — a fee is not an endpoint
    5. ETH and WETH already collapsed        — asserted, not assumed
    6. sign: received positive, sent negative
    7. group by token and sum
    8. discard legs within the residual tolerance
    9. classify what survives

Steps 3 and 4 are the two most likely places for a subtle bug: doing either one *after* the sum
silently mixes a searcher's inventory or a referral fee into the user's intent, and the result
still looks like a perfectly ordinary trade.

Step 8's tolerance is ``max($0.01, 0.01% of transaction notional)``, so the definition of
*notional* decides what counts as unexplained money. **It is what the transaction left behind,
never what flowed through it.** Gross flow is the wrong unit for this and every attack on the
threshold is the same attack: move a large quantity, bring nearly all of it back, and whatever
fraction fails to cancel is the price of a tolerance sized by the whole. It does not matter
whether the leg cancels exactly (a flash loan), to within a cent (a loan repaid a shade short) or
to within a tenth of a percent (an order almost entirely refunded) — the answer is the same in all
three, because the notional counts nets and not grosses. See :func:`transaction_notional_usd`,
which keeps that separate from the gross volume a non-trade reports.

Every transaction returns exactly one :class:`~contracts.trades.NetTradeResult`. There is no path
that returns nothing: an unexplained dropped event is prohibited outright by the failure policy,
so each transaction is accounted for by exactly one ``ClassificationStatus`` and every non-trade
carries a reason naming the rule that produced it.

USD is only ever asked for on quote assets (§4.6). Netting never consults a price for a long-tail
token — not as a policy the caller must remember, but structurally: the price lookup is guarded by
``is_quote_asset``. A leg whose USD value is unknown is therefore never claimed to be negligible,
because "small" is not a statement anyone can make about a number they do not have.
"""

from decimal import Decimal, localcontext
from typing import Dict, List

from contracts import (
    CALCULATION_CONTEXT,
    NATIVE_ETH,
    ClassificationStatus,
    NetDelta,
    NetTradeResult,
    QuarantineRequired,
    calc,
    is_quote_asset,
    require_finite,
    sub,
)
from phase0.parameters import PARAMETERS

# -- the frozen tolerance (addendum §8) -----------------------------------------
#
#     USD residual <= max($0.01, 0.01% of transaction notional)
#
# The floor-plus-percentage shape is deliberate: the fixed dollar floor handles dust on small
# trades, the percentage handles large ones. Both arms are needed — a pure percentage would call
# $0.009 of dust on a $50 trade material, and a pure floor would call $0.05 of rounding on a
# $956 arbitrage round trip material, which is exactly the case §4.3 exists to catch.
#
# Both arms are read from the ticket-11 frozen set. The tolerance decides which residual rows go to
# the primary metric and which go to the reconciliation queue, so a copy of it here would be a
# second answer to "is this transaction material?" that nothing compares to the first.

RESIDUAL_FLOOR_USD = PARAMETERS.value("netting.residual_tolerance.floor_usd")
RESIDUAL_NOTIONAL_RATE = PARAMETERS.value("netting.residual_tolerance.notional_rate")  # 0.01%

#: Statuses that owe someone an answer. Addendum §8 routes above-tolerance residuals to a
#: reconciliation queue, and ``QuarantineRequired`` sends unsupported-but-real input to the same
#: place. ``FAILED_TRANSACTION`` and ``CIRCULAR_ARBITRAGE`` are deliberately absent: they are
#: settled findings with a known cause, not open questions, and queueing them would bury the
#: transactions that genuinely need a human.
QUEUED_STATUSES = (
    ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL,
    ClassificationStatus.NO_CLEAR_ENDPOINT,
    ClassificationStatus.UNSUPPORTED,
)


# -- sign, under the frozen context ---------------------------------------------
#
# ``-x`` and ``abs(x)`` are arithmetic operations in ``decimal``, not notation: both round their
# result to the *ambient* context, which is 28 digits by default while every USD value here is
# carried at 38. Any price obtained by division carries all 38 — that is what ``divide`` returns —
# so a plain unary minus silently drops ten digits from every sent leg, and a plain ``abs`` drops
# them from every trade size. The same shape shipped in ``LotConsumption.realized_return`` and was
# caught by review rather than by a test, because the truncated value looks entirely reasonable.


def _negate(value):
    """``-value`` under CALCULATION_CONTEXT, so a sent leg is the exact mirror of a received one."""
    return sub(Decimal("0"), value)


def _magnitude(value):
    """``abs(value)`` with no rounding: a comparison, then at most one frozen-context negation."""
    return value if value >= 0 else _negate(value)


def residual_tolerance_usd(notional_usd):
    """``max($0.01, 0.01% of notional)`` — the negligibility threshold, addendum §8.

    ``notional_usd`` may be ``None`` when no leg of the transaction is priceable, in which case
    only the floor is available. Nothing is quantized here: a value rounded to cents before this
    comparison has already lost the quantity being compared.
    """
    if notional_usd is None:
        return RESIDUAL_FLOOR_USD
    notional = require_finite(calc(notional_usd), "notional_usd")
    if notional < 0:
        raise ValueError(
            "transaction notional cannot be negative; got {}. Notional is a gross one-way flow, "
            "so a negative value means the caller signed it somewhere it should not have "
            "been.".format(notional)
        )
    with localcontext(CALCULATION_CONTEXT):
        proportional = +(notional * RESIDUAL_NOTIONAL_RATE)
    return max(RESIDUAL_FLOOR_USD, proportional)


# -- pricing --------------------------------------------------------------------


def _usd_value(quote_usd, token, raw_amount):
    """USD value of a non-negative raw quantity of ``token``, or ``None`` when unpriceable.

    ``quote_usd`` is either a callable ``(token, raw_amount) -> Optional[Decimal]`` or a mapping
    ``{token: Decimal usd per raw unit}``. Non-quote tokens short-circuit to ``None`` *before* the
    book is consulted, so §4.6 ("USD prices are used only for liquid quote assets") holds by
    construction and a long-tail oracle cannot enter the metric through this door.
    """
    if raw_amount < 0:
        raise ValueError("_usd_value takes a magnitude; sign is applied by the caller")
    if raw_amount == 0:
        return Decimal("0")  # zero tokens are worth zero dollars; no oracle is involved
    if not is_quote_asset(token):
        return None

    if callable(quote_usd):
        value = quote_usd(token, raw_amount)
    else:
        try:
            price = quote_usd[token]
        except (KeyError, TypeError):
            price = None
        if price is None:
            return None
        with localcontext(CALCULATION_CONTEXT):
            value = +(calc(price) * raw_amount)

    if value is None:
        return None
    value = require_finite(calc(value), "quote_usd({})".format(token))
    if value < 0:
        raise ValueError(
            "quote_usd returned a negative USD value ({}) for a positive quantity of {}; a price "
            "book that can produce this would flip the sign of a trade leg".format(value, token)
        )
    return value


# -- steps 3 to 7: the sum ------------------------------------------------------


def _require_eth_collapsed(tx):
    """Step 5. ``Transfer`` collapses the native-ETH sentinel onto WETH on construction, so this
    can only fire if the seam was bypassed — and if it ever does, netting must refuse rather than
    treat one endpoint as two assets (§4.2)."""
    for t in tx.transfers:
        if t.token == NATIVE_ETH:
            raise QuarantineRequired(
                "transfer at log_index {} still carries the native ETH sentinel; §4.2 requires "
                "ETH and WETH to be collapsed to one asset before netting, or a route that "
                "enters in ETH and leaves in WETH nets to two endpoints that are really "
                "one".format(t.log_index)
            )


def _owner_flows(tx, owner):
    """Steps 3, 4, 6, 7 in one pass: gross one-way flows and the signed net, per token.

    Returns ``{token: [sent_raw, received_raw]}``. Both are needed. The net answers "what did the
    user end up with" and sizes the transaction; the gross answers "how much of this token moved"
    and is what a net is judged against when asking whether it came back (:func:`_came_back`) —
    without it, a $0.049 residual on a $956 round trip and a $0.049 residual on a $0.05 trade are
    the same number and §4.3 cannot tell them apart.
    """
    flows = {}  # type: Dict[str, List[int]]
    for t in tx.transfers:
        if t.is_fee:
            continue  # step 4 — a fee or referral transfer is never an endpoint
        if t.from_addr == t.to_addr:
            # Moving a token to yourself moves nothing. Added to both sides it nets to zero
            # (right) while inflating the gross one-way flow (wrong). The gross no longer sets the
            # notional, but it is still what a net is judged against: a large enough self-move
            # makes a real endpoint a vanishing fraction of its own flow, and the endpoint reads
            # as a phantom. It also inflates the volume a non-trade reports.
            continue
        if owner != t.from_addr and owner != t.to_addr:
            continue  # step 3 — someone else's money in the same transaction
        flow = flows.setdefault(t.token, [0, 0])
        if t.to_addr == owner:
            flow[1] += t.raw_amount
        if t.from_addr == owner:
            flow[0] += t.raw_amount
    return flows


def transaction_notional_usd(tx, quote_usd):
    """The **size** of a transaction: the largest *net* USD position any token left behind.

    ``None`` when nothing priceable stayed. This is the number the negligibility tolerance is a
    percentage of, so it is the number that decides what counts as unexplained money, and the one
    rule it has to obey is that **money which did not stay cannot size anything.**

    *Net, not gross.* A token's contribution is what the owner ended up holding or owing in it, not
    what passed through their address on the way. The three shapes below are the same attack at
    three depths, and counting grosses answers all three wrongly:

        exactly cancelled     300 WETH borrowed and repaid       $900,000 gross,  $0 net
        nearly cancelled      the same loan repaid $0.021 short  $900,000 gross,  $0.021 net
        largely cancelled     900,000 USDC sent, 899,000 back    $900,000 gross,  $1,000 net

    In each, sizing by the gross buys a $90.00 tolerance and $50 of money nobody can explain
    becomes dust in a transaction then admitted to the primary metric as a clean trade. The bias is
    self-selecting: the transactions it wrongly admits are exactly the ones carrying an unexplained
    balance. Counting nets caps the tolerance at 0.01% of what was actually traded — $0.10 in all
    three — and no choice of how much to move, or of how nearly to bring it back, changes that.

    *Except when nothing stayed at all.* A transaction every leg of which came back has no endpoint
    to be sized by, and §4.3 measures a round trip at what it routed: the $956 arbitrage keeps a
    notional of $956.049, not the $0.049 profit, or 0.01% of the profit would call the round trip
    material and the exclusion would never fire. That branch cannot admit anything — see
    :func:`_notional_from_flows` for why every leg reaching it is already negligible, so
    ``CIRCULAR_ARBITRAGE`` is the only status it can produce.

    What this is *not*: the volume that moved. That question is answered by
    :func:`_gross_volume_from_flows`, and a non-trade result reports it in ``quote_usd``.
    """
    owner = tx.attribution.portfolio_owner
    if owner is None:
        return None
    return _notional_from_flows(_owner_flows(tx, owner), quote_usd)


def _came_back(net_usd, gross_usd):
    """True when what a leg left behind would be negligible *in a transaction of the leg's size*.

    This is :func:`residual_tolerance_usd` applied to the leg alone: ``net <= max($0.01, 0.01% of
    the leg's own gross flow)``. Nothing transaction-level enters, so there is no circularity — the
    leg is judged against itself and the answer is fixed before any notional exists.

    Judging it against a *fixed* floor instead is what makes the test absolute while its
    consequence stays proportional: $0.01 is the right question for a $100 leg and absurd for a
    $900,000 one, so a shortfall of two cents on a flash loan reads as an endpoint and returns the
    entire $900,000 gross to the notional. Scaling the question with the leg is what closes that —
    a shortfall is measured as a fraction of the flow it failed to cancel, at every size.

    An unpriceable non-zero net is never called cancelled. Unknown is not small (see
    :func:`_is_negligible`), and a leg with no USD value contributes no notional either way.
    """
    if net_usd is None or gross_usd is None:
        return False
    return net_usd <= residual_tolerance_usd(gross_usd)


def _notional_from_flows(flows, quote_usd):
    """Largest net endpoint; failing that, the round trip the transaction routed.

    The fallback is safe in the only direction that matters. Reaching it means every token came
    back, i.e. each leg's net is within ``max($0.01, 0.01% of that leg's gross)``. The fallback
    notional is the largest of those grosses, so the transaction tolerance is at least every leg's
    own — every leg is therefore negligible, nothing survives, and the result is
    ``CIRCULAR_ARBITRAGE``: excluded from the primary metric with its volume still on the record.
    No arrangement of cancelling legs can push a residual into a trade through this door.
    """
    endpoint_usd = None   # largest net USD value among tokens that left something behind
    routed_usd = None     # largest gross USD flow among tokens that did not
    left_an_endpoint = False

    for token in sorted(flows):
        sent, received = flows[token]
        net = received - sent
        if net == 0:
            continue  # moved and came back to the raw unit: an intermediate, a loan, a self-move
        # abs() on ints throughout: exact, and no decimal context is involved.
        net_usd = _usd_value(quote_usd, token, abs(net))
        gross_usd = _usd_value(quote_usd, token, max(sent, received))
        if _came_back(net_usd, gross_usd):
            if routed_usd is None or gross_usd > routed_usd:
                routed_usd = gross_usd
            continue
        # Something stayed. That is true even when it cannot be priced, and an unpriceable
        # endpoint must still suppress the round-trip fallback — otherwise a transaction whose
        # only endpoint is a long-tail token would be sized by a loan wrapped around it.
        left_an_endpoint = True
        if net_usd is not None and (endpoint_usd is None or net_usd > endpoint_usd):
            endpoint_usd = net_usd

    return endpoint_usd if left_an_endpoint else routed_usd


def _gross_volume_from_flows(flows, quote_usd):
    """The largest one-way flow of any priceable token, cancelling legs included.

    This is *volume*, not size: what a per-leg sum would have booked. A non-trade carries it so
    that the reconciliation queue can be sorted by how much moved and the §4.3 exclusion can report
    the phantom volume it removed — including for a round trip that netted to exactly zero, which
    has no endpoint to be sized by and would otherwise report nothing at all.

    It is deliberately not what the tolerance is a percentage of; see
    :func:`transaction_notional_usd`.
    """
    volume = None
    for token in sorted(flows):
        sent, received = flows[token]
        value = _usd_value(quote_usd, token, max(sent, received))
        if value is None:
            continue
        if volume is None or value > volume:
            volume = value
    return volume


# -- step 8 and 9: negligibility and classification -----------------------------


def _legs(flows, quote_usd):
    """Signed net deltas, sorted by token so the output is byte-stable."""
    legs = []
    for token in sorted(flows):
        sent, received = flows[token]
        raw = received - sent
        magnitude = _usd_value(quote_usd, token, abs(raw))
        usd = None if magnitude is None else (_negate(magnitude) if raw < 0 else magnitude)
        legs.append(NetDelta(token=token, raw=raw, usd=usd))
    return legs


def _is_negligible(leg, tolerance):
    """A leg drops out only when it is provably small.

    An unpriceable leg (``usd is None``) with a non-zero quantity is *not* negligible. Treating an
    unknown value as a small one is the single easiest way to manufacture a clean two-leg trade
    out of a transaction nobody actually understood.
    """
    if leg.raw == 0:
        return True
    if leg.usd is None:
        return False
    return _magnitude(leg.usd) <= tolerance


def net_transaction(tx, quote_usd):
    """Reconstruct one transaction's economic intent. Always returns a result.

    ``quote_usd`` is a callable ``(token, raw_amount) -> Optional[Decimal]`` or a mapping
    ``{token: Decimal usd per raw unit}``, consulted for quote assets only.

    On the returned :class:`NetTradeResult`:

    * for a trade, ``quote_usd`` is the absolute USD value of the quote leg — the trade size §4.4
      weights by;
    * for every other status it carries the **gross volume**: the largest one-way flow of any
      priceable token, cancelling legs included, so the reconciliation queue can show how much
      moved and the circular-arbitrage exclusion can report how much phantom volume it removed.
      ``status.is_trade`` is what separates the two readings. It is *not* the notional the
      negligibility tolerance is taken from — that one counts endpoints only, see
      :func:`transaction_notional_usd`;
    * ``residuals`` holds every netted leg that is not an endpoint — the intermediates that
      cancelled, the dust that was discarded as negligible, and, for a non-trade, the legs that
      survived. Together with the endpoints and the fee transfers it reconciles exactly to the
      owner's raw balance change: nothing created, nothing vanished;
    * ``pool`` is left ``None``. Balance netting cannot attribute a pool — a split route touches
      several — and guessing one would satisfy §4.1's "attributable to a specific pool" with a
      fiction.
    """
    owner = tx.attribution.portfolio_owner
    base = {
        "tx_hash": tx.tx_hash,
        "portfolio_owner": owner,
        "block_number": tx.block_number,
        "timestamp": tx.timestamp,
    }

    # Step 1. §4.1 requires meta.err == null. A reverted transaction's transfers did not happen,
    # so they are not netted even when a source hands them to us.
    if not tx.success:
        return NetTradeResult(
            status=ClassificationStatus.FAILED_TRANSACTION,
            reason="transaction reverted (success=False); §4.1 requires a successful transaction, "
                   "and no balance change in a reverted transaction is real",
            **base
        )

    # Step 2. Addendum §8: uncertain owner attribution is excluded from the primary metric rather
    # than resolved by falling back to the transaction sender. `coalesce(taker, tx_from)` is that
    # fallback, and it attributes solver-settled trades to the solver — phantom mega-wallets.
    if not tx.attribution.is_usable_for_primary_metric:
        return NetTradeResult(
            status=ClassificationStatus.UNSUPPORTED,
            reason="attribution is not usable for the primary metric (method={}, account_type={}, "
                   "owner={}); addendum §8 excludes uncertain ownership rather than guessing "
                   "it".format(tx.attribution.method.value, tx.attribution.account_type.value,
                               owner),
            **base
        )

    _require_eth_collapsed(tx)  # step 5

    flows = _owner_flows(tx, owner)  # steps 3, 4, 6, 7
    # Size and volume are different questions and are answered separately: the tolerance is a
    # percentage of what the transaction actually traded, while a non-trade reports everything
    # that moved. Collapsing the two lets a leg that cancelled set the negligibility threshold.
    notional = _notional_from_flows(flows, quote_usd)
    volume = _gross_volume_from_flows(flows, quote_usd)
    tolerance = residual_tolerance_usd(notional)
    legs = _legs(flows, quote_usd)

    if not legs:
        return NetTradeResult(
            status=ClassificationStatus.NO_CLEAR_ENDPOINT,
            quote_usd=volume,
            reason="no non-fee transfer touches the portfolio owner, so there is no balance "
                   "change to net",
            **base
        )

    surviving = [leg for leg in legs if not _is_negligible(leg, tolerance)]
    discarded = tuple(leg for leg in legs if _is_negligible(leg, tolerance))

    # §4.3. Every leg netted to within tolerance: the transaction is a round trip. Netting reports
    # it correctly as near-zero, but there is no token bought and none sold to express, and left
    # in, arbitrage bots read as wallets with thousands of small profitable trades.
    if not surviving:
        return NetTradeResult(
            status=ClassificationStatus.CIRCULAR_ARBITRAGE,
            quote_usd=volume,
            residuals=tuple(legs),
            reason="every netted leg is within the negligible tolerance of ${}; §4.3 round trip — "
                   "there is no endpoint to express, and per-leg summing would book the gross "
                   "route as user volume".format(tolerance),
            **base
        )

    # Exactly one leg survived: something moved and nothing came back to explain it. Partial fills
    # and unmatched movements land here. Addendum §8 sends them to the reconciliation queue —
    # neither silently included nor silently dropped.
    if len(surviving) == 1:
        leg = surviving[0]
        return NetTradeResult(
            status=ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL,
            quote_usd=volume,
            residuals=tuple(legs),
            reason="one surviving leg ({}, raw {}, usd {}) exceeds the negligible tolerance of "
                   "${} and has no counterparty leg; routed to the reconciliation queue "
                   "(addendum §8)".format(leg.token, leg.raw, leg.usd, tolerance),
            **base
        )

    if len(surviving) > 2:
        return NetTradeResult(
            status=ClassificationStatus.NO_CLEAR_ENDPOINT,
            quote_usd=volume,
            residuals=tuple(legs),
            reason="{} legs survive the ${} tolerance; a trade has two endpoints, and choosing "
                   "two of these would be a guess".format(len(surviving), tolerance),
            **base
        )

    first, second = surviving
    quote_legs = [leg for leg in surviving if is_quote_asset(leg.token)]

    if len(quote_legs) == 2:
        return NetTradeResult(
            status=ClassificationStatus.NO_CLEAR_ENDPOINT,
            quote_usd=volume,
            residuals=tuple(legs),
            reason="both surviving legs ({} and {}) are quote assets; neither is the asset being "
                   "traded, so the trade has no expressible direction".format(
                       first.token, second.token),
            **base
        )

    if not quote_legs:
        return NetTradeResult(
            status=ClassificationStatus.NO_CLEAR_ENDPOINT,
            quote_usd=volume,
            residuals=tuple(legs),
            reason="neither surviving leg ({} nor {}) is a quote asset; §4.1 requires a valid "
                   "quote asset, and §4.6 permits no USD price for either".format(
                       first.token, second.token),
            **base
        )

    quote_leg = quote_legs[0]
    asset_leg = second if quote_leg is first else first

    if (quote_leg.raw > 0) == (asset_leg.raw > 0):
        return NetTradeResult(
            status=ClassificationStatus.NO_CLEAR_ENDPOINT,
            quote_usd=volume,
            residuals=tuple(legs),
            reason="both surviving legs moved in the same direction ({} raw {}, {} raw {}); a "
                   "swap has one leg in and one leg out".format(
                       quote_leg.token, quote_leg.raw, asset_leg.token, asset_leg.raw),
            **base
        )

    if quote_leg.usd is None:
        # §4.1: trade size must be computable. Emitting a trade with an unknown size would put a
        # hole in the weighted aggregation that no downstream module could see.
        return NetTradeResult(
            status=ClassificationStatus.UNSUPPORTED,
            quote_usd=volume,
            residuals=tuple(legs),
            reason="quote leg {} has no USD price in the supplied book, so trade size is not "
                   "computable (§4.1); quarantined rather than reported with an unknown "
                   "size".format(quote_leg.token),
            **base
        )

    # Quote leg negative means the owner paid the quote asset away: a buy of the other leg.
    status = (ClassificationStatus.VALID_BUY if quote_leg.raw < 0
              else ClassificationStatus.VALID_SELL)
    sold_leg, bought_leg = ((quote_leg, asset_leg) if quote_leg.raw < 0
                            else (asset_leg, quote_leg))

    return NetTradeResult(
        status=status,
        sold_asset=sold_leg.token,
        bought_asset=bought_leg.token,
        sold_raw_amount=-sold_leg.raw,   # raw units, exact; the seam forbids rounding these
        bought_raw_amount=bought_leg.raw,
        quote_asset=quote_leg.token,
        quote_usd=_magnitude(quote_leg.usd),
        residuals=discarded,
        **base
    )


# -- batch helpers --------------------------------------------------------------


def net_transactions(transactions, quote_usd):
    """Net a sequence, preserving input order. Pure: no state carries between transactions."""
    return tuple(net_transaction(tx, quote_usd) for tx in transactions)


def reconciliation_queue(results):
    """The transactions that owe someone an answer, oldest first.

    Volume (``quote_usd``, the gross notional) and age (``timestamp``, ``block_number``) are
    already on each result, which is what ticket 21 requires be visible.
    """
    queued = [r for r in results if r.status in QUEUED_STATUSES]
    queued.sort(key=lambda r: (r.timestamp if r.timestamp is not None else 0, r.tx_hash))
    return tuple(queued)


def status_counts(results):
    """Coverage: how many transactions landed in each status.

    Every status is present in the mapping, including the zeroes. A coverage report that omits the
    statuses it never saw cannot be compared against the next run's.
    """
    counts = {status: 0 for status in ClassificationStatus}
    for result in results:
        counts[result.status] += 1
    return counts
