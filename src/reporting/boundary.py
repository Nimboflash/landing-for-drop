"""The output boundary — the one place in the pipeline a number is quantized.

``contracts.numeric`` states the policy: *ratios and returns are NEVER quantized before final
aggregation; reporting quantizes exactly once, at the output boundary.* This module is that
boundary. Every ``quantize_*`` call that decides a published figure goes through here, and every
other package keeps its numbers at the frozen 38 digits until it hands them over.

The rule is not tidiness. A share rounded to eight decimal places before it enters a weighted mean
carries its rounding error into the aggregate, and the error does not cancel: it is a function of
each wallet's magnitude, so a basket of small wallets is biased differently from a basket of large
ones. The aggregate then disagrees with the same aggregate computed by the Independent Validator,
which quantized somewhere else, and the reconciliation fails on rounding rather than on substance.

``tests/test_quantization_boundary.py`` enforces this structurally: outside ``src/reporting``, a
``quantize_*`` result may only be consumed by a string-rendering expression, never bound to a name
or returned as a value.

Two things this module does that a bare call to :func:`contracts.quantize_usd` does not:

**It holds the frozen context while quantizing.** ``Decimal.quantize`` raises ``InvalidOperation``
when the result would need more digits than the *ambient* context allows — 28 by default, 38 under
the frozen one. Without the ``localcontext`` block below, whether a $1e30 figure could be reported
at all would depend on a global this package does not control, which is the same defect that once
moved the canonical hash.

**It refuses rather than truncating.** A value too large to render at its scale raises
:class:`UnreportableValue` naming the field. The alternative — falling back to exponential notation,
or to a coarser scale — publishes a number under a scale it does not actually have.
"""

from decimal import InvalidOperation, localcontext

from contracts import (
    CALCULATION_CONTEXT,
    REPORTING_SCALES,
    SCALE_PERCENTAGE_POINTS,
    SCALE_RATIO,
    SCALE_USD,
    ContractError,
    calc,
    quantize_pp,
    quantize_ratio,
    quantize_usd,
    require_finite,
)

#: The three output classes §10 reports in. ``smd`` exists in the seam's scale table but belongs to
#: covariate balance, which ``matching_null`` reports on its own artifact, not to §10's outputs.
USD = "usd"
RATIO = "ratio"
PERCENTAGE_POINTS = "percentage_points"

KINDS = (USD, RATIO, PERCENTAGE_POINTS)

_SCALES = {
    USD: SCALE_USD,
    RATIO: SCALE_RATIO,
    PERCENTAGE_POINTS: SCALE_PERCENTAGE_POINTS,
}

# The seam owns the scales; this module owns only the decision about which class a figure belongs
# to. Checked at import rather than asserted, because ``python -O`` strips an assert and a silent
# divergence here would publish a figure at a scale the freeze manifest does not describe.
for _kind, _scale in _SCALES.items():
    if REPORTING_SCALES.get(_kind) != _scale:
        raise ImportError(
            "reporting scale for {!r} is {} but contracts.REPORTING_SCALES says {}; the seam owns "
            "the scales and reporting may not hold a second copy that can drift".format(
                _kind, _scale, REPORTING_SCALES.get(_kind)
            )
        )


class UnreportableValue(ContractError):
    """A value cannot be rendered at its declared scale, and no coarser one will be substituted.

    Distinct from a negative finding. "This wallet's realized share was 3%" is a result; "this
    figure needs 41 significant digits to render at six decimal places" is a modelling or a data
    error, and silently widening the scale would publish it as the former.
    """


def at_output(value, kind, field):
    """Quantize one figure, once, at the boundary.

    :param kind: one of :data:`KINDS`. An unknown kind raises rather than defaulting to ``ratio``
        — the scale is part of what a reported number *means*, and a default would let a USD
        amount be published at eight decimal places without anyone choosing that.
    """
    if kind not in _SCALES:
        raise ValueError(
            "unknown output kind {!r} for {}; §10 reports in {}. A default here would let a "
            "figure be published at a scale nobody chose.".format(kind, field, ", ".join(KINDS))
        )
    amount = require_finite(calc(value), field)
    # Dispatched by branch rather than through a table of callables, so that
    # ``tests/test_quantization_boundary.py`` can see all three quantizers being called here —
    # the check's second half asserts that the boundary is the package that actually quantizes,
    # and a table lookup would satisfy the rule by making the calls invisible instead.
    with localcontext(CALCULATION_CONTEXT):
        try:
            if kind == USD:
                return quantize_usd(amount)
            if kind == RATIO:
                return quantize_ratio(amount)
            return quantize_pp(amount)
        except InvalidOperation:
            raise UnreportableValue(
                "{} is {}, which cannot be rendered at the {} scale {} even at the frozen {} "
                "digits. Reporting refuses rather than falling back to a coarser scale or to "
                "exponential notation, either of which would publish the figure under a scale it "
                "does not have.".format(
                    field, amount, kind, _SCALES[kind], CALCULATION_CONTEXT.prec
                )
            )


def output_usd(value, field="usd amount"):
    return at_output(value, USD, field)


def output_ratio(value, field="ratio"):
    return at_output(value, RATIO, field)


def output_pp(value, field="percentage points"):
    return at_output(value, PERCENTAGE_POINTS, field)


def optional_output(value, kind, field):
    """``None`` survives the boundary as ``None``.

    ``N/A`` is a state §10 asks for by name — Copy Retention below the display threshold, a
    positive-trade rate over zero executable trades — and a zero standing in for it would read as
    a measured result of zero, which is the failure this whole protocol is arranged around.
    """
    if value is None:
        return None
    return at_output(value, kind, field)


def scale_for(kind):
    """The scale a ``kind`` renders at. Exposed so a reviewer can check a figure's exponent."""
    if kind not in _SCALES:
        raise ValueError("unknown output kind {!r}".format(kind))
    return _SCALES[kind]
