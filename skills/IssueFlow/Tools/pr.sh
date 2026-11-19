#!/usr/bin/env bash
# pr.sh — the one place the workflows talk to the forge about pull requests.
#
# Today: GitHub through `gh` ($FORGE=github). A GitLab implementation adds a `glab` branch per
# verb in this file; the workflows do not change. This is the forge adapter seam.
#
# Usage:
#   pr.sh find   --head BRANCH [--base BRANCH]            → "NUMBER URL STATE"   (exit 1 if none open)
#   pr.sh create --head BRANCH --title T [--base BRANCH]  body on stdin; creates, or updates title +
#                                                           body when one is already open; prints the URL
#   pr.sh view   --head BRANCH [--json fields]
#   pr.sh close  --head BRANCH
#   pr.sh merge  --head BRANCH --squash                   (fast-forward landing is a git push in Merge)
#   pr.sh list   [--base BRANCH]                          → JSON number,title,headRefName,url
#
# --base defaults to $INTEGRATION_BRANCH. If stdin is empty on create and the repo has
# .github/pull_request_template.md, that template becomes the body so reviewers see the
# sections they expect.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/profile.sh"

VERB="${1:-}"; shift || true
HEAD=""; BASE="$INTEGRATION_BRANCH"; TITLE=""; JSON="number,url,state,title,headRefName"; SQUASH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --head)  shift; HEAD="$1" ;;
    --base)  shift; BASE="$1" ;;
    --title) shift; TITLE="$1" ;;
    --json)  shift; JSON="$1" ;;
    --squash) SQUASH=1 ;;
    *) if_die "pr.sh: unknown argument '$1'" ;;
  esac
  shift
done

[ "$FORGE" = github ] || if_die "FORGE=$FORGE is not implemented in pr.sh (github only). Add its verbs here."
command -v gh >/dev/null 2>&1 || if_die "gh CLI not found (gh auth login)"
need_head() { [ -n "$HEAD" ] || if_die "pr.sh $VERB needs --head BRANCH"; }
find_pr() {
  (cd "$IF_ROOT" && gh pr list --head "$HEAD" --base "$BASE" --state open --json number,url,state \
     --jq '.[0] | select(.) | "\(.number) \(.url) \(.state)"' 2>/dev/null)
}

case "$VERB" in
  find)
    need_head; out="$(find_pr)"; [ -n "$out" ] || exit 1; echo "$out" ;;
  create)
    need_head; [ -n "$TITLE" ] || if_die "pr.sh create needs --title"
    body=""; [ -t 0 ] || body="$(cat)"
    if [ -z "$body" ] && [ -f "$IF_ROOT/.github/pull_request_template.md" ]; then
      body="$(cat "$IF_ROOT/.github/pull_request_template.md")"
    fi
    existing="$(find_pr)"
    if [ -n "$existing" ]; then
      n="${existing%% *}"; url="$(printf '%s' "$existing" | cut -d' ' -f2)"
      (cd "$IF_ROOT" && gh pr edit "$n" --title "$TITLE" --body "$body" >/dev/null) || exit 1
      echo "$url"
    else
      (cd "$IF_ROOT" && gh pr create --head "$HEAD" --base "$BASE" --title "$TITLE" --body "$body")
    fi ;;
  view)  need_head; (cd "$IF_ROOT" && gh pr view "$HEAD" --json "$JSON") ;;
  close) need_head; (cd "$IF_ROOT" && gh pr close "$HEAD") ;;
  merge)
    need_head; [ -n "$SQUASH" ] || if_die "pr.sh merge supports --squash only; ff-only landing is 'git push' in the Merge workflow"
    (cd "$IF_ROOT" && gh pr merge "$HEAD" --squash) ;;
  list)  (cd "$IF_ROOT" && gh pr list --base "$BASE" --state open --json number,title,headRefName,url) ;;
  *) if_die "usage: pr.sh find|create|view|close|merge|list [--head B] [--base B] [--title T] [--json F] [--squash]" ;;
esac
