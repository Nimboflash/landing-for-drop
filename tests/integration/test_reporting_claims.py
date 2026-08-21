"""Every sentence ``src/reporting`` states about itself, as an assertion.

A verification pass over the module found four docstrings claiming something a measurement refutes,
and four repairs that could be deleted with the whole suite green. Those are one failure with two
faces — a claim nothing tests is a claim that drifts, and a repair nothing tests is a repair the
next refactor deletes — so both are pinned here, in one file, next to the sentence each defends.

Three rules this file follows, because they are what made the earlier tests miss these:

* **Pin the claim, not the code.** Several tests below assert something the module admits it does
  *not* close (a §9 derived check that holds on a diagnostic payload; a rewritten basket figure
  reaching the artifact). They pass today. If somebody closes one, the test goes red and the
  docstring that states the residue has to be rewritten — which is the point: the residue is
  published as a falsifiable claim rather than a paragraph nobody can check.
* **Delete the repair and watch it fail.** Each repair-pinning test names, in its docstring, the
  exact line whose deletion turns it red. Every one of them was verified that way.
* **Literals, not the implementation's own expression.** The expected values below are written out.

Fixtures are reused from ``test_reporting.py`` rather than rebuilt, so the composed run these
assertions describe is the same one that file asserts on.
"""

from decimal import Decimal as D

import pytest

import gate_validation
from contracts import REPORTING_SCHEMA_VERSION, calc, canonicalise
from gate_validation import (
    IS_TRUE,
    MISMATCH,
    RECONCILIATION_CONDITIONS,
    SCHEMA,
    VALIDATION_GATE_CONDITIONS,
    check_conditions_detail,
)
from reporting import (
    CAPITAL_LEVELS,
    Diagnostic,
    DiagnosticPromotionRefused,
    DiagnosticRanking,
    DiagnosticRankingRow,
    DiagnosticScope,
    DiagnosticValue,
    RunReport,
    UnknownCapitalLevel,
    UnknownDiagnostic,
    diagnostic,
    diagnostic_pack,
    profit_ranking,
    report_run,
    run_artifact,
)
from reporting.boundary import RATIO, USD

from .test_reporting import WALLETS, _diagnostics, _run

SCOPE = DiagnosticScope(chain="ethereum", window=1, population="selected")


def _scope(**overrides):
    fields = dict(chain="ethereum", window=1, population="selected")
    fields.update(overrides)
    return DiagnosticScope(**fields)


# -- the identity key: one spelling per measurement ------------------------------
#
# ``DiagnosticPack`` refuses two items answering one question, and that refusal is only as good as
# the key it compares. ``_scope_key`` used to render the capital level with ``str``, where
# ``Decimal("1500000")`` and ``Decimal("1.5E+6")`` — equal, and equal-hashing — render differently.
# One measurement became two entries and the pack published both. The strings had the same shape
# with no normalisation at all.


def test_a_respelled_capital_level_is_the_same_scope_and_not_a_second_one():
    """Deleting the ``level_key`` call in ``DiagnosticScope.__post_init__`` turns this red.

    Measured on the unfixed code: keys ``('ethereum', 1, 'selected', '1500000', None, None)`` and
    ``('ethereum', 1, 'selected', '1.5E+6', None, None)``, pack accepted, ``buy_win_rate`` published
    at 0.61 and at 0.19 under one scope.
    """
    plain = _scope(capital_level=D("1500000"))
    exponent = _scope(capital_level=D("1.5E+6"))

    assert str(plain.capital_level) == "1500000"
    assert str(exponent.capital_level) == "1500000"
    assert plain == exponent
    assert hash(plain) == hash(exponent)
    assert canonicalise(plain) == canonicalise(exponent)

    with pytest.raises(UnknownDiagnostic) as refusal:
        diagnostic_pack((
            diagnostic("buy_win_rate", plain, D("0.61")),
            diagnostic("buy_win_rate", exponent, D("0.19")),
        ))
    assert "appears twice for the same scope" in str(refusal.value)


def test_a_respelled_capital_level_is_also_refused_at_the_key_and_not_only_at_the_field():
    """The second, independent reason: ``_scope_key`` renders the level through ``canonicalise``.

    Deleting *either* repair leaves the other holding, which is why both exist — the identity key
    must not depend on a normalisation that lives three screens away. This test reads the private
    helper deliberately: it is the only way to assert the key itself rather than its consequence.
    """
    from reporting.diagnostics import _scope_key

    key = _scope_key(_scope(capital_level=D("1500000")))
    assert key == ("ethereum", 1, "selected", "1500000", None, None)
    assert _scope_key(_scope(capital_level=D("1.5E+6"))) == key
    # And the rendering the key uses is the rendering the artifact gets.
    assert canonicalise(D("1.5E+6")) == "1500000"

    # The level put back out of canonical form, which is what the constructor's normalisation
    # being absent — or rewritten past — looks like from here. Reverting this line to
    # ``str(scope.capital_level)`` turns the assertion below red while everything above it stays
    # green, which is the only way to tell a redundant repair from an absent one.
    respelled = _scope(capital_level=D("1500000"))
    object.__setattr__(respelled, "capital_level", D("1.5E+6"))
    assert _scope_key(respelled) == key


def test_a_level_respelled_past_the_constructor_is_still_one_entry_in_the_pack():
    """The same repair as above, pinned by its consequence instead of by the private key.

    The test above reads ``_scope_key`` directly, which is the only way to see the key itself and
    also the reason it needs a partner: a helper's return value is not a published fact. Here the
    rewrite that ``object.__setattr__`` performs — the one the constructor's normalisation cannot
    reach, because it happens afterwards — has to come out as the pack refusing two answers to one
    question. With ``_scope_key`` back on ``str`` the pack accepts both and publishes ``0.61`` and
    ``0.19`` for one measurement.
    """
    first = diagnostic("buy_win_rate", _scope(capital_level=D("1500000")), D("0.61"))
    second = diagnostic("buy_win_rate", _scope(capital_level=D("1500000")), D("0.19"))
    object.__setattr__(second.scope, "capital_level", D("1.5E+6"))

    with pytest.raises(UnknownDiagnostic) as refusal:
        diagnostic_pack((first, second))
    assert "appears twice for the same scope" in str(refusal.value)


def test_a_capital_level_nobody_pre_registered_is_refused_rather_than_keyed():
    """§3.1 fixes five rungs. A sixth is a different experiment, not a sixth row."""
    for level in CAPITAL_LEVELS:
        assert _scope(capital_level=level).capital_level == level
    with pytest.raises(UnknownCapitalLevel):
        _scope(capital_level=D("1000000"))


def test_two_spellings_of_one_chain_or_population_are_one_scope():
    """The same class as the capital level, in the fields nothing had normalised at all.

    Measured on the unfixed code: ``chain="ethereum"`` and ``chain="Ethereum"`` were two keys, and
    ``buy_win_rate`` published twice with two different answers. Deleting either ``_canonical_text``
    call in ``DiagnosticScope.__post_init__`` turns this red.
    """
    assert _scope(chain="Ethereum") == _scope(chain="ethereum")
    assert _scope(chain="  ETHEREUM  ") == _scope(chain="ethereum")
    assert _scope(population="Matched  Controls") == _scope(population="matched controls")
    assert _scope(liquidity_band="Deep") == _scope(liquidity_band="deep")

    for a, b in (
        (_scope(chain="ethereum"), _scope(chain="Ethereum")),
        (_scope(population="selected"), _scope(population="Selected")),
        (_scope(liquidity_band="deep"), _scope(liquidity_band="DEEP")),
    ):
        with pytest.raises(UnknownDiagnostic):
            diagnostic_pack((
                diagnostic("buy_win_rate", a, D("0.61")),
                diagnostic("buy_win_rate", b, D("0.19")),
            ))


def test_an_absent_liquidity_band_has_one_spelling():
    """``None`` and ``""`` key differently and read identically in a report."""
    assert _scope(liquidity_band=None).liquidity_band is None
    with pytest.raises(ValueError) as refusal:
        _scope(liquidity_band="   ")
    assert "absence spelled as a presence" in str(refusal.value)


def test_the_empty_band_is_refused_without_help_from_the_whitespace_collapse():
    """The second pin on the same guard, at the input that does not need ``_canonical_text``.

    ``"   "`` only reaches the emptiness check because ``_canonical_text`` collapses it first, so a
    test built on that one input cannot say which of the two lines it is holding down. A literal
    ``""`` reaches it directly. The key each spelling would produce is written out beside it: an
    absent band is ``None`` in position four, and an empty one would be ``""`` — a second entry for
    one measurement, which is the collapse this whole file is about.
    """
    from reporting.diagnostics import _scope_key

    with pytest.raises(ValueError) as refusal:
        _scope(liquidity_band="")
    assert "absence spelled as a presence" in str(refusal.value)

    assert _scope_key(_scope()) == ("ethereum", 1, "selected", None, None, None)


def test_a_scope_field_that_is_not_a_string_is_refused_by_name():
    with pytest.raises(TypeError) as refusal:
        _scope(chain=1)
    assert "chain" in str(refusal.value)


@pytest.mark.parametrize("field", ["chain", "population", "liquidity_band"])
def test_every_string_scope_field_is_refused_by_name_when_it_is_not_a_string(field):
    """The test above holds only ``chain`` down, and the guard is three calls, not one.

    Deleting the ``_canonical_text`` call for ``population`` or for ``liquidity_band`` left the
    whole suite green on the non-string input: ``if not self.population`` is satisfied by any
    truthy object, so a scope carrying the ``int`` ``1`` as its population was constructed, keyed
    and published. Each field is asserted separately here, so a deletion cannot hide behind a
    sibling that is still checked.
    """
    with pytest.raises(TypeError) as refusal:
        _scope(**{field: 1})
    assert field in str(refusal.value)
    assert "must be a string naming a scope" in str(refusal.value)


def test_each_scope_string_field_is_stored_canonically_and_not_merely_compared_equal():
    """The stored value, field by field, written out.

    ``test_two_spellings_of_one_chain_or_population_are_one_scope`` asserts that two scopes are
    *equal*, which a comparison that ignored case would also satisfy — and the module says
    explicitly that the fix is a normalisation of the stored field rather than a lenient
    comparison, because the artifact publishes what is stored. These are the stored strings.
    """
    scope = _scope(chain="  ETHEREUM  ", population="Matched  Controls", liquidity_band="Deep")
    assert scope.chain == "ethereum"
    assert scope.population == "matched controls"
    assert scope.liquidity_band == "deep"

    published = canonicalise(diagnostic("buy_win_rate", scope, D("0.61")))["scope"]
    assert published["chain"] == "ethereum"
    assert published["population"] == "matched controls"
    assert published["liquidity_band"] == "deep"


def test_the_three_collapses_canonical_text_performs_are_the_three_it_names():
    """``_canonical_text`` says exactly which spellings it collapses; this is that list.

    The sentence used to read "case-folding and internal whitespace, and nothing else" and omitted
    the strip — in a function whose entire subject is which spellings become one key. Each collapse
    is asserted on its own, and the last case pins the "nothing else": a character that is neither
    whitespace nor an ASCII letter survives untouched, so this is not a general slugifier that a
    later edit could widen without a test noticing.
    """
    from reporting.diagnostics import _canonical_text

    assert _canonical_text("ETHereum", "chain") == "ethereum"           # case
    assert _canonical_text("matched  controls", "population") == "matched controls"  # internal
    assert _canonical_text("\tethereum\n ", "chain") == "ethereum"      # leading and trailing
    assert _canonical_text("arbitrum-one_v2.1", "chain") == "arbitrum-one_v2.1"      # nothing else
    assert _canonical_text(None, "liquidity_band") is None

    # And the strip is not cosmetic: it is what makes a padded name the same scope, not a second.
    assert _scope(chain="  ethereum  ") == _scope(chain="ethereum")


# -- publication is where the invariant has to hold ------------------------------


def _tamper(report):
    scalar = [item for item in report.diagnostics.items if isinstance(item, Diagnostic)][0]
    object.__setattr__(scalar, "gate_relevance", "GATE")
    object.__setattr__(scalar, "name", "sharpe_ratio")
    return scalar


def test_a_diagnostic_rewritten_after_assembly_cannot_reach_the_artifact():
    """Deleting ``report.diagnostics.verify()`` in ``run_artifact`` turns this red.

    This is the window the comment in ``report_run`` used to claim it closed. Measured on the
    unfixed code: the artifact carried ``{"gate_relevance": "GATE", "name": "sharpe_ratio", …}``
    with payload hash 1944bee2… and ``verify_envelope`` returning clean.
    """
    report = _run()
    _tamper(report)
    with pytest.raises(UnknownDiagnostic):
        run_artifact(report)


def test_the_assembly_check_refuses_before_a_report_exists_at_all():
    """``report_run``'s own ``diagnostics.verify()``, pinned apart from ``run_artifact``'s.

    Both calls refuse the same tampered pack, so a test that only asserts "this cannot be
    published" is held down by whichever of the two still exists. What only the assembly check
    buys is stated in the comment beside it: the refusal names the assembly step, and no
    ``RunReport`` carrying the tamper is ever handed back — so a caller who serialises the report
    themselves, quotes a figure out of it, or hands it to anything that is not ``run_artifact``
    never holds one.

    The tamper is a bare ``Decimal`` written back over a payload, which is a different check inside
    ``verify()`` from the ``gate_relevance`` rewrite the other test uses. ``run_artifact`` is
    deliberately never called here: with ``diagnostics.verify()`` deleted from ``report_run`` this
    goes red, while every publication-time test stays green.
    """
    pack = _diagnostics()
    scalar = [item for item in pack.items if isinstance(item, Diagnostic)][0]
    object.__setattr__(scalar, "value", D("0.184"))

    with pytest.raises(DiagnosticPromotionRefused) as refusal:
        report_run(
            run_id="phase0-2026-08-01",
            chain="ethereum",
            basket=_run().basket,
            windows=_run().windows,
            capital_ladder=_run().capital_ladder,
            churn=_run().churn,
            diagnostics=pack,
        )
    assert "Decimal" in str(refusal.value)


def test_a_run_report_built_directly_cannot_publish_a_rewritten_diagnostic():
    """``RunReport`` is exported and constructible without ``report_run``'s guard, so publication
    has to be the boundary rather than assembly. Same repair, second route."""
    clean = _run()
    pack = _diagnostics()
    tampered = [item for item in pack.items if isinstance(item, Diagnostic)][0]
    object.__setattr__(tampered, "gate_relevance", "GATE")

    direct = RunReport(
        run_id=clean.run_id,
        chain=clean.chain,
        basket=clean.basket,
        windows=clean.windows,
        capital_ladder=clean.capital_ladder,
        churn=clean.churn,
        diagnostics=pack,
    )
    with pytest.raises(DiagnosticPromotionRefused):
        run_artifact(direct)


def test_a_report_that_holds_no_pack_at_all_is_refused_where_it_is_assembled():
    """Deleting the ``DiagnosticPack`` check in ``RunReport.__post_init__`` turns this red: the
    publication-time ``verify()`` would then meet a bare tuple with an ``AttributeError``."""
    clean = _run()
    with pytest.raises(TypeError) as refusal:
        RunReport(
            run_id=clean.run_id,
            chain=clean.chain,
            basket=clean.basket,
            windows=clean.windows,
            capital_ladder=clean.capital_ladder,
            churn=clean.churn,
            diagnostics=tuple(clean.diagnostics.items),
        )
    assert "DiagnosticPack" in str(refusal.value)


class _DuckPack(object):
    """Something that answers ``verify()``. It is not a pack and refuses nothing."""

    items = ()

    def verify(self):
        return True


def test_the_pack_check_is_on_the_type_and_not_on_the_presence_of_verify():
    """Second pin on the same check, at the input that makes it load-bearing rather than tidy.

    A bare tuple is caught either way in the end: without the type check, ``run_artifact``'s
    ``report.diagnostics.verify()`` meets it with an ``AttributeError``. An object that *answers*
    ``verify()`` is not — deleting the check publishes an artifact whose diagnostics block was
    never a pack, so nothing ever re-ran an item's invariants and the ``DIAGNOSTIC_ONLY`` label on
    the block is a label and not a check.
    """
    clean = _run()
    with pytest.raises(TypeError) as refusal:
        RunReport(
            run_id=clean.run_id,
            chain=clean.chain,
            basket=clean.basket,
            windows=clean.windows,
            capital_ladder=clean.capital_ladder,
            churn=clean.churn,
            diagnostics=_DuckPack(),
        )
    assert "DiagnosticPack" in str(refusal.value)
    assert "_DuckPack" in str(refusal.value)


def test_a_clean_report_still_publishes_unchanged():
    """The guard above must refuse tampers and nothing else."""
    report = _run()
    envelope = run_artifact(report)
    assert envelope["payload"]["reporting_schema_version"] == "report-v1"
    assert run_artifact(report) == envelope


def test_the_other_four_blocks_are_not_re_verified_at_publication():
    """The residue ``run_artifact``'s docstring states, pinned as a claim rather than a paragraph.

    A rewritten basket figure reaches the artifact and its payload hash: only the diagnostics pack
    is reconstructed at publication. If somebody closes this, the assertion below fails and the
    docstring that admits it must be rewritten — which is the entire reason it is written down.
    """
    report = _run()
    object.__setattr__(report.basket, "n_wallets", 99)
    envelope = run_artifact(report)
    assert envelope["payload"]["basket"]["n_wallets"] == "99"


# -- the ranking's two undefended checks ----------------------------------------


class _DuckRow(object):
    """A row-shaped object that is not a row. Carries a readable payload, like the real thing."""

    rank = 1
    wallet = WALLETS[0]
    value = DiagnosticValue(amount=D("999999"), kind=USD)


def test_a_ranking_refuses_a_row_that_is_not_a_row():
    """Deleting ``if not isinstance(row, DiagnosticRankingRow)`` in ``DiagnosticRanking`` turns this
    red. Measured on the unfixed code: accepted, and the duck row passed the pack and ``verify()``
    with the whole suite green."""
    with pytest.raises(DiagnosticPromotionRefused) as refusal:
        DiagnosticRanking(
            name="absolute_profit_ranking", scope=SCOPE, kind=USD, rows=(_DuckRow(),)
        )
    assert "_DuckRow" in str(refusal.value)


def test_the_ranking_row_guard_holds_for_a_mixed_tuple_and_for_a_bare_payload():
    """Second pin on ``DiagnosticRanking``'s own row check, at two inputs the first does not reach.

    A ranking whose *first* row is real and whose second is not is the shape a mis-assembled join
    produces, and it distinguishes a guard that checks every row from one that checks ``rows[0]``.
    A bare ``DiagnosticValue`` in a row slot is the likelier mis-splice of the two — it carries a
    ``kind``, so with the guard deleted it reaches ``row.value.kind`` and is refused by an
    ``AttributeError`` naming neither the ranking nor the type.
    """
    real = DiagnosticRankingRow(
        rank=1, wallet=WALLETS[0], value=DiagnosticValue(amount=D("2000"), kind=USD)
    )
    with pytest.raises(DiagnosticPromotionRefused) as mixed:
        DiagnosticRanking(
            name="absolute_profit_ranking", scope=SCOPE, kind=USD, rows=(real, _DuckRow())
        )
    assert "_DuckRow" in str(mixed.value)

    with pytest.raises(DiagnosticPromotionRefused) as payload:
        DiagnosticRanking(
            name="absolute_profit_ranking", scope=SCOPE, kind=USD,
            rows=(DiagnosticValue(amount=D("2000"), kind=USD),),
        )
    assert "DiagnosticValue was placed in a diagnostic ranking" in str(payload.value)


def test_a_row_spliced_into_a_built_ranking_is_refused_at_publication():
    ranking = profit_ranking(SCOPE, ((WALLETS[0], D("1000")), (WALLETS[1], D("2000"))))
    pack = diagnostic_pack((ranking,))
    object.__setattr__(ranking, "rows", (_DuckRow(),))
    with pytest.raises(DiagnosticPromotionRefused):
        pack.verify()


def test_a_spliced_row_with_no_payload_at_all_is_a_typed_refusal():
    """Deleting the ``isinstance`` guard in ``_check_payload``'s row loop turns this red.

    It becomes ``AttributeError: 'str' object has no attribute 'value'`` — still refused, by a duck
    test, which is the thing ``_rebuilt``'s docstring says this module does not rely on.
    """
    ranking = profit_ranking(SCOPE, ((WALLETS[0], D("1000")),))
    pack = diagnostic_pack((ranking,))
    object.__setattr__(ranking, "rows", ("not a row",))
    with pytest.raises(DiagnosticPromotionRefused) as refusal:
        pack.verify()
    assert "a str was placed in diagnostic ranking 'absolute_profit_ranking'" in str(refusal.value)


def test_the_row_guard_names_the_ranking_for_any_spliced_type():
    """The second pin on ``_check_payload``'s row loop, and on the thing that makes it worth having.

    A ``Decimal`` in a row slot is the shape of a mis-assembled ranking rather than a splice, and
    without the guard it is refused by ``AttributeError: 'decimal.Decimal' object has no attribute
    'value'`` — the duck test this module says it does not rely on.

    The message naming the ranking is not decoration. It is the only thing that distinguishes this
    refusal from ``DiagnosticRanking``'s own, which fires when ``_rebuilt`` runs first and says
    only "a diagnostic ranking". Swapping ``_check_payload`` and ``_rebuilt`` in
    ``DiagnosticPack.__post_init__`` turns this red for exactly that reason, which is why the
    comment there no longer claims the ordering is inert.
    """
    ranking = profit_ranking(SCOPE, ((WALLETS[0], D("1000")),))
    pack = diagnostic_pack((ranking,))
    object.__setattr__(ranking, "rows", (D("1000"),))

    with pytest.raises(DiagnosticPromotionRefused) as refusal:
        pack.verify()
    message = str(refusal.value)
    assert "a Decimal was placed in diagnostic ranking 'absolute_profit_ranking'" in message


def test_a_ranking_cannot_report_dollars_under_a_ratio_label():
    """Deleting ``if row.value.kind != self.kind`` in ``DiagnosticRanking`` turns this red.

    Measured on the unfixed code: accepted, and ``(ranking.kind, str(row.value), row.value.kind)``
    published as ``('ratio', '1000', 'usd')`` — $1,000 under a label that says it is a ratio.
    ``DiagnosticRankingRow`` forces its own payload to USD, so this check is the only thing that
    couples the ranking's declared scale to the figures inside it.
    """
    row = DiagnosticRankingRow(
        rank=1, wallet=WALLETS[0], value=DiagnosticValue(amount=D("1000"), kind=USD)
    )
    with pytest.raises(ValueError) as refusal:
        DiagnosticRanking(name="absolute_profit_ranking", scope=SCOPE, kind=RATIO, rows=(row,))
    assert "the scale is part of what a reported number means" in str(refusal.value)


def test_a_rankings_declared_kind_rewritten_after_the_fact_is_refused_at_publication():
    ranking = profit_ranking(SCOPE, ((WALLETS[0], D("1000")), (WALLETS[1], D("2000"))))
    pack = diagnostic_pack((ranking,))
    object.__setattr__(ranking, "kind", RATIO)
    with pytest.raises(ValueError):
        pack.verify()


def test_the_pack_keeps_the_item_it_was_handed_and_repairs_nothing():
    """``_rebuilt`` is a re-validation, not a repair — the claim the ordering comment rests on.

    If the rebuild's result were ever kept, ``_as_payload`` would coerce a bare-``Decimal`` tamper
    into a valid payload on the way to the artifact, and the refusal below would become a silent
    correction.
    """
    item = diagnostic("median_return", _scope(), D("0.045"))
    pack = diagnostic_pack((item,))
    assert pack.items[0] is item

    object.__setattr__(item, "value", D("0.045"))
    with pytest.raises(DiagnosticPromotionRefused):
        pack.verify()
    assert item.value == D("0.045")
    assert not isinstance(item.value, DiagnosticValue)


# -- what the gate does and does not refuse, measured ----------------------------


def test_no_gate_condition_holds_on_a_diagnostic_payload_and_one_is_not_a_schema_error():
    """The corrected paragraph in ``DiagnosticValue``, over all sixteen conditions.

    The docstring used to say a payload is a ``SCHEMA`` discrepancy "whichever comparison the
    condition names". ``IS_TRUE`` tests ``value is True`` before ``calc`` is reached, so it yields
    ``MISMATCH``. The load-bearing half — nothing holds — is asserted over every condition; the
    mechanism is asserted per comparison, so the day ``IS_TRUE`` starts routing through ``calc``
    this goes red and the docstring is rewritten rather than left behind.
    """
    conditions = VALIDATION_GATE_CONDITIONS + RECONCILIATION_CONDITIONS
    payload = diagnostic("buy_win_rate", SCOPE, D("1")).value

    boolean, numeric = [], []
    for condition in conditions:
        detail = check_conditions_detail({condition.field: payload}, (condition,), "spot")
        assert not detail.ok, condition.field
        kinds = [discrepancy.kind for discrepancy in detail.discrepancies]
        if condition.comparison == IS_TRUE:
            assert kinds == [MISMATCH], condition.field
            boolean.append(condition.field)
        else:
            assert kinds == [SCHEMA], condition.field
            numeric.append(condition.field)

    assert boolean == ["independent_review_completed"]
    assert len(numeric) == len(conditions) - 1


def test_the_numeric_gate_entry_points_refuse_a_payload():
    """The bullet's first half: everything that reads its figure through ``calc``."""
    payload = diagnostic("buy_win_rate", SCOPE, D("0.61")).value
    with pytest.raises(TypeError):
        calc(payload)
    with pytest.raises(TypeError):
        gate_validation.evaluate_windows_detail([], payload)
    with pytest.raises(TypeError):
        gate_validation.assess_capital_feasibility({D("1500000"): payload})

    spec = gate_validation.ToleranceSpec(name="buy_quality", tolerance=D("0.005"))
    report = gate_validation.check_numeric_fields_detail(
        {"buy_quality": payload}, {"buy_quality": D("0.61")}, (spec,)
    ).report
    assert [d.kind for d in report.discrepancies] == [SCHEMA]


def test_a_diagnostic_payload_satisfies_a_section_nine_derived_check():
    """The exception the module's opening bullet now states, pinned in both directions.

    ``contracts.verify_redundant_derived`` reads its claimed figure as ``Decimal(str(claimed_raw))``
    rather than through ``calc``, and ``DiagnosticValue.__str__`` is the rendered figure — so a
    payload behaves at ``check_derived_fields`` exactly as the bare ``Decimal`` it wraps. Both
    directions are asserted, because "zero discrepancies" alone would also be what a check that
    never ran looks like.

    **This test passing is a defect, not a feature.** It is here so the sentence describing the
    residue cannot quietly stop being true: close the leak — ``verify_redundant_derived`` reading
    through ``calc``, which is inside the frozen seam — and this goes red, and the bullet in
    ``reporting/diagnostics.py`` gets rewritten in the same commit.
    """
    payload = diagnostic("buy_win_rate", SCOPE, D("0.61")).value
    recomputations = {"total": lambda p: calc(p["a"]) + calc(p["b"])}

    agrees = gate_validation.check_derived_fields(
        {"total": payload, "a": "0.3", "b": "0.31"}, recomputations
    )
    disagrees = gate_validation.check_derived_fields(
        {"total": payload, "a": "0.3", "b": "0.32"}, recomputations
    )
    assert agrees.discrepancies == ()
    assert len(disagrees.discrepancies) == 1
    assert "0.61000000" in disagrees.discrepancies[0].detail

    # The same figure, unwrapped, behaves identically — which is what "read as a number" means.
    assert gate_validation.check_derived_fields(
        {"total": D("0.61"), "a": "0.3", "b": "0.31"}, recomputations
    ).discrepancies == ()


# -- equality, hashing, and the shape of a published figure ----------------------


def test_a_payload_that_compares_equal_to_a_number_also_hashes_like_one():
    """Deleting the ``hash(self.amount)`` repair turns this red.

    Measured on the unfixed code: ``a == D("1")`` was ``True`` while ``hash(a) == hash(D("1"))`` was
    ``False``, ``len({a, D("1")})`` was 2 and ``D("1") in {a}`` was ``False`` — ``==`` disagreeing
    with itself depending on which container asked.
    """
    usd_one = DiagnosticValue(amount=D("1"), kind=USD)
    ratio_one = DiagnosticValue(amount=D("1"), kind=RATIO)
    one = D("1")

    assert usd_one == one
    assert hash(usd_one) == hash(one)
    assert one in {usd_one}
    assert len({usd_one, one}) == 1
    assert usd_one in [one]


def test_payload_equality_is_not_transitive_across_kinds_and_says_so():
    """The stated residue of permitting cross-type equality. Kept as an assertion so that the
    paragraph in ``DiagnosticValue`` describing it stays checkable."""
    usd_one = DiagnosticValue(amount=D("1"), kind=USD)
    ratio_one = DiagnosticValue(amount=D("1"), kind=RATIO)
    one = D("1")

    assert usd_one == one and ratio_one == one
    assert usd_one != ratio_one
    # Equal hashes, unequal objects: legal, and the direction that fails safe.
    assert hash(usd_one) == hash(ratio_one)
    assert len({usd_one, ratio_one}) == 2


def test_the_published_diagnostic_shape_is_pinned_against_the_version_that_names_it():
    """``report-v1`` no longer describes this block, and the note in ``run.py`` says so.

    The figures are literals. If the shape moves again under the same version string, this goes red
    — which is the only thing standing between a consumer pinned to ``report-v1`` and an artifact
    that no longer matches it.
    """
    report = _run()
    payload = run_artifact(report)["payload"]
    assert payload["reporting_schema_version"] == "report-v1"
    assert REPORTING_SCHEMA_VERSION == "report-v1"

    diagnostics = payload["diagnostics"]["items"]
    scalar = [item for item in diagnostics if item["name"] == "simple_wallet_return"][0]
    assert scalar["value"] == {"amount": "0.184", "kind": "ratio"}
    assert scalar["gate_relevance"] == "DIAGNOSTIC_ONLY"

    ranking = [item for item in diagnostics if item["name"] == "absolute_profit_ranking"][0]
    assert ranking["rows"][0]["value"] == {"amount": "980000.25", "kind": "usd"}
