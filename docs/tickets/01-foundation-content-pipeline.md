# 01 — Foundation: project scaffold + validated content pipeline

**What to build:** A running Next.js site where `/` and `/lens/beautiful-imperfection` server-render the complete W04 lens as semantic, unstyled-but-tokenized text — every scene's data (thesis, hero messages, grid statement, 2 menu items, 3 films, 11 tracks, 4 art pieces, footer) rendered from the validated content object, with all 20 mock assets served locally. This is the tracer bullet proving the data path end to end before any motion exists.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Next.js App Router + TypeScript strict + Vitest + Playwright + Zod installed and configured; CI-runnable `test`, `typecheck`, `build` scripts
- [ ] Schema + W04 mock JSON + validated export adopted from `handoff/04-mock-content/src/content/`; mock assets copied to `public/media/lenses/beautiful-imperfection/` per `handoff/04-mock-content/media-manifest.csv` (note: the `lenses/` path segment follows the mock-pack manifest and the JSON's `src` values, deliberately deviating from the brief's §13 *suggested* tree)
- [ ] Content seam tests: schema parses W04; malformed data fails loudly; `assertProductionMedia` throws on the mock pack (asserted as correct behavior); counts match manifest (2/3/11/4)
- [ ] Rights-state coverage at the content seam, one fixture per state: production check fails on `development-mock` and `productionAllowed: false`, fails/warns loudly on required `replace-with-final` assets (extend the adopted guard — the handoff version checks only the first two), and exposes a dev/staging-only internal flag for `rights-pending` display
- [ ] A synthetic variable-count fixture lens (e.g. 5 menu items, 4 tracks, plus schema minimums: 2 menu / 3 tracks / 1 art piece) parses and is available to later tickets' count-driven tests
- [ ] Both routes render all lens text server-side (visible with JS disabled), Persian primary with `lang="fa"` and correct `dir` on text containers
- [ ] Design tokens in place: brief color variables, type scale, Montserrat + self-hosted Vazirmatn with no layout shift after font load
- [ ] Page seam smoke test: both routes return 200, contain the W04 title, 11 track titles, and zero console errors
- [ ] No hardcoded content strings, counts, or media paths inside components
