import { NextResponse } from "next/server";

// Liveness probe for the Cloudflare tunnel preflight and any uptime check —
// matches the /healthz the other ActWise origins (ops/data/old portal) expose.
export function GET() {
  return NextResponse.json({ status: "ok", server: "actwise-eve-portal" });
}
