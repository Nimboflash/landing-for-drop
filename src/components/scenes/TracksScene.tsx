"use client";

/**
 * The tracks carousel — the sound edit as a field of transparent CD jewel cases (brief §7.8,
 * ticket 12).
 *
 * A large heading, then a cover-flow field of clear jewel cases over the Monochrome Mesh: the
 * active case centred, largest, brightest and closest, its neighbours smaller and dimmer on both
 * sides, up to five positions on desktop and three on tablet and mobile. Every word, every image
 * and the number of cases come from {@link TracksSceneProps.tracks}; nothing in this file knows
 * what a track is called, who made it, or where its artwork lives.
 *
 * ## The artwork is ON THE DISC
 *
 * This is the rule the mock pack calls out and the one thing the composition lives or dies by:
 * the song artwork is CLIPPED ONTO THE CIRCULAR DISC inside the clear case — it is never a square
 * card floating above the disc. The circle is the one place the sharp-corner hard rule yields,
 * because the physical form is a disc (CLAUDE.md; brief §4). The case itself is square-cornered
 * like everything else in the system.
 *
 * Whether an image may paint at all is `canDisplayAsset`'s decision and nobody else's (brief §11,
 * §18): the whole mock pack is `development-mock` / `productionAllowed: false`, so it renders
 * while developing and is replaced by a branded DROP disc anywhere it is not cleared. Never a
 * broken image, and the localized alt text from the data travels with both.
 *
 * ## This scene decides nothing
 *
 * No ScrollTrigger, no progress of its own, and — the important one for a carousel — **no local
 * active index**. `trackIndex` is reducer output (BUILD-GUIDE seam 2, one-way data flow), and all
 * four input methods are dumb event sources feeding the same reducer through
 * {@link TracksSceneProps.onPrevious} / {@link TracksSceneProps.onNext} /
 * {@link TracksSceneProps.onSelect}:
 *
 * | input | routed as |
 * | --- | --- |
 * | scroll | the shell's ScrollTrigger, already wired |
 * | drag / swipe | one step per drag threshold crossed |
 * | arrow buttons | `onPrevious` / `onNext` |
 * | keyboard arrows, Home / End | `onPrevious` / `onNext` / `onSelect` |
 *
 * Because the whole presentation is a pure function of `trackIndex`, reverse scroll steps
 * backward through exactly the states forward scroll produced, and the reducer's documented
 * precedence (most recent input wins) is what mixed-input behavior is unit-tested against.
 *
 * ## Which direction is "next"
 *
 * The field is composed physically left-to-right and held that way by absolute positioning and
 * transforms, never by flipping the document's direction — the same rule the film scene's
 * editorial grid follows (brief §16). So `ArrowRight` advances and `ArrowLeft` retreats: they
 * follow the field the reader can see, not the direction of the Persian text sitting under it.
 * Each text run still carries its own `dir`, so Persian reads right-to-left inside a field whose
 * order is fixed.
 *
 * ## Motion, and what happens when there is none
 *
 * The step itself is a CSS transition over transforms driven by `--track-travel`; the ambient
 * life of the case — the slow disc revolution, the floating active case, the travelling gloss —
 * is CSS keyframes on separate layers so the step, the float and the pointer tilt can never
 * fight over one `transform`. GSAP appears for the one thing CSS cannot do here: the
 * reduced-motion crossfade. `globals.css` collapses every transition and animation under
 * `prefers-reduced-motion`, which is exactly right for the travel and exactly wrong for the
 * brief crossfade §14 asks for — so that fade is a GSAP tween on a custom property, created once
 * inside a motion scope that is reverted on unmount.
 *
 * Reduced motion therefore keeps the coverflow, keeps all five positions, keeps every input
 * method and keeps every track reachable: only the travel between them stops being animated
 * (brief §16 — reduced motion must never remove content or capability). No audio is loaded,
 * played, or autoplayed anywhere in this file; a track's `sourceUrl`, when the data has one,
 * becomes a small external link on the title and nothing else.
 *
 * ## Observable state (BUILD-GUIDE seam 3)
 *
 * On the carousel: `data-tracks-carousel`, `data-track-count`, `data-track-index`,
 * `data-carousel-slots`, `data-carousel-motion` (`animated` / `static`), `data-carousel-quality`,
 * and `data-carousel-dragging` while a horizontal drag is in flight. On each item: `data-track`,
 * `data-index`, `data-active`, `data-offset` (signed distance from the active track),
 * `data-in-field` (inside the painted coverflow positions) and `aria-current` on the active one.
 * Inside: `data-track-title`, `data-track-artist`, `data-track-group` (with `data-track-period`),
 * `data-track-artwork` (`asset` / `placeholder` — rights verdict, or a failed load) and
 * `data-track-source` on
 * an external link. The controls keep `data-carousel-control="prev" | "next"`. Playwright asserts
 * these attributes and text only — never transforms, opacity, or computed styles.
 */

import Image from "next/image";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

import { DropWordmark } from "@/components/brand";
import {
  canDisplayAsset,
  type LocalizedText,
  type RuntimeEnvironment,
  type TrackRecommendation,
} from "@/content";
import { createMotionScope, gsap, type MotionScope } from "@/lib/motion/gsap";
import {
  DEFAULT_QUALITY_TIER,
  QUALITY_TIER_SETTINGS,
  REDUCED_MOTION_CROSSFADE_SECONDS,
  detectEnvironmentQualityTier,
  type QualityTier,
} from "@/lib/performance/quality-tier";

import styles from "./TracksScene.module.css";

/* ---------------------------------------------------------------- interface copy */

/**
 * Control labels — interface copy, not editorial content. The lens schema carries no control
 * strings, and these do not change when the lens does, so they live here rather than in the
 * data (the same reasoning the shell applies to its own control labels). Persian, because
 * Persian is the primary language.
 */
const CAROUSEL_PREVIOUS_LABEL = "قطعهٔ قبلی";
const CAROUSEL_NEXT_LABEL = "قطعهٔ بعدی";
/** Prefix for a case's accessible name; the track's own title and artist complete it. */
const SELECT_TRACK_LABEL = "نمایش قطعه";
/** Announced inside an external link, so "opens elsewhere" is never left to a visual cue. */
const EXTERNAL_LINK_NOTE = "باز شدن در تب تازه";

/* ------------------------------------------------------------------- environment */

/**
 * The environment the media-rights check is made in.
 *
 * `resolveRuntimeEnvironment()` reads `DROP_ENV` / `NODE_ENV` through a DYNAMIC lookup, which no
 * bundler can inline into a client bundle: in the browser Next substitutes a `process` shim whose
 * `env` is empty (`next/dist/build/polyfills/process.js`), so that function always answers
 * `"development"` there. A client scene asking it directly would paint mock artwork during
 * hydration while the server, reading the real environment, had rendered the branded stand-in —
 * a hydration mismatch, and a media-rights leak in production.
 *
 * A STATIC `process.env.NODE_ENV` is the one reading both sides inline identically, so it is what
 * this scene resolves from; `canDisplayAsset` remains the only authority on whether an asset may
 * paint. `staging` is therefore indistinguishable from `development` here — the difference
 * between them is `rights-pending` display, gated by an internal flag the browser cannot read
 * either. Both are plumbing for the integrator to hand down as a server-resolved prop if a lens
 * ever needs them.
 */
const PAINT_ENVIRONMENT: RuntimeEnvironment =
  process.env.NODE_ENV === "production" ? "production" : "development";

/* ------------------------------------------------------------------------ tuning */

/**
 * How many positions each side of the active case the field paints.
 *
 * Brief §7.8 asks for "up to five positions in the cover-flow field when the viewport allows",
 * and §15 fixes where that is allowed: five on desktop (≥1200px), three on tablet (768–1199px),
 * and mobile is swipe-first — which keeps three so the neighbours peek in and advertise the
 * swipe. Two slots each side is five positions; one is three.
 */
export const COVERFLOW_SLOTS = Object.freeze({ desktop: 2, tablet: 1, mobile: 1 });

/** Brief §15 breakpoints. */
const DESKTOP_MIN_PX = 1200;
const TABLET_MIN_PX = 768;

/**
 * Slots assumed before the viewport can be measured — server render and the hydration pass.
 * The widest layout, so the first paint is the composition the brief leads with; a narrower
 * viewport narrows it after mount, which is a state change rather than a hydration mismatch.
 */
export const DEFAULT_COVERFLOW_SLOTS = COVERFLOW_SLOTS.desktop;

/**
 * Stacking ceiling for the field. Cases stack by nearness — the active one in front — but from a
 * fixed top rather than from the track count, so a long playlist can never stack a case above the
 * arrow controls that sit over the field. Anything this far out is invisible anyway.
 */
const CASE_STACK_TOP = 40;

/** How far a pointer must travel before the gesture commits to an axis. */
const DRAG_AXIS_LOCK_PX = 8;
/** One carousel step, as a fraction of the field's width. */
const DRAG_STEP_FRACTION = 0.13;
/** …with a floor, so a narrow field never turns a nudge into three steps. */
const DRAG_MIN_STEP_PX = 56;
/** How far the field may lean into an unfinished drag, in px. Feedback, not travel. */
const DRAG_ELASTIC_PX = 44;
/** Fraction of the residual drag the field actually leans by. */
const DRAG_ELASTIC_RATIO = 0.4;

/* -------------------------------------------------------------------------- pure */

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

function clampUnit(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < -1) return -1;
  if (value > 1) return 1;
  return value;
}

/** An index that is always inside `0..count - 1`, and 0 for an empty collection. */
function clampIndex(value: number, count: number): number {
  if (count <= 0) return 0;
  const rounded = Number.isFinite(value) ? Math.round(value) : 0;
  if (rounded < 0) return 0;
  if (rounded > count - 1) return count - 1;
  return rounded;
}

/**
 * Slots for a viewport width, from the brief's §15 breakpoints. Pure, so the breakpoint table
 * is readable and testable without a browser.
 */
export function coverflowSlots(viewportWidth: number): number {
  if (!Number.isFinite(viewportWidth)) return DEFAULT_COVERFLOW_SLOTS;
  if (viewportWidth >= DESKTOP_MIN_PX) return COVERFLOW_SLOTS.desktop;
  if (viewportWidth >= TABLET_MIN_PX) return COVERFLOW_SLOTS.tablet;
  return COVERFLOW_SLOTS.mobile;
}

/**
 * How present a case is at `distance` steps from the active one: 1 at the centre, fading evenly
 * outward, and exactly 0 for anything past the field's slots. Brief §7.8: "Previous/next items
 * appear smaller and dimmer on both sides."
 */
export function casePresence(distance: number, slots: number): number {
  const span = Math.max(1, slots) + 1;
  return clamp01((span - Math.abs(distance)) / span);
}

/**
 * Depth for the coverflow's scale and z-translation: the distance, capped one step past the
 * field so a long playlist's far tracks cannot scale through zero and mirror themselves.
 */
export function caseDepth(distance: number, slots: number): number {
  return Math.min(Math.abs(distance), Math.max(1, slots) + 1);
}

/**
 * How far out a case actually travels, in steps — the signed distance, parked one step past the
 * field.
 *
 * Every track stays mounted so its text is server-rendered and its state observable, and an
 * eleven-track playlist would otherwise lay its far cases out hundreds of pixels beyond the
 * viewport: invisible at zero presence, but still real layout, and still counted in the
 * document's scrollable width. Parking them just outside the field keeps the page's width
 * honest without changing anything the reader can see — a case entering the field still travels
 * exactly one step, because the step from the parking position to the outermost painted slot is
 * exactly one step.
 */
/**
 * A track's place in the field relative to the active one, measured AROUND the playlist.
 *
 * The plain difference `index - activeIndex` leaves the ends of the playlist bare: on track 1
 * there is nothing to the left and on the last track nothing to the right, so the coverflow paints
 * two or three cases instead of five and the field visibly collapses at both ends. Measuring the
 * shortest signed way round instead means every track always has neighbours, whatever the count.
 *
 * The map from raw distance to signed offset is injective, so no two tracks can ever land on the
 * same slot: at 3 tracks the offsets are {0, +1, -1}, at 4 they are {0, +1, +2, -1}, and at 11 the
 * item before track 1 is track 11.
 *
 * This is PRESENTATION ONLY. The reducer still clamps the index at the ends — first and last stay
 * first and last, prev on track 1 does nothing — because that is documented, tested behaviour and
 * a wrapping index would break the non-decreasing contract the scroll mapping depends on. What
 * wraps is the picture, not the position.
 */
export function ringOffset(index: number, activeIndex: number, count: number): number {
  if (count <= 0) return 0;
  const raw = (((index - activeIndex) % count) + count) % count;
  return raw > Math.floor(count / 2) ? raw - count : raw;
}

export function caseTravel(distance: number, slots: number): number {
  const limit = Math.max(1, slots) + 1;
  if (distance > limit) return limit;
  if (distance < -limit) return -limit;
  return distance;
}

/* -------------------------------------------------------------------- components */

export interface TracksSceneProps {
  /** The lens's section label. Both languages are rendered; nothing is written into this file. */
  heading: LocalizedText;
  /** The playlist. Count, order and every string come from here (brief §7.8, "Data behavior"). */
  tracks: readonly TrackRecommendation[];
  /** Reducer output: which track is active. This scene never computes it. */
  trackIndex: number;
  /** Dispatches `carouselPrev` into the scene-state reducer. */
  onPrevious: () => void;
  /** Dispatches `carouselNext` into the scene-state reducer. */
  onNext: () => void;
  /** Dispatches `carouselTo` into the scene-state reducer. */
  onSelect: (index: number) => void;
  /** Progress through the tracks scene, 0..1. Presentation drift only — never visibility. */
  progress: number;
  /**
   * Is this scene the active one?
   *
   * The carousel's controls were in the tab order for the whole page, so tabbing forward from the
   * footer walked backwards into a scene the reader had already passed — and the page scrolled
   * back to it. They stay fully readable and fully present to assistive technology; only the tab
   * STOP follows the scene, which is the roving-tabindex pattern this component already uses
   * internally, applied one level up.
   */
  sceneActive?: boolean;
  /** The reducer's reduced-motion flag: coverflow kept, travel replaced by a brief crossfade. */
  reducedMotion: boolean;
  /**
   * Reducer output: the Pixel B dark beat has finished, so this composition may enter.
   *
   * Brief §7.7 steps 6-7 hold "a short empty dark beat" at 100% and only THEN let the Tracks title
   * and carousel enter; §19 makes "a completed dark beat precedes the Tracks entrance" an
   * acceptance criterion. Section geometry cannot express that on its own — the tracks section
   * scrolls into view while the beat is still running — so the entrance is gated on reducer state
   * instead, and reflected as `data-tracks-entered` so the page seam can assert it.
   */
  entered: boolean;
}

export function TracksScene({
  heading,
  tracks,
  trackIndex,
  onPrevious,
  onNext,
  onSelect,
  progress,
  reducedMotion,
  entered,
  sceneActive = true,
}: TracksSceneProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const scopeRef = useRef<MotionScope | null>(null);
  const crossfadeRef = useRef<gsap.core.Tween | null>(null);
  const dragRef = useRef<DragGesture | null>(null);
  /** True while the click that ends a real drag is still on its way, so it selects nothing. */
  const suppressClickRef = useRef(false);
  const previousIndexRef = useRef(trackIndex);

  const headingId = useId();
  const count = tracks.length;
  const activeIndex = clampIndex(trackIndex, count);

  /**
   * Viewport- and device-derived values, read through `useSyncExternalStore` for the same reason
   * `useReducedMotion` does: the server and the hydration pass both get the documented default,
   * so the client reproduces the server's HTML exactly, and the real value arrives immediately
   * afterwards as a subscription update rather than as a cascading render.
   */
  const slots = useSyncExternalStore(subscribeViewport, readSlots, readDefaultSlots);
  const finePointer = useSyncExternalStore(
    subscribeFinePointer,
    readFinePointer,
    readDefaultFinePointer,
  );
  const tier = useSyncExternalStore(neverChanges, readQualityTier, readDefaultQualityTier);

  /**
   * Pointer tilt is a desktop enhancement and nothing depends on it (brief §15: "No feature may
   * depend on hover"). It is off for reduced motion, off without a fine pointer, and off on the
   * tier that has already decided it cannot afford pointer response.
   */
  const pointerTiltEnabled =
    !reducedMotion && finePointer && QUALITY_TIER_SETTINGS[tier].shaderDetail.pointerResponse;

  /** One motion scope for the scene's lifetime; `revert()` kills everything created inside it. */
  useEffect(() => {
    const scope = createMotionScope(rootRef.current);
    scopeRef.current = scope;
    return () => {
      scope.revert();
      scopeRef.current = null;
      crossfadeRef.current = null;
    };
  }, []);

  /**
   * The one GSAP tween in this scene: the reduced-motion crossfade, built once and left paused.
   *
   * `immediateRender: false` matters — a paused `fromTo` that rendered its start values would
   * drop the custom property to 0 and blank the active case before anything asked it to.
   */
  useEffect(() => {
    const scope = scopeRef.current;
    const root = rootRef.current;
    if (!scope || !root) return;

    scope.run(() => {
      gsap.killTweensOf(root);
      gsap.set(root, { "--drop-tracks-crossfade": 1 });
      crossfadeRef.current = gsap.fromTo(
        root,
        { "--drop-tracks-crossfade": 0 },
        {
          "--drop-tracks-crossfade": 1,
          duration: REDUCED_MOTION_CROSSFADE_SECONDS,
          ease: "none",
          paused: true,
          immediateRender: false,
        },
      );
    });
  }, []);

  /**
   * What a step costs, once the reducer has already moved the index. Two consequences, no
   * decisions.
   *
   * First the roving tab stop follows the active case. A case that leaves the painted field
   * becomes `inert`, and a browser blurs an element that turns inert — so a keyboard user whose
   * focus stayed behind would lose it a few steps into the playlist and the arrows would go dead
   * halfway through. Focus moves only when it was already on a case, so the arrow buttons and the
   * caption's link keep theirs, and never while a drag is in flight.
   *
   * Then, under reduced motion, the step arrives as a brief crossfade instead of travelling
   * (brief §14, §16).
   */
  useEffect(() => {
    if (previousIndexRef.current === activeIndex) return;
    previousIndexRef.current = activeIndex;
    followFocusToActiveCase(rootRef.current, dragRef.current !== null);
    if (!reducedMotion) return;
    crossfadeRef.current?.restart();
  }, [activeIndex, reducedMotion]);

  /**
   * Scene progress, written straight to the element rather than through a style prop: it changes
   * on every scroll frame, and keeping it out of the render output keeps the server's HTML and
   * the hydrated client's HTML identical. It only ever drifts the heading — no content's
   * visibility depends on it — so it is written to the heading itself, which is the carousel's
   * sibling rather than its child and would never inherit a property set on the field.
   */
  useEffect(() => {
    headingRef.current?.style.setProperty("--drop-tracks-progress", clamp01(progress).toFixed(4));
  }, [progress]);

  /* ------------------------------------------------------------------ input */

  const handleKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLDivElement>) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      // A key means the pointer sequence is over. A drag that ended without producing a click
      // would otherwise leave the suppression flag armed, and swallow the click that an Enter or
      // a Space on the focused case is about to fire.
      suppressClickRef.current = false;
      switch (event.key) {
        // The field is composed physically left-to-right, so the arrows follow the field.
        case "ArrowRight":
          onNext();
          break;
        case "ArrowLeft":
          onPrevious();
          break;
        case "Home":
          onSelect(0);
          break;
        case "End":
          onSelect(Math.max(0, count - 1));
          break;
        default:
          return;
      }
      event.preventDefault();
    },
    [count, onNext, onPrevious, onSelect],
  );

  const handlePointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const stage = stageRef.current;
    if (!stage) return;
    const width = stage.getBoundingClientRect().width;
    suppressClickRef.current = false;
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      anchorX: event.clientX,
      axis: "none",
      step: Math.max(DRAG_MIN_STEP_PX, width * DRAG_STEP_FRACTION),
    };
  }, []);

  const handlePointerMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const stage = stageRef.current;
      const root = rootRef.current;
      if (!stage || !root) return;

      const gesture = dragRef.current;
      if (!gesture || gesture.pointerId !== event.pointerId) {
        if (pointerTiltEnabled) applyTilt(root, stage, event.clientX, event.clientY);
        return;
      }

      if (gesture.axis === "none") {
        const dx = event.clientX - gesture.startX;
        const dy = event.clientY - gesture.startY;
        if (Math.abs(dx) < DRAG_AXIS_LOCK_PX && Math.abs(dy) < DRAG_AXIS_LOCK_PX) return;
        // A vertical gesture belongs to the page, not to the carousel: never fight the scroll.
        gesture.axis = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
        if (gesture.axis !== "x") return;
        suppressClickRef.current = true;
        root.dataset.carouselDragging = "true";
        // Captured only once the gesture is committed, so a plain tap still reaches the case.
        try {
          stage.setPointerCapture(event.pointerId);
        } catch {
          // A pointer that has already been released cannot be captured; the drag still tracks.
        }
      }
      if (gesture.axis !== "x") return;

      // Every threshold crossed is one event into the reducer — the carousel keeps no index.
      let travel = event.clientX - gesture.anchorX;
      while (travel <= -gesture.step) {
        onNext();
        gesture.anchorX -= gesture.step;
        travel += gesture.step;
      }
      while (travel >= gesture.step) {
        onPrevious();
        gesture.anchorX += gesture.step;
        travel -= gesture.step;
      }

      const lean = Math.max(
        -DRAG_ELASTIC_PX,
        Math.min(DRAG_ELASTIC_PX, travel * DRAG_ELASTIC_RATIO),
      );
      root.style.setProperty("--drop-tracks-drag", `${lean.toFixed(1)}px`);
    },
    [onNext, onPrevious, pointerTiltEnabled],
  );

  const endDrag = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const gesture = dragRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    dragRef.current = null;

    const stage = stageRef.current;
    if (stage?.hasPointerCapture(event.pointerId)) stage.releasePointerCapture(event.pointerId);

    const root = rootRef.current;
    if (!root) return;
    root.dataset.carouselDragging = "false";
    root.style.setProperty("--drop-tracks-drag", "0px");
  }, []);

  const handlePointerLeave = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      endDrag(event);
      const root = rootRef.current;
      if (!root) return;
      root.style.setProperty("--drop-tracks-tilt-x", "0");
      root.style.setProperty("--drop-tracks-tilt-y", "0");
    },
    [endDrag],
  );

  const handleSelect = useCallback(
    (index: number) => {
      if (suppressClickRef.current) {
        suppressClickRef.current = false;
        return;
      }
      onSelect(index);
    },
    [onSelect],
  );

  /* ----------------------------------------------------------------- render */

  return (
    <>
      {/*
        Brief §7.8 opens the scene with a large TRACKS heading, and the reference composition
        centres it above the field. Both languages come from the lens's own section label: the
        Persian is the dominant line because Persian is the primary language, with the Latin word
        the brief names carried beneath it. No count, no copy of this file's own invention.
      */}
      <h2
        ref={headingRef}
        className={`${styles.heading} ${styles.readingGround} ${styles.entranceGate}`}
        id={headingId}
        data-section-heading="tracks"
        data-tracks-entered={entered}
      >
        <span className={styles.headingFa} dir="rtl">
          {heading.fa}
        </span>
        <span className={styles.headingEn} lang="en" dir="ltr">
          {heading.en ?? heading.fa}
        </span>
      </h2>

      <div
        ref={rootRef}
        className={`${styles.carousel} ${styles.entranceGate}`}
        role="group"
        aria-labelledby={headingId}
        onKeyDown={handleKeyDown}
        data-tracks-entered={entered}
        data-tracks-carousel
        data-track-count={count}
        data-track-index={activeIndex}
        data-carousel-slots={slots}
        data-carousel-motion={reducedMotion ? "static" : "animated"}
        data-carousel-quality={tier}
      >
        <div
          ref={stageRef}
          className={styles.stage}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onPointerLeave={handlePointerLeave}
        >
          {/* `role="list"` because `list-style: none` costs the list its semantics in Safari. */}
          <ol className={styles.cases} role="list" data-tracks>
            {tracks.map((track, index) => {
              const offset = ringOffset(index, activeIndex, tracks.length);
              const distance = Math.abs(offset);
              const active = index === activeIndex;
              const inField = distance <= slots;
              const style: TrackStyle = {
                "--track-travel": String(caseTravel(offset, slots)),
                "--track-depth": caseDepth(offset, slots).toFixed(3),
                "--track-presence": casePresence(offset, slots).toFixed(3),
                zIndex: Math.max(1, CASE_STACK_TOP - distance),
              };

              return (
                <li
                  key={track.id}
                  className={styles.track}
                  style={style}
                  data-track
                  data-index={index}
                  data-active={active}
                  data-offset={offset}
                  data-in-field={inField}
                  aria-current={active ? "true" : undefined}
                  // Past the painted positions a case is scenery for nobody: out of the tab
                  // order, out of the a11y tree, and not clickable while it is invisible.
                  {...(inField ? {} : { inert: true, "aria-hidden": true })}
                >
                  <div className={styles.case}>
                    {/*
                      Roving tabindex: the active case is the carousel's single tab stop, and the
                      arrow keys move between tracks from there. Selecting a neighbour routes
                      through the same reducer as scroll — this scene keeps no index of its own.
                    */}
                    <button
                      type="button"
                      className={styles.caseButton}
                      data-track-case
                      tabIndex={sceneActive && active ? 0 : -1}
                      /*
                        `aria-current`, not `aria-pressed`: this button selects one item out of a
                        set, it is not a toggle, and aria-current is already this repo's vocabulary
                        for "the current one of a set".
                      */
                      aria-current={active ? "true" : undefined}
                      aria-label={`${SELECT_TRACK_LABEL}: ${track.title} — ${track.artist}`}
                      onClick={() => handleSelect(index)}
                    >
                      {/*
                        Three nested layers, one transform each, so the step, the ambient float
                        and the pointer tilt can never fight over a single `transform` slot:
                        `.case` travels, `.caseFloat` breathes, `.caseTilt` leans, and
                        `.caseBody` is the plastic itself. They have to NEST — a float on an
                        empty sibling would animate nothing.
                      */}
                      <span className={styles.caseFloat}>
                        <span className={styles.caseTilt}>
                          {/*
                            Painted back to front, the way the object is actually built: the disc
                            sits INSIDE the case, so the hinged spine and the gloss on the outer
                            plastic both pass over its left edge rather than under it.
                          */}
                          <span className={styles.caseBody}>
                            <TrackDisc track={track} environment={PAINT_ENVIRONMENT} />
                            <span className={styles.spine} aria-hidden="true" />
                            <span className={styles.gloss} aria-hidden="true" />
                          </span>
                        </span>
                      </span>
                    </button>
                  </div>

                  {/*
                    Brief §7.8: "Under the active case: song title first, artist second, optional
                    time-of-day group label third." The caption is a sibling of the case rather
                    than a child of it, so it holds still and stays legible while the case it
                    belongs to travels, scales and tilts.
                  */}
                  <div
                    className={`${styles.caption} ${styles.readingGround}`}
                    data-track-caption
                    dir="rtl"
                    {...(active ? {} : { inert: true, "aria-hidden": true })}
                  >
                    <p className={styles.title}>
                      {track.sourceUrl ? (
                        <a
                          className={styles.sourceLink}
                          href={track.sourceUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          tabIndex={active ? 0 : -1}
                          data-track-source
                          data-external="true"
                        >
                          <span data-track-title lang="en" dir="ltr">
                            {track.title}
                          </span>
                          <span className="visually-hidden"> ({EXTERNAL_LINK_NOTE})</span>
                        </a>
                      ) : (
                        <span data-track-title lang="en" dir="ltr">
                          {track.title}
                        </span>
                      )}
                    </p>
                    <p className={styles.artist} data-track-artist lang="en" dir="ltr">
                      {track.artist}
                    </p>
                    <p className={styles.group} data-track-group data-track-period={track.period}>
                      {track.groupTitle.fa}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>

          {/*
            Brief §7.8 and §15: visible arrow controls, keyboard accessible, on every viewport.
            Never disabled at the ends — the reducer clamps the index, and a control that
            disappears from the interaction model at the edges is a control that cannot be
            relied on.
          */}
          <button
            type="button"
            className={`${styles.control} ${styles.previous}`}
            data-carousel-control="prev"
            aria-label={CAROUSEL_PREVIOUS_LABEL}
            onClick={onPrevious}
          >
            <span className={styles.controlGlyph} aria-hidden="true">
              ‹
            </span>
          </button>
          <button
            type="button"
            className={`${styles.control} ${styles.next}`}
            data-carousel-control="next"
            aria-label={CAROUSEL_NEXT_LABEL}
            onClick={onNext}
          >
            <span className={styles.controlGlyph} aria-hidden="true">
              ›
            </span>
          </button>
        </div>
      </div>
    </>
  );
}

/* -------------------------------------------------------------------- the disc */

/**
 * The disc inside one case: the track's artwork clipped onto the circle, or a branded DROP disc
 * where this environment may not paint the asset.
 *
 * The artwork is the disc's surface — clipped to the circle, spinning with it, with the clear
 * hub sitting over its centre exactly as it does on a real CD. It is never a square card laid on
 * top. `canDisplayAsset` is the only authority on whether the asset paints at all, and the
 * stand-in carries the same localized alt text so the meaning survives the substitution.
 *
 * Two ways the artwork can be absent, one stand-in: the environment may not paint it, or the file
 * itself failed to load. Brief §7.8 asks for a branded DROP disc in that case and explicitly not
 * for a broken image, so a failed load falls back to exactly the same disc — and says so in
 * `data-track-artwork`, rather than leaving the DOM claiming an asset that never arrived. The
 * failure flag is presentation state about one image; it is not, and must never become, anything
 * the carousel's active index is derived from.
 */
function TrackDisc({
  track,
  environment,
}: {
  track: TrackRecommendation;
  environment: RuntimeEnvironment;
}) {
  const asset = track.artwork;
  const alt = asset.alt.fa;
  const [loadFailed, setLoadFailed] = useState(false);
  const painted = canDisplayAsset(asset, environment) && !loadFailed;

  return (
    <span className={styles.disc} data-track-artwork={painted ? "asset" : "placeholder"}>
      {painted ? (
        <Image
          className={styles.discArtwork}
          src={asset.src}
          alt={alt}
          width={asset.width}
          height={asset.height}
          sizes="(max-width: 767px) 46vw, (max-width: 1199px) 24vw, 16vw"
          onError={() => setLoadFailed(true)}
        />
      ) : (
        <span
          className={`${styles.discArtwork} ${styles.discPlaceholder}`}
          role="img"
          aria-label={alt}
        >
          <DropWordmark className={styles.placeholderMark} variant="light" />
        </span>
      )}
      <span className={styles.discSheen} aria-hidden="true" />
      <span className={styles.discHub} aria-hidden="true" />
    </span>
  );
}

/* --------------------------------------------------------------- environment */

/**
 * The environment readers behind this scene's three `useSyncExternalStore` calls.
 *
 * Each pair is a live reader plus the value the server (and the hydration pass) sees instead.
 * Keeping them at module scope keeps their identities stable, which is what stops the store
 * from resubscribing on every render.
 */

/** A store that cannot change after the first read; React still re-checks it once after mount. */
function neverChanges(): () => void {
  return () => {};
}

function subscribeViewport(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("resize", onChange, { passive: true });
  return () => window.removeEventListener("resize", onChange);
}

function readSlots(): number {
  if (typeof window === "undefined") return DEFAULT_COVERFLOW_SLOTS;
  return coverflowSlots(window.innerWidth);
}

function readDefaultSlots(): number {
  return DEFAULT_COVERFLOW_SLOTS;
}

/** The one media query this scene reads directly: pointer tilt is a fine-pointer enhancement. */
const FINE_POINTER_QUERY = "(pointer: fine)";

function finePointerQuery(): MediaQueryList | null {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  try {
    return window.matchMedia(FINE_POINTER_QUERY);
  } catch {
    // A malformed-query throw must never take down a render.
    return null;
  }
}

function subscribeFinePointer(onChange: () => void): () => void {
  const list = finePointerQuery();
  if (!list || typeof list.addEventListener !== "function") return () => {};
  list.addEventListener("change", onChange);
  return () => list.removeEventListener("change", onChange);
}

function readFinePointer(): boolean {
  return finePointerQuery()?.matches === true;
}

function readDefaultFinePointer(): boolean {
  return false;
}

function readQualityTier(): QualityTier {
  if (typeof window === "undefined") return DEFAULT_QUALITY_TIER;
  // Cached by the module after the first probe, so this stays a stable snapshot.
  return detectEnvironmentQualityTier();
}

function readDefaultQualityTier(): QualityTier {
  return DEFAULT_QUALITY_TIER;
}

/* ---------------------------------------------------------------------- helpers */

/** Marks a case's button — the carousel's roving tab stop. Also the seam-3 hook for the case. */
const CASE_ATTRIBUTE = "data-track-case";
const ACTIVE_CASE_SELECTOR = `[data-track][data-active="true"] [${CASE_ATTRIBUTE}]`;

/**
 * Move the carousel's single tab stop onto the active case after the reducer steps.
 *
 * Only when the focus is already on a case: pressing an arrow *button* must leave the focus on
 * that button, and a drag must never yank it anywhere. `preventScroll` is not optional — this
 * scene is pinned, and letting the browser scroll a newly focused element into view would move
 * the very scroll position the reducer is reading its progress from.
 */
function followFocusToActiveCase(root: HTMLElement | null, dragging: boolean): void {
  if (!root || dragging || typeof document === "undefined") return;

  const focused = document.activeElement;
  if (!(focused instanceof HTMLElement)) return;
  if (!root.contains(focused) || !focused.hasAttribute(CASE_ATTRIBUTE)) return;

  const active = root.querySelector<HTMLElement>(ACTIVE_CASE_SELECTOR);
  if (active && active !== focused) active.focus({ preventScroll: true });
}

/**
 * Point the field's tilt at the pointer. Written as custom properties and smoothed by a CSS
 * transition on the tilt layer rather than by a tween, so the follow costs no timeline and
 * nothing is left ticking when the pointer leaves.
 */
function applyTilt(root: HTMLElement, stage: HTMLElement, clientX: number, clientY: number): void {
  const rect = stage.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return;
  const x = ((clientX - rect.left) / rect.width - 0.5) * 2;
  const y = ((clientY - rect.top) / rect.height - 0.5) * 2;
  root.style.setProperty("--drop-tracks-tilt-x", clampUnit(y).toFixed(3));
  root.style.setProperty("--drop-tracks-tilt-y", clampUnit(x).toFixed(3));
}

/** A drag in flight. Mutated in place: it is gesture bookkeeping, not rendered state. */
type DragGesture = {
  pointerId: number;
  startX: number;
  startY: number;
  /** Moves by one step each time a threshold is crossed, so a long drag steps repeatedly. */
  anchorX: number;
  /** `none` until the gesture commits; `y` hands the gesture back to the page's scroll. */
  axis: "none" | "x" | "y";
  step: number;
};

/** Per-case ordinal geometry. Derived from props alone, so server and client agree exactly. */
type TrackStyle = CSSProperties & {
  "--track-travel": string;
  "--track-depth": string;
  "--track-presence": string;
};

export default TracksScene;
