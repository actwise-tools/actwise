import { NextResponse } from "next/server";
import { ssoEnabled } from "@/auth";

// Public, non-secret client config. The chat page reads this to decide which
// sign-in UI to show: Microsoft SSO (ssoEnabled) or the email-cookie fallback.
export async function GET() {
  return NextResponse.json({ ssoEnabled });
}
