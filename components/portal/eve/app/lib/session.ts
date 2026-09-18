import { cookies } from "next/headers";
import { auth, ssoEnabled } from "@/auth";

// The portal identity is the DOCenter user id used all the way down to docenter-mcp.
//
// When Entra SSO is configured (ssoEnabled), it is the *verified* email from the
// Auth.js session — the user proved their Microsoft identity. When SSO is off, it
// falls back to the lightweight httpOnly email cookie (local dev / no registration):
// the portal itself does not password-check; the real credential check happens when
// the user connects their DOCenter account through a broker door (SSO or password).

export const PORTAL_COOKIE = "portal_user";

export async function getPortalUser(): Promise<string | null> {
  if (ssoEnabled) {
    const session = await auth();
    const email = session?.user?.email ?? "";
    return email.length > 0 ? email.toLowerCase() : null;
  }
  const store = await cookies();
  const value = store.get(PORTAL_COOKIE)?.value ?? "";
  return value.length > 0 ? value : null;
}
