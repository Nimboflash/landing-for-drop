"use client";

/**
 * Lenis smooth scrolling, wired into GSAP's single ticker.
 *
 * BUILD-GUIDE standing rule: "Lenis and GSAP share one RAF; never introduce a second scroll or
 * animation engine for the same interaction." That is enforced structurally here — the only
 * loop Lenis is driven by is {@link attachRafDriver}, which hangs off GSAP's existing ticker.
 * `autoRaf: false` makes sure Lenis never starts its own `requestAnimationFrame` loop, and every
 * scroll event immediately re-runs `ScrollTrigger.update()` so the scene-state machine reads the
 * smoothed position rather than the raw one.
 *
 * Brief §9: "No scroll-jacking that ignores the user's wheel/touch momentum." So `syncTouch`
 * stays off — touch keeps the platform's own momentum, and only the wheel is smoothed — and
 * under `prefers-reduced-motion` smoothing is disabled outright: the page then scrolls exactly
 * as the browser would (brief §16), while everything else on the page still works.
 *
 * Teardown removes the scroll listener, detaches the raf driver (restoring GSAP's lag smoothing)
 * and destroys the Lenis instance, so a route change leaves nothing running.
 *
 * ## The loader lock
 *
 * While the entry loader owns the viewport the document must not scroll. The brief keeps the page
 * mounted beneath the loader "to prevent a layout jump" (§7.1) — as scenery, not as a live scroll
 * surface. Without a lock, a wheel flick during the ~3.2s loader scrolls the document underneath
 * the overlay and the O portal opens onto wherever the user landed, skipping the thesis, menu
 * deck, grid statement and pixel A: four of the ten scenes in brief §6's fixed sequence.
 *
 * `lenis.stop()` alone is not enough. Under `prefers-reduced-motion` smoothing is off, so the
 * wheel is never intercepted and the browser scrolls natively regardless of Lenis's state — which
 * is exactly the path a motion-sensitive visitor takes. The non-passive wheel/touch listeners are
 * what actually hold the page still on that path.
 */

import { useEffect, type ReactNode } from "react";
import Lenis from "lenis";

import { ScrollTrigger, attachRafDriver } from "@/lib/motion/gsap";
import { useReducedMotion } from "@/lib/motion/reduced-motion";

export type SmoothScrollProviderProps = {
  children: ReactNode;
  /**
   * Hold the document still. Driven by reducer output (`!transitionState.loaderComplete`), so the
   * lock releases on the same fact that ends the loader — never on a timer of its own.
   */
  locked?: boolean;
};

export function SmoothScrollProvider({ children, locked = false }: SmoothScrollProviderProps) {
  const reducedMotion = useReducedMotion();

  useEffect(() => {
    const lenis = new Lenis({
      // GSAP's ticker is the only loop in this app.
      autoRaf: false,
      // Reduced motion: no smoothing at all, native 1:1 scrolling.
      smoothWheel: !reducedMotion,
      // Native touch momentum stays with the platform — never re-simulated.
      syncTouch: false,
      // Belt and braces: Lenis also watches the media query itself.
      respectReducedMotion: true,
    });

    const stopScrollSync = lenis.on("scroll", () => {
      ScrollTrigger.update();
    });
    const detachRafDriver = attachRafDriver((timeMs) => {
      lenis.raf(timeMs);
    });

    return () => {
      stopScrollSync();
      detachRafDriver();
      lenis.destroy();
    };
  }, [reducedMotion]);

  useEffect(() => {
    if (!locked) return;

    /*
     * Block the INPUT, not the scroller.
     *
     * `lenis.stop()` looks like the obvious lock, but it also freezes PROGRAMMATIC scrolling — and
     * a fragment entry (`/#scene-tracks`), a browser-restored reload and the skip link all move
     * the page deliberately while the loader is still on screen. Freezing those overrides an
     * intentional landing position instead of protecting it.
     *
     * Preventing the wheel and touch gestures stops exactly the thing that caused the defect (a
     * flick during the ~3.2s loader carrying the document past four scenes) and nothing else.
     */
    const block = (event: Event) => event.preventDefault();
    // Non-passive, or preventDefault() is ignored and the page scrolls anyway.
    const listen: AddEventListenerOptions = { passive: false };
    window.addEventListener("wheel", block, listen);
    window.addEventListener("touchmove", block, listen);

    return () => {
      window.removeEventListener("wheel", block);
      window.removeEventListener("touchmove", block);
    };
  }, [locked]);

  return <>{children}</>;
}
