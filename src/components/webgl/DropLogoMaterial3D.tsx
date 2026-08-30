"use client";

/**
 * `DropLogoMaterial3D` — the loader's temporary overlay canvas and its choreography (brief §7.1).
 *
 * This is the one component in the project allowed to own a WebGL context that is not the shared
 * background canvas (ticket 04's contract note): the brief requires the DOM page to stay mounted
 * *beneath* the loader, so the loader must draw above it. The bargain is that the context is
 * temporary — when the portal completes this component unmounts and every geometry, material,
 * texture and context it created is released, leaving exactly one persistent context behind.
 *
 * ## Why plain three.js rather than R3F
 *
 * The brief names React Three Fiber as *preferred*, not required, and R3F brings its own
 * `requestAnimationFrame` loop. The project's standing rule is one animation clock — Lenis joins
 * GSAP's ticker rather than starting a second one — and the loader is pure choreography, so it
 * hangs off that same ticker. Everything R3F would have given us here (a canvas, a quad, a
 * material) is four lines of three.js; a competing RAF loop would not have been.
 *
 * ## The sequence
 *
 * One GSAP timeline drives a plain object of scalars; the render callback reads that object.
 * Timeline, not hand-rolled easing, because the whole sequence has to be compressible: the brief
 * caps the loader at 4s, so a slow first paint shortens the choreography via `timeScale` instead
 * of overrunning it. See {@link DropLogoMaterial3DProps.budgetSeconds}.
 *
 * ## One canvas per mount, created here
 *
 * The canvas element is built inside the effect rather than rendered by React, and removed on
 * teardown. Releasing a context is deliberately destructive — `WEBGL_lose_context` poisons the
 * element it was created from, and dispatches `webglcontextlost` asynchronously — so a canvas
 * that React kept across a remount would hand the *next* renderer a dead context and deliver the
 * old teardown's loss event to the new listener. Owning the element makes disposal total: the
 * node goes with the context.
 *
 * The aperture is never tweened towards an absolute target. The pulse rides between
 * `APERTURE_PULSE_MIN` and `APERTURE_PULSE_MAX`, a separate `expand` scalar runs 0 -> 1, and the
 * aperture is resolved against the *current* layout each frame — so a resize or an orientation
 * change mid-portal cannot leave the void short of the corner it has to clear.
 */

import { useEffect, useRef } from "react";
import {
  Mesh,
  NoBlending,
  OrthographicCamera,
  PlaneGeometry,
  Scene,
  ShaderMaterial,
  Vector2,
  WebGLRenderer,
} from "three";

import { APERTURE_PULSE_MAX, APERTURE_PULSE_MIN } from "@/components/brand";
import { gsap } from "@/lib/motion/gsap";
import {
  QUALITY_TIER_SETTINGS,
  detectEnvironmentQualityTier,
  resolveDevicePixelRatio,
  resolveRenderSettings,
} from "@/lib/performance/quality-tier";
import { observeContextLoss, releaseWebGLContext } from "@/lib/performance/webgl-support";
import {
  LOADER_FRAGMENT_SHADER,
  LOADER_VERTEX_SHADER,
  createLoaderMask,
  createLoaderUniforms,
  resolveLoaderLayout,
  updateLoaderUniforms,
  type LoaderLogoSizing,
  type LoaderMask,
} from "./LoaderMaterial";

/** Full entry sequence, in seconds. Brief §7.1 target: 3.2s once critical assets are ready. */
export const LOADER_FULL_SEQUENCE_SECONDS = 3.2;

/** Internal route navigation replays the mask, not the loader (brief §7.1). */
export const LOADER_SHORT_SEQUENCE_SECONDS = 0.56;

/** How much of the material's life the short mask transition keeps. */
const SHORT_SEQUENCE_LIFE = 0.75;

export type LoaderSequence = "full" | "short";

export interface DropLogoMaterial3DProps {
  /**
   * How large the wordmark sits in the viewport. Comes from the scene so the static fallback
   * logo's CSS and this material read the same numbers.
   */
  logoSizing: LoaderLogoSizing;
  /** `full` on a first hard visit; `short` for internal route navigation. */
  sequence?: LoaderSequence;
  /**
   * Seconds the sequence may take. When shorter than the sequence's natural length the timeline
   * is compressed rather than truncated, so the portal still opens smoothly — the brief's hard
   * cap must never become a hard cut.
   */
  budgetSeconds?: number;
  /** The portal has cleared the viewport. The loader may now unmount. */
  onComplete: () => void;
  /** First frame is on screen; the static fallback logo can cross-fade out. */
  onReady?: () => void;
  /** No usable context (creation failed, or it was lost mid-sequence). Fall back to the static path. */
  onUnsupported?: () => void;
  className?: string;
}

/** The scalars the timeline animates. Read once per frame; never allocated per frame. */
type Drive = {
  materialize: number;
  settle: number;
  pulse: number;
  expand: number;
  portal: number;
  life: number;
};

type Timeline = ReturnType<typeof gsap.timeline>;

function buildTimeline(drive: Drive, sequence: LoaderSequence, onComplete: () => void): Timeline {
  const timeline = gsap.timeline({ paused: true, onComplete });

  if (sequence === "short") {
    drive.materialize = 1;
    drive.settle = 1;
    drive.life = SHORT_SEQUENCE_LIFE;
    timeline
      .to(drive, { portal: 1, duration: 0.12, ease: "none" }, 0.02)
      .to(drive, { expand: 1, duration: 0.5, ease: "power2.inOut" }, 0.06);
    return timeline;
  }

  timeline
    // 1. materialise out of near-black shadow
    .to(drive, { materialize: 1, duration: 0.95, ease: "power2.out" }, 0)
    // 2. surface noise and speculars begin travelling across all four modules
    .to(drive, { life: 1, duration: 1.05, ease: "power1.inOut" }, 0.3)
    // 3. the O aperture pulses about its resting inner radius
    .to(drive, { pulse: APERTURE_PULSE_MAX, duration: 0.42, ease: "sine.inOut" }, 1.02)
    .to(drive, { pulse: APERTURE_PULSE_MIN, duration: 0.48, ease: "sine.inOut" }, 1.44)
    .to(drive, { pulse: APERTURE_PULSE_MAX, duration: 0.46, ease: "sine.inOut" }, 1.92)
    .to(drive, { pulse: APERTURE_PULSE_MIN, duration: 0.32, ease: "sine.inOut" }, 2.38)
    // 4. the pulse becomes the focus while D/R/P settle
    .to(drive, { settle: 1, duration: 0.66, ease: "power2.inOut" }, 1.86)
    // 5-6. the void turns into a real hole, then expands beyond the viewport
    .to(drive, { portal: 1, duration: 0.16, ease: "none" }, 2.6)
    .to(drive, { expand: 1, duration: 0.6, ease: "power2.inOut" }, 2.6);

  return timeline;
}

export function DropLogoMaterial3D({
  logoSizing,
  sequence = "full",
  budgetSeconds,
  onComplete,
  onReady,
  onUnsupported,
  className,
}: DropLogoMaterial3DProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);

  // Callbacks are read through refs so a parent re-render never tears down the GL context.
  // Synced from an effect, never during render.
  const onCompleteRef = useRef(onComplete);
  const onReadyRef = useRef(onReady);
  const onUnsupportedRef = useRef(onUnsupported);
  useEffect(() => {
    onCompleteRef.current = onComplete;
    onReadyRef.current = onReady;
    onUnsupportedRef.current = onUnsupported;
  }, [onComplete, onReady, onUnsupported]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const canvas = document.createElement("canvas");
    canvas.setAttribute("aria-hidden", "true");
    host.appendChild(canvas);

    let disposed = false;
    let mask: LoaderMask | null = null;
    let renderer: WebGLRenderer | null = null;
    let geometry: PlaneGeometry | null = null;
    let material: ShaderMaterial | null = null;
    let scene: Scene | null = null;
    let timeline: Timeline | null = null;
    let tick: ((time: number) => void) | null = null;
    let stopContextWatch: () => void = () => {};
    let resizeObserver: ResizeObserver | null = null;

    const teardown = (): void => {
      if (disposed) return;
      disposed = true;
      if (tick) gsap.ticker.remove(tick);
      timeline?.kill();
      resizeObserver?.disconnect();
      // Detach before releasing: losing the context on purpose fires the same event.
      stopContextWatch();
      scene?.clear();
      geometry?.dispose();
      material?.dispose();
      mask?.dispose();
      if (renderer) {
        const gl = renderer.getContext();
        // dispose() first: it removes three's own context-loss listeners, so deliberately
        // losing the context below stays silent.
        renderer.dispose();
        releaseWebGLContext(gl);
      }
      renderer = null;
      canvas.remove();
    };

    const tier = detectEnvironmentQualityTier();
    const settings = resolveRenderSettings({ tier, reducedMotion: false });

    try {
      mask = createLoaderMask({
        textureSizeCap: QUALITY_TIER_SETTINGS[tier].shaderDetail.textureSizeCap,
      });
      if (!mask) {
        onUnsupportedRef.current?.();
        return teardown;
      }

      renderer = new WebGLRenderer({
        canvas,
        alpha: true,
        antialias: false,
        depth: false,
        stencil: false,
        // The overlay is a mask: straight alpha, so the compositor reads our hole as a hole.
        premultipliedAlpha: false,
        powerPreference: "high-performance",
      });
    } catch {
      // Context creation failed. The static logo + crossfade is a required fallback anyway.
      onUnsupportedRef.current?.();
      return teardown;
    }

    renderer.setClearColor(0x000000, 0);
    // A full-screen procedural material is the heaviest thing this page draws, so the loader
    // takes the low end of its tier's sanctioned DPR band.
    const devicePixelRatio =
      typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;
    renderer.setPixelRatio(
      Math.min(resolveDevicePixelRatio(tier, devicePixelRatio), settings.dprCapRange[0]),
    );

    const loaderMask = mask;
    const uniforms = createLoaderUniforms(loaderMask);
    geometry = new PlaneGeometry(2, 2);
    material = new ShaderMaterial({
      uniforms,
      vertexShader: LOADER_VERTEX_SHADER,
      fragmentShader: LOADER_FRAGMENT_SHADER,
      // The fragment output IS the overlay: no blending, no depth, nothing behind it in-scene.
      blending: NoBlending,
      depthTest: false,
      depthWrite: false,
      transparent: true,
    });
    scene = new Scene();
    scene.add(new Mesh(geometry, material));
    const camera = new OrthographicCamera(-1, 1, 1, -1, 0, 1);

    const drive: Drive = {
      materialize: 0,
      settle: 0,
      pulse: 1,
      expand: 0,
      portal: 0,
      life: 0,
    };

    let viewportWidth = 1;
    let viewportHeight = 1;

    const measure = (): void => {
      const rect = host.getBoundingClientRect();
      viewportWidth = Math.max(1, Math.round(rect.width));
      viewportHeight = Math.max(1, Math.round(rect.height));
      renderer?.setSize(viewportWidth, viewportHeight, false);
    };
    measure();

    let ready = false;
    const drawingBuffer = new Vector2();
    const render = (time: number): void => {
      if (disposed || !renderer || !scene) return;
      const layout = resolveLoaderLayout(loaderMask, logoSizing, viewportWidth, viewportHeight);
      renderer.getDrawingBufferSize(drawingBuffer);
      updateLoaderUniforms(uniforms, {
        timeSeconds: time,
        resolution: [drawingBuffer.x, drawingBuffer.y],
        layout,
        edgeSoftness: loaderMask.edgeSoftness,
        materialize: drive.materialize,
        settle: drive.settle,
        // Resolved against the live layout, so a resize mid-portal still clears the corner.
        apertureScale: drive.pulse + (layout.portalScale - drive.pulse) * drive.expand,
        portal: drive.portal,
        fieldFade: 1,
        life: drive.life,
        settings,
      });
      renderer.render(scene, camera);
      if (!ready) {
        ready = true;
        onReadyRef.current?.();
      }
    };
    tick = render;

    timeline = buildTimeline(drive, sequence, () => {
      onCompleteRef.current();
    });

    const natural = timeline.duration();
    if (budgetSeconds !== undefined && budgetSeconds > 0 && budgetSeconds < natural) {
      timeline.timeScale(natural / budgetSeconds);
    }

    stopContextWatch = observeContextLoss(canvas, {
      onLost: () => {
        onUnsupportedRef.current?.();
      },
    });

    resizeObserver = new ResizeObserver(() => {
      measure();
    });
    resizeObserver.observe(host);

    // First frame before the timeline starts: the field is already off-white, so the handover
    // from the server-rendered static logo has something to cross-fade into.
    render(0);
    gsap.ticker.add(render);
    timeline.play(0);

    return teardown;
    // `logoSizing`, `sequence` and `budgetSeconds` are read once, at setup: changing them
    // mid-loader would mean restarting the entry animation, which is never what the page wants.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div ref={hostRef} className={className} aria-hidden="true" />;
}

export default DropLogoMaterial3D;
