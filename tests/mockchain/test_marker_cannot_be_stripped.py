"""Every way to get the marker off, tried — and the four that work, named.

``tools/mockchain/provenance.py`` claims the marker is *indelible in the only sense that matters*:
it is not attached to the identifier, it **is** the identifier, so removing it does not yield the
same run without a label — it yields a different wallet, a different pool and a different payload
hash. This file performs the rewrites rather than accepting the adjective.

The file is in two halves and the second half is the important one.

**What holds.** The marker reaches the published payload through netting, FIFO, marking, scoring
and reporting, it is inside the hashed bytes rather than beside them, and every attempt below to
publish an artifact without it is refused: a report genuinely built over an unmarked wallet, a
report rewritten after assembly with ``object.__setattr__``, an identifier laundered through a
``str`` round trip, and a ``reporting.WalletReport`` rebuilt without its constructor.

**What does not hold, measured rather than admitted.** :func:`audit_payload_provenance` can be
walked past four ways, and each has a test here that *demonstrates the walk-past succeeding*:

1. ``addresses_in`` collects strings by ``value.startswith("0x")``, which is case-sensitive. A real
   address spelled ``0X…`` is not address-shaped to it and is never checked.
2. Any of the five :data:`PERMITTED_UNMARKED` addresses substituted for a wallet passes by design —
   the §4.6 quote assets must be real, so they cannot be marked, so they cannot be refused.
3. The check reads ``value.startswith``, which a ``str`` subclass may override. A subclass whose
   text is a real address and whose ``startswith`` returns ``True`` audits clean and serialises the
   real address.
4. An address embedded in a longer string — ``"wallet 0xabc…"`` — is not address-shaped either.

None of the four is fixable *here*: 1 and 4 are the deliberate looseness ``addresses_in``'s
docstring describes, 2 is the §4.6 exception the whole module is built around, and 3 is Python. They
are pinned so that "cannot be walked past" is never what anyone believes, and so that a later
tightening of ``addresses_in`` has a test that goes red when it changes behaviour.
"""

import copy
import dataclasses
import json

import pytest

from attribution import AttributionContext
from contracts import NATIVE_ETH, QUOTE_ASSETS, Transfer, WETH, to_canonical_json
from pipeline import ObservedTransaction

from tools.mockchain import report as report_module
from tools.mockchain import run_synthetic_window, synthetic_report
from tools.mockchain.chain import (
    INFRASTRUCTURE,
    SELECTED_WALLETS,
    WALLET_ONE_TRADE,
)
from tools.mockchain.provenance import (
    IDENTIFIER_PREFIX,
    MARKER,
    PERMITTED_UNMARKED,
    SyntheticProvenanceLost,
    addresses_in,
    audit_payload_provenance,
    is_synthetic_identifier,
    publish_synthetic_artifact,
)
from tools.mockchain.report import SyntheticRun

from conftest import SEED

#: A perfectly ordinary-looking mainnet address, and not one this package minted.
BARE_HEX = "0x" + "ab" * 20


# -- helpers --------------------------------------------------------------------


def _rewrite(value, old, new):
    """A copy of an already-canonicalised payload with every occurrence of ``old`` replaced.

    Keys as well as values: :func:`addresses_in` walks both, so a rewrite that only touched values
    would be testing a narrower thing than the check covers.
    """
    if isinstance(value, str):
        return new if value == old else value
    if isinstance(value, dict):
        return {_rewrite(k, old, new): _rewrite(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [_rewrite(item, old, new) for item in value]
    return value


def _payload_copy(run):
    return copy.deepcopy(run.payload)


def _chain_with_one_unmarked_wallet(chain):
    """The same generated chain, with one wallet's identifier replaced by a bare hex address.

    This is not a rewrite of a finished report: the pipeline runs over the unmarked identifier and
    the reporting layer assembles a genuine §10 report around it. It is the case where the *source*
    stopped marking, which the module docstring names as one of the two things an unmarked address
    can mean.
    """
    def relabel(tx):
        if tx.tx_sender != WALLET_ONE_TRADE:
            return tx
        legs = tuple(
            Transfer(
                token=leg.token,
                from_addr=BARE_HEX if leg.from_addr == WALLET_ONE_TRADE else leg.from_addr,
                to_addr=BARE_HEX if leg.to_addr == WALLET_ONE_TRADE else leg.to_addr,
                raw_amount=leg.raw_amount, log_index=leg.log_index, is_fee=leg.is_fee,
            )
            for leg in tx.transfers
        )
        return ObservedTransaction(
            tx_hash=tx.tx_hash, block_number=tx.block_number, timestamp=tx.timestamp,
            success=True, tx_sender=BARE_HEX, transfers=legs,
            context=AttributionContext(
                eoas=frozenset({BARE_HEX}), infrastructure=INFRASTRUCTURE
            ),
        )

    forward = dict(chain.forward_valid_buys)
    forward[BARE_HEX] = forward[WALLET_ONE_TRADE]
    baseline = dict(chain.baseline_valid_buys)
    baseline[BARE_HEX] = baseline[WALLET_ONE_TRADE]
    return dataclasses.replace(
        chain,
        transactions=tuple(relabel(tx) for tx in chain.transactions),
        forward_valid_buys=forward,
        baseline_valid_buys=baseline,
    )


# -- what the marker is ---------------------------------------------------------


def test_every_minted_identifier_carries_the_marker_in_its_own_text(chain):
    """Wallets, tokens, pools and transaction hashes. The quote assets are the stated exception."""
    for transaction in chain.transactions:
        assert is_synthetic_identifier(transaction.tx_hash)
        assert is_synthetic_identifier(transaction.tx_sender)
        for leg in transaction.transfers:
            for address in (leg.token, leg.from_addr, leg.to_addr):
                assert is_synthetic_identifier(address) or address in PERMITTED_UNMARKED, address
    for asset, pool in chain.pools.items():
        assert is_synthetic_identifier(asset)
        assert is_synthetic_identifier(pool.address)
        assert pool.quote in PERMITTED_UNMARKED


def test_the_unmarked_addresses_are_exactly_the_four_quote_assets_and_the_sentinel():
    """The exception is a list, not a habit — so it is pinned as a list."""
    assert PERMITTED_UNMARKED == frozenset(QUOTE_ASSETS | {NATIVE_ETH})
    assert len(PERMITTED_UNMARKED) == 5
    assert WETH in PERMITTED_UNMARKED
    assert not any(is_synthetic_identifier(address) for address in PERMITTED_UNMARKED)


def test_the_marker_is_not_hexadecimal_and_is_the_width_of_an_address(chain):
    for wallet in SELECTED_WALLETS:
        assert len(wallet) == 42
        assert wallet.startswith(IDENTIFIER_PREFIX)
        body = wallet[2:]
        assert any(character not in "0123456789abcdef" for character in body), (
            "a minted identifier must be un-parseable as hex, or it could collide with a real "
            "address: {}".format(wallet)
        )
    assert MARKER == "synthetic"


# -- the marker through the pipeline --------------------------------------------


def test_the_marker_survives_netting(result):
    for trade in result.results:
        assert is_synthetic_identifier(trade.tx_hash)
        assert is_synthetic_identifier(trade.portfolio_owner)
        if trade.bought_asset is not None:
            assert is_synthetic_identifier(trade.bought_asset) or (
                trade.bought_asset in PERMITTED_UNMARKED
            )
        if trade.quote_asset is not None:
            assert trade.quote_asset in PERMITTED_UNMARKED


def test_the_marker_survives_fifo_and_marking(result):
    for account in result.accounts:
        assert is_synthetic_identifier(account.buy.tx_hash)
        assert is_synthetic_identifier(account.buy.portfolio_owner)
        assert is_synthetic_identifier(account.buy.bought_asset)
        if account.position is not None:
            venue = [
                item for item in account.position.evidence if item.startswith("venue=")
            ]
            assert venue, account.position.evidence
            assert is_synthetic_identifier(venue[0].split("=", 1)[1])


def test_the_marker_survives_scoring(result):
    for wallet in result.wallets:
        assert is_synthetic_identifier(wallet.wallet)
        if wallet.quality is not None:
            assert is_synthetic_identifier(wallet.quality.wallet)


def test_the_marker_survives_reporting_into_every_block(run):
    report = run.report
    for wallet in report.basket.wallets:
        assert is_synthetic_identifier(wallet.wallet)
    for wallet, _state in report.churn.states:
        assert is_synthetic_identifier(wallet)
    # The capital ladder carries no identifier at all — ``CapitalLevelReport`` is aggregates only,
    # so the §4.5 block contributes nothing to the payload's address surface. Asserted rather than
    # skipped: if a per-wallet row is ever added to that block, this line stops being true and the
    # address count below stops being the whole story.
    assert not any(
        "wallet" in field and field != "n_wallets"
        for level in report.capital_ladder.levels
        for field in level.__dataclass_fields__
    )
    for item in report.diagnostics.items:
        for row in getattr(item, "rows", ()):
            assert is_synthetic_identifier(row.wallet)


def test_the_marker_reaches_the_published_payload_and_nothing_unmarked_does(run):
    addresses = addresses_in(run.payload)
    assert addresses == run.addresses
    assert addresses, "a payload with no address-shaped string proves nothing about the marker"
    assert all(is_synthetic_identifier(address) for address in addresses)
    # Ten wallets: the nine that traded, plus the silent one that the churn block carries. No
    # token, pool or transaction hash reaches §10's blocks, so the payload's whole address surface
    # is the selected population.
    assert len(addresses) == len(SELECTED_WALLETS) == 10


def test_the_marker_is_inside_the_hashed_bytes_not_beside_them(run):
    """Rewriting one identifier changes the hash. That is what "it is the value" means."""
    marked = run.addresses[0]
    tampered = _rewrite(_payload_copy(run), marked, BARE_HEX)
    assert tampered != run.payload
    original = json.dumps(run.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    rewritten = json.dumps(tampered, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert original != rewritten
    import hashlib
    assert hashlib.sha256(original.encode("utf-8")).hexdigest() == run.payload_hash
    assert hashlib.sha256(rewritten.encode("utf-8")).hexdigest() != run.payload_hash


# -- the three strip attempts the brief names -----------------------------------


def test_a_report_genuinely_built_over_an_unmarked_wallet_is_refused_at_publication(chain):
    """The source stopped marking. Everything downstream ran normally; publication did not."""
    unmarked = _chain_with_one_unmarked_wallet(chain)
    result = run_synthetic_window(unmarked)
    assert BARE_HEX in {wallet.wallet for wallet in result.wallets}
    report = report_module._assemble(unmarked, result)
    with pytest.raises(SyntheticProvenanceLost) as raised:
        publish_synthetic_artifact(report)
    message = str(raised.value)
    assert BARE_HEX in message
    assert IDENTIFIER_PREFIX in message
    assert "Publishing nothing" in message


def test_a_report_rewritten_after_assembly_is_refused_at_publication():
    """``object.__setattr__`` rewrites a field of any Python object. The bytes are read anyway."""
    report = synthetic_report(SEED).report
    victim = report.basket.wallets[0]
    object.__setattr__(victim, "wallet", BARE_HEX)
    assert report.basket.wallets[0].wallet == BARE_HEX
    with pytest.raises(SyntheticProvenanceLost) as raised:
        publish_synthetic_artifact(report)
    assert BARE_HEX in str(raised.value)


def test_a_wallet_report_rebuilt_without_its_constructor_is_refused_at_publication():
    """``object.__new__`` skips ``__post_init__``. Publication reads the payload, not the object."""
    from reporting.wallet import WalletReport

    run = synthetic_report(SEED)
    original = run.report.basket.wallets[0]
    forged = object.__new__(WalletReport)
    for field in original.__dataclass_fields__:
        object.__setattr__(forged, field, getattr(original, field))
    object.__setattr__(forged, "wallet", BARE_HEX)
    object.__setattr__(
        run.report.basket, "wallets", (forged,) + tuple(run.report.basket.wallets[1:])
    )
    with pytest.raises(SyntheticProvenanceLost) as raised:
        publish_synthetic_artifact(run.report)
    assert BARE_HEX in str(raised.value)


@pytest.mark.parametrize(
    "launder",
    [
        pytest.param(lambda value: str(value), id="str"),
        pytest.param(lambda value: "".join(value), id="join"),
        pytest.param(lambda value: value[:], id="slice"),
        pytest.param(lambda value: "{}".format(value), id="format"),
        pytest.param(lambda value: value + "", id="concat"),
        pytest.param(lambda value: copy.deepcopy(value), id="deepcopy"),
        pytest.param(lambda value: json.loads(json.dumps(value)), id="json"),
        pytest.param(lambda value: value.lower(), id="lower"),
        pytest.param(lambda value: value.strip(), id="strip"),
        pytest.param(lambda value: type(value)(value), id="str-constructor"),
    ],
)
def test_a_str_round_trip_does_not_launder_an_identifier(run, launder):
    """There is nothing to remove. The marker is characters of the value, so a copy is a copy."""
    marked = run.addresses[0]
    laundered = launder(marked)
    assert laundered == marked
    assert is_synthetic_identifier(laundered)
    payload = _rewrite(_payload_copy(run), marked, laundered)
    assert audit_payload_provenance(payload) == run.addresses


def test_title_casing_the_marker_is_caught_as_an_unmarked_address(run):
    """``0xSynthetic-…`` still looks like an address to the check, and is not a marked one."""
    marked = run.addresses[0]
    disguised = "0x" + marked[2:].capitalize()
    assert not is_synthetic_identifier(disguised)
    payload = _rewrite(_payload_copy(run), marked, disguised)
    with pytest.raises(SyntheticProvenanceLost) as raised:
        audit_payload_provenance(payload)
    assert disguised in str(raised.value)


def test_a_payload_carrying_no_synthetic_identifier_at_all_is_refused_separately(run):
    """The two rules do not subsume each other, so both are tested at the point they diverge.

    Every wallet replaced by WETH satisfies the unmarked-address rule *vacuously* — WETH is on
    :data:`PERMITTED_UNMARKED` — and it is the second rule that refuses the payload.
    """
    payload = _payload_copy(run)
    for address in run.addresses:
        payload = _rewrite(payload, address, WETH)
    unmarked = [
        address for address in addresses_in(payload)
        if not is_synthetic_identifier(address) and address not in PERMITTED_UNMARKED
    ]
    assert unmarked == [], "the first rule must pass, or this is not testing the second"
    with pytest.raises(SyntheticProvenanceLost) as raised:
        audit_payload_provenance(payload)
    assert "carries no synthetic identifier at all" in str(raised.value)


def test_an_empty_payload_is_refused_rather_than_passing_vacuously():
    with pytest.raises(SyntheticProvenanceLost):
        audit_payload_provenance({})


# -- the SyntheticRun constructor's own audit -----------------------------------


def test_the_run_object_re_audits_the_envelope_it_is_handed(run):
    """A ``SyntheticRun`` cannot be built around a payload that was laundered after publication."""
    envelope = copy.deepcopy(run.envelope)
    envelope["payload"] = _rewrite(envelope["payload"], run.addresses[0], BARE_HEX)
    with pytest.raises(SyntheticProvenanceLost):
        SyntheticRun(
            seed=run.seed, snapshot=run.snapshot, run_id=run.run_id, chain=run.chain,
            result=run.result, report=run.report, envelope=envelope,
        )


def test_the_run_object_refuses_a_snapshot_that_does_not_declare_itself_synthetic(run):
    with pytest.raises(SyntheticProvenanceLost) as raised:
        SyntheticRun(
            seed=run.seed, snapshot="dune-2026-07-31", run_id=run.run_id, chain=run.chain,
            result=run.result, report=run.report, envelope=run.envelope,
        )
    assert "does not declare itself synthetic" in str(raised.value)


def test_the_run_object_refuses_an_envelope_that_is_not_one(run):
    with pytest.raises(SyntheticProvenanceLost):
        SyntheticRun(
            seed=run.seed, snapshot=run.snapshot, run_id=run.run_id, chain=run.chain,
            result=run.result, report=run.report, envelope={"no": "payload"},
        )


def test_a_synthetic_run_rebuilt_without_its_constructor_is_never_audited(run):
    """A measured residue, not a guarantee: the constructor's check is on the way in only.

    ``object.__new__`` skips ``__post_init__``, so an object of this class can hold an envelope no
    audit ever saw. That is why the audit that matters is the one in
    :func:`publish_synthetic_artifact`, which reads the bytes rather than trusting the object.
    """
    forged = object.__new__(SyntheticRun)
    envelope = copy.deepcopy(run.envelope)
    envelope["payload"] = _rewrite(envelope["payload"], run.addresses[0], BARE_HEX)
    for field, value in (
        ("seed", run.seed), ("snapshot", run.snapshot), ("run_id", run.run_id),
        ("chain", run.chain), ("result", run.result), ("report", run.report),
        ("envelope", envelope), ("addresses", ()),
    ):
        object.__setattr__(forged, field, value)
    assert isinstance(forged, SyntheticRun)
    assert BARE_HEX in to_canonical_json(forged.payload)
    with pytest.raises(SyntheticProvenanceLost):
        audit_payload_provenance(forged.payload)


# -- the four walk-pasts, demonstrated ------------------------------------------


def test_walk_past_1_an_uppercase_0X_prefix_is_never_looked_at(run):
    """``addresses_in`` matches ``startswith("0x")``, and ``"0X…".startswith("0x")`` is False."""
    real_address = "0X" + "c0ffee" * 6 + "abcd"
    assert len(real_address) == 42
    payload = _rewrite(_payload_copy(run), run.addresses[0], real_address)
    assert real_address not in addresses_in(payload)
    audit_payload_provenance(payload)  # publishes clean, carrying an unmarked real address
    assert real_address in to_canonical_json(payload)


def test_walk_past_2_a_permitted_quote_asset_substituted_for_a_wallet_passes_by_design(run):
    """WETH in the basket instead of a wallet. Refusing it would refuse every priced trade."""
    payload = _rewrite(_payload_copy(run), run.addresses[0], WETH)
    audit_payload_provenance(payload)
    assert WETH in addresses_in(payload)


def test_walk_past_3_a_str_subclass_may_lie_about_its_own_prefix(run):
    """The check asks the value whether it is marked. A value can answer wrongly."""
    class LiesAboutItsPrefix(str):
        def startswith(self, prefix, *args):  # noqa: D401 - deliberately wrong
            return True

    real_address = "0x" + "c0ffee" * 6 + "abcd"
    liar = LiesAboutItsPrefix(real_address)
    assert is_synthetic_identifier(liar)
    assert MARKER not in str(liar)
    payload = _rewrite(_payload_copy(run), run.addresses[0], liar)
    audit_payload_provenance(payload)
    assert real_address in json.dumps(payload)


def test_walk_past_4_an_address_embedded_in_a_longer_string_is_not_address_shaped(run):
    embedded = "copied from wallet 0x" + "ab" * 20
    payload = _payload_copy(run)
    payload["smuggled"] = embedded
    assert embedded not in addresses_in(payload)
    audit_payload_provenance(payload)
