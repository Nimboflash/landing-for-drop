# 13 — Raw-chain ground truth reader for a single transaction

**What to build:** The independent path. Given one transaction hash, produce the balance-delta picture
from raw chain data alone — receipt, event logs, execution trace, and raw balance changes — with no
vendor normalisation anywhere in the path. This is the reference the entire validation gate is
measured against, and it exists because two normalisation vendors can share assumptions and errors,
and in this domain they demonstrably take opposite conventions on the same events. Vendor output is
the thing being tested, not the reference.

**Blocked by:** 05 (and 03 for archival RPC access)

**Status:** ready-for-agent — **and it must be the validator's agent, not the builder's**

> ### This was built once, by the builder, and removed the same day
>
> On 2026-08-16 `src/groundtruth/` was written: a stdlib-only reader that met five of the seven
> criteria below, read 548 receipts from the committed snapshot without a refusal, and was
> cross-checked against `ingest`'s independently written decoder on three real transactions. It is
> at commit `7644955` and it is not in the tree.
>
> It was removed the same day, when ticket 02 settled on an **AI validator**. The argument for
> keeping it was that decoding an ERC-20 `Transfer` log has one right answer fixed by a public
> standard, so there is no judgement in it to anchor on. That argument is sound and it stops being
> sufficient the moment the validator shares a prior with whoever wrote the reader: `MACHINE-
> INDEPENDENT` already concedes that two agents from the same base model make correlated errors,
> and handing one of them a reference the other wrote is that problem in its sharpest form. A gate
> whose reference and whose subject were written by the same hand certifies nothing, and — this is
> the part that matters — it certifies nothing *invisibly*.
>
> **What removal buys, stated honestly, because it is less than it looks.** The code is in git
> history, and `src/ingest/events.py` decodes the same logs and is staying. Anyone can read either.
> This is a protocol constraint, not an enforced one — the same class as "reasoning before
> comparison", which ticket 02's own ledger already lists under *not achieved*. What it does is
> remove the path of least resistance and put the intent on the record.
>
> **So: whoever builds this must not read `7644955`, and should not read `ingest/events.py` before
> writing their own decoder.** If they do read either, the honest move is to say so in the
> validation report rather than to quietly proceed — a declared dependency can be discounted, an
> undeclared one cannot.
>
> Two findings from the removed build are worth keeping, because they are facts about the *builder*
> lane and survive it:
>
> 1. **`ingest.events.decode_logs` refuses an entire receipt on one unknown event signature.** On
>    `0x8f7c6ce3…` it refuses over a Uniswap V2 `Mint`. That is its no-silent-skip rule working as
>    documented, and it means the builder lane currently reads *nothing* from that transaction.
> 2. **A fee-on-transfer token cannot be detected from logs alone.** It emits the after-fee transfer
>    plus a separate fee transfer, both balanced; the amount the sender intended appears in no log.
>    Ticket 14's coverage matrix requires such a case, so it must be sought out deliberately —
>    sampling will not surface one, and a cell filled by sampling would be filled with a token
>    nobody verified takes a fee.

- [ ] Given a transaction hash, the reader emits per-address, per-token signed balance deltas derived
      from receipts, logs, traces, and raw balance changes.
- [ ] Internal ETH movement is captured from traces, not inferred from the value field alone.
- [ ] The reader emits the transaction's success or failure status from the receipt, independently of
      any vendor field.
- [ ] Three worked transactions are read and hand-checked against a block explorer: one simple single
      hop, one multi-hop route, and one transaction containing transfers unrelated to the trader.
- [ ] The reader imports nothing from the pipeline's classification, netting, FIFO, or valuation code,
      and this separation is structurally enforced rather than observed.
- [ ] Output is stable and re-derivable: the same transaction hash produces byte-identical output on
      re-run.
- [ ] The reader is usable by the Independent Validator without the builder's assistance, and the
      validator confirms this on at least one transaction they choose themselves.
