# ActWise eve portal — local production container (non-Vercel host).
#
# Runs the Next.js app + the eve runtime as TWO processes in one container. The
# "Local production build" topology from eve/docs/guides/frontend/nextjs.mdx bakes the
# /eve/v1 proxy destination (127.0.0.1:4274) into the Next routes-manifest at build
# time, so `next start` never re-runs rewrites() and never spawns the runtime — the
# entrypoint starts it explicitly:
#   eve build   -> compiles the eve runtime to agent .output/server/index.mjs
#   next build  -> builds the Next.js app (withEve bakes the /eve/v1 -> :4274 proxy)
#   docker-entrypoint.sh -> runs the eve runtime on :4274 AND next start on :3333
#
# Node 24 (the package's engines requirement) lives in the image, so it does not
# depend on the host Node version. Secrets are NOT baked in — pass them at run
# time with `--env-file .env.local`. Build needs no secrets.
FROM node:24-slim

WORKDIR /app

# Install deps against the committed lockfile first (better layer caching).
COPY package.json package-lock.json ./
RUN npm ci

# App source.
COPY . .

# eve build statically evaluates connections/*.ts and bakes each connection's
# RESOLVED url into the agent manifest. DOCENTER_MCP_URL is the public AWS MCP
# endpoint (not a secret), so it must be present at BUILD time or the docenter
# connection freezes to its localhost dev fallback (127.0.0.1:8787). Runtime secrets
# (proxy API key, user-token secret) stay out of the build — the connection's
# headers() function reads them from the environment at request time.
ARG DOCENTER_MCP_URL=""
ENV DOCENTER_MCP_URL=${DOCENTER_MCP_URL}

# Compile the eve runtime, then the Next.js app. No secrets required at build.
RUN npx eve build && npm run build

ENV NODE_ENV=production
# The front-proxy listens on 8080 (published); next start on 3333 and the eve runtime
# on 4274 are internal. The entrypoint starts all three (see the script).
EXPOSE 8080

# Normalise line endings (the script may be checked out with CRLF on Windows) and
# make it executable.
RUN sed -i 's/\r$//' docker-entrypoint.sh && chmod +x docker-entrypoint.sh

CMD ["./docker-entrypoint.sh"]
