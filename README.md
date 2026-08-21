# agents

Repository scaffold, set up as a reusable template.

## What's in here

- **`.claude/skills/`** — 41 Claude Code skills installed from
  [`mattpocock/skills`](https://github.com/mattpocock/skills) via `npx skills@latest add mattpocock/skills`
  (copied, not symlinked, so they travel with the repo). Tracked in `skills-lock.json`; run
  `npx skills@latest update` to pull upstream changes, or `npx skills@latest list` to see what's installed.
- **`executive-multi-agent-model/`** — the "Virtual Software Organization" (VSO) framework: a
  reusable, technology-independent governance model for running software development as an
  interconnected virtual organization of AI agents (orchestrator, product manager, CTO, QA,
  security, code review, etc.), with task/handoff/state schemas, templates, diagrams, and a worked
  example project. Start at [`executive-multi-agent-model/README.md`](executive-multi-agent-model/README.md)
  and [`executive-multi-agent-model/USAGE.md`](executive-multi-agent-model/USAGE.md).

## Using this as a template

1. Create a new repo from this one (GitHub "Use this template", or clone + re-point `origin`).
2. To apply the VSO framework to a new project, follow
   `executive-multi-agent-model/USAGE.md` (copy `project-profile.example.yaml` into
   `executive-multi-agent-model/projects/<slug>/`, pick a profile, fill the shared context from
   your PRD).
3. To pull in more Claude Code skills, run `npx skills@latest add <owner>/<repo>` from the repo
   root — see `skills-lock.json` for the ones already installed.
