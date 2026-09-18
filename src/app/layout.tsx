import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { getCurrentLens } from "@/content";

import "./globals.css";
import { fontVariables } from "./fonts";
import styles from "./layout.module.css";

/**
 * The brand name is fixed identity, not lens content — it does not change when
 * the current lens changes, and the content schema has no field for it. Every
 * value that *is* lens content (title, thesis) is read from the content module.
 */
const SITE_NAME = "DROP";

/**
 * Interface copy, not editorial content: the weekly lens schema carries no
 * accessibility strings. Persian, because Persian is the primary language.
 */
const SKIP_LINK_LABEL = "پرش به محتوای اصلی";

/**
 * Metadata is derived from the current lens, never hardcoded. `await` here is
 * deliberate: it types identically whether the content module resolves the
 * current lens synchronously or asynchronously.
 */
/**
 * What Safari paints its own chrome with.
 *
 * iOS tints the address bar and the toolbar from `theme-color`, and with none set it falls back
 * to something light — so on a phone the page ended at a white bar under a black composition,
 * with a hard seam across the bottom of every screen.
 *
 * Black rather than the `--drop-off-white` that `html, body` carry, because off-white is the
 * ground UNDER the scenes and the reader never sees it: every scene paints the brand's black over
 * it, top to bottom, and the footer ends on it too. The chrome should agree with what is on
 * screen, not with what is behind it.
 *
 * Declared as `viewport`, not inside `generateMetadata` — Next moved `themeColor` out of Metadata
 * and warns if it is returned from there (node_modules/next/dist/lib/metadata/resolve-metadata.js).
 */
export const viewport: Viewport = {
  themeColor: "#000000",
};

export async function generateMetadata(): Promise<Metadata> {
  const lens = await getCurrentLens();

  const lensTitle = lens.title.fa;
  const description = lens.thesis.fa;
  const documentTitle = `${lensTitle} — ${SITE_NAME}`;

  return {
    title: {
      default: documentTitle,
      template: `%s — ${SITE_NAME}`,
    },
    description,
    openGraph: {
      type: "website",
      locale: "fa_IR",
      siteName: SITE_NAME,
      title: documentTitle,
      description,
    },
  };
}

/**
 * Root document.
 *
 * Persian is the primary editorial language, so the document is `lang="fa"`
 * `dir="rtl"` (brief §16). The film scene's deliberate left/right editorial
 * layout is held by CSS grid further down the tree — never by flipping document
 * direction — so nothing here should be read as a layout-direction hack.
 *
 * Kept deliberately thin: no header (that belongs to the immersive shell), no
 * client boundary, no WebGL assumption. It renders meaningful text on the
 * server on its own.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fa" dir="rtl" className={fontVariables}>
      <body>
        <a className={styles.skipLink} href="#main">
          {SKIP_LINK_LABEL}
        </a>
        <main id="main" className={styles.main} tabIndex={-1}>
          {children}
        </main>
      </body>
    </html>
  );
}
