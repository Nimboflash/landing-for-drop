"""What the decoder refuses, and why each refusal is not pedantry.

Every case here is a log that a lenient decoder would read as a number. That is the point: none of
these produce an error downstream, they produce a *plausible* number, which is the failure mode
this repository exists to prevent.
"""

from contextlib import contextmanager
from dataclasses import replace

import pytest

from contracts import WETH
from ingest import (
    APPROVAL,
    DECLINED,
    DEPOSIT,
    ORDER_FILLED,
    PERMIT2_PERMIT,
    SIGNATURES,
    SWAP_V2,
    SWAP_V3,
    SYNC,
    TOKEN_EXCHANGE,
    TRANSFER,
    TRANSFER_BATCH,
    TRANSFER_SINGLE,
    WITHDRAWAL,
    LogShapeMismatch,
    MalformedLog,
    NativeUnwrap,
    NativeWrap,
    NoValueEvent,
    TokenTransfer,
    UnknownEvent,
    decode_log,
    decode_logs,
    signature_for,
)

from .conftest import ROUTER, WALLET, address_word, log, word

TOKEN = "0x97e6e31afb2d93d437301e006d9da714616766a5"


def transfer_log(index=0, address=TOKEN, amount=7, topics=None, data=None):
    return log(
        topics if topics is not None else [
            TRANSFER, address_word(WALLET), address_word(ROUTER)
        ],
        data=word(amount) if data is None else data,
        address=address,
        index=index,
    )


# -- the registry itself ---------------------------------------------------------


def test_the_registry_is_the_short_explicit_list_it_claims_to_be():
    """Ten signatures, three of which move value. Pinned so growth is a deliberate act.

    A decoder's registry is the one place where "just add it" is always locally reasonable and
    globally the thing that lets a silent skip in. Changing this assertion is the cost of adding
    one.

    It used to read six, then nine, and every entry added since has been a *non*-mover: 1inch's
    ``OrderFilled``, Uniswap v3's ``Swap``, Curve's ``TokenExchange`` and now Permit2's ``Permit``.
    The first three restate ERC-20 Transfers already in the same receipt; the fourth restates
    nothing at all, exactly as ERC-20 ``Approval`` restates nothing — an allowance is permission to
    move tokens later. **The count of movers has never moved**, and that is the shape of a safe
    widening: an entry claiming to move value would have to name an asset and an amount, and every
    such claim here is still one of the original three.

    ``Permit`` was added because refusing it was not a smaller number, it was a wrong one. 43 of
    the 548 transactions on ``tools/case_runs.py``'s four real wallets carried that topic and
    nothing else unreadable — 7.8% of the population refused end to end for an allowance grant,
    because Permit2 sits between a wallet and a router and so appears in ordinary swap receipts.
    """
    assert set(SIGNATURES) == {
        TRANSFER, WITHDRAWAL, DEPOSIT, SYNC, SWAP_V2, APPROVAL,
        ORDER_FILLED, SWAP_V3, TOKEN_EXCHANGE, PERMIT2_PERMIT,
    }
    assert sorted(s.name for s in SIGNATURES.values() if s.moves_value) == [
        "Deposit", "Transfer", "Withdrawal",
    ]
    assert sorted(s.name for s in SIGNATURES.values() if not s.moves_value) == [
        "Approval", "OrderFilled", "Permit", "Swap", "Swap", "Sync", "TokenExchange",
    ]
    assert all(s.restates for s in SIGNATURES.values() if not s.moves_value), (
        "a signature admitted as moving no value must say what it restates; without that the "
        "entry is a skip with a comment"
    )
    assert {s.name: s.only_on for s in SIGNATURES.values() if s.only_on} == {
        "Withdrawal": WETH, "Deposit": WETH,
    }


def test_the_two_swap_entries_are_two_events_that_share_only_a_name():
    """``SWAP_V2`` and ``SWAP_V3`` are both called ``Swap`` and are not the same event.

    Pinned because the registry is keyed by topic and a reader scanning it by ``name`` would see
    the second entry as a duplicate of the first. The v2 pair emits four ``uint256`` amounts; the
    v3 pool emits two *signed* ``int256`` ones. Collapsing them would attach v2's shape to v3's
    logs, and the shape check would then reject every real v3 ``Swap`` in the chain's history.
    """
    v2, v3 = SIGNATURES[SWAP_V2], SIGNATURES[SWAP_V3]

    assert v2.name == v3.name == "Swap"
    assert v2.topic != v3.topic
    assert v2.text == "Swap(address,uint256,uint256,uint256,uint256,address)"
    assert v3.text == "Swap(address,address,int256,int256,uint160,uint128,int24)"
    assert (v2.topics, v2.data_words) == (3, 4)
    assert (v3.topics, v3.data_words) == (3, 5)


def test_every_entry_states_a_shape_and_it_is_at_least_one_topic():
    """``topics`` counts ``topics[0]`` too, so no entry may claim zero.

    A signature with ``topics=0`` would be enforced against a log that names no event at all, which
    :func:`ingest.events._topics` refuses earlier — the check would read as satisfied and mean
    nothing.
    """
    for signature in SIGNATURES.values():
        assert signature.topics >= 1, signature.name
        assert signature.data_words >= 0, signature.name


def test_each_topic_is_keyed_by_itself():
    for topic, signature in SIGNATURES.items():
        assert signature.topic == topic
        assert len(topic) == 66 and topic.startswith("0x")


def test_moves_value_is_a_claim_the_module_has_to_honour_in_both_directions():
    """``moves_value`` used to be read by nothing at all, and this is what changed that.

    :func:`ingest.events.decode_log` branches on ``topic``, not on ``moves_value``, so before
    :func:`ingest.events._require_the_registry_agrees_with_this_module` existed an entry could
    declare anything and the decoder would carry on regardless. That is not a cosmetic gap: the
    field is the whole classification, and a declaration nothing enforces drifts in both directions.
    Both are constructed here.

    Not a ``LogRefused``, and that is asserted rather than assumed. A registry defect wearing that
    type would be turned into a carried status by :mod:`pipeline.chain` and published as "the chain
    contained something we could not read" — a defect in this repository counted as a limitation of
    Ethereum.
    """
    from ingest.events import (
        MOVEMENT_DECODERS,
        LogRefused,
        RegistryInconsistent,
        _require_the_registry_agrees_with_this_module,
    )

    assert not issubclass(RegistryInconsistent, LogRefused)
    assert MOVEMENT_DECODERS == {TRANSFER, WITHDRAWAL, DEPOSIT}

    # a declared mover with no branch: its leg would be reported as an acknowledgement
    liar = dict(SIGNATURES)
    liar[SYNC] = replace(SIGNATURES[SYNC], moves_value=True)
    with _registry(liar):
        with pytest.raises(RegistryInconsistent, match="decoded as an acknowledgement"):
            _require_the_registry_agrees_with_this_module()

    # a branch with no declaration: the movement is emitted and the entry says it is a restatement
    liar = dict(SIGNATURES)
    liar[TRANSFER] = replace(SIGNATURES[TRANSFER], moves_value=False, restates="nothing at all")
    with _registry(liar):
        with pytest.raises(RegistryInconsistent, match="counting the hop twice"):
            _require_the_registry_agrees_with_this_module()


def test_a_non_mover_with_no_written_reason_is_refused_at_import():
    """"It looked harmless" is not a classification, and now it is not expressible either."""
    from ingest.events import RegistryInconsistent, _require_the_registry_agrees_with_this_module

    liar = dict(SIGNATURES)
    liar[SWAP_V3] = replace(SIGNATURES[SWAP_V3], restates="")
    with _registry(liar):
        with pytest.raises(RegistryInconsistent, match="do not say what they restate"):
            _require_the_registry_agrees_with_this_module()


@contextmanager
def _registry(entries):
    """Swap :data:`SIGNATURES` in place for the body, and always put it back.

    The check reads the module global rather than taking an argument, because it runs at import
    where there is nothing to pass it. So a test that constructs a lying registry has to install
    one, and has to restore it even when the assertion fails — a leaked registry would make every
    later test in the process assert against a fiction.
    """
    import ingest.events as module

    original = module.SIGNATURES
    module.SIGNATURES = entries
    try:
        yield
    finally:
        module.SIGNATURES = original


def test_a_declined_topic_is_not_in_the_registry_and_says_why():
    """:data:`DECLINED` is a record of a decision, and it must not be a second registry.

    The one thing that would make it dangerous is an entry appearing in both: ``SIGNATURES`` would
    win, and the written reason for refusing the event would sit there being read by nobody while
    the event was decoded anyway.
    """
    assert set(DECLINED) & set(SIGNATURES) == set()
    assert set(DECLINED) == {TRANSFER_SINGLE, TRANSFER_BATCH}
    for topic, declined in DECLINED.items():
        assert declined.topic == topic
        assert declined.reason, declined.name


# -- what decodes ----------------------------------------------------------------


def test_a_transfer_decodes_to_its_three_fields():
    assert decode_log(transfer_log(index=3, amount=12345)) == TokenTransfer(
        token=TOKEN, from_addr=WALLET, to_addr=ROUTER, raw_amount=12345, log_index=3
    )


def test_a_withdrawal_and_a_deposit_decode_on_weth():
    unwrap = log([WITHDRAWAL, address_word(ROUTER)], data=word(99), address=WETH, index=5)
    wrap = log([DEPOSIT, address_word(ROUTER)], data=word(99), address=WETH, index=6)

    assert decode_log(unwrap) == NativeUnwrap(holder=ROUTER, raw_amount=99, log_index=5)
    assert decode_log(wrap) == NativeWrap(holder=ROUTER, raw_amount=99, log_index=6)


def test_a_recognised_non_movement_comes_back_as_an_acknowledgement():
    """``Sync`` is returned, not dropped. There is no code path that returns nothing."""
    decoded = decode_log(log([SYNC], data=word(1) + format(2, "064x"), address=ROUTER, index=9))

    assert decoded == NoValueEvent(name="Sync", topic=SYNC, address=ROUTER, log_index=9)


def test_topics_are_matched_case_insensitively():
    """A vendor upper-casing a topic must not turn a known event into an unknown one."""
    shouted = "0x" + TRANSFER[2:].upper()
    upper = transfer_log(topics=[shouted, address_word(WALLET), address_word(ROUTER)])

    assert decode_log(upper).raw_amount == 7


# -- unknown events --------------------------------------------------------------


def test_an_unlisted_signature_is_refused_rather_than_ignored():
    unlisted = log(["0x" + "ab" * 32], address=TOKEN, index=4)

    with pytest.raises(UnknownEvent) as refusal:
        decode_log(unlisted)

    message = str(refusal.value)
    assert "0x" + "ab" * 32 in message
    assert "log 4" in message and TOKEN in message
    assert "SIGNATURES" in message, "the refusal must say how to admit the event deliberately"


def test_a_withdrawal_on_something_other_than_weth_is_not_an_unwrap():
    """A topic is the hash of a name, and any contract may emit any hash.

    Decoding this as native ETH would credit an address with money that never moved — and the
    credit would net against a real sale to produce a trade nobody made.
    """
    impostor = log([WITHDRAWAL, address_word(WALLET)], data=word(10 ** 18), address=TOKEN, index=2)

    with pytest.raises(UnknownEvent) as refusal:
        decode_log(impostor)

    assert WETH in str(refusal.value) and TOKEN in str(refusal.value)


def test_signature_for_is_the_same_gate_as_decode_log():
    assert signature_for(transfer_log()).name == "Transfer"
    with pytest.raises(UnknownEvent):
        signature_for(log(["0x" + "cd" * 32]))


# -- ABI mismatches --------------------------------------------------------------


def test_an_erc721_transfer_is_refused_rather_than_read_as_an_amount():
    """The single most dangerous shape here: four topics, same signature hash.

    Read positionally, the third indexed parameter — a token id — arrives as ``raw_amount``. It is
    an integer, in raw units, and entirely fictional as a quantity.
    """
    nft = log(
        [TRANSFER, address_word(WALLET), address_word(ROUTER), word(4211)],
        data="0x", address=TOKEN, index=1,
    )

    with pytest.raises(LogShapeMismatch) as refusal:
        decode_log(nft)

    assert "ERC-721" in str(refusal.value) and "token id" in str(refusal.value)


def test_a_transfer_with_unindexed_parties_is_refused():
    """Some non-standard tokens emit all three parameters in ``data``. That is a different ABI."""
    flat = log([TRANSFER], data=word(1) + format(2, "064x") + format(3, "064x"), address=TOKEN)

    with pytest.raises(LogShapeMismatch):
        decode_log(flat)


def test_a_data_word_of_the_wrong_width_is_refused():
    with pytest.raises(LogShapeMismatch) as refusal:
        decode_log(transfer_log(data="0x2a"))

    assert "64 hex digits" in str(refusal.value)


def test_a_non_mover_whose_data_is_the_wrong_width_is_refused_too():
    """The shape check covers the events whose words are never read. That is the harder half.

    A v3 ``Swap`` decodes to a :class:`NoValueEvent` and nothing in this module ever looks at its
    five data words — so a lenient decoder has no reason to check them, and would answer "no value
    moved" about a log carrying three. But the whole output of decoding a non-mover *is* the
    sentence "no value moved here", and a log that does not have v3's shape is not a v3 ``Swap``:
    the sentence would be true of some other event and asserted about this receipt.
    """
    stunted = log(
        [SWAP_V3, address_word(WALLET), address_word(ROUTER)],
        data="0x" + "0" * 64 * 3, address=ROUTER, index=4,
    )

    with pytest.raises(LogShapeMismatch) as refusal:
        decode_log(stunted)

    assert "5 ABI word(s)" in str(refusal.value)
    assert "192 digit(s)" in str(refusal.value)


def test_a_non_mover_whose_topic_count_is_wrong_is_refused_too():
    """Same argument, one field over. Curve's ``TokenExchange`` indexes exactly one parameter."""
    wrong = log([TOKEN_EXCHANGE], data="0x" + "0" * 64 * 4, address=ROUTER, index=8)

    with pytest.raises(LogShapeMismatch) as refusal:
        decode_log(wrong)

    assert "TokenExchange" in str(refusal.value)
    assert "the log has 1" in str(refusal.value)


def test_a_declined_event_is_refused_and_the_refusal_says_it_was_a_decision():
    """An ERC-1155 topic earns :class:`UnknownEvent`, and a message that is not "never seen this".

    The exception type has to be the same one an unheard-of topic earns, because that is what
    :mod:`pipeline.chain` turns into a counted row. Only the message differs — and it has to,
    because the reader's next move is different: there is nothing to classify here, the asset this
    event moves simply cannot be named in a ``contracts.Transfer``.
    """
    single = log(
        [TRANSFER_SINGLE, address_word(ROUTER), address_word(WALLET), address_word(ROUTER)],
        data=word(4211) + format(1, "064x"), address=TOKEN, index=2,
    )

    with pytest.raises(UnknownEvent) as refusal:
        decode_log(single)

    message = str(refusal.value)
    assert "deliberately does not admit" in message
    assert "(contract, id)" in message
    assert refusal.value.topic == TRANSFER_SINGLE
    assert refusal.value.address == TOKEN and refusal.value.log_index == 2


def test_an_address_word_with_a_non_zero_prefix_is_refused():
    """Truncating it would yield a well-formed address owned by nobody."""
    dirty = "0x" + "1" * 24 + WALLET[2:]

    with pytest.raises(LogShapeMismatch) as refusal:
        decode_log(transfer_log(topics=[TRANSFER, dirty, address_word(ROUTER)]))

    assert "owned by nobody" in str(refusal.value)


# -- malformed logs --------------------------------------------------------------


@pytest.mark.parametrize("missing", ["address", "topics", "data", "logIndex"])
def test_a_log_missing_a_member_is_refused_by_name(missing):
    entry = transfer_log()
    del entry[missing]

    with pytest.raises(MalformedLog) as refusal:
        decode_log(entry)

    assert missing in str(refusal.value)


def test_an_empty_topics_list_names_no_event():
    with pytest.raises(MalformedLog):
        decode_log(log([], address=TOKEN))


def test_a_non_hex_member_is_refused():
    with pytest.raises(MalformedLog):
        decode_log(transfer_log(data="0xzz" + "0" * 62))


def test_decode_logs_refuses_the_whole_list_on_one_bad_log():
    """Partial success is the shape that loses a leg. There is no 'decoded 7 of 8'."""
    logs = [transfer_log(index=0), log(["0x" + "ef" * 32], index=1)]

    with pytest.raises(UnknownEvent):
        decode_logs(logs)


def test_decode_logs_refuses_something_that_is_not_a_list():
    with pytest.raises(MalformedLog):
        decode_logs({"logs": []})
