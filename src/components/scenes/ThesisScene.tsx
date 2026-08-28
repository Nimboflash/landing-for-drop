"use client";

/**
 * The pinned lens thesis (brief §7.2, ticket 06).
 *
 * A minimal off-white stage: the lens identity, the hero messages replacing one another under
 * scroll, and — as the scene closes — the lens's full argument. The atmospheric glow at the lower
 * edge belongs to the shared canvas in `offWhiteGlow` mode; this scene never draws one, and the
 * Opacity hero reference's top-right "Join the waitlist" pill is exactly the furniture the brief
 * forbids (§7.2: "No button, CTA, nav group, or `Join the waitlist` element at the top-right").
 * Only the composition transfers: mark top-left, empty top-right, large centred type, deep air.
 *
 * ## This scene decides nothing
 *
 * `messageIndex` is scene-state reducer output (BUILD-GUIDE seam 2, one-way data flow). The scene
 * has no ScrollTrigger, computes no index, no scene progress and no background mode — it renders
 * the props it is handed and drives its choreography FROM them. That is what makes reverse scroll
 * correct by construction: the reducer walks the index back, and each index change plays the
 * mirrored transition (incoming from above, outgoing downward) from wherever the previous one
 * had got to.
 *
 * ## Two presentations, and why CSS never hides text
 *
 * | `data-presentation` | when | what it is |
 * | --- | --- | --- |
 * | `static` | server render, no JavaScript, pre-hydration | one readable editorial column: identity, every message, every statement |
 * | `stage` | after mount | the pinned composition: messages overlaid one at a time, the argument arriving as they retire |
 *
 * Brief §17 wants meaningful text server-rendered, and a JavaScript-disabled visitor has no
 * reducer to declare anything active — so the stylesheet's *default* state is the readable one and
 * every hiding decision is written after mount, by GSAP (per-message) or by the progress-driven
 * custom properties (the two layers). Nothing in this scene is ever hidden from assistive
 * technology: no `aria-hidden`, no `inert`, no `display: none`. A screen reader reads the whole
 * argument in order, exactly as the server sent it.
 *
 * ## Line masks, not typewriters
 *
 * Brief §7.2: "Each message enters through line masks: `yPercent`, opacity, and a small blur
 * resolving to sharp text. The outgoing message lifts and softens while the next replaces it.
 * Avoid typewriter effects and random letter animation." Each message's words are wrapped in a
 * clip box; the words are grouped into lines by measuring their offset at transition time, so a
 * whole line rises behind one continuous mask edge and the next line follows it. Nothing is
 * animated per letter, and no text is ever revealed character by character.
 *
 * The blur is a post-process: it is skipped on the `low` quality tier, whose settings turn
 * post-processing off (brief §14, "Low: … no expensive refraction, static/slow fallback"). The
 * masks and the lift still play; only the softening drops.
 *
 * ## Contrast
 *
 * WCAG AA over the live glow is an acceptance criterion, so every text colour here is `ink` or a
 * mix no lighter than {@link ThesisScene}'s stylesheet allows (≥ 74% of the scene's ink), and
 * partially-faded text is only ever a transient state between two AA-safe ends — the glow itself
 * is capped by the shader (see `OffWhiteGlowShader`, `GLOW_CEILING`) and confined to the lower
 * edge, well below the message stage.
 *
 * ## Observable state (BUILD-GUIDE seam 3)
 *
 * Unchanged from the shell placeholder this replaces — `data-lens-label`, `data-lens-title`,
 * `data-hero-messages`, `data-hero-message` + `data-index` + `data-active`, `data-lens-thesis`,
 * `data-lens-tension`, `data-lens-balance`, `data-lens-not-this` — plus `aria-current` on the
 * active message and `data-presentation` / `data-revealed` for the two presentation states.
 * Playwright asserts attributes and text only; the transforms below are the animation engine's
 * business and are never assertable.
 */

import {
  Fragment,
  useEffect,
  useRef,
  useSyncExternalStore,
  type CSSProperties,
} from "react";

import type { LocalizedText, WeeklyLens } from "@/content";
import { gsap } from "@/lib/motion/gsap";
import {
  QUALITY_TIER_SETTINGS,
  REDUCED_MOTION_CROSSFADE_SECONDS,
  detectEnvironmentQualityTier,
} from "@/lib/performance/quality-tier";

import styles from "./ThesisScene.module.css";

/* ------------------------------------------------------------------ tuning */

/**
 * The closing beat, as a window inside the FINAL message's share of the scene: the message stage
 * retires while the lens's four statements arrive in its place.
 *
 * Count-agnostic, and that is the whole point of expressing it as a fraction of a band rather
 * than as a fixed pair of thresholds. The reducer splits the thesis scene into one equal band per
 * hero message, so the last band opens at `1 - 1/count` — 0.667 for W04's three, 0.8 for a lens
 * with five. A fixed 0.78 would retire the stage while a five-message lens was still bringing its
 * fourth message in; a fraction of the last band cannot.
 *
 * Published because the integrator may want to pace the beat against the menu deck's entry ("The
 * final thesis text leaves" — brief §7.3), NOT as a value for a test to assert: scroll budgets and
 * thresholds are tunable by design, and seam-2 / seam-3 assertions stay ordinal (BUILD-GUIDE).
 * The band arithmetic is a FEEL-level reading of the reducer's pacing, never a contract — the
 * scene also gates the beat on the reducer's own index, so a future change to how the reducer
 * bands the scene could only change when the hand-over feels right, never let it happen under a
 * message that is still arriving.
 */
export const ARGUMENT_BAND_WINDOW: Readonly<{ from: number; to: number }> = Object.freeze({
  from: 0.45,
  to: 0.8,
});

/**
 * The opening line's entrance, played once when the page lands on this scene after the loader.
 *
 * Slower than a message swap on purpose: a swap is one line replacing another and wants to be
 * brisk, whereas this is the first thing the reader is shown after the portal and should settle
 * rather than snap. Opacity only — the words do not lift, so nothing competes with the page
 * arriving underneath it.
 */
const OPENING_ENTRY_SECONDS = 0.9;
const OPENING_ENTRY_EASE = "power2.out";

/** The closing beat's progress window for a lens holding `messageCount` hero messages. */
export function thesisArgumentWindow(messageCount: number): { start: number; end: number } {
  const count = Number.isFinite(messageCount) && messageCount >= 1 ? Math.floor(messageCount) : 1;
  const band = 1 / count;
  const lastBandStart = 1 - band;
  return {
    start: lastBandStart + band * ARGUMENT_BAND_WINDOW.from,
    end: lastBandStart + band * ARGUMENT_BAND_WINDOW.to,
  };
}

/** Reduced motion steps across the window's midpoint instead of scrubbing through it. */
function argumentStepAt(messageCount: number): number {
  const { start, end } = thesisArgumentWindow(messageCount);
  return (start + end) / 2;
}

/** Entry: weighted and cinematic (brief §9), never a bouncy app spring. */
const ENTER_DURATION_S = 0.92;
/** The fade/de-blur resolves a little before the lines land, so the text reads sharp on arrival. */
const ENTER_FADE_RATIO = 0.8;
/** Leaving is quicker than arriving: a retreat, not a second performance. */
const EXIT_DURATION_S = 0.56;
/** The incoming message starts while the outgoing one is still lifting — they overlap, never cut. */
const ENTER_OFFSET_S = 0.16;
/** Per-line delay. Whole lines move together; this is what makes it read as a line mask. */
const ENTER_LINE_STAGGER_S = 0.085;
const EXIT_LINE_STAGGER_S = 0.04;
/** How far below its mask a line waits, as a percentage of its own height. */
const ENTER_Y_PERCENT = 132;
/** How far the outgoing line lifts before it is gone. */
const EXIT_Y_PERCENT = 78;
/** "a small blur resolving to sharp text" — small is the operative word. */
const ENTER_BLUR_PX = 9;
const EXIT_BLUR_PX = 7;
/** `power4.out` is GSAP's read of `--ease-cinematic` (cubic-bezier(0.22, 1, 0.36, 1)). */
const ENTER_EASE = "power4.out";
const ENTER_FADE_EASE = "power2.out";
const EXIT_EASE = "power2.in";
/** Two words sit on the same line when their offsets agree to within this many pixels. */
const LINE_EPSILON_PX = 2;

/* ------------------------------------------------------------ presentation */

/**
 * Has the scene hydrated?
 *
 * The stage is a client-only presentation: the server cannot know which message the reducer will
 * call active, so it renders the readable static column and the stage takes over once React is
 * driving. `useSyncExternalStore` is the SSR-correct way to ask — the server snapshot is `false`,
 * the hydration pass matches it, and the client snapshot flips it afterwards. A store that never
 * changes needs no subscription, so these three are module-level constants (a new `subscribe`
 * identity on every render would resubscribe on every render).
 */
const subscribeToNothing = (): (() => void) => () => {};
const stagedOnClient = (): boolean => true;
const stagedOnServer = (): boolean => false;

/* ------------------------------------------------------------------- pure */

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

/** The reducer's index, defended against an empty or shorter `heroMessages` array. */
function clampIndex(index: number, count: number): number {
  if (count <= 0) return 0;
  if (!Number.isFinite(index)) return 0;
  const rounded = Math.round(index);
  if (rounded < 0) return 0;
  if (rounded > count - 1) return count - 1;
  return rounded;
}

/**
 * How far the closing beat has come, 0..1. Smoothstepped, so it has zero slope at both ends of
 * {@link thesisArgumentWindow} and neither the retire nor the arrival shows an edge.
 */
export function argumentReveal(progress: number, messageCount: number): number {
  const { start, end } = thesisArgumentWindow(messageCount);
  const value = clamp01(progress);
  if (value <= start) return 0;
  if (value >= end) return 1;
  const t = (value - start) / (end - start);
  return t * t * (3 - 2 * t);
}

/**
 * Split a message into words for the line masks.
 *
 * Whitespace only — Persian words keep their internal shaping (including ZWNJ), and the element's
 * text content is unchanged, so text assertions and screen readers read the original sentence.
 */
function splitWords(text: string): string[] {
  return text.split(/\s+/u).filter((word) => word.length > 0);
}

/** English where the data has it, Persian otherwise — never an empty slot (brief §11). */
function englishOr(text: LocalizedText): string {
  return text.en ?? text.fa;
}

/* -------------------------------------------------------------- measuring */

function wordsOf(message: HTMLElement): HTMLElement[] {
  return Array.from(message.querySelectorAll<HTMLElement>("[data-hero-word]"));
}

/**
 * Which line each word landed on, by measuring where the browser actually broke the sentence.
 * Read at transition time rather than cached: the line count changes with the viewport, the font
 * and the message, and one layout read per message change is cheaper than watching for all three.
 */
function lineIndexes(words: readonly HTMLElement[]): number[] {
  const tops: number[] = [];
  return words.map((word) => {
    const top = word.offsetTop;
    const existing = tops.findIndex((known) => Math.abs(known - top) <= LINE_EPSILON_PX);
    if (existing >= 0) return existing;
    tops.push(top);
    return tops.length - 1;
  });
}

/* -------------------------------------------------------------- component */

export interface ThesisSceneProps {
  /** The validated lens. Every string on screen comes from here; nothing is written into this file. */
  lens: WeeklyLens;
  /**
   * The reducer's `transitionState.messageIndex` — which of `lens.heroMessages` is current.
   * Count-agnostic: the scene animates whatever index it is handed, for a lens of any length.
   */
  messageIndex: number;
  /** The reducer's `sceneProgress` for this scene, 0..1. Drives the closing beat, nothing else. */
  progress: number;
  /** The reducer's reduced-motion flag: messages swap by a plain crossfade, all readable. */
  reducedMotion: boolean;
  /**
   * Has the page actually reached this scene?
   *
   * The first message used to be ASSERTED visible the moment the scene mounted — which happens
   * while the thesis is still below the fold, behind the loader. It was therefore already on
   * screen, fully opaque, before the reader ever arrived, so the opening line did not enter: it
   * was simply found. Held at zero until this turns true, it fades in as the page lands on it.
   *
   * Defaults to `true` so a caller that does not care keeps the old behaviour.
   */
  revealed?: boolean;
}

export function ThesisScene({
  lens,
  messageIndex,
  progress,
  reducedMotion,
  revealed = true,
}: ThesisSceneProps) {
  const messages = lens.heroMessages;
  const activeIndex = clampIndex(messageIndex, messages.length);

  const rootRef = useRef<HTMLDivElement | null>(null);
  const messageRefs = useRef<Array<HTMLParagraphElement | null>>([]);
  const contextRef = useRef<gsap.Context | null>(null);
  const timelineRef = useRef<gsap.core.Timeline | null>(null);
  const previousIndexRef = useRef(activeIndex);
  /** Has a message state been written yet? The first write is instant; later ones animate. */
  const appliedRef = useRef(false);
  /** The opening line enters once. After that a message change is an ordinary crossfade. */
  const openingEntryPendingRef = useRef(true);
  /**
   * The message the live timeline is retiring. Reverse scroll mid-transition hands the stage
   * straight back to it, and knowing that is what lets the new timeline pick it up where the
   * interrupted one left it instead of snapping it back to the entry mark.
   */
  const retiringRef = useRef<HTMLElement | null>(null);
  /** Whether this device can afford the blur (brief §14: low tier drops post-processing). */
  const softenRef = useRef(true);

  /** Pre-hydration renders the readable static column; the stage is a client-only presentation. */
  const staged = useSyncExternalStore(subscribeToNothing, stagedOnClient, stagedOnServer);

  /**
   * One motion context for the scene's whole lifetime. Reverting it on unmount kills every tween
   * created through it and undoes the inline styles they wrote (brief §9, §17: no accumulating
   * triggers, no leaked animation state on route change).
   *
   * `gsap.context(noop, root)` rather than `createMotionScope(root)`: that helper currently builds
   * its context as `gsap.context(undefined, root)`, and GSAP reads a falsy first argument as "give
   * me the CURRENTLY ACTIVE context" (`context: (func, scope) => func ? new Context(func, scope) :
   * _context`), which is `undefined` outside one — the same reason `useSceneStateMachine` uses
   * `gsap.context` directly. The shape is deliberately identical to the helper's, so this moves
   * back onto it the moment that one-liner lands.
   */
  useEffect(() => {
    softenRef.current =
      QUALITY_TIER_SETTINGS[detectEnvironmentQualityTier()].shaderDetail.postProcessing;

    const context = gsap.context(() => {}, rootRef.current ?? undefined);
    contextRef.current = context;

    return () => {
      timelineRef.current?.kill();
      timelineRef.current = null;
      context.revert();
      contextRef.current = null;
      appliedRef.current = false;
      retiringRef.current = null;
    };
  }, []);

  /**
   * The message transition, driven by the reducer's index and nothing else.
   *
   * Forward (index up) brings the next message in from below and lifts the current one away;
   * reverse (index down) mirrors both. Every message that is part of neither side is parked in
   * the rest state first, so a rapid scroll can never leave a third message stranded half-lit.
   * The two that ARE part of the swap keep what the interrupted timeline had reached: the exit
   * tweens from wherever the message currently sits, and a message caught mid-exit by a
   * direction flip is picked back up instead of being snapped to its entry mark.
   */
  useEffect(() => {
    if (!staged) return;
    const context = contextRef.current;
    const elements = messageRefs.current;
    const incoming = elements[activeIndex] ?? null;
    if (!context || !incoming) return;

    const previousIndex = previousIndexRef.current;
    previousIndexRef.current = activeIndex;
    const first = !appliedRef.current;
    appliedRef.current = true;

    const outgoing = first || previousIndex === activeIndex ? null : elements[previousIndex] ?? null;
    const soften = softenRef.current && !reducedMotion;
    // Ties (a reduced-motion toggle, a re-entry at the same index) read as forward.
    const direction = activeIndex >= previousIndex ? 1 : -1;

    /*
     * Reverse scroll must reverse "cleanly at any point" (ticket 06) — including the point
     * halfway through a transition, which is where a naive `fromTo` betrays itself: the message
     * that was lifting away is asked to come back, and jumping it to the entry mark first would
     * read as a stutter at exactly the moment the user changed their mind. Read while the old
     * timeline is still alive, because the first thing the new one does is kill it.
     */
    const resumeIncoming = timelineRef.current?.isActive() === true && incoming === retiringRef.current;
    retiringRef.current = outgoing;

    context.add(() => {
      timelineRef.current?.kill();
      timelineRef.current = null;

      for (const element of elements) {
        if (!element || element === incoming || element === outgoing) continue;
        gsap.set(element, { opacity: 0, clearProps: "filter" });
        gsap.set(wordsOf(element), { yPercent: 0 });
      }

      if (!outgoing) {
        gsap.set(wordsOf(incoming), { yPercent: 0 });

        // Not arrived yet: hold the opening line at zero rather than leaving it waiting on screen.
        if (!revealed) {
          gsap.set(incoming, { opacity: 0, clearProps: "filter" });
          return;
        }

        // The page has just landed on the scene: the opening line ENTERS, once.
        if (openingEntryPendingRef.current) {
          openingEntryPendingRef.current = false;
          gsap.set(incoming, { clearProps: "filter" });
          if (reducedMotion) {
            gsap.set(incoming, { opacity: 1 });
            return;
          }
          const entry = gsap.timeline();
          timelineRef.current = entry;
          entry.fromTo(
            incoming,
            { opacity: 0 },
            { opacity: 1, duration: OPENING_ENTRY_SECONDS, ease: OPENING_ENTRY_EASE },
          );
          return;
        }

        // Any later re-render that did not move the index: assert the rest state.
        gsap.set(incoming, { opacity: 1, clearProps: "filter" });
        return;
      }

      const timeline = gsap.timeline({ defaults: { overwrite: "auto" } });
      timelineRef.current = timeline;

      if (reducedMotion) {
        // Brief §7.2 reduced motion: a simple crossfade. No lift, no mask, no blur — and the
        // words stay put, so nothing moves on screen at all.
        gsap.set(wordsOf(outgoing), { yPercent: 0 });
        gsap.set(wordsOf(incoming), { yPercent: 0 });
        const fade = { duration: REDUCED_MOTION_CROSSFADE_SECONDS, ease: "none" } as const;
        timeline.to(outgoing, { opacity: 0, ...fade }, 0);
        if (resumeIncoming) {
          timeline.to(incoming, { opacity: 1, ...fade }, 0);
        } else {
          timeline.fromTo(incoming, { opacity: 0 }, { opacity: 1, ...fade }, 0);
        }
        return;
      }

      const outgoingWords = wordsOf(outgoing);
      const incomingWords = wordsOf(incoming);
      const outgoingLines = lineIndexes(outgoingWords);
      const incomingLines = lineIndexes(incomingWords);

      timeline.to(
        outgoing,
        {
          opacity: 0,
          ...(soften ? { filter: `blur(${EXIT_BLUR_PX}px)` } : null),
          duration: EXIT_DURATION_S,
          ease: EXIT_EASE,
        },
        0,
      );

      if (outgoingWords.length > 0) {
        timeline.to(
          outgoingWords,
          {
            yPercent: -direction * EXIT_Y_PERCENT,
            duration: EXIT_DURATION_S,
            ease: EXIT_EASE,
            stagger: (index) => (outgoingLines[index] ?? 0) * EXIT_LINE_STAGGER_S,
          },
          0,
        );
      }

      /*
       * A resumed entry starts immediately: the message is already part-way on stage, so making
       * it wait out the overlap offset again would leave the stage empty for a beat.
       */
      const enterAt = resumeIncoming ? 0 : ENTER_OFFSET_S;

      const enterFade: gsap.TweenVars = {
        opacity: 1,
        ...(soften ? { filter: "blur(0px)" } : null),
        duration: ENTER_DURATION_S * ENTER_FADE_RATIO,
        ease: ENTER_FADE_EASE,
        // Sharp text is not "blur(0px)" text: drop the filter once it has resolved, so the
        // resting message costs no filter pass at all.
        onComplete: () => {
          gsap.set(incoming, { clearProps: "filter" });
        },
      };

      if (resumeIncoming) {
        timeline.to(incoming, enterFade, enterAt);
      } else {
        timeline.fromTo(
          incoming,
          { opacity: 0, ...(soften ? { filter: `blur(${ENTER_BLUR_PX}px)` } : null) },
          enterFade,
          enterAt,
        );
      }

      if (incomingWords.length > 0) {
        const enterLines: gsap.TweenVars = {
          yPercent: 0,
          duration: ENTER_DURATION_S,
          ease: ENTER_EASE,
          stagger: (index: number) => (incomingLines[index] ?? 0) * ENTER_LINE_STAGGER_S,
        };
        if (resumeIncoming) {
          timeline.to(incomingWords, enterLines, enterAt);
        } else {
          timeline.fromTo(
            incomingWords,
            { yPercent: direction * ENTER_Y_PERCENT },
            enterLines,
            enterAt,
          );
        }
      }
    });
  }, [activeIndex, reducedMotion, revealed, staged, messages.length]);

  /* ------------------------------------------------------------- rendering */

  const sceneProgress = clamp01(progress);
  /*
   * The closing beat exists only once the reducer says the LAST message is the active one: the
   * gate is reducer output, the ramp is the progress the reducer hands down, and both are pure
   * functions of props — so the beat reverses exactly as it played, from any point.
   */
  const lastMessageActive = activeIndex >= messages.length - 1;
  const reveal = !lastMessageActive
    ? 0
    : reducedMotion
      ? sceneProgress >= argumentStepAt(messages.length)
        ? 1
        : 0
      : argumentReveal(sceneProgress, messages.length);
  const retired = reveal >= 1;

  const style: ThesisStyle = {
    // The identity's drift is motion; reduced motion holds it still (the stylesheet's media query
    // is the authority, this only keeps the value honest).
    "--drop-thesis-progress": (reducedMotion ? 0 : sceneProgress).toFixed(3),
    "--drop-argument-reveal": reveal.toFixed(3),
  };

  return (
    <div
      ref={rootRef}
      className={styles.thesis}
      style={style}
      data-thesis-scene
      data-presentation={staged ? "stage" : "static"}
    >
      <div className={styles.identity}>
        {/* Brief §7.2: the optional small English lens label. Week and title, both from data. */}
        <p className={styles.label} data-lens-label lang="en" dir="ltr">
          {lens.week} / {englishOr(lens.title)}
        </p>
        <h1 className={styles.title} data-lens-title dir="rtl">
          {lens.title.fa}
        </h1>
      </div>

      <div className={styles.stack}>
        <div
          className={`${styles.layer} ${styles.messages}`}
          data-hero-messages
          data-retired={retired}
        >
          {messages.map((message, index) => {
            const active = index === activeIndex;
            return (
              <p
                key={index}
                ref={(element) => {
                  messageRefs.current[index] = element;
                }}
                className={styles.message}
                dir="rtl"
                data-hero-message
                data-index={index}
                data-active={active}
                aria-current={active ? "true" : undefined}
              >
                {splitWords(message.fa).map((word, wordIndex) => (
                  <Fragment key={wordIndex}>
                    {wordIndex > 0 ? " " : null}
                    <span className={styles.word}>
                      <span className={styles.wordInner} data-hero-word>
                        {word}
                      </span>
                    </span>
                  </Fragment>
                ))}
              </p>
            );
          })}
        </div>

        {/*
          The lens's argument, arriving as the excerpts retire. The hero messages are drawn from
          these statements in the seed content, so holding both on screen at once would read as a
          duplicate — the closing beat hands the stage from one to the other instead.
        */}
        <div
          className={`${styles.layer} ${styles.argument}`}
          data-lens-argument
          data-revealed={retired}
        >
          <p className={styles.statement} dir="rtl" data-lens-thesis>
            {lens.thesis.fa}
          </p>
          <p className={styles.statement} dir="rtl" data-lens-tension>
            {lens.tension.fa}
          </p>
          <p className={styles.statement} dir="rtl" data-lens-balance>
            {lens.balance.fa}
          </p>
          <p className={styles.statement} dir="rtl" data-lens-not-this>
            {lens.notThis.fa}
          </p>
        </div>
      </div>
    </div>
  );
}

/** The two custom properties the stylesheet reads for the closing beat. */
type ThesisStyle = CSSProperties & {
  "--drop-thesis-progress": string;
  "--drop-argument-reveal": string;
};

export default ThesisScene;
