import type { CSSProperties, ReactNode } from "react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import {
  APERTURE_PULSE_MAX,
  APERTURE_PULSE_MIN,
  DropO,
  DropPrimaryLogo,
  DropSymbolRow,
  DropWordmark,
  type BrandVariant,
} from "@/components/brand";

/**
 * Brand geometry preview — a development harness, not a route of the site.
 *
 * Every mark at several module sizes, in both variants, plus the O's aperture swept across the
 * loader's whole range so the portal is checkable by eye rather than by argument. It exists to be
 * held against `handoff/01-brand/drop-final-wordmark-reference.png` and
 * `drop-final-storefront-logo.jpg`; the marks themselves are procedural geometry and no part of
 * this page loads either photograph.
 *
 * Styles are inline because this page is scaffolding: the brand components carry their own CSS
 * module, and a dev harness should not grow a stylesheet the production bundle has to reason
 * about.
 */

export const metadata: Metadata = {
  title: "Brand geometry",
  robots: { index: false, follow: false },
};

/** Module sizes: header-small through hero-large. */
const SIZES = [16, 24, 40, 72];

/**
 * The aperture range the loader drives (brief §7.1): the resting pulse, then the portal opening
 * past the tile. At 2.0 the ring has thinned; past ~3.3 the tile is gone entirely.
 */
const APERTURE_SWEEP = [APERTURE_PULSE_MIN, 1, APERTURE_PULSE_MAX, 2, 6];

const page: CSSProperties = {
  padding: "3rem var(--page-gutter)",
  display: "grid",
  gap: "3rem",
  fontFamily: "var(--font-latin)",
};

const panel = (variant: BrandVariant): CSSProperties => ({
  padding: "2.5rem",
  display: "grid",
  gap: "2.5rem",
  background: variant === "dark" ? "var(--drop-off-white)" : "var(--drop-black)",
  color: variant === "dark" ? "var(--drop-ink)" : "var(--drop-off-white)",
});

const label: CSSProperties = {
  font: "var(--label)/1 var(--font-latin)",
  letterSpacing: "0.18em",
  textTransform: "uppercase",
  opacity: 0.6,
  margin: 0,
};

const shelf: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "flex-end",
  gap: "2rem",
};

function Group({ name, children }: { name: string; children: ReactNode }) {
  return (
    <section style={{ display: "grid", gap: "0.9rem" }}>
      <p style={label}>{name}</p>
      <div style={shelf}>{children}</div>
    </section>
  );
}

function Specimen({ caption, children }: { caption: string; children: ReactNode }) {
  return (
    <figure style={{ margin: 0, display: "grid", gap: "0.5rem", justifyItems: "start" }}>
      {children}
      <figcaption style={{ ...label, opacity: 0.45 }}>{caption}</figcaption>
    </figure>
  );
}

function Variant({ variant }: { variant: BrandVariant }) {
  return (
    <div style={panel(variant)} lang="en" dir="ltr">
      <p style={{ ...label, opacity: 1 }}>
        {variant === "dark" ? "dark tiles on light ground" : "light tiles on dark ground"}
      </p>

      <Group name="wordmark">
        {SIZES.map((size) => (
          <Specimen key={size} caption={`module ${size}`}>
            <DropWordmark size={size} variant={variant} title="DROP" />
          </Specimen>
        ))}
      </Group>

      <Group name="primary logo">
        {SIZES.map((size) => (
          <Specimen key={size} caption={`module ${size}`}>
            <DropPrimaryLogo size={size} variant={variant} title="DROP" />
          </Specimen>
        ))}
      </Group>

      <Group name="symbol row">
        {SIZES.map((size) => (
          <Specimen key={size} caption={`module ${size}`}>
            <DropSymbolRow size={size} variant={variant} />
          </Specimen>
        ))}
      </Group>

      <Group name="O">
        {SIZES.map((size) => (
          <Specimen key={size} caption={`module ${size}`}>
            <DropO size={size} variant={variant} />
          </Specimen>
        ))}
      </Group>

      <Group name="O — aperture sweep, pulse through portal">
        {APERTURE_SWEEP.map((apertureScale) => (
          <Specimen key={apertureScale} caption={`aperture ${apertureScale}`}>
            <DropO size={96} variant={variant} apertureScale={apertureScale} />
          </Specimen>
        ))}
      </Group>
    </div>
  );
}

export default function BrandPreviewPage() {
  if (process.env.NODE_ENV === "production") notFound();

  return (
    <div style={page}>
      <header lang="en" dir="ltr">
        <h1 style={{ font: "var(--title-md)/1 var(--font-latin)", fontWeight: 800 }}>
          Brand geometry
        </h1>
        <p style={{ ...label, marginTop: "0.75rem" }}>
          development preview — hold against handoff/01-brand
        </p>
      </header>
      <Variant variant="dark" />
      <Variant variant="light" />
    </div>
  );
}
