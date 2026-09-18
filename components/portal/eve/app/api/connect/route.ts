import { NextResponse } from "next/server";
import { getPortalUser } from "@/app/lib/session";

// Proactive "Connect your DOCenter account" flow. The browser can't hold the broker
// secret, so this server route mints a one-time login link on the user's behalf by
// calling the broker's R1′ POST /links hop, then hands the login_url back to the UI.
// Opening it lands the user on the broker's two-door page (SSO or username/password).
export async function POST() {
  const user = await getPortalUser();
  if (!user) return NextResponse.json({ error: "not signed in" }, { status: 401 });

  const base = (process.env.DOCENTER_BROKER_URL ?? "").replace(/\/+$/, "");
  const secret = process.env.DOCENTER_BROKER_SECRET ?? "";
  if (!base || !secret) {
    return NextResponse.json(
      { error: "broker not configured (DOCENTER_BROKER_URL / DOCENTER_BROKER_SECRET)" },
      { status: 503 },
    );
  }

  let resp: Response;
  try {
    resp = await fetch(`${base}/links`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Broker-Secret": secret },
      body: JSON.stringify({ user }),
    });
  } catch {
    return NextResponse.json({ error: "broker unreachable" }, { status: 502 });
  }
  if (!resp.ok) {
    return NextResponse.json({ error: `broker /links failed (${resp.status})` }, { status: 502 });
  }
  const data = await resp.json();
  return NextResponse.json({ login_url: data.login_url });
}
