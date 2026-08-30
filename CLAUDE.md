# DROP Immersive Weekly Lens

This repo builds the DROP Immersive Weekly Lens website — a scroll-driven, cinematic, Persian-first editorial page for DROP, a food concept store in Tehran. Read these before doing anything:

1. **`handoff/DROP_CLAUDE_MASTER_BUILD_BRIEF_EN.md`** — the master build brief (v1.2). Source of truth for product, design, motion, engineering, and QA. When anything conflicts with it, the brief wins.
2. **`docs/spec/drop-immersive-weekly-lens.md`** — the spec (PRD) derived from the brief: user stories, implementation decisions, testing decisions, agreed seams.
3. **`docs/tickets/`** — the tracer-bullet ticket breakdown with blocking edges. Work the frontier: any ticket whose blockers are all done.
4. **`docs/BUILD-GUIDE.md`** — how to build: TDD loop, agreed test seams, phase order, definition of done, hard rules.
5. **`CONTEXT.md`** — domain glossary. Use its vocabulary in code, tests, and issues.

## Hard rules (from the brief — never violate)

- Content is data-driven from the validated W04 lens object. Never hardcode titles, counts, image URLs, years, artists, or descriptions inside scene/animation code.
- All 20 mock media assets stay `rightsStatus: "development-mock"` / `productionAllowed: false`. Never remove or weaken the production-media guard; the production build must fail while temporary assets remain, and must fail/warn loudly on required `replace-with-final` assets. `rights-pending` assets render only in dev/staging behind an explicit internal flag.
- No commerce UI anywhere: no price, buy, cart, like, favorite, or waitlist elements. Top-right header stays empty in V1.
- Sharp corners on the logo and content-card system (`border-radius: 0` on cards) unless the physical form explicitly requires a circle (the O, discs); pills only for compact metadata when essential. No generic rounded SaaS styling.
- Never hotlink, scrape, or ship reference-site assets, code, copy, film posters, or album art.
- Every scroll-driven transition must be reversible; reduced-motion and no-WebGL fallbacks are mandatory, not optional.

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues (`gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` at the root, ADRs under `docs/adr/`. See `docs/agents/domain.md`.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
