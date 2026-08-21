"""Structural enforcement of the frozen 38-digit decimal context.

``contracts.numeric`` freezes precision at 38 digits and exports ``calc``, ``divide``, ``sub``,
``add`` and ``mul`` so that arithmetic in the numeric path holds it. Python's ``decimal`` module
does not cooperate: every operator — ``+ - * /``, unary ``-``, ``abs()``, ``round()``,
``normalize()`` — rounds its result to whatever context happens to be current, which is the
default 28 digits unless a block says otherwise. A 38-digit value that meets a bare operator loses
ten digits and says nothing about it. The truncated value looks entirely reasonable, which is why
review catches this and tests do not.

It has shipped three times:

1. ``LotConsumption.realized_return`` — ``divide(...) - Decimal("1")``, in the frozen seam itself.
   ``divide`` held 38 digits; the subtraction that followed it landed back in the ambient 28.
2. ``canonicalise`` — ``value.normalize()`` under the ambient context. The canonical form, and
   therefore the freeze-manifest hash, moved with a global the seam does not control: the same
   value hashed three different ways at ambient precision 9, 28 and 38.
3. ``fifo/matching.py`` — ``abs(divide(...))``, written *inside the repair for* (1), by an agent
   that had been briefed on (1) in the same document it was working from.

(3) is the one that motivates this file. Being told about the class, in prose, in the same
document, did not prevent writing another instance of it. So the check is structural: a static
assertion over committed code, in the style of :mod:`tests.test_lane_independence`, that survives
any agent, any harness and any future session.

The rule
--------

Decimal arithmetic in ``src/`` must be either

* routed through ``calc`` / ``divide`` / ``sub`` / ``add`` / ``mul``, which hold the context
  internally, or
* lexically inside a ``with localcontext(CALCULATION_CONTEXT):`` block.

``localcontext()`` with no argument does **not** count: it copies the ambient context, so it
freezes nothing.

Comparisons (``< <= == != >= >``) are not flagged. ``Decimal.__lt__`` and friends are exact and
consult no context. ``abs()`` *written inside* a comparison is still flagged, because the rounding
happens before the comparison sees the value.

What the heuristic can and cannot see
-------------------------------------

There is no type inference here, so "is this operand a Decimal?" is decided by a syntactic
vocabulary built from the tree itself, described in :func:`_decimal_vocabulary` and
:class:`_ModuleFacts`. It **can** see:

* ``Decimal(...)`` and the ``contracts.numeric`` primitives, including under an import alias
  (``from decimal import Decimal as _D``);
* attribute names annotated ``Decimal`` anywhere in ``src/`` — every dataclass field on the seam,
  so ``leg.usd`` and ``comparison.difference`` are known;
* names bound to any of the above, transitively, plus loop and comprehension targets over a
  container of them;
* parameters annotated ``Decimal``, and unannotated parameters proven Decimal by a call site
  **in the same module**;
* names proven Decimal by being compared against one.

It **cannot** see, and these are the live blind spots:

* **Unannotated parameters crossing a module boundary.** ``_binding_constraint(size, ...)`` is
  known only because ``depth/execution.py`` also contains its caller. The same function in
  another module would be invisible. This is the largest hole.
* **Values that arrive through an opaque container** — a dict parsed from JSON, ``**kwargs``,
  ``getattr``, a list built by ``append`` in a loop.
* **Deferred execution.** A function defined inside a ``with localcontext`` block inherits the
  block's protection, because that is what such a nested definition is normally for. A closure
  that escaped the block and was called outside it would be missed.
* **Runtime context switching.** Only ``with localcontext(CALCULATION_CONTEXT)`` is recognised.
  ``decimal.setcontext()`` or mutating ``getcontext().prec`` is neither credited nor flagged.
* **``src/`` only.** Test files are not scanned, and a recomputation written with a bare operator
  in a test will not be caught here.

The rounding-method set (``normalize``, ``sqrt``, ``ln``, ``exp``, ``log10``, ``fma``, ``scaleb``,
``shift``, ``rotate``, ``logb``) is flagged with **no** operand check, because nothing else in this
repository defines those names, so requiring the receiver to be provably Decimal would only add a
way to miss defect (2). ``quantize`` is deliberately absent: it takes an explicit scale and raises
``InvalidOperation`` rather than truncating silently, and quantizing at the reporting boundary is
the policy.

The direction of the operand heuristic is otherwise toward silence: an operand that cannot be
shown to be a Decimal is not flagged. A check that cries wolf gets suppressed, and then it
protects nothing.
"""

import ast
import collections
import os

import pytest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

#: The frozen context. A ``with`` block naming anything else — including bare ``localcontext()``,
#: which copies the ambient context — does not count as protection.
FROZEN_CONTEXT_NAME = "CALCULATION_CONTEXT"

#: Calls that return a Decimal *and* hold the frozen context internally. Arithmetic routed through
#: these is the sanctioned form; a call to one is also a Decimal-valued expression.
FROZEN_PRIMITIVES = frozenset({"calc", "divide", "sub", "add", "mul"})

#: Other calls whose result is a Decimal. These do not make surrounding arithmetic safe; they only
#: tell the operand heuristic what it is looking at.
DECIMAL_VALUED_CALLS = FROZEN_PRIMITIVES | frozenset({
    "Decimal", "quantize_usd", "quantize_ratio", "quantize_pp", "require_finite",
    "quantize", "copy_abs", "copy_negate", "next_plus", "next_minus",
})

#: Decimal methods that consult the ambient context and round. Flagged unconditionally — see the
#: module docstring for why the operand check is skipped for these.
ROUNDING_METHODS = frozenset({
    "normalize", "sqrt", "exp", "ln", "log10", "fma", "scaleb", "shift", "rotate", "logb",
    "remainder_near",
})

#: Builtins that round a Decimal argument to the ambient context.
ROUNDING_BUILTINS = frozenset({"abs", "round"})

#: Builtins that pass a Decimal through without rounding it, so they propagate Decimal-ness to the
#: result but are not themselves violations. ``sum`` *does* add, but it adds under the ambient
#: context and is therefore treated as arithmetic below.
TRANSPARENT_BUILTINS = frozenset({"max", "min", "sorted", "list", "tuple", "next"})

_ARITHMETIC_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)


# -- allowlists -----------------------------------------------------------------
#
# Two dicts, kept apart on purpose, because "this is fine" and "this is broken and someone else
# owns the file" are different claims and collapsing them is how an allowlist stops meaning
# anything. Both are keyed ``"<path under src/>::<qualified name>"`` rather than by line number,
# so an unrelated edit above does not silently move an exemption onto different code. Both are
# checked for staleness by ``test_no_stale_allowlist_entries``: an entry that no longer matches a
# violation is a failure, not a leftover.

#: Genuine exceptions. Every entry must say why the arithmetic is exact or context-independent.
ALLOWED = {
    # (empty — the current tree needs none, and that is the state to keep it in)
}

#: Real violations of the rule, left in place because ``src/contracts/`` is the frozen seam and is
#: being edited by other agents this round. These are debts, not exemptions: each one is a genuine
#: instance of the class, reported rather than repaired. Deleting an entry without fixing the code
#: makes the suite fail, which is the intended pressure.
DEFERRED = {
    # (empty — the three seam violations recorded here were repaired rather than carried:
    #  BuyQuality.__post_init__ now sums via add() and compares via copy_abs(),
    #  CovariateBalance.balanced uses copy_abs(), and verify_redundant_derived runs its
    #  difference under the frozen context. An entry here is a debt, so the list staying
    #  empty is the state to keep it in.)
}


# -- parsing --------------------------------------------------------------------


Violation = collections.namedtuple("Violation", "path line qualname what source")


def _module_files(root):
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _parse(path):
    with open(path, "r", encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=path)


def _annotation_names_decimal(node):
    """``Decimal``, ``Optional[Decimal]``, ``Dict[X, Decimal]``, ``"Decimal"`` — all count.

    Deliberately textual. The alternative is resolving annotation expressions, which needs the
    import graph and buys nothing: no other name in this repository ends in ``Decimal``.
    """
    if node is None:
        return False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id.endswith("Decimal"):
            return True
        if isinstance(sub, ast.Attribute) and sub.attr.endswith("Decimal"):
            return True
        if isinstance(sub, ast.Str) and "Decimal" in sub.s:
            return True
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and "Decimal" in sub.value:
            return True
    return False


def _decimal_vocabulary(trees):
    """Repo-wide names that identify a Decimal on sight.

    ``attributes`` are field names annotated ``Decimal`` anywhere — the seam's dataclasses supply
    most of them, which is what lets ``comparison.difference`` be recognised in a module that never
    mentions Decimal. ``functions`` are ``-> Decimal`` returns.

    The scope is deliberately global rather than per-class: resolving ``x.usd`` to a class needs
    type inference, and a name annotated ``Decimal`` on one class being a str on another is not a
    shape this codebase has.
    """
    attributes, functions = set(), set()
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if _annotation_names_decimal(node.annotation):
                    attributes.add(node.target.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _annotation_names_decimal(node.returns):
                    functions.add(node.name)
    return attributes, functions


def _called_name(node):
    """The bare name of whatever is being called: ``f``, ``mod.f`` and ``obj.method`` all reduce."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_frozen_context_block(item):
    """``with localcontext(CALCULATION_CONTEXT):`` and nothing looser."""
    expr = item.context_expr
    if not isinstance(expr, ast.Call) or _called_name(expr.func) != "localcontext":
        return False
    return any(_called_name(arg) == FROZEN_CONTEXT_NAME
               or (isinstance(arg, ast.Name) and arg.id == FROZEN_CONTEXT_NAME)
               for arg in expr.args)


def _bound_names(target):
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names = []
        for element in target.elts:
            names.extend(_bound_names(element))
        return names
    return []


def _rebound_names(function):
    """Names the body assigns to. A parameter that is reassigned is no longer just its argument."""
    rebound = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                rebound.update(_bound_names(target))
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            rebound.update(_bound_names(node.target))
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            rebound.update(_bound_names(node.target))
    return rebound


def _producer_aliases(tree):
    """``from decimal import Decimal as _D`` — without this, ``serialization.py`` reads as clean."""
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                original = alias.name.split(".")[-1]
                if alias.asname and original in DECIMAL_VALUED_CALLS:
                    aliases[alias.asname] = original
    return aliases


# -- per-module inference -------------------------------------------------------


class _ModuleFacts(object):
    """What this module's names hold, computed to a fixed point.

    Two sources of imprecision are handled by iterating rather than by ordering: a name may be
    bound to a Decimal below the line that uses it (loop accumulators), and a parameter may only
    be shown to be a Decimal by a call site defined later in the file. Both settle in two or three
    passes; ``_ROUNDS`` is generous.
    """

    _ROUNDS = 6

    def __init__(self, tree, attributes, decimal_functions):
        self.attributes = attributes
        self.decimal_functions = decimal_functions
        self.aliases = _producer_aliases(tree)
        self.functions = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions[node.name] = node
        self.decimal_params = collections.defaultdict(set)
        self.module_names = set()
        self.containers = set()
        self._settle(tree)

    def _settle(self, tree):
        for _ in range(self._ROUNDS):
            before = (frozenset(self.module_names), frozenset(self.containers),
                      frozenset((k, frozenset(v)) for k, v in self.decimal_params.items()))
            self.module_names, self.containers = self._names_in(tree, set(), set(), frozenset())
            for name, node in sorted(self.functions.items()):
                self.names_for(node)
            after = (frozenset(self.module_names), frozenset(self.containers),
                     frozenset((k, frozenset(v)) for k, v in self.decimal_params.items()))
            if before == after:
                break

    def names_for(self, function):
        """The Decimal-valued names visible inside one function body."""
        names = set(self.module_names)
        containers = set(self.containers)
        arguments = function.args
        parameters = set()
        for arg in (list(getattr(arguments, "posonlyargs", [])) + arguments.args
                    + arguments.kwonlyargs):
            parameters.add(arg.arg)
            if _annotation_names_decimal(arg.annotation):
                names.add(arg.arg)
        names |= self.decimal_params[function.name]
        return self._names_in(function, names, containers,
                              parameters - _rebound_names(function))[0]

    def _names_in(self, root, names, containers, provable_by_comparison):
        """Flow-insensitive union of everything bound to a Decimal anywhere under ``root``."""
        for _ in range(self._ROUNDS):
            grew = False
            for node in ast.walk(root):
                for name in self._bindings(node, names, containers, provable_by_comparison):
                    if name not in names:
                        names.add(name)
                        grew = True
                for name in self._container_bindings(node, names, containers):
                    if name not in containers:
                        containers.add(name)
                        grew = True
                if isinstance(node, ast.Call):
                    self._record_call_site(node, names, containers)
            if not grew:
                break
        return names, containers

    def _bindings(self, node, names, containers, provable_by_comparison=frozenset()):
        if isinstance(node, ast.Assign):
            if self.is_decimal(node.value, names, containers):
                for target in node.targets:
                    for name in _bound_names(target):
                        yield name
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if (_annotation_names_decimal(node.annotation)
                    or self.is_decimal(node.value, names, containers)):
                yield node.target.id
        elif isinstance(node, ast.AugAssign):
            if self.is_decimal(node.value, names, containers):
                for name in _bound_names(node.target):
                    yield name
        elif isinstance(node, ast.NamedExpr) if hasattr(ast, "NamedExpr") else False:
            if self.is_decimal(node.value, names, containers):
                for name in _bound_names(node.target):
                    yield name
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            if self.is_decimal_container(node.iter, names, containers):
                for name in _bound_names(node.target):
                    yield name
        elif isinstance(node, ast.comprehension):
            if self.is_decimal_container(node.iter, names, containers):
                for name in _bound_names(node.target):
                    yield name
        elif isinstance(node, ast.Compare):
            # A name compared against a Decimal is a Decimal — but only for parameters the body
            # never rebinds. Without that restriction, ``index = int(position)`` followed by
            # ``if position != index`` infects an int with the Decimal-ness of the value it was
            # truncated from, and every later ``index - 1`` is a false positive. The evidence is
            # weak, so it is spent only where nothing stronger is available: an unannotated
            # parameter arriving from another module.
            operands = [node.left] + list(node.comparators)
            if any(self.is_decimal(operand, names, containers) for operand in operands):
                for operand in operands:
                    if isinstance(operand, ast.Name) and operand.id in provable_by_comparison:
                        yield operand.id
        elif isinstance(node, ast.withitem):
            if node.optional_vars is not None and self.is_decimal(
                    node.context_expr, names, containers):
                for name in _bound_names(node.optional_vars):
                    yield name

    def _container_bindings(self, node, names, containers):
        if isinstance(node, ast.Assign) and self.is_decimal_container(
                node.value, names, containers):
            for target in node.targets:
                for name in _bound_names(target):
                    yield name
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if _annotation_names_decimal(node.annotation) and isinstance(
                    node.annotation, ast.Subscript):
                yield node.target.id

    def _record_call_site(self, node, names, containers):
        """A Decimal passed to a function defined in this module pins down its parameter.

        This is the whole of the interprocedural analysis, and it stops at the module boundary.
        See the module docstring — it is the largest blind spot, and it is stated rather than
        papered over.
        """
        called = _called_name(node.func)
        target = self.functions.get(called)
        if target is None:
            return
        parameters = (list(getattr(target.args, "posonlyargs", [])) + target.args.args
                      + target.args.kwonlyargs)
        positional = [p.arg for p in parameters]
        for index, argument in enumerate(node.args):
            if index < len(positional) and self.is_decimal(argument, names, containers):
                self.decimal_params[called].add(positional[index])
        for keyword in node.keywords:
            if keyword.arg and self.is_decimal(keyword.value, names, containers):
                self.decimal_params[called].add(keyword.arg)

    # -- the operand heuristic --

    def _resolve(self, node):
        called = _called_name(node)
        return self.aliases.get(called, called)

    def is_decimal(self, node, names, containers):
        if node is None:
            return False
        if isinstance(node, ast.Call):
            called = self._resolve(node.func)
            if called in DECIMAL_VALUED_CALLS or called in self.decimal_functions:
                return True
            if called in ROUNDING_METHODS:
                return True
            if called in ROUNDING_BUILTINS or called in TRANSPARENT_BUILTINS or called == "sum":
                return any(self.is_decimal(a, names, containers) for a in node.args) or any(
                    self.is_decimal_container(a, names, containers) for a in node.args)
            return False
        if isinstance(node, ast.Name):
            return node.id in names
        if isinstance(node, ast.Attribute):
            return node.attr in self.attributes
        if isinstance(node, ast.BinOp):
            return (self.is_decimal(node.left, names, containers)
                    or self.is_decimal(node.right, names, containers))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return self.is_decimal(node.operand, names, containers)
        if isinstance(node, ast.IfExp):
            return (self.is_decimal(node.body, names, containers)
                    or self.is_decimal(node.orelse, names, containers))
        if isinstance(node, ast.Subscript):
            return self.is_decimal_container(node.value, names, containers)
        return False

    def is_decimal_container(self, node, names, containers):
        """A list/dict/generator whose elements are Decimals, so its loop target is one."""
        if node is None:
            return False
        if isinstance(node, ast.Name):
            return node.id in containers
        if isinstance(node, ast.Attribute):
            return node.attr in self.attributes
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return self.is_decimal(node.elt, names, containers)
        if isinstance(node, ast.DictComp):
            return self.is_decimal(node.value, names, containers)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return bool(node.elts) and all(
                self.is_decimal(e, names, containers) for e in node.elts)
        if isinstance(node, ast.Dict):
            return bool(node.values) and all(
                self.is_decimal(v, names, containers) for v in node.values)
        if isinstance(node, ast.Call):
            called = self._resolve(node.func)
            if called in ("values", "keys", "sorted", "list", "tuple", "reversed", "set"):
                return any(self.is_decimal_container(a, names, containers) for a in node.args) or (
                    isinstance(node.func, ast.Attribute)
                    and self.is_decimal_container(node.func.value, names, containers))
        return False


# -- the walk -------------------------------------------------------------------


class _Walker(ast.NodeVisitor):
    """Flags unguarded Decimal arithmetic, tracking the enclosing ``with`` blocks as it goes.

    The ``with`` tracking is the difference between a check and a nuisance: a previous scan of this
    tree found 57 raw hits of which nearly all were legitimately inside a frozen block.
    """

    def __init__(self, path, facts):
        self.path = path
        self.facts = facts
        self.depth = 0
        self.scope = []
        self.names = set(facts.module_names)
        self.containers = set(facts.containers)
        self.violations = []

    # -- scope --

    def visit_With(self, node):
        guarded = any(_is_frozen_context_block(item) for item in node.items)
        for item in node.items:
            self.visit(item.context_expr)
        if guarded:
            self.depth += 1
        for statement in node.body:
            self.visit(statement)
        if guarded:
            self.depth -= 1

    visit_AsyncWith = visit_With

    def visit_ClassDef(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node):
        saved_names, saved_containers = self.names, self.containers
        self.names = self.facts.names_for(node)
        self.containers = set(self.facts.containers)
        self.scope.append(node.name)
        # ``self.depth`` is deliberately *not* reset. A nested def inside a frozen block is
        # normally there to be called inside it; see the deferred-execution blind spot.
        for decorator in node.decorator_list:
            self.visit(decorator)
        for statement in node.body:
            self.visit(statement)
        self.scope.pop()
        self.names, self.containers = saved_names, saved_containers

    visit_AsyncFunctionDef = visit_FunctionDef

    # -- flagging --

    def _flag(self, node, what):
        self.violations.append(Violation(
            path=self.path, line=node.lineno, qualname=".".join(self.scope) or "<module>",
            what=what, source=""))

    def _decimal(self, node):
        return self.facts.is_decimal(node, self.names, self.containers)

    def visit_BinOp(self, node):
        if isinstance(node.op, _ARITHMETIC_OPS) and self.depth == 0 and self._decimal(node):
            self._flag(node, "bare `{}` on a Decimal".format(_OP_TEXT[type(node.op)]))
        self.generic_visit(node)

    def visit_UnaryOp(self, node):
        if isinstance(node.op, (ast.USub, ast.UAdd)) and self.depth == 0:
            if self._decimal(node.operand):
                self._flag(node, "bare unary `{}` on a Decimal".format(
                    "-" if isinstance(node.op, ast.USub) else "+"))
        self.generic_visit(node)

    def visit_Call(self, node):
        called = self.facts._resolve(node.func)
        if self.depth == 0:
            if called in ROUNDING_BUILTINS and any(self._decimal(a) for a in node.args):
                self._flag(node, "`{}()` on a Decimal".format(called))
            elif called == "sum" and any(
                    self.facts.is_decimal_container(a, self.names, self.containers)
                    for a in node.args):
                self._flag(node, "`sum()` over Decimals")
            elif called in ROUNDING_METHODS:
                self._flag(node, "`.{}()`".format(called))
        self.generic_visit(node)


_OP_TEXT = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
    ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**",
}


# -- entry points ---------------------------------------------------------------


def scan_source(source, path="<memory>", vocabulary=None):
    """Scan one module given as text. Used by the historical-defect tests."""
    tree = ast.parse(source, filename=path)
    if vocabulary is None:
        vocabulary = _decimal_vocabulary([tree])
    attributes, functions = vocabulary
    facts = _ModuleFacts(tree, attributes, functions)
    walker = _Walker(path, facts)
    for statement in tree.body:
        walker.visit(statement)
    lines = source.splitlines()
    return [v._replace(source=lines[v.line - 1].strip() if v.line <= len(lines) else "")
            for v in walker.violations]


def scan_tree(root):
    paths = list(_module_files(root))
    trees = {path: _parse(path) for path in paths}
    vocabulary = _decimal_vocabulary(list(trees.values()))
    violations = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as fh:
            source = fh.read()
        violations.extend(scan_source(source, os.path.relpath(path, root), vocabulary))
    return violations


def _key(violation):
    return "{}::{}".format(violation.path, violation.qualname)


def _describe(violations):
    return "\n  ".join(
        "{}:{}  {}  in {}\n      {}".format(v.path, v.line, v.what, v.qualname, v.source)
        for v in violations)


# -- the tests ------------------------------------------------------------------


def test_no_unguarded_decimal_arithmetic():
    """The check itself, over the committed tree."""
    violations = [v for v in scan_tree(SRC) if _key(v) not in ALLOWED and _key(v) not in DEFERRED]
    assert not violations, (
        "Decimal arithmetic outside the frozen context:\n  {}\n\n"
        "Each of these rounds to whatever context is ambient — 28 digits by default, against "
        "values carried at 38. Route it through contracts.numeric (calc/divide/sub/add/mul) or "
        "put it inside `with localcontext(CALCULATION_CONTEXT):`. If it is genuinely exact, add "
        "it to ALLOWED with a comment saying why.".format(_describe(violations)))


def test_no_stale_allowlist_entries():
    """An exemption that no longer matches anything is a claim nobody is checking."""
    live = {_key(v) for v in scan_tree(SRC)}
    stale = sorted((set(ALLOWED) | set(DEFERRED)) - live)
    assert not stale, (
        "these allowlist entries no longer match a violation: {}. Delete them — a stale "
        "exemption silently covers whatever moves into that name next.".format(", ".join(stale)))


def test_deferred_entries_are_debts_not_exemptions():
    """Keep the two dicts from collapsing into one."""
    assert not (set(ALLOWED) & set(DEFERRED)), "an entry cannot be both allowed and deferred"
    for key, reason in DEFERRED.items():
        assert reason and len(reason) > 20, (
            "{} is deferred without saying why or who owns it".format(key))


# -- guarding the guard ---------------------------------------------------------
#
# A structural check that cannot fail is theatre. Each of the three shipped defects is rebuilt
# below and the scanner is required to flag it.


HISTORICAL_REALIZED_RETURN = '''
from decimal import Decimal
from contracts import divide

class LotConsumption(object):
    proceeds_usd: Decimal
    basis_usd: Decimal

    @property
    def realized_return(self):
        # Shipped in the seam. `divide` holds 38 digits; the subtraction lands in the ambient 28.
        return divide(self.proceeds_usd, self.basis_usd) - Decimal("1")
'''

HISTORICAL_CANONICALISE = '''
from decimal import Decimal

def canonicalise(value):
    # Shipped in contracts/serialization.py. `normalize()` respects the ambient context, so the
    # canonical form — and the freeze-manifest hash built from it — moved with a global.
    return format(value.normalize(), "f")
'''

HISTORICAL_FIFO_ABS = '''
from decimal import Decimal
from contracts import calc, divide, sub

def _check(remainder, total_usd, taken_raw, whole_raw, sign):
    # Both shapes as they were written, in the repair for the first defect. `Decimal.__abs__` and
    # `Decimal.__neg__` are arithmetic like `__sub__`: they round to the ambient context, so the
    # 38-digit ratio is truncated to 28 before it is compared to MAX_CLOSING_DRIFT, and the sign
    # goes back on a share that has just lost ten digits.
    share = divide(Decimal(taken_raw), Decimal(whole_raw))
    drift = abs(divide(sub(remainder, share), share))
    return drift, (-share if sign else share)
'''


def test_catches_the_realized_return_defect():
    violations = scan_source(HISTORICAL_REALIZED_RETURN)
    assert [v.what for v in violations] == ["bare `-` on a Decimal"], _describe(violations)
    assert violations[0].qualname == "LotConsumption.realized_return"


def test_catches_the_canonicalise_defect():
    violations = scan_source(HISTORICAL_CANONICALISE)
    assert [v.what for v in violations] == ["`.normalize()`"], _describe(violations)


def test_catches_the_fifo_abs_defect():
    violations = scan_source(HISTORICAL_FIFO_ABS)
    assert sorted(v.what for v in violations) == [
        "`abs()` on a Decimal", "bare unary `-` on a Decimal"], _describe(violations)


def test_the_same_code_inside_a_frozen_block_is_not_flagged():
    """The other half of the guard: the check must be silent on the correct form."""
    guarded = '''
from decimal import Decimal, localcontext
from contracts import CALCULATION_CONTEXT, divide, sub

def realized_return(proceeds, basis):
    with localcontext(CALCULATION_CONTEXT):
        return divide(proceeds, basis) - Decimal("1")

def routed(proceeds, basis):
    return sub(divide(proceeds, basis), Decimal("1"))
'''
    assert scan_source(guarded) == []


def test_a_bare_localcontext_is_not_protection():
    """``localcontext()`` with no argument copies the ambient context and freezes nothing."""
    source = '''
from decimal import Decimal, localcontext

def f(a):
    with localcontext():
        return Decimal(a) * Decimal("2")
'''
    assert [v.what for v in scan_source(source)] == ["bare `*` on a Decimal"]


def test_comparisons_are_not_flagged():
    """``Decimal.__lt__`` is exact and consults no context. Flagging it would be the noise that
    gets the whole check suppressed."""
    source = '''
from decimal import Decimal

def f(a, b):
    x = Decimal(a)
    y = Decimal(b)
    return x < y and x == y and x >= y
'''
    assert scan_source(source) == []


def test_int_arithmetic_is_not_flagged():
    """Raw token quantities are ``int`` by policy — exact, unrounded, and none of this check's
    business. Flagging them is how the false-positive rate gets out of hand."""
    source = '''
def f(taken_raw, whole_raw):
    return taken_raw * whole_raw + 1
'''
    assert scan_source(source) == []


def test_an_import_alias_does_not_hide_a_decimal():
    """``contracts/serialization.py`` imports ``Decimal as _D``; without alias resolution the whole
    file reads as clean."""
    source = '''
from decimal import Decimal as _D

def f(claimed, recomputed, tolerance):
    return abs(_D(str(claimed)) - recomputed) <= tolerance
'''
    assert sorted(v.what for v in scan_source(source)) == [
        "`abs()` on a Decimal", "bare `-` on a Decimal"]


def test_a_seam_annotated_attribute_is_recognised_across_modules():
    """``comparison.difference`` is a Decimal because some dataclass says so, in a file that may
    not be this one."""
    vocabulary = ({"difference"}, set())
    source = '''
def detail(comparison):
    return "difference {}".format(abs(comparison.difference))
'''
    assert [v.what for v in scan_source(source, vocabulary=vocabulary)] == ["`abs()` on a Decimal"]


def test_a_call_site_pins_down_an_unannotated_parameter():
    """The one interprocedural rule, and the one that reaches ``_binding_constraint``."""
    source = '''
from decimal import Decimal

def _binding(size, ceiling):
    return abs(size - ceiling)

def caller(raw):
    return _binding(Decimal(raw), Decimal("1"))
'''
    assert sorted(v.what for v in scan_source(source)) == [
        "`abs()` on a Decimal", "bare `-` on a Decimal"]


def test_a_nested_def_inherits_the_enclosing_block():
    """Documented as a blind spot; pinned here so it is a decision rather than an accident."""
    source = '''
from decimal import Decimal, localcontext
from contracts import CALCULATION_CONTEXT, divide

def bisect(marginal, gas, upper):
    with localcontext(CALCULATION_CONTEXT):
        def derivative(z):
            return +(marginal - divide(gas, z * z))
        return derivative(upper)
'''
    assert scan_source(source) == []
