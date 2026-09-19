# Auto-deploy

Deploy script: /opt/bot/deploy.sh (cron every 3 min, flock-protected).
Flow: git fetch -> reset --hard origin/main -> docker compose build -> up -d.
Smoke-test commit for autodeploy verification (2026-09-19).
