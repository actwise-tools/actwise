#!/usr/bin/env bash
# Bring up the noVNC display stack, then the broker. A headed Chromium launched
# by the self-hosted backend renders on :99 and is viewable/drivable via noVNC.
set -euo pipefail

: "${DISPLAY:=:99}"

Xvfb "${DISPLAY}" -screen 0 1280x800x24 &
sleep 1
fluxbox >/dev/null 2>&1 &
x11vnc -display "${DISPLAY}" -forever -shared -nopw -quiet -rfbport 5900 >/dev/null 2>&1 &
websockify --web=/usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 &

exec docenter-broker
