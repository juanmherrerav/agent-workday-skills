---
name: RepoScaffold
description: Make any software repo agent-ready by scaffolding the repo-side conventions that the IssueFlow, ProductionDeployment and IssueSync skills rely on — the committed `.claude/` logic vs git-ignored `.claude/local/` runtime split, the gitignore block, per-machine permission settings, a CLAUDE.md routing table that points at the issue workflow, a PR template, a provider-agnostic CI pipeline shape the preflight gate mirrors 1:1, and TESTING/CONTRIBUTING docs with the e2e tag taxonomy and fixture/live/record modes. Finishes by running IssueFlow Setup to write the profile. USE WHEN set up claude automation in this repo, scaffold the agent workflow, onboard a repo, add the issue workflow to a new repo, make this repo agent-ready, new repo claude setup. NOT FOR filling profile values on their own (IssueFlow Setup), generating application code, or writing CI YAML from scratch without being asked.
---

## Customization

**Optional personal preferences:** `${AGENT_SKILLS_CONFIG:-~/.config/agent-skills}/RepoScaffold/PREFERENCES.md`.

If that file exists, read and apply it; otherwise proceed with skill defaults. Personal preferences only: anything
that is a fact about a repo or product belongs in that repo (its `.claude/workflow-profile.sh`
or tool configs), never here.

# RepoScaffold

IssueFlow and its siblings assume a few things about the repo they run in. This skill puts
those things in place, derives every value from the repo, and never invents a command.

```
.claude/                      committed: profile, release matrix, README (the contract)
.claude/local/                git-ignored: worktrees, ledger, tracker cache, worklogs
.claude/settings.local.json   git-ignored: this machine's permission mode
CLAUDE.md                     routing table → "work an issue" = IssueFlow
.github/pull_request_template.md   (or the forge's equivalent)
docs/TESTING.md  docs/CONTRIBUTING.md   tag taxonomy, API modes, branch + commit rules
CI pipeline                   lint → security → unit → coverage → e2e(fixture) → summary
```

## Workflow routing

| Trigger | Workflow |
| --- | --- |
| "scaffold this repo", "make it agent-ready", "set up the issue workflow here" | [Workflows/Scaffold.md](Workflows/Scaffold.md) |
| only the profile is missing | IssueFlow → Setup (this skill calls it as its last step) |

## Templates

Tokens look like `{{TOKEN}}`. Every token must be filled from the repo or from the user, and a
template whose tokens are not all resolved is not written.

| Template | Lands at | Purpose |
| --- | --- | --- |
| `Templates/CLAUDE.md.template` | `CLAUDE.md` | routing table: issue workflow, automation map, real commands, CI troubleshooting |
| `Templates/claude-README.md.template` | `.claude/README.md` | the shared-vs-local contract, permission decision, first-time setup |
| `Templates/settings.local.json.template` | `.claude/settings.local.json` | per-machine permission mode (never committed) |
| `Templates/gitignore.block` | appended to `.gitignore` | runtime paths that must never be committed (idempotent marker) |
| `Templates/pull_request_template.md` | `.github/pull_request_template.md` | validation evidence + impact assessment |
| `Templates/TESTING.md.template` | `docs/TESTING.md` | principles, test types, tag taxonomy, fixture/live/record, coverage gate |
| `Templates/CONTRIBUTING.md.template` | `CONTRIBUTING.md` | install, branches named by issue key, conventional commits, PR process |
| `Templates/ci-pipeline.md` | reference only | the pipeline shape to compare the repo's CI against, per provider |

## Non-negotiables

- **Derive, don't invent.** Commands come from the repo's README, Makefile, package manifests
  and CI. A command that is not already run somewhere in the repo does not go in a template.
- **Never commit runtime.** `.claude/local/`, `.claude/settings.local.json`, `CLAUDE.local.md`
  and env files stay git-ignored. Check with `git check-ignore` before finishing.
- **Don't rewrite existing docs or CI.** Add the missing sections and report the gaps. The
  user decides what to replace.
- **CI and preflight change together.** Whatever the CI lint/type job runs is what
  `PREFLIGHT_CHECKS` runs, in the same order.
