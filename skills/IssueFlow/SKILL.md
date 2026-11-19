---
name: IssueFlow
description: Gated, worktree-isolated issue lifecycle for any repo, driven by a per-repo profile (.claude/workflow-profile.sh) — pull issue → provision isolated worktree with its own ports → plan → implement until unit + full e2e + CI-parity preflight are green → developer validation gate → push, PR, preview URL, tracker comment, stakeholder message → stakeholder gate → rebase, re-validate, merge, resolve, clean up. Works one issue of any type that lands in one PR (story, bug, task, work item, ticket); baskets such as epics or remediation sprints are worked as cycles. Also stakeholder review-request tables. USE WHEN work issue, work ticket, work story, work on ABC-123, start issue, pick up ticket, fix bug ABC-123, issue lifecycle, ticket lifecycle, merge approved issue, stakeholder approved, remediation cycle, tech-debt cycle, epic cycle, review request, QA table, what's ready for review, set up issue workflow for this repo. NOT FOR plain JIRA list/comment/transition (use IssueSync), development→production releases (use ProductionDeployment), or picking what to refactor (use CodeQuality).
---

## Customization

**Optional personal preferences:** `${AGENT_SKILLS_CONFIG:-~/.config/agent-skills}/IssueFlow/PREFERENCES.md`.

If that file exists, read and apply it; otherwise proceed with skill defaults. Personal preferences only: anything
that is a fact about a repo or product belongs in that repo (its `.claude/workflow-profile.sh`
or tool configs), never here.

# IssueFlow

One issue, end to end, with hard human gates and nothing product-specific baked in.
Every product detail lives in the repo's **profile**: issue key pattern, branches, env files,
setup/test/serve commands, preview URLs, stakeholder, and IDE.

**What an issue is here.** The unit this skill works is the tracker's *leaf*: whatever your
tracker calls the thing that lands in **one** branch and **one** PR (a JIRA Story, Task or Bug;
an Azure Boards work item; a Linear or GitHub issue; a "ticket"). The word "issue" is used
because every tracker uses it for that level, JIRA included, where Epic, Story, Task and Bug are
all issue *types*. A **basket** issue that spans many PRs (an Epic, a remediation sprint) is
worked as cycles with the Remediation workflow: one key, one worktree, one PR per cycle.

## Step 0 — every workflow starts here

```bash
IS="${SKILLS_HOME:-$HOME/.claude/skills}/IssueSync/Tools"; IF="${SKILLS_HOME:-$HOME/.claude/skills}/IssueFlow/Tools"
bash "$IF/profile.sh"          # prints the effective profile, or how to create one
```

- **No profile?** Run the **Setup** workflow before anything else. Never guess commands.
- Read [Conventions.md](Conventions.md) once per session. It covers approval vocabulary,
  resume logic, naming, ports, env files, e2e tags and modes, the tracker verbs and comment
  templates, pull requests, previews, and the stakeholder message.

## Workflow routing

| Trigger | Workflow |
| --- | --- |
| repo has no `.claude/` split, CLAUDE.md or CI shape yet, "make this repo agent-ready" | **RepoScaffold** skill (it ends by calling Setup below) |
| "set up issueflow for this repo", no profile found | [Workflows/Setup.md](Workflows/Setup.md) |
| "work ABC-26", "start issue", "fix bug ABC-26", resume an issue | [Workflows/Issue.md](Workflows/Issue.md) |
| "stakeholder approved", "merge ABC-26" | [Workflows/Merge.md](Workflows/Merge.md) |
| "remediation cycle", "tech-debt cycle on ABC-52" | [Workflows/Remediation.md](Workflows/Remediation.md) |
| "review request", "QA table", "what's ready for review" | [Workflows/ReviewRequest.md](Workflows/ReviewRequest.md) |

## Tools (deterministic; read the profile themselves)

| Script | Does |
| --- | --- |
| `profile.sh` | Sourced by all tools: main-root resolution, defaults, server lifecycle helpers. Run directly → print the effective profile |
| `provision.sh <name> <branch> [X\|auto] [purpose] [--reuse]` | Worktree off latest integration branch + env files + ports + setup + ledger row + IDE add. `--reuse` re-points an existing worktree at a new branch (remediation cycles) |
| `validate-env.sh [--production] [wt]` | Required/optional env vars present; placeholders flagged (rejected in `--production`) |
| `serve.sh [wt]` | Fresh app on the worktree port, left running, health-checked |
| `e2e.sh [--record] [--no-server] [wt] [-- args]` | Full e2e against a fresh server, always torn down. `--record` runs the server in record mode and reports the fixture count |
| `preflight.sh [--fix] [wt]` | CI-parity checks, every check reported |
| `issue-sync.sh <verb> KEY …` | Tracker adapter (`$TRACKER`): pull, cache, worklog, comment, transitions, transition, assign, count-comments |
| `pr.sh <verb> --head B …` | Forge adapter (`$FORGE`): find, create (idempotent), view, close, merge, list |
| `preview-url.sh <branch> [--sha S] [--wait N]` | Branch-stable + commit preview URLs (template → provider CLI → GitHub deployments) |
| `cleanup.sh <wt> [--delete-remote] [--keep-branch] [--keep-worktree]` | Stop server, IDE removal, worktree + branch removal, ledger row freed. `--keep-worktree` closes a remediation cycle |

The tools resolve the **main** checkout via `git-common-dir`, so they behave the same from the
repo root or from inside any worktree. Templates: `workflow-profile.sh` (the profile) and
`remediation-issue.md` (the basket issue the Remediation workflow works).

## Non-negotiables

- **Gates are hard stops.** Never self-approve developer validation or stakeholder approval.
- **Green means all of them:** unit + full e2e + preflight. A gate whose command is not in
  the profile is reported as **SKIPPED**, never as passed.
- **Never weaken a test or a lint rule to get green.** Stale tests are updated to the new
  requirement. Failing rules are fixed in the code.
- **Never force-push the integration branch.** If a fast-forward is refused, rebase again.
- **One branch, one issue.** Keep scope to the issue's acceptance criteria.
