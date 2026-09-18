// Phase 2 proof — Door-1 identity plumbing, verified offline (no model, no live
// portal, no MCP). Drives the REAL source functions:
//   - portalUser()          from agent/channels/eve.ts     (route auth: JWT -> user principal)
//   - buildDocenterHeaders  from agent/lib/docenter-headers.ts (per-user signed header)
//   - verifyDocenterUserToken from agent/lib/docenter-user-token.ts (offline verify)
//
// ✔ For two stub users it proves: a portal-minted JWT resolves to a distinct
//   `user` principal, and the connection emits a distinct, signature-valid
//   X-DOCenter-User for each — while anonymous/app callers get none.
//
// Run: node --import ./fixtures/register.mjs fixtures/phase2-proof.ts
// Requires env: PORTAL_JWT_SECRET, DOCENTER_USER_TOKEN_SECRET.
import { createHmac } from "node:crypto";
import { portalUser, PORTAL_JWT_ISSUER, PORTAL_JWT_AUDIENCE } from "../agent/channels/eve.ts";
import { buildDocenterHeaders } from "../agent/lib/docenter-headers.ts";
import { verifyDocenterUserToken } from "../agent/lib/docenter-user-token.ts";

const PORTAL_JWT_SECRET = process.env.PORTAL_JWT_SECRET ?? "";
const USER_TOKEN_SECRET = process.env.DOCENTER_USER_TOKEN_SECRET ?? "";
if (!PORTAL_JWT_SECRET || !USER_TOKEN_SECRET) {
  console.error("error: PORTAL_JWT_SECRET and DOCENTER_USER_TOKEN_SECRET must be set");
  process.exit(2);
}

let failures = 0;
function check(label: string, cond: boolean): void {
  console.log(`${cond ? "  PASS" : "  FAIL"}  ${label}`);
  if (!cond) failures++;
}

function b64url(input: string): string {
  return Buffer.from(input).toString("base64url");
}

// Stand-in for the Next.js sign-in: mint the portal HS256 JWT the front end sends.
function mintPortalJwt(userId: string, secret = PORTAL_JWT_SECRET): string {
  const now = Math.floor(Date.now() / 1000);
  const header = b64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = b64url(
    JSON.stringify({
      iss: PORTAL_JWT_ISSUER,
      aud: PORTAL_JWT_AUDIENCE,
      sub: userId,
      iat: now,
      exp: now + 900,
    }),
  );
  const sig = createHmac("sha256", secret).update(`${header}.${payload}`).digest("base64url");
  return `${header}.${payload}.${sig}`;
}

function request(bearer: string | null, url = "http://localhost/eve/v1/session"): Request {
  const headers = new Headers();
  if (bearer) headers.set("authorization", "Bearer " + bearer);
  return new Request(url, { method: "POST", headers });
}

const authFn = portalUser();

async function proveUser(userId: string): Promise<string> {
  console.log(`\n[user ${userId}]`);
  const principal = await authFn(request(mintPortalJwt(userId)));
  check("valid portal JWT resolves to a principal", principal !== null);
  check("principalType is 'user'", principal?.principalType === "user");
  check("subject equals the userId", principal?.subject === userId);
  check("principalId equals the userId (not iss-prefixed)", principal?.principalId === userId);

  const headers = buildDocenterHeaders(principal, {
    apiKey: "shared-proxy-key",
    userTokenSecret: USER_TOKEN_SECRET,
  });
  check("X-API-Key still sent", headers["X-API-Key"] === "shared-proxy-key");
  const token = headers["X-DOCenter-User"];
  check("X-DOCenter-User present", typeof token === "string" && token.length > 0);

  const verified = verifyDocenterUserToken(token, USER_TOKEN_SECRET);
  check("X-DOCenter-User verifies offline to the same userId", verified.userId === userId);
  return token;
}

const aliceToken = await proveUser("alice@example.com");
const bobToken = await proveUser("bob@contoso.com");

console.log("\n[cross-user + negative cases]");
check("alice and bob get DISTINCT X-DOCenter-User values", aliceToken !== bobToken);

const noBearer = await authFn(request(null));
check("no-bearer request falls through route auth (null)", noBearer === null);

const wrongSecret = await authFn(request(mintPortalJwt("mallory@evil.com", "wrong-secret")));
check("JWT signed with the wrong secret is rejected (null)", wrongSecret === null);

const appHeaders = buildDocenterHeaders(
  { principalType: "app" },
  { apiKey: "shared-proxy-key", userTokenSecret: USER_TOKEN_SECRET },
);
check("app/non-user caller gets NO X-DOCenter-User", appHeaders["X-DOCenter-User"] === undefined);

const anonHeaders = buildDocenterHeaders(null, {
  apiKey: "shared-proxy-key",
  userTokenSecret: USER_TOKEN_SECRET,
});
check("null caller gets NO X-DOCenter-User", anonHeaders["X-DOCenter-User"] === undefined);

let tamperRejected = false;
try {
  verifyDocenterUserToken(aliceToken.slice(0, -4) + "AAAA", USER_TOKEN_SECRET);
} catch {
  tamperRejected = true;
}
check("tampered X-DOCenter-User signature is rejected", tamperRejected);

// Emit the two live tokens for the Python cross-language verify step.
console.log(`\nALICE_TOKEN=${aliceToken}`);
console.log(`BOB_TOKEN=${bobToken}`);

console.log(`\n${failures === 0 ? "ALL CHECKS PASSED" : `${failures} CHECK(S) FAILED`}`);
process.exit(failures === 0 ? 0 : 1);
