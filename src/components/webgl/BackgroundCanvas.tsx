"use client";

/**
 * The one persistent WebGL background.
 *
 * Brief Section 12 ("Important architecture decision"): "Use one shared, fixed WebGL background
 * canvas where possible. Transition shader scenes by uniforms/state rather than creating multiple
 * simultaneous WebGL contexts. DOM content remains semantic and above the canvas. WebGL is
 * decorative and receives `aria-hidden='true'`."
 *
 * ## Where its state comes from
 *
 * Nowhere but its props. `mode`, `sceneProgress`, `transitionState` and `reducedMotion` are the
 * scene-state reducer's output (BUILD-GUIDE seam 2), handed down by the shell. This component owns
 * no scroll listener, computes no scene id, and derives no active index — if it did, the seam-2
 * tests would be describing a model the page does not actually render from.
 *
 * ## Why there is only ever one context
 *
 * Modes are separate GLSL programs on separate fullscreen planes inside the SAME renderer. A mode
 * change swaps which plane is mounted; a crossfade briefly mounts two and blends them with a
 * constant blend factor. At no point is a second `WebGLRenderer` — or a second canvas — created.
 * The loader (ticket 05) is the one sanctioned exception and lives on its own temporary overlay.
 *
 * ## Crossfades, and who owns a mode change
 *
 * Brief Section 14: "Pixel transitions own the change between modes." So `pixelA`/`pixelB` never
 * crossfade — entering or leaving them is a hard swap and the mosaic performs the reveal itself.
 * Every other mode change gets one brief fade. Reduced motion keeps the fade (Section 14: "static
 * backgrounds with brief crossfades") but stops the shader clock and switches the renderer to the
 * on-demand frameloop, so nothing animates on its own.
 *
 * ## Degrading
 *
 * A styled static ground — the active module's `fallbackCss()` — is painted underneath at all
 * times. If WebGL cannot be created the canvas is never mounted and that ground *is* the
 * background; if the context is lost mid-session the canvas fades out and reveals it, then fades
 * back in when the browser restores the context. There is no state in which the page is blank.
 *
 * ## Stacking contract for the shell
 *
 * This renders one `position: fixed` box at `z-index: 0`. Page content must come AFTER it and sit
 * in a positioned wrapper (`position: relative`, or an explicit `z-index: 1`) — non-positioned
 * content paints below a positioned `z-index: 0` sibling and would end up behind the background.
 * `z-index: -1` is deliberately not used: `globals.css` paints an opaque background on `body`,
 * which covers negatively-stacked children.
 */

import { Canvas, invalidate, useFrame, useThree } from "@react-three/fiber";
import {
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type RefObject,
} from "react";
import type { IUniform, ShaderMaterial } from "three";
import {
  AddEquation,
  ConstantAlphaFactor,
  CustomBlending,
  NoBlending,
  OneMinusConstantAlphaFactor,
} from "three";

import {
  DEFAULT_QUALITY_TIER,
  detectEnvironmentQualityTier,
  resolveDevicePixelRatio,
  resolveRenderSettings,
  type EffectiveRenderSettings,
  type QualityTier,
} from "@/lib/performance/quality-tier";
import {
  detectWebGLSupport,
  observeContextLoss,
  releaseWebGLContext,
} from "@/lib/performance/webgl-support";
import type { BackgroundMode, TransitionState } from "@/lib/scene";

import styles from "./BackgroundCanvas.module.css";
import {
  FULLSCREEN_QUAD_VERTEX_SHADER,
  type BackgroundFrame,
  type BackgroundShaderModule,
} from "./shader-contract";
import { backgroundShaderFor } from "./shader-registry";

/* ------------------------------------------------------------------ tuning */

/**
 * Length of a mode crossfade with full motion. Long enough to read as a dissolve rather than a cut,
 * short enough that scrubbing back and forth across a scene boundary never feels laggy. Reduced
 * motion uses the shorter fade the performance module already publishes.
 */
const MODE_CROSSFADE_SECONDS = 0.42;

/** Modes whose own mosaic performs the scene change; the canvas must not fade them (brief §14). */
const SELF_TRANSITIONING_MODES: readonly BackgroundMode[] = ["pixelA", "pixelB"];

/** Clamp per-frame time steps so a backgrounded tab does not jump the ambient clock on return. */
const MAX_FRAME_DELTA_SECONDS = 1 / 20;

function ownsItsOwnTransition(mode: BackgroundMode): boolean {
  return SELF_TRANSITIONING_MODES.includes(mode);
}

function canCrossfade(from: BackgroundMode, to: BackgroundMode): boolean {
  return !ownsItsOwnTransition(from) && !ownsItsOwnTransition(to);
}

/**
 * Client components still evaluate during server render, where `useLayoutEffect` warns. The alias
 * keeps the browser path synchronous (the shaders must see the same frame the DOM was laid out
 * for) without emitting that warning on the server.
 */
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

/* -------------------------------------------------------------------- types */

export type BackgroundCanvasProps = {
  /** Active background mode — reducer output, never computed here. */
  mode: BackgroundMode;
  /** Progress within the active scene, 0..1 — reducer output. */
  sceneProgress: number;
  /** Declarative transition descriptors — reducer output. */
  transitionState: TransitionState;
  /** Reduced-motion preference, as the reducer mirrors it. */
  reducedMotion: boolean;
};

/** The live values a frame is assembled from. Mutated in place; never re-created per frame. */
type LiveInput = {
  mode: BackgroundMode;
  sceneProgress: number;
  transitionState: TransitionState;
  reducedMotion: boolean;
  quality: EffectiveRenderSettings;
};

/** Which mode is on screen, and which one it is still fading out of. */
type Layers = {
  current: BackgroundMode;
  previous: BackgroundMode | null;
};

/* --------------------------------------------------------------- one plane */

type ModePlaneProps = {
  shader: BackgroundShaderModule;
  baseFrameRef: RefObject<BackgroundFrame | null>;
  /** Blend weight for the incoming layer; the outgoing layer ignores it. */
  fadeRef: RefObject<number>;
  /** The incoming (or only) layer blends over the outgoing one. */
  isIncoming: boolean;
};

/**
 * One background mode, drawn on a fullscreen clip-space quad.
 *
 * The plane is 2×2 units because `FULLSCREEN_QUAD_VERTEX_SHADER` writes `position.xy` straight to
 * clip space — no camera is involved, so no camera can desynchronise the modes.
 *
 * Disposal: R3F frees the geometry and material when this unmounts; the module's own `dispose` is
 * called for anything it allocated itself (textures, render targets).
 */
function ModePlane({
  shader,
  baseFrameRef,
  fadeRef,
  isIncoming,
}: ModePlaneProps): React.ReactElement {
  const uniforms = useMemo<Record<string, IUniform>>(() => shader.createUniforms(), [shader]);
  const materialRef = useRef<ShaderMaterial>(null);

  // Each layer sees a frame reporting ITS OWN mode: during a crossfade the outgoing module is still
  // rendering, and the contract says a module runs while `frame.mode` is its own.
  const frameRef = useRef<BackgroundFrame | null>(null);

  useEffect(() => {
    const material = materialRef.current;
    return () => {
      // Dispose the same object `update` wrote into — anything the module allocated lives on the
      // material's cloned uniforms, so freeing the orphaned copy would leak it.
      shader.dispose?.(material?.uniforms ?? uniforms);
    };
  }, [shader, uniforms]);

  useFrame(() => {
    const base = baseFrameRef.current;
    if (base === null) return;

    let frame = frameRef.current;
    if (frame === null) {
      frame = { ...base, mode: shader.mode };
      frameRef.current = frame;
    } else {
      frame.sceneProgress = base.sceneProgress;
      frame.transitionState = base.transitionState;
      frame.reducedMotion = base.reducedMotion;
      frame.quality = base.quality;
      frame.timeSeconds = base.timeSeconds;
      frame.resolution = base.resolution;
      frame.pointer = base.pointer;
    }

    // Write to the material's OWN uniforms, not the object we handed to `<shaderMaterial>`.
    // three.js clones uniforms when it builds the material (`cloneUniforms`), so the object from
    // `createUniforms()` is orphaned the moment the material exists: updating it would leave every
    // progress-driven uniform frozen at its initial value and each mode stuck on its first frame.
    // The clone carries the same keys, so modules see the shape they created.
    const material = materialRef.current;
    shader.update(material?.uniforms ?? uniforms, frame);

    if (material !== null && isIncoming) {
      material.blendAlpha = fadeRef.current;
    }
  });

  return (
    <mesh renderOrder={isIncoming ? 1 : 0} frustumCulled={false}>
      <planeGeometry args={[2, 2]} />
      <shaderMaterial
        ref={materialRef}
        vertexShader={shader.vertexShader ?? FULLSCREEN_QUAD_VERTEX_SHADER}
        fragmentShader={shader.fragmentShader}
        uniforms={uniforms}
        depthTest={false}
        depthWrite={false}
        toneMapped={false}
        /* The outgoing layer lays down opaque pixels; the incoming layer blends over them with a
           constant alpha, which is the crossfade. With no crossfade running the weight is 1, which
           reduces to a plain overwrite. */
        transparent={isIncoming}
        blending={isIncoming ? CustomBlending : NoBlending}
        blendEquation={AddEquation}
        blendSrc={ConstantAlphaFactor}
        blendDst={OneMinusConstantAlphaFactor}
        blendAlpha={1}
      />
    </mesh>
  );
}

/* ------------------------------------------------------------- scene graph */

type BackgroundSceneProps = {
  mode: BackgroundMode;
  crossfadeSeconds: number;
  inputRef: RefObject<LiveInput>;
  pointerRef: RefObject<[number, number]>;
  onContextLost: () => void;
  onContextRestored: () => void;
};

/**
 * Everything that lives inside the single renderer: frame assembly, layer bookkeeping, and the
 * context-loss wiring. Memoised on `mode` so scroll progress never re-renders the R3F tree —
 * progress reaches the shaders through `inputRef`, one mutation per frame.
 */
const BackgroundScene = memo(function BackgroundScene({
  mode,
  crossfadeSeconds,
  inputRef,
  pointerRef,
  onContextLost,
  onContextRestored,
}: BackgroundSceneProps): React.ReactElement {
  const gl = useThree((state) => state.gl);
  const size = useThree((state) => state.size);

  const [layers, setLayers] = useState<Layers>(() => ({ current: mode, previous: null }));

  // Derived state, adjusted during render rather than in an effect: React re-runs this component
  // immediately, before anything paints, so a mode change never shows one stale frame.
  if (layers.current !== mode) {
    const fades = crossfadeSeconds > 0 && canCrossfade(layers.current, mode);
    setLayers({ current: mode, previous: fades ? layers.current : null });
  }

  /** 0 → the outgoing layer is fully visible; 1 → the incoming layer has taken over. */
  const fadeRef = useRef(1);
  /** The layer `fadeRef` currently describes, so the frame loop can spot a swap without an effect. */
  const fadeOwnerRef = useRef<BackgroundMode>(mode);
  const timeRef = useRef(0);
  const resolutionRef = useRef<[number, number]>([size.width, size.height]);
  const baseFrameRef = useRef<BackgroundFrame | null>(null);

  // Context loss must reveal the styled ground instead of a dead canvas, and the observer has to be
  // torn down BEFORE the context is released on unmount, so teardown cannot masquerade as a loss.
  useEffect(() => {
    const stop = observeContextLoss(gl.domElement, {
      onLost: onContextLost,
      onRestored: onContextRestored,
    });
    return () => {
      stop();
      releaseWebGLContext(gl.getContext());
    };
  }, [gl, onContextLost, onContextRestored]);

  // Under the on-demand frameloop that reduced motion uses, a mode change has to ask for the frame
  // that shows it.
  useEffect(() => {
    invalidate();
  }, [mode]);

  // Negative priority runs this before every ModePlane's own callback — and negative priorities,
  // unlike positive ones, leave R3F's automatic render in charge.
  useFrame((_state, delta) => {
    const input = inputRef.current;

    timeRef.current += input.reducedMotion
      ? 0
      : Math.min(Math.max(delta, 0), MAX_FRAME_DELTA_SECONDS);

    resolutionRef.current[0] = size.width;
    resolutionRef.current[1] = size.height;

    let frame = baseFrameRef.current;
    if (frame === null) {
      frame = {
        mode: input.mode,
        sceneProgress: input.sceneProgress,
        transitionState: input.transitionState,
        reducedMotion: input.reducedMotion,
        quality: input.quality,
        timeSeconds: timeRef.current,
        resolution: resolutionRef.current,
        pointer: pointerRef.current,
      };
      baseFrameRef.current = frame;
    } else {
      frame.mode = input.mode;
      frame.sceneProgress = input.sceneProgress;
      frame.transitionState = input.transitionState;
      frame.reducedMotion = input.reducedMotion;
      frame.quality = input.quality;
      frame.timeSeconds = timeRef.current;
      frame.resolution = resolutionRef.current;
      frame.pointer = pointerRef.current;
    }

    // A new incoming layer starts at 0 when it is crossfading in, and at 1 when the mode change is
    // a hard swap (a pixel transition owning its own reveal).
    if (fadeOwnerRef.current !== layers.current) {
      fadeOwnerRef.current = layers.current;
      fadeRef.current = layers.previous === null ? 1 : 0;
    }

    if (layers.previous !== null) {
      const step = crossfadeSeconds > 0 ? delta / crossfadeSeconds : 1;
      fadeRef.current = Math.min(1, fadeRef.current + step);
      if (fadeRef.current >= 1) {
        setLayers((live) => (live.previous === null ? live : { ...live, previous: null }));
      }
      // Keeps the fade running under the on-demand frameloop.
      invalidate();
    }
  }, -1);

  return (
    <>
      {layers.previous !== null ? (
        <ModePlane
          key={layers.previous}
          shader={backgroundShaderFor(layers.previous)}
          baseFrameRef={baseFrameRef}
          fadeRef={fadeRef}
          isIncoming={false}
        />
      ) : null}
      <ModePlane
        key={layers.current}
        shader={backgroundShaderFor(layers.current)}
        baseFrameRef={baseFrameRef}
        fadeRef={fadeRef}
        isIncoming
      />
    </>
  );
});

/* ------------------------------------------------------------------- root */

type WebGLAvailability = "unknown" | "ready" | "unavailable";

/**
 * What the browser can actually do. Read through `useSyncExternalStore` rather than an effect for
 * the usual reason: probing needs a document, so the server render and the hydration pass must both
 * see {@link SERVER_ENVIRONMENT} or the markup would not match. React then swaps in the real
 * verdict on the client. (`reduced-motion.ts` reads its media query the same way.)
 */
type CanvasEnvironment = {
  availability: WebGLAvailability;
  tier: QualityTier;
};

const SERVER_ENVIRONMENT: CanvasEnvironment = Object.freeze({
  availability: "unknown",
  tier: DEFAULT_QUALITY_TIER,
});

let probedEnvironment: CanvasEnvironment | null = null;

/** Probes once per page. Both underlying detectors cache too, so this stays referentially stable. */
function readEnvironment(): CanvasEnvironment {
  if (probedEnvironment !== null) return probedEnvironment;

  const support = detectWebGLSupport();
  // "no-document" means "not knowable yet", not "unsupported" — and caching it under a runtime
  // shared between requests would poison every later browser answer.
  if (support.failureReason === "no-document") return SERVER_ENVIRONMENT;

  probedEnvironment = Object.freeze({
    availability: support.supported ? "ready" : "unavailable",
    tier: detectEnvironmentQualityTier(),
  });
  return probedEnvironment;
}

/** Capability never changes for the life of the page; context loss is tracked separately. */
const subscribeEnvironment = (): (() => void) => () => {};

const readServerEnvironment = (): CanvasEnvironment => SERVER_ENVIRONMENT;

export function BackgroundCanvas({
  mode,
  sceneProgress,
  transitionState,
  reducedMotion,
}: BackgroundCanvasProps): React.ReactElement {
  const { availability, tier } = useSyncExternalStore(
    subscribeEnvironment,
    readEnvironment,
    readServerEnvironment,
  );
  const [contextLost, setContextLost] = useState(false);

  const settings = useMemo(
    () => resolveRenderSettings({ tier, reducedMotion }),
    [tier, reducedMotion],
  );

  const pointerRef = useRef<[number, number]>([0, 0]);

  // Pointer parallax is a desktop-only enhancement: the field is fully alive without it, and on a
  // coarse pointer (or reduced motion, or the low tier) the listener is never attached at all.
  useEffect(() => {
    pointerRef.current[0] = 0;
    pointerRef.current[1] = 0;
    if (!settings.pointerResponse) return;
    if (typeof window === "undefined") return;
    if (typeof window.matchMedia === "function" && !window.matchMedia("(pointer: fine)").matches) {
      return;
    }

    const handleMove = (event: PointerEvent): void => {
      const width = window.innerWidth || 1;
      const height = window.innerHeight || 1;
      pointerRef.current[0] = (event.clientX / width) * 2 - 1;
      pointerRef.current[1] = -((event.clientY / height) * 2 - 1);
    };

    window.addEventListener("pointermove", handleMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", handleMove);
    };
  }, [settings.pointerResponse]);

  const activeShader = backgroundShaderFor(mode);

  const inputRef = useRef<LiveInput>({
    mode,
    sceneProgress,
    transitionState,
    reducedMotion,
    quality: settings,
  });

  // The bridge from React's output to the render loop. A layout effect, not a render-phase write:
  // it lands before paint, so the shaders and the DOM always describe the same scroll position.
  useIsomorphicLayoutEffect(() => {
    const input = inputRef.current;
    input.mode = mode;
    input.sceneProgress = sceneProgress;
    input.transitionState = transitionState;
    input.reducedMotion = reducedMotion;
    input.quality = settings;
    if (!settings.animateShaders) invalidate();
  }, [mode, sceneProgress, transitionState, reducedMotion, settings]);

  const handleContextLost = useCallback(() => {
    setContextLost(true);
  }, []);
  const handleContextRestored = useCallback(() => {
    setContextLost(false);
  }, []);

  const dpr = useMemo(
    () =>
      resolveDevicePixelRatio(tier, typeof window === "undefined" ? 1 : window.devicePixelRatio),
    [tier],
  );

  const crossfadeSeconds =
    settings.crossfadeSeconds > 0 ? settings.crossfadeSeconds : MODE_CROSSFADE_SECONDS;

  const canvasActive = availability === "ready";
  const showingFallback = !canvasActive || contextLost;

  const staticFallback = useMemo(() => activeShader.fallbackCss(), [activeShader]);
  const fallbackBackground = showingFallback
    ? activeShader.fallbackCss({ transitionState, sceneProgress })
    : staticFallback;

  return (
    <div
      className={styles.root}
      aria-hidden="true"
      data-background-canvas=""
      data-background-mode={mode}
      data-webgl={showingFallback ? "fallback" : "active"}
      data-quality-tier={tier}
      data-reduced-motion={reducedMotion ? "true" : "false"}
    >
      <div className={styles.fallback} style={{ background: fallbackBackground }} />
      {canvasActive ? (
        <Canvas
          className={`${styles.canvas}${contextLost ? ` ${styles.canvasHidden}` : ""}`}
          style={{ pointerEvents: "none" }}
          dpr={dpr}
          flat
          linear
          frameloop={settings.animateShaders ? "always" : "demand"}
          gl={{
            alpha: true,
            antialias: false,
            depth: false,
            stencil: false,
            powerPreference: "high-performance",
            preserveDrawingBuffer: false,
          }}
        >
          <BackgroundScene
            mode={mode}
            crossfadeSeconds={crossfadeSeconds}
            inputRef={inputRef}
            pointerRef={pointerRef}
            onContextLost={handleContextLost}
            onContextRestored={handleContextRestored}
          />
        </Canvas>
      ) : null}
    </div>
  );
}
