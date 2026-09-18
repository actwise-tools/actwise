// WORKAROUND (eve 0.24.5): the dev-host bundle inlines eve's own package.js, so
// its self-location helper (resolvePackageBuildRoot) can't find node_modules/eve/dist
// and mis-resolves the compiled-module-map loader to THIS project path instead of the
// eve package. Without this shim, createSessionStep dies with:
//   Cannot find module '.../src/internal/authored-module-map-loader.ts'
// Re-export the real loader from the installed eve package (relative path bypasses the
// package "exports" map; eve's own #subpath imports still resolve against eve's package.json).
// Remove once eve fixes dev-host externalization of its runtime package.
export * from "../../node_modules/eve/dist/src/internal/authored-module-map-loader.js";
