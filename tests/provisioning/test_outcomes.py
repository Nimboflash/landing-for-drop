"""The five outcomes, and the asymmetry between the first four and the last.

``ABSENT`` costs nothing to report honestly. ``PROVEN`` has to be *earned*. These tests pin that
asymmetry: a result may be constructed for every unhappy state of the world with nothing but a
sentence, but ``PROVEN`` without evidence and ``REFUSED`` without the endpoint's own words are both
refused at construction. If either of those constructors ever starts accepting, this file goes red.
"""

from decimal import Decimal

import pytest

from tools.provisioning.outcomes import (
    ABSENT,
    INSUFFICIENT,
    PROVEN,
    REFUSED,
    STATUSES,
    UNREACHABLE,
    ProbeResult,
    absent,
    insufficient,
    proven,
    refused,
    unreachable,
)


def test_the_five_outcomes_are_exactly_these():
    assert STATUSES == (ABSENT, UNREACHABLE, REFUSED, INSUFFICIENT, PROVEN)


def test_each_unhappy_outcome_needs_only_a_legible_sentence():
    assert absent("dune", "set DUNE_API_KEY").status == ABSENT
    assert unreachable("dune", "no answer").status == UNREACHABLE
    assert insufficient("dune", "zero rows").status == INSUFFICIENT
    assert refused("rpc", "declined", verbatim="archive requests require a personal token").status \
        == REFUSED


def test_only_proven_counts_as_provisioned():
    assert proven("dune", "rows came back", {"rows": 25}).is_proven is True
    for result in (
        absent("dune", "no key"),
        unreachable("dune", "no answer"),
        refused("dune", "no", verbatim="nope"),
        insufficient("dune", "zero rows"),
    ):
        assert result.is_proven is False, result.status


# -- PROVEN must be earned -------------------------------------------------------

def test_proven_without_evidence_is_refused():
    """The single most important line in this package.

    A probe that reached an endpoint, understood nothing, and raised no exception has proven
    nothing. If this constructor ever accepts an empty evidence mapping, ``data_budget: APPROVED``
    becomes reachable by writing a probe that cannot fail.
    """
    with pytest.raises(ValueError) as excinfo:
        ProbeResult("dune", PROVEN, "it did not error", evidence={})
    assert "never by the absence of an error" in str(excinfo.value)


def test_proven_with_evidence_records_what_was_seen():
    result = proven("dune", "25 rows", {"rows_total": 25, "block_range": "16308190-16309190"})
    assert result.evidence["rows_total"] == 25
    assert result.as_dict()["evidence"]["block_range"] == "16308190-16309190"


def test_refused_without_the_endpoints_own_words_is_refused():
    with pytest.raises(ValueError) as excinfo:
        ProbeResult("archival_rpc", REFUSED, "the node said no")
    assert "verbatim" in str(excinfo.value)


def test_refused_keeps_the_message_verbatim():
    message = "archive requests require a personal token"
    result = refused("archival_rpc", "trace declined", verbatim=message)
    assert result.verbatim == message
    assert result.as_dict()["verbatim"] == message


def test_a_result_must_name_its_source_and_say_something():
    with pytest.raises(ValueError):
        ProbeResult("", ABSENT, "detail")
    with pytest.raises(ValueError):
        ProbeResult("dune", ABSENT, "")


def test_an_unknown_status_is_refused():
    with pytest.raises(ValueError) as excinfo:
        ProbeResult("dune", "FINE", "looks alright")
    assert "unknown probe status" in str(excinfo.value)


# -- evidence stays JSON-safe, and free of floats --------------------------------

def test_a_float_in_evidence_is_refused():
    """Vendor payloads are full of JSON doubles. The probe converts at the point it decides what
    it saw, which is where somebody should be thinking about precision anyway."""
    with pytest.raises(TypeError) as excinfo:
        proven("dune", "rows", {"amount_usd": 1234.56})
    assert "float in probe evidence" in str(excinfo.value)


def test_a_nested_float_in_evidence_is_refused():
    with pytest.raises(TypeError):
        proven("dune", "rows", {"rows": [{"amount_usd": 1.0}]})


def test_a_decimal_in_evidence_is_refused_so_the_register_stays_plain_json():
    with pytest.raises(TypeError) as excinfo:
        proven("dune", "rows", {"total": Decimal("478")})
    assert "Serialize it with str()" in str(excinfo.value)


def test_ints_bools_strings_and_none_are_all_fine():
    result = proven("rpc", "four capabilities", {
        "block": 16308190,
        "balance_delta_wei": -1234567890123456789,
        "trace": True,
        "method": "debug_traceTransaction",
        "without_flag_http_status": None,
        "keys": ["from", "to"],
    })
    assert result.evidence["block"] == 16308190
