# The two lenses that never ran

**Run:** 2026-08-09 against `02f07b7`, by hand rather than by agent — four workflow attempts died
on infrastructure. Every figure below was produced by a script and is reproducible.

Eighteen breaches were found and closed by two earlier lenses (`72beaab`). **These two never ran**,
and they cover the routes the repair's own residue arguments depend on — so until now those
arguments had never been tested by anyone.

**Verdict: no breach. Two observations, neither of which moves a basket.**

---

## Lens 1 — signatures, the type lattice, the import graph

### The decisive question

> Is there any signature that accepts both a pre-T0 and a post-T0 type in the same slot?

```
public surface inspected     531 parameters and returns
gaps                           0
```

The first version of this system failed exactly here: 147 function definitions, zero annotations,
so every parameter was implicitly `Any`. The full sweep over `src/universe/` now finds:

```
469  nominal
 65  object       all operator dunders — __eq__, __add__, __reduce__, __setstate__
  3  unannotated  all three are `visit`, a nested closure inside look_ahead_audit
```

`object` on `__eq__(self, other)` is the Python operator protocol, not a hole: the runtime calls it
with anything, and narrowing the annotation would describe the language incorrectly. `visit` is a
local callback for an object-graph walk whose entire job is to accept arbitrary values; it is not
reachable as a signature.

Inventory hash `e2772a33888c5b10`.

### Transitive import reachability

Built as a real graph over all of `src/` — direct imports, relative imports resolved, and the
closure walked — rather than by grepping for `import forward`:

```
reachable(selection module, universe.forward)     0 of 11
modules importing universe.forward at all         0
```

The second line is the stronger one, and it is deliberate. `universe/__init__.py` does **not**
re-export `forward`, and says why:

> A re-export would make every importer of `universe` an importer of the post-T0 side. The output
> side has to write `from universe.forward import ...`, which is visible in a diff.

The import arrow runs `forward -> selection side` and never the reverse.

### Direct attack on the ordering barrier

```
PreT0Workspace(...)  named directly    OrderingViolation
ForwardMount(...)    named directly    OrderingViolation
ForwardMount(...)    with the stolen _ORDER_TOKEN    ArtifactRefused
```

`_ORDER_TOKEN` is importable — any private name in the same interpreter is, and the repair said so
rather than claiming otherwise. **It does not help.** The token is not the gate; a sealed
`SelectedWalletArtifact` is. Sealing is step 4 of the eight-step order and selection is step 2.

---

## Lens 2 — numeric laundering and runtime taint

### The algebra, on real values

```
PRE_T0       + PRE_T0        ->  PRE_T0
PRE_T0       + POST_T0       ->  CONTAMINATED
PRE_T0       + CONTAMINATED  ->  CONTAMINATED
POST_T0      + anything      ->  CONTAMINATED
CONTAMINATED + anything      ->  CONTAMINATED
```

All nine pairs verified. The headline laundering expression — the one no import rule and no AST
scan can see, because no forward object is ever read — is caught:

```python
pre / (pre + Decimal("0.42"))     ->  ContaminatedDecimal
```

A bare `Decimal` entering the algebra contaminates the result. That is the whole point of the layer
and it holds.

### Attempts to strip provenance in transit

```
pre + pre            carries      pre / pre        carries
pre - pre            carries      pre * pre        carries
min(pre, pre)        carries
abs(pre)             REFUSED  TypeError
copy.deepcopy        REFUSED  ProvenanceRefused
pickle round-trip    REFUSED  ProvenanceRefused
Decimal(str(pre))    REFUSED  InvalidOperation — the repr is not parseable as a Decimal
int(pre)             REFUSED  TypeError

pre.value            strips to Decimal      <- the admitted residue
bool(pre)            strips to bool
sum([pre, pre])      -> ContaminatedDecimal <- observation, see below
```

### The residue claim, tested for the first time

`provenance.py` admits that `.value` is readable and `measured_before_t0` accepts a bare number,
and argues the ordering barrier bounds this: *"under a governed selection a forward return is not
obtainable."* Measured:

```
ForwardDecimal(Decimal("0.42"), 18_600_000)   builds — fabrication is not prevented
  -> measured_before_t0(fd, ...)              TypeError: takes a Decimal, int or str
  -> fd.value                                 AttributeError: no such attribute
```

**The `.value` route does not exist on the forward side at all.** Only `PreT0Decimal` carries
`.value`, and reading a pre-T0 number is exactly what selection is permitted to do. The residue is
narrower than the docstring claims, not wider.

A *fabricated* forward number is not look-ahead — it is a made-up number, and nothing anywhere can
distinguish a fabricated measurement from a real one. A *genuine* forward number needs a
`ForwardLedger`, which needs a `ForwardMount`, which needs a sealed artifact, which is step 4. The
order is the gate.

---

## Two observations, neither a breach

**`sum([pre, pre])` returns `ContaminatedDecimal`.** `sum()` starts from the integer `0`, and `0 +
pre` contaminates. It fails *closed*, so it cannot leak — but it means `sum()` is unusable on these
values and a caller reaching for it gets a refusal downstream rather than an error at the point of
the mistake. Worth a named helper if summing pre-T0 values is ever wanted.

**`bool(pre)` strips to `bool`.** A truthiness test on a pre-T0 value is not post-T0 information, so
this leaks nothing. Recorded because it is a real strip point and the next reader should not have to
rediscover that it is harmless.

---

## What this does not establish

The lenses attack the barrier, not the measurements. Nothing here says the metric is right, and
nothing here has touched real chain data — ticket 03 remains the blocker.

And the standing caution from three rounds of this: **round 2 believed it had closed the class and
had not.** Two lenses found eighteen breaches in a design that passed all its own checks. These two
found none, which is evidence and not proof.
