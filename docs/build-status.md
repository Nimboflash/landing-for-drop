# Build status

**As of:** 2026-08-16 · **Suite:** 3602 passing, 59 skipped on `main` · **Mutations:** 119
**Project status:** unchanged — `DESIGNED, NOT READY FOR EXECUTION`

This file exists because the ticket list and the repository drift apart, and that gap is how someone
six weeks from now assumes a ticket is done when only its *logic* exists. The tickets describe
**tracer-bullet vertical slices** — "one wallet, one window, end to end, matching a hand-computed
answer". What has been built is the **computational core those slices need**, which is a different
thing and a smaller claim.

**Nothing here has touched real chain data.** Every number in the suite is hand-computed or
constructed.

---

## The distinction that governs everything below

```
the machine       the instrument Phase 0 will run    largely built, under repair
Phase 0 itself    the experiment                     never started, cannot start
```

The four preconditions are the whole blocker and none of them is technical:

```
01  Primary Builder assigned          not assigned
02  Independent Validator assigned    not assigned
03  Data budget approved              not approved  (~$478/month)
04  10-12 week capacity reserved      not reserved
```

`phase0 status` prints this and refuses every stage. That refusal is the feature.

---

## What is genuinely complete

| Ticket | State | Note |
|---|---|---|
| 06 — governance state machine | **done** | 57 out-of-order transitions refused; the matrix is generated from the state order, so coverage is complete by construction |
| 07 — commit the original specification | **done** | `specification-v1.md`, frozen unamended |
| 08 — matching vs null conflict | **resolved** | matched pairs + within-set permutation |
| 09 — Edge Origin threshold | **resolved** | 40% kept, demoted to backstop, recorded |
| 10 — follower order sizing | **resolved** | sized to the execution cost cap |
| 19 — tracer bullet | **done** | one real wallet, one real window, one real buy, hand-checked against Blockscout field by field. `buy_quality_30d` = 0.38208584367631280809404165321516640020. Reproducible with no network: `PYTHONPATH=src .venv/bin/python -m tools.tracer_bullet` |
| 02 — validator register | **infrastructure done, unassigned** | the record, the four binding independence constraints and the three reachable statuses exist and refuse correctly. Nobody is named — that is the project owner's decision and no code path can produce one. **Direction settled 2026-08-16: an AI validator, capped at `MACHINE-INDEPENDENT`**, which makes the §9.5 external review the only thing that narrows the shared prior. A quote is being sought; `quoted_usd` is still `None`, meaning nobody has one — not `$0` |
| 18 — known-answer battery | **done, audited** | sixteen cases, exact comparison with no tolerance, no waiver path, and a gate condition verified to fail both on 15/16 *and* on a battery that crashed and published nothing. Unblocked by ticket 11 and the ticket did not say so. Criterion 7 closed by `.github/workflows/suite.yml` — the repo's first CI — pinned in turn by `tests/test_standing_regression_suite.py`, because a workflow file is one `git rm` from not existing. A stronger run-ordering version was built and reverted; see the ticket |
| 11 — freeze the pre-registration | **done** | 53 parameters, each quoted to its section. **Frozen by Nimbo at `4bbae13` on 2026-08-16.** An attempt to move the 15pp mean threshold to 0.10 was refused as audit entry #2 naming the requester; the chain verifies over all three entries. Every stage that has a threshold reads it from the table |

**Ticket 11's blockers (06, 07, 08, 09, 10) had all been satisfied for weeks and nobody noticed.** It
mattered because its own text says the freeze must happen *before* the golden set is hand-traced —
the golden answers depend on the frozen definitions of FIFO, marking, dead pools and token age, so
ticket 14 was waiting on something that had been unblocked the whole time. It is now frozen, which
removes that blocker. Ticket 14 still has three others — 12 (the data pull), 13 (the raw-chain
reader) and 02 (the validator leads the work) — so the freeze shortened the chain rather than
ending it.

**What the freeze does and does not change.** The parameters are closed and every write to them is
refused. Nothing has been measured — the numbers were fixed before any result existed, which is the
only reason fixing them was worth doing. `phase0 status` still refuses every stage on preconditions
01–04.

What the third criterion caught, recorded because the near-miss is the useful part. The rule is
"no stage carries its own version of a threshold", and the first pass migrated 25 constants and
listed the ones it could not migrate — but missed two: `phase0/seeds.py` held
`MASTER_SEED_BYTES = 32` and `FIELD_SEPARATOR = "|"` while the frozen set restated both as
literals, in the same block where `seeds.derivation_rule` was deliberately read from
`RunRecord.SEED_RULE` rather than retyped. Both copies agreed, so the whole suite passed. Setting
the frozen width to 48 left `new_master_seed` minting 32 bytes and nothing said so. The inventory
is now derived from the tree instead of written by hand: a sweep walks every module-level
assignment in `src/` and fails on any literal equal to a frozen value that is named in none of the
four lists. Two §-cited values were also absent from the table entirely — §10's activity bands,
which two packages held their own copies of (`universe/protocol.py` said so in its own comment:
"a known drift surface rather than presented as a design"), and §9.5's 10–15 externally reviewed
complex accounts.

**The first freeze performed against this repository was recorded by nobody, and that is worth
writing down.** Following the instructions above, the placeholder in `--requester "<نام شما>"` was
never replaced, and the register accepted it: the pre-registration read `FROZEN`, by `<نام شما>`, at
a real commit, on a real date. The `NON_NAMES` tripwire is entirely English and had nothing to say
about Persian — and its own docstring had already conceded the point, having been written without
`todo` and accepted it for a day. Two leaks is enough evidence that a list of spellings was never
the mechanism.

So the rule is now a shape rather than a vocabulary: a requester wrapped in any of nine bracket
pairs is refused without the contents being read in any language, and both registers share the
predicate rather than the word list. A real name in a non-Latin script still passes — a guard that
had closed the hole by rejecting what it could not read would have made the register unusable by
most of the people who might sign it. Mutation 113 narrows the bracket table back to the single pair
that appeared in the incident, which is the shape an over-fitted fix would take.

The limitation is unchanged and is not closed by this: any name-shaped string is accepted, in any
script. What bounds the deliberate case is the hash-chained audit entry the name is written into.

## What exists as code but cannot close its ticket

| Ticket | Code | Blocked on |
|---|---|---|
| 05 — run skeleton and start gate | `phase0/` 3,254 loc | tickets 01–04. The CLI correctly refuses every stage; recording a precondition needs a real name to record |
| 20 — attribution | `attribution/` 990 | ticket 19 |
| 21 — netting | `netting/` 604 | **audited: 1 met, 8 partial.** The orphaned reconciliation queue (criterion 7) is closed — a residual now reaches the queue with volume and age, guarded by an invariant. Mutations 118-119 |
| 22 — FIFO | `fifo/` 475 | **audited: 3 met, 3 partial, 1 not met.** No realized/open status field; one frozen answer cannot fail |
| 23 — marking | `marking/` 884 | **audited: 4 met, 5 partial.** The §9.1 conjunction is evaluated on a later pool than §4.4 asks for |
| 24 — buy quality and age buckets | `scoring/` 876 | **audited: 7 met, 1 partial, 1 not met.** The strongest of the four; the 5pp guard held under deliberate attack |
| 29 — activity-matched benchmark | `matching_null/` 1,628 | ticket 19 |
| 30 — depth and copier penalty | `depth/` 1,585 | ticket 19 |
| 33 — gate evaluation | `gate_validation/` 2,208 | ticket 19 |
| 34 — diagnostics pack | `reporting/` 2,781 | ticket 19 |
| 25–28 — universe, Step 0, freeze, selection | `universe/` 8,798 | ticket 12. Merged at `d62aaad`; see below |

## `phase0 decisions` — the queue, and why it is a queue

Asked on 2026-08-16 to build a machine that makes the human approvals and moves forward. The motive
was right and the literal form would void the experiment, so what exists is the half that helps.

**Why there is no auto-approver.** The pre-registration's worth is a claim about time and
attribution: a *person* fixed these numbers before any result existed and can be asked about it. A
script writing a name into a `FreezeRecord` produces an audit entry naming nobody — the chain still
verifies, the status still reads `FROZEN`, and the one question the record exists to answer now has
no answer, while looking answered. That is not hypothetical here: the first freeze against this
repository went through as `<نام شما>`, and closing it took replacing a vocabulary with a shape. An
auto-approver is that hole reintroduced on purpose. Three of the six acts also commit resources this
machine does not own — a monthly budget, a review fee, and ten to twelve weeks of somebody's
calendar.

**What was built instead.** `phase0 decisions` lists every outstanding human act with what it
blocks, what the decider must supply that the machine cannot, what is already prepared, the exact
command, and — per act rather than as one blanket sentence — the specific thing that cannot be
delegated. The act stays human; the homework does not.

`phase0.decisions` has no write path, and that is enforced rather than promised:
`test_the_module_has_no_write_path` walks the committed source and fails on any call to the injected
registers outside a read allowlist. Its first version forbade `append` by name and fired on
`lines.append` — building a list of strings is not writing to an audit log — so the rule is keyed on
the *receiver*, and it is guard-the-guarded by planting the convenience that would turn the queue
into an approver.

## The arbiter certified two verdicts it did not derive — both now checked

**The most serious finding of the nine package audits, and it is not a bug — it is a boundary in the
wrong place.** `src/gate_validation/` decides GO / CONDITIONAL_REVIEW / STOP, and its import isolation
is real and enforced: an AST walk permits `contracts` and the standard library, nothing else. That
buys **import** independence and not **derivation** independence, and two of §7's conditions arrive
already decided by the lane being judged.

The package holds **no first-hour limit constant anywhere** — verified by grep. It reads
`edge_origin_status`, an enum computed by `src/scoring/edge.py`, and copies `first_hour_edge_share`
into the verdict without comparing it to anything, so a `VALID` score carrying a first-hour share of
**0.95 passes §7.1**. And `NullSummary.significant` compares against `percentile_95` and
`empirical_p` that are *fields* — the caller declares them; the arbiter holds `null_statistics` and
never recomputes the quantile, never recomputes p, never checks `n_runs` against §8.2's 1,000.

**Both are closed as of 2026-08-16, by two different shapes.** §7.1's is a *consistency* check — the
status and the share are compared to each other and an impossible pair is refused, deriving nothing,
because this module's docstring is right that an arbiter growing its own copy of the gate rule is the
failure it exists to prevent. §7.3's *does* derive: it recomputes the nearest-rank percentile and the
`+1`-corrected p-value from `null_statistics`, because those are genuine degrees of freedom pinned in
prose, and an arbiter that recomputes them from the documented rule is the only reader that can catch
the builder drifting off it. The gate rule itself stays in the seam; what is recomputed are its inputs.

**Closing §7.3 failed eight of this repository's own tests, and every one deserved to fail.** The
fixtures declared p-values their distributions cannot produce: three null runs — 0.10, 0.15, 0.20 —
declaring `empirical_p = 0.01`, when three runs cannot report below 1/(3+1) = 0.25. `p <= 0.05` was
arithmetically unreachable and the suite asserted it anyway. **§7.3's significance path had never been
exercised on data that could legitimately be significant.** All four fixtures now carry twenty runs,
the smallest that can honestly clear the gate, since the floor is 1/(n+1) and n ≥ 19.

This is the same shape as the reason `src/groundtruth/` was removed the same day: a reference built
out of the thing it checks agrees with it about whatever it got wrong. There the remedy was to delete;
here it is to derive. It also explains ticket 33's criterion 10 — thresholds unbound to the frozen
set — as a consequence of the lane rule rather than an oversight: `gate.first_hour_edge_share_max` is
frozen at 0.40 and the arbiter has **no counterpart to hold equal**.

What did hold: the identity-key defect class is closed at both keyed sites, each refusing on the
collision rather than on the values disagreeing, with published-outcome proofs. That was the defect
that flipped a §7 outcome between GO and CONDITIONAL_REVIEW on dict iteration order, and the audit
was asked to check the class rather than the instance.

## What the nine package audits found

Nine packages, 77 criteria, ~15,000 lines already running on real Ethereum data. Full findings are on
each ticket. Tally: **34 met, 33 partial, 8 not met, 2 blocked on the golden set.**

**The theme, in five packages: computed and then not published.** Attribution's coverage gap and
fallback rate; netting's reconciliation queue, whose `reconciliation_queue`, `QUEUED_STATUSES` and
`ABOVE_TOLERANCE_RESIDUAL` **had** zero callers outside `src/netting/` — **now closed**: `pipeline.run` routes every residual to the queue with its priced volume and block-number age, on a distinct `Stage.RECONCILIATION`, guarded by an invariant that refuses a run where the counts disagree (mutations 118-119). §6.6's
balance table — `unique_controls`, `control_reuse_rate`, `effective_sample_size`,
`unmatched_selected` — serialized by nothing; depth's `s1_at_trade` and `pool_depth_at_trade`, dropped
by the only record the pipeline emits; and four of the diagnostics pack's standing metrics with no
field in any report type. `RunReport` can carry none of them. Downstream, a value computed and not
published is indistinguishable from a value nobody measured.

**Docstring claims standing in for enforcement, twice.** Ticket 30's criterion 6 — "the follower
enters at the first full block after the leader, using no future information" — is asserted nowhere
in code or tests, over an interface accepting an arbitrary `PoolState`; there is no block arithmetic
in `src/depth/` at all. The copier penalty is entirely determined by which block's state is handed
in, so the one input that decides the headline result is the one input nothing checks, and this path
sits outside the five-layer post-T0 barrier built for exactly that class. Ticket 29's structural
exclusion of robustness controls from the gate holds by construction and is pinned by no test —
extending the benchmark group with them breaks nothing.

**Things that held under deliberate attack.** Ticket 24's 5pp small-denominator guard: evaluated
before the share, `None` ↔ `INDETERMINATE` enforced in two modules, `passes` requiring `VALID` alone,
a property test rejecting `INDETERMINATE` at every threshold including −1,000,000, serialising as
`null` and never `"0"`. Ticket 30's cost caps: no `LONG_TAIL` key exists and a missing cap raises, so
addendum §9.5's "no long-tail trade" is said by absence. A10.4's 5–23× band is reported and never
applied as a multiplier. §10's activity bands tile the eligible range with no gap.

**One gap closed while auditing.** Both `fills` properties read `fill_ratio >= MIN_FILL_RATIO`, and
every case sat well inside the band — so flipping `>=` to `>` survived the entire suite. Addendum
§9.4 says *at least* 90%; the failure direction discards a copyable trade. Now pinned at exactly 0.90
on both types.

## What the first four package audits found

Tickets 21–24 were audited on 2026-08-16 against their own acceptance criteria — 34 criteria over
~2,900 lines that already run on real Ethereum data. The full findings are on each ticket. Three
things are worth reading here.

**The theme is closed at the publication end.** `reporting.DataIntegrity` is now a required block on
`RunReport` carrying §10's four standing figures — the decoder coverage gap, the attribution fallback
rate, the unexplained reconciliation difference and the reconciliation-queue volume — and it survives
into the hashed artifact. **`None` means not measured and never zero**, which is the whole design: a
run reporting `0` claims somebody looked and found nothing missing, a run reporting `None` says
nobody looked, and `NOT_MEASURED` gives the reason for each. `unmeasured` names *which* figures are
absent rather than how many, because which is what decides whether the headline number can be read.

Every run in this tree reports four `None`s today, which is the true statement about it. What remains
per package is the wiring — computing each figure into the block at the composition root — rather than
the block being unable to hold it. Adding it moved the canonical payload hash, which is the **second**
shape change under one `report-v1` stamp; both are now recorded in `reporting/run.py`'s own note and
in the re-measured tripwire literal, so the next seam unfreeze has two reasons to bump the version.

**One theme, three instances: computed and then not published.** Attribution's coverage gap and
fallback rate are computed and `RunReport` has no field for either. Netting's reconciliation queue is
computed and `reconciliation_queue`, `QUEUED_STATUSES` and `ABOVE_TOLERANCE_RESIDUAL` have **zero
callers anywhere in `src/` outside `src/netting/`** — so an addendum §8 residual is excluded from the
primary metric and then appears in no queue record, no total and no report. `QuarantineRecord`'s own
docstring claims to be the thing netting routes to, and nothing routes. Downstream, a value computed
and not published is indistinguishable from a value nobody measured, which is the failure mode this
project treats as worse than a wrong number.

**A frozen answer that cannot fail.** `FifoResult.unmatched_sell_raw` is written by no code path and
asserted `== {}` in four places, two of them frozen known-answer cases where the battery calls it "the
check that the buy and the sell agree about how many tokens ever existed". The oversell quarantine took
over its job and the field was left behind. It is the same class as the `token_imbalance()` method
removed from `groundtruth` the same morning, and it was deliberately **not** fixed: two readers are
frozen battery cases, so removing the key moves `known_answer_fixture_hash` and the §9.6 manifest pin
with it. Re-freezing is cheap while nothing has been measured, and is not a thing to do quietly.

**The marking horizon, which is disclosed and now fully disclosed.** The realized/open split uses each
buy's own day 30; the mark uses the run horizon. That is a declared modelling choice forced by the seam
supplying one `PoolState` per pool, published per buy as `horizon_lag_seconds`. What the disclosure did
not say is that §9.1's dead-pool conjunction is evaluated on the same later pool — so a venue exitable
at day 30 that drained afterwards zeroes the position outright. Not a drift in a price: the difference
between a holding and a total loss, in one direction only, since a pool cannot un-quiet. `run.py` now
says so.

**And one thing that held.** Ticket 24's 5pp small-denominator guard was attacked deliberately, because
an unmeasurable window carrying a share of zero would pass the ≤40% Edge Origin test. The guard is
evaluated before the share, the `None` ↔ `INDETERMINATE` pairing is enforced in two modules rather than
one, `passes` requires `VALID` alone, a property test rejects `INDETERMINATE` at every threshold
including −1,000,000, and it serialises as `null` rather than `"0"`.

Tickets 20, 29, 30, 33 and 34 — 43 further criteria — are not yet audited.

## The universe merge, and what it did and did not close

`src/universe/` is **on `main`**, merged at `d62aaad`. The history, because the merge is only
trustworthy in the light of it:

- an audit of the original post-T0 barrier returned **FAIL on 7 of 8 criteria** — 147 function
  definitions with zero type annotations, so every signature accepted both the selection and the
  forward family (`docs/reviews/post-t0-barrier-audit.json`);
- the barrier was rebuilt as five layers — `provenance`, `snapshot`, `artifact`, `ordering`,
  `containment` — and then **attacked rather than admired**: eighteen breaches were found and closed
  at `72beaab`, two more named holes at `29aae38`;
- the structural half is `tests/test_post_t0_barrier.py` (ten rules over committed code) and
  `tests/test_signature_barrier.py` (six rules banning `Any`, `object`, bare parameters and generic
  containers on a selection path).

What that does **not** close is ticket 12. Nothing in this repository has touched real chain data, so
there is no measured universe: `step0.universe` is wired to `pipeline/stages/step0.py` and composes
`measure_window` over the design's four windows, and called with no observations it refuses, naming
ticket 12 and the archival node ticket 03 is waiting on. Ticket 26's other criteria — the four-window
report, the five distributions, the `INSUFFICIENT CANDIDATE UNIVERSE` status, the pre-registered
replacement rule, the §13.7 base-rate comparison — are code that runs on constructed inputs only.

One of ticket 26's criteria is **not** met by any code on `main`: "Step 0 completion is recorded as a
governance precondition for ranking". `phase0.execution.STAGE_AUTHORITY` cannot express it — there is
no ranking stage among the thirteen, and `step0.universe` advances no governance state a later stage
could require. What exists is `universe.freeze.require_step0_complete`, a *call* that
`rank_and_select` does not make, pinned in `tests/integration/test_universe.py` and nowhere else.

**The wiring was then attacked in the same way the barrier was, and five things gave.** Four guards
the wiring added were deletable with the suite still green — the sort that puts the four windows in
the design's order, the three materialisations that stop a lazily-supplied window measuring a
different population on the re-run, `_require_stage` inside the Step 0 runner, and the pairing of the
`==` the runner checks the dataset snapshot with against the `str()` the report publishes it through.
All four are now pinned, and the last of them was a real instance of the identity-key class rather
than an unpinned guard: it is fixed in `pipeline/stages/step0.py` by doing the transformation once,
before the check.

The fifth was **§6.1's floor itself**, and it had never been pinned in either direction: changing
`<` to `<=` in `Step0Measurement.status` left the whole suite green, because every fixture universe
in this repository is a handful of accounts and both comparisons agree on all of them. Ticket 26 and
§6.1 both say *below* 10,000, so a window sitting exactly on the floor is `SUFFICIENT`; the code was
right and nothing held it there. Pinned now in `tests/hand_computed/test_universe.py` and by mutation
105. The end-to-end path was also walked by hand at 9,999 / 10,000 / 10,001 eligible accounts through
`execute_stage`: all three complete, all three are carried, and a mixed sufficient/insufficient report
is `permits_ranking = False` without any window crashing. It is not in the suite because measuring a
genuine 10,000-account window costs 11.5s and the slowest test here is 6.5s.

## Real data, and what it cost to get there

`tools/case_runs.py` drives four real Ethereum wallet populations through `run_wallet_window`. Every
number below came out of running it, not out of reading the code, and each one took a working
assumption with it.

```
population        548 transactions in, census conserved on all four cases
undecodable        34, dominated by NativeSettlementUnknown
§4.7 starts        28 of 30 derived, 2 refused
pools              16 of 16 read at the horizon, 0 refused
positions marked   39, across four valuation bases
```

- **§4.7 token starts** were the largest loss in the machine — 82 buys quarantined for a date the
  chain already held. The obvious derivation (scan the factories for `PairCreated`) needs
  `eth_getLogs` over seven million blocks, and every free endpoint caps the range at ten or fifty:
  about 700,000 requests, so not slow but *unavailable*. Computing the pool address by CREATE2 and
  binary-searching `eth_getCode` costs ~24 calls instead. `pipeline/keccak.py` is verified against
  all twelve topic constants in `ingest/events.py` before it is trusted for anything.
- **§9.1 met real pools for the first time** and produced four bases rather than one:
  `LIQUIDITY_BOUND/LIVE`, `LIQUIDITY_BOUND/THIN`, `DEAD_ZEROED/DEAD`, `POOL_MARKED/LIVE`. The dead
  ones are not borderline — 54 and 48 days of inactivity against a 30-day condition, in pools
  holding one wei of WETH.
- **The A10.4 TVL-understatement band was confirmed against a real pool**: 13.35× measured on
  Uniswap v3 USDC/WETH, inside the pre-registered 5–23× band.

## The limit every remaining data gap has the same shape as

Free endpoints serve receipts, historical logs and archive state. They refuse `trace_transaction`
and `debug_traceTransaction` — every one tried, without exception. Everything still unmeasured here
is downstream of that:

- an **internal transfer** to a wallet inside another transaction in the same block moves its
  balance and appears in no top-level field, so `ingest/blockscan.py` establishes "no top-level
  transaction and no protocol credit touched this wallet", which is narrower than "nothing did";
- `last_swap_block` on a v2 pool is `blockTimestampLast`, the last *reserve change* rather than the
  last swap. Usable only because the error is one-directional — it can read a dead pool as live,
  never a live pool as dead, and the second would publish −100% on a healthy position. The exact
  reading is a 30-day `Swap` scan: ~21,600 requests per pool at a ten-block cap;
- a **Uniswap v3 pool is refused rather than read**, because `slot0()` reports a price and a tick,
  not a time, and defaulting `last_swap_block` to the horizon would assert perfect freshness about
  a pool nobody looked at — §9.1's first condition would then never fire on a v3 venue.

None of these is hidden behind a plausible number. Each is a refusal that names itself.

## The validator lane, and the thing that was built and taken back out

`groundtruth/` — tickets 13 and 36. **Not in the tree, and that is a decision rather than a gap.**

The warning here has always been *do not build it early to get ahead*:

> The validation gate's entire worth rests on the validator having derived its expected outputs
> independently. If both lanes come from the same context they share its misunderstanding, and a
> shared bug is invisible to the comparison — both sides compute the same wrong answer and agree.
> Building it early also *anchors* whoever is eventually assigned to ticket 02.
> `tests/test_lane_independence.py` enforces the import boundary; it cannot enforce independence of
> mind.

**On 2026-08-16 ticket 13's reader was built anyway, and removed the same day.** The argument for
building it was narrow and, on its own terms, correct: decoding an ERC-20 `Transfer` log has one
right answer fixed by a public standard, so a reader contains no *judgement* to anchor on — unlike
FIFO versus LIFO, or when a pool counts as dead, which are choices and which `groundtruth`
deliberately never touched.

What ended it was ticket 02 settling on an **AI validator**. `MACHINE-INDEPENDENT` already concedes
that two agents from the same base model make correlated errors; handing one of them a reference the
other wrote is that concession at its sharpest. A gate whose reference and whose subject came from
the same hand certifies nothing, and it certifies nothing *invisibly*, which is the only reason the
trade-off is worth 450 lines.

**What the removal buys is less than it looks, and saying so is the point.** The code is at
`7644955` and `ingest/events.py` decodes the same logs and is staying. This is a protocol
constraint, not an enforced one — the same class as "reasoning before comparison", which ticket 02's
own ledger already lists under *not achieved*. It removes the path of least resistance and puts the
intent on the record. Whoever builds ticket 13 must not consult either, and must say so in the
validation report if they do: a declared dependency can be discounted, an undeclared one cannot.

**Two findings from that build survive it**, because they are facts about the *builder* lane:

1. `ingest.events.decode_logs` refuses an entire receipt on one unknown event signature — on
   `0x8f7c6ce3…`, over a Uniswap V2 `Mint`. That is its no-silent-skip rule working as documented,
   and it means the builder lane currently reads nothing at all from that transaction.
2. A fee-on-transfer token cannot be detected from logs alone: it emits the after-fee transfer plus
   a separate fee transfer, both balanced, and the intended amount appears in no log. **Ticket 14's
   coverage matrix requires such a case, so it has to be sought out deliberately** — sampling will
   not surface one, and a cell filled by sampling would hold a token nobody verified takes a fee.

---

## Architecture as built

```
src/
  contracts/        SHARED   1,310  the frozen seam — types, enums, errors, numeric policy,
                                    canonical serialization. No substantive calculation, enforced
                                    by an inventory check plus an AST check on derived fields.
  phase0/           SHARED   3,254  governance, preconditions, run records, seeds, audit log,
                                    the validator register, and the not-real-snapshot rule
  transport/        SHARED   1,415  raw RPC over three free endpoints, failover, recording cache.
                                    Shared because it interprets nothing — raw bytes only
  gate_validation/  SHARED   2,208  the arbiter — may not import what it judges

  attribution/      BUILDER    990  tx_sender vs portfolio_owner, account typing
  netting/          BUILDER    604  transaction-level balance netting
  fifo/             BUILDER    475  lot matching across partial sells
  ingest/           BUILDER  1,888  logs to Transfer; the settlement identity and its precondition
  marking/          BUILDER    884  pool marks, liquidity bound, dead pools, token age
  scoring/          BUILDER    876  buy_quality, Edge Origin
  depth/            BUILDER  1,585  copier penalty, virtual reserves, order sizing
  matching_null/    BUILDER  1,628  matched sets, permutation null
  pipeline/         BUILDER  6,533  the composition root, the thirteen stage runners, keccak,
                                    CREATE2 pool addresses, §4.7 token starts, pool reading
  reporting/        BUILDER  2,781  wallet/window/capital/churn aggregation, diagnostics
  universe/         BUILDER  8,798  candidate universe, Step 0, T0 freeze, ranking and selection,
                                    and the five-layer look-ahead containment system

  groundtruth/      VALIDATOR not in the tree. Built and removed 2026-08-16 (7644955); it must
                              be the validator's own work — see above

tools/                       outside the lane graph, deliberately — none of it is the instrument
  mockchain/                 a synthetic chain, marked SYNTHETIC- so it cannot pass for a run
  hyperliquid/               a second real venue, marked NOT-PREREGISTERED-
  provisioning/              the ticket-03 probe: what each source serves, proven or absent
  tracer_bullet.py           ticket 19, one wallet, replay-only
  case_runs.py               four real populations, replay-only
```

Lane independence is enforced statically: no builder↔validator import edge, and **no shared→lane
edge either**, so the arbiter cannot call the code it judges. Undeclared packages fail the suite
rather than defaulting to permissive.

Structural checks, all holding, with `ALLOWED` and `DEFERRED` empty:

```
test_lane_independence.py      the lane graph, including the shared->lane asymmetry
test_shared_purity.py          contracts holds no substantive calculation
test_frozen_context.py         no Decimal arithmetic outside the frozen context
test_quantization_boundary.py  quantization only at the output boundary
test_post_t0_barrier.py        no selection module reaches or names the post-T0 side
test_signature_barrier.py      no signature in src/universe/ silently accepts everything
```

---

## The defect class this repository keeps finding

> **An identity key that a boundary collapses silently**, so two distinct inputs become one entry and
> which one survives depends on iteration order.

| Round | Where | Outcome |
|---|---|---|
| 1 | duplicate `tx_hash` at the composition boundary | already closed |
| 2 (`2672eed`) | four asset-keyed mappings — pools, prices, token_starts, replacement_pools | closed |
| 3 (`e31dc22`) | **`gate_validation.CapitalFeasibility`** — flipped the published §7 gate outcome between GO and CONDITIONAL_REVIEW on caller iteration order alone | closed |

Round 2 believed it had closed the class and had not: the instance was fixed, five sites were fixed,
and two more were left open. Only an independent adversarial pass found the rest. **Assume the same
of round 3** until something independent says otherwise.

The rule that came out of it, and it is the most repeated mistake here: **refuse on the collision,
not on the values disagreeing.** A guard conditioned on disagreement closes the traced instance and
leaves the class open.

## Verified infrastructure gaps

Recorded so they are not rediscovered:

- **Traces require a paid endpoint; everything else does not.** This entry used to say an
  authenticated archival node was needed at all, and that was wrong — measured with an honest
  User-Agent, the free endpoints serve receipts, historical `eth_getLogs` and archive-height
  `eth_call`/`eth_getBalance`/`eth_getCode`. What they refuse, without exception, is
  `trace_transaction` and `debug_traceTransaction`.
- **Log ranges are capped hard.** blastapi: *"up to a 10 block range"*. nodies: *"maximum allowed
  is 50 blocks on your current plan"*. Any design that sweeps history with `eth_getLogs` is
  unavailable here, not merely slow — which is why pool addresses are computed rather than searched.
- **Do not send a fake browser User-Agent.** One probe did, and Cloudflare banned the signature at
  `eth.drpc.org` permanently: *"Your user-agent has been banned. Do not retry."* The honest agent
  is `phase0-ingest/1.0 (…)` and it is what every request sends now.
- **`eth_getBlockByNumber` with full transaction objects returns hundreds of kilobytes** for a 2023
  block, and the free endpoints time out on it often enough that a recording pass may need retrying.
- **The wrong-remote problem is resolved.** `origin` now points at
  `git@github.com:Nimboflash/wallet.git`. A local branch `claude/git-pull-setup-848c17` still holds
  a merge of the unrelated `financial-pannel-` history; it is on no remote and should be deleted.
