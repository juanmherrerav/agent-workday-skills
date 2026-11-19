# workflow-profile.sh — per-repo profile for the IssueFlow and ProductionDeployment skills.
#
# Copy to <repo>/.claude/workflow-profile.sh and fill in. It is a bash file SOURCED by the
# skill tools, so plain assignments and arrays only — no side effects.
# Commit it: it holds shared conventions, not secrets. Every key is optional unless marked
# REQUIRED; the default is shown in the comment.

# ── Identity ───────────────────────────────────────────────────────────────────────────
PROJECT_NAME="my-app"                         # default: repo dir name
ISSUE_PATTERN='^ABC-[0-9]+$'                 # REQUIRED-ish: keys outside this are rejected
# ISSUE_PREFIX is derived from the pattern (ABC). Set it only when the pattern has no literal prefix.
TRACKER="jira"                                # an IssueSync adapter directory: jira | none | <yours>; empty = auto-detect
FORGE="github"                                # github (gh). Other forges: add their verbs to pr.sh

# ── Branching ──────────────────────────────────────────────────────────────────────────
REMOTE="origin"
INTEGRATION_BRANCH="development"              # issues merge here       (default: main)
PRODUCTION_BRANCH="main"                      # releases promote here    (default: main)
BRANCH_TEMPLATE='{KEY}'                       # {KEY} {key} {slug} → e.g. 'feature/{key}-{slug}'
MERGE_STRATEGY="ff-only"                      # ff-only | squash   (how Merge lands the branch)

# ── Worktrees ──────────────────────────────────────────────────────────────────────────
WORKTREE_DIR=".claude/local/worktrees"        # must be git-ignored
LEDGER_FILE=".claude/local/worktree-registry.md"
# git-ignored files copied from the main checkout into each worktree (secrets, local config)
ENV_FILES=(".env" ".env.local")
# Each worktree claims a digit X (1-9): backend = PORT_BASE_BACKEND+X, frontend = …FRONTEND+X.
# The main checkout is X=0, so parallel issues never collide.
PORT_BASE_BACKEND=8000
PORT_BASE_FRONTEND=3000
PORT_ENV_FILE=".env.local"                    # where the worktree's ports get appended
PORT_VAR_BACKEND="PORT"
PORT_VAR_FRONTEND="FRONTEND_PORT"
# Run in the new worktree, in order. PORT / FRONTEND_PORT / WT / X are exported.
SETUP_CMDS=(
  "uv sync"
  "npm install"
)
# Optional product-specific tweak after setup (same env). e.g. point a frontend at the
# worktree's backend:  sed -i "s|^API_URL=.*|API_URL=http://127.0.0.1:$PORT|" web/.env.local
POST_PROVISION_HOOK=""
# Paths (relative to the worktree) that must exist after setup, or provisioning fails
VERIFY_PATHS=(".venv/bin/python" "node_modules")

# ── Env validation (validate-env.sh) ───────────────────────────────────────────────────
# Looked up in the process env, then ENV_FILES (later wins). Empty lists → ENV gate SKIPPED.
ENV_REQUIRED_VARS=("OPENAI_API_KEY" "DATABASE_URL")
ENV_OPTIONAL_VARS=("LOG_LEVEL")
# Values CI writes so fixture mode boots without credentials; rejected with --production.
ENV_PLACEHOLDER_VALUES=("test-key" "your-key-here")

# ── Gates ──────────────────────────────────────────────────────────────────────────────
UNIT_CMD="uv run pytest tests/ -q"            # empty → unit gate reported SKIPPED
# Full end-to-end suite; runs against a fresh server (SERVE_CMD) on the worktree port.
# PORT and BASE_URL are exported. Empty → e2e gate reported SKIPPED.
E2E_CMD="npm --prefix tests/e2e run test:e2e"
E2E_SERVER_ENV=("ENABLE_AUTH=false")          # extra env for the e2e server only
# Fixture recording (e2e.sh --record): the server must save upstream responses when it sees
# E2E_RECORD_ENV. E2E_RECORD_CMD defaults to E2E_CMD. FIXTURES_DIR is counted + committed.
E2E_RECORD_ENV=("ENABLE_AUTH=false" "E2E_API_MODE=record")
E2E_RECORD_CMD=""
FIXTURES_DIR="tests/fixtures"
# Mirror your CI lint/type job 1:1 — "label::command". Keep in lock-step with CI.
PREFLIGHT_CHECKS=(
  "ruff check::uv run ruff check ."
  "ruff format::uv run ruff format --check ."
  "mypy::uv run mypy ."
  "eslint::npm run lint"
  "prettier::npm run format:check"
)
PREFLIGHT_FIX_CMDS=(
  "uv run ruff format ."
  "uv run ruff check --fix ."
  "npm run lint -- --fix"
  "npm run format"
)

# ── App server (developer validation + e2e) ──────────────────────────────────────────
# Must bind to $PORT. Empty → no local launch step.
SERVE_CMD='uv run uvicorn app.main:app --host 127.0.0.1 --port "$PORT"'
HEALTH_PATH="/health"                         # polled until 2xx            (default: /)
APP_PATH="/"                                  # appended to URLs for humans  (default: /)
SERVE_TIMEOUT=60

# ── Preview deployments + review ───────────────────────────────────────────────────────
PREVIEW_PROVIDER="github"                     # github (deployments API, any host) | vercel | netlify | none
PREVIEW_ENVIRONMENT="Preview"                 # GitHub deployment environment name
# Stable per-branch alias. {branch} {branch_slug} {project}. Empty → ask the provider CLI, then
# the GitHub deployments API.
PREVIEW_URL_TEMPLATE='https://{branch_slug}.preview.example.com'
# Provider identity, declared ONCE here and used by preview-url.sh (CLI source) and by
# ProductionDeployment Phase 3 (env pulls + API metadata). Token comes from $VERCEL_TOKEN
# (team-scoped for SSO teams). Not secrets, but org-specific: commit them, never put them in a skill.
PREVIEW_PROJECT=""                            # platform project name  (default: PROJECT_NAME)
PREVIEW_SCOPE=""                              # team / scope slug, e.g. "myteam"
PREVIEW_TEAM_ID=""                            # e.g. team_xxx   (API metadata checks; empty → that tier SKIPPED)
PREVIEW_PROJECT_ID=""                         # e.g. prj_xxx
STAKEHOLDER_GATE=true                         # false → developer approval merges directly
STAKEHOLDER="the product owner"               # who approves; used in messages + approval phrases
REVIEW_CHANNEL="Slack"                        # Teams | Slack | none — where review messages go

# ── IDE ────────────────────────────────────────────────────────────────────────────────
IDE_CLI="none"                                # cursor | code | none — `<cli> --add <worktree>`
IDE_WORKSPACE_FILE=""                         # e.g. my-app.code-workspace (folder removed on cleanup)

# ── ProductionDeployment ───────────────────────────────────────────────────────────────
ENV_MATRIX_FILE=".claude/release/settings-matrix.json"   # variable RULES only; identity is above
