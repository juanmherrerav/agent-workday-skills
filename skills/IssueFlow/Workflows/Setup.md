# Setup — write the repo profile

Run this when `bash "$IF/profile.sh"` reports no profile. The output is one committed file:
`<repo>/.claude/workflow-profile.sh`.

**Derive values from the repo, never invent them.** Every command in the profile must be one
the repo already runs somewhere.

This table is the single detection table. RepoScaffold points here instead of keeping its own.

| Profile key | Where to find the truth |
| --- | --- |
| `ISSUE_PATTERN` (prefix is derived) | `git log --oneline -50`, recent PR titles, branch names |
| `TRACKER` (an IssueSync adapter name: `jira`, `none`, …), `FORGE` | `JIRA_*` or other tracker vars in `.env.example`; `git remote -v` (github.com → `gh`) |
| `INTEGRATION_BRANCH`, `PRODUCTION_BRANCH` | `gh repo view --json defaultBranchRef`, branch list, CI triggers |
| `BRANCH_TEMPLATE` | `git branch -r` naming for existing issue branches |
| `ENV_FILES`, `ENV_REQUIRED_VARS`, `ENV_OPTIONAL_VARS` | `.gitignore` + `*.example` files: which ignored files the app needs, and which vars they list |
| `SETUP_CMDS`, `VERIFY_PATHS` | README / Makefile / `package.json` / `pyproject.toml` install steps |
| `UNIT_CMD`, `E2E_CMD` | the commands CI runs (`.github/workflows/*.yml`), not a guess |
| `E2E_SERVER_ENV`, `E2E_RECORD_ENV`, `FIXTURES_DIR` | the env CI writes before starting the app; the mode switch the app reads; where recorded fixtures live |
| `PREFLIGHT_CHECKS`, `PREFLIGHT_FIX_CMDS` | the CI lint/type job, **1:1** and in the same order |
| `SERVE_CMD`, `HEALTH_PATH`, `APP_PATH` | the dev-server script and the health route in code |
| `PREVIEW_PROVIDER`, `PREVIEW_URL_TEMPLATE`, `PREVIEW_PROJECT`, `PREVIEW_SCOPE`, `PREVIEW_*_ID` | an existing PR's Deployments section / bot comment; `vercel.json`, `netlify.toml`; the provider dashboard for IDs |
| `STAKEHOLDER*`, `REVIEW_CHANNEL`, `IDE_*` | ask the user; these are people and process facts |

Steps:

1. `cp "${SKILLS_HOME:-$HOME/.claude/skills}/IssueFlow/Templates/workflow-profile.sh" .claude/workflow-profile.sh`
2. Fill it from the table. Delete keys that don't apply rather than leaving template values.
3. Make sure `.claude/local/` (worktrees, ledger, tracker cache) is in `.gitignore`.
4. Prove each command: run `UNIT_CMD`, each `PREFLIGHT_CHECKS` command, and `SERVE_CMD` +
   `curl` on the health path in the main checkout. A command that fails here will fail in
   every issue.
5. Show the user `bash "$IF/profile.sh"` and the diff. Commit only when they agree.

Anything specific to the product that a plain value can't express (rewriting a frontend env
file to point at the worktree backend, seeding a local DB) goes in `POST_PROVISION_HOOK`,
not in the skill.
