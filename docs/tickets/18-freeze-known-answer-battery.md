# 18 — Freeze the known-answer battery and stand up its harness

**What to build:** Sixteen synthetic cases whose answers are fixed before any code runs, plus the
harness that executes them. Every case in the battery exists because a specific documented failure
mode produced a wrong answer in a real system, so this is also the permanent regression suite. As with
the golden set, the demo is the harness running red against an empty pipeline — sixteen failures, each
naming the case it belongs to.

**Blocked by:** 11, 06

**Status:** all seven criteria met and audited. Unblocked by ticket 11's freeze on 2026-08-16 — its
blockers (11, 06) had both been satisfied and the ticket did not say so, which is the second time
that has happened this week.

Criterion 7 is closed by CI, which is what its wording asks for. A stronger reading of it — a run
that measures must have run the battery *in that run* — remains open by choice, with the failed
attempt and its reason recorded under that criterion. CI catches the developer who never ran the
battery; it does not catch the run that never ran it, and only the second reaches a published number.

- [x] All sixteen cases exist as fixtures with pre-determined expected answers: Simple Buy + Full
      Sell; Multiple Buys + Partial Sell; Multi-hop Buy; FIFO Allocation; Open Position at Day 30;
      Dead Pool; Thin but Live Pool; Liquidity-Bound Marking; Fee-on-Transfer Token; Failed
      Transaction; Circular Arbitrage; Internal Transfer; Multiple Pools for One Token; Pool
      Migration; First-Hour Classification; End-of-Window 30-Day Extension.
      — `REQUIRED_CASE_NAMES` is sixteen, `BATTERY` is sixteen, and `battery_report` computes the
      rate over the *required* names rather than over whatever is registered, so a battery that lost
      a case reports below 1 instead of a perfect score over fifteen.
- [x] Expected answers are authored from the frozen definitions, are recorded before any
      implementation exists, and are frozen under a fixtures version that the freeze manifest pins.
      — the version is a **content hash**, `known_answer_fixture_hash()`, pinned in the freeze
      manifest as §9.6's `known_answer_fixture_hash` and checked there; a hand-maintained version
      string would be one more thing that can disagree with what it names.

      *"Authored from the frozen definitions" only became checkable on 2026-08-16*, because before
      the freeze there were no frozen definitions to author from. The battery keeps its own literals
      on purpose — its comment is right that "a horizon that moves with a constant somewhere else
      pins nothing about the horizon" — so it is bound the way ticket 11 binds every other copy it
      could not remove: held equal by a test.
      `test_a_battery_constant_agrees_with_the_frozen_definition` pins `HORIZON_SECONDS`,
      `DAY_SECONDS` and `HOUR_SECONDS` against `measurement.horizon_days`,
      `token_age.bucket_c.seconds` and `token_age.bucket_b.seconds`, and
      `test_the_battery_reads_no_parameter_at_import` guards that guard — the equality is only worth
      something while there are genuinely two literals.
- [x] For deterministic logic — FIFO, net balance change, failed-transaction exclusion — the expected
      answer is exact, and only machine rounding error is tolerated in numeric results.
      — stricter than asked. `_answers_match` is plain `==` with no tolerance anywhere; there is no
      `approx`, no `isclose`, no `quantize` in the battery. Decimal scale is the only slack
      (`Decimal("2000.000000") == Decimal("2000")`), which preserves value rather than admitting
      error. `evaluate_case` is two-sided: a missing key *and* an unregistered extra key both fail.
- [x] The harness reports pass/fail per case and requires 100% pass; there is no waiver mechanism and
      no "known edge case" state.
      — `CaseResult` rejects both a pass carrying failures and a failure with no reason, so there is
      no third state to reach. A crash is a failed case, never a skipped one. Enforced statically by
      `test_no_case_may_be_skipped_or_expected_to_fail`, which AST-scans the package.

      **That check had two holes and they are now closed.** It keyed on the literal name `pytest` to
      the left of the dot, so `from pytest import skip` reached the same outcome unseen; and
      `__test__ = False` — not a pytest marker at all — removes a module from collection entirely,
      so every case in it disappears while the suite reports green over what is left. Both are one
      line. Both are now flagged, with their own guard-the-guard.
- [x] Run against an empty pipeline, the harness reports sixteen failures and exits with a failure
      status.
      — `test_against_an_empty_pipeline_the_harness_reports_sixteen_failures`.
- [x] The harness is wired to the governance module such that a known-answer failure prevents
      `VALIDATION_PASSED`.
      — `known_answer_pass_rate` must be `EXACTLY 1` in `VALIDATION_GATE_CONDITIONS`, and §9.8's
      gate failing leaves the null distribution and the main test unauthorised. Verified both ways
      rather than read: a rate of 15/16 fails the condition, and a battery that *crashed* — which
      publishes no value at all — fails as `MISSING`, "was not reported, so the condition cannot
      hold". The absent case is the one worth checking, because `measure.py` raises rather than
      publishing a sub-1 rate, so the gate never sees a low number, only a hole.
- [x] The battery is registered as the standing regression suite, run on every subsequent pipeline
      ticket, not only at the validation gate.
      — closed on 2026-08-16 by `.github/workflows/suite.yml`, the repository's first CI. The battery
      runs as its own named step before the full suite, so sixteen frozen cases failing produce a red
      check that says *Known-answer battery* rather than one dot among three and a half thousand.
      §9.3 admits no waiver, so no step may carry `continue-on-error`.

      The workflow is pinned by `tests/test_standing_regression_suite.py`, because a workflow file is
      one `git rm` from not existing with nothing noticing — the same reason every other rule here is
      enforced rather than described. Eight cases: it exists, the battery is a named step, no step
      may fail quietly, the interpreter is pinned to 3.9 (the tree uses no 3.10 syntax, so a later
      job would pass while hiding that), it triggers on push rather than only on request, and the
      cheap checks precede the slow one.

      Two things were measured rather than assumed, and both changed the file. A fresh
      `pip install -e ".[dev]"` and every step were run in a throwaway 3.9 venv — shipping CI that
      fails on step one would be careless. And the mutation battery copies the tree and runs pytest
      in a **subprocess** per mutation: 113 mutations are ~226 cold interpreter starts, which took
      over ten minutes standalone from a cold cache against six minutes warm inside the full suite.
      So the first draft's separate mutation step was removed — it doubled the slowest thing in the
      project for a label — and `timeout-minutes` is 60, because a job killed on timeout is
      indistinguishable in the checks list from a job whose tests failed, and a check people learn to
      ignore is worse than no check.

      **What this closes is the process half, which is what the criterion's own wording asks** —
      "every subsequent pipeline *ticket*" is an obligation on development, not on run ordering. The
      run-ordering version is described below and is still open:
      `known_answer.battery` is in `STAGES`, has a runner, and holds
      `StageAuthority(PARAMETERS_FROZEN, None)` — available from the parameter freeze onward,
      advancing nothing, so it is repeatable rather than gate-only.

      What is absent is anything that *requires* it to have run **inside a given run**.
      `companion_stages` derives companions from `advances`, which is `None` here, so the companion
      set is empty; and `VALIDATION_GATED_STAGES` deliberately excludes the build lane. So
      `pipeline.buy_quality`, `benchmark.match` and `follower.adjust` can all complete in a run where
      the battery never ran. CI catches the developer who never ran it; it does not catch the *run*
      that never ran it, and only the second reaches a published number.

      One smaller gap alongside it: only tickets 21–24 name battery cases in their own acceptance
      criteria. Tickets 19, 20 and 25–34 name none, so the per-ticket obligation is prose in
      `docs/tickets/README.md` rather than a checkbox anyone has to tick.

      **A stage-level version was implemented on 2026-08-16 and reverted, and the reason is worth
      keeping.**
      It worked: `REGRESSION_GATED_STAGES` derived the four build-lane stages after the battery from
      the declared order in `STAGES`, `regression_refusal` scoped the check through
      `completed_stages` — so an invalidation correctly required the battery again — and two
      mutations killed. What it also did was fail 27 tests, and the one that mattered was
      `tests/properties/test_execution.py::test_every_pair_agrees_with_the_specification`.

      That test derives which `(stage, state)` pairs may run from `STAGE_AUTHORITY`, whose own
      docstring says the table *is* the ordering rule: "a stage absent from here has no ordering
      rule at all, so absence is a test failure rather than a permissive default". The rule was
      bolted in beside the table rather than expressed inside it, so the specification and the
      implementation disagreed — and the property test was right to say so. The other 26 failures
      were consequences of the same thing.

      So closing it properly means a third field on `StageAuthority` — something like
      `certified_by` — so the table stays the single source of ordering truth and the property tests
      keep deriving from it. That is a real refactor of `phase0`, the SHARED package, and it means
      editing the tests that *encode the specification*, which is the last place to make a change on
      one's own reading of an ambiguous criterion. Named here, deliberately not taken.
