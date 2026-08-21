"""Attribution invariants, over generated transactions.

The hand-computed layer proves the resolver is right about the shapes we thought of. This layer
proves it cannot be wrong in a particular direction about the shapes we did not: for *every*
generated context and transfer set, infrastructure never becomes an owner, an unflagged owner is
never the transaction sender, and UNRESOLVED never carries one.

The generators deliberately produce contradictory evidence — a Safe that is also a smart account, a
user operation whose sender is the bundler, transfers that touch nobody. None of those may raise:
an unattributable transaction is a finding, not a crash.
"""

from decimal import Decimal

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from attribution import (
    AttributionContext,
    SafeExecution,
    UserOperation,
    attribution_coverage,
    attribution_fallback_rate,
    resolve_attribution,
)
from attribution.context import NULL_ADDRESS
from contracts import (
    USDC,
    WETH,
    AccountType,
    Attribution,
    AttributionMethod,
    Transfer,
    to_canonical_json,
)

ADDRESSES = tuple("0x" + format(i, "040x") for i in range(1, 11))
TOKENS = (WETH, USDC, "0x" + "cc" * 20)

ROLES = ("infrastructure", "safes", "smart_accounts", "contract_accounts", "eoas", "unknown")

#: EOAs are over-weighted to match reality and to keep the DIRECT_EOA branch reachable; a uniform
#: draw leaves it at roughly one example in a hundred, which is not a test.
ROLE_DRAW = ROLES + ("eoas", "eoas", "eoas")

RESOLVED_METHODS = (
    AttributionMethod.DIRECT_EOA,
    AttributionMethod.SAFE_EXECUTION,
    AttributionMethod.ERC4337_SENDER,
    AttributionMethod.ROUTER_RECIPIENT,
)


@st.composite
def scenarios(draw):
    """A context whose address sets are disjoint by construction, plus a transaction."""
    assignments = draw(
        st.lists(st.sampled_from(ROLE_DRAW), min_size=len(ADDRESSES), max_size=len(ADDRESSES))
    )
    sets = dict((role, set()) for role in ROLES)
    for address, role in zip(ADDRESSES, assignments):
        sets[role].add(address)

    # Smart-account evidence short-circuits the transfer-based methods, so the three kinds are
    # drawn evenly. Without this, "plain" scenarios are rare and the DIRECT_EOA and
    # ROUTER_RECIPIENT branches are never reached.
    kind = draw(st.sampled_from(("plain", "safe", "erc4337")))

    # The null address is drawn into the Safe and user-operation sender fields on purpose. It is
    # filtered out of the transfer-derived endpoint set, so the event lane is the only way it can
    # reach ``portfolio_owner`` — and a generator that never puts it there leaves
    # ``test_infrastructure_is_never_an_owner``'s NULL_ADDRESS assertion unreachable and therefore
    # not a test at all.
    IDENTITIES = ADDRESSES + (NULL_ADDRESS,)

    safe_execution = None
    if kind == "safe":
        safe = draw(st.sampled_from(IDENTITIES))
        signers = draw(st.lists(st.sampled_from(ADDRESSES), max_size=3, unique=True))
        safe_execution = SafeExecution(
            safe=safe, signers=tuple(s for s in signers if s != safe)
        )

    operations = ()
    if kind != "plain":
        operations = tuple(
            UserOperation(
                sender=draw(st.sampled_from(IDENTITIES)),
                bundler=draw(st.one_of(st.none(), st.sampled_from(ADDRESSES))),
                paymaster=draw(st.one_of(st.none(), st.sampled_from(ADDRESSES))),
            )
            for _ in range(draw(st.integers(min_value=0 if kind == "safe" else 1, max_value=2)))
        )

    # Half the scenarios carry a real swap shape — two legs between one address and a venue —
    # because purely random transfers almost never produce the single two-sided counterparty that
    # DIRECT_EOA and ROUTER_RECIPIENT resolve on, and a property that never reaches its branch
    # proves nothing.
    transfer_specs = []
    if draw(st.booleans()):
        trader = draw(st.sampled_from(ADDRESSES))
        venue = draw(st.sampled_from(ADDRESSES))
        transfer_specs.append((TOKENS[1], trader, venue, 1000 * 10 ** 6, False))
        transfer_specs.append((TOKENS[0], venue, trader, 5 * 10 ** 17, False))
        if draw(st.booleans()):
            transfer_specs.append(
                (TOKENS[0], venue, draw(st.sampled_from(ADDRESSES)), 10 ** 15, True)
            )

    transfer_specs.extend(
        draw(
            st.lists(
                st.tuples(
                    st.sampled_from(TOKENS),
                    st.sampled_from(ADDRESSES + (NULL_ADDRESS,)),
                    st.sampled_from(ADDRESSES + (NULL_ADDRESS,)),
                    st.integers(min_value=0, max_value=10 ** 24),
                    st.booleans(),
                ),
                max_size=4,
            )
        )
    )
    transfers = tuple(
        Transfer(
            token=token, from_addr=sender, to_addr=recipient,
            raw_amount=amount, log_index=index, is_fee=is_fee,
        )
        for index, (token, sender, recipient, amount, is_fee) in enumerate(transfer_specs)
    )

    context = AttributionContext(
        infrastructure=frozenset(sets["infrastructure"]),
        safes=frozenset(sets["safes"]),
        smart_accounts=frozenset(sets["smart_accounts"]),
        contract_accounts=frozenset(sets["contract_accounts"]),
        eoas=frozenset(sets["eoas"]),
        safe_execution=safe_execution,
        user_operations=operations,
        permit_tx_sender_fallback=draw(st.booleans()),
    )
    tx_hash = "0x" + format(draw(st.integers(min_value=1, max_value=2 ** 32)), "064x")

    # The sender is often, but not always, one of the addresses that moved value — the two cases
    # are DIRECT_EOA and "someone else paid the gas", and both need to occur.
    participants = sorted(
        set(a for t in transfers for a in (t.from_addr, t.to_addr)) & set(ADDRESSES)
    )
    if participants and draw(st.booleans()):
        tx_sender = draw(st.sampled_from(participants))
    else:
        tx_sender = draw(st.sampled_from(ADDRESSES))
    return tx_hash, tx_sender, transfers, context


SETTINGS = settings(
    max_examples=250,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


@given(scenarios())
@SETTINGS
def test_always_returns_a_typed_attribution(scenario):
    """An unattributable transaction is a finding, never an exception."""
    tx_hash, sender, transfers, context = scenario
    result = resolve_attribution(tx_hash, sender, transfers, context)

    assert isinstance(result, Attribution)
    assert result.tx_sender == sender
    assert result.tx_hash == tx_hash
    assert result.evidence
    assert Decimal("0") <= result.confidence <= Decimal("1")


@given(scenarios())
@SETTINGS
def test_unresolved_never_carries_an_owner(scenario):
    result = resolve_attribution(*scenario)
    if result.method is AttributionMethod.UNRESOLVED:
        assert result.portfolio_owner is None
        assert result.account_type is AccountType.UNKNOWN
        assert result.confidence == Decimal("0")
        assert result.is_usable_for_primary_metric is False


@given(scenarios())
@SETTINGS
def test_fallback_unknown_and_infrastructure_are_never_usable(scenario):
    """The property the whole module exists to guarantee."""
    result = resolve_attribution(*scenario)
    if (
        result.is_fallback
        or result.account_type in (AccountType.UNKNOWN, AccountType.INFRASTRUCTURE)
        or result.portfolio_owner is None
    ):
        assert result.is_usable_for_primary_metric is False
    if result.is_usable_for_primary_metric:
        assert result.method in RESOLVED_METHODS
        assert result.portfolio_owner is not None


@given(scenarios())
@SETTINGS
def test_infrastructure_is_never_an_owner(scenario):
    _tx, _sender, _transfers, context = scenario
    result = resolve_attribution(*scenario)
    if result.portfolio_owner is not None:
        assert result.portfolio_owner not in context.infrastructure
        assert result.account_type is not AccountType.INFRASTRUCTURE
        assert result.portfolio_owner != NULL_ADDRESS


@given(scenarios())
@SETTINGS
def test_the_sender_becomes_the_owner_only_when_flagged_or_directly_evidenced(scenario):
    """``coalesce(taker, tx_from)``, closed off for every generated input.

    An owner equal to the sender is permitted only when it was named by something other than the
    sender field: the endpoint set, an ExecutionSuccess, a UserOperationEvent — or when it is a
    flagged fallback. The inferred method may never land there at all.
    """
    _tx, sender, _transfers, context = scenario
    result = resolve_attribution(*scenario)
    if result.portfolio_owner != sender:
        return

    assert result.method is not AttributionMethod.ROUTER_RECIPIENT
    if result.method is AttributionMethod.DIRECT_EOA:
        assert context.account_type(sender) is AccountType.EOA
    elif result.method is AttributionMethod.SAFE_EXECUTION:
        assert context.safe_execution is not None
        assert context.safe_execution.safe == sender
    elif result.method is AttributionMethod.ERC4337_SENDER:
        assert sender in set(op.sender for op in context.user_operations)
    else:
        assert result.method is AttributionMethod.TX_SENDER_FALLBACK
        assert result.is_fallback is True


#: An address the context types as one of these is a portfolio in its own right. Written out
#: rather than imported from the resolver: a test that moves with the constant it is checking
#: tests nothing.
PORTFOLIO_TYPES = (AccountType.EOA, AccountType.SAFE, AccountType.ERC4337)


def two_sided_addresses(transfers, context):
    """The two-sided non-infrastructure set, rebuilt with plain set algebra.

    Deliberately not a call into the module's own endpoint code: these properties assert the
    *rule*, not the implementation's arithmetic for finding candidates.
    """
    sent, received = set(), set()
    for transfer in transfers:
        if transfer.is_fee or transfer.raw_amount <= 0:
            continue
        if transfer.from_addr == transfer.to_addr:
            continue
        sent.add(transfer.from_addr)
        received.add(transfer.to_addr)
    return set(
        a for a in sent & received
        if a and a != NULL_ADDRESS and not context.is_infrastructure(a)
    )


def evidenced_owners(transfers, context):
    """Every distinct portfolio the transaction carries evidence for.

    Two kinds, counted the same: an address that is two-sided *and* typed as a portfolio identity,
    and an address a Safe or 4337 event names outright.
    """
    owners = set(
        a for a in two_sided_addresses(transfers, context)
        if context.account_type(a) in PORTFOLIO_TYPES
    )
    if context.safe_execution is not None:
        owners.add(context.safe_execution.safe)
    owners |= set(op.sender for op in context.user_operations)
    return set(
        a for a in owners
        if a and a != NULL_ADDRESS and not context.is_infrastructure(a)
    )


@given(scenarios())
@SETTINGS
def test_several_owners_are_never_collapsed_onto_one(scenario):
    """A transaction carrying evidence for more than one portfolio has no single owner to report.

    Deliberately blind to *how* the transaction was settled. An ``Attribution`` has one owner slot,
    so naming one of several owners erases the rest, and letting the settlement mechanism break the
    tie is ``coalesce(taker, tx_from)`` reintroduced as a tie-break: a Safe or a bundler names an
    account, which is not a statement that the transaction has only one. There is no ``assume``
    here on purpose — the Safe and ERC-4337 scenarios are exactly the ones the check used to run
    behind.
    """
    _tx, _sender, transfers, context = scenario
    result = resolve_attribution(*scenario)
    owners = evidenced_owners(transfers, context)

    if len(owners) > 1:
        assert result.method is AttributionMethod.UNRESOLVED
        assert result.portfolio_owner is None
        for address in owners:
            assert address in " ".join(result.evidence)


@given(scenarios())
@SETTINGS
def test_an_undistinguished_plurality_on_the_transfer_lane_is_refused(scenario):
    """With no event, two-sidedness is the whole of the evidence.

    So several two-sided addresses and no single portfolio among them is a transaction the resolver
    has nothing to rank with, and it refuses rather than picking. Exactly one portfolio among them
    is the unlabelled-venue case, which resolves — that is the other property below.
    """
    _tx, _sender, transfers, context = scenario
    assume(context.safe_execution is None and not context.user_operations)
    result = resolve_attribution(*scenario)

    candidates = two_sided_addresses(transfers, context)
    typed = set(a for a in candidates if context.account_type(a) in PORTFOLIO_TYPES)

    if len(candidates) > 1 and len(typed) != 1:
        assert result.method is AttributionMethod.UNRESOLVED
        assert result.portfolio_owner is None
        for address in candidates:
            assert address in " ".join(result.evidence)


@given(scenarios())
@SETTINGS
def test_an_owner_is_never_read_off_an_address_the_context_cannot_type(scenario):
    """The owner comes from the evidence, and an untyped venue is not evidence.

    Where a transaction has exactly one portfolio and any number of unidentified two-sided
    addresses, the portfolio is the owner — that is the unlabelled-venue case, and refusing it
    would make the §8 population a function of label coverage. The unidentified addresses are still
    named in the record.
    """
    _tx, _sender, transfers, context = scenario
    assume(context.safe_execution is None and not context.user_operations)
    result = resolve_attribution(*scenario)

    candidates = two_sided_addresses(transfers, context)
    typed = set(a for a in candidates if context.account_type(a) in PORTFOLIO_TYPES)

    if len(candidates) > 1 and len(typed) == 1 and result.portfolio_owner is not None:
        assert result.portfolio_owner in typed
        for address in candidates - typed:
            assert address in " ".join(result.evidence)


@given(scenarios())
@SETTINGS
def test_a_fallback_requires_an_explicit_permission_and_a_non_infrastructure_eoa(scenario):
    _tx, sender, _transfers, context = scenario
    result = resolve_attribution(*scenario)
    if result.is_fallback:
        assert context.permit_tx_sender_fallback is True
        assert context.account_type(sender) is AccountType.EOA
        assert sender not in context.infrastructure


@given(scenarios())
@SETTINGS
def test_safe_evidence_never_attributes_to_a_signer(scenario):
    _tx, _sender, _transfers, context = scenario
    result = resolve_attribution(*scenario)
    execution = context.safe_execution
    if execution is not None and result.method is AttributionMethod.SAFE_EXECUTION:
        assert result.portfolio_owner == execution.safe
        assert result.portfolio_owner not in execution.signers
        assert result.account_type is AccountType.SAFE


@given(scenarios())
@SETTINGS
def test_erc4337_never_attributes_to_a_bundler_or_paymaster(scenario):
    _tx, _sender, _transfers, context = scenario
    result = resolve_attribution(*scenario)
    if result.method is AttributionMethod.ERC4337_SENDER:
        senders = set(op.sender for op in context.user_operations)
        roles = set(
            role for op in context.user_operations for role in op.infrastructure_roles
        )
        assert result.portfolio_owner in senders
        assert result.portfolio_owner not in roles
        assert result.account_type is AccountType.ERC4337


@given(scenarios())
@SETTINGS
def test_resolution_is_deterministic(scenario):
    """No clock, no randomness, no global state: identical inputs, identical record."""
    first = resolve_attribution(*scenario)
    second = resolve_attribution(*scenario)
    assert first == second
    assert to_canonical_json(first) == to_canonical_json(second)


@given(scenarios())
@SETTINGS
def test_every_output_survives_canonical_json(scenario):
    """A float leaking in through any path raises here."""
    result = resolve_attribution(*scenario)
    payload = to_canonical_json(result)
    assert '"tx_sender":' in payload
    assert "NaN" not in payload


@given(st.lists(scenarios(), max_size=8))
@SETTINGS
def test_coverage_accounts_for_every_transaction(scenarios_list):
    results = [resolve_attribution(*scenario) for scenario in scenarios_list]
    coverage = attribution_coverage(results)

    assert coverage.total == len(results)
    assert coverage.resolved + coverage.fallback + coverage.unresolved == coverage.total
    assert sum(coverage.by_method.values()) == coverage.total
    assert sum(coverage.by_account_type.values()) == coverage.total
    assert coverage.usable_for_primary_metric <= coverage.resolved
    assert coverage.fallback_rate == attribution_fallback_rate(results)
    if results:
        for rate in (coverage.fallback_rate, coverage.unresolved_rate, coverage.usable_rate):
            assert Decimal("0") <= rate <= Decimal("1")
    else:
        assert coverage.fallback_rate is None
    assert to_canonical_json(coverage)


@given(scenarios())
@SETTINGS
def test_fee_only_and_zero_amount_legs_are_not_evidence(scenario):
    """Adding a fee leg or a zero-amount leg cannot change who the owner is (§4.2)."""
    tx_hash, sender, transfers, context = scenario
    assume(context.safe_execution is None and not context.user_operations)

    baseline = resolve_attribution(tx_hash, sender, transfers, context)
    noise = transfers + (
        Transfer(token=WETH, from_addr=ADDRESSES[0], to_addr=ADDRESSES[1],
                 raw_amount=10 ** 15, log_index=90, is_fee=True),
        Transfer(token=USDC, from_addr=ADDRESSES[2], to_addr=ADDRESSES[3],
                 raw_amount=0, log_index=91),
    )

    assert resolve_attribution(tx_hash, sender, noise, context) == baseline
