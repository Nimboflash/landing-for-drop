# 39 — Code and data freeze, freeze manifest, and the invalidation drill

**What to build:** Turn the experiment into a specific reproducible object rather than a claim. The
freeze manifest pins every input; the main test and the null runs must execute from the same commit
through the same shared functions, so no divergence between them is possible. The second half of this
ticket is the drill nobody wants to run later for the first time: inject a real bug after the freeze
and prove the system marks the run `INVALIDATED` and forces a complete repeat rather than allowing a
patch.

**Blocked by:** 38

**Status:** ready-for-agent

- [ ] The freeze manifest captures every one of: source code commit; dataset snapshot; golden dataset
      version; protocol coverage list; decoder coverage version; model version; configuration; master
      and child seeds; known-answer fixtures; token and pool rules; price and marking rules;
      validation report. Plus the original specification pin from ticket 07, or its explicit
      `UNAVAILABLE` marker.
- [ ] The dataset snapshot covers the training and forward windows for the frozen universe, so the
      null can be built by resampling already-extracted data with **no new vendor queries**.
- [ ] The governance state advances to `CODE_AND_DATA_FROZEN`, and any subsequent code change requires
      a new registered version rather than an in-place edit.
- [ ] The manifest hash is computed and is the identifier every later result binds to.
- [ ] Invalidation drill: a real, documented bug is introduced after freeze, and the system sets
      `Current Run Status: INVALIDATED`.
- [ ] From `INVALIDATED`, the system refuses to patch or partially correct the previous result, and
      requires the full sequence: fix, register a new code version, re-run the entire validation gate,
      rebuild the null from scratch, re-run the main test.
- [ ] Selectively using the old or the new result is structurally unavailable, proven by an attempt
      that is rejected with an audit record.
- [ ] The drill is reverted cleanly and the manifest for the real run is regenerated and re-hashed.
