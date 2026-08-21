"""Canonical serialization and hashing.

Frozen before the modules land, because two correct implementations can otherwise disagree over
whether a value is ``2.0`` or ``2.00`` and the reconciliation fails on formatting rather than on
substance.

Rules:

* **Decimal is serialized as a string, never a JSON number.** A JSON number is parsed as a double
  by nearly every consumer, which reintroduces the float this project spent its whole seam design
  avoiding.
* **Integers are serialized as decimal strings.** Raw token quantities routinely exceed 2^53, and
  a JSON number silently loses precision past that in any JavaScript-based reader.
* **Enums serialize to their frozen ``value``**, versioned via :data:`ENUM_SCHEMA_VERSION`.
* **``None`` stays ``null``.** It is a meaningful state — ``INDETERMINATE`` — not a missing field.
* **Deterministic key ordering**, so the canonical hash is stable.
* **No NaN, no infinity, no float, no locale formatting.**

The canonical hash of a builder artifact goes in the freeze manifest, which is what lets
``gate_validation`` verify an artifact without importing the code that produced it.
"""

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from enum import Enum

from .numeric import CALCULATION_CONTEXT

#: Bump when any enum's set of values changes. An artifact written under an older version must be
#: re-derived rather than reinterpreted, because a silently renamed status is a silently changed
#: meaning.
ENUM_SCHEMA_VERSION = 1

#: The one permitted timestamp format. UTC, seconds, explicit offset.
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S+00:00"


def format_timestamp(epoch_seconds):
    if not isinstance(epoch_seconds, int):
        raise TypeError("timestamps are integer UTC seconds, got {}".format(type(epoch_seconds).__name__))
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).strftime(TIMESTAMP_FORMAT)


def canonicalise(value):
    """Convert a value into JSON-safe primitives under the frozen rules."""
    if value is None or isinstance(value, bool):
        return value

    if isinstance(value, float):
        raise TypeError(
            "float reached serialization: {!r}. Every numeric field is int or Decimal by seam "
            "rule; a float here means one leaked in through a library or a dataframe "
            "conversion.".format(value)
        )

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("refusing to serialize non-finite Decimal {}".format(value))
        # Normalise the exponent so 2 and 2.00 hash identically, then render without exponent
        # notation so large and small magnitudes are both human-readable.
        #
        # BOTH operations run under the frozen context, and that is load-bearing rather than
        # tidy. `normalize()` and `quantize()` respect the *ambient* decimal context, so without
        # this block the canonical form — and therefore `canonical_hash` — depended on a global
        # the seam does not control:
        #
        #     ambient prec  9  ->  0.769230769                  hash 838b8a22...
        #     ambient prec 28  ->  0.7692307692307692307692307692   hash e6e2cc34...
        #     ambient prec 38  ->  0.76923076923076923076923076923076923077  hash 6ea083a1...
        #
        # Same value, same code, three different manifest hashes. Since §9.6 records that hash in
        # the freeze manifest, and gate_validation uses it to verify an artifact it deliberately
        # refuses to import, a hash that moves with an ambient global would let a correct artifact
        # fail verification — or a re-run under a different context appear to be a different
        # experiment.
        with localcontext(CALCULATION_CONTEXT):
            normalised = value.normalize()
            sign, digits, exponent = normalised.as_tuple()
            if exponent > 0:
                normalised = normalised.quantize(Decimal(1))
            return format(normalised, "f")

    if isinstance(value, int):
        return str(value)

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key = k.value if isinstance(k, Enum) else k
            if not isinstance(key, str):
                key = str(key)
            out[key] = canonicalise(v)
        return out

    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=repr) if isinstance(value, (set, frozenset)) else value
        return [canonicalise(v) for v in items]

    if hasattr(value, "__dataclass_fields__"):
        return {
            name: canonicalise(getattr(value, name))
            for name in sorted(value.__dataclass_fields__)
        }

    raise TypeError("no canonical form defined for {}".format(type(value).__name__))


def to_canonical_json(value):
    """Deterministic JSON. Same input, byte-identical output, on any machine."""
    return json.dumps(
        canonicalise(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def canonical_hash(value):
    """SHA-256 of the canonical JSON. This is what the freeze manifest records."""
    return hashlib.sha256(to_canonical_json(value).encode("utf-8")).hexdigest()


def artifact_envelope(kind, produced_by, payload, schema_version=ENUM_SCHEMA_VERSION):
    """Wrap a builder or validator output for on-disk exchange.

    ``gate_validation`` reads these files. It never imports the module that wrote one — an arbiter
    that can execute the code it judges can inherit that code's bug and then certify it.
    """
    body = {
        "kind": kind,
        "produced_by": produced_by,
        "schema_version": schema_version,
        "payload": canonicalise(payload),
    }
    body["payload_hash"] = hashlib.sha256(
        json.dumps(body["payload"], sort_keys=True, separators=(",", ":"),
                   ensure_ascii=True, allow_nan=False).encode("utf-8")
    ).hexdigest()
    return body


# -- derived fields as redundant assertions -------------------------------------


class DerivedFieldMismatch(ValueError):
    """A serialized derived value disagrees with the primitives it claims to summarise."""


def verify_redundant_derived(payload, recomputations, tolerance=None):
    """Recompute every supplied derived field and refuse the artifact on mismatch.

    Derived fields are **never authoritative** in an artifact. The primitives are. If a derived
    value is exported for convenience, it is a redundant assertion and must be checked, not
    trusted — otherwise an artifact can claim a 20% return while carrying a cost and a proceeds
    that imply 15%, and every consumer downstream believes the claim.

    :param payload: already-canonicalised mapping (Decimals as strings).
    :param recomputations: ``{field_name: callable(payload) -> Decimal}``.
    :param tolerance: absolute tolerance; ``None`` means exact string identity after
        canonicalisation, which is the default because both sides ran the same frozen policy.
    """
    from decimal import Decimal as _D

    mismatches = []
    for name, recompute in recomputations.items():
        if name not in payload:
            continue  # absent is fine — the primitives remain authoritative
        claimed_raw = payload[name]
        recomputed = recompute(payload)
        if claimed_raw is None or recomputed is None:
            if claimed_raw is not recomputed:
                mismatches.append("{}: claimed {!r}, recomputed {!r}".format(
                    name, claimed_raw, recomputed))
            continue
        claimed = _D(str(claimed_raw))
        if tolerance is None:
            ok = canonicalise(claimed) == canonicalise(recomputed)
        else:
            # Under the frozen context, and ``copy_abs`` rather than ``abs``. This is the check
            # that decides whether an artifact is internally consistent or must be invalidated,
            # so a difference truncated to the ambient 28 digits would admit an artifact whose
            # true difference exceeds the tolerance in its 29th digit. Demonstrable:
            #
            #     tolerance   1.234567890123456789012345678
            #     claimed     2.2345678901234567890123456780000000001
            #     recomputed  1
            #     true diff       1.2345678901234567890123456780000000001  -> outside
            #     ambient diff    1.234567890123456789012345678            -> admitted
            with localcontext(CALCULATION_CONTEXT):
                ok = (claimed - recomputed).copy_abs() <= tolerance
        if not ok:
            mismatches.append(
                "{}: artifact claims {}, primitives imply {}".format(name, claimed, recomputed)
            )

    if mismatches:
        raise DerivedFieldMismatch(
            "artifact is internally inconsistent and must be invalidated rather than "
            "reinterpreted: {}".format("; ".join(mismatches))
        )
    return True
