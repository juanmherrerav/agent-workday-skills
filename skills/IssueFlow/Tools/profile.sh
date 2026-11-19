#!/usr/bin/env bash
# profile.sh — SOURCED by every IssueFlow tool. Locates the MAIN repo root (even when
# called from inside a feature worktree), loads the repo's workflow profile, applies
# defaults, and defines small helpers. Not meant to be executed directly.
#
# Profile: <main-root>/.claude/workflow-profile.sh   (override path with IF_PROFILE)
# Template: $SKILLS_HOME/IssueFlow/Templates/workflow-profile.sh

if_die() { echo "✗ $*" >&2; exit 1; }

# Main checkout root. `--show-toplevel` would return the WORKTREE root when run inside
# one; the common git dir always belongs to the main checkout.
if_main_root() {
  local common
  common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  dirname "$common"
}

IF_ROOT="$(if_main_root)" || if_die "not inside a git repository"
IF_SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IF_PROFILE="${IF_PROFILE:-$IF_ROOT/.claude/workflow-profile.sh}"

[ -f "$IF_PROFILE" ] || if_die "no workflow profile at $IF_PROFILE
  create one:  cp $IF_SKILL_DIR/Templates/workflow-profile.sh $IF_ROOT/.claude/workflow-profile.sh"
# shellcheck disable=SC1090
. "$IF_PROFILE"

_tf_default() { [ -n "${!1:-}" ] || printf -v "$1" '%s' "$2"; }
_tf_default_array() { declare -p "$1" >/dev/null 2>&1 || eval "$1=()"; }

_tf_default PROJECT_NAME        "$(basename "$IF_ROOT")"
_tf_default ISSUE_PATTERN      '^[A-Z][A-Z0-9]+-[0-9]+$'
_tf_default TRACKER             jira
_tf_default REMOTE              origin
_tf_default INTEGRATION_BRANCH  main
_tf_default PRODUCTION_BRANCH   main
_tf_default BRANCH_TEMPLATE     '{KEY}'
_tf_default MERGE_STRATEGY      ff-only
_tf_default WORKTREE_DIR        .claude/local/worktrees
_tf_default LEDGER_FILE         .claude/local/worktree-registry.md
_tf_default PORT_BASE_BACKEND   8000
_tf_default PORT_BASE_FRONTEND  3000
_tf_default PORT_ENV_FILE       .env.local
_tf_default PORT_VAR_BACKEND    PORT
_tf_default PORT_VAR_FRONTEND   FRONTEND_PORT
_tf_default HEALTH_PATH         /
_tf_default APP_PATH            /
_tf_default SERVE_TIMEOUT       60
_tf_default PREVIEW_PROVIDER    none
_tf_default PREVIEW_ENVIRONMENT Preview
_tf_default STAKEHOLDER_GATE    true
_tf_default REVIEW_CHANNEL      none
_tf_default IDE_CLI             none
_tf_default UNIT_CMD            ""
_tf_default E2E_CMD             ""
_tf_default SERVE_CMD           ""
_tf_default E2E_RECORD_CMD      ""
_tf_default FIXTURES_DIR        tests/fixtures
_tf_default PREVIEW_PROJECT     "$PROJECT_NAME"
_tf_default PREVIEW_SCOPE       ""
_tf_default PREVIEW_TEAM_ID     ""
_tf_default PREVIEW_PROJECT_ID  ""
_tf_default FORGE               github
_tf_default ENV_MATRIX_FILE     .claude/release/settings-matrix.json
# ISSUE_PREFIX is derived from ISSUE_PATTERN ('^ABC-[0-9]+$' → ABC). Set it in the profile only
# when the pattern has no literal prefix. Empty means "group releases by any KEY-123 key".
if [ -z "${ISSUE_PREFIX:-}" ]; then
  ISSUE_PREFIX="${ISSUE_PATTERN#^}"; ISSUE_PREFIX="${ISSUE_PREFIX%%-*}"
  case "$ISSUE_PREFIX" in *[\[\(\\.\*\+\?]*) ISSUE_PREFIX="" ;; esac
fi
_tf_default_array ENV_FILES
_tf_default_array SETUP_CMDS
_tf_default_array VERIFY_PATHS
_tf_default_array PREFLIGHT_CHECKS
_tf_default_array PREFLIGHT_FIX_CMDS
_tf_default_array E2E_SERVER_ENV
_tf_default_array E2E_RECORD_ENV
_tf_default_array ENV_REQUIRED_VARS
_tf_default_array ENV_OPTIONAL_VARS
_tf_default_array ENV_PLACEHOLDER_VALUES
# what CI writes into env files so fixture mode boots without credentials
[ "${#ENV_PLACEHOLDER_VALUES[@]}" -gt 0 ] || ENV_PLACEHOLDER_VALUES=("test-key" "your-key-here" "changeme" "placeholder")

IF_LEDGER="$IF_ROOT/$LEDGER_FILE"
IF_LOCAL_DIR="$IF_ROOT/$(dirname "$LEDGER_FILE")"   # the git-ignored runtime dir (worktrees, ledger, tracker cache)

# --- helpers ------------------------------------------------------------------------
if_resolve_wt() {    # if_resolve_wt [DIR] — absolute path of a worktree dir (default CWD), or fail
  local d
  d="$(cd "${1:-$PWD}" 2>/dev/null && pwd)" || { echo "✗ no such dir: ${1:-}" >&2; return 1; }
  printf '%s' "$d"
}

if_require_key() {   # if_require_key KEY — exits unless KEY matches ISSUE_PATTERN
  [[ "${1:-}" =~ $ISSUE_PATTERN ]] || if_die "issue key '${1:-}' does not match ISSUE_PATTERN ($ISSUE_PATTERN)"
}

if_slugify() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g'; }

if_branch() {        # if_branch KEY [SLUG] — render BRANCH_TEMPLATE
  local key="$1" slug="${2:-}" b="$BRANCH_TEMPLATE"
  b="${b//\{KEY\}/$key}"
  b="${b//\{key\}/$(printf '%s' "$key" | tr '[:upper:]' '[:lower:]')}"
  b="${b//\{slug\}/$slug}"
  printf '%s' "$b"
}

if_wt_path() { printf '%s/%s/%s' "$IF_ROOT" "$WORKTREE_DIR" "$1"; }

if_wt_port() {       # if_wt_port WT — backend port written by provision.sh (empty if none)
  grep -E "^${PORT_VAR_BACKEND}=" "$1/$PORT_ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2
}

if_free_port() {     # if_free_port PORT — kill whatever holds it
  local holder
  holder="$(lsof -ti:"$1" 2>/dev/null || true)"
  if [ -n "$holder" ]; then
    echo "▶ port :$1 held by PID(s) $holder — killing"
    # shellcheck disable=SC2086
    kill -9 $holder 2>/dev/null || true
    sleep 1
  fi
}

if_wait_healthy() {  # if_wait_healthy PORT LOG — poll HEALTH_PATH until 2xx/3xx or timeout
  local url="http://127.0.0.1:$1$HEALTH_PATH" i
  for ((i = 0; i < SERVE_TIMEOUT; i++)); do
    curl -sf -o /dev/null "$url" && return 0
    sleep 1
  done
  echo "✗ server never became healthy at $url (log: $2)" >&2
  return 1
}

IF_SRV_PID=""
if_start_server() {  # if_start_server PORT LOG [VAR=VAL ...] — kill any stale holder, start SERVE_CMD in its
                     # own session with the given env + PORT, wait for HEALTH_PATH. Returns 1 if it never came up.
  local port="$1" log="$2"; shift 2
  [ -n "$SERVE_CMD" ] || { echo "✗ no SERVE_CMD in $IF_PROFILE — nothing to launch" >&2; return 1; }
  if_free_port "$port"
  echo "▶ fresh server on :$port  (env: ${*:-none})  log: $log"
  env "$@" PORT="$port" setsid bash -c "$SERVE_CMD" >"$log" 2>&1 &
  IF_SRV_PID=$!
  if_wait_healthy "$port" "$log" || return 1
  echo "✔ server healthy"
}

if_stop_server() {   # if_stop_server PORT — stop what if_start_server started; no-op otherwise
  [ -n "$IF_SRV_PID" ] || return 0
  kill -- "-$IF_SRV_PID" 2>/dev/null || kill "$IF_SRV_PID" 2>/dev/null || true
  if_free_port "$1" >/dev/null
  IF_SRV_PID=""
  echo "▶ server on :$1 torn down"
}

if_seed_ledger() {
  [ -f "$IF_LEDGER" ] && return 0
  mkdir -p "$(dirname "$IF_LEDGER")"
  cat >"$IF_LEDGER" <<EOF
# Worktree ledger — $PROJECT_NAME (live, machine-specific, git-ignored)

| Path | Branch | Purpose | X | Status |
| ---- | ------ | ------- | - | ------ |
| \`.\` (repo root) | \`$INTEGRATION_BRANCH\` | Primary checkout | 0 ($PORT_BASE_FRONTEND/$PORT_BASE_BACKEND) | Active |
EOF
}

# Executed directly (not sourced) → print the effective profile.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "profile: $IF_PROFILE"
  for v in PROJECT_NAME ISSUE_PATTERN ISSUE_PREFIX TRACKER FORGE REMOTE INTEGRATION_BRANCH PRODUCTION_BRANCH \
           BRANCH_TEMPLATE MERGE_STRATEGY WORKTREE_DIR IF_LOCAL_DIR PORT_BASE_BACKEND PORT_BASE_FRONTEND \
           UNIT_CMD E2E_CMD SERVE_CMD HEALTH_PATH APP_PATH FIXTURES_DIR \
           PREVIEW_PROVIDER PREVIEW_PROJECT PREVIEW_SCOPE PREVIEW_URL_TEMPLATE ENV_MATRIX_FILE \
           STAKEHOLDER_GATE STAKEHOLDER REVIEW_CHANNEL IDE_CLI; do
    printf '  %-20s %s\n' "$v" "${!v:-<unset>}"
  done
  printf '  %-20s %s\n' PREFLIGHT_CHECKS "${#PREFLIGHT_CHECKS[@]} check(s)" SETUP_CMDS "${#SETUP_CMDS[@]} cmd(s)" \
         ENV_REQUIRED_VARS "${#ENV_REQUIRED_VARS[@]} var(s)" E2E_RECORD_ENV "${#E2E_RECORD_ENV[@]} var(s)"
fi
