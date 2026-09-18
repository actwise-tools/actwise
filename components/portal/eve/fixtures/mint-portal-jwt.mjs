// Phase 2 test fixture — mint a portal HS256 JWT for a stub user, standing in for
// the Next.js sign-in that arrives in a later phase. The JWT's claims match what
// agent/channels/eve.ts (portalUser) verifies: iss=actwise-portal, aud=actwise-eve,
// sub=<userId>. Send it as `Authorization: ****** to eve's HTTP channel.
//
//   node fixtures/mint-portal-jwt.mjs <userId> [ttlSeconds]
//
// Reads PORTAL_JWT_SECRET from the environment (load .env.local first).

import { createHmac } from "node:crypto";

const ISSUER = "actwise-portal";
const AUDIENCE = "actwise-eve";

function b64url(input) {
  return Buffer.from(input).toString("base64url");
}

const userId = process.argv[2];
const ttl = Number(process.argv[3] ?? 900);
const secret = process.env.PORTAL_JWT_SECRET ?? "";

if (!userId) {
  console.error("usage: node fixtures/mint-portal-jwt.mjs <userId> [ttlSeconds]");
  process.exit(2);
}
if (!secret) {
  console.error("error: PORTAL_JWT_SECRET is not set (load .env.local)");
  process.exit(2);
}

const now = Math.floor(Date.now() / 1000);
const header = { alg: "HS256", typ: "JWT" };
const payload = { iss: ISSUER, aud: AUDIENCE, sub: userId, iat: now, exp: now + ttl };
const signingInput = `${b64url(JSON.stringify(header))}.${b64url(JSON.stringify(payload))}`;
const sig = createHmac("sha256", secret).update(signingInput).digest("base64url");
process.stdout.write(`${signingInput}.${sig}`);
