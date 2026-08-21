"""Raw Ethereum JSON-RPC. Bytes as the node returned them, and nothing else.

This package is **shared**: the builder lane and the validator lane both import it, and
``tests/test_lane_independence.py`` declares it ``SHARED``. That is only safe because it
interprets nothing. It moves a JSON-RPC request to an endpoint, hands back the ``result`` member
verbatim, records it so the call can be replayed, and — when every endpoint declines — reports each
refusal in the endpoint's own words.

The line, and why it is where it is
-----------------------------------

Permitted here: transport. HTTP, failover, back-off, request framing, parameter *encoding*,
recording, replay, refusal evidence.

Forbidden here, permanently: anything that gives the bytes meaning. Swap decoding, transfer
filtering, ETH/WETH normalisation, endpoint (address role) detection, lot matching, marking, dead
pool tests, token-age derivation. If the word "Transfer" appears in this package, something has
gone into the wrong module.

The reason is not tidiness. Ticket 36's validator must derive its expected answers independently of
the builder; if both lanes shared a decoder they would share its bug, and a shared bug is invisible
to the comparison — both sides compute the same wrong answer and agree, and the validation gate
certifies it. Raw bytes cannot carry that kind of bug: two lanes disagreeing about what a receipt
*says* is exactly the disagreement the gate exists to surface.

What this package guarantees
----------------------------

* the parsed ``result`` is returned unmodified — no renaming, no coercion, no int conversion;
* a recorded call replays without opening a socket, and :attr:`RpcClient.calls` says which mode
  each call ran in;
* no ``float`` ever enters or leaves — a JSON float in a chain response is refused on sight;
* the User-Agent sent is honest, enforced in the transport base class so a test fake inherits it.

What it does not guarantee
--------------------------

That any answer is correct, that two endpoints agree, that a free endpoint will still serve you
tomorrow, or that a replayed answer still matches the chain. Reproducible is not verified. Traces
in particular were refused by every free endpoint measured on 2026-08-09; nothing here can obtain
one, and the refusal text is preserved so that fact can be taken to a vendor rather than argued.

Typical use::

    from transport import RpcClient, RecordingCache

    client = RpcClient(cache=RecordingCache("tests/fixtures/transport/recordings"))
    receipt = client.get_transaction_receipt("0xb868...")
    assert client.last_call.replayed          # came from the snapshot, no network
"""

from .cache import (  # noqa: F401
    LIVE,
    REPLAY,
    Recording,
    RecordingCache,
    RecordingCorrupt,
    RecordingMissing,
    cache_key,
    optional_cache,
)
from .client import (  # noqa: F401
    AUTO,
    DEFAULT_BACKOFF_SECONDS,
    HTTP_STATUS,
    MALFORMED,
    MODES,
    REFRESH,
    REFUSAL_REASONS,
    REPLAY_ONLY,
    RPC_ERROR,
    UNREACHABLE,
    VERBATIM_LIMIT,
    Attempt,
    CallRecord,
    Refusal,
    RpcClient,
    RpcRefused,
)
from .endpoints import DEFAULT_ENDPOINTS, USER_AGENT, Endpoint, as_endpoints  # noqa: F401
from .http import (  # noqa: F401
    DEFAULT_TIMEOUT,
    DishonestUserAgent,
    EndpointUnreachable,
    FloatInChainResponse,
    HttpResponse,
    HttpTransport,
    UrllibHttpTransport,
    assert_honest_user_agent,
    parse_json_bytes,
)
from .params import (  # noqa: F401
    BLOCK_TAGS,
    assert_wire_safe,
    block_parameter,
    hex_quantity,
    require_address,
    require_hash,
)

__all__ = [
    "AUTO", "REPLAY_ONLY", "REFRESH", "MODES",
    "LIVE", "REPLAY",
    "RpcClient", "Attempt", "CallRecord", "Refusal", "RpcRefused",
    "UNREACHABLE", "HTTP_STATUS", "RPC_ERROR", "MALFORMED", "REFUSAL_REASONS",
    "VERBATIM_LIMIT", "DEFAULT_BACKOFF_SECONDS",
    "RecordingCache", "Recording", "RecordingMissing", "RecordingCorrupt", "cache_key",
    "optional_cache",
    "Endpoint", "DEFAULT_ENDPOINTS", "USER_AGENT", "as_endpoints",
    "HttpTransport", "UrllibHttpTransport", "HttpResponse", "EndpointUnreachable",
    "DishonestUserAgent", "FloatInChainResponse", "assert_honest_user_agent",
    "parse_json_bytes", "DEFAULT_TIMEOUT",
    "hex_quantity", "block_parameter", "require_hash", "require_address", "assert_wire_safe",
    "BLOCK_TAGS",
]
