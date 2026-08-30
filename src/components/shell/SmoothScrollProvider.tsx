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

import { useEffect, useRef, type ReactNode } from "react";
import Lenis from "lenis";

import { ScrollTrigger, attachRafDriver } from "@/lib/motion/gsap";

import styles from "./SmoothScrollProvider.module.css";
import { useReducedMotion } from "@/lib/motion/reduced-motion";

/* ------------------------------------------------------------------ the reveal */

/**
 * The beat between the O portal finishing and the page carrying itself into the first scene.
 *
 * Long enough that the portal reads as having completed and the background has settled behind it,
 * short enough that the reader is never left looking at an empty stage wondering whether the site
 * is finished loading.
 */
const REVEAL_DELAY_MS = 900;

/** How long that carry takes. Paced as a scene transition, not as a jump-to-anchor. */
const REVEAL_DURATION_S = 1.2;

/**
 * If the reader has already moved this far, the reveal is abandoned: they started reading on
 * their own and the page must not take the wheel back off them.
 */
const REVEAL_ABORT_PX = 8;

/** Reader input that cancels a pending reveal outright. */
const REVEAL_CANCEL_EVENTS = ["wheel", "touchstart", "keydown", "pointerdown"] as const;

/** Keys that scroll a document, which the loader lock must hold along with wheel and touch. */
const SCROLLING_KEYS = new Set([
  "PageDown",
  "PageUp",
  "ArrowDown",
  "ArrowUp",
  "Home",
  "End",
  " ",
]);

/** Where a scrolling key is the user typing, not the user scrolling. */
const isEditable = (target: EventTarget | null): boolean => {
  const element = target as HTMLElement | null;
  if (!element || !element.tagName) return false;
  if (element.isContentEditable) return true;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName);
};

/** Persian-first, like every other visible string in this app. */
const BACK_TO_TOP_LABEL = "بازگشت به بالا";

export type SmoothScrollProviderProps = {
  children: ReactNode;
  /**
   * Hold the document still. Driven by reducer output (`!transitionState.loaderComplete`), so the
   * lock releases on the same fact that ends the loader — never on a timer of its own.
   */
  locked?: boolean;
  /**
   * Selector for the element to carry the page to once the lock releases — the first scene with
   * something to read.
   *
   * The loader owns a scroll budget of its own, so when its portal opens the viewport is still on
   * the LOADER's section and what it opens onto is that section's now-empty stage: measured at
   * rest, the first line of the lens sat 457px below the fold and nothing was on screen but the
   * background. The portal is meant to be "a hole opening onto a page that was already there", so
   * the page brings that page to the reader rather than waiting to be scrolled.
   *
   * Omit it and nothing moves on its own.
   */
  revealTarget?: string | null;
};

export function SmoothScrollProvider({
  children,
  locked = false,
  revealTarget = null,
}: SmoothScrollProviderProps) {
  const reducedMotion = useReducedMotion();
  /** The live instance, so the reveal below scrolls THROUGH Lenis rather than around it. */
  const lenisRef = useRef<Lenis | null>(null);

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

    lenisRef.current = lenis;

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
      lenisRef.current = null;
    };
  }, [reducedMotion]);

  /**
   * The loader must open on the TOP of the page.
   *
   * Its logo is a MASK, not a picture: the dark tiles are holes onto whatever is mounted beneath
   * the overlay. That is the point — the portal is "a hole opening onto a page that was already
   * there" — but it means the loader shows whatever the document is scrolled to. At the top that
   * is the loader's own empty stage, which is what the tiles are supposed to read as.
   *
   * The browser's default `scrollRestoration: "auto"` breaks that on the very next reload: it
   * restores the position the page was left at, the loader plays over a document already scrolled
   * into the lens, and the first lines of the thesis appear INSIDE the logo tiles while the
   * sequence is still running. Observed exactly that, and it is also why a mid-page reload used
   * to hand the scene machine a scroll position its ScrollTriggers had not been built for.
   *
   * Taking restoration manual is the fix at its source: every load starts at the top, the loader
   * always opens onto the same thing, and the reveal below is what moves the reader afterwards.
   * Restored on teardown so the setting never outlives this page.
   */
  useEffect(() => {
    if (!("scrollRestoration" in history)) return;
    const previous = history.scrollRestoration;
    history.scrollRestoration = "manual";
    return () => {
      history.scrollRestoration = previous;
    };
  }, []);

  /**
   * Belt to those braces: a bfcache restore or a fragment entry can still hand the loader a
   * scrolled document, and the overlay would show the lens through its own logo. While the lock
   * is on, the page sits at the top — instantly, because this is a correction, not a movement
   * the reader should see.
   */
  useEffect(() => {
    if (!locked) return;
    if (window.scrollY === 0) return;
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [locked]);

  /**
   * Carry the page into the first readable scene once the loader lets go.
   *
   * Driven through `lenis.scrollTo` and not `window.scrollTo`: Lenis owns the scroll position and
   * only emits the scroll event `ScrollTrigger.update()` hangs off when it moves the page itself.
   * A native scroll here would slide the document while the scene-state machine stayed frozen on
   * the loader — the page would move and nothing would follow it.
   *
   * It yields to the reader completely. It never starts if they have already scrolled, any wheel,
   * touch, key or pointer cancels it before it fires, and `lock: false` leaves them free to take
   * over mid-flight. Under reduced motion it lands immediately: a cut, never a glide.
   */
  useEffect(() => {
    if (locked || !revealTarget) return;

    const lenis = lenisRef.current;
    const target = document.querySelector<HTMLElement>(revealTarget);
    if (!lenis || !target) return;
    if (window.scrollY > REVEAL_ABORT_PX) return;

    let settled = false;
    const teardown = () => {
      window.clearTimeout(timer);
      for (const type of REVEAL_CANCEL_EVENTS) window.removeEventListener(type, cancel);
    };

    /*
     * Yielding, not merely cancelling.
     *
     * The listeners used to be torn down the instant the tween started, so a key pressed DURING
     * the 1.2s carry was ignored: Lenis only adopts a native scroll while it is idle, and mid-tween
     * it rewrites the scroll position from its own animated value on the next tick. The reader
     * pressed Page Down and the page pulled itself back. Keeping the listeners live through the
     * tween and stopping Lenis on the first input hands the document straight back — stop()/start()
     * reset its animated and target scroll to wherever the key actually left it, so the next native
     * scroll is adopted normally.
     */
    const cancel = () => {
      if (settled) return;
      settled = true;
      teardown();
      lenis.stop();
      lenis.start();
    };

    const timer = window.setTimeout(() => {
      if (settled) return;
      if (window.scrollY > REVEAL_ABORT_PX) {
        settled = true;
        teardown();
        return;
      }
      lenis.scrollTo(target, {
        duration: REVEAL_DURATION_S,
        immediate: reducedMotion,
        lock: false,
        onComplete: () => {
          settled = true;
          teardown();
        },
      });
    }, REVEAL_DELAY_MS);

    for (const type of REVEAL_CANCEL_EVENTS) {
      window.addEventListener(type, cancel, { passive: true });
    }

    return teardown;
  }, [locked, revealTarget, reducedMotion]);

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
    /*
     * The lock blocked the wheel and touch but not the KEYBOARD, so Page Down during the loader
     * scrolled the document under the overlay and the portal opened on wherever it landed — the
     * exact defect the lock exists to prevent, reachable by anyone not using a mouse.
     *
     * Same rule as the others: block the INPUT, not the scroller. Only the keys that scroll, only
     * when the target is not something being typed into, and never Tab or Enter — so the skip link
     * stays reachable and the loader can never trap a keyboard user.
     */
    const blockKeys = (event: KeyboardEvent) => {
      if (!SCROLLING_KEYS.has(event.key)) return;
      if (isEditable(event.target)) return;
      event.preventDefault();
    };

    window.addEventListener("wheel", block, listen);
    window.addEventListener("touchmove", block, listen);
    window.addEventListener("keydown", blockKeys, listen);

    return () => {
      window.removeEventListener("wheel", block);
      window.removeEventListener("touchmove", block);
      window.removeEventListener("keydown", blockKeys);
    };
  }, [locked]);

  /*
   * The long-page escape.
   *
   * A 28-screen scroll needs a way out that is not "scroll all the way back". A real <button>
   * rather than an <a href="#top">, because the target is a scroll position rather than a
   * document fragment, and because a button inherits the page's existing focus ring with no new
   * CSS. It lives here because this component owns the Lenis instance — going through Lenis is
   * what keeps ScrollTrigger following the move, exactly as the reveal does.
   *
   * Rendered only once the loader has let go, so it is never a tab stop over the portal.
   */
  const backToTop = () => {
    const lenis = lenisRef.current;
    if (lenis) lenis.scrollTo(0, { duration: REVEAL_DURATION_S, lock: false });
    else window.scrollTo({ top: 0 });
  };

  return (
    <>
      {children}
      {!locked ? (
        <button
          type="button"
          className={styles.backToTop}
          data-back-to-top
          onClick={backToTop}
        >
          {BACK_TO_TOP_LABEL}
        </button>
      ) : null}
    </>
  );
}
