import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { PORTAL_COOKIE, getPortalUser } from "@/app/lib/session";

// GET  → { user } (current portal identity, or null)
// POST → set the portal identity from { email }
// DELETE → sign out
export async function GET() {
  return NextResponse.json({ user: await getPortalUser() });
}

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  const email = String(body?.email ?? "").trim().toLowerCase();
  if (!email || !email.includes("@")) {
    return NextResponse.json({ error: "a valid email is required" }, { status: 400 });
  }
  const store = await cookies();
  store.set(PORTAL_COOKIE, email, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 8,
  });
  return NextResponse.json({ user: email });
}

export async function DELETE() {
  const store = await cookies();
  store.delete(PORTAL_COOKIE);
  return NextResponse.json({ user: null });
}
