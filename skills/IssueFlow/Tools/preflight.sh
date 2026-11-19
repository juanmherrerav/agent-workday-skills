#!/usr/bin/env bash
# preflight.sh — run the SAME quality gate CI runs, locally, before pushing.
#
# PREFLIGHT_CHECKS in the profile must mirror the repo's CI lint/type job 1:1 so that
# "green locally" means "green in CI". Change both in the same commit.
# Every check runs even after a failure, so one pass reports every gap.
#
# Usage: preflight.sh [--fix] [worktree-dir]
#   --fix  run PREFLIGHT_FIX_CMDS (formatters, lint --fix) first, then re-check
# Exit:  non-zero if any mirrored check would fail. "PREFLIGHT: SKIPPED" when none defined.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/profile.sh"

FIX=0; WT="$PWD"
for arg in "$@"; do
  case "$arg" in --fix) FIX=1 ;; *) WT="$arg" ;; esac
done
WT="$(if_resolve_wt "$WT")" || exit 1
cd "$WT"

if [ "${#PREFLIGHT_CHECKS[@]}" -eq 0 ]; then
  echo "PREFLIGHT: SKIPPED — no PREFLIGHT_CHECKS in $IF_PROFILE"
  exit 0
fi

if [ "$FIX" = 1 ]; then
  echo "── auto-fixing ──────────────────────────────────────────────"
  for cmd in "${PREFLIGHT_FIX_CMDS[@]}"; do
    echo "▶ $cmd"; bash -c "$cmd" || true
  done
fi

echo "══ CI parity ════════════════════════════════════════════════"
fail=0
for entry in "${PREFLIGHT_CHECKS[@]}"; do
  label="${entry%%::*}"; cmd="${entry#*::}"
  [ "$label" = "$entry" ] && label="$cmd"
  echo "▶ $label"
  if bash -c "$cmd"; then echo "  ✓ $label"; else echo "  ✗ $label — CI would FAIL here"; fail=1; fi
done
echo "═════════════════════════════════════════════════════════════"
if [ "$fail" = 0 ]; then
  echo "PREFLIGHT: PASS — safe to push"
else
  echo "PREFLIGHT: FAIL — push would turn CI red. Re-run with --fix, commit the result, fix the rest."
fi
exit "$fail"
