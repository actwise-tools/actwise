import { eveChannel } from "eve/channels/eve";
import { extractBearerToken, localDev, verifyJwtHmac, type AuthFn } from "eve/channels/auth";

// Phase 2 — Door-1 identity plumbing.
//
// The portal's front end (Phase 2+: a Next.js app after the user signs in) mints
// a short-lived HS256 JWT whose `sub` is the end user's id, and sends it as
// `Authorization: ****** to eve's HTTP channel. `portalUser()` verifies that
// JWT and stamps a `user` principal into `ctx.session.auth.current`, which the
// docenter MCP connection then reads to mint the per-user `X-DOCenter-User`
// header (see agent/connections/docenter.ts).
//
// `jwtHmac()` from eve would work, but it hardcodes `principalType: "service"`
// and an issuer-prefixed principalId (`iss:sub`). We want a clean `user`
// principal whose id IS the DOCenter user id, so we wrap the same verifier and
// remap. `localDev()` stays last so direct loopback curl calls (no bearer) still
// resolve for Phase 1-style shared-identity testing.

export const PORTAL_JWT_ISSUER = "actwise-portal";
export const PORTAL_JWT_AUDIENCE = "actwise-eve";

export function portalUser(): AuthFn<Request> {
  const secret = process.env.PORTAL_JWT_SECRET ?? "";
  return async (request) => {
    if (secret.length === 0) return null; // not configured — fall through to localDev
    const token = extractBearerToken(request.headers.get("authorization"));
    const result = await verifyJwtHmac(token, {
      algorithm: "HS256",
      audiences: [PORTAL_JWT_AUDIENCE],
      issuer: PORTAL_JWT_ISSUER,
      secret,
    });
    if (!result.ok || !result.sessionAuth.subject) return null;
    const userId = result.sessionAuth.subject;
    return {
      attributes: result.sessionAuth.attributes,
      authenticator: "portal-jwt",
      issuer: result.sessionAuth.issuer,
      principalId: userId,
      principalType: "user",
      subject: userId,
    };
  };
}

export default eveChannel({
  auth: [portalUser(), localDev()],
});
