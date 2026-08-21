"""What is known about the addresses in one transaction — the input side of attribution.

The context is *evidence*, not configuration. Every field answers a question the resolver would
otherwise have to guess at, and a question left unanswered produces ``UNKNOWN`` or ``UNRESOLVED``
rather than a default. §6.2 excludes routers, aggregators, relayers, bundlers, bridges, treasuries,
vaults, pools, market makers, and CEX hot wallets from the candidate universe *entirely*; that
exclusion is expressed here, before resolution runs, so no later step has to remember it.

The context carries no defaults that could stand in for missing knowledge. An empty context means
"nothing is known", and a resolver given nothing returns ``UNRESOLVED`` — which is the correct
answer, and the one a coverage report can act on.
"""

from dataclasses import dataclass, field
from typing import FrozenSet, Optional, Tuple

from contracts import AccountType

#: Mint and burn legs use the zero address as a counterparty. It is an accounting placeholder, not
#: an account, and must never be recovered as a portfolio owner — a burn leg otherwise makes the
#: zero address look like a two-sided trader in every token launch.
NULL_ADDRESS = "0x" + "0" * 40


def normalise_address(address):
    """Lowercase, with ``None`` collapsing to the empty string.

    Addresses arrive from logs, traces, and vendor tables in mixed case. A checksummed address and
    its lowercase form are the same account, and comparing them raw silently splits one portfolio
    into two.
    """
    return (address or "").strip().lower()


@dataclass(frozen=True)
class SafeExecution:
    """A Safe ``ExecutionSuccess`` observed in the transaction.

    The presence of this record is itself the evidence that the executing account is a Safe. The
    signers are carried so that the resolver can state, in evidence, that they were considered and
    rejected as traders — §6.2 requires signers not to be counted as separate traders, and a rule
    that is applied but not recorded cannot be audited against the golden set.
    """

    safe: str
    signers: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "safe", normalise_address(self.safe))
        object.__setattr__(
            self, "signers", tuple(normalise_address(s) for s in self.signers)
        )
        if not self.safe:
            raise ValueError("a SafeExecution must name the Safe it executed for")
        if self.safe in self.signers:
            raise ValueError(
                "the Safe {} is listed among its own signers; the two roles are distinct and "
                "collapsing them is how a signer becomes a phantom trader".format(self.safe)
            )


@dataclass(frozen=True)
class UserOperation:
    """One ERC-4337 ``UserOperationEvent``.

    ``sender`` is the smart account — the trader. ``bundler`` and ``paymaster`` are infrastructure
    and are recorded only so the resolver can refuse them by name.
    """

    sender: str
    bundler: Optional[str] = None
    paymaster: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(self, "sender", normalise_address(self.sender))
        for name in ("bundler", "paymaster"):
            value = getattr(self, name)
            object.__setattr__(self, name, normalise_address(value) if value else None)
        if not self.sender:
            raise ValueError("a UserOperation must name its sender (the smart account)")

    @property
    def infrastructure_roles(self):
        return tuple(a for a in (self.bundler, self.paymaster) if a)


@dataclass(frozen=True)
class AttributionContext:
    """Address typing plus the per-transaction smart-account evidence.

    The five address sets are deliberately separate rather than one ``Dict[str, AccountType]``:
    contradictions between them are refused at construction, and a single mapping would accept
    "this address is both a Safe and a bundler" without complaint.
    """

    #: Routers, aggregators, solvers and settlement contracts, relayers, bundlers, paymasters,
    #: bridges, treasuries, public vaults, pools, market makers, CEX hot wallets. §6.2 excludes
    #: these from the candidate universe entirely — they are never portfolio owners.
    infrastructure: FrozenSet[str] = frozenset()
    safes: FrozenSet[str] = frozenset()
    smart_accounts: FrozenSet[str] = frozenset()
    #: Code-bearing addresses that are not otherwise typed and that plausibly control one
    #: portfolio. Overlap with ``infrastructure`` is permitted and infrastructure wins: a router
    #: is a contract, and the exclusion is the stronger fact.
    contract_accounts: FrozenSet[str] = frozenset()
    #: Addresses observed to carry no code.
    eoas: FrozenSet[str] = frozenset()

    safe_execution: Optional[SafeExecution] = None
    user_operations: Tuple[UserOperation, ...] = field(default_factory=tuple)

    #: Off by default. When on, an EOA sender with no endpoint evidence resolves to
    #: ``TX_SENDER_FALLBACK`` — flagged, and excluded from the primary metric by
    #: ``Attribution.is_usable_for_primary_metric``. It is never honoured for infrastructure
    #: senders, whatever this flag says: that combination is precisely Dune's
    #: ``coalesce(taker, tx_from)``.
    permit_tx_sender_fallback: bool = False

    _ADDRESS_SETS = ("infrastructure", "safes", "smart_accounts", "contract_accounts", "eoas")

    def __post_init__(self):
        for name in self._ADDRESS_SETS:
            object.__setattr__(
                self,
                name,
                frozenset(
                    a for a in (normalise_address(x) for x in getattr(self, name)) if a
                ),
            )
        object.__setattr__(self, "user_operations", tuple(self.user_operations))

        portfolio = self.safes | self.smart_accounts | self.eoas
        self._refuse_overlap(
            self.infrastructure & portfolio,
            "infrastructure is excluded from the candidate universe entirely (§6.2), so an "
            "address cannot be both infrastructure and a portfolio identity",
        )
        self._refuse_overlap(
            self.eoas & (self.contract_accounts | self.safes | self.smart_accounts),
            "an address cannot be both codeless and a contract account",
        )

    @staticmethod
    def _refuse_overlap(overlap, rule):
        if overlap:
            raise ValueError(
                "{}: {}".format(rule, ", ".join(sorted(overlap)))
            )

    def is_infrastructure(self, address):
        return normalise_address(address) in self.infrastructure

    def account_type(self, address):
        """Type one address. Unknown code status is ``UNKNOWN``, never assumed to be an EOA.

        Order matters: infrastructure is tested first because a router is also a contract, and
        the exclusion must not be reachable through the weaker classification.
        """
        a = normalise_address(address)
        if not a or a == NULL_ADDRESS:
            return AccountType.UNKNOWN
        if a in self.infrastructure:
            return AccountType.INFRASTRUCTURE
        if a in self.safes:
            return AccountType.SAFE
        if a in self.smart_accounts:
            return AccountType.ERC4337
        if a in self.contract_accounts:
            return AccountType.OTHER_CONTRACT
        if a in self.eoas:
            return AccountType.EOA
        return AccountType.UNKNOWN
