"""Dune — the historical DEX trade warehouse. Proof is *rows*, for a named block range.

Reaching ``api.dune.com`` proves that Dune exists. The capability Phase 0 depends on is that
``dex.trades`` and the aggregator tables have decoded the blocks we are going to ask about, and the
only way to learn that is to ask for those blocks and count what comes back.

So zero rows is a **failure**, not an empty result. Blocks 16,308,190–16,309,190 are roughly three
and a half hours of Ethereum mainnet on 1 Jan 2023; there is no reading of the world in which they
contain no DEX trades. An empty answer means the key is scoped to something else, the table has
been renamed, or the decoders do not reach where we assumed — all of which are things to find out
before the budget is approved rather than in month two.

Both halves are proven in one execution. ``dex.trades`` is the netting input; the aggregator tables
are what stop a 1inch or CoW settlement from being attributed to the solver (§13.5). A key that
returns one and not the other is provisioned for half the job, so the union query labels each row
with its source table and the probe requires rows from both.

Query creation is optional. Set ``DUNE_QUERY_ID`` to reuse a saved query — some tiers do not permit
creating one over the API, and being unable to *create* a query is not the same fact as being
unable to *read* ``dex.trades``.
"""

import time

from .. import fixtures
from ..outcomes import insufficient, proven
from .base import Probe

API_ROOT = "https://api.dune.com/api/v1"

#: Labelled so one execution proves both halves. Only plain scalar columns are projected, and
#: ``amount_usd`` is cast to text at the warehouse: a JSON double in the evidence would be a float
#: in the register, which the repository's numeric policy refuses on sight.
SQL = """
(select 'dex.trades' as source_table, block_number, project,
        cast(amount_usd as varchar) as amount_usd
   from dex.trades
  where blockchain = 'ethereum'
    and block_number between {start} and {end}
  limit 25)
union all
(select 'dex_aggregator.trades' as source_table, block_number, project,
        cast(amount_usd as varchar) as amount_usd
   from dex_aggregator.trades
  where blockchain = 'ethereum'
    and block_number between {start} and {end}
  limit 25)
"""

TERMINAL_STATES = ("QUERY_STATE_COMPLETED", "QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED")
POLL_ATTEMPTS = 40
POLL_SECONDS = 3


class DuneProbe(Probe):

    source = "dune"
    capability = (
        "dex.trades and dex_aggregator.trades return rows for Ethereum blocks {}-{} ({})".format(
            fixtures.BLOCK_RANGE_START, fixtures.BLOCK_RANGE_END, fixtures.WINDOW_1_LABEL
        )
    )
    credential_env = ("DUNE_API_KEY",)

    def __init__(self, sleep=None, poll_attempts=POLL_ATTEMPTS):
        #: Injected so the suite exercises the polling loop without spending forty seconds on it.
        self._sleep = sleep if sleep is not None else time.sleep
        self._poll_attempts = poll_attempts

    def _headers(self, env):
        return {"X-Dune-API-Key": env["DUNE_API_KEY"].strip(), "Accept": "application/json"}

    def _probe(self, transport, env):
        headers = self._headers(env)

        query_id = (env.get("DUNE_QUERY_ID") or "").strip()
        if not query_id:
            created = transport.post_json(
                "{}/query".format(API_ROOT),
                {
                    "name": "phase0-provisioning-probe",
                    "query_sql": SQL.format(
                        start=fixtures.BLOCK_RANGE_START, end=fixtures.BLOCK_RANGE_END
                    ),
                    "is_private": True,
                },
                headers=headers,
            )
            if not created.ok:
                return self.refusal(created, "creating a probe query")
            payload = created.json() or {}
            query_id = payload.get("query_id")
            if not query_id:
                return insufficient(
                    self.source,
                    "query creation answered 2xx but named no query_id; nothing was executed. "
                    "Set DUNE_QUERY_ID to a saved query if this tier cannot create queries.",
                )

        execution = transport.post_json(
            "{}/query/{}/execute".format(API_ROOT, query_id), {}, headers=headers
        )
        if not execution.ok:
            return self.refusal(execution, "executing the probe query",
                                evidence={"query_id": str(query_id)})
        execution_id = (execution.json() or {}).get("execution_id")
        if not execution_id:
            return insufficient(
                self.source,
                "execute answered 2xx but named no execution_id, so there is nothing to read.",
                evidence={"query_id": str(query_id)},
            )

        state = None
        for attempt in range(self._poll_attempts):
            status = transport.get("{}/execution/{}/status".format(API_ROOT, execution_id),
                                   headers=headers)
            if not status.ok:
                return self.refusal(status, "polling the execution",
                                    evidence={"execution_id": str(execution_id)})
            state = (status.json() or {}).get("state")
            if state in TERMINAL_STATES:
                break
            self._sleep(POLL_SECONDS)

        if state != "QUERY_STATE_COMPLETED":
            return insufficient(
                self.source,
                "execution ended in state {!r} after {} polls — no rows were produced, so the "
                "warehouse is not proven.".format(state, self._poll_attempts),
                evidence={"execution_id": str(execution_id), "state": str(state)},
            )

        results = transport.get("{}/execution/{}/results".format(API_ROOT, execution_id),
                                headers=headers)
        if not results.ok:
            return self.refusal(results, "reading the execution results",
                                evidence={"execution_id": str(execution_id)})

        rows = ((results.json() or {}).get("result") or {}).get("rows") or []
        by_table = {}
        blocks = []
        for row in rows:
            table = str(row.get("source_table", "unknown"))
            by_table[table] = by_table.get(table, 0) + 1
            block = row.get("block_number")
            if isinstance(block, int):
                blocks.append(block)

        evidence = {
            "query_id": str(query_id),
            "execution_id": str(execution_id),
            "block_range": "{}-{}".format(fixtures.BLOCK_RANGE_START, fixtures.BLOCK_RANGE_END),
            "window": fixtures.WINDOW_1_LABEL,
            "rows_total": len(rows),
            "rows_dex_trades": by_table.get("dex.trades", 0),
            "rows_dex_aggregator": by_table.get("dex_aggregator.trades", 0),
            "first_block_seen": min(blocks) if blocks else None,
            "last_block_seen": max(blocks) if blocks else None,
        }

        empty = [name for name, count in (
            ("dex.trades", evidence["rows_dex_trades"]),
            ("dex_aggregator.trades", evidence["rows_dex_aggregator"]),
        ) if count == 0]
        if empty:
            return insufficient(
                self.source,
                "the query ran and returned no rows from {} for blocks {}-{}. That range is "
                "~3.5 hours of Ethereum mainnet inside window 1 and certainly contains trades, so "
                "an empty answer means the key, the tier or the decoders do not cover what this "
                "project assumes — not that nothing happened.".format(
                    " and ".join(empty), fixtures.BLOCK_RANGE_START, fixtures.BLOCK_RANGE_END
                ),
                evidence=evidence,
            )

        return proven(
            self.source,
            "{} rows for blocks {}-{}: {} from dex.trades, {} from the aggregator tables.".format(
                evidence["rows_total"],
                fixtures.BLOCK_RANGE_START,
                fixtures.BLOCK_RANGE_END,
                evidence["rows_dex_trades"],
                evidence["rows_dex_aggregator"],
            ),
            evidence=evidence,
        )
