"use client";

/**
 * The DROP material loader and its O portal (brief §7.1, ticket 05).
 *
 * The scene is a fixed off-white overlay above the page. The page itself stays mounted beneath
 * it the whole time — that is the brief's requirement, and it is what makes the ending possible:
 * when the O's aperture expands past the viewport it is not a curtain lifting, it is a hole
 * opening onto a page that was already there. No hard cut, no separate loading-screen fade.
 *
 * ## Four paths, one scene
 *
 * | path | when | what plays |
 * | --- | --- | --- |
 * | `material` / `full` | first hard visit, WebGL, full motion | the whole ~3.2s sequence |
 * | `material` / `short` | internal route navigation | the mask transition only, ~0.6s |
 * | `static` | `prefers-reduced-motion`, or no WebGL | static logo held, then an O-shaped crossfade |
 * | retired | after any of the above | nothing — the scene unmounts itself |
 *
 * "First hard visit" is tracked by a module-level flag rather than storage: a hard visit builds
 * a new document and resets it, a client-side route change does not. That is exactly the
 * distinction the brief draws, it survives every navigation within the tab, and it writes
 * nothing to the user's machine.
 *
 * ## Timing is a promise, not a hope
 *
 * The full sequence targets 3.2s *after critical assets are ready*, and the brief caps the whole
 * loader at 4s — "never trap the user waiting for noncritical media". Both are enforced here:
 * a cap timer runs from mount in every path and retires the scene on its own, and the material
 * sequence is handed the time actually left so it compresses rather than overruns. The cap timer
 * is a `setTimeout`, which keeps counting in a backgrounded tab where the animation clock does
 * not — so a user who tabs away mid-loader comes back to the page, not to a frozen logo.
 *
 * ## What this scene does not decide
 *
 * Nothing about page-level state. The reducer owns `sceneId`, `backgroundMode` and
 * `headerVariant` (which is `"hidden"` for `loader`, so no header renders here); this scene
 * reports one fact upward — the portal finished — through {@link LoaderSceneProps.onComplete},
 * where the shell dispatches `{ type: "loaderComplete" }`. Retiring itself afterwards is local
 * presentation lifecycle, and it is idempotent with the shell unmounting the scene from reducer
 * output.
 */

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";

import { DropWordmark, brandGeometry } from "@/components/brand";
import { gsap } from "@/lib/motion/gsap";
import { prefersReducedMotion } from "@/lib/motion/reduced-motion";
import { detectWebGLSupport } from "@/lib/performance/webgl-support";
import type { LoaderLogoSizing } from "@/components/webgl/LoaderMaterial";

import styles from "./LoaderScene.module.css";

/**
 * The material logo is loaded on the client only: it carries three.js and a procedural texture
 * bake, neither of which belongs in the server bundle or in the reduced-motion path.
 */
const DropLogoMaterial3D = dynamic(
  () => import("@/components/webgl/DropLogoMaterial3D").then((module) => module.DropLogoMaterial3D),
  { ssr: false },
);

/** Brief §7.1: total target for the full sequence, once critical assets are ready. */
export const LOADER_TARGET_SECONDS = 3.2;

/** Brief §7.1: hard cap. The loader must never hold the page longer than this. */
export const LOADER_CAP_SECONDS = 4;

/** Brief §7.1 reduced motion: "static logo for 500-700ms". */
const STATIC_HOLD_MS = 600;

/** …"then a simple O-shaped crossfade". */
const STATIC_CROSSFADE_MS = 420;

/** Longest we wait for fonts before starting anyway. Fonts are critical; nothing else is. */
const CRITICAL_ASSET_TIMEOUT_MS = 700;

/** Headroom between the material sequence finishing and the cap firing. */
const CAP_HEADROOM_SECONDS = 0.2;

/** Clearance past the furthest viewport corner for the static crossfade's mask. */
const STATIC_PORTAL_OVERSHOOT = 1.04;

/**
 * How large the wordmark sits in the viewport.
 *
 * One constant, two consumers: the static logo's CSS (through the custom properties below) and
 * the shader layout (through `resolveLoaderLayout`). Wide and narrow mirror the brief's §15
 * breakpoint, and both are expressed as fractions of the viewport rather than pixel sizes so the
 * mark scales with the field it sits in.
 */
export const LOADER_LOGO_SIZING: LoaderLogoSizing = Object.freeze({
  wide: Object.freeze({ widthFraction: 0.52, heightFraction: 0.22 }),
  narrow: Object.freeze({ widthFraction: 0.78, heightFraction: 0.16 }),
  /** Brief §15 puts mobile below 768px. */
  narrowBelowPx: 768,
});

/* The mark's proportions come from the brand geometry, never from a measured screenshot. */
const GEOMETRY = brandGeometry();
const WORDMARK = GEOMETRY.wordmark;
const O_TILE = WORDMARK.tiles.find((tile) => tile.glyph === "O");
/** Where the O's centre sits across the wordmark row, 0..1. */
const O_CENTRE_X_FRACTION = O_TILE ? (O_TILE.x + O_TILE.size / 2) / WORDMARK.width : 0.5;
/** The resting aperture radius as a fraction of the row's width. */
const O_RADIUS_FRACTION = GEOMETRY.oRestingInnerRadius / WORDMARK.width;
const WORDMARK_ASPECT = WORDMARK.width / WORDMARK.height;

/** Scoped to this scene, and inert whenever scripting is on. Not a global stylesheet. */
const NOSCRIPT_HIDE_LOADER = '<style>[data-loader-overlay]{display:none!important}</style>';

/**
 * Has the full loader already *played* in this document? Module scope on purpose — see the note
 * on "first hard visit" above. Set on completion rather than on mount, so a development
 * double-mount (React strict mode) still shows the full sequence.
 */
let fullLoaderPlayed = false;

/** Which presentation the scene resolved to. Reflected into the DOM for the page seam. */
type LoaderMode = "pending" | "material" | "static" | "retired";

export interface LoaderSceneProps {
  /**
   * The portal has completed and the page is revealed. The shell dispatches
   * `{ type: "loaderComplete" }` into the scene-state reducer from here.
   *
   * Called exactly once, whichever path ran — including when the hard cap fires.
   */
  onComplete?: () => void;
  /**
   * Reduced-motion preference from the reducer. Omit it and the scene reads the media query
   * directly, so the loader is correct even before the shell has wired its state through.
   */
  reducedMotion?: boolean;
}

/**
 * Resolve when the loader may begin: fonts loaded, or {@link CRITICAL_ASSET_TIMEOUT_MS} elapsed,
 * whichever comes first. Fonts are the only critical asset the entry has — everything else is
 * noncritical by the brief's own definition, and waiting on it is exactly what the cap forbids.
 */
function whenCriticalAssetsReady(): Promise<void> {
  const fonts = document.fonts;
  if (!fonts || typeof fonts.ready?.then !== "function") return Promise.resolve();
  return Promise.race([
    fonts.ready.then(() => undefined),
    new Promise<void>((resolve) => {
      window.setTimeout(resolve, CRITICAL_ASSET_TIMEOUT_MS);
    }),
  ]);
}

export function LoaderScene({ onComplete, reducedMotion }: LoaderSceneProps) {
  const [mode, setMode] = useState<LoaderMode>("pending");
  const [canvasReady, setCanvasReady] = useState(false);
  const [sequence, setSequence] = useState<"full" | "short">("full");
  const [budgetSeconds, setBudgetSeconds] = useState(LOADER_TARGET_SECONDS);

  const overlayRef = useRef<HTMLDivElement | null>(null);
  const logoRef = useRef<HTMLDivElement | null>(null);
  const completedRef = useRef(false);

  // Latest props, reachable from callbacks and from the mount-once decision below. Kept in sync
  // from an effect, never during render.
  const reducedMotionRef = useRef(reducedMotion);
  const onCompleteRef = useRef(onComplete);
  useEffect(() => {
    reducedMotionRef.current = reducedMotion;
    onCompleteRef.current = onComplete;
  }, [reducedMotion, onComplete]);

  const complete = useCallback(() => {
    if (completedRef.current) return;
    completedRef.current = true;
    fullLoaderPlayed = true;
    // Written here rather than from an effect: the shell unmounts this scene the moment
    // `onComplete` lands, so an effect for the retired state may never run.
    document.documentElement.dataset.dropLoader = "complete";
    setMode("retired");
    onCompleteRef.current?.();
  }, []);

  /**
   * Decide which path runs, and when it may start.
   *
   * Runs once, at mount: the loader is an entry animation, and a shell re-render must never
   * restart it. The environment reads (media query, WebGL probe) cannot happen during render —
   * the server does not know them and hydration has to match — so the scene paints its static
   * mark first and resolves the path immediately afterwards.
   */
  useEffect(() => {
    let cancelled = false;
    const startedAt = performance.now();
    const short = fullLoaderPlayed;
    const reduced = reducedMotionRef.current ?? prefersReducedMotion();
    // Probed here rather than inside the canvas: a failed `WebGLRenderer` construction is a
    // console error on some engines, and this scene promises none.
    const staticPath = reduced || !detectWebGLSupport().supported;

    // Nothing to wait for on the static path (the mark is vector geometry, not type) or on the
    // short mask transition (the page is already loaded).
    const ready = staticPath || short ? Promise.resolve() : whenCriticalAssetsReady();

    void ready.then(() => {
      if (cancelled) return;
      const elapsed = (performance.now() - startedAt) / 1000;
      setSequence(short ? "short" : "full");
      setBudgetSeconds(
        Math.max(
          0.4,
          Math.min(LOADER_TARGET_SECONDS, LOADER_CAP_SECONDS - elapsed - CAP_HEADROOM_SECONDS),
        ),
      );
      setMode(staticPath ? "static" : "material");
    });

    return () => {
      cancelled = true;
    };
  }, []);

  /** The hard cap. Runs in every path, from mount, whatever the animation clock is doing. */
  useEffect(() => {
    const timer = window.setTimeout(complete, LOADER_CAP_SECONDS * 1000);
    return () => window.clearTimeout(timer);
  }, [complete]);

  /** Reduced motion / no WebGL: hold the static mark, then open the O. */
  useEffect(() => {
    if (mode !== "static") return;
    const overlay = overlayRef.current;
    const logo = logoRef.current;
    if (!overlay || !logo) return;

    const box = logo.getBoundingClientRect();
    const centreX = box.left + box.width * O_CENTRE_X_FRACTION;
    const centreY = box.top + box.height / 2;
    const startRadius = box.width * O_RADIUS_FRACTION;
    const endRadius =
      Math.hypot(
        Math.max(centreX, window.innerWidth - centreX),
        Math.max(centreY, window.innerHeight - centreY),
      ) * STATIC_PORTAL_OVERSHOOT;

    const setRadius = (radius: number): void => {
      overlay.style.setProperty("--drop-loader-portal-r", `${radius}px`);
    };
    overlay.style.setProperty("--drop-loader-portal-x", `${centreX}px`);
    overlay.style.setProperty("--drop-loader-portal-y", `${centreY}px`);
    setRadius(startRadius);

    // GSAP, not a CSS transition: the global reduced-motion rule flattens CSS durations to
    // nothing, and this crossfade is the one motion the brief asks reduced motion to keep.
    const portal = { radius: startRadius };
    const tween = gsap.to(portal, {
      radius: endRadius,
      duration: STATIC_CROSSFADE_MS / 1000,
      delay: STATIC_HOLD_MS / 1000,
      ease: "power2.inOut",
      onUpdate: () => setRadius(portal.radius),
      onComplete: complete,
    });

    return () => {
      tween.kill();
    };
  }, [mode, complete]);

  /**
   * Reflect the loader's own lifecycle onto the document element. The scene unmounts when it
   * finishes, so the page seam needs somewhere durable to read "which path ran, and did it
   * finish" from — and the shell can gate its own entry choreography on the same attribute.
   */
  useEffect(() => {
    if (mode === "retired") return;
    const root = document.documentElement;
    root.dataset.dropLoader = "playing";
    if (mode === "material" || mode === "static") {
      root.dataset.dropLoaderMode = mode;
      root.dataset.dropLoaderSequence = mode === "material" ? sequence : "static";
    }
  }, [mode, sequence]);

  if (mode === "retired") return null;

  const sizingVariables = {
    "--drop-loader-logo-aspect": `${WORDMARK_ASPECT}`,
    "--drop-loader-logo-vw": `${LOADER_LOGO_SIZING.wide.widthFraction * 100}`,
    "--drop-loader-logo-vh": `${LOADER_LOGO_SIZING.wide.heightFraction * 100}`,
    "--drop-loader-logo-vw-narrow": `${LOADER_LOGO_SIZING.narrow.widthFraction * 100}`,
    "--drop-loader-logo-vh-narrow": `${LOADER_LOGO_SIZING.narrow.heightFraction * 100}`,
  } as CSSProperties;

  return (
    <div
      ref={overlayRef}
      className={styles.overlay}
      style={sizingVariables}
      data-loader-overlay="true"
      data-loader-mode={mode}
      data-loader-sequence={sequence}
      data-canvas-ready={canvasReady ? "true" : "false"}
      aria-hidden="true"
    >
      {/*
        With scripting off the loader can never finish, so it must never start: the page below is
        fully server-rendered and has to stay reachable. Written as raw markup because a real
        <style> child would be a live stylesheet the moment React created it as a DOM node.
      */}
      <noscript dangerouslySetInnerHTML={{ __html: NOSCRIPT_HIDE_LOADER }} />

      <div className={styles.stage}>
        <div ref={logoRef} className={styles.logo}>
          <DropWordmark variant="dark" />
        </div>
      </div>

      {mode === "material" ? (
        <DropLogoMaterial3D
          className={styles.canvas}
          logoSizing={LOADER_LOGO_SIZING}
          sequence={sequence}
          budgetSeconds={budgetSeconds}
          onReady={() => setCanvasReady(true)}
          onComplete={complete}
          onUnsupported={() => {
            setCanvasReady(false);
            setMode("static");
          }}
        />
      ) : null}
    </div>
  );
}

export default LoaderScene;
