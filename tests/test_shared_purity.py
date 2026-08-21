"""The shared package must define what a valid answer looks like, never how a lane obtains one.

If a formula lives in ``contracts``, both the builder and the validator inherit it through a
dependency each believes to be neutral — and then they agree, because they are running the same
mistake. That agreement is precisely what the validation gate would certify.

So ``contracts`` is limited to:

    Types · Enums · Serialization · Construction invariants · Error definitions · Manifest schemas
    · the frozen numeric policy

and must contain none of:

    netting helpers · FIFO assignment · marking formulas · scoring aggregation
    · depth calculation · matching distance · gate evaluation

Enforcement is by explicit inventory rather than by heuristic. Every public callable must be
declared with a category, and an undeclared one fails the suite — so a formula cannot arrive in
shared by accident, only by someone deliberately mislabelling it.
"""

import ast
import inspect
import os

import pytest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

# NOTE: deliberately no ``sys.path.insert`` here. pyproject already sets
# ``pythonpath = ["src"]``, so the insert was redundant — and actively harmful. Inserting at
# position 0 at *import* time overrides PYTHONPATH for every test file sharing the process, which
# silently defeated mutation testing of the whole seam: the first mutation harness reported all
# ten ``contracts`` mutations as dead, because the mutated copy was never the one imported.
#
# A test helper that quietly redirects imports is indistinguishable from a passing test suite.

import contracts
from contracts import core, metrics, numeric, serialization, trades

MODULES = (core, trades, metrics, numeric, serialization)

# -- permitted categories -------------------------------------------------------

TYPE = "type"
ENUM = "enum"
ERROR = "error"
PREDICATE = "predicate"            # answers "is this valid/permitted", stores no formula
DERIVED_FIELD = "derived_field"    # restates stored fields; no domain rule of its own
SERIALIZATION = "serialization"
NUMERIC_POLICY = "numeric_policy"  # defines precision/rounding; performs no domain arithmetic

PERMITTED_CATEGORIES = frozenset(
    {TYPE, ENUM, ERROR, PREDICATE, DERIVED_FIELD, SERIALIZATION, NUMERIC_POLICY}
)

#: The category that must never appear here. Named so the boundary is legible at the point of
#: enforcement, and so mislabelling requires writing the word.
FORBIDDEN_CATEGORY = "calculation"

INVENTORY = {
    # core — vocabulary
    "normalise_asset": PREDICATE,
    "is_quote_asset": PREDICATE,
    # trades / metrics — types
    "Attribution": TYPE, "Transfer": TYPE, "Transaction": TYPE, "NetDelta": TYPE,
    "NetTradeResult": TYPE, "Lot": TYPE, "LotConsumption": TYPE, "FifoResult": TYPE,
    "PoolState": TYPE, "PositionValue": TYPE, "BuyOutcome": TYPE, "BuyQuality": TYPE,
    "WindowScore": TYPE, "CopySimulation": TYPE, "MatchedSet": TYPE, "CovariateBalance": TYPE,
    "PermutationResult": TYPE, "FreezeManifest": TYPE, "GateDecision": TYPE,
    # enums
    "AssetTier": ENUM, "ClassificationStatus": ENUM, "AccountType": ENUM,
    "AttributionMethod": ENUM, "PoolStatus": ENUM, "ValueBasis": ENUM,
    "EdgeOriginStatus": ENUM, "TokenAgeBucket": ENUM, "GateOutcome": ENUM,
    "ValidationStatus": ENUM,
    # errors
    "ContractError": ERROR, "LongTailExcludedError": ERROR,
    "AttributionUnresolvedError": ERROR, "QuarantineRequired": ERROR,
    "LookAheadViolation": ERROR, "FreezeViolation": ERROR,
    # serialization
    "canonicalise": SERIALIZATION, "to_canonical_json": SERIALIZATION,
    "canonical_hash": SERIALIZATION, "artifact_envelope": SERIALIZATION,
    "format_timestamp": SERIALIZATION, "verify_redundant_derived": SERIALIZATION,
    "DerivedFieldMismatch": ERROR,
    # numeric policy
    "calc": NUMERIC_POLICY, "divide": NUMERIC_POLICY, "quantize_usd": NUMERIC_POLICY,
    "quantize_ratio": NUMERIC_POLICY, "quantize_pp": NUMERIC_POLICY,
    "is_finite": NUMERIC_POLICY, "require_finite": NUMERIC_POLICY,
    "sub": NUMERIC_POLICY, "add": NUMERIC_POLICY, "mul": NUMERIC_POLICY,
}


def _public_callables():
    found = {}
    for module in MODULES:
        for name, obj in vars(module).items():
            if name.startswith("_") or getattr(obj, "__module__", None) != module.__name__:
                continue
            if inspect.isclass(obj) or inspect.isfunction(obj):
                found[name] = obj
    return found


def test_every_public_callable_is_declared():
    undeclared = sorted(set(_public_callables()) - set(INVENTORY))
    assert not undeclared, (
        "undeclared in contracts: {}. Add each to INVENTORY with a category. A formula cannot "
        "arrive in the shared package by accident — only by someone deliberately choosing a "
        "category for it, which is the point.".format(", ".join(undeclared))
    )


def test_no_declared_category_is_calculation():
    assert FORBIDDEN_CATEGORY not in PERMITTED_CATEGORIES
    bad = sorted(n for n, c in INVENTORY.items() if c not in PERMITTED_CATEGORIES)
    assert not bad, "not a permitted shared category: {}".format(", ".join(bad))


def test_inventory_has_no_stale_entries():
    stale = sorted(set(INVENTORY) - set(_public_callables()))
    assert not stale, (
        "declared but absent: {}. A stale allowlist entry is a hole — it would silently permit a "
        "future function of that name.".format(", ".join(stale))
    )


FORBIDDEN_NAME_FRAGMENTS = (
    "net_transaction", "match_fifo", "mark_position", "buy_quality", "window_score",
    "size_to_cost", "copier_slippage", "matched_set", "permutation_null", "evaluate_windows",
    "emit_decision", "edge_share", "distance",
)


def test_no_domain_calculation_names_in_shared():
    """A blunt second net, in case something is mislabelled rather than undeclared."""
    offenders = []
    for name in _public_callables():
        lowered = name.lower()
        for fragment in FORBIDDEN_NAME_FRAGMENTS:
            if fragment in lowered:
                offenders.append("{} (matches {!r})".format(name, fragment))
    assert not offenders, (
        "domain calculation appears to live in contracts: {}. Shared defines what a valid answer "
        "looks like; how a lane obtains one belongs to that lane.".format("; ".join(offenders))
    )


def test_contracts_imports_only_stdlib_and_itself():
    """No third-party dependency may enter through the seam.

    A dataframe library is the usual way a float gets in: it converts silently, and by the time a
    value reaches a comparison the precision is already gone.
    """
    allowed = {"dataclasses", "decimal", "enum", "typing", "hashlib", "json", "datetime",
               "contracts"}
    violations = []
    for module in MODULES:
        path = module.__file__
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in allowed:
                        violations.append("{}: import {}".format(os.path.basename(path), top))
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                top = node.module.split(".")[0]
                if top not in allowed:
                    violations.append("{}: from {}".format(os.path.basename(path), top))
    assert not violations, "non-stdlib import in contracts: {}".format("; ".join(violations))


@pytest.mark.parametrize("name,category", sorted(INVENTORY.items()))
def test_derived_fields_restate_rather_than_decide(name, category):
    """A ``derived_field`` or ``predicate`` must not encode a threshold from the protocol.

    ``LotConsumption.realized_return`` dividing two stored fields is a definition. A property that
    compared a value against 40% would be the Edge Origin *rule*, and that belongs in scoring
    where it can be tested against hand-computed cases and mutated.
    """
    if category not in (DERIVED_FIELD, PREDICATE):
        pytest.skip("only derived fields and predicates are constrained here")
    obj = _public_callables()[name]
    source = inspect.getsource(obj)
    for literal in ("0.40", "40%", "0.05", "5 percentage", "0.10"):
        assert literal not in source, (
            "{} appears to encode protocol threshold {!r}; thresholds live in the lane that "
            "applies them".format(name, literal)
        )


# -- derived fields: AST-enforced, not merely declared ---------------------------
#
# A human can label a formula `derived_field` with impressive confidence. The inventory records
# intent; this makes the category mean something.

DERIVED_FIELDS = {
    ("LotConsumption", "realized_return"): trades.LotConsumption,
    ("CopySimulation", "fill_ratio"): metrics.CopySimulation,
}

#: The only functions a derived field may call. Shared numeric primitives and Decimal itself.
ALLOWED_DERIVED_CALLS = frozenset({"divide", "calc", "sub", "add", "mul", "Decimal"})

#: Quantization inside a projection would bake an output scale into an internal value.
FORBIDDEN_DERIVED_CALLS = frozenset({
    "quantize_usd", "quantize_ratio", "quantize_pp", "quantize", "round", "float", "int",
    "min", "max", "abs",
})

ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div)


def _property_body(owner, name):
    prop = getattr(owner, name)
    source = inspect.getsource(prop.fget)
    # dedent so a method body parses standalone
    lines = source.split("\n")
    indent = len(lines[0]) - len(lines[0].lstrip())
    dedented = "\n".join(line[indent:] if len(line) > indent else line for line in lines)
    tree = ast.parse(dedented)
    fn = tree.body[0]
    body = list(fn.body)
    # drop the docstring
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return body


@pytest.mark.parametrize("key", sorted(DERIVED_FIELDS))
def test_derived_field_is_pure_algebra(key):
    """A shared derived field may read only its own immutable fields, use only shared numeric
    primitives and arithmetic, and decide nothing.

    Banned outright: branching, comparison, enum or status references, quantization, fallbacks.
    Each of those would be a domain policy — ``fill_ratio >= 0.90`` is an executability rule,
    ``share <= 0.40`` is the Edge Origin rule — and policy belongs where it can be frozen and
    mutation-tested, not in a projection every lane inherits.
    """
    class_name, prop_name = key
    body = _property_body(DERIVED_FIELDS[key], prop_name)

    assert len(body) == 1 and isinstance(body[0], ast.Return), (
        "{}.{} must be a single return of an expression; anything else is control flow".format(
            class_name, prop_name
        )
    )

    for node in ast.walk(body[0]):
        kind = type(node)

        if kind in (ast.If, ast.IfExp, ast.BoolOp, ast.Compare):
            pytest.fail(
                "{}.{} branches or compares — that is a decision, and decisions belong in the "
                "domain module where the threshold can be frozen and mutated".format(
                    class_name, prop_name)
            )
        if kind in (ast.For, ast.While, ast.Try, ast.Lambda, ast.ListComp, ast.DictComp):
            pytest.fail("{}.{} contains control flow".format(class_name, prop_name))
        if kind in (ast.Import, ast.ImportFrom):
            pytest.fail("{}.{} imports".format(class_name, prop_name))

        if isinstance(node, ast.BinOp) and not isinstance(node.op, ALLOWED_BINOPS):
            pytest.fail("{}.{} uses a non-arithmetic operator {}".format(
                class_name, prop_name, type(node.op).__name__))

        if isinstance(node, ast.Call):
            fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            assert fname not in FORBIDDEN_DERIVED_CALLS, (
                "{}.{} calls {}() — quantization and clamping inside a projection bake an "
                "output policy into an internal value".format(class_name, prop_name, fname)
            )
            assert fname in ALLOWED_DERIVED_CALLS, (
                "{}.{} calls {}(); only {} are permitted".format(
                    class_name, prop_name, fname, ", ".join(sorted(ALLOWED_DERIVED_CALLS)))
            )

        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            assert node.value.id == "self", (
                "{}.{} reads {}.{} — a derived field may read only its own fields".format(
                    class_name, prop_name, node.value.id, node.attr)
            )


@pytest.mark.parametrize("key", sorted(DERIVED_FIELDS))
def test_derived_field_is_total_over_valid_construction(key):
    """The projection must never have to decide what a zero denominator means.

    That decision — mispriced leg? impossible order? — is a domain judgement. Guaranteeing it at
    construction is what lets the projection stay pure algebra instead of growing a fallback.
    """
    from decimal import Decimal as D

    class_name, prop_name = key
    if class_name == "LotConsumption":
        buy = trades.NetTradeResult("0x1", "0xa", core.ClassificationStatus.VALID_BUY,
                                    sold_asset="q", bought_asset="t", sold_raw_amount=1,
                                    bought_raw_amount=1, quote_asset="q")
        with pytest.raises(ValueError):
            trades.LotConsumption(buy, buy, 1, D("0"), D("10"))
        with pytest.raises(ValueError):
            trades.LotConsumption(buy, buy, 1, D("-5"), D("10"))
    else:
        with pytest.raises(ValueError):
            metrics.CopySimulation(D("1000"), core.AssetTier.MAJOR, D("0"), D("0"),
                                   D("0"), D("0"), True)
        with pytest.raises(ValueError):
            metrics.CopySimulation(D("1000"), core.AssetTier.MAJOR, D("100"), D("150"),
                                   D("0"), D("0"), True)


def test_derived_fields_are_not_serialized_as_authoritative():
    """``canonicalise`` walks dataclass *fields*, never properties.

    So an artifact carries the primitives and not the projection, and a consumer that wants the
    projection recomputes it. That is what stops an artifact claiming one return while carrying
    primitives implying another.
    """
    from decimal import Decimal as D

    buy = trades.NetTradeResult("0x1", "0xa", core.ClassificationStatus.VALID_BUY,
                                sold_asset="q", bought_asset="t", sold_raw_amount=1,
                                bought_raw_amount=1, quote_asset="q")
    consumption = trades.LotConsumption(buy, buy, 100, D("100"), D("120"))
    payload = serialization.canonicalise(consumption)

    assert "realized_return" not in payload
    assert payload["allocated_cost_usd"] == "100"
    assert payload["proceeds_usd"] == "120"
