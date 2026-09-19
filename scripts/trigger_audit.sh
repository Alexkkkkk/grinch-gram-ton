#!/usr/bin/env bash
# Trigger the Grok audit on demand from the server (cron / post-deploy hook).
set -euo pipefail
REPO="${REPO:-Alexkkkkk/grinch-gram-ton}"
GH_TOKEN="${GH_TOKEN:?set GH_TOKEN}"
EVENT="${EVENT:-grok-audit}"

curl -fsSL -X POST \
  -H "Authorization: Bearer ${GH_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${REPO}/dispatches" \
  -d "{\"event_type\":\"${EVENT}\",\"client_payload\":{\"source\":\"$(hostname)\",\"when\":\"$(date -u +%FT%TZ)\"}}"
echo "dispatch '${EVENT}' отправлен в ${REPO}"
