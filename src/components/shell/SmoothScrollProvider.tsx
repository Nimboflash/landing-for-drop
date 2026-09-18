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
 * Neither `lenis.stop()` nor a plain preventDefault() is enough on its own. Under
 * `prefers-reduced-motion` smoothing is off and the browser scrolls natively regardless of
 * Lenis's state; with smoothing ON, Lenis handles the wheel itself and scrolls the document
 * programmatically, which preventDefault() does not touch. The lock therefore CAPTURES the
 * gesture and stops it propagating, which covers both paths without freezing the programmatic
 * scrolling the reveal and the skip link depend on.
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
/*
 * Short enough that the page does not read as stalled.
 *
 * This is a beat before the page carries the reader off the loader, so the handover is not
 * instant. 900ms was that beat measured against nothing else; stacked on the loader and the
 * carry and the opening line's fade it was a third of a second-and-a-half of dead time, on a
 * screen with nothing on it yet. A quarter second still reads as a beat rather than a cut.
 */
const REVEAL_DELAY_MS = 250;

/** How long that carry takes. Paced as a scene transition, not as a jump-to-anchor. */
/* The carry itself. Long enough to read as travel, short enough not to be a wait. */
const REVEAL_DURATION_S = 0.8;

/**
 * If the reader has already moved this far, the reveal is abandoned: they started reading on
 * their own and the page must not take the wheel back off them.
 */
const REVEAL_ABORT_PX = 8;

/** Reader input that cancels a pending reveal outright. */
const REVEAL_CANCEL_EVENTS = [
  "wheel",
  "touchstart",
  "keydown",
  "pointerdown",
] as const;

/**
 * How far the document may sit from where the carry believes it is before the carry gives up.
 *
 * Sub-pixel drift is normal — Lenis animates a float and the document rounds it — so this is a
 * tolerance, not an equality.
 */
const REVEAL_FOREIGN_SCROLL_PX = 24;

/**
 * How many of the carry's own recent positions a scroll report is allowed to be reporting.
 *
 * The tolerance above compares the document against where the carry is RIGHT NOW, which assumes
 * the browser reports scroll the instant it applies it. iOS Safari does not: measured on an
 * iPhone 17, the carry started, moved 219px and then cancelled itself and never moved again — the
 * reader was left on a blank screen with the first line of text 607px below the fold. Nobody had
 * touched anything. The carry covers ~1070px/s, so a scroll report only 25ms stale already reads
 * as 27px of divergence, and the guard meant to catch SOMEBODY ELSE moving the page was catching
 * the carry's own motion arriving late.
 *
 * So the document is checked against the positions the carry has recently HELD, not only its
 * newest one. Eight samples is roughly 130ms of history at a frame per scroll event — comfortably
 * past iOS's lag, and still nowhere near the reach of a real foreign scroll, which lands at a
 * position this tween was never heading for (a restored offset, a deep link, a test harness) and
 * is therefore outside the whole trail rather than behind its tip.
 */
const REVEAL_TRAIL_SAMPLES = 8;

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

    /* Where the carry has been, newest last — see REVEAL_TRAIL_SAMPLES. */
    const trail: number[] = [];
    const remember = (value: number) => {
      trail.push(value);
      if (trail.length > REVEAL_TRAIL_SAMPLES) trail.shift();
    };

    const teardown = () => {
      window.clearTimeout(timer);
      for (const type of REVEAL_CANCEL_EVENTS)
        window.removeEventListener(type, cancel);
      window.removeEventListener("scroll", onForeignScroll);
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
      /* The first report after the tween starts can still be describing the old position. */
      remember(lenis.animatedScroll);
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

    /*
     * A scroll this carry did not perform also cancels it.
     *
     * The four events above are the ways a READER takes the page. They are not the only ways the
     * page moves: the browser restores a scroll position on refresh and on back-navigation, and
     * anything driving the page programmatically — a deep link, a test harness — moves it without
     * any of them firing. Those all lost, and lost silently. The note above this effect explains
     * why: Lenis adopts a native scroll only while it is idle, and mid-tween it rewrites the
     * position from its own animated value on the next tick. So the page went where it was put
     * and was then quietly dragged back to the hero, with the scene machine still reporting the
     * loader — a reader who refreshed halfway down the page lost their place.
     *
     * `animatedScroll` is what the carry itself is doing, so comparing the document against it
     * separates our own motion from somebody else's without having to guess at intent.
     */
    const onForeignScroll = () => {
      if (settled) return;
      remember(lenis.animatedScroll);
      const here = window.scrollY;
      /* Ours if it matches ANY position the carry has recently held — see REVEAL_TRAIL_SAMPLES. */
      const ours = trail.some(
        (at) => Math.abs(here - at) <= REVEAL_FOREIGN_SCROLL_PX,
      );
      if (!ours) cancel();
    };
    window.addEventListener("scroll", onForeignScroll, { passive: true });

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
    /*
     * preventDefault() alone did NOT hold the page.
     *
     * It stops the BROWSER scrolling. It does not stop Lenis, which runs its own wheel
     * handler, reads the delta and then scrolls the document programmatically from its own
     * rAF loop. Lenis registers that handler when it is constructed, which is before this
     * effect ever runs, so it saw every event first and moved the page while the loader was
     * still up — the exact defect the lock exists to prevent, just by a different route.
     *
     * Capturing and stopping the event is what actually holds it: on the capture phase this
     * runs before any listener Lenis attached, and stopImmediatePropagation means Lenis never
     * receives the event at all. Note this still is not `lenis.stop()` — Lenis itself keeps
     * running, so the reveal, the skip link and a fragment entry can all still move the page
     * deliberately while the loader is on screen. The INPUT is blocked, not the scroller.
     */
    const block = (event: Event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
    };
    // Non-passive, or preventDefault() is ignored; capture, or Lenis gets there first.
    const listen: AddEventListenerOptions = { passive: false, capture: true };
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
      // The capture flag is part of a listener's identity: remove without it and the
      // listener stays attached, and the page is locked for the rest of the session.
      window.removeEventListener("wheel", block, listen);
      window.removeEventListener("touchmove", block, listen);
      window.removeEventListener("keydown", blockKeys, listen);
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
