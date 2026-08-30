"use client";

/**
 * The single place gsap and ScrollTrigger are imported and registered.
 *
 * Brief Section 9 ("Motion System and State Architecture") forbids one giant timeline and
 * demands that timelines/triggers be killed on unmount or route change; BUILD-GUIDE's
 * standing engineering rules add "Lenis and GSAP share one RAF; never introduce a second
 * scroll or animation engine for the same interaction". Both of those are enforced here:
 *
 * - Every module that animates imports `gsap` / `ScrollTrigger` from THIS file, never from
 *   the packages directly, so the plugin is registered exactly once.
 * - The shell attaches Lenis (or any other raf consumer) with {@link attachRafDriver},
 *   which hangs off GSAP's existing ticker instead of starting a competing one.
 * - Scenes create their tweens/triggers inside a {@link createMotionScope} and call
 *   `revert()` on unmount, which kills everything created within that scope.
 *
 * Nothing here touches the DOM during server render: registration and scope creation are
 * no-ops wherever ScrollTrigger cannot run, and that pass simply gets an inert scope.
 *
 * The module is marked `"use client"` so gsap can never be pulled into a server bundle;
 * client components still evaluate it during SSR, which is why the guards above stay.
 */

import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

export { gsap, ScrollTrigger };

/**
 * True only where ScrollTrigger can actually run. Client components also evaluate during
 * SSR, and `ScrollTrigger.register()` immediately builds a `gsap.matchMedia()` — so a
 * DOM without `matchMedia` (jsdom, used by the Vitest seams) is as unusable as no DOM at
 * all. Every real browser we target has `matchMedia`.
 */
const canRegister = (): boolean =>
  typeof window !== "undefined" &&
  typeof document !== "undefined" &&
  typeof window.matchMedia === "function";

/**
 * Registration flag lives on `globalThis`, not in module scope, so a duplicated module
 * instance (HMR, a second bundle chunk) cannot register the plugin a second time.
 */
const REGISTRATION_FLAG = "__dropMotionPluginsRegistered";

type RegistrationHost = { [REGISTRATION_FLAG]?: boolean };

const registrationHost = (): RegistrationHost => globalThis as RegistrationHost;

/**
 * Register ScrollTrigger with GSAP. Idempotent, and a no-op wherever ScrollTrigger cannot
 * run (server render, jsdom).
 *
 * @returns whether the plugins are registered and safe to use.
 */
export function registerMotionPlugins(): boolean {
  const host = registrationHost();
  if (host[REGISTRATION_FLAG] === true) return true;
  if (!canRegister()) return false;

  try {
    gsap.registerPlugin(ScrollTrigger);
  } catch {
    // An environment that looks like a browser but cannot host ScrollTrigger must degrade
    // to the static fallback, never take a render down with it.
    return false;
  }
  host[REGISTRATION_FLAG] = true;
  return true;
}

/** Whether {@link registerMotionPlugins} has already run in this environment. */
export function motionPluginsRegistered(): boolean {
  return registrationHost()[REGISTRATION_FLAG] === true;
}

// Register as early as the module is evaluated in the browser, so importing `gsap` from
// here is always enough. The SSR pass falls through without touching the DOM.
registerMotionPlugins();

/**
 * A raf consumer driven by GSAP's ticker. Receives the tick time in **milliseconds**,
 * which is what Lenis's `raf(time)` expects (GSAP's own ticker reports seconds).
 */
export type RafDriver = (timeMs: number) => void;

/** GSAP's default lag smoothing, restored when the last driver detaches. */
const DEFAULT_LAG_SMOOTHING_THRESHOLD = 500;
const DEFAULT_LAG_SMOOTHING_ADJUSTED_LAG = 33;

let attachedDrivers = 0;

/**
 * Attach a raf driver (Lenis, in this project) to GSAP's ticker — the one ticker the whole
 * app shares. Lag smoothing is disabled while a driver is attached, per Lenis + ScrollTrigger
 * guidance, and restored when the last driver detaches.
 *
 * @returns a teardown that detaches the driver. Safe to call more than once.
 */
export function attachRafDriver(driver: RafDriver): () => void {
  if (!registerMotionPlugins()) {
    // Server render: nothing ticks, so the teardown has nothing to undo.
    return () => {};
  }

  const tick = (timeSeconds: number): void => {
    driver(timeSeconds * 1000);
  };

  gsap.ticker.add(tick);
  attachedDrivers += 1;
  gsap.ticker.lagSmoothing(0);

  let detached = false;
  return () => {
    if (detached) return;
    detached = true;
    gsap.ticker.remove(tick);
    attachedDrivers = Math.max(0, attachedDrivers - 1);
    if (attachedDrivers === 0) {
      gsap.ticker.lagSmoothing(
        DEFAULT_LAG_SMOOTHING_THRESHOLD,
        DEFAULT_LAG_SMOOTHING_ADJUSTED_LAG,
      );
    }
  };
}

/**
 * A cleanup scope. Every tween, timeline and ScrollTrigger created inside {@link MotionScope.run}
 * belongs to the scope; `revert()` kills all of them and undoes their DOM writes.
 *
 * Scenes own one of these each — no cross-scene timeline reach-ins, and no scene leaves
 * triggers behind on unmount or route change.
 */
export type MotionScope = {
  /** Run animation setup inside the scope. No-op where ScrollTrigger cannot run. */
  run: (setup: () => void) => void;
  /** Kill every trigger/tween created within the scope and revert its DOM writes. */
  revert: () => void;
  /** True once {@link MotionScope.revert} has run — and immediately true for an inert scope. */
  isReverted: () => boolean;
};

const inertScope: MotionScope = {
  run: () => {},
  revert: () => {},
  isReverted: () => true,
};

/**
 * Create a cleanup scope, optionally rooted at an element so scoped selector strings
 * ("`.card`") only match inside it.
 *
 * During server render this returns an inert scope, so callers can create it
 * unconditionally and still be SSR-safe.
 */
export function createMotionScope(root?: Element | string | object | null): MotionScope {
  if (!registerMotionPlugins()) return inertScope;

  // The setup function is NOT optional: `gsap.context(func, scope)` is
  // `func ? new Context(func, scope) : _context`, so a falsy first argument asks for the
  // CURRENTLY ACTIVE context — `undefined` outside one, whose `.add()` then throws on the first
  // client render. A no-op setup gives us the real, empty Context this scope wraps.
  const context = root == null ? gsap.context(() => {}) : gsap.context(() => {}, root);
  let reverted = false;

  return {
    run: (setup) => {
      if (reverted) return;
      context.add(setup);
    },
    revert: () => {
      if (reverted) return;
      reverted = true;
      context.revert();
    },
    isReverted: () => reverted,
  };
}

/**
 * Recalculate every ScrollTrigger's start/end positions — call after fonts and critical
 * assets load, and after any layout-changing content swap (brief Section 9).
 */
export function refreshScrollTriggers(): void {
  if (!motionPluginsRegistered()) return;
  ScrollTrigger.refresh();
}

/**
 * Number of live ScrollTriggers. Feeds the page seam's dev-only diagnostics object
 * (BUILD-GUIDE's escape hatch) so leak checks — "no accumulating ScrollTriggers after a
 * route round-trip", brief Section 17 — never have to reach into GSAP internals.
 */
export function getScrollTriggerCount(): number {
  if (!motionPluginsRegistered()) return 0;
  return ScrollTrigger.getAll().length;
}
