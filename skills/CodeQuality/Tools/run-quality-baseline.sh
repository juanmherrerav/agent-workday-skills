#!/usr/bin/env bash
# run-quality-baseline.sh — run every tool in tools.tsv for the detected (or given) languages into one report dir.
#
# Usage: run-quality-baseline.sh [--dry-run] [js|python|yaml ...]
#   no language args → detect: package.json → js; pyproject.toml|requirements.txt|*.py → python; *.yaml|*.yml → yaml
#   --dry-run        → print the resolved commands and the report path, run nothing, exit 0
#
# Output: reports/codequality/<YYYY-MM-DD>-<HHMMSS>/ with one file per tool plus summary.md
# (per-tool status OK / FAILED / MISSING / SKIPPED, issue counts, P0/P1/P2 totals). Prints the report path last.
# Tokens substituted in the manifest `run` cell: $OUT (report dir), $SRC (source dirs, from QUALITY_SRC_DIRS,
# default "src" if it exists else "."), $PM (npm|pnpm|bun from the lockfile), $NPX (npx --no | pnpm exec | bunx).
# One tool failing never aborts the run. Run from the target repo root; add reports/ to .gitignore.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="${QUALITY_MANIFEST:-$HERE/tools.tsv}"
DRY=0
LANGS=()
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    js|python|yaml) LANGS+=("$a") ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown argument: $a (expected --dry-run, js, python, yaml)" >&2; exit 2 ;;
  esac
done
[ -r "$MANIFEST" ] || { echo "manifest not found: $MANIFEST" >&2; exit 2; }

# --- detection -------------------------------------------------------------
find_any() { find . -maxdepth 3 -not -path '*/node_modules/*' -not -path '*/.venv/*' -not -path '*/.git/*' "$@" -print -quit 2>/dev/null | grep -q .; }
detect_langs() {
  [ -f package.json ] && echo js
  { [ -f pyproject.toml ] || [ -f requirements.txt ] || find_any -name '*.py'; } && echo python
  find_any \( -name '*.yaml' -o -name '*.yml' \) && echo yaml
  return 0
}
if [ ${#LANGS[@]} -eq 0 ]; then
  mapfile -t LANGS < <(detect_langs)
fi
[ ${#LANGS[@]} -gt 0 ] || { echo "no supported language detected (js/python/yaml); pass one explicitly" >&2; exit 1; }
has_lang() { [[ " ${LANGS[*]} " == *" $1 "* ]]; }

# --- tokens ----------------------------------------------------------------
PM=npm
[ -f pnpm-lock.yaml ] && PM=pnpm
{ [ -f bun.lockb ] || [ -f bun.lock ]; } && PM=bun
case "$PM" in npm) NPX="npx --no" ;; pnpm) NPX="pnpm exec" ;; bun) NPX="bunx" ;; esac
if [ -n "${QUALITY_SRC_DIRS:-}" ]; then SRC="$QUALITY_SRC_DIRS"; elif [ -d src ]; then SRC="src"; else SRC="."; fi
OUT="reports/codequality/$(date +%Y-%m-%d)-$(date +%H%M%S)"
export OUT SRC PM NPX

resolve() { sed -e "s|\$OUT|$OUT|g" -e "s|\$SRC|$SRC|g" -e "s|\$NPX|$NPX|g" -e "s|\$PM|$PM|g" <<<"$1"; }

# Is the tool's binary present? Avoids npx trying to download anything.
available() { # run-cell
  local run="$1" first
  if [[ "$run" == '$NPX '* ]]; then
    first="${run#\$NPX }"; first="${first%% *}"
    [ -x "node_modules/.bin/$first" ]
  elif [[ "$run" == '$PM '* ]]; then
    command -v "$PM" >/dev/null 2>&1
  else
    first="${run%% *}"
    command -v "$first" >/dev/null 2>&1
  fi
}

# Did the command leave any output behind? (linters exit non-zero when they find issues, so exit code alone is not failure)
produced_output() { # resolved-run
  local p
  p="$(grep -oE "$OUT/[^ \"']+" <<<"$1" | head -1)"
  [ -n "$p" ] || return 0
  if [ -d "$p" ]; then [ -n "$(ls -A "$p" 2>/dev/null)" ]; else [ -s "$p" ]; fi
}

# Issue count per tool, when the output is parseable. Prints "?" otherwise.
count_issues() { # tool
  local n
  n="$(count_raw "$1" 2>/dev/null | head -1)"
  if [[ "$n" =~ ^[0-9]+$ ]]; then echo "$n"; else echo "?"; fi
}
count_raw() { # tool  (grep -c prints 0 and exits 1 on empty input; count_issues only looks at the text)
  local f
  case "$1" in
    secretlint) f="$OUT/secretlint.json"; jq -r '[.[].messages[]] | length' "$f" ;;
    npm-audit)  f="$OUT/npm-audit.json";  jq -r '.metadata.vulnerabilities | select(. != null) | (.critical // 0) + (.high // 0) + (.moderate // 0) + (.low // 0)' "$f" ;;
    oxlint)     f="$OUT/oxlint.json";     jq -r '.diagnostics | length' "$f" ;;
    eslint)     f="$OUT/eslint.json";     jq -r '[.[].messages[]] | length' "$f" ;;
    tsc)        grep -c 'error TS' "$OUT/tsc.txt" ;;
    type-coverage) grep -cE '^[^ ]+:[0-9]+:[0-9]+' "$OUT/type-coverage.txt" ;;
    madge)      jq -r 'length' "$OUT/madge-circular.json" ;;
    knip)       jq -r '(.files | length) + ([.issues[]? | to_entries[] | select(.value | type == "array") | .value | length] | add // 0)' "$OUT/knip.json" ;;
    jscpd)      jq -r '.statistics.total.clones' "$OUT/jscpd/jscpd-report.json" ;;
    lizard)     grep -c . "$OUT/lizard.txt" ;;
    prettier)   grep -cE '^\[warn\] [^ ]+$' "$OUT/prettier.txt" "$OUT/prettier-yaml.txt" 2>/dev/null | awk -F: '{s+=$NF} END {print s+0}' ;;
    bandit)     jq -r '.results | length' "$OUT/bandit.json" ;;
    pip-audit)  jq -r '[.dependencies[].vulns[]] | length' "$OUT/pip-audit.json" ;;
    ruff)       jq -r 'length' "$OUT/ruff.json" ;;
    mypy)       grep -c '"severity": *"error"' "$OUT/mypy.jsonl" ;;
    vulture)    grep -c . "$OUT/vulture.txt" ;;
    pylint)     jq -r '.messages | length' "$OUT/pylint-dup.json" ;;
    ruff-format) grep -c 'Would reformat' "$OUT/ruff-format.txt" ;;
    checkov)    jq -r 'if type == "array" then [.[].summary.failed] | add else .summary.failed end' "$OUT/checkov.json" ;;
    yamllint)   grep -c . "$OUT/yamllint.txt" ;;
    *) echo "?" ;;
  esac
}

# --- run -------------------------------------------------------------------
echo "languages: ${LANGS[*]}   SRC=$SRC   PM=$PM   report: $OUT"
[ "$DRY" = 1 ] || mkdir -p "$OUT"
declare -A P=( [P0]=0 [P1]=0 [P2]=0 )
declare -a ROWS=() FAILED=()
SEEN_RUNS=" "
while IFS=$'\t' read -r lang cat prio tool _install run _notes; do
  [ -z "$lang" ] && continue
  [[ "$lang" == language || "$lang" == \#* ]] && continue
  has_lang "$lang" || continue
  if [ "$run" = "-" ]; then
    ROWS+=("| $tool | $lang | $cat | $prio | SKIPPED | - | not run by the baseline |")
    continue
  fi
  if [[ "$SEEN_RUNS" == *" $run "* ]]; then continue; fi   # identical command listed under two languages
  SEEN_RUNS="$SEEN_RUNS$run "
  resolved="$(resolve "$run")"
  if [ "$DRY" = 1 ]; then
    echo "+ [$prio $tool] $resolved"
    continue
  fi
  if ! available "$run"; then
    echo "- [$prio $tool] MISSING (not installed)"
    ROWS+=("| $tool | $lang | $cat | $prio | MISSING | - | run Install |")
    continue
  fi
  echo "+ [$prio $tool] $resolved"
  bash -c "$resolved" 2>"$OUT/$tool.stderr"; rc=$?
  [ -s "$OUT/$tool.stderr" ] || rm -f "$OUT/$tool.stderr"
  if [ $rc -eq 127 ] || [ $rc -eq 126 ] || { [ $rc -ne 0 ] && ! produced_output "$resolved"; }; then
    echo "  FAILED (exit $rc)"
    FAILED+=("$tool")
    ROWS+=("| $tool | $lang | $cat | $prio | FAILED | - | exit $rc, see $tool.stderr |")
    continue
  fi
  n="$(count_issues "$tool")"
  if [ $rc -ne 0 ] && [ "$n" = "?" ]; then   # non-zero exit and nothing we can read as findings = the tool itself failed
    echo "  FAILED (exit $rc, output not parseable)"
    FAILED+=("$tool")
    ROWS+=("| $tool | $lang | $cat | $prio | FAILED | - | exit $rc, see ${tool}.stderr and the output file |")
    continue
  fi
  [[ "$n" =~ ^[0-9]+$ ]] && P[$prio]=$(( ${P[$prio]} + n ))
  outfile="$(grep -oE "$OUT/[^ \"']+" <<<"$resolved" | head -1)"
  ROWS+=("| $tool | $lang | $cat | $prio | OK | $n | ${outfile#$OUT/} |")
  echo "  OK — issues: $n"
done < "$MANIFEST"

if [ "$DRY" = 1 ]; then
  echo "(dry run: nothing executed, no report written)"
  exit 0
fi

# --- summary ---------------------------------------------------------------
{
  echo "# Quality baseline — $(date +%Y-%m-%d\ %H:%M:%S)"
  echo
  echo "- Languages: ${LANGS[*]}"
  echo "- Source dirs: $SRC"
  echo "- Package manager: $PM"
  echo "- Manifest: $MANIFEST"
  echo
  echo "## Per tool"
  echo
  echo "| Tool | Lang | Category | Priority | Status | Issues | Output |"
  echo "| --- | --- | --- | --- | --- | --- | --- |"
  printf '%s\n' "${ROWS[@]}"
  echo
  echo "## Issues by priority (parsed counts only; \"?\" rows are not included)"
  echo
  echo "| Priority | Meaning | Issues |"
  echo "| --- | --- | --- |"
  echo "| P0 | security | ${P[P0]} |"
  echo "| P1 | correctness | ${P[P1]} |"
  echo "| P2 | maintainability | ${P[P2]} |"
  echo
  if [ ${#FAILED[@]} -gt 0 ]; then
    echo "## Failed"
    echo
    for t in "${FAILED[@]}"; do echo "- $t: FAILED"; done
    echo
  fi
  echo "Next: Loop workflow in tool mode selects the highest P0 → P1 → P2 finding from this file."
} > "$OUT/summary.md"

echo
echo "P0=${P[P0]} P1=${P[P1]} P2=${P[P2]}   failed: ${#FAILED[@]}"
echo "$OUT"
