# Resume here

**Frozen:** 2026-08-02, mid-session, for a machine shutdown.
**Read this first, then `docs/README.md`.**

> **Since the freeze.** Branch `universe` was attacked, repaired and **merged** — `d62aaad` on
> `main`. Section 2 below is done, and is left standing as the record of what was asked for. The
> state table is the state *at the freeze*: history, not current. `docs/build-status.md` is current.

---

## Where the project is

**Phase 0 — `DESIGNED, NOT READY FOR EXECUTION`.** That has not changed and cannot change here.

The distinction that matters, and that the rest of this file assumes:

```
the machine       the instrument that Phase 0 will run    largely built, under repair
Phase 0 itself    the experiment                          never started, cannot start
```

Nothing in this repository has touched real chain data. Every number in the suite is hand-computed
or constructed. The four preconditions are the whole blocker and none of them is technical:

```
01  Primary Builder assigned          not assigned
02  Independent Validator assigned    not assigned
03  Data budget approved              not approved  (~$478/month)
04  10-12 week capacity reserved      not reserved
```

`phase0 status` prints this and refuses every stage. That refusal is the feature.

---

## State at the freeze

| | |
|---|---|
| Branch `main` | `e1a8b6e` — green, **1714 passed, 59 skipped** |
| Branch `universe` | `10ff98a` — green, **1817 passed, 59 skipped**, **not merged** |
| Remote | `git@github.com:Nimboflash/wallet.git` — corrected this session |
| Structural checks | four hold; `ALLOWED` and `DEFERRED` both empty |

Run the suite:

```bash
/Users/nimaalishahi/wallet/.venv/bin/python -m pytest -q
```

The worktree used for the `universe` branch was at
`…/scratchpad/wt-universe`. It is disposable — the branch has the work. If the
scratchpad is gone, `git worktree prune` then re-add wherever you like.

---

## The thread this session was pulling

One defect class, chased through three rounds:

> **An identity key that a boundary collapses silently**, so two distinct inputs become one entry
> and which one survives depends on iteration order.

| Round | Found | Verdict |
|---|---|---|
| 1 | duplicate `tx_hash` double-counts | already closed at the composition boundary |
| 2 (`2672eed`) | four asset-keyed mappings — pools, prices, token_starts, replacement_pools | closed |
| 3 (`e31dc22`) | **`gate_validation.CapitalFeasibility`** | closed |

Round 3 is the one to remember. Five verification lenses over `2672eed` produced 26 measured
findings, and the worst was inside the arbiter — the module that decides GO / CONDITIONAL_REVIEW /
STOP. `CapitalFeasibility` collapsed two caller keys onto one capital level, and **the published §7
gate outcome flipped between GO and CONDITIONAL_REVIEW on caller iteration order alone.**

A gate outcome that depends on dict ordering is not a decision.

The lesson, which is the reason this file spends a page on it: **round 2 believed it had closed the
class and had not.** The instance was fixed; the class was fixed at five sites and left open at two
more. Only an independent adversarial pass found the rest. Assume the same is true of round 3 until
something independent says otherwise.

Full evidence, all 26 findings with their constructed inputs and wrong-vs-right numbers:
[`docs/reviews/2672eed-five-lens-verification.json`](reviews/2672eed-five-lens-verification.json).

---

## Pick up here — in this order

### 1. Finish the confirm pass on `main` (small, and it is a real gap)

`e31dc22` was written by four agents editing one checkout in parallel. Each deletion-tested its own
repairs; **nobody has deletion-tested the merged tree.** The confirm agent was cut short by the
shutdown. What it was going to do:

- reproduce the `CapitalFeasibility` gate flip on the code as it now stands, with **at least three
  spellings**, and confirm the class is closed rather than the one input the lens used
- delete each claimed repair, run the suite, confirm RED, restore — any that stays green is an
  unpinned repair, and five of round 3's findings were exactly that
- re-read every docstring the four wrote, for new overclaims. `2672eed` removed three and introduced
  two. This round must not repeat that.

### 2. Attack the containment system on the `universe` branch — **done, and it was merged**

The four lenses ran. Eighteen breaches were found and closed (`72beaab`), two further named holes
after that (`29aae38`), and the branch was merged at `d62aaad`; `docs/build-status.md` carries the
result. What follows is the brief as it was written, kept because it is the record of what the
attack was asked to cover and the standard any future barrier work is held to.

The branch is green and the barrier is **built but untested**. An audit against eight pass criteria
returned **FAIL on seven**, and the rebuild that followed produced five layers:

```
provenance.py   PRE_T0 / POST_T0 / CONTAMINATED travelling WITH the value
snapshot.py     cutoff proven — max_block <= t0_block, evidence hashed
artifact.py     canonical sealing; pickle refused; provenance verified
ordering.py     mount pre-T0 → select → seal → unmount → mount forward → evaluate
containment.py  a breach invalidates the RUN, not one wallet
```

plus `tests/test_signature_barrier.py`, which bans `Any`, `object`, bare parameters and generic
containers (`Mapping[str, Decimal]`, `pd.Series`) on selection paths over committed code.

**Four adversarial lenses were specified and none of them ran** — three consecutive workflows died
on infrastructure. So what exists is a design that satisfies its own checks, which is exactly the
evidence this project treats as insufficient: the audit that produced these five layers found seven
failures in a design that *also* satisfied its own checks.

The full specification is in the workflow script at
`.../scratchpad/barrier-v2.js` — the invariant, the decisive question, the fifteen routes, the
binding outcome table and the eight criteria. The four lenses:

```
static      signature inventory, the type lattice, transitive import reachability,
            symbol origin through re-exports, shared field names
taint       numeric laundering FIRST (it reads no forward object, so poisoned
            descriptors cannot see it), then poisoned descriptors, computed getattr,
            sort keys, dataclasses.replace
isolation   is the snapshot physically truncated? can selection fetch forward data
            by asking? is the ordering gate on the hash or on existence? pickle?
tests       deletion-test every guard; route-by-route coverage of the fifteen;
            assertions that recompute the implementation; docstring claims
```

Binding, and the part most easily got wrong: `RAISED_LOOKAHEAD` is a pass **only** if the whole run
invalidates. `try: ... except LookAheadViolation: continue` is `SILENTLY_DROPPED` — the basket
composition changed on post-T0 information whether or not something was raised.

### 3. What is still unbuilt

`src/groundtruth/` — the VALIDATOR lane, tickets 13 and 36. Blocked on ticket 03 (credentials);
trace access needs an authenticated archival node, verified against three public endpoints.

> **This warning was tested on 2026-08-16 and held.** Ticket 13's reader was built anyway, on the
> argument that decoding an ERC-20 log has one right answer fixed by a public standard and so
> contains no judgement to anchor on. Then ticket 02 settled on an **AI validator**, and the
> argument stopped being sufficient: `MACHINE-INDEPENDENT` already concedes that two agents from
> the same base model make correlated errors. The reader is at `7644955` and is not in the tree.
> Removal is a protocol constraint and not an enforced one — the code is in history and
> `ingest/events.py` decodes the same logs — so whoever builds this must not consult either, and
> must say so in the validation report if they do. See `docs/tickets/13-…` for the two findings
> from that build that were worth keeping.

**Do not build it with an agent to "get ahead".** The validation gate's entire worth rests on the
validator having derived its expected outputs independently. If both lanes come from the same
context, they share its misunderstanding, and a shared bug is invisible to the comparison — both
sides compute the same wrong answer and agree. Building it early also *anchors* whoever is
eventually assigned to ticket 02. The lane split is enforced structurally by
`tests/test_lane_independence.py`, but that enforces the import boundary, not independence of mind.

---

## Loose ends

- **`claude/git-pull-setup-848c17`** — a local branch holding `e76f91c`, a merge of the unrelated
  `Nimboflash/financial-pannel-` history from when `origin` pointed at the wrong repository. On no
  remote, nothing depends on it. Delete it; its only remaining function is to let someone branch
  from it by accident and pull that history back in.
- ~~**`docs/build-status.md`** is stale — written at 393 tests~~. Brought current at `065b9f8` and
  again after the `universe` merge; it now records the suite at 2,400 and the remote as resolved.
- Persian translations exist for the pre-registration, the amendments and the project overview.
  Not translated: `decision-engine-addendum`, `specification-v1`, `orchestration-guide`,
  `docs/README`.

---

## House rules, so the next session does not have to rediscover them

- `src/contracts/` is the **frozen seam**. Types, enums, serialization, numeric policy. No
  substantive calculation, enforced by an inventory check plus an AST check on derived fields.
  **Do not edit it.**
- All Decimal arithmetic goes through `contracts.numeric` — `add`, `sub`, `mul`, `divide`, `calc` —
  inside the frozen context. Precision 38, ROUND_HALF_EVEN, quantization only at the output
  boundary. `calc()` rejects a float on sight.
- `ALLOWED` and `DEFERRED` in `tests/test_frozen_context.py` are empty and must stay empty. If the
  scan complains, fix the code — an exemption is a debt filed as a permission.
- No builder↔validator import edge, and **no shared→lane edge either**: the arbiter must not be able
  to call the code it judges. Leaf builder packages may not import siblings; `pipeline` is the only
  composition root.
- **Errors vs statuses.** A disappointing *measurement* is a carried status — a failed hypothesis is
  a valid result, not a software crash. A defect in *what assembled the call* raises, naming the
  rule, the input, and what it costs.
- **Refuse on the collision, not on the values disagreeing.** A guard conditioned on disagreement
  closes the traced instance and leaves the class open. This is the single most repeated mistake in
  this repository's history.
- **Docstrings must not overclaim.** Say what a thing guarantees *and what it does not*. Stating a
  residue honestly is acceptable; asserting it away is not.
- **Hand-computed tests pin literals.** Never write an assertion that recomputes the
  implementation's own expression — this repository has already shipped a defect that a test blessed
  exactly that way, and the test was the thing that had to be deleted.
- **A repair no test defends is not a repair.** Delete it, run the suite, see red, restore.
