"""Test package marker.

Present so the three layers may each hold a ``test_<mod>.py`` for the same module without
pytest colliding on the shared basename under rootdir import mode.
"""
