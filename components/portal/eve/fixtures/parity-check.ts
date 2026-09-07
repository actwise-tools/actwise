// Phase 2 parity check — prove the TS signer and the Python twin produce
// identical tokens for the same inputs. Run with Node's type stripping:
//   node fixtures/parity-check.ts
import { mintDocenterUserToken, verifyDocenterUserToken } from "../agent/lib/docenter-user-token.ts";

const userId = "alice@example.com";
const secret = "test-secret";
const now = 1_000_000_000;
const ttl = 300;

const token = mintDocenterUserToken(userId, secret, ttl, now);
const verified = verifyDocenterUserToken(token, secret, now);
if (verified.userId !== userId || verified.exp !== now + ttl) {
  throw new Error("TS self-verify mismatch");
}
process.stdout.write(token);
