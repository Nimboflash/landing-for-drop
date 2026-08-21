"""The shape every probe shares: name a capability, then try to fail to demonstrate it.

The base class exists to make three things impossible to forget.

**A missing credential short-circuits before anything is built.** No transport is constructed, no
URL is templated, and nothing that could contain a key is ever assembled. That is why the whole
suite runs green with an empty environment: ``ABSENT`` is reached before the interesting code.

**"The endpoint did not answer" and "the endpoint said no" stay different.** ``TransportError``
becomes ``UNREACHABLE``; a non-2xx :class:`~tools.provisioning.transport.Response` becomes
``REFUSED`` carrying the vendor's own words. The two have different owners — one is a node choice,
the other is a purchase — and a single FAILED status would lose the instruction.

**A crash inside interpretation is not a pass.** Any unexpected exception while reading a payload
becomes ``INSUFFICIENT``, never ``PROVEN``. The one exception deliberately allowed to escape is
:class:`~tools.provisioning.prohibited.ProhibitedSourceError`: that is a defect in this package,
not a fact about a vendor, and swallowing it into a status would turn the prohibition into a
warning.

**Nothing leaves here carrying a credential.** Every result is passed through the redactor on the
way out, against *the environment the probe was handed* rather than against ``os.environ``. Those
are the same mapping in production and different ones the moment a caller supplies an env — which
``main(env=...)`` does, and which the suite does for every test. Redacting per-probe is belt and
braces behind the redaction each probe already does at the point of recording; it is here because
this is the one line every result must cross, so a probe author who forgets cannot leak.
"""

import os

from ..outcomes import ProbeResult, absent, insufficient, refused, unreachable
from ..prohibited import ProhibitedSourceError
from ..redaction import redact
from ..transport import TransportError, UrllibTransport

#: Truncation for a vendor's error body. Long enough for a real message ("archive requests require
#: a personal token"), short enough that a stack-trace-shaped HTML page does not fill the register.
VERBATIM_LIMIT = 600


class Probe(object):
    """One source, one capability, one status.

    Subclasses set :attr:`source`, :attr:`capability` and :attr:`credential_env`, and implement
    ``_probe(transport, env)`` returning a :class:`~tools.provisioning.outcomes.ProbeResult`.
    """

    source = None
    capability = None
    #: Environment variables that must be non-empty before the probe is worth attempting.
    credential_env = ()

    def run(self, transport=None, env=None):
        env = os.environ if env is None else env
        return redacted_result(self._run(transport, env), env)

    def _run(self, transport, env):
        missing = [name for name in self.credential_env if not (env.get(name) or "").strip()]
        if missing:
            return absent(
                self.source,
                "no credential configured: set {}. Nothing was contacted.".format(
                    ", ".join(missing)
                ),
            )

        if transport is None:
            transport = UrllibTransport()

        try:
            return self._probe(transport, env)
        except ProhibitedSourceError:
            # A bug in this package, not a state of the world. Let it escape loudly.
            raise
        except TransportError as exc:
            return unreachable(
                self.source,
                "endpoint did not answer: {}".format(exc.reason),
                evidence={"endpoint": exc.url},
            )
        except Exception as exc:  # noqa: BLE001 - deliberate: see module docstring
            return insufficient(
                self.source,
                "probe could not interpret what came back ({}: {}). This is not a pass — the "
                "capability is unproven.".format(type(exc).__name__, redact(str(exc))),
            )

    # -- helpers for subclasses ------------------------------------------------

    def _probe(self, transport, env):  # pragma: no cover - abstract
        raise NotImplementedError

    def refusal(self, response, what, evidence=None):
        """Turn a non-2xx answer into ``REFUSED`` with the endpoint's own words kept intact."""
        body = response.text(limit=VERBATIM_LIMIT).strip()
        verbatim = body or "HTTP {} with an empty body".format(response.status)
        detail = "{} was declined with HTTP {}. The endpoint's message is recorded verbatim.".format(
            what, response.status
        )
        combined = {"http_status": response.status, "endpoint": response.url}
        combined.update(evidence or {})
        return refused(self.source, detail, verbatim=verbatim, evidence=combined)


def redacted_result(result, env):
    """A copy of ``result`` with every string scrubbed against ``env``.

    ``env`` is the environment of record, not a supplement to ``os.environ``: a probe run against a
    supplied mapping is being asked about *those* credentials, and treating the ambient process as
    an additional source of secrets would make the redaction depend on who happened to export what.

    Numbers pass through untouched. A wei balance or a row count cannot contain a key, and casting
    them to text to redact them would be the one place in this package that turns an int into a
    string on the way to the register.
    """
    return ProbeResult(
        result.source,
        result.status,
        redact(result.detail, env),
        evidence=_redacted(result.evidence, env),
        verbatim=redact(result.verbatim, env),
    )


def _redacted(value, env):
    if isinstance(value, str):
        return redact(value, env)
    if isinstance(value, dict):
        return {key: _redacted(item, env) for key, item in value.items()}
    if isinstance(value, list):
        return [_redacted(item, env) for item in value]
    return value
