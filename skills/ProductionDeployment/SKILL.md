---
name: ProductionDeployment
description: Release pipeline that promotes an integration branch to production for any repo — builds the release PR with a changelog grouped by issue, resolves merge conflicts with a deterministic integration-wins strategy (flagging anything ambiguous), and gates the deploy on an environment-variable parity matrix (SAME / ENV-SPECIFIC / PRESENT) across Production and Preview, with indirect checks for encrypted vars. Branches, issue pattern and provider identity come from the repo's IssueFlow profile; the matrix of variable rules lives in the repo. USE WHEN deploy to production, release to main, production release, promote development, merge development to main, release PR, pre-deploy validation, env parity check, vercel env check. NOT FOR merging a single issue into the integration branch (use IssueFlow Merge) or deploying preview builds.
---

## Customization

**Optional personal preferences:** `${AGENT_SKILLS_CONFIG:-~/.config/agent-skills}/ProductionDeployment/PREFERENCES.md`.

If that file exists, read and apply it; otherwise proceed with skill defaults. Personal preferences only: anything
that is a fact about a repo or product belongs in that repo (its `.claude/workflow-profile.sh`
or tool configs), never here.

# ProductionDeployment

```
PHASE 2: CONFLICTS          PHASE 1: PR                 PHASE 3: VALIDATION
[integration-wins merge] ──► [Release PR]  ──────────► [env parity matrix]  ──►  DEPLOY
 deterministic, flags         changelog                  pass/fail gate,
 the ambiguous                grouped by issue           blocks on failure
```

## Configuration (all from the IssueFlow profile)

```bash
IF="${SKILLS_HOME:-$HOME/.claude/skills}/IssueFlow/Tools"; . "$IF/profile.sh"
```

No profile → the loader stops and says how to create one. Run IssueFlow **Setup** (or
RepoScaffold) first. Never guess branch names.

| Setting | Profile key |
| --- | --- |
| branches, remote | `INTEGRATION_BRANCH`, `PRODUCTION_BRANCH`, `REMOTE` |
| changelog grouping | `ISSUE_PREFIX` (derived from `ISSUE_PATTERN`; empty = any `KEY-123`) |
| forge for the release PR | `FORGE` → `pr.sh` |
| provider identity for env pulls and API metadata | `PREVIEW_PROVIDER`, `PREVIEW_SCOPE`, `PREVIEW_PROJECT`, `PREVIEW_TEAM_ID`, `PREVIEW_PROJECT_ID` |
| variable rules, runtime endpoints, known dead vars | `$ENV_MATRIX_FILE` (default `.claude/release/settings-matrix.json`) |

No matrix file → Phase 3 is **SKIPPED**, and said so. To create one, start from
`Templates/settings-matrix.example.json` and list **only** variables the code reads (`git grep`
them). The matrix holds rules; identity lives in the profile so it is declared once.

## Workflow routing

| Trigger | Run |
| --- | --- |
| "deploy to production", "release", "full deploy" | [Workflows/Deploy.md](Workflows/Deploy.md), all phases (order: 2 → 1 → 3) |
| "create release PR" | Deploy.md Phase 1 |
| "resolve release conflicts" | Deploy.md Phase 2 |
| "validate env", "env matrix", "check vercel settings" | Deploy.md Phase 3 |

## Conflict strategy: integration wins, ambiguity escalates

| Conflict | Resolution | Why |
| --- | --- | --- |
| Refactor on integration side (renames, extracted constants/enums, restructured code) | take integration | it holds the newest refactoring |
| Legacy naming on production side vs new naming on integration | take integration | newer conventions supersede |
| Deleted on integration, modified on production | delete | the removal was a decision |
| Net-new, overlapping code on both sides | **STOP, human decides** | guessing here ships bugs |

## Matrix rules

- **SAME:** identical in Production and Preview. A difference means drift.
- **ENV-SPECIFIC:** must differ between them. Identical values mean a copy-paste error that
  could route preview traffic to production systems. Optional `production_pattern` /
  `preview_pattern` substrings are also checked.
- **PRESENT:** exists and is non-empty in `required_in` (default: both).

## Non-negotiables (on top of IssueFlow Conventions)

- The release PR merge is the only path into production. Never push to it.
- Never skip env validation when a matrix exists. A misconfigured production is worse than a
  late deploy.
- Always generate the changelog. The PR body is the deployment record.
- Never auto-resolve an ambiguous conflict.
- Pulled env files hold secrets. Delete them in the same phase, and never commit them.

## Prerequisites

`gh` authenticated. For Vercel matrices: the `vercel` CLI (or `bunx vercel`), the repo linked
(`vercel link`), and a `VERCEL_TOKEN` scoped to the right team. SSO teams need a team-scoped
token, because a personal token returns "scope does not exist".
