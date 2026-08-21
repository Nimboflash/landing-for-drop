"""Two stage runners: the measured buy-quality window, and the frozen known-answer battery.

:func:`phase0.execution.execute_stage` authorises a stage, opens its run record *before* the stage
runs, calls ``runner(context)``, and records ``COMPLETED`` / ``REFUSED`` / ``HELD`` / ``CRASHED``. It
takes the runner as an argument because ``phase0`` is SHARED and must not know what a stage does.
This module is the other half of that arrangement: it knows exactly what these two stages do, and it
lives in ``pipeline`` because ``pipeline`` is the composition root — the one builder package
permitted to import other builder packages. ``tests/test_lane_independence.py`` forbids the
``(SHARED, BUILDER)`` edge these runners would need if they lived in ``phase0``, which is why the
wiring is here and the authority is there.

**Factories, not bare runners.** Each public function takes the stage's inputs and returns a
``runner(context)``. The inputs are pinned at wiring time and the closure holds nothing else, so the
integrator can wire a stage without this module knowing anything about a command line, and a reader
of the wiring can see what a stage was given without reading this file.

**Raising is the contract, not an accident.** Neither runner catches anything from the code it
composes. A refusal from :func:`pipeline.run.run_wallet_window` — a duplicate transaction hash, two
spellings of one asset key, a transaction outside the measurement period — reaches ``execute_stage``
as ``CRASHED`` with the reason, and the stage publishes no value at all. That is the intended
behaviour for a defect: a stage that did not complete has nothing to publish, and a plausible-looking
``None`` in place of a measurement is the exact failure this design exists to prevent.

**What the stage context is used for here: nothing.** Both stages are deterministic functions of
inputs pinned before the run record was opened. Neither draws a ``child_seed``, neither reads
``context.commit``, and neither would compute anything different under a different run. The runners
accept the context because that is the contract; ignoring it is the honest thing to do, since using
it would imply these measurements vary with the run, and they do not.

**What this module does not check.** The inputs handed to a factory and the ``config`` recorded in
the run record are two separate things, and nothing here verifies that they describe each other.
Whoever wires the stage owns that correspondence: a runner that re-derived its inputs from the run
record would be a second authority on what the run's inputs were, and two authorities on one fact is
how they come to disagree.
"""

import importlib
import importlib.util
import os
import sys

from ..run import run_wallet_window

__all__ = [
    "KnownAnswerDefect",
    "BatteryUnavailable",
    "BatteryNotTheFrozenList",
    "KnownAnswerRegression",
    "buy_quality_runner",
    "known_answer_battery_runner",
    "load_battery",
]


# -- pipeline.buy_quality --------------------------------------------------------


def buy_quality_runner(transactions, pools, prices, window, config):
    """Wire ``pipeline.buy_quality``: one window, every wallet in it, one accounted result.

    The five arguments are :func:`pipeline.run.run_wallet_window`'s own, unchanged and unwrapped —
    the observed transactions, the pool book, the price book, the :class:`~pipeline.inputs.Window`
    and the :class:`~pipeline.inputs.WindowConfig`. "A window worth of wallets" needs no loop here:
    ``run_wallet_window`` attributes each transaction to its owner and reports one
    :class:`~pipeline.result.WalletOutcome` per wallet it saw, so a per-wallet loop in this file
    would split one population into several and lose the cross-wallet census that makes the result
    an account rather than a number.

    :param transactions: :class:`~pipeline.inputs.ObservedTransaction` values. Materialised into a
        tuple **here**, at wiring time, rather than at call time: a generator would be exhausted by
        the first run and a re-run of a held stage would then measure an empty window and publish a
        confidently empty result. A tuple cannot do that.
    :param pools: ``{token: PoolState}``. Passed through untouched, deliberately — the pool book's
        two refusals (two spellings of one token, a key naming a different token from the
        ``PoolState`` it holds) belong to ``run_wallet_window`` and quote the caller's own spelling.
        Copying or normalising it here would answer them in a worse voice.
    :param prices: ``{quote_asset: Decimal USD per raw unit}``. Passed through for the same reason.
    :param window: the :class:`~pipeline.inputs.Window` being evaluated.
    :param config: the :class:`~pipeline.inputs.WindowConfig`.
    :returns: ``runner(context) -> WalletWindowResult``.

    **What the runner guarantees.** It calls ``run_wallet_window`` once with exactly these inputs
    and returns what it returns. Nothing is caught, so every refusal that function makes — the
    duplicate-hash refusal, the asset-key refusals, the measurement-period bounds, the short-horizon
    refusal — arrives at ``execute_stage`` as a crash carrying its reason. A quarantine is *not* a
    crash and never becomes one: a transaction nobody can price is a carried status inside the
    returned result's queue, which is a finding about the data rather than a defect in the code.

    **What it does not guarantee.** It does not check that the window, the horizon or the pool book
    are the ones the run record's ``config`` describes, and it does not check that the transactions
    are the whole of the window — no function reachable from here knows what the whole of a window
    is. It composes what it was given.
    """
    transactions = tuple(transactions)

    def runner(context):
        """Run the §4 stages over this window. See :func:`buy_quality_runner` for the inputs."""
        return run_wallet_window(transactions, pools, prices, window, config)

    return runner


# -- known_answer.battery --------------------------------------------------------


class KnownAnswerDefect(Exception):
    """A defect in, or around, the frozen known-answer battery. Never a measurement."""


class BatteryUnavailable(KnownAnswerDefect):
    """The battery could not be located, so the stage has nothing to run."""


class BatteryNotTheFrozenList(KnownAnswerDefect):
    """The registered cases are no longer the §9.3 sixteen the pass rate is a fraction of."""


class KnownAnswerRegression(KnownAnswerDefect):
    """A pinned answer moved. The case, and both numbers, are in the message."""


#: The module names the battery is importable under, in the order they are tried. It is a *test*
#: package with no ``tests/__init__.py``, so which one works depends on who is running: under pytest
#: the ``tests`` directory is on ``sys.path`` and the package is ``known_answer``; from a process
#: started at the repository root it is the namespace package ``tests.known_answer``. Both are tried
#: before the path fallback, because an already-imported battery is the same object the test suite
#: is holding and a second copy loaded from the same file would not be.
BATTERY_MODULE_NAMES = ("known_answer.battery", "tests.known_answer.battery")

#: The attributes :func:`known_answer_battery_runner` reads off a battery module. Listed so that a
#: caller passing something else is told what is missing rather than meeting an ``AttributeError``
#: from inside the runner, half way through a stage.
REQUIRED_BATTERY_SURFACE = ("battery_report", "REQUIRED_CASE_NAMES")


def load_battery():
    """Import :mod:`tests.known_answer.battery`, or raise :class:`BatteryUnavailable`.

    Tried in order: each name in :data:`BATTERY_MODULE_NAMES`, then ``tests/known_answer/battery.py``
    relative to this file's checkout. The fallback exists because the battery lives in the test tree
    and the test tree is not packaged — an installed ``pipeline`` has no battery to run, and this
    says so with the paths it looked at instead of failing on an import line.

    Raises rather than returning ``None`` on every path. A stage that cannot find its battery has
    not measured a pass rate of zero; it has not measured anything.
    """
    attempts = []
    for name in BATTERY_MODULE_NAMES:
        try:
            return importlib.import_module(name)
        except ImportError as exc:
            attempts.append("import {}: {}".format(name, exc))

    path = _battery_path_in_checkout()
    if path is not None:
        return _load_module_from_path(path)
    attempts.append("no file at {}".format(_expected_battery_path()))

    raise BatteryUnavailable(
        "the known-answer battery could not be located, so known_answer.battery has nothing to "
        "run. Tried:\n  {}\nThe battery is tests/known_answer/battery.py — a test-tree artifact "
        "that no packaged install carries, so run this stage from a checkout, or hand the module "
        "to known_answer_battery_runner directly. Not measuring the battery is not the same as "
        "measuring it and finding a failure, and this stage will not report the second when the "
        "first happened.".format("\n  ".join(attempts))
    )


def _expected_battery_path():
    """Where ``tests/known_answer/battery.py`` sits relative to this file, in a checkout.

    ``src/pipeline/stages/measure.py`` — three directories up from this one is ``src``'s parent.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(root, "tests", "known_answer", "battery.py")


def _battery_path_in_checkout():
    path = _expected_battery_path()
    return path if os.path.isfile(path) else None


def _load_module_from_path(path):
    """Execute ``battery.py`` as a module of its own, under a name nothing else claims.

    Loaded flat rather than as ``known_answer.battery``: the file imports only absolute names
    (``contracts``, ``fifo``, ``marking``, ``netting``, ``scoring``), so it needs no parent package,
    and inventing one would shadow the package the test suite imports.
    """
    name = "pipeline._known_answer_battery"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise BatteryUnavailable(
            "{} exists but Python would not load it as a module".format(path)
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        # A half-executed module left in sys.modules would be returned intact by the next call.
        sys.modules.pop(name, None)
        raise
    return module


def known_answer_battery_runner(battery=None):
    """Wire ``known_answer.battery``: run the frozen §9.3 cases and report pass/fail per case.

    :param battery: the battery module, or ``None`` to :func:`load_battery` it now. Resolved **here**
        rather than inside the runner, so a checkout without a battery fails while the wiring is
        being assembled — before governance authorises anything and before a run record is opened
        for a stage that was never going to run.
    :returns: ``runner(context) -> dict``.

    The returned value, on the only path that returns one:

    ==============================  =======================================================
    ``cases``                       ``((case name, True), ...)`` in battery order
    ``passed`` / ``total``          cases passed, and the length of the §9.3 required list
    ``known_answer_pass_rate``      §9.8's rate, the battery's own ``Decimal``
    ``fixture_hash``                §9.6's ``known_answer_fixture_hash`` of what was run
    ==============================  =======================================================

    Every entry in ``cases`` is ``True``, necessarily, and it is still worth returning: it is the
    evidence of *which* sixteen cases were run under this run's commit, which a pass rate alone does
    not carry.

    **Why a failing case crashes the stage.** These answers were derived from the §4 definitions
    before the modules were written. A case that no longer produces its pinned answer means either
    the code moved or the frozen answer moved, and both are defects — there is no third reading
    under which a pre-registered number changes and everything is fine. §9.3 forbids waiving one as
    an edge case, so the stage raises :class:`KnownAnswerRegression` naming the case, the key, the
    expected value and the observed one, and ``execute_stage`` records ``CRASHED``.

    **What that costs, stated plainly.** A crashed stage publishes no value, so nothing downstream
    receives a ``known_answer_pass_rate`` below 1 from this stage. Anything gating on that rate must
    treat the absence of a value as *unmeasured* rather than as a rate of zero — the audit log and
    the run record carry the crash and its reason, and they are where the evidence is. This runner
    does not decide the §9.8 gate and does not touch governance; it measures, or it raises.
    """
    battery = _require_battery_surface(load_battery() if battery is None else battery)

    def runner(context):
        """Evaluate every registered case. See :func:`known_answer_battery_runner`."""
        report = battery.battery_report()
        results = tuple(report["results"])

        # The roster first: the pass rate is a fraction of the §9.3 list, so a battery that lost a
        # case or gained one makes every rate computed from it a fraction of the wrong thing, and a
        # regression reported against a roster nobody recognises is reported against nothing.
        _require_the_frozen_list(battery, results, report)

        failed = tuple(result for result in results if not result.passed)
        if failed:
            raise KnownAnswerRegression(_regression_report(failed, report))

        return {
            "cases": tuple((result.name, result.passed) for result in results),
            "passed": report["passed"],
            "total": report["total"],
            "known_answer_pass_rate": report["known_answer_pass_rate"],
            "fixture_hash": report["fixture_hash"],
        }

    return runner


def _require_battery_surface(battery):
    """A battery module is a thing with :data:`REQUIRED_BATTERY_SURFACE`, checked at wiring time."""
    missing = [name for name in REQUIRED_BATTERY_SURFACE if not hasattr(battery, name)]
    if missing:
        raise TypeError(
            "{!r} is not a known-answer battery: it has no {}. known_answer.battery reads {} off "
            "the module it is given, and finding that out half way through a stage would file a "
            "wiring defect as a failed measurement.".format(
                battery, ", ".join(missing), " and ".join(REQUIRED_BATTERY_SURFACE),
            )
        )
    return battery


def _require_the_frozen_list(battery, results, report):
    """The registered cases are exactly the §9.3 names — no fewer, no more."""
    required = tuple(battery.REQUIRED_CASE_NAMES)
    registered = tuple(result.name for result in results)
    missing = tuple(name for name in required if name not in registered)
    unregistered = tuple(name for name in registered if name not in required)
    if not missing and not unregistered:
        return
    raise BatteryNotTheFrozenList(
        "the known-answer battery is no longer the §9.3 list it pins: {} of the {} required "
        "case(s) absent{}, {} case(s) present that are not on the list{}. The pass rate is a "
        "fraction of the required list, so a battery that can shrink reports a perfect score over "
        "whatever survived, and one that can grow reports a rate above 1. Neither is a "
        "measurement. Fixture hash of what was run: {}.".format(
            len(missing), len(required),
            " ({})".format(", ".join(missing)) if missing else "",
            len(unregistered),
            " ({})".format(", ".join(unregistered)) if unregistered else "",
            report["fixture_hash"],
        )
    )


def _regression_report(failed, report):
    """One line per moved answer: the case, the key, the pinned number, the observed one."""
    lines = []
    for result in failed:
        if result.error is not None:
            lines.append("  {}: raised {}".format(result.name, result.error))
        for failure in result.failures:
            lines.append("  {}: {}".format(result.name, failure))
    return (
        "{} of {} known-answer case(s) no longer produce their pinned answer:\n{}\n"
        "Every one of these numbers was derived from the §4 definitions before the code was "
        "written, so a case that moved means the code changed or the frozen answer changed, and "
        "both are defects rather than findings. §9.3 forbids waiving a failing case as an edge "
        "case, so this stage crashes instead of publishing a pass rate below 1. Fixture hash of "
        "what was run: {}.".format(
            len(failed), report["total"], "\n".join(lines), report["fixture_hash"],
        )
    )
