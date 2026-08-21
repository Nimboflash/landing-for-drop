# 07 — Commit the original specification to version control

**What to build:** The freeze manifest is supposed to pin every input to the experiment. One of those
inputs — the original project specification — currently exists only as text pasted into a chat session
and is not under version control. Three repository documents cite its sections (5.1, 5.2, 5.3, 5.4,
5.5, 5.7, 5.8, 5.9, 5.10, 5.11, 5.12, 9, 10, 11, 12, 13, 14) and none of those references resolve.
This ticket ends with the specification committed, or with its absence recorded as a permanent,
enumerated gap so the freeze does not silently pin a chat log.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] The original specification text is recovered and committed to version control at a named commit,
      unedited, with its provenance recorded.
- [ ] Every section reference made by the pre-registration, the amendments document, and the addendum
      is checked against the committed text and marked resolved or unresolved.
- [ ] If the text cannot be recovered, the outcome is a recorded gap register rather than a
      reconstruction. Contents are **not** invented.
- [ ] The gap register enumerates at minimum: §14's full example output shape, §5.11's original
      example allocation, §9's original data model that A14 adds fields to, §12's original risk list,
      and the twelve engines named but not specified.
- [ ] Where an amendment says "currently the spec says X", the paraphrase is marked as either
      confirmed against the committed source or recorded as the only surviving record.
- [ ] The freeze manifest schema is updated so that the specification is a pinned input with either a
      commit hash or an explicit `UNAVAILABLE` marker — it cannot be silently omitted.
