#!/usr/bin/env bash
set -euo pipefail
PROJECT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$PROJECT/scripts/python.sh" -m web_gateway.cli \
  --config "${WEB_GATEWAY_CONFIG:-$PROJECT/var/runtime.json}" "$@"
