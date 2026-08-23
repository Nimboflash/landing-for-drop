"use client";

/**
 * The immersive shell: one Weekly Lens rendered as the ten-scene scroll journey of brief §6.
 *
 * ## What this component is
 *
 * The page-level composition and the single wiring point of the scene-state machine. It renders
 * the smooth-scroll provider, the shared background canvas, the persistent header and all ten
 * scene sections in `SCENE_ORDER`, and it hands each scene the slice of reducer output that
 * scene renders from. Nothing here computes scene, mode, or index state — it reads
 * `useSceneStateMachine()` and passes values down (BUILD-GUIDE seam 2, one-way data flow).
 *
 * ## Scenes
 *
 * Every scene's presentation lives in its own component under `src/components/scenes/`, with its
 * own CSS module. This file owns NO scene typography: it is composition and prop plumbing only.
 * Each scene renders exclusively from the props below — all of which are reducer output or the
 * `lens` prop — and no title, count, year, artist, media path or description is written here
 * (CLAUDE.md hard rule); counts come from array lengths inside the scenes.
 *
 * Media rights are each scene's decision, taken through `canDisplayAsset` at the point of paint:
 * the mock pack is `development-mock` / `productionAllowed: false`, so which assets may render in
 * which environment is that function's call, never this file's.
 *
 * ## Scene-scoped progress
 *
 * The reducer reports ONE progress value — how far through the *active* scene the page is. Most
 * scenes want their own 0..1: 0 before they are reached, their own progress while they hold the
 * viewport, and 1 once the page is past them (so a scene that has handed over stays in its
 * finished pose instead of snapping back to its entry pose). {@link scopedProgress} derives that
 * from `state.sceneId` + `state.sceneProgress` and the static `SCENE_ORDER` contract. It is
 * wiring, not a second state machine: it reads reducer output and consults a constant.
 *
 * ## Client component, server-rendered text
 *
 * `"use client"` because the state machine, Lenis and ScrollTrigger all need the browser — but
 * the tree is still prerendered on the server, so every word below is in the initial HTML and
 * readable with JavaScript disabled (brief §17). The one thing the server cannot know is which
 * scene is active, so no content is hidden behind `data-active`.
 */

import dynamic from "next/dynamic";
import { memo, useCallback, useMemo, type ReactNode } from "react";

import type { WeeklyLens } from "@/content";
import { ArtPiecesScene } from "@/components/scenes/ArtPiecesScene";
import { FilmScene } from "@/components/scenes/FilmScene";
import { FooterScene } from "@/components/scenes/FooterScene";
import { GridStatementScene } from "@/components/scenes/GridStatementScene";
import { MenuDeckScene } from "@/components/scenes/MenuDeckScene";
import { ThesisScene } from "@/components/scenes/ThesisScene";
import { TracksScene } from "@/components/scenes/TracksScene";
import { SCENE_ORDER, lensCounts, type SceneId } from "@/lib/scene";

import { SceneSection } from "./SceneSection";
import { SiteHeader } from "./SiteHeader";
import { SmoothScrollProvider } from "./SmoothScrollProvider";
import { sceneBudgets } from "./scene-budgets";
import { useSceneStateMachine } from "./useSceneStateMachine";

import styles from "./ImmersiveLensPage.module.css";

/**
 * The shared WebGL background (ticket 04): ONE fixed canvas whose mode is reducer output.
 * Loaded on the client only — it must never run during server render, and the page must remain
 * complete without it (brief §12, §15: WebGL is decorative, DOM content is the page).
 */
const BackgroundCanvas = dynamic(
  () => import("@/components/webgl/BackgroundCanvas").then((mod) => mod.BackgroundCanvas),
  { ssr: false },
);

/**
 * The entry loader (ticket 05) is the one sanctioned exception to the shared canvas: it renders
 * the material DROP logo on its OWN temporary overlay canvas above the DOM, then disposes it once
 * the O portal completes. Client-only, and the page stays complete without it.
 */
const LoaderScene = dynamic(
  () => import("@/components/scenes/LoaderScene").then((mod) => mod.LoaderScene),
  { ssr: false },
);

/**
 * Memoised at the wiring site, not inside the scene modules.
 *
 * The shell re-renders on every scroll frame (that is what scrubbed choreography is), but a
 * scene's props only change while it is the one being scrubbed: {@link scopedProgress} hands
 * every other scene a constant 0 or 1, and the lens arrays are the same references for the life
 * of the route. So nine of the ten scene trees reconcile to nothing per frame instead of being
 * walked. Nothing about behaviour depends on this — remove it and the page still renders
 * identically, only slower.
 */
const Thesis = memo(ThesisScene);
const MenuDeck = memo(MenuDeckScene);
const GridStatement = memo(GridStatementScene);
const Films = memo(FilmScene);
const Tracks = memo(TracksScene);
const ArtPieces = memo(ArtPiecesScene);
const Footer = memo(FooterScene);

export type ImmersiveLensPageProps = {
  /** The validated lens this page renders. Scenes receive their data from here, as props. */
  lens: WeeklyLens;
};

/* ---------------------------------------------------------------- the shell */

export function ImmersiveLensPage({ lens }: ImmersiveLensPageProps) {
  const counts = useMemo(() => lensCounts(lens), [lens]);
  const budgets = useMemo(() => sceneBudgets(counts), [counts]);

  const { state, dispatch, registerScene } = useSceneStateMachine({
    counts,
    contentMode: lens.contentMode,
  });
  const { transitionState } = state;

  /**
   * Scene contrast, straight from reducer output: `headerVariant` is the reducer's verdict on how
   * light or dark the active scene's ground is (brief §8 states it for the logo; the copy on top
   * of that ground has to follow the same verdict or it stops being readable). The loader's
   * `"hidden"` sits on the off-white loader ground, so it reads as a light ground too.
   */
  const contrast = transitionState.headerVariant === "light" ? "light" : "dark";

  const goToPreviousTrack = useCallback(() => dispatch({ type: "carouselPrev" }), [dispatch]);
  const goToNextTrack = useCallback(() => dispatch({ type: "carouselNext" }), [dispatch]);
  const goToTrack = useCallback(
    (index: number) => dispatch({ type: "carouselTo", index }),
    [dispatch],
  );

  /**
   * The loader reports exactly one fact upward — the O portal finished. The reducer owns what that
   * means for the rest of the page (header appears, hero takes over), keeping data flow one-way.
   */
  const completeLoader = useCallback(() => dispatch({ type: "loaderComplete" }), [dispatch]);

  /**
   * One scene's own 0..1 progress: 0 before it, `sceneProgress` while it is active, 1 after it.
   * Derived from reducer output and the static `SCENE_ORDER` contract — no scene computes this,
   * and nothing here decides which scene is active.
   */
  const activeOrdinal = SCENE_ORDER.indexOf(state.sceneId);
  const scopedProgress = (sceneId: SceneId): number => {
    const ordinal = SCENE_ORDER.indexOf(sceneId);
    if (ordinal < activeOrdinal) return 1;
    if (ordinal > activeOrdinal) return 0;
    return state.sceneProgress;
  };

  /** Accessible name per scene, from the lens data — no invented section copy. */
  const sceneLabel = (sceneId: SceneId): string | undefined => {
    switch (sceneId) {
      case "thesis":
        return lens.title.fa;
      case "menu":
        return lens.sectionLabels.menu.fa;
      case "gridStatement":
        return lens.gridStatement.fa;
      case "films":
        return lens.sectionLabels.films.fa;
      case "tracks":
        return lens.sectionLabels.tracks.fa;
      case "artPieces":
        return lens.sectionLabels.artPieces.fa;
      case "footer":
        return lens.footer.statement.fa;
      default:
        return undefined;
    }
  };

  const sceneContent = (sceneId: SceneId): ReactNode => {
    switch (sceneId) {
      case "loader":
        return <LoaderScene onComplete={completeLoader} reducedMotion={state.reducedMotion} />;
      case "thesis":
        return (
          <Thesis
            lens={lens}
            messageIndex={transitionState.messageIndex}
            progress={scopedProgress("thesis")}
            reducedMotion={state.reducedMotion}
          />
        );
      case "menu":
        return (
          <MenuDeck
            heading={lens.sectionLabels.menu}
            items={lens.menuItems}
            flippedCards={transitionState.flippedCards}
            progress={scopedProgress("menu")}
            reducedMotion={state.reducedMotion}
          />
        );
      case "gridStatement":
        // The statement fades across pixel transition A (brief §7.5), so its `progress` is that
        // transition's, not the grid scene's: the descriptor while the mosaic runs, and the
        // pixelA scene's scoped progress either side of it (0 before, 1 after).
        return (
          <GridStatement
            statement={lens.gridStatement}
            revealed={transitionState.gridStatementRevealed}
            progress={transitionState.pixelA?.progress ?? scopedProgress("pixelA")}
            reducedMotion={state.reducedMotion}
          />
        );
      case "films":
        return (
          <Films
            heading={lens.sectionLabels.films}
            films={lens.films}
            filmIndex={transitionState.filmIndex}
            progress={scopedProgress("films")}
            filmFade={transitionState.filmFade}
            reducedMotion={state.reducedMotion}
          />
        );
      case "tracks":
        return (
          <Tracks
            heading={lens.sectionLabels.tracks}
            tracks={lens.tracks}
            trackIndex={transitionState.trackIndex}
            onPrevious={goToPreviousTrack}
            onNext={goToNextTrack}
            onSelect={goToTrack}
            progress={scopedProgress("tracks")}
            reducedMotion={state.reducedMotion}
            entered={!transitionState.darkBeat}
          />
        );
      case "artPieces":
        return (
          <ArtPieces
            heading={lens.sectionLabels.artPieces}
            pieces={lens.artPieces}
            artIndex={transitionState.artIndex}
            progress={scopedProgress("artPieces")}
            reducedMotion={state.reducedMotion}
          />
        );
      case "footer":
        return (
          <Footer
            footer={lens.footer}
            footerReveal={transitionState.footerReveal}
            progress={scopedProgress("footer")}
            reducedMotion={state.reducedMotion}
          />
        );
      // The pixel transitions are pure background choreography (brief §7.5, §7.7): scroll
      // length and a mode, no content of their own.
      case "pixelA":
      case "pixelB":
        return null;
    }
  };

  return (
    // The document stays still until the O portal completes, so the portal always opens on the
    // top of the page rather than on wherever a wheel flick during the loader landed.
    <SmoothScrollProvider locked={!state.transitionState.loaderComplete}>
      <div
        className={styles.page}
        data-lens={lens.slug}
        data-content-mode={lens.contentMode}
        data-active-scene={state.sceneId}
        data-background-mode={state.backgroundMode}
        data-contrast={contrast}
        data-reduced-motion={state.reducedMotion}
      >
        <BackgroundCanvas
          mode={state.backgroundMode}
          sceneProgress={state.sceneProgress}
          transitionState={transitionState}
          reducedMotion={state.reducedMotion}
        />
        <SiteHeader variant={transitionState.headerVariant} />
        {budgets.map(({ sceneId, vh, pin }) => (
          <SceneSection
            key={sceneId}
            sceneId={sceneId}
            budgetVh={vh}
            pin={pin}
            active={state.sceneId === sceneId}
            sectionRef={registerScene(sceneId)}
            label={sceneLabel(sceneId)}
            decorative={sceneLabel(sceneId) === undefined}
          >
            {sceneContent(sceneId)}
          </SceneSection>
        ))}
      </div>
    </SmoothScrollProvider>
  );
}
