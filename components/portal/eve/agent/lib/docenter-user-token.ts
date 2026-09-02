import { createHmac, timingSafeEqual } from "node:crypto";

// Phase 2 — the portal-side signer for the per-user DOCenter identity header.
//
// X-DOCenter-User is a compact HMAC-signed token that binds a request to one
// end user WITHOUT trusting the caller-supplied user id (R2). The portal mints
// it; the MCP verifies it (Phase 3, docenter_mcp/user_token.py — a byte-for-byte
// twin of this file). Keep the two implementations in lockstep.
//
// Wire format (v1), 4 dot-separated ASCII parts:
//
//   v1 . base64url(userId) . exp . base64url(HMAC_SHA256(secret, payload))
//   \____________________ payload ____________________/
//
//   - base64url: RFC 4648 §5, no padding
//   - exp: token expiry as unix seconds (decimal)
//   - payload = "v1." + base64url(userId) + "." + exp  (the signed bytes)
//   - HMAC key = DOCENTER_USER_TOKEN_SECRET (utf-8)
//
// The delimiter "." never appears in base64url output or in the decimal exp, so
// splitting on "." is unambiguous.

const VERSION = "v1";
const DEFAULT_TTL_SECONDS = 300;

function b64urlEncode(data: Buffer): string {
  return data.toString("base64url");
}

function b64urlDecode(value: string): Buffer {
  return Buffer.from(value, "base64url");
}

function sign(payload: string, secret: string): string {
  return b64urlEncode(createHmac("sha256", secret).update(payload, "utf8").digest());
}

/**
 * Mint a signed X-DOCenter-User token for `userId`, valid for `ttlSeconds`.
 * `nowSeconds` is injectable for deterministic tests.
 */
export function mintDocenterUserToken(
  userId: string,
  secret: string,
  ttlSeconds: number = DEFAULT_TTL_SECONDS,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): string {
  if (userId.length === 0) throw new Error("mintDocenterUserToken: userId is empty");
  if (secret.length === 0) throw new Error("mintDocenterUserToken: secret is empty");
  const exp = nowSeconds + ttlSeconds;
  const payload = `${VERSION}.${b64urlEncode(Buffer.from(userId, "utf8"))}.${exp}`;
  return `${payload}.${sign(payload, secret)}`;
}

export interface VerifiedDocenterUserToken {
  readonly userId: string;
  readonly exp: number;
}

/**
 * Verify a token's signature and expiry offline. Returns the decoded user id
 * and expiry, or throws with a precise reason. Mirrors the Phase 3 MCP verifier.
 */
export function verifyDocenterUserToken(
  token: string,
  secret: string,
  nowSeconds: number = Math.floor(Date.now() / 1000),
  clockSkewSeconds = 30,
): VerifiedDocenterUserToken {
  const parts = token.split(".");
  if (parts.length !== 4) throw new Error("verifyDocenterUserToken: malformed token");
  const [version, userIdB64, expStr, sig] = parts;
  if (version !== VERSION) throw new Error(`verifyDocenterUserToken: unsupported version ${version}`);

  const payload = `${version}.${userIdB64}.${expStr}`;
  const expected = sign(payload, secret);
  const expectedBuf = Buffer.from(expected, "utf8");
  const sigBuf = Buffer.from(sig, "utf8");
  if (expectedBuf.length !== sigBuf.length || !timingSafeEqual(expectedBuf, sigBuf)) {
    throw new Error("verifyDocenterUserToken: bad signature");
  }

  const exp = Number.parseInt(expStr, 10);
  if (!Number.isInteger(exp)) throw new Error("verifyDocenterUserToken: bad exp");
  if (nowSeconds > exp + clockSkewSeconds) throw new Error("verifyDocenterUserToken: token expired");

  return { userId: b64urlDecode(userIdB64).toString("utf8"), exp };
}
