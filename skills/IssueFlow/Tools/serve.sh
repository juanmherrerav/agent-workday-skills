#!/usr/bin/env bash
# serve.sh — launch the app for ONE worktree so a human can validate it, and LEAVE IT RUNNING
# (unlike e2e.sh, which tears its server down). Kills any stale holder of the port first so
# the human never validates old code, waits for HEALTH_PATH, prints the URL and stop command.
#
# Usage: serve.sh [worktree-dir]   (default: CWD)
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/profile.sh"

WT="$(if_resolve_wt "${1:-$PWD}")"
PORT="$(if_wt_port "$WT")"; [ -n "$PORT" ] || PORT="$PORT_BASE_BACKEND"
LOG="${TMPDIR:-/tmp}/if-serve-$PROJECT_NAME-$PORT.log"

cd "$WT"
if_start_server "$PORT" "$LOG"
disown "$IF_SRV_PID" 2>/dev/null || true
echo "✅ app is up — open:  http://127.0.0.1:$PORT$APP_PATH"
echo "   stop it with:      kill -9 \$(lsof -ti:$PORT)"
