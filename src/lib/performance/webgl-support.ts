/**
 * WebGL capability detection and context-loss handling.
 *
 * Brief Section 15 ("Browser considerations"): "Provide a non-WebGL fallback when context
 * creation fails." Section 17 forbids console errors and WebGL warnings. A lost context
 * must therefore degrade to the styled static background a scene already ships for reduced
 * motion — never a blank page, never a thrown render.
 *
 * Two questions are answered here, and they are different:
 *   1. Can a context be created **at all**? (`supported`)
 *   2. Does it **survive** creation — a real, non-lost context that answers `getParameter`?
 *      Some environments hand back a context that is already lost or immediately unusable.
 *
 * SSR-safe: with no document, detection reports "unsupported, reason `no-document`" rather
 * than throwing. Callers that only render WebGL on the client should treat `no-document`
 * as "not yet known" (see `readDeviceSignals` in `./quality-tier`, which does exactly that).
 */

/** Why WebGL is unavailable, when it is. */
export type WebGLFailureReason =
  | "no-document"
  | "no-canvas"
  | "no-context"
  | "context-lost"
  | "threw";

export type WebGLSupport = {
  /** A context was created and survived. */
  supported: boolean;
  /** WebGL major version of the surviving context. */
  version: 2 | 1 | null;
  /**
   * Unmasked renderer string where the browser exposes it cheaply, else the masked one.
   * Consumed by the quality tier to spot software rasterisers.
   */
  renderer: string | null;
  failureReason: WebGLFailureReason | null;
};

/** Frozen "no WebGL here" result, used for every failure path. */
function unsupported(failureReason: WebGLFailureReason): WebGLSupport {
  return Object.freeze({
    supported: false,
    version: null,
    renderer: null,
    failureReason,
  });
}

/** The slice of `document` detection needs — injectable so tests never need a real DOM. */
export type DocumentLike = {
  createElement: (tagName: string) => unknown;
};

export type DetectWebGLOptions = {
  /**
   * Injected document. Pass `null` to simulate a server render. Omit the key entirely to
   * use the real document and the module-level cache.
   */
  document?: DocumentLike | null;
};

type MinimalRenderingContext = {
  getParameter: (parameter: number) => unknown;
  getExtension: (name: string) => unknown;
  isContextLost?: () => boolean;
  VERSION: number;
  RENDERER: number;
};

type LoseContextExtension = { loseContext: () => void };

type DebugRendererInfoExtension = { UNMASKED_RENDERER_WEBGL: number };

function realDocument(): DocumentLike | null {
  if (typeof document === "undefined") return null;
  return document as unknown as DocumentLike;
}

function isRenderingContext(value: unknown): value is MinimalRenderingContext {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as { getParameter?: unknown; getExtension?: unknown };
  return (
    typeof candidate.getParameter === "function" &&
    typeof candidate.getExtension === "function"
  );
}

function readRenderer(gl: MinimalRenderingContext): string | null {
  try {
    const debugInfo = gl.getExtension("WEBGL_debug_renderer_info");
    if (debugInfo && typeof debugInfo === "object") {
      const unmasked = (debugInfo as DebugRendererInfoExtension).UNMASKED_RENDERER_WEBGL;
      const value = gl.getParameter(unmasked);
      if (typeof value === "string" && value.length > 0) return value;
    }
    const masked = gl.getParameter(gl.RENDERER);
    return typeof masked === "string" && masked.length > 0 ? masked : null;
  } catch {
    return null;
  }
}

/**
 * Release a context we created only to probe it — or one a scene is disposing. Frees the
 * GPU resources immediately instead of waiting for GC (brief Section 17: "Dispose
 * geometries, materials, and textures on unmount").
 */
export function releaseWebGLContext(gl: unknown): void {
  if (!isRenderingContext(gl)) return;
  try {
    const lose = gl.getExtension("WEBGL_lose_context");
    if (lose && typeof lose === "object") {
      (lose as LoseContextExtension).loseContext();
    }
  } catch {
    // Extension unavailable: the context will be collected normally.
  }
}

function probe(doc: DocumentLike | null): WebGLSupport {
  if (!doc) return unsupported("no-document");

  let canvas: { getContext?: (id: string, attrs?: unknown) => unknown } | null = null;
  try {
    const created = doc.createElement("canvas");
    if (typeof created !== "object" || created === null) return unsupported("no-canvas");
    canvas = created as { getContext?: (id: string, attrs?: unknown) => unknown };
    if (typeof canvas.getContext !== "function") return unsupported("no-canvas");
  } catch {
    return unsupported("threw");
  }

  // `failIfMajorPerformanceCaveat` is deliberately NOT set: a software rasteriser is still
  // better than a blank scene, and the quality tier demotes it to "low" from the renderer
  // string instead.
  const attributes = { alpha: true, antialias: false, depth: false, stencil: false };
  const candidates: readonly { id: string; version: 2 | 1 }[] = [
    { id: "webgl2", version: 2 },
    { id: "webgl", version: 1 },
    { id: "experimental-webgl", version: 1 },
  ];

  for (const candidate of candidates) {
    let context: unknown;
    try {
      context = canvas.getContext(candidate.id, attributes);
    } catch {
      continue;
    }
    if (!isRenderingContext(context)) continue;

    // Does it survive? An already-lost context, or one that cannot answer a basic
    // parameter query, is not usable.
    try {
      if (typeof context.isContextLost === "function" && context.isContextLost()) {
        continue;
      }
      const version = context.getParameter(context.VERSION);
      if (typeof version !== "string" || version.length === 0) continue;
    } catch {
      continue;
    }

    const renderer = readRenderer(context);
    releaseWebGLContext(context);
    return Object.freeze({
      supported: true,
      version: candidate.version,
      renderer,
      failureReason: null,
    });
  }

  return unsupported("no-context");
}

let cached: WebGLSupport | null = null;

/**
 * Detect WebGL support. Creating a probe context is not free, so the result for the real
 * document is cached for the lifetime of the page.
 */
export function detectWebGLSupport(options: DetectWebGLOptions = {}): WebGLSupport {
  const usingRealDocument = !("document" in options);
  if (usingRealDocument && cached) return cached;

  const doc = usingRealDocument ? realDocument() : (options.document ?? null);
  const result = probe(doc);

  // Never cache a `no-document` verdict: on the server it means "not known yet", and the
  // same module instance would otherwise poison the browser answer under a shared runtime.
  if (usingRealDocument && result.failureReason !== "no-document") {
    cached = result;
  }
  return result;
}

/** Clear the cached probe result. */
export function resetWebGLSupportCache(): void {
  cached = null;
}

export type ContextLossHandlers = {
  /** The context was lost — swap to the scene's styled static background. */
  onLost?: () => void;
  /** The context came back — rebuild GPU resources and resume. */
  onRestored?: () => void;
};

export type ObserveContextLossOptions = {
  /**
   * Call `preventDefault()` on the loss event so the browser will attempt to restore the
   * context. Defaults to true; set false when the scene is being torn down anyway.
   */
  allowRestore?: boolean;
};

/** The slice of a canvas element this helper needs. */
export type ContextLossTarget = {
  addEventListener: (
    type: string,
    listener: (event: { preventDefault?: () => void }) => void,
  ) => void;
  removeEventListener: (
    type: string,
    listener: (event: { preventDefault?: () => void }) => void,
  ) => void;
};

/**
 * Watch a canvas for context loss/restore so a scene can fall back to a styled static
 * background instead of a blank page.
 *
 * @returns a teardown that removes both listeners. Always callable, including when there
 *   was no canvas to observe.
 */
export function observeContextLoss(
  canvas: ContextLossTarget | null | undefined,
  handlers: ContextLossHandlers,
  options: ObserveContextLossOptions = {},
): () => void {
  if (!canvas || typeof canvas.addEventListener !== "function") return () => {};
  const allowRestore = options.allowRestore !== false;

  const handleLost = (event: { preventDefault?: () => void }): void => {
    if (allowRestore) event.preventDefault?.();
    handlers.onLost?.();
  };
  const handleRestored = (): void => {
    handlers.onRestored?.();
  };

  canvas.addEventListener("webglcontextlost", handleLost);
  canvas.addEventListener("webglcontextrestored", handleRestored);

  let stopped = false;
  return () => {
    if (stopped) return;
    stopped = true;
    canvas.removeEventListener("webglcontextlost", handleLost);
    canvas.removeEventListener("webglcontextrestored", handleRestored);
  };
}
