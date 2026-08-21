"""The stage registry: every key in :data:`phase0.runs.STAGES`, and the factory that builds its runner.

``phase0.execution.execute_stage(stage, runner, ...)`` authorises a stage, writes its run record
*before* it runs, calls the runner, and records ``COMPLETED`` / ``REFUSED`` / ``HELD`` / ``CRASHED``.
It takes the runner as an argument because ``phase0`` is SHARED and must not know what a stage does.
That half has existed and worked since ticket 06; the only runner anywhere in the tree was
``phase0/cli.py:_trivial_runner``, whose docstring says it "computes nothing on purpose". Thirteen
stages could be authorised, refused, held and recorded, and not one of them did any work.

This package is the other half. It lives in ``src/pipeline`` because ``pipeline`` is the composition
root — the one builder package permitted to import other builder packages — and because
``tests/test_lane_independence.py`` forbids the ``(SHARED, BUILDER)`` edge these runners would need
if they lived in ``phase0``. The dependency arrow points *from* the builder lane *into* ``phase0``,
never back: :mod:`pipeline.execute` imports ``phase0`` and hands it a callable, and nothing in
``phase0`` imports this package or could. Injection is what makes that direction possible.

Why a registry of *factories* rather than of runners
----------------------------------------------------

A runner is ``runner(context) -> value`` and takes no inputs, so it has to be built with its inputs
already pinned. Each factory therefore has its own signature — ``pipeline.buy_quality`` needs a
window and a pool book, ``threshold.calibrate`` needs the two nulls, ``golden_set.trace`` needs
nothing at all. :func:`runner_for` is the one place that maps a stage key onto a factory, so a
crossed wire has exactly one place to be wrong, and every runner here also checks
``context.stage`` from the inside — see ``decide._require_stage`` and ``inference._require_stage``
for why an opaque callable needs that check to be made twice.

What completeness means, and what it does not
----------------------------------------------

:data:`STAGE_RUNNERS` covers all thirteen keys, and
``tests/integration/test_stage_registry.py`` fails if it and ``STAGES`` disagree in *either*
direction. A missing key would mean a stage silently has no runner, which is the situation this
package exists to end; an extra key would mean a runner nobody can request, which is a stage that
looks wired and is not.

Completeness is a claim about coverage, not about capability. Three of the thirteen are wired to
:mod:`pipeline.stages.decide`'s blocked-stage runners, which **always raise**, naming the ticket
they are waiting for:

    golden_set.trace               needs an authenticated archival node (ticket 03)
    reconciliation.cross_source    needs two independent data sources (tickets 03, 12, 13)
    validation.independent         src/groundtruth/ does not exist (tickets 02, 36)

They are registered rather than omitted deliberately. A blocked stage that is absent from the
registry is indistinguishable from a stage nobody got to; a blocked stage that is present and
refuses loudly is a fact about the tree that a run record and an audit entry will carry. Neither
returns an empty result, a zero, or a ``None`` that could be read as a measurement — a wrong number
that looks plausible is the failure mode this project exists to prevent.

The ten that are wired to real work reach it through the leaf builder packages, which stay leaves:
this package composes them, and none of them imports a sibling.

``step0.universe`` was the fourth blocked stage until ``src/universe/`` was merged. It is now wired
to :mod:`pipeline.stages.step0`, and it is the one entry where "wired" and "will produce a value
today" still come apart: called with no observations it returns the *same* blocked runner under one
blocker — ticket 12, no measured universe, because nothing in this repository has touched real
chain data. That is a fact about the data rather than about this registry, which is why it is not
in :data:`BLOCKED_STAGES`: the stage can run, and there is nothing yet for it to run on.
"""

from . import benchmark, decide, inference, measure, step0

#: Stage key -> the factory that builds that stage's runner.
#:
#: Every key of :data:`phase0.runs.STAGES` appears here exactly once. The values are factories,
#: not runners: a runner takes only a ``StageContext``, so its inputs must already be closed over,
#: and each factory's signature is that stage's inputs. See :func:`runner_for`.
STAGE_RUNNERS = {
    # -- blocked. These raise decide.StageBlocked naming the ticket. ---------------
    "golden_set.trace": decide.golden_set_trace_runner,
    "reconciliation.cross_source": decide.reconciliation_cross_source_runner,
    "validation.independent": decide.validation_independent_runner,

    # -- wired to real work --------------------------------------------------------
    "step0.universe": step0.step0_universe_runner,
    "known_answer.battery": measure.known_answer_battery_runner,
    "pipeline.buy_quality": measure.buy_quality_runner,
    "benchmark.match": benchmark.benchmark_match_runner,
    "follower.adjust": benchmark.follower_adjust_runner,
    "null.leader": inference.null_leader_runner,
    "null.follower": inference.null_follower_runner,
    "threshold.calibrate": inference.threshold_calibrate_runner,
    "main_test": decide.main_test_runner,
    "decision.emit": decide.decision_emit_runner,
}

#: The stages whose registered factory always raises, and the ticket each is waiting for.
#:
#: A mapping rather than a set so the reason travels with the name: a reader of the registry sees
#: what is blocked *and* what would clear it without opening :mod:`pipeline.stages.decide`. The
#: authority on the full refusal is still the runner's own ``StageBlocked``; this is an index, and
#: ``tests/integration/test_stage_registry.py`` checks that every stage named here does in fact
#: refuse and that no stage outside it does.
BLOCKED_STAGES = {
    "golden_set.trace":
        "tickets 03, 13 — hand-traced expected outputs need an authenticated archival node",
    "reconciliation.cross_source":
        "tickets 03, 12, 13 — a second independent data source",
    "validation.independent":
        "tickets 02, 36 — src/groundtruth/ does not exist",
}

#: The ten stages whose runner does real work. Derived, so it cannot drift from the other two.
#:
#: "Live" is a claim about the runner, not about the data: ``step0.universe`` is here because it
#: measures whatever windows it is given, and it still refuses when it is given none. See the
#: module docstring.
LIVE_STAGES = tuple(sorted(set(STAGE_RUNNERS) - set(BLOCKED_STAGES)))

__all__ = [
    "STAGE_RUNNERS",
    "BLOCKED_STAGES",
    "LIVE_STAGES",
    "UnregisteredStage",
    "runner_for",
    "benchmark",
    "decide",
    "inference",
    "measure",
    "step0",
]


class UnregisteredStage(KeyError):
    """A stage key with no registered factory.

    A :class:`KeyError` subclass rather than a governance refusal, and the distinction is the one
    ``execute_stage`` draws for an unknown stage: a refusal is governance working, and this is a
    caller that is wrong. Nothing about the run is at fault, so nothing about the run is recorded.
    """


def runner_for(stage, **inputs):
    """Build the runner for ``stage`` from its inputs.

    :param stage: a key of :data:`STAGE_RUNNERS`, which is every key of ``phase0.runs.STAGES``.
    :param inputs: the stage's own inputs, passed straight to its factory. The three blocked stages
        take none, and ``step0.universe`` accepts none *and then refuses*, which is a different
        sentence. Every other signature is that factory's, documented on it, and deliberately not
        restated here — a second copy of an argument list is a second thing to get out of date.
    :returns: ``runner(context) -> value``, the callable ``execute_stage`` takes.
    :raises UnregisteredStage: for a key with no factory.

    **Wiring defects raise from here, before any run record exists.** Each factory validates what it
    can at wiring time — a ``main_test`` handed a bare ``WindowEvaluation``, a null column missing
    its partner, a blocked stage wired to name no blocker — and this function does not catch any of
    it. That is the intended split: a defect in what *assembled* the call is not a stage outcome and
    must not be recorded as one, while a defect *inside* the stage reaches ``execute_stage`` and is
    recorded as ``CRASHED`` against a run record that says what it was about to do.

    The consequence, stated because it is a real one: a mis-wired stage raises here even in a run
    that governance would have refused, so the refusal never happens and never appears in the audit
    log. The wiring error is the more urgent fact and it is not silent, but a reader of the audit
    log alone will not see that a stage was requested.
    """
    try:
        factory = STAGE_RUNNERS[stage]
    except KeyError:
        raise UnregisteredStage(
            "no runner is registered for stage {!r}. Registered stages are: {}. A stage with no "
            "runner can still be authorised, recorded and refused by phase0 while computing "
            "nothing, which is exactly the gap this registry closes — so an unknown key is a "
            "caller error rather than a permissive default.".format(
                stage, ", ".join(sorted(STAGE_RUNNERS))
            )
        )
    return factory(**inputs)
