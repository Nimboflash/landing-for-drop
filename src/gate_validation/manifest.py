"""The freeze manifest, and what happens when a bug is found after the freeze.

§9.6 pins every input before the null distribution runs, so that the experiment is a specific
reproducible object rather than a claim. §9.7 says what to do when the object turns out to be wrong:
the run is `INVALIDATED`, and the previous result may not be patched or partially corrected.

The second half is the part that needs code rather than a policy document, because the failure it
prevents is not carelessness. When a bug surfaces after a favourable result, the honest sequence —
fix, register a new version, re-run the whole validation gate, rebuild the null from scratch, re-run
the main test — costs weeks, and the dishonest one costs an afternoon. So the refusal is structural:

* an invalidated run emits no decision at all, not a decision with a caveat;
* clearing an invalidation requires a **different** code version, because re-registering the same
  one is a patch with new paperwork;
* a result computed under a superseded version can never be quoted again, which is what makes
  "selectively using the old or the new result" unavailable rather than merely prohibited.

That last rule is the one with teeth. Both results will exist on disk; the prohibition only means
something if something refuses to read one of them.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from contracts import (
    NUMERIC_POLICY_VERSION,
    REPORTING_SCHEMA_VERSION,
    FreezeManifest,
    FreezeViolation,
    canonical_hash,
)

from .artifacts import (
    MISMATCH,
    MISSING,
    UNPINNED,
    CheckReport,
    Discrepancy,
    _mapping,
)

#: Derived from the seam rather than restated, so a field added to :class:`contracts.FreezeManifest`
#: cannot be quietly left unchecked here. ``tests`` assert the resulting names, so a seam change
#: fails loudly rather than widening the arbiter's blind spot in silence.
REQUIRED_MANIFEST_FIELDS = tuple(sorted(FreezeManifest.__dataclass_fields__))

#: These two are not merely compared against the run — they are compared against the policy this
#: process is *currently executing*. A manifest pinned under a different decimal policy describes
#: different arithmetic, and comparing its numbers to ours would reconcile two experiments.
POLICY_PINS = {
    "numeric_policy_version": NUMERIC_POLICY_VERSION,
    "reporting_schema_version": REPORTING_SCHEMA_VERSION,
}


@dataclass(frozen=True)
class ManifestCheck:
    """The manifest, what the run actually used, and every way they disagree."""

    pinned: Dict[str, str]
    observed: Dict[str, str]
    report: CheckReport

    @property
    def ok(self):
        return self.report.ok

    @property
    def discrepancies(self):
        return self.report.discrepancies

    @property
    def messages(self):
        return self.report.messages

    @property
    def manifest_hash(self):
        """The identifier every later result binds to (ticket 39).

        Computed over the pinned values as read, so it is reproducible by anyone holding the same
        manifest file and nothing else.
        """
        return canonical_hash(self.pinned)


def check_freeze_manifest_detail(manifest, observed):
    """Compare what was frozen against what the run actually used.

    Four distinct failures, kept apart because they call for different fixes:

    ``not pinned``      the manifest never recorded this input — the run is unreproducible
    ``empty``           the field exists but carries no value, which is a pin in name only
    ``not observed``    the run did not report what it used — absence is not agreement
    ``differs``         the run used something else — this is the freeze violation proper
    """
    pinned = _mapping(manifest, "manifest")
    seen = _mapping(observed, "observed")
    found = []

    for field in REQUIRED_MANIFEST_FIELDS:
        if field not in pinned:
            found.append(Discrepancy(
                kind=MISSING, field=field,
                detail="is not pinned by the freeze manifest; §9.6 requires every input frozen "
                       "before the null runs, and an unpinned input makes the run unreproducible",
            ))
            continue

        value = pinned[field]
        if value is None or value == "":
            found.append(Discrepancy(
                kind=MISSING, field=field,
                detail="is pinned to an empty value, which is a pin in name only",
            ))

        expected_policy = POLICY_PINS.get(field)
        if expected_policy is not None and value != expected_policy:
            found.append(Discrepancy(
                kind=MISMATCH, field=field, expected=expected_policy, observed=str(value),
                detail="was frozen under a different policy than this process runs; the manifest "
                       "describes a different experiment and its numbers are not comparable",
            ))

        if field not in seen:
            found.append(Discrepancy(
                kind=MISSING, field=field,
                detail="was not observed by the run; a field the run cannot report is not a field "
                       "it matched",
            ))
        elif seen[field] != value:
            found.append(Discrepancy(
                kind=MISMATCH, field=field, expected=str(value), observed=str(seen[field]),
                detail="differs from what the freeze manifest pins",
            ))

    for field in sorted(seen):
        if field not in REQUIRED_MANIFEST_FIELDS and field not in pinned:
            found.append(Discrepancy(
                kind=UNPINNED, field=field, observed=str(seen[field]),
                detail="was used by the run but is not pinned by the manifest",
            ))

    return ManifestCheck(
        pinned=dict(pinned),
        observed=dict(seen),
        report=CheckReport(what="freeze_manifest", discrepancies=tuple(found)),
    )


def check_freeze_manifest(manifest, observed):
    """§9.6. Returns one line per disagreement; an empty list means the freeze held."""
    return check_freeze_manifest_detail(manifest, observed).messages


def freeze_manifest_from(manifest):
    """Reduce a parsed mapping to the seam type, refusing anything the seam does not describe.

    The arbiter works in dicts so that it never imports what it judges, but the decision it emits
    carries a :class:`contracts.FreezeManifest`. This is the single conversion point, and it is
    strict on purpose: an extra key would be an input nobody declared.
    """
    pinned = _mapping(manifest, "manifest")
    missing = [f for f in REQUIRED_MANIFEST_FIELDS if f not in pinned]
    if missing:
        raise FreezeViolation(
            "the freeze manifest is missing {}; a decision cannot be bound to a manifest that "
            "does not pin every input".format(", ".join(sorted(missing)))
        )
    unknown = [f for f in sorted(pinned) if f not in REQUIRED_MANIFEST_FIELDS]
    if unknown:
        raise FreezeViolation(
            "the freeze manifest carries undeclared field(s) {}; the seam defines what a manifest "
            "is, and an undeclared input is one nobody agreed to freeze".format(
                ", ".join(unknown))
        )
    return FreezeManifest(**{f: pinned[f] for f in REQUIRED_MANIFEST_FIELDS})


# -- §9.7 invalidation ----------------------------------------------------------


@dataclass(frozen=True)
class RunStatus:
    """Which code version is authoritative, and which ones have been discarded.

    Immutable, and every transition returns a new value. A mutable status is a status that can be
    quietly restored to a friendlier state; a value that must be re-derived leaves the old one in
    the caller's hands, where it is visible.
    """

    code_version: str
    invalidated: bool = False
    invalidation_reason: Optional[str] = None
    discarded_versions: Tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "discarded_versions", tuple(self.discarded_versions))
        if not self.code_version:
            raise ValueError("a run must name the code version it executed")
        if self.invalidated and not self.invalidation_reason:
            raise ValueError(
                "an invalidation must record its reason; 'INVALIDATED' with no documented bug is "
                "indistinguishable from discarding a result someone disliked"
            )
        if self.code_version in self.discarded_versions:
            raise ValueError(
                "the current code version {} is also recorded as discarded; nothing may be both "
                "authoritative and superseded".format(self.code_version)
            )

    @property
    def permits_decision(self):
        return not self.invalidated


def invalidate(status, reason):
    """§9.7. Mark the run INVALIDATED. Nothing advances until a new code version is registered."""
    if not reason:
        raise ValueError("an invalidation must document the bug that caused it")
    if status.invalidated:
        return status
    return RunStatus(
        code_version=status.code_version,
        invalidated=True,
        invalidation_reason=reason,
        discarded_versions=status.discarded_versions,
    )


def register_code_version(status, new_version):
    """The one recovery path out of an invalidation. The old result is discarded, never patched.

    Refuses the *same* version, because "fix the bug and register a new code version" and "edit the
    code and keep the version" differ by exactly this check. Without it the recovery path is a
    patch with extra paperwork, and every downstream artifact keeps pointing at a commit whose
    contents have changed underneath it.
    """
    if not status.invalidated:
        raise FreezeViolation(
            "run_status: the run is not invalidated, so there is nothing to clear. Registering a "
            "code version is the recovery path from an invalidation (§9.7), not a way to change "
            "code mid-run — a mid-run change is itself an invalidation."
        )
    if new_version == status.code_version:
        raise FreezeViolation(
            "code_version: {} is already the invalidated version. Re-registering it is a patch of "
            "the previous run, and §9.7 forbids patching or partially correcting it: fix the bug, "
            "register a NEW version, re-run the entire validation gate, rebuild the null from "
            "scratch, and re-run the main test.".format(new_version)
        )
    if new_version in status.discarded_versions:
        raise FreezeViolation(
            "code_version: {} was already discarded by an earlier invalidation and cannot be "
            "reinstated; that would be selecting between an old and a new result, which §9.7 "
            "prohibits outright.".format(new_version)
        )
    if not new_version:
        raise ValueError("a registered code version must be named")

    return RunStatus(
        code_version=new_version,
        invalidated=False,
        invalidation_reason=None,
        discarded_versions=status.discarded_versions + (status.code_version,),
    )


def require_current_version(status, result_code_version):
    """Refuse a result produced by any version other than the authoritative one.

    This is what makes §9.7's prohibition real. Both the old and the new result exist on disk after
    a re-run; a rule that only says "do not choose between them" changes nothing unless something
    refuses to read the discarded one.
    """
    if result_code_version in status.discarded_versions:
        raise FreezeViolation(
            "result_code_version: {} was discarded when the run was invalidated and re-registered "
            "as {}. The previous result is not available for comparison, quotation, or partial "
            "reuse — selectively using the old or the new result is prohibited (§9.7).".format(
                result_code_version, status.code_version
            )
        )
    if result_code_version != status.code_version:
        raise FreezeViolation(
            "result_code_version: the result was produced by {} but the authoritative version is "
            "{}; a result and the run it belongs to must be the same object.".format(
                result_code_version, status.code_version
            )
        )
    return True
