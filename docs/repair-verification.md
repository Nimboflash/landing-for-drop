# Repair verification

**Date:** 2026-08-01 · **Suite at time of verdict:** 877 passed, 52 skipped, 0 failures

Five agents repaired the twelve findings in [`module-review.md`](./module-review.md) in parallel. A
sixth then reconstructed every reviewer-traced failing case and ran it, rather than reading the
diffs.

It found **8 of 12 genuinely fixed, 3 papered over, and 4 new defects introduced by the repairs.**
It also ran 35 mutations of its own, of which 2 survived.

That outcome is the point of the exercise. A repair pass that reports total success is the one to
distrust — five agents each fixing their own reported case in isolation is precisely the setup that
produces narrow fixes.

---

## Verdict per finding

| # | Verdict |
|---|---|
| attribution.1 | **fixed on the transfer lane, general defect survives on the Safe and 4337 lanes** |
| attribution.2 | genuinely fixed — with a coverage regression, see D-A |
| netting.1 | **papered over — 2 cents defeats it** |
| fifo.1 | fixed in `src`; the anti-pattern survives in the test file, see D-D |
| fifo.2 | genuinely fixed, and deeper than asked |
| marking.1 | genuinely fixed |
| marking.2 | genuinely fixed |
| depth.1 | **papered over — one raw unit defeats it** |
| depth.2 | genuinely fixed — `properties/` 737 lines, `integration/` 476 lines |
| depth.3 | genuinely fixed |
| depth.4 | genuinely fixed |
| depth.5 | genuinely fixed |

---

## P-1 · depth.1 — the guard closed the point, not the class

`src/depth/amm.py:334` now refuses `real_usd <= 0`. But the quarantine at `amm.py:380`
(`virtual_usd < real_usd`) is just as toothless when the real reserve is *tiny* as when it is zero.
**One raw unit of USDC restores the reviewer's entire traced output verbatim:**

```
quote_reserve_raw    depth        understatement_factor   copyable   order_usd
0                    QuarantineRequired
1  ($0.000001)       $5,000,000   5.000000E+12            True       $35,000
10 ($0.00001)        $5,000,000   5.000000E+11            True       $35,000
```

$35,000 of executable capacity against a pool holding a millionth of a dollar, with
`binding_constraint='cost_cap'`.

The docstring cites a *measured* 5–23× understatement band; nothing bounds the factor above. And
the new property test hard-codes `quote_reserve_raw=0` while the generator draws understatement
factors from 1..23 with at least one whole quote unit — so **the regime is structurally unreachable
by the new suite, exactly as it was by the old one.**

## P-2 · netting.1 — the exclusion test is absolute, the consequence is proportional

`_left_no_endpoint` calls a leg cancelled if its net is zero *or* `net_usd <= $0.01`. Repay a flash
loan a shade short and the full gross returns to the notional:

```
repaid in full    notional $1,000.00      tol $0.10    NO_CLEAR_ENDPOINT
$0.003 short      notional $1,000.00      tol $0.10    NO_CLEAR_ENDPOINT
$0.0102 short     notional $900,000.00    tol $90.00   VALID_BUY   <- $50 written off
$0.02 short       notional $900,000.00    tol $90.00   VALID_BUY   <- $50 written off
```

Same transaction, same $50 nobody can explain, admitted to the primary metric — decided by repaying
**0.0000011% short**. The hand-computed test covers only the $0.003 case and its own docstring names
the floor as the boundary, so the hole was known and left.

## P-3 · attribution.1 — the rule is stated globally, installed on one of three lanes

The ambiguity check runs at `resolve.py:115`, but lines 107–110 return from the Safe and ERC-4337
lanes first. The identical 25-trader batch:

```
transfer lane                 ->  UNRESOLVED, 25 addresses named
+ a SafeExecution             ->  SAFE_EXECUTION, confidence 1, usable=True, 24 erased
+ a single UserOperationEvent ->  ERC4337_SENDER, confidence 1, usable=True, 24 erased
```

The module's own new docstring says *"who signed is never evidence about who traded… A batch
settling twenty-five users has twenty-five owners and one owner slot."* A Safe-settled batch is
precisely that shape, and the only thing standing between it and a phantom mega-wallet is
`is_infrastructure(safe)` — the label list that finding attribution.2 exists **because it is never
complete**.

---

## New defects introduced by the repairs

**D-A · Attribution coverage collapses against any unlabelled venue.** `_candidate_owners` excludes
only `is_infrastructure`, so an unlabelled or `contract_accounts`-typed counterparty becomes a
co-candidate and `DIRECT_EOA` becomes unreachable:

```
known EOA vs labelled pool       ->  DIRECT_EOA      (control)
known EOA vs unlabelled pool     ->  UNRESOLVED
known EOA, 2-hop via unlabelled  ->  UNRESOLVED
```

Every `DIRECT_EOA` test uses a labelled venue, so the suite cannot see it. The direction is
conservative — refusal, not a wrong owner — but the §8 usable population now moves with label-set
completeness, which is the input the module was designed not to depend on.

**D-B · `abs()` outside the frozen context, inside the fifo repair itself.**
`src/fifo/matching.py:272`: `drift = abs(divide(sub(remainder, share), share))`. `Decimal.__abs__`
rounds to the ambient context, truncating the 38-digit ratio to 28 before it is compared to
`MAX_CLOSING_DRIFT`. Same file line 240: `return -share if sign else share`, a bare unary minus.

**This is the exact pattern `contracts/numeric.py` was written to eliminate, reintroduced by the fix
for fifo.2.** The lesson did not generalise from the briefing to the hands.

**D-C · Two live behaviours the suite would not notice if regressed.** Both survived all 877 tests:

- `netting/balance.py:329` `_magnitude(leg.usd) <= tolerance` → `abs(...)` **survives**. Demonstrated
  flip: a leg of `-0.10000000000000000000000000000000000001` against a $0.1 tolerance is negligible
  under `abs()` and not under `_magnitude()`.
- `marking/pools.py:188` `normalise_asset(venue.quote) != normalise_asset(pool.quote)` →
  `venue.quote != pool.quote` **survives**. `PoolState` stores `quote` verbatim, so normalisation is
  load-bearing for checksummed addresses and for WETH-vs-native-ETH.

**D-D · The fifo.1 anti-pattern is still in the file the reviewer named.**
`tests/integration/test_fifo.py:313` asserts `realized_return` against a recomputed
`divide(...) - 1`. It passes only because it targets the row whose return is exactly 1; the other
two rows both evaluate `False`.

Worse, lines 307–312 pass a `realized_return` recomputation to `verify_redundant_derived` two lines
after asserting `"realized_return" not in row`. `verify_redundant_derived` skips absent keys, **so
that lambda never executes and the call asserts nothing.**

---

## What this says about the process

Three of the twelve repairs closed the reported *instance* while leaving the *class* open, and all
three did it the same way: a guard on the exact value the reviewer cited — `raw == 0`, "repaid in
full", the transfer lane — rather than on the condition that made it dangerous. One raw unit, two
cents, and one Safe event respectively walk straight past.

That is not carelessness. It is what fixing a traced failing case *looks like* when the trace is
taken as the specification. The reviewer's job was to find an instance; the fixer's job was to close
the class, and the brief did not make that distinction sharply enough.

The other pattern worth naming: **D-B is the repair reintroducing the precise defect the briefing
opened with.** Being told about a class of bug, in the same document, did not prevent writing one.
Only the structural check catches that — which is why the next round adds one.
