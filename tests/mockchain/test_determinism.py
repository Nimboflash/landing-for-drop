"""Same seed, byte-identical output — in one process, across processes, across hash seeds.

Three claims, and each catches something the others cannot:

* **twice in one process** catches an accumulator that survives between runs;
* **a pinned literal hash** catches a change that is deterministic today and was different
  yesterday — the only form of drift the other two are blind to, because both compare this run
  against another run of the same code;
* **several ``PYTHONHASHSEED`` values, in subprocesses** catches the one that actually bites: a
  number aggregated in ``set`` or ``dict`` iteration order. That order is a function of the hash
  seed for ``str`` keys, and every identifier in this package is a ``str``. In-process repetition
  cannot see it, because one process has one hash seed.

Why the hash and not just the report: :attr:`SyntheticRun.payload_hash` is what
``gate_validation.manifest`` records under §9.6 and what an artifact is verified against without
importing the code that wrote it. If determinism is worth anything here it is worth it at exactly
that string.
"""

import hashlib
import json
import os
import subprocess
import sys

from contracts import to_canonical_json

from tools.mockchain import generate_chain, run_synthetic_window, synthetic_report
from tools.mockchain.provenance import snapshot_id

from conftest import OTHER_SEED, ROOT, SEED

#: What seed 7 produces, recorded from a run and then written down. It is a tripwire, not a
#: derivation: if a deliberate change to ``src/`` or to the generator moves it, re-measure it and
#: say in the commit which change moved it. If it moves and nothing was changed, something in the
#: path is not deterministic and that is the defect this literal exists to find.
#:
#: Moved twice, both deliberately, and both recorded here rather than quietly re-measured.
#:
#: 1. ``report._capital_ladder`` stopped re-implementing §4.5's five-level composition and now
#:    calls ``pipeline.stages.benchmark.follower_adjust_runner``, the code a real run executes. The
#:    two implementations disagreed about a buy the follower could not place — the fixture entered
#:    it at a zero return, the stage drops it — so the §10 ladder's numbers moved.
#:    ``4a65961b92c04bfe7a169fdcee3fc6f49b5ae636f2931452a01639afc9695557``
#: 2. ``RunReport`` gained the required ``integrity`` block — §10's four standing data-integrity
#:    figures, which four packages computed and nothing published. No measured number moved: the
#:    block reports four ``None``s here, because this run measures none of them. The *shape* moved,
#:    and the payload hash is over the shape.
#:    ``31c768213ac0eb33bb179b0fe1804cf85ac1103addfbe384186396adf0d78f30``
#:
#: **The second move is the second shape change under one ``report-v1`` stamp**, and
#: ``reporting/run.py``'s module docstring already records the first for the same reason. Two
#: artifacts both declaring ``report-v1`` are not interchangeable, and a reader pinned to that
#: version cannot tell from the stamp which shape they have. The constant lives in the frozen seam,
#: so this lane cannot bump it; the note is here so the next unfreeze has two reasons rather than one.
SEED_7_PAYLOAD_HASH = "1193146db923eb1f714766e95eeca455af510cd0774d15a445a38baf4d19090a"

SEED_7_SNAPSHOT = "SYNTHETIC-mockchain-v1-seed-7-c610779940e0-NOT-A-MEASUREMENT"
SEED_7_RUN_ID = "SYNTHETIC-mockchain-v1-run-seed-7"

#: Hash seeds the subprocess check runs under. 0 disables randomisation entirely; the other two are
#: ordinary values. Three is enough to fail loudly — a set-ordered aggregate does not survive two
#: different orders by luck — and cheap enough to keep in the suite.
HASH_SEEDS = ("0", "1", "42")

_SCRIPT = (
    "import hashlib, sys;"
    "from tools.mockchain import synthetic_report;"
    "run = synthetic_report(int(sys.argv[1]));"
    "from contracts import to_canonical_json;"
    "print(run.payload_hash);"
    "print(hashlib.sha256(to_canonical_json(run.report).encode('utf-8')).hexdigest());"
    "print(run.snapshot);"
    "print(run.run_id)"
)


def _in_subprocess(seed, hash_seed):
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = hash_seed
    env["PYTHONPATH"] = os.pathsep.join((os.path.join(ROOT, "src"), ROOT))
    out = subprocess.check_output(
        [sys.executable, "-c", _SCRIPT, str(seed)], env=env, cwd=ROOT
    )
    return tuple(out.decode("utf-8").strip().splitlines())


def test_the_same_seed_twice_in_one_process_is_byte_identical(run):
    again = synthetic_report(SEED)
    assert to_canonical_json(again.payload) == to_canonical_json(run.payload)
    assert again.payload_hash == run.payload_hash
    assert again.snapshot == run.snapshot
    assert again.run_id == run.run_id
    # Not only the published payload: the run behind it, too. A report that matched over a result
    # that did not would mean the reporting layer was flattening a difference.
    assert to_canonical_json(again.result.reconciliation()) == to_canonical_json(
        run.result.reconciliation()
    )


def test_the_chain_itself_is_byte_identical_before_any_pipeline_runs():
    """Pinned separately from the report, so a difference is attributable to a side of the seam."""
    assert to_canonical_json(generate_chain(SEED)) == to_canonical_json(generate_chain(SEED))
    assert to_canonical_json(generate_chain(SEED)) != to_canonical_json(generate_chain(OTHER_SEED))


def test_the_pipeline_over_one_chain_is_byte_identical(chain):
    first = run_synthetic_window(chain)
    second = run_synthetic_window(chain)
    assert to_canonical_json(first) == to_canonical_json(second)


def test_seed_7_hashes_to_the_recorded_literal(run):
    assert run.payload_hash == SEED_7_PAYLOAD_HASH
    assert run.snapshot == SEED_7_SNAPSHOT == snapshot_id(SEED)
    assert run.run_id == SEED_7_RUN_ID
    # The envelope's own hash is over the canonicalised payload; recompute it here rather than
    # trusting the field, so a payload rewritten after publication cannot keep a stale hash.
    recomputed = hashlib.sha256(
        json.dumps(run.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                   allow_nan=False).encode("utf-8")
    ).hexdigest()
    assert recomputed == run.payload_hash


def test_a_different_seed_is_a_different_run():
    other = synthetic_report(OTHER_SEED)
    assert other.payload_hash != SEED_7_PAYLOAD_HASH
    assert other.snapshot != SEED_7_SNAPSHOT
    assert other.run_id != SEED_7_RUN_ID
    # Different numbers, same shape: the seed moves the quantities and nothing else. A seed that
    # changed which wallets exist would make every other pin in this directory seed-specific.
    assert [w.wallet for w in other.report.basket.wallets] == [
        w.wallet for w in synthetic_report(SEED).report.basket.wallets
    ]


def test_the_whole_path_is_stable_under_several_python_hash_seeds():
    outputs = {seed: _in_subprocess(SEED, seed) for seed in HASH_SEEDS}
    distinct = set(outputs.values())
    assert len(distinct) == 1, (
        "the published artifact depends on PYTHONHASHSEED: {}. Something in the path aggregates "
        "over a set or a dict whose keys are strings, and the published number is therefore a "
        "function of an interpreter start-up detail.".format(
            {seed: value[0] for seed, value in outputs.items()}
        )
    )
    payload_hash, report_hash, snapshot, run_id = distinct.pop()
    assert payload_hash == SEED_7_PAYLOAD_HASH
    assert snapshot == SEED_7_SNAPSHOT
    assert run_id == SEED_7_RUN_ID
    assert report_hash  # the canonical JSON of the report itself, hashed the same way every time


def test_a_different_seed_is_different_under_every_hash_seed():
    outputs = {seed: _in_subprocess(OTHER_SEED, seed) for seed in ("0", "42")}
    assert len(set(outputs.values())) == 1
    assert outputs["0"][0] != SEED_7_PAYLOAD_HASH
