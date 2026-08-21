"""What a run is given: transactions before an owner is known, the window, and the horizon.

Attribution is the *first* stage of §4, which means the pipeline cannot be handed
:class:`contracts.Transaction` values — that type already carries a resolved
:class:`contracts.Attribution`, and a caller who supplied one would have answered the question the
first stage exists to ask. So the entry type here is :class:`ObservedTransaction`: the transfers, the
sender, and the per-transaction evidence, with the owner slot still empty.

There is a second entry type, and it exists because the first one cannot be honest about a receipt
nobody could read. :class:`UndecodableTransaction` is the carried status for a transaction whose
logs :mod:`ingest.events` refused — real, in the window, and with an unknown net position. It is a
*type* rather than an exception for one reason: an exception raised during ingestion removes the
transaction from the population before the population is counted, and then no census, no queue and
no coverage report can say a transaction went missing.

Nothing in this module reads a clock, a file, or a network. The horizon, the window bounds, the token
trading starts and the pool snapshots are all supplied, because every one of them is a value a run
must be able to reproduce from its record alone.
"""

from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple

from contracts import NATIVE_ETH, PoolState, Transfer, WETH, normalise_asset

from attribution import AttributionContext, normalise_address

#: §4.4. "For each valid buy, measure the return over the following **30 days**." Thirty days of UTC
#: seconds, pinned as a literal here and asserted against ``2_592_000`` in
#: ``tests/hand_computed/test_pipeline.py`` — a test that spells this as ``30 * 86400`` moves with the
#: constant and pins nothing about it.
#:
#: **Not read from the ticket-11 frozen set, and named as such.** The set carries §4.4's horizon in
#: the unit the document states it in — ``measurement.horizon_days`` = 30 — and this package needs
#: seconds, so reading it here would mean multiplying a frozen value at import time.
#: ``tests/test_frozen_context.py`` flags that as unguarded Decimal arithmetic (it cannot see that a
#: ``DAYS`` parameter is an exact ``int``), and the house rule is that its allowlists stay empty. So
#: the literal stays, and the equality with the frozen value is pinned instead, in
#: ``tests/hand_computed/test_parameters.py`` under ``UNMIGRATED``. A named copy that a test holds
#: equal is a smaller hole than an allowlist entry.
MEASUREMENT_HORIZON_SECONDS = 30 * 24 * 60 * 60


# -- asset-keyed mappings -------------------------------------------------------
#
# A run is configured with four mappings keyed by an asset: the pool book and the price book handed
# to :func:`pipeline.run.run_wallet_window`, and the §4.7 trading starts and migration replacements
# carried by :class:`WindowConfig`. All four are looked up with a *normalised* key, because that is
# the only spelling the stages have — ``normalise_asset`` lowercases and collapses the native-ETH
# sentinel onto WETH (§4.2), and every asset reaching a lookup has been through it.
#
# So the key space of these mappings is the normalised one whether the caller knows it or not, and
# two keys that normalise to one key are one entry. The two functions below make that fact refuse
# rather than resolve itself: without them the collapse happens inside ``dict``, silently, and which
# of the two entries survives is decided by the order the caller's mapping iterates in.
#
# Two keys naming one asset is one half of the identity-key defect. The other half is one key naming
# the wrong asset, and it is checkable exactly when the *value* says which asset it is for. A
# ``PoolState`` does; a price and a ``TokenStart`` do not. :data:`STATES_ITS_ASSET` is where that is
# recorded, once, so the rule reaches every asset-keyed mapping whose values carry an asset rather
# than being written out at the call sites that happen to have been traced.

#: Value types that name, in the value itself, the asset they are for. A key filed against one of
#: these is checkable against it — the mapping is being asked to agree with itself, which is a
#: question about the caller's data structure and not about the world. Read through the MRO, so a
#: derived pool state is still a pool state here.
STATES_ITS_ASSET = {PoolState: lambda pool: pool.asset}


def stated_asset(value):
    """The asset ``value`` says it is for, or ``None`` when its type does not say."""
    for kind in type(value).__mro__:
        reader = STATES_ITS_ASSET.get(kind)
        if reader is not None:
            return reader(value)
    return None


def _normalised(text, described):
    """``normalise_asset(text)``, refusing a non-string here rather than inside the frozen seam.

    ``contracts.normalise_asset`` lowercases, so it raises ``AttributeError`` on anything else — from
    inside the seam, naming neither the mapping nor the key. Every other refusal in this module
    quotes the caller's own spelling, which is the one they can search for, and this keeps that true
    for the one input that used to escape it.
    """
    if not isinstance(text, str):
        raise TypeError(
            "{} must be a str, and is a {}. An asset is an address here and every lookup goes "
            "through contracts.normalise_asset, which lowercases a string — so nothing this run "
            "can produce would ever match it. Refused here rather than left to raise from inside "
            "the frozen seam, where the message would name neither the mapping nor the "
            "key.".format(described, type(text).__name__)
        )
    return normalise_asset(text)


def asset_pairs(mapping):
    """The caller's ``(key, value)`` pairs, in order, with nothing collapsed on the way in.

    ``dict(mapping)`` would be the obvious spelling and is the wrong one: handed a sequence of
    pairs it applies its own last-one-wins rule to a repeated key before anything here can object,
    so the check would be reading a mapping this module built rather than the one the caller
    supplied. A ``Mapping`` cannot repeat a key, but a caller is free to pass pairs and this entry
    point accepts them.
    """
    items = getattr(mapping, "items", None)
    return tuple(items() if callable(items) else mapping)


def asset_keyed(pairs, what):
    """``{normalise_asset(key): value}``, refusing a key that does not identify its entry.

    Two refusals, and they are the two halves of one rule — *the key and the entry it points at
    must identify each other*. Two keys naming one asset is the half where the key is ambiguous;
    one key naming a different asset from the value it holds is the half where it is simply wrong.

    **Two keys, one asset.** The refusal is on the **collision**, not on the two values
    disagreeing. A caller whose key
    space is not normalised has the defect; the entries happening to agree is luck, and a guard
    conditioned on disagreement is the shape that closes a traced instance and leaves the class
    open. :func:`pipeline.run._require_one_transaction_per_hash` refuses the same transaction
    supplied twice on the same ground, and this is that rule one mapping over.

    Refused rather than quarantined, and for the reasons the duplicate hash is: nobody can say
    which of the two entries is *the* entry, so there is no answer to give it; and it is a defect
    in whatever assembled the call rather than a condition the chain produced. What it costs when
    it is not refused, measured on the composed run:

    * **the pool book.** Two spellings of one token, holding pools of different depth: the position
      is marked against whichever arrived last, and a $1,000 lot returns −25% or −50% with nothing
      in the queue, the census or the coverage report to say a book of two entries became one.
    * **the price book.** USDC is priced per *raw* unit, so a checksummed duplicate carrying the
      unscaled price moves every notional in the run by six orders of magnitude while leaving each
      return untouched — the same price scales cost and proceeds together. The published figure
      that moves is the one nobody re-derives.
    * **the replacement pools.** The worst of the four, because the drop produces a
      *measured-looking zero*: a migration the caller configured is not found, the dead primary is
      valued at ``DEAD_ZEROED``, and §10's dead share reports the whole exposure as a measurement.

    **What the collision refusal costs, chosen deliberately and not an oversight.** §4.2 makes ETH
    and WETH one asset, so a price table that quotes both — the ordinary shape of a vendor feed, or
    of any book carrying a zero-address placeholder row beside a real WETH row — is two keys naming
    one asset even when the two prices *agree*. That input ran correctly before this refusal
    existed: measured on the pinned integration day, it published the baseline day's canonical hash
    byte for byte, and it now refuses the whole run and publishes nothing. Kept anyway, because
    admitting it means conditioning the guard on the two values disagreeing, which is the shape that
    closes the traced instance and leaves the class open — and because a caller who reduces the book
    to one row loses nothing: §4.2 has already made the other row redundant. The message says so, so
    that the reader who hits it has the remedy rather than a motive to weaken the check.

    **One key, the wrong asset.** A value that carries the asset it is for — a
    :class:`contracts.PoolState` does, and :data:`STATES_ITS_ASSET` is the list — makes the key
    checkable without this module knowing anything about the world: the mapping is being asked to
    agree with itself. Refused on the same ground as the collision, and it has to be its own rule
    because a collision refusal does nothing about it — one key, one entry, nothing collapses, and
    both spellings of the defect were measured on the composed run:

    * **the key is the wrong half.** ``pools`` or ``replacement_pools`` filed under an address that
      is one hex digit off the pool's own ``asset`` — an ordinary typo, and no collision. The
      token's own lookup misses. On the pool book that is loud (the buy is quarantined,
      *"leaves an open position … and no pool state was supplied"*); on the replacement pools it is
      a wrong number rather than an absent one — ``-1``, ``DEAD_ZEROED``, dead share 1, an empty
      queue, census ``{VALID_BUY: 1}``, and evidence reading ``replacement=none`` about a run that
      supplied one, against a true ``-0.25``.
    * **the value is the wrong half.** ``pools[TOKEN_R] = PoolState(asset=TOKEN_H)`` — the shape of
      a mis-assembled join or an off-by-one ``zip``, with every key correctly spelled. The lookup
      *succeeds* and marks the position against another token's pool: a $1,000 lot published
      ``-0.25`` against a true ``-0.5``, with an identical census, an empty queue and an identical
      coverage report. Nothing is missing, so nothing is loud.

    **A padded key is refused too, and the reason is narrower than it first looks.**
    ``contracts.normalise_asset`` lowercases and collapses the sentinel; it does **not** strip, and
    it is the frozen seam, so it will not start — ``Transfer(token="  0xabc  ")`` keeps its padding
    all the way to the lookup. So ``"  0xabc  "`` in a pool book is not *unmatchable*; it is
    matchable by exactly one thing, a transfer whose token carries the identical padding, and that
    is the same defect one layer down — one asset split into two across netting, FIFO and marking,
    where nothing at this boundary can reach it. Either way the entry is dead to every ordinary
    input, and on the replacement pools a dead entry is a wrong *number* rather than a missing one,
    for the same reason the checksummed key was.

    Refused rather than trimmed for that second half: trimming would give this module a key space
    the seam does not have, so the pool book would quietly start matching a token the rest of the
    run still treats as its own asset.

    **What none of this claims, with what each residue costs, measured.** Nothing here validates
    that a key is an address, and a key that no entry contradicts is admitted whether or not the
    run ever reads it — a price book listing a quote asset the window never traded, or a pool book
    covering more tokens than the run touched, is the ordinary case and must stay legal. What is
    left after the two refusals above, and it was measured rather than reasoned about:

    * **``prices`` and ``token_starts`` state no asset,** so a typo'd key there is caught by
      nothing here. Both are loud one layer down: a mis-keyed price leaves the transaction
      ``UNSUPPORTED`` in the census with the wallet unscorable, and a mis-keyed §4.7 start
      quarantines the buy (*"no §4.7 token trading start was supplied"*). No number is published in
      either case, which is why the pool book was the half worth closing first.
    * **a mis-spelling made twice, in agreement, is not a disagreement.**
      ``replacement_pools[TYPO] = PoolState(asset=TYPO)`` passes both refusals — the mapping agrees
      with itself and it is still unreachable — and it publishes the same measured-looking zero as
      before: ``-1``, ``DEAD_ZEROED``, dead share 1, no queue entry. The same input in the ``pools``
      book quarantines loudly instead. Nothing at this boundary can reach it: the replacement pool
      book is a separate argument from the pool book, and requiring a replacement key to name a
      token the run holds would refuse the legal case above.
    * **a transposed *value* under correctly spelled keys** is closed only where the value states
      its asset. ``token_starts`` values do not: swapping two tokens' ``TokenStart`` values moves
      the §4.7 bucket from D to A — the first-ten-blocks bucket the Edge Origin condition
      measures — with an empty queue and an unchanged ``buy_quality``. See
      :class:`WindowConfig`; it is a wrong value rather than a mis-keyed structure, and no check
      here can see it.

    :param pairs: ``(key, value)`` pairs from :func:`asset_pairs`, in the caller's order.
    :param what: the parameter's name, so the message names the mapping the caller passed.
    :raises TypeError: a key, or a value's stated asset, is not a str.
    :raises ValueError: a key carries surrounding whitespace, two keys normalise to one asset, or a
        key disagrees with the asset its value states it is for.
    """
    for key, _ in pairs:
        text = key if isinstance(key, str) else ""
        if text != text.strip():
            raise ValueError(
                "{}[{!r}] is padded with whitespace. contracts.normalise_asset lowercases and "
                "collapses the native-ETH sentinel but does not strip, and it is the only "
                "normalisation an asset reaching a lookup has been through — so this entry is "
                "reachable by nothing except a transfer whose token carries the same padding, and "
                "the mapping is one entry shorter than the caller believes. Refused rather than "
                "trimmed: trimming here would give this module a key space the seam does not have, "
                "and a padded token in the transfer stream would still be a second asset "
                "everywhere else in the run, where nothing at this boundary can reach "
                "it.".format(what, key)
            )
    order = []
    spellings = {}
    values = {}
    for key, value in pairs:
        canonical = _normalised(key, "{}[{!r}]'s key".format(what, key))
        stated = stated_asset(value)
        if stated is not None:
            described = "{}[{!r}] holds a {}, whose asset".format(
                what, key, type(value).__name__
            )
            if _normalised(stated, described) != canonical:
                raise ValueError(
                    "{}[{!r}] holds a {} that states it is for {!r}. The key and the value name "
                    "two different assets ({} and {} normalised), so the mapping disagrees with "
                    "itself and neither half can be taken as what the caller meant. What it costs "
                    "when it is not refused, both measured on the composed run: if the *key* is "
                    "the wrong half, the token's own lookup misses — and on replacement_pools a "
                    "missed lookup is a wrong number rather than an absent one, because the "
                    "migration is never followed, the dead primary is valued DEAD_ZEROED, the "
                    "position publishes -100%, §10 reports the whole exposure as dead share, and "
                    "the position's own evidence says 'replacement=none' about a run that supplied "
                    "one. If the *value* is the wrong half the lookup succeeds and the position is "
                    "marked against another token's pool: a $1,000 lot published -25% against a "
                    "true -50%, with an identical census, an empty quarantine queue and an "
                    "identical coverage report. Refused rather than resolved, on the same ground as "
                    "two spellings of one asset: the disagreement is the evidence that nobody can "
                    "say which half was meant.".format(
                        what, key, type(value).__name__, stated,
                        canonical, _normalised(stated, described),
                    )
                )
        if canonical not in spellings:
            order.append(canonical)
            spellings[canonical] = []
            values[canonical] = value
        spellings[canonical].append(key)
    collided = [canonical for canonical in order if len(spellings[canonical]) > 1]
    if not collided:
        return {canonical: values[canonical] for canonical in order}
    raise ValueError(
        "{} names {} asset(s) more than once: {}. An asset key is normalised before it is used — "
        "lowercased, and the native-ETH sentinel collapsed onto WETH (§4.2: {} and {} are one "
        "asset) — so two spellings of one asset arrive as two entries and leave as one, and the "
        "last one supplied would have won. That makes the published answer a function of the "
        "order the caller's mapping happens to iterate in, which is not a record a run can be "
        "reproduced from. "
        "Refused rather than resolved: keeping either entry, or refusing only when the two "
        "disagree, would require knowing which spelling the caller meant, and supplying both is "
        "the evidence that nobody does. Supply exactly one of these spellings — §4.2 makes them "
        "one asset, so the other row is redundant even when the two carry the same value, and "
        "removing it costs the run nothing.".format(
            what,
            len(collided),
            "; ".join(
                "{} is named by {} keys: {}".format(
                    canonical,
                    len(spellings[canonical]),
                    ", ".join(repr(key) for key in spellings[canonical]),
                )
                for canonical in collided
            ),
            NATIVE_ETH,
            WETH,
        )
    )


@dataclass(frozen=True)
class ObservedTransaction:
    """One transaction as observed, before an owner has been established.

    ``context`` is per transaction rather than per run because the evidence it carries is: a
    ``SafeExecution`` and a ``UserOperationEvent`` belong to one transaction, and hoisting them to
    the run would attribute one transaction's settlement mechanism to all of them. The address
    typing inside it is genuinely run-level, and a caller sharing one context across transactions
    with no smart-account evidence is doing the ordinary thing.

    ``transfers`` holds :class:`contracts.Transfer` values and nothing else. The type is not
    decoration: ``Transfer.__post_init__`` lowercases both addresses and collapses the native-ETH
    sentinel onto WETH, and every stage downstream is written against a world where that has already
    happened — §4.2 requires ETH and WETH to be one asset before netting, or a route that enters in
    ETH and leaves in WETH nets to two endpoints that are really one.

    The check below is on the **exact type**, and that is the whole of the difference between it and
    a claim. A duck-typed object carrying the same five attribute names satisfies every stage's
    *access* while satisfying none of its *guarantees* — and so does a subclass, which is the case
    an ``isinstance`` check waves through. ``contracts.Transfer`` is a plain frozen dataclass with no
    ``__init_subclass__``, so::

        @dataclass(frozen=True)
        class RawTransfer(Transfer):
            def __post_init__(self): pass      # §4.2's ETH->WETH collapse never runs

    is an ``isinstance(leg, Transfer)`` and reaches netting with the sentinel intact and the
    addresses in whatever case they arrived in. ``type(item) is Transfer`` refuses every derivation
    of it, in any base order, without ``contracts`` needing an ``__init_subclass__`` of its own —
    sealing ``Transfer`` at the seam would be the better place for it, and the seam is frozen.

    **What that guarantees, and what it does not.** It guarantees one thing exactly: the leg's type
    is ``contracts.Transfer`` and not a derivation of it. It does **not** guarantee that
    ``Transfer.__init__`` ever ran — an earlier draft of this paragraph said it did, and three
    ordinary routes were then constructed that satisfy ``type(x) is Transfer`` without it:
    ``object.__new__(Transfer)`` followed by ``object.__setattr__``; ``copy.copy``, ``copy.deepcopy``
    and ``pickle.loads``, all of which go through ``__reduce_ex__`` rather than the constructor
    (``dataclasses.replace`` does re-run it); and ``object.__setattr__(leg, "__class__", Transfer)``
    on an instance of the very subclass this check refuses. ``copy.copy`` in particular is not
    adversarial code. Nor does the check guarantee that the normalisation still holds where the
    constructor *did* run: ``object.__setattr__`` rewrites a field of any Python object.

    The consequence set is the same for all of them, and it is bounded rather than open — measured,
    not argued: a token rewritten back to the native-ETH sentinel is caught downstream by
    ``netting._require_eth_collapsed`` and becomes a quarantine record, while an address rewritten
    to mixed case is caught nowhere — ``netting._owner_flows`` compares it to the owner, does not
    match, and files the leg as someone else's money in the same transaction. Re-deriving each
    leg's normal form here would close both, and would also make netting's own §4.2 refusal
    unreachable through this entry point, which is the only route the composed pipeline has to it.
    So the residue is stated rather than claimed away: this check bounds what *type* of thing may
    enter, not what a caller did to it after the constructor returned.
    """

    tx_hash: str
    block_number: int
    timestamp: int
    success: bool
    tx_sender: str
    transfers: Tuple[Transfer, ...] = ()
    context: AttributionContext = field(default_factory=AttributionContext)

    def __post_init__(self):
        object.__setattr__(self, "tx_hash", (self.tx_hash or "").strip().lower())
        object.__setattr__(self, "tx_sender", normalise_address(self.tx_sender))
        object.__setattr__(self, "transfers", tuple(self.transfers))
        if not self.tx_hash:
            raise ValueError(
                "tx_hash is required: a transaction with no identity cannot be quarantined, "
                "counted in the census, or reconciled against raw chain data afterwards"
            )
        if not self.tx_sender:
            raise ValueError(
                "tx_sender is required: it is recorded alongside the recovered owner (amendment "
                "A6.1) and neither field may stand in for the other"
            )
        for name in ("block_number", "timestamp"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    "{} must be an int; block numbers and UTC seconds are int by seam rule, "
                    "got {}".format(name, type(value).__name__)
                )
        if not isinstance(self.context, AttributionContext):
            raise TypeError(
                "context must be an AttributionContext; attribution has no defaults to fall back "
                "on, and an empty context is how a caller says 'nothing is known'"
            )
        for position, item in enumerate(self.transfers):
            # Exact type, not ``isinstance``. A subclass overriding ``__post_init__`` is an
            # ``isinstance`` and runs none of §4.2's normalisation; see the class docstring.
            if type(item) is not Transfer:
                raise TypeError(
                    "{}: transfers[{}] is a {}, not a contracts.Transfer. The seam type is what "
                    "collapses the native-ETH sentinel onto WETH and lowercases the addresses "
                    "(§4.2); an object that merely carries the same attribute names — or one that "
                    "derives from Transfer and overrides __post_init__ — reaches netting with "
                    "whatever it was handed, and every refusal downstream is written assuming "
                    "that normalisation already happened.".format(
                        self.tx_hash, position, type(item).__name__
                    )
                )


@dataclass(frozen=True)
class UndecodableTransaction:
    """A transaction that exists, touches the wallet, and that this decoder could not read.

    **Why this is a type and not an exception.** ``ingest.events.SIGNATURES`` is a closed registry
    and no registry is ever complete. Every aggregator's fill event, every venue's own settlement
    event and every token standard the seam cannot name is an event the chain is entitled to
    contain and this decoder may never have enumerated. Refusing the whole receipt is the correct
    decode — a partly-read transaction is not a smaller answer, it is a wrong one — but a refusal
    that leaves ingestion as an exception removes the transaction from the run *before the
    population is counted*, and then no census, no queue and no coverage report says a transaction
    went missing. The population a run measures would be silently defined by what the decoder
    happens to know.

    **Widening the registry does not retire this type, and no list of examples here would stay
    true.** An earlier draft of this paragraph named four events as ones the decoder had not
    enumerated; ticket 20 then admitted three of them, and the paragraph went on asserting it. So
    no admitted signature is named here, and
    ``test_the_carried_status_names_no_event_the_decoder_can_now_read`` holds that against
    ``SIGNATURES`` rather than against a reader's memory. The two events that *are* safe to name
    are ``TransferSingle`` and ``TransferBatch``, and they are safe for a structural reason rather
    than a clerical one: they are in ``ingest.events.DECLINED``, refused because ERC-1155's asset
    is the pair ``(contract, id)`` and ``contracts.Transfer`` has one address and no second field.
    Admitting them is a change to the frozen seam, not an entry in a registry — so they will still
    be arriving through this type after the next widening, and the one after that.

    So the refusal becomes a value. An unknown event is not a defect in what assembled the call —
    the caller did nothing wrong, and the chain is allowed to carry events nobody listed — it is a
    limitation of what can be measured, and a limitation is a status the report publishes.

    **It names the log, not just the transaction.** ``topic``, ``contract`` and ``log_index`` are
    the three facts that let a reader act: they say which event to look up, on which contract, at
    which position in the receipt, which is exactly what somebody widening ``SIGNATURES`` needs.
    ``refusal`` is the exception class name and ``detail`` its message, kept so the queue entry
    reads the way the decoder's own refusal read.

    What this type guarantees
    -------------------------

    That the transaction has an identity, a position in time, a sender, and a named reason it could
    not be read — enough to be counted in the census, to be named in the quarantine queue, and to
    be looked up on an explorer.

    What it does not guarantee
    --------------------------

    Anything about what the transaction *did*. It carries no transfers, and it must not be given
    any: the whole point of the refusal is that this receipt's legs are partly unreadable, so the
    net position it moved is unknown. In particular an empty ``transfers`` tuple would be a lie of
    exactly the shape §4 is least able to survive — see
    :func:`pipeline.run.run_wallet_window` for why a transaction in this state is excluded from
    scoring rather than netted as a no-op, and what that exclusion costs.
    """

    tx_hash: str
    block_number: int
    timestamp: int
    tx_sender: str
    #: ``topics[0]`` of the log that could not be decoded — the event signature hash a reader looks
    #: up. ``None`` only when the refusal did not reach a topic at all.
    topic: Optional[str]
    #: The contract that emitted it. A topic is the hash of a *name* and any contract may emit any
    #: hash, so the pair (topic, contract) is the unit somebody widening the registry works with —
    #: ``Withdrawal(address,uint256)`` on WETH and on an arbitrary token are not the same event.
    contract: Optional[str]
    #: Its position in the receipt.
    log_index: Optional[int]
    #: The refusal's class name, e.g. ``"UnknownEvent"``.
    refusal: str
    #: The refusal's own message, verbatim.
    detail: str

    def __post_init__(self):
        object.__setattr__(self, "tx_hash", (self.tx_hash or "").strip().lower())
        object.__setattr__(self, "tx_sender", normalise_address(self.tx_sender))
        if self.topic is not None:
            object.__setattr__(self, "topic", self.topic.strip().lower())
        if self.contract is not None:
            object.__setattr__(self, "contract", normalise_address(self.contract))
        if not self.tx_hash:
            raise ValueError(
                "tx_hash is required: a transaction with no identity cannot be counted in the "
                "census or named in the quarantine queue, and an undecodable transaction that "
                "cannot be named is the exact omission this type exists to prevent"
            )
        if not self.tx_sender:
            raise ValueError(
                "tx_sender is required: it is recorded alongside the recovered owner (amendment "
                "A6.1) and neither field may stand in for the other"
            )
        for name in ("block_number", "timestamp"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    "{} must be an int; block numbers and UTC seconds are int by seam rule, "
                    "got {}".format(name, type(value).__name__)
                )
        if self.log_index is not None and (
            isinstance(self.log_index, bool) or not isinstance(self.log_index, int)
        ):
            raise TypeError(
                "log_index must be an int or None, got {}".format(type(self.log_index).__name__)
            )
        if not self.refusal or not self.detail:
            raise ValueError(
                "{}: an undecodable transaction must carry both the refusal's class and its "
                "message. A queue entry that says only 'could not decode' cannot be worked: the "
                "reader's next action is to widen ingest.events.SIGNATURES or to decide the event "
                "moves no value, and neither is possible without knowing what was "
                "refused.".format(self.tx_hash)
            )

    def describe(self):
        """One line naming what could not be decoded, for a quarantine record's ``reason``."""
        return (
            "ingestion could not decode {}: {} on log {} of contract {}, topic {}. The whole "
            "receipt is refused rather than partly read — a transaction with an unreadable leg has "
            "an unknown net position, and reading the legs that did decode would publish a trade "
            "assembled from half a transaction. Counted here and excluded from scoring; to admit "
            "it, classify the topic in ingest.events.SIGNATURES with moves_value stated. The "
            "decoder's own words: {}".format(
                self.tx_hash, self.refusal,
                "(unstated)" if self.log_index is None else self.log_index,
                self.contract or "(unstated)", self.topic or "(unstated)", self.detail,
            )
        )


@dataclass(frozen=True)
class Window:
    """One walk-forward evaluation window (§6.3), by block and by UTC second.

    Both are carried because the seam pairs every timestamp with a block number, and the two
    stages that consume a window edge want different ones: token age is decided in blocks for
    bucket A (§4.7) and in seconds thereafter.
    """

    index: int
    start_block: int
    start_ts: int
    end_block: int
    end_ts: int

    def __post_init__(self):
        for name in ("index", "start_block", "start_ts", "end_block", "end_ts"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    "{} must be an int, got {}".format(name, type(value).__name__)
                )
        if self.end_block < self.start_block or self.end_ts < self.start_ts:
            raise ValueError(
                "window {} ends before it starts (blocks {}..{}, ts {}..{})".format(
                    self.index, self.start_block, self.end_block, self.start_ts, self.end_ts
                )
            )

    def contains(self, block_number, timestamp):
        """Half-open at the top in neither dimension: §6.3 windows are given by both edges."""
        return (
            self.start_block <= block_number <= self.end_block
            and self.start_ts <= timestamp <= self.end_ts
        )


@dataclass(frozen=True)
class TokenStart:
    """§4.7's Token Trading Start: first usable liquidity **plus** one real swap.

    Not contract creation, and not the current pool's creation. A migration does not reset it, which
    is why it is keyed by token here rather than derived from whatever pool is marking the position.
    """

    block: int
    timestamp: int

    def __post_init__(self):
        for name in ("block", "timestamp"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    "TokenStart.{} must be an int, got {}".format(name, type(value).__name__)
                )


@dataclass(frozen=True)
class WindowConfig:
    """Everything a run needs that is not a transaction, a pool, or a price.

    ``horizon_block`` / ``horizon_ts`` are the **marking horizon**: the paired block and second at
    which every position still open is valued. It is a window-level parameter, and that is a real
    modelling choice rather than an oversight — see :func:`pipeline.run.run_wallet_window` for what
    it costs and what the result reports so the cost stays visible.

    ``token_starts`` maps a token to its §4.7 trading start. A buy of a token with no entry here is
    **quarantined, not bucketed as D**: an unknown-age buy filed outside the first hour is precisely
    the misclassification the Edge Origin condition is trying to measure.

    ``replacement_pools`` maps a token to the pool its liquidity migrated to, if any. Marking
    follows a migration only once the primary has gone quiet and only within one quote asset.

    Both mappings are keyed by :func:`contracts.normalise_asset` on the way in, and looked up the
    same way — the two halves have to agree, and they did not. The keys were stored verbatim while
    the lookups lowercased, so a caller who spelled a token in checksummed form supplied a mapping
    that could never be read: the §4.7 start was reported missing and the buy quarantined as
    unknown-age, and the migration was never followed, so a dead primary pool was valued
    ``DEAD_ZEROED`` and §10 reported the whole exposure as measured-dead. Normalising here closes
    both, and :func:`asset_keyed` refuses the two spellings that closing it would otherwise let
    collapse into one.

    A ``PoolState`` names the asset it is a pool for, so ``replacement_pools`` gets the second half
    of that rule as well: a key that disagrees with ``pool.asset`` is refused rather than stored as
    an entry nothing can read. That is what turns an ordinary typo in a replacement key from a
    published ``-100%`` into a refusal — the measurement is in :func:`asset_keyed`.

    ``token_starts`` does not get it, and the gap is worth naming because it is not the same class.
    ``TokenStart`` carries a block and a second and *not* the token they describe, so there is
    nothing for the key to be checked against. A key that disagrees with the value it holds is
    therefore invisible here, and the case that matters is the transposition: give TOKEN_R's start
    to TOKEN_M and TOKEN_M's to TOKEN_R, both keys spelled correctly, and the §4.7 bucket moves from
    D to A — the first-ten-blocks bucket the Edge Origin condition measures — with an empty
    quarantine queue and an unchanged ``buy_quality``. Closing it would mean changing the shape of
    the input so a ``TokenStart`` names its token; it is not a check this boundary can add.
    """

    horizon_block: int
    horizon_ts: int
    token_starts: Mapping[str, TokenStart] = field(default_factory=dict)
    replacement_pools: Mapping[str, PoolState] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("horizon_block", "horizon_ts"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(
                    "{} must be an int, got {}".format(name, type(value).__name__)
                )
        # Per-entry well-formedness first, then the invariant across entries — the same order
        # ``run_wallet_window`` applies to its transactions, and for the same reason: a statement
        # about a set of entries that are not yet entries is a statement about the wrong thing.
        # The type errors quote the caller's own spelling, which is the one they can search for.
        starts = asset_pairs(self.token_starts)
        for token, start in starts:
            if not isinstance(start, TokenStart):
                raise TypeError(
                    "token_starts[{!r}] must be a TokenStart, got {}".format(
                        token, type(start).__name__
                    )
                )
        replacements = asset_pairs(self.replacement_pools)
        for token, pool in replacements:
            if not isinstance(pool, PoolState):
                raise TypeError(
                    "replacement_pools[{!r}] must be a PoolState, got {}".format(
                        token, type(pool).__name__
                    )
                )
        object.__setattr__(self, "token_starts", asset_keyed(starts, "token_starts"))
        object.__setattr__(
            self, "replacement_pools", asset_keyed(replacements, "replacement_pools")
        )

    def token_start(self, token):
        # type: (str) -> Optional[TokenStart]
        return self.token_starts.get(normalise_asset(token))

    def replacement_pool(self, token):
        # type: (str) -> Optional[PoolState]
        return self.replacement_pools.get(normalise_asset(token))
