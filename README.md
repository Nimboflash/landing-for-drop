# DROP Immersive Weekly Lens

The website for **DROP** — a food concept store in Tehran with a cultural point of view. Each Weekly Lens is one scroll-driven, cinematic, Persian-first editorial journey through a weekly theme: taste, films, music, and art pieces held together by one thesis. Launch seed: **W04 / Beautiful Imperfection**.

## Where to start

| Doc | What it is |
|---|---|
| [`handoff/DROP_CLAUDE_MASTER_BUILD_BRIEF_EN.md`](handoff/DROP_CLAUDE_MASTER_BUILD_BRIEF_EN.md) | Master build brief v1.2 — **the source of truth** for product, design, motion, engineering, QA |
| [`docs/spec/drop-immersive-weekly-lens.md`](docs/spec/drop-immersive-weekly-lens.md) | The spec (PRD): user stories, implementation and testing decisions, agreed seams |
| [`docs/tickets/`](docs/tickets/README.md) | 15 tracer-bullet tickets with blocking edges — the build plan |
| [`docs/BUILD-GUIDE.md`](docs/BUILD-GUIDE.md) | How to build: TDD loop, the three test seams, definition of done |
| [`CONTEXT.md`](CONTEXT.md) | Domain glossary — the project's vocabulary |
| [`CLAUDE.md`](CLAUDE.md) | Agent entry point + hard rules |

The full handoff package (brand references, motion/layout references, validated W04 mock content, 20 local mock assets) is vendored under [`handoff/`](handoff/PACKAGE_MANIFEST.md); only the three large `.mov` motion clips are excluded (see `handoff/02-motion/VIDEO_REFERENCES.md`).

## Tooling that ships with the repo

- **`.claude/skills/`** — 41 Claude Code skills from [`mattpocock/skills`](https://github.com/mattpocock/skills) (tracked in `skills-lock.json`). The build process uses `/to-spec`, `/to-tickets`, `/tdd`, `/implement`, `/code-review`, and `/triage`; tracker config lives in `docs/agents/`.
- **`executive-multi-agent-model/`** — the Virtual Software Organization (VSO) framework: a reusable governance model for running development as a virtual organization of AI agents. See its [README](executive-multi-agent-model/README.md).

## Status

Planning docs complete; implementation not started. First ticket on the frontier: [`docs/tickets/01-foundation-content-pipeline.md`](docs/tickets/01-foundation-content-pipeline.md).
