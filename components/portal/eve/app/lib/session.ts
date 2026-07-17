import { cookies } from "next/headers";

// The portal "session" for this PoC is just the user's DOCenter identity (email)
// held in an httpOnly cookie. This is deliberately lightweight: the portal itself
// does not password-check the user — the real credential check happens when the
// user connects their DOCenter account through a broker door (SSO or password).
// For production, replace this with a real IdP sign-in (Auth.js/Entra) whose
// verified subject becomes the DOCenter user id.

export const PORTAL_COOKIE = "portal_user";

export async function getPortalUser(): Promise<string | null> {
  const store = await cookies();
  const value = store.get(PORTAL_COOKIE)?.value ?? "";
  return value.length > 0 ? value : null;
}
