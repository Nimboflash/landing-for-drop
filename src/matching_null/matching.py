"""Standardised-distance matching, and the covariate balance table it has to justify itself with.

Pre-registration §6.6.

Five primary controls per selected wallet are the benchmark the gate is measured against; five
robustness controls are reported and **cannot change the gate**. Matching is with replacement, so
a good control may serve several selected wallets — which is why the balance table carries the
unique-control count, the reuse rate and Kish's effective sample size rather than just an ``n``.
Five hundred sets built from fifty distinct controls is not a five-hundred-strong benchmark, and
only the effective sample size says so.

The one thing this module must never do is report a balanced-looking table it did not earn. Two
guards for that:

* ``account_type`` is matched **exactly**, not standardised;
* zero matched sets raises rather than returning an empty balance table, because
  ``CovariateBalance.balanced`` is ``all(...)`` over the SMD mapping and ``all(())`` is ``True`` —
  an empty match would report perfect balance.
"""

import hashlib
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Dict, Optional, Tuple

from contracts import (
    CALCULATION_CONTEXT,
    MATCHING_DIMENSIONS,
    SMD_BALANCE_TARGET,
    ContractError,
    CovariateBalance,
    MatchedSet,
    calc,
    divide,
    mul,
    require_finite,
)
from phase0.parameters import PARAMETERS

from .features import (
    CATEGORICAL_DIMENSION,
    NUMERIC_DIMENSIONS,
    WalletFeatures,
    Standardisation,
    mean_of,
    require_pre_t0,
    sqrt_of,
    squared_distance,
    standardise,
    variance_of,
    z_vector,
)

ZERO = Decimal("0")

#: §6.6. Five of each, and the asymmetry between them is the point: the primary set is the
#: benchmark, the robustness set is a report. Both counts are read from the ticket-11 frozen set —
#: the primary count is the size of the matched set the permutation null relabels within, so a
#: local copy of it here would be a second answer to "how many controls is the gate measured
#: against?" and the null would belong to a different experiment from the test.
PRIMARY_CONTROLS = PARAMETERS.value("benchmark.primary_matched_controls")
ROBUSTNESS_CONTROLS = PARAMETERS.value("benchmark.robustness_controls")


class MatchingInfeasible(ContractError):
    """Not one selected wallet could be matched.

    A modelling refusal, not a measurement. With no matched sets there is no benchmark, no
    permutation null and no experiment — and an empty ``CovariateBalance`` would report itself as
    perfectly balanced, because every SMD in an empty mapping is below target. Some selected
    wallets going unmatched is an ordinary observed outcome and is reported in
    ``unmatched_selected``; all of them is not an outcome, it is an absent control group.
    """


def _tiebreak_key(seed, wallet):
    """A deterministic pseudo-random ordering key for candidates at identical distance.

    Ties are common — many wallets share a rounded feature profile — and they have to be broken
    somehow. Breaking them by address would be deterministic but not neutral: addresses are not
    random, and the lowest ones would be picked as controls again and again, inflating the reuse
    rate and deflating the effective sample size for no reason connected to the data.

    Derived from the seed by SHA-256 rather than from ``random``, so the ordering is reproducible
    from ``(seed, wallet)`` alone on any machine and any Python version — the module never touches
    a global RNG.
    """
    digest = hashlib.sha256("{}|{}".format(seed, wallet).encode("utf-8")).digest()
    return int.from_bytes(digest, "big")


@dataclass(frozen=True)
class Candidate:
    """One control candidate for one selected wallet, with the distance that ranked it."""

    wallet: str
    squared_distance: Decimal
    distance: Decimal


@dataclass(frozen=True)
class MatchDetail:
    """One selected wallet's matching, with every number a reviewer needs to redo it by hand."""

    selected: str
    primary: Tuple[Candidate, ...]
    robustness: Tuple[Candidate, ...]
    candidates_considered: int

    @property
    def matched_set(self):
        return MatchedSet(
            selected=self.selected,
            primary_controls=tuple(c.wallet for c in self.primary),
            robustness_controls=tuple(c.wallet for c in self.robustness),
        )

    @property
    def worst_primary_distance(self):
        return max((c.distance for c in self.primary), default=None)


@dataclass(frozen=True)
class UnmatchedSelected:
    """A selected wallet that could not be given a full primary control set, and why.

    §6.4 forbids dropping a wallet for anything it did after T0. This is the only legitimate
    reason one leaves the analysis: the frozen universe did not contain enough comparable wallets.
    It is reported, never silently skipped.
    """

    wallet: str
    reason: str
    candidates_available: int


@dataclass(frozen=True)
class MatchingResult:
    """The rich result. :func:`build_matched_sets` reduces this to the seam pair.

    Carries what the seam types have no field for and a reviewer cannot reproduce the numbers
    without: the ruler each dimension was standardised against, every chosen control's distance,
    why each unmatched wallet was unmatched, and the balance of the robustness set alongside the
    primary one.
    """

    matches: Tuple[MatchDetail, ...]
    unmatched: Tuple[UnmatchedSelected, ...]
    balance: CovariateBalance
    robustness_balance: Optional[CovariateBalance]
    standardisation: Dict[str, Standardisation]
    t0_block: int
    t0_timestamp: Optional[int]
    seed: int
    universe_size: int
    caliper: Optional[Decimal]

    @property
    def sets(self):
        return tuple(m.matched_set for m in self.matches)

    @property
    def control_slots(self):
        """Control *slots*, not distinct controls: a control reused five times fills five."""
        return sum(len(m.primary) for m in self.matches)


def _resolve_features(features):
    """``wallet -> WalletFeatures``, from either accepted input shape, under **one** rule.

    ``features`` may be a mapping or an iterable of records. The two branches are now one rule —
    they share the collector below — and that rule is: *two entries naming the same wallet are
    refused, never resolved.*

    They used to disagree, and the silent one was the mapping. It computed ``key = wallet.lower()``
    and assigned, so two keys differing only in case — ``"0xC1"`` and ``"0xc1"`` — each passed the
    self-consistency check (both records already carry the lowercased address; that is
    ``WalletFeatures.__post_init__``'s doing) and then collapsed onto one entry, last writer
    winning on the caller's ``dict`` order. The iterable branch raised on the identical five
    records. Two branches of one function disagreeing about whether an input is legal meant one of
    them was wrong.

    What the refusal buys, measured on the universe in
    ``tests/hand_computed/test_matching_null_identity.py`` — three selected wallets, four controls,
    ``n_primary=1``, ``0xc1`` described twice, once at ``capital_deployed = 1`` and once at
    ``1000``, everything else identical::

        surviving 0xc1     matched sets                          SMD capital_deployed   ESS  balanced
        capital 1     0xs1->0xc2  0xs2->0xc1  0xs3->0xc3                             0    3  True
        capital 1000  0xs1->0xc2  0xs2->0xc2  0xs3->0xc3   0.377964473009227227214...  1.8  False

    One input, two ``dict`` orderings. A different control is matched, the universe is
    standardised against a different ruler, the effective sample size moves from 3 to 1.8, and the
    published §6.6 covariate-balance table flips from *not balanced* to *perfectly balanced*. A
    matched set was being built against a wallet the matcher could not see.
    """
    records = {}

    def collect(key, record):
        if key in records:
            raise ValueError(
                "duplicate feature record for wallet {}. Two entries name it and nothing here can "
                "say which one is its features; resolving that by iteration order would let the "
                "caller's ordering choose the control, the ruler the universe is standardised "
                "against, and the §6.6 balance table that is published as evidence the match was "
                "earned.".format(key)
            )
        records[key] = record

    if hasattr(features, "items"):
        for wallet, record in features.items():
            if not isinstance(record, WalletFeatures):
                raise TypeError(
                    "features[{!r}] must be a WalletFeatures, got {}".format(
                        wallet, type(record).__name__
                    )
                )
            key = (wallet or "").lower()
            if key != record.wallet:
                raise ValueError(
                    "features key {!r} does not match the record's own wallet {!r}; a mapping "
                    "that disagrees with itself would match one wallet using another's "
                    "features".format(wallet, record.wallet)
                )
            collect(key, record)
        return records

    for record in features:
        if not isinstance(record, WalletFeatures):
            raise TypeError(
                "features must contain WalletFeatures, got {}".format(type(record).__name__)
            )
        collect(record.wallet, record)
    return records


def _distinct_lower(wallets, label):
    """Case-folded wallet addresses, in the caller's order, with duplicates refused.

    The same identity rule :func:`_resolve_features` applies to the feature mapping, applied to
    the two wallet *lists*: ``"0xC1"`` and ``"0xc1"`` are one wallet, and a list naming it twice is
    refused rather than deduplicated. Deduplicating would be the quiet option and the wrong one —
    in ``universe`` it would shrink the control pool without reporting it; in ``selected`` it would
    put one wallet into the benchmark twice under one label and count it twice in every §6.6
    balance figure.

    Pinned by ``tests/hand_computed/test_matching_null_identity.py``. It was not pinned by
    anything until then: the whole 96-test ``matching_null`` selection stayed green with this
    refusal disabled.
    """
    out = []
    seen = set()
    for wallet in wallets:
        key = (wallet or "").lower()
        if not key:
            raise ValueError("{} contains an empty wallet address".format(label))
        if key in seen:
            raise ValueError(
                "{} contains {} twice. A duplicate would be matched twice and would enter the "
                "benchmark twice under one label.".format(label, key)
            )
        seen.add(key)
        out.append(key)
    return tuple(out)


def build_matched_sets(selected, universe, features, t0_block, seed, t0_timestamp=None,
                       n_primary=PRIMARY_CONTROLS, n_robustness=ROBUSTNESS_CONTROLS,
                       caliper=None):
    """§6.6 matching. Returns ``(sets, balance)`` — the seam pair.

    See :func:`build_matched_sets_detail` for the full derivation.
    """
    result = build_matched_sets_detail(
        selected, universe, features, t0_block, seed,
        t0_timestamp=t0_timestamp, n_primary=n_primary, n_robustness=n_robustness,
        caliper=caliper,
    )
    return list(result.sets), result.balance


def build_matched_sets_detail(selected, universe, features, t0_block, seed, t0_timestamp=None,
                              n_primary=PRIMARY_CONTROLS, n_robustness=ROBUSTNESS_CONTROLS,
                              caliper=None):
    """Match each selected wallet to its nearest controls in standardised space.

    :param selected: the wallets chosen at T0 (§6.5). Must be a subset of ``universe``.
    :param universe: the frozen T0 universe (§6.4). Controls are drawn from it, minus the
        selected wallets — a selected wallet standing as its own benchmark's control would put
        the treatment group on both sides of the contrast.
    :param features: mapping ``wallet -> WalletFeatures``, or an iterable of them.
    :param t0_block: the selection instant. **Every** supplied feature record is checked against
        it, not only the ones that end up being used: a features mapping containing one
        forward-looking record was produced by a pipeline that cannot be trusted for the others.
    :param seed: breaks distance ties deterministically. See :func:`_tiebreak_key`.
    :param caliper: optional maximum standardised distance for a primary control. Defaults to
        ``None`` — **no caliper**. §6.6 pre-registers none, and a default one would be an
        unregistered threshold silently deciding which selected wallets leave the analysis.

    ``account_type`` is matched exactly. The remaining nine dimensions are standardised over the
    frozen universe and compared by equally weighted Euclidean distance.
    """
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError("seed must be an int, got {}".format(type(seed).__name__))
    for name, count in (("n_primary", n_primary), ("n_robustness", n_robustness)):
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("{} must be a non-negative int, got {!r}".format(name, count))
    if n_primary < 1:
        raise ValueError(
            "n_primary must be at least 1; a matched set with no controls has no benchmark, and "
            "the permutation null would have nothing to permute"
        )
    if caliper is not None:
        caliper = require_finite(caliper, "caliper")
        if caliper <= 0:
            raise ValueError("a caliper must be a positive standardised distance")

    records = _resolve_features(features)

    # Before anything else. A look-ahead violation must not be pre-empted by a structural
    # complaint about the same data — the trap is the headline failure of this module.
    for wallet in sorted(records):
        require_pre_t0(records[wallet], t0_block, t0_timestamp)

    universe_wallets = _distinct_lower(universe, "universe")
    selected_wallets = _distinct_lower(selected, "selected")
    if not selected_wallets:
        raise ValueError("no selected wallets were supplied")

    universe_set = set(universe_wallets)
    outside = sorted(set(selected_wallets) - universe_set)
    if outside:
        raise ValueError(
            "selected wallet(s) are not in the frozen T0 universe: {}. §6.4 freezes the universe "
            "at T0 and draws both the selected wallets and their controls from it; a selected "
            "wallet from outside it has been chosen on information the universe does not "
            "contain.".format(", ".join(outside))
        )
    missing = sorted(universe_set - set(records))
    if missing:
        raise ValueError(
            "no features for universe wallet(s): {}{}. A universe member with no features is "
            "silently absent from the control pool, which shrinks the benchmark without "
            "reporting it.".format(
                ", ".join(missing[:5]), "" if len(missing) <= 5 else " (+{} more)".format(len(missing) - 5)
            )
        )

    # Address order throughout, never the caller's. Decimal addition is not associative at 38
    # digits, so a universe supplied in a different order would produce a standard deviation
    # differing in its last digit — enough to swap two near-tied controls and produce a different
    # matched set from identical data. Sorting makes the result a function of the data alone.
    universe_wallets = tuple(sorted(universe_wallets))
    selected_wallets = tuple(sorted(selected_wallets))

    universe_records = [records[w] for w in universe_wallets]
    standardisation = standardise(universe_records)
    vectors = {w: z_vector(records[w], standardisation) for w in universe_wallets}

    selected_set = set(selected_wallets)
    pool_by_type = {}
    for wallet in universe_wallets:
        if wallet in selected_set:
            continue
        pool_by_type.setdefault(records[wallet].account_type, []).append(wallet)

    wanted = n_primary + n_robustness
    matches = []
    unmatched = []
    for wallet in selected_wallets:
        account_type = records[wallet].account_type
        pool = pool_by_type.get(account_type, ())
        origin = vectors[wallet]

        ranked = []
        for other in pool:
            d2 = squared_distance(origin, vectors[other])
            ranked.append((d2, _tiebreak_key(seed, other), other))
        ranked.sort()

        chosen = []
        for d2, _key, other in ranked[:wanted]:
            chosen.append(Candidate(wallet=other, squared_distance=d2, distance=sqrt_of(d2)))

        primary = tuple(chosen[:n_primary])
        if len(primary) < n_primary:
            unmatched.append(UnmatchedSelected(
                wallet=wallet,
                reason=(
                    "only {} control candidate(s) of account_type {} in the frozen universe; "
                    "{} primary controls are required".format(
                        len(pool), account_type.value, n_primary
                    )
                ),
                candidates_available=len(pool),
            ))
            continue
        if caliper is not None and any(c.distance > caliper for c in primary):
            unmatched.append(UnmatchedSelected(
                wallet=wallet,
                reason=(
                    "nearest {} control(s) reach standardised distance {}, beyond the caliper "
                    "{}".format(n_primary, primary[-1].distance, caliper)
                ),
                candidates_available=len(pool),
            ))
            continue

        matches.append(MatchDetail(
            selected=wallet,
            primary=primary,
            robustness=tuple(chosen[n_primary:]),
            candidates_considered=len(pool),
        ))

    if not matches:
        raise MatchingInfeasible(
            "not one of the {} selected wallet(s) could be matched to {} primary controls of its "
            "own account type from a universe of {}. With no matched sets there is no benchmark "
            "and no null to permute — and an empty balance table would report itself as balanced, "
            "because every SMD in an empty mapping is below the {} target.".format(
                len(selected_wallets), n_primary, len(universe_wallets), SMD_BALANCE_TARGET
            )
        )

    unmatched_wallets = tuple(u.wallet for u in unmatched)
    balance = _balance(
        [records[m.selected] for m in matches],
        [records[c.wallet] for m in matches for c in m.primary],
        standardisation,
        unmatched_wallets,
    )
    robustness_slots = [records[c.wallet] for m in matches for c in m.robustness]
    robustness_balance = None
    if robustness_slots:
        robustness_balance = _balance(
            [records[m.selected] for m in matches],
            robustness_slots,
            standardisation,
            unmatched_wallets,
        )

    return MatchingResult(
        matches=tuple(matches),
        unmatched=tuple(unmatched),
        balance=balance,
        robustness_balance=robustness_balance,
        standardisation=standardisation,
        t0_block=t0_block,
        t0_timestamp=t0_timestamp,
        seed=seed,
        universe_size=len(universe_wallets),
        caliper=caliper,
    )


# -- covariate balance ----------------------------------------------------------


def standardised_mean_difference(selected_values, control_values, fallback_sd=None):
    """``(mean_t - mean_c) / sqrt((var_t + var_c) / 2)`` — the causal-inference standard.

    Population variances on both sides (see :func:`~matching_null.features.variance_of`).

    The zero-denominator branch is not an edge case here, it is the normal case for a dimension
    that a matched design has driven to a constant. Two situations, and they are not the same
    fact:

    * numerator zero as well — the groups agree exactly, which is perfect balance, so 0;
    * numerator non-zero — every selected wallet sits at one value and every control at another.
      That is *total* imbalance, and returning 0 for it would report the worst possible match as
      the best. The universe standard deviation is used as the ruler instead: a fixed scale that
      does not depend on which group a wallet landed in.
    """
    mean_t = mean_of(selected_values)
    mean_c = mean_of(control_values)
    with localcontext(CALCULATION_CONTEXT):
        numerator = +(mean_t - mean_c)
    pooled = sqrt_of(
        mean_of([variance_of(selected_values, mean_t), variance_of(control_values, mean_c)])
    )
    denominator = pooled
    if denominator == 0 and fallback_sd is not None:
        denominator = calc(fallback_sd)
    if denominator == 0:
        if numerator != 0:
            # Unreachable: both groups are drawn from the universe, so a universe with zero
            # spread forces equal means. Stated rather than assumed, because the alternative to
            # noticing it here is publishing a 0 for an infinitely imbalanced dimension.
            raise ValueError(
                "zero spread on a dimension whose group means differ by {}; the groups are not "
                "drawn from the universe they were standardised against".format(numerator)
            )
        return ZERO
    return divide(numerator, denominator)


def categorical_imbalance(selected_types, control_types):
    """The largest absolute category-proportion difference, for the one categorical dimension.

    Deliberately **not** a standardised difference. Standardising an indicator divides by its
    within-group spread, and under the exact-match caliper that spread is zero for every category
    in the normal case — so the standard formula's denominator is zero exactly when the matching
    worked. The proportion difference has no such problem: it is 0 under exact matching, it is
    bounded by 1, and it would blow straight through the 0.10 target the moment the caliper was
    relaxed. That is the behaviour a balance table needs from this row.
    """
    selected_types = list(selected_types)
    control_types = list(control_types)
    if not selected_types or not control_types:
        raise ValueError("cannot compare category proportions against an empty group")

    categories = sorted(set(selected_types) | set(control_types), key=lambda t: t.value)
    worst = ZERO
    for category in categories:
        share_t = divide(sum(1 for t in selected_types if t is category), len(selected_types))
        share_c = divide(sum(1 for t in control_types if t is category), len(control_types))
        with localcontext(CALCULATION_CONTEXT):
            gap = +(share_t - share_c)
        # ``copy_abs`` rather than ``abs``: the copy operations are the only ones in ``decimal``
        # defined to ignore the context entirely — no rounding, no flags. ``abs()`` is arithmetic
        # like every other operator and would round both sides to the ambient 28 digits before
        # comparing two gaps carried at 38, deciding which imbalance is the worst on a value
        # neither of them has.
        if gap.copy_abs() > worst.copy_abs():
            worst = gap
    return worst


def effective_sample_size(counts):
    """Kish's ESS: ``(sum w)^2 / sum w^2`` over the per-control use counts.

    Matching with replacement means the benchmark's nominal size overstates it. Five hundred
    control slots filled by fifty distinct wallets carry the information of about fifty, not five
    hundred, and this is the number that says so — ``unique_controls`` alone does not, because it
    cannot tell an even spread from one control carrying half the weight.
    """
    weights = [calc(c) for c in counts]
    if not weights:
        raise ValueError("effective sample size is undefined for an empty control set")
    with localcontext(CALCULATION_CONTEXT):
        total = ZERO
        square_total = ZERO
        for weight in weights:
            total += weight
            square_total += weight * weight
    # Both sums leave the block at 38 digits, and squaring the first of them outside it rounded
    # the product back to the ambient 28 — for counts whose square needs more than 28 digits the
    # quotient then moved in its 31st significant digit. ``mul`` holds the frozen context, so the
    # single rounding step is ``divide``'s.
    return divide(mul(total, total), square_total)


def _balance(selected_records, control_records, standardisation, unmatched_wallets):
    """Balance over control **slots**, not distinct controls.

    A control serving three selected wallets is compared against three selected wallets and
    therefore enters the benchmark three times. Collapsing it to one would compute the balance of
    a benchmark nobody is measured against.
    """
    smd = {CATEGORICAL_DIMENSION: categorical_imbalance(
        [r.account_type for r in selected_records],
        [r.account_type for r in control_records],
    )}
    for dimension in NUMERIC_DIMENSIONS:
        smd[dimension] = standardised_mean_difference(
            [r.values[dimension] for r in selected_records],
            [r.values[dimension] for r in control_records],
            fallback_sd=standardisation[dimension].sd,
        )
    if set(smd) != set(MATCHING_DIMENSIONS):
        # Not an assert: `python -O` strips those, and a balance table missing a row is a
        # confounder reported as absent rather than as unmeasured.
        raise ValueError(
            "balance table covers {} of the ten §6.6 dimensions".format(len(smd))
        )

    counts = {}
    for record in control_records:
        counts[record.wallet] = counts.get(record.wallet, 0) + 1
    slots = len(control_records)

    return CovariateBalance(
        smd=smd,
        unique_controls=len(counts),
        # The share of control slots filled by a wallet already used elsewhere. 0 when every
        # control is distinct; approaches 1 as the same few wallets carry the whole benchmark.
        control_reuse_rate=divide(slots - len(counts), slots),
        effective_sample_size=effective_sample_size(counts.values()),
        unmatched_selected=unmatched_wallets,
    )
