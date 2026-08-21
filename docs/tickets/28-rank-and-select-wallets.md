# 28 — Rank and select: clamp(1% of universe, 250, 1000)

**What to build:** Produce the selected basket for each window, ranked strictly on the six months
before `T0`, with the count derived from the measured universe rather than fixed. A percentage rather
than a fixed count keeps selection pressure approximately constant across windows — a fixed 500 could
mean the top 2.5% in one window and the top 0.25% in another, and those are not the same experiment.
The demo is four selected baskets plus an audit proving nothing after `T0` touched the ranking.

**Blocked by:** 26, 27

**Status:** ready-for-agent

- [ ] Ranking is computed on `buy_quality_30d` over the six months before `T0` and on nothing else.
- [ ] `Selected Wallet Count = clamp(1% of Eligible Universe, 250, 1000)` per window, derived from the
      Step 0 measurement, and the derived count is recorded per window.
- [ ] Governance refuses to run this stage unless Step 0 is complete for the window and the universe
      is frozen.
- [ ] A look-ahead audit shows that no information generated after `T0` entered selection, including
      post-`T0` activity, forward returns, and any vendor field whose value is recomputed over time.
- [ ] The selected basket is emitted as a frozen artefact per window, versioned and pinnable by the
      freeze manifest.
- [ ] Activity-band composition of the selected basket is reported across 20–99, 100–499 and 500–1,000
      valid buys, since sensitivity by band is a required diagnostic later.
- [ ] Selection is reproducible: same snapshot, same commit, same seed produces the same basket.
- [ ] No forward-window return is computed for the selected basket in this ticket — selection is a
      pre-`T0` operation and the forward numbers belong to the main test.
