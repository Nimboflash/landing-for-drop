#!/usr/bin/env node
/**
 * CI step for `npm run ci:rights-guard`.
 *
 * BUILD-GUIDE → "Production-guard CI wiring": the default `next build` stays green during
 * development, while a dedicated CI step runs the FLAGGED production build and asserts a
 * NON-ZERO exit while mock assets remain. That red build is the PASSING state of this step
 * until launch clearance:
 *
 *   - guard blocked the flagged build  -> exit 0 (expected)
 *   - flagged build succeeded          -> exit 1 (the guard was weakened, or every asset was
 *                                        cleared — in which case delete this step deliberately)
 *   - build failed for another reason  -> exit 1 (this step proved nothing)
 *
 * WHY SPAWN THE BUILD rather than importing the content module: the content module is
 * TypeScript and imports JSON, so plain `node` cannot load it without a loader, and this repo
 * has no `tsx` dependency. Spawning the already-configured `build:production-check` script is
 * the simpler reliable option, and it exercises the real production path end to end.
 */

import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

/**
 * First line of every guard failure. Duplicated literal — keep in sync with
 * `PRODUCTION_MEDIA_GUARD_FAILURE` in `src/content/rights.ts` (a .mjs script cannot import it).
 */
const GUARD_SIGNATURE = "Production media guard blocked the build";

const BUILD_SCRIPT = "build:production-check";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/**
 * Decide the step's outcome from the flagged build's result. Pure, so it can be reasoned about
 * (and exercised) without running a build.
 *
 * @param {{ status: number | null, error?: Error, output: string }} run
 * @returns {{ ok: boolean, reason: string }}
 */
export function classifyGuardRun(run) {
  if (run.error) {
    return {
      ok: false,
      reason:
        `Could not run \`npm run ${BUILD_SCRIPT}\`: ${run.error.message}\n` +
        `This step proves nothing until the flagged build can run.`,
    };
  }

  const blocked = run.output.includes(GUARD_SIGNATURE);

  if (run.status === 0) {
    return {
      ok: false,
      reason:
        `The flagged production build SUCCEEDED.\n` +
        `The production-media guard must block while any asset is development-mock, ` +
        `rights-pending, or productionAllowed: false.\n` +
        `Check, in order:\n` +
        `  1. the guard itself (src/content/rights.ts) — never weaken it;\n` +
        `  2. the module-scope gate at the bottom of src/content/index.ts, which runs ` +
        `enforceProductionMediaRights over every published lens — the build only reaches it if ` +
        `something (a route or the root layout) imports "@/content";\n` +
        `  3. the content flags themselves — every mock asset must stay development-mock / ` +
        `productionAllowed: false.\n` +
        `If every asset really was cleared, retiring this step is a deliberate launch decision: ` +
        `see handoff/04-mock-content/REPLACE_BEFORE_LAUNCH.md.`,
    };
  }

  if (!blocked) {
    return {
      ok: false,
      reason:
        `The flagged production build failed with exit code ${run.status}, but its output never ` +
        `mentions "${GUARD_SIGNATURE}".\n` +
        `Something other than the media-rights guard broke the build, so this step proved ` +
        `nothing. Fix the build, then re-run.`,
    };
  }

  return {
    ok: true,
    reason:
      `The production-media guard blocked the flagged build (exit code ${run.status}), as it ` +
      `must while the development mock pack is in place.`,
  };
}

function main() {
  process.stdout.write(
    `Running \`npm run ${BUILD_SCRIPT}\` and asserting the production-media guard blocks it.\n` +
      `A blocked build is the PASSING state of this step until launch clearance.\n\n`,
  );

  const result = spawnSync("npm", ["run", BUILD_SCRIPT], {
    cwd: repoRoot,
    encoding: "utf8",
    env: { ...process.env, DROP_ENFORCE_MEDIA_RIGHTS: "1", FORCE_COLOR: "0" },
    shell: process.platform === "win32",
    maxBuffer: 64 * 1024 * 1024,
  });

  const output = `${result.stdout ?? ""}${result.stderr ?? ""}`;
  process.stdout.write(output.endsWith("\n") ? output : `${output}\n`);

  const verdict = classifyGuardRun({
    status: result.status,
    error: result.error,
    output,
  });

  if (verdict.ok) {
    process.stdout.write(`\nPASS — rights guard held.\n${verdict.reason}\n`);
    process.exit(0);
  }

  process.stderr.write(`\nFAIL — rights guard did NOT block the production build.\n${verdict.reason}\n`);
  process.exit(1);
}

const invokedDirectly =
  process.argv[1] !== undefined &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (invokedDirectly) {
  main();
}
