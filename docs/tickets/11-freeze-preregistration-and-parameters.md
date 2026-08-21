# 11 — Freeze the pre-registration and the parameter set

**What to build:** The moment the experiment stops being editable. The pre-registration is finalised
at a named commit, every parameter it fixes is loaded into the governance module's authoritative
parameter set, and the state advances to `PARAMETERS_FROZEN` — after which every write to that set is
rejected. The demo is an attempted threshold edit that fails with an audit record. This must happen
before the golden set is hand-traced, because the golden answers depend on the frozen definitions of
FIFO, marking, dead pools, and token age.

**Blocked by:** 06, 07, 08, 09, 10

**Status:** done — frozen by Nimbo at commit `4bbae13` on 2026-08-16

The blockers (06, 07, 08, 09, 10) were all satisfied and nobody noticed for weeks. That mattered:
this ticket's own text says the freeze must happen *before* the golden set is hand-traced, so
ticket 14 was waiting on a ticket that had been unblocked the whole time — and so, transitively,
was the validator named by ticket 02.

The freeze was performed on 2026-08-16 and `phase0 parameters` now reads `FROZEN`, by Nimbo, at
commit `4bbae13`. `request-parameter-change` answers with `FrozenError` rather than the softer
pre-freeze refusal, and the difference is the whole point: the message no longer says "edit the
document and the module together", it says what proceeding costs under §9.7 — the run is
INVALIDATED, the validation gate is re-run, the null distribution is rebuilt from scratch, and
selectively using the old or the new result is prohibited.

**It took two attempts, and the first one is on the record.** The first freeze was performed with
the placeholder from this file's own instructions pasted unchanged — `--requester "<نام شما>"` —
and it was accepted, because every spelling in `NON_NAMES` is English. That state directory is
archived as `.phase0-void-2026-08-16` rather than deleted; a hash-chained audit log is not
something to erase quietly, and the near-miss is more useful kept than tidied away. The refusal is
now a shape rather than a vocabulary — see the note under the last criterion.

`FreezeRecord` still cannot be built without all three fields. There is no default requester, no
`freeze_if_ready`, and no argument whose omission supplies one; moving references like `HEAD` are
refused. `PARAMETERS_FROZEN` is in `MANUAL_TRANSITIONS` and in `SYNTHETIC_MAY_NOT_ADVANCE`.

> Depends on all three OPEN conflicts. The frozen document must contain the resolutions from tickets
> 08, 09 and 10; it cannot be frozen around an undefined matching/null interface, an unjustified 40%
> Edge Origin threshold, or an undefined follower order size.

- [x] The pre-registration is frozen at a named commit, with the freeze date and the commit hash
      recorded in the sign-off block.
      — frozen by Nimbo at `4bbae13` on 2026-08-16, recorded in the hash-chained audit log as
      entries #0 and #1. §17's block in `phase-0-preregistration.md` still needs the same two lines
      written into the document itself.
- [x] The resolutions of OPEN conflicts 1, 2 and 3 are present in the frozen text, not referenced from
      elsewhere.
      — merged into the body at v1.1: §6.6 benchmarks are matched pairs, §8.2 the null is a
      within-matched-set permutation, §4.5 follower orders are sized to the execution cost cap, and
      §7.1 condition 3 keeps 40% with its demotion to a backstop recorded.
- [x] The authoritative parameter set contains at minimum: the four walk-forward windows; the
      eligibility bounds (10–1,200 potential buys, 20–1,000 valid buys); the universe floor of 10,000
      accounts; the selection rule `clamp(1% of eligible universe, 250, 1000)`; the five capital
      levels; the netting residual tolerance `max($0.01, 0.01% of transaction notional)`; the
      three-part dead-pool conjunction; the token-age bucket boundaries; the starting mean threshold
      of 15pp; the Edge Origin threshold as resolved in 09; the 5pp small-denominator guard; the
      execution cost caps of 1% majors and 2% mid-cap; the ≥90% fill requirement; the Copy Retention
      2pp display floor; and the master seed.
- [x] The Arbitrum secondary diagnostic is pre-registered **now** as secondary and outside the gate,
      so it cannot be introduced after an Ethereum result is seen.
- [x] The wording of a negative result is fixed in the frozen text verbatim: "No sufficient persistent
      and copyable wallet-selection edge was found for the Ethereum Mainnet target population and
      capital profile."
- [x] The state advances to `PARAMETERS_FROZEN` and a subsequent attempt to change any parameter is
      rejected with an audit record naming the requester.
      — demonstrated end to end on 2026-08-16. An attempt to move `gate.starting_mean_threshold`
      from 0.15 to 0.10, with the reason "the 15pp threshold looks hard to clear", was refused as
      audit entry #2 naming Nimbo. The audit chain verifies over all three entries. The entry is
      written *before* the refusal is raised, so the record exists whether or not anybody reads the
      message.
- [x] The frozen set is readable by every downstream stage; no stage carries its own copy of a
      threshold.
      — 25 constants migrated, and the copies that cannot be migrated are named with their reasons
      rather than left implicit: `gate_validation/` may not import `phase0` because an arbiter must
      not be able to call what it judges, and `contracts/` is the frozen seam that `phase0` itself
      imports. Four values point the other way — `phase0.seeds` and `phase0.validator` hold the
      single literal and the table reads *them*, because `parameters` imports both and neither can
      import back.

      **This criterion was the one that nearly passed while false.** The first pass restated
      `MASTER_SEED_BYTES = 32` and `FIELD_SEPARATOR = "|"` as literals while `phase0/seeds.py` held
      its own copies — in the same block where `seeds.derivation_rule` was deliberately read from
      `RunRecord.SEED_RULE` rather than retyped, and next to a comment in `seeds.py` saying outright
      that "it is the freeze that fixes it". Both copies agreed, so the suite was green; setting the
      frozen width to 48 left `new_master_seed` minting 32 bytes and nothing failed. The inventory
      is no longer written by hand — a sweep walks every module-level assignment in `src/` and fails
      on any literal equal to a frozen value named in none of the four lists.
