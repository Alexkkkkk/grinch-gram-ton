#!/usr/bin/env bash
# Install a GitHub Actions self-hosted runner as a systemd service.
# Run ON the target server (2.27.25.126 / 632969.senko.network) as root:
#   REPO=Alexkkkkk/grinch-gram-ton GH_TOKEN=<PAT> bash setup_self_hosted_runner.sh
set -euo pipefail

REPO="${REPO:-Alexkkkkk/grinch-gram-ton}"
GH_TOKEN="${GH_TOKEN:-}"
RUNNER_NAME="${RUNNER_NAME:-$(hostname)-gha}"
LABELS="${LABELS:-self-hosted,linux,x64,senko}"
RUNNER_DIR="${RUNNER_DIR:-/opt/actions-runner}"
RUNNER_VERSION="${RUNNER_VERSION:-2.319.1}"

[[ $EUID -eq 0 ]] || { echo "Запустите от root."; exit 1; }
[[ -n "$GH_TOKEN" ]] || { echo "Нужен GH_TOKEN (PAT с правами repo admin)."; exit 1; }

install -d -m 0755 "$RUNNER_DIR"
cd "$RUNNER_DIR"

echo "==> Получаю registration-token"
REG_TOKEN="$(curl -fsSL -X POST \
  -H "Authorization: Bearer ${GH_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${REPO}/actions/runners/registration-token" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')"

if [[ ! -x ./config.sh ]]; then
  echo "==> Скачиваю runner ${RUNNER_VERSION}"
  curl -fsSL -o runner.tar.gz \
    "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
  tar xzf runner.tar.gz && rm -f runner.tar.gz
fi

echo "==> Настраиваю runner: ${RUNNER_NAME} [${LABELS}]"
./config.sh --unattended --replace \
  --url "https://github.com/${REPO}" \
  --token "$REG_TOKEN" \
  --name "$RUNNER_NAME" \
  --labels "$LABELS" \
  --work "_work"

echo "==> Устанавливаю как systemd-сервис"
./svc.sh install
./svc.sh start
./svc.sh status || true

echo "Готово. Проверка: https://github.com/${REPO}/settings/actions/runners"
echo "В GitHub задайте переменную репозитория GROK_RUNNER=${RUNNER_NAME}"
