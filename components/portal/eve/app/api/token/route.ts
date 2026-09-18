import { NextResponse } from "next/server";
import { getPortalUser } from "@/app/lib/session";
import { mintPortalJwt } from "@/agent/lib/portal-jwt";

// Mints a short-lived HS256 portal JWT (sub = the signed-in DOCenter user id) that
// the browser sends as `Authorization: Bearer …` to eve's HTTP channel. The secret
// stays server-side; the frontend fetches a fresh token per request.
export async function GET() {
  const user = await getPortalUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });
  const secret = process.env.PORTAL_JWT_SECRET ?? "";
  if (!secret) {
    return NextResponse.json({ error: "PORTAL_JWT_SECRET not configured" }, { status: 503 });
  }
  return NextResponse.json({ token: mintPortalJwt(user, secret) });
}
