/**
 * `prefers-reduced-motion` detection.
 *
 * Brief Section 16: "Respect `prefers-reduced-motion` across every scene" and "Reduced motion
 * must not remove content or make the page unusable"; Section 14 fixes what reduced motion
 * means for the shared canvas — static backgrounds with brief crossfades. The rendering
 * consequences live in `@/lib/performance/quality-tier` (`resolveRenderSettings`); this module
 * only answers "is reduced motion requested, right now?".
 *
 * Reduced motion is a *separate axis* from the quality tier: a high-tier workstation can ask
 * for reduced motion, and a low-tier phone can ask for full motion.
 *
 * Everything here is SSR-safe. Before hydration there is no media query to read, so the
 * documented default — {@link REDUCED_MOTION_DEFAULT} — is returned instead of throwing.
 */

import { useSyncExternalStore } from "react";

/** The media query the whole app reads. */
export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

/**
 * Value returned when no media query is available (server render, and the first client
 * paint before hydration). Full motion is the design's default; a reduced-motion user gets
 * the simplified choreography the moment the store subscribes.
 */
export const REDUCED_MOTION_DEFAULT = false;

/** The slice of `MediaQueryList` this module needs, including the legacy Safari listener API. */
export type MediaQueryListLike = {
  matches: boolean;
  addEventListener?: (type: "change", listener: () => void) => void;
  removeEventListener?: (type: "change", listener: () => void) => void;
  /** Safari < 14 and other legacy engines. */
  addListener?: (listener: () => void) => void;
  removeListener?: (listener: () => void) => void;
};

/** Injection seam: anything that can answer a media query. `null` means "server render". */
export type MediaQueryScope = {
  matchMedia?: (query: string) => MediaQueryListLike;
};

/** The real browser scope, or `null` when there is no window. */
function browserScope(): MediaQueryScope | null {
  if (typeof window === "undefined") return null;
  return window as unknown as MediaQueryScope;
}

function queryList(scope: MediaQueryScope | null): MediaQueryListLike | null {
  if (!scope || typeof scope.matchMedia !== "function") return null;
  try {
    return scope.matchMedia(REDUCED_MOTION_QUERY);
  } catch {
    // A malformed-query throw must never take down a render.
    return null;
  }
}

/**
 * Read the current preference. Never throws, and returns {@link REDUCED_MOTION_DEFAULT}
 * when `window`/`matchMedia` are unavailable.
 */
export function prefersReducedMotion(
  scope: MediaQueryScope | null = browserScope(),
): boolean {
  const list = queryList(scope);
  if (!list) return REDUCED_MOTION_DEFAULT;
  return list.matches === true;
}

/**
 * Subscribe to preference changes.
 *
 * @returns a teardown that removes the listener. Always callable — including when there was
 *   no media query to listen to — and safe to call more than once.
 */
export function subscribeReducedMotion(
  listener: (enabled: boolean) => void,
  scope: MediaQueryScope | null = browserScope(),
): () => void {
  const list = queryList(scope);
  if (!list) return () => {};

  const handle = (): void => {
    listener(list.matches === true);
  };

  if (typeof list.addEventListener === "function") {
    list.addEventListener("change", handle);
    let stopped = false;
    return () => {
      if (stopped) return;
      stopped = true;
      list.removeEventListener?.("change", handle);
    };
  }

  if (typeof list.addListener === "function") {
    list.addListener(handle);
    let stopped = false;
    return () => {
      if (stopped) return;
      stopped = true;
      list.removeListener?.(handle);
    };
  }

  return () => {};
}

// Stable references for useSyncExternalStore — a new subscribe function on every render
// would resubscribe on every render.
const subscribe = (onStoreChange: () => void): (() => void) =>
  subscribeReducedMotion(() => {
    onStoreChange();
  });

const getSnapshot = (): boolean => prefersReducedMotion();

const getServerSnapshot = (): boolean => REDUCED_MOTION_DEFAULT;

/**
 * React binding for the preference. Returns {@link REDUCED_MOTION_DEFAULT} during server
 * render and on the hydration pass, then the live value.
 *
 * Client components only. The shell reads this once and feeds it into the scene-state
 * reducer as a `reducedMotion` input event, so scenes render from reducer output rather
 * than each subscribing separately.
 */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
