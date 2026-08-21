"""Dune probe — all five outcomes, and the one that matters: rows, or it did not happen.

The interesting assertion in this file is ``test_zero_rows_is_a_failure_not_an_empty_result``.
Blocks 16,308,190–16,309,190 are about three and a half hours of Ethereum mainnet on 1 Jan 2023.
There is no state of the world in which they contain no DEX trades, so an empty answer is a fact
about our access — the key, the tier, the decoders — and not about the chain. A probe that reported
success there would be answering "did the API respond?", which nobody was asking.
"""

import json

import pytest

from tools.provisioning.outcomes import ABSENT, INSUFFICIENT, PROVEN, REFUSED, UNREACHABLE
from tools.provisioning.probes.dune import DuneProbe

from conftest import Boom, FakeTransport, Json
from payloads import dune_rows as rows, dune_routes as routes

ENV = {"DUNE_API_KEY": "dune-key-abc"}


def probe():
    # No real sleeping: the polling loop is exercised, not waited on.
    return DuneProbe(sleep=lambda seconds: None, poll_attempts=3)


# -- ABSENT ----------------------------------------------------------------------

def test_no_key_is_absent_and_contacts_nothing(clean_env):
    transport = FakeTransport()
    result = probe().run(transport=transport, env=clean_env)
    assert result.status == ABSENT
    assert "DUNE_API_KEY" in result.detail
    assert transport.calls == []


# -- UNREACHABLE -----------------------------------------------------------------

def test_an_endpoint_that_does_not_answer_is_unreachable():
    result = probe().run(transport=FakeTransport(default=Boom("connection timed out")), env=ENV)
    assert result.status == UNREACHABLE
    assert "connection timed out" in result.detail


# -- REFUSED ---------------------------------------------------------------------

def test_a_declined_key_is_refused_with_the_message_verbatim():
    message = "invalid API Key"
    transport = FakeTransport(default=Json({"error": message}, status=401))
    result = probe().run(transport=transport, env=ENV)
    assert result.status == REFUSED
    assert message in result.verbatim
    assert result.evidence["http_status"] == 401


def test_a_refusal_at_the_results_step_is_still_a_refusal():
    transport = FakeTransport(routes=routes(results_status=403))
    result = probe().run(transport=transport, env=ENV)
    assert result.status == REFUSED
    assert result.evidence["execution_id"] == "exec-1"


# -- INSUFFICIENT ----------------------------------------------------------------

def test_zero_rows_is_a_failure_not_an_empty_result():
    result = probe().run(transport=FakeTransport(routes=routes(result_rows=[])), env=ENV)
    assert result.status == INSUFFICIENT
    assert "certainly contains trades" in result.detail
    assert result.evidence["rows_total"] == 0


def test_dex_trades_alone_is_half_a_provisioning():
    """The aggregator tables are what stop a solver-settled trade being attributed to the solver."""
    result = probe().run(
        transport=FakeTransport(routes=routes(result_rows=rows(dex=5, aggregator=0))), env=ENV
    )
    assert result.status == INSUFFICIENT
    assert "dex_aggregator.trades" in result.detail
    assert result.evidence["rows_dex_trades"] == 5
    assert result.evidence["rows_dex_aggregator"] == 0


def test_an_execution_that_never_completes_proves_nothing():
    result = probe().run(
        transport=FakeTransport(routes=routes(state="QUERY_STATE_EXECUTING")), env=ENV
    )
    assert result.status == INSUFFICIENT
    assert "QUERY_STATE_EXECUTING" in result.detail


def test_a_failed_execution_proves_nothing():
    result = probe().run(transport=FakeTransport(routes=routes(state="QUERY_STATE_FAILED")), env=ENV)
    assert result.status == INSUFFICIENT


def test_a_2xx_with_no_query_id_is_not_a_pass():
    transport = FakeTransport(routes=[("/api/v1/query", Json({"ok": True}))])
    result = probe().run(transport=transport, env=ENV)
    assert result.status == INSUFFICIENT
    assert "DUNE_QUERY_ID" in result.detail


# -- PROVEN ----------------------------------------------------------------------

def test_rows_from_both_tables_are_proof():
    transport = FakeTransport(routes=routes())
    result = probe().run(transport=transport, env=ENV)
    assert result.status == PROVEN
    assert result.evidence["rows_dex_trades"] == 3
    assert result.evidence["rows_dex_aggregator"] == 2
    assert result.evidence["block_range"] == "16308190-16309190"
    assert result.evidence["window"] == "window 1 train (Jan-Jun 2023)"
    assert result.evidence["first_block_seen"] == 16308190


def test_the_query_names_the_block_range_and_both_tables():
    """The SQL is the specification of what "proven" means here, so it is asserted."""
    transport = FakeTransport(routes=routes())
    probe().run(transport=transport, env=ENV)
    creation = [call for call in transport.calls if call["url"].endswith("/api/v1/query")]
    sql = json.loads(creation[0]["body"].decode("utf-8"))["query_sql"]
    assert "dex.trades" in sql
    assert "dex_aggregator.trades" in sql
    assert "16308190" in sql and "16309190" in sql
    assert "blockchain = 'ethereum'" in sql


def test_a_saved_query_id_skips_creation():
    """Some tiers cannot create a query over the API. Being unable to *create* one is a different
    fact from being unable to *read* dex.trades, and the probe must not conflate them."""
    transport = FakeTransport(routes=routes())
    env = dict(ENV, DUNE_QUERY_ID="1234567")
    result = probe().run(transport=transport, env=env)
    assert result.status == PROVEN
    assert result.evidence["query_id"] == "1234567"
    assert not [c for c in transport.calls if c["url"].endswith("/api/v1/query")]


def test_the_key_travels_in_a_header_and_never_in_a_url():
    transport = FakeTransport(routes=routes())
    probe().run(transport=transport, env=ENV)
    assert all("dune-key-abc" not in url for url in transport.urls())
    assert transport.calls[0]["headers"]["X-Dune-API-Key"] == "dune-key-abc"


@pytest.mark.parametrize("evidence_key", [
    "query_id", "execution_id", "block_range", "rows_total",
    "rows_dex_trades", "rows_dex_aggregator",
])
def test_the_evidence_records_what_was_seen(evidence_key):
    result = probe().run(transport=FakeTransport(routes=routes()), env=ENV)
    assert evidence_key in result.evidence
