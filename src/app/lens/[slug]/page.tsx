import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { getLensBySlug, listLenses } from "@/content";
import { ImmersiveLensPage } from "@/components/shell";

/**
 * `/lens/[slug]` — the same immersive template as `/`, for any published lens (brief §2, §5).
 * Every lens keeps a permanent, independently shareable URL.
 *
 * Next 16: `params` is a PROMISE and must be awaited, in the page and in `generateMetadata`
 * alike.
 */

type LensRouteProps = {
  params: Promise<{ slug: string }>;
};

/**
 * One static route per published lens. The list comes from the content module — adding a lens is
 * a data change, and nothing here enumerates slugs.
 */
export function generateStaticParams(): Array<{ slug: string }> {
  return listLenses().map((lens) => ({ slug: lens.slug }));
}

/**
 * Metadata from the lens itself. The root layout supplies the `… — DROP` title template and the
 * site-level Open Graph defaults; this only fills in what is lens-specific.
 *
 * An unknown slug returns empty metadata rather than throwing: the page below is what turns the
 * request into a 404, and metadata generation must not pre-empt it.
 */
export async function generateMetadata({ params }: LensRouteProps): Promise<Metadata> {
  const { slug } = await params;
  const lens = getLensBySlug(slug);
  if (!lens) return {};

  const title = lens.title.fa;
  const description = lens.thesis.fa;

  return {
    title,
    description,
    openGraph: {
      type: "article",
      locale: "fa_IR",
      title,
      description,
    },
  };
}

export default async function LensPage({ params }: LensRouteProps) {
  const { slug } = await params;
  const lens = getLensBySlug(slug);

  // Unknown slug: a real 404, not an empty lens page.
  if (!lens) notFound();

  return <ImmersiveLensPage key={lens.slug} lens={lens} />;
}
