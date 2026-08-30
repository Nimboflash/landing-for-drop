"use client";

/**
 * The ONE place the scene-state reducer is driven (BUILD-GUIDE seam 2, ticket 03).
 *
 * ## One-way data flow — mandatory
 *
 * Per-scene ScrollTriggers created here are DUMB PROGRESS SOURCES. They know their own
 * `sceneId` and their own element, nothing else; every callback does the same thing —
 * dispatch `{ type: "scrollProgress", sceneId, progress }` into `sceneStateReducer`. Scenes and
 * the shared background canvas then render EXCLUSIVELY from the returned {@link SceneState}. No
 * scene computes its own scene id, background mode, or active index; a controller that merely
 * mirrored what scenes worked out independently would make the seam-2 tests meaningless.
 *
 * Discrete inputs (carousel keyboard/buttons/drag, the reduced-motion media query) go through
 * the very same `dispatch`, which is why the reducer's documented precedence — most recent
 * input wins — is the whole app's precedence.
 *
 * ## Trigger geometry and the hand-over rule
 *
 * Each scene's trigger spans `start: "top top"` → `end: "bottom bottom"`: the window in which
 * the section owns the viewport (exactly the sticky travel of a pinned scene). Consecutive
 * windows are separated by one viewport of scroll — the hand-over, where the outgoing scene
 * slides up and out while the incoming one slides in. Reversibility (brief §9) demands that
 * window resolve to the SAME state in both directions, so the rule is: the hand-over belongs to
 * the scene that just finished.
 *
 * - scrolling down out of scene k  → `onLeave`     → report (k, 1)
 * - scrolling up out of scene k    → `onLeaveBack` → report (k - 1, 1)   [k - 1 just finished]
 *
 * `SCENE_ORDER` is a static contract from the seam module, not derived state; consulting it to
 * name the previous scene is wiring, not a second state machine.
 *
 * ## Cleanup
 *
 * Every trigger is created inside one `gsap.context`; the effect's teardown reverts it, which
 * kills all of them on unmount and on route change (brief §9, §17: "No console errors, WebGL
 * warnings, or accumulating ScrollTriggers"). The dev-only diagnostics object below lets the page
 * seam check that without reaching into GSAP internals.
 *
 * NOTE — why not `createMotionScope()` from `@/lib/motion/gsap`: that helper builds its context
 * with `gsap.context(undefined, root)`, and GSAP reads a falsy first argument as "give me the
 * CURRENTLY ACTIVE context" (`context: (func, scope) => func ? new Context(func, scope) : _context`
 * in `gsap-core.js`). Outside a context that is `undefined`, so `scope.run()` throws
 * `Cannot read properties of undefined (reading 'add')` on the first client render. The fix is a
 * one-liner in that module (pass the setup function to `gsap.context`), and this hook should move
 * back onto it the moment it lands — the shape below is deliberately identical.
 */

import { useCallback, useEffect, useMemo, useRef, useReducer } from "react";

import {
  ScrollTrigger,
  getScrollTriggerCount,
  gsap,
  refreshScrollTriggers,
} from "@/lib/motion/gsap";
import { useReducedMotion } from "@/lib/motion/reduced-motion";
import {
  SCENE_ORDER,
  createInitialSceneState,
  sceneStateReducer,
  type InputEvent,
  type LensCounts,
  type SceneId,
  type SceneState,
} from "@/lib/scene";

/** Ref callback a scene section hands to the machine so its element can be observed. */
export type SceneSectionRef = (element: HTMLElement | null) => void;

export type SceneStateMachineOptions = {
  /** Counts from the validated lens (array lengths) — every count-driven slot reads these. */
  counts: LensCounts;
  /** `lens.contentMode`, surfaced in dev diagnostics so QA can see which pack is on screen. */
  contentMode?: string;
};

export type SceneStateMachine = {
  /** The single source of truth every scene and the canvas render from. */
  state: SceneState;
  /**
   * Route discrete input through the same reducer — carousel keyboard/buttons/drag today,
   * loader completion tomorrow. Stable across renders.
   */
  dispatch: (event: InputEvent) => void;
  /** Ref callback for a scene's section element. Stable per scene id. */
  registerScene: (sceneId: SceneId) => SceneSectionRef;
};

/**
 * Dev-build diagnostics (BUILD-GUIDE's sanctioned page-seam escape hatch).
 *
 * Live getters, so Playwright reads current values rather than a stale snapshot. Stripped from
 * production builds: `NODE_ENV` is inlined at build time, and `NEXT_PUBLIC_DROP_DIAGNOSTICS`
 * (unset by default) is the deliberate opt-in for a production build under test, so the whole
 * block dead-code-eliminates in a normal production bundle.
 */
export type SceneDiagnostics = {
  readonly scrollTriggerCount: number;
  readonly sceneId: SceneId;
  readonly sceneProgress: number;
  readonly backgroundMode: string;
  readonly reducedMotion: boolean;
  readonly contentMode: string | undefined;
  readonly sceneOrder: readonly SceneId[];
};

/** Global name the page seam reads. */
export const SCENE_DIAGNOSTICS_KEY = "__dropSceneDiagnostics";

type DiagnosticsHost = { [SCENE_DIAGNOSTICS_KEY]?: SceneDiagnostics };

const DIAGNOSTICS_ENABLED =
  process.env.NODE_ENV !== "production" ||
  process.env.NEXT_PUBLIC_DROP_DIAGNOSTICS === "1";

export function useSceneStateMachine({
  counts,
  contentMode,
}: SceneStateMachineOptions): SceneStateMachine {
  // `counts` is the reducer's third argument — data, not state. It is derived from the lens's
  // array lengths and is stable for as long as the lens is (routes key the shell by slug), so
  // closing over it here keeps `dispatch` stable without a ref.
  const [state, dispatch] = useReducer(
    (current: SceneState, event: InputEvent) => sceneStateReducer(current, event, counts),
    counts,
    createInitialSceneState,
  );

  // Latest state for the diagnostics getters, without making them a render dependency.
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  });

  /* ------------------------------------------------------------ scene elements */

  const elementsRef = useRef(new Map<SceneId, HTMLElement>());
  const refCallbacksRef = useRef(new Map<SceneId, SceneSectionRef>());

  const registerScene = useCallback((sceneId: SceneId): SceneSectionRef => {
    const existing = refCallbacksRef.current.get(sceneId);
    if (existing) return existing;

    const callback: SceneSectionRef = (element) => {
      if (element) elementsRef.current.set(sceneId, element);
      else elementsRef.current.delete(sceneId);
    };
    refCallbacksRef.current.set(sceneId, callback);
    return callback;
  }, []);

  /* --------------------------------------------------------- reduced motion */

  const reducedMotion = useReducedMotion();
  useEffect(() => {
    dispatch({ type: "reducedMotion", enabled: reducedMotion });
  }, [reducedMotion]);

  /* -------------------------------------------------------------- triggers */

  useEffect(() => {
    const elements = elementsRef.current;
    const created: ScrollTrigger[] = [];

    const report = (sceneId: SceneId, progress: number): void => {
      dispatch({ type: "scrollProgress", sceneId, progress });
    };

    // One context owns every trigger this hook creates; reverting it kills all of them.
    const context = gsap.context(() => {
      SCENE_ORDER.forEach((sceneId, index) => {
        const element = elements.get(sceneId);
        if (!element) return;

        // The scene that just finished when this one is left backwards (see hand-over rule).
        const previousSceneId = index > 0 ? SCENE_ORDER[index - 1] : null;

        created.push(
          ScrollTrigger.create({
            trigger: element,
            start: "top top",
            end: "bottom bottom",
            invalidateOnRefresh: true,
            onUpdate: (self) => report(sceneId, self.progress),
            onToggle: (self) => {
              if (self.isActive) report(sceneId, self.progress);
            },
            onLeave: () => report(sceneId, 1),
            onLeaveBack: () => {
              if (previousSceneId) report(previousSceneId, 1);
              else report(sceneId, 0);
            },
            onRefresh: (self) => {
              if (self.isActive) report(sceneId, self.progress);
            },
          }),
        );
      });
    });

    // Settle the machine against wherever the page actually is: a reload can restore scroll
    // mid-page, and ScrollTrigger does not fire a toggle for a trigger that starts active.
    const active = created.find((trigger) => trigger.isActive);
    if (active) {
      const sceneId = SCENE_ORDER.find((id) => elements.get(id) === active.trigger);
      if (sceneId) report(sceneId, active.progress);
    }

    // Brief §9: "Recalculate after fonts and critical assets load."
    let live = true;
    const refresh = (): void => {
      if (live) refreshScrollTriggers();
    };
    if (typeof document !== "undefined" && "fonts" in document) {
      void document.fonts.ready.then(refresh).catch(() => {});
    }
    if (document.readyState === "complete") refresh();
    else window.addEventListener("load", refresh);

    return () => {
      live = false;
      window.removeEventListener("load", refresh);
      context.revert();
    };
  }, []);

  /* ----------------------------------------------------------- diagnostics */

  useEffect(() => {
    if (!DIAGNOSTICS_ENABLED) return;

    const host = window as unknown as DiagnosticsHost;
    host[SCENE_DIAGNOSTICS_KEY] = {
      get scrollTriggerCount() {
        return getScrollTriggerCount();
      },
      get sceneId() {
        return stateRef.current.sceneId;
      },
      get sceneProgress() {
        return stateRef.current.sceneProgress;
      },
      get backgroundMode() {
        return stateRef.current.backgroundMode;
      },
      get reducedMotion() {
        return stateRef.current.reducedMotion;
      },
      get contentMode() {
        return contentMode;
      },
      get sceneOrder() {
        return SCENE_ORDER;
      },
    };

    return () => {
      delete host[SCENE_DIAGNOSTICS_KEY];
    };
  }, [contentMode]);

  return useMemo(
    () => ({ state, dispatch, registerScene }),
    [state, registerScene],
  );
}
