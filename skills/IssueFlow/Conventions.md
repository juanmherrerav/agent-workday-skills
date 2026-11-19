# IssueFlow conventions (shared by every workflow)

Values in `$CAPS` come from the repo profile. Print them with `bash "$IF/profile.sh"`, or
`. "$IF/profile.sh"` inside a bash command to use them. Two path variables are used
throughout: `IF="${SKILLS_HOME:-$HOME/.claude/skills}/IssueFlow/Tools"` and
`IS="${SKILLS_HOME:-$HOME/.claude/skills}/IssueSync/Tools"` (the tracker skill).

## Approval vocabulary: two distinct gates

| Gate | User phrases | Action |
| --- | --- | --- |
| **Developer validation** (Issue step 6 → 7) | "local approve", "approved", "looks good", "lgtm", "ship it to review" | Push, open/update PR, post tracker comment, draft stakeholder message |
| **Stakeholder approval** (Issue step 7.5 → Merge) | "stakeholder approved", "reviewer approved", "<$STAKEHOLDER> approved", "merge it" | Run the Merge workflow |

A bare "approve" is ambiguous, so ask which gate is meant. Never infer stakeholder approval
from developer approval. If `$STAKEHOLDER_GATE=false`, developer approval goes straight to
Merge.

## Resume (Issue and Remediation check this first)

1. **Open PR for the branch?** `bash "$IF/pr.sh" find --head "<branch>"`. Open means the work
   is in review. Issue: ask "check status, address feedback, or merge (only on stakeholder
   approval)?" and default to a status check. Remediation: ask "merge this cycle or abandon
   it?".
2. **Worktree exists?** `$WORKTREE_DIR/<key-lower>-*` and its ledger row. Ask which state we
   are in (implementing / ready for PR / awaiting approval; for Remediation, uncommitted work
   means continue or discard) and resume there.
3. **Neither?** Start at Step 1.

## Naming

- **Issue key:** must match `$ISSUE_PATTERN`. Reject anything else before doing work.
- **Branch:** `$BRANCH_TEMPLATE` rendered with `{KEY}` / `{key}` / `{slug}`. Inside bash, use
  `if_branch KEY SLUG` after sourcing `profile.sh`.
- **Worktree:** `$WORKTREE_DIR/<key-lower>-<slug>`. The slug is only there for human
  readability, and the directory is git-ignored.
- **Remediation branches:** `<branch>-cycle-<N>`, worktree `<key-lower>-remediation` (reused).

## Ports and the ledger

- Each worktree claims a digit `X` (1–9): backend `$PORT_BASE_BACKEND+X`, frontend
  `$PORT_BASE_FRONTEND+X`. The main checkout is `X=0` and is never touched, so parallel issues
  never collide.
- `provision.sh` picks the lowest free X from the **live ledger** (`$LEDGER_FILE`, git-ignored,
  seeded automatically) and writes the row. `cleanup.sh` frees it. A paused worktree still
  holds its X until cleaned up.
- `git worktree list` is the source of truth. If the ledger drifts, fix the ledger.

## Integration and release

- Issues merge into `$INTEGRATION_BRANCH` and releases promote it to `$PRODUCTION_BRANCH`.
  The promotion belongs to the ProductionDeployment skill, not here.
- With a stakeholder gate, issues stay open PRs with previews until approved, and only then
  merge.

## Tracker (the IssueSync skill, adapter chosen by `$TRACKER`)

Workflows never call a tracker CLI directly. They call `bash "$IS/issue-sync.sh" <verb>` and
`$TRACKER` names the IssueSync adapter directory: `jira` today, `none` for no tracker (exit 3
with what to do instead), any other name once its adapter exists. The runtime dir is always
under the **main** checkout, so a worktree and the repo root share one cache. A new tracker
(Linear, GitHub Issues, Azure Boards) is one new adapter directory in IssueSync; the workflows
do not change.

| Verb | Does | Used by |
| --- | --- | --- |
| `pull KEY…` / `cache KEY` | refresh the cache / print its path (summary, description, status, type, comments) | Issue 2, Remediation 1 |
| `worklog KEY` | path of the comment draft; write comments there, in the tracker's markup | Issue 7.2, Merge 4, Remediation 7 |
| `comment KEY [FILE]` | post the worklog (or FILE) as a comment | same |
| `transitions KEY` → `transition KEY NAME` | list the exact names, then apply one. **List first, every time**: they differ by issue type and current status | Issue 7.3, Merge 4, Remediation close |
| `assign KEY QUERY` | assign to the first assignable match | Issue (optional) |
| `count-comments KEY REGEX` | cycle counter | Remediation 1 |

**Markup belongs to the adapter.** Ask `bash "$IS/issue-sync.sh" markup` before writing a
comment: `wiki` (JIRA: `h2.`, `*bold*`, `{{mono}}`, `||h||` tables, `[label|url]`) or
`markdown`. The templates below are written in wiki markup; for a Markdown adapter write the
same structure in Markdown. Syntax details live in the IssueSync skill and nowhere else.

## Tracker comment templates

Three comments, one per stage. Write to `$(bash "$IS/issue-sync.sh" worklog KEY)`, then
`issue-sync.sh comment KEY`. **Review** and **Resolution** replace the file. **Cycle** appends,
because the `h2. Cycle` headings are the cycle counter.

**Review** (Issue 7.2):

```
h2. Ready for Review

*Preview:* <branch-preview-url>
*Pull Request:* [PR #N|<pr-url>]

h3. What changed
* <what the user experiences differently>

h3. How to validate
# <step for the reviewer>

h3. Acceptance criteria addressed
||Criterion||Status||
|<AC>|<how it is satisfied>|
```

**Resolution** (Merge 4):

```
h2. Resolved

h3. How it landed
* {{<branch>}} → {{<integration branch>}} by <ff-only|squash>, <before-sha> → <after-sha>, rebased: <yes|no>
# <sha> <subject>        (oldest → newest)

h3. How the code addresses the issue
* *Root problem:* <one sentence>
* *Fix:* <behavior change>, in {{<key file>}}, {{<key file>}}
||Criterion||How||
|<AC>|<how it is satisfied>|

h3. Validation
* Unit ✅ N/N · Preflight ✅ · e2e ✅ N/N

h3. Approval
* <who>, <date>
```

**Cycle** (Remediation 7, appended):

```
h2. Cycle <N> — <short title>

*PR:* [PR #X|<pr-url>]   *Merged:* <date>

* <what changed>

_Cumulative cycles this sprint: <N>_
```

## Pull requests (`pr.sh`, forge chosen by `$FORGE`)

`pr.sh find|create|view|close|merge|list` is the only place the workflows touch the forge
(GitHub through `gh` today). `create` is idempotent: an open PR for the branch is updated, not
duplicated, so resume paths call it again without checking. The body comes from stdin; an
empty stdin falls back to the repo's PR template. Every body carries a summary, the issue
key, validation (unit / e2e / preflight counts, or SKIPPED), and how to review (the
branch-stable preview URL when there is one).

## Env files

- `provision.sh` copies `$ENV_FILES` from the main checkout into the worktree and appends the
  ports. `validate-env.sh [wt]` then checks `$ENV_REQUIRED_VARS` / `$ENV_OPTIONAL_VARS`.
- **Placeholders** (`$ENV_PLACEHOLDER_VALUES`, e.g. `test-key`) are what CI writes so fixture
  mode boots without credentials. They pass in development, fail with `--production`, and
  mean "live-tagged scenarios cannot run here".
- Env files are parsed, never sourced. Secrets never go into a tracker comment, a PR body or
  a fixture.

## E2E tags and API modes

The e2e suite is expected to carry a **tag taxonomy** and an **API mode switch**. Both are
repo code, and the RepoScaffold `TESTING.md` template documents the target state.

| Tag | Meaning | CI | Full e2e gate |
| --- | --- | --- | --- |
| `@smoke` | app shell renders | yes | yes |
| `@api-only` | backend HTTP, no browser | yes | yes |
| `@live-api` | needs real upstream credentials | **no** | fixture mode only |
| `@wip` | in progress or quarantined | no | no |

| Mode | Server env | What happens |
| --- | --- | --- |
| fixture | `$E2E_SERVER_ENV` (default) | upstream calls replayed from `$FIXTURES_DIR` |
| live | real credentials, no mode override | real upstream calls |
| record | `$E2E_RECORD_ENV` | live, and every response is saved as a fixture |

- The gate (`e2e.sh`) runs `$E2E_CMD` in fixture mode on a fresh server. "Full" means
  `not @wip`, never a smoke subset.
- When an upstream contract changes, `e2e.sh --record [wt]` re-records with real
  credentials (server env `$E2E_RECORD_ENV`). Review the fixture diff for secrets, then
  commit `$FIXTURES_DIR`.

## Previews

- `preview-url.sh <branch>` prints `BRANCH_URL` (a stable alias that follows the branch's
  latest deploy) and/or `COMMIT_URL` (one exact SHA). **Prefer `BRANCH_URL` in anything
  humans read.** It survives force-pushes, while commit URLs go stale.
- Sources, in order: `$PREVIEW_URL_TEMPLATE` (deterministic), the provider CLI
  (`vercel ls` + `inspect` with `$PREVIEW_PROJECT` / `$PREVIEW_SCOPE` / `VERCEL_TOKEN`), then
  the GitHub deployments API. Custom domains make the alias unpredictable, so set the template
  from a real PR or let the CLI ask the platform. Never guess a URL.
- After obtaining a URL, confirm the deployed build contains your change (a visible marker,
  or the version/SHA endpoint if there is one). A stale deploy looks identical to a broken fix.
- `$PREVIEW_PROVIDER=none`: say so, and the stakeholder validates locally or on staging.

## Stakeholder message template (`$REVIEW_CHANNEL`)

Plain language, because the audience is product and business people. Draft it, show it to the
user, and let them post it themselves.

```
**<KEY>: <Short title> — Ready for Review**

Hi team — this is ready for a look:

- **Pull Request:** <pr-url>
- **Preview:** <branch-preview-url>

**What's new:**
<2–3 sentences on what the user experiences differently. No implementation detail.>

**Highlights:**
- <benefit 1>
- <benefit 2>

**To test:** <1–2 sentences, minimal steps.>
```

## Shell hygiene

- CWD does not persist between tool calls. Re-derive `TF`, `WT` and `BRANCH` in each command,
  or use `git -C "$WT"`.
- Never `cd` into the main checkout to edit issue code. Work inside `$WT`.
