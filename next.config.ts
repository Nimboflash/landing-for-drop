import type { NextConfig } from "next";

/**
 * Presentation / QA mode.
 *
 * `next dev` paints its devtools badge over the immersive scenes, which makes a screenshot or a
 * design review of the grid statement, the transitions or the footer misleading — the badge sits
 * in the composition. `next start` never shows it, so this is a development-only nuisance rather
 * than a shipping defect.
 *
 * Setting `DROP_PRESENTATION=1` hides the badge and NOTHING else: HMR, Fast Refresh and the error
 * overlay are separate paths in Next 16 and stay on, so this cannot quietly become "run the dev
 * server with the tooling off". Anything environment-shaped belongs on `DROP_ENV` instead, which
 * the media-rights guard already reads.
 *
 * `devIndicators: false` is the shape this Next accepts — verified against
 * node_modules/next/dist/server/config-shared.d.ts:1349 (`false | { position?: … }`), not from memory.
 */
const presentationMode = process.env.DROP_PRESENTATION === "1";

/**
 * Which hosts may pull dev assets — i.e. "can I open this on my phone".
 *
 * `next dev` serves everything under `/_next` only to `localhost` unless a host is listed here;
 * anything else gets a flat 403. Loaded from a phone on the same network that is not a warning,
 * it is the whole page failing quietly: measured against this app at `http://172.20.10.2:3000`,
 * fourteen chunks came back 403, so no WebGL context was created, the loader never completed and
 * the scroll lock it holds was never released. Reported as "it doesn't load, the animation never
 * happens and scrolling does nothing" — and all three are that one 403.
 *
 * The HTML itself is served fine, which is what makes it confusing: the page renders its static
 * no-JavaScript form and looks broken rather than blocked.
 *
 * Private ranges only, and only these three, because that is the whole of "a device on my own
 * network": Apple's personal-hotspot subnet, the usual home/office Wi-Fi range, and the wider
 * private block. No public address is listed, and none should be.
 *
 * Matching is per dot-separated segment, right to left, with `*` covering exactly one segment
 * (node_modules/next/dist/server/app-render/csrf-protection.js) — so these patterns match an IPv4
 * host, not only a DNS name. `localhost` and `**.localhost` are always allowed and need no entry.
 *
 * Development only. `next build` and `next start` never read it, so nothing here reaches
 * production, and the dev server must be restarted for a change to take effect.
 */
const LAN_DEV_ORIGINS = [
  /* Apple personal hotspot. */
  "172.20.10.*",
  /* Home and office Wi-Fi. */
  "192.168.*.*",
  /* The wider private block. */
  "10.*.*.*",
];

const nextConfig: NextConfig = {
  allowedDevOrigins: LAN_DEV_ORIGINS,
  ...(presentationMode ? { devIndicators: false as const } : {}),
};

export default nextConfig;
