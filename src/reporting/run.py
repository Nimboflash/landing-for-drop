"""The whole of §10, assembled once — and deliberately without the gate decision.

§10 opens with *"Beyond the gate decision, these must be reported"*, so the run report is what sits
beside the decision, not what contains it. :func:`report_run` takes no ``GateDecision``, no
``GateOutcome`` and no threshold, and there is no parameter through which one could arrive. Two
things follow from that, and both are the point:

* **churn cannot become conditional on the result.** §10 requires churn reported in its own right —
  *"If 60% of top wallets go quiet within six months, the system has a churn problem no engine
  fixes"* — and a report that had the outcome in scope is one refactor away from reporting churn
  differently, or only, when the gate passed;
* **the report cannot be read as the decision.** ``gate_validation.emit_decision`` produces the
  only :class:`contracts.GateDecision` there is, after confirming the freeze manifest. A second
  object carrying an outcome would be a second answer to the question the arbiter exists to answer.

What the report *does* carry, permanently and in every copy, is the two sentences that keep it from
being misread: :data:`GATE_RELEVANCE_STATEMENT`, which says only ``buy_quality`` decides, and
:data:`NOT_TESTED`, which says what Phase 0 did not test. Ticket 34 and PRD 129 require both, and
they are stored fields rather than a preamble somebody prints because a field survives
serialization and a preamble does not.

Why the basket and the churn population are different sizes, and why that is not an error
-----------------------------------------------------------------------------------------

A wallet with no valid buy in the forward period has no buy quality — ``scoring`` refuses to invent
one — so it appears in the churn block as `Inactive` and does not appear in the basket at all.
The basket is therefore **conditioned on survival**, and every figure in it describes the wallets
that kept trading. ``basket.n_wallets`` and ``churn.n_wallets`` both appear in the report precisely
so the gap between them is visible: a basket of 40 wallets beside a churn population of 100 is a
headline number computed on the survivors of a 60% churn rate, and reading the first without the
second is the survivorship error §10's churn block exists to make impossible.

The two populations are deliberately **not** cross-checked for equality here. They legitimately
differ, and a check that forced them to match would force a caller to either drop the churn record
of a dead wallet or invent a score for it — the two things §10 and ticket 27 respectively forbid.

``report-v1`` no longer describes the diagnostics block — recorded, not fixed
---------------------------------------------------------------------------

:data:`contracts.REPORTING_SCHEMA_VERSION` is ``"report-v1"`` and is stamped into every report by
:attr:`RunReport.reporting_schema_version`. The published shape of a diagnostic's figure changed
underneath it when the payload became a :class:`~reporting.diagnostics.DiagnosticValue`::

    before   "value": "980000.25"                          "value": "0.184"
    after    "value": {"amount": "980000.25", "kind": "usd"}
                                                           "value": {"amount": "0.184",
                                                                     "kind": "ratio"}

No measured figure moved — the amounts are byte-identical — but the structure did, and with it the
canonical hash that ``gate_validation.manifest`` records and §9.6 pins. Two artifacts both
declaring ``report-v1`` are therefore not interchangeable, and a reader pinned to that version
cannot tell from the stamp that ``value`` went from a scalar to an object.

**It has since happened a second time.** ``RunReport`` gained the required ``integrity`` block —
§10's four standing data-integrity figures, which four packages computed and nothing published — so
a fifth key now appears in every payload and the canonical hash moved again. No measured figure
changed; the shape did, under the same stamp, for the second time.

This is stated here rather than fixed because ``REPORTING_SCHEMA_VERSION`` lives in
``contracts/numeric.py``, inside the frozen seam, and the seam is not this lane's to edit. **The
next time the seam is unfrozen, this constant goes to ``report-v2``**, with both changes above as
its reason. Nothing has been published from this instrument yet, so today's blast radius is zero; the
note exists so that it is a decision rather than a discovery.
``tests/integration/test_reporting_claims.py`` pins the shape against the version string, so a
further shape change under the same stamp goes red.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Tuple

from contracts import (
    NUMERIC_POLICY_VERSION,
    REPORTING_SCHEMA_VERSION,
    ContractError,
    artifact_envelope,
    calc,
    require_finite,
)

from .capital import CapitalLadderReport
from .churn import ChurnReport
from .diagnostics import DiagnosticPack
from .wallet import BasketReport
from .window import EXPECTED_WINDOWS, WindowReport

#: The artifact kind. Terminal output: ``gate_validation`` reads builder *results* as data and has
#: no reason to read this, and cannot import the module that writes it in any case.
ARTIFACT_KIND = "phase0_required_outputs"
PRODUCED_BY = "reporting"

#: §10, verbatim in substance. Carried in every run report so the sentence cannot be separated from
#: the numbers it governs.
GATE_RELEVANCE_STATEMENT = (
    "Only buy_quality decides the gate. Every diagnostic in this report is labelled "
    "DIAGNOSTIC_ONLY and changes nothing: a diagnostic passing while buy_quality fails is "
    "informative, and reporting a diagnostic and then using it to overturn a gate result is the "
    "failure mode the pre-registration exists to prevent."
)

#: PRD 129 / §11.3. What a pass does not mean.
NOT_TESTED = (
    "Berk-Green capital-degradation effects were not tested.",
    "Generalisation beyond Ethereum Mainnet was not tested; Phase 0 says nothing about Base, "
    "Solana, or memecoin markets.",
    "Whether the full product would be profitable was not tested.",
    "Long-tail assets were excluded from Ethereum Phase 0 outright, so no result here describes "
    "them.",
)


class IncompleteRunReport(ContractError):
    """A required §10 block is missing, and an absent block is not an empty one."""


#: What each integrity figure means when it is ``None``. Carried as data so the report can say why a
#: number is absent rather than leaving the reader to assume it is zero.
NOT_MEASURED = {
    "decoder_coverage_gap": (
        "no decoder coverage gap has been measured. Ticket 12 measures it against a real data "
        "pull; roughly 8.2% of tracked Ethereum DEX volume has no decoder at all, meaning those "
        "trades are invisible rather than mislabelled. Until that pull happens this is unknown, "
        "which is not the same as small"
    ),
    "attribution_fallback_rate": (
        "no attribution fallback rate accompanied this run. The rate is the share of trades where "
        "portfolio_owner fell back to the transaction sender, and a run that does not report it "
        "cannot be read for how often the owner was guessed"
    ),
    "unexplained_reconciliation_difference": (
        "layer-3 cross-source reconciliation has not run. Ticket 35 needs two independent sources "
        "and there is one"
    ),
    "reconciliation_queue_volume_usd": (
        "no reconciliation queue volume accompanied this run. Residuals above the addendum §8 "
        "tolerance are excluded from the primary metric, so the volume they represent is the "
        "measure of what the headline number leaves out"
    ),
}


@dataclass(frozen=True)
class DataIntegrity:
    """The four standing figures that must accompany every result, §10 and addendum §8.

    **This block exists because four packages computed these and nothing published them.** The
    attribution coverage gap and fallback rate, the reconciliation queue volume and the unexplained
    reconciliation difference were each derived somewhere in ``src/`` and then had no field in any
    report type — so a reader of a hashed §10 artifact saw none of them. Downstream, a figure
    computed and not published is indistinguishable from a figure nobody measured.

    **``None`` means not measured, and never zero.** That distinction is the whole design. A run
    that has not measured its decoder coverage gap reports ``None`` and :data:`NOT_MEASURED` says
    why; a run reporting ``0`` claims somebody looked and found nothing missing. The first is
    honest about an unfinished project and the second is a false claim about a finished one, and
    they are one keystroke apart.

    The block itself is **required** on :class:`RunReport`. A run may honestly not know these
    numbers; it may not omit the question.
    """

    decoder_coverage_gap: Optional[Decimal] = None
    attribution_fallback_rate: Optional[Decimal] = None
    unexplained_reconciliation_difference: Optional[Decimal] = None
    reconciliation_queue_volume_usd: Optional[Decimal] = None

    def __post_init__(self):
        for name in NOT_MEASURED:
            value = getattr(self, name)
            if value is None:
                continue
            coerced = require_finite(calc(value), name)
            if coerced < 0:
                raise IncompleteRunReport(
                    "{} is {}, and none of these figures can be negative. A negative rate or "
                    "volume is a defect in what produced it, not a small one.".format(
                        name, coerced)
                )
            object.__setattr__(self, name, coerced)

    @property
    def unmeasured(self):
        """The figures this run does not have, in a fixed order, each with its reason.

        Reported rather than counted: "three of four measured" tells a reader how much is missing
        and not *which*, and which is the part that decides whether the run's headline number can
        be read at all.
        """
        return tuple(
            (name, NOT_MEASURED[name])
            for name in sorted(NOT_MEASURED)
            if getattr(self, name) is None
        )

    @property
    def fully_measured(self):
        return not self.unmeasured


@dataclass(frozen=True)
class RunReport:
    """Everything §10 requires, for one run, on one chain.

    ``missing_windows`` is recorded rather than refused, for the same reason a window report records
    a missing column: the gate decides what an absent window means, and a report's job is to make
    the absence visible instead of letting three windows read as four.
    """

    run_id: str
    chain: str
    basket: BasketReport
    windows: Tuple[WindowReport, ...]
    capital_ladder: CapitalLadderReport
    churn: ChurnReport
    diagnostics: DiagnosticPack
    #: Required. See :class:`DataIntegrity`: a run may honestly not know these figures, and may not
    #: omit the question. Defaulted so that every existing caller keeps working and reports four
    #: ``None``s with their reasons, which is the true statement about a run that measured none of
    #: them — rather than silently reporting nothing at all, which is what it did before.
    integrity: DataIntegrity = field(default_factory=DataIntegrity)
    missing_windows: Tuple[int, ...] = ()
    reporting_schema_version: str = REPORTING_SCHEMA_VERSION
    numeric_policy_version: str = NUMERIC_POLICY_VERSION
    gate_relevance: str = GATE_RELEVANCE_STATEMENT
    not_tested: Tuple[str, ...] = field(default_factory=lambda: NOT_TESTED)

    def __post_init__(self):
        object.__setattr__(self, "windows", tuple(self.windows))
        object.__setattr__(self, "missing_windows", tuple(self.missing_windows))
        object.__setattr__(self, "not_tested", tuple(self.not_tested))
        if not self.run_id:
            raise IncompleteRunReport("a run report must name its run")
        if not self.chain:
            raise IncompleteRunReport(
                "a run report must name its chain. §11.1 selected Ethereum Mainnet and excluded "
                "three others for stated reasons; a figure without its chain is not "
                "interpretable."
            )
        if not isinstance(self.integrity, DataIntegrity):
            raise IncompleteRunReport(
                "integrity must be a DataIntegrity, got {}. The block is what distinguishes a "
                "figure nobody measured from a figure measured at zero, and a bare mapping "
                "distinguishes nothing.".format(type(self.integrity).__name__)
            )
        if not self.not_tested:
            raise IncompleteRunReport(
                "the report must state what Phase 0 did not test, or a pass reads as more than "
                "it is"
            )
        if not isinstance(self.diagnostics, DiagnosticPack):
            # Also checked in ``report_run``, which is not the same thing: ``RunReport`` is exported
            # and constructible directly, and ``run_artifact`` calls ``verify()`` on this field. A
            # report holding a bare tuple here would meet that call with an ``AttributeError``
            # instead of a refusal naming the block.
            raise TypeError(
                "diagnostics must be a DiagnosticPack, got {}. The pack is what refuses a gate "
                "input carried among the diagnostics, and what re-runs their invariants at "
                "publication; a bare tuple refuses nothing.".format(type(self.diagnostics).__name__)
            )
        if self.gate_relevance != GATE_RELEVANCE_STATEMENT:
            raise IncompleteRunReport(
                "the gate-relevance statement was altered. It is a stored field so that it "
                "survives serialization and cannot be separated from the numbers it governs; "
                "rewriting it is how a diagnostic acquires standing."
            )


def report_run(run_id, chain, basket, windows, capital_ladder, churn, diagnostics,
               integrity=None):
    """Assemble §10's required outputs.

    :param windows: :class:`reporting.window.WindowReport` per evaluated window, any order.
    :param diagnostics: a :class:`reporting.diagnostics.DiagnosticPack`. Required, not optional —
        an omitted pack and an empty one are different claims, and ``diagnostic_pack(())`` says the
        second one out loud.
    :param integrity: a :class:`DataIntegrity`. Omitted, the report carries one whose four figures
        are all ``None`` — which is the true statement about a run that measured none of them, and
        is what every caller in this tree produces today. What it is not is silence: the block is
        always present, and :attr:`DataIntegrity.unmeasured` names each absent figure and why.

    Note what is not a parameter: no gate decision, no outcome, no threshold. §10's outputs sit
    beside the decision, and churn in particular is a finding in its own right.
    """
    if not isinstance(basket, BasketReport):
        raise TypeError("basket must be a BasketReport, got {}".format(type(basket).__name__))
    if not isinstance(capital_ladder, CapitalLadderReport):
        raise TypeError(
            "capital_ladder must be a CapitalLadderReport, got {}. §10 requires all five levels "
            "and the ladder type is what refuses four.".format(type(capital_ladder).__name__)
        )
    if not isinstance(churn, ChurnReport):
        raise TypeError("churn must be a ChurnReport, got {}".format(type(churn).__name__))
    if not isinstance(diagnostics, DiagnosticPack):
        raise TypeError(
            "diagnostics must be a DiagnosticPack, got {}. The pack is what refuses a gate input "
            "carried among the diagnostics, and a bare tuple refuses nothing.".format(
                type(diagnostics).__name__
            )
        )
    # Re-checked here, not only where the pack was built: a pack constructed correctly can be
    # rewritten afterwards — ``__post_init__`` runs once and ``object.__setattr__`` rewrites a field
    # of any Python object — so this closes the window between the pack's construction and this
    # assembly.
    #
    # This is **assembly**, not publication, and the comment that used to sit here said otherwise.
    # Measured: rewriting an item after ``report_run`` returned, then calling ``run_artifact``, put
    # ``gate_relevance="GATE"`` and an unregistered name into a hashed, envelope-verified artifact.
    # The publication-time check is the one in :func:`run_artifact`; this one buys a refusal that
    # names the assembly step, where the caller can still see which pack it handed over.
    diagnostics.verify()

    ordered = sorted(tuple(windows), key=lambda report: report.window)
    seen = set()
    for report in ordered:
        if not isinstance(report, WindowReport):
            raise TypeError(
                "windows must hold WindowReport rows, got {}".format(type(report).__name__)
            )
        if report.window in seen:
            raise IncompleteRunReport(
                "window {} is reported twice; two answers to one question means something must "
                "choose between them".format(report.window)
            )
        seen.add(report.window)
    if not ordered:
        raise IncompleteRunReport(
            "no windows were reported. §6.3 fixes four walk-forward windows and §7.4 requires "
            "three to pass; a report over none is not a partial result."
        )

    return RunReport(
        run_id=run_id,
        chain=chain,
        basket=basket,
        windows=tuple(ordered),
        capital_ladder=capital_ladder,
        churn=churn,
        diagnostics=diagnostics,
        integrity=DataIntegrity() if integrity is None else integrity,
        missing_windows=tuple(w for w in range(1, EXPECTED_WINDOWS + 1) if w not in seen),
    )


def run_artifact(report):
    """Wrap a run report for on-disk exchange, with a payload hash.

    Terminal output. This is not a gate input and there is no ``gate_validation`` reader for it:
    the arbiter consumes builder *results* — window scores, permutation results, manifests — and
    §10's outputs sit beside its decision rather than feeding it.

    **This is the publication step, so the diagnostics pack is verified here.** It is also verified
    in :func:`report_run`, and that was previously the only place — which left the window that
    matters open, since the rewrite a tamper performs lands *after* a report has been assembled.
    Three routes to a hashed artifact were measured against the old code and only one was closed::

        report_run(..., diagnostics=tampered_pack)      -> refused        (assembly)
        RunReport(..., diagnostics=tampered_pack)       -> published      (public, exported)
        report = report_run(...); tamper(report); run_artifact(report)
                                                        -> published      GATE + sharpe_ratio
                                                           in the payload, envelope verifying clean

    The check below closes the second and third, because both must pass through here to become an
    artifact. Nothing runs between it and the envelope.

    **What it does not re-verify, stated because the sentence above is the kind that grows.** The
    other four §10 blocks — basket, windows, capital ladder, churn — are serialised as they stand.
    They have no ``verify()`` and this function does not reconstruct them, so a figure rewritten
    into a :class:`~reporting.wallet.BasketReport` after it was built reaches the artifact and its
    payload hash. The diagnostics pack is singled out because it is the block carrying the
    ``DIAGNOSTIC_ONLY`` label that §10's whole separation rests on; the rest is unclosed, not
    closed-and-unmentioned.
    """
    if not isinstance(report, RunReport):
        raise TypeError("run_artifact wraps a RunReport, got {}".format(type(report).__name__))
    report.diagnostics.verify()
    return artifact_envelope(ARTIFACT_KIND, PRODUCED_BY, report)
