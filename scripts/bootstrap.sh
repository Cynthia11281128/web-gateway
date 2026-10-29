#!/usr/bin/env bash
set -euo pipefail
PROJECT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${WEB_GATEWAY_PYTHON:-python3}"
export UV_CACHE_DIR="$PROJECT/var/uv-cache"
mkdir -p "$PROJECT/.downloads" "$PROJECT/.bin"
test -x "$PROJECT/.venv/bin/python" || \
  uv venv --python "$PYTHON" "$PROJECT/.venv"
uv pip install --python "$PROJECT/.venv/bin/python" -r "$PROJECT/server/requirements.lock"
uv pip install --python "$PROJECT/.venv/bin/python" --no-deps -e "$PROJECT/server"
curl --fail --location --max-time 120 \
  https://github.com/caddyserver/caddy/releases/download/v2.11.7/caddy_2.11.7_linux_amd64.tar.gz \
  -o "$PROJECT/.downloads/caddy_2.11.7_linux_amd64.tar.gz"
curl --fail --location --max-time 30 \
  https://github.com/caddyserver/caddy/releases/download/v2.11.7/caddy_2.11.7_checksums.txt \
  -o "$PROJECT/.downloads/checksums.txt"
(
  cd "$PROJECT/.downloads"
  awk '$2 == "caddy_2.11.7_linux_amd64.tar.gz" { print }' checksums.txt | sha512sum --check -
)
tar -xzf "$PROJECT/.downloads/caddy_2.11.7_linux_amd64.tar.gz" -C "$PROJECT/.bin" caddy
"$PROJECT/.bin/caddy" version
