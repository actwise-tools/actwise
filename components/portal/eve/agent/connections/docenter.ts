import { defineMcpClientConnection } from "eve/connections";
import { buildDocenterHeaders } from "../lib/docenter-headers.js";

// Connect eve to the existing docenter MCP (components/docenter/docenter_mcp).
//
// The filename ("docenter") is the connection name; discovered tools are exposed to the
// model as docenter__search_docs, docenter__find_bundles, docenter__get_catalog,
// docenter__get_page, docenter__get_toc, docenter__list_docs.
//
// Two headers go out on every MCP request:
//   - X-API-Key: the shared proxy key (server-to-server auth; unchanged).
//   - X-DOCenter-User: Phase 2 — a signed token binding the request to the authenticated
//     end user in ctx.session.auth.current. The portal MINTS and SENDS it here; the MCP
//     VERIFIES and ENFORCES it in Phase 3 (flag-gated DOCENTER_PER_USER). When no user
//     principal is present (e.g. localDev loopback with no bearer), the header is omitted
//     and the MCP falls back to today's shared-cookie behavior — byte-for-byte Phase 1.
export default defineMcpClientConnection({
  url: process.env.DOCENTER_MCP_URL ?? "http://127.0.0.1:8787/mcp",
  description:
    "NICE Actimize product documentation (DOCenter portal). Search product guides and " +
    "reference docs, find bundles, get the product/version catalog, fetch a full page as " +
    "Markdown, and get a bundle's table of contents. Use for any Actimize product question " +
    "— configuration, install/upgrade, ActOne, AIS, SAM, CDD, IFM, DART, Policy Manager, " +
    "QAS, Extend, integrations, release notes — and cite the returned portal_url.",
  headers: (ctx) =>
    buildDocenterHeaders(ctx.session.auth.current, {
      apiKey: process.env.DOCENTER_PROXY_API_KEY ?? "",
      userTokenSecret: process.env.DOCENTER_USER_TOKEN_SECRET ?? "",
    }),
});
