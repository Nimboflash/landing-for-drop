"""Ticket 18 — the frozen known-answer battery (§9.3).

Sixteen named scenarios whose answers are fixed *before* the code runs. This package is the
pre-registration artifact itself: :mod:`tests.known_answer.battery` holds the fixtures, the
expected answers, and the harness; the three test modules beside it are the three layers.

§9.3 requires 100% of these to pass and forbids waiving any as an "edge case". There is
deliberately no skip, no xfail, and no waiver state anywhere in this package.
"""
