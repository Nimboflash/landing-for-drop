import type { Metadata } from "next";
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
