# 27 — Freeze the universe at T0 and report churn as an output

**What to build:** Close the survivorship door. The candidate universe is frozen at each window's `T0`
and no wallet is ever removed afterwards for going quiet, going inactive, or exceeding 1,000 buys. A
wallet that blew up and went dormant stays in the sample with its actual result. Post-`T0` activity is
computed and reported — it is a required output — but the system must make it structurally impossible
to use as a selection filter, because that is exactly how look-ahead bias enters through the back door
as a reasonable-sounding "still active" filter.

**Blocked by:** 26

**Status:** ready-for-agent

- [ ] The eligible universe is frozen per window at `T0` under a snapshot identifier that later stages
      pin.
- [ ] After `T0`, no wallet is removed for exceeding 1,000 buys, sharply increasing activity, reducing
      activity, or going fully inactive — proven by a test that attempts each removal and is refused.
- [ ] Post-`T0` activity is available only on an output path; no selection, ranking, or matching stage
      can read it, and this is enforced structurally rather than by convention.
- [ ] Churn is reported as `Churn Rate = selected wallets with no valid buy in the forward period /
      total selected wallets`, in three states: `Active`, `Reduced Activity`, `Inactive`.
- [ ] The three-state definition distinguishes a wallet that fell from 100 trades to 1 as effectively
      dead, rather than counting it as active.
- [ ] Benchmark baskets are drawn from the same frozen `T0` universe, so the control is subject to
      exactly the same survivorship constraints as the selected set.
- [ ] A look-ahead audit runs over the frozen universe and reports zero post-`T0` inputs reaching any
      selection path.
