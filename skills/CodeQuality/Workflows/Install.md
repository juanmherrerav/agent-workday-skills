# Install — put the manifest's tools in place

Installs, for the languages present in the repo, every tool listed in `Tools/tools.tsv`. No tool
is named in this file on purpose: the manifest is the only list. Run from the repo root.

```bash
CQ="${SKILLS_HOME:-$HOME/.claude/skills}/CodeQuality/Tools"
```

## Step 1 — Detect and preview

```bash
bash "$CQ/install-quality-tools.sh" --dry-run           # detected languages + the exact commands
bash "$CQ/install-quality-tools.sh" --dry-run js python  # or force the languages
```

Detection: `package.json` → js; `pyproject.toml`, `requirements.txt` or any `*.py` → python;
any `*.yaml`/`*.yml` → yaml. The package manager comes from the lockfile (npm, pnpm, bun). Python
and yaml tools go through `uv pip install` when `uv` exists, else `python3 -m pip install`.

Show the user the dry-run output and confirm before installing. Point out anything that will
change the repo: js tools land in `devDependencies` (lockfile diff), and the script creates
`.secretlintrc.json` when it is missing.

Skip a language when its tools would be noise, for example `yaml` in a repo whose only YAML is
CI config and not infrastructure (the IaC scanner is a heavy install).

## Step 2 — Install

```bash
bash "$CQ/install-quality-tools.sh" [js python yaml]
```

Python without a virtual environment: the script warns. Create one first (`uv venv` or
`python3 -m venv .venv`, then activate) so the tools do not land in the system interpreter.

## Step 3 — Repo-side configuration the tools need

Some tools refuse to run without a config file. Check, and create the minimum when absent:

| Tool (if in the manifest for this repo) | Needs | When absent |
| --- | --- | --- |
| eslint | an eslint config at the root | ask before adding one; a repo without eslint config may prefer the fast linter alone |
| tsc | `tsconfig.json` | pure-JS repos: leave it; the baseline reports the row FAILED and the Loop ignores it |
| secretlint | `.secretlintrc.json` | created by the install script via `--init` |
| yamllint, prettier, ruff, mypy | nothing | defaults apply; repo configs are honoured when present |

Add `reports/` to `.gitignore` if it is not there: both scan and loop write under `reports/codequality/`.

## Step 4 — Verify

```bash
bash "$CQ/run-quality-baseline.sh" --dry-run     # every resolved command, nothing runs
```

Then check one binary per channel: `npx --no <tool> --version` (or `pnpm exec` / `bunx`) for js,
`<tool> --version` for python and yaml. The real check is the first Scan: any row still
MISSING in `summary.md` did not install.

## Step 5 — Report

```
Quality tools installed
Languages: <js python yaml>        Package manager: <npm>   Python: <uv | pip>
Installed: <n> js devDependencies, <n> python packages
Config created: <.secretlintrc.json | none>
Skipped: <language or tool, reason>
Next: Scan (part A) to get the first summary.md
```
