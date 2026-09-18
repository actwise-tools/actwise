#!/bin/sh
# ActWise eve portal container entrypoint.
#
# The Next.js production build (withEve) proxies /eve/v1/** to the eve runtime on a
# fixed loopback port. That destination is baked into routes-manifest.json at BUILD
# time, so `next start` never re-evaluates rewrites() and never spawns the runtime —
# we must start it ourselves. Worse, Next's external-rewrite proxy BUFFERS the long
# SSE chat stream, so a slow turn stalls the browser at "Working…" even though the run
# completes server-side. So we run THREE processes and put a streaming front proxy in
# front that bypasses Next for /eve/v1 (see front-proxy.mjs):
#   1. eve runtime (durable agent backend)   on EVE_NEXT_PRODUCTION_PORT (4274)
#   2. next start (UI, /api/*, /healthz)      on 3333
#   3. front-proxy (published)                on 8080 -> /eve/v1 :4274, * :3333
set -e

EVE_PORT="${EVE_NEXT_PRODUCTION_PORT:-4274}"
NEXT_PORT="${NEXT_PORT:-3333}"
FRONT_PORT="${FRONT_PORT:-8080}"
export EVE_NEXT_PRODUCTION_PORT="$EVE_PORT" NEXT_PORT FRONT_PORT
# The eve workflow queue delivers messages to the runtime over HTTP; PORT lets it
# resolve its own base URL (there is no netstat in the slim image).
export EVE_BASE_URL="http://127.0.0.1:${EVE_PORT}"

echo "starting eve runtime on :${EVE_PORT} ..."
HOST=127.0.0.1 NITRO_HOST=127.0.0.1 PORT="$EVE_PORT" NITRO_PORT="$EVE_PORT" \
  node .output/server/index.mjs &
EVE_PID=$!

# Wait for the runtime to accept connections before serving Next (avoids startup 502s).
i=0
while [ "$i" -lt 60 ]; do
  if node -e "fetch('http://127.0.0.1:${EVE_PORT}/eve/v1/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" 2>/dev/null; then
    echo "eve runtime healthy on :${EVE_PORT}"
    break
  fi
  if ! kill -0 "$EVE_PID" 2>/dev/null; then
    echo "eve runtime exited during startup" >&2
    exit 1
  fi
  i=$((i + 1))
  sleep 1
done

echo "starting next start on :${NEXT_PORT} ..."
npx --no-install next start -p "$NEXT_PORT" &
NEXT_PID=$!

# Wait for Next before opening the front port (avoids 502s on the domain during boot).
i=0
while [ "$i" -lt 60 ]; do
  if node -e "fetch('http://127.0.0.1:${NEXT_PORT}/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" 2>/dev/null; then
    echo "next healthy on :${NEXT_PORT}"
    break
  fi
  if ! kill -0 "$NEXT_PID" 2>/dev/null; then
    echo "next start exited during startup" >&2
    exit 1
  fi
  i=$((i + 1))
  sleep 1
done

echo "starting front-proxy on :${FRONT_PORT} ..."
exec node front-proxy.mjs
