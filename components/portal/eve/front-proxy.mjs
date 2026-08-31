// ActWise eve portal — streaming front reverse proxy.
//
// Why this exists: the eve chat stream is a long-lived Server-Sent-Events response
// (GET /eve/v1/session/:id/stream). In the self-hosted container we serve the UI with
// `next start`, whose withEve rewrites() proxies /eve/v1/** to the eve (Nitro) runtime.
// That Next external-rewrite proxy BUFFERS the response: when a single slow doc-portal
// tool call leaves the stream silent for ~20s+, the browser's fetch through the Next
// proxy stalls open-but-silent, so the final answer never renders even though the run
// completes server-side. (Confirmed: runs reach status "completed" on disk while the UI
// hangs at "Working…".)
//
// The fix: put this pass-through proxy in front. It streams /eve/v1/** straight to the
// Nitro runtime with plain socket piping (no buffering, no idle timeout, Nagle off) and
// forwards everything else to Next. Next's own rewrite is bypassed for the stream path.
//
// Ports (all loopback inside the container):
//   FRONT_PORT (default 8080) — published; the tunnel/browser hit this
//   NEXT_PORT  (default 3333) — `next start` (UI, /api/*, /healthz)
//   EVE_PORT   (default 4274) — eve Nitro runtime (/eve/v1/**)
import http from "node:http";
import { StringDecoder } from "node:string_decoder";

const FRONT_PORT = Number(process.env.FRONT_PORT ?? 8080);
const NEXT_PORT = Number(process.env.NEXT_PORT ?? 3333);
const EVE_PORT = Number(process.env.EVE_NEXT_PRODUCTION_PORT ?? 4274);

// The eve client's per-send stream stops reading at these "turn boundary" events
// (see isCurrentTurnBoundaryEvent in eve/dist/src/protocol/message.js). The public
// URL is served through a Cloudflare tunnel forced onto `--protocol http2` (QUIC/UDP
// 7844 is blocked by the corporate VPN). cloudflared's http2 edge transport BUFFERS
// the entire response and only delivers it once the origin closes the connection, so
// a long-lived NDJSON stream never reaches the browser and the UI hangs at
// "Researching…" while the run finishes server-side. To make answers appear over
// http2 we end the response as soon as a turn-boundary event has been forwarded:
// cloudflared then flushes the whole buffered turn, the client reads up to the
// boundary and stops, and the next send() opens a fresh stream. This trades
// token-by-token streaming for a working answer through the tunnel; direct/local
// streaming (and QUIC tunnels, off-VPN) are unaffected because the client already
// stops at the same boundary event.
const TURN_BOUNDARY_EVENTS = new Set([
  "session.waiting",
  "session.completed",
  "session.failed",
]);

function targetPort(url) {
  return url.startsWith("/eve/v1") ? EVE_PORT : NEXT_PORT;
}

const server = http.createServer((req, res) => {
  const url = req.url ?? "/";
  const port = targetPort(url);
  const upstream = http.request(
    {
      host: "127.0.0.1",
      port,
      method: req.method,
      path: url,
      headers: req.headers,
    },
    (upRes) => {
      const headers = { ...upRes.headers };
      // Cloudflare's edge streams text/event-stream but BUFFERS other bodies (the eve
      // chat stream is application/x-ndjson). Buffering makes a slow turn hang the
      // browser at "Working…" through the tunnel even though the run finished. Relabel
      // the stream as text/event-stream so the edge flushes each chunk; the eve client
      // reads response.body as NDJSON and ignores the content-type, so this is safe.
      const ct = String(upRes.headers["content-type"] ?? "");
      const isStream = url.startsWith("/eve/v1") && ct.includes("ndjson");
      // The eve message stream (GET /eve/v1/session/:id/stream) is the only long-lived
      // NDJSON body; only it needs the turn-boundary close described above.
      const isMessageStream =
        isStream && /\/eve\/v1\/session\/[^/]+\/stream(?:[/?]|$)/.test(url);
      if (isStream) {
        headers["content-type"] = "text/event-stream";
        headers["cache-control"] = "no-cache, no-transform";
        headers["x-accel-buffering"] = "no";
        delete headers["content-length"];
      }
      res.writeHead(upRes.statusCode ?? 502, headers);
      if (!isStream) {
        upRes.pipe(res);
        return;
      }
      // Streamed NDJSON: forward chunks (with backpressure) and inject a newline
      // keepalive during silent tool gaps. A very slow single doc-portal tool call
      // can leave the stream silent for 100s+, and Cloudflare's edge treats an idle
      // response as timed out (524) — the browser then hangs at "Researching…" even
      // though the run finished server-side. A lone "\n" is a safe keepalive: the eve
      // NDJSON reader trims each line and skips empties, so it never reaches
      // JSON.parse. We only emit it at a line boundary so a partial JSON object is
      // never split.
      let atBoundary = true;
      const keepalive = setInterval(() => {
        if (atBoundary && !res.writableEnded) res.write("\n");
      }, 15000);
      const stop = () => clearInterval(keepalive);
      // Scan forwarded NDJSON for a turn-boundary event and end the response right
      // after one (see TURN_BOUNDARY_EVENTS). The raw chunk — including the boundary
      // line — is written first, so the client receives the complete turn before the
      // stream closes; extra bytes after the boundary are harmless (the client stops
      // reading at the boundary event).
      const decoder = new StringDecoder("utf8");
      let scan = "";
      let ended = false;
      const finish = () => {
        if (ended) return;
        ended = true;
        stop();
        upRes.destroy();
        if (!res.writableEnded) res.end();
      };
      upRes.on("data", (chunk) => {
        if (ended) return;
        if (chunk.length > 0) atBoundary = chunk[chunk.length - 1] === 0x0a;
        const ok = res.write(chunk);
        if (isMessageStream) {
          scan += decoder.write(chunk);
          let nl;
          while ((nl = scan.indexOf("\n")) >= 0) {
            const line = scan.slice(0, nl).trim();
            scan = scan.slice(nl + 1);
            if (!line) continue;
            let ev;
            try {
              ev = JSON.parse(line);
            } catch {
              ev = null;
            }
            if (ev && TURN_BOUNDARY_EVENTS.has(ev.type)) {
              finish();
              return;
            }
          }
        }
        if (ok === false) {
          upRes.pause();
          res.once("drain", () => upRes.resume());
        }
      });
      upRes.on("end", () => {
        stop();
        if (!res.writableEnded) res.end();
      });
      upRes.on("error", () => {
        stop();
        if (!res.writableEnded) res.end();
      });
      res.on("close", stop);
    },
  );
  // Stream immediately, never idle-close a silent SSE gap, low latency.
  upstream.on("socket", (s) => {
    s.setNoDelay(true);
    s.setTimeout(0);
  });
  upstream.on("error", (err) => {
    if (!res.headersSent) res.writeHead(502, { "content-type": "text/plain" });
    res.end("front-proxy upstream error: " + err.message);
  });
  res.on("close", () => upstream.destroy());
  req.pipe(upstream);
});

// Proxy WebSocket / HTTP upgrades (defensive; the chat stream is SSE, not WS).
server.on("upgrade", (req, socket, head) => {
  const port = targetPort(req.url ?? "/");
  const upstream = http.request({
    host: "127.0.0.1",
    port,
    method: req.method,
    path: req.url,
    headers: req.headers,
  });
  upstream.on("upgrade", (upRes, upSocket, upHead) => {
    const lines = [`HTTP/1.1 ${upRes.statusCode} ${upRes.statusMessage}`];
    for (let i = 0; i < upRes.rawHeaders.length; i += 2) {
      lines.push(`${upRes.rawHeaders[i]}: ${upRes.rawHeaders[i + 1]}`);
    }
    socket.write(lines.join("\r\n") + "\r\n\r\n");
    if (upHead && upHead.length) upSocket.unshift(upHead);
    upSocket.setNoDelay(true);
    socket.setNoDelay(true);
    upSocket.pipe(socket);
    socket.pipe(upSocket);
  });
  upstream.on("error", () => socket.destroy());
  socket.on("error", () => upstream.destroy());
  if (head && head.length) upstream.write(head);
  upstream.end();
});

// Never let the proxy itself time out a long-lived stream.
server.requestTimeout = 0;
server.headersTimeout = 0;
server.timeout = 0;

server.listen(FRONT_PORT, "0.0.0.0", () => {
  console.log(
    `front-proxy on :${FRONT_PORT} -> /eve/v1 :${EVE_PORT}, * :${NEXT_PORT}`,
  );
});
