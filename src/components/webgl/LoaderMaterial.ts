/**
 * Loader material — the near-black glossy lacquer the DROP logo is made of (brief §7.1).
 *
 * The reference (`handoff/02-motion/opacity-loader-material-reference.png`) is a wet, thick
 * lacquer slab with a circular void: soft irregular edges, real bevelled depth, and broad
 * specular streaks travelling across the surface. This module is the GPU half of that: the
 * GLSL, its uniforms, and the one texture the shader needs. It owns no React, no timeline and
 * no lifecycle — `DropLogoMaterial3D` drives it.
 *
 * ## Not a background mode
 *
 * The loader is the single sanctioned exception to the shared background canvas (ticket 04's
 * contract note): it lives on its own temporary overlay canvas ABOVE the DOM and disposes when
 * the portal completes. So nothing here implements `BackgroundShaderModule` — but the brand
 * colour tokens and the fullscreen-quad vertex shader are shared with it, because a second copy
 * of either would be a second source of truth.
 *
 * ## How the mark reaches the GPU
 *
 * The letterforms are never redrawn here and never traced from a bitmap. `@/components/brand`
 * is the single source of the geometry; {@link createLoaderMask} rasterises exactly the path
 * data `lockupPaths` returns — tiles, minus knocked-out letterform bodies, plus the counters
 * given back — into a one-channel coverage field, blurred so the shader can read it as a height
 * field. A blurred coverage field is both things at once: `smoothstep` around 0.5 recovers a
 * crisp silhouette (the SDF-text trick), while the raw value is the bevel the lighting needs.
 *
 * The O's aperture is deliberately NOT in that texture. It is rasterised closed
 * (`apertureScale: 0`) and the shader subtracts an analytic circle instead, so one uniform
 * drives the resting pulse, the portal expansion, and the screen-space hole that reveals the
 * page — with no texture re-upload and no quantisation as the aperture grows past the viewport.
 *
 * ## Coordinate space
 *
 * Everything the fragment shader reasons about lives in "space units": the viewport mapped to
 * y ∈ [-0.5, 0.5] with x scaled by the aspect ratio, so **one space unit is one viewport
 * height** on both axes. {@link resolveLoaderLayout} converts the brand geometry into that
 * space; the shader never sees a pixel dimension except for antialiasing widths.
 */

import {
  CanvasTexture,
  ClampToEdgeWrapping,
  LinearFilter,
  NoColorSpace,
  type IUniform,
} from "three";

import {
  DEFAULT_MODULE_SIZE,
  brandGeometry,
  lockupPaths,
  type BrandGeometry,
  type Lockup,
} from "@/components/brand";
import type { EffectiveRenderSettings } from "@/lib/performance/quality-tier";
import {
  FULLSCREEN_QUAD_VERTEX_SHADER,
  GLSL_BRAND_COLORS,
} from "@/components/webgl/shader-contract";

/* ------------------------------------------------------------------ shaders */

/** The loader draws one screen-space quad, exactly like the background modes do. */
export const LOADER_VERTEX_SHADER = FULLSCREEN_QUAD_VERTEX_SHADER;

/**
 * The lacquer.
 *
 * Read it as four stages: recover the surface (mask + aperture + irregularity), build a normal
 * from it, light that normal with a travelling studio environment, then decide what is material,
 * what is field, and what is hole.
 *
 * Deliberately free of `dFdx`/`fwidth`: derivative availability differs between GLSL ES 1.00
 * shaders on WebGL2 implementations, and every edge width here is knowable from `uResolution`
 * anyway.
 */
export const LOADER_FRAGMENT_SHADER = /* glsl */ `
${GLSL_BRAND_COLORS}

varying vec2 vUv;

uniform sampler2D uMask;
uniform vec2 uResolution;
uniform float uTime;

// choreography (brief §7.1, driven by the loader timeline)
uniform float uMaterialize;   // 0 = near-black shadow, 1 = fully realised material
uniform float uSettle;        // 0 = every module alive, 1 = D/R/P settled, the O keeps moving
uniform float uAperture;      // aperture scale; 1.0 is the resting inner radius
uniform float uPortal;        // 0 = aperture is off-white field, 1 = aperture is a real hole
uniform float uFieldFade;     // safety multiplier on overlay alpha; 1 for the whole sequence

// material knobs (quality tier)
uniform float uSurface;       // displacement + edge irregularity amount
uniform float uSpecular;      // travelling highlight intensity
uniform float uRefraction;    // chromatic spread of the highlights and the refracted rim
uniform float uGrain;
uniform float uDetail;        // 1 = full noise octaves, 0 = simplified (low tier)

// layout, all in space units (1.0 == one viewport height)
uniform vec4 uLogoRect;       // xy = centre, zw = half extent of the mask texture
uniform vec2 uOCenter;
uniform float uRestingRadius;
uniform float uEdgeSoftness;
uniform vec2 uContentX;       // maps mask u -> 0..1 across the wordmark row (scale, offset)

float hash21(vec2 p) {
  vec3 q = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
  q += dot(q, q.yzx + 33.33);
  return fract((q.x + q.y) * q.z);
}

float valueNoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float a = hash21(i);
  float b = hash21(i + vec2(1.0, 0.0));
  float c = hash21(i + vec2(0.0, 1.0));
  float d = hash21(i + vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

/* Third octave is scaled by uDetail rather than skipped, so the low tier takes the same code
   path — a branch here would be a shader variant, and variants are a compile stall. */
float fbm(vec2 p) {
  float v = 0.5 * valueNoise(p);
  v += 0.25 * valueNoise(p * 2.03 + 11.7);
  v += 0.125 * uDetail * valueNoise(p * 4.11 + 23.3);
  return v / (0.75 + 0.125 * uDetail);
}

/** Viewport in space units: y in [-0.5, 0.5], x scaled by aspect. */
vec2 toSpace(vec2 uv) {
  float aspect = uResolution.x / max(uResolution.y, 1.0);
  return (uv - 0.5) * vec2(aspect, 1.0);
}

vec2 maskUv(vec2 p) {
  return (p - uLogoRect.xy) / (2.0 * uLogoRect.zw) + 0.5;
}

/**
 * Aperture radius, with a slow angular irregularity so the void breathes like a liquid edge
 * rather than a stencil. Cheap trigonometry on purpose: this is evaluated several times per
 * fragment, and the wobble only has to be non-periodic to the eye.
 */
float apertureRadiusAt(vec2 p) {
  vec2 d = p - uOCenter;
  float a = atan(d.y, d.x);
  float wobble = 1.0 + 0.014 * uSurface * sin(a * 3.0 + uTime * 0.8) * sin(a * 5.0 - uTime * 0.53);
  return uRestingRadius * max(uAperture, 0.0) * wobble;
}

/** 0 inside the aperture, 1 outside it. */
float apertureField(vec2 p, float soft) {
  float d = length(p - uOCenter);
  float r = apertureRadiusAt(p);
  return smoothstep(r - soft, r + soft, d);
}

/** Blurred coverage of the mark at p, with the aperture cut out of it. */
float surfaceAt(vec2 p, float soft) {
  float m = texture2D(uMask, clamp(maskUv(p), 0.0, 1.0)).r;
  return min(m, apertureField(p, soft));
}

/** Broad soft studio bands. The offset travels, which is what makes the highlights move. */
float band(vec2 q, vec2 dir, float width, float off) {
  float t = dot(q, dir) - off;
  return exp(-(t * t) / (width * width));
}

/*
 * A dark studio with three sources: one broad soft box and two thin strips. Their offsets are
 * bounded oscillations rather than linear ramps, so a highlight that has crossed the mark comes
 * back — a 3.2s scene cannot afford a light that leaves and never returns.
 */
float environment(vec2 q) {
  float v = band(q, normalize(vec2(0.82, 0.57)), 0.20, 0.55 * sin(uTime * 0.50) - 0.06);
  v += 0.55 * band(q, normalize(vec2(-0.44, 0.90)), 0.075, 0.90 * sin(uTime * 0.37 + 1.7));
  v += 0.30 * band(q, normalize(vec2(0.21, -0.98)), 0.050, 0.80 * sin(uTime * 0.62 + 3.1));
  return v;
}

void main() {
  vec2 p = toSpace(vUv);
  float unitPx = 1.0 / max(uResolution.y, 1.0);
  float soft = unitPx * 1.6;

  // Soft irregular silhouette: displace the lookup, not the geometry.
  float wobbleAmount = uSurface * 0.0045;
  vec2 pw = p + wobbleAmount * vec2(
    valueNoise(p * 5.3 + uTime * 0.05) - 0.5,
    valueNoise(p * 5.1 - uTime * 0.04 + 7.0) - 0.5
  );

  // Which module we are on. Tile bands fall in the gaps, so quarters are exact.
  float contentX = uContentX.x * maskUv(pw).x + uContentX.y;
  float tile = clamp(floor(contentX * 4.0), 0.0, 3.0);
  float isO = step(1.5, tile) * step(tile, 2.5);
  // "The pulse becomes the focus while D/R/P settle": the O keeps its life, the squares calm down.
  float calm = mix(1.0, mix(0.34, 1.0, isO), uSettle);

  float m0 = surfaceAt(pw, soft);
  float edge = unitPx * 1.4;
  float mx = surfaceAt(pw + vec2(edge, 0.0), soft);
  float my = surfaceAt(pw + vec2(0.0, edge), soft);
  vec2 edgeGrad = vec2(m0 - mx, m0 - my);

  // Surface swell sampled at a much larger step: a gentle roll has a gentle slope, and a
  // one-pixel difference of it would be numerically invisible.
  float swellStep = 0.02;
  vec2 swellUv = pw * 2.4 + vec2(uTime * 0.06, uTime * -0.041);
  float s0 = fbm(swellUv);
  float sx = fbm(swellUv + vec2(swellStep * 2.4, 0.0));
  float sy = fbm(swellUv + vec2(0.0, swellStep * 2.4));
  vec2 swellGrad = vec2(s0 - sx, s0 - sy) / swellStep;

  float body = smoothstep(0.25, 0.75, m0);
  // Restrained on purpose: the reference is a flat lacquer slab with soft edges, not an embossed
  // chrome letter. The bevel's WIDTH comes from the mask's blur; this is only its steepness.
  vec3 n = normalize(vec3(
    edgeGrad * 1.15 + swellGrad * uSurface * calm * body * 0.055,
    1.0
  ));

  // View is orthographic down -z, so the reflected direction is essentially 2 * n.xy. The
  // positional term is large enough that a light band reads as a streak crossing the mark rather
  // than the whole face switching on at once.
  vec2 q = n.xy * 2.2 + pw * 1.7;
  vec2 chroma = vec2(0.012, 0.007) * uRefraction;
  vec3 env = vec3(environment(q + chroma), environment(q), environment(q - chroma));

  float fresnel = pow(1.0 - clamp(n.z, 0.0, 1.0), 2.4);
  vec3 gloss = pow(clamp(env, 0.0, 1.0), vec3(2.6)) * (0.70 + 0.85 * fresnel);

  vec3 lacquer = vec3(0.012, 0.012, 0.015);
  vec3 material = lacquer + gloss * uSpecular * calm * vec3(0.98, 0.99, 1.0);
  // The field refracting through the wet edge, restrained.
  material += DROP_OFF_WHITE * fresnel * 0.07 * uRefraction;
  material = clamp(material, 0.0, 1.0);

  // Materialisation staggers across the modules so the logo settles rather than switching on.
  float delay = tile * 0.16;
  float mat = clamp(uMaterialize * 1.48 - delay, 0.0, 1.0);

  float coverage = smoothstep(0.5 - uEdgeSoftness, 0.5 + uEdgeSoftness, m0);
  float shadow = smoothstep(0.04, 0.86, m0) * 0.55;
  float logoAlpha = clamp(mix(shadow, coverage, mat), 0.0, 1.0);
  vec3 logoColor = mix(vec3(0.05, 0.05, 0.055), material, mat);

  // A whisper of contact shadow so the slab sits on the field instead of floating in it.
  vec3 field = DROP_OFF_WHITE * (1.0 - 0.05 * smoothstep(0.0, 0.4, m0) * (1.0 - coverage));

  vec3 rgb = mix(field, logoColor, logoAlpha);
  rgb += (hash21(gl_FragCoord.xy + fract(uTime) * 137.0) - 0.5) * 0.014 * uGrain;

  // The portal: the same aperture, now cut through the overlay itself.
  float hole = 1.0 - apertureField(pw, unitPx * 1.1);
  float alpha = (1.0 - hole * uPortal) * uFieldFade;

  gl_FragColor = vec4(clamp(rgb, 0.0, 1.0), clamp(alpha, 0.0, 1.0));
}
`;

/* ------------------------------------------------------------------ the mask */

/** Fraction of the texture's short side kept clear so the blur never clamps at the border. */
const MASK_PADDING_FRACTION = 0.035;
/** Blur radius as a fraction of the drawn mark's height. Sets how soft the lacquer edge reads. */
const MASK_BLUR_FRACTION = 0.026;
/** Widest mask we ever rasterise; above this the extra texels buy nothing at loader scale. */
const MASK_MAX_WIDTH = 1024;
/** Narrowest useful mask, so a low-tier texture cap cannot dissolve the letterforms. */
const MASK_MIN_WIDTH = 512;
/**
 * Half-width of the `smoothstep` that recovers a crisp silhouette from the blurred coverage.
 * Small enough to stay a sharp mark, wide enough to keep the soft lacquer edge of the reference.
 */
const MASK_EDGE_SOFTNESS = 0.085;

/** The rasterised mark, plus everything the layout needs to place it. */
export type LoaderMask = {
  /** Blurred coverage in the red channel: crisp silhouette AND bevel height field. */
  readonly texture: CanvasTexture;
  /** Wordmark box, in the lockup's own units. */
  readonly lockupWidth: number;
  readonly lockupHeight: number;
  /** Clear border around the mark inside the texture, in lockup units. */
  readonly padLockup: number;
  /** Centre of the O tile, in lockup units. */
  readonly oCenter: readonly [number, number];
  /** Resting aperture radius, in lockup units. */
  readonly restingInnerRadius: number;
  /** `smoothstep` half-width that turns the blurred field back into a silhouette. */
  readonly edgeSoftness: number;
  /** Release the texture and its backing canvas. */
  dispose(): void;
};

export type CreateLoaderMaskOptions = {
  /** Quality-tier texture cap (long edge, px). */
  textureSizeCap?: number;
  /** Injected document, for tests. `null` means "no DOM". */
  documentRef?: Document | null;
};

const clampIndex = (index: number, length: number): number =>
  index < 0 ? 0 : index >= length ? length - 1 : index;

/**
 * Separable box blur. Run twice it approximates a Gaussian closely enough for a height field,
 * and unlike `CanvasRenderingContext2D.filter` it produces the same result on every engine —
 * Safari only gained canvas filters in 17, and a loader that is bevelled on one browser and
 * flat on another is not one material.
 */
function boxBlur(source: Float32Array, width: number, height: number, radius: number): Float32Array {
  const span = radius * 2 + 1;
  const horizontal = new Float32Array(source.length);
  const result = new Float32Array(source.length);

  for (let y = 0; y < height; y += 1) {
    const row = y * width;
    let sum = 0;
    for (let x = -radius; x <= radius; x += 1) sum += source[row + clampIndex(x, width)];
    for (let x = 0; x < width; x += 1) {
      horizontal[row + x] = sum / span;
      sum -= source[row + clampIndex(x - radius, width)];
      sum += source[row + clampIndex(x + radius + 1, width)];
    }
  }

  for (let x = 0; x < width; x += 1) {
    let sum = 0;
    for (let y = -radius; y <= radius; y += 1) sum += horizontal[clampIndex(y, height) * width + x];
    for (let y = 0; y < height; y += 1) {
      result[y * width + x] = sum / span;
      sum -= horizontal[clampIndex(y - radius, height) * width + x];
      sum += horizontal[clampIndex(y + radius + 1, height) * width + x];
    }
  }

  return result;
}

function oTileCentre(geometry: BrandGeometry, lockup: Lockup): readonly [number, number] {
  const tile = lockup.tiles.find((candidate) => candidate.glyph === "O");
  // The wordmark always carries an O; the fallback keeps the type honest rather than throwing
  // inside a decorative loader.
  if (!tile) return [lockup.width / 2, lockup.height / 2];
  return [tile.x + tile.size / 2, tile.y + tile.size / 2];
}

/**
 * Rasterise the wordmark into the shader's coverage/height texture.
 *
 * Returns `null` wherever the browser cannot do it (server render, no 2D context, no `Path2D`) —
 * the caller falls back to the static logo path, which is a required fallback anyway.
 */
export function createLoaderMask(options: CreateLoaderMaskOptions = {}): LoaderMask | null {
  const doc = options.documentRef === undefined ? globalThis.document : options.documentRef;
  if (!doc || typeof doc.createElement !== "function") return null;
  if (typeof globalThis.Path2D !== "function") return null;

  const geometry = brandGeometry(DEFAULT_MODULE_SIZE);
  const lockup = geometry.wordmark;
  // Aperture closed: the shader owns the aperture analytically, at any scale.
  const paths = lockupPaths(geometry, lockup, 0);

  const cap = options.textureSizeCap ?? MASK_MAX_WIDTH;
  const texWidth = Math.round(Math.min(MASK_MAX_WIDTH, Math.max(MASK_MIN_WIDTH, cap)));
  const padPx = Math.max(2, Math.round(texWidth * MASK_PADDING_FRACTION));
  const contentWidth = texWidth - 2 * padPx;
  const scale = contentWidth / lockup.width;
  const contentHeight = Math.round(lockup.height * scale);
  const texHeight = contentHeight + 2 * padPx;

  const canvas = doc.createElement("canvas");
  canvas.width = texWidth;
  canvas.height = texHeight;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;

  ctx.setTransform(scale, 0, 0, scale, padPx, padPx);
  ctx.fillStyle = "#ffffff";
  ctx.fill(new Path2D(paths.tiles));
  // Bodies union under the nonzero rule — an R's stem, bowl and leg overlap by design.
  ctx.globalCompositeOperation = "destination-out";
  ctx.fill(new Path2D(paths.bodies));
  ctx.globalCompositeOperation = "source-over";
  if (paths.counters !== "") ctx.fill(new Path2D(paths.counters));
  ctx.setTransform(1, 0, 0, 1, 0, 0);

  const image = ctx.getImageData(0, 0, texWidth, texHeight);
  const coverage = new Float32Array(texWidth * texHeight);
  for (let i = 0; i < coverage.length; i += 1) coverage[i] = image.data[i * 4 + 3] / 255;

  const blurRadius = Math.max(2, Math.round(contentHeight * MASK_BLUR_FRACTION));
  const pass = Math.max(1, Math.round(blurRadius / 2));
  const blurred = boxBlur(boxBlur(coverage, texWidth, texHeight, pass), texWidth, texHeight, pass);

  for (let i = 0; i < blurred.length; i += 1) {
    const value = Math.round(Math.min(1, Math.max(0, blurred[i])) * 255);
    image.data[i * 4] = value;
    image.data[i * 4 + 1] = value;
    image.data[i * 4 + 2] = value;
    image.data[i * 4 + 3] = 255;
  }
  ctx.putImageData(image, 0, 0);

  const texture = new CanvasTexture(canvas);
  texture.minFilter = LinearFilter;
  texture.magFilter = LinearFilter;
  texture.wrapS = ClampToEdgeWrapping;
  texture.wrapT = ClampToEdgeWrapping;
  texture.generateMipmaps = false;
  // A coverage field is data, not colour: no transfer function may be applied to it.
  texture.colorSpace = NoColorSpace;
  texture.needsUpdate = true;

  return {
    texture,
    lockupWidth: lockup.width,
    lockupHeight: lockup.height,
    padLockup: padPx / scale,
    oCenter: oTileCentre(geometry, lockup),
    restingInnerRadius: geometry.oRestingInnerRadius,
    edgeSoftness: MASK_EDGE_SOFTNESS,
    dispose() {
      texture.dispose();
      canvas.width = 0;
      canvas.height = 0;
    },
  };
}

/* ------------------------------------------------------------------ layout */

/**
 * How large the wordmark sits in the viewport.
 *
 * The values live in `LoaderScene`, not here: the same numbers drive the static fallback logo's
 * CSS, and the scene is the one place that can hand them to both the stylesheet and the shader.
 * Only the shape is declared here, so this module stays importable without pulling in React —
 * and, more to the point, so importing the scene never pulls in three.
 */
export type LoaderLogoSizing = {
  readonly wide: { readonly widthFraction: number; readonly heightFraction: number };
  readonly narrow: { readonly widthFraction: number; readonly heightFraction: number };
  /** Below this viewport width the narrow sizing applies. */
  readonly narrowBelowPx: number;
};

/** Clearance past the furthest viewport corner before the portal counts as fully open. */
const PORTAL_OVERSHOOT = 1.08;

/** Everything the shader needs to place the mark, in space units. */
export type LoaderLayout = {
  /** Mask rect: centre x, centre y, half width, half height. */
  readonly rect: readonly [number, number, number, number];
  readonly oCenter: readonly [number, number];
  readonly restingRadius: number;
  /** `uContentX`: maps mask u onto 0..1 across the wordmark row. */
  readonly contentX: readonly [number, number];
  /** Aperture scale at which the void has swallowed the whole viewport. */
  readonly portalScale: number;
};

/** Place the mark for a viewport, in the shader's space units. */
export function resolveLoaderLayout(
  mask: LoaderMask,
  logoSizing: LoaderLogoSizing,
  viewportWidth: number,
  viewportHeight: number,
): LoaderLayout {
  const height = Math.max(viewportHeight, 1);
  const width = Math.max(viewportWidth, 1);
  const sizing = width < logoSizing.narrowBelowPx ? logoSizing.narrow : logoSizing.wide;

  const contentAspect = mask.lockupWidth / mask.lockupHeight;
  const contentWidthPx = Math.min(
    width * sizing.widthFraction,
    height * sizing.heightFraction * contentAspect,
  );
  const pxPerUnit = contentWidthPx / mask.lockupWidth;

  const totalWidth = mask.lockupWidth + 2 * mask.padLockup;
  const totalHeight = mask.lockupHeight + 2 * mask.padLockup;
  const halfW = (totalWidth * pxPerUnit) / (2 * height);
  const halfH = (totalHeight * pxPerUnit) / (2 * height);

  // Lockup y runs down the page, space y runs up it.
  const oX = ((mask.oCenter[0] - mask.lockupWidth / 2) * pxPerUnit) / height;
  const oY = (-(mask.oCenter[1] - mask.lockupHeight / 2) * pxPerUnit) / height;
  const restingRadius = (mask.restingInnerRadius * pxPerUnit) / height;

  const contentStart = mask.padLockup / totalWidth;
  const contentSpan = mask.lockupWidth / totalWidth;

  const halfViewportX = width / height / 2;
  const halfViewportY = 0.5;
  let furthestCorner = 0;
  for (const cornerX of [-halfViewportX, halfViewportX]) {
    for (const cornerY of [-halfViewportY, halfViewportY]) {
      furthestCorner = Math.max(furthestCorner, Math.hypot(cornerX - oX, cornerY - oY));
    }
  }

  return {
    rect: [0, 0, halfW, halfH],
    oCenter: [oX, oY],
    restingRadius,
    contentX: [1 / contentSpan, -contentStart / contentSpan],
    portalScale: (furthestCorner * PORTAL_OVERSHOOT) / Math.max(restingRadius, 1e-6),
  };
}

/* ------------------------------------------------------------------ uniforms */

export type LoaderUniforms = Record<string, IUniform>;

/** Fresh uniforms per mount, so nothing leaks between loader instances. */
export function createLoaderUniforms(mask: LoaderMask): LoaderUniforms {
  return {
    uMask: { value: mask.texture },
    uResolution: { value: [1, 1] },
    uTime: { value: 0 },
    uMaterialize: { value: 0 },
    uSettle: { value: 0 },
    uAperture: { value: 1 },
    uPortal: { value: 0 },
    uFieldFade: { value: 1 },
    uSurface: { value: 0 },
    uSpecular: { value: 0 },
    uRefraction: { value: 0 },
    uGrain: { value: 0 },
    uDetail: { value: 1 },
    uLogoRect: { value: [0, 0, 0.25, 0.05] },
    uOCenter: { value: [0, 0] },
    uRestingRadius: { value: 0.02 },
    uEdgeSoftness: { value: MASK_EDGE_SOFTNESS },
    uContentX: { value: [1, 0] },
  };
}

/** The loader's per-frame inputs. Every value is choreography or capability — never scene state. */
export type LoaderFrame = {
  timeSeconds: number;
  resolution: readonly [number, number];
  layout: LoaderLayout;
  edgeSoftness: number;
  /** 0 -> 1: near-black shadow becomes realised material. */
  materialize: number;
  /** 0 -> 1: D/R/P calm down while the O pulse takes focus. */
  settle: number;
  /** Aperture scale. 1 rests; the pulse rides ~0.84..1.08; the portal drives it far past 1. */
  apertureScale: number;
  /** 0 -> 1: the aperture stops being off-white field and becomes a hole through the overlay. */
  portal: number;
  /** Overlay alpha multiplier. Held at 1: the brief forbids a loading-screen fade. */
  fieldFade: number;
  /** Travelling-highlight and surface-motion amount; 0 holds the material still. */
  life: number;
  settings: EffectiveRenderSettings;
};

function writeVec(uniforms: LoaderUniforms, name: string, values: readonly number[]): void {
  const target = uniforms[name]?.value as number[] | undefined;
  if (!Array.isArray(target)) return;
  for (let i = 0; i < values.length; i += 1) target[i] = values[i];
}

function writeNumber(uniforms: LoaderUniforms, name: string, value: number): void {
  const uniform = uniforms[name];
  if (uniform) uniform.value = value;
}

/** Push one frame of choreography into the uniforms. Mutates in place; allocates nothing. */
export function updateLoaderUniforms(uniforms: LoaderUniforms, frame: LoaderFrame): void {
  const { settings, layout } = frame;
  const detail = settings.shaderDetail;

  writeNumber(uniforms, "uTime", settings.animateShaders ? frame.timeSeconds : 0);
  writeNumber(uniforms, "uMaterialize", frame.materialize);
  writeNumber(uniforms, "uSettle", frame.settle);
  writeNumber(uniforms, "uAperture", frame.apertureScale);
  writeNumber(uniforms, "uPortal", frame.portal);
  writeNumber(uniforms, "uFieldFade", frame.fieldFade);
  writeNumber(uniforms, "uSurface", frame.life);
  writeNumber(uniforms, "uSpecular", frame.life);
  writeNumber(uniforms, "uRefraction", detail.refraction ? frame.life : 0);
  writeNumber(uniforms, "uGrain", detail.grain ? 1 : 0);
  writeNumber(uniforms, "uDetail", detail.noiseDetail === "full" ? 1 : 0);
  writeNumber(uniforms, "uRestingRadius", layout.restingRadius);
  writeNumber(uniforms, "uEdgeSoftness", frame.edgeSoftness);

  writeVec(uniforms, "uResolution", frame.resolution);
  writeVec(uniforms, "uLogoRect", layout.rect);
  writeVec(uniforms, "uOCenter", layout.oCenter);
  writeVec(uniforms, "uContentX", layout.contentX);
}
