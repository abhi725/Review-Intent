#!/usr/bin/env bash
# Push the lead queue into Google Sheets. Run from cron.
#
# Runs the request *inside* the container, for three reasons:
#
#   * Port 8100 is exposed but not published to the host, so 127.0.0.1:8100 is not
#     reachable from here — Traefik reaches the container over the Docker network.
#   * The container's IP changes on every redeploy, and every deploy recreates it,
#     so an address baked into this file would work until the next release.
#   * Going out through the public hostname would put Cloudflare in the path,
#     which cuts a request at about 100 seconds and reports the failure even when
#     the work completed. A scheduled job that logs failures for successful work
#     is worse than no logging.
#
# The container has no curl, so the request is made with httpx, which the
# application already depends on.
set -uo pipefail

CONTAINER=swan-intent-api
LOG=/var/log/intent-desk-sheets.log

if ! docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
  echo "$(date -Is) FAILED container $CONTAINER is not running" >> "$LOG"
  exit 1
fi

# The token is read inside the container from its own environment, so it is never
# passed on a command line where `ps` would show it.
OUTPUT=$(docker exec "$CONTAINER" python -c '
import json, os, sys

import httpx

token = os.environ.get("MCP_BEARER_TOKEN", "")
if not token:
    print("FAILED no MCP_BEARER_TOKEN in the container environment")
    sys.exit(1)
try:
    r = httpx.post("http://127.0.0.1:8100/cron/push-sheet",
                   headers={"Authorization": "Bearer " + token}, timeout=120)
except Exception as exc:
    print("FAILED " + repr(exc))
    sys.exit(1)
if r.status_code == 200:
    print("ok " + json.dumps(r.json()))
else:
    print("FAILED http=%s %s" % (r.status_code, r.text[:300]))
    sys.exit(1)
' 2>&1)

echo "$(date -Is) $OUTPUT" >> "$LOG"

# Keep the log bounded; this runs every 15 minutes.
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG")" -gt 1000000 ]; then
  tail -n 500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

case "$OUTPUT" in
  ok*) exit 0 ;;
  *)   exit 1 ;;
esac
