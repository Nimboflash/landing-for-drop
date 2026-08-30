/**
 * Quality tier — the `high` / `medium` / `low` rendering level, plus the reduced-motion axis.
 *
 * Brief Section 14 ("Quality tiers"):
 *   - High:   full shader detail, DPR capped at 1.75-2, reflections, grain, pointer response.
 *   - Medium: DPR capped at 1.5, fewer mesh subdivisions, reduced post-processing.
 *   - Low:    DPR 1, simplified noise, no expensive refraction, static/slow fallback.
 *   - Reduced motion: static backgrounds with brief crossfades; all content stays accessible.
 *
 * The last bullet is a **separate axis**, not a fourth tier: a workstation can request
 * reduced motion and a budget phone can request full motion. {@link resolveRenderSettings}
 * combines the two into the single settings object shaders and scenes read, so no shader
 * re-derives tiers for itself.
 *
 * Detection is pure: {@link detectQualityTier} takes {@link DeviceSignals} and nothing else,
 * and {@link readDeviceSignals} is the only function that touches the environment — SSR-safe,
 * and injectable for tests.
 */

import { detectWebGLSupport } from "./webgl-support";

export type QualityTier = "high" | "medium" | "low";

/** Every tier, best first. */
export const QUALITY_TIERS = ["high", "medium", "low"] as const satisfies readonly QualityTier[];

/**
 * Tier when nothing is known yet — server render and the pre-hydration pass. Medium keeps
 * the first client frame honest: it neither promises a workstation nor punishes one.
 */
export const DEFAULT_QUALITY_TIER: QualityTier = "medium";

/** What WebGL detection contributes to tier selection. `null` means "not probed yet". */
export type WebGLSignal = {
  supported: boolean;
  /** Unmasked renderer string where available. */
  renderer: string | null;
};

/**
 * Device capability signals. Every field is nullable where the browser may not report it —
 * `null` means "unknown", which is never treated as "bad".
 */
export type DeviceSignals = {
  /** `navigator.deviceMemory`, in GB. Quantised by the browser (0.25/0.5/1/2/4/8). */
  deviceMemoryGb: number | null;
  /** `navigator.hardwareConcurrency` — logical cores. */
  hardwareConcurrency: number | null;
  /** `window.devicePixelRatio`. A 3x panel multiplies fragment cost. */
  devicePixelRatio: number;
  /** `(pointer: coarse)` — touch-first input. */
  coarsePointer: boolean;
  /** `navigator.userAgentData.mobile`, or a coarse-pointer narrow viewport. */
  mobileHint: boolean;
  /** WebGL probe result, or `null` when WebGL has not been probed (server render). */
  webgl: WebGLSignal | null;
};

/** Signals for an environment that has told us nothing — the server-render shape. */
export const UNKNOWN_DEVICE_SIGNALS: DeviceSignals = Object.freeze({
  deviceMemoryGb: null,
  hardwareConcurrency: null,
  devicePixelRatio: 1,
  coarsePointer: false,
  mobileHint: false,
  webgl: null,
});

/* -------------------------------------------------------------------------- */
/* DPR caps — brief Section 14                                                 */
/* -------------------------------------------------------------------------- */

/**
 * The DPR ceiling each tier renders at. Brief Section 14: high 1.75-2, medium 1.5, low 1.
 * The renderer never exceeds these, and {@link DPR_CAP_RANGE} documents the sanctioned band
 * for high, within which a heavy scene may choose a lower ceiling.
 */
export const DPR_CAP = {
  high: 2,
  medium: 1.5,
  low: 1,
} as const satisfies Readonly<Record<QualityTier, number>>;

/** `[min, max]` DPR ceiling per tier. Only high has a band; medium and low are exact. */
export const DPR_CAP_RANGE = {
  high: [1.75, 2],
  medium: [1.5, 1.5],
  low: [1, 1],
} as const satisfies Readonly<Record<QualityTier, readonly [number, number]>>;

/** Never render below 1x, whatever the device reports. */
const MIN_DEVICE_PIXEL_RATIO = 1;

/**
 * The pixel ratio to actually render at: the device's own ratio, clamped to the tier's cap.
 * Brief Section 14 forbids unbounded DPR.
 */
export function resolveDevicePixelRatio(
  tier: QualityTier,
  devicePixelRatio: number,
): number {
  const cap = DPR_CAP[tier];
  if (!Number.isFinite(devicePixelRatio) || devicePixelRatio <= 0) return MIN_DEVICE_PIXEL_RATIO;
  return Math.max(MIN_DEVICE_PIXEL_RATIO, Math.min(devicePixelRatio, cap));
}

/* -------------------------------------------------------------------------- */
/* Shader detail knobs — plain data, read by shaders, never re-derived by them  */
/* -------------------------------------------------------------------------- */

export type ShaderDetail = {
  /** Plane/mesh segments per side for the Monochrome Mesh and Wavy Dots fields. */
  meshSubdivision: number;
  /** Post-processing pass on/off. */
  postProcessing: boolean;
  /** Reflections on/off (brief lists reflections as a high-tier feature). */
  reflections: boolean;
  /** Film grain overlay. */
  grain: boolean;
  /** Expensive refraction — the loader material and jewel case. Off below high. */
  refraction: boolean;
  /** Pointer micro-interaction response in shader uniforms. */
  pointerResponse: boolean;
  /** Brief Section 14: low tier uses simplified noise. */
  noiseDetail: "full" | "simplified";
  /** Brief Section 17: "Cap texture size based on quality tier." Long edge, px. */
  textureSizeCap: number;
};

export type QualityTierSettings = {
  tier: QualityTier;
  dprCap: number;
  dprCapRange: readonly [number, number];
  shaderDetail: ShaderDetail;
};

/**
 * The per-tier configuration object shaders read. Subdivision counts and texture caps are
 * tunable by feel (like scroll budgets); what is fixed by the brief is their ordering —
 * detail decreases strictly from high to low — and the DPR caps above.
 */
export const QUALITY_TIER_SETTINGS = {
  high: {
    tier: "high",
    dprCap: DPR_CAP.high,
    dprCapRange: DPR_CAP_RANGE.high,
    shaderDetail: {
      meshSubdivision: 128,
      postProcessing: true,
      reflections: true,
      grain: true,
      refraction: true,
      pointerResponse: true,
      noiseDetail: "full",
      textureSizeCap: 2048,
    },
  },
  medium: {
    tier: "medium",
    dprCap: DPR_CAP.medium,
    dprCapRange: DPR_CAP_RANGE.medium,
    shaderDetail: {
      // "fewer mesh subdivisions, reduced post-processing": the pass stays, the
      // reflections and refraction it would feed do not.
      meshSubdivision: 64,
      postProcessing: true,
      reflections: false,
      grain: true,
      refraction: false,
      pointerResponse: true,
      noiseDetail: "full",
      textureSizeCap: 1024,
    },
  },
  low: {
    tier: "low",
    dprCap: DPR_CAP.low,
    dprCapRange: DPR_CAP_RANGE.low,
    shaderDetail: {
      meshSubdivision: 32,
      postProcessing: false,
      reflections: false,
      grain: false,
      refraction: false,
      pointerResponse: false,
      noiseDetail: "simplified",
      textureSizeCap: 512,
    },
  },
} as const satisfies Readonly<Record<QualityTier, QualityTierSettings>>;

/* -------------------------------------------------------------------------- */
/* Tier detection                                                              */
/* -------------------------------------------------------------------------- */

/** Software rasterisers: present, but not worth full shader detail. */
const SOFTWARE_RENDERER_PATTERN =
  /swiftshader|llvmpipe|softpipe|software|microsoft basic render|generic renderer/i;

export function isSoftwareRenderer(renderer: string | null): boolean {
  if (!renderer) return false;
  return SOFTWARE_RENDERER_PATTERN.test(renderer);
}

/** At or below this, the device cannot hold the scene's textures comfortably. */
const LOW_MEMORY_GB = 2;
/** At or above this, memory is not the constraint. */
const HIGH_MEMORY_GB = 8;
/** At or below this, the main thread has no headroom for scrubbed timelines. */
const LOW_CORE_COUNT = 2;
/** At or above this, the CPU is not the constraint. */
const HIGH_CORE_COUNT = 8;
/** Enough memory for the scene's textures at medium detail. */
const MODEST_MEMORY_GB = 4;
/** Mid-range devices driving a 3x panel pay for it in fragments. */
const DEMANDING_PIXEL_RATIO = 3;
const MODEST_CORE_COUNT = 4;

/**
 * Pick a tier from device signals. Pure — inject fake signals to test it.
 *
 * Rules, in order:
 *   1. No WebGL, or a software rasteriser → low (the scene falls back to static anyway).
 *   2. Very low memory or very few cores → low.
 *   3. Desktop-class input **and** high memory **and** high core count → high. Touch devices
 *      never claim high: brief Section 17 targets 60fps desktop but only 30fps+ on mobile.
 *   4. Otherwise, if memory and cores are at least modest (or unknown) → medium…
 *   5. …demoted to low when a modest CPU also has to fill a 3x panel.
 *   6. Anything left → low.
 */
export function detectQualityTier(signals: DeviceSignals): QualityTier {
  const { webgl } = signals;
  if (webgl && !webgl.supported) return "low";
  if (webgl && isSoftwareRenderer(webgl.renderer)) return "low";

  const memory = signals.deviceMemoryGb;
  const cores = signals.hardwareConcurrency;

  if (memory !== null && memory <= LOW_MEMORY_GB) return "low";
  if (cores !== null && cores <= LOW_CORE_COUNT) return "low";

  const touchFirst = signals.mobileHint || signals.coarsePointer;
  const memoryIsHigh = memory !== null && memory >= HIGH_MEMORY_GB;
  const coresAreHigh = cores !== null && cores >= HIGH_CORE_COUNT;

  if (!touchFirst && memoryIsHigh && coresAreHigh) return "high";

  // Unknown counts as "at least modest" — never punish a device for staying quiet.
  const memoryIsModest = memory === null || memory >= MODEST_MEMORY_GB;
  const coresAreModest = cores === null || cores >= MODEST_CORE_COUNT;
  if (!memoryIsModest || !coresAreModest) return "low";

  const modestCpu = cores !== null && cores <= MODEST_CORE_COUNT;
  if (modestCpu && signals.devicePixelRatio >= DEMANDING_PIXEL_RATIO) return "low";

  return "medium";
}

/* -------------------------------------------------------------------------- */
/* Reading real device signals — the only environment-touching code here        */
/* -------------------------------------------------------------------------- */

/** Injection seam for the globals this module reads. `null` means "server render". */
export type DeviceSignalScope = {
  navigator?: {
    deviceMemory?: unknown;
    hardwareConcurrency?: unknown;
    userAgentData?: { mobile?: unknown };
  };
  devicePixelRatio?: unknown;
  innerWidth?: unknown;
  matchMedia?: (query: string) => { matches: boolean };
};

export type ReadDeviceSignalsOptions = {
  /** Injected globals. Omit for the real window; pass `null` to simulate a server render. */
  scope?: DeviceSignalScope | null;
  /**
   * Injected WebGL verdict. Omit the key to probe for real; pass `null` to skip probing
   * and leave the signal unknown.
   */
  webgl?: WebGLSignal | null;
};

/** Brief Section 15: mobile is below 768px. */
const MOBILE_VIEWPORT_MAX = 768;

function browserScope(): DeviceSignalScope | null {
  if (typeof window === "undefined") return null;
  return window as unknown as DeviceSignalScope;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

function mediaMatches(scope: DeviceSignalScope, query: string): boolean {
  if (typeof scope.matchMedia !== "function") return false;
  try {
    return scope.matchMedia(query).matches === true;
  } catch {
    return false;
  }
}

/**
 * Read device signals from the environment. Never throws: with no window (or an environment
 * that reports nothing) it returns {@link UNKNOWN_DEVICE_SIGNALS}, which
 * {@link detectQualityTier} maps to {@link DEFAULT_QUALITY_TIER}.
 */
export function readDeviceSignals(options: ReadDeviceSignalsOptions = {}): DeviceSignals {
  const scope = options.scope === undefined ? browserScope() : options.scope;
  if (!scope) return { ...UNKNOWN_DEVICE_SIGNALS };

  const nav = scope.navigator;
  const coarsePointer = mediaMatches(scope, "(pointer: coarse)");
  const viewportWidth = finiteNumber(scope.innerWidth);
  const uaMobile = nav?.userAgentData?.mobile === true;
  const mobileHint =
    uaMobile || (coarsePointer && viewportWidth !== null && viewportWidth < MOBILE_VIEWPORT_MAX);

  let webgl: WebGLSignal | null;
  if ("webgl" in options) {
    webgl = options.webgl ?? null;
  } else {
    const support = detectWebGLSupport();
    // "no-document" means not knowable yet, not "unsupported".
    webgl =
      support.failureReason === "no-document"
        ? null
        : { supported: support.supported, renderer: support.renderer };
  }

  return {
    deviceMemoryGb: finiteNumber(nav?.deviceMemory),
    hardwareConcurrency: finiteNumber(nav?.hardwareConcurrency),
    devicePixelRatio: finiteNumber(scope.devicePixelRatio) ?? 1,
    coarsePointer,
    mobileHint,
    webgl,
  };
}

let cachedTier: QualityTier | null = null;

/**
 * Detect the tier for the current environment, probing WebGL once and caching the verdict.
 * Returns {@link DEFAULT_QUALITY_TIER} during server render.
 */
export function detectEnvironmentQualityTier(options?: ReadDeviceSignalsOptions): QualityTier {
  if (options === undefined && cachedTier !== null) return cachedTier;
  const tier = detectQualityTier(readDeviceSignals(options));
  if (options === undefined) cachedTier = tier;
  return tier;
}

/** Clear the cached environment tier. */
export function resetQualityTierCache(): void {
  cachedTier = null;
}

/* -------------------------------------------------------------------------- */
/* Effective settings — tier combined with the reduced-motion axis              */
/* -------------------------------------------------------------------------- */

export type BackgroundBehavior = "animated" | "static";
export type TransitionStyle = "scrubbed" | "crossfade";

/**
 * Brief Section 14: reduced motion gets "static backgrounds with brief crossfades". Brief,
 * not instant — an instant cut is its own kind of motion jolt.
 */
export const REDUCED_MOTION_CROSSFADE_SECONDS = 0.24;

export type EffectiveRenderSettings = {
  tier: QualityTier;
  reducedMotion: boolean;
  dprCap: number;
  dprCapRange: readonly [number, number];
  shaderDetail: ShaderDetail;
  /** `static` renders one frame and holds it; `animated` runs the shader clock. */
  backgroundBehavior: BackgroundBehavior;
  /** `scrubbed` follows scroll progress; `crossfade` swaps modes over a short fade. */
  transitionStyle: TransitionStyle;
  /** Duration of the reduced-motion crossfade; 0 when transitions are scrubbed. */
  crossfadeSeconds: number;
  /** Whether the shader clock advances at all. */
  animateShaders: boolean;
  /** Pointer micro-interactions — off for reduced motion and on the low tier. */
  pointerResponse: boolean;
};

export type ResolveRenderSettingsInput = {
  tier: QualityTier;
  reducedMotion: boolean;
};

/**
 * Combine the tier with the reduced-motion axis into the one settings object scenes and
 * shaders read. Reduced motion never lowers the DPR cap or removes content — it stops the
 * clock (brief Section 16: reduced motion must not remove content or make the page unusable).
 */
export function resolveRenderSettings(
  input: ResolveRenderSettingsInput,
): EffectiveRenderSettings {
  const tierSettings = QUALITY_TIER_SETTINGS[input.tier];
  const { reducedMotion } = input;

  const shaderDetail: ShaderDetail = reducedMotion
    ? { ...tierSettings.shaderDetail, pointerResponse: false }
    : { ...tierSettings.shaderDetail };

  return {
    tier: tierSettings.tier,
    reducedMotion,
    dprCap: tierSettings.dprCap,
    dprCapRange: tierSettings.dprCapRange,
    shaderDetail,
    backgroundBehavior: reducedMotion ? "static" : "animated",
    transitionStyle: reducedMotion ? "crossfade" : "scrubbed",
    crossfadeSeconds: reducedMotion ? REDUCED_MOTION_CROSSFADE_SECONDS : 0,
    animateShaders: !reducedMotion,
    pointerResponse: shaderDetail.pointerResponse,
  };
}
