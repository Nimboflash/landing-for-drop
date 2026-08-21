"""Structural enforcement of the single quantization boundary.

``contracts/numeric.py`` states the policy in four lines::

    Raw token quantities    int, never Decimal, never rounded
    USD accounting          Decimal at full internal precision
    Ratios and returns      NEVER quantized before final aggregation
    Reporting               quantized exactly once, at the output boundary

The third and fourth lines are the ones a module can violate while looking entirely reasonable. A
share rounded to eight decimal places *before* it enters a weighted mean carries its rounding error
into the aggregate, the error is a function of each wallet's magnitude, and the result disagrees
with the same aggregate computed by the Independent Validator — which quantized somewhere else. The
reconciliation then fails on rounding rather than on substance, at 0.5% tolerances where a genuine
error hides comfortably.

So, like ``tests/test_lane_independence`` and ``tests/test_frozen_context``, this is a static
assertion over committed code rather than a convention.

The rule
--------

A ``quantize_usd`` / ``quantize_ratio`` / ``quantize_pp`` call in ``src/`` must be either

* inside ``src/reporting/``, which **is** the output boundary; or
* lexically inside a string-rendering expression — an f-string, ``format(...)``, or
  ``"...".format(...)``.

The second exemption is real rather than a concession. ``marking/mark.py`` renders a shortfall into
an evidence line and ``depth/amm.py`` renders a slippage into a refusal message; in both, the
quantized value is consumed by a string and never becomes a number anyone computes with. That is
the same thing the boundary does, at a smaller scale, and forbidding it would push those modules
toward hand-rolled formatting that agrees with the reporting scales only by luck.

What is forbidden is a quantized value that is **bound to a name, returned, stored on a dataclass,
or passed to anything but a formatter**, anywhere outside ``src/reporting/``. That is the shape
that reaches an aggregation.

What this cannot see
--------------------

``Decimal.quantize`` called directly, rather than through the seam's helpers. It is not flagged
because ``contracts.serialization.canonicalise`` legitimately calls it to normalise an exponent,
and distinguishing that from a rounding-to-report needs the kind of type inference this file
deliberately does not have. The seam's helpers are the documented route, and a module reaching past
them to ``value.quantize(...)`` is visible in review for a different reason: it has to spell out a
scale, and the scales live in ``contracts.numeric``.

Test files are not scanned. A test may quantize freely — it is asserting on output, which is
exactly where quantization belongs.
"""

import ast
import collections
import os

import pytest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

#: The package that *is* the boundary.
BOUNDARY_PACKAGE = "reporting"

#: The seam's quantizers. ``quantize`` itself is deliberately absent — see the module docstring.
QUANTIZERS = frozenset({"quantize_usd", "quantize_ratio", "quantize_pp"})

Violation = collections.namedtuple("Violation", "path line source")


def _python_files(root):
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _called_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_rendering_expression(node):
    """An f-string, ``format(x, spec)``, or ``"...".format(x)``.

    ``.format`` on a bare name is *not* credited: ``row.format(quantize_usd(v))`` could be anything.
    Only a literal string receiver counts, which is every legitimate use in the tree.
    """
    if isinstance(node, ast.JoinedStr):
        return True
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id == "format":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "format":
        receiver = func.value
        if isinstance(receiver, ast.Constant) and isinstance(receiver.value, str):
            return True
        if isinstance(receiver, ast.Str):  # pragma: no cover - Python < 3.8 shape
            return True
    return False


def _quantizer_calls(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _called_name(node.func) in QUANTIZERS:
            yield node


def _rendered_quantizer_calls(tree):
    """Every quantizer call sitting anywhere inside a rendering expression."""
    rendered = set()
    for node in ast.walk(tree):
        if _is_rendering_expression(node):
            for inner in _quantizer_calls(node):
                rendered.add(id(inner))
    return rendered


def scan_tree(root):
    violations = []
    if not os.path.isdir(root):
        return violations
    for path in _python_files(root):
        relative = os.path.relpath(path, root)
        if relative.split(os.sep)[0] == BOUNDARY_PACKAGE:
            continue
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source, filename=path)
        lines = source.splitlines()
        rendered = _rendered_quantizer_calls(tree)
        for call in _quantizer_calls(tree):
            if id(call) in rendered:
                continue
            violations.append(
                Violation(
                    path=relative,
                    line=call.lineno,
                    source=lines[call.lineno - 1].strip() if call.lineno <= len(lines) else "",
                )
            )
    return violations


def _describe(violations):
    return "\n  ".join(
        "{}:{}  {}".format(v.path, v.line, v.source) for v in sorted(violations)
    )


def test_quantization_happens_only_at_the_reporting_boundary():
    violations = scan_tree(SRC)
    assert not violations, (
        "quantization outside src/{}/:\n  {}\n\n"
        "A value quantized here is a value that can enter an aggregation already rounded, and "
        "'ratios are NEVER quantized before final aggregation' (contracts/numeric.py). Keep the "
        "figure at full precision and let reporting render it, or — if the quantized value is only "
        "ever rendered into a string — put the call inside the f-string or .format() that consumes "
        "it, which is what the existing evidence-line and refusal-message uses do.".format(
            BOUNDARY_PACKAGE, _describe(violations)
        )
    )


def test_the_reporting_package_is_the_one_that_does_quantize():
    """Guard against the rule being satisfied by nobody quantizing at all.

    §10 requires published figures at a declared scale. If ``reporting`` stopped calling the
    quantizers, this file would pass while the output boundary had quietly disappeared.
    """
    boundary = os.path.join(SRC, BOUNDARY_PACKAGE)
    assert os.path.isdir(boundary), "src/{}/ does not exist".format(BOUNDARY_PACKAGE)

    found = set()
    for path in _python_files(boundary):
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        for call in _quantizer_calls(tree):
            found.add(_called_name(call.func))

    assert found == QUANTIZERS, (
        "src/{}/ calls {} but the boundary must render all three classes §10 reports in: "
        "{}".format(BOUNDARY_PACKAGE, sorted(found) or "nothing", sorted(QUANTIZERS))
    )


# -- guard the guard ------------------------------------------------------------


def test_the_check_catches_a_quantized_value_bound_to_a_name(tmp_path):
    """The shape that actually reaches an aggregation."""
    package = tmp_path / "netting"
    package.mkdir()
    (package / "balance.py").write_text(
        "from contracts import quantize_ratio\n"
        "\n"
        "def tolerance(value):\n"
        "    rounded = quantize_ratio(value)\n"
        "    return rounded\n"
    )
    violations = scan_tree(str(tmp_path))
    assert [v.line for v in violations] == [4]


def test_the_check_catches_a_quantized_value_returned_directly(tmp_path):
    package = tmp_path / "scoring"
    package.mkdir()
    (package / "quality.py").write_text(
        "from contracts import quantize_usd\n"
        "\n"
        "def cost(value):\n"
        "    return quantize_usd(value)\n"
    )
    assert [v.line for v in scan_tree(str(tmp_path))] == [4]


def test_a_quantized_value_rendered_into_a_string_is_not_flagged(tmp_path):
    """The two legitimate uses in the tree, in all three rendering shapes."""
    package = tmp_path / "marking"
    package.mkdir()
    (package / "mark.py").write_text(
        "from contracts import quantize_pp, quantize_ratio, quantize_usd\n"
        "\n"
        "def evidence(a, b, c):\n"
        "    one = 'shortfall={}'.format(quantize_ratio(a))\n"
        "    two = format(quantize_pp(b), 'f')\n"
        "    three = f'cost={quantize_usd(c)}'\n"
        "    return one, two, three\n"
    )
    assert scan_tree(str(tmp_path)) == []


def test_a_format_call_on_a_non_literal_receiver_is_not_credited(tmp_path):
    """``template.format(quantize_usd(v))`` could be anything; only a literal string counts."""
    package = tmp_path / "depth"
    package.mkdir()
    (package / "amm.py").write_text(
        "from contracts import quantize_usd\n"
        "\n"
        "def render(template, value):\n"
        "    return template.format(quantize_usd(value))\n"
    )
    assert [v.line for v in scan_tree(str(tmp_path))] == [4]


def test_the_reporting_package_is_exempt(tmp_path):
    package = tmp_path / BOUNDARY_PACKAGE
    package.mkdir()
    (package / "boundary.py").write_text(
        "from contracts import quantize_usd\n"
        "\n"
        "def output(value):\n"
        "    return quantize_usd(value)\n"
    )
    assert scan_tree(str(tmp_path)) == []


@pytest.mark.parametrize("quantizer", sorted(QUANTIZERS))
def test_every_quantizer_the_seam_exports_is_watched(quantizer):
    """If ``contracts`` grows a fourth quantizer, this list must grow with it."""
    import contracts

    assert hasattr(contracts, quantizer)


def test_no_seam_quantizer_escapes_the_watch_list():
    import contracts

    exported = {
        name for name in dir(contracts)
        if name.startswith("quantize_") and callable(getattr(contracts, name))
    }
    assert exported == QUANTIZERS, (
        "contracts exports {} but this check watches {}. A quantizer nobody watches is a second "
        "output boundary.".format(sorted(exported), sorted(QUANTIZERS))
    )
