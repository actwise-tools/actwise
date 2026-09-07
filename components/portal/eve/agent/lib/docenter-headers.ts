import { mintDocenterUserToken } from "./docenter-user-token.js";

// The exact header map the docenter MCP connection sends on every request.
// Extracted so agent/connections/docenter.ts and the Phase 2 proof driver share
// one implementation (no drift between what ships and what we verify).
//
//   - X-API-Key: shared proxy key (server-to-server auth; unchanged).
//   - X-DOCenter-User: signed per-user identity, minted ONLY when the caller is
//     an authenticated end user. Omitted for anonymous/app/local-dev callers, so
//     the MCP falls back to today's shared-cookie behavior (byte-for-byte Phase 1).

export interface DocenterCaller {
  readonly principalType: string;
  readonly subject?: string;
}

export interface DocenterHeaderOptions {
  readonly apiKey: string;
  readonly userTokenSecret: string;
}

export function buildDocenterHeaders(
  caller: DocenterCaller | null,
  opts: DocenterHeaderOptions,
): Record<string, string> {
  const headers: Record<string, string> = { "X-API-Key": opts.apiKey };
  if (caller?.principalType === "user" && caller.subject && opts.userTokenSecret.length > 0) {
    headers["X-DOCenter-User"] = mintDocenterUserToken(caller.subject, opts.userTokenSecret);
  }
  return headers;
}
