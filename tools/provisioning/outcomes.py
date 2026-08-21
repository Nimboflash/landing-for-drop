"""The five outcomes of a probe. These are statuses, not exceptions.

A probe that raised on a missing credential would make "we have not bought this yet" look like a
defect, and the natural fix for a noisy defect is to stop running the check. So every state of the
world a probe can meet becomes a value it returns:

    ABSENT        no credential configured — a normal state, reported and moved past
    UNREACHABLE   credential present, endpoint did not answer at all
    REFUSED       endpoint answered and declined the capability; the message is kept VERBATIM
    INSUFFICIENT  answered, but did not prove the capability (no rows, no trace, live pool only)
    PROVEN        capability demonstrated, with the evidence recorded

The asymmetry between the first four and the last is the whole point. ``ABSENT`` is cheap: it
costs nothing to be honest about a credential you do not have. ``PROVEN`` is expensive: it must be
*earned* by evidence, never by an absent error. A probe that reached the endpoint, understood
nothing it received, and raised no exception has proven nothing — so :class:`ProbeResult` refuses
to construct a ``PROVEN`` result with an empty evidence mapping, and refuses ``REFUSED`` without
the endpoint's own words.

``REFUSED`` is kept distinct from ``INSUFFICIENT`` because they have different owners. "archive
requests require a personal token" is a commercial fact — someone must buy something. "the node
served a receipt but the trace came back empty" is a technical fact about that node — someone must
choose a different one. Collapsing them into one FAILED status loses the instruction.
"""

from decimal import Decimal

ABSENT = "ABSENT"
UNREACHABLE = "UNREACHABLE"
REFUSED = "REFUSED"
INSUFFICIENT = "INSUFFICIENT"
PROVEN = "PROVEN"

#: Reporting order: worst-understood state first, so a table reads as a work queue.
STATUSES = (ABSENT, UNREACHABLE, REFUSED, INSUFFICIENT, PROVEN)

#: The only status that lets a source count towards ``data_budget: APPROVED``.
SUFFICIENT_STATUSES = frozenset({PROVEN})

_EVIDENCE_SCALARS = (str, int, bool, type(None))


def _check_evidence(value, path):
    """Evidence must be JSON-safe primitives, and must contain no float.

    The repository rule is that money and every other number crossing a boundary is ``int`` or
    ``Decimal``, never ``float``; a float in the register would be a float that some future reader
    parses as a double and compares against a threshold. Vendor payloads are full of JSON floats,
    so the conversion has to happen at the point the probe decides what it saw — which is exactly
    where the probe should be forced to think about precision anyway.
    """
    if isinstance(value, bool) or isinstance(value, _EVIDENCE_SCALARS):
        return
    if isinstance(value, float):
        raise TypeError(
            "float in probe evidence at {}: {!r}. Record it as a string or an int — a float here "
            "would be read back as a double by every JSON consumer.".format(path, value)
        )
    if isinstance(value, Decimal):
        raise TypeError(
            "Decimal in probe evidence at {}: {!r}. Serialize it with str() at the point of "
            "recording so the register stays plain JSON.".format(path, value)
        )
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("evidence keys must be strings; got {!r} at {}".format(key, path))
            _check_evidence(item, "{}.{}".format(path, key))
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_evidence(item, "{}[{}]".format(path, index))
        return
    raise TypeError(
        "evidence at {} is {}, which is not JSON-safe".format(path, type(value).__name__)
    )


class ProbeResult(object):
    """What one probe found, and what it can prove.

    ``detail`` is written for the person who has to act on it, so it names the next move rather
    than restating the status. ``verbatim`` holds the vendor's own words on a ``REFUSED``, because
    a paraphrase of "archive requests require a personal token" is not something you can take to
    the person holding the card.
    """

    __slots__ = ("source", "status", "detail", "evidence", "verbatim")

    def __init__(self, source, status, detail, evidence=None, verbatim=None):
        if status not in STATUSES:
            raise ValueError(
                "unknown probe status {!r}; the five outcomes are {}".format(
                    status, ", ".join(STATUSES)
                )
            )
        if not source:
            raise ValueError("a probe result must name its source")
        if not detail:
            raise ValueError("a probe result must carry a legible detail; {} alone is not one".format(status))

        evidence = dict(evidence or {})
        _check_evidence(evidence, "evidence")

        if status == PROVEN and not evidence:
            raise ValueError(
                "{}: PROVEN with no evidence. A capability is proven by what came back, never by "
                "the absence of an error — record what you saw or report INSUFFICIENT.".format(source)
            )
        if status == REFUSED and not verbatim:
            raise ValueError(
                "{}: REFUSED with no verbatim message. The endpoint's own words are the artefact "
                "here; a paraphrase cannot be taken to whoever must buy the access.".format(source)
            )

        self.source = source
        self.status = status
        self.detail = detail
        self.evidence = evidence
        self.verbatim = verbatim

    @property
    def is_proven(self):
        return self.status in SUFFICIENT_STATUSES

    def as_dict(self):
        return {
            "status": self.status,
            "detail": self.detail,
            "evidence": dict(self.evidence),
            "verbatim": self.verbatim,
        }

    def __repr__(self):
        return "ProbeResult({!r}, {!r})".format(self.source, self.status)


def absent(source, detail):
    return ProbeResult(source, ABSENT, detail)


def unreachable(source, detail, evidence=None):
    return ProbeResult(source, UNREACHABLE, detail, evidence=evidence)


def refused(source, detail, verbatim, evidence=None):
    return ProbeResult(source, REFUSED, detail, evidence=evidence, verbatim=verbatim)


def insufficient(source, detail, evidence=None):
    return ProbeResult(source, INSUFFICIENT, detail, evidence=evidence)


def proven(source, detail, evidence):
    return ProbeResult(source, PROVEN, detail, evidence=evidence)
