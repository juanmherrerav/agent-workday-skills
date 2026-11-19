#!/usr/bin/env bash
# preview-url.sh — resolve the preview deployment URL for a branch.
#
# Prints up to two lines:
#   BRANCH_URL=<url>   stable alias that follows the branch's latest deploy (prefer in messages)
#   COMMIT_URL=<url>   deploy for one exact SHA (goes stale after a force-push)
#
# Sources, in order (each only runs if the previous ones found nothing):
#   1. PREVIEW_URL_TEMPLATE  — e.g. https://{branch_slug}.preview.example.com
#      placeholders: {branch} {branch_slug} {project}
#   2. Provider CLI — PREVIEW_PROVIDER=vercel with `vercel` (or `bunx vercel`) and VERCEL_TOKEN:
#      newest Ready deployment for the branch (PREVIEW_PROJECT, PREVIEW_SCOPE), then `inspect`
#      for the branch alias. Custom domains make the alias unpredictable; this asks the platform.
#   3. GitHub deployments API for the SHA (works for any provider that reports deployment
#      statuses back to GitHub: Vercel, Netlify, Render, …); polls up to --wait seconds.
#
# Usage: preview-url.sh <branch> [--sha SHA] [--wait SECONDS]
# Exit:  0 if any URL was found, 2 if PREVIEW_PROVIDER=none, 1 otherwise.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/profile.sh"

BRANCH=""; SHA=""; WAIT=0
while [ $# -gt 0 ]; do
  case "$1" in
    --sha) shift; SHA="$1" ;;
    --wait) shift; WAIT="$1" ;;
    *) BRANCH="$1" ;;
  esac
  shift
done
[ -n "$BRANCH" ] || if_die "usage: preview-url.sh <branch> [--sha SHA] [--wait SECONDS]"
[ "$PREVIEW_PROVIDER" = none ] && { echo "no preview deployments configured (PREVIEW_PROVIDER=none)"; exit 2; }

found=1
if [ -n "${PREVIEW_URL_TEMPLATE:-}" ]; then
  u="$PREVIEW_URL_TEMPLATE"
  u="${u//\{branch\}/$BRANCH}"
  u="${u//\{branch_slug\}/$(if_slugify "$BRANCH")}"
  u="${u//\{project\}/$PROJECT_NAME}"
  echo "BRANCH_URL=${u%/}$APP_PATH"
  found=0
fi

# --- 2. provider CLI (vercel) --------------------------------------------------------
if [ "$found" != 0 ] && [ "$PREVIEW_PROVIDER" = vercel ] && [ -n "${VERCEL_TOKEN:-}" ]; then
  vc=""
  if command -v vercel >/dev/null 2>&1; then vc="vercel"
  elif command -v bunx >/dev/null 2>&1; then vc="bunx vercel"; fi
  if [ -n "$vc" ]; then
    scope=(); [ -n "${PREVIEW_SCOPE:-}" ] && scope=(--scope "$PREVIEW_SCOPE")
    slug="$(if_slugify "$BRANCH")"
    # newest Ready deployment for this branch (metadata filter; falls back to any Ready one)
    dep="$($vc ls "$PREVIEW_PROJECT" --token "$VERCEL_TOKEN" ${scope[@]+"${scope[@]}"} \
            -m "githubCommitRef=$BRANCH" 2>/dev/null | grep -E 'Ready' | grep -oE 'https?://[^[:space:]]+' | head -1 || true)"
    if [ -n "$dep" ]; then
      insp="$($vc inspect "$dep" --token "$VERCEL_TOKEN" ${scope[@]+"${scope[@]}"} 2>/dev/null || true)"
      alias_host="$(printf '%s' "$insp" | grep -oE "[A-Za-z0-9.-]*-git-${slug}[A-Za-z0-9.-]*" | head -1 || true)"
      [ -n "$alias_host" ] || alias_host="$(printf '%s' "$insp" | grep -oE '[A-Za-z0-9.-]*-git-[A-Za-z0-9.-]*' | head -1 || true)"
      if [ -n "$alias_host" ]; then echo "BRANCH_URL=https://${alias_host}${APP_PATH}"; found=0; fi
      echo "COMMIT_URL=${dep%/}$APP_PATH"; found=0
    fi
  fi
fi

# --- 3. GitHub deployments API --------------------------------------------------------
[ -n "$SHA" ] || SHA="$(git -C "$IF_ROOT" rev-parse "$REMOTE/$BRANCH" 2>/dev/null || true)"
if [ -n "$SHA" ] && command -v gh >/dev/null; then
  repo="$(cd "$IF_ROOT" && gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null)"
  deadline=$((SECONDS + WAIT))
  while [ -n "$repo" ]; do
    id="$(gh api "repos/$repo/deployments?sha=$SHA&environment=$PREVIEW_ENVIRONMENT&per_page=5" --jq '.[0].id // empty' 2>/dev/null)"
    if [ -n "$id" ]; then
      url="$(gh api "repos/$repo/deployments/$id/statuses" --jq '[.[] | select(.state=="success")][0].environment_url // empty' 2>/dev/null)"
      if [ -n "$url" ]; then echo "COMMIT_URL=${url%/}$APP_PATH"; found=0; break; fi
    fi
    [ "$SECONDS" -ge "$deadline" ] && break
    sleep 20
  done
fi

[ "$found" = 0 ] || echo "⏳ no preview URL yet — check the PR's Deployments section"
exit "$found"
