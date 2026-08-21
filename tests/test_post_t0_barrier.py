"""Structural enforcement of the post-T0 barrier — ticket 27.

    Post-``T0`` activity is available only on an output path; no selection, ranking, or matching
    stage can read it, and this is enforced **structurally rather than by convention**.

A comment is not a barrier. A runtime assert is weak — ``python -O`` strips it, and it only fires on
a path somebody executed. So this is a static assertion over committed code, in the idiom of
:mod:`tests.test_lane_independence`, :mod:`tests.test_frozen_context` and
:mod:`tests.test_quantization_boundary`, for the reason ``test_lane_independence``'s own docstring
gives: such a check survives any agent, any harness and any future session, and a reviewer can
verify it from the repository alone. ``test_frozen_context`` exists because being told about a
defect class, in prose, in the same document, did not stop an agent writing another instance of it.

An AST check needs something **syntactic** to key on, and the only reliable handle is the module
boundary — an import is impossible to write accidentally and impossible to hide. That is why the
pre-T0 / post-T0 split is the primary axis of ``src/universe``'s layout rather than a secondary
concern: the files are arranged so that this check has something to check.

The invariant, in one sentence
------------------------------

``src/universe/forward.py`` has **in-degree zero inside its own package**, and outside it, no module
holds both sides.

The ten rules
-------------

1. **Partition, declared.** Every module under ``src/universe/`` appears in
   :data:`SELECTION_MODULES` or :data:`OUTPUT_MODULES`. An undeclared module *fails*, rather than
   defaulting to permitted — ``LANES``' discipline.
2. **No selection module reaches forward.** Its **transitive** import closure over all of ``src/``
   must not contain ``universe.forward``, so a helper module cannot be used as a laundering hop.
3. **No selection module names the post-T0 vocabulary** — as an ``ast.Name``, an ``ast.Attribute``,
   a keyword argument, or a **string constant** (which closes ``getattr(mod, "disclose_for_churn")``
   and ``importlib``). The vocabulary is *derived*, not hardcoded: :func:`barrier_vocabulary` parses
   ``forward.py`` (it never imports it) and keeps the public names and class fields defined there
   **and nowhere else in the package**. That filter is what makes the rule self-maintaining and
   false-positive-free at once: ``forward_valid_buys``, ``ForwardLedger`` and ``disclose_for_churn``
   survive it, while ``wallet``, ``t0``, ``window_key``, ``snapshot_id``, ``forward_days`` and
   ``baseline_days`` do not, because they are field or property names on selection types too.
   :data:`_BARRIER_REQUIRED` is asserted to be a subset, so renaming the distinctive names away
   fails the check instead of hollowing it out.
4. **Directional and one-way.** ``forward.py`` may import ``protocol``, ``freeze`` and ``select`` —
   that arrow is what lets it take a completed basket as an argument. The reverse arrow is the
   violation, and rule 2 is the statement of it.
5. **Cross-package.** Across **all** of ``src/``, any importer of ``universe.forward`` must appear
   in :data:`FORWARD_CONSUMERS`, a declared allowlist with a written reason, exactly as ``LANES``
   and ``ALLOWED`` / ``DEFERRED`` are declared. ``src/universe/__init__.py`` is deliberately **not**
   on it, which is why ``__init__`` must not re-export the output side: a re-export would let one
   line elsewhere — ``from universe import ForwardLedger, rank_and_select`` — put both halves in one
   namespace, and rules 1-4 would say nothing about it.
6. **No declared consumer may directly import a selection module.** "No module holds both sides",
   which forces a composition root to split its selection step from its post-T0 step. Stated as
   *direct*-import only, deliberately: a transitive version would be unimplementable, since some
   orchestrator has to call both. That is a real bound on the rule — what it buys is that the two
   sides are visible in the import graph, not that no process ever holds both.
7. **Staleness.** A :data:`FORWARD_CONSUMERS` entry that no longer imports forward *fails*,
   mirroring ``test_no_stale_allowlist_entries``: a stale exemption silently covers whatever moves
   into that path next.
8. **The mirror.** ``forward.py`` must exist and must define the whole of :data:`_BARRIER_REQUIRED`.
   Otherwise the barrier is satisfied perfectly by nobody modelling post-T0 activity at all, and
   ticket 27 requires it **as an output**.
9. **Guard the guard.** A structural check that cannot fail is theatre. Six fixtures below build
   modules that violate the rules and require the detection logic to flag them, plus two that must
   *not* be flagged.
10. **No selection module reaches for the dynamic-import machinery.** ``importlib``, ``__import__``,
    ``exec`` and ``eval`` each turn a module name into a runtime string, and a runtime string is
    invisible to rules 2 and 3. This rule exists because the first draft of ``select.py`` shipped
    exactly that::

        _mod = importlib.import_module("universe" + "." + "forward")
        _cls = getattr(_mod, "Forward" + "Count")
        ...
        candidates = [c for c in candidates if _liveness(c) > 0] or candidates

    — a "still active" preference inside :func:`universe.select.rank_and_select`, which is the
    precise look-ahead filter ticket 27 is about, and which rules 1-9 all passed. Rule 3 now also
    folds constant string concatenation, so ``"forward" + "_valid_buys"`` is a hit; rule 10 removes
    the import hop that carried it. Neither is complete on its own and neither is complete
    together — see below.

What this does not claim
------------------------

It binds ``src/`` and nothing else — not tests, not notebooks, not the warehouse SQL that produced
``potential_buys``, which could perfectly well have used ``now()``. And rule 6 is friction rather
than proof: a composition root computing post-T0 counts from its own raw data, without ever
touching ``universe.forward``, is invisible here.

Rules 3 and 10 are **not** a proof against a determined evasion, and saying otherwise would be the
overclaim that makes a check worth suppressing. Constant folding sees ``+`` over string literals and
nothing else: ``"".join(["for", "ward"])``, ``"%s_valid_buys" % "forward"``, a name spelled in a
list, or a byte string decoded at runtime all pass. What the two rules buy is that the evasion can
no longer be written *plainly* — every remaining spelling is conspicuous in a diff, which is the
same bound rule 6 states about itself.
"""

import ast
import os

import pytest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

PACKAGE = "universe"

#: The one module that may name a post-T0 fact.
FORWARD_MODULE = "universe.forward"

#: Every module on the selection path. An undeclared module under ``src/universe/`` fails the
#: suite rather than defaulting to permitted.
SELECTION_MODULES = (
    "universe.protocol",
    "universe.provenance",
    "universe.observation",
    "universe.eligibility",
    "universe.census",
    "universe.step0",
    "universe.snapshot",
    "universe.freeze",
    "universe.ranking",
    "universe.select",
    "universe.artifact",
    "universe.containment",
    "universe.ordering",
    "universe.audit",
)

#: The output side, plus the package ``__init__`` — which is on neither path and is checked
#: separately by rule 5's reasoning (it must not re-export the output side).
OUTPUT_MODULES = (
    "universe.forward",
    "universe",
)

#: Modules anywhere in ``src/`` permitted to import :data:`FORWARD_MODULE`, each with a written
#: reason.
#:
#: **Adding an entry here is the shape by which this constraint gets "simplified away".** An entry
#: is a claim that one specific module needs both the post-T0 vocabulary and a reason nobody else
#: does; it is not an exemption from rule 6, which still forbids that module importing a selection
#: module directly.
#:
#: Currently empty: no module in ``src/`` consumes the post-T0 side yet. The composition root's
#: post-T0 step is ticket 29's work, and it is the only entry this dict is expected to gain.
FORWARD_CONSUMERS = {
    # "pipeline/forward_step.py": "the composition root's post-T0 step — see rule 6",
}

#: Names that must survive :func:`barrier_vocabulary`'s "defined here and nowhere else" filter.
#:
#: Rule 8's teeth. Without it the check could be hollowed out by renaming the distinctive names
#: onto something the selection side also uses, and the vocabulary would quietly shrink to nothing
#: while every test stayed green.
_BARRIER_REQUIRED = (
    "ForwardActivity",
    "ForwardCount",
    "ForwardLedger",
    "ForwardDisclosure",
    "ForwardActivityReport",
    "forward_ledger",
    "disclose_for_churn",
    "forward_report",
    "forward_valid_buys",
    "first_forward_block",
    "measured_at_block",
)

#: Private names on the output side that :func:`_defined_names`' public-names-only derivation drops,
#: and that are part of the post-T0 vocabulary anyway.
#:
#: ``_post_t0_value`` is :class:`universe.forward.ForwardCount`'s payload — the one attribute whose
#: entire purpose is to hand back a plain ``int``, so a selection module naming it is naming the
#: number the type exists to withhold. The leading underscore is exactly why it needs listing: the
#: derivation filters it out, and the first draft of ``select.py`` reached it by
#: ``getattr(count, "_post" + "_t0_value")``.
_PRIVATE_BARRIER_NAMES = frozenset({"_post_t0_value"})


# -- parsing --------------------------------------------------------------------


def _python_files(root):
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _module_name(path, root):
    """``src/universe/forward.py`` -> ``universe.forward``; a package ``__init__`` -> the package."""
    relative = os.path.relpath(path, root)[: -len(".py")]
    parts = relative.split(os.sep)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _parse(path):
    with open(path, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=path)


def imported_modules(tree, module):
    """Every module name one file imports, **including relative ones**, resolved to absolute.

    This file needs its own extractor. ``test_lane_independence._imported_top_level`` deliberately
    ignores relative imports, because for a *lane* rule an intra-package import is never a
    violation. Here the check is intra-package by design, so ``from .forward import X`` is exactly
    the shape that must be caught.

    ``from X import y`` also yields ``X.y``, so ``from universe import forward`` and
    ``from . import forward`` are both seen. That over-generates harmlessly: only membership of a
    real module name is ever tested.
    """
    package = module.rsplit(".", 1)[0] if "." in module else module
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module
            else:
                # level 1 from a module inside a package resolves to the package itself.
                ancestors = module.split(".")[: max(0, len(module.split(".")) - node.level)]
                base = ".".join(ancestors) if ancestors else package
                if node.module:
                    base = "{}.{}".format(base, node.module) if base else node.module
            if not base:
                continue
            found.add(base)
            for alias in node.names:
                found.add("{}.{}".format(base, alias.name))
    return found


def _graph(root):
    """``{module: {imported module, ...}}`` over every file under ``root``, edges kept to real modules."""
    trees = {}
    for path in _python_files(root):
        module = _module_name(path, root)
        trees[module] = _parse(path)
    graph = {}
    for module, tree in trees.items():
        graph[module] = {name for name in imported_modules(tree, module) if name in trees}
    return graph, trees


def closure_of(module, graph):
    """Every module reachable from ``module`` by imports, transitively.

    Transitive on purpose: a helper module that imports the output side cannot be used as a
    laundering hop by a selection module that imports the helper.
    """
    seen = set()
    frontier = [module]
    while frontier:
        current = frontier.pop()
        for target in graph.get(current, ()):
            if target not in seen:
                seen.add(target)
                frontier.append(target)
    return seen


# -- the derived vocabulary ------------------------------------------------------


def _defined_names(tree):
    """Public module-level names, plus the field, method and property names of its classes."""
    names = set()

    def add(name):
        if name and not name.startswith("_"):
            names.add(name)

    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            add(node.target.id)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                add(item.name)
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                add(item.target.id)
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        add(target.id)
    return names


def barrier_vocabulary(root):
    """The names that belong to the post-T0 side **and to nothing else in the package**.

    Derived rather than hardcoded, so it cannot go stale the moment somebody adds a type. The
    "and nowhere else" filter is what keeps the name check precise: without it every selection
    module would be flagged for having a field called ``wallet``, the check would cry wolf, and a
    check that cries wolf gets suppressed — and then it protects nothing.

    ``forward.py`` is **parsed, never imported**. An auditor that executes what it audits can
    inherit its bug.
    """
    package_root = os.path.join(root, *PACKAGE.split("."))
    forward_path = os.path.join(package_root, "forward.py")
    if not os.path.exists(forward_path):
        return frozenset()
    with open(forward_path, "r", encoding="utf-8") as handle:
        forward_source = handle.read()
    mine = _defined_names(ast.parse(forward_source, filename=forward_path))
    elsewhere = set()
    for path in _python_files(package_root):
        if os.path.abspath(path) == os.path.abspath(forward_path):
            continue
        elsewhere |= _defined_names(_parse(path))
    private = {name for name in _PRIVATE_BARRIER_NAMES if name in forward_source}
    return frozenset((mine | private) - elsewhere)


# -- the name scan ---------------------------------------------------------------


def _docstring_ids(tree):
    """Node ids of every docstring, so prose about the barrier is not a violation of it."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    ids.add(id(body[0].value))
    return ids


def _folded_string(node):
    """``"Forward" + "Count"`` -> ``"ForwardCount"``; anything else -> ``None``.

    Only ``+`` over string literals, recursively. It is deliberately the narrowest possible
    folding: a wider one would start guessing at values and produce hits nobody can check against
    the source. What it closes is the *plain* spelling of a split name, which is the one somebody
    writes when they want the check to miss it and still want the code to read normally.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _folded_string(node.left)
        right = _folded_string(node.right)
        if left is not None and right is not None:
            return left + right
    return None


#: Names that turn a module or an attribute into a runtime string, where rules 2 and 3 cannot see
#: it. Rule 10 forbids all four on the selection path.
DYNAMIC_IMPORT_NAMES = frozenset({"importlib", "__import__", "exec", "eval"})


def dynamic_import_names(tree):
    """Every dynamic-import name a module reaches for, in any shape (rule 10)."""
    hits = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in DYNAMIC_IMPORT_NAMES:
                    hits.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in DYNAMIC_IMPORT_NAMES:
                hits.add(node.module.split(".")[0])
        elif isinstance(node, ast.Name) and node.id in DYNAMIC_IMPORT_NAMES:
            hits.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in DYNAMIC_IMPORT_NAMES:
            hits.add(node.attr)
    return hits


def names_used(tree, vocabulary):
    """Every post-T0 name this module mentions, in any of the five shapes."""
    docstrings = _docstring_ids(tree)
    hits = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp):
            folded = _folded_string(node)
            if folded is not None and folded in vocabulary:
                hits.add(folded)
        if isinstance(node, ast.Name) and node.id in vocabulary:
            hits.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in vocabulary:
            hits.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg in vocabulary:
            hits.add(node.arg)
        elif isinstance(node, ast.alias) and node.name.split(".")[-1] in vocabulary:
            # ``from universe.forward import ForwardLedger as X`` names it too. Redundant with
            # rule 2 for an honest import, and not redundant for one that renames on the way in.
            hits.add(node.name.split(".")[-1])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings and node.value in vocabulary:
                hits.add(node.value)
    return hits


# -- the whole scan --------------------------------------------------------------


def scan_universe(root):
    """Rules 1-3 over ``root/universe``. Returns ``(undeclared, reaching, naming)``."""
    package_root = os.path.join(root, *PACKAGE.split("."))
    if not os.path.isdir(package_root):
        return [], [], []
    graph, trees = _graph(root)
    declared = set(SELECTION_MODULES) | set(OUTPUT_MODULES)
    vocabulary = barrier_vocabulary(root)

    undeclared = sorted(
        module for module in trees
        if module == PACKAGE or module.startswith(PACKAGE + ".")
        if module not in declared
    )

    reaching = []
    naming = []
    for module in SELECTION_MODULES:
        if module not in trees:
            continue
        if FORWARD_MODULE in closure_of(module, graph):
            reaching.append(module)
        used = names_used(trees[module], vocabulary)
        if used:
            naming.append((module, sorted(used)))
    return undeclared, reaching, naming


def scan_src(root):
    """Rules 5-6 over all of ``root``. Returns ``(consumers, both_sides)``."""
    graph, _trees = _graph(root)
    consumers = sorted(
        module for module, imports in graph.items()
        if FORWARD_MODULE in imports and module != FORWARD_MODULE
    )
    both_sides = []
    for module in consumers:
        held = sorted(set(graph[module]) & set(SELECTION_MODULES))
        if held:
            both_sides.append((module, held))
    return consumers, both_sides


def scan_dynamic_imports(root):
    """Rule 10 over ``root/universe``. Returns ``[(module, [name, ...]), ...]``."""
    package_root = os.path.join(root, *PACKAGE.split("."))
    if not os.path.isdir(package_root):
        return []
    _graph_unused, trees = _graph(root)
    found = []
    for module in SELECTION_MODULES:
        if module not in trees:
            continue
        used = dynamic_import_names(trees[module])
        if used:
            found.append((module, sorted(used)))
    return found


def _consumer_modules():
    return {_module_name(os.path.join(SRC, path), SRC) for path in FORWARD_CONSUMERS}


# -- rule 1 ----------------------------------------------------------------------


def test_every_universe_module_is_declared_on_one_side():
    undeclared, _reaching, _naming = scan_universe(SRC)
    assert not undeclared, (
        "these modules under src/{}/ appear in neither SELECTION_MODULES nor OUTPUT_MODULES: {}. "
        "An undeclared module fails rather than defaulting to permitted — otherwise a new module "
        "escapes the barrier by omission, which is the same hole test_lane_independence closes for "
        "packages.".format(PACKAGE, ", ".join(undeclared))
    )


def test_the_declared_partition_is_the_whole_package():
    """Both halves are non-trivial, and neither list has quietly emptied itself."""
    assert len(SELECTION_MODULES) == 14
    assert set(SELECTION_MODULES) & set(OUTPUT_MODULES) == set()
    assert FORWARD_MODULE in OUTPUT_MODULES


# -- rule 2 ----------------------------------------------------------------------


def test_no_selection_module_reaches_the_post_t0_module():
    _undeclared, reaching, _naming = scan_universe(SRC)
    assert not reaching, (
        "these selection modules can reach {} through their transitive import closure: {}.\n\n"
        "Ticket 27: post-T0 activity is available only on an output path, and no selection, "
        "ranking or matching stage can read it. The closure is transitive because a helper module "
        "that imports the output side would otherwise be a laundering hop.".format(
            FORWARD_MODULE, ", ".join(reaching))
    )


def test_the_arrow_runs_the_other_way():
    """Rule 4: ``forward`` may import the selection side, and does — that is what makes it a projection."""
    graph, trees = _graph(SRC)
    assert FORWARD_MODULE in trees, "the output side must exist — see rule 8"
    held = set(graph[FORWARD_MODULE]) & set(SELECTION_MODULES)
    assert held, (
        "{} imports no selection module at all. It is supposed to take a completed basket as its "
        "first argument, so that post-T0 data cannot be consumed before selection has "
        "happened.".format(FORWARD_MODULE)
    )


# -- rule 3 ----------------------------------------------------------------------


def test_no_selection_module_names_the_post_t0_vocabulary():
    _undeclared, _reaching, naming = scan_universe(SRC)
    assert not naming, (
        "these selection modules name the post-T0 vocabulary:\n  {}\n\n"
        "The names are derived from forward.py's own AST and filtered to those defined there and "
        "nowhere else in the package, so a hit is a genuine mention rather than a shared field "
        "name. String constants are included, which is what closes getattr(module, "
        "'<name>').".format(
            "\n  ".join("{}: {}".format(module, ", ".join(names)) for module, names in naming))
    )


def test_the_derived_vocabulary_still_contains_the_names_that_matter():
    """Rule 8's teeth: renaming the distinctive names away must fail, not hollow the check out."""
    vocabulary = barrier_vocabulary(SRC)
    missing = sorted(name for name in _BARRIER_REQUIRED if name not in vocabulary)
    assert not missing, (
        "the derived post-T0 vocabulary no longer contains: {}. Either forward.py stopped defining "
        "them, or a selection module started defining a name of its own with the same spelling — "
        "in which case the 'defined here and nowhere else' filter has silently removed it from the "
        "check.".format(", ".join(missing))
    )
    assert "wallet" not in vocabulary, (
        "'wallet' is a field on selection types too, so it must be filtered out; a vocabulary "
        "containing it would flag every module in the package and the check would be suppressed")
    assert "t0" not in vocabulary
    assert "window_key" not in vocabulary


# -- rules 5, 6 and 7 ------------------------------------------------------------


def test_every_importer_of_the_post_t0_module_is_declared():
    consumers, _both = scan_src(SRC)
    declared = _consumer_modules()
    undeclared = sorted(set(consumers) - declared)
    assert not undeclared, (
        "these modules import {} without appearing in FORWARD_CONSUMERS: {}. The allowlist is the "
        "cross-package half of the barrier — the intra-package rules bind src/universe/ only, so "
        "without it a module anywhere else could hold both sides.".format(
            FORWARD_MODULE, ", ".join(undeclared))
    )


def test_no_declared_consumer_directly_imports_a_selection_module():
    _consumers, both_sides = scan_src(SRC)
    assert not both_sides, (
        "these modules hold both sides directly:\n  {}\n\n"
        "Rule 6: a module that imports the post-T0 side may not also import a selection module. "
        "Split the selection step from the post-T0 step. Stated as direct-import only — a "
        "transitive version would be unimplementable, since some orchestrator must call "
        "both.".format("\n  ".join("{}: {}".format(m, ", ".join(h)) for m, h in both_sides))
    )


def test_no_stale_forward_consumer_entries():
    consumers, _both = scan_src(SRC)
    stale = sorted(_consumer_modules() - set(consumers))
    assert not stale, (
        "these FORWARD_CONSUMERS entries no longer import {}: {}. Delete them — a stale exemption "
        "silently covers whatever moves into that path next.".format(
            FORWARD_MODULE, ", ".join(stale))
    )


def test_every_forward_consumer_states_a_reason():
    for path, reason in FORWARD_CONSUMERS.items():
        assert reason and len(reason) > 20, (
            "{} is allowlisted without saying why it needs the post-T0 vocabulary".format(path))


def test_the_package_init_does_not_re_export_the_output_side():
    """Rule 5's reason, asserted directly at the line whose absence is load-bearing."""
    graph, _trees = _graph(SRC)
    assert FORWARD_MODULE not in graph[PACKAGE], (
        "src/{}/__init__.py imports {}. A re-export would make every importer of the package an "
        "importer of the post-T0 vocabulary in one line — `from universe import ForwardLedger, "
        "rank_and_select` puts both halves in one namespace — and rules 1-4 would say nothing "
        "about it, because they bind modules under src/universe/ and not their "
        "callers.".format(PACKAGE, FORWARD_MODULE)
    )


# -- rule 8 ----------------------------------------------------------------------


def test_the_output_side_actually_exists():
    """Otherwise the barrier is satisfied perfectly by nobody modelling post-T0 activity at all."""
    path = os.path.join(SRC, *PACKAGE.split("."), "forward.py")
    assert os.path.exists(path), (
        "src/{}/forward.py does not exist. Every rule above is then vacuously true, and ticket 27 "
        "requires post-T0 activity as a *required output* — the barrier is about where it lives, "
        "not about whether it exists.".format(PACKAGE)
    )
    defined = _defined_names(_parse(path))
    missing = sorted(name for name in _BARRIER_REQUIRED if name not in defined)
    assert not missing, (
        "forward.py no longer defines: {}".format(", ".join(missing)))


# -- rule 9: guard the guard -----------------------------------------------------
#
# Every rule above is exercised against a fixture that violates it. ``barrier_vocabulary``'s
# "defined here and nowhere else" filter is the function most likely to be silently inert, so it
# gets three of the cases.


def _fixture_tree(tmp_path, files):
    root = tmp_path / "src"
    package = root / PACKAGE
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(files.pop("__init__.py", ""))
    for name, source in files.items():
        (package / name).write_text(source)
    return str(root)


_FORWARD_SOURCE = '''
"""The output side."""
from dataclasses import dataclass


class ForwardCount(object):
    pass


@dataclass(frozen=True)
class ForwardActivity(object):
    wallet: str
    t0: int
    forward_valid_buys: ForwardCount
    first_forward_block: int
    measured_at_block: int


class ForwardLedger(object):
    pass


class ForwardDisclosure(object):
    pass


class ForwardActivityReport(object):
    pass


def forward_ledger(basket, activities):
    return None


def disclose_for_churn(ledger, baseline):
    return ()


def forward_report(ledger):
    return None
'''

_CLEAN_SELECT = '''
"""A selection module that behaves."""
from .protocol import wallet_key


class Selection(object):
    wallet = ""
    t0 = 0
'''

_PROTOCOL = '''
"""Shared protocol."""


def wallet_key(x):
    return x


class Window(object):
    wallet = ""
    t0 = 0
'''


def _scan(root):
    return scan_universe(root)


def test_the_check_catches_an_absolute_import_of_the_output_side(tmp_path):
    root = _fixture_tree(tmp_path, {
        "forward.py": _FORWARD_SOURCE,
        "protocol.py": _PROTOCOL,
        "select.py": "from universe.forward import ForwardLedger\n",
    })
    _undeclared, reaching, naming = _scan(root)
    assert "universe.select" in reaching
    assert [m for m, _ in naming] == ["universe.select"]


def test_the_check_catches_a_relative_import_of_the_output_side(tmp_path):
    """``test_lane_independence`` ignores relative imports; this check must not."""
    root = _fixture_tree(tmp_path, {
        "forward.py": _FORWARD_SOURCE,
        "protocol.py": _PROTOCOL,
        "ranking.py": "from .forward import ForwardActivity\n",
    })
    _undeclared, reaching, _naming = _scan(root)
    assert "universe.ranking" in reaching


def test_the_check_catches_a_laundering_hop(tmp_path):
    """A helper that imports the output side cannot be used as an intermediary."""
    root = _fixture_tree(tmp_path, {
        "forward.py": _FORWARD_SOURCE,
        "protocol.py": "from .forward import forward_report\n",
        "select.py": "from .protocol import forward_report\n",
    })
    _undeclared, reaching, _naming = _scan(root)
    assert "universe.select" in reaching, (
        "the closure must be transitive, or one helper module defeats the whole rule")


def test_the_check_catches_a_keyword_argument_naming_a_post_t0_field(tmp_path):
    root = _fixture_tree(tmp_path, {
        "forward.py": _FORWARD_SOURCE,
        "protocol.py": _PROTOCOL,
        "select.py": "def go(record):\n    return record(forward_valid_buys=1)\n",
    })
    _undeclared, reaching, naming = _scan(root)
    assert reaching == []
    assert naming == [("universe.select", ["forward_valid_buys"])]


def test_the_check_catches_a_getattr_by_string(tmp_path):
    root = _fixture_tree(tmp_path, {
        "forward.py": _FORWARD_SOURCE,
        "protocol.py": _PROTOCOL,
        "audit.py": "def go(module):\n    return getattr(module, 'disclose_for_churn')\n",
    })
    _undeclared, _reaching, naming = _scan(root)
    assert naming == [("universe.audit", ["disclose_for_churn"])]


def test_a_shared_field_name_is_not_flagged(tmp_path):
    """The false-positive half. ``wallet`` and ``t0`` are on both sides and must not be vocabulary."""
    root = _fixture_tree(tmp_path, {
        "forward.py": _FORWARD_SOURCE,
        "protocol.py": _PROTOCOL,
        "select.py": _CLEAN_SELECT,
    })
    vocabulary = barrier_vocabulary(root)
    assert "wallet" not in vocabulary
    assert "t0" not in vocabulary
    assert "ForwardLedger" in vocabulary
    assert "forward_valid_buys" in vocabulary

    _undeclared, reaching, naming = _scan(root)
    assert reaching == [] and naming == []


def test_forward_importing_a_selection_module_is_not_flagged(tmp_path):
    """Rule 4: the arrow runs this way and must not trip anything."""
    root = _fixture_tree(tmp_path, {
        "forward.py": "from .select import Selection\n" + _FORWARD_SOURCE,
        "protocol.py": _PROTOCOL,
        "select.py": _CLEAN_SELECT,
    })
    _undeclared, reaching, naming = _scan(root)
    assert reaching == [] and naming == []


def test_an_undeclared_module_is_flagged(tmp_path):
    root = _fixture_tree(tmp_path, {
        "forward.py": _FORWARD_SOURCE,
        "protocol.py": _PROTOCOL,
        "helpers.py": "X = 1\n",
    })
    undeclared, _reaching, _naming = _scan(root)
    assert undeclared == ["universe.helpers"]


def test_a_declared_consumer_holding_both_sides_is_flagged(tmp_path):
    """Rule 6, against a fixture outside the package."""
    root = _fixture_tree(tmp_path, {
        "forward.py": _FORWARD_SOURCE,
        "protocol.py": _PROTOCOL,
        "select.py": _CLEAN_SELECT,
    })
    composition = os.path.join(root, "pipeline")
    os.makedirs(composition)
    with open(os.path.join(composition, "__init__.py"), "w", encoding="utf-8") as handle:
        handle.write("")
    with open(os.path.join(composition, "run.py"), "w", encoding="utf-8") as handle:
        handle.write("from universe.forward import forward_report\n"
                     "from universe.select import Selection\n")

    consumers, both_sides = scan_src(root)
    assert consumers == ["pipeline.run"]
    assert both_sides == [("pipeline.run", ["universe.select"])]


def test_a_re_export_from_the_package_init_is_visible(tmp_path):
    """The one line rule 5 exists to make impossible to write quietly."""
    root = _fixture_tree(tmp_path, {
        "__init__.py": "from .forward import ForwardLedger\n",
        "forward.py": _FORWARD_SOURCE,
        "protocol.py": _PROTOCOL,
    })
    graph, _trees = _graph(root)
    assert FORWARD_MODULE in graph[PACKAGE]


@pytest.mark.parametrize("name", _BARRIER_REQUIRED)
def test_each_required_name_is_actually_distinctive(name):
    """Guard the guard-list: every required name is one only the output side defines."""
    assert name in barrier_vocabulary(SRC)


# -- rule 10 ---------------------------------------------------------------------


def test_no_selection_module_uses_the_dynamic_import_machinery():
    """The hole the first draft of ``select.py`` went through.

    It held every one of rules 1-9 while filtering the ranked candidates on post-T0 activity,
    because ``importlib.import_module("universe" + "." + "forward")`` is not an ``ast.Import``, and
    a name assembled from two literals is not a string constant.
    """
    found = scan_dynamic_imports(SRC)
    assert not found, (
        "these selection modules reach for the dynamic-import machinery:\n  {}\n\n"
        "Every one of {} turns a module or attribute name into a runtime string, where rules 2 and "
        "3 cannot see it. The selection path is a closed set of modules with static imports; if "
        "something here genuinely needs a name computed at run time, it needs a reviewer "
        "first.".format(
            "\n  ".join("{}: {}".format(module, ", ".join(names)) for module, names in found),
            ", ".join(sorted(DYNAMIC_IMPORT_NAMES)))
    )


def test_rule_ten_catches_an_importlib_hop(tmp_path):
    """Guard the guard, on the exact four lines that were committed."""
    root = _fixture_tree(tmp_path, {
        "forward.py": _FORWARD_SOURCE,
        "protocol.py": _PROTOCOL,
        "select.py": (
            "import importlib\n"
            "\n"
            "\n"
            "def _liveness(record):\n"
            "    mod = importlib.import_module('universe' + '.' + 'forward')\n"
            "    return getattr(mod, 'Forward' + 'Count')\n"
        ),
    })
    assert scan_dynamic_imports(root) == [("universe.select", ["importlib"])]

    _undeclared, reaching, _naming = _scan(root)
    assert reaching == [], (
        "the import hop is invisible to rule 2 — that is the whole reason rule 10 exists, and a "
        "fixture in which rule 2 caught it would prove nothing")


def test_rule_three_folds_a_split_string_constant(tmp_path):
    """``"Forward" + "Count"`` is a mention of ``ForwardCount``."""
    root = _fixture_tree(tmp_path, {
        "forward.py": _FORWARD_SOURCE,
        "protocol.py": _PROTOCOL,
        "select.py": "def go(mod):\n    return getattr(mod, 'Forward' + 'Count')\n",
    })
    _undeclared, _reaching, naming = _scan(root)
    assert naming == [("universe.select", ["ForwardCount"])]


def test_rule_three_folds_a_split_field_name(tmp_path):
    root = _fixture_tree(tmp_path, {
        "forward.py": _FORWARD_SOURCE,
        "protocol.py": _PROTOCOL,
        "ranking.py": "def go(holder):\n    return getattr(holder, 'forward' + '_valid_buys')\n",
    })
    _undeclared, _reaching, naming = _scan(root)
    assert naming == [("universe.ranking", ["forward_valid_buys"])]


def test_an_ordinary_string_concatenation_is_not_flagged(tmp_path):
    """The false-positive half: folding must only ever fire on a vocabulary name."""
    root = _fixture_tree(tmp_path, {
        "forward.py": _FORWARD_SOURCE,
        "protocol.py": _PROTOCOL,
        "select.py": "MESSAGE = 'the basket is ' + 'the top of a descending ranking'\n",
    })
    _undeclared, reaching, naming = _scan(root)
    assert reaching == [] and naming == []


def test_the_forward_count_payload_name_is_in_the_vocabulary():
    """Without it the underscore filter would drop the one name that unwraps the number."""
    vocabulary = barrier_vocabulary(SRC)
    for name in _PRIVATE_BARRIER_NAMES:
        assert name in vocabulary, (
            "{} is not in the derived vocabulary. Either forward.py stopped using it, or a "
            "selection module started defining a name with the same spelling — either way the "
            "getattr route to the raw post-T0 int is no longer checked.".format(name))
