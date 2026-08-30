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

const nextConfig: NextConfig = {
  ...(presentationMode ? { devIndicators: false as const } : {}),
};

export default nextConfig;
