"""Worked attribution examples, expected values written by hand before the implementation.

Every case here is a transaction shape that exists on Ethereum mainnet and that a published
pipeline gets wrong. The expectations were derived by reading §6.2 and amendment A6.1 and writing
the answer down, not by running the code and recording what it said.

The load-bearing one is :func:`test_infrastructure_sender_never_falls_back`. Dune's core macro
contains ``coalesce(base_trades.taker, base_trades.tx_from)``: when the taker is unknown the
transaction sender is used, and for a solver-settled trade the transaction sender is the solver.
That single line manufactures phantom mega-wallets and erases the real users. The rule here is that
the fallback is refused outright for infrastructure senders — not flagged, refused.
"""

import ast
from decimal import Decimal

import pytest

from attribution import (
    AttributionContext,
    AttributionCoverage,
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
    Attribution,
    AttributionMethod,
    AttributionUnresolvedError,
    Transfer,
    to_canonical_json,
)

# -- fixtures -------------------------------------------------------------------

TX = "0x" + "11" * 32

ALICE = "0x" + "a1" * 20
BOB = "0x" + "b2" * 20
CAROL = "0x" + "c2" * 20
SAFE = "0x" + "5a" * 20
SAFE_2 = "0x" + "5b" * 20
SIGNER_1 = "0x" + "51" * 20
SIGNER_2 = "0x" + "52" * 20
SMART_ACCOUNT = "0x" + "44" * 20
BUNDLER = "0x" + "bd" * 20
PAYMASTER = "0x" + "9a" * 20
RELAYER = "0x" + "7e" * 20
SOLVER = "0x" + "50" * 20
SETTLEMENT = "0x" + "5e" * 20
ROUTER = "0x" + "70" * 20
POOL = "0x" + "0d" * 20
#: A pool nobody has labelled yet. The infrastructure list is built from published label sets and
#: is never complete for a venue deployed last week — which is exactly when it matters.
NEWPOOL = "0x" + "9e" * 20
#: The same, one hop further along, and for a settlement contract and a Safe.
NEWROUTER = "0x" + "9f" * 20
NEWSETTLEMENT = "0x" + "9d" * 20
NEWSAFE = "0x" + "9c" * 20
UNTYPED_CONTRACT = "0x" + "c0" * 20
NULL = "0x" + "00" * 20

USDC_1000 = 1000 * 10 ** 6
WETH_HALF = 5 * 10 ** 17

INFRA = frozenset({BUNDLER, PAYMASTER, RELAYER, SOLVER, SETTLEMENT, ROUTER, POOL})


def sell_usdc_buy_weth(owner, venue=POOL, start_index=0):
    """The two legs of an ordinary $1,000 USDC -> 0.5 WETH purchase."""
    return (
        Transfer(token=USDC, from_addr=owner, to_addr=venue,
                 raw_amount=USDC_1000, log_index=start_index),
        Transfer(token=WETH, from_addr=venue, to_addr=owner,
                 raw_amount=WETH_HALF, log_index=start_index + 1),
    )


# -- 1. the ordinary case -------------------------------------------------------


def test_direct_eoa_swap():
    """A known EOA sends its own swap and is an endpoint of it. Owner = that EOA, confidence 1."""
    context = AttributionContext(infrastructure=INFRA, eoas=frozenset({ALICE}))

    result = resolve_attribution(TX, ALICE, sell_usdc_buy_weth(ALICE), context)

    assert result.portfolio_owner == ALICE
    assert result.tx_sender == ALICE
    assert result.account_type is AccountType.EOA
    assert result.method is AttributionMethod.DIRECT_EOA
    assert result.confidence == Decimal("1")
    assert result.is_fallback is False
    assert result.is_usable_for_primary_metric is True


def test_eoa_sender_that_is_not_an_endpoint_is_not_the_owner():
    """A gas payer is not a trader.

    ALICE sends the transaction; every token leg belongs to BOB. Attributing to ALICE is the
    Solana-style error (§13 — Jupiter sponsors gas, Dune sets ``trader_id = tx_signer``, so the
    sponsor collects other people's trades).
    """
    context = AttributionContext(
        infrastructure=INFRA, eoas=frozenset({ALICE, BOB}),
    )

    result = resolve_attribution(TX, ALICE, sell_usdc_buy_weth(BOB), context)

    assert result.portfolio_owner == BOB
    assert result.method is AttributionMethod.ROUTER_RECIPIENT
    assert result.account_type is AccountType.EOA
    assert result.confidence == Decimal("0.8")
    assert result.is_usable_for_primary_metric is True


def test_fee_only_participation_is_not_an_endpoint():
    """§4.2: fee and referral transfers must not be mistaken for endpoints.

    BOB trades; ALICE (the sender) only collects a referral fee. ALICE has no economic leg, so the
    owner is BOB — not the fee collector who happened to sign.
    """
    transfers = sell_usdc_buy_weth(BOB) + (
        Transfer(token=USDC, from_addr=POOL, to_addr=ALICE, raw_amount=3 * 10 ** 6,
                 log_index=2, is_fee=True),
    )
    context = AttributionContext(infrastructure=INFRA, eoas=frozenset({ALICE, BOB}))

    result = resolve_attribution(TX, ALICE, transfers, context)

    assert result.portfolio_owner == BOB
    assert result.method is AttributionMethod.ROUTER_RECIPIENT


# -- 2. Safe --------------------------------------------------------------------


def test_safe_execution_attributes_to_the_safe_not_the_signer():
    """§6.2: portfolio identity is the Safe address; signers are not separate traders."""
    context = AttributionContext(
        infrastructure=INFRA,
        safes=frozenset({SAFE}),
        eoas=frozenset({SIGNER_1, SIGNER_2}),
        safe_execution=SafeExecution(safe=SAFE, signers=(SIGNER_1, SIGNER_2)),
    )

    result = resolve_attribution(TX, SIGNER_1, sell_usdc_buy_weth(SAFE), context)

    assert result.portfolio_owner == SAFE
    assert result.tx_sender == SIGNER_1
    assert result.portfolio_owner not in (SIGNER_1, SIGNER_2)
    assert result.account_type is AccountType.SAFE
    assert result.method is AttributionMethod.SAFE_EXECUTION
    assert result.confidence == Decimal("1")
    assert result.is_usable_for_primary_metric is True


def test_safe_with_a_4337_module_is_still_the_safe():
    """A Safe running the ERC-4337 module emits both an execution and a user operation.

    Consistent evidence — the user operation's sender *is* the Safe — so this is not a conflict.
    """
    context = AttributionContext(
        infrastructure=INFRA,
        safes=frozenset({SAFE}),
        safe_execution=SafeExecution(safe=SAFE, signers=(SIGNER_1,)),
        user_operations=(UserOperation(sender=SAFE, bundler=BUNDLER, paymaster=PAYMASTER),),
    )

    result = resolve_attribution(TX, BUNDLER, sell_usdc_buy_weth(SAFE), context)

    assert result.portfolio_owner == SAFE
    assert result.method is AttributionMethod.SAFE_EXECUTION
    assert result.account_type is AccountType.SAFE


def test_safe_execution_conflicting_with_a_foreign_user_operation_is_unresolved():
    context = AttributionContext(
        infrastructure=INFRA,
        safes=frozenset({SAFE}),
        smart_accounts=frozenset({SMART_ACCOUNT}),
        safe_execution=SafeExecution(safe=SAFE, signers=(SIGNER_1,)),
        user_operations=(UserOperation(sender=SMART_ACCOUNT, bundler=BUNDLER),),
    )

    result = resolve_attribution(TX, BUNDLER, sell_usdc_buy_weth(SAFE), context)

    assert result.method is AttributionMethod.UNRESOLVED
    assert result.portfolio_owner is None
    assert result.account_type is AccountType.UNKNOWN
    assert result.confidence == Decimal("0")


def test_a_safe_on_the_infrastructure_list_is_unresolved_not_owned():
    """A shared multisig treasury is infrastructure, and infrastructure is not a portfolio."""
    context = AttributionContext(
        infrastructure=INFRA | {SAFE},
        safe_execution=SafeExecution(safe=SAFE, signers=(SIGNER_1,)),
    )

    result = resolve_attribution(TX, SIGNER_1, sell_usdc_buy_weth(SAFE), context)

    assert result.method is AttributionMethod.UNRESOLVED
    assert result.portfolio_owner is None


# -- 3. ERC-4337 ----------------------------------------------------------------


def test_erc4337_attributes_to_the_smart_account_never_to_infrastructure():
    """§6.2: bundler, paymaster, and relayer are never recorded as the trader."""
    context = AttributionContext(
        infrastructure=INFRA,
        smart_accounts=frozenset({SMART_ACCOUNT}),
        user_operations=(
            UserOperation(sender=SMART_ACCOUNT, bundler=BUNDLER, paymaster=PAYMASTER),
        ),
    )
    transfers = sell_usdc_buy_weth(SMART_ACCOUNT) + (
        Transfer(token=WETH, from_addr=SMART_ACCOUNT, to_addr=PAYMASTER,
                 raw_amount=10 ** 15, log_index=2, is_fee=True),
    )

    result = resolve_attribution(TX, BUNDLER, transfers, context)

    assert result.portfolio_owner == SMART_ACCOUNT
    assert result.portfolio_owner not in (BUNDLER, PAYMASTER, RELAYER)
    assert result.tx_sender == BUNDLER
    assert result.account_type is AccountType.ERC4337
    assert result.method is AttributionMethod.ERC4337_SENDER
    assert result.confidence == Decimal("1")
    assert result.is_usable_for_primary_metric is True


def test_bundled_user_operations_are_unresolved_not_guessed():
    """One bundle, two owners, one attribution slot. The honest answer is that it is ambiguous."""
    context = AttributionContext(
        infrastructure=INFRA,
        smart_accounts=frozenset({SMART_ACCOUNT, ALICE}),
        user_operations=(
            UserOperation(sender=SMART_ACCOUNT, bundler=BUNDLER),
            UserOperation(sender=ALICE, bundler=BUNDLER),
        ),
    )

    result = resolve_attribution(TX, BUNDLER, sell_usdc_buy_weth(SMART_ACCOUNT), context)

    assert result.method is AttributionMethod.UNRESOLVED
    assert result.portfolio_owner is None
    with pytest.raises(AttributionUnresolvedError):
        require_resolved_attribution(
            TX, BUNDLER, sell_usdc_buy_weth(SMART_ACCOUNT), context
        )


def test_user_operation_whose_sender_is_the_bundler_is_unresolved():
    context = AttributionContext(
        infrastructure=INFRA,
        user_operations=(UserOperation(sender=BUNDLER, bundler=BUNDLER),),
    )

    result = resolve_attribution(TX, BUNDLER, sell_usdc_buy_weth(BUNDLER), context)

    assert result.method is AttributionMethod.UNRESOLVED
    assert result.portfolio_owner is None


# -- 4. solver-settled and aggregator-routed ------------------------------------


def test_solver_settled_trade_attributes_to_the_user_not_the_solver():
    """The exact shape Dune's ``coalesce`` gets wrong.

    The solver sends the transaction and takes a fee. The only address that both pays and receives
    a non-fee leg is the user, so the user is the owner and the solver is never a candidate.
    """
    transfers = sell_usdc_buy_weth(ALICE, venue=SETTLEMENT) + (
        Transfer(token=WETH, from_addr=SETTLEMENT, to_addr=SOLVER,
                 raw_amount=2 * 10 ** 15, log_index=2, is_fee=True),
    )
    context = AttributionContext(infrastructure=INFRA, eoas=frozenset({ALICE}))

    result = resolve_attribution(TX, SOLVER, transfers, context)

    assert result.portfolio_owner == ALICE
    assert result.portfolio_owner != SOLVER
    assert result.tx_sender == SOLVER
    assert result.method is AttributionMethod.ROUTER_RECIPIENT
    assert result.confidence == Decimal("0.8")
    assert result.is_usable_for_primary_metric is True


def test_batched_settlement_with_two_users_is_unresolved():
    """A CoW batch settles several users at once. Neither is *the* owner of the transaction."""
    transfers = (
        sell_usdc_buy_weth(ALICE, venue=SETTLEMENT, start_index=0)
        + sell_usdc_buy_weth(BOB, venue=SETTLEMENT, start_index=2)
    )
    context = AttributionContext(infrastructure=INFRA, eoas=frozenset({ALICE, BOB}))

    result = resolve_attribution(TX, SOLVER, transfers, context)

    assert result.method is AttributionMethod.UNRESOLVED
    assert result.portfolio_owner is None
    assert result.is_usable_for_primary_metric is False


def test_a_batch_signed_by_one_of_its_own_traders_is_still_unresolved():
    """Ambiguity is decided before the signer is looked at.

    Identical economic shape to ``test_batched_settlement_with_two_users_is_unresolved``; the only
    difference is that ALICE paid the gas instead of the solver. Two addresses are on both sides of
    the transfers, and an ``Attribution`` has one owner slot: returning ALICE publishes her at
    confidence 1 and erases BOB with no quarantine record, no reason string, and no trace in the
    coverage report. Who signed is not evidence about who traded — that is the whole premise of the
    module — so it cannot be what decides between refusing and resolving either.
    """
    transfers = (
        sell_usdc_buy_weth(ALICE, venue=SETTLEMENT, start_index=0)
        + sell_usdc_buy_weth(BOB, venue=SETTLEMENT, start_index=2)
    )
    context = AttributionContext(infrastructure=INFRA, eoas=frozenset({ALICE, BOB}))

    signed_by_a_trader = resolve_attribution(TX, ALICE, transfers, context)
    signed_by_the_solver = resolve_attribution(TX, SOLVER, transfers, context)

    assert signed_by_a_trader.method is AttributionMethod.UNRESOLVED
    assert signed_by_a_trader.portfolio_owner is None
    assert signed_by_a_trader.confidence == Decimal("0")
    assert signed_by_a_trader.is_usable_for_primary_metric is False
    # The same shape gets the same answer whoever paid the gas.
    assert signed_by_a_trader.method is signed_by_the_solver.method
    # Both erased traders leave a trace in the record that goes to the reconciliation queue.
    reason = " ".join(signed_by_a_trader.evidence)
    assert ALICE in reason and BOB in reason


def test_an_unlabelled_venue_is_not_promoted_when_the_trader_signs():
    """A two-sided sender is evidence of a second candidate, not evidence of none.

    ALICE's code status is unknown — the ``eoas`` set is never complete — and she swaps against a
    pool that has not been added to the infrastructure list. Deleting the sender from the candidate
    set rather than counting it left the pool as the sole survivor, so the pool was returned as
    ``portfolio_owner`` under an evidence line stating the sender "is not the beneficiary" about an
    address that demonstrably both sent and received. §6.2 excludes pools from the candidate
    universe entirely, and the record was counted as resolved, so ``unresolved_rate`` hid it.
    """
    context = AttributionContext(
        infrastructure=frozenset({SETTLEMENT, SOLVER}),
        contract_accounts=frozenset({NEWPOOL}),
    )

    result = resolve_attribution(
        TX, ALICE, sell_usdc_buy_weth(ALICE, venue=NEWPOOL), context
    )

    assert result.portfolio_owner is None
    assert result.portfolio_owner != NEWPOOL
    assert result.method is AttributionMethod.UNRESOLVED
    assert result.is_usable_for_primary_metric is False

    coverage = attribution_coverage([result])
    assert coverage.unresolved == 1 and coverage.resolved == 0
    assert coverage.unresolved_rate == Decimal("1")  # 1/1, by hand


def test_infrastructure_sender_never_falls_back():
    """The single most important refusal in this module.

    An infrastructure sender with no owner evidence produces UNRESOLVED even when the caller has
    explicitly permitted the tx-sender fallback. Flagging would not be enough: a flagged phantom
    whale still enters the universe measurement, and one solver address would carry thousands of
    other people's trades.
    """
    context = AttributionContext(
        infrastructure=INFRA,
        permit_tx_sender_fallback=True,
    )

    result = resolve_attribution(TX, SOLVER, (), context)

    assert result.method is AttributionMethod.UNRESOLVED
    assert result.portfolio_owner is None
    assert result.is_fallback is False
    assert result.is_usable_for_primary_metric is False


# -- 5. the flagged fallback ----------------------------------------------------


def test_fallback_is_refused_unless_explicitly_permitted():
    context = AttributionContext(infrastructure=INFRA, eoas=frozenset({ALICE}))

    result = resolve_attribution(TX, ALICE, (), context)

    assert result.method is AttributionMethod.UNRESOLVED
    assert result.portfolio_owner is None


def test_permitted_fallback_is_flagged_and_excluded():
    """A fallback owner is recorded as a fallback, and is never usable for the primary metric."""
    context = AttributionContext(
        infrastructure=INFRA, eoas=frozenset({ALICE}), permit_tx_sender_fallback=True,
    )

    result = resolve_attribution(TX, ALICE, (), context)

    assert result.portfolio_owner == ALICE
    assert result.method is AttributionMethod.TX_SENDER_FALLBACK
    assert result.confidence == Decimal("0.1")
    assert result.is_fallback is True
    assert result.is_usable_for_primary_metric is False


def test_unknown_contract_sender_is_never_fallen_back_to():
    """A contract whose economic controller is unidentified is excluded (§6.2), not guessed at."""
    context = AttributionContext(
        infrastructure=INFRA, permit_tx_sender_fallback=True,
    )

    result = resolve_attribution(TX, UNTYPED_CONTRACT, (), context)

    assert result.method is AttributionMethod.UNRESOLVED
    assert result.portfolio_owner is None


# -- 6. account typing ----------------------------------------------------------


def test_unknown_code_status_yields_unknown_and_is_not_usable():
    """An owner we cannot type is recovered but excluded — UNKNOWN is not a pass."""
    context = AttributionContext(infrastructure=INFRA)  # BOB's code status is unknown

    result = resolve_attribution(TX, SOLVER, sell_usdc_buy_weth(BOB, venue=SETTLEMENT), context)

    assert result.portfolio_owner == BOB
    assert result.account_type is AccountType.UNKNOWN
    assert result.is_usable_for_primary_metric is False


def test_other_contract_owner_is_typed_and_usable():
    context = AttributionContext(
        infrastructure=INFRA, contract_accounts=frozenset({BOB}),
    )

    result = resolve_attribution(TX, SOLVER, sell_usdc_buy_weth(BOB, venue=SETTLEMENT), context)

    assert result.portfolio_owner == BOB
    assert result.account_type is AccountType.OTHER_CONTRACT
    assert result.is_usable_for_primary_metric is True


def test_the_null_address_is_never_an_owner():
    """Mint and burn legs make the zero address look like a two-sided counterparty."""
    transfers = (
        Transfer(token=USDC, from_addr=NULL, to_addr=POOL, raw_amount=USDC_1000, log_index=0),
        Transfer(token=WETH, from_addr=POOL, to_addr=NULL, raw_amount=WETH_HALF, log_index=1),
    )
    context = AttributionContext(infrastructure=INFRA)

    result = resolve_attribution(TX, SOLVER, transfers, context)

    assert result.portfolio_owner is None
    assert result.method is AttributionMethod.UNRESOLVED


def test_a_safe_execution_naming_the_null_address_is_unresolved():
    """The zero address reaches ``portfolio_owner`` through the event lane, not the transfer lane.

    ``_economic_endpoints`` filters the null address, so the transfer-derived methods can never
    return it — but ``SafeExecution`` accepts it (it is a non-empty string), and the Safe branch
    runs before any of that. A malformed ExecutionSuccess therefore published the mint/burn
    placeholder as a Safe portfolio at confidence 1, usable for the primary metric.
    """
    context = AttributionContext(safe_execution=SafeExecution(safe=NULL, signers=(SIGNER_1,)))

    result = resolve_attribution(TX, SIGNER_1, (), context)

    assert result.portfolio_owner is None
    assert result.method is AttributionMethod.UNRESOLVED
    assert result.is_usable_for_primary_metric is False


def test_a_user_operation_naming_the_null_address_is_unresolved():
    """The same hole on the ERC-4337 lane."""
    context = AttributionContext(
        infrastructure=INFRA,
        user_operations=(UserOperation(sender=NULL, bundler=BUNDLER),),
    )

    result = resolve_attribution(TX, BUNDLER, (), context)

    assert result.portfolio_owner is None
    assert result.method is AttributionMethod.UNRESOLVED


def test_the_null_address_guard_at_the_exit_point_would_actually_fire():
    """Guard the guard, as with the tx-sender rule: the backstop must reject, not just document."""
    from attribution.resolve import AttributionInvariantError, _finalise

    context = AttributionContext()
    with pytest.raises(AttributionInvariantError):
        _finalise(
            tx_hash=TX,
            tx_sender=SIGNER_1,
            owner=NULL,
            account_type=AccountType.SAFE,
            method=AttributionMethod.SAFE_EXECUTION,
            evidence=("fabricated",),
            context=context,
        )


def test_contradictory_context_is_refused_at_construction():
    """An address cannot be both infrastructure and a portfolio identity."""
    with pytest.raises(ValueError):
        AttributionContext(infrastructure=frozenset({SAFE}), safes=frozenset({SAFE}))
    with pytest.raises(ValueError):
        AttributionContext(eoas=frozenset({ALICE}), contract_accounts=frozenset({ALICE}))


def test_missing_identity_is_refused():
    context = AttributionContext()
    with pytest.raises(ValueError):
        resolve_attribution("", ALICE, (), context)
    with pytest.raises(ValueError):
        resolve_attribution(TX, "", (), context)


# -- 7. the standing fallback-rate metric ---------------------------------------


def test_fallback_rate_is_exact_and_unquantized():
    """Ticket 20: the fallback rate is a standing metric emitted with every run.

    Four attributions, one of them a fallback: 1/4 = 0.25 exactly, by hand.
    """
    context = AttributionContext(
        infrastructure=INFRA,
        eoas=frozenset({ALICE, BOB}),
        permit_tx_sender_fallback=True,
    )
    results = [
        resolve_attribution(TX, ALICE, sell_usdc_buy_weth(ALICE), context),   # DIRECT_EOA
        resolve_attribution(TX, ALICE, sell_usdc_buy_weth(BOB), context),     # ROUTER_RECIPIENT
        resolve_attribution(TX, SOLVER, (), context),                         # UNRESOLVED
        resolve_attribution(TX, BOB, (), context),                            # fallback
    ]

    assert [r.method for r in results] == [
        AttributionMethod.DIRECT_EOA,
        AttributionMethod.ROUTER_RECIPIENT,
        AttributionMethod.UNRESOLVED,
        AttributionMethod.TX_SENDER_FALLBACK,
    ]
    assert attribution_fallback_rate(results) == Decimal("0.25")

    coverage = attribution_coverage(results)
    assert isinstance(coverage, AttributionCoverage)
    assert coverage.total == 4
    assert coverage.fallback == 1
    assert coverage.unresolved == 1
    assert coverage.usable_for_primary_metric == 2
    assert coverage.fallback_rate == Decimal("0.25")
    assert coverage.unresolved_rate == Decimal("0.25")
    assert coverage.usable_rate == Decimal("0.5")
    assert coverage.by_method[AttributionMethod.DIRECT_EOA] == 1
    # Three EOAs: the direct one, the router recipient, and the flagged fallback — the fallback is
    # excluded by its method, not by its account type.
    assert coverage.by_account_type[AccountType.EOA] == 3
    assert coverage.by_account_type[AccountType.UNKNOWN] == 1


def test_empty_population_has_no_rate_rather_than_a_zero_rate():
    """Seam rule: missing is None, never a sentinel number.

    A 0% fallback rate over zero transactions would read as a clean run.
    """
    assert attribution_fallback_rate([]) is None
    empty = attribution_coverage([])
    assert empty.total == 0
    assert empty.fallback_rate is None
    assert empty.unresolved_rate is None
    assert empty.usable_rate is None


# -- 8. serialization and structure ---------------------------------------------


def test_every_output_survives_canonical_json():
    context = AttributionContext(
        infrastructure=INFRA, eoas=frozenset({ALICE}), permit_tx_sender_fallback=True,
    )
    results = [
        resolve_attribution(TX, ALICE, sell_usdc_buy_weth(ALICE), context),
        resolve_attribution(TX, SOLVER, (), context),
        resolve_attribution(TX, ALICE, (), context),
    ]

    for result in results:
        payload = to_canonical_json(result)
        assert '"confidence":"' in payload  # Decimal serialized as a string, never a JSON number

    assert to_canonical_json(attribution_coverage(results))


def test_tx_sender_can_reach_portfolio_owner_only_through_the_flagged_fallback():
    """Ticket 20: enforced structurally, not by convention.

    Reads the module's own AST and asserts that the ``tx_sender`` parameter is passed as an owner
    in exactly one function — the one that marks the result ``TX_SENDER_FALLBACK``.
    """
    import attribution.resolve as resolve_module

    source = open(resolve_module.__file__, "r", encoding="utf-8").read()
    tree = ast.parse(source, filename=resolve_module.__file__)

    functions_passing_tx_sender_as_owner = set()
    for function in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for call in [n for n in ast.walk(function) if isinstance(n, ast.Call)]:
            for keyword in call.keywords:
                if keyword.arg == "owner" and isinstance(keyword.value, ast.Name):
                    if keyword.value.id == "tx_sender":
                        functions_passing_tx_sender_as_owner.add(function.name)

    assert functions_passing_tx_sender_as_owner == {"_tx_sender_fallback"}, (
        "tx_sender reached an owner position outside the flagged fallback: {}".format(
            sorted(functions_passing_tx_sender_as_owner)
        )
    )


def test_the_structural_guard_would_actually_fire():
    """Guard the guard: the exit-point invariant must reject a leaked owner, not just document it.

    Calls the internal finaliser directly with the shape the guard exists to catch — an owner
    equal to the transaction sender under a method that claims independent evidence.
    """
    from attribution.resolve import AttributionInvariantError, _finalise

    context = AttributionContext(eoas=frozenset({ALICE}))
    with pytest.raises(AttributionInvariantError):
        _finalise(
            tx_hash=TX,
            tx_sender=ALICE,
            owner=ALICE,
            account_type=AccountType.EOA,
            method=AttributionMethod.ROUTER_RECIPIENT,
            evidence=("fabricated",),
            context=context,
        )


def test_resolution_is_a_frozen_contract_type():
    context = AttributionContext(infrastructure=INFRA, eoas=frozenset({ALICE}))
    result = resolve_attribution(TX, ALICE, sell_usdc_buy_weth(ALICE), context)
    assert isinstance(result, Attribution)
    assert result.evidence, "every attribution must carry evidence naming the rule it applied"


# -- 9. how many owners is a fact about the transaction, not about the lane ------
#
# The ambiguity rule used to run after the Safe and ERC-4337 lanes had already returned, so the
# identical multi-owner transaction was refused when a solver submitted it and published as one
# owner at confidence 1 when a Safe executed it. These four vary the settlement mechanism, the
# number of owners, the account type of the owners, and whether any label list names the executing
# account at all — the condition is "this transaction carries evidence for more than one
# portfolio", and none of them is the twenty-five-EOA batch that exposed it.


def test_a_safe_execution_does_not_outrank_a_second_owner_in_the_transfers():
    """The smallest size the class exists at: two owners, one owner slot.

    BOB's swap is the only economic activity in the transaction, and a Safe executed it. Returning
    the Safe at confidence 1 does not rank the Safe above BOB on the evidence — it ranks the lane
    above the evidence, because the lane returned before anything counted the owners. An
    ``ExecutionSuccess`` names *an* account; it is not a statement that the transaction has only
    one.
    """
    context = AttributionContext(
        infrastructure=INFRA,
        safes=frozenset({SAFE}),
        eoas=frozenset({BOB, SIGNER_1}),
        safe_execution=SafeExecution(safe=SAFE, signers=(SIGNER_1,)),
    )

    result = resolve_attribution(TX, SIGNER_1, sell_usdc_buy_weth(BOB), context)

    assert result.method is AttributionMethod.UNRESOLVED
    assert result.portfolio_owner is None
    assert result.confidence == Decimal("0")
    assert result.is_usable_for_primary_metric is False
    reason = " ".join(result.evidence)
    assert SAFE in reason and BOB in reason


def test_a_single_user_operation_does_not_outrank_two_safe_traders():
    """Three owners, none of them an EOA, and one ordinary UserOperationEvent.

    The reviewer's case was twenty-five EOAs and a bundle; the condition has nothing to do with
    either number or with EOAs. Two Safes settled through a shared settlement contract plus one
    smart account named by the event is three portfolios and one owner slot.
    """
    context = AttributionContext(
        infrastructure=INFRA,
        safes=frozenset({SAFE, SAFE_2}),
        smart_accounts=frozenset({SMART_ACCOUNT}),
        user_operations=(UserOperation(sender=SMART_ACCOUNT, bundler=BUNDLER),),
    )
    transfers = (
        sell_usdc_buy_weth(SAFE, venue=SETTLEMENT, start_index=0)
        + sell_usdc_buy_weth(SAFE_2, venue=SETTLEMENT, start_index=2)
    )

    result = resolve_attribution(TX, BUNDLER, transfers, context)

    assert result.method is AttributionMethod.UNRESOLVED
    assert result.portfolio_owner is None
    assert result.is_usable_for_primary_metric is False
    reason = " ".join(result.evidence)
    for erased in (SAFE, SAFE_2, SMART_ACCOUNT):
        assert erased in reason


def test_an_unlabelled_safe_settling_for_two_traders_is_still_refused():
    """The label list is not what stands between a settling Safe and a phantom mega-wallet.

    NEWSAFE is on no list — not infrastructure, not typed as a Safe — and neither is the venue it
    settled through. ``is_infrastructure(safe)`` therefore says nothing, and the refusal has to
    come from counting the owners. The infrastructure list is the input finding attribution.2
    exists because it is never complete.
    """
    context = AttributionContext(
        eoas=frozenset({ALICE, BOB}),
        safe_execution=SafeExecution(safe=NEWSAFE, signers=()),
    )
    transfers = (
        sell_usdc_buy_weth(ALICE, venue=NEWSETTLEMENT, start_index=0)
        + sell_usdc_buy_weth(BOB, venue=NEWSETTLEMENT, start_index=2)
    )

    result = resolve_attribution(TX, NEWSAFE, transfers, context)

    assert result.method is AttributionMethod.UNRESOLVED
    assert result.portfolio_owner is None
    reason = " ".join(result.evidence)
    for erased in (ALICE, BOB, NEWSAFE):
        assert erased in reason


def test_the_same_batch_gets_the_same_answer_on_all_three_lanes():
    """One economic shape, three settlement mechanisms, one answer.

    Whether a batch arrives through plain transfers, an ``ExecutionSuccess``, or a
    ``UserOperationEvent`` is a fact about how it was submitted. Who traded is a fact about the
    transfers, and it is the same in all three.
    """
    transfers = (
        sell_usdc_buy_weth(ALICE, venue=SETTLEMENT, start_index=0)
        + sell_usdc_buy_weth(BOB, venue=SETTLEMENT, start_index=2)
    )
    base = dict(
        infrastructure=INFRA,
        safes=frozenset({SAFE}),
        smart_accounts=frozenset({SMART_ACCOUNT}),
        eoas=frozenset({ALICE, BOB}),
    )
    plain = AttributionContext(**base)
    by_safe = AttributionContext(
        safe_execution=SafeExecution(safe=SAFE, signers=(SIGNER_1,)), **base
    )
    by_bundle = AttributionContext(
        user_operations=(UserOperation(sender=SMART_ACCOUNT, bundler=BUNDLER),), **base
    )

    results = [
        resolve_attribution(TX, SOLVER, transfers, context)
        for context in (plain, by_safe, by_bundle)
    ]

    assert [r.method for r in results] == [AttributionMethod.UNRESOLVED] * 3
    assert [r.portfolio_owner for r in results] == [None, None, None]
    assert [r.confidence for r in results] == [Decimal("0")] * 3
    for result in results:
        reason = " ".join(result.evidence)
        assert ALICE in reason and BOB in reason


# -- 10. coverage must not move with the completeness of the label list ----------
#
# §6.2's exclusion list is built from published label sets and is never complete. A resolver whose
# *refusal* rate rises when a venue is missing from it has made the usable population a function of
# label coverage — the one input this module is designed not to depend on. Three unlabelled shapes,
# one labelled control, and the two refusals that must survive the change.


def test_a_known_eoa_owns_its_swap_against_an_unlabelled_venue():
    """Same trader, same swap, four venues: one labelled, three not.

    An address that is two-sided but positively typed as neither an EOA, a Safe, nor a smart
    account is a venue passing value through — that is what the two-sided test was for. It is not
    a second portfolio, and it must not be able to defeat a sender that *is* one.
    """
    labelled = AttributionContext(infrastructure=INFRA, eoas=frozenset({ALICE}))
    unlabelled = AttributionContext(
        infrastructure=frozenset({SETTLEMENT, SOLVER}), eoas=frozenset({ALICE})
    )
    typed_contract = AttributionContext(
        infrastructure=frozenset({SETTLEMENT, SOLVER}),
        contract_accounts=frozenset({NEWPOOL, NEWROUTER}),
        eoas=frozenset({ALICE}),
    )
    two_hop = (
        Transfer(token=USDC, from_addr=ALICE, to_addr=NEWPOOL,
                 raw_amount=USDC_1000, log_index=0),
        Transfer(token=USDC, from_addr=NEWPOOL, to_addr=NEWROUTER,
                 raw_amount=USDC_1000, log_index=1),
        Transfer(token=WETH, from_addr=NEWROUTER, to_addr=ALICE,
                 raw_amount=WETH_HALF, log_index=2),
    )

    results = [
        resolve_attribution(TX, ALICE, sell_usdc_buy_weth(ALICE, venue=POOL), labelled),
        resolve_attribution(TX, ALICE, sell_usdc_buy_weth(ALICE, venue=NEWPOOL), unlabelled),
        resolve_attribution(TX, ALICE, sell_usdc_buy_weth(ALICE, venue=NEWPOOL), typed_contract),
        resolve_attribution(TX, ALICE, two_hop, typed_contract),
    ]

    for result in results:
        assert result.portfolio_owner == ALICE
        assert result.method is AttributionMethod.DIRECT_EOA
        assert result.account_type is AccountType.EOA
        assert result.confidence == Decimal("1")
        assert result.is_usable_for_primary_metric is True

    # The venues that were set aside travel with the record, so a reviewer can see what the rule
    # discarded rather than having to re-derive it.
    assert NEWPOOL in " ".join(results[1].evidence)
    assert NEWPOOL in " ".join(results[3].evidence)
    assert NEWROUTER in " ".join(results[3].evidence)


def test_an_eoa_settled_through_an_unlabelled_settlement_contract_is_still_recovered():
    """The same rule where the owner is not the signer: solver-settled through an unlisted venue.

    ALICE never signs; a solver does. Two addresses are on both sides of the transfers and exactly
    one of them is a portfolio, so the settlement contract is a venue and ALICE is the owner —
    at ROUTER_RECIPIENT's 0.8, because no event named her.
    """
    context = AttributionContext(infrastructure=frozenset({SOLVER}), eoas=frozenset({ALICE}))
    transfers = sell_usdc_buy_weth(ALICE, venue=NEWSETTLEMENT) + (
        Transfer(token=WETH, from_addr=NEWSETTLEMENT, to_addr=SOLVER,
                 raw_amount=2 * 10 ** 15, log_index=2, is_fee=True),
    )

    result = resolve_attribution(TX, SOLVER, transfers, context)

    assert result.portfolio_owner == ALICE
    assert result.method is AttributionMethod.ROUTER_RECIPIENT
    assert result.confidence == Decimal("0.8")
    assert result.is_usable_for_primary_metric is True
    assert NEWSETTLEMENT in " ".join(result.evidence)


def test_two_known_eoas_against_an_unlabelled_venue_are_still_ambiguous():
    """The relaxation is "exactly one portfolio", not "at least one".

    Two typed EOAs traded through the unlisted venue. Naming either of them erases the other, so
    the presence of an unlabelled venue changes nothing about the refusal.
    """
    context = AttributionContext(eoas=frozenset({ALICE, BOB}))
    transfers = (
        sell_usdc_buy_weth(ALICE, venue=NEWSETTLEMENT, start_index=0)
        + sell_usdc_buy_weth(BOB, venue=NEWSETTLEMENT, start_index=2)
    )

    result = resolve_attribution(TX, ALICE, transfers, context)

    assert result.method is AttributionMethod.UNRESOLVED
    assert result.portfolio_owner is None
    reason = " ".join(result.evidence)
    assert ALICE in reason and BOB in reason


def test_an_untyped_sender_against_an_unlabelled_venue_is_still_refused():
    """Finding attribution.2, re-checked: the relaxation must not reopen it.

    Nothing types ALICE, so the transaction contains no portfolio at all — two two-sided addresses
    and no evidence ranking them. Resolving it would return the pool as the owner under an
    evidence line saying the sender "is not the beneficiary".
    """
    context = AttributionContext(
        infrastructure=frozenset({SETTLEMENT, SOLVER}),
        contract_accounts=frozenset({NEWPOOL}),
    )

    result = resolve_attribution(TX, ALICE, sell_usdc_buy_weth(ALICE, venue=NEWPOOL), context)

    assert result.method is AttributionMethod.UNRESOLVED
    assert result.portfolio_owner is None
    assert result.portfolio_owner != NEWPOOL


def test_a_one_sided_eoa_signer_does_not_outrank_the_two_sided_trader():
    """Being *an* endpoint is weaker evidence than being on both sides.

    CAROL is a known EOA who paid USDC into the route and received nothing back; BOB is on both
    sides of it. Reading DIRECT_EOA off the sender's mere presence in the endpoint set hands the
    swap to the funder and erases the trader — the gas-payer error with one leg of cover.
    """
    context = AttributionContext(
        infrastructure=frozenset({SOLVER}), eoas=frozenset({CAROL, BOB}),
    )
    transfers = (
        Transfer(token=USDC, from_addr=CAROL, to_addr=NEWPOOL,
                 raw_amount=USDC_1000, log_index=0),
        Transfer(token=USDC, from_addr=NEWPOOL, to_addr=BOB,
                 raw_amount=USDC_1000, log_index=1),
        Transfer(token=WETH, from_addr=BOB, to_addr=NEWPOOL,
                 raw_amount=WETH_HALF, log_index=2),
    )

    result = resolve_attribution(TX, CAROL, transfers, context)

    assert result.portfolio_owner != CAROL
    assert result.portfolio_owner == BOB
    assert result.method is AttributionMethod.ROUTER_RECIPIENT
