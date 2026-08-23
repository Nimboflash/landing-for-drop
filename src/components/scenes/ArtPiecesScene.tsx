"use client";

/**
 * Art Pieces / field notes — the editorial close of the lens body (brief §7.9, ticket 13).
 *
 * A section heading with a DATA-DRIVEN count, then one vertical editorial row per field note:
 * index, category, title, creator/year (or duration + label), and the selection rationale on the
 * physically LEFT side, sharp-edged media on the physically RIGHT side, a thin horizontal divider
 * between rows. The Monochrome Mesh keeps running underneath in its `reading` variant — that is
 * the shared canvas's business (ticket 10), not this scene's; nothing here paints a background.
 *
 * The X2Y motion reference contributes rhythm only. There are no rounded service cards, no
 * commerce control of any kind, and every string on screen comes from {@link ArtPiecesSceneProps}.
 *
 * ## This scene decides nothing
 *
 * No active index, no background mode, no scene progress of its own, and no ScrollTrigger that
 * decides which row is active — the scene-state reducer already decided all of it (BUILD-GUIDE
 * seam 2, one-way data flow). Everything below is a pure function of the props:
 *
 * | what | driven by |
 * | --- | --- |
 * | which row has priority (`data-active`, `data-art-phase`) | {@link ArtPiecesSceneProps.artIndex} |
 * | whether a row is composed or still masked (`data-art-revealed`) | `artIndex` + {@link ArtPiecesSceneProps.progress} |
 * | parallax offsets, entry zoom, dimming | `progress` (per-row local position) |
 * | masks vs. a plain fade | {@link ArtPiecesSceneProps.reducedMotion} |
 *
 * Because every one of those is a pure function of the props, reverse scroll reconstructs the
 * previous state exactly: the reducer walks `artIndex` and `progress` back down, and the rows
 * walk back with them. GSAP appears here for PRESENTATION ONLY — the line/clip masks and the
 * media's vertical crop reveal, tweened from booleans the reducer handed down, inside one
 * context that is reverted on unmount so nothing is left ticking.
 *
 * ## Media, and why the kind is sniffed from the file extension
 *
 * The media slot supports an image or a muted loop video (inline, pausable, never autoplaying
 * audio). The adopted content schema (`src/content/drop-weekly-lens.schema.ts`) has **no explicit
 * media-kind field**, and this ticket may not edit `src/content/**`, so {@link artMediaKind}
 * derives the kind from the asset's file extension. That is a documented stopgap: the schema
 * should grow a `kind: "image" | "video"` field, and this helper should then read it. W04 ships
 * images only, so the video path is built but never exercised by the seed.
 *
 * Nothing paints before {@link canDisplayAsset} says so. The W04 pack is `development-mock` /
 * `productionAllowed: false`, so it renders in development and is withheld in production — the
 * frame keeps its exact geometry either way (the aspect ratio comes from the asset's own
 * dimensions), so the layout is identical whether or not the rights check clears the image.
 * Alt text is localized and comes from the data, which is what keeps these images honest: they
 * are DROP concept studies, never photographs of the referenced original works. The asset's
 * `credit` is rendered with the media for the same reason.
 *
 * ## Reduced motion and no-JavaScript
 *
 * Reduced motion drops the masks and the parallax entirely: rows reveal by a simple fade and
 * every row stays fully readable, undimmed and undisplaced. Nothing in CSS ever hides content —
 * the masked state is written by GSAP after mount, exactly as in `GridStatementScene` — so a
 * JavaScript-disabled render shows the server-rendered rows as they will finally read.
 */

import Image from "next/image";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { DropO } from "@/components/brand";
import type { ArtPiece, LocalizedText, MediaAsset } from "@/content";
import { canDisplayAsset, type RuntimeEnvironment } from "@/content/rights";
import { gsap } from "@/lib/motion/gsap";

import styles from "./ArtPiecesScene.module.css";

/* ------------------------------------------------------------------ interface copy */

/**
 * Control and announcement copy — interface, not editorial content. The lens schema carries no
 * control labels, and these strings do not change when the lens does (same reasoning as the
 * carousel labels in the shell). Persian, because Persian is the primary language.
 */
const EXTERNAL_LINK_HINT = "پیوند بیرونی — در تب تازه باز می‌شود";
const VIDEO_PLAY_LABEL = "پخش ویدیو";
const VIDEO_PAUSE_LABEL = "توقف ویدیو";

/* ------------------------------------------------------------------ tuning */

/**
 * Brief §6: "Art Pieces: 75-95vh per item" — the scroll the shell budgets for one row. One
 * viewport of that budget is spent scrolling the last row up into view, so the scroll distance
 * the reducer spends inside a single row's band is `perItem - 100/count`. Matching the row's
 * layout pitch to it is what keeps the row the reducer calls active near the middle of the
 * viewport when it lights up. Purely a layout constant; nothing asserts it.
 */
const ROW_SCROLL_VH = 85;
/** Floor for short lenses, so a one-item field-note section still reads as an editorial row. */
const MIN_ROW_PITCH_SVH = 46;

/**
 * How far ahead of its own band a row starts entering, in band units. `-0.45` puts the next
 * row's reveal in the second half of the active row's band, which is what "adjacent rows may
 * partially enter/leave" (brief §7.9) looks like from the row's side.
 */
const REVEAL_LEAD = -0.45;
/**
 * The scene progress at which the FIRST row is considered started.
 *
 * `progress` is 0 both before the scene is reached and at its very first pixel, so the first row
 * — unlike every later one — has no earlier band to enter from. Waiting for a non-zero progress
 * is what lets it enter through its masks instead of being composed before the reader arrives.
 */
const SCENE_START_EPSILON = 0.001;

/** Parallax amplitudes, in svh, across one row's travel. Mild, and deliberately unequal. */
const MEDIA_PARALLAX_SVH = 3.4;
const TEXT_PARALLAX_SVH = -1.2;
const TITLE_PARALLAX_SVH = -1.1;
/** Entry zoom on the media, resolving to 1 as the row enters. Restrained. */
const MEDIA_ENTRY_ZOOM = 0.055;

/** Dimming of rows that do not hold priority. Kept high so contrast never falls to a whisper. */
const ADJACENT_DIM = 0.82;
const DISTANT_DIM = 0.7;
/** Veil over non-priority media. Restrained: the image stays legible, it just steps back. */
const ADJACENT_VEIL = 0.24;
const DISTANT_VEIL = 0.34;

/** Reveal timing. Cinematic and weighted (brief §9), never a bouncy app spring. */
const REVEAL_DURATION_S = 0.85;
const REVEAL_STAGGER_S = 0.07;
/** The media opens a touch slower than the text, so the two read at different speeds. */
const MEDIA_REVEAL_DURATION_S = 1.05;
/** Putting a row back is quicker than the reveal — a retreat, not a second performance. */
const HIDE_DURATION_S = 0.4;
/** Reduced motion: one plain fade, no mask, no displacement. */
const FADE_DURATION_S = 0.3;
/** `power4.out` is GSAP's read of `--ease-cinematic` (cubic-bezier(0.22, 1, 0.36, 1)). */
const REVEAL_EASE = "power4.out";
const HIDE_EASE = "power2.in";

/** How far below its mask a line waits, as a percentage of its own height. */
const MASKED_Y_PERCENT = 112;

const LINE_OPEN = { yPercent: 0, opacity: 1 } as const;
const LINE_MASKED = { yPercent: MASKED_Y_PERCENT, opacity: 0 } as const;
/** The media's vertical crop: closed from the top edge, opening downward over the frame. */
const CLIP_OPEN = { clipPath: "inset(0% 0% 0% 0%)" } as const;
const CLIP_CLOSED = { clipPath: "inset(100% 0% 0% 0%)" } as const;

/* ------------------------------------------------------------------ pure helpers */

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

/** Two-digit editorial number, derived from position or count — never stored in the content. */
function twoDigit(value: number): string {
  return String(Math.max(0, Math.trunc(value))).padStart(2, "0");
}

/** Media kinds this scene can paint. */
export type ArtMediaKind = "image" | "video";

/** Extensions that mean "muted loop video". `.webm` is a video; `.webp` is not. */
const VIDEO_EXTENSIONS: ReadonlySet<string> = new Set(["mp4", "webm", "m4v", "mov", "ogv"]);

/**
 * Which kind of media an asset is.
 *
 * SCHEMA GAP: the adopted `mediaAssetSchema` has no explicit kind, so the file extension is the
 * only signal available to a component that may not edit `src/content/**`. Replace this with the
 * schema field the moment one exists — a `/media/…/study` with no extension, or a content type
 * that does not match its extension, is invisible to this reading.
 */
export function artMediaKind(asset: Pick<MediaAsset, "src">): ArtMediaKind {
  const path = asset.src.split(/[?#]/, 1)[0] ?? "";
  const lastSlash = path.lastIndexOf("/");
  const name = lastSlash === -1 ? path : path.slice(lastSlash + 1);
  const dot = name.lastIndexOf(".");
  if (dot === -1) return "image";
  return VIDEO_EXTENSIONS.has(name.slice(dot + 1).toLowerCase()) ? "video" : "image";
}

/**
 * Where a row stands relative to the row the reducer made active. Ordinal and symmetric, so a
 * forward pass and its reverse produce mirrored trajectories.
 */
export type ArtRowPhase = "passed" | "leaving" | "active" | "entering" | "upcoming";

function rowPhase(index: number, activeIndex: number): ArtRowPhase {
  if (index === activeIndex) return "active";
  if (index === activeIndex - 1) return "leaving";
  if (index === activeIndex + 1) return "entering";
  return index < activeIndex ? "passed" : "upcoming";
}

/**
 * Whether a row is composed (masks open) or still waiting behind them.
 *
 * @param local  the row's position in band units: 0 when its own band starts, 1 when it ends.
 */
function rowRevealed(
  index: number,
  activeIndex: number,
  local: number,
  sceneProgress: number,
): boolean {
  // Rows the reducer has already walked past are composed, whatever the progress value says.
  if (index < activeIndex) return true;
  // The active row. The first row waits for the scene to have actually started; see
  // SCENE_START_EPSILON.
  if (index === activeIndex) return index > 0 || sceneProgress > SCENE_START_EPSILON;
  // Rows still ahead: only the next one enters, and only in the second half of the active band.
  return local >= REVEAL_LEAD;
}

/**
 * The environment the media-rights check is made in.
 *
 * `resolveRuntimeEnvironment()` reads `DROP_ENV` / `NODE_ENV` through a DYNAMIC lookup, which no
 * bundler can inline into a client bundle: in the browser `process.env` is an empty shim, so that
 * function always answers `"development"` there. A scene that asked it directly would paint mock
 * media on the client while the server (which reads the real environment) rendered none — a
 * hydration mismatch, and a rights leak in production.
 *
 * A STATIC `process.env.NODE_ENV` is inlined on both sides, so it is the one reading guaranteed
 * identical during server render and hydration. `staging` therefore cannot be distinguished from
 * `development` in a client scene; the difference between them is `rights-pending` display, which
 * is gated by an internal flag the browser cannot read either. Both readings are plumbing the
 * integrator should hand down as a server-resolved prop when a lens needs them.
 */
const PAINT_ENVIRONMENT: RuntimeEnvironment =
  process.env.NODE_ENV === "production" ? "production" : "development";

/* ------------------------------------------------------------------ props */

export interface ArtPiecesSceneProps {
  /** The lens's Art Pieces section label. Both languages render; nothing is written into here. */
  heading: LocalizedText;
  /** The field notes, in order. The section's count is this array's length, never a literal. */
  pieces: readonly ArtPiece[];
  /** The reducer's `transitionState.artIndex`: which row holds priority. */
  artIndex: number;
  /**
   * The Art Pieces scene's own progress, 0..1: 0 before the scene is reached, ramping to 1 as
   * its budget scrolls past, and 1 for every scene after it. The shell derives it from the
   * reducer's `sceneProgress` and the active scene's position in `SCENE_ORDER` — this scene
   * never computes it.
   */
  progress: number;
  /** The reducer's reduced-motion flag: plain fades, no masks, no parallax. */
  reducedMotion: boolean;
}

/* ------------------------------------------------------------------ component */

export function ArtPiecesScene({
  heading,
  pieces,
  artIndex,
  progress,
  reducedMotion,
}: ArtPiecesSceneProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const contextRef = useRef<gsap.Context | null>(null);
  /** The reveal flags last written to the DOM, so only rows that changed are re-animated. */
  const appliedRef = useRef<string | null>(null);
  /** Which motion mode those flags were written in; a mode change re-applies everything. */
  const appliedMotionRef = useRef<string | null>(null);

  const count = pieces.length;
  const scene = clamp01(progress);
  const activeIndex = count === 0 ? 0 : clamp(Math.trunc(artIndex), 0, count - 1);

  const rows = pieces.map((piece, index) => {
    // The row's own position in band units. `artIndex` is the reducer's floor of this value, so
    // the two agree by construction — this only adds the sub-band detail parallax needs.
    const local = count === 0 ? 0 : scene * count - index;
    const phase = rowPhase(index, activeIndex);
    const revealed = rowRevealed(index, activeIndex, local, scene);
    // 0 while the row is still below, 1 once it has properly entered. Drives the entry zoom and
    // the restrained sweep that dissipates as the row settles.
    const entered = clamp01(local + 0.6);
    // Centred on the row's midpoint so a row's parallax passes through zero as it holds priority.
    const travel = clamp(local, -1.2, 2.2) - 0.5;
    return { piece, index, phase, revealed, entered, travel };
  });

  /** Stable primitive dependency: one character per row, plus the motion mode. */
  const revealFlags = rows.map((row) => (row.revealed ? "1" : "0")).join("");
  const motionKey = reducedMotion ? "reduced" : "full";

  /**
   * One GSAP context for the scene's whole lifetime; reverting it on unmount kills every tween
   * created through it and undoes the inline styles they wrote (brief §9, §17).
   *
   * NOTE — why not `createMotionScope()` from `@/lib/motion/gsap`: that helper builds its context
   * with `gsap.context(undefined, root)`, and GSAP reads a falsy first argument as "give me the
   * CURRENTLY ACTIVE context" (`context: (func, scope) => func ? new Context(func, scope) :
   * _context` in `gsap-core.js`). Outside a context that is `undefined`, so `scope.run()` throws
   * on the first client render. `useSceneStateMachine` documents the same one-line fix and the
   * same workaround; this scene should move back onto the helper the moment it lands.
   */
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const context = gsap.context(() => {}, root);
    contextRef.current = context;
    return () => {
      context.revert();
      contextRef.current = null;
      appliedRef.current = null;
      appliedMotionRef.current = null;
    };
  }, []);

  /**
   * The reveal, driven by the reducer's index and nothing else.
   *
   * The masked state is written here rather than in CSS on purpose: with scripting off there is
   * no reducer to declare anything revealed, and text the server rendered must not be waiting
   * behind a mask that will never open.
   */
  useEffect(() => {
    const context = contextRef.current;
    const root = rootRef.current;
    if (!context || !root) return;

    const previousFlags = appliedRef.current;
    const previousMotion = appliedMotionRef.current;
    // First application after mount (or after the motion mode flipped) is instant: there is no
    // earlier state to animate away from, and a reader arriving mid-page must not watch a
    // retroactive performance.
    const instant = previousFlags === null || previousMotion !== motionKey;

    appliedRef.current = revealFlags;
    appliedMotionRef.current = motionKey;

    context.add(() => {
      const elements = root.querySelectorAll<HTMLElement>("[data-art-piece]");
      elements.forEach((element, index) => {
        const revealed = revealFlags[index] === "1";
        if (!instant && previousFlags?.[index] === revealFlags[index]) return;
        applyRowMotion(element, revealed, instant, reducedMotion);
      });
      // The heading enters with the first row: it is the same arrival.
      const headingRevealed = revealFlags[0] === "1";
      if (instant || previousFlags?.[0] !== revealFlags[0]) {
        applyLineMotion(
          root.querySelectorAll<HTMLElement>("[data-art-heading-line]"),
          headingRevealed,
          instant,
          reducedMotion,
        );
      }
    });
  }, [revealFlags, motionKey, reducedMotion]);

  const sceneStyle: SceneStyle = {
    "--art-count": String(count),
    // Matching the layout pitch to the reducer's band keeps the active row near the middle of
    // the viewport when it lights up. See ROW_SCROLL_VH.
    "--art-row-pitch": `${Math.max(
      MIN_ROW_PITCH_SVH,
      ROW_SCROLL_VH - 100 / Math.max(1, count),
    ).toFixed(2)}svh`,
  };

  return (
    <div ref={rootRef} className={styles.scene} style={sceneStyle} data-art-scene>
      <h2 className={styles.heading} data-section-heading="artPieces">
        <span className={styles.line}>
          <span className={styles.headingFa} data-art-heading-line dir="rtl">
            {heading.fa}
          </span>
        </span>
        <span className={styles.headingMeta}>
          {heading.en ? (
            <span className={styles.line}>
              <span className={styles.headingEn} data-art-heading-line lang="en" dir="ltr">
                {heading.en}
              </span>
            </span>
          ) : null}
          {/* Data-driven count (brief §7.9) — the array's length, never a written number. */}
          <span className={styles.line}>
            <span
              className={styles.headingCount}
              data-art-heading-line
              data-art-count
              lang="en"
              dir="ltr"
            >
              {twoDigit(count)}
            </span>
          </span>
        </span>
      </h2>

      <ol className={styles.rows} data-art-pieces>
        {rows.map(({ piece, index, phase, revealed, entered, travel }) => {
          const active = index === activeIndex;
          const dim = reducedMotion
            ? 1
            : phase === "active"
              ? 1
              : phase === "entering" || phase === "leaving"
                ? ADJACENT_DIM
                : DISTANT_DIM;
          const veil = active
            ? 0
            : phase === "entering" || phase === "leaving"
              ? ADJACENT_VEIL
              : DISTANT_VEIL;
          const rowStyle: RowStyle = {
            "--art-dim": dim.toFixed(3),
            "--art-veil": veil.toFixed(3),
            "--art-enter": reducedMotion ? "1" : entered.toFixed(3),
            "--art-media-shift": reducedMotion
              ? "0svh"
              : `${(travel * MEDIA_PARALLAX_SVH).toFixed(2)}svh`,
            "--art-text-shift": reducedMotion
              ? "0svh"
              : `${(travel * TEXT_PARALLAX_SVH).toFixed(2)}svh`,
            "--art-title-shift": reducedMotion
              ? "0svh"
              : `${(travel * TITLE_PARALLAX_SVH).toFixed(2)}svh`,
            "--art-media-zoom": reducedMotion
              ? "1"
              : (1 + MEDIA_ENTRY_ZOOM * (1 - entered)).toFixed(4),
          };

          return (
            <li
              key={piece.id}
              className={styles.row}
              style={rowStyle}
              data-art-piece
              data-index={index}
              data-active={active}
              data-art-phase={phase}
              data-art-revealed={revealed}
              aria-current={active ? "true" : undefined}
            >
              <ArtRowText piece={piece} index={index} />
              <ArtRowMedia piece={piece} reducedMotion={reducedMotion} />
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export default ArtPiecesScene;

/* ------------------------------------------------------------------ row: text */

function ArtRowText({ piece, index }: { piece: ArtPiece; index: number }) {
  // Optional fields must not leave gaps (brief §11): absent fields render nothing at all, and
  // the meta line itself disappears when every one of its fields is missing. W04's fourth item
  // (The Pratfall Effect) arrives with duration + label and no creator/year; it reads as a
  // complete row, not as a row with two holes in it.
  const hasMeta = Boolean(piece.creator || piece.year || piece.duration || piece.label);

  const title = piece.sourceUrl ? (
    <a
      className={styles.titleLink}
      href={piece.sourceUrl}
      target="_blank"
      rel="noopener noreferrer"
      data-art-source
      // Announced as external, and the visible title is part of the name (WCAG 2.5.3). The
      // outward marker is a CSS pseudo-element, so it never enters the title's text content.
      aria-label={`${piece.title} — ${EXTERNAL_LINK_HINT}`}
    >
      {piece.title}
    </a>
  ) : (
    piece.title
  );

  return (
    <div className={styles.text} dir="rtl">
      <p className={styles.index} data-art-index>
        <Line className={styles.latin} lang="en" dir="ltr">
          {twoDigit(index + 1)}
        </Line>
      </p>
      <p className={styles.category} data-art-category>
        <Line>{piece.category.fa}</Line>
      </p>
      <h3 className={styles.title} data-art-title lang="en" dir="ltr">
        <Line>{title}</Line>
      </h3>
      {hasMeta ? (
        <p className={styles.meta}>
          <Line>
            {piece.creator ? (
              <span className={styles.metaItem} data-art-creator lang="en" dir="ltr">
                {piece.creator}
              </span>
            ) : null}
            {piece.year ? (
              <span className={styles.metaItem} data-art-year lang="en" dir="ltr">
                {piece.year}
              </span>
            ) : null}
            {piece.duration ? (
              <span className={styles.metaItem} data-art-duration lang="en" dir="ltr">
                {piece.duration}
              </span>
            ) : null}
            {piece.label ? (
              <span className={styles.metaItem} data-art-label dir="rtl">
                {piece.label.fa}
              </span>
            ) : null}
          </Line>
        </p>
      ) : null}
      <p className={styles.rationale} data-art-rationale>
        <Line>{piece.rationale.fa}</Line>
      </p>
    </div>
  );
}

/**
 * One masked line: the parent clips, this element moves. GSAP writes the masked state after
 * mount, so with scripting off the line simply reads.
 */
function Line({
  children,
  className,
  lang,
  dir,
}: {
  children: ReactNode;
  className?: string;
  lang?: string;
  dir?: "rtl" | "ltr";
}) {
  return (
    <span
      className={className ? `${styles.lineInner} ${className}` : styles.lineInner}
      data-art-line
      lang={lang}
      dir={dir}
    >
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ row: media */

function ArtRowMedia({ piece, reducedMotion }: { piece: ArtPiece; reducedMotion: boolean }) {
  const asset = piece.media;
  const kind = artMediaKind(asset);
  const painted = canDisplayAsset(asset, PAINT_ENVIRONMENT);
  const isVideo = painted && kind === "video";
  // Always called, never conditionally: the hook is inert unless this row's media is a video.
  const { ref: videoRef, playing, toggle } = useLoopVideo(isVideo, reducedMotion);
  // The frame keeps the asset's own proportions whether or not the rights check clears it, so
  // the composition — and the scroll length it produces — never depends on the environment.
  const frameStyle: FrameStyle = { "--art-media-ratio": `${asset.width} / ${asset.height}` };

  return (
    <figure className={styles.mediaColumn}>
      <div
        className={styles.media}
        style={frameStyle}
        data-art-media
        data-art-media-kind={kind}
        data-art-media-painted={painted}
      >
        {painted ? (
          <>
            <div className={styles.mediaClip} data-art-media-clip>
              <div className={styles.mediaShift}>
                {isVideo ? (
                  /*
                   * A muted loop video: inline, never autoplaying audio, and pausable — brief
                   * §16, and WCAG 2.2.2 for anything that moves for more than five seconds.
                   * W04 ships images only, so this path exists for the schema, not the seed.
                   */
                  <video
                    ref={videoRef}
                    className={styles.mediaAsset}
                    data-art-video
                    src={asset.src}
                    width={asset.width}
                    height={asset.height}
                    aria-label={asset.alt.fa}
                    muted
                    loop
                    playsInline
                    preload="metadata"
                    autoPlay={!reducedMotion}
                  />
                ) : (
                  <Image
                    className={styles.mediaAsset}
                    src={asset.src}
                    alt={asset.alt.fa}
                    width={asset.width}
                    height={asset.height}
                    sizes="(max-width: 767px) 92vw, 44vw"
                  />
                )}
              </div>
              {/* Priority veil and the restrained entry sweep. Decorative, and never over text. */}
              <span className={styles.mediaVeil} aria-hidden="true" />
              <span className={styles.mediaSweep} aria-hidden="true" />
            </div>
            {/*
              The pause control lives OUTSIDE the crop and outside the parallax layer: a control
              that drifts with the image, or that the vertical crop reveal clips away, is not a
              control. It anchors to the frame, which never moves.
            */}
            {isVideo ? (
              <button
                type="button"
                className={styles.mediaControl}
                data-art-media-control
                data-playing={playing}
                onClick={toggle}
              >
                {playing ? VIDEO_PAUSE_LABEL : VIDEO_PLAY_LABEL}
              </button>
            ) : null}
          </>
        ) : (
          // Rights withheld the asset: a branded DROP slot, never a broken image (brief §7.8).
          // The asset's own localized description stays the accessible name — withholding the
          // PICTURE must not withhold the DESCRIPTION, or a screen reader loses the row's media
          // entirely (and in a production build every asset takes this branch). Menu, film and
          // track placeholders already do this; this scene was the outlier.
          <span className={styles.mediaWithheld} role="img" aria-label={asset.alt.fa}>
            <DropO className={styles.withheldMark} variant="light" />
          </span>
        )}
      </div>
      {painted && asset.credit ? (
        // Credit stays in the data whatever the scene does with it (brief §18); showing it is
        // also what keeps a concept study from reading as a photograph of the original work.
        <figcaption className={styles.credit} data-art-media-credit lang="en" dir="ltr">
          {asset.credit}
        </figcaption>
      ) : null}
    </figure>
  );
}

/**
 * Playback state for one loop video, and the element ref that carries it out.
 *
 * Reduced motion starts the video paused; otherwise it plays muted and looping. A browser that
 * refuses the play request has made a normal decision, not raised an error — the refusal is
 * reflected back into state so the control reads `play`, which is what the reader can now do.
 */
function useLoopVideo(enabled: boolean, reducedMotion: boolean) {
  const ref = useRef<HTMLVideoElement | null>(null);
  const [playing, setPlaying] = useState(!reducedMotion);
  const toggle = useCallback(() => setPlaying((value) => !value), []);

  useEffect(() => {
    const video = ref.current;
    if (!enabled || !video) return;
    if (!playing) {
      video.pause();
      return;
    }
    let cancelled = false;
    const refused = () => {
      if (!cancelled) setPlaying(false);
    };
    try {
      // `play()` resolves to a promise in browsers and to nothing in older/limited hosts.
      const started: unknown = video.play();
      if (started instanceof Promise) started.catch(refused);
    } catch {
      // A host that throws synchronously has refused exactly as a rejected promise does. Report
      // it back on a microtask so the effect body never sets state during its own run (which
      // would cascade a render), and so the cleanup below can still cancel it.
      void Promise.resolve().then(refused);
    }
    return () => {
      cancelled = true;
    };
  }, [enabled, playing]);

  return { ref, playing, toggle };
}

/* ------------------------------------------------------------------ motion */

/** Apply one row's reveal state: line masks, and the media's vertical crop. */
function applyRowMotion(
  row: HTMLElement,
  revealed: boolean,
  instant: boolean,
  reducedMotion: boolean,
): void {
  const lines = row.querySelectorAll<HTMLElement>("[data-art-line]");
  const clips = row.querySelectorAll<HTMLElement>("[data-art-media-clip]");

  if (reducedMotion) {
    // Simple fade, and nothing stays masked or displaced: every row is fully readable.
    gsap.set(lines, LINE_OPEN);
    if (clips.length > 0) gsap.set(clips, CLIP_OPEN);
    const opacity = revealed ? 1 : 0;
    if (instant) gsap.set(row, { opacity });
    else gsap.to(row, { opacity, duration: FADE_DURATION_S, ease: "none", overwrite: "auto" });
    return;
  }

  gsap.set(row, { opacity: 1 });
  applyLineMotion(lines, revealed, instant, false);

  if (clips.length === 0) return;
  if (instant) {
    gsap.set(clips, revealed ? CLIP_OPEN : CLIP_CLOSED);
    return;
  }
  gsap.to(clips, {
    ...(revealed ? CLIP_OPEN : CLIP_CLOSED),
    duration: revealed ? MEDIA_REVEAL_DURATION_S : HIDE_DURATION_S,
    ease: revealed ? REVEAL_EASE : HIDE_EASE,
    overwrite: "auto",
  });
}

/** Open or close a set of line masks. Shared by the rows and the section heading. */
function applyLineMotion(
  lines: NodeListOf<HTMLElement>,
  revealed: boolean,
  instant: boolean,
  reducedMotion: boolean,
): void {
  if (lines.length === 0) return;
  if (reducedMotion) {
    gsap.set(lines, LINE_OPEN);
    return;
  }
  if (instant) {
    gsap.set(lines, revealed ? LINE_OPEN : LINE_MASKED);
    return;
  }
  gsap.to(lines, {
    ...(revealed ? LINE_OPEN : LINE_MASKED),
    duration: revealed ? REVEAL_DURATION_S : HIDE_DURATION_S,
    ease: revealed ? REVEAL_EASE : HIDE_EASE,
    stagger: revealed ? REVEAL_STAGGER_S : 0,
    overwrite: "auto",
  });
}

/* ------------------------------------------------------------------ style types */

/** Custom properties the stylesheet reads for the section's rhythm. */
type SceneStyle = CSSProperties & {
  "--art-count": string;
  "--art-row-pitch": string;
};

/** Custom properties the stylesheet reads for one row's parallax and priority. */
type RowStyle = CSSProperties & {
  "--art-dim": string;
  "--art-veil": string;
  "--art-enter": string;
  "--art-media-shift": string;
  "--art-text-shift": string;
  "--art-title-shift": string;
  "--art-media-zoom": string;
};

/** The media frame's proportions, from the asset's own dimensions. */
type FrameStyle = CSSProperties & {
  "--art-media-ratio": string;
};
