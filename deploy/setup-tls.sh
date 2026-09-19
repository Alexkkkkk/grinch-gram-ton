#!/bin/bash
# -*- mode: sh; sh-shell: bash -*-
#--------------------------------------------------------------------------
#  setup-tls.sh — install the WebSocket-aware + TLS nginx site and obtain a
#  Let's Encrypt certificate. Run once on the VPS as root.
#
#  Usage: DOMAIN=632969.senko.network bash deploy/setup-tls.sh
#--------------------------------------------------------------------------
set -euo pipefail

DOMAIN=${DOMAIN:-632969.senko.network}
EMAIL=${EMAIL:-}
SRC="$(cd "$(dirname "$0")" && pwd)/nginx/grinch.conf"
DEST=/etc/nginx/sites-available/grinch

[ -f "$SRC" ] || { echo "config not found: $SRC" >&2; exit 1; }

echo "==> Installing nginx site"
cp "$SRC" "$DEST"
ln -sf "$DEST" /etc/nginx/sites-enabled/grinch
mkdir -p /var/www/html

echo "==> Opening 443 (ufw)"
if command -v ufw >/dev/null && ufw status | grep -q active; then
    ufw allow 443/tcp || true
fi

echo "==> Obtaining certificate for $DOMAIN"
# Build argv explicitly: an earlier draft appended ${EMAIL} as a bare positional
# argument, which certbot rejects with "unrecognized arguments".
CERTBOT_ARGS=(certonly --webroot -w /var/www/html -d "$DOMAIN"
              --non-interactive --agree-tos --keep-until-expiring)
if [ -n "$EMAIL" ]; then
    CERTBOT_ARGS+=(--email "$EMAIL")
else
    CERTBOT_ARGS+=(--register-unsafely-without-email)
fi
certbot "${CERTBOT_ARGS[@]}" || {
    echo "certbot failed. Check that $DOMAIN resolves to this host and that"
    echo "port 80 is reachable from the internet, then re-run this script." >&2
    exit 1
}

echo "==> Validating and reloading nginx"
nginx -t
systemctl reload nginx
systemctl enable --now certbot.timer 2>/dev/null || true

echo "==> Done. Dashboard should now be reachable over https://$DOMAIN"
