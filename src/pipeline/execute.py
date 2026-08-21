"""The builder-lane entry point: run a governed stage with a *real* runner injected.

    run_stage(stage, requester, wiring=..., commit=..., dataset_snapshot=..., inputs={...})

:func:`phase0.execution.execute_stage` checks the start gate, obtains governance's authorisation,
writes the run record, calls ``runner(context)``, and records ``COMPLETED`` / ``REFUSED`` / ``HELD``
/ ``CRASHED``. It takes the runner as an argument. This module supplies it, from
:data:`pipeline.stages.STAGE_RUNNERS`.

Why there are two entry points, and why neither is dead code
------------------------------------------------------------

``phase0/cli.py`` has a ``run`` command that injects ``_trivial_runner``. It is **not** superseded
by this module and must not be deleted:

* It is the governance demo. It exists to show — from a shell, with no builder code present at all —
  that the ordering rules refuse, hold, record and advance correctly. That demonstration is only
  worth something if the injected stage body computes nothing: if it did real work, a green run
  would be evidence about the pipeline rather than about governance, which is the one thing it is
  supposed to isolate.
* It *cannot* be the real one. ``phase0`` is SHARED. ``tests/test_lane_independence.py`` forbids the
  ``(SHARED, BUILDER)`` edge, so a ``phase0`` command line that knew what a stage does would be that
  forbidden import wearing a different hat — and the reason the edge is forbidden is that governance
  which could call the pipeline could be asked to call it differently.

This module is the real one, and it lives in the builder lane because that is where knowing what a
stage does is allowed. The injection runs one way: ``pipeline`` imports ``phase0`` and hands it a
callable; ``phase0`` imports nothing from here and cannot. Anyone tempted to add ``import pipeline``
to ``phase0`` to "finish the wiring" has the direction backwards — the wiring is already finished,
in this file, pointing the other way.

So: two entry points, two different questions. ``phase0 run`` answers "does governance work?".
``run_stage`` answers "does this stage work, under governance?". Deleting either one deletes an
answer.

What this module does not do
-----------------------------

It does not assemble a stage's inputs. Those are Python objects — a pool book, four windows of
matched sets, a ``RunEvidence`` — and the caller that has them is the caller that owns them. It
does not check that ``inputs`` and the ``config`` recorded in the run record describe each other,
for the reason :mod:`pipeline.stages.measure` gives: a second authority on what a run's inputs were
is how two authorities come to disagree.

It also does not decide anything. Every refusal below belongs to ``phase0`` (the start gate,
governance) or to the stage's own factory (a wiring defect). Nothing here interprets an outcome, and
in particular nothing here turns a ``CRASHED`` blocked stage into a friendlier status.
"""

import argparse
import inspect
import os
import sys

from phase0.cli import EXIT_CODES  # one definition of "the outcome is the exit code"
from phase0.errors import Phase0Error
from phase0.execution import execute_stage, wire
from phase0.runs import STAGES

from .stages import BLOCKED_STAGES, STAGE_RUNNERS, runner_for

__all__ = ["run_stage", "stages_runnable_without_inputs", "main"]

DEFAULT_ROOT = os.environ.get("PHASE0_STATE_DIR", ".phase0")


def run_stage(stage, requester, *, wiring, commit, dataset_snapshot, inputs=None, config=None,
              master_seed=None):
    """Build ``stage``'s runner from ``inputs`` and execute it under ``wiring``'s governance.

    :param stage: a key of :data:`pipeline.stages.STAGE_RUNNERS`.
    :param requester: who asked — a person or an agent identifier. Required, and recorded.
    :param wiring: a :class:`phase0.execution.Wiring`, from ``phase0.execution.wire(root)``. Taken
        whole rather than as four collaborators so that the audit log, the preconditions, the
        governance state and the run store are necessarily the same set — three accounts of one run
        that could disagree is what one hash-chained sequence prevents.
    :param commit: the source commit the run is pinned to.
    :param dataset_snapshot: the dataset snapshot identifier.
    :param inputs: keyword arguments for the stage's factory, or ``None`` for a stage that takes
        none. See the factory's own docstring for what it wants.
    :param config: the stage's configuration, hashed into the run record and copied into the
        context. Defaults to ``{"stage": stage}`` — the same placeholder ``phase0 run`` uses, and
        as thin. A run that means to record its configuration must pass it.
    :param master_seed: pin it to replay a documented run; omitted, the run record mints one.
    :returns: a :class:`phase0.execution.StageResult`. Never ``None``, on any path.

    **The factory is called first, and its refusals are not stage outcomes.** A wiring defect —
    the wrong type, a missing null column, a generator already consumed — raises out of this
    function and no run record is opened, because nothing was about to run. A defect *inside* the
    stage reaches ``execute_stage`` and is recorded as ``CRASHED`` against a run record that says
    what it was about to do under which pinned inputs. :func:`pipeline.stages.runner_for` states
    the cost of that split: a mis-wired stage raises before governance gets the chance to refuse
    it, so the refusal that would have happened is not in the audit log.
    """
    runner = runner_for(stage, **(inputs or {}))
    return execute_stage(
        stage,
        runner,
        requester,
        governance=wiring.governance,
        preconditions=wiring.preconditions,
        runs=wiring.runs,
        audit=wiring.audit,
        commit=commit,
        dataset_snapshot=dataset_snapshot,
        config={"stage": stage} if config is None else config,
        master_seed=master_seed,
    )


def stages_runnable_without_inputs():
    """The stages whose factory has no required parameter, so a shell can drive them.

    Derived from the factories' own signatures rather than listed, so a factory that grows a
    required argument leaves this set on its own instead of leaving a command that fails at the
    call. Today it is the three blocked stages, ``known_answer.battery`` — whose battery argument
    defaults to locating the frozen sixteen cases in the checkout — and ``step0.universe``, every
    one of whose arguments defaults to "not supplied" so that the refusal it makes with no
    observations is reachable from a shell rather than only from Python.

    Everything else needs Python objects — a pool book, matched sets, a ``RunEvidence`` — which is a
    fact about those stages and not a shortcoming of the command line. Use :func:`run_stage`.
    """
    out = []
    for stage, factory in STAGE_RUNNERS.items():
        parameters = inspect.signature(factory).parameters.values()
        required = [
            p for p in parameters
            if p.default is inspect.Parameter.empty
            and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        ]
        if not required:
            out.append(stage)
    return tuple(sorted(out))


# -- the command line -------------------------------------------------------------


def cmd_stages(args):
    """List the thirteen stages, what each is wired to, and which a shell can drive."""
    drivable = stages_runnable_without_inputs()
    print("Stage runners registered in pipeline.stages.STAGE_RUNNERS")
    print("=" * 78)
    for stage in STAGES:
        factory = STAGE_RUNNERS[stage]
        note = BLOCKED_STAGES.get(stage, "{}.{}".format(factory.__module__, factory.__name__))
        print("  {:<28} {:<9} {}".format(
            stage, "BLOCKED" if stage in BLOCKED_STAGES else "wired", note,
        ))
    print("\nRunnable from this command line (factories with no required inputs):")
    for stage in drivable:
        print("  {}".format(stage))
    print("\nEvery other stage takes Python objects and is wired through "
          "pipeline.execute.run_stage.")
    return 0


def cmd_run(args):
    drivable = stages_runnable_without_inputs()
    if args.stage not in drivable:
        print(
            "REFUSED: {} takes inputs this command line cannot supply — its factory "
            "{}.{} has required parameters, and they are Python objects (a pool book, matched "
            "sets, a RunEvidence). Wire it through pipeline.execute.run_stage instead. Stages "
            "this command can drive: {}.".format(
                args.stage,
                STAGE_RUNNERS[args.stage].__module__,
                STAGE_RUNNERS[args.stage].__name__,
                ", ".join(drivable),
            ),
            file=sys.stderr,
        )
        return 2

    wiring = wire(args.root)
    result = run_stage(
        args.stage, args.requester, wiring=wiring, commit=args.commit,
        dataset_snapshot=args.dataset_snapshot,
    )

    print("{}  {}".format(result.status, result.stage))
    print("  requester        {}".format(result.requester))
    print("  run record       {}".format(
        result.run_id or "none written — nothing was about to run"))
    print("  state before     {}".format(result.state_before))
    print("  state after      {}".format(result.state_after))
    if result.advanced_to:
        print("  advanced to      {}".format(result.advanced_to))
    if result.pending:
        print("  awaiting         {}".format(", ".join(result.pending)))
    if result.reason:
        print("  reason           {}".format(result.reason))
    if result.completed:
        print("  value            {}".format(result.value))
    return EXIT_CODES[result.status]


def build_parser():
    p = argparse.ArgumentParser(
        prog="pipeline-stage",
        description="Run a governed stage with its real runner injected from pipeline.stages.",
    )
    p.add_argument("--root", default=DEFAULT_ROOT, help="state directory (default: .phase0)")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("stages", help="list the thirteen stages and what each is wired to")

    rn = sub.add_parser("run", help="execute a stage whose runner needs no constructed inputs")
    rn.add_argument("stage", choices=STAGES)
    rn.add_argument("--requester", required=True)
    rn.add_argument("--commit", required=True)
    rn.add_argument("--dataset-snapshot", required=True, dest="dataset_snapshot")

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1

    handlers = {"stages": cmd_stages, "run": cmd_run}
    try:
        return handlers[args.command](args)
    except Phase0Error as exc:
        print("REFUSED: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
