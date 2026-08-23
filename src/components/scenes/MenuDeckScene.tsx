"use client";

/**
 * The menu deck — the taste edit as a physical deck of cards (brief §7.3, ticket 07).
 *
 * A compressed stack rises from below centre, fans into small rotations and offsets with the
 * CARD BACKS facing us, then the cards flip in 3D with a crisp stagger and each front reveals a
 * real menu item. Every word and every image comes from {@link MenuDeckSceneProps.items}; the
 * count comes from that array's length, and nothing in this file knows what a fruit tart is.
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
 * ## Four layers of geometry, on purpose
 *
 * | layer | owner | why |
 * | --- | --- | --- |
 * | per-card fan position (`--card-step`, `--card-angle`, `--card-arc`) | this file, from `items.length` | count adaptation is data-driven and must be identical on server and client |
 * | how far one step travels at this viewport | the stylesheet | mobile gets narrower angles and offsets (brief §15) with no resize listener |
 * | deck scrub (`--deck-arrival`, `--deck-fan`, `--deck-open`) | an effect, written imperatively | changes every scroll frame; keeping it out of the render output also keeps SSR and hydration identical |
 * | the flip (`--card-flip`) and the tilt (`--deck-tilt-*`) | GSAP | a real stagger, reverse ordering, and one shared ticker |
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
 * Brief §7.3: "Initial fan angles may begin around `-8deg, -3deg, 3deg, 8deg` and adapt to
 * count." Those four numbers are a four-card deck spread evenly across ±8°, so the spread is
 * what generalises: {@link fanAngle} distributes any count evenly between `-spread` and
 * `+spread`.
 */
const MAX_FAN_SPREAD_DEG = 8;

/**
 * Angle between adjacent cards, taken from the brief's own four-card example: ±8° across three
 * gaps is 5.33° per gap. Small decks keep that step instead of splaying to the full ±8°.
 */
const FAN_STEP_DEG = (MAX_FAN_SPREAD_DEG * 2) / 3;

/** Floor on the spread, so the smallest allowed deck still reads as a fan and not as a pair. */
const MIN_FAN_SPREAD_DEG = 4.5;

/** Flip stagger. Brief §7.3 asks for 70–110ms; this is the middle of that window. */
const FLIP_STAGGER_S = 0.09;

/** One card's flip. Weighted at both ends — a card turning over, not a UI toggle. */
const FLIP_DURATION_S = 0.62;
const FLIP_EASE = "power3.inOut";

/** The spread follows the flip out, not in: it settles as the card lands. */
const OPEN_EASE = "power2.out";

/** `--card-flip`, in degrees, for each face. The stylesheet turns it into a `rotateY`. */
const FACE_UP_DEG = 180;
const FACE_DOWN_DEG = 0;

/**
 * How much of the deck scene's entry band the rise occupies, and where the fan starts inside it.
 * They overlap: the stack is still arriving as it begins to open, which is what makes the entry
 * read as one gesture instead of two moves.
 */
const RISE_SPAN_OF_ENTRY = 0.62;
const FAN_START_OF_ENTRY = 0.35;

/** Pointer tilt: peak rotation in degrees, and how long the deck takes to follow / release. */
const TILT_MAX_DEG = 2.6;
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

/** Total fan spread in degrees for a deck of `count` cards: the outermost card sits at ±this. */
export function fanSpreadDeg(count: number): number {
  if (count <= 1) return 0;
  const stepped = (FAN_STEP_DEG * (count - 1)) / 2;
  return Math.min(MAX_FAN_SPREAD_DEG, Math.max(MIN_FAN_SPREAD_DEG, stepped));
}

/** Card position across the fan, -1 (first) … +1 (last). 0 for a single card. */
export function fanPosition(index: number, count: number): number {
  if (count <= 1) return 0;
  return (index / (count - 1)) * 2 - 1;
}

/** In-plane rotation of card `index`, evenly distributed across the spread. */
export function fanAngle(index: number, count: number): number {
  return fanPosition(index, count) * fanSpreadDeg(count);
}

/** Signed distance from the deck's centre in card steps: ∓0.5 for two, -1/0/+1 for three. */
export function fanStep(index: number, count: number): number {
  return index - (count - 1) / 2;
}

/** How far the stack has arrived: 0 below the viewport, 1 fully risen. */
export function deckArrival(progress: number, flippedCards: number, count: number): number {
  // A card can only be face-up after the entry band, so the deck is certainly in place by then.
  if (flippedCards > 0) return 1;
  const rise = deckEntrySpan(count) * RISE_SPAN_OF_ENTRY;
  return rise <= 0 ? 1 : clamp01(clamp01(progress) / rise);
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
      deck.style.removeProperty("--deck-arrival");
      deck.style.removeProperty("--deck-fan");
      return;
    }
    deck.style.setProperty("--deck-arrival", arrival.toFixed(4));
    deck.style.setProperty("--deck-fan", fan.toFixed(4));
  }, [arrival, fan, reducedMotion]);

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
    const previous = appliedFlipsRef.current;
    // What is actually WRITTEN, which under reduced motion is every front — recording the
    // logical targets instead would leave the deck stuck face-up if the preference is turned
    // back off mid-scene, because the next pass would see nothing to change.
    appliedFlipsRef.current = reducedMotion ? cards.map(() => true) : targets;

    context.add(() => {
      const flipTo = (faceUp: boolean): string =>
        String(faceUp ? FACE_UP_DEG : FACE_DOWN_DEG);

      // How far the fan has opened into its reading spread. Eased alongside the flips it
      // belongs to, so the deck widens as the cards turn instead of stepping between them.
      const openTo = open.toFixed(4);

      if (reducedMotion) {
        // Fronts shown without the 3D flip: the stylesheet's resting state, held.
        gsap.set(deck, { "--deck-open": "1" });
        cards.forEach((card) => {
          if (card) gsap.set(card, { "--card-flip": String(FACE_UP_DEG) });
        });
        return;
      }

      if (previous === null) {
        // First application after mount: take the deck to its logical state without a show.
        gsap.set(deck, { "--deck-open": openTo });
        cards.forEach((card, index) => {
          if (card) gsap.set(card, { "--card-flip": flipTo(targets[index]) });
        });
        return;
      }

      gsap.to(deck, {
        duration: FLIP_DURATION_S,
        ease: OPEN_EASE,
        overwrite: "auto",
        "--deck-open": openTo,
      });

      const changed = targets
        .map((target, index) => ({ target, index }))
        .filter(({ target, index }) => target !== previous[index]);
      if (changed.length === 0) return;

      const revealing = changed[0].target;
      const ordered = revealing ? changed : [...changed].reverse();

      ordered.forEach(({ target, index }, position) => {
        const card = cards[index];
        if (!card) return;
        gsap.to(card, {
          duration: FLIP_DURATION_S,
          ease: FLIP_EASE,
          delay: position * FLIP_STAGGER_S,
          overwrite: "auto",
          "--card-flip": flipTo(target),
        });
      });
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
  };

  return (
    <>
      <h2 className={styles.heading} data-section-heading="menu">
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
            // `data-flipped` is the reducer's verdict; `data-card-face` is the face actually
            // presented, and under reduced motion that is the front on every card — there is no
            // 3D flip to wait for. Keeping the two attributes distinct lets the page seam assert
            // "reduced motion shows fronts" from attributes alone, never a computed transform.
            const presentedFace = faceUp || reducedMotion ? "front" : "back";
            const style: CardStyle = {
              "--card-index": String(index),
              "--card-step": fanStep(index, count).toFixed(3),
              "--card-angle": fanAngle(index, count).toFixed(3),
              "--card-arc": (fanPosition(index, count) ** 2).toFixed(3),
            };

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
};

/** Per-card fan geometry: count-derived, so identical on the server and in the browser. */
type CardStyle = CSSProperties & {
  "--card-index": string;
  "--card-step": string;
  "--card-angle": string;
  "--card-arc": string;
};

export default MenuDeckScene;
