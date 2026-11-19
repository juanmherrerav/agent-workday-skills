#!/usr/bin/env bash
# install-quality-tools.sh — install the tools listed in tools.tsv for the detected (or given) languages.
#
# Usage: install-quality-tools.sh [--dry-run] [js|python|yaml ...]
#   no language args → detect: package.json → js; pyproject.toml|requirements.txt|*.py → python; *.yaml|*.yml → yaml
#   --dry-run        → print the install commands and exit 0
#
# Channels: js → devDependencies with the repo package manager (lockfile → npm/pnpm/bun);
#           python and yaml → `uv pip install` when uv exists, else `python3 -m pip install`.
# An install cell may override its language channel with a `npm:` or `pip:` prefix. `-` installs nothing.
# Run from the target repo root. Override the manifest with QUALITY_MANIFEST=/path/tools.tsv.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="${QUALITY_MANIFEST:-$HERE/tools.tsv}"
DRY=0
LANGS=()
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    js|python|yaml) LANGS+=("$a") ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
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

# --- channels --------------------------------------------------------------
PM=npm
[ -f pnpm-lock.yaml ] && PM=pnpm
{ [ -f bun.lockb ] || [ -f bun.lock ]; } && PM=bun
case "$PM" in
  npm)  NPM_INSTALL="npm install -D";  NPX="npx --no" ;;
  pnpm) NPM_INSTALL="pnpm add -D";     NPX="pnpm exec" ;;
  bun)  NPM_INSTALL="bun add -d";      NPX="bunx" ;;
esac
if command -v uv >/dev/null 2>&1; then PIP_INSTALL="uv pip install"; else PIP_INSTALL="python3 -m pip install"; fi

# --- collect packages from the manifest ------------------------------------
NPM_PKGS=()
PIP_PKGS=()
add_unique() { # array-name pkg...
  local -n arr="$1"; shift
  local p
  for p in "$@"; do [[ " ${arr[*]:-} " == *" $p "* ]] || arr+=("$p"); done
}
while IFS=$'\t' read -r lang _cat _prio _tool install _run _notes; do
  [ -z "$lang" ] && continue
  [[ "$lang" == language || "$lang" == \#* ]] && continue
  has_lang "$lang" || continue
  [ "$install" = "-" ] && continue
  case "$install" in
    npm:*) add_unique NPM_PKGS ${install#npm:} ;;
    pip:*) add_unique PIP_PKGS ${install#pip:} ;;
    *) if [ "$lang" = js ]; then add_unique NPM_PKGS $install; else add_unique PIP_PKGS $install; fi ;;
  esac
done < "$MANIFEST"

# --- plan ------------------------------------------------------------------
echo "languages: ${LANGS[*]}"
echo "package manager: $PM   python installer: $PIP_INSTALL"
CMDS=()
if [ ${#NPM_PKGS[@]} -gt 0 ]; then
  if [ -f package.json ]; then
    CMDS+=("$NPM_INSTALL ${NPM_PKGS[*]}")
  else
    echo "warning: no package.json, skipping npm packages (${NPM_PKGS[*]}). Install globally if needed: npm install -g ${NPM_PKGS[*]}" >&2
  fi
fi
if [ ${#PIP_PKGS[@]} -gt 0 ]; then
  if [[ "$PIP_INSTALL" == uv* ]] && [ -z "${VIRTUAL_ENV:-}" ] && [ ! -d .venv ]; then
    echo "warning: uv found but no active venv or ./.venv; run 'uv venv' first or export VIRTUAL_ENV" >&2
  fi
  CMDS+=("$PIP_INSTALL ${PIP_PKGS[*]}")
fi
[ ${#CMDS[@]} -gt 0 ] || { echo "nothing to install for: ${LANGS[*]}"; exit 0; }

# --- execute ---------------------------------------------------------------
rc=0
for c in "${CMDS[@]}"; do
  echo "+ $c"
  [ "$DRY" = 1 ] && continue
  bash -c "$c" || { echo "install FAILED: $c" >&2; rc=1; }
done
if [ "$DRY" = 1 ]; then
  echo "(dry run: nothing installed)"
  exit 0
fi
# secretlint refuses to run without a config; create the recommended one once.
if has_lang js && [ -f package.json ] && [ ! -f .secretlintrc.json ] && [ -x node_modules/.bin/secretlint ]; then
  echo "+ $NPX secretlint --init"
  $NPX secretlint --init || echo "warning: secretlint --init failed; create .secretlintrc.json by hand" >&2
fi
echo "done. Verify with: $NPX <tool> --version (js) / <tool> --version (python, yaml)"
exit $rc
