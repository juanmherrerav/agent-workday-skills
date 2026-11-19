#!/usr/bin/env bash
# cleanup.sh — tear a feature worktree down: stop its server, drop it from the IDE workspace
# file, remove the worktree, delete the local (and optionally remote) branch, free its ledger
# row.
#
# Usage: cleanup.sh <worktree-dir> [--delete-remote] [--keep-branch] [--keep-worktree]
#   --keep-worktree  remediation cycles: stop the server, detach the worktree onto the latest
#                    integration branch, delete the cycle branch, keep the worktree + ledger row
#   --keep-branch    never delete branches
#   --delete-remote  also delete the branch on $REMOTE
# A local branch is deleted only when it is contained in $REMOTE/$INTEGRATION_BRANCH.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/profile.sh"

WT=""; DEL_REMOTE=""; KEEP_BRANCH=""; KEEP_WT=""
for arg in "$@"; do
  case "$arg" in
    --delete-remote) DEL_REMOTE=1 ;;
    --keep-branch)   KEEP_BRANCH=1 ;;
    --keep-worktree) KEEP_WT=1 ;;
    *) WT="$arg" ;;
  esac
done
[ -n "$WT" ] || if_die "usage: cleanup.sh <worktree-dir> [--delete-remote] [--keep-branch] [--keep-worktree]"
WT="$(if_resolve_wt "$WT")" || exit 1
[ "$WT" = "$IF_ROOT" ] && if_die "refusing to clean up the main checkout"
NAME="$(basename "$WT")"
BRANCH="$(git -C "$WT" rev-parse --abbrev-ref HEAD)"

PORT="$(if_wt_port "$WT")"
[ -n "$PORT" ] && if_free_port "$PORT"

git -C "$IF_ROOT" fetch -q "$REMOTE" "$INTEGRATION_BRANCH" 2>/dev/null || true

if [ -n "$KEEP_WT" ]; then
  git -C "$WT" diff --quiet HEAD 2>/dev/null \
    || if_die "uncommitted work in $WT — commit or stash it before closing the cycle"
  git -C "$WT" switch -q --detach "$REMOTE/$INTEGRATION_BRANCH" \
    && echo "✔ worktree kept, detached at $REMOTE/$INTEGRATION_BRANCH (branch $BRANCH is free)"
else
  if [ -n "${IDE_WORKSPACE_FILE:-}" ] && [ -f "$IF_ROOT/$IDE_WORKSPACE_FILE" ]; then
    python3 - "$IF_ROOT/$IDE_WORKSPACE_FILE" "$NAME" <<'EOF' && echo "⚠️  removed from $IDE_WORKSPACE_FILE — reload the IDE window"
import json, sys
path, name = sys.argv[1], sys.argv[2]
ws = json.load(open(path))
before = len(ws.get("folders", []))
ws["folders"] = [f for f in ws.get("folders", []) if not f.get("path", "").rstrip("/").endswith(name)]
if len(ws["folders"]) == before:
    sys.exit(1)
json.dump(ws, open(path, "w"), indent="\t")
EOF
  fi
  git -C "$IF_ROOT" worktree remove "$WT" || if_die "worktree has local changes — commit/stash or remove by hand"
  [ -f "$IF_LEDGER" ] && grep -vF "\`$WORKTREE_DIR/$NAME\`" "$IF_LEDGER" >"$IF_LEDGER.tmp" && mv "$IF_LEDGER.tmp" "$IF_LEDGER"
  echo "✔ worktree removed, ledger row freed"
fi

if [ -z "$KEEP_BRANCH" ] && [ "$BRANCH" != HEAD ] \
   && [ "$BRANCH" != "$INTEGRATION_BRANCH" ] && [ "$BRANCH" != "$PRODUCTION_BRANCH" ]; then
  if git -C "$IF_ROOT" merge-base --is-ancestor "$BRANCH" "$REMOTE/$INTEGRATION_BRANCH" 2>/dev/null; then
    git -C "$IF_ROOT" branch -D "$BRANCH" >/dev/null && echo "✔ local branch $BRANCH deleted (contained in $REMOTE/$INTEGRATION_BRANCH)"
  else
    echo "⚠️  $BRANCH is not contained in $REMOTE/$INTEGRATION_BRANCH — left in place (delete by hand only if you are sure)"
  fi
  if [ -n "$DEL_REMOTE" ]; then
    git -C "$IF_ROOT" push "$REMOTE" --delete "$BRANCH" 2>/dev/null && echo "✔ remote branch deleted" \
      || echo "ℹ︎ remote branch $BRANCH already gone"
  fi
fi
