"""Structural enforcement of validator independence.

Ticket 13 requires that the ground-truth reader "imports nothing from the pipeline's
classification, netting, FIFO, or valuation code, and this separation is **structurally enforced
rather than observed**".

The orchestration guide ranks the available controls by how much they actually protect you:

1. **This check.** A static assertion over committed code. It survives any agent misbehaviour,
   any harness configuration, and any future session, and a reviewer can verify it from the
   repository alone.
2. CODEOWNERS and branch protection.
3. A ``PreToolUse`` hook denying cross-lane reads — defence in depth, since it only holds inside
   the agent harness.

Only the first is a guarantee. This is that check.

Why it matters more than it looks: the validation gate's entire worth rests on the validator
having derived its expected outputs independently. If the two lanes share so much as a transfer
filter, they share its bug — and a shared bug is invisible to the comparison, because both sides
compute the same wrong answer and agree.
"""

import ast
import os

import pytest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

BUILDER = "builder"
VALIDATOR = "validator"
SHARED = "shared"

#: Every top-level package under ``src/`` must be declared here. An undeclared package fails the
#: suite rather than defaulting to something permissive — a new package must be classified
#: deliberately, not by omission.
LANES = {
    # The frozen seam. Shared: it interprets no chain bytes, it only names the shapes.
    "contracts": SHARED,

    # Governance, preconditions, run records, seeds, audit. Shared infrastructure: it authorises
    # and records stages, and interprets no chain bytes at all.
    "phase0": SHARED,

    # The arbiter. Shared, and deliberately so — it must not be able to call the code it judges.
    # It consumes typed results as data and confirms them against the freeze manifest.
    "gate_validation": SHARED,

    # Ticket 19's transport. Shared, and it is the *only* thing the orchestration guide permits to
    # be: "raw transport only — RPC/receipt/log/trace bytes as the node returned them". It moves a
    # JSON-RPC request, hands back the ``result`` member verbatim, records it so the call replays,
    # and reports each endpoint's refusal in that endpoint's own words. It gives no byte a meaning.
    #
    # That is what makes sharing it safe rather than convenient: two lanes reading the same bytes
    # and disagreeing about what those bytes *say* is precisely the disagreement the validation
    # gate exists to surface, and raw bytes cannot carry the shared-decoder bug — there is no
    # interpretation in them to share.
    "transport": SHARED,

    # Builder lane — everything that interprets chain bytes or computes the metric.
    #
    # ``pipeline`` is the composition root: it is the one builder package permitted to import
    # other builder packages, because composing them is its entire job. The leaf modules stay
    # leaves — none of them may import a sibling — so the dependency graph has exactly one node
    # that knows the order things happen in.
    "pipeline": BUILDER,
    "reporting": BUILDER,
    "attribution": BUILDER,
    "netting": BUILDER,
    "fifo": BUILDER,
    "marking": BUILDER,
    "scoring": BUILDER,
    "depth": BUILDER,
    "matching_null": BUILDER,

    # Ticket 19: the builder lane's decoding. Where a receipt's bytes acquire meaning — which log
    # is a transfer, which leg is native ETH, what scale a token's amounts are in.
    #
    # This is the declaration the ``transport`` entry above exists to be contrasted with, and the
    # line between them is the whole of the lane rule. ``transport`` may be shared because it
    # interprets nothing; ``ingest`` may not be shared for the same reason inverted — the validator
    # lane (tickets 13 and 36) must derive its expected answers from the same bytes without
    # importing a line of it. A shared ``Transfer`` filter, a shared ETH/WETH collapse or a shared
    # ``decimals()`` reader would be a shared bug, and a shared bug is invisible to the comparison:
    # both sides compute the same wrong answer and agree.
    "ingest": BUILDER,

    # Tickets 25-28: the candidate universe, Step 0, the T0 freeze and the selected basket. A
    # leaf, and the one whose leaf-ness is a design constraint rather than a consequence: §6.5
    # ranks on ``buy_quality_30d``, which ``scoring`` computes, so ``universe`` receives the
    # scores as **data** — ``universe.ranking.PreT0Score``, whose coverage of the frozen
    # membership must be exactly equal — and never by importing the package that produced them.
    # The composition root supplies them, which is the shape every other leaf here already has.
    "universe": BUILDER,

    # Validator lane — the raw-chain ground truth reader (ticket 13) and the independent
    # expected-output derivation (ticket 36).
    "groundtruth": VALIDATOR,
}

#: The composition root — the one builder package permitted to import other builder packages,
#: because composing them is its entire job.
COMPOSITION_ROOT = "pipeline"

#: Every other builder package. A leaf importing a sibling is a violation.
#:
#: This rule was documented in the ``LANES`` comment above and enforced nowhere, which made it a
#: convention — and a convention is exactly what ticket 25's brief rules out for the one place it
#: does real work. ``universe`` must receive ``buy_quality_30d`` as data rather than by importing
#: ``scoring``; without this check that sentence has no structural answer at all, and the next
#: agent to need a score writes the import.
#:
#: Verified before it was added: no leaf builder imported a sibling, so the check was green on
#: arrival and cost nothing to adopt.
LEAF_BUILDERS = tuple(
    sorted(name for name, lane in LANES.items()
           if lane == BUILDER and name != COMPOSITION_ROOT)
)

#: Edges that must not exist. Both directions are forbidden: the builder reading the validator's
#: expected outputs would be as corrupting as the reverse.
FORBIDDEN_EDGES = (
    (VALIDATOR, BUILDER),
    (BUILDER, VALIDATOR),
    # The arbiter may not call what it judges. gate_validation receives typed results as data and
    # checks them against the manifest; if it could import the builder's scoring code it could
    # inherit the very bug the validation gate exists to catch.
    (SHARED, BUILDER),
    (SHARED, VALIDATOR),
)

#: From the orchestration guide. Recorded here so the boundary is legible at the point it is
#: enforced, not only in prose.
PERMITTED_SHARED_SURFACE = "raw transport only — RPC/receipt/log/trace bytes as returned by the node"
FORBIDDEN_SHARED_SURFACE = (
    "anything that interprets those bytes: swap decoding, transfer filtering, ETH/WETH "
    "normalisation, endpoint detection, lot matching, marking, dead-pool tests, token-age "
    "derivation"
)


def _packages():
    if not os.path.isdir(SRC):
        return []
    return sorted(
        name for name in os.listdir(SRC)
        if os.path.isdir(os.path.join(SRC, name)) and not name.startswith((".", "_"))
        and not name.endswith(".egg-info")
    )


def _module_files(package):
    root = os.path.join(SRC, package)
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _imported_top_level(path):
    """Top-level package names imported by one module, from the AST rather than by regex."""
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)

    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import: within the same package, never cross-lane.
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def test_every_package_declares_a_lane():
    """An unclassified package is a failure, not a default."""
    undeclared = [p for p in _packages() if p not in LANES]
    assert not undeclared, (
        "these packages are not declared in LANES: {}. Classify each as builder, validator, or "
        "shared before adding code to it — an unclassified package silently escapes the "
        "independence check, which is the one control a reviewer can verify from the "
        "repository alone.".format(", ".join(undeclared))
    )


@pytest.mark.parametrize("package", _packages() or ["<none>"])
def test_no_forbidden_cross_lane_import(package):
    if package == "<none>":
        pytest.skip("no packages under src/ yet")

    lane = LANES.get(package)
    if lane is None:
        pytest.skip("covered by test_every_package_declares_a_lane")

    violations = []
    for path in _module_files(package):
        for imported in _imported_top_level(path):
            other = LANES.get(imported)
            if other is None or imported == package:
                continue
            if (lane, other) in FORBIDDEN_EDGES:
                violations.append(
                    "{} ({} lane) imports {} ({} lane)".format(
                        os.path.relpath(path, SRC), lane, imported, other
                    )
                )

    assert not violations, (
        "cross-lane import(s) found:\n  {}\n\n"
        "Permitted shared surface: {}\n"
        "Forbidden shared surface: {}\n\n"
        "If both lanes genuinely need this, it belongs in the shared package — but only if it "
        "interprets no chain bytes. A shared interpretation is a shared bug, and a shared bug "
        "is invisible to the comparison the validation gate depends on.".format(
            "\n  ".join(violations), PERMITTED_SHARED_SURFACE, FORBIDDEN_SHARED_SURFACE
        )
    )


def test_both_lanes_may_import_shared():
    """The rule forbids cross-lane edges, not all coupling.

    Both lanes need the frozen seam and the governance skeleton. Neither interprets chain bytes,
    so sharing them creates no shared interpretation and therefore no shared bug.
    """
    assert LANES["contracts"] == SHARED
    assert LANES["phase0"] == SHARED
    for lane in (BUILDER, VALIDATOR):
        assert (lane, SHARED) not in FORBIDDEN_EDGES


def test_shared_may_not_import_either_lane():
    """The asymmetry is the point, and it is what makes the arbiter an arbiter.

    ``gate_validation`` decides GO / CONDITIONAL_REVIEW / STOP. If it could import the builder's
    scoring code to "check" a result, it would inherit the very bug the validation gate exists to
    catch — and would then certify its own error. It receives typed results as data instead.
    """
    assert LANES["gate_validation"] == SHARED
    for lane in (BUILDER, VALIDATOR):
        assert (SHARED, lane) in FORBIDDEN_EDGES


def test_the_check_would_actually_catch_a_violation(tmp_path):
    """Guard the guard.

    A structural check that cannot fail is theatre. This builds a module that violates the rule
    and asserts the detection logic flags it.
    """
    offender = tmp_path / "reader.py"
    offender.write_text(
        "from netting.balance import net_transaction\n"
        "import phase0.audit\n"
    )
    imported = _imported_top_level(str(offender))

    assert "netting" in imported
    assert "phase0" in imported

    lane = LANES["groundtruth"]
    flagged = [i for i in imported if (lane, LANES.get(i)) in FORBIDDEN_EDGES]

    assert flagged == ["netting"], "the builder-lane import must be flagged"
    assert "phase0" not in flagged, "the shared import must not be flagged"


@pytest.mark.parametrize("package", LEAF_BUILDERS)
def test_a_leaf_builder_does_not_import_a_sibling(package):
    """Only ``pipeline`` composes. Every other builder package imports the seam and nothing else.

    The dependency graph then has exactly one node that knows the order things happen in, and a
    leaf's inputs are all values somebody handed it — which is what makes each leaf testable on its
    own, and what makes ``universe`` take §6.5's ranking metric as a typed input rather than
    reaching into ``scoring`` for it.
    """
    if not os.path.isdir(os.path.join(SRC, package)):
        pytest.skip("{} is not in the tree yet".format(package))

    violations = []
    for path in _module_files(package):
        for imported in _imported_top_level(path):
            if imported == package or LANES.get(imported) != BUILDER:
                continue
            violations.append("{} imports {}".format(os.path.relpath(path, SRC), imported))

    assert not violations, (
        "{} is a leaf builder and imports (a) sibling builder package(s):\n  {}\n\n"
        "Only {} composes. A leaf that reaches for a sibling makes the dependency graph a mesh "
        "with several nodes that know the order things happen in — and in this tree it also "
        "defeats the one place the rule is load-bearing: §6.5's ranking metric must reach "
        "``universe`` as data the composition root supplies, so that the ranked population is "
        "covered exactly rather than by whatever the scorer happened to "
        "return.".format(package, "\n  ".join(violations), COMPOSITION_ROOT)
    )


def test_the_leaf_rule_would_catch_a_universe_reaching_for_scoring(tmp_path):
    """Guard the guard, on the exact line this rule exists to stop somebody writing."""
    offender = tmp_path / "ranking.py"
    offender.write_text(
        "from scoring.quality import buy_quality\n"
        "from contracts import Decimal\n"
        "from .protocol import WindowKey\n"
    )
    imported = _imported_top_level(str(offender))

    assert "scoring" in imported
    assert "contracts" in imported
    assert "protocol" not in imported, "the relative import is intra-package, not a lane edge"

    flagged = [i for i in imported if i != "universe" and LANES.get(i) == BUILDER]
    assert flagged == ["scoring"], (
        "the sibling import must be flagged and the seam import must not")
    assert "universe" in LEAF_BUILDERS and COMPOSITION_ROOT not in LEAF_BUILDERS


def test_relative_imports_are_not_treated_as_cross_lane(tmp_path):
    """``from .audit import AuditLog`` is intra-package and must not trip the check."""
    module = tmp_path / "m.py"
    module.write_text("from .audit import AuditLog\nfrom ..other import thing\n")
    assert _imported_top_level(str(module)) == set()
