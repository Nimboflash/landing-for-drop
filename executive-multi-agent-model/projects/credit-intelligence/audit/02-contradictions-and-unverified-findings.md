# 02 — Contradictions and Unverified Findings

The disagreements inside the evidence, and the claims that evidence cannot settle. Uncertainty is not
resolved by guessing; it is recorded and routed to a follow-up task.

## Contradiction table

| Topic | Document A | Document B | Conflict | Likely resolution | Classification | Confidence | Follow-up |
|---|---|---|---|---|---|---|---|
| `credit-architect` scope | `repo:credit-architect.md` (Target stack, "design for scale", 20 "suggested" contexts, no Phase-1 gating) | `repo:PROMPT.md §7,§10` + `repo:cto.md` (phase-split required; lane clamped to policy) | The agent file contradicts the constitution's phase discipline | The constitution wins by its own precedence rule → `credit-architect.md` is "a bug"; the seed prompt is stale | Extracted (tension) / Inferred (cause) | High / Medium | FU-1 |
| Agent count in `extracted-system/` | Prior brief: "agents (20)" | On-disk: 19 agent files | Off-by-one count | On-disk count (19) is correct | Extracted | High | — |
| Template count | Prior brief: "templates (19)" | On-disk: 20 template files | Off-by-one count | On-disk count (20) is correct | Extracted | High | — |
| Domain gates status | `CONTRIBUTING.md` CI section (names leakage/replay/stability etc.) | `repo:.github/workflows/ci.yml` (only format/lint/mypy/pytest/gitleaks/layering wired) | Documented gates are not implemented | Specified, not implemented — a real gap, not a contradiction of fact | Extracted (both true) | High | FU-2 |
| Hook vs CI denylist | `repo:.claude/hooks/domain-purity.sh` (lacks `pandas`/`numpy`) | `repo:tests/test_layering.py` `FORBIDDEN_IN_DOMAIN` (includes them) | Two enforcement points disagree on the denylist | CI layering test is the real backstop; single source of truth recommended | Extracted | Medium | FU-3 |
| "Release-ready `main`" vs no release path | `repo:CONTRIBUTING.md` ("`main` always releasable") | `EXT/13-git-devops-and-release.md` (no deploy/release/rollback exists) | Aspiration vs absence | Both true: `main` is *kept* releasable, but there is nowhere to release to | Extracted / Missing | High | — |

None of these is a factual contradiction the framework must adjudicate blindly; each resolves to
"constitution precedence," "on-disk truth," or "specified but not implemented," and the two that need
original-repo access to fully settle become follow-up tasks.

## Unverified findings (evidence cannot settle these)

Everything below requires evidence the working copy does not contain — chiefly git history. All are
**Unverified**; none may be asserted as fact.

| Finding | Why Unverified | What would settle it |
|---|---|---|
| Order in which agents/docs were authored | No git history; all file mtimes identical (single archive extraction) | The original `.git` |
| `credit-architect` predates the nine specialists | Structural inference only; no timestamps | Commit history / authorship |
| ADRs authored in numeric order (0001→0002→0003) | Citation-direction inference (0002 cites 0001; 0003 cites both) | Commit dates |
| Any release/version chronology | Zero shipped versions; no tags | Tags / release records |
| Whether the git conventions in `CONTRIBUTING.md` were actually followed | No history to check practice against policy | Commit/PR history |
| Agent usage per version | No runtime logs, no history | Session/CI run history |

## The one structural anomaly (Inferred, not contradiction)

`credit-architect.md` is the format outlier of the roster — free-form body, "combines the experience
of nine professions," a Target stack without Phase-1 gating, "Suggested bounded contexts 1–20," and
the only agent lacking both a Definition of Done and an Escalation section. The prior analysis reads
this as a generation-0 seed agent later disciplined by the constitution and nine specialists. This is
the single most interesting historical claim in the extraction, and it is **Inferred at medium
confidence** — recorded as such, carried into the roster as `domain-policy-architect` with a note, and
never presented as established fact.

## Handling rule applied

For every item above, the framework's response is uniform: preserve the classification, do not
upgrade it without new evidence, and — where original-repo access would settle it — write an explicit
follow-up task (`03-...`). Uncertainty is documented, not guessed away.
