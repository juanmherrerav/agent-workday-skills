# Instructions for agents working on this repository

This repo ships skills (`skills/<Name>/SKILL.md` plus `Workflows/`, `Tools/`, `Templates/`).

- **No personal or company data, ever.** No names of real people, employers, clients, products,
  hostnames, account IDs, spreadsheet IDs or local paths. Examples use `ABC-123`, `my-app`,
  `example.com`, `Alex`. User specifics belong in the user's config
  (`~/.config/agent-skills/<Skill>/`) or the repo profile (`.claude/workflow-profile.sh`).
- **Tools are deterministic and print JSON or labelled lines.** Python tools are
  `uv run --script` files with PEP 723 inline dependencies; bash tools pass `bash -n` and use
  `set -euo pipefail` (or `-uo` where every check must run).
- **Paths to other skills** go through `${SKILLS_HOME:-$HOME/.claude/skills}`; a tool finds its
  own skill directory from `BASH_SOURCE` / `__file__`.
- **Every write has a dry run, every gate reports SKIPPED rather than passing silently.**
- Run before committing:

  ```bash
  (cd skills/BattlePlan && uv run --with pytest --with openpyxl pytest -q tests/)
  for f in skills/*/Tools/*.sh; do bash -n "$f"; done
  ```
