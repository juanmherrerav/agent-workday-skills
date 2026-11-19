#!/usr/bin/env bash
# e2e.sh — run the full e2e suite against a FRESH server on this worktree's port, and ALWAYS
# tear the server down. With --record the server runs in record mode (E2E_RECORD_ENV) so the
# app saves upstream responses as fixtures, and the fixture count is reported afterwards.
#
# Server env: E2E_SERVER_ENV (fixture mode) or E2E_RECORD_ENV (--record). These are process
# env vars, so they beat .env values for loaders that don't force-override (python-dotenv
# default, pydantic-settings, most JS frameworks). The suite gets PORT and BASE_URL=http://127.0.0.1:$PORT.
#
# Usage: e2e.sh [--record] [--no-server] [worktree-dir] [-- extra args appended to the command]
# Exit:  the suite's exit code. "E2E: SKIPPED" (exit 0) when nothing is configured — report
#        that as SKIPPED, never as passed.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/profile.sh"

RECORD=""; NO_SERVER=""; WT="$PWD"; EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --record)    RECORD=1 ;;
    --no-server) NO_SERVER=1 ;;
    --) shift; EXTRA=("$@"); break ;;
    *) WT="$1" ;;
  esac
  shift
done
WT="$(if_resolve_wt "$WT")" || exit 1

if [ -n "$RECORD" ]; then
  MODE=record; CMD="${E2E_RECORD_CMD:-$E2E_CMD}"
  SRV_ENV=(${E2E_RECORD_ENV[@]+"${E2E_RECORD_ENV[@]}"})
  [ -z "$CMD" ] || [ "${#SRV_ENV[@]}" -gt 0 ] \
    || if_die "E2E_RECORD_ENV is empty — the server must be told it is recording (e.g. E2E_API_MODE=record)"
else
  MODE=e2e; CMD="$E2E_CMD"
  SRV_ENV=(${E2E_SERVER_ENV[@]+"${E2E_SERVER_ENV[@]}"})
fi
if [ -z "$CMD" ]; then
  echo "E2E: SKIPPED — no ${RECORD:+E2E_RECORD_CMD / }E2E_CMD in $IF_PROFILE"
  exit 0
fi

PORT="$(if_wt_port "$WT")"; [ -n "$PORT" ] || PORT="$PORT_BASE_BACKEND"
LOG="${TMPDIR:-/tmp}/if-$MODE-$PROJECT_NAME-$PORT.log"
trap 'if_stop_server "$PORT"' EXIT INT TERM
count_fixtures() { find "$WT/$FIXTURES_DIR" -type f 2>/dev/null | wc -l | tr -d ' '; }
before=0; [ -n "$RECORD" ] && before="$(count_fixtures)"

cd "$WT" || exit 1
if [ -z "$NO_SERVER" ]; then
  if_start_server "$PORT" "$LOG" ${SRV_ENV[@]+"${SRV_ENV[@]}"} || exit 1
fi

echo "▶ [$MODE] $CMD ${EXTRA[*]:-}"
PORT="$PORT" BASE_URL="http://127.0.0.1:$PORT" bash -c "$CMD \"\$@\"" _ ${EXTRA[@]+"${EXTRA[@]}"}
rc=$?

if [ -n "$RECORD" ]; then
  after="$(count_fixtures)"
  echo "RECORD: $after fixture file(s) in $FIXTURES_DIR ($((after - before)) new) — suite exit $rc"
  echo "   review the fixture diff for secrets, then commit $FIXTURES_DIR"
fi
[ "$rc" = 0 ] && echo "E2E: PASS" || echo "E2E: FAIL (exit $rc)"
exit "$rc"
