"use client";

/**
 * The dark-green grid statement (brief §7.4, ticket 08).
 *
 * One centered statement, from data, over the shared canvas in `greenGrid` mode. That is the
 * entire scene. The grid itself is the shader's — this component never draws a lattice — and the
 * brief's list of what may sit on top of it is a list of one: "Only one centered statement. No
 * form, button, email field, arrows, handwriting, social icons, imagery, footer, or floating UI."
 * The Zero University layout reference carries all of that furniture; the ticket excludes it
 * explicitly, so none of it is reproduced here. What transfers is the composition skeleton only:
 * quiet green grid, one line of type in the middle of the viewport.
 *
 * ## Two independent opacities, two different jobs
 *
 * | layer | driven by | what it is |
 * | --- | --- | --- |
 * | the runs, inside their masks | {@link GridStatementSceneProps.revealed} | the one-shot reveal |
 * | the statement block | {@link GridStatementSceneProps.progress} | the replacement fade |
 *
 * The reveal is a **one-shot**: the reducer latches `gridStatementRevealed` at the reveal point
 * and only clears it when scroll retreats before that point, so jitter can never re-fire the mask
 * animation, and a genuine reverse pass puts the runs back behind their masks for the next
 * forward pass. The fade is **scrubbed**: the brief puts it between roughly 20% and 55% of pixel
 * transition A's replacement progress (§7.5), so it is a pure function of `progress` and reverses
 * exactly by construction.
 *
 * ## The holding layer
 *
 * §7.5 can only be true — "the centered statement fades while the replacement reaches
 * approximately 20-55% progress" — if the statement is still on screen while the mosaic runs. The
 * scene stage cannot do that on its own: a pinned section releases its sticky child a full
 * viewport before the next scene's scroll window opens, so the statement would have scrolled away
 * before the first cell flipped. So while the statement is live — revealed, and not yet cleared
 * by the fade — it renders on a viewport-fixed holding layer whose padding repeats the stage's,
 * which puts it in the very same place. Both switches (in-flow → lifted at the reveal, lifted →
 * in-flow once cleared) happen at a moment where the type is at zero opacity, so neither is
 * visible; and `data-lifted` reports which state it is in.
 *
 * The cost is deliberate: the statement then HOLDS, unmoved, across the hand-over between the two
 * scroll windows before the mosaic starts — a held beat before the cut, the same device §7.7 uses
 * on the other side of the films. If that beat ever reads as too long, the lever is the
 * `gridStatement` budget in `scene-budgets.ts` (integrator-owned, brief §6: "tuned by feel"), not
 * a change here.
 *
 * ## This scene decides nothing
 *
 * No ScrollTrigger, no progress of its own, no index, no background mode — the scene-state
 * reducer already decided all of it (BUILD-GUIDE seam 2, one-way data flow). GSAP appears here
 * for presentation only: the line masks, tweened from the boolean the reducer hands down, inside
 * a context that is reverted on unmount so nothing is left ticking and no trigger accumulates.
 *
 * The brief's "Scene pins briefly" is the STAGE's pin (`scenePins("gridStatement")` in
 * `scene-budgets.ts`, realised as a sticky scene section): this component creates no pin, no
 * trigger and no scroll listener of its own.
 *
 * ## Observable state (BUILD-GUIDE seam 3)
 *
 * - `data-grid-statement` — the statement element;
 * - `data-revealed` — the reducer's one-shot, `"true"` / `"false"`;
 * - `data-statement-fade` — `"held"` / `"fading"` / `"cleared"`, the {@link StatementFadePhase};
 * - `data-replacement-percent` — the replacement progress this scene was handed, 0..100;
 * - `data-lifted` — whether the statement is on the holding layer;
 * - `data-statement-motion` — `"animated"` / `"static"`, the reduced-motion verdict.
 *
 * The fade attributes exist so the page seam can assert *when* the statement fades without
 * reading computed styles: a test drives scroll, reads the percent the scene reports, and checks
 * the phase against the brief's own 20-55% window in both directions.
 *
 * ## Reduced motion and no-JavaScript
 *
 * Reduced motion gets a static statement and no scrub: the runs are simply present (no mask
 * animation, no lift), and the block steps out once the replacement has passed the window rather
 * than fading through it. Nothing in CSS ever hides the text — the pre-reveal state is written by
 * GSAP after mount — so a JavaScript-disabled render shows the server-rendered statement exactly
 * as it will finally read, in the flow of its own scene, and both runs stay in the accessibility
 * tree throughout. Nothing here touches WebGL, so a failed context costs this scene nothing: the
 * canvas paints the grid as a CSS fallback and the type is unaffected.
 */

import { useEffect, useRef, type CSSProperties } from "react";

import type { LocalizedText } from "@/content";
import { gsap } from "@/lib/motion/gsap";

import styles from "./GridStatementScene.module.css";

/* ------------------------------------------------------------------ tuning */

/**
 * Brief §7.5: "The centered statement fades while the replacement reaches approximately 20-55%
 * progress." Published because the integrator and the page seam both need the window the DOM
 * phase is cut at — a test should still take these numbers from the brief, not from here.
 */
export const GRID_STATEMENT_FADE_WINDOW: Readonly<{ start: number; end: number }> = Object.freeze({
  start: 0.2,
  end: 0.55,
});

/** Reveal timing. Cinematic and weighted (brief §9), never a bouncy app spring. */
const REVEAL_DURATION_S = 0.9;
const REVEAL_STAGGER_S = 0.09;
/** Putting the runs back is quicker than the reveal — a retreat, not a second performance. */
const HIDE_DURATION_S = 0.42;
/** `power4.out` is GSAP's read of `--ease-cinematic` (cubic-bezier(0.22, 1, 0.36, 1)). */
const REVEAL_EASE = "power4.out";
const HIDE_EASE = "power2.in";

/**
 * How far below its mask a run waits, as a percentage of its own line box. Sized past the mask's
 * own descender padding AND past the amount tight display leading lets glyphs overflow that line
 * box, so a masked run never peeks over the edge at any of the clamped sizes.
 */
const MASKED_Y_PERCENT = 145;

/** How far the statement lifts as the mosaic replaces it, in small viewport heights. */
const FADE_LIFT_SVH = 2.2;

/** The runs' two resting states. Both are plain GSAP vars, applied by set or by tween. */
const LINE_REVEALED = { yPercent: 0, opacity: 1 } as const;
const LINE_MASKED = { yPercent: MASKED_Y_PERCENT, opacity: 0 } as const;

/** The masked/revealed runs, found by the attribute rather than by a class name. */
const LINE_SELECTOR = "[data-statement-line]";

/* ------------------------------------------------------------------- pure */

/** Where the statement stands relative to the brief's fade window. Reflected into the DOM. */
export type StatementFadePhase = "held" | "fading" | "cleared";

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

/** The phase for a replacement progress. Monotonic, so reverse scroll walks it back exactly. */
export function statementFadePhase(progress: number): StatementFadePhase {
  const value = clamp01(progress);
  if (value <= GRID_STATEMENT_FADE_WINDOW.start) return "held";
  if (value >= GRID_STATEMENT_FADE_WINDOW.end) return "cleared";
  return "fading";
}

/** 1 → 0 across the window, eased at both ends so the statement leaves without a visible edge. */
export function statementOpacity(progress: number): number {
  const { start, end } = GRID_STATEMENT_FADE_WINDOW;
  const value = clamp01(progress);
  if (value <= start) return 1;
  if (value >= end) return 0;
  const t = (value - start) / (end - start);
  // Smoothstep: zero slope at both ends of the window.
  return 1 - t * t * (3 - 2 * t);
}

/* -------------------------------------------------------------- component */

export interface GridStatementSceneProps {
  /** The lens's grid statement. Both languages are rendered; nothing is written into this file. */
  statement: LocalizedText;
  /**
   * The reducer's `transitionState.gridStatementRevealed` one-shot. True plays the mask reveal
   * once; a return to false (scroll retreated before the reveal point) re-arms it.
   */
  revealed: boolean;
  /**
   * Pixel transition A's **replacement progress**, 0..1: 0 while the grid still holds the
   * viewport, ramping to 1 as the mosaic finishes replacing it, and staying at 1 for every scene
   * after the replacement. The shell derives it from `transitionState.pixelA` and the active
   * scene's position in `SCENE_ORDER` — this scene never computes it.
   */
  progress: number;
  /** The reducer's reduced-motion flag: static statement, no scrub. */
  reducedMotion: boolean;
}

export function GridStatementScene({
  statement,
  revealed,
  progress,
  reducedMotion,
}: GridStatementSceneProps) {
  const rootRef = useRef<HTMLParagraphElement | null>(null);
  const contextRef = useRef<ReturnType<typeof gsap.context> | null>(null);
  /** Has a run state been applied yet? The first application is instant; later ones animate. */
  const appliedRef = useRef(false);

  /**
   * One GSAP context for the scene's whole lifetime. Declared before the state effect so it
   * exists by the time that effect first runs, and reverted on unmount — which kills every tween
   * created through it and undoes the inline styles they wrote (brief §9, §17).
   *
   * NOTE — why this is not `createMotionScope()` from `@/lib/motion/gsap`, which is the sanctioned
   * helper: it builds its context as `gsap.context(undefined, root)`, and GSAP reads a falsy first
   * argument as "give me the CURRENTLY ACTIVE context" (`context: (func, scope) => func ? new
   * Context(func, scope) : _context` in gsap-core.js). Outside a context that is `undefined`, so
   * the helper hands back a scope whose `run()` throws on the first client render. Passing a setup
   * function is the whole difference. `useSceneStateMachine` carries the same note and the same
   * shape; when that one-liner lands in the helper, both collapse back onto it.
   */
  useEffect(() => {
    const context = gsap.context(() => {}, rootRef.current ?? undefined);
    contextRef.current = context;
    return () => {
      context.revert();
      contextRef.current = null;
      appliedRef.current = false;
    };
  }, []);

  /**
   * The reveal, driven by the reducer's boolean and nothing else.
   *
   * The masked state is written here rather than in CSS on purpose: with scripting off there is
   * no reducer to declare anything revealed, and text the server rendered must not be waiting
   * behind a mask that will never open.
   */
  useEffect(() => {
    const context = contextRef.current;
    const root = rootRef.current;
    if (!context || !root) return;

    const lines = Array.from(root.querySelectorAll<HTMLElement>(LINE_SELECTOR));
    if (lines.length === 0) return;

    const instant = !appliedRef.current;
    appliedRef.current = true;

    context.add(() => {
      if (reducedMotion) {
        // Static statement: present, unmasked, never animated in or out.
        gsap.set(lines, LINE_REVEALED);
        return;
      }

      const target = revealed ? LINE_REVEALED : LINE_MASKED;
      if (instant) {
        gsap.set(lines, target);
        return;
      }

      gsap.to(lines, {
        ...target,
        duration: revealed ? REVEAL_DURATION_S : HIDE_DURATION_S,
        ease: revealed ? REVEAL_EASE : HIDE_EASE,
        stagger: revealed ? REVEAL_STAGGER_S : 0,
        overwrite: "auto",
      });
    });
  }, [revealed, reducedMotion]);

  const replacement = clamp01(progress);
  const phase = statementFadePhase(replacement);
  // Reduced motion steps out at the end of the window instead of scrubbing through it.
  const opacity = reducedMotion ? (phase === "cleared" ? 0 : 1) : statementOpacity(replacement);
  /**
   * On the holding layer exactly while the statement is live. Off before the reveal (there is
   * nothing to hold) and off again once the replacement has cleared it (nothing left to see), so
   * the fixed layer never outlives the moment it exists for.
   */
  const lifted = revealed && phase !== "cleared";

  const lift = reducedMotion ? "0px" : `${((opacity - 1) * FADE_LIFT_SVH).toFixed(3)}svh`;
  const style: StatementStyle = {
    "--drop-statement-opacity": opacity.toFixed(3),
    "--drop-statement-lift": lift,
  };

  return (
    <p
      ref={rootRef}
      className={styles.statement}
      style={style}
      dir="rtl"
      data-grid-statement
      data-revealed={revealed}
      data-statement-fade={phase}
      data-replacement-percent={Math.round(replacement * 100)}
      data-lifted={lifted}
      data-statement-motion={reducedMotion ? "static" : "animated"}
    >
      <span className={styles.line}>
        <span className={styles.persian} data-statement-line="fa">
          {statement.fa}
        </span>
      </span>
      {/*
        The Latin run of the same statement, when the lens carries one. `en` is optional in the
        schema, and an absent optional field must not leave a gap (brief §11) — nor may Persian
        copy be re-labelled `lang="en" dir="ltr"` to fill one, which would hand a screen reader
        the wrong language. A lens without an English line simply shows the Persian statement.
      */}
      {statement.en ? (
        <span className={styles.line}>
          <span className={styles.latin} data-statement-line="en" lang="en" dir="ltr">
            {statement.en}
          </span>
        </span>
      ) : null}
    </p>
  );
}

/** The two custom properties the stylesheet reads for the replacement fade. */
type StatementStyle = CSSProperties & {
  "--drop-statement-opacity": string;
  "--drop-statement-lift": string;
};

export default GridStatementScene;
