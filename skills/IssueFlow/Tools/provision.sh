#!/usr/bin/env bash
# provision.sh — create + fully provision a feature worktree, driven by the repo profile.
#
# `git worktree add` carries only tracked files. Everything needed to RUN (env files, deps,
# ports) is git-ignored and absent; this script supplies all of it deterministically:
#   1. picks the lowest free port digit X (1-9) from the live ledger (or uses the given X)
#   2. creates the worktree off the latest $REMOTE/$INTEGRATION_BRANCH (or reuses an
#      existing local branch of that name — resuming work)
#   3. copies ENV_FILES from the main checkout, appends this worktree's ports
#   4. runs SETUP_CMDS, then POST_PROVISION_HOOK, then checks VERIFY_PATHS
#   5. records the worktree in the ledger and adds it to the IDE workspace
#
# Usage: provision.sh <name> <branch> [X|auto] [purpose] [--reuse]
#   e.g. provision.sh abc-26-name-matching ABC-26 auto "flexible name matching"
#   --reuse  the worktree may already exist (remediation cycles): keep it and its ports,
#            refuse uncommitted work, point it at a NEW branch off the latest integration
#            branch, re-run steps 4-5 (deps may have moved; the ledger row gets the new branch).
#            Without --reuse an existing worktree is an error: resume it instead.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/profile.sh"

REUSE=""; ARGS=()
for a in "$@"; do case "$a" in --reuse) REUSE=1 ;; *) ARGS+=("$a") ;; esac; done
set -- ${ARGS[@]+"${ARGS[@]}"}

NAME="${1:?usage: provision.sh <name> <branch> [X|auto] [purpose] [--reuse]}"
BRANCH="${2:?usage: provision.sh <name> <branch> [X|auto] [purpose] [--reuse]}"
X="${3:-auto}"
PURPOSE="${4:-$BRANCH}"
WT="$(if_wt_path "$NAME")"
REL="$WORKTREE_DIR/$NAME"

git -C "$IF_ROOT" check-ignore -q "$REL" \
  || echo "⚠️  $WORKTREE_DIR is NOT git-ignored in $PROJECT_NAME — add it to .gitignore"
if_seed_ledger
git -C "$IF_ROOT" fetch "$REMOTE" "$INTEGRATION_BRANCH"
miss=0

if [ -e "$WT" ]; then
  [ -n "$REUSE" ] || if_die "$WT already exists — resume it instead of re-provisioning (or pass --reuse)"
  # --- reuse: new branch, same worktree, same ports ---------------------------------
  git -C "$WT" diff --quiet HEAD 2>/dev/null || if_die "uncommitted work in $WT — commit or stash it first"
  git -C "$WT" switch --no-track -c "$BRANCH" "$REMOTE/$INTEGRATION_BRANCH"
  BPORT="$(if_wt_port "$WT")"; [ -n "$BPORT" ] || if_die "no $PORT_VAR_BACKEND in $WT/$PORT_ENV_FILE — provision from scratch"
  X=$((BPORT - PORT_BASE_BACKEND)); FPORT=$((PORT_BASE_FRONTEND + X))
  grep -vF "\`$REL\`" "$IF_LEDGER" >"$IF_LEDGER.tmp" && mv "$IF_LEDGER.tmp" "$IF_LEDGER"
  echo "▶ reusing $WT on new branch $BRANCH (X=$X)"
else
  # --- 1. port digit ----------------------------------------------------------------
  if [ "$X" = auto ]; then
    # `|| true`: no claimed digits yet = grep exits 1, which pipefail + set -e would turn
    # into a silent abort on the very first worktree.
    used=" 0 $( { grep -oE '\| [1-9] \(' "$IF_LEDGER" || true; } | grep -oE '[1-9]' | tr '\n' ' ' || true)"
    X=""
    for x in 1 2 3 4 5 6 7 8 9; do
      case "$used" in *" $x "*) ;; *) X="$x"; break ;; esac
    done
    [ -n "$X" ] || if_die "no free port digit (1-9) left in $IF_LEDGER"
  fi
  case "$X" in [1-9]) ;; *) if_die "X must be 1-9, got '$X'" ;; esac
  BPORT=$((PORT_BASE_BACKEND + X))
  FPORT=$((PORT_BASE_FRONTEND + X))

  # --- 2. worktree ------------------------------------------------------------------
  mkdir -p "$(dirname "$WT")"
  if git -C "$IF_ROOT" show-ref --verify --quiet "refs/heads/$BRANCH"; then
    echo "▶ branch $BRANCH exists — attaching worktree to it"
    git -C "$IF_ROOT" worktree add "$WT" "$BRANCH"
  else
    git -C "$IF_ROOT" worktree add --no-track "$WT" -b "$BRANCH" "$REMOTE/$INTEGRATION_BRANCH"
  fi

  # --- 3. env files + ports ---------------------------------------------------------
  for f in "${ENV_FILES[@]}"; do
    if [ -f "$IF_ROOT/$f" ]; then
      mkdir -p "$(dirname "$WT/$f")"
      cp "$IF_ROOT/$f" "$WT/$f"
    else
      echo "⚠️  $IF_ROOT/$f missing — not copied"; miss=1
    fi
  done
  {
    echo ""
    echo "# worktree ports (IssueFlow provision.sh)"
    echo "${PORT_VAR_BACKEND}=$BPORT"
    echo "${PORT_VAR_FRONTEND}=$FPORT"
  } >>"$WT/$PORT_ENV_FILE"
fi

# --- 4. setup, hook, verify ---------------------------------------------------------
export IF_ROOT WT X BPORT FPORT BRANCH
export PORT="$BPORT" FRONTEND_PORT="$FPORT"
for cmd in "${SETUP_CMDS[@]}"; do
  echo "▶ $cmd"
  (cd "$WT" && bash -c "$cmd")
done
if [ -n "${POST_PROVISION_HOOK:-}" ]; then
  echo "▶ post-provision hook"
  (cd "$WT" && bash -c "$POST_PROVISION_HOOK")
fi
ok=1
for p in "${VERIFY_PATHS[@]}"; do
  [ -e "$WT/$p" ] || { echo "✗ missing after setup: $p"; ok=0; }
done

# --- 5. ledger + IDE ----------------------------------------------------------------
printf '| `%s` | `%s` | %s | %s (%s/%s) | Active |\n' "$REL" "$BRANCH" "$PURPOSE" "$X" "$FPORT" "$BPORT" >>"$IF_LEDGER"

ide="skipped"
if [ "$IDE_CLI" != none ] && [ -z "$REUSE" ]; then
  cli="$(command -v "$IDE_CLI" 2>/dev/null || true)"
  if [ -z "$cli" ] && [ "$IDE_CLI" = cursor ]; then   # remote/SSH sessions: cursor-server CLI
    cli="$(ls "$HOME"/.cursor-server/bin/*/bin/remote-cli/cursor 2>/dev/null | head -1 || true)"
  fi
  if [ -n "$cli" ] && "$cli" --add "$WT" 2>/dev/null; then ide="added to $IDE_CLI window"
  else ide="⚠️ $IDE_CLI --add failed — open $WT manually"; fi
fi

echo "----"
echo "worktree : $WT$([ -n "$REUSE" ] && echo ' (reused)')"
echo "branch   : $BRANCH"
echo "ports    : frontend $FPORT / backend $BPORT  (X=$X)"
echo "env files: $([ "$miss" = 0 ] && echo copied || echo '⚠️ some missing (see above)')"
echo "ide      : $ide"
echo "ledger   : row $([ -n "$REUSE" ] && echo updated || echo added) in $IF_LEDGER"
[ "$ok" = 1 ] && echo "bootstrap: ✅ ready" || { echo "bootstrap: ✗ incomplete"; exit 1; }
