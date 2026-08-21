# 33 — Gate evaluation engine over the full condition matrix

**What to build:** The engine that turns numbers into a verdict, built and exhaustively tested on
table-driven fixtures **before** any real result exists. Both columns gate: leader skill persistence
and economic copyability at design capital. A raw positive leader edge may not conceal an execution-
capacity failure, and a diagnostic may never overturn a gate result — the engine must make that
structurally impossible rather than merely discouraged, because it is the failure mode the entire
protocol exists to prevent.

**Blocked by:** 31, 32

**Status:** audited 2026-08-16, and the headline finding closed the same day. `src/gate_validation/`
is 2,208 lines. The audit read **4 met, 5 partial, 1 not met**; criterion 1's first-hour half and
criterion 3's significance half are now closed, and criterion 10 with them as far as the lane rule
permits. Boxes stay unticked until the remaining partials are worked; the audit is below.

**The finding, in one line: the arbiter certified two verdicts it did not derive.** Its import
isolation was real and enforced — `contracts` and the standard library, nothing else — and that buys
*import* independence, not *derivation* independence. Both are now checked. What remains open is
criterion 6 (nothing forces the `CONDITIONAL_REVIEW` decision to be recorded) and criterion 8 (the
STOP branch of the decision matrix asserts nothing, so a wrongly-STOPped GO passes silently).

## §7.1's half, closed

**Closed 2026-08-16.** The arbiter now refuses a `WindowScore` whose `edge_origin_status` and
`first_hour_edge_share` cannot both be true, and holds `FIRST_HOUR_EDGE_SHARE_MAX = 0.40` itself —
where before it held no first-hour limit at all and could not have checked the condition even in
principle.

**Deliberately a consistency check and not a second verdict.** This module's docstring is right that
an arbiter growing its own copy of the gate rule is the failure it exists to prevent: two
implementations disagreeing silently, with whichever was consulted last deciding. So nothing is
derived. Two fields the caller supplied together are compared *to each other*, and an impossible
pair raises rather than being resolved — refusing on the contradiction rather than picking a side,
which is the same shape as the identity-key rule elsewhere in this package. The docstring's fear is
silence; a refusal removes the silence without adding a rule.

Both directions refuse, including the safe one. A window wrongly marked `UNCOPYABLE_DOMINATED` inside
the limit costs a finding rather than manufacturing one — and is still refused, because the arbiter
does not know which of the two fields is the defect, and trusting the status here would be trusting
it in the dangerous direction too.

The boundary is pinned on the side that matters: ticket 09 resolved §7.1 as *strictly greater than*
40% failing, so exactly 40% is consistent with `VALID`. Mutation 115 tightens `>` to `>=` and dies.
Mutation 114 removes the check entirely and dies.

**This also closes criterion 10 as far as the lane rule permits.** The constant is a copy — importing
`phase0` would let the arbiter reach the lane it judges — and it is now held equal to the frozen
`gate.first_hour_edge_share_max` in ticket 11's `UNMIGRATED` list, alongside the four
`gate_validation` entries already there.

**The property suite was generating impossible data, which is how this survived.** Its strategy drew
the share independently of the status, so it produced `VALID` beside 0.95 and asserted invariants
about it; only non-`VALID` scores were checked for failure. The strategy now draws the share on the
side of the limit its status claims, importing the limit from the module rather than restating it.

## §7.3's half, closed the same day — and the fixtures were the finding

`percentile_95` and `empirical_p` reached the arbiter as *fields the caller declares*, while
`null_statistics` — the distribution both are derived from — sat unread in the same object. The
arbiter now recomputes both and refuses on disagreement.

**This one does derive, and that is the difference from §7.1's half.** The first-hour check compares
two supplied fields to each other and computes nothing. This reimplements two conventions — the
nearest-rank percentile and the `+1`-corrected p-value — because they are genuine degrees of freedom,
both pinned in prose, and an arbiter that recomputes them from the documented rule is the only reader
that can catch the builder drifting off it. What stays in the seam is the gate *rule*
(`observed > p95 and p <= 0.05`); what is recomputed here are its inputs.

**Then the check failed eight of this repository's own tests, and every one was right to fail.**

The fixtures declared p-values their distributions cannot produce. `tests/hand_computed` and
`tests/properties` both used three null runs — 0.10, 0.15, 0.20 — and declared `empirical_p = 0.01`
for the significant case. **Three runs cannot report a p below 1/(3+1) = 0.25**, so `p <= 0.05` was
arithmetically unreachable and the suite simply asserted it. The two integration fixtures had correct
percentiles and fabricated p-values the same way: 0.008 declared where twenty runs bound p at 1/21.

So **§7.3's significance path had never been exercised on data that could legitimately be
significant.** Every "significant" case in the arbiter's suite rested on a number its own evidence
did not reach.

All four fixtures now carry twenty runs, which is the smallest distribution that can honestly clear
the gate: the smallest p at n runs is 1/(n+1), so n ≥ 19. With the observed statistic above every
null the count is zero and p is exactly 1/21 — and the insignificant cases are made insignificant by
lowering the *observed* value into the distribution rather than by overriding a bound.

`NULL_PERCENTILE = 0.95` joins the arbiter's local constants, held equal to
`gate.significance.null_percentile` in ticket 11's `UNMIGRATED` list. Mutations 116 (remove the
check) and 117 (drop the `+1` correction, so a distribution no run beat reports `p = 0`) both die.

**Still open on this criterion:** `n_runs` is not checked against §8.2's 1,000. That is deliberate —
the fixtures run at 20 and the requirement is a property of a real calibration run rather than of
every evaluation, so enforcing it here would refuse every test in the tree. It belongs with the run,
not with the arbiter.

## The original finding, kept because the reasoning is the useful part

The package docstring says it exists so that a gate cannot inherit the bug it is judging, and its
import isolation is real and enforced: an AST walk over every module permits `contracts`,
`dataclasses`, `decimal` and `typing` and nothing else. **That buys import independence, not
derivation independence,** and two of §7's conditions are decided by numbers the builder lane handed
over already decided.

**§7.1's first-hour condition.** `gate_validation` holds **no first-hour limit constant anywhere** —
verified by grep, not inferred. It reads `score.edge_origin_status`, an enum computed by
`src/scoring/edge.py`, and copies `first_hour_edge_share` into the verdict without comparing it to
anything. So a `VALID` score carrying a first-hour share of **0.95** passes the gate. The property
test's own strategy generates exactly that shape and asserts only that a non-`VALID` score fails.

**§7.3's significance.** `NullSummary.significant` is
`observed_statistic > percentile_95 and empirical_p <= 0.05`, where both bounds are **fields** — the
caller declares them. The arbiter holds `null_statistics` and never recomputes the quantile, never
recomputes p, never checks `n_runs` against the 1,000 §8.2 requires, and never binds
`observed_statistic` to the evaluation it is judging.

Both are checkable here from data already in hand, without importing anything outside `contracts`:
the share against a locally pinned 0.40, and the quantile and p from `null_statistics`. As written, a
scoring bug that stamps `VALID` on a 0.95 share, or a null summary field off by one rung, produces a
GO that no test in this package can distinguish from a real one.

This is the same shape as the reason `src/groundtruth/` was removed the same day: a reference built
out of the thing it checks agrees with it about whatever it got wrong. There the fix was to delete;
here it is to derive.

## Criterion 10 is not met, and it connects to ticket 11

Thresholds are not bound to the frozen set. `windows.py:225` accepts any finite caller threshold and
`decision.py:240` only compares it to the caller's own `locked_threshold`. The threshold appears in
no manifest field.

This is a consequence of the lane rule rather than an oversight — `gate_validation` may not import
`phase0`, for exactly the reason above — and ticket 11 handled the same problem for four other
constants by listing them in `UNMIGRATED` and holding them equal by test. `gate.first_hour_edge_share_max`
= 0.40 is in the frozen set and has **no counterpart here to hold equal**, which is the finding: the
arbiter is missing the constant, not merely unlinked from it.

## Met, and worth naming

Gate 2 requires **both** $1.5M and $2M — `missing_levels` iterates the design levels and feasibility
demands no missing, none unmeasured and none at or below zero. The three-of-four rule needs both
columns per window, and an *absent* window is caught rather than silently counted as passing.
`PASSED` with capital `FAILED` yields `CONDITIONAL_REVIEW`, doubled in `contracts.metrics`.
`INDETERMINATE` is solid throughout.

**The identity-key defect class is closed at both keyed sites** — `by_window` and `_level_keyed` —
each refusing on the collision rather than on the values disagreeing, each with a published-outcome
proof, and the `object.__new__` residual stated rather than papered over. That was the defect that
flipped a published §7 outcome between GO and CONDITIONAL_REVIEW on dict iteration order, and the
audit was asked to check the whole class rather than the one instance. The remaining unguarded
mappings are the module-version dicts, which fail closed to MISSING.

## Two halves that never touch

Criterion 6: `CONDITIONAL_REVIEW` must carry a recorded decision from a closed list. The validator
exists; nothing forces the call. `DecisionRecord` and `GateDecision` carry no chosen-option field,
there is no caller in the repository, and the integration test emits a `CONDITIONAL_REVIEW` and then
validates an unrelated literal.

Criterion 8: the decision matrix is exercised by examples, not enumerated. The property test asserts
implications *from* GO and CR only, so the STOP branch asserts nothing — **a wrongly-STOPped GO
passes silently.**

- [ ] Gate 1 requires all three conditions per window: mean buy quality advantage ≥ the calibrated mean
      threshold; median buy quality advantage > 0; First-Hour Edge Share within the resolved limit.
- [ ] Gate 2 requires Follower-Adjusted Excess Buy Quality > 0 at **both** $1,500,000 and $2,000,000.
- [ ] Significance requires each result to exceed the 95th percentile of **its own** null distribution
      with empirical p ≤ 0.05 — leader against the leader null, follower-adjusted against the follower
      null, never borrowing the other's.
- [ ] The project-level rule is Gate 1 AND Gate 2 AND significance in at least 3 of 4 windows.
- [ ] The three-state outcome is produced correctly, including `Gate Result: PASSED` with
      `Capital Feasibility: FAILED` resolving to `Project Status: CONDITIONAL REVIEW`.
- [ ] `CONDITIONAL REVIEW` requires an explicit recorded decision before Phase 1 from the fixed list:
      reduce design capital, restrict the token universe, restrict wallets by copy capacity, reduce
      base position size, or stop.
- [ ] `INDETERMINATE` and `INSUFFICIENT CANDIDATE UNIVERSE` resolve to window failure, not abstention.
- [ ] Table-driven fixtures cover the entire condition matrix, including every combination that
      produces `CONDITIONAL REVIEW`, and all of them pass.
- [ ] No diagnostic input can reach the gate computation; the engine physically cannot read the
      diagnostics pack, and a test proves it.
- [ ] The engine reads its thresholds from the frozen parameter set and refuses to run with any local
      override.
