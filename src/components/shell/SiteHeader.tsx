"use client";

/**
 * The persistent header (brief §8).
 *
 * Everything this component does is a rule from that section:
 *
 * - a small final DROP logo fixed at the TOP-LEFT from the hero onward;
 * - **nothing at the top-right in V1** — no nav group, no language toggle, no waitlist or demo
 *   button. The footer reference image contains a "Schedule demo" pill; that is exactly what the
 *   brief forbids, and the right-hand slot below is deliberately empty markup, not a container
 *   waiting to be filled;
 * - the mark's contrast follows the scene, never the other way round: the variant arrives as
 *   `state.transitionState.headerVariant` from the scene-state reducer, which also hides the
 *   header entirely for the loader;
 * - it "must not intercept scroll or cover primary content on mobile": the header is
 *   `pointer-events: none` and only as large as the mark.
 *
 * Top-left is PHYSICAL left. The document is `dir="rtl"` (Persian first), so this deliberately
 * uses `left` rather than `inset-inline-start` — the logo's corner is a brand constant, not a
 * direction-dependent layout.
 */

import { DropWordmark } from "@/components/brand";
import type { TransitionState } from "@/lib/scene";

import styles from "./SiteHeader.module.css";

/**
 * Brand identity, not lens content: the wordmark's accessible name does not change when the
 * current lens changes, and the content schema has no field for it (same reasoning as
 * `SITE_NAME` in `src/app/layout.tsx`).
 */
const BRAND_NAME = "DROP";

export type SiteHeaderProps = {
  /** Reducer output. `"hidden"` is the loader — brief §8: "Loader: no header." */
  variant: TransitionState["headerVariant"];
};

export function SiteHeader({ variant }: SiteHeaderProps) {
  const hidden = variant === "hidden";

  return (
    <header
      className={styles.header}
      data-header-variant={variant}
      data-hidden={hidden}
      {...(hidden ? { inert: true, "aria-hidden": true } : {})}
    >
      <div className={styles.mark} lang="en" dir="ltr">
        <DropWordmark
          className={styles.wordmark}
          variant={hidden ? "dark" : variant}
          title={BRAND_NAME}
        />
      </div>
      {/* Top-right stays empty in V1 (brief §8). Nothing goes here without approval. */}
    </header>
  );
}
