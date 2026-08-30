#!/usr/bin/env node
/**
 * Lighthouse gate for the DROP Immersive Weekly Lens (brief §17, ticket 15 box 6).
 *
 * Audits BOTH lens routes on BOTH form factors against an **already-running** production
 * server. It never builds and never starts a server: every agent on this repo shares one
 * `.next` directory, and concurrent builds corrupt it. Point it at the running port instead.
 *
 *     node scripts/lighthouse-audit.mjs                 # defaults to http://localhost:3200
 *     node scripts/lighthouse-audit.mjs --port 3200
 *     node scripts/lighthouse-audit.mjs --url http://localhost:3200
 *
 * ## The gate
 *
 * Brief §17, "Suggested launch targets" — these four numbers and no others:
 *
 * | target                | threshold | applies to                       |
 * | --------------------- | --------- | -------------------------------- |
 * | Accessibility         | ≥ 95      | every route × form factor        |
 * | Best Practices        | ≥ 90      | every route × form factor        |
 * | Performance (mobile)  | ≥ 75      | mobile runs only                 |
 * | CLS                   | < 0.1     | every route × form factor        |
 *
 * Desktop performance is measured and printed but **not** gated: the brief names a mobile
 * performance target only ("Mobile performance: 75 or higher for the full immersive build"),
 * and inventing a desktop threshold would be a target this project never agreed to.
 *
 * A missed gated threshold exits non-zero so this can gate CI later.
 *
 * ## The caveat that matters more than the score
 *
 * Lighthouse's `color-contrast` audit **silently skips text drawn over a canvas** — axe-core
 * cannot sample a WebGL framebuffer, so it reports no contrast finding at all rather than a
 * failure. Every scene on this page puts editorial text over a live shader. A passing
 * accessibility score therefore says **nothing** about AA contrast over the backgrounds; that
 * stays a `[manual]` acceptance box, sampled on worst-case shader frames. The same sentence is
 * printed on every run and written into the JSON summary so it cannot be lost between the
 * number and the PR.
 */

import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { hostname, arch, cpus, platform, release, totalmem } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import * as chromeLauncher from "chrome-launcher";
import lighthouse from "lighthouse";
import desktopConfig from "lighthouse/core/config/desktop-config.js";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_PORT = 3200;

/** Brief §5: both routes render the same lens template, so both are audited. */
const ROUTES = ["/", "/lens/beautiful-imperfection"];

/** Brief §17 launch targets. Expected values come from the brief, never from a measured run. */
const THRESHOLDS = {
  accessibility: { min: 95, label: "Accessibility score", appliesTo: "all" },
  "best-practices": { min: 90, label: "Best Practices score", appliesTo: "all" },
  performance: { min: 75, label: "Mobile performance", appliesTo: "mobile" },
  cls: { max: 0.1, label: "CLS", appliesTo: "all" },
};

const CONTRAST_CAVEAT =
  "Lighthouse's color-contrast audit SILENTLY SKIPS text drawn over a <canvas>: axe-core cannot " +
  "sample a WebGL framebuffer, so it reports nothing rather than a failure. Every scene here " +
  "puts editorial text over a live shader, so a passing accessibility score says NOTHING about " +
  "AA contrast over the backgrounds. That remains a [manual] acceptance box — sample worst-case " +
  "shader frames by hand and attach the measurements.";

/**
 * Ticket 15's `[manual]` acceptance boxes. Nothing in this script measures them; they are
 * listed on every run so a green gate is never mistaken for a complete acceptance pass.
 */
const MANUAL_BOXES = [
  "AA contrast for text over live shaders — sample worst-case shader frames by hand (Lighthouse cannot).",
  "60fps on capable desktop / >=30fps on mid-range mobile for the heaviest scenes — profile with named hardware.",
  "Shader look against the references, and scroll rhythm judged by feel.",
];

/* ------------------------------------------------------------------ arguments */

function parseArgs(argv) {
  const args = { url: null, port: DEFAULT_PORT, out: null };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (flag === "--port") {
      args.port = Number(value);
      index += 1;
    } else if (flag === "--url") {
      args.url = value;
      index += 1;
    } else if (flag === "--out") {
      args.out = value;
      index += 1;
    } else if (flag === "--help" || flag === "-h") {
      console.log(
        "usage: node scripts/lighthouse-audit.mjs [--port 3200] [--url http://host:port] [--out file.json]",
      );
      process.exit(0);
    }
  }
  if (!Number.isFinite(args.port) || args.port <= 0) {
    throw new Error(`--port must be a positive number, got "${args.port}"`);
  }
  args.url ??= `http://localhost:${args.port}`;
  args.out ??= path.join(REPO_ROOT, "docs", "qa", "lighthouse-summary.json");
  return args;
}

/* --------------------------------------------------------------- environment */

/**
 * Fail loudly and immediately if nothing is serving. This script must NEVER start or build a
 * server — the running one is shared with other agents and with the Playwright suite.
 */
async function assertServerIsUp(baseUrl) {
  for (const route of ROUTES) {
    const target = new URL(route, baseUrl).toString();
    let response;
    try {
      response = await fetch(target, { redirect: "follow" });
    } catch (cause) {
      throw new Error(
        `No server answered ${target}. Start the production server yourself (this script will ` +
          `not build or launch one) and re-run.\n  ${cause instanceof Error ? cause.message : cause}`,
      );
    }
    if (!response.ok) {
      throw new Error(`${target} answered ${response.status}; expected 200 before auditing.`);
    }
    await response.arrayBuffer();
  }
}

function describeMachine(chromeVersion) {
  const cores = cpus();
  return {
    host: hostname(),
    platform: `${platform()} ${release()}`,
    arch: arch(),
    cpu: cores[0]?.model ?? "unknown",
    logicalCores: cores.length,
    totalMemoryGb: Math.round((totalmem() / 1024 ** 3) * 10) / 10,
    chrome: chromeVersion,
    node: process.version,
  };
}

function chromeVersionOf(chromePath) {
  try {
    return execFileSync(chromePath, ["--version"], { encoding: "utf8" }).trim();
  } catch {
    return "unknown";
  }
}

/** Cap on how many failing nodes are copied into the JSON summary, so it stays readable. */
const MAX_REPORTED_NODES = 12;

/**
 * The audits that genuinely failed inside the named categories. Lighthouse marks audits it
 * could not run as `notApplicable`/`manual`/`informative`; those carry a `null` score and are
 * not failures, so they are filtered out rather than reported as problems.
 */
function failedAuditsIn(lhr, categoryIds) {
  const failures = [];
  const seen = new Set();
  for (const categoryId of categoryIds) {
    for (const ref of lhr.categories[categoryId]?.auditRefs ?? []) {
      const audit = lhr.audits[ref.id];
      if (!audit || typeof audit.score !== "number" || audit.score >= 1) continue;
      if (seen.has(ref.id)) continue;
      seen.add(ref.id);
      failures.push({
        category: categoryId,
        id: ref.id,
        title: audit.title,
        score: audit.score,
        failingNodes: audit.details?.items?.length ?? 0,
      });
    }
  }
  return failures;
}

/* ------------------------------------------------------------------- running */

/**
 * One Lighthouse run. `preset` selects the form factor: the default config is mobile
 * (moto-G-class emulation + slow 4G), `desktop-config.js` is Lighthouse's own desktop preset.
 */
async function audit({ baseUrl, route, preset, chromePort }) {
  const url = new URL(route, baseUrl).toString();
  const config = preset === "desktop" ? desktopConfig : undefined;
  const flags = {
    port: chromePort,
    output: "json",
    logLevel: "error",
    onlyCategories: ["performance", "accessibility", "best-practices"],
    // The page animates a WebGL background forever, so the CPU never goes quiet. Lighthouse
    // waits out `maxWaitForLoad` and proceeds, which is correct here but slow; the explicit
    // value documents that the wait is expected rather than a hang.
    maxWaitForLoad: 45_000,
  };

  const result = await lighthouse(url, flags, config);
  if (!result?.lhr) throw new Error(`Lighthouse returned no report for ${url} (${preset})`);
  const { lhr } = result;

  const score = (id) => {
    const value = lhr.categories[id]?.score;
    return typeof value === "number" ? Math.round(value * 100) : null;
  };
  const clsAudit = lhr.audits["cumulative-layout-shift"];

  return {
    route,
    url,
    preset,
    scores: {
      performance: score("performance"),
      accessibility: score("accessibility"),
      "best-practices": score("best-practices"),
    },
    cls: typeof clsAudit?.numericValue === "number" ? clsAudit.numericValue : null,
    metrics: {
      firstContentfulPaintMs: lhr.audits["first-contentful-paint"]?.numericValue ?? null,
      largestContentfulPaintMs: lhr.audits["largest-contentful-paint"]?.numericValue ?? null,
      totalBlockingTimeMs: lhr.audits["total-blocking-time"]?.numericValue ?? null,
      speedIndexMs: lhr.audits["speed-index"]?.numericValue ?? null,
    },
    /**
     * Proof of the caveat rather than a claim about it: whether axe actually evaluated
     * `color-contrast` on this page, how many nodes it looked at, and — when it found
     * failures — which ones. `notApplicable`, or a pass over a handful of nodes, is exactly
     * the silent skip described above.
     *
     * The failing nodes are worth capturing verbatim: everything axe *can* see here is plain
     * DOM text over a CSS colour, so a failure listed below is a real WCAG AA violation
     * against brief §16, not the canvas blind spot. The two must never be confused.
     */
    colorContrastAudit: (() => {
      const contrast = lhr.audits["color-contrast"];
      if (!contrast) return { present: false };
      const items = contrast.details?.items ?? [];
      return {
        present: true,
        scoreDisplayMode: contrast.scoreDisplayMode,
        score: contrast.score,
        failingNodes: items.length,
        failures: items.slice(0, MAX_REPORTED_NODES).map((item) => ({
          selector: item.node?.selector ?? null,
          snippet: item.node?.snippet ?? null,
          explanation: item.node?.explanation ?? null,
        })),
      };
    })(),
    /**
     * Every audit that actually scored below 1 in the accessibility and best-practices
     * categories, so the notes can name what cost the points instead of quoting a bare
     * number. Informational-only audits (`notApplicable`, `manual`, `informative`) are
     * excluded — they are not failures.
     */
    failedAudits: failedAuditsIn(lhr, ["accessibility", "best-practices"]),
    /**
     * Why the performance number is what it is. Not gated and not an expectation — just the
     * two things anyone reading a missed mobile target asks next: what Chrome considered the
     * largest paint, and which opportunities Lighthouse costed.
     */
    performanceDiagnostics: {
      lcpElement:
        lhr.audits["largest-contentful-paint-element"]?.details?.items?.[0]?.items?.[0]?.node
          ?.selector ?? null,
      opportunities: Object.values(lhr.audits)
        .filter(
          (audit) =>
            audit?.details?.type === "opportunity" &&
            typeof audit.details.overallSavingsMs === "number" &&
            audit.details.overallSavingsMs >= 100,
        )
        .sort((a, b) => b.details.overallSavingsMs - a.details.overallSavingsMs)
        .slice(0, 5)
        .map((audit) => ({
          id: audit.id,
          title: audit.title,
          savingsMs: Math.round(audit.details.overallSavingsMs),
        })),
    },
    lighthouseVersion: lhr.lighthouseVersion,
    fetchTime: lhr.fetchTime,
    userAgent: lhr.environment?.hostUserAgent ?? null,
    throttling: lhr.configSettings?.throttlingMethod ?? null,
    formFactor: lhr.configSettings?.formFactor ?? null,
  };
}

/* ------------------------------------------------------------------- gating */

/** Every gated check for one run, as `{ target, threshold, measured, met }` rows. */
function checksFor(run) {
  const rows = [];
  for (const [key, rule] of Object.entries(THRESHOLDS)) {
    if (rule.appliesTo === "mobile" && run.preset !== "mobile") continue;
    const measured = key === "cls" ? run.cls : run.scores[key];
    const met =
      measured === null
        ? false
        : "min" in rule
          ? measured >= rule.min
          : measured < rule.max;
    rows.push({
      target: rule.label,
      threshold: "min" in rule ? `>= ${rule.min}` : `< ${rule.max}`,
      measured,
      met,
    });
  }
  return rows;
}

/** CSS-module class names carry a build hash; strip it so the printed selector stays readable. */
function shortSelector(selector) {
  if (!selector) return "?";
  return selector.replace(/-module__[A-Za-z0-9_]+__/g, ".");
}

/** Pull `contrast of 2.32 (foreground …, background …)` out of axe's explanation prose. */
function contrastRatioOf(explanation) {
  if (!explanation) return "";
  const ratio = /contrast of ([\d.]+)/.exec(explanation)?.[1];
  const foreground = /foreground color: (#[0-9a-fA-F]{3,8})/.exec(explanation)?.[1];
  const background = /background color: (#[0-9a-fA-F]{3,8})/.exec(explanation)?.[1];
  const expected = /Expected contrast ratio of ([\d.]+):1/.exec(explanation)?.[1];
  if (!ratio) return "";
  return `${ratio}:1 (need ${expected ?? "?"}:1, ${foreground ?? "?"} on ${background ?? "?"})`.padEnd(46);
}

const fmt = (value) =>
  value === null ? "n/a" : typeof value === "number" && !Number.isInteger(value)
    ? value.toFixed(4)
    : String(value);

function printRun(run, checks) {
  console.log(`\n  ${run.preset.toUpperCase().padEnd(7)} ${run.route}`);
  for (const check of checks) {
    const mark = check.met ? "PASS" : "FAIL";
    console.log(
      `    [${mark}] ${check.target.padEnd(22)} ${String(check.threshold).padEnd(8)} measured ${fmt(check.measured)}`,
    );
  }
  if (run.preset === "desktop" && run.scores.performance !== null) {
    console.log(
      `    [ -- ] ${"Desktop performance".padEnd(22)} ${"(ungated)".padEnd(8)} measured ${run.scores.performance}`,
    );
  }
  console.log(
    `    ....  FCP ${Math.round(run.metrics.firstContentfulPaintMs ?? 0)}ms · ` +
      `LCP ${Math.round(run.metrics.largestContentfulPaintMs ?? 0)}ms · ` +
      `TBT ${Math.round(run.metrics.totalBlockingTimeMs ?? 0)}ms · ` +
      `SI ${Math.round(run.metrics.speedIndexMs ?? 0)}ms`,
  );
  const diagnostics = run.performanceDiagnostics;
  if (checks.some((check) => !check.met) && diagnostics) {
    if (diagnostics.lcpElement) {
      console.log(`    ....  LCP element: ${shortSelector(diagnostics.lcpElement)}`);
    }
    for (const opportunity of diagnostics.opportunities) {
      console.log(`    ....  opportunity: ${opportunity.id} (~${opportunity.savingsMs}ms)`);
    }
  }
}

/* --------------------------------------------------------------------- main */

async function main() {
  const args = parseArgs(process.argv.slice(2));

  console.log("DROP — Lighthouse gate (brief §17)");
  console.log(`  target server : ${args.url}  (already running; this script starts nothing)`);
  await assertServerIsUp(args.url);

  const chrome = await chromeLauncher.launch({
    chromeFlags: [
      "--headless=new",
      "--disable-extensions",
      "--no-first-run",
      "--no-default-browser-check",
    ],
  });

  const machine = describeMachine(chromeVersionOf(chrome.process?.spawnfile ?? "google-chrome"));
  console.log(`  machine       : ${machine.cpu}, ${machine.logicalCores} cores, ${machine.totalMemoryGb} GB`);
  console.log(`  browser       : ${machine.chrome} (headless)`);

  const runs = [];
  try {
    for (const preset of ["mobile", "desktop"]) {
      for (const route of ROUTES) {
        process.stdout.write(`  auditing ${preset} ${route} … `);
        const run = await audit({ baseUrl: args.url, route, preset, chromePort: chrome.port });
        process.stdout.write("done\n");
        runs.push(run);
      }
    }
  } finally {
    await chrome.kill();
  }

  console.log("\nBrief §17 launch targets");
  const failures = [];
  const reported = runs.map((run) => {
    const checks = checksFor(run);
    printRun(run, checks);
    for (const check of checks) {
      if (!check.met) {
        failures.push(`${run.preset} ${run.route}: ${check.target} ${check.threshold} — measured ${fmt(check.measured)}`);
      }
    }
    return { ...run, checks };
  });

  console.log("\nAudits that cost points (accessibility / best practices)");
  let anyAuditFailure = false;
  for (const run of reported) {
    if (run.failedAudits.length === 0) continue;
    anyAuditFailure = true;
    console.log(`\n  ${run.preset.toUpperCase().padEnd(7)} ${run.route}`);
    for (const audit of run.failedAudits) {
      console.log(`    ${audit.category}/${audit.id} — ${audit.title} (${audit.failingNodes} node(s))`);
    }
    // Deduped: five identical footer links produce five identical rows otherwise.
    const seenSelectors = new Set();
    for (const failure of run.colorContrastAudit?.failures ?? []) {
      const selector = shortSelector(failure.selector);
      if (seenSelectors.has(selector)) continue;
      seenSelectors.add(selector);
      console.log(`      contrast ${contrastRatioOf(failure.explanation)}  ${selector}`);
    }
  }
  if (!anyAuditFailure) console.log("  none — every scored audit in both categories passed.");

  console.log("\nCAVEAT — read before quoting the accessibility score");
  console.log(`  ${CONTRAST_CAVEAT.replace(/(.{95}) /g, "$1\n  ")}`);
  for (const run of reported) {
    const contrast = run.colorContrastAudit;
    if (contrast?.present) {
      console.log(
        `  color-contrast on ${run.preset} ${run.route}: scoreDisplayMode=${contrast.scoreDisplayMode}, ` +
          `score=${contrast.score}, failingNodes=${contrast.failingNodes} — whatever this number ` +
          `says, text over the canvas is NOT among the nodes it can see.`,
      );
    }
  }

  console.log("\n[manual] boxes this run does NOT cover");
  for (const box of MANUAL_BOXES) console.log(`  - ${box}`);

  const summary = {
    generatedAt: new Date().toISOString(),
    targetServer: args.url,
    note: "Run against an already-running production server; this script never builds or starts one.",
    machine,
    thresholds: THRESHOLDS,
    contrastCaveat: CONTRAST_CAVEAT,
    manualBoxes: MANUAL_BOXES,
    runs: reported,
    failures,
    passed: failures.length === 0,
  };

  await mkdir(path.dirname(args.out), { recursive: true });
  await writeFile(args.out, `${JSON.stringify(summary, null, 2)}\n`, "utf8");
  console.log(`\nJSON summary → ${path.relative(REPO_ROOT, args.out)}`);

  if (failures.length > 0) {
    console.error(`\nFAILED — ${failures.length} threshold(s) missed:`);
    for (const failure of failures) console.error(`  - ${failure}`);
    process.exitCode = 1;
    return;
  }
  console.log("\nAll gated brief §17 thresholds met.");
}

main().catch((error) => {
  console.error(`\nlighthouse-audit failed: ${error instanceof Error ? error.stack : error}`);
  process.exitCode = 1;
});
