"""Recover the economic owner of one transaction, or refuse to.

The rule this module exists to prevent is one line of SQL:

    coalesce(base_trades.taker, base_trades.tx_from) AS taker

That is Dune's core macro. Any project without an explicit taker attributes to the transaction
sender — which for a solver-settled trade is the solver, for an ERC-4337 trade is the bundler, and
for a sponsored trade is whoever paid the gas. The result is a handful of phantom mega-wallets
holding thousands of other people's trades, and the real users missing from the universe entirely.
Both failure directions exist in the same public dataset: CoW's model makes the opposite error and
overwrites ``tx_from`` with the trader.

So this module has exactly one way for ``tx_sender`` to become ``portfolio_owner``:
:func:`_tx_sender_fallback`, which marks the result ``TX_SENDER_FALLBACK`` so that
``Attribution.is_fallback`` is True and §8 excludes it from the primary metric. Every result leaves
through :func:`_finalise`, which re-checks that invariant at runtime, and
``tests/hand_computed/test_attribution.py`` re-checks it against the module's own AST. Structure,
not convention.

Resolution order, strongest evidence first:

    more than one portfolio evidenced -> UNRESOLVED, all of them named
    Safe ExecutionSuccess   -> owner is the Safe; signers are not traders
    ERC-4337 UserOperation  -> owner is the smart account; bundler/paymaster/relayer never are
    sender is a known EOA and an endpoint of the transfers -> owner is that EOA
    exactly one candidate on both sides                    -> owner is that address
    otherwise               -> UNRESOLVED, or an explicitly permitted flagged fallback

The ambiguity step sits at the top, above *every* lane, and counts the transaction sender and the
executing account like any other address, because those are all the same rule seen from different
sides: **who signed, and what executed, is never evidence about who traded.** A batch settling
twenty-five users has twenty-five owners and one owner slot; picking whichever of them paid the
gas — or the Safe that executed for them — publishes that one at full confidence and erases the
rest with no quarantine record. That is the mega-wallet failure arriving through the front door
instead of through ``coalesce``.

How many owners a transaction has is a property of the transaction. It is not a property of the
lane that resolved it, so it cannot be checked inside one: an ``ExecutionSuccess`` or a
``UserOperationEvent`` names *an* account, which is strong evidence about that account and no
evidence at all that the transaction has only one. Running the check per lane made the answer
depend on the settlement mechanism, which is the shape of the bug, not an instance of it.

The counting is deliberately blind to §6.2's exclusion list beyond removing what is on it. An
address is a portfolio here when the context positively types it as one — EOA, Safe, or smart
account — or when an execution event names it. An address that is merely two-sided and untyped is
a venue passing value through, which is what the two-sided test was for, and it can neither be an
owner on its own nor defeat one. Requiring it to be *labelled* infrastructure instead would make
the §8 usable population a function of how complete somebody's label set is — and that list is
never complete for a venue deployed last week, which is exactly when it matters.

An UNRESOLVED result is a legitimate observed outcome and is returned as a typed status.
:func:`require_resolved_attribution` is the variant that raises, for callers that quarantine
rather than count.
"""

from contracts import (
    AccountType,
    Attribution,
    AttributionMethod,
    AttributionUnresolvedError,
    ContractError,
    calc,
)

from .context import NULL_ADDRESS, AttributionContext, normalise_address

#: Pinned per method so two implementations of this seam produce identical records. These are not
#: probabilities to be arithmetic on; they are ordered evidence strengths, and only
#: ``TX_SENDER_FALLBACK`` and ``UNRESOLVED`` are treated specially downstream — through
#: ``is_fallback`` and ``is_usable_for_primary_metric``, never through a confidence threshold.
CONFIDENCE = {
    AttributionMethod.DIRECT_EOA: calc("1"),
    AttributionMethod.SAFE_EXECUTION: calc("1"),
    AttributionMethod.ERC4337_SENDER: calc("1"),
    AttributionMethod.ROUTER_RECIPIENT: calc("0.8"),
    AttributionMethod.TX_SENDER_FALLBACK: calc("0.1"),
    AttributionMethod.UNRESOLVED: calc("0"),
}

#: Positive evidence that an address is a portfolio in its own right rather than something value
#: passed through. ``OTHER_CONTRACT`` and ``UNKNOWN`` are deliberately absent: a code-bearing
#: address nobody has identified is as likely to be a venue as a trader, and treating one as a
#: portfolio is how an unlisted pool became an owner (finding attribution.2).
PORTFOLIO_TYPES = frozenset(
    {AccountType.EOA, AccountType.SAFE, AccountType.ERC4337}
)


class AttributionInvariantError(ContractError):
    """The exit point caught a result this module is not permitted to produce.

    Not a data condition: an unresolvable transaction is ``UNRESOLVED``, and a shaky owner is a
    flagged fallback. This fires only when the resolver itself has a bug — above all, when
    ``tx_sender`` reached ``portfolio_owner`` without being marked as a fallback.
    """


# -- public surface -------------------------------------------------------------


def resolve_attribution(tx_hash, tx_sender, transfers, context):
    """Return the :class:`~contracts.trades.Attribution` for one transaction.

    Never raises for an unattributable transaction — that is ``UNRESOLVED`` with no owner, which
    is a finding. Raises ``ValueError`` only for malformed input (no transaction identity, no
    sender), because such a record cannot be quarantined, audited, or reconciled against raw chain
    data afterwards.
    """
    tx_hash = (tx_hash or "").strip().lower()
    if not tx_hash:
        raise ValueError(
            "tx_hash is required: an attribution without a transaction identity cannot be "
            "quarantined or reconciled against raw chain data"
        )
    sender = normalise_address(tx_sender)
    if not sender:
        raise ValueError(
            "tx_sender is required: it is recorded alongside the recovered owner (amendment "
            "A6.1) and neither field may stand in for the other"
        )
    if not isinstance(context, AttributionContext):
        raise TypeError(
            "context must be an AttributionContext; attribution has no defaults to fall back on"
        )

    transfers = tuple(transfers or ())
    endpoints = _economic_endpoints(transfers)
    candidates = [endpoint.address for endpoint in _candidate_owners(endpoints, context)]
    owners = _evidenced_owners(candidates, context)

    # Ambiguity is settled here, once, before a lane is chosen — and without consulting the
    # sender or the executing account, both of which are answers to a different question.
    # Checking it inside the transfer lane made the refusal conditional on the settlement
    # mechanism: the same twenty-five-user batch was refused when a solver submitted it and
    # published as one owner at confidence 1 when a Safe executed it or a bundler carried it.
    if len(owners) > 1:
        return _several_owners(tx_hash, sender, owners, candidates, context)

    if context.safe_execution is not None:
        return _resolve_safe(tx_hash, sender, context)
    if context.user_operations:
        return _resolve_user_operations(tx_hash, sender, context)

    set_aside = ()
    if len(candidates) > 1:
        if len(owners) != 1:
            # More than one owner was refused above, so the transaction contains no portfolio at
            # all: several two-sided addresses, none of them typed, and nothing to rank them by.
            return _no_owner_among_several(tx_hash, sender, candidates, context)
        # Exactly one of them is a portfolio and the rest are venues value passed through. They
        # are named in the evidence rather than dropped, so a reviewer can see what was set aside.
        # Narrowed by filtering the candidate list rather than by assigning the owner into it: the
        # two lanes above have already returned, so the sole owner can only have come from these
        # candidates, and if that ever stops being true this refuses instead of inventing an owner
        # that no transfer puts in the transaction.
        set_aside = tuple(sorted(a for a in candidates if a != owners[0]))
        candidates = [a for a in candidates if a == owners[0]]

    direct = _resolve_direct_eoa(tx_hash, sender, endpoints, candidates, set_aside, context)
    if direct is not None:
        return direct

    recipient = _resolve_single_recipient(tx_hash, sender, candidates, set_aside, context)
    if recipient is not None:
        return recipient

    return _resolve_fallback_or_refuse(tx_hash, sender, candidates, context)


def require_resolved_attribution(tx_hash, tx_sender, transfers, context):
    """As :func:`resolve_attribution`, but raise ``AttributionUnresolvedError`` on UNRESOLVED.

    For callers that quarantine the transaction rather than counting it. A flagged fallback is
    *not* raised on: it is a usable record that ``is_usable_for_primary_metric`` already excludes,
    and turning it into an exception would hide it from the standing fallback-rate metric.
    """
    result = resolve_attribution(tx_hash, tx_sender, transfers, context)
    if result.method is AttributionMethod.UNRESOLVED:
        raise AttributionUnresolvedError(
            "{}: economic owner could not be established and must not be guessed. {}".format(
                tx_hash, " ".join(result.evidence)
            )
        )
    return result


# -- resolution steps -----------------------------------------------------------


def _resolve_safe(tx_hash, tx_sender, context):
    """§6.2: portfolio identity is the Safe address; signers are not separate traders."""
    execution = context.safe_execution
    safe = execution.safe

    if safe == NULL_ADDRESS:
        # The endpoint set filters the zero address, so the event lanes are the only way it can
        # reach an owner. Nothing between the log and here rejects it: it is a non-empty string,
        # it is not on the infrastructure list, and ``account_type`` reports UNKNOWN rather than
        # refusing. Without this, a malformed ExecutionSuccess publishes the mint/burn placeholder
        # as a Safe portfolio at confidence 1.
        return _unresolved(
            tx_hash, tx_sender, context,
            "the executing Safe is recorded as the zero address; that is a mint/burn accounting "
            "placeholder, not an account, and never a portfolio",
        )
    if context.is_infrastructure(safe):
        return _unresolved(
            tx_hash, tx_sender, context,
            "executing Safe {} is on the infrastructure list; a shared multisig is not one "
            "portfolio and §6.2 excludes it from the candidate universe".format(safe),
        )

    foreign = sorted({op.sender for op in context.user_operations} - {safe})
    if foreign:
        return _unresolved(
            tx_hash, tx_sender, context,
            "conflicting execution evidence: Safe {} executed while user operation sender(s) {} "
            "are present; one transaction cannot carry two owners".format(
                safe, ", ".join(foreign)
            ),
        )

    evidence = [
        "Safe ExecutionSuccess: portfolio identity is the Safe address {}".format(safe),
        "signer(s) {} considered and rejected as traders (§6.2)".format(
            ", ".join(execution.signers) or "none recorded"
        ),
    ]
    if context.user_operations:
        evidence.append(
            "user operation sender matches the Safe (4337 module); bundler and paymaster excluded"
        )
    return _finalise(
        tx_hash=tx_hash,
        tx_sender=tx_sender,
        owner=safe,
        account_type=AccountType.SAFE,
        method=AttributionMethod.SAFE_EXECUTION,
        evidence=tuple(evidence),
        context=context,
    )


def _resolve_user_operations(tx_hash, tx_sender, context):
    """§6.2: owner is the smart account sender; bundler, paymaster, relayer never are."""
    operations = context.user_operations
    senders = []
    for operation in operations:
        if operation.sender not in senders:
            senders.append(operation.sender)

    if len(senders) > 1:
        return _unresolved(
            tx_hash, tx_sender, context,
            "bundle carries {} user operations with distinct senders ({}); per-transaction "
            "attribution is ambiguous and the bundler is not the trader".format(
                len(senders), ", ".join(sorted(senders))
            ),
        )

    account = senders[0]
    infrastructure_roles = sorted(
        {role for operation in operations for role in operation.infrastructure_roles}
    )

    if account == NULL_ADDRESS:
        # Same hole as the Safe lane: the zero address survives UserOperation construction and
        # every check below, and would be published as a smart account at confidence 1.
        return _unresolved(
            tx_hash, tx_sender, context,
            "the user operation sender is recorded as the zero address; that is a mint/burn "
            "accounting placeholder, not a smart account",
        )
    if context.is_infrastructure(account):
        return _unresolved(
            tx_hash, tx_sender, context,
            "user operation sender {} is on the infrastructure list; infrastructure is excluded "
            "from the candidate universe entirely (§6.2)".format(account),
        )
    if account in infrastructure_roles:
        return _unresolved(
            tx_hash, tx_sender, context,
            "user operation sender {} is also recorded as bundler or paymaster; the trader "
            "cannot be distinguished from the infrastructure that carried it".format(account),
        )

    # Account typing comes from the UserOperationEvent itself rather than from code presence: an
    # EIP-7702 delegated EOA is a valid 4337 sender and looks codeless, so refusing on "no code"
    # would reject a real trader.
    return _finalise(
        tx_hash=tx_hash,
        tx_sender=tx_sender,
        owner=account,
        account_type=AccountType.ERC4337,
        method=AttributionMethod.ERC4337_SENDER,
        evidence=(
            "ERC-4337 UserOperationEvent: owner is the smart account sender {}".format(account),
            "bundler/paymaster {} never recorded as the trader (§6.2)".format(
                ", ".join(infrastructure_roles) or "not recorded"
            ),
        ),
        context=context,
    )


def _candidate_owners(endpoints, context):
    """Addresses this transaction *could* have been for, in first-appearance order.

    Two-sided — both sent and received non-fee value — is the module's one piece of transfer-derived
    ownership evidence. §6.2 then removes infrastructure, which is excluded from the candidate
    universe entirely.

    This is a weak test on its own, and knowing why bounds what may be built on it: a trader ends
    up on both ends of a swap, but so does the venue it swapped against, and so does every hop in
    between. Which of them is the portfolio is decided by :func:`_evidenced_owners`, on the
    context's typing, not here. Being a candidate is therefore never sufficient to be an owner
    while another candidate is a typed portfolio.

    The transaction sender is **not** removed here. It is a candidate on exactly the same terms as
    everyone else, because whether an address traded is a question about the transfers, not about
    who paid the gas. Removing it (as the single-recipient step used to) turns a two-owner
    transaction into a one-owner transaction and hands the answer to the counterparty.
    """
    return [
        endpoint for endpoint in endpoints.values()
        if endpoint.sent
        and endpoint.received
        and not context.is_infrastructure(endpoint.address)
    ]


def _evidenced_owners(candidates, context):
    """Every distinct portfolio this transaction carries evidence for, first appearance first.

    Two kinds of evidence, and they count the same here because the question is only *how many*:

    * an address that is two-sided in the transfers **and** positively typed as a portfolio
      identity — a trader ends up on both ends of a swap, and the typing is what separates it from
      the venue that also does;
    * an address named by an ``ExecutionSuccess`` or a ``UserOperationEvent`` — the event names it
      directly, which is why those lanes outrank the transfer-derived ones once the count is one.

    Infrastructure and the null address are dropped from both. They are excluded from the
    candidate universe entirely (§6.2), so their presence is never evidence of a second owner, and
    naming one in a refusal would read as though a portfolio had been found and discarded.
    """
    owners = []

    def add(address):
        if not address or address == NULL_ADDRESS:
            return
        if context.is_infrastructure(address):
            return
        if address not in owners:
            owners.append(address)

    for address in candidates:
        if context.account_type(address) in PORTFOLIO_TYPES:
            add(address)
    if context.safe_execution is not None:
        add(context.safe_execution.safe)
    for operation in context.user_operations:
        add(operation.sender)
    return owners


def _several_owners(tx_hash, tx_sender, owners, candidates, context):
    """More than one address is a portfolio here, so none of them is *the* portfolio.

    An ``Attribution`` carries one owner. A batched settlement carries several, and there is no
    evidence in the transaction that ranks them — least of all the signature, which for a batch
    belongs to whoever submitted it, or the execution event, which for a batch belongs to whatever
    settled it. Refusing keeps the transaction in the population as a counted ``UNRESOLVED`` with
    every owner named, so the reconciliation queue can see who was dropped; resolving one of them
    would delete the rest from the universe silently.
    """
    named = sorted(set(owners))
    reason = (
        "{} addresses in this transaction carry portfolio evidence ({}); an Attribution has one "
        "owner slot and nothing here ranks them, so neither the address that signed it nor the "
        "account that executed it is thereby the trader (§6.2)".format(
            len(named), ", ".join(named)
        )
    )
    also = sorted(set(candidates) - set(named))
    if also:
        reason += "; also on both sides of the transfers, untyped: {}".format(", ".join(also))
    return _unresolved(tx_hash, tx_sender, context, reason)


def _no_owner_among_several(tx_hash, tx_sender, candidates, context):
    """Several addresses passed value both ways and the context types none of them as a portfolio.

    On this lane two-sidedness is the whole of the evidence, so with nothing to rank them by there
    is no owner to recover. Resolving to whichever one is not the sender is how an unlisted pool
    became a portfolio at confidence 0.8 (finding attribution.2).
    """
    addresses = sorted(set(candidates))
    return _unresolved(
        tx_hash, tx_sender, context,
        "{} addresses are on both sides of the transfers ({}) and the context types none of them "
        "as a portfolio; two-sidedness alone does not separate a trader from the venue it traded "
        "against, and the address that signed it is not thereby the trader (§6.2)".format(
            len(addresses), ", ".join(addresses)
        ),
    )


def _set_aside_evidence(set_aside):
    if not set_aside:
        return ()
    return (
        "{} further address(es) on both sides of the transfers ({}) are typed as neither an EOA, "
        "a Safe, nor a smart account, and were read as venues rather than owners".format(
            len(set_aside), ", ".join(set_aside)
        ),
    )


def _resolve_direct_eoa(tx_hash, tx_sender, endpoints, candidates, set_aside, context):
    """The sender is a known EOA and is itself an economic endpoint of the transaction.

    The owner value is read out of the endpoint set, not copied from the ``tx_sender`` parameter —
    the same evidence any other method must produce.

    Being *an* endpoint is not enough when somebody else in the transaction is on both sides of it:
    a known EOA that only paid into a route is a funder, and reading the swap off its presence in
    the endpoint set hands the trade to whoever supplied the money and erases the trader.
    """
    if context.account_type(tx_sender) is not AccountType.EOA:
        return None
    endpoint = endpoints.get(tx_sender)
    if endpoint is None:
        return None
    if candidates and tx_sender not in candidates:
        return None
    return _finalise(
        tx_hash=tx_hash,
        tx_sender=tx_sender,
        owner=endpoint.address,
        account_type=AccountType.EOA,
        method=AttributionMethod.DIRECT_EOA,
        evidence=(
            "sender is a known EOA and an economic endpoint of the transaction "
            "(sent={}, received={})".format(endpoint.sent, endpoint.received),
        ) + _set_aside_evidence(set_aside),
        context=context,
    )


def _resolve_single_recipient(tx_hash, tx_sender, candidates, set_aside, context):
    """Router-, aggregator-, or solver-settled: the one candidate address on both sides.

    Ambiguity has already been decided upstream, over a candidate set that counted the sender, so
    at most one candidate survives to here. Skipping a candidate that *is* the sender is therefore
    not a filter on the evidence any more — it only chooses between two ways of describing the same
    single-owner transaction. A sender that genuinely traded for itself was resolved as
    ``DIRECT_EOA`` one step above on stronger evidence; a sender this step cannot type is refused
    below rather than inferred, because inferring it is ``coalesce(taker, tx_from)`` under a new
    name.
    """
    others = [candidate for candidate in candidates if candidate != tx_sender]
    if len(others) != 1:
        return None

    owner = others[0]
    return _finalise(
        tx_hash=tx_hash,
        tx_sender=tx_sender,
        owner=owner,
        account_type=context.account_type(owner),
        method=AttributionMethod.ROUTER_RECIPIENT,
        evidence=(
            "sole candidate address on both sides of the transfers: {}".format(owner),
            "transaction sender {} was routed through and is not the beneficiary".format(
                tx_sender
            ),
        ) + _set_aside_evidence(set_aside),
        context=context,
    )


def _resolve_fallback_or_refuse(tx_hash, tx_sender, candidates, context):
    """The last step. Refuses by default; falls back only when explicitly permitted and safe."""
    sender_type = context.account_type(tx_sender)
    # Counted over candidates rather than over every endpoint: a venue on both sides of a swap is
    # not owner evidence, and reporting it as such made the refusal reason read as though a
    # candidate had been found and discarded.
    two_sided = len(candidates)

    if sender_type is AccountType.INFRASTRUCTURE:
        # Refused even when the fallback is permitted. Flagging would not be enough: a flagged
        # phantom whale still enters the universe measurement carrying other people's trades.
        return _unresolved(
            tx_hash, tx_sender, context,
            "sender {} is infrastructure and no owner evidence was found; the tx-sender fallback "
            "is refused outright for infrastructure senders".format(tx_sender),
        )
    if not context.permit_tx_sender_fallback:
        return _unresolved(
            tx_hash, tx_sender, context,
            "no owner evidence ({} candidate address(es) on both sides of the transfers) and the "
            "tx-sender fallback was not permitted".format(two_sided),
        )
    if sender_type is not AccountType.EOA:
        return _unresolved(
            tx_hash, tx_sender, context,
            "sender {} is typed {} — a contract whose economic controller is unidentified is "
            "excluded (§6.2) rather than assumed to be a portfolio".format(
                tx_sender, sender_type.value
            ),
        )
    return _tx_sender_fallback(tx_hash, tx_sender, two_sided, context)


def _tx_sender_fallback(tx_hash, tx_sender, two_sided, context):
    """The **only** place ``tx_sender`` may be written into ``portfolio_owner``.

    It is marked ``TX_SENDER_FALLBACK``, so ``is_fallback`` is True, ``is_usable_for_primary_metric``
    is False, and the standing fallback-rate metric counts it.
    """
    return _finalise(
        tx_hash=tx_hash,
        tx_sender=tx_sender,
        owner=tx_sender,
        account_type=AccountType.EOA,
        method=AttributionMethod.TX_SENDER_FALLBACK,
        evidence=(
            "no endpoint evidence ({} candidate address(es) on both sides); fell back to the "
            "transaction sender".format(two_sided),
            "flagged as a fallback and excluded from the primary metric (§8)",
        ),
        context=context,
    )


def _unresolved(tx_hash, tx_sender, context, reason):
    return _finalise(
        tx_hash=tx_hash,
        tx_sender=tx_sender,
        owner=None,
        account_type=AccountType.UNKNOWN,
        method=AttributionMethod.UNRESOLVED,
        evidence=(reason,),
        context=context,
    )


# -- endpoints ------------------------------------------------------------------


class _Endpoint(object):
    """One address's economic participation in a transaction. Fee legs excluded."""

    __slots__ = ("address", "sent", "received")

    def __init__(self, address):
        self.address = address
        self.sent = 0
        self.received = 0


def _economic_endpoints(transfers):
    """Addresses that moved value, in order of first appearance.

    Excluded, each for a reason that has bitten a published pipeline:

    * ``is_fee`` legs — §4.2: fee and referral transfers must not be mistaken for endpoints, or
      the fee collector becomes the trader.
    * zero-amount legs — approvals and no-op events carry no economic evidence.
    * self-transfers — they would make any address look two-sided.
    * the null address — a mint or burn counterparty is not an account.
    """
    endpoints = {}

    def touch(address, direction):
        if not address or address == NULL_ADDRESS:
            return
        endpoint = endpoints.get(address)
        if endpoint is None:
            endpoint = endpoints[address] = _Endpoint(address)
        setattr(endpoint, direction, getattr(endpoint, direction) + 1)

    for transfer in transfers:
        if transfer.is_fee or transfer.raw_amount <= 0:
            continue
        if transfer.from_addr == transfer.to_addr:
            continue
        touch(transfer.from_addr, "sent")
        touch(transfer.to_addr, "received")

    return endpoints


# -- the single exit point ------------------------------------------------------


def _finalise(tx_hash, tx_sender, owner, account_type, method, evidence, context):
    """Build the Attribution, after re-checking the invariants at runtime.

    Every return in this module goes through here, which is what makes the tx-sender rule
    structural: there is one place where an owner can be written, and it refuses the shapes this
    module is not allowed to produce.
    """
    if method is AttributionMethod.UNRESOLVED:
        if owner is not None:
            raise AttributionInvariantError("UNRESOLVED must not carry an owner")
        if account_type is not AccountType.UNKNOWN:
            raise AttributionInvariantError(
                "UNRESOLVED has no owner, so it has no account type to report"
            )
    elif owner is None:
        raise AttributionInvariantError(
            "{} produced no owner; a missing owner is UNRESOLVED, not a resolved "
            "result with a hole in it".format(method.value)
        )

    if owner is not None:
        if owner == tx_sender and method is AttributionMethod.ROUTER_RECIPIENT:
            # ROUTER_RECIPIENT is the one *inferred* method — no event names the owner, the
            # resolver deduces it. It is therefore the only path where the sender could be
            # promoted without evidence, so it is the path the runtime guard bites on. The three
            # remaining methods each name the owner from an independent source (the endpoint set,
            # an ExecutionSuccess, a UserOperationEvent), and an owner that happens to equal the
            # sender there is a real EIP-7702 or self-bundling account, not a coalesce.
            raise AttributionInvariantError(
                "ROUTER_RECIPIENT promoted the transaction sender {} to owner. That is "
                "coalesce(taker, tx_from): it manufactures phantom mega-wallets and erases the "
                "real users.".format(tx_sender)
            )
        if owner == NULL_ADDRESS:
            # Backstop for the two event lanes, in the same shape as the infrastructure guard
            # below: the resolution step refuses the zero address as a data finding, and the exit
            # point refuses it as a structural one, so a future lane cannot reintroduce it by
            # forgetting.
            raise AttributionInvariantError(
                "the zero address is a mint/burn accounting placeholder, not an account, and can "
                "never be a portfolio owner"
            )
        if context.is_infrastructure(owner):
            raise AttributionInvariantError(
                "{} is infrastructure and is excluded from the candidate universe entirely "
                "(§6.2); it can never be a portfolio owner".format(owner)
            )
        if account_type is AccountType.INFRASTRUCTURE:
            raise AttributionInvariantError(
                "an owner may not be typed INFRASTRUCTURE"
            )

    if not evidence:
        raise AttributionInvariantError(
            "every attribution carries evidence naming the rule it applied; an unexplained "
            "result cannot be audited against the golden set"
        )

    return Attribution(
        tx_hash=tx_hash,
        tx_sender=tx_sender,
        portfolio_owner=owner,
        account_type=account_type,
        method=method,
        confidence=CONFIDENCE[method],
        evidence=tuple(evidence),
    )
