"""Multi-step scenarios: a day of mixed traffic, resolved end to end.

The unit layers check one transaction at a time. What ticket 20 actually asks for is a *run*: many
transactions, several account types, a reported fallback rate, and infrastructure that never
appears as a trader however many times it signs a transaction. That is what these check.
"""

from decimal import Decimal

import pytest

from attribution import (
    AttributionContext,
    SafeExecution,
    UserOperation,
    attribution_coverage,
    attribution_fallback_rate,
    require_resolved_attribution,
    resolve_attribution,
)
from contracts import (
    USDC,
    WETH,
    AccountType,
    AttributionMethod,
    AttributionUnresolvedError,
    Transfer,
    artifact_envelope,
    canonical_hash,
    to_canonical_json,
)

# -- a small universe -----------------------------------------------------------

SAFE = "0x" + "5a" * 20
SIGNERS = ("0x" + "51" * 20, "0x" + "52" * 20, "0x" + "53" * 20)
SMART_ACCOUNT = "0x" + "44" * 20

BUNDLER = "0x" + "bd" * 20
PAYMASTER = "0x" + "9a" * 20
RELAYER = "0x" + "7e" * 20
SOLVER = "0x" + "50" * 20
SETTLEMENT = "0x" + "5e" * 20
POOL = "0x" + "0d" * 20

INFRASTRUCTURE = frozenset({BUNDLER, PAYMASTER, RELAYER, SOLVER, SETTLEMENT, POOL})

TRADERS = tuple("0x" + format(0xE0A00 + i, "040x") for i in range(30))
QUIET_EOA = "0x" + "ee" * 20

USDC_1000 = 1000 * 10 ** 6
WETH_HALF = 5 * 10 ** 17


def tx_hash(index):
    return "0x" + format(index, "064x")


def swap_legs(owner, venue, start_index=0):
    return (
        Transfer(token=USDC, from_addr=owner, to_addr=venue,
                 raw_amount=USDC_1000, log_index=start_index),
        Transfer(token=WETH, from_addr=venue, to_addr=owner,
                 raw_amount=WETH_HALF, log_index=start_index + 1),
    )


def base_context(**overrides):
    fields = dict(
        infrastructure=INFRASTRUCTURE,
        safes=frozenset({SAFE}),
        smart_accounts=frozenset({SMART_ACCOUNT}),
        eoas=frozenset(TRADERS + SIGNERS + (QUIET_EOA,)),
    )
    fields.update(overrides)
    return AttributionContext(**fields)


# -- 1. a day of mixed traffic --------------------------------------------------


def resolve_a_days_traffic(infrastructure=INFRASTRUCTURE):
    """Twenty transactions: 8 direct, 3 Safe, 3 ERC-4337, 4 solver-settled, 1 batch, 1 fallback.

    ``infrastructure`` is a parameter so the same day can be replayed against a label set that has
    not caught up with the venues yet — see
    :func:`test_the_usable_population_does_not_move_with_the_venue_label_list`.
    """
    results = []
    index = 0

    def context(**overrides):
        overrides.setdefault("infrastructure", infrastructure)
        return base_context(**overrides)

    for i in range(8):
        index += 1
        trader = TRADERS[i]
        results.append(
            resolve_attribution(
                tx_hash(index), trader, swap_legs(trader, POOL), context()
            )
        )

    for i in range(3):
        index += 1
        # A different signer each time — the portfolio identity must not move with the signer.
        results.append(
            resolve_attribution(
                tx_hash(index), SIGNERS[i], swap_legs(SAFE, POOL),
                context(safe_execution=SafeExecution(safe=SAFE, signers=SIGNERS)),
            )
        )

    for _ in range(3):
        index += 1
        results.append(
            resolve_attribution(
                tx_hash(index), BUNDLER, swap_legs(SMART_ACCOUNT, POOL),
                context(
                    user_operations=(
                        UserOperation(
                            sender=SMART_ACCOUNT, bundler=BUNDLER, paymaster=PAYMASTER
                        ),
                    ),
                ),
            )
        )

    for i in range(4):
        index += 1
        trader = TRADERS[10 + i]
        transfers = swap_legs(trader, SETTLEMENT) + (
            Transfer(token=WETH, from_addr=SETTLEMENT, to_addr=SOLVER,
                     raw_amount=2 * 10 ** 15, log_index=2, is_fee=True),
        )
        results.append(
            resolve_attribution(tx_hash(index), SOLVER, transfers, context())
        )

    index += 1
    batch = swap_legs(TRADERS[20], SETTLEMENT, 0) + swap_legs(TRADERS[21], SETTLEMENT, 2)
    results.append(resolve_attribution(tx_hash(index), SOLVER, batch, context()))

    index += 1
    results.append(
        resolve_attribution(
            tx_hash(index), QUIET_EOA, (), context(permit_tx_sender_fallback=True)
        )
    )

    return results


def test_a_days_traffic_is_fully_accounted_for():
    results = resolve_a_days_traffic()
    coverage = attribution_coverage(results)

    assert coverage.total == 20
    assert coverage.by_method == {
        AttributionMethod.DIRECT_EOA: 8,
        AttributionMethod.SAFE_EXECUTION: 3,
        AttributionMethod.ERC4337_SENDER: 3,
        AttributionMethod.ROUTER_RECIPIENT: 4,
        AttributionMethod.UNRESOLVED: 1,
        AttributionMethod.TX_SENDER_FALLBACK: 1,
    }
    assert coverage.by_account_type == {
        AccountType.EOA: 13,   # 8 direct + 4 solver-settled users + the flagged fallback
        AccountType.SAFE: 3,
        AccountType.ERC4337: 3,
        AccountType.UNKNOWN: 1,
    }

    # 1/20 and 18/20, by hand.
    assert coverage.fallback_rate == Decimal("0.05")
    assert coverage.unresolved_rate == Decimal("0.05")
    assert coverage.usable_rate == Decimal("0.9")
    assert coverage.usable_for_primary_metric == 18
    assert attribution_fallback_rate(results) == coverage.fallback_rate


def test_no_infrastructure_address_is_ever_a_trader_in_a_days_traffic():
    owners = set(r.portfolio_owner for r in resolve_a_days_traffic())
    owners.discard(None)

    assert not owners & INFRASTRUCTURE
    assert not owners & set(SIGNERS)
    assert SAFE in owners and SMART_ACCOUNT in owners


def test_the_days_traffic_serializes_and_hashes_deterministically():
    first = resolve_a_days_traffic()
    second = resolve_a_days_traffic()

    envelope = artifact_envelope("attribution", "attribution.resolve", first)
    assert envelope["payload_hash"] == artifact_envelope(
        "attribution", "attribution.resolve", second
    )["payload_hash"]
    assert canonical_hash(attribution_coverage(first)) == canonical_hash(
        attribution_coverage(second)
    )
    assert to_canonical_json(first)


# -- 2. the phantom mega-wallet ------------------------------------------------


def test_one_solver_settling_for_many_users_does_not_become_a_mega_wallet():
    """The failure this module exists to prevent, at the scale it happens at.

    Twenty-five users, one solver, one signing address. ``coalesce(taker, tx_from)`` would return
    twenty-five trades for the solver and none for the users: one phantom whale in the top of the
    ranking, and twenty-five real wallets missing from the universe.
    """
    results = []
    for i in range(25):
        trader = TRADERS[i % len(TRADERS)]
        transfers = swap_legs(trader, SETTLEMENT) + (
            Transfer(token=WETH, from_addr=SETTLEMENT, to_addr=SOLVER,
                     raw_amount=10 ** 15, log_index=2, is_fee=True),
        )
        results.append(resolve_attribution(tx_hash(i), SOLVER, transfers, base_context()))

    owners = [r.portfolio_owner for r in results]
    naive_coalesce = [r.tx_sender for r in results]

    assert len(set(owners)) == 25
    assert SOLVER not in owners
    assert set(naive_coalesce) == {SOLVER}, "the naive attribution collapses to one address"
    assert all(r.method is AttributionMethod.ROUTER_RECIPIENT for r in results)
    assert all(r.is_usable_for_primary_metric for r in results)
    assert attribution_fallback_rate(results) == Decimal("0")


def test_a_settlement_batch_signed_by_one_of_its_traders_is_refused_whole():
    """The mega-wallet failure's other direction, at the same scale.

    Twenty-five users settled in one transaction, signed by the first of them. There is one owner
    slot and twenty-five owners: naming TRADERS[0] would put twenty-five people's USDC->WETH legs
    on one wallet at confidence 1 and drop the other twenty-four without a quarantine record. The
    solver-signed variant already refused, so before this the same batch got two different answers
    depending only on who paid the gas.
    """
    transfers = ()
    for i in range(25):
        transfers += swap_legs(TRADERS[i], SETTLEMENT, start_index=2 * i)
    context = base_context()

    signed_by_a_trader = resolve_attribution(tx_hash(1), TRADERS[0], transfers, context)
    signed_by_the_solver = resolve_attribution(tx_hash(1), SOLVER, transfers, context)

    assert signed_by_a_trader.method is AttributionMethod.UNRESOLVED
    assert signed_by_a_trader.portfolio_owner is None
    assert signed_by_a_trader.tx_sender == TRADERS[0]  # A6.1: the sender is still recorded
    assert signed_by_a_trader.method is signed_by_the_solver.method
    assert signed_by_a_trader.portfolio_owner == signed_by_the_solver.portfolio_owner

    # Nobody is dropped silently: all twenty-five travel with the record into the queue.
    reason = " ".join(signed_by_a_trader.evidence)
    for trader in TRADERS[:25]:
        assert trader in reason

    with pytest.raises(AttributionUnresolvedError):
        require_resolved_attribution(tx_hash(1), TRADERS[0], transfers, context)

    coverage = attribution_coverage([signed_by_a_trader])
    assert coverage.unresolved == 1 and coverage.usable_for_primary_metric == 0
    assert coverage.unresolved_rate == Decimal("1")  # 1/1, by hand


def test_a_settlement_batch_is_refused_whichever_mechanism_settled_it():
    """The same twenty-five users, submitted three ways, must get one answer.

    The transfer lane already refused this. Adding an ``ExecutionSuccess`` used to return the Safe
    at confidence 1, and adding a single ``UserOperationEvent`` used to return the smart account at
    confidence 1 — twenty-four traders erased in each case, with no quarantine record and no trace
    in the coverage report. How many owners a transaction has is a fact about the transfers; the
    settlement mechanism is a fact about how it was submitted, and it is not evidence about who
    traded.
    """
    transfers = ()
    for i in range(25):
        transfers += swap_legs(TRADERS[i], SETTLEMENT, start_index=2 * i)

    contexts = (
        base_context(),
        base_context(safe_execution=SafeExecution(safe=SAFE, signers=SIGNERS)),
        base_context(
            user_operations=(UserOperation(sender=SMART_ACCOUNT, bundler=BUNDLER),)
        ),
    )
    results = [
        resolve_attribution(tx_hash(1), SOLVER, transfers, context) for context in contexts
    ]

    for result in results:
        assert result.method is AttributionMethod.UNRESOLVED
        assert result.portfolio_owner is None
        assert result.confidence == Decimal("0")
        assert result.is_usable_for_primary_metric is False
        reason = " ".join(result.evidence)
        for trader in TRADERS[:25]:
            assert trader in reason

    # The executing account is named too: it is one of the owners the transaction could not choose
    # between, not the answer to the question.
    assert SAFE in " ".join(results[1].evidence)
    assert SMART_ACCOUNT in " ".join(results[2].evidence)

    for context in contexts:
        with pytest.raises(AttributionUnresolvedError):
            require_resolved_attribution(tx_hash(1), SOLVER, transfers, context)

    coverage = attribution_coverage(results)
    assert coverage.total == 3 and coverage.unresolved == 3
    assert coverage.usable_for_primary_metric == 0
    assert coverage.unresolved_rate == Decimal("1")  # 3/3, by hand


def test_the_usable_population_does_not_move_with_the_venue_label_list():
    """Replay the same day against an empty infrastructure list.

    §6.2's exclusion list is built from published label sets and is never complete. If dropping it
    changes the owners or the usable rate, then the §8 population is a function of how well
    somebody has labelled the venues rather than of what the chain says — and the number would
    quietly drift every time a new pool is deployed.
    """
    labelled = resolve_a_days_traffic()
    unlabelled = resolve_a_days_traffic(infrastructure=frozenset())

    assert [r.portfolio_owner for r in unlabelled] == [r.portfolio_owner for r in labelled]
    assert [r.method for r in unlabelled] == [r.method for r in labelled]

    coverage = attribution_coverage(unlabelled)
    assert coverage.by_method == {
        AttributionMethod.DIRECT_EOA: 8,
        AttributionMethod.SAFE_EXECUTION: 3,
        AttributionMethod.ERC4337_SENDER: 3,
        AttributionMethod.ROUTER_RECIPIENT: 4,
        AttributionMethod.UNRESOLVED: 1,
        AttributionMethod.TX_SENDER_FALLBACK: 1,
    }
    # 18/20 and 1/20, by hand — the same figures as the labelled run.
    assert coverage.usable_for_primary_metric == 18
    assert coverage.usable_rate == Decimal("0.9")
    assert coverage.unresolved_rate == Decimal("0.05")


# -- 3. smart accounts ----------------------------------------------------------


def test_erc4337_account_with_bundler_paymaster_and_relayer_all_present():
    """Ticket 20: proven on an account that has all three."""
    context = base_context(
        user_operations=(
            UserOperation(sender=SMART_ACCOUNT, bundler=BUNDLER, paymaster=PAYMASTER),
        ),
    )
    transfers = swap_legs(SMART_ACCOUNT, POOL) + (
        Transfer(token=WETH, from_addr=SMART_ACCOUNT, to_addr=PAYMASTER,
                 raw_amount=10 ** 15, log_index=2, is_fee=True),
        Transfer(token=WETH, from_addr=RELAYER, to_addr=BUNDLER,
                 raw_amount=10 ** 14, log_index=3, is_fee=True),
    )

    result = resolve_attribution(tx_hash(1), RELAYER, transfers, context)

    assert result.portfolio_owner == SMART_ACCOUNT
    assert result.portfolio_owner not in (BUNDLER, PAYMASTER, RELAYER)
    assert result.tx_sender == RELAYER
    assert result.account_type is AccountType.ERC4337
    assert result.is_usable_for_primary_metric


def test_a_safe_keeps_one_identity_across_a_week_of_rotating_signers():
    def context_for():
        return base_context(safe_execution=SafeExecution(safe=SAFE, signers=SIGNERS))

    results = [
        resolve_attribution(
            tx_hash(i), SIGNERS[i % len(SIGNERS)], swap_legs(SAFE, POOL), context_for()
        )
        for i in range(7)
    ]

    assert set(r.portfolio_owner for r in results) == {SAFE}
    assert set(r.tx_sender for r in results) == set(SIGNERS)
    assert all(r.account_type is AccountType.SAFE for r in results)
    coverage = attribution_coverage(results)
    assert coverage.usable_for_primary_metric == 7
    assert coverage.fallback_rate == Decimal("0")


# -- 4. quarantine rather than drop ---------------------------------------------


def test_an_unresolvable_transaction_is_reported_not_dropped():
    """Failure policy: an unsupported event is quarantined and reported, never silently dropped."""
    batch = swap_legs(TRADERS[0], SETTLEMENT, 0) + swap_legs(TRADERS[1], SETTLEMENT, 2)
    context = base_context()

    counted = resolve_attribution(tx_hash(1), SOLVER, batch, context)
    assert counted.method is AttributionMethod.UNRESOLVED
    assert counted.evidence, "the reason travels with the record into the reconciliation queue"

    with pytest.raises(AttributionUnresolvedError) as raised:
        require_resolved_attribution(tx_hash(1), SOLVER, batch, context)
    assert tx_hash(1) in str(raised.value)

    # Both paths describe the same transaction, and the counting path keeps it in the population.
    coverage = attribution_coverage([counted])
    assert coverage.total == 1 and coverage.unresolved == 1
    assert coverage.unresolved_rate == Decimal("1")


# -- 5. input-order independence -------------------------------------------------


def test_transfer_order_does_not_change_the_owner():
    """Log ordering differs between vendors and between a node and a warehouse table.

    A recovered owner that depends on log order would reconcile against raw chain data only by
    luck, and §9.2 requires an exact match.
    """
    transfers = swap_legs(TRADERS[3], SETTLEMENT) + (
        Transfer(token=WETH, from_addr=SETTLEMENT, to_addr=SOLVER,
                 raw_amount=10 ** 15, log_index=2, is_fee=True),
    )
    context = base_context()

    forward = resolve_attribution(tx_hash(1), SOLVER, transfers, context)
    reversed_ = resolve_attribution(tx_hash(1), SOLVER, tuple(reversed(transfers)), context)

    assert forward.portfolio_owner == reversed_.portfolio_owner == TRADERS[3]
    assert forward.method is reversed_.method
