"""Ethereum archival RPC — all four capabilities for one named historical transaction, or nothing.

This is the source ticket 03 was written around. It has no invoice attached, so nobody gets a
monthly reminder that it exists, and it is the independent ground truth the entire validation gate
rests on (§13, ticket 13). The predictable way to fail Phase 0 is to assume it: "we can always get
a trace" is true of Ethereum in general and false of most endpoints in particular.

Four capabilities, and the source is provisioned only if it serves **all four** for the same
transaction:

    receipt         eth_getTransactionReceipt      status, gas, and the canonical log set
    event logs      eth_getLogs                    logs are *indexed*, not merely embedded
    execution trace debug_traceTransaction         internal calls and value movements
                    or trace_transaction           (geth and erigon/parity spellings both accepted)
    balance delta   eth_getBalance at N-1 and N    historical *state*, which is what "archival" means

The failure mode this exists to catch is a node that serves the first two happily and refuses the
third — already observed on three public endpoints. That refusal arrives as **HTTP 200** with a
JSON-RPC ``error`` object inside it, so a probe that checked status codes would record it as a
success. Here, the JSON-RPC error is read, classified as REFUSED, and its message is recorded
verbatim: "archive requests require a personal token" is a sentence somebody has to take to
whoever holds the card, and a paraphrase is no use to them.

The balance delta is not decoration. Receipts and logs are served from the *receipts* database,
which pruned nodes keep; ``eth_getBalance`` at a three-year-old height requires historical state.
It is the only one of the four that a full-but-not-archival node cannot fake.

The credential *is a URL*, so every endpoint string leaving this module goes through
:mod:`tools.provisioning.redaction` first. The register records ``https://host/<redacted>``.
"""

from .. import fixtures
from ..outcomes import insufficient, proven, refused
from ..redaction import redact, redact_url
from .base import Probe, VERBATIM_LIMIT

#: How far into the block to look for a transaction with logs before giving up. A plain ETH
#: transfer has no logs, so index 0 is not always usable; walking a bounded distance keeps the
#: choice deterministic while staying honest about which transaction was used.
MAX_TX_SCAN = 25

TRACE_METHODS = (
    ("debug_traceTransaction", "callTracer"),   # geth, reth
    ("trace_transaction", None),                # erigon, nethermind, openethereum lineage
)


class ArchivalRpcProbe(Probe):

    source = "archival_rpc"
    capability = (
        "receipt, event logs, execution trace and a raw balance delta for one transaction in "
        "block {}".format(fixtures.ARCHIVAL_BLOCK)
    )
    credential_env = ("ETH_ARCHIVAL_RPC_URL",)

    def __init__(self):
        self._id = 0

    # -- JSON-RPC --------------------------------------------------------------

    def _call(self, transport, url, method, params):
        """Return ``(result, error)``. A JSON-RPC error is an *answer*, never an exception."""
        self._id += 1
        response = transport.post_json(
            url, {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        )
        if not response.ok:
            body = response.text(limit=VERBATIM_LIMIT).strip()
            return None, {
                "code": response.status,
                "message": body or "HTTP {} with an empty body".format(response.status),
                "transport": "http",
            }
        payload = response.json()
        if payload is None:
            return None, {"code": None, "message": "the endpoint answered with something that is "
                                                   "not JSON", "transport": "http"}
        if isinstance(payload, dict) and payload.get("error"):
            error = payload["error"]
            if not isinstance(error, dict):
                error = {"code": None, "message": str(error)}
            return None, {
                "code": error.get("code"),
                "message": redact(str(error.get("message", ""))) or "(no message)",
                "transport": "jsonrpc",
            }
        return (payload or {}).get("result"), None

    def _refused(self, what, error, evidence):
        return refused(
            self.source,
            "{} was declined by the node (JSON-RPC code {}). A node that serves some of the four "
            "capabilities and refuses this one is not provisioned — the message below is what to "
            "take to whoever buys the access.".format(what, error.get("code")),
            verbatim=error.get("message"),
            evidence=evidence,
        )

    # -- the probe -------------------------------------------------------------

    def _probe(self, transport, env):
        url = env["ETH_ARCHIVAL_RPC_URL"].strip()
        block = fixtures.ARCHIVAL_BLOCK
        block_hex = hex(block)
        evidence = {
            "endpoint": redact_url(url),
            "block": block,
            "block_note": fixtures.ARCHIVAL_BLOCK_NOTE,
            "capabilities_required": ["receipt", "event_logs", "execution_trace", "balance_delta"],
        }

        tx_hash, sender, block_hash, error, detail = self._named_transaction(
            transport, url, env, block_hex
        )
        if error is not None:
            return self._refused("reading block {}".format(block), error, evidence)
        if tx_hash is None:
            return insufficient(self.source, detail, evidence=evidence)

        evidence["transaction"] = tx_hash
        evidence["selected_by"] = detail

        # 1 -- receipt ---------------------------------------------------------
        receipt, error = self._call(transport, url, "eth_getTransactionReceipt", [tx_hash])
        if error is not None:
            return self._refused("eth_getTransactionReceipt", error, evidence)
        if not isinstance(receipt, dict) or "blockNumber" not in receipt:
            return insufficient(
                self.source,
                "no usable receipt for {} — the node answered without an error and without a "
                "receipt, which is not a pass.".format(tx_hash),
                evidence=evidence,
            )
        logs = receipt.get("logs") or []
        evidence["receipt_status"] = str(receipt.get("status"))
        evidence["receipt_gas_used"] = str(receipt.get("gasUsed"))
        evidence["receipt_log_count"] = len(logs)

        # 2 -- event logs, from the index rather than from the receipt ---------
        addresses = sorted({str(entry.get("address")) for entry in logs if entry.get("address")})
        log_filter = {"fromBlock": block_hex, "toBlock": block_hex}
        if addresses:
            log_filter["address"] = addresses[0]
        indexed, error = self._call(transport, url, "eth_getLogs", [log_filter])
        if error is not None:
            return self._refused("eth_getLogs", error, evidence)
        indexed = indexed or []
        ours = [entry for entry in indexed
                if str(entry.get("transactionHash", "")).lower() == tx_hash.lower()]
        evidence["logs_in_block_for_address"] = len(indexed)
        evidence["logs_matching_transaction"] = len(ours)
        if not ours:
            return insufficient(
                self.source,
                "eth_getLogs returned {} logs for block {} but none belonging to {}. The receipt "
                "carried logs the log index does not, so the two disagree — that is a defect in "
                "the node, not in the transaction.".format(len(indexed), block, tx_hash),
                evidence=evidence,
            )

        # 3 -- execution trace -------------------------------------------------
        trace, error, method = self._trace(transport, url, tx_hash)
        if trace is None and error is not None:
            evidence["trace_methods_attempted"] = [name for name, _ in TRACE_METHODS]
            return self._refused(
                "the execution trace ({})".format(
                    " and ".join(name for name, _ in TRACE_METHODS)
                ),
                error,
                evidence,
            )
        if not trace:
            evidence["trace_methods_attempted"] = [name for name, _ in TRACE_METHODS]
            return insufficient(
                self.source,
                "the node accepted a trace request for {} and returned nothing usable. A receipt "
                "without a trace is exactly the half-provisioned node this probe exists to "
                "catch.".format(tx_hash),
                evidence=evidence,
            )
        evidence["trace_method"] = method
        evidence["trace_top_level_keys"] = sorted(trace)[:12] if isinstance(trace, dict) else None
        evidence["trace_entries"] = len(trace) if isinstance(trace, list) else None

        # 4 -- raw balance delta, which needs historical state -----------------
        before, error = self._call(transport, url, "eth_getBalance", [sender, hex(block - 1)])
        if error is not None:
            return self._refused(
                "eth_getBalance at block {} (historical state)".format(block - 1), error, evidence
            )
        after, error = self._call(transport, url, "eth_getBalance", [sender, block_hex])
        if error is not None:
            return self._refused(
                "eth_getBalance at block {} (historical state)".format(block), error, evidence
            )
        try:
            # wei is a raw quantity: int, never Decimal and never float. §"numeric policy".
            before_wei, after_wei = int(before, 16), int(after, 16)
        except (TypeError, ValueError):
            return insufficient(
                self.source,
                "eth_getBalance answered without an error but not with a quantity "
                "({!r} -> {!r}), so historical state is unproven.".format(before, after),
                evidence=evidence,
            )
        evidence["balance_account"] = sender
        evidence["balance_wei_before"] = before_wei
        evidence["balance_wei_after"] = after_wei
        evidence["balance_delta_wei"] = after_wei - before_wei

        return proven(
            self.source,
            "all four capabilities for {} in block {}: receipt ({} logs), {} indexed logs, a {} "
            "trace, and a balance delta of {} wei across blocks {}-{}.".format(
                tx_hash, block, evidence["receipt_log_count"],
                evidence["logs_matching_transaction"], method,
                evidence["balance_delta_wei"], block - 1, block,
            ),
            evidence=evidence,
        )

    # -- helpers ---------------------------------------------------------------

    def _named_transaction(self, transport, url, env, block_hex):
        """The transaction under test: pinned by env, or named by construction from the block.

        Returns ``(tx_hash, sender, block_hash, error, detail)``. See :mod:`..fixtures` for why
        this is derived rather than pasted.
        """
        block, error = self._call(transport, url, "eth_getBlockByNumber", [block_hex, True])
        if error is not None:
            return None, None, None, error, None
        if not isinstance(block, dict):
            return None, None, None, None, (
                "the node returned no block at {}. A node that cannot serve a 2023 block is not "
                "archival on any definition.".format(block_hex)
            )

        transactions = block.get("transactions") or []
        block_hash = block.get("hash")

        pinned = fixtures.pinned_archival_tx(env)
        if pinned:
            for index, tx in enumerate(transactions):
                if str(tx.get("hash", "")).lower() == pinned.lower():
                    return (tx["hash"], tx.get("from"), block_hash, None,
                            "pinned by ETH_ARCHIVAL_PROBE_TX (index {} of block)".format(index))
            return None, None, None, None, (
                "ETH_ARCHIVAL_PROBE_TX names a transaction that is not in block {}; pin one that "
                "is, or unset it and let the probe choose.".format(block_hex)
            )

        for index, tx in enumerate(transactions[:MAX_TX_SCAN]):
            # A contract call is wanted, not a bare transfer: the probe has to prove *logs*, and a
            # plain ETH send has none. ``input`` longer than "0x" is the cheap, local test.
            if tx.get("hash") and len(str(tx.get("input", "0x"))) > 2:
                return (tx["hash"], tx.get("from"), block_hash, None,
                        "first contract-calling transaction of block {} (index {})".format(
                            int(block_hex, 16), index))

        return None, None, None, None, (
            "no contract-calling transaction in the first {} of block {} — the block came back "
            "empty or malformed, so there is nothing to prove the four capabilities against.".format(
                MAX_TX_SCAN, int(block_hex, 16)
            )
        )

    def _trace(self, transport, url, tx_hash):
        """Try each trace spelling. Returns ``(trace, last_error, method_name)``."""
        last_error = None
        for method, tracer in TRACE_METHODS:
            params = [tx_hash, {"tracer": tracer}] if tracer else [tx_hash]
            trace, error = self._call(transport, url, method, params)
            if error is None:
                return trace, None, method
            last_error = error
        return None, last_error, None
