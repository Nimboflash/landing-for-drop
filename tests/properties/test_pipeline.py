"""Invariants the composition root must hold for every run hypothesis can build.

Three of these are the reason this file exists, and none of them is visible in a worked example:

* **Nothing leaves without a line.** Every transaction that went in is accounted for by exactly one
  status, one exclusion, or one queue entry. A composed run loses population at the joins, not
  inside a stage, and a spot check cannot see it because the numbers that remain still look
  plausible.
* **The answer does not depend on the order the caller assembled its input.** Every aggregate here
  is a sum of 38-digit Decimals, and each addition rounds. A total that followed input order would
  be reproducible only by accident, and §9.2 requires the Independent Validator to re-derive it.
* **The answer does not depend on the caller's ambient decimal context.** ``abs()``, unary ``-`` and
  bare ``+ - * /`` all round to whatever context happens to be current. Every one of them returns a
  plausible number, which is why this class of defect has shipped three times here and been caught
  by review rather than by a test.

The generators deliberately produce broken shapes as well as good ones — sells with no buys, batches
with two owners, reverted transactions, dust. A property suite that only builds well-formed input
tests the happy path with extra steps.
"""

import dataclasses
from decimal import ROUND_DOWN, ROUND_UP, Context, Decimal, localcontext

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from contracts import (
    ClassificationStatus,
    PoolState,
    Transfer,
    USDC,
    add,
    sub,
)
from attribution import AttributionContext
from pipeline import (
    ACCOUNTING_STAGES,
    MEASUREMENT_HORIZON_SECONDS,
    STAGE_ORDER,
    ObservedTransaction,
    Stage,
    TokenStart,
    Window,
    WindowConfig,
    run_wallet_window,
)

# -- the world ------------------------------------------------------------------

WALLETS = [
    "0x" + "a1" * 20,
    "0x" + "a2" * 20,
    "0x" + "a3" * 20,
]
STRANGER = "0x" + "a9" * 20
VENUE = "0x" + "b0" * 20

TOKENS = ["0x" + "c1" * 20, "0x" + "c2" * 20, "0x" + "c3" * 20]
POOLS_BY_TOKEN = ["0x" + "d1" * 20, "0x" + "d2" * 20, "0x" + "d3" * 20]

ONE_USDC = 10 ** 6
ONE_TOKEN = 10 ** 18

START_BLOCK = 18_000_000
START_TS = 1_700_000_000
END_BLOCK = START_BLOCK + 7_200
END_TS = START_TS + 86_400
HORIZON_BLOCK = END_BLOCK + 216_000
HORIZON_TS = END_TS + MEASUREMENT_HORIZON_SECONDS

PRICES = {USDC: Decimal("0.000001")}

WINDOW = Window(index=1, start_block=START_BLOCK, start_ts=START_TS,
                end_block=END_BLOCK, end_ts=END_TS)

CONTEXT = AttributionContext(
    infrastructure=frozenset({VENUE} | set(POOLS_BY_TOKEN)),
    eoas=frozenset(WALLETS + [STRANGER]),
)

POOLS = {
    token: PoolState(
        address=address, asset=token, quote=USDC,
        # Reserves large enough that an ordinary exit is not liquidity-bounded, and a last swap at
        # the horizon so nothing here is dead — the dead path has its own worked example.
        asset_reserve_raw=10 ** 24, quote_reserve_raw=10 ** 12,
        last_swap_block=HORIZON_BLOCK, last_swap_timestamp=HORIZON_TS, fee_bps=30,
    )
    for token, address in zip(TOKENS, POOLS_BY_TOKEN)
}

CONFIG = WindowConfig(
    horizon_block=HORIZON_BLOCK,
    horizon_ts=HORIZON_TS,
    token_starts={
        token: TokenStart(block=START_BLOCK - 50_000 * (index + 1),
                          timestamp=START_TS - 600_000 * (index + 1))
        for index, token in enumerate(TOKENS)
    },
)

SETTINGS = settings(max_examples=60, deadline=None,
                    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])


# -- strategies -----------------------------------------------------------------

KINDS = ["buy", "sell", "dust", "failed", "batch"]

actions = st.lists(
    st.tuples(
        st.sampled_from(KINDS),
        st.integers(min_value=0, max_value=len(WALLETS) - 1),
        st.integers(min_value=0, max_value=len(TOKENS) - 1),
        st.integers(min_value=1, max_value=5_000),      # USDC, whole dollars
        st.integers(min_value=1, max_value=100_000),    # tokens, whole units
    ),
    min_size=1,
    max_size=10,
)


def _transfer(token, from_addr, to_addr, raw, index):
    return Transfer(token=token, from_addr=from_addr, to_addr=to_addr, raw_amount=raw,
                    log_index=index)


def build(action_list):
    """Turn the drawn actions into observed transactions on strictly increasing blocks.

    Blocks are unique across the whole run, which keeps FIFO's same-block refusal out of the picture
    unless a test is deliberately after it — the properties below are about composition, and a book
    quarantined for an unorderable pair would mask them.
    """
    transactions = []
    for index, (kind, wallet_index, token_index, usdc, tokens) in enumerate(action_list):
        wallet = WALLETS[wallet_index]
        token = TOKENS[token_index]
        pool = POOLS_BY_TOKEN[token_index]
        tx_hash = "0x{:04x}".format(index)
        block = START_BLOCK + 1 + index * 5
        timestamp = START_TS + 12 + index * 60
        raw_usdc = usdc * ONE_USDC
        raw_tokens = tokens * ONE_TOKEN

        if kind == "buy":
            transfers = [
                _transfer(USDC, wallet, pool, raw_usdc, 0),
                _transfer(token, pool, wallet, raw_tokens, 1),
            ]
        elif kind == "sell":
            transfers = [
                _transfer(token, wallet, pool, raw_tokens, 0),
                _transfer(USDC, pool, wallet, raw_usdc, 1),
            ]
        elif kind == "dust":
            transfers = [_transfer(USDC, wallet, STRANGER, raw_usdc, 0)]
        elif kind == "failed":
            transfers = [
                _transfer(USDC, wallet, pool, raw_usdc, 0),
                _transfer(token, pool, wallet, raw_tokens, 1),
            ]
        else:  # "batch" — two typed EOAs settled together: two owners, one owner slot
            other = WALLETS[(wallet_index + 1) % len(WALLETS)]
            transfers = [
                _transfer(USDC, wallet, pool, raw_usdc, 0),
                _transfer(token, pool, wallet, raw_tokens, 1),
                _transfer(USDC, other, pool, raw_usdc, 2),
                _transfer(token, pool, other, raw_tokens, 3),
            ]

        transactions.append(ObservedTransaction(
            tx_hash=tx_hash,
            block_number=block,
            timestamp=timestamp,
            success=(kind != "failed"),
            tx_sender=STRANGER if kind == "batch" else wallet,
            transfers=tuple(transfers),
            context=CONTEXT,
        ))
    return transactions


def run(transactions):
    return run_wallet_window(transactions, POOLS, PRICES, WINDOW, CONFIG)


def projection(result):
    """Everything a reader would publish, in a form two runs can be compared on."""
    return (
        result.window,
        result.stages,
        tuple(sorted(result.census.counts.items(), key=lambda kv: kv[0].value)),
        result.census.quarantined,
        result.coverage,
        tuple(sorted(
            (w.wallet, w.quality, w.unscorable_reason is None) for w in result.wallets
        )),
        tuple(sorted(r.tx_hashes for r in result.quarantine)),
        tuple(sorted(e.tx_hash for e in result.excluded)),
    )


# -- nothing leaves without a line ----------------------------------------------


@SETTINGS
@given(actions)
def test_every_transaction_is_accounted_for_exactly_once(action_list):
    """The reconciliation the result type exists for, over arbitrary input.

    Netting is total, so every transaction either produced a result or was refused outright, and the
    census must cover both. A transaction in neither has been dropped without a record — the one
    outcome the failure policy prohibits outright.
    """
    transactions = build(action_list)
    result = run(transactions)

    classified = {r.tx_hash for r in result.results}
    refused = set(t for r in result.quarantine.by_stage(Stage.NETTING) for t in r.tx_hashes)

    assert classified | refused == {t.tx_hash for t in transactions}
    assert not (classified & refused)
    assert result.census.total == len(transactions)
    assert sum(result.census.counts.values()) + result.census.quarantined == len(transactions)
    assert result.stages.transactions_in == len(transactions)


@SETTINGS
@given(actions)
def test_every_valid_buy_is_scored_quarantined_deferred_or_left_unscored(action_list):
    """The four-way partition of the buy population, asserted rather than trusted to a constructor.

    ``StageCounts`` refuses to be built if it does not hold, so this is guarding the guard: a
    partition enforced only where it is computed is a partition nobody has checked against a run.
    """
    result = run(build(action_list))
    stages = result.stages
    assert (stages.buys_scored + stages.buys_quarantined + stages.buys_outside_window
            + stages.buys_unscored) == stages.buys
    assert stages.buys == result.census.counts[ClassificationStatus.VALID_BUY]
    assert stages.sells == result.census.counts[ClassificationStatus.VALID_SELL]
    assert stages.trades == result.census.trades


@SETTINGS
@given(actions)
def test_an_excluded_attribution_never_reaches_a_wallet_score(action_list):
    """§8 exclusion has to be an exclusion. A batch settling two owners must not be scored for
    either of them — that is the phantom mega-wallet arriving through the composition root instead
    of through ``coalesce(taker, tx_from)``."""
    result = run(build(action_list))

    excluded = {record.tx_hash for record in result.excluded}
    scored = {account.buy.tx_hash for account in result.accounts}
    assert not (excluded & scored)
    assert len(result.excluded) == result.stages.attributions_excluded
    assert (result.stages.attributions_usable + result.stages.attributions_excluded
            == result.stages.transactions_in)


@SETTINGS
@given(actions)
def test_a_quarantined_transaction_never_reaches_a_wallet_score(action_list):
    result = run(build(action_list))
    queued = set(result.quarantine.transactions)
    scored = {account.buy.tx_hash for account in result.accounts}
    assert not (queued & scored)


# -- conservation ---------------------------------------------------------------


@SETTINGS
@given(actions)
def test_raw_quantity_is_conserved_across_the_fifo_marking_join(action_list):
    """``realized + open == bought``, exactly, in raw units with no tolerance.

    §9.2 lists FIFO lot assignment among the deterministic fields that must match the golden set at
    raw-unit level, and the join between FIFO and marking is where a unit would be created or lost:
    one side counts what was consumed and the other values what is left.
    """
    result = run(build(action_list))
    for account in result.accounts:
        assert account.realized_raw >= 0
        assert account.open_raw >= 0
        assert account.realized_raw + account.open_raw == account.buy.asset_raw_amount
        assert account.late_sold_raw <= account.open_raw
        assert (account.position is None) == (account.open_raw == 0)


@SETTINGS
@given(actions)
def test_the_value_basis_shares_sum_to_one_for_every_scored_wallet(action_list):
    """§10's mix, checked at the top level. ``BuyQuality`` enforces it at construction; this asserts
    that the composition root actually produced one rather than a bare number that lost it."""
    result = run(build(action_list))
    for wallet, quality in result.qualities.items():
        total = add(add(quality.realized_share, quality.marked_share), quality.dead_share)
        assert total.copy_abs() > 0
        assert sub(total, Decimal("1")).copy_abs() <= Decimal("0.0001")
        assert quality.wallet == wallet
        assert quality.n_buys >= 1


@SETTINGS
@given(actions)
def test_coverage_is_bounded_by_the_population_it_describes(action_list):
    result = run(build(action_list))
    coverage = result.coverage
    assert Decimal("0") <= coverage.notional_usd_scored <= coverage.notional_usd_trades
    assert coverage.notional_usd_trades <= coverage.notional_usd_total
    assert coverage.notional_usd_non_trades >= 0
    if coverage.is_reportable:
        assert Decimal("0") <= coverage.trade_share <= Decimal("1")
        assert Decimal("0") <= coverage.scored_share <= Decimal("1")
    else:
        assert coverage.trade_share is None
        assert coverage.scored_share is None
    assert (coverage.transactions_priced + coverage.transactions_unpriced
            >= result.stages.netted)


# -- reproducibility ------------------------------------------------------------


@SETTINGS
@given(actions, st.randoms(use_true_random=False))
def test_the_result_does_not_depend_on_the_order_the_caller_supplied(action_list, random):
    """Shuffle the input and every published number must be identical, to the last digit.

    Not merely "close". Each of these totals is a sum of 38-digit Decimals and every addition
    rounds, so an aggregate that accumulated in caller order would agree on small inputs and drift
    on large ones — a reproducibility failure that only appears at scale, which is the worst place
    to find one.
    """
    transactions = build(action_list)
    shuffled = list(transactions)
    random.shuffle(shuffled)

    assert projection(run(shuffled)) == projection(run(transactions))


@SETTINGS
@given(actions)
def test_the_result_does_not_depend_on_the_callers_ambient_decimal_context(action_list):
    """Evaluated at 9 digits rounding down, and at 50 rounding up. Both must agree with the default.

    Every value in the run is carried at the frozen 38 digits. A bare operator anywhere in the
    composition would silently adopt the ambient context and hand back a truncated number that looks
    entirely reasonable, which is exactly how this defect reached production three times.
    """
    transactions = build(action_list)
    baseline = projection(run(transactions))

    with localcontext(Context(prec=9, rounding=ROUND_DOWN)):
        assert projection(run(transactions)) == baseline
    with localcontext(Context(prec=50, rounding=ROUND_UP)):
        assert projection(run(transactions)) == baseline


@SETTINGS
@given(actions)
def test_two_identical_runs_produce_identical_results(action_list):
    """No hidden state carries between runs: no clock, no cache, no accumulated context."""
    transactions = build(action_list)
    assert projection(run(transactions)) == projection(run(transactions))


@SETTINGS
@given(actions)
def test_the_stages_always_run_in_the_order_section_4_fixes(action_list):
    result = run(build(action_list))
    assert result.stages_run == STAGE_ORDER


# -- isolation ------------------------------------------------------------------


@SETTINGS
@given(actions, actions)
def test_one_wallets_score_does_not_move_when_another_wallets_transactions_arrive(first, second):
    """A wallet's score is a function of that wallet's own trades.

    The generators draw from a shared address pool, so the second batch is filtered to the wallets
    the first does not use — the property is about *independent* wallets, and pooling two wallets'
    activity under one owner is a different bug with its own test in ``attribution``.
    """
    alone = run(build(first))
    if not alone.qualities:
        return

    owners = set(alone.qualities)
    spare = [w for w in WALLETS if w not in owners]
    if not spare:
        return
    keep = WALLETS.index(spare[0])
    extra = [
        (kind, keep, token, usdc, tokens)
        for (kind, _wallet, token, usdc, tokens) in second
        if kind != "batch"  # a batch names a second wallet and could name one of the first's
    ]
    if not extra:
        return

    combined_actions = list(first) + extra
    combined = run(build(combined_actions))

    for wallet, quality in alone.qualities.items():
        assert combined.qualities.get(wallet) == quality


# -- identity -------------------------------------------------------------------
#
# Every property above is a statement about a population, and each of them is keyed by ``tx_hash``
# somewhere: the census split, the four-way buy partition, the queue's transaction list, the map
# from a buy to the consumptions that realized it. All of them are statements about *sets of
# transactions* only while one hash means one transaction, and nothing upstream of the composition
# root establishes that. So it is established at the boundary, and asserted here over every shape
# the generators can draw rather than over the six that were traced by hand.


@SETTINGS
@given(actions, st.integers(min_value=0, max_value=9), st.sampled_from(["plain", "upper", "padded"]))
def test_any_two_transactions_sharing_a_hash_are_refused_and_the_hash_is_named(
        action_list, offset, spelling):
    """Duplicate any one row's hash onto any other row, and the run must refuse rather than answer.

    The control runs first, so the property cannot pass by refusing everything: the same input with
    distinct hashes is required to produce a result. The spellings are drawn because
    ``ObservedTransaction`` normalises the hash before anything sees it — a check written against
    what the caller typed would miss ``"0xDUP  "`` against ``"0xdup"``, which is the same collision
    wearing different clothes.
    """
    transactions = build(action_list)
    if len(transactions) < 2:
        return
    run(transactions)  # the control: distinct hashes answer, so the refusal below is not vacuous

    source = offset % len(transactions)
    target = (source + 1) % len(transactions)
    collided = transactions[source].tx_hash
    spelled = {
        "plain": collided,
        "upper": collided.upper(),
        "padded": "  " + collided + "  ",
    }[spelling]

    duplicated = list(transactions)
    duplicated[target] = dataclasses.replace(duplicated[target], tx_hash=spelled)

    with pytest.raises(ValueError) as refusal:
        run(duplicated)
    message = str(refusal.value)
    assert collided in message
    assert "appears 2 times" in message
    assert str(sorted((source, target))[0]) in message


@SETTINGS
@given(actions)
def test_a_run_whose_hashes_are_distinct_names_every_transaction_exactly_once(action_list):
    """The invariant the refusal buys, stated positively.

    Everything the result publishes about *which* transactions did what is a hash: the census
    split, the queue's transaction list, the exclusion records, and the buy rows underneath every
    wallet score. If any of those could carry a hash twice, none of them would be a list of
    transactions.
    """
    transactions = build(action_list)
    result = run(transactions)

    hashes = [t.tx_hash for t in transactions]
    assert len(set(hashes)) == len(hashes)
    assert len({r.tx_hash for r in result.results}) == len(result.results)
    assert len({e.tx_hash for e in result.excluded}) == len(result.excluded)
    for wallet in result.wallets:
        rows = [a.buy.tx_hash for a in wallet.accounts]
        assert len(set(rows)) == len(rows)


# -- one spelling, one asset ----------------------------------------------------
#
# The transaction hash is one of five identity keys the boundary indexes by. The other four are the
# configuration mappings — the pool book, the price book, the §4.7 trading starts and the migration
# replacements — and every one of them is read through ``normalise_asset``, so its key space is the
# normalised one whether the caller spells it that way or not. Two properties hold it, and they are
# opposite halves of the same statement: respelling a key must change nothing, and supplying two
# spellings must refuse.

MAPPINGS = ("pools", "prices", "token_starts", "replacement_pools")
RESPELLINGS = ("upper", "checksummed")


def _respell(key, style):
    return {
        "upper": key.upper(),
        "checksummed": key[:2] + key[2:].upper(),
        "padded": "  " + key + "  ",
    }[style]


def _configured(transactions, pools=None, prices=None, config=None):
    return run_wallet_window(
        transactions,
        POOLS if pools is None else pools,
        PRICES if prices is None else prices,
        WINDOW,
        CONFIG if config is None else config,
    )


def _config_with(token_starts=None, replacement_pools=None):
    return WindowConfig(
        horizon_block=HORIZON_BLOCK,
        horizon_ts=HORIZON_TS,
        token_starts=CONFIG.token_starts if token_starts is None else token_starts,
        replacement_pools={} if replacement_pools is None else replacement_pools,
    )


def _run_with_a_second_spelling(transactions, which, style):
    """The same value under two spellings of one asset. Both entries agree, deliberately.

    A guard that fired only when the two disagreed would close every case a reviewer would trace
    and leave the condition — an unnormalised key space — untouched, so the property is stated over
    the collision rather than over the values.
    """
    token = TOKENS[0]
    if which == "pools":
        book = dict(POOLS)
        book[_respell(token, style)] = POOLS[token]
        return _configured(transactions, pools=book)
    if which == "prices":
        book = dict(PRICES)
        book[_respell(USDC, style)] = PRICES[USDC]
        return _configured(transactions, prices=book)
    if which == "token_starts":
        starts = dict(CONFIG.token_starts)
        starts[_respell(token, style)] = CONFIG.token_starts[token]
        return _configured(transactions, config=_config_with(token_starts=starts))
    return _configured(transactions, config=_config_with(
        replacement_pools={token: POOLS[token], _respell(token, style): POOLS[token]},
    ))


def _run_with_the_key_respelled(transactions, which, style):
    """The same mapping, one key spelled differently — no collision, and nothing may move."""
    token = TOKENS[0]
    if which == "pools":
        return _configured(transactions, pools={
            (_respell(key, style) if key == token else key): value
            for key, value in POOLS.items()
        })
    if which == "prices":
        return _configured(transactions, prices={
            _respell(key, style): value for key, value in PRICES.items()
        })
    return _configured(transactions, config=_config_with(token_starts={
        (_respell(key, style) if key == token else key): value
        for key, value in CONFIG.token_starts.items()
    }))


@SETTINGS
@given(actions, st.sampled_from(MAPPINGS), st.sampled_from(RESPELLINGS))
def test_two_spellings_of_one_asset_in_any_configuration_mapping_are_refused(
        action_list, which, style):
    """Whichever mapping, whichever spelling: two keys naming one asset is refused at entry.

    The control runs first, so the property cannot pass by refusing everything.
    """
    transactions = build(action_list)
    run(transactions)

    with pytest.raises(ValueError) as refusal:
        _run_with_a_second_spelling(transactions, which, style)
    message = str(refusal.value)
    assert which in message
    assert (USDC if which == "prices" else TOKENS[0]) in message
    assert "more than once" in message


@SETTINGS
@given(actions, st.sampled_from(MAPPINGS), st.sampled_from(RESPELLINGS + ("padded",)))
def test_a_padded_key_in_any_configuration_mapping_is_refused(action_list, which, style):
    """A padded key can never be matched, because the seam's normalisation does not strip.

    Drawn alongside the two spellings that *can* be matched so the case cannot quietly become a
    test of the collision rule: for ``upper`` and ``checksummed`` the single key is accepted and the
    run answers, and only ``padded`` refuses.
    """
    transactions = build(action_list)
    if which == "replacement_pools":
        which = "pools"

    if style != "padded":
        _run_with_the_key_respelled(transactions, which, style)
        return

    with pytest.raises(ValueError) as refusal:
        _run_with_the_key_respelled(transactions, which, style)
    assert "padded with whitespace" in str(refusal.value)


@SETTINGS
@given(actions, st.sampled_from(("pools", "prices", "token_starts")),
       st.sampled_from(RESPELLINGS))
def test_how_the_caller_spells_a_configuration_key_changes_no_published_number(
        action_list, which, style):
    """The other half: a key is an asset, not a string, so respelling one must move nothing.

    This is the half that was missing, and its absence is what let the defect be *half* fixed.
    ``WindowConfig`` looked its keys up normalised and stored them verbatim, so a caller using
    checksummed addresses supplied §4.7 trading starts that could never be read — every buy
    quarantined as unknown-age — while the pool book and the price book beside it worked fine.
    Asserting the refusal alone would have left that asymmetry entirely unpinned.
    """
    transactions = build(action_list)
    assert projection(_run_with_the_key_respelled(transactions, which, style)) == projection(
        run(transactions)
    )


# -- the queue ------------------------------------------------------------------


@SETTINGS
@given(actions)
def test_quarantined_volume_is_reported_and_never_negative(action_list):
    """Quarantined volume is a number §10 will not let be an omission. It may be unknown for a
    record — that is what ``unpriced`` counts — but it is never invented and never negative."""
    result = run(build(action_list))
    queue = result.quarantine
    assert queue.total_volume_usd >= 0
    assert queue.unpriced <= len(queue)
    for record in queue:
        assert record.tx_hashes
        assert record.reason
        # ACCOUNTING_STAGES, not STAGE_ORDER: a queue record may also come from ingestion, which
        # is not a §4 stage. This generator only builds decodable transactions, so an INGESTION
        # record never arises here — asserting against the narrower tuple would still pass and
        # would be a claim about the generator rather than about the queue.
        assert record.stage in ACCOUNTING_STAGES
        assert record.volume_usd is None or record.volume_usd >= 0
    assert result.coverage.notional_usd_quarantined == queue.total_volume_usd
