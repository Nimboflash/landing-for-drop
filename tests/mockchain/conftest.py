"""Fixtures for the synthetic-source suite, and the one seed every assertion in it is about.

**Make ``tools`` importable.** ``pyproject`` sets ``pythonpath = ["src"]``, which is right: the
pipeline lives under ``src/`` and nothing else belongs on the path by default. ``tools/`` is
deliberately outside it — ``tests/test_lane_independence.py`` classifies every package under
``src/`` into a lane and a synthetic source is none of them — so this suite puts the repository root
on ``sys.path`` itself. It *appends* rather than inserting at position 0, for the reason
``tests/provisioning/conftest.py`` records: an insert at 0 silently overrode ``PYTHONPATH`` for
every test sharing the process and turned a whole mutation run into false negatives.

**One seed, named once.** :data:`SEED` is 7 and :data:`OTHER_SEED` is 8; neither is special and
neither was chosen after looking at a result. Every literal in this directory is the value seed 7
produced — measured from the run, then written down — so a change to the generator, to the pipeline,
or to the reporting layer moves a literal and goes red rather than quietly reporting a different
fixture. That is the point of pinning them: a synthetic run whose numbers are recomputed by the code
under test pins nothing about that code.

**The run is session-scoped because it is expensive, not because it is shared state.** A full
``synthetic_report`` is ~1.9 seconds — 1,041 scored buys, five capital levels, one ``depth``
simulation per buy per level. The object is frozen and every test here treats it as read-only; the
two tests that need to mutate a report build their own.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from tools.mockchain import generate_chain, run_synthetic_window, synthetic_report  # noqa: E402

#: The seed every pinned literal in this directory belongs to.
SEED = 7

#: A second seed, used only to show that the output moves with the seed.
OTHER_SEED = 8


@pytest.fixture(scope="session")
def chain():
    return generate_chain(SEED)


@pytest.fixture(scope="session")
def result(chain):
    """The ``pipeline.run_wallet_window`` result, without a report built on top of it."""
    return run_synthetic_window(chain)


@pytest.fixture(scope="session")
def run():
    """One seed all the way to a published, provenance-audited artifact."""
    return synthetic_report(SEED)
