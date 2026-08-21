"""Operator tooling. Deliberately outside ``src/``.

Nothing in here is pipeline code. These packages interpret no chain bytes and compute no metric,
so none of them is a builder, a validator, or shared seam code — they must not appear in the lane
graph at all (see ``tests/test_lane_independence.py``, whose ``LANES`` table covers ``src/`` only).
"""
