# DOCenter login broker — self-hosted noVNC + Playwright backend.
#
# Runs the broker (FastAPI) plus a headed Chromium the end user drives through
# noVNC in the browser. This is the Conditional-Access fallback backend (R5):
# self-host on the corp network where the employee SSO / Entra CA policy allows
# an interactive login. For the Browserbase (datacenter) backend no image is
# needed — set BROKER_BACKEND=browserbase + the Browserbase env vars instead.
#
# Base image ships Chromium + the noVNC/websockify/x11 stack for Playwright.
FROM mcr.microsoft.com/playwright/python:v1.55.0-jammy

# noVNC + a lightweight X server / VNC bridge so the user can see & drive Chromium.
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb x11vnc fluxbox novnc websockify \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the actwise distribution (broker console script + docenter deps).
COPY . /app
RUN pip install --no-cache-dir -e "." \
    && python -m playwright install chromium

ENV BROKER_BACKEND=self-hosted \
    BROKER_HOST=0.0.0.0 \
    BROKER_PORT=8099 \
    BROKER_HEADLESS=false \
    BROKER_NOVNC_URL=http://localhost:6080/vnc.html \
    DISPLAY=:99

EXPOSE 8099 6080

# Start Xvfb + VNC + noVNC, then the broker. A headed Chromium launched by the
# self-hosted backend renders onto :99 and is reachable via noVNC on :6080.
COPY components/portal/broker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
