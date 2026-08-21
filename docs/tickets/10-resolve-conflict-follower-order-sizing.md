# 10 — Resolve OPEN conflict 3: follower order sizing

**What to build:** A recorded, signed resolution of the third conflict, and the one that blocks the
most code. `follower_adjusted_buy_quality` was locked with an assumed follower order size of 2% of
total portfolio capital at five capital levels. Portfolio construction is now out of scope, so "2% of
portfolio" has no definition to refer to. The addendum supplies replacement inputs — `strategy_aum`
and the execution cost caps of 1% on majors and 2% on mid-caps — but never connects them into a sizing
rule. The copyability engine cannot be built until one option is chosen, because the two options do
not measure the same thing.

**Blocked by:** None — can start immediately.

**Status:** resolved 2026-07-31 — size each order to the execution cost cap

- [ ] Both candidates are written out precisely:
      **(a)** 2% of `strategy_aum` as a fixed simulation assumption, explicitly labelled a capacity
      probe rather than a portfolio weight;
      **(b)** the largest order that stays within the execution cost cap (1% majors, 2% mid-cap),
      bounded by `strategy_aum`.
- [ ] The record states plainly that these are different measurements — "what a 2% position would have
      returned" versus "what the largest economically executable position would have returned" — and
      that both are defensible.
- [ ] The consequences of each are recorded for: the five capital levels, Copy Retention and its 2pp
      display floor, the unexecutable trade share, and what Gate 2 then means at $1.5M and $2M.
- [ ] Exactly one is selected. If the other is retained at all, it is retained as a reported
      diagnostic that cannot change a gate.
- [ ] The chosen rule is expressed as a formula an implementer can encode without further
      interpretation, including its behaviour when the cost cap admits no viable size at all.
- [ ] The decision is dated before any measurement result exists, is signed by the Research Owner, and
      is staged for inclusion in the pre-registration.

---

**Resolution (2026-07-31, Research Owner):** Each simulated order is the largest amount whose total execution cost stays within the cap (1% majors, 2% mid-cap), bounded by strategy_aum at each of the five levels. This changes the metric from 'what a fixed 2% position returned' to 'what the largest economically executable position returned'. Merged into pre-registration v1.1 §4.5.
