"""The package imports, and the two routes it promises not to have.

Until ``tools/mockchain/report.py`` existed, ``import tools.mockchain`` raised ``ImportError`` at
line 50 of ``__init__.py``: the package named three things it could not provide. That is the first
thing to pin, and it is worth its own file — every other test in this directory imports the package,
so a broken import shows up as forty errors with one cause, and one test that says which cause.

The other two assertions are structural rather than behavioural, and both pin a claim
``report.py``'s docstring makes about itself:

* it reaches ``reporting.run_artifact`` only through
  :func:`tools.mockchain.provenance.publish_synthetic_artifact`, so there is exactly one route from
  a synthetic run to a hashed artifact and that route re-reads the bytes it is about to hash;
* it imports no ``phase0`` name at all, so assembling a report cannot touch the state machine.

Both are checked against the module's own AST rather than by calling it. A behavioural test can only
show that the route was not taken *this time*; the import graph is what makes it not takeable.
"""

import ast
import os

import tools.mockchain as mockchain
from tools.mockchain import report as report_module

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = os.path.join(os.path.dirname(os.path.dirname(HERE)), "tools", "mockchain")


def _imported_names(path):
    """``(module, name)`` for every import in one file, ``name`` empty for a plain ``import x``."""
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, ""))
        elif isinstance(node, ast.ImportFrom):
            module = ("." * node.level) + (node.module or "")
            for alias in node.names:
                found.append((module, alias.name))
    return tuple(found)


def test_the_package_imports_and_provides_the_three_names_init_asks_for():
    # The exact three names ``__init__.py`` imports from ``.report``. Spelled out rather than
    # derived from the module, so deleting one from ``report.py`` *and* from ``__init__.py``
    # together — which would leave the package importable and silently smaller — still goes red.
    assert mockchain.SyntheticRun is report_module.SyntheticRun
    assert mockchain.run_synthetic_window is report_module.run_synthetic_window
    assert mockchain.synthetic_report is report_module.synthetic_report


def test_the_package_exports_provenance_and_governance_beside_the_report():
    """A caller who has the report entry point must also have the two halves that constrain it."""
    for name in (
        "publish_synthetic_artifact", "audit_payload_provenance", "SyntheticProvenanceLost",
        "snapshot_id", "synthetic_address", "synthetic_tx_hash", "is_synthetic_identifier",
        "refuse_if_synthetic_would_advance", "execute_synthetic_stage", "SyntheticRunRefused",
        "generate_chain", "SyntheticChain",
    ):
        assert name in mockchain.__all__, name
        assert getattr(mockchain, name) is not None


def test_report_never_imports_run_artifact_directly():
    """One route to a hashed artifact, and it is the one that audits the payload first."""
    imports = _imported_names(os.path.join(PACKAGE, "report.py"))
    direct = [
        (module, name) for module, name in imports
        if name == "run_artifact" or module.endswith("reporting.run")
    ]
    assert direct == [], (
        "report.py imports {} directly. reporting.run_artifact publishes without reading the "
        "payload's provenance; publish_synthetic_artifact is the same call with "
        "audit_payload_provenance run over the bytes about to be hashed. Two routes to an "
        "artifact means the audited one is optional.".format(direct)
    )
    assert ("provenance", "publish_synthetic_artifact") in [
        (module.lstrip("."), name) for module, name in imports
    ]


def test_report_imports_no_phase0_name():
    """Assembling a report cannot advance the experiment, because it cannot reach the machine."""
    offenders = [
        (module, name) for module, name in _imported_names(os.path.join(PACKAGE, "report.py"))
        if module == "phase0" or module.startswith("phase0.")
    ]
    assert offenders == [], (
        "report.py imports {} from phase0. A synthetic run reaches the state machine only through "
        "tools.mockchain.governance.execute_synthetic_stage, which refuses the transition on both "
        "sides of the runner.".format(offenders)
    )


def test_nothing_under_src_imports_the_synthetic_source():
    """The fixture may import the metric. The metric may never import the fixture.

    ``tests/test_lane_independence.py`` classifies packages *within* ``src/``; it says nothing about
    a package outside it. This is the direction that matters for a synthetic source: a builder that
    could import ``tools.mockchain`` is a builder that could be handed generated data by something
    other than a test.
    """
    src = os.path.join(os.path.dirname(os.path.dirname(HERE)), "src")
    offenders = []
    for dirpath, _dirnames, filenames in os.walk(src):
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            for module, name in _imported_names(path):
                if module.split(".")[0] == "tools" or (module == "tools" and name):
                    offenders.append(os.path.relpath(path, src))
    assert offenders == [], "src/ imports tools/: {}".format(sorted(set(offenders)))
