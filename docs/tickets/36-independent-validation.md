# 36 — Independent validation with a separate implementation path

**What to build:** Validation layer 4. The Independent Validator derives expected outputs from raw
chain data and the specification only, using an implementation path that shares no classification,
FIFO, or valuation function with the builder, records their reasoning **before** comparison, and emits
a machine-readable validation report that can block the main test. The honest limitation is recorded
in the same report: two agents from the same base model share priors and make correlated errors, which
is exactly the class this layer exists to catch and the class two agents are worst at catching.

**Blocked by:** 35, 02

**Status:** ready-for-agent

- [ ] The validator's implementation shares no function with the builder's classification, FIFO, or
      valuation code, and the separation is structurally enforced rather than asserted.
- [ ] Expected outputs are derived from raw chain data and the frozen specification only — never from
      the builder's code, intermediate artefacts, or output.
- [ ] The validator's reasoning is recorded before any comparison is run, and the audit log timestamps
      support the ordering.
- [ ] Validation status is emitted explicitly as `MACHINE-INDEPENDENT`, `EXTERNALLY REVIEWED`, or
      `NOT INDEPENDENT` — never assumed, never omitted.
- [ ] `NOT INDEPENDENT` blocks the main test through the governance module, not through a note in a
      report.
- [ ] The report is machine-readable and is a required input to the validation gate summary.
- [ ] The correlated-error limitation of `MACHINE-INDEPENDENT` is stated in the report itself, so the
      strength of the check travels with it.
- [ ] Every discrepancy found is resolved by finding and fixing the cause; averaging errors away or
      dismissing many small discrepancies collectively is not available as an outcome.
