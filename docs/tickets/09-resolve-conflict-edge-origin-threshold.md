# 09 — Resolve OPEN conflict 2: the Edge Origin threshold after long-tail exclusion

**What to build:** A recorded, signed resolution of the second conflict. `First-Hour Edge Share ≤ 40%`
is a hard gate condition built to exclude sniping and insider-like behaviour. But most first-hour
sniping happens in long-tail tokens, and long-tail assets are now excluded from Ethereum Phase 0
outright because their measured capacity is $0. The condition still binds for a mid-cap token in its
first hour, but that is a much smaller population, and the 40% number was calibrated against an
intuition about a universe that no longer contains its main source of first-hour activity. The
condition should stay — it costs nothing. What must be decided is whether 40% stands, whether it moves,
and whether the condition is still claimed as a primary defence or is recorded as a cheap backstop.
Choosing silently is the one option not available.

**Blocked by:** None — can start immediately.

**Status:** resolved 2026-07-31 — keep 40%, recorded as a backstop

- [ ] The population the condition now actually covers is characterised: mid-cap and major tokens in
      their first hour on Ethereum, with long-tail excluded.
- [ ] The threshold is either confirmed at 40%, or changed to a stated value, with the reasoning
      recorded either way.
- [ ] The condition's role is stated explicitly as either a primary defence against sniper-driven gate
      passes, or a cheap backstop retained because it costs nothing.
- [ ] If it is demoted to a backstop, the compensating defence against adversarial targeting is named
      — or its absence is recorded as an accepted, unmitigated risk.
- [ ] The small-denominator guard is confirmed or revised in the same decision: total positive edge
      contribution below 5 percentage points marks a window `INDETERMINATE`, and `INDETERMINATE` is a
      failure and not an abstention.
- [ ] The decision is dated before any measurement result exists, is signed by the Research Owner, and
      is staged for inclusion in the pre-registration.
- [ ] No option is available in which the threshold is left at 40% without a recorded justification.

---

**Resolution (2026-07-31, Research Owner):** The threshold is unchanged and the condition still binds, but it is now documented as a cheap backstop rather than the primary defence against uncopyable behaviour — that role belongs to Gate 2, which tests economic copyability directly at design_capital. Merged into pre-registration v1.1 §7.1.
