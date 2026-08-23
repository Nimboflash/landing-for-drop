/**
 * The immersive shell.
 *
 * `ImmersiveLensPage` is the only entry point a route needs: give it a validated `WeeklyLens`
 * and it renders the ten-scene journey. Everything else is exported for the scene tickets that
 * build inside it — the stage wrapper, the header, the scroll provider, the state machine, and
 * the scroll budgets that pace the page.
 */

export { ImmersiveLensPage, type ImmersiveLensPageProps } from "./ImmersiveLensPage";
export { SceneSection, type SceneSectionProps } from "./SceneSection";
export { SiteHeader, type SiteHeaderProps } from "./SiteHeader";
export { SmoothScrollProvider, type SmoothScrollProviderProps } from "./SmoothScrollProvider";
export {
  useSceneStateMachine,
  SCENE_DIAGNOSTICS_KEY,
  type SceneDiagnostics,
  type SceneSectionRef,
  type SceneStateMachine,
  type SceneStateMachineOptions,
} from "./useSceneStateMachine";
export {
  ART_PIECE_VH_PER_ITEM,
  LOADER_MAX_MS,
  LOADER_TARGET_MS,
  TRACKS_MAX_VH,
  TRACKS_MIN_VH,
  TRACKS_VH_PER_TRACK,
  artPiecesBudgetVh,
  sceneBudgetVh,
  sceneBudgets,
  scenePins,
  totalBudgetVh,
  tracksBudgetVh,
  type SceneBudget,
} from "./scene-budgets";
