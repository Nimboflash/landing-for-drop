# 20 — Attribution and account typing end to end

**What to build:** Widen the tracer bullet so it survives contact with smart accounts and solver-
settled trades. The same one-command run now recovers the beneficial owner correctly for EOAs, Safes,
and ERC-4337 accounts, refuses to record infrastructure as a trader, and reports how often it had to
fall back to the transaction sender. That fallback rate is the specific failure that produces phantom
whales and erases real users, so it becomes a standing metric here rather than a one-time check.

**Blocked by:** 19

**Status:** audited 2026-08-16 — **2 met, 5 partial, 1 blocked.** `src/attribution/` is 990 lines and
runs on real Ethereum data. Boxes left unticked; the audit is below.

**Criterion 7 is met, and the first audit of it was wrong.** The claim was that
"no code path writes `tx_sender` into `portfolio_owner`, structurally enforced" rests on an AST check
narrow enough to evade — inspecting only `call.keywords` for the literal name `tx_sender`, in one
file — and that `_finalise(owner=sender, method=DIRECT_EOA)` slips through it. That call does not
exist: `owner=sender` appears nowhere in the module, and the only `owner=tx_sender` is inside
`_tx_sender_fallback`, which is exactly what the check asserts.

The AST check is narrow, and it is not the enforcement. `_finalise` carries a runtime exit-point
invariant that raises `AttributionInvariantError` when `owner == tx_sender`, and it is
guard-the-guarded by a test that calls the finaliser directly with the shape it exists to catch. Its
scope is deliberately one method: `ROUTER_RECIPIENT` is the only *inferred* path — no event names the
owner there, so it is the only place the sender could be promoted without evidence. The other three
methods each name the owner from an independent source, and an owner equal to the sender there is a
real EIP-7702 or self-bundling account rather than a coalesce. The comment says so.

**Met.** Safe accounts resolve to the Safe address with seven rotating signers collapsing to one
identity, pinned by a property test. Solver, aggregator and batch routing are refused on all three
mechanisms, and ambiguity is settled once before a lane is chosen — so the same twenty-five-user
batch is no longer refused when a solver submits it and accepted when the router does.

**The partials are one fact, and it is the theme of the day: computed and not published.**
`attribution_fallback_rate` is computed exactly and pinned, carried on the pipeline result, and
`RunReport` has **no field for it** — `src/reporting/` never imports `attribution` at all. So every
hashed §10 artifact is silent about how often the owner was guessed, which is what the criterion's
"emitted with every run" was for. Same shape for criterion 6: uncertain trades are flagged and
excluded and counted, but `ExclusionRecord` carries no volume, while `QuarantineRecord` beside it
does — so the *count* of exclusions is reported and the notional is not.

Closing both means a required `attribution` field on `RunReport` with an `IncompleteRunReport`
refusal when it is absent, mirroring how `not_tested` already works, and a volume on
`ExclusionRecord`. Worth doing together with ticket 21's orphaned reconciliation queue and ticket
24's four standing metrics — the three are the same defect in three packages.

**One small thing worth naming.** A fifth `account_type` value ships with a live owner: `UNKNOWN`,
outside the four the criterion lists. It is pinned in tests, so it is intended rather than
accidental; the criterion's enumeration is what is now incomplete.

Ticket 19 fired; this ticket's only stated blocker is closed.

Ticket 19 fired; this ticket's only stated blocker is closed. `src/attribution/` is 990 lines and is
exercised on real Ethereum mainnet data by `tools/case_runs.py`, so the work is well under way and
the checkboxes below have not been audited against it. **They are left unticked deliberately** —
`docs/build-status.md` exists because ticket files and the repository drift apart, and ticking a box
from the presence of a module is exactly that drift.

Two of them cannot close yet whoever audits the rest: *"the golden expectation for every traced
account"* and *"the golden harness now reports green"* both reference a golden set that does not
exist. Tickets 14–17 are behind 12, 13 and 02. So this ticket can reach `account_type`, the Safe and
ERC-4337 resolution, `attribution_fallback_rate` and the structural ban on writing `tx_sender` into
`portfolio_owner` — and then stops, two boxes short, for a reason that is nothing to do with
attribution.

- [ ] `account_type` is emitted per portfolio identity as `EOA | SAFE | ERC4337 | OTHER_CONTRACT`, and
      matches the golden expectation for every traced account.
- [ ] Safe accounts resolve to the Safe address as `portfolio_owner`; signers are never emitted as
      separate traders.
- [ ] ERC-4337 accounts resolve to the smart account sender; bundler, paymaster, and relayer are never
      emitted as the trader, proven on a golden account that has all three.
- [ ] Solver-settled and aggregator-routed trades do not attribute to the solver, and the golden
      account chosen for this case passes.
- [ ] `attribution_fallback_rate` — the share of trades where `portfolio_owner` fell back to
      `tx_sender` — is computed and emitted with every run as a standing metric.
- [ ] Trades whose owner attribution is uncertain are flagged and excluded from the primary metric
      rather than attributed by guess, and the excluded volume is reported.
- [ ] No code path exists in which `tx_sender` can be written into `portfolio_owner`, and this is
      enforced structurally rather than by convention.
- [ ] The golden harness now reports green on every account whose only hard case is attribution or
      account type.
