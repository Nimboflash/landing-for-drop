"""Parameter encoding and shape checks, against hand-written literals.

Every expectation below is written out rather than derived from the function under test. A test
that computes ``hex(16308001)`` to check ``hex_quantity(16308001)`` pins nothing at all.
"""

import pytest

from transport.params import (
    BLOCK_TAGS,
    assert_wire_safe,
    block_parameter,
    hex_quantity,
    require_address,
    require_hash,
)

TX = "0xb8681e7a43edca5fe12d5fc0183b901d73255f86e4188715e3d556ba57f269e3"
WALLET = "0xe15b3d62c2bce51f2a8a8d53d76c36b4fab8721c"


# -- quantities ------------------------------------------------------------------


@pytest.mark.parametrize("value,expected", [
    (0, "0x0"),
    (1, "0x1"),
    (15, "0xf"),
    (16, "0x10"),
    (16308001, "0xf8d721"),
    (16308190, "0xf8d7de"),
])
def test_hex_quantity_matches_the_wire_form(value, expected):
    assert hex_quantity(value) == expected


def test_hex_quantity_refuses_a_bool_even_though_python_calls_it_an_int():
    """``hex_quantity(True)`` would encode ``0x1`` and mean block one. Nobody wrote that."""
    with pytest.raises(TypeError):
        hex_quantity(True)


def test_hex_quantity_refuses_a_negative_and_a_float():
    with pytest.raises(ValueError):
        hex_quantity(-1)
    with pytest.raises(TypeError):
        hex_quantity(1.0)


# -- block parameters ------------------------------------------------------------


def test_a_height_becomes_a_quantity_and_a_quantity_passes_through():
    assert block_parameter(16308001) == "0xf8d721"
    assert block_parameter("0xf8d721") == "0xf8d721"


@pytest.mark.parametrize("tag", sorted(BLOCK_TAGS))
def test_every_declared_tag_passes_through_verbatim(tag):
    assert block_parameter(tag) == tag


@pytest.mark.parametrize("value", ["newest", "0xzz", "", "16308001", "0x"])
def test_an_unrecognised_block_parameter_is_refused_rather_than_forwarded(value):
    with pytest.raises(ValueError):
        block_parameter(value)


@pytest.mark.parametrize("value", [True, None, 1.5, ["0x1"]])
def test_a_block_parameter_of_the_wrong_type_is_refused(value):
    with pytest.raises((TypeError, ValueError)):
        block_parameter(value)


# -- identifiers -----------------------------------------------------------------


def test_a_well_formed_hash_and_address_are_returned_unchanged():
    assert require_hash(TX) == TX
    assert require_address(WALLET) == WALLET


def test_an_address_keeps_its_case():
    """Silently lower-casing here would make two spellings share one cache entry."""
    mixed = "0xE15b3d62C2BCe51f2a8A8d53d76c36b4fAB8721c"
    assert require_address(mixed) == mixed
    assert require_address(mixed) != WALLET


@pytest.mark.parametrize("value", [
    TX[:-1],                       # 63 digits
    TX + "0",                      # 65 digits
    TX.replace("0x", ""),          # unprefixed
    WALLET,                        # an address is not a hash
    None,
    12345,
])
def test_a_malformed_hash_is_refused_with_the_reason_it_matters(value):
    with pytest.raises(ValueError) as exc:
        require_hash(value)
    if isinstance(value, str):
        assert "null" in str(exc.value), (
            "the refusal must say why a bad hash is dangerous: several vendors answer null, which "
            "reads downstream as 'no such transaction'"
        )


@pytest.mark.parametrize("value", [WALLET[:-1], WALLET + "0", TX, "0xnothex" + "0" * 33, None])
def test_a_malformed_address_is_refused(value):
    with pytest.raises(ValueError):
        require_address(value)


# -- wire safety -----------------------------------------------------------------


def test_the_permitted_parameter_types_pass():
    params = [{"fromBlock": "0xf8d721", "toBlock": "0xf8d721", "topics": [None, ["0x" + "a" * 64]]},
              True, None, "0x1"]
    assert assert_wire_safe(params) is params


def test_an_int_parameter_is_refused_and_the_message_shows_the_encoding():
    with pytest.raises(TypeError) as exc:
        assert_wire_safe([16308001])
    message = str(exc.value)
    assert "hex_quantity" in message
    assert "0xf8d721" in message, "the refusal must show the caller what to write instead"
    assert "two keys" in message, "the refusal must name the cache split it prevents"


def test_a_float_parameter_is_refused():
    with pytest.raises(TypeError) as exc:
        assert_wire_safe({"value": 1.5})
    assert "float" in str(exc.value)


def test_a_non_string_object_key_is_refused():
    with pytest.raises(TypeError) as exc:
        assert_wire_safe([{1: "0x1"}])
    assert "non-string key" in str(exc.value)


def test_the_path_of_the_offending_value_is_named():
    with pytest.raises(TypeError) as exc:
        assert_wire_safe([{"filter": {"fromBlock": 16308001}}])
    assert "params[0]['filter']['fromBlock']" in str(exc.value)


def test_an_unusable_type_is_refused():
    with pytest.raises(TypeError):
        assert_wire_safe([object()])
