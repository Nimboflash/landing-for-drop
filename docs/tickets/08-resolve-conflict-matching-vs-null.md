# 08 — Resolve OPEN conflict 1: matching design versus null construction

**What to build:** A recorded, signed resolution of a genuine conflict between two locked documents.
The pre-registration builds the null by drawing random baskets of N wallets from the eligible universe
and comparing basket against basket. The addendum specifies 5 primary plus 5 robustness matched
controls per selected wallet, standardised distance matching, and a balance target of `|SMD| < 0.10`.
These are different statistical designs and both cannot be the gate. Until this is decided, the
matching engine and the null engine have an undefined interface and neither can be built. The
deliverable is a decision, written into the pre-registration before it is frozen — an agent can
prepare the options and the recommendation, but the Research Owner signs.

**Blocked by:** None — can start immediately.

**Status:** resolved 2026-07-31 — matched pairs + within-matched-set permutation null

- [ ] Both designs are stated precisely enough to be implemented, including what the 95th percentile
      refers to under each.
- [ ] The reconciliation candidate is written out in full: matched controls become the primary
      benchmark and the null is built by permuting selected/control labels **within matched sets** —
      a standard permutation test, stronger than random-basket resampling.
- [ ] The consequences of each option are recorded for the null sample size rule, for the requirement
      that the null gate be the identical full three-condition gate, and for the "no new vendor
      queries" constraint.
- [ ] Exactly one design is selected and recorded as the gating design. The other is either dropped or
      demoted to a reported robustness check that cannot change a gate.
- [ ] The interface between the matching engine and the null engine is specified: what the matching
      engine emits, what the null engine consumes, and how the null sample size is derived under the
      chosen design.
- [ ] The resolution is signed by the Research Owner and staged for inclusion in the pre-registration,
      not merely recorded in a side document.
- [ ] The resolution is dated before any measurement result exists, and that is verifiable from the
      audit log.

---

**Resolution (2026-07-31, Research Owner):** Matched controls are the primary benchmark. The null permutes selected/control labels within each matched set and recomputes the full gate. The naive random basket is kept only as a sanity floor that cannot change the gate. Merged into pre-registration v1.1 §6.6 and §8.2.
