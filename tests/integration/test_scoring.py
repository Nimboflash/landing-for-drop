"""Realistic multi-step scenarios for ``scoring``.

These run the module the way the pipeline will: a basket of buys spread across the four §4.7 age
buckets, scored into a wallet-level ``buy_quality_30d``, compared bucket by bucket against an
activity-matched benchmark, and reduced to a window verdict — then written out as an artifact the
gate engine can read without importing any of this code.

Three wallets recur, and the difference between them is the whole point of §7.1:

* **the durable-edge wallet**, whose advantage sits in buckets C and D — the window passes;
* **the sniper**, whose mean advantage is larger and whose edge is almost entirely first-hour — the
  window fails as ``UNCOPYABLE_DOMINATED``, and no threshold rescues it;
* **the flat wallet**, whose total positive contribution is under 5 percentage points — the window
  fails as ``INDETERMINATE``, carrying no share at all.

USD amounts are the real ones and every value basis is stated, because §10 requires the realized /
marked / dead mix to arrive attached to the score rather than in a separate report.
"""

from decimal import Decimal, localcontext

import pytest

from contracts import (
    CALCULATION_CONTEXT,
    USDC,
    ClassificationStatus,
    EdgeOriginStatus,
    NetTradeResult,
    TokenAgeBucket,
    artifact_envelope,
    canonical_hash,
    canonicalise,
    quantize_ratio,
    to_canonical_json,
    verify_redundant_derived,
)
from scoring import (
    FIRST_HOUR_EDGE_SHARE_MAX,
    MIN_TOTAL_POSITIVE_EDGE,
    buy_outcome,
    buy_quality_detail,
    edge_origin,
    evaluate_window,
    score_window,
)

D = Decimal

A = TokenAgeBucket.A
B = TokenAgeBucket.B
C = TokenAgeBucket.C
DD = TokenAgeBucket.D

TOKEN = "0x" + "aa" * 20

#: The calibrated mean threshold starts at 15pp (§8.3). Not a sacred number, and not calibrated
#: here — the null distribution (ticket 40) sets the final one.
STARTING_MEAN_THRESHOLD = D("0.15")


def _wallet(n):
    return "0x{:040x}".format(n)


SELECTED = _wallet(0x11)
SNIPER = _wallet(0x33)
FLAT = _wallet(0x44)
BENCHMARK = _wallet(0x22)


def a_buy(owner, index, bucket):
    """A netted valid buy. 12-second slots, so block and timestamp stay paired (seam rule)."""
    return NetTradeResult(
        tx_hash="0x{:064x}".format(hash((owner, index)) & (2 ** 256 - 1)),
        portfolio_owner=owner,
        status=ClassificationStatus.VALID_BUY,
        sold_asset=USDC,
        bought_asset=TOKEN,
        sold_raw_amount=1_000_000,
        bought_raw_amount=10 ** 18,
        quote_asset=USDC,
        block_number=18_000_000 + index,
        timestamp=1_695_000_000 + 12 * index,
        token_age_bucket=bucket,
    )


def score(wallet, rows):
    """``rows`` are ``(bucket, trade_value_usd, return_pct, basis, basis_usd)``."""
    outcomes = []
    for index, (bucket, value_usd, return_pct, basis, basis_usd) in enumerate(rows):
        outcomes.append(
            buy_outcome(
                a_buy(wallet, index, bucket),
                trade_value_usd=D(value_usd),
                return_pct=D(return_pct),
                **{basis: D(basis_usd)}
            )
        )
    return buy_quality_detail(outcomes, wallet)


#: The activity-matched benchmark: same shape of book, ordinary results.
BENCHMARK_ROWS = [
    (A, "1800", "1.50", "realized_usd", "4500"),
    (B, "1200", "0.70", "marked_usd", "2040"),
    (C, "7000", "0.10", "realized_usd", "7700"),
    (C, "4000", "-0.20", "marked_usd", "3200"),
    (DD, "18000", "0.05", "realized_usd", "18900"),
    (DD, "11000", "0.02", "marked_usd", "11220"),
    (DD, "8000", "-0.10", "realized_usd", "7200"),
]

#: The edge lives in the mature buckets: the first-hour buys barely beat the benchmark.
DURABLE_ROWS = [
    (A, "2000", "1.55", "realized_usd", "5100"),
    (B, "1500", "0.72", "marked_usd", "2580"),
    (C, "8000", "0.40", "realized_usd", "11200"),
    (C, "5000", "-0.30", "marked_usd", "3500"),
    (DD, "20000", "0.25", "realized_usd", "25000"),
    (DD, "12000", "0.10", "marked_usd", "13200"),
    (DD, "9000", "-0.15", "realized_usd", "7650"),
]

#: The same book, except the first-hour buys are enormous winners and the rest is ordinary. This is
#: the population the copyability engine exists to remove.
SNIPER_ROWS = [
    (A, "2000", "2.30", "realized_usd", "6600"),
    (B, "1500", "1.20", "marked_usd", "3300"),
    (C, "8000", "0.12", "realized_usd", "8960"),
    (C, "4000", "-0.19", "marked_usd", "3240"),
    (DD, "18000", "0.06", "realized_usd", "19080"),
    (DD, "11000", "0.03", "marked_usd", "11330"),
    (DD, "8000", "-0.09", "realized_usd", "7280"),
]

#: Beats the benchmark everywhere, by almost nothing.
FLAT_ROWS = [
    (A, "1800", "1.51", "realized_usd", "4530"),
    (B, "1200", "0.71", "marked_usd", "2052"),
    (C, "7000", "0.11", "realized_usd", "7770"),
    (C, "4000", "-0.19", "marked_usd", "3240"),
    (DD, "18000", "0.06", "realized_usd", "19080"),
    (DD, "11000", "0.03", "marked_usd", "11330"),
    (DD, "8000", "-0.09", "realized_usd", "7280"),
]


@pytest.fixture(scope="module")
def benchmark():
    return score(BENCHMARK, BENCHMARK_ROWS)


@pytest.fixture(scope="module")
def durable(benchmark):
    return score(SELECTED, DURABLE_ROWS)


@pytest.fixture(scope="module")
def sniper():
    return score(SNIPER, SNIPER_ROWS)


@pytest.fixture(scope="module")
def flat():
    return score(FLAT, FLAT_ROWS)


# -- the wallet score -----------------------------------------------------------


def test_a_wallet_scores_across_all_four_buckets(durable):
    assert durable.n_buys == 7
    by_bucket = {b.bucket: b for b in durable.buckets}

    assert [by_bucket[b].n_buys for b in (A, B, C, DD)] == [1, 1, 2, 3]
    # Log weighting: the three D-bucket buys are 41,000 of 47,500 dollars but under half the weight.
    assert by_bucket[DD].weight_share < D("0.5")


def test_the_section_ten_mix_travels_with_the_score(durable):
    """"If only 20% of volume is realized and 80% rests on marking, the gate result lacks
    credibility even if it looks strongly positive." So the mix is on the score, not beside it."""
    quality = durable.quality

    total = quality.realized_share + quality.marked_share + quality.dead_share

    assert quality.realized_share > D("0.6")
    assert quality.marked_share > D("0")
    assert abs(total - D("1")) < D("1e-30")
    assert durable.basis_total_usd == D("68230")
    assert durable.basis_unaccounted_buys == 0


def test_a_score_resting_mostly_on_marking_says_so():
    """The same headline number, reported very differently."""
    mostly_marked = score(
        _wallet(0x55),
        [
            (DD, "10000", "0.30", "realized_usd", "2600"),
            (DD, "40000", "0.30", "marked_usd", "10400"),
        ],
    )

    assert mostly_marked.quality.realized_share == D("0.2")
    assert mostly_marked.quality.marked_share == D("0.8")
    # The score itself is untouched by the mix; that is exactly why the mix has to be reported.
    assert quantize_ratio(mostly_marked.value) == quantize_ratio(D("0.3"))


# -- a window that passes -------------------------------------------------------


def test_a_durable_edge_wallet_passes_its_window(durable, benchmark):
    origin = edge_origin(durable.quality, benchmark.quality)
    evaluation = evaluate_window(
        1, "leader", [durable.value - benchmark.value, D("0.22"), D("0.17")], origin
    )

    assert origin.status is EdgeOriginStatus.VALID
    assert origin.share < FIRST_HOUR_EDGE_SHARE_MAX
    assert origin.total_positive_contribution >= MIN_TOTAL_POSITIVE_EDGE
    assert evaluation.passes(STARTING_MEAN_THRESHOLD)


def test_the_advantage_is_concentrated_in_the_mature_buckets(durable, benchmark):
    origin = edge_origin(durable.quality, benchmark.quality)
    by_bucket = {row.bucket: row for row in origin.buckets}

    assert by_bucket[DD].contribution > by_bucket[A].contribution
    assert by_bucket[DD].contribution > by_bucket[B].contribution
    assert origin.first_hour_contribution < origin.total_positive_contribution


# -- a window that fails on where the edge came from ----------------------------


def test_a_sniper_fails_the_window_however_large_the_advantage(sniper, benchmark):
    """A hard failure, not a warning. §7.1: wallets that buy in the first block of a token's life
    and hold are exactly the population Phase 2's copyability engine would remove, so a gate pass
    driven by them would evaporate the moment that engine is switched on."""
    origin = edge_origin(sniper.quality, benchmark.quality)
    evaluation = evaluate_window(1, "leader", [D("5"), D("5"), D("5")], origin)

    assert origin.status is EdgeOriginStatus.UNCOPYABLE_DOMINATED
    assert origin.share > FIRST_HOUR_EDGE_SHARE_MAX
    assert evaluation.mean_advantage == D("5")  # conditions 1 and 2 pass by a mile
    assert evaluation.median_advantage == D("5")
    assert not evaluation.passes(STARTING_MEAN_THRESHOLD)
    assert not evaluation.passes(D("-1000"))  # no threshold rescues it


def test_the_sniper_beats_the_durable_wallet_on_the_headline_number(sniper, durable):
    """Which is the point. The condition is not a tie-breaker among good scores; it removes a
    score that looks better than the one it fails against."""
    assert sniper.value > durable.value


def test_bucket_a_is_reported_in_isolation_beside_the_first_hour_gate(sniper, benchmark):
    """Ticket 32: the gate applies to A+B; A alone is a diagnostic and cannot change the verdict."""
    origin = edge_origin(sniper.quality, benchmark.quality)

    assert origin.bucket_a_contribution <= origin.first_hour_contribution
    assert origin.bucket_a_share <= origin.share
    assert origin.status is EdgeOriginStatus.UNCOPYABLE_DOMINATED


# -- a window that fails because it could not be measured -----------------------


def test_a_flat_window_is_indeterminate_and_carries_no_share(flat, benchmark):
    """The most dangerous bug in the project, exercised end to end.

    Every bucket beats the benchmark, so a naive implementation reports a small, tidy, entirely
    passing first-hour share. There is not enough edge to attribute, so there is no share.
    """
    origin = edge_origin(flat.quality, benchmark.quality)
    evaluation = evaluate_window(1, "leader", [D("0.30"), D("0.28"), D("0.35")], origin)

    assert all(row.contribution >= 0 for row in origin.buckets)
    assert origin.total_positive_contribution < MIN_TOTAL_POSITIVE_EDGE
    assert origin.share is None
    assert origin.status is EdgeOriginStatus.INDETERMINATE
    assert evaluation.score.first_hour_edge_share is None
    assert not evaluation.passes(STARTING_MEAN_THRESHOLD)


def test_an_indeterminate_window_is_a_failure_not_an_abstention(flat, benchmark):
    origin = edge_origin(flat.quality, benchmark.quality)
    score_ = score_window(1, "leader", [D("9")], origin)

    assert not score_.edge_origin_status.passes
    assert not score_.passes(D("0"))
    assert not score_.passes(D("-99"))


# -- four windows, the §7.4 shape ----------------------------------------------


def test_three_of_four_windows_pass_and_the_fourth_is_unmeasurable(durable, flat, benchmark):
    """§7: at least 3 of 4 windows must pass. An INDETERMINATE window does not count toward them."""
    durable_origin = edge_origin(durable.quality, benchmark.quality)
    flat_origin = edge_origin(flat.quality, benchmark.quality)

    windows = [
        score_window(1, "leader", [D("0.31"), D("0.22"), D("0.17")], durable_origin),
        score_window(2, "leader", [D("0.28"), D("0.19"), D("0.21")], durable_origin),
        score_window(3, "leader", [D("0.24"), D("0.16"), D("0.30")], durable_origin),
        score_window(4, "leader", [D("0.40"), D("0.38"), D("0.44")], flat_origin),
    ]

    passed = [w for w in windows if w.passes(STARTING_MEAN_THRESHOLD)]

    assert len(passed) == 3
    assert windows[3].edge_origin_status is EdgeOriginStatus.INDETERMINATE
    # The unmeasurable window has the largest mean advantage of the four and still does not count.
    assert windows[3].mean_advantage > max(w.mean_advantage for w in windows[:3])


def test_both_columns_are_scored_the_same_way(durable, benchmark):
    """§7.1 runs twice: the leader's raw metric and the follower-adjusted one. Same three
    conditions, same Edge Origin decomposition, different inputs."""
    origin = edge_origin(durable.quality, benchmark.quality)
    advantages = [D("0.31"), D("0.22"), D("0.17")]

    leader = score_window(1, "leader", advantages, origin)
    follower = score_window(1, "follower_adjusted", advantages, origin)

    assert leader.column == "leader" and follower.column == "follower_adjusted"
    assert leader.mean_advantage == follower.mean_advantage
    assert leader.passes(STARTING_MEAN_THRESHOLD) is follower.passes(STARTING_MEAN_THRESHOLD)


# -- artifacts ------------------------------------------------------------------


def test_a_window_artifact_is_byte_stable_and_hashes_the_same_twice(durable, benchmark):
    """``gate_validation`` reads these files and never imports the code that wrote one."""
    origin = edge_origin(durable.quality, benchmark.quality)
    evaluation = evaluate_window(1, "leader", [D("0.31"), D("0.22"), D("0.17")], origin)

    first = artifact_envelope("window_score", "scoring", evaluation.score)
    second = artifact_envelope("window_score", "scoring", evaluation.score)

    assert first == second
    assert first["payload_hash"] == second["payload_hash"]
    assert canonical_hash(evaluation.score) == canonical_hash(
        score_window(1, "leader", [D("0.31"), D("0.22"), D("0.17")], origin)
    )


def test_rescoring_the_same_basket_produces_an_identical_artifact():
    """§9.2 requires the number to be reproducible from a fixed event set."""
    assert canonical_hash(score(SELECTED, DURABLE_ROWS).quality) == canonical_hash(
        score(SELECTED, DURABLE_ROWS).quality
    )


def test_the_decomposition_is_a_redundant_assertion_not_an_authority(durable, benchmark):
    """A derived field in an artifact is never authoritative; the primitives are.

    Recomputed at a tolerance rather than exactly, because ``canonicalise`` renders through
    ``Decimal.normalize()`` at the ambient 28-digit context while the values are carried at the
    frozen 38 — so the artifact's own strings are already 28-digit. 1e-20 is nine orders of
    magnitude inside §9.2's 0.5 percentage-point acceptance for buy quality.
    """
    origin = edge_origin(durable.quality, benchmark.quality)
    payload = canonicalise(origin)

    def recompute_total(body):
        with localcontext(CALCULATION_CONTEXT):
            total = D("0")
            for row in body["buckets"]:  # already in BUCKET_ORDER
                total += D(row["contribution"])
            return +total

    def recompute_share(body):
        with localcontext(CALCULATION_CONTEXT):
            total = recompute_total(body)
            if total < MIN_TOTAL_POSITIVE_EDGE:
                return None
            return +(D(body["first_hour_contribution"]) / total)

    assert verify_redundant_derived(
        payload,
        {"total_positive_contribution": recompute_total, "share": recompute_share},
        tolerance=D("1e-20"),
    )


def test_an_indeterminate_share_is_null_in_the_artifact_and_never_zero(flat, benchmark):
    origin = edge_origin(flat.quality, benchmark.quality)
    rendered = to_canonical_json(score_window(4, "leader", [D("0.4")], origin))

    assert '"first_hour_edge_share":null' in rendered
    assert '"first_hour_edge_share":"0"' not in rendered
    assert '"edge_origin_status":"INDETERMINATE"' in rendered


def test_every_scoring_output_survives_canonical_serialization(durable, benchmark):
    origin = edge_origin(durable.quality, benchmark.quality)
    evaluation = evaluate_window(1, "leader", [D("0.31"), D("0.22")], origin)

    for payload in (durable, durable.quality, origin, evaluation, evaluation.score):
        assert to_canonical_json(payload) == to_canonical_json(payload)
