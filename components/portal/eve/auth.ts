import NextAuth from "next-auth";
import MicrosoftEntraID from "next-auth/providers/microsoft-entra-id";

// Entra SSO for the portal. Additive and env-gated: when the three Entra vars are
// present the portal signs users in with their Microsoft identity (Auth.js), and
// the verified email becomes the DOCenter portal user id (see app/lib/session.ts).
// When they're unset the provider list is empty and the app falls back to the
// lightweight email-cookie sign-in, so local dev needs no app registration.
//
//   AUTH_MICROSOFT_ENTRA_ID_ID      SPA/Web app registration client id
//   AUTH_MICROSOFT_ENTRA_ID_SECRET  client secret (confidential client)
//   AUTH_MICROSOFT_ENTRA_ID_ISSUER  https://login.microsoftonline.com/<tenant>/v2.0
//   AUTH_SECRET                     Auth.js session-cookie encryption secret
const clientId = process.env.AUTH_MICROSOFT_ENTRA_ID_ID ?? "";
const clientSecret = process.env.AUTH_MICROSOFT_ENTRA_ID_SECRET ?? "";
const issuer = process.env.AUTH_MICROSOFT_ENTRA_ID_ISSUER ?? "";

export const ssoEnabled = Boolean(clientId && clientSecret && issuer);

export const { handlers, auth, signIn, signOut } = NextAuth({
  // Self-hosted behind the front-proxy + Cloudflare tunnel: trust the forwarded host.
  trustHost: true,
  secret: process.env.AUTH_SECRET,
  providers: ssoEnabled
    ? [MicrosoftEntraID({ clientId, clientSecret, issuer })]
    : [],
});
