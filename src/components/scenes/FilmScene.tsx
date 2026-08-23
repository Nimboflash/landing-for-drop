"use client";

/**
 * Film and series recommendations — the pinned three-view sequence (brief §7.6, ticket 09) and
 * the film half of pixel transition B (brief §7.7, ticket 11).
 *
 * One recommendation is on screen at a time: the information column physically LEFT (ordinal,
 * view label, title, director, year, genres, Persian rationale) and one large vertical poster
 * physically RIGHT, entering from the lower right with a slight rotation and scale, leaving
 * upward and outward as the next one arrives, with two subtle paper layers stacked behind it.
 * Never three posters side by side as static cards.
 *
 * ## This scene decides nothing
 *
 * `filmIndex`, `progress` and `filmFade` are scene-state reducer output, handed down by the
 * shell (BUILD-GUIDE seam 2, one-way data flow). Nothing here computes an active index, a scene
 * progress or a background mode, and this scene creates NO ScrollTrigger of its own — the
 * reducer already decided which film is active, and a second progress source would make the
 * seam-2 tests meaningless. GSAP appears for PRESENTATION ONLY: poster travel and line masks,
 * tweened from the index the reducer hands down.
 *
 * ## Pose is a pure function of the reducer's index — which is what makes it reversible
 *
 * Every film sits in one of three poses, chosen only by where it stands relative to
 * `filmIndex`: *waiting* (below and right of the frame, not yet arrived), *active* (at rest,
 * crisp and dominant), *exited* (lifted up and out). Because the pose is derived rather than
 * remembered, scrolling back does not need to know it is scrolling back — a film that stops
 * being active travels to whichever pose its new relation implies, so reverse scroll is the
 * exact mirror of forward scroll by construction (brief §9).
 *
 * ## The fade into pixel transition B
 *
 * `filmFade` runs 1 → 0 across pixel transition B (brief §7.7: "Film content must not disappear
 * abruptly"). It is applied as a plain custom property, so it is a pure function of the prop and
 * reverses exactly, and it is reflected into the DOM as {@link FilmFadePhase} plus a percentage
 * so the page seam can assert *when* film content fades without reading computed styles.
 *
 * ## The holding layer
 *
 * §7.7 can only be true — "Film 03 remains visible. With continued scroll, the poster and left
 * description begin fading" — if the film stage is still on screen while the mosaic runs. The
 * scene stage cannot do that on its own: a pinned section releases its sticky child a full
 * viewport before the next scene's scroll window opens, so film 03 would have scrolled away
 * before the first cell flipped. So while the scene is live — entered ({@link FilmSceneProps.progress}
 * above 0) and not yet cleared by the fade — it renders on a viewport-fixed holding layer whose
 * padding repeats the stage's, which puts it in the very same place. The switch into the layer
 * happens at the very start of the scene, where the sticky child is already flush with the
 * viewport and the two positions coincide exactly; the switch back out happens at zero opacity.
 * `data-film-hold` reports which state it is in.
 *
 * The cost is deliberate: film 03 then HOLDS, unmoved, across the hand-over into pixel
 * transition B rather than sliding away — which is precisely the beat §7.7 asks for before the
 * fade begins. This is the same device the grid statement uses on the other side of the films.
 *
 * ## Rights, and what these posters are
 *
 * Nothing paints before {@link canDisplayAsset} says it may: the mock pack is
 * `development-mock` / `productionAllowed: false`, so these posters render in development and
 * staging and are withheld in production, where the frame falls back to a branded DROP mark
 * carrying the asset's localized alt text as its accessible name. The poster's `credit` from the
 * data is rendered as a small caption — these are original DROP concept posters and must never
 * be presented as official film posters (brief §18).
 *
 * ## Observable state (BUILD-GUIDE seam 3)
 *
 * Kept exactly as the shell placeholder emitted them: `data-section-heading="films"`,
 * `data-films`, and per film `data-film`, `data-index`, `data-active`, `aria-current`,
 * `data-film-view-label`, `data-film-title`, `data-film-director`, `data-film-year`,
 * `data-film-genres`, `data-film-rationale`, `data-film-media`. Added by this ticket:
 * `data-film-fade` / `data-film-fade-percent` (the pixel-B fade), `data-film-hold`,
 * `data-film-stage`, `data-film-number`, `data-film-credit`, `data-poster-src`,
 * `data-poster-state`, `data-film-source-link`.
 *
 * ## Reduced motion, no JavaScript, no GSAP
 *
 * Reduced motion swaps films by a short opacity crossfade with no travel and no parallax; all
 * three stay reachable. The server-rendered markup is a plain editorial list of all three films,
 * so a JavaScript-disabled render reads every recommendation in full — the single-film stage,
 * and the `inert` on the films that are not active, are switched on only once the motion context
 * is live and can actually move them.
 */

import Image from "next/image";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { DropWordmark } from "@/components/brand";
import type { FilmRecommendation, LocalizedText, MediaAsset } from "@/content";
import { canDisplayAsset, resolveRuntimeEnvironment } from "@/content/rights";
import { gsap } from "@/lib/motion/gsap";

import styles from "./FilmScene.module.css";

/* ------------------------------------------------------------------ tuning */

/**
 * Rendered poster width at each breakpoint, so the browser picks a sensibly sized source
 * instead of assuming the poster is as wide as the viewport. Mirrors the widths the stylesheet
 * resolves for `.posterCard`.
 */
const POSTER_SIZES = "(max-width: 767px) 62vw, (max-width: 1199px) 34vw, 26vw";

/**
 * Interface copy, not editorial content: the lens schema carries no control labels, and this
 * string does not change when the lens does (same reasoning as the shell's carousel labels).
 * Persian, because Persian is the primary language. Announced through `aria-describedby` rather
 * than as visible text, so a subtly clickable title stays a title and never becomes a CTA.
 */
const EXTERNAL_LINK_NOTE = "پیوند بیرونی؛ در زبانهٔ تازه باز می‌شود.";

/** Poster travel. Slight rotation and scale, cinematic rather than springy (brief §7.6, §9). */
const POSTER_ACTIVE = { xPercent: 0, yPercent: 0, rotation: -1.2, scale: 1 } as const;
/** Not yet arrived: waiting below and to the right of the frame. */
const POSTER_WAITING = { xPercent: 16, yPercent: 24, rotation: 6.5, scale: 0.9 } as const;
/** Already shown: lifted upward and outward as the next poster takes the frame. */
const POSTER_EXITED = { xPercent: 7, yPercent: -28, rotation: -6, scale: 1.07 } as const;

/** Editorial text rides its own clip mask: below it while waiting, above it once it has left. */
const LINE_ACTIVE = { yPercent: 0, opacity: 1 } as const;
const LINE_WAITING = { yPercent: 120, opacity: 0 } as const;
const LINE_EXITED = { yPercent: -120, opacity: 0 } as const;

const ENTER_DURATION_S = 1.05;
const EXIT_DURATION_S = 0.78;
const LINE_STAGGER_S = 0.055;
/** Reduced motion: films swap by crossfade, nothing travels (brief §16). */
const CROSSFADE_DURATION_S = 0.32;
/** GSAP's read of `--ease-cinematic` / `--ease-material` from the token file. */
const ENTER_EASE = "power4.out";
const EXIT_EASE = "power2.inOut";

/* ------------------------------------------------------------------- pure */

/** Where film content stands in the pixel-B fade. Reflected into the DOM, never a style read. */
export type FilmFadePhase = "held" | "fading" | "cleared";

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

/**
 * The phase for a fade value. `filmFade` is 1 for every scene before pixel B and 0 for every
 * scene after it, so the phase walks back exactly as scroll reverses.
 */
export function filmFadePhase(filmFade: number): FilmFadePhase {
  const value = clamp01(filmFade);
  if (value >= 1) return "held";
  if (value <= 0) return "cleared";
  return "fading";
}

/** Two-digit editorial ordinal, derived from position — never stored in the content. */
function twoDigit(value: number): string {
  return String(value).padStart(2, "0");
}

/** Poster width ÷ height, from the asset's own dimensions. The natural poster rectangle. */
function posterRatio(poster: MediaAsset): string {
  if (!poster.width || !poster.height) return "0.6667";
  return (poster.width / poster.height).toFixed(4);
}

/* -------------------------------------------------------------- component */

export interface FilmSceneProps {
  /** `lens.sectionLabels.films`. The scene's own label; no copy is written into this file. */
  heading: LocalizedText;
  /** The lens's films, in view order. Counts and content come entirely from here. */
  films: readonly FilmRecommendation[];
  /** Reducer output: which recommendation is active. This scene never derives it. */
  filmIndex: number;
  /**
   * The **films scene's own** progress, scene-scoped exactly like the grid statement's: `0`
   * while the films scene has not been reached, its own `0..1` while it is the active scene,
   * and `1` for every scene after it. The shell derives it from `state.sceneProgress` and the
   * active scene's position in `SCENE_ORDER`; this scene never computes it.
   *
   * It drives the editorial parallax **and the holding layer** (see the note above), so it must
   * be the scene-scoped value and not the raw progress of whichever scene happens to be active
   * — a foreign scene's progress would lift the film stage over a scene it does not belong to.
   */
  progress: number;
  /** Reducer output: 1 → 0 across pixel transition B. Film content never cuts out. */
  filmFade: number;
  /** Reducer output: crossfade the films, drop the travel and the parallax. */
  reducedMotion: boolean;
}

type SceneStyle = CSSProperties & {
  "--drop-film-fade": string;
  "--drop-film-progress": string;
};

type PosterStyle = CSSProperties & { "--drop-poster-ratio": string };

export function FilmScene({
  heading,
  films,
  filmIndex,
  progress,
  filmFade,
  reducedMotion,
}: FilmSceneProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  /**
   * One GSAP context for the scene's lifetime; reverting it on unmount kills every tween made
   * through it and undoes the inline styles they wrote (brief §9, §17).
   *
   * Deliberately `gsap.context(fn, root)` rather than `createMotionScope(root)` from
   * `@/lib/motion/gsap`: that helper builds its context as `gsap.context(undefined, root)`, and
   * GSAP reads a falsy first argument as "give me the CURRENTLY ACTIVE context" — which is
   * `undefined` outside one, so `scope.run()` throws on the first client render. The same note
   * (and the same shape) is in `useSceneStateMachine`; when that one-line fix lands in the
   * motion module this scene should move back onto the shared helper.
   */
  const contextRef = useRef<ReturnType<typeof gsap.context> | null>(null);
  /** Has a pose been applied yet? The first application is instant; later ones animate. */
  const appliedRef = useRef(false);
  /**
   * The single-film stage. False until the motion context is live, so the server-rendered
   * markup — and any browser where GSAP cannot run — keeps every recommendation readable
   * instead of stacking three of them on top of one another.
   */
  const [staged, setStaged] = useState(false);

  const noteId = useId();

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    const context = gsap.context(() => {}, root);
    contextRef.current = context;
    setStaged(true);

    return () => {
      context.revert();
      contextRef.current = null;
      appliedRef.current = false;
    };
  }, []);

  /**
   * The choreography, driven by the reducer's index and nothing else. Poses are derived from
   * each film's relation to `filmIndex`, so forward and reverse produce mirrored trajectories.
   */
  useEffect(() => {
    const context = contextRef.current;
    const root = rootRef.current;
    if (!context || !root) return;

    const items = Array.from(root.querySelectorAll<HTMLElement>("[data-film]"));
    if (items.length === 0) return;

    const instant = !appliedRef.current;
    appliedRef.current = true;

    const apply = (
      targets: readonly Element[],
      vars: gsap.TweenVars,
      duration: number,
      ease: string,
    ): void => {
      if (targets.length === 0) return;
      if (instant) {
        // First application settles the scene silently — no travel, and no stagger to walk
        // through, so a freshly mounted (or remounted) scene is simply already in place.
        const { stagger: _stagger, ...settled } = vars;
        void _stagger;
        gsap.set(targets as Element[], settled);
        return;
      }
      gsap.to(targets as Element[], { ...vars, duration, ease, overwrite: "auto" });
    };

    context.add(() => {
      items.forEach((item, index) => {
        const active = index === filmIndex;
        const waiting = index > filmIndex;
        const duration = active ? ENTER_DURATION_S : EXIT_DURATION_S;
        const ease = active ? ENTER_EASE : EXIT_EASE;

        // The whole recommendation — poster and left column together — carries the swap.
        apply(
          [item],
          { opacity: active ? 1 : 0 },
          reducedMotion ? CROSSFADE_DURATION_S : duration,
          reducedMotion ? "none" : ease,
        );

        const card = item.querySelector<HTMLElement>("[data-film-poster]");
        if (card) {
          const pose =
            reducedMotion || active
              ? POSTER_ACTIVE
              : waiting
                ? POSTER_WAITING
                : POSTER_EXITED;
          apply([card], { ...pose }, duration, ease);
        }

        const lines = Array.from(item.querySelectorAll<HTMLElement>("[data-film-line]"));
        const linePose =
          reducedMotion || active ? LINE_ACTIVE : waiting ? LINE_WAITING : LINE_EXITED;
        apply(
          lines,
          { ...linePose, stagger: active && !reducedMotion ? LINE_STAGGER_S : 0 },
          duration,
          ease,
        );
      });
    });
  }, [filmIndex, reducedMotion, films.length]);

  const fade = clamp01(filmFade);
  const phase = filmFadePhase(fade);
  const sceneProgress = clamp01(progress);
  /** Live: the scene has been entered and its content has not yet faded out. */
  const held = sceneProgress > 0 && fade > 0;
  const style: SceneStyle = {
    "--drop-film-fade": fade.toFixed(3),
    // Neutral (mid-scene) under reduced motion, so the editorial parallax simply stops.
    "--drop-film-progress": (reducedMotion ? 0.5 : sceneProgress).toFixed(4),
  };

  const environment = resolveRuntimeEnvironment();

  return (
    <div
      ref={rootRef}
      className={styles.scene}
      style={style}
      data-film-fade={phase}
      data-film-fade-percent={Math.round(fade * 100)}
      data-film-hold={held}
    >
      <h2 className={styles.heading} data-section-heading="films" dir="rtl">
        {heading.fa}
      </h2>

      <ol className={styles.stage} data-films data-film-stage={staged ? "cinematic" : "editorial"}>
        {films.map((film, index) => {
          const active = index === filmIndex;
          const hidden = staged && !active;
          const poster = film.poster;
          const painted = canDisplayAsset(poster, environment);
          const posterStyle: PosterStyle = { "--drop-poster-ratio": posterRatio(poster) };
          const externalNoteId = `${noteId}-${film.id}`;

          const title: ReactNode = film.sourceUrl ? (
            // Brief §7.6: "make the title/poster subtly clickable rather than adding a large
            // CTA" — and only where the data actually carries a source.
            <a
              className={styles.titleLink}
              href={film.sourceUrl}
              target="_blank"
              rel="noopener noreferrer"
              aria-describedby={externalNoteId}
              data-film-source-link
            >
              {film.title}
            </a>
          ) : (
            film.title
          );

          return (
            <li
              key={film.id}
              className={styles.film}
              data-film
              data-index={index}
              data-active={active}
              aria-current={active ? "true" : undefined}
              {...(hidden ? { inert: true, "aria-hidden": true } : {})}
            >
              {/*
                Brief §7.6 / §16: information physically left, poster physically right — held by
                the grid in the stylesheet, never by flipping the document's direction. Each text
                run carries its own `dir`, so the Persian column reads right-to-left (and aligns
                right, as the brief allows) inside a composition whose column order is fixed.
              */}
              <div className={styles.info} dir="rtl">
                {/*
                  Every run rides its own clip mask: the `.line` wrapper is the mask and the
                  element inside it is what travels, so a run genuinely disappears behind an
                  edge instead of sliding over its neighbour (brief §9: masks/clip reveals for
                  editorial text).
                */}
                <div className={styles.line}>
                  <p className={styles.label} data-film-line>
                    <span className={styles.number} data-film-number lang="en" dir="ltr">
                      {twoDigit(index + 1)}
                    </span>
                    <span data-film-view-label>{film.viewLabel.fa}</span>
                  </p>
                </div>

                <div className={styles.line}>
                  <h3 className={styles.title} data-film-title data-film-line lang="en" dir="ltr">
                    {title}
                  </h3>
                </div>

                <div className={styles.line}>
                  <p className={styles.meta} data-film-line>
                    <span data-film-director lang="en" dir="ltr">
                      {film.director}
                    </span>
                    <span className={styles.separator} aria-hidden="true">
                      ·
                    </span>
                    <span data-film-year lang="en" dir="ltr">
                      {film.year}
                    </span>
                    {film.genres && film.genres.length > 0 ? (
                      <>
                        <span className={styles.separator} aria-hidden="true">
                          ·
                        </span>
                        <span data-film-genres>{film.genres.join(" — ")}</span>
                      </>
                    ) : null}
                  </p>
                </div>

                <div className={styles.line}>
                  <p className={styles.rationale} data-film-rationale data-film-line>
                    {film.rationale.fa}
                  </p>
                </div>

                {/*
                  Brief §18: credit stays with the media. These are original DROP concept
                  posters, and the caption is what keeps them from reading as official artwork.
                */}
                {poster.credit ? (
                  <div className={styles.line}>
                    <p
                      className={styles.credit}
                      data-film-credit
                      data-film-line
                      lang="en"
                      dir="ltr"
                    >
                      {poster.credit}
                    </p>
                  </div>
                ) : null}

                {film.sourceUrl ? (
                  <span id={externalNoteId} className="visually-hidden">
                    {EXTERNAL_LINK_NOTE}
                  </span>
                ) : null}
              </div>

              <div className={styles.posterColumn}>
                <div className={styles.posterCard} style={posterStyle} data-film-poster>
                  {/* Brief §7.6: "1-2 subtle paper layers behind the active poster." */}
                  <span className={styles.paper} data-film-paper="2" aria-hidden="true" />
                  <span className={styles.paper} data-film-paper="1" aria-hidden="true" />
                  <div
                    className={styles.posterMedia}
                    data-film-media
                    data-poster-src={poster.src}
                    data-poster-state={painted ? "painted" : "withheld"}
                  >
                    {painted ? (
                      <Image
                        className={styles.posterImage}
                        src={poster.src}
                        alt={poster.alt.fa}
                        fill
                        sizes={POSTER_SIZES}
                      />
                    ) : (
                      // Rights withheld: a branded DROP frame, never a broken image, and the
                      // asset's own localized description remains the accessible name.
                      <span className={styles.withheld} role="img" aria-label={poster.alt.fa}>
                        <DropWordmark className={styles.withheldMark} variant="light" />
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export default FilmScene;
