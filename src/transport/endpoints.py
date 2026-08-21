"""The endpoints, the honest User-Agent, and what each was measured to serve.

Endpoints are a **parameter** everywhere in this package. :data:`DEFAULT_ENDPOINTS` is the
documented default, not a constant the client reaches for: ``RpcClient(endpoints=...)`` replaces
it wholesale, which is what lets a future ticket point the same code at a paid archive node
without editing this file.

What the default list is
------------------------

Three free public Ethereum mainnet JSON-RPC endpoints, probed on 2026-08-09 with the honest agent
below. Each was observed to serve receipts, ``eth_getLogs`` over a 2023 block, and archive state at
a 2023 height. **Traces were refused by all three** — 401, 406, or ``Method not found`` depending
on the vendor — so nothing in this repository may assume a trace is obtainable for free.

What this list does not guarantee
---------------------------------

Nothing about the future. It is a record of one measurement on one day, not a service level: a
free endpoint may rate-limit, prune, change vendor policy, or disappear without notice. It also
says nothing about *correctness* — that three endpoints answer does not make any of them right,
which is why :mod:`transport.cache` exists and why ticket 35 reconciles across sources.

The User-Agent is not decoration
--------------------------------

An earlier probe sent a fake browser agent and got that signature **permanently banned by
Cloudflare at eth.drpc.org**. The ban is on the signature, not on a session, and it cannot be
undone from here. So this package refuses to send a browser-shaped agent at all — see
:func:`transport.http.assert_honest_user_agent`, which is enforced in the transport base class so
that a fake transport in a test refuses exactly as the live one does.
"""

from dataclasses import dataclass

#: Identifies who is calling and how to reach them. Anything browser-shaped is refused by
#: :func:`transport.http.assert_honest_user_agent`; see the module docstring for what that cost.
USER_AGENT = "phase0-ingest/1.0 (smart-wallet research; contact: product@saraf.app)"


@dataclass(frozen=True)
class Endpoint:
    """One JSON-RPC URL and what it was observed to do.

    ``note`` is provenance for a human reader. Nothing in this package branches on it — an
    endpoint's capabilities are established by calling it and reading the refusal, never by
    consulting a label.
    """

    url: str
    note: str = ""

    def __post_init__(self):
        if not isinstance(self.url, str) or not self.url.startswith(("http://", "https://")):
            raise ValueError(
                "an endpoint must be an http(s) URL; got {!r}. Passing a bare hostname would be "
                "sent to urllib as a relative path and fail with an error that names the wrong "
                "problem.".format(self.url)
            )


#: Probed 2026-08-09. receipt OK / logs(2023) OK / archive-state OK on all three; traces refused
#: on all three. Ordered as tried: the client fails over down this list.
DEFAULT_ENDPOINTS = (
    Endpoint(
        "https://eth-mainnet.public.blastapi.io",
        "receipt OK, logs(2023) OK, archive-state OK; traces refused (probed 2026-08-09)",
    ),
    Endpoint(
        "https://eth-pokt.nodies.app",
        "receipt OK, logs(2023) OK, archive-state OK; traces refused (probed 2026-08-09)",
    ),
    Endpoint(
        "https://rpc.mevblocker.io",
        "receipt OK, logs(2023) OK, archive-state OK; traces refused (probed 2026-08-09)",
    ),
)


def as_endpoints(values):
    """Normalise a caller's ``endpoints=`` argument to a tuple of :class:`Endpoint`.

    Accepts :class:`Endpoint` instances and plain URL strings, so a caller may write
    ``endpoints=["https://my-archive.example"]`` without importing anything. An empty sequence is
    a defect, not an empty result: a client with nowhere to call would report every measurement as
    a refusal by nobody.
    """
    out = []
    for value in values:
        out.append(value if isinstance(value, Endpoint) else Endpoint(str(value)))
    if not out:
        raise ValueError(
            "endpoints is empty. A client with no endpoints cannot fail over, it can only refuse "
            "every call with an empty list of reasons — which reads as 'the chain said no' when "
            "in fact nothing was ever contacted."
        )
    return tuple(out)
