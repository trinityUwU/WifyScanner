#!/usr/bin/env bash
# Arrête API, frontend Vite et collecteur (PIDs dans logs/*.pid).
# Équivalent : ./start.sh stop

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/start.sh" stop
