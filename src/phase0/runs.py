"""Run records — ticket 05.

A run record pins everything needed to reproduce a stage: the commit, the configuration, the
dataset snapshot, and the seed derivation. It is written **before** the stage executes, not after,
so that a stage which crashes or is halted still leaves evidence of what it was about to do under
which pinned inputs.

Once written, a run record is immutable. Reproducibility is not a report you assemble afterwards
from memory.
"""

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone

from .errors import FrozenError
from .seeds import new_master_seed

STAGES = (
    "step0.universe",
    "golden_set.trace",
    "known_answer.battery",
    "pipeline.buy_quality",
    "benchmark.match",
    "follower.adjust",
    "reconciliation.cross_source",
    "validation.independent",
    "null.leader",
    "null.follower",
    "threshold.calibrate",
    "main_test",
    "decision.emit",
)


def config_hash(config):
    """Stable hash of a configuration mapping."""
    blob = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class RunRecord(object):
    __slots__ = (
        "run_id", "stage", "opened_at", "commit", "config_hash", "dataset_snapshot",
        "master_seed", "seed_rule", "requester",
    )

    #: Recorded verbatim so a reader never has to guess how child seeds were produced.
    SEED_RULE = (
        "child_seed = HMAC-SHA256(key=master_seed, msg=f'{commit}|{purpose}|{index}') "
        "interpreted as a big-endian 256-bit integer"
    )

    def __init__(self, run_id, stage, opened_at, commit, config_hash_, dataset_snapshot,
                 master_seed, seed_rule, requester):
        self.run_id = run_id
        self.stage = stage
        self.opened_at = opened_at
        self.commit = commit
        self.config_hash = config_hash_
        self.dataset_snapshot = dataset_snapshot
        self.master_seed = master_seed
        self.seed_rule = seed_rule
        self.requester = requester

    def to_dict(self):
        return {
            "run_id": self.run_id,
            "stage": self.stage,
            "opened_at": self.opened_at,
            "commit": self.commit,
            "config_hash": self.config_hash,
            "dataset_snapshot": self.dataset_snapshot,
            "master_seed": self.master_seed,
            "seed_rule": self.seed_rule,
            "requester": self.requester,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            d["run_id"], d["stage"], d["opened_at"], d["commit"], d["config_hash"],
            d["dataset_snapshot"], d["master_seed"], d["seed_rule"], d["requester"],
        )


class RunStore(object):
    """Immutable, append-only store of run records, one JSON file per run."""

    def __init__(self, directory, audit_log=None, clock=None, id_factory=None):
        self.directory = str(directory)
        self._audit = audit_log
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex[:12])

    def _path(self, run_id):
        return os.path.join(self.directory, "{}.json".format(run_id))

    def open_run(self, stage, commit, config, dataset_snapshot, requester, master_seed=None):
        """Write a run record and return it. Called before the stage executes."""
        if stage not in STAGES:
            raise ValueError(
                "unknown stage {!r}; expected one of {}".format(stage, ", ".join(STAGES))
            )
        for name, value in (("commit", commit), ("dataset_snapshot", dataset_snapshot),
                            ("requester", requester)):
            if not value or not str(value).strip():
                raise ValueError("run record needs {}".format(name))

        record = RunRecord(
            run_id=self._id_factory(),
            stage=stage,
            opened_at=self._clock(),
            commit=str(commit),
            config_hash_=config_hash(config),
            dataset_snapshot=str(dataset_snapshot),
            master_seed=master_seed or new_master_seed(),
            seed_rule=RunRecord.SEED_RULE,
            requester=str(requester),
        )

        os.makedirs(self.directory, exist_ok=True)
        path = self._path(record.run_id)
        if os.path.exists(path):
            raise FrozenError(
                "run record {} already exists and is immutable".format(record.run_id)
            )
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(record.to_dict(), fh, indent=2, sort_keys=True)
            fh.write("\n")

        if self._audit is not None:
            self._audit.append(requester, "run.open", {
                "run_id": record.run_id,
                "stage": stage,
                "commit": record.commit,
                "config_hash": record.config_hash,
                "dataset_snapshot": record.dataset_snapshot,
            })
        return record

    def get(self, run_id):
        path = self._path(run_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            return RunRecord.from_dict(json.load(fh))

    def list_runs(self):
        if not os.path.isdir(self.directory):
            return []
        out = []
        for name in sorted(os.listdir(self.directory)):
            if name.endswith(".json"):
                out.append(self.get(name[:-5]))
        return [r for r in out if r is not None]
