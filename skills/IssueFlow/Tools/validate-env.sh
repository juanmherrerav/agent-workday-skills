#!/usr/bin/env bash
# validate-env.sh — check the profile's ENV_REQUIRED_VARS / ENV_OPTIONAL_VARS for a worktree.
#
# A value is looked up in the process environment first, then in the profile's ENV_FILES
# (later files win, last definition in a file wins). Files are parsed, never sourced, so a
# hostile or broken env file cannot run code here.
#
# Placeholder values (ENV_PLACEHOLDER_VALUES, e.g. "test-key") are what CI writes so fixture
# mode can run without credentials. They count as present in development and as missing with
# --production.
#
# Usage: validate-env.sh [--production] [worktree-dir]
# Exit:  1 if a required var is missing (or a placeholder with --production).
#        "ENV: SKIPPED" (exit 0) when the profile lists no vars — report it as SKIPPED.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/profile.sh"

PROD=0; WT="$PWD"
for a in "$@"; do
  case "$a" in --production) PROD=1 ;; *) WT="$a" ;; esac
done
WT="$(if_resolve_wt "$WT")" || exit 1

if [ "${#ENV_REQUIRED_VARS[@]}" -eq 0 ] && [ "${#ENV_OPTIONAL_VARS[@]}" -eq 0 ]; then
  echo "ENV: SKIPPED — no ENV_REQUIRED_VARS / ENV_OPTIONAL_VARS in $IF_PROFILE"
  exit 0
fi

file_val() {   # file_val VAR — value from ENV_FILES, later files win
  local i f line v
  for ((i = ${#ENV_FILES[@]} - 1; i >= 0; i--)); do
    f="$WT/${ENV_FILES[$i]}"; [ -f "$f" ] || continue
    line="$(grep -E "^(export )?$1=" "$f" 2>/dev/null | tail -1)"
    if [ -n "$line" ]; then
      v="${line#*=}"; v="${v#\"}"; v="${v%\"}"; v="${v#\'}"; v="${v%\'}"
      printf '%s' "$v"; return 0
    fi
  done
  return 1
}
val() { if [ -n "${!1:-}" ]; then printf '%s' "${!1}"; else file_val "$1" || true; fi; }
is_placeholder() { local x; for x in "${ENV_PLACEHOLDER_VALUES[@]}"; do [ "$1" = "$x" ] && return 0; done; return 1; }

echo "══ env check ($([ "$PROD" = 1 ] && echo production || echo development)) — $WT ═══"
fail=0
for var in "${ENV_REQUIRED_VARS[@]}"; do
  v="$(val "$var")"
  if [ -z "$v" ]; then
    echo "  ✗ $var (required, missing)"; fail=1
  elif is_placeholder "$v"; then
    if [ "$PROD" = 1 ]; then echo "  ✗ $var (placeholder '$v' is not allowed in production)"; fail=1
    else echo "  ⚠ $var (placeholder '$v' — fixture mode only)"; fi
  else
    echo "  ✓ $var"
  fi
done
for var in "${ENV_OPTIONAL_VARS[@]}"; do
  v="$(val "$var")"
  [ -z "$v" ] && echo "  ○ $var (optional, unset)" || echo "  ✓ $var"
done
echo "═══════════════════════════════════════════════════════════════"
if [ "$fail" = 0 ]; then
  echo "ENV: PASS"
else
  echo "ENV: FAIL — set the vars above in ${ENV_FILES[*]:-the environment} (see .env.example)"
fi
exit "$fail"
