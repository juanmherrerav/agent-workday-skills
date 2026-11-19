#!/usr/bin/env bash
# install.sh — link (default) or copy the skills into one or more agent skill directories.
#
#   ./install.sh                         Claude Code: ~/.claude/skills
#   ./install.sh --agent codex           OpenAI Codex CLI: ~/.codex/skills
#   ./install.sh --agent agents          Cross-agent standard location: ~/.agents/skills
#   ./install.sh --target DIR            any directory (Cursor, Gemini CLI, OpenCode, a project's .claude/skills, …)
#   ./install.sh --copy                  copy instead of symlink (symlinks keep `git pull` updates live)
#   ./install.sh --only BattlePlan,MeetingAnalysis
#   ./install.sh --uninstall [same flags]
#
# Existing entries that are not symlinks into this repo are never overwritten.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGETS=(); MODE=link; ONLY=""; UNINSTALL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --agent)
      case "${2:?}" in
        claude) TARGETS+=("${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills") ;;
        codex)  TARGETS+=("${CODEX_HOME:-$HOME/.codex}/skills") ;;
        agents) TARGETS+=("$HOME/.agents/skills") ;;
        *) echo "unknown agent '$2' (claude | codex | agents; use --target for others)" >&2; exit 2 ;;
      esac; shift ;;
    --target) TARGETS+=("${2:?}"); shift ;;
    --copy) MODE=copy ;;
    --only) ONLY="${2:?}"; shift ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n 2,12p "$0"; exit 0 ;;
    *) echo "unknown option '$1'" >&2; exit 2 ;;
  esac
  shift
done
[ ${#TARGETS[@]} -gt 0 ] || TARGETS=("${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills")

for target in "${TARGETS[@]}"; do
  mkdir -p "$target"
  for src in "$REPO"/skills/*/; do
    name="$(basename "$src")"
    if [ -n "$ONLY" ] && [[ ",$ONLY," != *",$name,"* ]]; then continue; fi
    dest="$target/$name"
    if [ -n "$UNINSTALL" ]; then
      if [ -L "$dest" ] && [[ "$(readlink "$dest")" == "$REPO"/* ]]; then rm "$dest"; echo "removed  $dest"
      elif [ -e "$dest" ]; then echo "kept     $dest (not a link into this repo; remove by hand)"; fi
      continue
    fi
    if [ -L "$dest" ] && [[ "$(readlink "$dest")" == "$REPO"/* ]]; then rm "$dest"
    elif [ -e "$dest" ]; then echo "skipped  $dest (exists and is not ours)"; continue; fi
    if [ "$MODE" = copy ]; then cp -R "${src%/}" "$dest"; else ln -s "${src%/}" "$dest"; fi
    echo "$MODE     $dest"
  done
done

[ -n "$UNINSTALL" ] && exit 0
cat <<EOF

Next:
  1. Make sure uv is installed (https://docs.astral.sh/uv/).
  2. If the skills are not in ~/.claude/skills, export SKILLS_HOME=<that dir> in your shell profile,
     so the workflows' commands find the tools.
  3. Run the setup for each skill you use, from your agent:
       "set up battleplan"   "set up meeting analysis"   "set up issueflow for this repo"
EOF
