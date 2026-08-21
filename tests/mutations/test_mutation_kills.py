"""Mutation kill harness — does the suite actually catch the bugs that matter?

"703 passing" is a statement about the tests, not about the code. The question this file answers is
the only one that matters before a gate decision is published: **if someone introduced the specific
one-character bug that turns a failed hypothesis into a green dashboard, would anything go red?**

Each mutation below is a bug that (a) is easy to write, (b) leaves every type check, every lint and
every docstring intact, and (c) moves the answer in the direction that flatters the hypothesis. A
mutation that survives the suite is not a curiosity — it is a hole through which exactly that bug
could reach a published GO.

How a case runs:

    1. copy ``src/``, ``tests/`` and ``pyproject.toml`` to a temp workspace   (the working tree is
       never touched)
    2. apply the mutation as a source transformation    (anchored by search, never by line number)
    3. run the relevant test files *from that workspace* in a subprocess
    4. assert the run FAILED

Step 1 copies the tests as well as the source, and that is not tidiness. The module
``tests/test_shared_purity`` does this at import time::

    SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    if SRC not in sys.path:
        sys.path.insert(0, SRC)

which pins ``contracts`` to the repository's own source no matter what ``PYTHONPATH`` or
``-o pythonpath=`` say — and because it lands at ``sys.path[0]`` before any other test module is
imported, it pins it for *every* file sharing the process. Pointing an interpreter at a mutated
``src`` while running the repository's ``tests`` therefore silently exercises the pristine code: the
first draft of this harness reported all ten ``contracts`` mutations as dead for exactly that
reason. Copying the whole tree keeps that computed path inside the workspace, where it resolves to
the mutated source and the run means what it says.

The control cases below exist so that this class of failure cannot pass unnoticed: they run each
selection against an *unmutated* workspace through the same machinery and require it to be green, so
a "kill" can never be an artefact of a broken harness.

**A surviving mutation leaves a failing test here on purpose.** Downgrading it to a skip or an xfail
would convert a known hole in the suite into a silent one, which is the same class of error the
harness exists to detect.

Known survivors when this file was written — 17 of the 19 die, and these two do not:

    15-fill-ratio-inverted             CopySimulation.fill_ratio, numerator and denominator swapped
    19-fill-ratio-measures-the-shortfall   the same field reporting ``intended - filled``

Both were re-run against the **entire** suite, not merely their selection, and all 703 tests still
passed. Nothing anywhere evaluated ``CopySimulation.fill_ratio``: ``test_shared_purity`` proves it
is pure algebra without ever asking what the algebra says, ``depth`` asserts on the identically
named field of ``OrderBookFill``, and ``gate_validation`` recomputes a ``fill_ratio`` of its own
from an artifact payload. Three files mentioned the name; none pinned the value.

**Both are now killed** by ``tests/hand_computed/test_contracts_derived.py``, which asserts the
value directly. Worth recording that the gap was invisible to every proxy for coverage: the field
was exercised, named in three test files, and provably pure — and still meant nothing.

The second round: the four newest components
--------------------------------------------

Mutations 1-26 cover ``contracts``, ``depth``, ``fifo``, ``gate_validation``, ``marking``,
``matching_null``, ``netting`` and ``scoring``. They touched none of ``src/pipeline``,
``src/reporting``, ``src/phase0`` or ``tests/known_answer`` — the newest and least-reviewed code in
the repository, and the only code between a stage's output and a published gate decision. "1,417
passing including mutations" was therefore a true statement that said nothing at all about them,
which is the exact shape of a coverage claim worth distrusting.

Sixteen more close that — 27-42, less the one renumbered ``E1`` for the reason given below. Ten
died on arrival; **six survived**, and the six are the interesting part:

    27  a netting quarantine reporting $0 instead of an unknown cost
    28  the canonical ``(block, tx_hash)`` sort of the results tuple, deleted
    29  the two halves of ``UNSUPPORTED`` collapsed into one status count
    33  ``DiagnosticPack`` validating the constant instead of its own label
    35  a wallet's quality quantized on the way *into* the mean
    E1  scored notional including wallets nobody could score

Five of the six had a test *named* for the behaviour sitting a few lines away, and each was blind
for a different reason worth remembering:

* 27 — ``test_an_unpriceable_queue_entry_is_none_and_not_a_zero`` builds the ``QuarantineQueue`` by
  hand, so it pins the dataclass and never executes the branch that produces the record. Netting's
  only refusal needs the seam bypassed to reach, so the composition's netting-quarantine path had
  never run at all;
* 28 — the property test shuffles the input and compares the *aggregates*. Those agree on small
  fixtures whatever the order; the ordering itself was unasserted;
* 29 — ``unsupported_from_pricing`` was exercised only at zero, and a count that is never non-zero
  is a count nobody has checked;
* 33 — the identical rule was pinned on a single ``Diagnostic`` and not on the collection;
* 35 — ``test_copy_retention_is_aggregated_before_it_is_rendered`` pins exactly this rule for
  Copy Retention. The three means beside it, in the same function, were unpinned.

All five are now killed by tests added to ``hand_computed/test_pipeline.py`` and
``hand_computed/test_reporting.py``. **E1 is not, and cannot be**: it is an equivalent mutant, kept
below under an inverted assertion. See :data:`EQUIVALENT`.

The third round: an invariant nobody had written down
-----------------------------------------------------

43 and 44 are a different shape from everything above them. The first forty-two mutate a rule the
code states — a bound, a conjunction, a sort key — and ask whether the suite reads it. These two
mutate a rule the code *relied on without stating*: that one ``tx_hash`` means one transaction.
Nothing established it, four dictionaries and three sets were keyed on it, and the result was a
composition that pooled two transactions into one and published the pooled number with §10's
credibility mix reporting full confidence in it.

44 is the more useful of the two to keep. It is not a bug anyone would write from scratch; it is
what the repair looks like when the traced case is read as the specification, and this file exists
partly to make that particular failure expensive.

The fourth round: the candidate universe
----------------------------------------

50-65 cover ``src/universe`` — tickets 25-28, the stage that decides which accounts exist as far as
the experiment is concerned. All sixteen died on arrival, which is a weaker claim than it looks and
is worth stating as such: the package arrived with its tests written against it in the same round,
so this is evidence that the tests read the code rather than evidence that they would have caught a
bug introduced later by somebody else.

Three of the sixteen are a shape this file had not used before. 63, 64 and 65 mutate ``src/`` in
ways only a **static** check can see — an import edge — and their test selection is that static
check alone. ``tests/test_post_t0_barrier.py`` and ``tests/test_lane_independence.py`` both carry
"guard the guard" fixtures that build violating modules under ``tmp_path``, and both were green
before these cases existed. What the cases add is the only thing those fixtures cannot supply:
evidence that the rule fires against the **real tree**, not merely against a module the test wrote
itself. A structural rule whose sole evidence is its own fixtures is a rule about fixtures.

65 is the one to keep if only one survives review. It is not invented: it restores, line for line,
the ``_liveness`` filter that was committed in ``src/universe/select.py`` at fca51e3 and that every
one of the barrier's rules 1-9 passed while preferring wallets that were still trading after T0.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, Tuple

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
TESTS = os.path.join(REPO, "tests")

#: Copied into every workspace alongside ``src`` and ``tests``. ``tools/tracer_bullet.py`` is an
#: entry point rather than library source, but it is the only caller that drives the real
#: composition root over committed mainnet bytes — so the tests that pin ticket 19's findings
#: import it, and a workspace without it collects nothing rather than running green. Not mutated by
#: any case here; present so a selection may name a test that needs it.
TOOLS = os.path.join(REPO, "tools")

#: A mutant run that has not finished by now is not a slow test, it is a hang — a mutation that
#: removes a loop bound would otherwise stall the suite instead of reporting.
RUN_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class Edit:
    """One exact source substitution, located by content.

    ``occurrences`` is checked before anything is replaced. If the count is wrong the case fails
    loudly naming the file, because "the anchor moved" and "the mutation was applied" must never be
    confused: a silently unapplied mutation would be reported as a kill by a suite that did nothing.

    ``tree`` is ``src`` or ``tests``. The second exists because ``tests/known_answer`` is not a test
    *of* the machine, it is a frozen artifact *of* it: §9.6 hashes the sixteen cases into the freeze
    manifest, and a battery that can silently lose a case or hash a subset of itself is the same
    class of defect as a source bug — it just happens to live under ``tests/``. Mutating it is the
    only way to ask whether anything would notice.
    """

    relpath: str
    find: str
    replace: str
    occurrences: int = 1
    tree: str = "src"


@dataclass(frozen=True)
class Mutation:
    """One plausible bug, the tests that should notice, and what a survival would mean."""

    id: str
    bug: str
    survival_means: str
    edits: Tuple[Edit, ...]
    tests: Tuple[str, ...]


# -- 1-9: gate and pipeline -----------------------------------------------------

GATE_AND_PIPELINE = (
    Mutation(
        id="01-indeterminate-share-becomes-zero",
        bug="the small-denominator guard reports first_hour_edge_share=0 instead of None",
        survival_means=(
            "an unmeasurable window would carry a share of zero, and zero passes the <=40% "
            "condition — the single most dangerous bug in the scoring path, converting 'we could "
            "not measure this' into 'this passed'"
        ),
        edits=(
            Edit(
                relpath="scoring/edge.py",
                find="        share = None\n        status = EdgeOriginStatus.INDETERMINATE\n",
                replace='        share = Decimal("0")\n'
                        "        status = EdgeOriginStatus.INDETERMINATE\n",
            ),
        ),
        tests=("hand_computed/test_scoring.py", "integration/test_scoring.py"),
    ),
    Mutation(
        id="02-dead-pool-conjunction-becomes-or",
        bug="the §9.1 three-way dead-pool conjunction becomes a disjunction",
        survival_means=(
            "any one condition alone would zero a position: a pool quiet for 30 days but still "
            "exitable, or a token whose liquidity migrated, would be marked -100%"
        ),
        edits=(
            Edit(
                relpath="marking/mark.py",
                find="    if all(held for _name, held in conditions):",
                replace="    if any(held for _name, held in conditions):",
            ),
        ),
        tests=("hand_computed/test_marking.py", "integration/test_marking.py"),
    ),
    Mutation(
        id="03-owner-transfer-filter-removed",
        bug="step 3, the owner-touching transfer filter, is deleted from _owner_flows",
        survival_means=(
            "someone else's transfers in the same transaction would enter the owner's netted "
            "balance change, and an MEV bundle would still read as an ordinary trade"
        ),
        edits=(
            Edit(
                relpath="netting/balance.py",
                find="        if owner != t.from_addr and owner != t.to_addr:\n"
                     "            continue  # step 3 — someone else's money in the same "
                     "transaction\n",
                replace="",
            ),
        ),
        tests=("hand_computed/test_netting.py", "integration/test_netting.py"),
    ),
    Mutation(
        id="04-above-tolerance-residual-not-quarantined",
        bug="a single surviving above-tolerance leg is booked as circular arbitrage instead of "
            "being quarantined",
        survival_means=(
            "an unexplained movement would be absorbed into a settled exclusion and never reach "
            "the reconciliation queue — addendum §8 requires it be neither included nor dropped"
        ),
        edits=(
            Edit(
                relpath="netting/balance.py",
                find="            status=ClassificationStatus.ABOVE_TOLERANCE_RESIDUAL,",
                replace="            status=ClassificationStatus.CIRCULAR_ARBITRAGE,",
            ),
        ),
        tests=("hand_computed/test_netting.py", "integration/test_netting.py"),
    ),
    Mutation(
        id="05-long-tail-returns-zero-capacity",
        bug="cost_cap_for returns a zero cap for LONG_TAIL instead of raising "
            "LongTailExcludedError",
        survival_means=(
            "an out-of-scope modelling decision would be published as a measurement: measured "
            "long-tail capacity really was $0, so a returned zero is indistinguishable from that "
            "finding"
        ),
        edits=(
            Edit(
                relpath="depth/execution.py",
                find="    if tier is AssetTier.LONG_TAIL:\n"
                     "        raise LongTailExcludedError(\n"
                     '            "long-tail assets are excluded from Ethereum Phase 0 (addendum '
                     '§9.5). Refusing to "\n'
                     '            "return a capacity of zero: measured long-tail capacity really '
                     'was $0 at every edge "\n'
                     '            "level, so a zero here would be read downstream as that finding '
                     'rather than as an "\n'
                     '            "out-of-scope modelling decision."\n'
                     "        )\n",
                replace="    if tier is AssetTier.LONG_TAIL:\n        return ZERO\n",
            ),
        ),
        tests=("hand_computed/test_depth.py",),
    ),
    Mutation(
        id="06-edge-origin-boundary-becomes-exclusive",
        bug="the Edge Origin boundary changes from '<= 40% passes' to '< 40% passes'",
        survival_means=(
            "the pre-registered boundary is untested at the boundary, so §7.1 condition 3 could be "
            "silently redefined after the fact and no window would change hands visibly"
        ),
        edits=(
            Edit(
                relpath="scoring/edge.py",
                find="            if share > FIRST_HOUR_EDGE_SHARE_MAX",
                replace="            if share >= FIRST_HOUR_EDGE_SHARE_MAX",
            ),
        ),
        tests=("hand_computed/test_scoring.py", "integration/test_scoring.py"),
    ),
    Mutation(
        id="07-negative-bucket-contribution-allowed",
        bug="the max(0, ...) guard on a bucket's edge contribution is removed",
        survival_means=(
            "a bucket that lost to the benchmark would enter the denominator as a negative number, "
            "so the first-hour share would depend on which direction the losses fell rather than "
            "on where the edge came from"
        ),
        edits=(
            Edit(
                relpath="scoring/edge.py",
                find="    if contribution <= 0:\n"
                     "        # max(0, ...). The comparison is <= rather than < so that a negative "
                     "zero, which Decimal\n"
                     "        # produces from a negative advantage times a zero weight, is "
                     "normalised away before it can\n"
                     '        # serialize as "-0".\n'
                     "        contribution = ZERO\n",
                replace="",
            ),
        ),
        tests=("hand_computed/test_scoring.py", "integration/test_scoring.py"),
    ),
    Mutation(
        id="08-pre-t0-boundary-becomes-exclusive",
        bug="the look-ahead guard accepts a feature computed exactly at T0 (>= becomes >)",
        survival_means=(
            "a feature measured at T0 has already seen T0; it does not crash and does not look "
            "wrong, it makes the matched sets fit the outcome and voids every number downstream"
        ),
        edits=(
            Edit(
                relpath="matching_null/features.py",
                find=">= t0_block:",
                replace="> t0_block:",
                occurrences=2,
            ),
        ),
        tests=("hand_computed/test_matching_null.py", "integration/test_matching_null.py"),
    ),
    Mutation(
        id="09-go-ignores-capital-feasibility",
        bug="the outcome map emits GO without consulting capital_feasibility_failed",
        survival_means=(
            "a positive raw edge would conceal an execution-capacity failure — §7.5's whole reason "
            "for having three outcomes rather than two"
        ),
        edits=(
            Edit(
                relpath="gate_validation/decision.py",
                find="    if both_gates_pass and not capital_failed:",
                replace="    if both_gates_pass:",
            ),
        ),
        tests=("hand_computed/test_gate_validation.py", "integration/test_gate_validation.py"),
    ),
)


# -- 10-14: LotConsumption.realized_return --------------------------------------

_REALIZED_RETURN = '        return sub(divide(self.proceeds_usd, self.allocated_cost_usd), Decimal("1"))'

_ALLOCATED_COST_GUARD = (
    "        if self.allocated_cost_usd <= 0:\n"
    "            raise ValueError(\n"
    '                "allocated_cost_usd must be > 0; a zero or negative buy cost makes the return "\n'
    '                "undefined, and that is a classification the domain module must make rather "\n'
    '                "than something realized_return silently absorbs"\n'
    "            )\n"
)

REALIZED_RETURN_TESTS = (
    "test_shared_purity.py",
    "hand_computed/test_fifo.py",
    "integration/test_fifo.py",
)

REALIZED_RETURN = (
    Mutation(
        id="10-realized-return-inverted",
        bug="realized_return divides cost by proceeds instead of proceeds by cost",
        survival_means="every realized return in the metric is the wrong way up",
        edits=(
            Edit(
                relpath="contracts/trades.py",
                find=_REALIZED_RETURN,
                replace='        return sub(divide(self.allocated_cost_usd, self.proceeds_usd), '
                        'Decimal("1"))',
            ),
        ),
        tests=REALIZED_RETURN_TESTS,
    ),
    Mutation(
        id="11-realized-return-keeps-the-one",
        bug="the ``- 1`` is dropped, so a return becomes a gross multiple",
        survival_means=(
            "a break-even trade would report +100% and every buy quality would be inflated by "
            "exactly one"
        ),
        edits=(
            Edit(
                relpath="contracts/trades.py",
                find=_REALIZED_RETURN,
                replace="        return divide(self.proceeds_usd, self.allocated_cost_usd)",
            ),
        ),
        tests=REALIZED_RETURN_TESTS,
    ),
    Mutation(
        id="12-realized-return-quantized-before-subtraction",
        bug="the ratio is quantized to the reporting scale before the ``- 1``",
        survival_means=(
            "an output scale would be baked into an internal value, and §9.2's requirement that a "
            "reviewer re-derive the number would silently move to 8dp"
        ),
        edits=(
            Edit(
                relpath="contracts/trades.py",
                find="from .numeric import divide, sub",
                replace="from .numeric import divide, quantize_ratio, sub",
            ),
            Edit(
                relpath="contracts/trades.py",
                find=_REALIZED_RETURN,
                replace="        return sub(quantize_ratio(divide(self.proceeds_usd, "
                        'self.allocated_cost_usd)), Decimal("1"))',
            ),
        ),
        tests=REALIZED_RETURN_TESTS,
    ),
    Mutation(
        id="13-realized-return-through-float",
        bug="one operand is converted to float on the way into the division",
        survival_means=(
            "the seam's never-float rule would hold everywhere except inside the projection every "
            "lane inherits"
        ),
        edits=(
            Edit(
                relpath="contracts/trades.py",
                find=_REALIZED_RETURN,
                replace="        return sub(divide(float(self.proceeds_usd), "
                        'self.allocated_cost_usd), Decimal("1"))',
            ),
        ),
        tests=REALIZED_RETURN_TESTS,
    ),
    Mutation(
        id="14-realized-return-zero-denominator-fallback",
        bug="the construction guard is removed and the projection returns zero on a zero cost",
        survival_means=(
            "a mispriced buy leg would report a flat 0% return — a measurement nobody made — "
            "instead of forcing the domain module to classify it"
        ),
        edits=(
            Edit(relpath="contracts/trades.py", find=_ALLOCATED_COST_GUARD, replace=""),
            Edit(
                relpath="contracts/trades.py",
                find=_REALIZED_RETURN,
                replace="        if self.allocated_cost_usd == 0:\n"
                        '            return Decimal("0")\n' + _REALIZED_RETURN,
            ),
        ),
        tests=REALIZED_RETURN_TESTS,
    ),
)


# -- 15-19: CopySimulation.fill_ratio -------------------------------------------

_FILL_RATIO = "        return divide(self.filled_order_usd, self.intended_order_usd)"

_OVERFILL_GUARD = (
    '        if not (Decimal("0") <= self.filled_order_usd <= self.intended_order_usd):\n'
    "            raise ValueError(\n"
    '                "filled_order_usd must lie in [0, intended_order_usd]; got {} against {}. "\n'
    '                "Over-fill is rejected at construction rather than clamped, because a clamp "\n'
    '                "would hide the modelling error that produced it.".format(\n'
    "                    self.filled_order_usd, self.intended_order_usd\n"
    "                )\n"
    "            )\n"
)

_INTENDED_GUARD = (
    "        if self.intended_order_usd <= 0:\n"
    "            raise ValueError(\n"
    '                "intended_order_usd must be > 0; an order of zero size is not a simulation "\n'
    '                "outcome, it is a caller error"\n'
    "            )\n"
)

FILL_RATIO_TESTS = (
    # Added after this harness first reported 15 and 19 as survivors. The three files below all
    # mention fill_ratio and none of them pinned its value — purity checks the expression's shape,
    # depth asserts on OrderBookFill's identically named field, and gate_validation recomputes its
    # own from an artifact. The hand-computed file is the one that actually asserts what the
    # projection returns.
    "hand_computed/test_contracts_derived.py",
    "test_shared_purity.py",
    "hand_computed/test_depth.py",
    "integration/test_gate_validation.py",
)

FILL_RATIO = (
    Mutation(
        id="15-fill-ratio-inverted",
        bug="fill_ratio divides intended by filled instead of filled by intended",
        survival_means=(
            "a half-filled order would report a fill ratio of 2, and §9.4's 90%-fill rule would be "
            "applied to a number that is not a fill ratio"
        ),
        edits=(
            Edit(
                relpath="contracts/metrics.py",
                find=_FILL_RATIO,
                replace="        return divide(self.intended_order_usd, self.filled_order_usd)",
            ),
        ),
        tests=FILL_RATIO_TESTS,
    ),
    Mutation(
        id="16-fill-ratio-clamped-instead-of-rejected",
        bug="over-fill is clamped in the projection instead of refused at construction",
        survival_means=(
            "a modelling error that fills more than was ordered would be hidden behind a tidy 1.0 "
            "rather than raising where it was produced"
        ),
        edits=(
            Edit(relpath="contracts/metrics.py", find=_OVERFILL_GUARD, replace=""),
            Edit(
                relpath="contracts/metrics.py",
                find=_FILL_RATIO,
                replace='        return min(Decimal("1"), divide(self.filled_order_usd, '
                        "self.intended_order_usd))",
            ),
        ),
        tests=FILL_RATIO_TESTS,
    ),
    Mutation(
        id="17-fill-ratio-quantized",
        bug="fill_ratio is quantized to two decimals inside the projection",
        survival_means=(
            "an 89.6% fill would round to 0.90 and clear the §9.4 minimum — a reporting scale "
            "deciding an executability rule"
        ),
        edits=(
            Edit(
                relpath="contracts/metrics.py",
                find=_FILL_RATIO,
                replace="        return divide(self.filled_order_usd, "
                        'self.intended_order_usd).quantize(Decimal("0.01"))',
            ),
        ),
        tests=FILL_RATIO_TESTS,
    ),
    Mutation(
        id="18-fill-ratio-one-on-zero-order",
        bug="the construction guard is removed and the projection returns 1 on a zero order",
        survival_means=(
            "an order of zero size — a caller error — would be reported as a perfect fill, the "
            "friendliest possible reading of an impossible trade"
        ),
        edits=(
            Edit(relpath="contracts/metrics.py", find=_INTENDED_GUARD, replace=""),
            Edit(
                relpath="contracts/metrics.py",
                find=_FILL_RATIO,
                replace="        if self.intended_order_usd == 0:\n"
                        '            return Decimal("1")\n' + _FILL_RATIO,
            ),
        ),
        tests=FILL_RATIO_TESTS,
    ),
    Mutation(
        id="19-fill-ratio-measures-the-shortfall",
        bug="the numerator becomes intended - filled, so the field reports its own complement",
        survival_means=(
            "a fully filled order would report a fill ratio of zero and an unfilled one 1.0; the "
            "field's name would be the only thing still saying what it means"
        ),
        edits=(
            # No import edit: ``sub`` is imported by metrics.py already, since BuyQuality's
            # share-sum invariant now uses it. This mutation previously anchored on the exact
            # import line and broke when that line gained ``add, sub`` — the anchor check caught
            # it, which is what the anchor check is for.
            Edit(
                relpath="contracts/metrics.py",
                find=_FILL_RATIO,
                replace="        return divide(sub(self.intended_order_usd, "
                        "self.filled_order_usd), self.intended_order_usd)",
            ),
        ),
        tests=FILL_RATIO_TESTS,
    ),
)

# -- 20-24: the marking parameters and the units they are applied in ------------
#
# These five all have the same shape: the code keeps working, every test keeps passing, and the
# number moves. Four of them were confirmed to survive the marking suite as it stood before the
# §9.1 parameters were pinned by absolute literals — a test dated ``HORIZON_TS -
# DEAD_INACTIVITY_SECONDS`` passes at any window length, so it pins nothing about the window.

MARKING_TESTS = ("hand_computed/test_marking.py", "integration/test_marking.py")

MARKING = (
    Mutation(
        id="20-dead-pool-window-widened-to-ninety-days",
        bug="the §9.1 inactivity window is widened from 30 days to 90, in the frozen parameter set",
        survival_means=(
            "the pre-registered window could be moved after the fact in the Dune-flattering "
            "direction — a rugged token stays marked at its dust value for another two months "
            "instead of being zeroed, and every wallet that bought it keeps part of what it lost"
        ),
        edits=(
            # Ticket 11 moved this window out of ``marking/pools.py`` and into the frozen set, so
            # the mutation moved with it. That is the point of the migration and this case now
            # measures it: there is exactly one place left where 30 days can be turned into 90,
            # and the marking suite still notices when somebody does.
            Edit(
                relpath="phase0/parameters.py",
                find='Parameter("dead_pool.inactivity_seconds", 2592000, SECONDS,',
                replace='Parameter("dead_pool.inactivity_seconds", 7776000, SECONDS,',
            ),
        ),
        tests=MARKING_TESTS,
    ),
    Mutation(
        id="21-minimum-exit-value-raised-a-hundredfold",
        bug="the §9.1 minimum exit threshold is raised from $1.00 to $100.00",
        survival_means=(
            "the threshold that decides which positions are zeroed could be set to any value: at "
            "$100 every quiet position worth less than a hundred dollars is reported as an "
            "observed rug, and §10's dead share stops measuring rugs"
        ),
        edits=(
            Edit(
                relpath="marking/pools.py",
                find='MINIMUM_EXIT_VALUE_USD = Decimal("1.00")',
                replace='MINIMUM_EXIT_VALUE_USD = Decimal("100.00")',
            ),
        ),
        tests=MARKING_TESTS,
    ),
    Mutation(
        id="22-migration-crosses-quote-assets-unchecked",
        bug="the quote-asset guard on a followed migration is deleted",
        survival_means=(
            "a TOKEN/USDC -> TOKEN/WETH migration would price the replacement's WETH reserves at "
            "the raw-USDC price and return a mark 3.3e8x too large — or 3.3e8x too small in the "
            "reverse pairing, which lands as a plausible -100% rug"
        ),
        edits=(
            Edit(
                relpath="marking/mark.py",
                find="    if migrated:\n        require_same_quote_asset(pool, venue, price)\n",
                replace="",
            ),
        ),
        tests=MARKING_TESTS,
    ),
    Mutation(
        id="23-self-replacement-guard-removed",
        bug="a pool offered as its own replacement is accepted",
        survival_means=(
            "a fresher snapshot of the primary would rescue it from the dead conjunction and then "
            "price the exit against reserves the primary's own snapshot contradicts"
        ),
        edits=(
            Edit(
                relpath="marking/pools.py",
                find="    if replacement.address == pool.address:\n"
                     '        return False, ("replacement_rejected:same_pool:{}".format('
                     "replacement.address),)\n\n",
                replace="",
            ),
        ),
        tests=MARKING_TESTS,
    ),
    Mutation(
        id="24-shortfall-computed-in-the-ambient-context",
        bug="the spot-vs-exit shortfall drops back to bare Decimal arithmetic",
        survival_means=(
            "the LIQUIDITY_BOUND / POOL_MARKED boundary would be decided at whatever precision "
            "the caller happens to carry, so §10's depth-reliance share and §9.2's re-derivation "
            "would both depend on the reader rather than on the mark"
        ),
        edits=(
            Edit(
                relpath="marking/liquidity.py",
                find="    return divide(sub(spot_usd, marked_usd), spot_usd)",
                replace="    return (spot_usd - marked_usd) / spot_usd",
            ),
        ),
        tests=MARKING_TESTS,
    ),
)

# -- 25-26: the two arithmetic operations with no primitive in front of them -----
#
# ``contracts.numeric`` exports ``calc``, ``divide``, ``sub``, ``add`` and ``mul``. Magnitude and
# negation are not among them, so ``abs()`` and unary ``-`` are the two ways left to do arithmetic
# on a Decimal without going through the frozen context — and both are easy to write, because they
# do not look like arithmetic. The first draft of FIFO's closing-drift guard used ``abs()`` inside
# the fix for the very defect ``sub`` exists to prevent, in a module whose docstring names it.
#
# Mutation 24 is the same class in ``marking``. These two put it where it actually shipped.

FIFO_TESTS = ("hand_computed/test_fifo.py", "integration/test_fifo.py")

FIFO = (
    Mutation(
        id="25-closing-drift-magnitude-in-the-ambient-context",
        bug="the closing-slice drift takes its magnitude with bare abs() instead of _magnitude()",
        survival_means=(
            "the number deciding whether a lot book is reported or quarantined would be truncated "
            "to the caller's precision — nine parts in ten million over the limit rounds to the "
            "limit at six digits, and a closing basis no validator can re-derive is published as "
            "a measurement"
        ),
        edits=(
            Edit(
                relpath="fifo/matching.py",
                find="        drift = _magnitude(divide(sub(remainder, share), share))",
                replace="        drift = abs(divide(sub(remainder, share), share))",
            ),
        ),
        tests=FIFO_TESTS,
    ),
    Mutation(
        id="26-pro-rata-sign-applied-in-the-ambient-context",
        bug="the pro-rata sign is reapplied outside the frozen block",
        survival_means=(
            "every negative share would leave the module at whatever precision the caller carries "
            "— the identical defect to 25, spelled with the other operator that has no primitive"
        ),
        edits=(
            Edit(
                relpath="fifo/matching.py",
                find="        return -share if sign else share",
                replace="    return -share if sign else share",
            ),
        ),
        tests=FIFO_TESTS,
    ),
)

# -- 27-32: the composition root ------------------------------------------------
#
# ``src/pipeline`` is where a population quietly shrinks: five stages, each of which hands back
# fewer rows than it received for a reason that is correct in isolation. Nothing in a single module
# can notice when those reasons stop adding up, which is exactly why the composition root is the
# least self-defending code in the repository — and why, until this block existed, no mutation
# touched it at all.
#
# Every one of the six below leaves the run reconciling. ``StageCounts`` still balances,
# ``ClassificationCensus`` still totals, ``WalletWindowResult`` still constructs. They move a
# published number without breaking any invariant the result checks about itself, which is the only
# interesting kind of bug in an accounted pipeline.

PIPELINE_TESTS = (
    "hand_computed/test_pipeline.py",
    "integration/test_pipeline.py",
    "properties/test_pipeline.py",
)

PIPELINE = (
    Mutation(
        id="27-unpriceable-quarantine-becomes-a-zero",
        bug="a netting quarantine reports volume_usd=0 instead of None",
        survival_means=(
            "the reconciliation queue would report the entries nobody could price as costing "
            "nothing. `QuarantineQueue.unpriced` falls to zero and the queue reads as cheap for "
            "exactly the transactions that are hardest to dismiss — addendum §8's 'a quarantine is "
            "a number, not an omission' inverted into 'a quarantine is a zero'"
        ),
        edits=(
            Edit(
                relpath="pipeline/run.py",
                find="                # Netting refused before it produced a result, so nothing "
                     "priced this transaction.\n"
                     "                # None, not zero: the cost of this queue entry is unknown, "
                     "not nil.\n"
                     "                volume_usd=None,\n",
                replace="                volume_usd=ZERO,\n",
            ),
        ),
        tests=PIPELINE_TESTS,
    ),
    Mutation(
        id="28-canonical-result-order-deleted",
        bug="the results tuple keeps the caller's order instead of being sorted by (block, hash)",
        survival_means=(
            "every USD total in the coverage report accumulates over that tuple, and at 38 digits "
            "each addition rounds — so the published notional would move when the same "
            "transactions arrived shuffled, and §9.2's 'a reviewer can re-derive this number' "
            "would depend on how a caller sorted its input"
        ),
        edits=(
            Edit(
                relpath="pipeline/run.py",
                find="    results = tuple(sorted(results, key=lambda r: (r.block_number, "
                     "r.tx_hash)))",
                replace="    results = tuple(results)",
            ),
        ),
        tests=PIPELINE_TESTS,
    ),
    Mutation(
        id="29-unsupported-split-becomes-a-status-count",
        bug="unsupported_from_attribution counts every UNSUPPORTED result rather than only those "
            "§8 excluded",
        survival_means=(
            "UNSUPPORTED carries two entirely different findings — an owner §8 refused, and a trade "
            "whose quote leg had no price — and `unsupported_from_pricing` is the difference. "
            "Collapsing them reports every price-book gap as an attribution exclusion and makes the "
            "pricing gap structurally zero, so the one number that would send someone to fix the "
            "price book can never be non-zero"
        ),
        edits=(
            Edit(
                relpath="pipeline/run.py",
                find="        unsupported_from_attribution=sum(\n"
                     "            1 for r in results\n"
                     "            if r.status is ClassificationStatus.UNSUPPORTED and r.tx_hash in "
                     "excluded_hashes\n"
                     "        ),\n",
                replace="        unsupported_from_attribution=sum(\n"
                        "            1 for r in results\n"
                        "            if r.status is ClassificationStatus.UNSUPPORTED\n"
                        "        ),\n",
            ),
        ),
        tests=PIPELINE_TESTS,
    ),
    Mutation(
        id="31-marking-quarantine-counted-but-not-filed",
        bug="a buy refused at marking is counted as quarantined but no queue record is written",
        survival_means=(
            "`StageCounts` still reconciles — the buy is in `buys_quarantined` — so every count in "
            "the result balances while the transaction itself has left the reconciliation queue. "
            "Nobody can work a queue entry that does not exist, and its volume vanishes from "
            "`notional_usd_quarantined`: an unexplained drop hidden behind a correct-looking count"
        ),
        edits=(
            Edit(
                relpath="pipeline/run.py",
                find="        except QuarantineRequired as refusal:\n"
                     "            quarantined_buys.add(buy.tx_hash)\n"
                     "            quarantine.append(QuarantineRecord(\n"
                     "                stage=Stage.MARKING,\n"
                     "                reason=str(refusal),\n"
                     "                tx_hashes=(buy.tx_hash,),\n"
                     "                wallet=buy.portfolio_owner,\n"
                     "                asset=buy.asset,\n"
                     "                volume_usd=buy.quote_usd,\n"
                     "            ))\n"
                     "            continue\n",
                replace="        except QuarantineRequired:\n"
                        "            quarantined_buys.add(buy.tx_hash)\n"
                        "            continue\n",
            ),
        ),
        tests=PIPELINE_TESTS,
    ),
    Mutation(
        id="32-measurement-tail-reported-as-scored",
        bug="buys_outside_window is folded into buys_scored and reported as zero",
        survival_means=(
            "the §4.8 measurement tail — buys that opened a lot after the window closed and belong "
            "to the *next* window — would be published as buys this window scored. The four-way "
            "reconciliation still sums to `buys`, so the result validates; what changes is that a "
            "window claims to have measured samples it deliberately deferred"
        ),
        edits=(
            Edit(
                relpath="pipeline/run.py",
                find="        buys_scored=buys_scored,\n"
                     "        buys_quarantined=len(quarantined_buys),\n"
                     "        buys_outside_window=buys_outside_window,\n",
                replace="        buys_scored=buys_scored + buys_outside_window,\n"
                        "        buys_quarantined=len(quarantined_buys),\n"
                        "        buys_outside_window=0,\n",
            ),
        ),
        tests=PIPELINE_TESTS,
    ),
)


# -- 33-36: §10's outputs -------------------------------------------------------
#
# ``reporting`` is the last module before a number is published, and three of the four below are
# invisible to any check on *shape*: the value is a Decimal, at the right scale, inside a record
# whose constructor validates. Only a hand-computed literal separates them from the truth.

REPORTING_TESTS = (
    "hand_computed/test_reporting.py",
    "integration/test_reporting.py",
    "properties/test_reporting.py",
)

REPORTING = (
    Mutation(
        id="33-pack-validates-a-constant-instead-of-its-label",
        bug="DiagnosticPack checks the literal DIAGNOSTIC_ONLY rather than its own gate_relevance",
        survival_means=(
            "the call is still there and still passes, so the structural refusal reads as intact "
            "while the pack will now accept any label at all. §10's line — 'reporting a diagnostic "
            "and then using it to overturn a gate result is the failure mode this entire document "
            "exists to prevent' — would be enforced by a check that cannot fail"
        ),
        edits=(
            Edit(
                relpath="reporting/diagnostics.py",
                find='        object.__setattr__(self, "items", tuple(self.items))\n'
                     "        _check_gate_relevance(self.gate_relevance)\n",
                replace='        object.__setattr__(self, "items", tuple(self.items))\n'
                        "        _check_gate_relevance(DIAGNOSTIC_ONLY)\n",
            ),
        ),
        tests=REPORTING_TESTS,
    ),
    Mutation(
        id="34-reduced-activity-threshold-moved-to-a-tenth",
        bug="§10's Reduced Activity boundary moves from a quarter of baseline rate to a tenth",
        survival_means=(
            "the state that exists precisely so a wallet falling from 100 trades to 15 is not "
            "counted as healthy would stop catching it. `ChurnReport` carries the threshold, so "
            "any test asserting the report against `REDUCED_ACTIVITY_RATIO` moves with the "
            "constant and pins nothing — only an absolute literal, and a wallet placed between the "
            "two boundaries, can tell"
        ),
        edits=(
            Edit(
                relpath="reporting/churn.py",
                # Anchored with the comment above it: the constant's own value also appears in
                # the module docstring, and an anchor matching both would rewrite the prose too —
                # which is not the bug. A real one leaves the docstring saying 0.25.
                find="#: published churn figure says which boundary produced it.\n"
                     'REDUCED_ACTIVITY_RATIO = Decimal("0.25")',
                replace="#: published churn figure says which boundary produced it.\n"
                        'REDUCED_ACTIVITY_RATIO = Decimal("0.10")',
            ),
        ),
        tests=REPORTING_TESTS,
    ),
    Mutation(
        id="35-quantized-before-the-mean-not-after",
        bug="each wallet's raw buy quality is quantized on the way *into* the mean as well as after",
        survival_means=(
            "``reporting.boundary``'s whole reason for existing. The published figure is still a "
            "Decimal at the ratio scale inside a validated record — nothing about its shape "
            "changes — but every wallet's rounding error is now carried into the aggregate, and "
            "the error is a function of that wallet's magnitude, so a basket of small wallets is "
            "biased differently from a basket of large ones and the Independent Validator's "
            "reconciliation fails on rounding instead of on substance"
        ),
        edits=(
            Edit(
                relpath="reporting/capital.py",
                find="        mean_raw_buy_quality=output_ratio(\n"
                     '            mean((o.raw_buy_quality for o in wallet_outcomes), '
                     '"raw_buy_quality"),\n'
                     '            "mean_raw_buy_quality",\n'
                     "        ),\n",
                replace="        mean_raw_buy_quality=output_ratio(\n"
                        "            mean(\n"
                        "                (output_ratio(o.raw_buy_quality, \"raw_buy_quality\")\n"
                        "                 for o in wallet_outcomes),\n"
                        '                "raw_buy_quality",\n'
                        "            ),\n"
                        '            "mean_raw_buy_quality",\n'
                        "        ),\n",
            ),
        ),
        tests=REPORTING_TESTS,
    ),
    Mutation(
        id="36-mean-and-median-copy-retention-transposed",
        bug="the mean and the median Copy Retention are reported under each other's names",
        survival_means=(
            "§10 asks for both precisely because they disagree: one wallet retaining 100% can carry "
            "a basket in which most retain almost nothing, and the mean/median gap is the only "
            "thing that shows it. Transposed, the pair still looks like a pair and every "
            "constructor invariant holds — and any fixture whose retentions happen to be "
            "symmetric makes the two identical, so the test data decides whether this is visible"
        ),
        edits=(
            Edit(
                relpath="reporting/capital.py",
                find="        mean_copy_retention=optional_output(\n"
                     '            mean(retentions, "copy_retention") if retentions else None,\n'
                     "            RATIO,\n"
                     '            "mean_copy_retention",\n'
                     "        ),\n"
                     "        median_copy_retention=optional_output(\n"
                     '            median(retentions, "copy_retention") if retentions else None,\n'
                     "            RATIO,\n"
                     '            "median_copy_retention",\n'
                     "        ),\n",
                replace="        mean_copy_retention=optional_output(\n"
                        '            median(retentions, "copy_retention") if retentions else None,\n'
                        "            RATIO,\n"
                        '            "mean_copy_retention",\n'
                        "        ),\n"
                        "        median_copy_retention=optional_output(\n"
                        '            mean(retentions, "copy_retention") if retentions else None,\n'
                        "            RATIO,\n"
                        '            "median_copy_retention",\n'
                        "        ),\n",
            ),
        ),
        tests=REPORTING_TESTS,
    ),
)


# -- 37-40: the order of operations governance is made of ------------------------
#
# ``phase0.execute_stage`` names three orderings as load-bearing and says what each one is for.
# Prose in a docstring is not a control, and none of the four below breaks a signature, a type or
# an invariant — each simply performs the same steps in a different order, which is the only way
# this class of bug is ever actually written.

PHASE0_TESTS = (
    "hand_computed/test_execution.py",
    "integration/test_execution.py",
    "properties/test_execution.py",
    "test_governance.py",
)

PHASE0 = (
    Mutation(
        id="37-run-record-written-after-the-runner",
        bug="the run record's file is written once the runner returns instead of before it is called",
        survival_means=(
            "'3 before 4' inverted. A stage that crashes, or one held by a mid-stage HALT, would "
            "leave no run record — and the record is the only statement of which commit, which "
            "config hash, which dataset snapshot and which master seed the run was about to "
            "execute under. Ticket 05's entire point is that this survives the failure, because a "
            "record you assemble afterwards from memory is not reproducibility"
        ),
        edits=(
            Edit(
                relpath="phase0/runs.py",
                find="        os.makedirs(self.directory, exist_ok=True)\n"
                     "        path = self._path(record.run_id)\n"
                     "        if os.path.exists(path):\n"
                     "            raise FrozenError(\n"
                     '                "run record {} already exists and is immutable".format('
                     "record.run_id)\n"
                     "            )\n"
                     '        with open(path, "w", encoding="utf-8") as fh:\n'
                     "            json.dump(record.to_dict(), fh, indent=2, sort_keys=True)\n"
                     '            fh.write("\\n")\n'
                     "\n"
                     "        if self._audit is not None:\n",
                replace="        if self._audit is not None:\n",
            ),
            Edit(
                relpath="phase0/runs.py",
                find="    def get(self, run_id):\n",
                replace="    def persist(self, record):\n"
                        "        os.makedirs(self.directory, exist_ok=True)\n"
                        "        path = self._path(record.run_id)\n"
                        "        if os.path.exists(path):\n"
                        "            raise FrozenError(\n"
                        '                "run record {} already exists and is immutable".format('
                        "record.run_id)\n"
                        "            )\n"
                        '        with open(path, "w", encoding="utf-8") as fh:\n'
                        "            json.dump(record.to_dict(), fh, indent=2, sort_keys=True)\n"
                        '            fh.write("\\n")\n'
                        "        return record\n"
                        "\n"
                        "    def get(self, run_id):\n",
            ),
            Edit(
                relpath="phase0/execution.py",
                find="    # 5. governance re-checked. A HALT or an invalidation arriving while the "
                     "stage ran holds the\n",
                replace="    runs.persist(record)\n"
                        "\n"
                        "    # 5. governance re-checked. A HALT or an invalidation arriving while "
                        "the stage ran holds the\n",
            ),
        ),
        tests=PHASE0_TESTS,
    ),
    Mutation(
        id="38-start-gate-checked-after-the-run-record",
        bug="the §15.4 precondition check moves below runs.open_run",
        survival_means=(
            "'1 before 3' inverted. A stage refused by the start gate would leave a run record "
            "behind it — evidence that a run happened under pinned inputs when nothing was ever "
            "authorised to begin. The status returned is still REFUSED, so the caller sees the "
            "right answer; what is wrong is the artifact left on disk, which is the thing anyone "
            "auditing the run six months later actually reads"
        ),
        edits=(
            Edit(
                relpath="phase0/execution.py",
                find="    # 1-2. the start gate, then governance — both before anything is "
                     "written.\n"
                     "    try:\n"
                     "        preconditions.require_ready()\n"
                     '        _authorise(governance, authority, "Stage {}".format(stage))\n',
                replace="    # 1-2. governance, then the start gate.\n"
                        "    try:\n"
                        '        _authorise(governance, authority, "Stage {}".format(stage))\n',
            ),
            Edit(
                relpath="phase0/execution.py",
                find="    # 4. the runner.\n"
                     "    try:\n"
                     "        value = runner(StageContext(record, config))\n",
                replace="    try:\n"
                        "        preconditions.require_ready()\n"
                        "    except Phase0Error as exc:\n"
                        "        return _record_outcome(\n"
                        "            audit, ACTION_REFUSED,\n"
                        "            StageResult(stage, REFUSED, requester, record.run_id, "
                        "state_before,\n"
                        "                        governance.state, reason=str(exc), error=exc),\n"
                        "        )\n"
                        "\n"
                        "    # 4. the runner.\n"
                        "    try:\n"
                        "        value = runner(StageContext(record, config))\n",
            ),
        ),
        tests=PHASE0_TESTS,
    ),
    Mutation(
        id="39-a-crashed-stage-advances-the-run",
        bug="the crash path performs the transition the stage would have completed",
        survival_means=(
            "'6 after 4' inverted, and the worst of the four: the run moves forward past work that "
            "never happened. A `main_test` runner that raised would leave the machine in "
            "MAIN_TEST_EXECUTED, which makes the gate outcome writable and makes a re-run refused "
            "as 'already in this state'. The StageResult still says CRASHED — a refusal is "
            "visible, and a state that has silently advanced past nothing is not"
        ),
        edits=(
            Edit(
                relpath="phase0/execution.py",
                find="    except BaseException as exc:  # evidence is owed for any abrupt exit, "
                     "not only for Exception\n"
                     "        result = _record_outcome(\n",
                replace="    except BaseException as exc:  # evidence is owed for any abrupt exit, "
                        "not only for Exception\n"
                        "        if authority.advances is not None:\n"
                        "            governance.transition(\n"
                        '                authority.advances, requester, {"stage": stage}, '
                        "run_id=record.run_id\n"
                        "            )\n"
                        "        result = _record_outcome(\n",
            ),
        ),
        tests=PHASE0_TESTS,
    ),
    Mutation(
        id="40-no-governance-recheck-after-the-runner",
        bug="step 5, the re-authorisation between the runner and the transition, is deleted",
        survival_means=(
            "the only thing a mid-stage HALT can actually do. Nothing here can interrupt an opaque "
            "runner in flight, so stopping the *outcome* from being committed is the whole of the "
            "operations capability — delete the re-check and a build-lane stage returns COMPLETED "
            "with a published value under a halted or invalidated run, and an execution-lane stage "
            "escapes as an uncaught HaltedError instead of a recorded HELD. Either way the HELD "
            "status becomes unreachable, and a status no path can produce is a status nobody has "
            "tested"
        ),
        edits=(
            Edit(
                relpath="phase0/execution.py",
                find="    # 5. governance re-checked. A HALT or an invalidation arriving while the "
                     "stage ran holds the\n"
                     "    #    outcome rather than committing it — the condition is \"governance no "
                     "longer authorises\n"
                     "    #    this\", not \"someone pressed halt\".\n"
                     "    try:\n"
                     '        _authorise(governance, authority, "Committing stage {}".format('
                     "stage))\n"
                     "    except Phase0Error as exc:\n"
                     "        return _record_outcome(\n"
                     "            audit, ACTION_HELD,\n"
                     "            StageResult(stage, HELD, requester, record.run_id, state_before, "
                     "governance.state,\n"
                     "                        reason=str(exc), error=exc),\n"
                     "        )\n"
                     "\n",
                replace="",
            ),
        ),
        tests=PHASE0_TESTS,
    ),
)


# -- 41-42: the known-answer battery --------------------------------------------
#
# The battery lives under ``tests/`` and is not a test: §9.6 hashes its sixteen cases into the
# freeze manifest, §9.8 gates on its pass rate, and §9.1 puts it second in the binding order. It is
# an artifact of the run that happens to be written in Python, and the two ways it can lie are the
# two below — report a case green without running it, and hash less than it claims to hash.

KNOWN_ANSWER_TESTS = (
    "known_answer/test_hand_computed.py",
    "known_answer/test_integration.py",
    "known_answer/test_properties.py",
)

KNOWN_ANSWER = (
    Mutation(
        id="41-one-case-reported-green-without-running",
        bug="evaluate_case short-circuits one of the sixteen to passed=True without executing it",
        survival_means=(
            "§9.3 requires 100% and forbids waiving a failure as an edge case. A case that returns "
            "green without running is a waiver nobody had to argue for: the battery still holds "
            "sixteen names in order, `known_answer_pass_rate` still reports 1, §9.8 still passes, "
            "and NULL_COMPLETE is still authorised — on the strength of a case that was not "
            "computed. Skipping is the one failure mode a pass-rate gate cannot see"
        ),
        edits=(
            Edit(
                tree="tests",
                relpath="known_answer/battery.py",
                find="def evaluate_case(case):\n"
                     '    """Compare observed against the frozen answer, key by key."""\n'
                     "    try:\n"
                     "        observed = run_case(case)\n",
                replace="def evaluate_case(case):\n"
                        '    """Compare observed against the frozen answer, key by key."""\n'
                        '    if case.name == "Pool Migration":\n'
                        "        return CaseResult(name=case.name, passed=True)\n"
                        "    try:\n"
                        "        observed = run_case(case)\n",
            ),
        ),
        tests=KNOWN_ANSWER_TESTS,
    ),
    Mutation(
        id="42-fixture-hash-covers-half-the-battery",
        bug="canonical_battery hashes the first eight cases instead of all sixteen",
        survival_means=(
            "the §9.6 freeze manifest would carry a hash that eight of the sixteen cases can move "
            "freely underneath. A later run reproducing the hash would prove nothing about half "
            "the battery, and §9.7's 'change the fixtures and the run is invalidated' would apply "
            "to the first half only"
        ),
        edits=(
            Edit(
                tree="tests",
                relpath="known_answer/battery.py",
                find="    cases = BATTERY if battery is None else tuple(battery)",
                replace="    cases = BATTERY[:8] if battery is None else tuple(battery)",
            ),
        ),
        tests=KNOWN_ANSWER_TESTS,
    ),
)


# -- 43-44: one tx_hash, one transaction ----------------------------------------
#
# ``tx_hash`` is the identity key the composition root counts with — the census split, the queue's
# transaction list, the four sets recording which buys left the population, and the map from a buy
# to the consumptions that realized it. All of those are hash-keyed and none of them is a set *of
# transactions* unless the key identifies one, so ``run_wallet_window`` establishes it at the
# boundary before any stage runs.
#
# Both mutations below leave the run reconciling. That is what makes them worth a case: a duplicate
# hash does not crash and does not shrink the answer, it hands one lot book's sale to a different
# book's buy. §10's mix then reports realized 1 / marked 0 / dead 0 — maximum credibility — on a
# return assembled at a join. The reader's whole instrument for telling a measurement from a mark
# reads *most trustworthy* on the one number that was invented.

IDENTITY = (
    Mutation(
        id="43-duplicate-tx-hash-boundary-deleted",
        bug="the boundary refusal of duplicate tx_hash values is removed from run_wallet_window",
        survival_means=(
            "two transactions under one hash would be pooled rather than counted. The traced case "
            "publishes buy_quality 2 against a true 0.75 and reports an unsold lot at +200%, "
            "because `consumptions_by_buy` hands the other book's $3,000 sale to it — with "
            "`realized_share` 1 and `marked_share` 0, so §10's credibility mix declares the "
            "fabricated number the most trustworthy in the run. No quarantine, no exclusion, no "
            "census line: a wrong number that looks plausible, which is the failure the whole "
            "repository is built to refuse"
        ),
        edits=(
            Edit(
                relpath="pipeline/run.py",
                find="    _require_one_transaction_per_hash(handed_in)\n",
                replace="",
            ),
        ),
        tests=PIPELINE_TESTS,
    ),
    Mutation(
        id="44-duplicate-check-fires-only-on-a-third-row",
        bug="the repeated-hash test becomes `> 2`, so a pair passes and only a triple is refused",
        survival_means=(
            "the guard would still be there, still named, still raising on the input somebody "
            "wrote a test for — and blind to the shape that actually occurs. A page boundary read "
            "twice produces pairs, not triples. This is the papered-over repair in its usual form: "
            "a bound on the traced instance rather than on the condition, passing every test that "
            "was written against the reported case"
        ),
        edits=(
            Edit(
                relpath="pipeline/run.py",
                find="    repeated = [tx_hash for tx_hash in sorted(positions) "
                     "if len(positions[tx_hash]) > 1]",
                replace="    repeated = [tx_hash for tx_hash in sorted(positions) "
                        "if len(positions[tx_hash]) > 2]",
            ),
        ),
        tests=PIPELINE_TESTS,
    ),
    # -- 45-49: one spelling, one asset -----------------------------------------
    #
    # ``tx_hash`` was the reported instance; it was not the only identity key the boundary
    # collapsed. The pool book, the price book, the §4.7 trading starts and the migration
    # replacements are all keyed by an asset and all looked up through ``normalise_asset``, so two
    # caller keys naming one asset arrive as two entries and leave as one — with the survivor
    # decided by the order the caller's mapping iterates in. Same signature as the duplicate hash:
    # the run reconciles, the census totals, and the published number is different.
    Mutation(
        id="45-colliding-asset-keys-collapse-silently",
        bug="asset_keyed stops detecting collisions and returns the last-one-wins mapping",
        survival_means=(
            "two spellings of one token in the pool book would mark the position against whichever "
            "entry the caller's mapping yielded last: a $1,000 lot published at -25% or at -50% "
            "for the same input, with nothing in the queue, the census or the coverage report to "
            "say a book of two entries had become a book of one. The price book is worse and "
            "quieter — USDC is priced per raw unit, so the checksummed duplicate moves every "
            "notional in the run by six orders of magnitude and leaves every return untouched"
        ),
        edits=(
            Edit(
                relpath="pipeline/inputs.py",
                find="    collided = [canonical for canonical in order "
                     "if len(spellings[canonical]) > 1]\n",
                replace="    collided = []\n",
            ),
        ),
        tests=PIPELINE_TESTS,
    ),
    Mutation(
        id="46-collision-refused-only-when-the-values-disagree",
        bug="a repeated spelling is recorded only when its value differs from the one already held",
        survival_means=(
            "the papered-over repair in its usual form. Every case a reviewer would trace has two "
            "spellings carrying two different pools or two different prices, so all of them still "
            "refuse — and the guard would be conditioned on the entries disagreeing rather than on "
            "the key space being unnormalised, which is the actual defect. A caller who hands the "
            "same pool under two spellings today hands a different one tomorrow, and the check "
            "that was supposed to catch it has already been taught to look the other way"
        ),
        edits=(
            Edit(
                relpath="pipeline/inputs.py",
                find="        spellings[canonical].append(key)\n",
                replace="        if not spellings[canonical] or values[canonical] != value:\n"
                        "            spellings[canonical].append(key)\n",
            ),
        ),
        tests=PIPELINE_TESTS,
    ),
    Mutation(
        id="47-padded-asset-key-left-as-a-dead-entry",
        bug="the refusal of a whitespace-padded asset key is removed from asset_keyed",
        survival_means=(
            "``normalise_asset`` is the frozen seam and does not strip, so a padded key matches "
            "nothing any stage can produce. On the replacement pools that silent dead entry is a "
            "wrong number rather than a missing one: the migration the caller configured is never "
            "found, the dead primary is valued DEAD_ZEROED at -100%, and §10 reports the whole "
            "exposure as measured-dead"
        ),
        edits=(
            Edit(
                relpath="pipeline/inputs.py",
                find="    for key, _ in pairs:\n"
                     "        text = key if isinstance(key, str) else \"\"\n"
                     "        if text != text.strip():\n",
                replace="    for key, _ in pairs:\n"
                        "        text = key if isinstance(key, str) else \"\"\n"
                        "        if False:\n",
            ),
        ),
        tests=PIPELINE_TESTS,
    ),
    Mutation(
        id="48-window-config-stores-the-caller-s-spelling",
        bug="WindowConfig keeps the replacement-pool keys verbatim while the lookup normalises",
        survival_means=(
            "the original defect, which was half an implementation rather than a missing one: the "
            "lookup normalised and the store did not, so a migration supplied under a checksummed "
            "address could never be read. The position is marked DEAD_ZEROED and the run publishes "
            "-100% on a token whose liquidity had moved — a measured-looking zero produced by a "
            "spelling"
        ),
        edits=(
            Edit(
                relpath="pipeline/inputs.py",
                find="        object.__setattr__(\n"
                     "            self, \"replacement_pools\", "
                     "asset_keyed(replacements, \"replacement_pools\")\n"
                     "        )\n",
                replace="        object.__setattr__(self, \"replacement_pools\", "
                        "dict(replacements))\n",
            ),
        ),
        tests=PIPELINE_TESTS,
    ),
    Mutation(
        id="49-asset-pairs-lets-dict-collapse-the-repeat-first",
        bug="asset_pairs builds a dict before reading the caller's pairs",
        survival_means=(
            "the collision check would be reading a mapping this module built rather than the one "
            "the caller supplied. ``dict([(k, a), (k, b)])`` applies its own last-one-wins rule "
            "first, so a price book handed over as pairs loses an entry before anything can object "
            "— and the guard reports a clean book"
        ),
        edits=(
            Edit(
                relpath="pipeline/inputs.py",
                find="    items = getattr(mapping, \"items\", None)\n"
                     "    return tuple(items() if callable(items) else mapping)\n",
                replace="    return tuple(dict(mapping).items())\n",
            ),
        ),
        tests=PIPELINE_TESTS,
    ),
)


# -- 50-64: the candidate universe (tickets 25-28) -------------------------------
#
# ``src/universe`` decides which accounts exist as far as the experiment is concerned, and then
# which of them are selected. Nothing downstream can recover from a bug here: a wallet that never
# entered the universe is not under-weighted, it is absent, and every rate computed afterwards has
# the wrong denominator with nothing to notice.
#
# The mutations below are chosen for one shared property — **each of them leaves a run that
# reconciles**. None crashes, none produces an implausible number, and every one of them moves the
# answer in the direction that flatters the hypothesis:
#
#   * collapsing the two-stage buffer drops exactly the accounts netting would have rescued, and
#     those are the accounts the vendors decode worst;
#   * a ceiling in place of the floor raises realised selection pressure above the 1% §6.5 permits;
#   * an unattributed exclusion bucket shrinks the eligible universe silently, which moves the
#     selected wallet count;
#   * a removable member is survivorship, and it looks exactly like a smaller universe;
#   * ``>`` in place of ``>=`` at T0 admits a value computed at the instant the decision is made.
#
# The last two cases are a different shape: they mutate ``src/`` in ways only a **static** check can
# see, and their selection is the static check alone. A structural rule whose only evidence is its
# own tmp_path fixtures has never been run against the tree it binds.

UNIVERSE_TESTS = (
    "hand_computed/test_universe.py",
    "properties/test_universe.py",
    "integration/test_universe.py",
)

UNIVERSE = (
    Mutation(
        id="50-warehouse-filters-at-the-final-threshold",
        bug="stage one screens on the eligibility bounds instead of the buffered ones",
        survival_means=(
            "the two-stage buffer would be a single stage wearing two names. Every account netting "
            "would have carried across the boundary is dropped before enrichment, and the drop is "
            "invisible because those accounts were never returned — which is the exact failure "
            "ticket 25 calls load-bearing"
        ),
        edits=(
            Edit(
                relpath="universe/eligibility.py",
                find="        if row.potential_buys < POTENTIAL_BUY_FLOOR:\n",
                replace="        if row.potential_buys < VALID_BUY_FLOOR:\n",
            ),
            Edit(
                relpath="universe/eligibility.py",
                find="        elif row.potential_buys > POTENTIAL_BUY_CEILING:\n",
                replace="        elif row.potential_buys > VALID_BUY_CEILING:\n",
            ),
        ),
        tests=UNIVERSE_TESTS,
    ),
    Mutation(
        id="51-nothing-ever-crossed-the-boundary",
        bug="Admission.crossed_boundary is hard-wired False",
        survival_means=(
            "ticket 25's headline count — accounts that moved across the boundary between the "
            "potential-buy filter and the valid-buy threshold — would be reported as zero on every "
            "window, and a reader would conclude the buffer was doing nothing and remove it"
        ),
        edits=(
            Edit(
                relpath="universe/eligibility.py",
                find="        crossed = not (VALID_BUY_FLOOR <= observation.potential_buys "
                     "<= VALID_BUY_CEILING)\n",
                replace="        crossed = False\n",
            ),
        ),
        tests=UNIVERSE_TESTS,
    ),
    Mutation(
        id="52-the-census-tolerates-an-unattributed-bucket",
        bug="the reconciliation between considered, admitted and rule-attributed is removed",
        survival_means=(
            "accounts could leave the population with no rule naming them. They shrink the "
            "eligible universe, which is the number §6.5 derives the selected wallet count from, "
            "so the basket would be drawn at a selection pressure nobody measured"
        ),
        edits=(
            Edit(
                relpath="universe/census.py",
                find="        if self.admitted_count + excluded != self.considered:\n",
                replace="        if self.admitted_count + excluded < 0:\n",
            ),
        ),
        tests=UNIVERSE_TESTS,
    ),
    Mutation(
        id="53-one-percent-rounds-up",
        bug="the 1% fraction takes a ceiling instead of a floor",
        survival_means=(
            "realised selection pressure would sit above the 1% §6.5 authorises for every universe "
            "size that is not an exact multiple of 100 — roughly half of them — and the four "
            "worked examples in the pre-registration are all exact multiples, so nothing in the "
            "spec would contradict it"
        ),
        edits=(
            Edit(
                relpath="universe/select.py",
                find="    raw = size // SELECTION_PERCENT_DENOMINATOR\n",
                replace="    raw = -(-size // SELECTION_PERCENT_DENOMINATOR)\n",
            ),
        ),
        tests=UNIVERSE_TESTS,
    ),
    Mutation(
        id="54-the-high-clamp-becomes-inclusive",
        bug="the upper clamp fires at exactly 1,000 rather than above it",
        survival_means=(
            "a universe of exactly 100,000 would be reported CLAMPED_HIGH while selecting the same "
            "1,000 wallets. The count is right and the *state* is wrong, so every diagnostic that "
            "reads the clamp state to decide whether the window ran at 1% would read it backwards"
        ),
        edits=(
            Edit(
                relpath="universe/select.py",
                find="    if raw > SELECTED_MAX:\n",
                replace="    if raw >= SELECTED_MAX:\n",
            ),
        ),
        tests=UNIVERSE_TESTS,
    ),
    Mutation(
        id="55-ties-break-by-address-instead-of-by-seed",
        bug="the seeded tie-break is replaced by the wallet address",
        survival_means=(
            "deterministic but not neutral. Addresses are not random, so the lowest ones would be "
            "selected again and again for a reason unconnected to the data — and 'reproducible' "
            "would still be true, which is what makes this survivable without a tie fixture"
        ),
        edits=(
            Edit(
                relpath="universe/select.py",
                find="    candidates.sort(key=lambda score: _tiebreak_key(seed, score.wallet))\n",
                replace="    candidates.sort(key=lambda score: score.wallet)\n",
            ),
        ),
        tests=UNIVERSE_TESTS,
    ),
    Mutation(
        id="56-a-wallet-can-be-removed-after-t0",
        bug="the frozen membership is no longer cross-checked against the Step 0 count",
        survival_means=(
            "§6.4's whole subject. A wallet that blew up and went quiet could be dropped and the "
            "universe would still freeze, still hash, and still rank — survivorship arriving as a "
            "smaller number rather than as an error"
        ),
        edits=(
            Edit(
                relpath="universe/freeze.py",
                find="        if len(self.members) != self.measurement.eligible_universe_size:\n",
                replace="        if len(self.members) < 0:\n",
            ),
        ),
        tests=UNIVERSE_TESTS,
    ),
    Mutation(
        id="57-an-insufficient-window-freezes-without-a-revision",
        bug="the §6.1 floor refusal fires on SUFFICIENT windows instead of insufficient ones",
        survival_means=(
            "a window measured below 10,000 eligible accounts would advance to ranking with no "
            "design revision recorded. §6.1 says such a window is not valid and the four-window "
            "design must be revised *before* the main test, so this is the stopping condition "
            "silently inverted"
        ),
        edits=(
            Edit(
                relpath="universe/freeze.py",
                find="        if (self.measurement.status is "
                     "WindowStatus.INSUFFICIENT_CANDIDATE_UNIVERSE\n"
                     "                and self.revision is None):\n",
                replace="        if (self.measurement.status is WindowStatus.SUFFICIENT\n"
                        "                and self.revision is None):\n",
            ),
        ),
        tests=UNIVERSE_TESTS,
    ),
    Mutation(
        id="58-the-t0-boundary-becomes-exclusive",
        bug="an observation stamped exactly at T0 is admitted (>= becomes >)",
        survival_means=(
            "a value computed *at* T0 has already seen T0, and T0 is the instant the decision is "
            "made. Half a block of hindsight is still hindsight, and it does not crash and does "
            "not look wrong — it makes the selection fit the outcome"
        ),
        edits=(
            Edit(
                relpath="universe/observation.py",
                find="    if as_of_block >= t0.block:\n",
                replace="    if as_of_block > t0.block:\n",
            ),
        ),
        tests=UNIVERSE_TESTS,
    ),
    Mutation(
        id="59-ranking-coverage-becomes-a-subset",
        bug="a frozen member with no score and no stated absence is accepted",
        survival_means=(
            "the ranked population would shrink silently, and it shrinks in a direction that "
            "correlates with going quiet: score computation fails precisely for wallets whose buys "
            "all priced at zero. That is survivorship entering through an exception handler"
        ),
        edits=(
            Edit(
                relpath="universe/ranking.py",
                find="    if missing or extra:\n",
                replace="    if extra:\n",
            ),
        ),
        tests=UNIVERSE_TESTS,
    ),
    Mutation(
        id="60-the-replacement-registry-accepts-any-rule-id",
        bug="an unknown rule id falls back to the first registered rule",
        survival_means=(
            "a replacement window chosen after seeing the data would be authorised by a rule "
            "nobody cited. §6.1 forbids exactly that, and the fallback leaves a run that records a "
            "rule id, a statement and a commit — all of them true, and none of them the reason the "
            "window was chosen"
        ),
        edits=(
            Edit(
                relpath="universe/step0.py",
                find="    rule = registry.rule(rule_id)\n",
                replace="    rule = registry.rule(rule_id) or (\n"
                        "        registry.rules[0] if registry.rules else None)\n",
            ),
        ),
        tests=UNIVERSE_TESTS,
    ),
    Mutation(
        id="61-a-post-t0-count-becomes-hashable",
        bug="ForwardCount.__hash__ is restored to the default",
        survival_means=(
            "unhashable is the refusal people forget and the most valuable one, because the dict "
            "and the set are how a 'still active' filter is actually written. Restoring the hash "
            "reopens ``{w: activity[w] for w in basket.wallets if ...}`` without touching any "
            "comparison operator"
        ),
        edits=(
            Edit(
                relpath="universe/forward.py",
                find="    __hash__ = None\n",
                replace="    __hash__ = object.__hash__\n",
            ),
        ),
        tests=UNIVERSE_TESTS,
    ),
    Mutation(
        id="62-pre-t0-activity-can-be-laundered-as-post-t0",
        bug="the mirror guard on first_forward_block is removed",
        survival_means=(
            "the half of the T0 boundary that is easy to leave out. Without it, anyone can put "
            "pre-T0 activity into a record whose *name* says post-T0 and hand it to something that "
            "trusts the name — and the churn block would then be computed over the baseline"
        ),
        edits=(
            Edit(
                relpath="universe/forward.py",
                find="        if self.first_forward_block <= self.t0.block:\n",
                replace="        if self.first_forward_block < 0:\n",
            ),
        ),
        tests=UNIVERSE_TESTS,
    ),
    Mutation(
        id="63-the-selection-path-imports-the-post-t0-module",
        bug="src/universe/select.py imports universe.forward",
        survival_means=(
            "ticket 27's barrier would be enforced by nothing but its own tmp_path fixtures. A "
            "structural rule that has never been run against the tree it binds is a rule about "
            "fixtures. The selection here is the static check alone, deliberately: the check "
            "parses and never imports, so the circular import this edit creates is irrelevant to "
            "whether the rule fires"
        ),
        edits=(
            Edit(
                relpath="universe/select.py",
                find="from .ranking import RANKING_METRIC, RankingInputMismatch, RankingInputs\n",
                replace="from .forward import ForwardCount  # noqa: F401\n"
                        "from .ranking import RANKING_METRIC, RankingInputMismatch, "
                        "RankingInputs\n",
            ),
        ),
        tests=("test_post_t0_barrier.py",),
    ),
    Mutation(
        id="64-the-universe-leaf-reaches-for-scoring",
        bug="src/universe/ranking.py imports the sibling builder package that computes the metric",
        survival_means=(
            "the leaf rule would be a comment. §6.5's ranking metric must reach ``universe`` as "
            "data the composition root supplies, so that the ranked population is covered exactly "
            "rather than by whatever the scorer happened to return — and this is the one line the "
            "rule exists to stop somebody writing"
        ),
        edits=(
            Edit(
                relpath="universe/ranking.py",
                find="from .freeze import FrozenUniverse\n",
                replace="from scoring.quality import buy_quality  # noqa: F401\n"
                        "from .freeze import FrozenUniverse\n",
            ),
        ),
        tests=("test_lane_independence.py",),
    ),
    Mutation(
        id="65-the-still-active-filter-that-was-actually-committed",
        bug="``rank_and_select`` prefers wallets with post-T0 activity, reached through an "
            "importlib hop with split string literals",
        survival_means=(
            "this is not a hypothetical. It is the code that was committed in ``select.py`` at "
            "fca51e3 and that rules 1-9 of the barrier all passed: no ast.Import of the output "
            "module, no vocabulary name as a Name, Attribute, keyword or whole string constant, "
            "and a payload attribute starting with an underscore, which the derived vocabulary "
            "drops. The line it hid was ``candidates = [c for c in candidates if _liveness(c) > "
            "0] or candidates`` — a look-ahead filter inside the selection function, which is "
            "precisely what ticket 27 is about. Rule 3's constant folding and rule 10's ban on the "
            "dynamic-import machinery were written for it, and a mutation is the only way to ask "
            "whether they fire against the real tree rather than against their own tmp_path "
            "fixtures"
        ),
        edits=(
            Edit(
                relpath="universe/select.py",
                find="def _tiebreak_key(seed, wallet):\n",
                replace="_LEDGER = {}\n"
                        "\n"
                        "\n"
                        "def _liveness(record):\n"
                        '    """A \'still active\' preference, written so the AST barrier cannot '
                        'see it."""\n'
                        "    import importlib\n"
                        '    _mod = importlib.import_module("universe" + "." + "forward")\n'
                        '    _cls = getattr(_mod, "Forward" + "Count")\n'
                        "    holder = _LEDGER.get(record.wallet)\n"
                        "    if holder is None:\n"
                        "        return 0\n"
                        '    count = getattr(holder, "forward" + "_valid_buys")\n'
                        "    assert type(count) is _cls\n"
                        '    return getattr(count, "_post" + "_t0_value")\n'
                        "\n"
                        "\n"
                        "def _tiebreak_key(seed, wallet):\n",
            ),
            Edit(
                relpath="universe/select.py",
                find="    candidates.sort(key=lambda score: _tiebreak_key(seed, score.wallet))\n",
                replace="    candidates.sort(key=lambda score: _tiebreak_key(seed, score.wallet))\n"
                        "    candidates = [c for c in candidates if _liveness(c) > 0] "
                        "or candidates\n",
            ),
        ),
        tests=("test_post_t0_barrier.py",),
    ),
    Mutation(
        id="105-the-ten-thousand-account-floor-moves-by-one",
        bug="a window with exactly 10,000 eligible accounts is marked INSUFFICIENT",
        survival_means=(
            "§6.1's stopping condition off by one at the only place it is ever read, in the "
            "direction that costs a window. Ticket 26 marks a universe *below* 10,000 accounts "
            "INSUFFICIENT CANDIDATE UNIVERSE, so a window landing exactly on the pre-registered "
            "floor has met the condition and may be ranked; under this mutation it has not, "
            "``permits_ranking`` goes False for the whole report, and §6.1's remedy is not a "
            "smaller basket — it is 'that window is not valid, and the four-window design must be "
            "revised before the main test'. A sound walk-forward design would be sent back and a "
            "window replaced after the data had been seen, which is the one move §6.1 forbids, on "
            "the strength of one character. Nothing in this suite noticed until the boundary was "
            "pinned: every fixture universe here is a handful of accounts, so ``<`` and ``<=`` "
            "agreed on every one of them"
        ),
        edits=(
            Edit(
                relpath="universe/step0.py",
                find="        if self.eligible_universe_size < MINIMUM_ELIGIBLE_UNIVERSE:\n",
                replace="        if self.eligible_universe_size <= MINIMUM_ELIGIBLE_UNIVERSE:\n",
            ),
        ),
        tests=UNIVERSE_TESTS,
    ),
)


# -- equivalent mutants ---------------------------------------------------------
#
# A mutation that no input can distinguish from the real code is not a hole in the suite. It is a
# guard on a state the system cannot currently reach, and asserting that it dies would be asserting
# that a test exists which cannot exist.
#
# These are kept, and inverted: the harness requires them to **survive**. That is a stronger claim
# than deleting them, and a falsifiable one — the day the composition can reach the state, the case
# goes red and says so, which is precisely when the guard becomes worth a test. Nothing is skipped
# and nothing is xfailed; the assertion is simply the other way round, and the reason is recorded
# with each case rather than in a commit message.

EQUIVALENT = (
    Mutation(
        id="E1-unscorable-wallets-count-toward-coverage",
        bug="scored notional sums every wallet's accounts, including wallets that produced no score",
        survival_means=(
            "nothing, today, and that is the finding. The guard matters only for a WalletOutcome "
            "carrying accounts *and* no BuyQuality, and ``run_wallet_window`` cannot build one: "
            "accounts and outcomes are appended in lockstep, so a non-empty accounts tuple means "
            "``buy_quality_detail`` was called, and its three refusals are 'no buys' (excluded by "
            "the lockstep), 'total log weight is zero' and 'no value basis at all'. Netting will "
            "not emit a VALID_BUY at or below the $0.01 residual floor, log(1 + 0.01) is "
            "0.00995033..., and the weight does not vanish until ~1e-38 — 36 orders of magnitude "
            "below. The basis is bounded the same way: realized proceeds, a live pool's exit "
            "value and a dead pool's exposure are each strictly positive whenever they apply. So "
            "``StageCounts.buys_unscored`` is structurally zero and the coverage guard is defence "
            "in depth. ``hand_computed/test_pipeline.py::"
            "test_the_smallest_buy_netting_will_emit_still_carries_a_positive_weight`` pins both "
            "bounds as absolute literals, so this claim fails loudly instead of ageing quietly"
        ),
        edits=(
            Edit(
                relpath="pipeline/run.py",
                find="    scored = ZERO\n"
                     "    for outcome in wallet_outcomes:\n"
                     "        if outcome.quality is None:\n"
                     "            continue\n"
                     "        for account in outcome.accounts:\n",
                replace="    scored = ZERO\n"
                        "    for outcome in wallet_outcomes:\n"
                        "        for account in outcome.accounts:\n",
            ),
        ),
        tests=PIPELINE_TESTS,
    ),
)

# -- 45-48: one wallet, one entry, in matching_null ------------------------------
#
# The same class as 43-44, one component further along: an identity key a boundary collapses, so
# two distinct inputs become one entry and iteration order picks the survivor. ``matching_null``
# had it at two sites, and each is mutated here in both of its plausible forms — the original
# defect, and the repair conditioned on the instance a reviewer happened to construct.
#
# What makes these worth keeping is that neither site *looks* like a numeric bug. 45 publishes a
# balance table; 47 publishes a null pass rate. Both are the numbers §6.6 and §8.3 offer as
# evidence that the matching and the null were earned, and both move on nothing but the order of a
# caller's dict or list.

MATCHING_IDENTITY_TESTS = (
    "hand_computed/test_matching_null_identity.py",
    "hand_computed/test_matching_null.py",
)

MATCHING_IDENTITY = (
    Mutation(
        id="78-features-mapping-resolves-a-duplicate-by-order",
        bug="the mapping branch of _resolve_features assigns instead of collecting, so two keys "
            "spelling one address collapse onto one record",
        survival_means=(
            "a wallet's features would be chosen by dict iteration order. Measured on the seven-"
            "wallet universe in hand_computed/test_matching_null_identity.py, the two orderings "
            "of one input publish different matched sets, a capital_deployed SMD of 0 against "
            "0.37796447300922722721451653623418006082, an effective sample size of 3 against 1.8, "
            "and a §6.6 balance table that reads *balanced* in one and *not balanced* in the "
            "other. Nothing raises, nothing is missing, and the matched set is built against a "
            "wallet the matcher cannot see"
        ),
        edits=(
            Edit(
                relpath="matching_null/matching.py",
                find="            collect(key, record)\n",
                replace="            records[key] = record\n",
            ),
        ),
        tests=MATCHING_IDENTITY_TESTS,
    ),
    Mutation(
        id="79-duplicate-refused-only-when-the-records-disagree",
        bug="the collision refusal fires only if the two records differ",
        survival_means=(
            "the papered-over repair in its usual form: it closes the input a reviewer "
            "constructed — two spellings carrying different features — and leaves the rule "
            "unstated. It also puts the two branches of _resolve_features back into "
            "disagreement, since the iterable branch has never asked whether the duplicates agree"
        ),
        edits=(
            Edit(
                relpath="matching_null/matching.py",
                find="        if key in records:\n",
                replace="        if key in records and records[key] != record:\n",
            ),
        ),
        tests=MATCHING_IDENTITY_TESTS,
    ),
    Mutation(
        id="80-permutation-null-takes-the-callers-set-order",
        bug="permutation_null_detail stops ordering the matched sets before drawing",
        survival_means=(
            "_uniform_index keys the draw on a set's *position*, so the same sets in a different "
            "order give wallet A the draw that belonged to wallet B. Measured on the two-set null "
            "in hand_computed/test_matching_null_identity.py, that moves the published null pass "
            "rate from 0.9 to 0.8 — a §8.3 calibration input, changed by nothing but the order of "
            "a list"
        ),
        edits=(
            Edit(
                relpath="matching_null/permutation.py",
                find="    matched_sets = tuple(sorted(matched_sets, key=lambda m: "
                     "m.selected.lower()))\n",
                replace="    matched_sets = tuple(matched_sets)\n",
            ),
        ),
        tests=MATCHING_IDENTITY_TESTS,
    ),
    Mutation(
        id="81-duplicate-matched-set-keyed-on-the-exact-spelling",
        bug="the duplicate-selected refusal compares addresses without folding case",
        survival_means=(
            "the guard would still be there, still named, and blind to the shape the rest of the "
            "package exists to normalise: WalletFeatures lowercases, _distinct_lower refuses two "
            "spellings of one universe member, and MatchedSet is seam-frozen and folds nothing. "
            "A set pair spelled 0xs1 and 0xS1 would be relabelled twice and enter the null twice "
            "under one label"
        ),
        edits=(
            Edit(
                relpath="matching_null/permutation.py",
                find="        key = matched.selected.lower()\n",
                replace="        key = matched.selected\n",
            ),
        ),
        tests=MATCHING_IDENTITY_TESTS,
    ),
    Mutation(
        id="82-repeated-wallet-deduplicated-instead-of-refused",
        bug="_distinct_lower drops a repeated address instead of refusing the list",
        survival_means=(
            "the quiet option taken at the one place the package states the rule out loud. In "
            "`universe` it shrinks the control pool without reporting it; in `selected` it removes "
            "a wallet from the benchmark. This refusal was pinned by nothing at all before "
            "hand_computed/test_matching_null_identity.py — the entire 96-test matching_null "
            "selection stayed green with it disabled, which is how a guard becomes the next "
            "refactor's casualty"
        ),
        edits=(
            Edit(
                relpath="matching_null/matching.py",
                find="        if key in seen:\n"
                     "            raise ValueError(\n"
                     '                "{} contains {} twice. A duplicate would be matched twice '
                     'and would enter the "\n'
                     '                "benchmark twice under one label.".format(label, key)\n'
                     "            )\n",
                replace="        if key in seen:\n            continue\n",
            ),
        ),
        tests=MATCHING_IDENTITY_TESTS,
    ),
)


# -- 50-55: one spelling, one capital level — and one seed per purpose ------------
#
# The same class again, at the two places where it is worst. 50-54 sit in the **arbiter**: the
# §7.2 evidence is keyed by a capital level, the key is produced by ``calc`` plus a snap onto
# ``DESIGN_CAPITAL_LEVELS``, and ``calc`` maps ``str``, ``int`` and ``Decimal`` onto one key space.
# Two caller entries naming $1,500,000 therefore arrived as two and left as one, and
# ``CapitalFeasibility.feasible`` is read directly by ``emit_decision_detail`` — so the survivor,
# and with it GO versus CONDITIONAL_REVIEW, was decided by the order a caller's dict iterated in.
# Measured on the clean-run evidence, the same three entries in two orders published GO and
# CONDITIONAL_REVIEW.
#
# 55 is the same shape in the seed derivation, where the collapse is a flattening rather than a
# normalisation: ``(commit, purpose, index)`` joined with ``|``. Within one commit that join was
# already injective — which is why the permutation null's distinct-seed invariant was never at
# risk, and why the fix is a refusal of the separator rather than a re-encoding that would have
# moved every seed ever recorded.

CAPITAL_KEY_TESTS = (
    "hand_computed/test_gate_capital_keys.py",
    "integration/test_gate_capital_keys.py",
    "hand_computed/test_gate_validation.py",
    "integration/test_gate_validation.py",
)

SEED_FLATTENING_TESTS = (
    "hand_computed/test_seed_field_separator.py",
    "test_skeleton.py",
)

CAPITAL_IDENTITY = (
    Mutation(
        id="83-capital-level-collision-collapses-silently",
        bug="_level_keyed stops detecting collisions and returns the last-one-wins mapping",
        survival_means=(
            "the published §7 verdict would move on dict ordering alone. On the clean-run "
            "evidence, ['1500000', Decimal('1500000'), Decimal('2000000')] publishes GO with "
            "capital_feasibility_failed=False, and the same three entries reordered publish "
            "CONDITIONAL_REVIEW with the -0.0500 measurement at $1.5M intact. One of those two "
            "runs deletes a failing measurement and certifies the result"
        ),
        edits=(
            Edit(
                relpath="gate_validation/windows.py",
                find="    collided = [key for key in order if len(spellings[key]) > 1]\n",
                replace="    collided = []\n",
            ),
        ),
        tests=CAPITAL_KEY_TESTS,
    ),
    Mutation(
        id="84-capital-collision-refused-only-when-the-values-disagree",
        bug="a repeated capital level is recorded only when its excess differs from the one held",
        survival_means=(
            "the papered-over repair, on the arbiter this time. Every input a reviewer would "
            "construct carries two different excesses at one level, so all of them still refuse — "
            "and the guard would be conditioned on the two measurements disagreeing rather than on "
            "nobody being able to say which entry is the entry, which is the actual defect"
        ),
        edits=(
            Edit(
                relpath="gate_validation/windows.py",
                find="        spellings[key].append(level)\n",
                replace="        if not spellings[key] or values[key] != excess:\n"
                        "            spellings[key].append(level)\n",
            ),
        ),
        tests=CAPITAL_KEY_TESTS,
    ),
    Mutation(
        id="85-assess-capital-feasibility-converts-before-the-check",
        bug="assess_capital_feasibility calls dict() on the caller's input again",
        survival_means=(
            "the second half of the defect, restored. dict([(k, a), (k, b)]) applies its own "
            "last-one-wins rule before __post_init__ can object, so a caller supplying §7.2 "
            "evidence as pairs loses an entry and the refusal one layer down reports a clean "
            "mapping — the check would be reading a mapping this function had already cleaned up"
        ),
        edits=(
            Edit(
                relpath="gate_validation/windows.py",
                find="    return CapitalFeasibility(excess_by_level=excess_by_level)\n",
                replace="    return CapitalFeasibility(excess_by_level=dict(excess_by_level))\n",
            ),
        ),
        tests=CAPITAL_KEY_TESTS,
    ),
    Mutation(
        id="86-level-pairs-lets-dict-collapse-the-repeat-first",
        bug="_level_pairs builds a dict before reading the caller's pairs",
        survival_means=(
            "the same collapse one function further in, and the reason _level_pairs exists at all: "
            "a Mapping cannot repeat a key, so pairs are the only door through which a caller can "
            "name one level twice with the *same* spelling, and converting first closes that door "
            "by losing the evidence"
        ),
        edits=(
            Edit(
                relpath="gate_validation/windows.py",
                find="    items = getattr(excess_by_level, \"items\", None)\n"
                     "    return tuple(items() if callable(items) else excess_by_level)\n",
                replace="    return tuple(dict(excess_by_level).items())\n",
            ),
        ),
        tests=CAPITAL_KEY_TESTS,
    ),
    Mutation(
        id="87-capital-post-init-back-to-the-raw-items-loop",
        bug="CapitalFeasibility.__post_init__ keys the mapping itself instead of going through "
            "_level_keyed",
        survival_means=(
            "the shape the defect had before it was closed, and the shape a refactor would "
            "recreate: the snapping happens, the collision does not, and __post_init__ is the only "
            "boundary the type has — emit_decision accepts a CapitalFeasibility, not the output of "
            "assess_capital_feasibility, so a check that lives anywhere else can be walked around"
        ),
        edits=(
            Edit(
                relpath="gate_validation/windows.py",
                find="        keyed = _level_keyed(_level_pairs(self.excess_by_level), "
                     "\"excess_by_level\")\n"
                     "        normalised = {}\n"
                     "        for key, excess in keyed.items():\n",
                replace="        normalised = {}\n"
                        "        for level, excess in self.excess_by_level.items():\n"
                        "            key = _level_key(level)\n",
            ),
        ),
        tests=CAPITAL_KEY_TESTS,
    ),
    Mutation(
        id="88-seed-components-may-carry-the-field-separator",
        bug="derive_child_seed stops refusing a '|' in the commit or the purpose",
        survival_means=(
            "commit='abc|null.leader' with purpose='window1' derives exactly the seed of "
            "commit='abc' with purpose='null.leader|window1' — 9105705412286346049517972469849470"
            "9738616472449431008072485148703461237999389 for both. Two runs pinned to different "
            "commits, which the module's own header promises are different experiments, would draw "
            "the identical 'independent' numbers the permutation null is built from"
        ),
        edits=(
            Edit(
                relpath="phase0/seeds.py",
                find="    if FIELD_SEPARATOR in text:\n",
                replace="    if False:\n",
            ),
        ),
        tests=SEED_FLATTENING_TESTS,
    ),
)


# -- 56-59: a key that disagrees with the value it points at ---------------------
#
# 45-49 cover one half of the identity-key defect in ``pipeline``: two keys naming one asset, where
# something collapses. These cover the other half, where nothing collapses at all — one key names a
# different asset from the ``PoolState`` it holds. The mapping has exactly as many entries as the
# caller wrote and one of them is filed under the wrong name, so no count moves anywhere: the
# census, the quarantine queue and the coverage report of a wrong run are identical to a right
# one's, and the only field that differs is the published return.
#
# 57 is the papered-over form and the one worth keeping longest. A rule stated over raw strings
# passes every test whose keys are already lowercase — which is every test written from the traced
# report — and refuses the checksummed key that §4.2 says is the same asset. It turns a guard
# against a wrong number into a guard against a correct input.

PIPELINE_IDENTITY_TESTS = (
    "hand_computed/test_pipeline_identity.py",
    "hand_computed/test_fifo_identity.py",
    "properties/test_pipeline_identity.py",
)

PIPELINE_IDENTITY = (
    Mutation(
        id="89-key-may-disagree-with-the-pool-it-holds",
        bug="stated_asset always returns None, so the key/value agreement rule never runs",
        survival_means=(
            "a pool book whose values have been transposed — the ordinary shape of a mis-assembled "
            "join, every key correctly spelled — would mark a position against another token's "
            "pool and publish -25% against a true -50%, with an identical census, an empty "
            "quarantine queue and an identical coverage report. On the replacement pools the same "
            "defect one hex digit wide publishes DEAD_ZEROED at -100% with §10 reporting the whole "
            "exposure as dead share, while the position's evidence says 'replacement=none' about a "
            "run that supplied one"
        ),
        edits=(
            Edit(
                relpath="pipeline/inputs.py",
                find="    for kind in type(value).__mro__:\n"
                     "        reader = STATES_ITS_ASSET.get(kind)\n"
                     "        if reader is not None:\n"
                     "            return reader(value)\n"
                     "    return None\n",
                replace="    return None\n",
            ),
        ),
        tests=PIPELINE_IDENTITY_TESTS,
    ),
    Mutation(
        id="90-agreement-compared-as-raw-strings",
        bug="the key/value agreement is compared before normalisation, so §4.2 does not govern it",
        survival_means=(
            "the guard would start refusing correct input: a checksummed pool-book key over a "
            "lowercased pool.asset is one asset named twice in two spellings, and the run must "
            "answer normally. A guard that refuses valid input is worse than no guard, because the "
            "next person deletes it — and deleting it reopens the wrong-number case above"
        ),
        edits=(
            Edit(
                relpath="pipeline/inputs.py",
                find="            if _normalised(stated, described) != canonical:",
                replace="            if stated != key:",
            ),
        ),
        tests=PIPELINE_IDENTITY_TESTS,
    ),
    Mutation(
        id="91-non-string-key-left-to-the-frozen-seam",
        bug="a non-str asset key falls through to normalise_asset and raises AttributeError there",
        survival_means=(
            "the refusal would name neither the mapping nor the key, because it would surface from "
            "contracts.normalise_asset — a module this repository freezes and cannot edit to name "
            "them. Every other refusal at this boundary quotes the caller's own spelling, which is "
            "the one they can search for"
        ),
        edits=(
            Edit(
                relpath="pipeline/inputs.py",
                find="    if not isinstance(text, str):\n        raise TypeError(",
                replace="    if False:\n        raise TypeError(",
            ),
        ),
        tests=PIPELINE_IDENTITY_TESTS,
    ),
    Mutation(
        id="92-pool-book-call-site-reverts-to-dict",
        bug="_normalised_pools builds a dict before asset_pairs can read the caller's pairs",
        survival_means=(
            "case 49 mutates ``asset_pairs`` itself; this mutates one of its four *call sites*, "
            "which is the edit a maintainer actually makes — tidying an unfamiliar helper back to "
            "the obvious ``dict(...)`` spelling. A pool book supplied as pairs with a repeated key "
            "then publishes -25% or -50% for one identical input, decided by which pair came last, "
            "and the collision check reports a clean book because the entry was gone before it ran"
        ),
        edits=(
            Edit(
                relpath="pipeline/run.py",
                find="    supplied = asset_pairs(pools)",
                replace="    supplied = tuple(dict(pools).items())",
            ),
        ),
        tests=PIPELINE_IDENTITY_TESTS,
    ),
)


# -- 60-63: the four the confirm pass found still unpinned ----------------------
#
# ``e31dc22`` was written by four agents editing one checkout, and nobody deletion-tested the merged
# tree. Three of these four survived that merge with the whole suite green — each is a *narrowing*
# of a guard rather than its deletion, which is the shape a refactor produces and a coarse mutation
# misses. 63 is a hole none of the four found: the identity rule applied one function up from the
# capital levels, on the field the arbiter groups its results by.

WINDOW_KEY_TESTS = CAPITAL_KEY_TESTS

NARROWED = (
    Mutation(
        id="93-capital-level-stops-snapping-onto-the-pre-registered-constant",
        bug="_level_key returns calc(value) without snapping onto DESIGN_CAPITAL_LEVELS",
        survival_means=(
            "the stored key keeps whatever exponent the caller wrote. contracts.canonicalise "
            "normalises a Decimal *value*'s exponent and renders a Decimal *key* with str, and "
            "excess_by_level is keyed by the level — so Decimal('1.5E+6') and Decimal('1500000') "
            "serialise the same two measurements as '1.5E+6' and '1500000'. The refusal above "
            "still fires, so nothing collides; what moves is the bytes a decision record hashes to"
        ),
        edits=(
            Edit(
                relpath="gate_validation/windows.py",
                find="    level = calc(value)\n"
                     "    for known in DESIGN_CAPITAL_LEVELS:\n"
                     "        if level == known:\n"
                     "            return known\n"
                     "    return level\n",
                replace="    return calc(value)\n",
            ),
        ),
        tests=CAPITAL_KEY_TESTS,
    ),
    Mutation(
        id="94-stated-asset-looks-up-the-exact-type-instead-of-the-mro",
        bug="stated_asset reads STATES_ITS_ASSET.get(type(value)) rather than walking __mro__",
        survival_means=(
            "every base-class case stays refused and a PoolState *subclass* walks through. Both "
            "pool books type-check with isinstance, so a subclass arrives exactly as the base "
            "class does, and the key/value agreement rule silently stops running for it — the "
            "guard disappearing on a type the check cannot see, which is the same shape as the "
            "collapse it exists to refuse. Measured: -0.25 published against a true -0.5"
        ),
        edits=(
            Edit(
                relpath="pipeline/inputs.py",
                find="    for kind in type(value).__mro__:\n"
                     "        reader = STATES_ITS_ASSET.get(kind)\n"
                     "        if reader is not None:\n"
                     "            return reader(value)\n"
                     "    return None\n",
                replace="    reader = STATES_ITS_ASSET.get(type(value))\n"
                        "    if reader is not None:\n"
                        "        return reader(value)\n"
                        "    return None\n",
            ),
        ),
        tests=PIPELINE_IDENTITY_TESTS,
    ),
    Mutation(
        id="95-matched-sets-ordered-by-the-raw-spelling",
        bug="permutation_null_detail sorts the sets on selected rather than on selected.lower()",
        survival_means=(
            "the null becomes a function of how a caller *capitalised* an address. _uniform_index "
            "keys the draw on a set's position, and '0xB1' < '0xa2' while '0xb1' > '0xa2' — so on "
            "the two-set null in hand_computed/test_matching_null_identity.py the published null "
            "pass rate is 0.9 for 0xB1 and 0.8 for 0xb1, one wallet spelled two ways. §8.3 locks "
            "the threshold against that rate"
        ),
        edits=(
            Edit(
                relpath="matching_null/permutation.py",
                find="key=lambda m: m.selected.lower()))",
                replace="key=lambda m: m.selected))",
            ),
        ),
        tests=MATCHING_IDENTITY_TESTS,
    ),
    Mutation(
        id="96-window-results-grouped-on-an-undefined-identity",
        bug="evaluate_windows_detail stops requiring WindowScore.window to be an int",
        survival_means=(
            "results are grouped into {window: {column: score}}, so window is an identity key, and "
            "the seam declares it int without enforcing it. Python calls 1, True and 1.0 one dict "
            "key. A leader result at window 1 and a follower_adjusted result at window True are "
            "two windows that each lack a required column and each therefore FAIL; grouped they "
            "are one window carrying both columns, and it PASSES — a gate pass manufactured out of "
            "two failures, with nothing in the evaluation recording that a merge happened"
        ),
        edits=(
            Edit(
                relpath="gate_validation/windows.py",
                find="        if not isinstance(score.window, int) or isinstance(score.window, bool):",
                replace="        if False:",
            ),
        ),
        tests=WINDOW_KEY_TESTS,
    ),
)


STAGE_WIRING_TESTS = (
    "integration/test_stage_registry.py",
    "integration/test_stage_runners.py",
)

#: The fourth round: the wiring itself.
#:
#: Mutations 1-63 all assume a stage *ran*. Until the registry existed none of them did: thirteen
#: stages could be authorised, refused, held and recorded by ``phase0`` while
#: ``phase0/cli.py:_trivial_runner`` — "computes nothing on purpose" — was the only runner in the
#: tree. These five ask whether the suite would notice the wiring coming undone in the ways that
#: leave every type check, every docstring and every other test file intact.
STAGE_WIRING = (
    Mutation(
        id="97-a-stage-quietly-loses-its-runner",
        bug="one key is dropped from pipeline.stages.STAGE_RUNNERS",
        survival_means=(
            "the exact situation this registry was written to end, restored one stage at a time. "
            "phase0 keeps authorising main_test, keeps writing its run record, keeps refusing a "
            "second one — and there is nothing to run. The governance trail looks identical; the "
            "only difference is that no measurement exists behind it, and a registry that may be "
            "incomplete is a registry that says nothing about the twelve stages still in it"
        ),
        edits=(
            Edit(
                relpath="pipeline/stages/__init__.py",
                find='    "main_test": decide.main_test_runner,\n',
                replace="",
            ),
        ),
        tests=STAGE_WIRING_TESTS,
    ),
    Mutation(
        id="98-the-two-null-columns-are-crossed-in-the-registry",
        bug="null.follower is registered to inference.null_leader_runner",
        survival_means=(
            "§8.2 requires a null per column and §7.3 tests each result against its own. Crossed, "
            "the follower-adjusted result would be tested against the leader's null — a null built "
            "without the execution costs the follower column exists to carry, so systematically "
            "the easier one to clear. execute_stage takes the runner as an opaque callable and "
            "cannot see it; the seed purposes and the recorded column are the only evidence, and "
            "they only help if something reads them"
        ),
        edits=(
            Edit(
                relpath="pipeline/stages/__init__.py",
                find='    "null.follower": inference.null_follower_runner,\n',
                replace='    "null.follower": inference.null_leader_runner,\n',
            ),
        ),
        tests=STAGE_WIRING_TESTS,
    ),
    Mutation(
        id="99-a-blocked-stage-returns-an-empty-result-instead-of-raising",
        bug="blocked_stage_runner returns () rather than raising StageBlocked",
        survival_means=(
            "the central failure this whole project is built against. golden_set.trace COMPLETES "
            "with an empty value, which publishes '0 hand-traced discrepancies'; "
            "reconciliation.cross_source publishes '0 unexplained differences'; and "
            "validation.independent COMPLETES, which *advances VALIDATION_PASSED* and unlocks the "
            "code-and-data freeze and every execution-lane stage behind it. A run would then walk "
            "to a gate decision having validated nothing, with a clean audit log and a full set of "
            "run records — a wrong answer that looks exactly like a right one"
        ),
        edits=(
            Edit(
                relpath="pipeline/stages/decide.py",
                find="    def runner(context):\n"
                     "        _require_stage(context, stage)\n"
                     "        raise StageBlocked(stage, blockers, produces, empty_reads_as)\n",
                replace="    def runner(context):\n"
                        "        _require_stage(context, stage)\n"
                        "        return ()\n",
            ),
        ),
        tests=STAGE_WIRING_TESTS,
    ),
    Mutation(
        id="100-the-runner-stops-checking-which-stage-it-was-called-for",
        bug="decide._require_stage no longer compares context.stage against the expected key",
        survival_means=(
            "the guard on a crossed registry wire disappears, and it is the only one there is: "
            "execute_stage takes the runner as an opaque callable precisely so that phase0 never "
            "learns what a stage does, so nothing in the shared lane can tell that main_test's "
            "value was filed under decision.emit's authority — completing the transition "
            "DECISION_EMITTED off the back of a stage that emitted no decision"
        ),
        edits=(
            Edit(
                relpath="pipeline/stages/decide.py",
                find="    if context.stage != expected:\n",
                replace="    if False:\n",
            ),
        ),
        tests=STAGE_WIRING_TESTS,
    ),
    Mutation(
        id="104-a-short-universe-crashes-the-step-0-stage-instead-of-being-reported",
        bug="step0.universe raises on a window below §6.1's 10,000-account floor",
        survival_means=(
            "the errors-versus-statuses rule inverted at the exact place it costs most. §6.1's "
            "stopping condition is a *measurement*: a window at 8,400 eligible accounts is the "
            "cheapest and most decisive finding Phase 0 can produce, and this mutation turns it "
            "into a crash — the stage publishes nothing at all, so the counts, the five "
            "distributions and the §13.7 base-rate comparison for the other three windows are lost "
            "with it, and the audit log files the finding as a defect in the code. The reading a "
            "reviewer then gets is 'Step 0 is broken' rather than 'the target population does not "
            "exist at the size the design assumed', which is the one conclusion §13.7 exists to "
            "make reportable. The refusals that *do* have teeth are one step later, on "
            "FrozenUniverse and require_step0_complete, where a short universe may not be frozen "
            "or ranked without an explicit design revision"
        ),
        edits=(
            Edit(
                relpath="pipeline/stages/step0.py",
                find="        # No status is read here, and none is acted on. A window below "
                     "§6.1's floor is a carried\n"
                     "        # finding; the refusals that stop a short universe being *used* are "
                     "on FrozenUniverse and\n"
                     "        # require_step0_complete, one step later.\n"
                     "        return step0_report(\n",
                replace="        report = step0_report(\n",
            ),
            Edit(
                relpath="pipeline/stages/step0.py",
                find="            parameter_freeze_hash=parameter_freeze_hash,\n"
                     "            dataset_snapshot=dataset_snapshot,\n"
                     "        )\n"
                     "\n"
                     "    return runner\n",
                replace="            parameter_freeze_hash=parameter_freeze_hash,\n"
                        "            dataset_snapshot=dataset_snapshot,\n"
                        "        )\n"
                        "        if not report.permits_ranking:\n"
                        "            raise ValueError(\n"
                        '                "window(s) {} measured below the 10,000-account floor"'
                        ".format(\n"
                        "                    \", \".join(k.value for k in "
                        "report.insufficient_windows))\n"
                        "            )\n"
                        "        return report\n"
                        "\n"
                        "    return runner\n",
            ),
        ),
        tests=STAGE_WIRING_TESTS,
    ),
)



# -- 68-69: the real null statistic ---------------------------------------------
#
# ``pipeline.nullstat.window_statistic`` replaces the wiring fixtures' toy statistic with the
# gate's own number, recomputed per relabelling from per-wallet scores supplied once. Both
# mutations below are bugs in the *regrouping*, which is the only part that runs per draw — the
# per-wallet numbers are precomputed, so a defect here moves every one of the 1,000 runs and the
# observed statistic identically, and nothing downstream could tell.

NULLSTAT_TESTS = ("hand_computed/test_nullstat.py",)

NULLSTAT = (
    Mutation(
        id="101-nullstat-keeps-whichever-spelling-arrived-last",
        bug="window_statistic stops refusing a score book that spells one wallet two ways",
        survival_means=(
            "the same identity-key class the arbiter and the matcher already close, open again at "
            "the null's front door: two records under one case-folded wallet collapse to "
            "whichever the caller's mapping yielded last, so the observed statistic and all "
            "1,000 null runs are computed from a score chosen by dict iteration order — a "
            "different published null from the same inputs, with nothing anywhere to say a "
            "choice was made"
        ),
        edits=(
            Edit(
                relpath="pipeline/nullstat.py",
                find="        if key in seen:\n"
                     "            raise ValueError(\n"
                     '                "scores spells wallet {} two ways ({!r} and {!r}). One '
                     'wallet is one score: "\n'
                     '                "keeping both would score it with whichever record the '
                     "caller's mapping \"\n"
                     '                "yielded last, and the null would move with iteration '
                     'order.".format(\n'
                     "                    key, seen[key], wallet\n"
                     "                )\n"
                     "            )\n",
                replace="",
            ),
        ),
        tests=NULLSTAT_TESTS,
    ),
    Mutation(
        id="102-matched-benchmark-loses-its-log-weights",
        bug="the per-set benchmark pools its controls unweighted instead of by total log weight",
        survival_means=(
            "the matched benchmark stops being the benchmark the wallet was matched to: a $100 "
            "control gets the say of a $1,000,000 one, the per-set advantage moves, and with it "
            "the mean the whole permutation null compares — a different §8.3 calibration input "
            "from the same wallets, produced by an aggregation that still looks like a mean"
        ),
        edits=(
            Edit(
                relpath="pipeline/nullstat.py",
                find="    return weighted_mean((m.total_weight, m.value) for m in "
                     "_address_order(members))\n",
                replace='    return weighted_mean((Decimal("1"), m.value) for m in '
                        "_address_order(members))\n",
            ),
        ),
        tests=NULLSTAT_TESTS,
    ),
)


# -- 70: the evidence assembler --------------------------------------------------
#
# ``pipeline.evidence.assemble_run_evidence`` is the one place in ``src/`` that builds the
# arbiter's ``RunEvidence``, and its entire contract is that it collects what the holders of
# record hold and derives nothing. The mutation below deletes the refusal that keeps that true
# where it costs the most: the era's single pinned commit.

EVIDENCE_TESTS = ("integration/test_evidence_assembly.py",)

EVIDENCE = (
    Mutation(
        id="103-a-mixed-commit-era-is-arbitrated-instead-of-refused",
        bug="assemble_run_evidence stops refusing an era whose run records pin two commits",
        survival_means=(
            "the assembler silently derives the one fact its run_status field exists to collect: "
            "with the refusal gone, sorted()[0] picks the alphabetically first commit, so a null "
            "built at one commit and a main test run at another are certified to the arbiter as "
            "one experiment — §9.6's same-code requirement, decided by string ordering, inside a "
            "RunEvidence that looks exactly like a clean one, and the arbiter's own manifest "
            "check cannot see it because both sides of its comparison came from this assembler"
        ),
        edits=(
            Edit(
                relpath="pipeline/evidence.py",
                find="    if len(commits) != 1:\n"
                     "        raise EvidenceIncomplete(\n"
                     '            holder="the run store",\n'
                     '            missing="the run records since the last registered code version '
                     'pin {} different "\n'
                     '                    "commits ({})".format(len(commits), ", '
                     '".join(commits)),\n'
                     '            consequence="§9.6 requires the main test and the null runs to be '
                     'one experiment at "\n'
                     '                        "one commit; an assembler that chose between these '
                     'would be deriving "\n'
                     '                        "the one fact this field exists to collect.",\n'
                     "        )\n",
                replace="",
            ),
        ),
        tests=EVIDENCE_TESTS,
    ),
)


# -- 66-77: the five containment modules -----------------------------------------
#
# Four adversarial reviews of ``src/universe/{provenance,snapshot,artifact,ordering,containment}.py``
# ran ninety-six single-guard deletions between them. **Ninety-four survived the entire suite** at
# 1,817 passed, and the two that went red died on a neighbouring guard crashing a fixture rather
# than on any assertion reading the deleted one — the honest count of guards pinned by a behavioural
# assertion was zero. Those five files are where the whole post-T0 barrier lives.
#
# ``tests/hand_computed/test_containment.py`` is the repair, and these twelve are the standing proof
# that it works: each removes a guard the reviews used, and each has to go red. They are the twelve
# whose survival would restore a *measured* breach rather than a theoretical one, so a future edit
# that hollows one out fails here instead of quietly widening the door again.

CONTAINMENT_TESTS = ("hand_computed/test_containment.py",)

CONTAINMENT = (
    Mutation(
        id="66-selection-can-run-after-the-forward-mount",
        bug="the workspace stops running the ordering gate before handing back the universe",
        survival_means=(
            "the measured breach is back. Walk the eight steps honestly, read post-T0 activity "
            "through the sanctioned reader, then call rank_and_select again: on a thousand-wallet "
            "population ten of the two hundred and fifty selected wallets swapped for wallets with "
            "higher post-T0 activity, nothing raised, containment stayed RUNNING and the look-ahead "
            "audit certified the result with post_t0_values_found=0. This one line is what makes "
            "require_selection_permitted reachable at all — it had zero callers"
        ),
        edits=(
            Edit(
                relpath="universe/ordering.py",
                find="        self._order.require_selection_permitted(what)\n",
                replace="        pass\n",
            ),
        ),
        tests=CONTAINMENT_TESTS,
    ),
    Mutation(
        id="67-the-forward-mount-branch-of-the-gate-is-deleted",
        bug="require_selection_permitted stops recognising the FORWARD_MOUNTED phase",
        survival_means=(
            "a selection re-run with the post-T0 dataset open would be permitted by the one method "
            "whose docstring calls its refusal the single most valuable in the file"
        ),
        edits=(
            Edit(
                relpath="universe/ordering.py",
                find="        if self._phase is Phase.FORWARD_MOUNTED:\n",
                replace="        if False:\n",
            ),
        ),
        tests=CONTAINMENT_TESTS,
    ),
    Mutation(
        id="68-a-forward-mount-can-be-built-by-naming-the-class",
        bug="ForwardMount stops demanding the order's private token",
        survival_means=(
            "step 7 is reachable by writing ForwardMount(artifact, dataset_id, dataset_hash). "
            "Measured: evaluation ran to completion at phase ARTIFACT_SEALED with the pre-T0 "
            "workspace still readable, and the order never learned a mount existed"
        ),
        edits=(
            Edit(
                relpath="universe/ordering.py",
                find="        if token is not _ORDER_TOKEN:\n"
                     "            raise OrderingViolation(\n"
                     "                \"ForwardMount cannot be constructed directly.",
                replace="        if False:\n"
                        "            raise OrderingViolation(\n"
                        "                \"ForwardMount cannot be constructed directly.",
            ),
        ),
        tests=CONTAINMENT_TESTS,
    ),
    Mutation(
        id="69-the-snapshot-cutoff-is-never-compared-to-the-real-t0",
        bug="mount_pre_t0 stops comparing the snapshot's t0_block to the window's T0 block",
        survival_means=(
            "the whole max_block/t0_block apparatus proves only that a snapshot is self-consistent "
            "about a cutoff the caller chose. Measured: a census of rows at T0+500,000 and "
            "T0+999,999 reported VERIFIED and sealed an artifact publishing cutoff_block = "
            "T0+1,000,000, through all eight steps, with containment RUNNING"
        ),
        edits=(
            Edit(
                relpath="universe/ordering.py",
                find="        if snapshot.t0_block != universe.window.t0.block:\n",
                replace="        if False:\n",
            ),
        ),
        tests=CONTAINMENT_TESTS,
    ),
    Mutation(
        id="70-the-mount-stops-checking-the-artifact-is-the-one-sealed",
        bug="ForwardMount.artifact no longer compares the artifact against the hash step 4 recorded",
        survival_means=(
            "the gate falls back to self-consistency, which anybody holding the fields can restore: "
            "measured, a row was rewritten to a wallet that was never selected, artifact_hash was "
            "recomputed with this package's own public function, and evaluation ran over it"
        ),
        edits=(
            Edit(
                relpath="universe/ordering.py",
                find="        if current != self._sealed_hash or artifact.artifact_hash "
                     "!= self._sealed_hash:\n",
                replace="        if False:\n",
            ),
        ),
        tests=CONTAINMENT_TESTS,
    ),
    Mutation(
        id="71-a-published-row-need-not-have-been-constructed",
        bug="SelectedWalletArtifact stops checking that its rows ran their own constructor",
        survival_means=(
            "object.__new__(SelectedWallet) plus a dict update satisfies type(row) is "
            "SelectedWallet and ran no bound at all. Measured: rank 1 of a sealed artifact carried "
            "a wallet the ranking never selected with valid_buys = 1,000,000,000"
        ),
        edits=(
            Edit(
                relpath="universe/artifact.py",
                find="            require_constructed_row(row, \"the sealed artifact\")\n",
                replace="            pass\n",
            ),
        ),
        tests=CONTAINMENT_TESTS,
    ),
    Mutation(
        id="72-verify-hands-the-built-rows-straight-back",
        bug="SelectedWalletArtifact.verify stops rebuilding each row through its own constructor",
        survival_means=(
            "verify would re-run the artifact's invariants and none of its rows', which is how a "
            "negative valid_buys survived a gate whose whole job is to re-run every check. "
            "FrozenUniverse.verify has rebuilt its members since ticket 26; the two must not "
            "disagree"
        ),
        edits=(
            Edit(
                relpath="universe/artifact.py",
                find="        rebuilt = tuple(\n"
                     "            SelectedWallet(rank=row.rank, wallet=row.wallet, "
                     "value=row.value,\n"
                     "                           valid_buys=row.valid_buys, "
                     "account_type=row.account_type)\n"
                     "            for row in self.selections\n"
                     "        )\n",
                replace="        rebuilt = tuple(self.selections)\n",
            ),
        ),
        tests=CONTAINMENT_TESTS,
    ),
    Mutation(
        id="73-the-sealed-artifact-loses-its-descending-order",
        bug="SelectedWalletArtifact stops refusing a value inversion between adjacent ranks",
        survival_means=(
            "a sealed artifact re-ranks with public API only: swap two rows, re-hash with "
            "sealed_artifact, and the published order contradicts the published values while the "
            "ranks stay contiguous. SelectedBasket has had this guard since ticket 28 and the "
            "artifact is the type that actually crosses to evaluation"
        ),
        edits=(
            Edit(
                relpath="universe/artifact.py",
                find="            if previous is not None and _decimal_text(row.value) > "
                     "_decimal_text(previous.value):\n",
                replace="            if False:\n",
            ),
        ),
        tests=CONTAINMENT_TESTS,
    ),
    Mutation(
        id="74-snapshot-evidence-need-not-have-been-verified",
        bug="require_verified_snapshot stops checking that __post_init__ ever ran",
        survival_means=(
            "404 bytes of hand-written pickle produce an object for which type(x) is PreT0Snapshot, "
            "whose max_block is 99,999 blocks past T0 and whose snapshot_hash is the string 'not a "
            "hash of anything' — and it mounted, sealed, and published every isolation claim the "
            "run makes. __reduce__ cannot close it: the payload was written, not dumped"
        ),
        edits=(
            Edit(
                relpath="universe/snapshot.py",
                find="    if getattr(snapshot, \"_evidence_witness\", None) is not _VERIFIED:\n",
                replace="    if False:\n",
            ),
        ),
        tests=CONTAINMENT_TESTS,
    ),
    Mutation(
        id="75-the-t0-boundary-becomes-exclusive-on-the-type",
        bug="PreT0Snapshot.__post_init__ goes back to max_block > t0_block",
        survival_means=(
            "the type and pre_t0_snapshot would state two different T0 boundaries again, and the "
            "type — the one universe/__init__.py exports — would be the lenient one: a census whose "
            "last row was written exactly at T0 was refused by the factory and accepted by the "
            "class. A row written at T0 has already seen the instant the decision is made"
        ),
        edits=(
            Edit(
                relpath="universe/snapshot.py",
                find="        if self.max_block >= self.t0_block:\n",
                replace="        if self.max_block > self.t0_block:\n",
            ),
        ),
        tests=CONTAINMENT_TESTS,
    ),
    Mutation(
        id="76-the-containment-guard-swallows-the-breach",
        bug="_Guard.__exit__ returns True",
        survival_means=(
            "``try: ... except LookAheadViolation: continue`` becomes writable again with a class "
            "attached to it. The basket composition would depend on which wallets raised, which is "
            "post-T0 information deciding membership — SILENTLY_DROPPED, the outcome that looks "
            "like a caught breach and is not one"
        ),
        edits=(
            Edit(
                relpath="universe/containment.py",
                find="        # Never swallow. Returning True here would be the caught-exception "
                     "route, and this class\n"
                     "        # exists to make that unwritable rather than to provide a tidier "
                     "spelling of it.\n"
                     "        return False\n",
                replace="        return True\n",
            ),
        ),
        tests=CONTAINMENT_TESTS,
    ),
    Mutation(
        id="77-the-lattice-calls-every-pair-pre-t0",
        bug="combine returns Origin.PRE_T0 unconditionally",
        survival_means=(
            "the provenance lattice would be an identity function: a value composed from a post-T0 "
            "operand would read PRE_T0 and every constructor downstream would accept it. Not one "
            "test in the repository named combine before this round"
        ),
        edits=(
            Edit(
                relpath="universe/provenance.py",
                find="    if left is Origin.PRE_T0 and right is Origin.PRE_T0:\n"
                     "        return Origin.PRE_T0\n"
                     "    return Origin.CONTAMINATED\n",
                replace="    return Origin.PRE_T0\n",
            ),
        ),
        tests=CONTAINMENT_TESTS,
    ),
)

# -- 106: the tracer bullet's one un-derivable fact ------------------------------
#
# Every mutation above this line moves a number the repository computed from values it was handed.
# This one moves a number decoded from bytes Ethereum mainnet actually returned, which is what
# ticket 19 exists to make possible — so it is the first case here whose control run reads a
# committed snapshot rather than a fixture somebody wrote.
#
# The bug it applies is not invented for the harness. It is the second of the two shortcuts
# ``ingest.receipts`` names in its own module docstring and refuses, and it is the one that looks
# principled: *WETH9 credits the withdrawer, so record the withdrawer as where the ETH went.* That
# sentence is true about the log and false about the transaction — the router forwards the ETH on
# by a plain call, and a plain call writes no log. Taking the true half for the whole is how a
# required argument gets deleted by somebody who has read the ABI carefully.

INGEST_TESTS = ("hand_computed/test_ingest.py", "decoding/test_receipts.py")

INGEST = (
    Mutation(
        id="106-the-unwrap-is-assumed-to-stay-with-the-withdrawer",
        bug="transfers_from_logs ignores native_settlement and files the WETH unwrap's native ETH "
            "as ending on the withdrawer",
        survival_means=(
            "the tracer bullet's proceeds disappear and the receipt still parses cleanly. Log 41 "
            "unwraps 34,502,101,357,740,557 wei to the Universal Router, which forwards it to the "
            "wallet; under this mutation the synthesised leg runs router -> router, so the wallet "
            "sends 137,600,202,427,056,205,955 raw TOKEN_X out and receives nothing back. A sale "
            "becomes a giveaway — the position is a -100% realized return rather than a round "
            "trip, and nothing is missing anywhere to make it loud: eight logs still decode, the "
            "count still balances, the router still nets to zero (trivially, because it now keeps "
            "what it was paid), and the census has no status for 'a leg we invented'. It is also "
            "the one fact in this transaction that no amount of care with these bytes can recover "
            "— it is what a trace would say and what every free endpoint refuses to serve — so a "
            "suite that let it through would have converted the single input ingest makes a caller "
            "*establish* into one it quietly assumes"
        ),
        edits=(
            Edit(
                relpath="ingest/receipts.py",
                find="            counterparty = settlement.get(event.log_index)\n",
                replace="            counterparty = event.holder\n",
            ),
        ),
        tests=INGEST_TESTS,
    ),
)


# -- 107: the population defined by what the decoder happens to know -------------
#
# The bug is not a typo and it is not adversarial. It is the reasonable-sounding shortcut somebody
# reaches for the first time a real wallet contains an event ``SIGNATURES`` does not list: *we
# cannot read this receipt's logs, so record the transaction as having moved nothing and carry on.*
# One clause, no missing argument, no changed number, and every reconciliation in the repository
# still balances.
#
# What it destroys is the distinction the whole ingestion stage exists to hold. A transaction whose
# legs are partly unreadable has an **unknown** net position; a transaction with no transfers has a
# **known** one, namely none. Under this mutation the 1inch limit-order fill in the tracer bullet's
# own window becomes the second: it is attributed (UNRESOLVED, no owner evidence — there are no
# legs to find one on), classified UNSUPPORTED, counted in the census, and excluded by §8 with a
# rule beside it. ``census.total`` still reads 7. ``StageCounts`` still reconciles. The quarantine
# queue is *empty*, ``census.undecodable`` is 0, and nothing anywhere says a log went unread.
#
# That is strictly worse than the defect ticket 19 found. The old behaviour lost the transaction
# and the loss was at least detectable from outside by counting; this keeps the transaction and
# publishes a false statement about it, wearing a §8 exclusion's clothes.

# A note on the selection, added when ticket 20 widened the registry. ``OrderFilled`` is now in
# ``SIGNATURES``, so the tracer bullet's seven transactions all decode and
# ``test_tracer_bullet_window.py`` no longer walks the undecodable path at all — the kill comes
# entirely from ``test_undecodable_population.py``, which uses an event that is still unlisted. The
# file stays in the selection because it is the run that would notice if the *census* stopped
# reconciling, and it costs nothing to keep. What would be wrong is to let the widening quietly
# reduce this case to one file without saying so.

UNDECODABLE_TESTS = ("hand_computed/test_undecodable_population.py",
                     "hand_computed/test_tracer_bullet_window.py")

UNDECODABLE = (
    Mutation(
        id="107-an-unreadable-receipt-is-recorded-as-having-moved-nothing",
        bug="pipeline.chain.observed_transaction swallows the decoder's refusal and returns an "
            "ObservedTransaction with no transfers instead of an UndecodableTransaction",
        survival_means=(
            "the population a run measures would be silently defined by what ingest.events happens "
            "to know, with a census that adds up. The tracer bullet's tail sell — a 1inch limit "
            "order closing a 43,344 XUSDP position — would arrive as a transaction that moved "
            "nothing: UNSUPPORTED in the census, named in the §8 exclusion list with a rule beside "
            "it, absent from the quarantine queue, and undecodable=0. Every count reconciles and "
            "every share is over the right denominator, so no reconciliation can reach it; only a "
            "test that asks whether the *reason* is 'we could not read it' rather than 'nobody "
            "owns it' can. Ticket 20 admitted this particular event, so the tracer bullet's fill "
            "now decodes — the mutation is still live because the next unlisted event does exactly "
            "what this one did, and ERC-1155's TransferSingle is one this decoder has looked at and "
            "declined on purpose. Widen it to a wallet that trades through one and the whole window "
            "becomes no-ops with a clean report"
        ),
        edits=(
            Edit(
                relpath="pipeline/chain.py",
                find="    except (UnknownEvent, LogShapeMismatch) as refusal:\n"
                     "        return UndecodableTransaction(\n",
                replace="    except (UnknownEvent, LogShapeMismatch) as refusal:\n"
                        "        return ObservedTransaction(\n"
                        "            tx_hash=identity,\n"
                        "            block_number=header.number,\n"
                        "            timestamp=header.timestamp,\n"
                        "            success=True,\n"
                        "            tx_sender=sender(receipt),\n"
                        "            transfers=(),\n"
                        "            context=context if context is not None "
                        "else AttributionContext(),\n"
                        "        )\n"
                        "        return UndecodableTransaction(\n",
            ),
        ),
        tests=UNDECODABLE_TESTS,
    ),
)


# -- 108: the id read as an amount ----------------------------------------------
#
# The bug is the obvious next commit after ticket 20. Three signatures were admitted to
# ``SIGNATURES`` and the brief that asked for them also asked for ERC-1155's two; somebody finishing
# the job writes the entry the same way as the others, sees that ``TransferSingle`` obviously moves
# value, gives it ``moves_value=True``, and decodes it like an ERC-20 ``Transfer`` — operator and
# parties in the topics, amount in the data. The shape checks all pass: four topics is what the
# signature says, two data words is what it says, and the addresses are properly padded.
#
# It reads ``data[0:32]``, which on ERC-1155 is the token **id**. On the real log this case's tests
# decode — log 311 of ``0x8ed9a26a…``, an OpenSea-packed id with the creator's address in its top
# twenty bytes — that word is 44,117,174,291,519,862,098,428,858,737,600,272,443,055,727,955,321,
# 698,122,467,893,821,035,107,057,665 and the actual transfer is of one unit. Nothing downstream can
# tell: it is an unsigned integer in raw units, it passes ``Transfer.__post_init__``, it nets, and it
# is priced if the contract ever appears as a quote asset. Second-order and worse: even with the
# right word, ``contracts.Transfer`` names an asset by one address, so two ids of one contract would
# net against each other as a single fungible balance.
#
# The mutation removes the entry from ``DECLINED`` as well, which is what an author convinced the
# event should be read would actually do. Left in both, the disjointness check alone would fail and
# this case would prove only that the tripwire works.

REGISTRY_TESTS = ("decoding/test_events.py", "hand_computed/test_event_registry.py")

REGISTRY = (
    Mutation(
        id="108-an-erc1155-token-id-is-read-as-an-amount",
        bug="ingest.events admits ERC-1155 TransferSingle as an ERC-20-shaped mover, so the token "
            "id in data word 1 arrives as raw_amount",
        survival_means=(
            "a token id would be published as a position. The registry's whole discipline is that "
            "moves_value is stated honestly and the asset is one this seam can name; ERC-1155 "
            "fails the second test even when the first is answered right, and the failure is "
            "silent in both directions — a 4.4e76 raw quantity is an ordinary integer, and two ids "
            "of one contract netting against each other is an ordinary balance. Nothing in the "
            "census, the queue or the coverage report can distinguish it from a real trade, "
            "because on the numbers it is one"
        ),
        edits=(
            Edit(
                relpath="ingest/events.py",
                find="MOVEMENT_DECODERS = frozenset({TRANSFER, WITHDRAWAL, DEPOSIT})",
                replace="MOVEMENT_DECODERS = frozenset("
                        "{TRANSFER, WITHDRAWAL, DEPOSIT, TRANSFER_SINGLE})",
            ),
            Edit(
                relpath="ingest/events.py",
                find="DECLINED = {\n    TRANSFER_SINGLE: Declined(",
                replace="DECLINED = {\n    \"0xnot-a-topic\": Declined(",
            ),
            Edit(
                relpath="ingest/events.py",
                find="SIGNATURES = {\n",
                replace="SIGNATURES = {\n"
                        "    TRANSFER_SINGLE: Signature(\n"
                        "        name=\"TransferSingle\", topic=TRANSFER_SINGLE,\n"
                        "        text=\"TransferSingle(address,address,address,uint256,uint256)\",\n"
                        "        moves_value=True, topics=4, data_words=2,\n"
                        "    ),\n",
            ),
            Edit(
                relpath="ingest/events.py",
                # Indented one level inside ``decode_log``'s ``try``. The anchor read at the
                # outer level until this was corrected, matched nothing, and the case was
                # therefore **never applied** — the harness reported an anchor miss rather than a
                # kill, which is the failure ``_apply``'s assertion exists to make loud.
                find="        if signature.topic == TRANSFER:\n            return TokenTransfer(\n",
                replace="        if signature.topic == TRANSFER_SINGLE:\n"
                        "            return TokenTransfer(\n"
                        "                token=address,\n"
                        "                from_addr=_address_word("
                        "\"0x\" + topics[2], \"TransferSingle.from\"),\n"
                        "                to_addr=_address_word("
                        "\"0x\" + topics[3], \"TransferSingle.to\"),\n"
                        "                raw_amount=int(_member(log, \"data\")[2:66], 16),\n"
                        "                log_index=index,\n"
                        "            )\n"
                        "\n"
                        "        if signature.topic == TRANSFER:\n"
                        "            return TokenTransfer(\n",
            ),
        ),
        tests=REGISTRY_TESTS,
    ),
)


# -- 109-110: the Independent Validator's status, and the block it is worth ------
#
# Ticket 02's register is the only thing standing between "somebody was recorded as the validator"
# and "the comparison the gate reads is evidence". Both mutations below leave every field in the
# record intact — the name, the week-1 start date, the four bound constraints, the budget line —
# and change only what the record is *worth*. That is the shape this failure takes when it is
# written: nobody deletes the constraints, they just stop being load-bearing.

VALIDATOR_TESTS = (
    "hand_computed/test_validator_register.py",
    "integration/test_validator_gate.py",
)

VALIDATOR = (
    Mutation(
        id="109-an-unreviewed-validator-reads-as-machine-independent",
        bug="validation_status's final branch returns MACHINE_INDEPENDENT instead of "
            "NOT_INDEPENDENT",
        survival_means=(
            "every recorded validator would permit the main test. NOT INDEPENDENT is the only one "
            "of the three statuses that blocks anything, so a rule that can never return it is a "
            "three-tier label with two tiers and a gate that always opens — and it opens on the "
            "exact case §9.5 names, a validator whose work no external specialist has reviewed. "
            "The register would still print four constraints and a week-1 start date beside it"
        ),
        edits=(
            Edit(
                relpath="phase0/validator.py",
                find="    if assignment.is_ai_agent:\n"
                     "        return ValidationStatus.MACHINE_INDEPENDENT\n"
                     "    return ValidationStatus.NOT_INDEPENDENT\n",
                replace="    if assignment.is_ai_agent:\n"
                        "        return ValidationStatus.MACHINE_INDEPENDENT\n"
                        "    return ValidationStatus.MACHINE_INDEPENDENT\n",
            ),
        ),
        tests=VALIDATOR_TESTS,
    ),
    Mutation(
        id="110-the-validation-gate-stops-refusing-stages",
        bug="step 2b, the ticket-02 independence check, is deleted from execute_stage",
        survival_means=(
            "'NOT INDEPENDENT blocks the main test' would be a sentence in a report again. The "
            "register would still compute the status, phase0 status would still print it, and "
            "nothing would act on it — validation.independent would run, VALIDATION_PASSED would "
            "be reached, and the five execution-lane stages behind it would open in order. A "
            "status that refuses nothing is a label, and the ticket's whole point is that this "
            "one is a gate"
        ),
        edits=(
            Edit(
                relpath="phase0/execution.py",
                find="    if stage in VALIDATION_GATED_STAGES:\n"
                     '        refusal = preconditions.independence_refusal("stage {}".format('
                     "stage))\n"
                     "        if refusal is not None:\n"
                     "            return _record_outcome(\n"
                     "                audit, ACTION_REFUSED,\n"
                     "                StageResult(stage, REFUSED, requester, None, state_before, "
                     "governance.state,\n"
                     "                            reason=refusal, "
                     "error=NotIndependentError(refusal)),\n"
                     "            )\n"
                     "\n",
                replace="",
            ),
        ),
        tests=VALIDATOR_TESTS,
    ),
)


# -- 111: the freeze that does not bind at the state it names -------------------
#
# Ticket 11's whole worth is a claim about *time*: these numbers were fixed before anybody saw a
# result. The claim survives only if the refusal fires at the state that records the fixing.
#
# ``ParameterRegister.frozen`` reads frozen-ness out of the governance machine rather than storing
# it, so there is exactly one comparison holding the two together, and it is an inequality. Off by
# one character it becomes a strict ``>``: at ``PARAMETERS_FROZEN`` itself — the state the whole
# ticket exists to reach — the register reads NOT FROZEN, and ``request_change`` answers with the
# *softer* refusal, the one whose message says the values change by editing the document and the
# module together "BEFORE anybody freezes". Both refusals still raise, both still write an audit
# entry naming the requester, and the audit entry records the freeze status as NOT FROZEN. So a
# reader six months later, checking whether the pre-registration bound, finds a log saying it did
# not — while ``phase0 status`` prints ``PARAMETERS_FROZEN`` two lines above.
#
# The mutation only begins to bite at ``VALIDATION_PASSED``, which is where a run would notice it
# — long after the golden set was hand-traced against parameters the machine did not consider
# closed.

PARAMETER_FREEZE_TESTS = ("hand_computed/test_parameters.py",)

PARAMETER_FREEZE = (
    Mutation(
        id="111-the-parameter-freeze-does-not-bind-at-the-state-that-records-it",
        bug="ParameterRegister.frozen requires a state strictly past PARAMETERS_FROZEN",
        survival_means=(
            "the freeze would not bind at the moment it is performed. Every write is still "
            "refused — so nothing looks broken — but by the wrong rule and with the wrong record: "
            "the refusal says the set is not frozen, the audit entry says freeze_status NOT "
            "FROZEN, and the one thing a later reader has to be able to establish, that the "
            "numbers were closed before anybody saw a result, is contradicted by the log that "
            "exists to establish it"
        ),
        edits=(
            Edit(
                relpath="phase0/parameters.py",
                find="        return position(self._governance.state) >= position(PARAMETERS_FROZEN)",
                replace="        return position(self._governance.state) > position(PARAMETERS_FROZEN)",
            ),
        ),
        tests=PARAMETER_FREEZE_TESTS,
    ),
    # -- 112: §10's report quietly covering fewer wallets than the run selected --
    #
    # The activity bands used to be written out twice — once in ``universe/protocol.py``, which
    # said in its own comment that it was "a known drift surface rather than presented as a
    # design", and once in ``reporting/diagnostics.py``. Ticket 11 gave them one home, and the
    # tiling check came with it because a band table has a failure mode that nothing downstream
    # can see: a gap.
    #
    # Every wallet whose valid-buy count falls in the hole is reported under no band at all. The
    # §10 sensitivity table then sums to fewer wallets than the run selected, and there is no
    # column anywhere that says so — a short band looks exactly like a band that happened to be
    # thin, which is a *finding* rather than an omission. It is the same shape of defect as a
    # dropped row in the census: the number that is wrong is the one nobody printed.
    Mutation(
        id="112-a-gap-between-activity-bands-is-accepted",
        bug="the bands unit accepts a table whose bands do not tile, only checking they ascend",
        survival_means=(
            "§10's breakdown could develop a hole and report fewer wallets than the run selected, "
            "with nothing naming the ones it dropped. The bands are the one place a wallet can "
            "leave the report without leaving a refusal behind, because an under-covered band "
            "reads as a thin band and a thin band is a result"
        ),
        edits=(
            Edit(
                relpath="phase0/parameters.py",
                find="        if previous_high is not None and low != previous_high + 1:",
                replace="        if previous_high is not None and low < previous_high:",
            ),
        ),
        tests=PARAMETER_FREEZE_TESTS,
    ),
    # -- 113: the placeholder rule narrowed back to the case that was reported --
    #
    # This one is not hypothetical in either direction. The hole was real: on 2026-08-16 a person
    # following this project's own instructions pasted `--requester "<نام شما>"` and the register
    # recorded the pre-registration as frozen by that string, under a real commit and a real date.
    # Every spelling in NON_NAMES is English, so nothing objected.
    #
    # The mutation is the obvious over-fitted fix — keep the bracket rule, but only for the pair
    # that showed up in the bug report. It passes the case everyone remembers and reopens the hole
    # for every other convention, which is the shape a regression takes when the fix is written from
    # the incident rather than from the reason. A freeze carrying a plausible commit and a
    # placeholder name is worse than one carrying an obvious blank, because it looks signed.
    Mutation(
        id="113-the-placeholder-rule-covers-only-angle-brackets",
        bug="the placeholder bracket table is narrowed to <...>, the pair from the bug report",
        survival_means=(
            "the pre-registration could be frozen by nobody again, through any documentation "
            "convention other than the single one that was reported. The record would carry a real "
            "commit and a real date beside a name no one can be asked about, and the claim the "
            "whole freeze exists to support -- that these numbers were fixed, by someone, before "
            "any result was seen -- would rest on a signature nobody wrote"
        ),
        edits=(
            Edit(
                relpath="phase0/validator.py",
                find='    ("<", ">"), ("[", "]"), ("{", "}"), ("(", ")"),\n'
                     '    ("«", "»"), ("《", "》"), ("〈", "〉"), ("（", "）"), ("【", "】"),',
                replace='    ("<", ">"),',
            ),
        ),
        tests=PARAMETER_FREEZE_TESTS,
    ),
)


# -- 114: the arbiter goes back to certifying what it was handed -----------------

ARBITER_TESTS = ("hand_computed/test_gate_validation.py", "properties/test_gate_validation.py")

ARBITER = (
    Mutation(
        id="114-the-arbiter-stops-checking-the-first-hour-share-it-was-given",
        bug="the edge-origin consistency check is removed, so a status and its share need not agree",
        survival_means=(
            "§7.1's third condition would again be certified without being examined. The status is "
            "an enum `scoring` computed and the share arrives in the same object; with nothing "
            "comparing them, a scoring defect stamping VALID on a first-hour share of 0.95 "
            "produces a GO that no test in the arbiter can distinguish from a real one -- while "
            "the number that would expose it sits one attribute away. This was the state of the "
            "package until ticket 33's audit: it held no first-hour limit at all"
        ),
        edits=(
            Edit(
                relpath="gate_validation/windows.py",
                find="            _require_consistent_edge_origin(score)\n",
                replace="",
            ),
        ),
        tests=ARBITER_TESTS,
    ),
    Mutation(
        id="115-exactly-forty-percent-stops-being-a-passing-share",
        bug="the first-hour comparison is tightened from > to >=",
        survival_means=(
            "a window the pre-registration admits would be refused as inconsistent, and the "
            "refusal would read as a scoring defect. Ticket 09 resolved §7.1 as strictly greater "
            "than 40% failing, so exactly 40% passes -- a boundary nobody pins is a boundary that "
            "moves by one character"
        ),
        edits=(
            Edit(
                relpath="gate_validation/windows.py",
                find="    if status is EdgeOriginStatus.VALID and share > FIRST_HOUR_EDGE_SHARE_MAX:",
                replace="    if status is EdgeOriginStatus.VALID and share >= FIRST_HOUR_EDGE_SHARE_MAX:",
            ),
        ),
        tests=ARBITER_TESTS,
    ),
)


# -- 116-117: §7.3's bounds go back to being taken on trust ----------------------

NULL_CHECK_TESTS = ("hand_computed/test_gate_validation.py",)

NULL_CHECK = (
    Mutation(
        id="116-the-arbiter-stops-recomputing-the-null-bounds",
        bug="the permutation-result consistency check is removed for the leader column",
        survival_means=(
            "§7.3 would again be decided on two fields the caller declared, with the distribution "
            "they are derived from sitting unread in the same object. The fixtures in this "
            "repository declared p = 0.01 over a three-run null for a year; three runs cannot "
            "report below 1/(3+1) = 0.25, so `p <= 0.05` was arithmetically unreachable and the "
            "suite asserted it anyway. A null summary off by one rung produces a GO nothing can "
            "distinguish from a real one"
        ),
        edits=(
            Edit(
                relpath="gate_validation/decision.py",
                find="    _require_consistent_null(leader_null)\n",
                replace="",
            ),
        ),
        tests=NULL_CHECK_TESTS,
    ),
    Mutation(
        id="117-the-permutation-correction-is-dropped-from-the-p-value",
        bug="empirical p becomes #{null >= observed} / n, without the +1 on either side",
        survival_means=(
            "a distribution no run beat would report p = 0 -- a claim no finite number of runs can "
            "support -- and it would clear `p <= 0.05` on an arithmetic artefact rather than on "
            "evidence. The +1 is what makes the smallest reportable p at 1,000 runs equal 1/1001, "
            "which is what the evidence actually bounds"
        ),
        edits=(
            Edit(
                relpath="gate_validation/decision.py",
                find=("    return divide(sum(1 for v in ordered if v >= observed) + 1, "
                      "len(ordered) + 1)"),
                replace="    return divide(sum(1 for v in ordered if v >= observed), len(ordered))",
            ),
        ),
        tests=NULL_CHECK_TESTS,
    ),
)


# -- 118-119: the reconciliation queue loses its consumer again ------------------

RECONCILIATION_TESTS = ("integration/test_pipeline.py",)

RECONCILIATION = (
    Mutation(
        id="118-the-residual-record-is-stamped-netting-and-vanishes-from-the-queue",
        bug="the reconciliation-queue record is stamped Stage.NETTING instead of RECONCILIATION",
        survival_means=(
            "the invariant that every ABOVE_TOLERANCE_RESIDUAL reaches the RECONCILIATION queue "
            "would find zero records against one residual and the run would publish it silently. "
            "The distinct RECONCILIATION stage is load-bearing: a NETTING record means 'netting "
            "refused this and produced no result', the opposite of a residual, and misfiling one "
            "there both hides it from the residual invariant and double-counts it against the "
            "census's netting-quarantine count. `netting.reconciliation_queue` had zero callers "
            "before this loop, which is exactly how the residual's volume went missing"
        ),
        edits=(
            Edit(
                relpath="pipeline/run.py",
                find="            stage=Stage.RECONCILIATION,",
                replace="            stage=Stage.NETTING,",
            ),
        ),
        tests=RECONCILIATION_TESTS,
    ),
    Mutation(
        id="119-a-residual-record-forgets-the-volume-netting-priced",
        bug="the residual quarantine record is written with volume_usd=None",
        survival_means=(
            "the queue would report the residual as unpriceable when netting had in fact priced it. "
            "A residual whose volume reads None looks free, and addendum §8's whole point is that "
            "the volume excluded from the primary metric is the measure of what the headline number "
            "leaves out -- reporting it as unknown when it is known understates that by exactly the "
            "residual"
        ),
        edits=(
            Edit(
                relpath="pipeline/run.py",
                find="            volume_usd=residual.quote_usd,",
                replace="            volume_usd=None,",
            ),
        ),
        tests=RECONCILIATION_TESTS,
    ),
)


MUTATIONS = (GATE_AND_PIPELINE + REALIZED_RETURN + FILL_RATIO + MARKING + FIFO
             + PIPELINE + REPORTING + PHASE0 + KNOWN_ANSWER + IDENTITY + UNIVERSE
             + CONTAINMENT
             + MATCHING_IDENTITY + CAPITAL_IDENTITY + PIPELINE_IDENTITY + NARROWED
             + STAGE_WIRING + NULLSTAT + EVIDENCE + INGEST + UNDECODABLE + REGISTRY
             + VALIDATOR + PARAMETER_FREEZE + ARBITER + NULL_CHECK + RECONCILIATION)

#: Checked by :func:`test_mutation_anchor_still_matches_the_source` alongside the rest, so an
#: equivalent mutant cannot go stale unnoticed and quietly stop being applied at all.
ALL_CASES = MUTATIONS + EQUIVALENT

#: Every distinct test selection, run once against an unmutated copy. See ``test_control_*``.
SELECTIONS = tuple(sorted({m.tests for m in ALL_CASES}))


# -- machinery ------------------------------------------------------------------


def _apply(mutation, root):
    """Apply every edit to the copy at ``root``. Fails loudly if an anchor no longer matches.

    A mutation that cannot be applied must never be reported as one that was killed — that reads
    as "the suite caught it" when what actually happened is that nothing was tested.
    """
    for edit in mutation.edits:
        path = os.path.join(root, edit.tree, edit.relpath)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        found = text.count(edit.find)
        assert found == edit.occurrences, (
            "mutation {}: expected {} occurrence(s) of the anchor in {} but found {}. The source "
            "has been reshaped; the mutation was NOT applied and this case proves nothing until "
            "the anchor is updated to the code's actual shape.\nanchor:\n{}".format(
                mutation.id, edit.occurrences, edit.relpath, found, edit.find
            )
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(edit.find, edit.replace))


def _run(root, test_files):
    """Run the selected test files inside the workspace at ``root``, in a subprocess.

    Everything is resolved from inside the workspace: the test paths, the working directory, and
    ``pyproject.toml``'s ``pythonpath = ["src"]`` (relative to the rootdir pytest derives from the
    arguments). ``PYTHONPATH`` is pinned to the workspace's ``src`` as well, so a run can only reach
    the repository's own source through a path this function does not control — and the control
    cases would catch that, because they would go green while a mutation went green too.
    """
    cmd = [sys.executable, "-m", "pytest", "-x", "-p", "no:cacheprovider"] + [
        os.path.join(root, "tests", name) for name in test_files
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(root, "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        cmd, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=RUN_TIMEOUT_SECONDS,
    )


#: Byte-code and cached examples are excluded so a workspace cannot inherit a stale import, and
#: ``mutations`` is excluded so this harness can never be collected inside its own subprocess.
_IGNORED = shutil.ignore_patterns("__pycache__", ".hypothesis", "mutations", "*.pyc")


def _workspace(root):
    """Lay out ``src/`` + ``tests/`` + ``pyproject.toml`` under ``root``.

    ``pyproject.toml`` comes too: it carries the pytest configuration, so a workspace run uses the
    same ``addopts`` and the same ``pythonpath`` rule as an ordinary run — now resolved against the
    workspace instead of the repository.

    ``tools/`` comes too, for one reason: ``tools/tracer_bullet.py`` is the only caller that drives
    the real composition root over committed mainnet bytes, so the tests pinning ticket 19's
    findings import it. Without it those tests fail to *collect*, and a control run that errors on
    import is indistinguishable from one that fails on an assertion — the harness would refuse the
    selection rather than silently report a kill, but the case would be unusable either way.
    """
    shutil.copytree(SRC, os.path.join(root, "src"), ignore=_IGNORED)
    shutil.copytree(TESTS, os.path.join(root, "tests"), ignore=_IGNORED)
    shutil.copytree(TOOLS, os.path.join(root, "tools"), ignore=_IGNORED)
    shutil.copy2(os.path.join(REPO, "pyproject.toml"), os.path.join(root, "pyproject.toml"))
    return root


@pytest.fixture(scope="session")
def pristine(tmp_path_factory):
    """One unmutated workspace, built once and copied per mutation.

    The working tree is never written to: a harness that mutated the repository in place would be
    one interrupted run away from committing a deliberate bug.
    """
    return _workspace(str(tmp_path_factory.mktemp("pristine")))


@pytest.fixture(scope="session")
def control_results():
    """Cache of pristine runs, keyed by selection, so a shared selection is run once."""
    return {}  # type: Dict[Tuple[str, ...], int]


def _mutant(pristine_root, tmp_path, mutation):
    root = os.path.join(str(tmp_path), "mutant")
    shutil.copytree(pristine_root, root, ignore=_IGNORED)
    _apply(mutation, root)
    return root


def _control(pristine, control_results, selection):
    """Exit code of the unmutated run for ``selection``, computed once and cached.

    Cached rather than ordered: the kill cases must be able to establish their own baseline when
    only some of them are selected (``-k``, ``--lf``, a rerun of one id), because a case that
    silently skipped its baseline would report a kill it had not earned.
    """
    if selection not in control_results:
        control_results[selection] = _run(pristine, selection).returncode
    return control_results[selection]


# -- the harness ----------------------------------------------------------------


@pytest.mark.parametrize("mutation", ALL_CASES, ids=lambda m: m.id)
def test_mutation_anchor_still_matches_the_source(mutation):
    """Every anchor is present, exactly as often as expected — checked without a subprocess.

    This is the fast failure. When the source is refactored the anchors go stale, and the useful
    report is "the code changed shape here", delivered in milliseconds, rather than nineteen slow
    cases each failing for its own reason.
    """
    for edit in mutation.edits:
        path = os.path.join(REPO, edit.tree, edit.relpath)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        assert text.count(edit.find) == edit.occurrences, (
            "mutation {} no longer matches {}/{}: expected {} occurrence(s) of\n{}".format(
                mutation.id, edit.tree, edit.relpath, edit.occurrences, edit.find
            )
        )


@pytest.mark.parametrize("selection", SELECTIONS, ids=lambda s: "+".join(s))
def test_control_selection_passes_unmutated(pristine, control_results, selection):
    """The same files, the same machinery, no mutation: must be green.

    Without this, a harness that pointed at the wrong ``src``, mistyped a path, or failed to import
    anything at all would report nineteen kills and prove nothing.
    """
    assert _control(pristine, control_results, selection) == 0, (
        "the unmutated control run failed for {}, so no kill in this file means "
        "anything".format(" ".join(selection))
    )


@pytest.mark.parametrize("mutation", MUTATIONS, ids=lambda m: m.id)
def test_mutation_is_killed(pristine, control_results, tmp_path, mutation):
    """The suite must go red. A green run here is a hole, and the hole is named in the message."""
    assert _control(pristine, control_results, mutation.tests) == 0, (
        "the control run for {} did not pass, so this case cannot distinguish a kill from a "
        "broken harness".format(" ".join(mutation.tests))
    )

    root = _mutant(pristine, tmp_path, mutation)
    result = _run(root, mutation.tests)

    assert result.returncode != 0, (
        "MUTATION SURVIVED: {}\n"
        "  bug        : {}\n"
        "  ran        : {}\n"
        "  consequence: {}\n"
        "Nothing in those tests distinguishes the mutated code from the real one. This is a hole "
        "in the suite, not a problem with the harness — the fix is a test that pins the "
        "behaviour, not a weaker assertion here.".format(
            mutation.id, mutation.bug, " ".join(mutation.tests), mutation.survival_means
        )
    )


@pytest.mark.parametrize("mutation", EQUIVALENT, ids=lambda m: m.id)
def test_equivalent_mutation_is_indistinguishable(pristine, control_results, tmp_path, mutation):
    """The inverse assertion: this mutation must **survive**, because no input can reach it.

    A failure here is good news and still a failure. It means the state the guard protects has
    become reachable — so the guard now has an observable effect, and the case belongs back in
    :data:`MUTATIONS` with a test that pins it. The reason it is currently unreachable is recorded
    in ``survival_means`` and is printed on failure, so whoever sees this has the argument they
    need to check rather than a bare red.
    """
    assert _control(pristine, control_results, mutation.tests) == 0, (
        "the control run for {} did not pass, so this case cannot distinguish an equivalent "
        "mutant from a broken harness".format(" ".join(mutation.tests))
    )

    root = _mutant(pristine, tmp_path, mutation)
    result = _run(root, mutation.tests)

    assert result.returncode == 0, (
        "AN EQUIVALENT MUTANT WAS KILLED: {}\n"
        "  bug        : {}\n"
        "  ran        : {}\n"
        "  why it was believed unreachable: {}\n"
        "Something now distinguishes this mutation from the real code, which means the state the "
        "guard protects has become reachable. Move this case into MUTATIONS — it is a real "
        "behaviour with a real test behind it now.".format(
            mutation.id, mutation.bug, " ".join(mutation.tests), mutation.survival_means
        )
    )
