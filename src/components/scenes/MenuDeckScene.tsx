"use client";

/**
 * The menu deck — the taste edit as a physical deck of cards (brief §7.3, ticket 07).
 *
 * A compressed stack rises from below centre and fans into small rotations with the CARD BACKS
 * facing us; then the cards are DEALT out of it one at a time, each turning over in 3D as it
 * travels so that it reaches its place in the composition already showing a real menu item.
 * Every word and every image comes from {@link MenuDeckSceneProps.items}; the count comes from
 * that array's length, and nothing in this file knows what a fruit tart is.
 *
 * ## What is deliberately NOT here
 *
 * `handoff/03-layout/menu-card-front-reference.png` is a commerce card: rounded corners, a
 * heart/like button, a price and a cart button. `menu-card-back-reference.png` is a rounded
 * white card carrying a service list. **None of that ships.** The brief's card front is "one
 * product image, menu item name, maker/partner name, optional small category label" followed by
 * a list of prohibitions — "No description paragraph on the card. No price. No purchase button.
 * No cart. No like/favorite icon." — and the brief's card back is "pure/near black, centered
 * white English DROP primary logo, no additional copy, sharp corners". What transfers from the
 * references is the composition skeleton only: an image over a name/maker block on the front,
 * one identity mark centred on the back. Corners are square everywhere (CLAUDE.md hard rule).
 *
 * The item's selection rationale is real lens content (brief §5), so it stays in the scene and
 * in the accessibility tree — but off the card, where the brief forbids the paragraph.
 *
 * ## This scene decides nothing
 *
 * No ScrollTrigger, no progress of its own, no active index, no background mode: the scene-state
 * reducer already decided all of that (BUILD-GUIDE seam 2, one-way data flow). `flippedCards`
 * says how many cards are face-up; `progress` says how far the deck scene has scrubbed. GSAP
 * appears here for PRESENTATION ONLY — the staggered flip and the desktop pointer tilt — inside
 * a motion context reverted on unmount, so nothing is left ticking and no trigger accumulates.
 *
 * Because both inputs are pure functions of scroll, reverse scroll walks them back: cards
 * un-flip in the reverse of the order they flipped, the fan closes, and the stack drops back
 * below the viewport. Reversibility is structural here, not a second animation.
 *
 * The deal and the turn are carved out of the reducer's OWN bands (see {@link deckBands}), so
 * "the scene decides nothing" is now true of the pacing as well as of the verdict: a card takes
 * its place and comes over at the band boundary where `flippedCards` counts it, and the two can
 * no longer drift.
 *
 * ## Four layers of geometry, on purpose
 *
 * | layer | owner | why |
 * | --- | --- | --- |
 * | per-card place in the deck (`--card-index`), and the deal/turn widths (`--deal-bands`, `--flip-bands`) | this file | they never change, so they belong in the render output |
 * | how far one conveyor step travels at this viewport | the stylesheet | a phone gets a smaller card and a shallower recede with no resize listener |
 * | deck scrub (`--deck-bands`, `--deck-arrival`, `--phase-stack`, `--phase-fan`, `--column-position`) | an effect, written imperatively | changes every scroll frame; keeping it out of the render output also keeps SSR and hydration identical |
 * | the deal (`--deal-t`) and the flip (`--card-flip`) | the stylesheet, from `--deck-bands` and the card's index | a pure function of scroll, so the order and the reverse both fall out of the arithmetic |
 * | the pointer tilt (`--deck-tilt-*`) | GSAP | the one motion scroll does not drive, on one shared ticker |
 *
 * Everything composes inside ONE CSS transform per card, so the fan, the flip and the tilt can
 * never fight over the same inline `transform` string.
 *
 * `--card-flip` also decides which FACE is painted, through a hard 0/1 step in the stylesheet
 * rather than through backface culling alone: culling is not universal (measured by screenshot —
 * WebKit, the engine Safari ships, paints a mirror-imaged card FRONT where the black back
 * belongs), and a reader must never be shown a mirrored menu card because of an engine gap.
 *
 * ## Reduced motion, no-JavaScript, no-WebGL
 *
 * The stylesheet's resting state is the FINISHED one: deck arrived, fan open, fronts facing the
 * reader. The pre-flip state is written by script after mount, exactly as `GridStatementScene`
 * writes its masks — so a JavaScript-disabled render shows the whole taste edit as it finally
 * reads instead of a wall of card backs, and the server-rendered text is never trapped behind a
 * transform that will never run. Reduced motion keeps that resting state permanently: all fronts
 * shown, no rise, no fan scrub, no 3D flip, no pointer tilt. Nothing here touches WebGL, so a
 * failed context costs this scene nothing.
 *
 * ## Observable state (BUILD-GUIDE seam 3)
 *
 * On the deck: `data-menu-items`, `data-menu-count`, `data-flipped-count`, `data-deck-phase`
 * (`below` → `rising` → `fanned` → `revealing` → `revealed`), `data-deck-motion`
 * (`animated` / `static`). On each card: `data-menu-item`, `data-index`, `data-flipped` (the
 * reducer's verdict), `data-card-face` (`front` / `back` — the face actually presented, which
 * under reduced motion is always the front), and `aria-current` on the card the deck has most
 * recently revealed. Inside a card: `data-menu-name`,
 * `data-menu-maker`, `data-menu-category`, `data-menu-image` (`asset` / `placeholder`, the
 * rights verdict), with `data-menu-rationale` beside it. Playwright asserts these attributes and
 * text only — never transforms, opacity or computed styles.
 */

import Image from "next/image";
import { useEffect, useRef, type CSSProperties } from "react";

import { DropPrimaryLogo, DropWordmark } from "@/components/brand";
import {
  canDisplayAsset,
  type LocalizedText,
  type MenuItem,
  type RuntimeEnvironment,
} from "@/content";
import { gsap } from "@/lib/motion/gsap";

import styles from "./MenuDeckScene.module.css";

/* ------------------------------------------------------------------ tuning */

/**
 * Face-up, in the degrees the stylesheet turns into a `rotateY`.
 *
 * The scrubbed flip lives in the stylesheet now; this is only for the reduced-motion path, which
 * has no turn at all and has to assert the front inline so it beats the scrubbed value.
 */
const FACE_UP_DEG = 180;

/**
 * How much of the deck scene's entry band the rise occupies, and where the fan starts inside it.
 * They overlap: the stack is still arriving as it begins to open, which is what makes the entry
 * read as one gesture instead of two moves.
 */
const RISE_SPAN_OF_ENTRY = 0.62;
const FAN_START_OF_ENTRY = 0.35;

/** Pointer tilt: peak rotation in degrees, and how long the deck takes to follow / release. */
const TILT_MAX_DEG = 3.6;
const TILT_FOLLOW_S = 0.7;
const TILT_RELEASE_S = 1.1;

/** The desktop pointer the tilt is for. Never a hover dependency — the tilt reveals nothing. */
const FINE_POINTER_QUERY = "(hover: hover) and (pointer: fine) and (min-width: 1024px)";

/**
 * The environment the media-rights check is made in.
 *
 * `resolveRuntimeEnvironment()` reads `DROP_ENV` / `NODE_ENV` through a DYNAMIC lookup, and no
 * bundler can inline that into a client bundle — Next ships a `process` shim whose `env` is empty
 * (`next/dist/build/polyfills/process.js`), so in the browser that function always answers
 * `"development"`. A client scene that asked it directly would paint mock media during hydration
 * while the server, reading the real environment, had rendered the branded stand-in: a hydration
 * mismatch, and a media-rights leak in production. A STATIC `process.env.NODE_ENV` is the one
 * reading both sides inline identically, so it is what this scene resolves from — and
 * `canDisplayAsset` is still the only authority on whether an asset may paint.
 *
 * `staging` is therefore indistinguishable from `development` here; the difference between them
 * is `rights-pending` display, gated by an internal flag the browser cannot read either. Both are
 * plumbing for the integrator to hand down as a server-resolved prop if a lens ever needs them.
 */
const PAINT_ENVIRONMENT: RuntimeEnvironment =
  process.env.NODE_ENV === "production" ? "production" : "development";

/* -------------------------------------------------------------------- pure */

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

/**
 * Scene progress at which the first card flips.
 *
 * The scene-state reducer splits the menu scene into `count + 1` equal bands and documents the
 * first as "the stack's rise/fan phase; each later band flips one more card". The entry
 * choreography is timed against that band so the deck has arrived and opened by the moment the
 * reducer turns the first card — the presentation follows the state, it never re-decides it.
 */
export function deckEntrySpan(itemCount: number): number {
  return 1 / (Math.max(itemCount, 1) + 1);
}

/** How far the stack has arrived: 0 below the viewport, 1 fully risen. */
export function deckArrival(progress: number, flippedCards: number, count: number): number {
  // A card can only be face-up after the entry band, so the deck is certainly in place by then.
  if (flippedCards > 0) return 1;
  const rise = deckEntrySpan(count) * RISE_SPAN_OF_ENTRY;
  return rise <= 0 ? 1 : clamp01(clamp01(progress) / rise);
}

/**
 * How many of the reducer's own bands this scene's progress has covered, as a continuous float.
 *
 * `scopedFlippedCards()` splits the menu scene into `count + 1` equal bands with
 * `floor(progress * (count + 1))`, reserving the first band for the stack's rise and fan and
 * turning one more card face-up in each later band. This is that same expression WITHOUT the
 * floor, so `Math.floor` of it (clamped) is exactly `flippedCards`, and card `index` is the
 * reducer's business from the moment this passes `index + 1`.
 *
 * Every number the scene hands its stylesheet is expressed in these bands. That is the whole
 * point: presentation and state are then the same arithmetic, one floored and one not, and they
 * cannot drift apart. This still decides nothing — it re-derives the reducer's verdict for the
 * benefit of the frame, it does not compete with it.
 */
export function deckBands(progress: number, count: number): number {
  return clamp01(progress) * (Math.max(count, 1) + 1);
}

/**
 * The deck's ENTRY choreography, in fractions of the reducer's first band.
 *
 * The first band is the one the reducer reserves for the rise and the fan, so the entry is
 * written in fractions of it rather than in fractions of the whole scene. Band fractions also
 * make the choreography count-agnostic for real: a 2-item lens and a 6-item lens each get this
 * shape over their own entry band, instead of the same absolute windows meaning two different
 * things.
 *
 * Every phase overlaps the next on purpose, so the deck reads as one continuous move rather than
 * as three moves queued back to back.
 *
 * ## What these replaced, and why
 *
 * The windows used to be fixed fractions of the scene — stack 0.12-0.28, fan 0.25-0.42, spread
 * 0.40-0.58, flip 0.52-0.78 — that owed nothing to the reducer's bands. Measured on the running
 * page at 1440x900 and at 390x844, the two schedules disagreed by up to 0.41 of the scene: every
 * card reported `data-flipped` at its own band (progress 0.20 / 0.40 / 0.60 / 0.80) while the
 * stylesheet went on painting its BACK until the fixed flip window came round (0.61 / 0.64 /
 * 0.67 / 0.70). On the wide layout every card spent roughly half its time on screen face-down;
 * on the narrow layout, where the cards travel through the stage one at a time, three of the
 * four were painted back-side-up for the WHOLE of their time on screen and only turned over
 * after they had scrolled off the top. That is the "cards are not presenting their fronts when
 * they arrive" report, and it was structural, not a tuning value.
 *
 * The spread and flip windows are gone entirely: both are per-card now and both are carved out
 * of the card's own band, below.
 */
const ENTRY_WINDOWS = Object.freeze({
  /** The heading arrives and the hero hands over. */
  heading: Object.freeze({ from: 0.0, to: 0.6 }),
  /** The backs rise from below and gather into ONE centred stack. */
  stack: Object.freeze({ from: 0.08, to: 0.8 }),
  /** The stack fans: small alternating rotations, still overlapping. */
  fan: Object.freeze({ from: 0.55, to: 1.0 }),
});

/** A phase of the deck's entry. Distinct from `DeckPhase`, which is the observable
 * `data-deck-phase` state the page seam asserts. */
export type DeckChoreographyPhase = keyof typeof ENTRY_WINDOWS;

/**
 * How much of its own band a card spends travelling out of the stack to its place in the
 * composition, and how much of it it spends turning over — both ending exactly AT the band
 * boundary, which is the instant the reducer counts the card as flipped.
 *
 * The turn is the shorter of the two and so sits inside the travel: the card is already moving
 * before it starts to come over, and it lands flat and face-up. Under half a band each, so the
 * card that has arrived is then held, unmoving, for the rest of its band — the beat that lets
 * the item actually be read before the next card is dealt.
 */
const DEAL_BANDS = 0.62;
const FLIP_BANDS = 0.5;

/** Everything the scrub writes, so reduced motion can clear it without listing it twice. */
const SCRUBBED_PROPERTIES = [
  "--deck-arrival",
  "--deck-fan",
  "--deck-bands",
  "--phase-stack",
  "--phase-fan",
  "--column-position",
] as const;

/** Smoothstep, so no phase starts or stops with a jolt. Pure, so reverse scroll retraces it. */
function smoothstep(value: number): number {
  const t = clamp01(value);
  return t * t * (3 - 2 * t);
}

/**
 * How far through one entry phase the deck is, 0 before it and 1 after.
 *
 * Exported because the phases ARE the scene's contract with its stylesheet: the component writes
 * these numbers and the stylesheet composes every card's transform from them and the card's own
 * index. Nothing here knows how many cards there are beyond where the band boundaries fall.
 */
export function deckPhaseAmount(
  progress: number,
  phase: DeckChoreographyPhase,
  count: number,
): number {
  const { from, to } = ENTRY_WINDOWS[phase];
  const bands = deckBands(progress, count);
  if (to <= from) return bands >= to ? 1 : 0;
  return smoothstep((bands - from) / (to - from));
}

/**
 * Card `index`'s own turn, 0 face-down and 1 face-up.
 *
 * It reaches 1 exactly at band `index + 1` — the instant `scopedFlippedCards` starts counting
 * this card as flipped — so the card presents its front BY the time it takes its place rather
 * than some distance after it. Being a pure function of the bands is what keeps the reverse
 * contract: scrubbing back re-evaluates the same arithmetic, so the last card to turn is the
 * first to un-turn and the deck reconstructs itself in exactly the reverse of the order it was
 * dealt in.
 *
 * The stylesheet computes this same value from `--deck-bands`; it is duplicated here only so
 * `data-card-face` can report the face the reader is ACTUALLY shown (the stylesheet swaps faces
 * at the half-turn) rather than the reducer's verdict, which `data-flipped` already carries.
 */
export function deckCardTurn(bands: number, index: number): number {
  return clamp01((bands - index - 1 + FLIP_BANDS) / FLIP_BANDS);
}

/**
 * The vertical sequence's read position, in cards, for the narrow layout.
 *
 * Below the tablet breakpoint the deck stops spreading sideways and becomes a column that the
 * scene scrolls through: this is which card is level with the stage. It is the same band
 * position the flip is carved out of, so card `index` is level with the stage at band
 * `index + 1` — the moment its turn completes. The narrow layout therefore cannot show a card
 * on the stage face-down, which is precisely what it used to do.
 *
 * Smoothstepped WITHIN each band rather than across the whole travel, so each card eases into
 * the stage and holds there while its band runs out, instead of the column sliding through at a
 * constant rate with no card ever at rest.
 */
export function deckColumnPosition(progress: number, count: number): number {
  if (count <= 1) return 0;
  const travel = Math.min(Math.max(deckBands(progress, count) - 1, 0), count - 1);
  // The step currently being walked. Capped at the last one so `travel === count - 1` eases to
  // the end of that step rather than starting a step that does not exist.
  const step = Math.min(Math.floor(travel), count - 2);
  return step + smoothstep(travel - step);
}

/** How far the fan has opened out of the compressed stack: 0 compressed, 1 fanned. */
export function deckFan(progress: number, flippedCards: number, count: number): number {
  if (flippedCards > 0) return 1;
  const entry = deckEntrySpan(count);
  const start = entry * FAN_START_OF_ENTRY;
  const span = entry - start;
  if (span <= 0) return clamp01(progress) > 0 ? 1 : 0;
  return clamp01((clamp01(progress) - start) / span);
}

/** Where the deck stands in its choreography. Reflected as `data-deck-phase`. */
export type DeckPhase = "below" | "rising" | "fanned" | "revealing" | "revealed";

export function deckPhase(arrival: number, flippedCards: number, count: number): DeckPhase {
  if (count > 0 && flippedCards >= count) return "revealed";
  if (flippedCards > 0) return "revealing";
  if (arrival >= 1) return "fanned";
  if (arrival > 0) return "rising";
  return "below";
}

/* -------------------------------------------------------------- component */

export interface MenuDeckSceneProps {
  /** The lens's taste-edit heading, from `sectionLabels.menu`. Rendered, never written here. */
  heading: LocalizedText;
  /** The menu items, 2–6 of them. The deck's size, order and fan all derive from this array. */
  items: readonly MenuItem[];
  /**
   * The reducer's `transitionState.flippedCards`: how many cards are face-up, 0…`items.length`.
   * The flip is driven by this and nothing else — the scene never decides which card turns.
   */
  flippedCards: number;
  /**
   * The **menu scene's own** progress, 0..1: 0 before the scene, scrubbed while it holds the
   * viewport, 1 after it. Drives the stack's rise and the fan opening out of it. The scene never
   * computes this; the shell passes the reducer's scene-scoped value.
   */
  progress: number;
  /** The reducer's reduced-motion flag: static deck, fronts shown, no 3D flip, no tilt. */
  reducedMotion: boolean;
}

export function MenuDeckScene({
  heading,
  items,
  flippedCards,
  progress,
  reducedMotion,
}: MenuDeckSceneProps) {
  const deckRef = useRef<HTMLOListElement | null>(null);
  /**
   * The heading is a SIBLING of the deck, not a descendant, so it cannot inherit the deck's
   * custom properties — the scrub below writes `--deck-position` to both. Wrapping the two in a
   * shared element would be the other way, but the section's viewport already owns this layout
   * and a wrapper for one CSS variable is not worth changing it for.
   */
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const cardsRef = useRef<Array<HTMLElement | null>>([]);
  const contextRef = useRef<gsap.Context | null>(null);
  /** Flip state already written to the DOM, so only genuine changes are animated. */
  const appliedFlipsRef = useRef<boolean[] | null>(null);

  const count = items.length;
  const flipped = Math.max(0, Math.min(flippedCards, count));
  const arrival = deckArrival(progress, flipped, count);
  const fan = deckFan(progress, flipped, count);
  const open = count > 0 ? flipped / count : 0;
  const phase = deckPhase(arrival, flipped, count);

  /*
   * The scrubbed numbers the stylesheet composes every card's transform from. Each is a pure
   * function of this scene's own progress, so the whole deck is reversible by construction.
   *
   * `bands` is the one that matters: it is the reducer's own band counter without the floor, and
   * the stylesheet carves each card's deal and turn out of it by index. The deck no longer sends
   * a deck-wide spread or flip amount at all — both were the schedules that drifted from
   * `flippedCards`.
   */
  const bands = deckBands(progress, count);
  const stackAmount = deckPhaseAmount(progress, "stack", count);
  const fanAmount = deckPhaseAmount(progress, "fan", count);
  /** Which card is level with the stage in the narrow, vertical layout. */
  const columnPosition = deckColumnPosition(progress, count);

  /**
   * One motion context for the scene's lifetime; `revert()` kills every tween created through it
   * and undoes the inline styles those tweens wrote (brief §9, §17: nothing left ticking, no
   * animation state leaked across a route change).
   *
   * `gsap.context(noop, root)` rather than `createMotionScope(root)` — the sanctioned helper —
   * because that helper currently builds its context as `gsap.context(undefined, root)`, and GSAP
   * reads a falsy first argument as "give me the CURRENTLY ACTIVE context"
   * (`context: (func, scope) => func ? new Context(func, scope) : _context`), which is `undefined`
   * outside one. Measured in both engines at gsap 3.15: `gsap.context(undefined, el)` answers
   * `undefined`, so `run()` throws `Cannot read properties of undefined (reading 'add')`, while
   * `gsap.context(() => {}, el)` answers a real context. The shape below is deliberately identical
   * to the helper's, so this scene moves back onto it the moment that one-liner lands — the same
   * choice `ThesisScene`, `FilmScene`, `GridStatementScene` and `useSceneStateMachine` made.
   */
  useEffect(() => {
    const context = gsap.context(() => {}, deckRef.current ?? undefined);
    contextRef.current = context;
    return () => {
      context.revert();
      contextRef.current = null;
      appliedFlipsRef.current = null;
    };
  }, []);

  /**
   * The deck's scrubbed values — the rise and the fan — written straight to the element.
   *
   * Not React state and not a style prop: these change on every scroll frame, and leaving them
   * out of the render output keeps the server's HTML and the hydrated client's HTML identical.
   * The stylesheet's fallbacks are the finished state, so before this effect first runs — and
   * forever, with scripting off — the deck reads as arrived and open.
   *
   * `--deck-open` is deliberately NOT here. It is the only deck value that comes from a counter
   * rather than from progress, so writing it directly would step the spread open card by card
   * while the flips animate smoothly past it; it is tweened with the flip instead, below.
   */
  useEffect(() => {
    const deck = deckRef.current;
    if (!deck) return;
    if (reducedMotion) {
      delete deck.dataset.deckConveyor;
      for (const property of SCRUBBED_PROPERTIES) deck.style.removeProperty(property);
      headingRef.current?.style.removeProperty("--phase-stack");
      return;
    }
    /*
     * The conveyor is a SCRIPTED enhancement, and the stylesheet is gated on this attribute
     * rather than on the custom properties below.
     *
     * The deck moves its cards sideways, so the resting state of an ungated conveyor would put
     * every card at its own index along the line — and the scene section clips horizontally, so
     * with scripting off the entire taste edit would be clipped out of the page rather than
     * merely sitting still. Writing this from an effect means the browser only ever sees the
     * moving deck when something is actually there to move it; otherwise the plain grid at the
     * bottom of the stylesheet applies and every card is on screen, face-up, in order.
     */
    deck.dataset.deckConveyor = "on";
    deck.style.setProperty("--deck-arrival", arrival.toFixed(4));
    deck.style.setProperty("--deck-fan", fan.toFixed(4));
    deck.style.setProperty("--deck-bands", bands.toFixed(4));
    deck.style.setProperty("--phase-stack", stackAmount.toFixed(4));
    deck.style.setProperty("--phase-fan", fanAmount.toFixed(4));
    deck.style.setProperty("--column-position", columnPosition.toFixed(4));
    // The heading yields as the stack gathers, and is a sibling so it cannot inherit this.
    headingRef.current?.style.setProperty("--phase-stack", stackAmount.toFixed(4));
  }, [arrival, fan, bands, stackAmount, fanAmount, columnPosition, reducedMotion]);

  /**
   * The flip, driven by `flippedCards`.
   *
   * Only cards whose target actually changed are tweened, and they are staggered in the
   * direction of travel: ascending as the deck reveals, descending as it reconstructs, so a
   * reverse pass reads as the forward pass running backwards rather than as a new animation.
   */
  useEffect(() => {
    const context = contextRef.current;
    const deck = deckRef.current;
    if (!context || !deck) return;

    const cards = cardsRef.current.slice(0, count);
    if (cards.length === 0) return;

    const targets = cards.map((_, index) => index < flipped);
    // What is actually WRITTEN, which under reduced motion is every front — recording the
    // logical targets instead would leave the deck stuck face-up if the preference is turned
    // back off mid-scene, because the next pass would see nothing to change.
    appliedFlipsRef.current = reducedMotion ? cards.map(() => true) : targets;

    context.add(() => {
      /*
       * The FLIP IS NO LONGER TWEENED HERE.
       *
       * It is a pure function of scroll in the stylesheet now: each card carves its own turn out
       * of its own band of `--deck-bands` by index, so the deck turns left to right and reverse
       * scrolling un-turns it in exactly the reverse order. A GSAP tween writing an inline
       * `--card-flip` would win the cascade and freeze the card at whatever value the tween last
       * landed on, which is precisely the "fire-and-forget animation" the rebuild was asked to
       * remove.
       *
       * What is left here is the one thing scroll cannot express: reduced motion, where there is
       * no turn at all and every card is simply shown face-up. That still has to beat the
       * stylesheet's scrubbed value, so it stays an inline write.
       */
      if (reducedMotion) {
        gsap.set(deck, { "--deck-open": "1" });
        cards.forEach((card) => {
          if (card) gsap.set(card, { "--card-flip": String(FACE_UP_DEG) });
        });
        return;
      }

      // Motion restored after a reduced-motion pass: hand the flip back to the stylesheet.
      cards.forEach((card) => {
        if (card) card.style.removeProperty("--card-flip");
      });
      gsap.set(deck, { "--deck-open": open.toFixed(4) });
    });
  }, [flipped, count, open, reducedMotion]);

  /**
   * Desktop-only post-flip pointer tilt (brief §7.3).
   *
   * Decoration and nothing else: it reveals no content, carries no control, and is not attached
   * at all on coarse pointers, under reduced motion, or before the deck has finished revealing —
   * so no feature depends on hover (brief §15).
   */
  useEffect(() => {
    const deck = deckRef.current;
    const context = contextRef.current;
    if (!deck || !context) return;
    if (reducedMotion || count === 0 || flipped < count) return;
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    if (!window.matchMedia(FINE_POINTER_QUERY).matches) return;

    const setTilt = (x: number, y: number, duration: number): void => {
      context.add(() => {
        gsap.to(deck, {
          duration,
          ease: "power3.out",
          overwrite: "auto",
          "--deck-tilt-x": x.toFixed(3),
          "--deck-tilt-y": y.toFixed(3),
        });
      });
    };

    const handleMove = (event: PointerEvent): void => {
      const bounds = deck.getBoundingClientRect();
      if (bounds.width === 0 || bounds.height === 0) return;
      // -0.5 … +0.5 across the deck, doubled to -1 … +1 and clamped: a fanned card reaches
      // outside the deck's own box, so a pointer on its far corner parks the tilt at its limit
      // instead of running off with it.
      const x = clampUnit(((event.clientX - bounds.left) / bounds.width - 0.5) * 2);
      const y = clampUnit(((event.clientY - bounds.top) / bounds.height - 0.5) * 2);
      // Pointer below centre tips the deck's near edge toward the reader: rotateX follows -y.
      setTilt(-y * TILT_MAX_DEG, x * TILT_MAX_DEG, TILT_FOLLOW_S);
    };

    const handleLeave = (): void => setTilt(0, 0, TILT_RELEASE_S);

    // Listened for on the DECK, not on the window: the reducer leaves this scene revealed for
    // the rest of the journey, and a window-level move handler measuring layout on every event
    // would go on costing frames long after the deck has scrolled away (brief §17).
    deck.addEventListener("pointermove", handleMove, { passive: true });
    deck.addEventListener("pointerleave", handleLeave);

    return () => {
      deck.removeEventListener("pointermove", handleMove);
      deck.removeEventListener("pointerleave", handleLeave);
      // Release the tilt when this effect is merely re-running (the deck is still on the page),
      // never on unmount. React runs destructors in declaration order, so by the time this one
      // runs at unmount the scene's context effect — declared first — has already reverted and
      // cleared `contextRef`; starting a release tween there would put a tween on a detached
      // node, outside the context that was supposed to have disposed of everything.
      if (contextRef.current === context) handleLeave();
    };
  }, [reducedMotion, flipped, count]);

  const deckStyle: DeckStyle = {
    "--deck-count": String(Math.max(count, 1)),
    // Gaps, not cards: the stylesheet divides the content column by this to find the reading
    // spread. Never zero, so the division is always defined for a one-item deck.
    "--deck-gaps": String(Math.max(count - 1, 1)),
    // The deal and the turn, in bands. Constants, so they belong in the render output rather
    // than in the per-frame scrub — the server and the hydrated client write the same string,
    // and there is then ONE definition of each shared by the stylesheet and `deckCardTurn`.
    "--deal-bands": String(DEAL_BANDS),
    "--flip-bands": String(FLIP_BANDS),
  };

  return (
    <>
      <h2 ref={headingRef} className={styles.heading} data-section-heading="menu">
        {heading.fa}
      </h2>

      <div className={styles.stage}>
        <ol
          ref={deckRef}
          className={styles.deck}
          style={deckStyle}
          // The deck has no bullets and no margin, and WebKit drops list semantics from a list
          // styled that way — so the role is restated rather than lost to the styling.
          role="list"
          data-menu-items
          data-menu-count={count}
          data-flipped-count={flipped}
          data-deck-phase={phase}
          data-deck-motion={reducedMotion ? "static" : "animated"}
        >
          {items.map((item, index) => {
            const faceUp = index < flipped;
            /*
             * `data-flipped` is the reducer's verdict; `data-card-face` is the face actually
             * presented, and under reduced motion that is the front on every card — there is no
             * 3D flip to wait for. Keeping the two attributes distinct lets the page seam assert
             * "reduced motion shows fronts" from attributes alone, never a computed transform.
             *
             * The presented face reads the card's own turn rather than `faceUp`, because the
             * stylesheet swaps faces at the HALF-turn and the turn completes at the band boundary
             * `faceUp` steps on: for the last half of the turn the reader is already looking at
             * the front while the reducer has not yet counted the card. Reporting `faceUp` there
             * would make this attribute describe the state instead of the paint, which is the
             * one thing it exists not to do — `data-flipped` is right beside it for the state.
             */
            const presentedFace =
              reducedMotion || deckCardTurn(bands, index) >= 0.5 ? "front" : "back";
            // The card's place in the deck, and nothing else. Its position on the conveyor is
            // derived in the stylesheet from this plus the deck's single `--deck-position`, so
            // the markup React renders on the server is byte-identical to the hydrated markup.
            const style: CardStyle = { "--card-index": String(index) };

            return (
              <li
                key={item.id}
                ref={(node) => {
                  cardsRef.current[index] = node;
                }}
                className={styles.card}
                style={style}
                data-menu-item
                data-index={index}
                data-flipped={faceUp}
                data-card-face={presentedFace}
                // The deck's newest reveal: the card the reader is being shown right now.
                aria-current={faceUp && index === flipped - 1 ? "true" : undefined}
              >
                {/*
                  Card back (brief §7.3): near-black, one centred white DROP primary logo, no
                  other copy, sharp corners. Decorative — the front carries the item.
                */}
                <div className={`${styles.face} ${styles.back}`} aria-hidden="true">
                  <DropPrimaryLogo className={styles.backLogo} variant="light" />
                </div>

                <div className={`${styles.face} ${styles.front}`}>
                  <MenuCardImage item={item} environment={PAINT_ENVIRONMENT} />
                  <div className={styles.meta} dir="rtl">
                    <p className={styles.name} data-menu-name>
                      {item.name.fa}
                    </p>
                    <p className={styles.maker} data-menu-maker>
                      <span lang="en" dir="ltr">
                        {item.maker}
                      </span>
                    </p>
                    {item.category ? (
                      <p className={styles.category} data-menu-category>
                        {item.category.fa}
                      </p>
                    ) : null}
                  </div>
                </div>

                {/*
                  The selection rationale is lens content (brief §5), but the brief bans the
                  paragraph from the card. So it lives beside the faces: out of the composition,
                  in the accessibility tree, and in the server-rendered HTML.
                */}
                <p className={styles.rationale} dir="rtl" data-menu-rationale>
                  {item.rationale.fa}
                </p>
              </li>
            );
          })}
        </ol>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ image */

/**
 * One card's product image, or a branded DROP stand-in where this environment may not paint it.
 *
 * `canDisplayAsset` is the only authority on that (brief §11, §18): the whole mock pack is
 * `development-mock` / `productionAllowed: false`, so it renders while developing and is
 * replaced by the stand-in anywhere it is not cleared. The stand-in is a DROP mark on the
 * brand's own ground, carrying the same localized alt text — never a broken image.
 */
function MenuCardImage({
  item,
  environment,
}: {
  item: MenuItem;
  environment: RuntimeEnvironment;
}) {
  const asset = item.image;
  const alt = asset.alt.fa;

  if (!canDisplayAsset(asset, environment)) {
    return (
      <div
        className={`${styles.frame} ${styles.placeholder}`}
        data-menu-image="placeholder"
        role="img"
        aria-label={alt}
      >
        <DropWordmark className={styles.placeholderMark} variant="light" />
      </div>
    );
  }

  return (
    <div className={styles.frame} data-menu-image="asset">
      <Image
        className={styles.image}
        src={asset.src}
        alt={alt}
        width={asset.width}
        height={asset.height}
        sizes="(max-width: 767px) 50vw, 22vw"
      />
    </div>
  );
}

/* ------------------------------------------------------------------ types */

function clampUnit(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < -1) return -1;
  if (value > 1) return 1;
  return value;
}

/** Deck-level custom properties React writes. The scrub values are written by effect instead. */
type DeckStyle = CSSProperties & {
  "--deck-count": string;
  "--deck-gaps": string;
  "--deal-bands": string;
  "--flip-bands": string;
};

/** Per-card geometry: the index alone, so the markup is identical on the server and in the browser. */
type CardStyle = CSSProperties & {
  "--card-index": string;
};

export default MenuDeckScene;
