/**
 * Scene-state seam (BUILD-GUIDE seam 2): the contract types plus the page-level reducer.
 * Import scene state from `@/lib/scene` — never reach past this barrel into scene internals.
 */
export * from "./types";
export * from "./reducer";
