// Minimal ESM resolve hook: map a ".js" import specifier to its ".ts" sibling
// when the ".js" file doesn't exist. eve's own bundler does this; plain Node
// does not. Used ONLY to run the Phase 2 proof driver against the real source
// files (which use eve-idiomatic ".js" specifiers). Not shipped/loaded by eve.
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

export async function resolve(specifier, context, next) {
  if (/^\.\.?\//.test(specifier) && specifier.endsWith(".js")) {
    const asUrl = new URL(specifier, context.parentURL);
    if (!existsSync(fileURLToPath(asUrl))) {
      const tsSpecifier = specifier.slice(0, -3) + ".ts";
      const tsUrl = new URL(tsSpecifier, context.parentURL);
      if (existsSync(fileURLToPath(tsUrl))) return next(tsSpecifier, context);
    }
  }
  return next(specifier, context);
}
