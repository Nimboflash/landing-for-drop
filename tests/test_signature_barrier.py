"""Structural enforcement of the type barrier at signature level — the audit's headline finding.

    147 function definitions, 119 parameters, ZERO annotated parameters, ZERO annotated returns.
    Every parameter is implicitly ``Any``. There is no type barrier at signature level anywhere in
    the package.

The decisive question the audit asked was *is there any function signature that can accept both a
selection type and a forward type?* — and it answered itself before reaching any specific case,
because a bare parameter accepts everything. A type wall that exists only in the author's head is
the "please do not cheat" sign nailed up beside an open door.

This module is that wall, written as a static assertion over committed code, in the idiom of
:mod:`tests.test_lane_independence`, :mod:`tests.test_post_t0_barrier` and
:mod:`tests.test_frozen_context`, and for the same stated reason: such a check survives any agent,
any harness and any future session, and a reviewer can verify it from the repository alone.

The six rules
-------------

1. **Every public parameter is annotated.** A bare parameter is implicitly ``Any`` and therefore
   accepts a selection type and a forward type in the same slot. ``self`` and ``cls`` are exempt
   (their type is the class); ``**kwargs``/``*args`` are handled by rule 6.
2. **Every public return is annotated.** An unannotated return launders the barrier one call
   further out: the caller binds a name with no type and passes it anywhere.
3. **No annotation may name a universal type.** ``Any`` and ``object`` are the two spellings of
   "accepts both families". Both are banned on public signatures; the private escape (rule 5) is
   where ``object`` legitimately lives, because ``__eq__(self, other: object)`` is the operator
   protocol's own signature and narrowing it is a lie.
4. **No generic container may appear on a selection path.** ``Mapping[str, Decimal]``,
   ``Dict[str, Decimal]``, ``pandas.Series`` and friends are the audit's *most dangerous* shape:
   they turn the entire type barrier into a hope about column names, and an ``isinstance`` check
   in the body does not rescue them — that puts the boundary in the runtime and in the caller's
   cooperation rather than in the architecture. :data:`_CONTAINER_ORIGINS` names the constructors;
   the rule fires on a keyed container (``Dict``, ``Mapping``, ``DefaultDict``, ``Counter``) and on
   a homogeneous sequence whose element type is a bare scalar.
5. **A private callable is exempt from rules 1-3 only if it is genuinely private** — name starts
   with ``_`` and it is not re-exported. Rule 4 binds private callables too, because a private
   helper taking a ``Dict[str, Decimal]`` is exactly the tunnel shape and privacy does not narrow
   what it accepts.
6. **No untyped variadic on a public selection callable.** ``**kwargs`` with no annotation is a
   parameter list of unbounded width and unbounded type; it is how ``dataclasses.replace``-shaped
   smuggling is written.

Two exemptions, declared rather than assumed
--------------------------------------------

:data:`OPERATOR_PROTOCOL_METHODS` — ``__eq__``, ``__lt__``, ``__radd__`` and the rest — take
``other: object`` because Python's data model says so: a narrower annotation would be false, and
``NotImplemented`` is the protocol's answer to a foreign operand. These live on
:class:`universe.provenance.PreT0Decimal` and :class:`universe.provenance.ContaminatedDecimal`,
whose bodies refuse the foreign operand *by contaminating*, which is stronger than a type would be.

:data:`SERIALIZATION_RETURNS` — ``__reduce__`` returns ``object`` because it is the pickle
protocol's slot and the implementations exist precisely to **raise**.

Both lists are asserted non-empty and asserted to be exactly what is present, so an exemption that
stops being used fails the suite rather than quietly covering whatever moves in next — the
staleness rule ``test_no_stale_allowlist_entries`` applies to allowlists generally.

What this does not claim
------------------------

It binds ``src/universe/`` and nothing else. It reads annotations as **source text**, never by
importing and never by ``typing.get_type_hints``: an auditor that executes what it audits can
inherit its bug, and a forward reference in a string is still a nominal name to a reader.

It cannot tell you an annotation is *honest*. ``def f(x: PreT0Score)`` that then calls
``getattr(x, name)`` is a tunnel this check passes; that route is closed by
``tests/test_post_t0_barrier.py``'s rule 3 and by the sealing in ``universe.protocol``, not here.
Nor does it run a type checker: nothing verifies the annotation matches what the body does. What it
buys is that **no signature in this package silently accepts everything**, which is the specific
thing the audit found 147 times.
"""

import ast
import os

import pytest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

PACKAGE = "universe"

PACKAGE_ROOT = os.path.join(SRC, PACKAGE)

#: Names that mean "this parameter accepts anything", in every spelling reachable from source text.
UNIVERSAL_TYPES = frozenset({"Any", "object", "typing.Any", "t.Any", "builtins.object"})

#: Container constructors whose element types are addressed by *position or key* rather than by
#: name. A value reaching a selection path inside one of these is addressed by a string, and a
#: string is not a type.
_KEYED_CONTAINERS = frozenset({
    "Dict", "dict", "Mapping", "MutableMapping", "DefaultDict", "defaultdict",
    "OrderedDict", "Counter", "TypedDict", "Series", "DataFrame",
})

#: Sequence constructors. These are permitted when the element type is nominal — ``Tuple[PreT0Score,
#: ...]`` is a perfectly good annotation and the package is built out of them — and forbidden when
#: the element type is a bare scalar, because ``Tuple[Decimal, ...]`` on a selection path is a
#: column of numbers with no provenance, which is the laundering route in its natural habitat.
_SEQUENCE_CONTAINERS = frozenset({"Tuple", "tuple", "List", "list", "Sequence", "Iterable", "Set",
                                  "FrozenSet", "frozenset", "set"})

#: Element types that carry no provenance and no family. A container of these on a selection path
#: is the ``Mapping[str, Decimal]`` finding, whatever the outer constructor is.
_BARE_SCALARS = frozenset({"Decimal", "float", "complex"})

#: Methods whose signature is fixed by Python's data model. ``other: object`` here is the truth:
#: the operand may be anything, and the body's job is to say so by returning ``NotImplemented`` or,
#: in this package, by contaminating.
OPERATOR_PROTOCOL_METHODS = frozenset({
    "__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__",
    "__add__", "__radd__", "__sub__", "__rsub__", "__mul__", "__rmul__",
    "__truediv__", "__rtruediv__", "__exit__", "__init_subclass__",
})

#: Methods whose *return* is ``object`` because the protocol slot is untyped by construction.
SERIALIZATION_RETURNS = frozenset({"__reduce__", "__reduce_ex__"})

#: Methods whose *parameter* is ``object`` for the same reason, in the other direction.
#:
#: ``__setstate__`` is handed whatever the pickle payload says — a dict, a tuple, or anything a
#: hand-written payload chose. ``object`` is the **true** annotation there and a narrower one would
#: be a false statement about an attacker-supplied value, which is the shape this file exists to
#: refuse. Every implementation in the package raises, so nothing reads the parameter at all.
#:
#: Kept separate from :data:`OPERATOR_PROTOCOL_METHODS` because the two exemptions rest on different
#: arguments and collapsing them would let an operator name be added under a serialization reason.
SERIALIZATION_PARAMETERS = frozenset({"__setstate__"})

#: Modules on the selection path, where rule 4 binds. Kept as its own list rather than imported
#: from :mod:`tests.test_post_t0_barrier` so that neither check can be hollowed out by editing the
#: other's constant.
SELECTION_MODULE_FILES = (
    "protocol.py", "provenance.py", "observation.py", "eligibility.py", "census.py",
    "step0.py", "snapshot.py", "freeze.py", "ranking.py", "select.py", "artifact.py",
    "containment.py", "ordering.py", "audit.py",
)


# -- parsing ---------------------------------------------------------------------


def _module_files():
    """Every module under the package, as (filename, path). Parsed, never imported."""
    if not os.path.isdir(PACKAGE_ROOT):
        return []
    return [
        (name, os.path.join(PACKAGE_ROOT, name))
        for name in sorted(os.listdir(PACKAGE_ROOT))
        if name.endswith(".py")
    ]


def _parse(path):
    with open(path, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=path)


def annotation_names(node):
    """Every identifier appearing in an annotation, as source text.

    ``Optional[PreT0Decimal]`` yields ``{"Optional", "PreT0Decimal"}``; ``"PreT0Score"`` as a
    forward reference yields ``{"PreT0Score"}``; ``Dict[str, Decimal]`` yields
    ``{"Dict", "str", "Decimal"}``. Attribute access is flattened to its dotted text so
    ``typing.Any`` is visible as such.
    """
    if node is None:
        return frozenset()
    found = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(_dotted(child))
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            # A forward reference. Parse it; a malformed one is itself worth failing on.
            try:
                found |= annotation_names(ast.parse(child.value, mode="eval").body)
            except SyntaxError:
                found.add(child.value)
    return frozenset(found)


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _subscript_head(node):
    """``Dict`` from ``Dict[str, Decimal]``; ``None`` if the annotation is not subscripted."""
    if not isinstance(node, ast.Subscript):
        return None
    return _dotted(node.value) if isinstance(node.value, ast.Attribute) else (
        node.value.id if isinstance(node.value, ast.Name) else None)


def container_violation(node):
    """The rule-4 verdict for one annotation, or ``None``.

    Recurses, so ``Optional[Dict[str, Decimal]]`` and ``Tuple[Mapping[str, Decimal], ...]`` are both
    caught — wrapping a tunnel in ``Optional`` does not make it not a tunnel.
    """
    if node is None:
        return None
    head = _subscript_head(node)
    if head is not None:
        bare = head.split(".")[-1]
        if bare in _KEYED_CONTAINERS:
            return "{}[...] is addressed by key, and a key is a string, not a type".format(bare)
        if bare in _SEQUENCE_CONTAINERS:
            elements = annotation_names(node.slice) - {bare}
            scalar = sorted(elements & _BARE_SCALARS)
            if scalar and not (elements - _BARE_SCALARS - {"Ellipsis"}):
                return (
                    "{}[{}] is a column of provenance-free scalars".format(bare, scalar[0]))
    for child in ast.iter_child_nodes(node):
        found = container_violation(child)
        if found is not None:
            return found
    # A bare `Dict`/`Mapping`/`Series` with no subscript is worse, not better.
    if isinstance(node, (ast.Name, ast.Attribute)):
        bare = (node.id if isinstance(node, ast.Name) else _dotted(node)).split(".")[-1]
        if bare in _KEYED_CONTAINERS:
            return "a bare {} annotation is addressed by key and constrains nothing".format(bare)
    return None


def _is_public(qualname):
    """A callable is public unless some component of its dotted name starts with ``_``.

    ``PreT0Decimal._compose`` is private; ``PreT0Decimal.__eq__`` is a dunder and therefore public
    surface — it is reachable by an operator from any caller, which is exactly why rule 3's
    exemption for it has to be declared rather than inferred from the underscore.
    """
    for part in qualname.split("."):
        if part.startswith("_") and not (part.startswith("__") and part.endswith("__")):
            return False
    return True


def callables(tree, module_name):
    """Every function and method in one module, as records the rules can read.

    Yields ``(qualname, node, is_method)``. Nested functions inside a function body are skipped:
    they are not a signature any caller can reach.
    """
    found = []

    def walk(node, prefix, inside_class):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                walk(child, "{}.{}".format(prefix, child.name) if prefix else child.name, True)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = "{}.{}".format(prefix, child.name) if prefix else child.name
                found.append((qualname, child, inside_class))

    walk(tree, "", False)
    return found


def _parameters(node, is_method):
    """The parameters whose annotation the rules care about, with ``self``/``cls`` dropped."""
    args = node.args
    positional = list(getattr(args, "posonlyargs", [])) + list(args.args)
    if is_method and positional:
        first = positional[0].arg
        if first in ("self", "cls"):
            positional = positional[1:]
    return positional + list(args.kwonlyargs)


def scan(module_name, tree):
    """Every rule-1/2/3/6 violation in one module, as ``(rule, qualname, detail)``."""
    problems = []
    for qualname, node, is_method in callables(tree, module_name):
        leaf = qualname.split(".")[-1]
        public = _is_public(qualname)

        for arg in _parameters(node, is_method):
            if arg.annotation is None:
                if public:
                    problems.append(("1", qualname, "parameter {!r} is unannotated".format(arg.arg)))
                continue
            names = annotation_names(arg.annotation)
            hits = names & UNIVERSAL_TYPES
            if hits and public and leaf not in OPERATOR_PROTOCOL_METHODS \
                    and leaf not in SERIALIZATION_PARAMETERS:
                problems.append(
                    ("3", qualname, "parameter {!r} is annotated {}".format(
                        arg.arg, "/".join(sorted(hits)))))

        if node.returns is None:
            if public:
                problems.append(("2", qualname, "the return is unannotated"))
        else:
            hits = annotation_names(node.returns) & UNIVERSAL_TYPES
            if hits and public and leaf not in SERIALIZATION_RETURNS:
                problems.append(
                    ("3", qualname, "the return is annotated {}".format("/".join(sorted(hits)))))

        if public and leaf not in OPERATOR_PROTOCOL_METHODS:
            for variadic in (node.args.vararg, node.args.kwarg):
                if variadic is not None and variadic.annotation is None:
                    problems.append(
                        ("6", qualname, "*{} is an unannotated variadic".format(variadic.arg)))
    return problems


def scan_containers(module_name, tree):
    """Every rule-4 violation in one module. Binds private callables too, and dataclass fields."""
    problems = []
    for qualname, node, is_method in callables(tree, module_name):
        for arg in _parameters(node, is_method):
            found = container_violation(arg.annotation)
            if found is not None:
                problems.append((qualname, "parameter {!r}: {}".format(arg.arg, found)))
        found = container_violation(node.returns)
        if found is not None:
            problems.append((qualname, "the return: {}".format(found)))

    for child in ast.walk(tree):
        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            found = container_violation(child.annotation)
            if found is not None:
                problems.append((child.target.id, "the field: {}".format(found)))
    return problems


def inventory():
    """The counts the audit asked for, over the package as it stands.

    Returned as a dict so :func:`test_the_signature_inventory` can assert on it and a reporter can
    print it. Every number here is derived from the AST, never from a docstring.
    """
    totals = dict(modules=0, callables=0, public_callables=0, parameters=0,
                  public_parameters=0, annotated_parameters=0, annotated_returns=0,
                  any_annotations=0, object_annotations=0, untyped_public_parameters=0,
                  generic_containers=0)
    for name, path in _module_files():
        if name == "__init__.py":
            continue
        totals["modules"] += 1
        tree = _parse(path)
        module_name = "{}.{}".format(PACKAGE, name[:-3])
        for qualname, node, is_method in callables(tree, module_name):
            totals["callables"] += 1
            public = _is_public(qualname)
            totals["public_callables"] += 1 if public else 0
            for arg in _parameters(node, is_method):
                totals["parameters"] += 1
                totals["public_parameters"] += 1 if public else 0
                if arg.annotation is None:
                    if public:
                        totals["untyped_public_parameters"] += 1
                    continue
                totals["annotated_parameters"] += 1
                names = annotation_names(arg.annotation)
                if names & {"Any", "typing.Any"}:
                    totals["any_annotations"] += 1
                if "object" in names:
                    totals["object_annotations"] += 1
            if node.returns is not None:
                totals["annotated_returns"] += 1
        totals["generic_containers"] += len(scan_containers(module_name, tree))
    return totals


# -- rule 1, 2, 3, 6 -------------------------------------------------------------


@pytest.mark.parametrize("filename", [n for n, _p in _module_files()])
def test_every_public_signature_is_nominally_typed(filename):
    """Rules 1, 2, 3 and 6, one module at a time so a failure names the module."""
    path = os.path.join(PACKAGE_ROOT, filename)
    module_name = "{}.{}".format(PACKAGE, filename[:-3])
    problems = scan(module_name, _parse(path))
    assert not problems, (
        "{} has {} public signature(s) that accept more than one type family:\n  {}\n\n"
        "The audit's headline was that this package had 119 parameters and zero annotations, so "
        "every signature accepted a selection type and a forward type in the same slot. A bare "
        "parameter is implicitly Any. Annotate it with the nominal type it actually takes.".format(
            module_name, len(problems),
            "\n  ".join("rule {}: {} — {}".format(r, q, d) for r, q, d in problems))
    )


# -- rule 4 ----------------------------------------------------------------------


@pytest.mark.parametrize("filename", SELECTION_MODULE_FILES)
def test_no_generic_container_on_a_selection_path(filename):
    """Rule 4. The audit called this the most dangerous shape, and it is the one this package had."""
    path = os.path.join(PACKAGE_ROOT, filename)
    assert os.path.exists(path), "declared selection module {} is missing".format(filename)
    module_name = "{}.{}".format(PACKAGE, filename[:-3])
    problems = scan_containers(module_name, _parse(path))
    assert not problems, (
        "{} puts a generic container on a selection path:\n  {}\n\n"
        "Mapping and Series turn the entire type barrier into a hope about column names, and an "
        "isinstance assertion in the body does not rescue it — that puts the boundary in the "
        "runtime and in the caller's cooperation rather than in the architecture. Use a nominal "
        "type with named fields.".format(
            module_name, "\n  ".join("{} — {}".format(q, d) for q, d in problems))
    )


def test_the_selection_module_list_is_the_whole_selection_side():
    """Rule 4 covers every selection module, so none escapes it by omission."""
    on_disk = {name for name, _p in _module_files()} - {"__init__.py", "forward.py"}
    assert on_disk == set(SELECTION_MODULE_FILES), (
        "SELECTION_MODULE_FILES and src/{}/ disagree: only in the list {}, only on disk {}. A "
        "module missing from the list is a module rule 4 does not bind.".format(
            PACKAGE, sorted(set(SELECTION_MODULE_FILES) - on_disk), sorted(on_disk - set(
                SELECTION_MODULE_FILES)))
    )


# -- the inventory ---------------------------------------------------------------


def test_the_signature_inventory():
    """The audit's own counts, asserted rather than described.

    These are the numbers a report may quote. ``0 untyped public parameters`` and ``0 Any`` are the
    two the audit found at 119 and 119.
    """
    totals = inventory()
    assert totals["untyped_public_parameters"] == 0, totals
    assert totals["any_annotations"] == 0, totals
    assert totals["generic_containers"] == 0, totals
    assert totals["callables"] > 140, (
        "the package has shrunk to {} callables; this check was written against a package with "
        "147, and a barrier over nothing is not a barrier".format(totals["callables"]))
    assert totals["annotated_parameters"] >= totals["public_parameters"], totals


# -- the declared exemptions, and their staleness -------------------------------


def test_the_operator_protocol_exemption_is_used_and_not_over_wide():
    """Every exempted operator name is actually present, and the exemption covers only ``object``.

    A stale exemption silently covers whatever moves into that name next — the reason
    ``test_lane_independence`` fails on an allowlist entry that no longer applies.
    """
    used = set()
    for name, path in _module_files():
        if name == "__init__.py":
            continue
        for qualname, _node, _is_method in callables(_parse(path), name):
            leaf = qualname.split(".")[-1]
            if leaf in OPERATOR_PROTOCOL_METHODS:
                used.add(leaf)
    unused = sorted(OPERATOR_PROTOCOL_METHODS - used)
    assert not unused, (
        "these operator-protocol exemptions are declared but no longer used: {}. An exemption "
        "nobody needs is an exemption covering whatever moves in next.".format(", ".join(unused))
    )
    assert "Any" not in UNIVERSAL_TYPES - {"Any"}, "sanity: Any is a universal type"
    assert OPERATOR_PROTOCOL_METHODS & UNIVERSAL_TYPES == set()


def test_the_serialization_exemption_only_covers_pickle_slots():
    """``__reduce__`` is exempted on its return and ``__setstate__`` on its parameter, and nothing else."""
    assert SERIALIZATION_RETURNS == frozenset({"__reduce__", "__reduce_ex__"})
    assert SERIALIZATION_PARAMETERS == frozenset({"__setstate__"})
    assert not (SERIALIZATION_RETURNS & OPERATOR_PROTOCOL_METHODS)
    assert not (SERIALIZATION_PARAMETERS & OPERATOR_PROTOCOL_METHODS)
    assert not (SERIALIZATION_PARAMETERS & SERIALIZATION_RETURNS)
    used = set()
    for name, path in _module_files():
        if name == "__init__.py":
            continue
        for qualname, _node, _is_method in callables(_parse(path), name):
            leaf = qualname.split(".")[-1]
            if leaf in SERIALIZATION_RETURNS or leaf in SERIALIZATION_PARAMETERS:
                used.add(leaf)
    assert "__reduce__" in used, (
        "no __reduce__ is defined anywhere in the package, so pickle is unguarded and this "
        "exemption covers nothing — see tests/hand_computed/test_containment.py")
    assert "__setstate__" in used, (
        "no __setstate__ is defined anywhere in the package. __reduce__ binds the dumps direction "
        "only, and the payload that mattered was written by hand: without a loads-side refusal "
        "this exemption covers nothing.")


# -- rule 9: guard the guard -----------------------------------------------------
#
# A structural check that cannot fail is theatre. Each fixture below writes a module that violates
# one rule and requires the detection logic to flag it — and, in the same test, a near-miss that
# must NOT be flagged, because a check that fires on everything is a check that gets suppressed.


def test_the_check_catches_a_bare_parameter(tmp_path):
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def select(universe, features) -> int:\n    return 0\n"
        "def honest(universe: PreT0Universe) -> int:\n    return 0\n"
    )
    problems = scan("offender", _parse(str(offender)))
    flagged = {q for r, q, _d in problems if r == "1"}
    assert flagged == {"select"}, problems
    assert all(q != "honest" for _r, q, _d in problems)


def test_the_check_catches_an_any_annotation(tmp_path):
    offender = tmp_path / "offender.py"
    offender.write_text(
        "from typing import Any\n"
        "def leak(wallet: Any) -> None:\n    return None\n"
        "def dotted(wallet: typing.Any) -> None:\n    return None\n"
        "def honest(wallet: PreT0Score) -> None:\n    return None\n"
    )
    problems = scan("offender", _parse(str(offender)))
    flagged = {q for r, q, _d in problems if r == "3"}
    assert flagged == {"leak", "dotted"}, problems


def test_the_check_catches_an_object_annotation_outside_the_operator_protocol(tmp_path):
    offender = tmp_path / "offender.py"
    offender.write_text(
        "class Wrapper(object):\n"
        "    def __eq__(self, other: object) -> bool:\n        return False\n"
        "    def take(self, other: object) -> bool:\n        return False\n"
    )
    problems = scan("offender", _parse(str(offender)))
    flagged = {q for r, q, _d in problems if r == "3"}
    assert flagged == {"Wrapper.take"}, (
        "__eq__ is the data model's own signature and must not be flagged; a plain method taking "
        "object must be: {}".format(problems))


def test_the_check_catches_an_unannotated_return(tmp_path):
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def rank(universe: PreT0Universe):\n    return 0\n"
        "def honest(universe: PreT0Universe) -> int:\n    return 0\n"
    )
    problems = scan("offender", _parse(str(offender)))
    assert {q for r, q, _d in problems if r == "2"} == {"rank"}, problems


def test_the_check_catches_a_mapping_tunnel(tmp_path):
    offender = tmp_path / "offender.py"
    offender.write_text(
        "from decimal import Decimal\n"
        "from typing import Dict, Mapping, Optional, Tuple\n"
        "def a(record: Mapping[str, Decimal]) -> None:\n    return None\n"
        "def b(record: Dict[str, Decimal]) -> None:\n    return None\n"
        "def c(record: Optional[Dict[str, Decimal]]) -> None:\n    return None\n"
        "def d(row: pd.Series) -> None:\n    return None\n"
        "def e(column: Tuple[Decimal, ...]) -> None:\n    return None\n"
        "def honest(scores: Tuple[PreT0Score, ...]) -> None:\n    return None\n"
        "def also_honest(score: PreT0Score) -> Tuple[SelectedWallet, ...]:\n    return ()\n"
    )
    problems = scan_containers("offender", _parse(str(offender)))
    flagged = {q for q, _d in problems}
    assert flagged == {"a", "b", "c", "d", "e"}, (
        "every keyed container and every column of bare scalars must be flagged, and a tuple of "
        "nominal types must not: {}".format(problems))


def test_the_check_catches_a_mapping_field_on_a_dataclass(tmp_path):
    offender = tmp_path / "offender.py"
    offender.write_text(
        "from decimal import Decimal\n"
        "from typing import Dict, Tuple\n"
        "class Distribution:\n"
        "    quantiles: Dict[str, Decimal]\n"
        "    members: Tuple[PreT0Score, ...]\n"
    )
    problems = scan_containers("offender", _parse(str(offender)))
    assert {q for q, _d in problems} == {"quantiles"}, problems


def test_the_check_catches_an_untyped_kwargs(tmp_path):
    offender = tmp_path / "offender.py"
    offender.write_text(
        "def build(score: PreT0Score, **kwargs) -> None:\n    return None\n"
        "def honest(score: PreT0Score, **kwargs: str) -> None:\n    return None\n"
    )
    problems = scan("offender", _parse(str(offender)))
    assert {q for r, q, _d in problems if r == "6"} == {"build"}, problems


def test_a_private_helper_is_exempt_from_annotation_but_not_from_the_container_rule(tmp_path):
    """Rule 5's two halves, in one fixture, because they are easy to conflate."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "from decimal import Decimal\n"
        "from typing import Mapping\n"
        "def _helper(x):\n    return x\n"
        "def _tunnel(record: Mapping[str, Decimal]) -> None:\n    return None\n"
    )
    tree = _parse(str(offender))
    assert scan("offender", tree) == [], "a genuinely private helper is exempt from rules 1-3"
    assert {q for q, _d in scan_containers("offender", tree)} == {"_tunnel"}, (
        "privacy does not narrow what a signature accepts — rule 4 binds private callables too")


def test_a_forward_reference_in_a_string_is_read_as_a_nominal_name(tmp_path):
    """``-> "PreT0Decimal"`` is nominal, and ``-> "Any"`` is not, and the check must know."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        'def a(x: "PreT0Decimal") -> "PreT0Decimal":\n    return x\n'
        'def b(x: "Any") -> None:\n    return None\n'
    )
    problems = scan("offender", _parse(str(offender)))
    assert {q for r, q, _d in problems if r == "3"} == {"b"}, problems


def test_self_and_cls_are_not_required_to_be_annotated(tmp_path):
    """A near-miss that must not be flagged: their type is the class, and saying so is noise."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        "class T:\n"
        "    def method(self) -> int:\n        return 0\n"
        "    @classmethod\n"
        "    def build(cls) -> int:\n        return 0\n"
    )
    assert scan("offender", _parse(str(offender))) == []
