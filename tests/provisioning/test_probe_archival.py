"""Archival RPC — all four capabilities for one transaction, or the source is not provisioned.

This is the source ticket 03 was written around: no invoice, no monthly reminder that it exists,
and the ground truth the whole validation gate rests on. The failure mode it exists to catch is
already observed on three public endpoints — a node that serves receipts and logs happily and
refuses ``debug_traceTransaction`` — and the reason that failure survives casual checking is that
the refusal arrives as **HTTP 200 with a JSON-RPC error inside it**. A status-code check records it
as a success.

So the assertions that matter in this file are the negative ones. ``test_receipts_and_logs_without_
a_trace_is_the_observed_half_provisioned_node`` is the specific case; the parametrized
``test_all_four_are_required`` is the general one — break any single capability and the source must
not come back PROVEN, no matter how well the other three answered.

The balance delta is not decoration either. Receipts and logs come from the receipts database that
pruned nodes keep; ``eth_getBalance`` at a three-year-old height needs historical state, which is
the one thing a full-but-not-archival node cannot fake.
"""

import pytest

from tools.provisioning import fixtures
from tools.provisioning.outcomes import ABSENT, INSUFFICIENT, PROVEN, REFUSED, UNREACHABLE
from tools.provisioning.probes.archival import ArchivalRpcProbe
from tools.provisioning.redaction import REDACTED

from conftest import Boom, FakeTransport, Json, rpc_method
from payloads import (
    BALANCE_AFTER_WEI,
    BALANCE_BEFORE_WEI,
    BALANCE_DELTA_WEI,
    SENDER,
    TRACE_REFUSAL,
    TX,
    archival_routes,
    block_payload,
    jsonrpc_error,
    receipt_payload,
    rpc_result,
    sequence,
)

KEY = "9f2b7c4d1e6a8b3c5d7e0a1b"
RPC = "https://eth-mainnet.example.com/v2/{}".format(KEY)
ENV = {"ETH_ARCHIVAL_RPC_URL": RPC}


def probe():
    return ArchivalRpcProbe()


def run(routes=None, env=None, default=None, **kwargs):
    transport = FakeTransport(
        routes=archival_routes(**kwargs) if routes is None else routes, default=default
    )
    return probe().run(transport=transport, env=ENV if env is None else env), transport


# -- ABSENT ----------------------------------------------------------------------

def test_no_rpc_url_is_absent_and_contacts_nothing(clean_env):
    transport = FakeTransport()
    result = probe().run(transport=transport, env=clean_env)
    assert result.status == ABSENT
    assert "ETH_ARCHIVAL_RPC_URL" in result.detail
    assert transport.calls == []


# -- UNREACHABLE -----------------------------------------------------------------

def test_a_node_that_does_not_answer_is_unreachable():
    result, _ = run(routes=[], default=Boom("connection refused"))
    assert result.status == UNREACHABLE
    assert "connection refused" in result.detail


# -- REFUSED ---------------------------------------------------------------------

def test_receipts_and_logs_without_a_trace_is_the_observed_half_provisioned_node():
    """The case this probe exists for, arriving exactly as it does in the wild: HTTP 200."""
    result, _ = run(
        debug=jsonrpc_error(TRACE_REFUSAL, code=-32601),
        trace=jsonrpc_error(TRACE_REFUSAL, code=-32601),
    )
    assert result.status == REFUSED
    assert result.verbatim == TRACE_REFUSAL
    # The first two capabilities *did* work, and the register says so. "It serves receipts" is the
    # sentence that gets a node adopted; this is the evidence that it is not enough.
    assert result.evidence["receipt_log_count"] == 2
    assert result.evidence["logs_matching_transaction"] == 2
    assert result.evidence["trace_methods_attempted"] == [
        "debug_traceTransaction", "trace_transaction"
    ]


def test_a_refused_trace_names_both_spellings_before_giving_up():
    result, transport = run(
        debug=jsonrpc_error("method debug_traceTransaction does not exist"),
        trace=jsonrpc_error(TRACE_REFUSAL),
    )
    assert result.status == REFUSED
    # The last error is the one recorded, but both were genuinely attempted.
    assert result.verbatim == TRACE_REFUSAL
    methods = [call["body"] for call in transport.calls]
    assert any(b"debug_traceTransaction" in body for body in methods)
    assert any(b"trace_transaction" in body for body in methods)


def test_a_node_that_will_not_serve_historical_state_is_refused():
    """Pruned nodes answer receipts and refuse a three-year-old balance. That is not archival."""
    result, _ = run(balances=jsonrpc_error("missing trie node; state is not available", code=-32000))
    assert result.status == REFUSED
    assert "historical state" in result.detail
    assert "missing trie node" in result.verbatim


def test_an_http_level_decline_is_refused_with_the_status_recorded():
    result, _ = run(routes=[], default=Json({"error": "unauthorized"}, status=401))
    assert result.status == REFUSED
    assert "unauthorized" in result.verbatim


# -- INSUFFICIENT ----------------------------------------------------------------

def test_a_trace_request_that_succeeds_and_returns_nothing_is_not_a_pass():
    result, _ = run(debug=rpc_result(None), trace=rpc_result(None))
    assert result.status == INSUFFICIENT
    assert "half-provisioned node this probe exists to catch" in result.detail


def test_no_receipt_without_an_error_is_not_a_pass():
    result, _ = run(receipt=rpc_result(None))
    assert result.status == INSUFFICIENT
    assert "which is not a pass" in result.detail


def test_logs_the_index_does_not_have_are_a_defect_in_the_node():
    """The receipt carried logs and eth_getLogs does not. The two disagree; that is not proof."""
    result, _ = run(logs=rpc_result([]))
    assert result.status == INSUFFICIENT
    assert result.evidence["logs_matching_transaction"] == 0
    assert "defect in the node" in result.detail


def test_a_balance_that_is_not_a_quantity_leaves_historical_state_unproven():
    result, _ = run(balances=rpc_result("not-a-hex-string"))
    assert result.status == INSUFFICIENT
    assert "historical state is unproven" in result.detail


def test_a_node_with_no_block_at_that_height_is_not_archival_on_any_definition():
    result, _ = run(block=rpc_result(None))
    assert result.status == INSUFFICIENT
    assert "not archival on any definition" in result.detail


def test_a_block_of_bare_transfers_cannot_prove_the_log_capability():
    """A plain ETH send has no logs, so there is nothing to prove eth_getLogs against."""
    transfers = [{"hash": "0x" + "77" * 32, "from": SENDER, "input": "0x"} for _ in range(5)]
    result, _ = run(block=rpc_result(block_payload(transactions=transfers)))
    assert result.status == INSUFFICIENT
    assert "no contract-calling transaction" in result.detail


# -- PROVEN ----------------------------------------------------------------------

def test_all_four_capabilities_for_one_transaction_are_proof():
    result, _ = run()
    assert result.status == PROVEN
    assert result.evidence["transaction"] == TX
    assert result.evidence["block"] == fixtures.ARCHIVAL_BLOCK
    assert result.evidence["receipt_log_count"] == 2
    assert result.evidence["logs_matching_transaction"] == 2
    assert result.evidence["trace_method"] == "debug_traceTransaction"
    assert result.evidence["capabilities_required"] == [
        "receipt", "event_logs", "execution_trace", "balance_delta"
    ]


def test_the_balance_delta_is_computed_across_two_heights_in_raw_wei():
    """2 ETH before, 1.5 ETH after. Hand-computed: -500000000000000000 wei, as an int.

    Raw quantities are ``int`` — never Decimal, never float. A wei value that had been through a
    double would be wrong in its last four digits and look entirely reasonable.
    """
    result, _ = run()
    assert result.evidence["balance_wei_before"] == BALANCE_BEFORE_WEI
    assert result.evidence["balance_wei_after"] == BALANCE_AFTER_WEI
    assert result.evidence["balance_delta_wei"] == -500000000000000000
    assert result.evidence["balance_delta_wei"] == BALANCE_DELTA_WEI
    assert isinstance(result.evidence["balance_delta_wei"], int)
    assert not isinstance(result.evidence["balance_delta_wei"], bool)


def test_the_two_balance_calls_are_made_at_different_heights():
    """A delta between one block and itself is zero, and zero is not evidence of state access."""
    _, transport = run()
    balance_calls = [c["body"] for c in transport.calls if b"eth_getBalance" in c["body"]]
    assert len(balance_calls) == 2
    assert hex(fixtures.ARCHIVAL_BLOCK - 1).encode() in balance_calls[0]
    assert hex(fixtures.ARCHIVAL_BLOCK).encode() in balance_calls[1]


def test_the_erigon_spelling_is_accepted_when_geth_does_not_have_the_method():
    """Refusing a trace and not implementing one method are different facts about a node."""
    result, _ = run(
        debug=jsonrpc_error("the method debug_traceTransaction does not exist", code=-32601)
    )
    assert result.status == PROVEN
    assert result.evidence["trace_method"] == "trace_transaction"


def test_the_probe_walks_past_a_bare_transfer_to_a_contract_call():
    result, _ = run()
    assert result.evidence["transaction"] == TX
    assert "first contract-calling transaction" in result.evidence["selected_by"]


def test_an_operator_can_pin_the_transaction_by_hash():
    env = dict(ENV, ETH_ARCHIVAL_PROBE_TX=TX)
    result, _ = run(env=env)
    assert result.status == PROVEN
    assert "pinned by ETH_ARCHIVAL_PROBE_TX" in result.evidence["selected_by"]


def test_a_pinned_transaction_that_is_not_in_the_block_says_so():
    env = dict(ENV, ETH_ARCHIVAL_PROBE_TX="0x" + "ee" * 32)
    result, _ = run(env=env)
    assert result.status == INSUFFICIENT
    assert "ETH_ARCHIVAL_PROBE_TX names a transaction that is not in block" in result.detail


# -- all four, or nothing --------------------------------------------------------

@pytest.mark.parametrize("broken", ["receipt", "logs", "trace", "balance"])
def test_all_four_are_required(broken):
    """Three out of four is not three quarters provisioned. It is not provisioned."""
    kwargs = {}
    if broken == "receipt":
        kwargs["receipt"] = jsonrpc_error("method not supported")
    elif broken == "logs":
        kwargs["logs"] = jsonrpc_error("eth_getLogs is disabled on this endpoint")
    elif broken == "trace":
        kwargs["debug"] = jsonrpc_error(TRACE_REFUSAL)
        kwargs["trace"] = jsonrpc_error(TRACE_REFUSAL)
    else:
        kwargs["balances"] = jsonrpc_error("missing trie node")
    result, _ = run(**kwargs)
    assert result.status != PROVEN
    assert result.status == REFUSED


# -- the credential that is a URL ------------------------------------------------

def test_the_endpoint_key_never_reaches_the_evidence():
    result, _ = run()
    assert KEY not in result.evidence["endpoint"]
    assert result.evidence["endpoint"] == "https://eth-mainnet.example.com/v2/{}".format(REDACTED)


def test_the_endpoint_key_never_reaches_an_unreachable_detail():
    result, _ = run(routes=[], default=Boom("no route to host {}".format(RPC)))
    assert KEY not in result.detail
    assert KEY not in result.evidence["endpoint"]
    # Redacted, not deleted: the host is what a diagnostic is for.
    assert "eth-mainnet.example.com" in result.evidence["endpoint"]


def test_a_node_echoing_the_key_back_is_scrubbed_from_the_verbatim_message():
    """No structural rule catches this — the key is loose text in someone else's JSON."""
    result, _ = run(
        routes=[(rpc_method("eth_getBlockByNumber"),
                 jsonrpc_error("key {} is not authorised for archive".format(KEY)))]
    )
    assert result.status == REFUSED
    assert KEY not in result.verbatim
    assert REDACTED in result.verbatim


# -- sanity on the fake itself ---------------------------------------------------

def test_the_sequence_helper_answers_twice_and_then_holds():
    answer = sequence(rpc_result("0x1"), rpc_result("0x2"))
    assert answer("u").payload["result"] == "0x1"
    assert answer("u").payload["result"] == "0x2"
    assert answer("u").payload["result"] == "0x2"


def test_the_receipt_fixture_carries_the_logs_the_probe_counts():
    assert len(receipt_payload(log_count=3)["logs"]) == 3
