// Phase 2 test fixture — a streaming reverse proxy that sits in front of the real
// docenter MCP and logs the outbound X-DOCenter-User header on every request.
//
//   eve  ->  capture-proxy (this, :8788)  ->  docenter_mcp (:8787)
//
// Point the eve connection at the proxy (DOCENTER_MCP_URL=http://127.0.0.1:8788/mcp)
// so the full chat still works end-to-end while we capture what identity the portal
// actually sends. Captured tokens are appended to fixtures/captured-headers.jsonl;
// verify them offline with fixtures/docenter_user_token.py. This proxy does NOT
// verify or modify anything — enforcement is Phase 3, inside the MCP.

import http from "node:http";
import { appendFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const LISTEN_PORT = Number(process.env.CAPTURE_PROXY_PORT ?? 8788);
const UPSTREAM_HOST = process.env.CAPTURE_UPSTREAM_HOST ?? "127.0.0.1";
const UPSTREAM_PORT = Number(process.env.CAPTURE_UPSTREAM_PORT ?? 8787);
const LOG_FILE = join(dirname(fileURLToPath(import.meta.url)), "captured-headers.jsonl");

const server = http.createServer((clientReq, clientRes) => {
  const userHeader = clientReq.headers["x-docenter-user"];
  const record = {
    ts: new Date().toISOString(),
    method: clientReq.method,
    url: clientReq.url,
    hasApiKey: Boolean(clientReq.headers["x-api-key"]),
    xDocenterUser: typeof userHeader === "string" ? userHeader : null,
  };
  appendFileSync(LOG_FILE, JSON.stringify(record) + "\n");
  const tag = record.xDocenterUser ? record.xDocenterUser.slice(0, 24) + "…" : "(none)";
  console.log(`[capture] ${record.method} ${record.url}  X-DOCenter-User=${tag}`);

  const upstream = http.request(
    {
      host: UPSTREAM_HOST,
      port: UPSTREAM_PORT,
      method: clientReq.method,
      path: clientReq.url,
      headers: clientReq.headers,
    },
    (upstreamRes) => {
      clientRes.writeHead(upstreamRes.statusCode ?? 502, upstreamRes.headers);
      upstreamRes.pipe(clientRes);
    },
  );
  upstream.on("error", (err) => {
    console.error(`[capture] upstream error: ${err.message}`);
    if (!clientRes.headersSent) clientRes.writeHead(502);
    clientRes.end("capture-proxy: upstream error");
  });
  clientReq.pipe(upstream);
});

server.listen(LISTEN_PORT, "127.0.0.1", () => {
  console.log(
    `[capture] proxy on http://127.0.0.1:${LISTEN_PORT} -> http://${UPSTREAM_HOST}:${UPSTREAM_PORT}`,
  );
  console.log(`[capture] logging to ${LOG_FILE}`);
});
