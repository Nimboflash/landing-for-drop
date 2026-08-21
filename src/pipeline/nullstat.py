"""The real §8.2 statistic: §7.1's three-condition gate, recomputed on a relabelled population.

``matching_null.permutation_null_detail`` owns everything random about the null — the seed
derivation, the draws, the relabelling — and takes the statistic as an argument, because the
statistic is the *pipeline* and the null package imports nothing but ``contracts``. What it is
handed today by the wiring fixtures is a toy that sums a signal dict. :func:`window_statistic` is
the real one: the window score the gate would see, rebuilt on each relabelled split. It lives in
``pipeline`` because it is composition — ``scoring``'s aggregations regrouped around
``matching_null``'s relabelling — and the composition root is the one builder package permitted to
import both sides.

What one run computes
---------------------

``statistic_fn(relabelled_sets)`` receives the same wallets in the same matched sets, with only
the "selected" label moved, and rebuilds the §7.1 inputs the way the observed gate builds them:

* **one advantage per matched set** — the labelled wallet's buy quality minus its matched
  benchmark, where the benchmark is the set's primary controls pooled under the same
  ``log(1 + USD)`` weights §4.4 gives their buys. An unweighted mean would give a $100 control
  the say of a $1,000,000 one, which is not the benchmark the selected wallet was matched to.
* **one Edge Origin per window** — :func:`scoring.edge_origin` over the pooled selected basket
  and the pooled benchmark basket, so condition 3 is recomputed on the relabelled population
  rather than inherited from the observed one.
* **one** :class:`contracts.WindowScore` — assembled by :func:`scoring.score_window`, the same
  function the observed gate uses, so there is exactly one copy of the three-condition assembly
  and the null cannot quietly test a two-condition version of it (§8.2).

The scalar the permutation machinery compares is the score's ``mean_advantage``; the full score
travels with it because §8.3's Null Pass Rate is a three-condition question.

Robustness controls ride along unread: §6.6 says they cannot change the gate, ``relabel`` never
draws from them, and reading them here would let them do exactly what §6.6 says they cannot.

What is computed once, and what per run
---------------------------------------

Per-wallet buy quality is the expensive part — attribution, netting, FIFO, marking and scoring
over a window of transactions — and relabelling cannot change it: the label decides which group a
wallet's number is aggregated *into*, never the number itself. So the per-wallet scores are
supplied once, at construction, and the returned ``statistic_fn`` is a pure regrouping and
re-aggregation of those precomputed values.

What that guarantees: no per-run work proportional to the window's transaction count; no
randomness, clock, file or network anywhere in the closure; and the same relabelling of the same
population produces the same ``WindowScore`` whatever order the caller supplied the sets or the
scores in — every accumulation below runs in an order derived from the data, because at 38 digits
each addition rounds and §9.2's "reproducible" cannot depend on how a dict happened to iterate.

What it does **not** guarantee: that the scores are the right scores. A caller who supplies
per-wallet scores computed under a different configuration — another window's transactions,
another marking horizon, leader scores handed to the follower column — gets a statistic that is
internally consistent and wrong, and nothing here can see it. ``permutation_null_detail`` checks
the returned score's ``column`` and ``window`` labels against the null being built; the
provenance of the per-wallet numbers behind them is the integrator's to get right.
"""

from decimal import Decimal

from contracts import BuyQuality, MatchedSet, add, divide, sub
from scoring import (
    BUCKET_ORDER,
    COLUMNS,
    WalletScore,
    edge_origin,
    score_window,
    weighted_mean,
)

ZERO = Decimal("0")

#: The names the two pooled baskets carry into the ``EdgeOrigin`` each run produces. Labels, not
#: addresses: ``contracts.BuyQuality`` names a wallet, and a pooled basket is not one.
SELECTED_BASKET = "selected-basket"
BENCHMARK_BASKET = "matched-benchmark"

__all__ = ["BENCHMARK_BASKET", "SELECTED_BASKET", "window_statistic"]


def window_statistic(window, column, scores):
    """Build §8.2's ``statistic_fn`` for one window and one column, from per-wallet scores.

    :param window: the §6.3 walk-forward window index the scores were computed over. It labels
        every ``WindowScore`` this statistic returns, and ``permutation_null_detail`` refuses a
        score whose label disagrees with the null being built.
    :param column: ``"leader"`` or ``"follower_adjusted"`` (:data:`scoring.COLUMNS`). The two
        columns differ only in *which* per-wallet scores the caller supplies — the raw buy
        quality, or the follower-adjusted metric — so the factory is one function parameterised
        twice rather than two functions that could drift apart. Whether the supplied scores
        actually carry the adjustment the column name promises is not visible here; see the
        module docstring.
    :param scores: ``{wallet: scoring.WalletScore}`` — one per member of every matched set the
        statistic will ever be handed, computed once by the caller. The *rich* type, deliberately
        not :class:`contracts.BuyQuality`: pooling a basket needs each wallet's absolute log
        weight, and the seam type carries weight shares only, from which no cross-wallet pool can
        be built. Keys are case-folded — one wallet is one entry, in any spelling — and a key
        that disagrees with the wallet its record names is refused, because the lookup would
        succeed under the wrong name and score one wallet with another's number.
    :returns: ``statistic_fn(relabelled_sets) -> contracts.WindowScore``, deterministic, pure.

    Raised from the returned function, not caught here: a set naming a wallet the score book does
    not carry (the population the scores were computed over and the population being relabelled
    disagree — a defect in what assembled the call, not a data finding), and
    :class:`scoring.BenchmarkBucketMissing` when a relabelled benchmark basket never traded a
    bucket the relabelled selected basket did. Both crash the stage by design; a caught-and-
    defaulted value here would enter the null distribution unremarked.
    """
    if not isinstance(window, int) or isinstance(window, bool) or window < 1:
        raise ValueError(
            "window must be a positive int, got {!r}. It labels every score this statistic "
            "returns, and True, 1 and 1.0 are one key to Python.".format(window)
        )
    if column not in COLUMNS:
        raise ValueError(
            "unknown column {!r}; §7.1 pre-registers exactly {}. A third column is a null "
            "distribution with no gate to serve.".format(column, " and ".join(COLUMNS))
        )
    by_wallet = _scores_by_wallet(scores)

    def statistic(labelled):
        """One run: regroup the precomputed per-wallet scores under the labels as they arrived."""
        sets = _ordered_sets(labelled)
        advantages = []
        selected_group = []
        benchmark_group = []
        for matched in sets:
            selected = _score_for(by_wallet, matched.selected, matched)
            controls = tuple(
                _score_for(by_wallet, wallet, matched) for wallet in matched.primary_controls
            )
            selected_group.append(selected)
            benchmark_group.extend(controls)
            advantages.append(sub(selected.value, _pooled_value(controls)))
        edge = edge_origin(
            _pooled_quality(SELECTED_BASKET, selected_group),
            _pooled_quality(BENCHMARK_BASKET, benchmark_group),
        )
        return score_window(window, column, advantages, edge)

    return statistic


# -- the score book -------------------------------------------------------------


def _scores_by_wallet(scores):
    """``{case-folded wallet: WalletScore}``, with the identity rules applied at the boundary.

    Case-folded because that is what a wallet address is throughout this experiment —
    ``WalletFeatures`` lowercases, and ``permutation_null_detail`` refuses two spellings of one
    selected wallet on exactly this ground. ``WalletScore`` is a plain scoring result and does no
    folding of its own, so the rule is applied here rather than assumed.
    """
    if callable(scores):
        raise TypeError(
            "scores must be a mapping {wallet: scoring.WalletScore}, not a callable; the whole "
            "point of taking them at construction is that they were computed once, before any "
            "relabelling, and a callable could compute per draw"
        )
    seen = {}
    book = {}
    for wallet, score in scores.items():
        if not isinstance(wallet, str):
            raise TypeError(
                "score keys must be wallet address strings, got {}. One wallet is one entry, "
                "and that comparison has to be defined.".format(type(wallet).__name__)
            )
        if not isinstance(score, WalletScore):
            raise TypeError(
                "scores[{!r}] must be a scoring.WalletScore, got {}. The seam's BuyQuality "
                "carries weight shares only, and a basket cannot be pooled from "
                "shares.".format(wallet, type(score).__name__)
            )
        key = wallet.lower()
        if key in seen:
            raise ValueError(
                "scores spells wallet {} two ways ({!r} and {!r}). One wallet is one score: "
                "keeping both would score it with whichever record the caller's mapping "
                "yielded last, and the null would move with iteration order.".format(
                    key, seen[key], wallet
                )
            )
        if score.wallet.lower() != key:
            raise ValueError(
                "scores[{!r}] holds the score of wallet {!r}. A key that disagrees with its "
                "record is the shape of a mis-assembled join: the lookup succeeds under the "
                "wrong name and one wallet is scored with another's number.".format(
                    wallet, score.wallet
                )
            )
        seen[key] = wallet
        book[key] = score
    if not book:
        raise ValueError(
            "no per-wallet scores were supplied; a statistic over an empty score book could "
            "never score any relabelling"
        )
    return book


def _score_for(book, wallet, matched):
    score = book.get(wallet.lower())
    if score is None:
        raise ValueError(
            "no per-wallet score for {} (a member of the matched set whose current label is "
            "{}). The population the scores were computed over and the population being "
            "relabelled disagree, which is a defect in what assembled the call — every member "
            "of every set can wear the label, so every member needs a score.".format(
                wallet, matched.selected
            )
        )
    return score


# -- regrouping -----------------------------------------------------------------


def _ordered_sets(labelled):
    """The relabelled sets, in an order derived from the data rather than the caller's list.

    Keyed on the current label and then on the folded control addresses: under a relabelling two
    sets *may* legitimately carry the same label (matching is with replacement, and a control
    standing in two sets can be drawn in both), so the label alone is not a total order.
    """
    sets = tuple(labelled)
    if not sets:
        raise ValueError(
            "there is nothing to score: no matched sets were supplied. A window score over no "
            "sets is not a small answer, it is no answer."
        )
    for item in sets:
        if not isinstance(item, MatchedSet):
            raise TypeError(
                "the statistic consumes MatchedSet, got {}".format(type(item).__name__)
            )
    return tuple(sorted(
        sets,
        key=lambda m: (m.selected.lower(), tuple(sorted(w.lower() for w in m.primary_controls))),
    ))


def _address_order(members):
    """Wallet scores in folded-address order — the accumulation order every pool below uses."""
    return sorted(members, key=lambda score: score.wallet.lower())


def _pooled_value(members):
    """The buy quality of a basket, from its members' per-wallet scores.

    ``Σ(T_w · v_w) / Σ T_w`` where ``T_w`` is the wallet's total log weight and ``v_w`` its buy
    quality — algebraically the §4.4 weighted mean over the union of the members' buys, since
    ``T_w · v_w`` recovers the wallet's own ``Σ(w_i · r_i)``. Equal to that union up to the
    frozen context's rounding; computed from the per-wallet aggregates because those are what
    was precomputed.
    """
    return weighted_mean((m.total_weight, m.value) for m in _address_order(members))


def _pooled_quality(label, members):
    """One group's :class:`contracts.BuyQuality`, pooled from its members' per-wallet scores.

    Everything :func:`scoring.edge_origin` reads: the pooled value, the §10 mix summed in USD and
    re-shared, and per §4.7 bucket the group's weight share and log-weighted buy quality. A
    weightless bucket is absent, not zero — the same rule ``WalletScore.bucket_values`` applies —
    so a benchmark that never traded a bucket the selected basket did is *refused* downstream
    rather than credited with breaking even there.

    A wallet standing as a control in two sets contributes once per slot: §6.6's benchmark is
    five control *slots* per selected wallet, and dropping the repeat would silently reweight
    every other control in both sets.
    """
    ordered = _address_order(members)
    total_weight = ZERO
    realized = ZERO
    marked = ZERO
    dead = ZERO
    n_buys = 0
    for member in ordered:
        total_weight = add(total_weight, member.total_weight)
        realized = add(realized, member.realized_usd)
        marked = add(marked, member.marked_usd)
        dead = add(dead, member.dead_usd)
        n_buys += member.n_buys
    basis_total = add(add(realized, marked), dead)

    bucket_weights = {}
    bucket_values = {}
    for bucket in BUCKET_ORDER:
        entries = []
        for member in ordered:
            for row in member.buckets:
                if row.bucket is bucket and row.value is not None:
                    entries.append((row.weight, row.value))
        if not entries:
            continue
        weight = ZERO
        for entry_weight, _value in entries:
            weight = add(weight, entry_weight)
        bucket_weights[bucket] = divide(weight, total_weight)
        bucket_values[bucket] = weighted_mean(entries)

    return BuyQuality(
        wallet=label,
        value=_pooled_value(ordered),
        n_buys=n_buys,
        realized_share=divide(realized, basis_total),
        marked_share=divide(marked, basis_total),
        dead_share=divide(dead, basis_total),
        bucket_weights=bucket_weights,
        bucket_values=bucket_values,
    )
