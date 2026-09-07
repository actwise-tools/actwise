import { createHmac } from "node:crypto";

// Server-side minter for the portal's HS256 session JWT. Its claims must match
// what agent/channels/eve.ts (portalUser) verifies: iss=actwise-portal,
// aud=actwise-eve, sub=<docenter user id>. This is the production counterpart to
// fixtures/mint-portal-jwt.mjs — kept in lockstep with that verifier.
//
// The JWT is minted ONLY on the server (Next.js route handlers) from
// PORTAL_JWT_SECRET; it is never exposed to the browser as a long-lived token —
// the frontend fetches a short-lived one per request from /api/token.

export const PORTAL_JWT_ISSUER = "actwise-portal";
export const PORTAL_JWT_AUDIENCE = "actwise-eve";
const DEFAULT_TTL_SECONDS = 300;

function b64url(input: string): string {
  return Buffer.from(input).toString("base64url");
}

export function mintPortalJwt(
  userId: string,
  secret: string,
  ttlSeconds: number = DEFAULT_TTL_SECONDS,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): string {
  if (userId.length === 0) throw new Error("mintPortalJwt: userId is empty");
  if (secret.length === 0) throw new Error("mintPortalJwt: secret is empty");
  const header = { alg: "HS256", typ: "JWT" };
  const payload = {
    iss: PORTAL_JWT_ISSUER,
    aud: PORTAL_JWT_AUDIENCE,
    sub: userId,
    iat: nowSeconds,
    exp: nowSeconds + ttlSeconds,
  };
  const signingInput = `${b64url(JSON.stringify(header))}.${b64url(JSON.stringify(payload))}`;
  const sig = createHmac("sha256", secret).update(signingInput).digest("base64url");
  return `${signingInput}.${sig}`;
}
