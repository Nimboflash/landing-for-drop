/**
 * Quality-tier unit tests (ticket 03 — "prefers-reduced-motion utility and quality-tier
 * detection (high/medium/low) available and unit-tested").
 *
 * Expected values come from brief Section 14, not from re-running the implementation's own
 * arithmetic: the DPR caps are the brief's numbers written out by hand, and each tier
 * expectation is stated as a device profile → the tier that device should get.
 */

import { describe, expect, it } from "vitest";

import {
  DEFAULT_QUALITY_TIER,
  DPR_CAP,
  DPR_CAP_RANGE,
  QUALITY_TIERS,
  QUALITY_TIER_SETTINGS,
  detectQualityTier,
  readDeviceSignals,
  resolveDevicePixelRatio,
  resolveRenderSettings,
  type DeviceSignals,
  type QualityTier,
} from "@/lib/performance/quality-tier";
import { detectWebGLSupport, observeContextLoss } from "@/lib/performance/webgl-support";
import {
  prefersReducedMotion,
  subscribeReducedMotion,
  type MediaQueryScope,
} from "@/lib/motion/reduced-motion";

/**
 * Brief Section 14, transcribed by hand — the three tiers it names, and the DPR ceiling it
 * gives each one ("High: DPR capped at 1.75-2 … Medium: DPR capped at 1.5 … Low: DPR 1").
 * Expectations are read from here, never from the module under test.
 */
const BRIEF_TIERS = ["high", "medium", "low"] as const satisfies readonly QualityTier[];
const BRIEF_DPR_CAP: Readonly<Record<QualityTier, number>> = {
  high: 2,
  medium: 1.5,
  low: 1,
};

/** A device profile, written the way a QA note would describe the hardware. */
function device(overrides: Partial<DeviceSignals> = {}): DeviceSignals {
  return {
    deviceMemoryGb: 8,
    hardwareConcurrency: 8,
    devicePixelRatio: 2,
    coarsePointer: false,
    mobileHint: false,
    webgl: { supported: true, renderer: "ANGLE (Apple, Apple M2, Metal)" },
    ...overrides,
  };
}

describe("quality tier selection", () => {
  it("gives a desktop workstation with plenty of memory and cores the high tier", () => {
    const workstation = device({
      deviceMemoryGb: 8,
      hardwareConcurrency: 12,
      devicePixelRatio: 2,
      coarsePointer: false,
      mobileHint: false,
    });

    expect(detectQualityTier(workstation)).toBe("high");
  });

  it("gives a mid-range laptop the medium tier", () => {
    const midLaptop = device({
      deviceMemoryGb: 4,
      hardwareConcurrency: 4,
      devicePixelRatio: 1,
    });

    expect(detectQualityTier(midLaptop)).toBe("medium");
  });

  it("gives a low-memory phone the low tier", () => {
    const budgetPhone = device({
      deviceMemoryGb: 2,
      hardwareConcurrency: 4,
      devicePixelRatio: 2,
      coarsePointer: true,
      mobileHint: true,
    });

    expect(detectQualityTier(budgetPhone)).toBe("low");
  });

  it("gives a low-core device the low tier even when memory is plentiful", () => {
    const twoCoreMachine = device({ deviceMemoryGb: 8, hardwareConcurrency: 2 });

    expect(detectQualityTier(twoCoreMachine)).toBe("low");
  });

  it("never promotes a touch device to the high tier", () => {
    // Brief Section 17 targets 60fps on capable desktop but only 30fps+ on mid-range mobile.
    const flagshipPhone = device({
      deviceMemoryGb: 8,
      hardwareConcurrency: 8,
      devicePixelRatio: 3,
      coarsePointer: true,
      mobileHint: true,
    });

    expect(detectQualityTier(flagshipPhone)).toBe("medium");
  });

  it("drops a modest CPU driving a 3x panel to the low tier", () => {
    const midAndroid = device({
      deviceMemoryGb: 4,
      hardwareConcurrency: 4,
      devicePixelRatio: 3,
      coarsePointer: true,
      mobileHint: true,
    });

    expect(detectQualityTier(midAndroid)).toBe("low");
  });

  it("gives the low tier when WebGL cannot be created", () => {
    const noWebGL = device({ webgl: { supported: false, renderer: null } });

    expect(detectQualityTier(noWebGL)).toBe("low");
  });

  it("gives the low tier to a software rasteriser", () => {
    const softwareRendered = device({
      webgl: { supported: true, renderer: "Google SwiftShader" },
    });

    expect(detectQualityTier(softwareRendered)).toBe("low");
  });

  it("falls back to the default tier when the device reports nothing", () => {
    const silentDevice = device({
      deviceMemoryGb: null,
      hardwareConcurrency: null,
      devicePixelRatio: 1,
      webgl: null,
    });

    // Medium: a device that reports nothing is never punished for staying quiet, and the
    // first client frame neither promises a workstation nor throttles one.
    expect(detectQualityTier(silentDevice)).toBe("medium");
    expect(DEFAULT_QUALITY_TIER).toBe("medium");
  });
});

describe("DPR caps", () => {
  it("exposes exactly the three tiers the brief names, best first", () => {
    expect(QUALITY_TIERS).toEqual(["high", "medium", "low"]);
  });

  // Brief Section 14, written out by hand: high 1.75-2, medium 1.5, low 1.
  it("caps the high tier between 1.75 and 2", () => {
    expect(DPR_CAP_RANGE.high).toEqual([1.75, 2]);
    expect(DPR_CAP.high).toBe(2);
  });

  it("caps the medium tier at 1.5", () => {
    expect(DPR_CAP.medium).toBe(1.5);
    expect(DPR_CAP_RANGE.medium).toEqual([1.5, 1.5]);
  });

  it("caps the low tier at 1", () => {
    expect(DPR_CAP.low).toBe(1);
    expect(DPR_CAP_RANGE.low).toEqual([1, 1]);
  });

  it("clamps a 3x display to each tier's cap", () => {
    expect(resolveDevicePixelRatio("high", 3)).toBe(2);
    expect(resolveDevicePixelRatio("medium", 3)).toBe(1.5);
    expect(resolveDevicePixelRatio("low", 3)).toBe(1);
  });

  it("never renders above the device's own ratio", () => {
    expect(resolveDevicePixelRatio("high", 1)).toBe(1);
    expect(resolveDevicePixelRatio("medium", 1.25)).toBe(1.25);
  });
});

describe("shader detail per tier", () => {
  it("gives the high tier full detail: reflections, grain and pointer response", () => {
    const { shaderDetail } = QUALITY_TIER_SETTINGS.high;

    expect(shaderDetail.reflections).toBe(true);
    expect(shaderDetail.grain).toBe(true);
    expect(shaderDetail.pointerResponse).toBe(true);
    expect(shaderDetail.noiseDetail).toBe("full");
  });

  it("subdivides the mesh less at every step down the tiers", () => {
    expect(QUALITY_TIER_SETTINGS.high.shaderDetail.meshSubdivision).toBeGreaterThan(
      QUALITY_TIER_SETTINGS.medium.shaderDetail.meshSubdivision,
    );
    expect(QUALITY_TIER_SETTINGS.medium.shaderDetail.meshSubdivision).toBeGreaterThan(
      QUALITY_TIER_SETTINGS.low.shaderDetail.meshSubdivision,
    );
  });

  it("turns off post-processing and expensive refraction on the low tier", () => {
    const { shaderDetail } = QUALITY_TIER_SETTINGS.low;

    expect(shaderDetail.postProcessing).toBe(false);
    expect(shaderDetail.refraction).toBe(false);
    expect(shaderDetail.noiseDetail).toBe("simplified");
  });

  it("caps texture size lower at every step down the tiers", () => {
    expect(QUALITY_TIER_SETTINGS.high.shaderDetail.textureSizeCap).toBeGreaterThan(
      QUALITY_TIER_SETTINGS.medium.shaderDetail.textureSizeCap,
    );
    expect(QUALITY_TIER_SETTINGS.medium.shaderDetail.textureSizeCap).toBeGreaterThan(
      QUALITY_TIER_SETTINGS.low.shaderDetail.textureSizeCap,
    );
  });
});

describe("reduced motion combined with each tier", () => {
  it.each(BRIEF_TIERS)("holds the background static on the %s tier", (tier) => {
    const settings = resolveRenderSettings({ tier, reducedMotion: true });

    expect(settings.tier).toBe(tier);
    expect(settings.reducedMotion).toBe(true);
    expect(settings.backgroundBehavior).toBe("static");
    expect(settings.animateShaders).toBe(false);
    expect(settings.pointerResponse).toBe(false);
  });

  it.each(BRIEF_TIERS)("crossfades briefly instead of scrubbing on the %s tier", (tier) => {
    const settings = resolveRenderSettings({ tier, reducedMotion: true });

    expect(settings.transitionStyle).toBe("crossfade");
    expect(settings.crossfadeSeconds).toBeGreaterThan(0);
  });

  it.each(BRIEF_TIERS)("keeps the %s tier's DPR cap under reduced motion", (tier) => {
    // Reduced motion stops the clock; it is not a lower quality tier.
    const settings = resolveRenderSettings({ tier, reducedMotion: true });

    expect(settings.dprCap).toBe(BRIEF_DPR_CAP[tier]);
  });

  it.each(BRIEF_TIERS)("scrubs animated backgrounds on the %s tier without reduced motion", (tier) => {
    const settings = resolveRenderSettings({ tier, reducedMotion: false });

    expect(settings.backgroundBehavior).toBe("animated");
    expect(settings.transitionStyle).toBe("scrubbed");
    expect(settings.animateShaders).toBe(true);
  });
});

describe("SSR safety", () => {
  it("reads device signals without a window", () => {
    const signals = readDeviceSignals({ scope: null });

    expect(signals.webgl).toBeNull();
    expect(signals.deviceMemoryGb).toBeNull();
    expect(signals.hardwareConcurrency).toBeNull();
    expect(signals.devicePixelRatio).toBe(1);
  });

  it("resolves the default tier on the server", () => {
    expect(detectQualityTier(readDeviceSignals({ scope: null }))).toBe(DEFAULT_QUALITY_TIER);
  });

  it("reads device signals from an environment that reports nothing", () => {
    const signals = readDeviceSignals({ scope: {}, webgl: null });

    expect(signals.coarsePointer).toBe(false);
    expect(signals.mobileHint).toBe(false);
    expect(signals.devicePixelRatio).toBe(1);
  });

  it("reports WebGL as unsupported without a document", () => {
    const support = detectWebGLSupport({ document: null });

    expect(support.supported).toBe(false);
    expect(support.failureReason).toBe("no-document");
  });

  it("returns a callable teardown when there is no canvas to observe context loss on", () => {
    const stop = observeContextLoss(null, { onLost: () => {} });

    expect(() => {
      stop();
    }).not.toThrow();
  });

  it("reports full motion when there is no media query to read", () => {
    expect(prefersReducedMotion(null)).toBe(false);
    expect(prefersReducedMotion({})).toBe(false);
  });

  it("returns a callable teardown when there is nothing to subscribe to", () => {
    const stop = subscribeReducedMotion(() => {}, null);

    expect(() => {
      stop();
    }).not.toThrow();
  });
});

describe("reduced-motion subscription teardown", () => {
  it("removes its listener when torn down", () => {
    const listeners = new Set<() => void>();
    const scope: MediaQueryScope = {
      matchMedia: () => ({
        matches: true,
        addEventListener: (_type, listener) => {
          listeners.add(listener);
        },
        removeEventListener: (_type, listener) => {
          listeners.delete(listener);
        },
      }),
    };

    const stop = subscribeReducedMotion(() => {}, scope);
    expect(listeners.size).toBe(1);

    stop();
    expect(listeners.size).toBe(0);

    // Tearing down twice must stay harmless.
    stop();
    expect(listeners.size).toBe(0);
  });
});
