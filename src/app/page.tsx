import { getCurrentLens } from "@/content";
import { ImmersiveLensPage } from "@/components/shell";

/**
 * `/` renders the CONFIGURED current lens (brief §5), never a hardcoded one: swapping which
 * Weekly Lens the site opens on is a change to `currentLensSlug` in the content module, not to
 * this route. The lens arrives as a prop, exactly as it does on `/lens/[slug]` — the two routes
 * render the same template from the same data path.
 *
 * Metadata for this route comes from the root layout, which derives it from the same
 * `getCurrentLens()`.
 *
 * `await` is deliberate on a value the content module resolves synchronously today: it types
 * identically if that ever becomes asynchronous (same convention as `src/app/layout.tsx`).
 */
export default async function HomePage() {
  const lens = await getCurrentLens();

  // Keyed by slug so a different lens mounts a fresh scene-state machine rather than inheriting
  // the previous lens's indices.
  return <ImmersiveLensPage key={lens.slug} lens={lens} />;
}
