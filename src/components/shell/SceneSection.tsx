"use client";

/**
 * The generic scene stage every scene mounts into.
 *
 * One `<section>` per {@link SceneId}, sized from the scene's scroll budget and either pinned
 * (its child sticks for the whole budget, so the scene owns the viewport while scroll scrubs it)
 * or flowing (editorial reading, brief §7.9). The section element is what the scene-state
 * machine attaches its ScrollTrigger to — the section is a stage, never a state owner.
 *
 * ## DOM observable-state contract (BUILD-GUIDE seam 3)
 *
 * Logical state is reflected as attributes driven by reducer output, and Playwright asserts
 * those attributes and text only — never transforms, opacity, or computed styles:
 *
 * - `data-scene`   — which scene this is;
 * - `data-active`  — whether the reducer says this scene is the active one;
 * - `data-pinned`  — whether the scene holds the viewport;
 * - `aria-current` — the active scene within the set of ten.
 *
 * ## Overlay scenes
 *
 * A scene may opt into being REVEALED from behind the scene before it ({@link
 * SceneSectionProps.overlay}) rather than arriving after it. Its section is pulled up under its
 * predecessor by exactly one viewport, it paints BELOW the other sections instead of above them,
 * and its stage gives up the shared padding so the scene can paint its own edge-to-edge surface.
 * The geometry is CSS — sticky and a margin, the same class of thing as the pin above — so it
 * survives resize, a JavaScript-disabled render and reduced motion, and it is exactly reversible
 * without anything having to undo it. Which scenes opt in is config, in `scene-budgets.ts`.
 *
 * `hidden` / `inert` on inactive content is OPT-IN through {@link SceneSectionProps.hideInactiveContent},
 * and off by default on purpose: meaningful text must be server-rendered and readable with
 * JavaScript disabled (brief §17), and with no JS there is no reducer to declare a scene active.
 * Scenes that hide *within* themselves — the inactive film, the off-screen carousel slides —
 * turn it on for their own inner content.
 */

import type { CSSProperties, ReactNode, Ref } from "react";

import type { SceneId } from "@/lib/scene";

import { SCENE_UNDERLAP_VH } from "./scene-budgets";
import styles from "./SceneSection.module.css";

export type SceneSectionProps = {
  sceneId: SceneId;
  /** Section length in viewport heights, from `scene-budgets.ts`. */
  budgetVh: number;
  /** Whether the scene holds the viewport while its budget scrolls past. */
  pin: boolean;
  /**
   * Whether this scene is revealed from behind the scene before it: its section underlaps that
   * one by a viewport, it paints beneath the other sections, and its stage is unpadded so the
   * scene can run its own surface edge to edge. From `scene-budgets.ts`; see the note above.
   */
  overlay?: boolean;
  /** Reducer output: is this the active scene? */
  active: boolean;
  /** The section element the scene-state machine observes. */
  sectionRef?: Ref<HTMLElement>;
  /** Accessible name for the region. Omit for a decorative scene. */
  label?: string;
  /**
   * A scene that carries no content of its own — the pixel transitions are pure scroll-driven
   * background choreography (brief §7.5, §7.7) and have nothing to announce.
   */
  decorative?: boolean;
  /**
   * Apply `inert` + `aria-hidden` to this scene's content while it is not the active scene.
   * Off by default; see the note above.
   */
  hideInactiveContent?: boolean;
  children?: ReactNode;
};

/** Style carrying the scroll geometry into CSS. */
type SceneStyle = CSSProperties & {
  "--scene-budget": string;
  "--scene-underlap"?: string;
};

/**
 * Cancels the underlap when scripting is off, scoped to overlay sections only.
 *
 * With no JavaScript there is no reducer, so an overlay scene is served fully revealed (its own
 * module says how). A revealed surface UNDER the previous scene's last viewport would then have
 * that scene's content painting across it, which is a collision rather than a reveal — so with
 * scripting off the section simply goes back to following the one before it. Raw markup for the
 * same reason the loader's guard is: a real <style> child would be a live stylesheet the moment
 * React created it as a DOM node.
 */
const NOSCRIPT_DROP_UNDERLAP =
  '<style>[data-scene-overlay="true"]{margin-block-start:0!important}</style>';

export function SceneSection({
  sceneId,
  budgetVh,
  pin,
  overlay = false,
  active,
  sectionRef,
  label,
  decorative = false,
  hideInactiveContent = false,
  children,
}: SceneSectionProps) {
  const hideContent = hideInactiveContent && !active;
  const style: SceneStyle = {
    "--scene-budget": String(budgetVh),
    ...(overlay ? { "--scene-underlap": String(SCENE_UNDERLAP_VH) } : {}),
  };

  return (
    <section
      ref={sectionRef}
      id={`scene-${sceneId}`}
      className={`${styles.scene} ${pin ? styles.pinned : styles.flowing}${
        overlay ? ` ${styles.overlay}` : ""
      }`}
      style={style}
      data-scene={sceneId}
      data-active={active}
      data-pinned={pin}
      aria-current={active ? "true" : undefined}
      {...(overlay ? { "data-scene-overlay": "true" } : {})}
      {...(decorative ? { "aria-hidden": true } : label ? { "aria-label": label } : {})}
    >
      {overlay ? <noscript dangerouslySetInnerHTML={{ __html: NOSCRIPT_DROP_UNDERLAP }} /> : null}
      <div
        className={styles.viewport}
        data-scene-viewport={sceneId}
        {...(hideContent ? { inert: true, "aria-hidden": true } : {})}
      >
        {children}
      </div>
    </section>
  );
}
