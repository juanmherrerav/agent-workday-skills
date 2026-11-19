#!/usr/bin/env bash
# issue-sync.sh — tracker-agnostic entry point. Picks an adapter directory by name and runs
# the verb there. Adding a tracker = adding Adapters/<name>/adapter (see Adapters/README.md).
#
# Adapter selection, first match wins:
#   1. $ISSUE_TRACKER in the environment
#   2. TRACKER= in <main checkout>/.claude/workflow-profile.sh (the IssueFlow profile)
#   3. auto: JIRA_API_TOKEN present in env or .env(.local) → jira, otherwise none
# Root is the MAIN checkout (common git dir), so worktrees share one cache.
# Runtime dir: $ISSUE_SYNC_DIR, default <root>/.claude/local/<tracker>/ (git-ignored).
#
# Verbs (the contract):
#   adapter                     which adapter is active, and where it lives
#   markup                      comment syntax the tracker wants: wiki | markdown
#   list                        my active issues (adapter)
#   pull KEY [KEY ...]          refresh the cache → cache/KEY.json (adapter)
#   show KEY                    status + available transitions, no file writes (adapter)
#   cache KEY                   print the cache path
#   worklog KEY                 print the worklog path; write comments there
#   comment KEY [FILE]          post FILE (default: the worklog) as a comment (adapter)
#   transitions KEY             exact transition names available right now (adapter)
#   transition KEY NAME         apply one (adapter)
#   assign KEY QUERY            assign to the first assignable match (adapter)
#   count-comments KEY REGEX    cached comments whose body matches REGEX (e.g. '^h2\. Cycle')
# Exit: adapter's code; 3 = "no tracker, do this instead" (the none adapter).
set -uo pipefail
die() { echo "✗ $*" >&2; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADAPTERS="$(cd "$HERE/../Adapters" && pwd)"

common="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
ROOT="${common:+$(dirname "$common")}"; ROOT="${ROOT:-$PWD}"

TRACKER=""
PROFILE="$ROOT/.claude/workflow-profile.sh"
[ -f "$PROFILE" ] && TRACKER="$(bash -c ". '$PROFILE' 2>/dev/null; printf '%s' \"\${TRACKER:-}\"")"
TRACKER="${ISSUE_TRACKER:-$TRACKER}"
if [ -z "$TRACKER" ] || [ "$TRACKER" = auto ]; then
  if [ -n "${JIRA_API_TOKEN:-}" ] || grep -qsE '^(export )?JIRA_API_TOKEN=' "$ROOT/.env.local" "$ROOT/.env"; then
    TRACKER=jira
  else
    TRACKER=none
  fi
fi
[ -x "$ADAPTERS/$TRACKER/adapter" ] \
  || die "no adapter '$TRACKER' (have: $(ls "$ADAPTERS" | grep -v README | tr '\n' ' ')). Add $ADAPTERS/$TRACKER/adapter — see Adapters/README.md"

export ISSUE_SYNC_ROOT="$ROOT" ISSUE_SYNC_TRACKER="$TRACKER"
export ISSUE_SYNC_DIR="${ISSUE_SYNC_DIR:-$ROOT/.claude/local/$TRACKER}"

VERB="${1:-}"; shift || true
KEY="${1:-}"
[ -n "$VERB" ] || die "usage: issue-sync.sh <adapter|markup|list|pull|show|cache|worklog|comment|transitions|transition|assign|count-comments> [KEY ...]"

case "$VERB" in
  adapter) echo "$TRACKER ($ADAPTERS/$TRACKER)" ;;
  cache)   [ -n "$KEY" ] || die "cache needs KEY"; echo "$ISSUE_SYNC_DIR/cache/$KEY.json" ;;
  worklog) [ -n "$KEY" ] || die "worklog needs KEY"; mkdir -p "$ISSUE_SYNC_DIR/worklog"; echo "$ISSUE_SYNC_DIR/worklog/$KEY.md" ;;
  count-comments)
    [ -n "$KEY" ] || die "count-comments needs KEY REGEX"
    re="${2:?count-comments needs REGEX}"
    c="$ISSUE_SYNC_DIR/cache/$KEY.json"
    [ -f "$c" ] || "$ADAPTERS/$TRACKER/adapter" pull "$KEY" >/dev/null || exit $?
    python3 - "$c" "$re" <<'PY'
import json, re, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
rx = re.compile(sys.argv[2], re.M)
print(sum(1 for c in data.get("comments", []) if rx.search(c.get("body") or "")))
PY
    ;;
  *) exec "$ADAPTERS/$TRACKER/adapter" "$VERB" "$@" ;;
esac
