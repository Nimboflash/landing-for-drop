"""Invariants netting must hold for every transaction shape hypothesis can build.

The load-bearing one is conservation: **retained deltas reconcile to raw owner balance changes.**
Endpoints plus residuals plus fee legs equal the owner's total signed movement, token by token, in
exact raw units. Nothing created, nothing vanished. A netting bug that invents or loses quantity
is invisible in a spot check — the totals still look plausible — and shows up only as an
unexplained coverage gap weeks later.

The rest defend the two ordering-critical steps: the owner filter and the fee filter must not be
sensitive to transfer order, to how a route was split, or to whose money shares the transaction.
"""

from decimal import Decimal

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from contracts import (
    AccountType,
    Attribution,
    AttributionMethod,
    ClassificationStatus,
    Transaction,
    Transfer,
    USDC,
    USDT,
    WBTC,
    WETH,
    to_canonical_json,
)
from netting import (
    RESIDUAL_FLOOR_USD,
    RESIDUAL_NOTIONAL_RATE,
    net_transaction,
    residual_tolerance_usd,
    transaction_notional_usd,
)

OWNER = "0x1111111111111111111111111111111111111111"
OTHERS = [
    "0x2222222222222222222222222222222222222222",
    "0x3333333333333333333333333333333333333333",
    "0x4444444444444444444444444444444444444444",
]

PEPE = "0x6982508145454ce325ddbe47a25d4ec3d2311933"
SHIB = "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce"
TOKENS = [USDC, USDT, WETH, PEPE, SHIB]

PRICES = {
    USDC: Decimal("0.000001"),
    USDT: Decimal("0.000001"),
    WETH: Decimal("0.000000000000003"),
}

#: A lender, and a quote asset none of the strategies above ever draw. A cancelling loan has to be
#: in a token the transaction does not otherwise touch to isolate what is being tested: a token the
#: owner also trades has a gross flow of its own, and §4.3 sizes a round trip by what it routed.
LENDER = "0x9999999999999999999999999999999999999999"
LOAN_PRICES = dict(PRICES)
LOAN_PRICES[WBTC] = Decimal("0.0006")  # 8 decimals at $60,000

SETTINGS = settings(max_examples=200, deadline=None,
                    suppress_health_check=[HealthCheck.too_slow])


# -- strategies -----------------------------------------------------------------

raw_amounts = st.integers(min_value=1, max_value=10 ** 24)


def _transfer(token, from_addr, to_addr, raw, log_index, is_fee):
    return Transfer(token=token, from_addr=from_addr, to_addr=to_addr,
                    raw_amount=raw, log_index=log_index, is_fee=is_fee)


@st.composite
def owner_transfers(draw, min_size=0, max_size=6, touching_owner=True):
    """Transfers with at least one side pinned to (or kept away from) the owner."""
    count = draw(st.integers(min_value=min_size, max_value=max_size))
    out = []
    for i in range(count):
        token = draw(st.sampled_from(TOKENS))
        raw = draw(raw_amounts)
        is_fee = draw(st.booleans())
        counterparty = draw(st.sampled_from(OTHERS))
        if touching_owner:
            inbound = draw(st.booleans())
            from_addr, to_addr = (counterparty, OWNER) if inbound else (OWNER, counterparty)
        else:
            other = draw(st.sampled_from(OTHERS))
            assume(other != counterparty)
            from_addr, to_addr = counterparty, other
        out.append(_transfer(token, from_addr, to_addr, raw, i, is_fee))
    return out


@st.composite
def swaps(draw):
    """A well-formed swap, wrapped in every kind of noise netting is supposed to see through.

    The route is built so the answer is known before the code runs: one quote endpoint, one asset
    endpoint, an intermediate hop that round-trips to exactly zero, dust below any tolerance
    (1 raw unit of WETH is worth $3e-15), a fee transfer, and unrelated bundle traffic. Returns
    ``(transfers, expected_status, quote_token, quote_raw, asset_token, asset_raw)``.
    """
    quote = draw(st.sampled_from([USDC, USDT]))          # both 6 decimals at $1
    intermediate = USDT if quote == USDC else USDC
    asset = draw(st.sampled_from([PEPE, SHIB]))
    quote_raw = draw(st.integers(min_value=10 ** 6, max_value=10 ** 12))   # $1 .. $1,000,000
    asset_raw = draw(st.integers(min_value=1, max_value=10 ** 24))
    is_buy = draw(st.booleans())
    pool, pool_b, bundler = OTHERS

    out = []
    if is_buy:
        out.append(_transfer(quote, OWNER, pool, quote_raw, 0, False))
        out.append(_transfer(asset, pool, OWNER, asset_raw, 1, False))
    else:
        out.append(_transfer(asset, OWNER, pool, asset_raw, 0, False))
        out.append(_transfer(quote, pool, OWNER, quote_raw, 1, False))

    if draw(st.booleans()):  # an intermediate hop, netting to exactly zero
        # Drawn independently of ``quote_raw``: an intermediate built from the endpoint's own size
        # can never exceed it, which is precisely the case that has to be reachable — a hop (or a
        # flash loan) larger than the trade it wraps must still decide nothing.
        intermediate_raw = draw(st.integers(min_value=1, max_value=10 ** 15))
        out.append(_transfer(intermediate, pool, OWNER, intermediate_raw, 2, False))
        out.append(_transfer(intermediate, OWNER, pool_b, intermediate_raw, 3, False))
    if draw(st.booleans()):  # dust far below the $0.01 floor
        out.append(_transfer(WETH, pool, OWNER, 1, 4, False))
    if draw(st.booleans()):  # a referral fee, which is never an endpoint
        out.append(_transfer(quote, OWNER, bundler, draw(raw_amounts), 5, True))
    if draw(st.booleans()):  # a searcher's sandwich around the owner's trade
        out.append(_transfer(WETH, bundler, pool, draw(raw_amounts), 6, False))
        out.append(_transfer(asset, pool, bundler, draw(raw_amounts), 7, False))

    expected = (ClassificationStatus.VALID_BUY if is_buy
                else ClassificationStatus.VALID_SELL)
    return _renumber(out), expected, quote, quote_raw, asset, asset_raw


def _attribution(tx_hash="0xtx"):
    return Attribution(
        tx_hash=tx_hash, tx_sender=OWNER, portfolio_owner=OWNER,
        account_type=AccountType.EOA, method=AttributionMethod.DIRECT_EOA,
        confidence=Decimal("1"), evidence=("property fixture",),
    )


def _transaction(transfers, success=True):
    return Transaction(
        tx_hash="0xtx", block_number=18_000_000, timestamp=1_700_000_000,
        success=success, attribution=_attribution(), transfers=tuple(transfers),
    )


def _renumber(transfers):
    return [
        _transfer(t.token, t.from_addr, t.to_addr, t.raw_amount, i, t.is_fee)
        for i, t in enumerate(transfers)
    ]


def _signed_totals(transfers, include_fees=True):
    """The owner's raw balance change per token, computed the naive way, as the yardstick."""
    totals = {}
    for t in transfers:
        if t.is_fee and not include_fees:
            continue
        delta = 0
        if t.to_addr == OWNER:
            delta += t.raw_amount
        if t.from_addr == OWNER:
            delta -= t.raw_amount
        if delta or t.to_addr == OWNER or t.from_addr == OWNER:
            totals[t.token] = totals.get(t.token, 0) + delta
    return {k: v for k, v in totals.items()}


# -- conservation ---------------------------------------------------------------


@SETTINGS
@given(owner_transfers())
def test_retained_plus_residual_plus_fees_equals_raw_balance_change(transfers):
    """Endpoints + residuals + fee legs == the owner's total signed movement, exactly."""
    tx = _transaction(transfers)
    result = net_transaction(tx, PRICES)

    accounted = {}
    if result.status.is_trade:
        accounted[result.sold_asset] = accounted.get(result.sold_asset, 0) - result.sold_raw_amount
        accounted[result.bought_asset] = (
            accounted.get(result.bought_asset, 0) + result.bought_raw_amount
        )
    for delta in result.residuals:
        accounted[delta.token] = accounted.get(delta.token, 0) + delta.raw
    for t in transfers:
        if not t.is_fee:
            continue
        if t.to_addr == OWNER:
            accounted[t.token] = accounted.get(t.token, 0) + t.raw_amount
        if t.from_addr == OWNER:
            accounted[t.token] = accounted.get(t.token, 0) - t.raw_amount

    expected = _signed_totals(transfers)
    assert {k: v for k, v in accounted.items() if v != 0} == \
        {k: v for k, v in expected.items() if v != 0}


@SETTINGS
@given(owner_transfers())
def test_no_token_appears_that_the_owner_never_touched(transfers):
    touched = {t.token for t in transfers if OWNER in (t.from_addr, t.to_addr)}
    result = net_transaction(_transaction(transfers), PRICES)

    for delta in result.residuals:
        assert delta.token in touched
    for field in (result.sold_asset, result.bought_asset, result.quote_asset):
        if field is not None:
            assert field in touched


# -- one status per transaction, always -----------------------------------------


@SETTINGS
@given(owner_transfers(), st.booleans())
def test_every_transaction_gets_exactly_one_status_and_a_reason(transfers, success):
    result = net_transaction(_transaction(transfers, success=success), PRICES)

    assert isinstance(result.status, ClassificationStatus)
    if not result.status.is_trade:
        assert result.reason, "a non-trade without a reason is indistinguishable from a drop"
    assert result.tx_hash == "0xtx"
    assert result.block_number == 18_000_000
    assert result.timestamp == 1_700_000_000


@SETTINGS
@given(owner_transfers())
def test_output_always_survives_canonical_json_and_is_deterministic(transfers):
    tx = _transaction(transfers)
    first = to_canonical_json(net_transaction(tx, PRICES))
    second = to_canonical_json(net_transaction(tx, PRICES))
    assert first == second
    assert "e+" not in first.lower(), "exponent notation would break byte-stable hashing"


# -- the two ordering-critical filters ------------------------------------------


@SETTINGS
@given(owner_transfers(min_size=1))
def test_transfer_order_does_not_change_the_result(transfers):
    """Netting is a sum. If order mattered, some step would be reading a sequence, not a set."""
    forward = net_transaction(_transaction(transfers), PRICES)
    reverse = net_transaction(_transaction(list(reversed(transfers))), PRICES)
    assert to_canonical_json(forward) == to_canonical_json(reverse)


@SETTINGS
@given(owner_transfers(min_size=1), owner_transfers(max_size=4, touching_owner=False))
def test_third_party_transfers_never_change_the_result(owned, foreign):
    """The MEV-bundle guarantee: someone else's transfers in the same transaction are inert."""
    alone = net_transaction(_transaction(_renumber(owned)), PRICES)
    bundled = net_transaction(_transaction(_renumber(list(owned) + list(foreign))), PRICES)
    assert to_canonical_json(alone) == to_canonical_json(bundled)


@SETTINGS
@given(owner_transfers(min_size=1, max_size=4))
def test_splitting_a_transfer_in_two_does_not_change_the_result(transfers):
    """Route-shape agnosticism: a split route must net to the same intent as a single hop."""
    split = []
    for t in transfers:
        if t.raw_amount >= 2:
            half = t.raw_amount // 2
            split.append(_transfer(t.token, t.from_addr, t.to_addr, half, 0, t.is_fee))
            split.append(
                _transfer(t.token, t.from_addr, t.to_addr, t.raw_amount - half, 0, t.is_fee))
        else:
            split.append(t)

    whole = net_transaction(_transaction(_renumber(transfers)), PRICES)
    parts = net_transaction(_transaction(_renumber(split)), PRICES)
    assert to_canonical_json(whole) == to_canonical_json(parts)


@SETTINGS
@given(owner_transfers(min_size=1))
def test_marking_every_transfer_as_a_fee_leaves_no_endpoint(transfers):
    """Fees are never endpoints — so a transaction of nothing but fees is never a trade."""
    fees = [_transfer(t.token, t.from_addr, t.to_addr, t.raw_amount, i, True)
            for i, t in enumerate(transfers)]
    result = net_transaction(_transaction(fees), PRICES)
    assert result.status is ClassificationStatus.NO_CLEAR_ENDPOINT
    assert result.residuals == ()


# -- trade shape ----------------------------------------------------------------


@SETTINGS
@given(swaps())
def test_a_well_formed_swap_always_nets_to_exactly_one_trade(swap):
    """Noise in, one intent out — for every route shape the strategy can build.

    Intermediates, dust, referral fees and a searcher's sandwich all sit in the same transaction,
    and none of them may move the endpoint quantities by a single raw unit.
    """
    transfers, expected, quote, quote_raw, asset, asset_raw = swap
    result = net_transaction(_transaction(transfers), PRICES)

    assert result.status is expected
    assert result.quote_asset == quote
    assert result.asset == asset
    assert result.asset_raw_amount == asset_raw
    if expected is ClassificationStatus.VALID_BUY:
        assert result.sold_asset == quote and result.sold_raw_amount == quote_raw
        assert result.bought_asset == asset and result.bought_raw_amount == asset_raw
    else:
        assert result.bought_asset == quote and result.bought_raw_amount == quote_raw
        assert result.sold_asset == asset and result.sold_raw_amount == asset_raw
    # 6-decimal stablecoin at $1: the USD value is the raw quantity times 0.000001, exactly.
    assert result.quote_usd == Decimal(quote_raw) * Decimal("0.000001")
    # No intermediate, no dust and no fee may be reported as an endpoint.
    assert result.bought_asset != WETH and result.sold_asset != WETH


@SETTINGS
@given(swaps())
def test_a_swap_conserves_quantity_through_every_layer_of_noise(swap):
    transfers = swap[0]
    result = net_transaction(_transaction(transfers), PRICES)

    accounted = {result.sold_asset: -result.sold_raw_amount}
    accounted[result.bought_asset] = accounted.get(result.bought_asset, 0) + \
        result.bought_raw_amount
    for delta in result.residuals:
        accounted[delta.token] = accounted.get(delta.token, 0) + delta.raw
    for t in transfers:
        if t.is_fee and t.from_addr == OWNER:
            accounted[t.token] = accounted.get(t.token, 0) - t.raw_amount

    expected = _signed_totals(transfers)
    assert {k: v for k, v in accounted.items() if v != 0} == \
        {k: v for k, v in expected.items() if v != 0}


@SETTINGS
@given(owner_transfers(min_size=2))
def test_a_trade_is_always_one_quote_leg_against_one_asset_leg(transfers):
    result = net_transaction(_transaction(transfers), PRICES)
    if not result.status.is_trade:
        return

    assert result.sold_raw_amount > 0 and result.bought_raw_amount > 0
    assert result.sold_asset != result.bought_asset
    assert result.quote_asset in (result.sold_asset, result.bought_asset)
    assert result.quote_usd > 0
    # A surviving leg is above the tolerance by definition, and the tolerance is at least $0.01.
    assert result.quote_usd >= RESIDUAL_FLOOR_USD

    if result.status is ClassificationStatus.VALID_BUY:
        assert result.quote_asset == result.sold_asset
        assert result.asset == result.bought_asset
    else:
        assert result.quote_asset == result.bought_asset
        assert result.asset == result.sold_asset


@SETTINGS
@given(owner_transfers(min_size=2))
def test_residuals_on_a_trade_are_all_negligible(transfers):
    """A trade's residuals are the legs that were discarded — each provably within tolerance."""
    tx = _transaction(transfers)
    result = net_transaction(tx, PRICES)
    if not result.status.is_trade:
        return

    tolerance = residual_tolerance_usd(transaction_notional_usd(tx, PRICES))
    for delta in result.residuals:
        assert delta.raw == 0 or (delta.usd is not None and abs(delta.usd) <= tolerance)


@SETTINGS
@given(owner_transfers(min_size=1))
def test_circular_arbitrage_never_carries_a_position(transfers):
    result = net_transaction(_transaction(transfers), PRICES)
    if result.status is ClassificationStatus.CIRCULAR_ARBITRAGE:
        assert result.sold_asset is None and result.bought_asset is None
        assert result.sold_raw_amount is None and result.bought_raw_amount is None
        assert result.asset is None


# -- what may set the tolerance -------------------------------------------------
#
# The negligibility tolerance is a percentage of the transaction notional, so anything that can
# enlarge the notional can decide what counts as unexplained money. A leg that comes back in full
# is money that never stayed: it must not be able to buy a larger tolerance for the legs that did.


def _with_loan(transfers, loan_raw):
    """The same transfers, wrapped in a WBTC loan that is borrowed and repaid in full."""
    return _renumber(list(transfers) + [
        _transfer(WBTC, LENDER, OWNER, loan_raw, 0, False),
        _transfer(WBTC, OWNER, LENDER, loan_raw, 0, False),
    ])


@SETTINGS
@given(owner_transfers(), st.integers(min_value=1, max_value=10 ** 12))
def test_a_loan_that_is_repaid_in_full_never_moves_the_notional(transfers, loan_raw):
    """Up to $600,000,000 of borrowed WBTC, gone by the end of the transaction, sizes nothing."""
    plain = _transaction(_renumber(transfers))
    borrowed = _transaction(_with_loan(transfers, loan_raw))
    assert transaction_notional_usd(borrowed, LOAN_PRICES) == \
        transaction_notional_usd(plain, LOAN_PRICES)


def _with_partial_loan(transfers, loan_raw, shortfall_raw):
    """The same transfers, wrapped in a WBTC loan repaid ``shortfall_raw`` raw units short."""
    return _renumber(list(transfers) + [
        _transfer(WBTC, LENDER, OWNER, loan_raw, 0, False),
        _transfer(WBTC, OWNER, LENDER, loan_raw + shortfall_raw, 0, False),
    ])


@SETTINGS
@given(swaps(), st.data())
def test_a_loan_repaid_within_its_own_tolerance_never_moves_the_notional(swap, data):
    """The generalisation of the repaid-in-full case, and the one the floor rule failed.

    ``shortfall_raw`` is drawn as a fraction of the loan rather than as an absolute number of
    dollars, so the regime the previous rule could not survive — a shortfall above $0.01 on a leg
    large enough that it is still nothing — is reachable at every loan size the generator draws,
    instead of only at the one value a reviewer happened to cite.

    Any shortfall up to 0.01% of the loan is within the leg's own proportional tolerance, so the
    leg left no endpoint however many dollars that fraction happens to be: at 10^12 raw WBTC it is
    $60,000 of shortfall on $600,000,000 borrowed.
    """
    transfers, _, _, _, _, _ = swap
    loan_raw = data.draw(st.integers(min_value=10 ** 4, max_value=10 ** 12))
    shortfall_raw = data.draw(st.integers(min_value=0, max_value=loan_raw // 10_000))

    plain = _transaction(_renumber(transfers))
    borrowed = _transaction(_with_partial_loan(transfers, loan_raw, shortfall_raw))

    assert transaction_notional_usd(borrowed, LOAN_PRICES) == \
        transaction_notional_usd(plain, LOAN_PRICES)


@SETTINGS
@given(swaps(), st.data())
def test_scaling_a_cancelling_leg_a_thousandfold_changes_nothing(swap, data):
    """The tolerance may not move with the size of a leg that came back.

    The same shortfall is left on a loan and on one a thousand times larger. What stayed is
    identical, so the notional, the classification and the endpoints must be identical — an
    attacker choosing how much to borrow must not thereby be choosing the threshold.
    """
    transfers, _, _, _, _, _ = swap
    loan_raw = data.draw(st.integers(min_value=10 ** 4, max_value=10 ** 9))
    shortfall_raw = data.draw(st.integers(min_value=0, max_value=loan_raw // 10_000))

    small = _transaction(_with_partial_loan(transfers, loan_raw, shortfall_raw))
    large = _transaction(_with_partial_loan(transfers, loan_raw * 1000, shortfall_raw))

    assert transaction_notional_usd(large, LOAN_PRICES) == \
        transaction_notional_usd(small, LOAN_PRICES)

    small_result = net_transaction(small, LOAN_PRICES)
    large_result = net_transaction(large, LOAN_PRICES)

    def endpoints(result):
        return (result.status, result.sold_asset, result.sold_raw_amount, result.bought_asset,
                result.bought_raw_amount, result.quote_asset,
                result.quote_usd if result.status.is_trade else None)

    assert endpoints(large_result) == endpoints(small_result)


@SETTINGS
@given(swaps(), st.integers(min_value=1, max_value=10 ** 12))
def test_a_loan_that_is_repaid_in_full_leaves_a_well_formed_swap_intact(swap, loan_raw):
    """And it cannot reclassify one either.

    Without the loan these swaps are trades. With a $600m tolerance bought by a leg that netted to
    zero, every endpoint in them is dust and the transaction reads as circular arbitrage.
    """
    transfers, expected, quote, quote_raw, asset, asset_raw = swap
    result = net_transaction(_transaction(_with_loan(transfers, loan_raw)), LOAN_PRICES)

    assert result.status is expected
    assert result.quote_asset == quote
    assert result.asset == asset
    assert result.asset_raw_amount == asset_raw
    assert result.quote_usd == Decimal(quote_raw) * Decimal("0.000001")


# -- the tolerance function itself ----------------------------------------------


@SETTINGS
@given(st.decimals(min_value=Decimal("0"), max_value=Decimal("1e9"),
                   allow_nan=False, allow_infinity=False, places=6))
def test_tolerance_is_never_below_either_arm(notional):
    tolerance = residual_tolerance_usd(notional)
    assert tolerance >= RESIDUAL_FLOOR_USD
    assert tolerance >= notional * RESIDUAL_NOTIONAL_RATE


@SETTINGS
@given(st.decimals(min_value=Decimal("0"), max_value=Decimal("1e9"),
                   allow_nan=False, allow_infinity=False, places=6),
       st.decimals(min_value=Decimal("0"), max_value=Decimal("1e9"),
                   allow_nan=False, allow_infinity=False, places=6))
def test_tolerance_is_monotone_in_notional(a, b):
    small, large = (a, b) if a <= b else (b, a)
    assert residual_tolerance_usd(small) <= residual_tolerance_usd(large)
