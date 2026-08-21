"""A transaction nobody can decode is counted, named, and never scored.

``ingest.events.SIGNATURES`` is a closed registry and no registry is ever complete. What must be
impossible is not "an event we have not enumerated" — that will happen forever — but **an
undecodable transaction disappearing from the accounting**. Before the type this file exercises
existed, ``ingest`` raised on the whole receipt, the refusal propagated out of ingestion, and the
transaction entered no census, no queue and no coverage report: ``pipeline.run_wallet_window`` was
never called with it, and no field on ``WalletWindowResult`` could have held it.

The three things pinned here, in order:

* **the boundary.** :func:`pipeline.observed_transaction` turns a decoder limitation into a value
  and leaves an input defect as a raise — the line the house rules draw between the two;
* **the accounting.** ``census.total`` counts the transaction, ``StageCounts`` reconciles around
  it, the queue names its topic and contract, and nothing scores it;
* **the conservation check.** A shortfall is constructed by hand and the refusal confirmed, in
  both directions — a transaction accounted for nowhere, and one accounted for twice.

Every literal is written out. Nothing here re-derives an expectation by calling the code under
test with a different spelling of the same expression.
"""

import re
from dataclasses import replace
from decimal import Decimal

import pytest

from attribution import AttributionContext
from contracts import USDC, ClassificationStatus, Transfer
from ingest import DECLINED, SIGNATURES, MalformedLog, TRANSFER, TRANSFER_SINGLE
from pipeline import (
    ACCOUNTING_STAGES,
    MEASUREMENT_HORIZON_SECONDS,
    STAGE_ORDER,
    ClassificationCensus,
    ObservedTransaction,
    QuarantineQueue,
    QuarantineRecord,
    Stage,
    StageCounts,
    TokenStart,
    UndecodableTransaction,
    Window,
    WindowConfig,
    observed_transaction,
    run_wallet_window,
    stage_rank,
)
from pipeline.result import WalletWindowResult
from pipeline.run import _require_the_population_is_conserved

# -- the world ------------------------------------------------------------------

WALLET = "0x" + "a1" * 20
POOL = "0x" + "b1" * 20
TOKEN = "0x" + "c1" * 20
SEAPORT = "0x00000000006c3852cbef3e08e8df289169ede581"

#: Seaport 1.1's ``OrderFulfilled``, on the Seaport contract above. A real topic, read off log 307
#: of ``0x8ed9a26a…`` in ``tests/fixtures/events/recordings``, and **not** in ``SIGNATURES`` — which
#: is the whole point of the fixture.
#:
#: This used to be 1inch's ``OrderFilled``. It had to move when ticket 20 admitted that event to the
#: registry, and *that it had to move is the argument this file makes*: an unlisted event is not a
#: fixed set of topics to be worked through until the list is empty. Every widening turns some
#: transactions from unreadable to readable and leaves the next unlisted event doing exactly what
#: this one did. The accounting is what survives the widening; the entry is what does not.
UNLISTED_TOPIC = "0x9d9af8e38d66c62e2c12f0225249fd9d721c54b83f48d9352c97c6cacdcb6f31"

ONE_USDC = 10 ** 6
ONE_TOKEN = 10 ** 18

START_BLOCK = 18_000_000
START_TS = 1_700_000_000
END_BLOCK = START_BLOCK + 7_200
END_TS = START_TS + 86_400
HORIZON_BLOCK = END_BLOCK + 216_000
HORIZON_TS = END_TS + MEASUREMENT_HORIZON_SECONDS

WINDOW = Window(index=3, start_block=START_BLOCK, start_ts=START_TS,
                end_block=END_BLOCK, end_ts=END_TS)

CONFIG = WindowConfig(
    horizon_block=HORIZON_BLOCK, horizon_ts=HORIZON_TS,
    token_starts={TOKEN: TokenStart(block=START_BLOCK - 100_000,
                                    timestamp=START_TS - 1_000_000)},
)

PRICES = {USDC: Decimal("0.000001")}

CONTEXT = AttributionContext(
    infrastructure=frozenset({POOL}), eoas=frozenset({WALLET}),
)


def transfer(token, from_addr, to_addr, raw, index):
    return Transfer(token=token, from_addr=from_addr, to_addr=to_addr, raw_amount=raw,
                    log_index=index)


def a_buy(tx_hash, nth):
    """1,000 USDC out, 4,000 TOKEN in. Fully sold by ``a_sell`` below, so nothing is marked."""
    return ObservedTransaction(
        tx_hash=tx_hash,
        block_number=START_BLOCK + nth,
        timestamp=START_TS + nth * 12,
        success=True,
        tx_sender=WALLET,
        transfers=(
            transfer(USDC, WALLET, POOL, 1_000 * ONE_USDC, 0),
            transfer(TOKEN, POOL, WALLET, 4_000 * ONE_TOKEN, 1),
        ),
        context=CONTEXT,
    )


def a_sell(tx_hash, nth):
    """4,000 TOKEN out, 1,500 USDC in — a +50% round trip, sold inside the horizon."""
    return ObservedTransaction(
        tx_hash=tx_hash,
        block_number=START_BLOCK + nth,
        timestamp=START_TS + nth * 12,
        success=True,
        tx_sender=WALLET,
        transfers=(
            transfer(TOKEN, WALLET, POOL, 4_000 * ONE_TOKEN, 0),
            transfer(USDC, POOL, WALLET, 1_500 * ONE_USDC, 1),
        ),
        context=CONTEXT,
    )


def an_undecodable(tx_hash, nth, log_index=96):
    return UndecodableTransaction(
        tx_hash=tx_hash,
        block_number=START_BLOCK + nth,
        timestamp=START_TS + nth * 12,
        tx_sender=WALLET,
        topic=UNLISTED_TOPIC,
        contract=SEAPORT,
        log_index=log_index,
        refusal="UnknownEvent",
        detail="log {} on {} carries an unknown event signature {}.".format(
            log_index, SEAPORT, UNLISTED_TOPIC
        ),
    )


def run(transactions):
    return run_wallet_window(transactions, {}, PRICES, WINDOW, CONFIG)


# -- the type -------------------------------------------------------------------


def test_the_carried_status_names_no_event_the_decoder_can_now_read():
    """The docstring's own claim, held against the registry rather than against a reader's memory.

    :class:`pipeline.UndecodableTransaction`'s docstring used to list four events as ones the
    decoder had not enumerated. Ticket 20 admitted three of them and the paragraph went on
    asserting it, which is the failure mode a closed registry guarantees: any example of an
    unlisted event is a fact with a shelf life, and a docstring is not rebuilt when the registry is.

    So the rule is structural. Every event this type's docstring names must be one refused for a
    reason a widening cannot retire — ``ingest.events.DECLINED``, where ERC-1155's two sit because
    the asset they move is the pair ``(contract, id)`` and ``contracts.Transfer`` has one address
    and no second field. Admitting those is a change to the frozen seam, not an entry in a registry.

    The check reads the docstring's own code spans, so it fails the moment somebody adds an example
    that ``SIGNATURES`` already covers — including one added long after this file stopped being
    read.
    """
    spans = set(re.findall(r"``([^`]+)``", UndecodableTransaction.__doc__))
    admitted = {signature.name for signature in SIGNATURES.values()}
    declined = {entry.name for entry in DECLINED.values()}

    named_events = {span for span in spans if span in admitted | declined}
    assert named_events == {"TransferSingle", "TransferBatch"}
    assert not (named_events & admitted), (
        "the docstring names {}, which ingest.events.SIGNATURES now decodes".format(
            sorted(named_events & admitted)
        )
    )
    # And they are named for the structural reason, not by coincidence: both really are declined.
    assert named_events <= declined


def test_an_undecodable_transaction_must_name_what_could_not_be_decoded():
    """A queue entry saying only "could not decode" cannot be worked.

    The reader's next action is to classify the topic in ``ingest.events.SIGNATURES``, and that
    needs the topic. So the refusal's class and its message are both required at construction —
    the type refuses to exist in a state whose only content is that something went wrong.
    """
    with pytest.raises(ValueError, match="must carry both the refusal's class and its message"):
        UndecodableTransaction(
            tx_hash="0x1", block_number=START_BLOCK, timestamp=START_TS, tx_sender=WALLET,
            topic=UNLISTED_TOPIC, contract=SEAPORT, log_index=96, refusal="", detail="anything",
        )
    with pytest.raises(ValueError, match="must carry both the refusal's class and its message"):
        UndecodableTransaction(
            tx_hash="0x1", block_number=START_BLOCK, timestamp=START_TS, tx_sender=WALLET,
            topic=UNLISTED_TOPIC, contract=SEAPORT, log_index=96, refusal="UnknownEvent", detail="",
        )


def test_an_undecodable_transaction_must_have_an_identity():
    """Without a hash it can be counted and never named, which is the omission this type answers."""
    with pytest.raises(ValueError, match="tx_hash is required"):
        an_undecodable("", 1)


def test_the_hash_the_topic_and_the_contract_are_normalised_the_way_every_other_key_is():
    """Same spelling rules as ``ObservedTransaction``, so one transaction is one row in both."""
    item = UndecodableTransaction(
        tx_hash="  0xABCD  ", block_number=START_BLOCK, timestamp=START_TS,
        tx_sender=WALLET.upper(), topic=UNLISTED_TOPIC.upper(), contract=SEAPORT.upper(),
        log_index=96, refusal="UnknownEvent", detail="…",
    )
    assert item.tx_hash == "0xabcd"
    assert item.tx_sender == WALLET
    assert item.topic == UNLISTED_TOPIC
    assert item.contract == SEAPORT


def test_describe_names_the_transaction_the_contract_the_topic_and_the_log():
    described = an_undecodable("0xdead", 1).describe()
    for fact in ("0xdead", SEAPORT, UNLISTED_TOPIC, "log 96", "UnknownEvent"):
        assert fact in described
    assert "ingest.events.SIGNATURES" in described


def test_it_carries_no_transfers_at_all_and_has_nowhere_to_put_any():
    """The absence is structural, not a default.

    An empty ``transfers`` tuple on this type would say *this transaction moved nothing*, which is
    the one statement the refusal has established to be unknown. There is no field to put it in.
    """
    assert not hasattr(an_undecodable("0x1", 1), "transfers")


# -- the boundary: which refusals become a value --------------------------------


class _StubClient:
    """The two calls :func:`pipeline.observed_transaction` makes, answered from a dict."""

    def __init__(self, logs):
        self._logs = logs

    def get_transaction_receipt(self, tx_hash):
        return {
            "transactionHash": "0x" + "11" * 32,
            "blockNumber": "0x1",
            "blockHash": "0x" + "22" * 32,
            "status": "0x1",
            "from": WALLET,
            "logs": self._logs,
        }

    def get_block_by_number(self, height):
        return {"number": "0x1", "timestamp": "0x64", "hash": "0x" + "22" * 32}


def _log(topic0, topics=(), data="0x" + "00" * 32, index=0, address=SEAPORT):
    return {"address": address, "topics": [topic0] + list(topics), "data": data,
            "logIndex": hex(index)}


def test_an_unlisted_event_comes_back_as_a_value_rather_than_raising():
    item = observed_transaction(_StubClient([_log(UNLISTED_TOPIC, index=7)]), "0x" + "11" * 32)
    assert isinstance(item, UndecodableTransaction)
    assert item.refusal == "UnknownEvent"
    assert (item.topic, item.contract, item.log_index) == (UNLISTED_TOPIC, SEAPORT, 7)
    # The header and the receipt decoded perfectly; only the logs did not.
    assert (item.block_number, item.timestamp) == (1, 100)


def test_a_log_whose_shape_contradicts_its_signature_comes_back_as_a_value_too():
    """ERC-721 shares ERC-20's ``Transfer`` topic and indexes a third parameter, the token id.

    A decoder limitation, not an input defect: the log is a perfectly valid one that this decoder
    has chosen not to read. Read positionally it would hand over a token id where an amount
    belongs, so refusing it is right — and counting it is what this file is about.
    """
    erc721 = _log(
        TRANSFER,
        topics=["0x" + "00" * 32] * 3,
        index=4,
    )
    item = observed_transaction(_StubClient([erc721]), "0x" + "11" * 32)
    assert isinstance(item, UndecodableTransaction)
    assert item.refusal == "LogShapeMismatch"
    assert (item.topic, item.log_index) == (TRANSFER, 4)


def test_a_declined_event_comes_back_as_a_value_through_the_same_door():
    """An event the decoder has read and refused on purpose is counted like one it never met.

    ``ingest.events.DECLINED`` is the record of a decision — ERC-1155's ``TransferSingle`` moves
    value that ``contracts.Transfer`` cannot name, so admitting it would net one token id against
    another. The refusal has to stay :class:`UnknownEvent`, because that is the exception
    :func:`pipeline.observed_transaction` turns into a counted row, and a deliberate refusal needs
    counting for exactly the reason an accidental one does. Only the ``detail`` differs — and it has
    to, because the reader's next move is different: there is nothing here to classify.

    Pinned so that a future edit cannot make ``DECLINED`` its own exception type and quietly turn
    every ERC-1155 transaction back into an absence.
    """
    single = _log(
        TRANSFER_SINGLE,
        topics=["0x" + "00" * 32] * 3,
        data="0x" + "00" * 64,
        index=11,
    )
    item = observed_transaction(_StubClient([single]), "0x" + "11" * 32)

    assert isinstance(item, UndecodableTransaction)
    assert item.refusal == "UnknownEvent"
    assert (item.topic, item.log_index) == (TRANSFER_SINGLE, 11)
    assert "deliberately does not admit" in item.detail
    # And the queue record carries that sentence onward, so the distinction survives to the report.
    # The stub's block and timestamp are the stub's, not the window's, so they are replaced here
    # rather than the window being widened to accommodate a fixture.
    in_window = replace(item, block_number=START_BLOCK + 3, timestamp=START_TS + 36)
    result = run([a_buy("0x1", 1), a_sell("0x2", 2), in_window])
    record, = result.quarantine.by_stage(Stage.INGESTION)
    assert "deliberately does not admit" in record.reason


def test_a_dict_that_is_not_a_log_still_raises():
    """The line the house rules draw, pinned from the other side.

    ``MalformedLog`` says the bytes that reached this function are not the log they claim to be —
    a defect in what assembled the call, not a fact about Ethereum. Nothing was measured, so there
    is no measurement to qualify with a status, and turning it into one would let a malformed feed
    report itself as a limitation of the decoder.
    """
    with pytest.raises(MalformedLog):
        observed_transaction(_StubClient([{"address": SEAPORT, "logIndex": "0x0"}]),
                             "0x" + "11" * 32)


# -- the accounting -------------------------------------------------------------


def test_the_undecodable_transaction_is_in_the_census_and_the_queue_and_no_score():
    """Three transactions in, three accounted for, one of them never read.

    Hand-computed: the buy and the sell net to one VALID_BUY and one VALID_SELL, so
    ``counts`` sums to 2; nothing is quarantined by netting; one row is undecodable. 2 + 0 + 1 = 3.
    """
    result = run([a_buy("0x1", 1), a_sell("0x2", 2), an_undecodable("0x3", 3)])

    assert result.census.total == 3
    assert result.census.undecodable == 1
    assert sum(result.census.counts.values()) == 2
    assert result.census.counts[ClassificationStatus.VALID_BUY] == 1
    assert result.census.counts[ClassificationStatus.VALID_SELL] == 1
    assert result.census.quarantined == 0

    assert result.stages.transactions_in == 3
    assert result.stages.transactions_undecodable == 1
    assert result.stages.attributions_resolved == 2
    assert result.stages.netted == 2

    record, = result.quarantine.by_stage(Stage.INGESTION)
    assert record.tx_hashes == ("0x3",)
    assert record.volume_usd is None
    assert record.wallet is None
    assert UNLISTED_TOPIC in record.reason

    # Never scored, and not merely absent from the accounts: it reaches no stage at all.
    assert "0x3" not in {row.tx_hash for row in result.results}
    assert "0x3" not in {record.tx_hash for record in result.excluded}
    assert result.stages_run == STAGE_ORDER
    assert Stage.INGESTION not in result.stages_run
    # The +50% round trip is unaffected: $1,500 of proceeds on $1,000 of cost, exactly.
    account, = result.accounts
    assert account.cost_usd == Decimal("1000")
    assert account.realized_proceeds_usd == Decimal("1500")
    assert account.return_pct == Decimal("0.5")


def test_the_run_without_the_undecodable_row_publishes_the_same_score_and_a_smaller_total():
    """The counterfactual, so "counted" is a measured difference and not a claim.

    Drop the third row and the score is identical while ``census.total`` falls to 2. That is
    precisely the old behaviour, and precisely why it was invisible: nothing a reader looks at
    moves except the denominator, and the denominator was the thing being reported.
    """
    with_it = run([a_buy("0x1", 1), a_sell("0x2", 2), an_undecodable("0x3", 3)])
    without = run([a_buy("0x1", 1), a_sell("0x2", 2)])

    assert with_it.wallets[0].quality.value == without.wallets[0].quality.value
    assert (with_it.census.total, without.census.total) == (3, 2)
    assert (with_it.census.undecodable, without.census.undecodable) == (1, 0)
    assert (len(with_it.quarantine), len(without.quarantine)) == (1, 0)


def test_the_unreadable_transaction_counts_as_unpriced_coverage():
    """Nothing in it was decoded, so there is not even a leg to attempt a price on."""
    result = run([a_buy("0x1", 1), a_sell("0x2", 2), an_undecodable("0x3", 3)])
    coverage = result.coverage
    assert (coverage.transactions_priced, coverage.transactions_unpriced) == (2, 1)
    assert coverage.transactions_priced + coverage.transactions_unpriced == 3
    # $0 of *quarantined* notional is not $0 of cost: the record is unpriced, not free.
    assert coverage.notional_usd_quarantined == 0
    assert result.quarantine.unpriced == 1


def test_two_rows_under_one_hash_are_refused_across_both_kinds():
    """The hash uniqueness rule spans the decoded and the undecodable, or the census double-counts.

    One transaction arriving as both a read row and an unread one would be counted twice — once
    classified, once undecodable — and ``total`` would then be right about a population that does
    not exist.
    """
    with pytest.raises(ValueError, match="distinct tx_hash values"):
        run([a_buy("0x1", 1), an_undecodable("0x1", 3)])


def test_an_undecodable_row_outside_the_measurement_period_is_still_a_caller_error():
    """The window check is about the population the score is computed over, not about decoding."""
    late = UndecodableTransaction(
        tx_hash="0x9", block_number=HORIZON_BLOCK + 1, timestamp=HORIZON_TS + 1,
        tx_sender=WALLET, topic=UNLISTED_TOPIC, contract=SEAPORT, log_index=1,
        refusal="UnknownEvent", detail="…",
    )
    with pytest.raises(ValueError, match="after the marking horizon"):
        run([a_buy("0x1", 1), late])


def test_ingestion_is_ranked_before_the_four_stages_but_is_not_one_of_them():
    """The queue needs an order for it; §4's sequence must not acquire one.

    ``STAGE_ORDER`` is what ``WalletWindowResult`` checks a run's ``stages_run`` against, and
    ingestion is not a stage a run enters — its refusals arrive already made. RECONCILIATION is the
    same shape at the other end: the queue needs a rank for it, but it is not a §4 stage a run
    enters either — it names a residual that already has a result, routed for visibility. So both
    bracket ``STAGE_ORDER`` in ``ACCOUNTING_STAGES`` without joining it.
    """
    assert Stage.INGESTION not in STAGE_ORDER
    assert Stage.RECONCILIATION not in STAGE_ORDER
    assert ACCOUNTING_STAGES == (Stage.INGESTION,) + STAGE_ORDER + (Stage.RECONCILIATION,)
    assert stage_rank(Stage.INGESTION) == 0
    assert stage_rank(Stage.ATTRIBUTION) == 1
    assert stage_rank(Stage.SCORING) == 5
    assert stage_rank(Stage.RECONCILIATION) == 6


def test_the_queue_puts_ingestion_first():
    """A netting quarantine and an ingestion one in the same run, in reading order."""
    queue = QuarantineQueue(records=tuple(sorted(
        [
            QuarantineRecord(stage=Stage.MARKING, reason="no pool", tx_hashes=("0xb",)),
            QuarantineRecord(stage=Stage.INGESTION, reason="unknown event", tx_hashes=("0xa",)),
        ],
        key=lambda r: (stage_rank(r.stage), r.tx_hashes),
    )))
    assert [r.stage for r in queue] == [Stage.INGESTION, Stage.MARKING]


# -- conservation: a shortfall cannot be published ------------------------------


def _census(total, classified=2, quarantined=0, undecodable=0):
    counts = {status: 0 for status in ClassificationStatus}
    counts[ClassificationStatus.VALID_BUY] = classified
    return ClassificationCensus(
        counts=counts, quarantined=quarantined, unsupported_from_attribution=0,
        total=total, undecodable=undecodable,
    )


class _Row:
    """The one attribute :func:`_require_the_population_is_conserved` reads off a netted result."""

    def __init__(self, tx_hash):
        self.tx_hash = tx_hash


def test_the_census_refuses_a_total_larger_than_the_terms_that_make_it_up():
    """The reconciliation lives in the constructor, so a shortfall cannot be built at all."""
    with pytest.raises(ValueError, match="unexplained dropped event"):
        _census(total=4, classified=2, quarantined=0, undecodable=1)


def test_the_census_counts_an_undecodable_transaction_inside_the_total():
    """2 classified + 0 quarantined + 1 undecodable = 3, and 3 is what ``total`` must be."""
    census = _census(total=3, classified=2, quarantined=0, undecodable=1)
    assert (census.total, census.undecodable) == (3, 1)
    # The same three terms with the transaction dropped from the total is the old defect, exactly.
    with pytest.raises(ValueError, match="belongs in `undecodable`, not outside the total"):
        _census(total=2, classified=2, quarantined=0, undecodable=1)


def test_a_transaction_accounted_for_nowhere_refuses_the_run():
    """The guard compares the accounting against the *argument*, which no stage can redefine.

    Constructed shortfall: three transactions handed in, two netted, nothing else. This is the
    shape the tracer bullet found — every other invariant in the result holds, because they all
    reconcile against a total the run computed after the loss.
    """
    handed_in = [a_buy("0x1", 1), a_sell("0x2", 2), an_undecodable("0x3", 3)]
    with pytest.raises(ValueError) as refusal:
        _require_the_population_is_conserved(
            handed_in,
            [_Row("0x1"), _Row("0x2")],
            QuarantineQueue(records=()),
            _census(total=3, classified=2, undecodable=1),
        )
    assert "handed 3 transaction(s) and accounts for 2" in str(refusal.value)
    assert "Unaccounted for: 0x3" in str(refusal.value)


def test_a_transaction_accounted_for_twice_refuses_the_run():
    """A double count is as wrong as a drop, and a set comparison would miss it.

    The lists are compared with repeats, so a transaction that produced a netting result *and* an
    ingestion record — a row that was somehow both read and not read — fails here.
    """
    handed_in = [a_buy("0x1", 1), a_sell("0x2", 2)]
    queue = QuarantineQueue(records=(
        QuarantineRecord(stage=Stage.INGESTION, reason="unknown event", tx_hashes=("0x1",)),
    ))
    with pytest.raises(ValueError) as refusal:
        _require_the_population_is_conserved(
            handed_in, [_Row("0x1"), _Row("0x2")], queue, _census(total=2),
        )
    assert "handed 2 transaction(s) and accounts for 3" in str(refusal.value)
    assert "Accounted for but never handed in: 0x1" in str(refusal.value)


def test_a_census_totalling_a_different_population_refuses_the_run():
    """Both halves are checked: the lists may agree while ``total`` describes something else."""
    handed_in = [a_buy("0x1", 1), a_sell("0x2", 2)]
    with pytest.raises(ValueError, match="worse, the census totals 3"):
        _require_the_population_is_conserved(
            handed_in, [_Row("0x1"), _Row("0x2")], QuarantineQueue(records=()),
            _census(total=3, classified=2, undecodable=1),
        )


def test_the_conservation_check_passes_on_the_three_legitimate_doors():
    """Netted, netting-quarantined, ingestion-quarantined — and a FIFO record counted by none.

    The FIFO and MARKING records name transactions that already have a netting result. Counting
    them would report ``0x1`` twice and refuse a perfectly conserved run, so they are deliberately
    not counted; this pins that they are not.
    """
    handed_in = [a_buy("0x1", 1), a_sell("0x2", 2), an_undecodable("0x3", 3)]
    queue = QuarantineQueue(records=(
        QuarantineRecord(stage=Stage.INGESTION, reason="unknown event", tx_hashes=("0x3",)),
        QuarantineRecord(stage=Stage.FIFO, reason="unmatched book", tx_hashes=("0x1", "0x2")),
    ))
    _require_the_population_is_conserved(
        handed_in, [_Row("0x1"), _Row("0x2")], queue,
        _census(total=3, classified=2, undecodable=1),
    )


# -- counted is not enough: the result refuses an unnamed shortfall --------------


def _result(census, stages, quarantine):
    return WalletWindowResult(
        window=3, stages_run=STAGE_ORDER, stages=stages, census=census,
        attribution=run([a_buy("0x1", 1)]).attribution,
        coverage=run([a_buy("0x1", 1)]).coverage,
        wallets=(), quarantine=quarantine, excluded=(), results=(),
    )


def _stages(transactions_in, undecodable):
    decodable = transactions_in - undecodable
    return StageCounts(
        transactions_in=transactions_in, transactions_undecodable=undecodable,
        attributions_resolved=decodable, attributions_usable=decodable,
        attributions_excluded=0, netted=decodable, netting_quarantined=0,
        buys=0, sells=0, fifo_books=0, fifo_books_quarantined=0, consumptions=0,
        open_positions_marked=0, buys_scored=0, buys_quarantined=0, buys_outside_window=0,
        buys_unscored=0, sells_quarantined=0, wallets_seen=0, wallets_scored=0,
        wallets_unscorable=0,
    )


def test_a_result_that_counts_an_undecodable_transaction_without_naming_it_is_refused():
    """A count says something was lost. Only the record says which topic to go and classify."""
    census = _census(total=3, classified=2, undecodable=1)
    with pytest.raises(ValueError, match="1 transaction\\(s\\) could not be decoded and 0 are"):
        _result(census, _stages(3, 1), QuarantineQueue(records=()))


def test_a_result_whose_two_undecodable_counts_disagree_is_refused():
    """Two answers to one question publishes whichever the reader happens to look at."""
    census = _census(total=3, classified=2, undecodable=1)
    queue = QuarantineQueue(records=(
        QuarantineRecord(stage=Stage.INGESTION, reason="unknown event", tx_hashes=("0x3",)),
    ))
    with pytest.raises(ValueError, match="census reports 1 undecodable"):
        _result(census, _stages(3, 0), queue)


def test_the_stage_counts_refuse_an_attribution_count_that_ignores_the_undecodable_rows():
    """``transactions_in`` means handed in, and the §4 invariants make room for that.

    Two decodable rows and one undecodable: attribution resolves two, not three. A ``StageCounts``
    that still demanded ``resolved == transactions_in`` would force the caller to shrink
    ``transactions_in``, which is how the population was lost in the first place.
    """
    _stages(3, 1)  # the honest shape constructs
    with pytest.raises(ValueError, match="resolved \\+ 1 undecodable against 3 handed in"):
        StageCounts(
            transactions_in=3, transactions_undecodable=1, attributions_resolved=3,
            attributions_usable=3, attributions_excluded=0, netted=3, netting_quarantined=0,
            buys=0, sells=0, fifo_books=0, fifo_books_quarantined=0, consumptions=0,
            open_positions_marked=0, buys_scored=0, buys_quarantined=0, buys_outside_window=0,
            buys_unscored=0, sells_quarantined=0, wallets_seen=0, wallets_scored=0,
            wallets_unscorable=0,
        )
