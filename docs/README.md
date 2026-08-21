# Start here

**Project:** Smart Wallet Copy Trading & Portfolio Intelligence System
**Status:** `DESIGNED — NOT READY FOR EXECUTION`

---

## Read this paragraph before anything else

The build cannot start yet, and that is by design, not by oversight.

This project rests on one empirical claim: *wallets that traded well in the past will trade well in
the future, and you can profitably copy them.* Published work says the first half is true and **the
second half is false for four of the five selection methods ever tested**. So the first thing built
is not the product. It is a 10–12 week historical experiment whose job is to **kill the project
cheaply** if the evidence is not there.

That experiment is pre-registered: every threshold is fixed in writing before any measurement runs,
and none of them may change after a result is seen. Most of the discipline in these documents exists
to protect that one property.

The three open design conflicts were resolved on 2026-07-31 and merged into the pre-registration
(now v1.1). What blocks the experiment now is not a decision — it is four preconditions, none of
which is technical. See §"What unblocks everything" below.

---

## What to read, in order

| # | Document | Why | Time |
|---|---|---|---|
| 1 | [`project-overview.fa.md`](./project-overview.fa.md) | The whole project in one pass — what, why, how, plan. **Persian.** Start here if you want the shape before the detail. | 30 min |
| 2 | [`prd.md`](./prd.md) | The PRD. 129 user stories, implementation decisions, testing strategy, scope. What you are being asked to build. | 1–2 h |
| 3 | [`phase-0-preregistration.md`](./phase-0-preregistration.md) | **The core document.** The frozen experimental protocol: metric definitions, gate conditions, null distributions, the validation gate, the invalidation rules. Everything else defers to this. | 2–3 h |
| 4 | [`decision-engine-addendum.md`](./decision-engine-addendum.md) | Governance module, `strategy_aum` vs `user_capital`, the two deployment models, wallet health lifecycle. **§14 holds the three open conflicts.** | 45 min |
| 5 | [`tickets/README.md`](./tickets/README.md) | The 44-ticket breakdown with blocking edges. Your actual work queue. | 30 min |
| 6 | [`build-status.md`](./build-status.md) | **What is actually built versus what the tickets claim.** Read before assuming a ticket is done — the modules exist, the vertical slices do not. | 10 min |
| — | [`specification-v1.md`](./specification-v1.md) | The original specification, frozen and unamended. Read only to understand *why* things changed. | reference |
| — | [`spec-amendments.md`](./spec-amendments.md) | The 15 amendments (A1–A15) against v1. Read alongside v1. | reference |

Persian translations exist for the pre-registration and the amendments
(`*.fa.md`). The numbers and code blocks in them are byte-identical to the English.

**If you read only one thing:** the pre-registration. If you read only one section of it: §7 (gate
conditions) and §9 (validation gate).

---

## The shape of the work

```
PRECONDITIONS          01 Builder · 02 Validator · 03 Budget · 04 Capacity
                                        ↓
OPEN DECISIONS         08 matching · 09 edge-origin threshold · 10 follower sizing
                                        ↓
FREEZE                 11 pre-registration and parameters locked
                                        ↓
TESTS FIRST            14→17 golden set (hand-traced, frozen)   18 known-answer battery
                                        ↓
TRACER BULLET          19 one wallet, one window, one buy, matching a hand-computed answer
                                        ↓
PIPELINE               20 attribution → 21 netting → 22 FIFO → 23 marking → 24 buy_quality
                                        ↓
UNIVERSE               25 candidates → 26 Step 0 → 27 freeze at T0 → 28 select
                                        ↓
MEASUREMENT            29 benchmarks · 30 depth · 31 follower-adjusted · 32 edge origin · 33 gate
                                        ↓
VALIDATION             35 reconciliation → 36 independent → 37 external → 38 gate summary
                                        ↓
FREEZE                 39 code and data frozen
                                        ↓
STATISTICS             40 null (1,000×) → 41 calibrate → 42 MAIN TEST, ONCE → 43 decision record
```

Two properties of this ordering are load-bearing and must not be "optimised":

- **Tests are frozen before the pipeline exists.** Tickets 17 and 18 block 19. You write the expected
  answers by hand, freeze them, and only then write code that has to match.
- **The null distribution runs after the code freeze, and the main test runs exactly once.** A bug
  found after the freeze invalidates the entire run — you fix it, re-run the whole validation gate,
  rebuild the null from scratch, and re-run the main test. You may not patch and you may not choose
  between the old and new result.

---

## What unblocks everything

**Not a decision any more — four preconditions**, none of which is technical:

```
01  Primary Builder assigned          not assigned
02  Independent Validator assigned    not assigned
03  Data budget approved              not approved
04  10–12 week capacity reserved      not reserved
```

Ticket 11 (freeze the pre-registration) waits on these, and everything from 14 onward waits on the
freeze. The governance module already refuses every stage until they are recorded:

```
REFUSED: Phase 0 status is DESIGNED, NOT READY FOR EXECUTION.
Unmet precondition(s): Primary Builder assigned (ticket 01), ...
```

**Ticket 02 deserves emphasis.** The Independent Validator is not a reviewer who arrives at the end.
Their work (14→17, then 36→38) sits directly on the critical path — the golden set they build blocks
the tracer bullet. Bringing them in during week nine to sign a report is not independent validation,
and the pre-registration blocks the main test without it:

```
Validation Status:   NOT INDEPENDENT
Main Test Execution: BLOCKED
```

### Resolved, for the record

| # | Conflict | Resolution |
|---|---|---|
| 08 | matching design vs null construction | matched pairs primary; null permutes labels **within** matched sets |
| 09 | Edge Origin threshold after long-tail exclusion | 40% kept, recorded as a backstop rather than the primary defence |
| 10 | follower order sizing | sized to the execution cost cap (1% majors, 2% mid-cap), bounded by `strategy_aum` |

Reasoning in [`decision-engine-addendum.md`](./decision-engine-addendum.md) §14; merged into
[`phase-0-preregistration.md`](./phase-0-preregistration.md) §4.5, §6.6, §7.1, §8.2.

---

## What you can start today

These have no blockers:

```
01  Assign and record the Primary Builder
02  Assign and record the Independent Validator      ← on the critical path, not beside it
03  Approve the data budget and provision vendor access
04  Reserve 10–12 weeks of capacity, record the Phase 0 Lite refusal

07  Commit the original specification            ✅ done
08  Resolve conflict — matching versus null      ✅ done
09  Resolve conflict — Edge Origin threshold     ✅ done
10  Resolve conflict — follower order sizing     ✅ done
```

Then `05` (start gate) opens once 01–04 are recorded, and `12`/`13` (first data pull, raw-chain
reader) open after that.

The measurement core is already built ahead of them — see [`build-status.md`](./build-status.md) for
what exists versus what the tickets actually require.

---

## The four preconditions

Phase 0 formally starts only when all four are true:

```
Primary Builder assigned
Independent Validator assigned
Data budget approved
10–12 week capacity reserved
```

**Budget:** roughly $478/month — Dune Plus $349 + CoinGecko Onchain Analyst $129, plus free Binance
klines. Under $1,000 for the whole of Phase 0. The expense is engineering time, not data.

**Skills required of the Builder:** advanced SQL on Dune and Spellbook models; Python for simulation
and statistical testing; EVM internals — event logs, traces, balance deltas; DEX pools and
concentrated liquidity; FIFO and position accounting; backtest design without look-ahead bias;
bootstrap and null-distribution testing; reproducible versioned pipelines.

---

## How to work the tickets

Work the **frontier** — any ticket whose blockers are all complete. For the long serial stretch
(19→28) that means strictly top to bottom.

Per ticket, the sequence is:

```
read the ticket and the pre-registration section it implements
  → /tdd at the pre-agreed seam
  → implement
  → /code-review
  → commit
```

Do not batch tickets. Each is sized for one fresh agent context, and the acceptance criteria are the
contract.

**Where parallelism is right:** independent research questions, per-account golden-set tracing (14–16
across many accounts), and the two validation paths (Builder and Validator working the same accounts
from different implementations).

**Where parallelism is wrong:** anything touching the frozen protocol, the single main-test
execution, or the null distribution. Those are sequential by construction, and running them
concurrently is how a pre-registered experiment quietly stops being one.

---

## Two things that are true and inconvenient

**The critical path is nearly serial.** Twenty-seven of the 44 tickets sit on it. At 10 weeks that is
roughly two to three days per ticket, with no slack. The second person's value is mostly in the
golden set and validation, which are *on* the path rather than beside it — so a second pair of hands
does not straightforwardly halve the calendar.

**The most likely failure mode is no longer "the hypothesis was wrong."** It is "the Builder and the
Validator were never found." Both profiles are scarce, and the design blocks itself without them.
That is a better failure than starting badly, but it should be planned for rather than discovered.

---

## Related

- [`tickets/`](./tickets/) — 44 tickets, one file each, numbered in dependency order
- [`orchestration-guide.md`](./orchestration-guide.md) — how to actually run this with agents: VSO role
  mapping, structural enforcement of validator independence, the freeze/invalidation protocol,
  skill-to-ticket map, when to fan out, session handoff, and a worked example
- [`../executive-multi-agent-model/`](../executive-multi-agent-model/) — the VSO framework itself
- [`../.claude/skills/`](../.claude/skills/) — 41 skills; the ones used here are `tdd`, `implement`,
  `code-review`, `research`, `diagnosing-bugs`, `domain-modeling`, `handoff`
