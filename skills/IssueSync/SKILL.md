---
name: IssueSync
description: Tracker-agnostic issue I/O for any repo — pull issues to a git-ignored local cache under the main checkout, keep one worklog per issue, post it back as a comment, list and apply transitions, assign. One verb contract, one adapter directory per tracker (jira implemented, none built in; add linear, github, azure as directories). The adapter is chosen by TRACKER in the repo profile, ISSUE_TRACKER in the env, or detected from credentials. USE WHEN "jira", "sync issues", "pull my issues", "pull my tickets", "my open issues", "post a comment on ABC-12", "update the issue", "transition ABC-12", "move the issue to", "resolve the issue", "assign ABC-12", or working a tracker issue locally. NOT FOR the branch→PR→merge lifecycle (use IssueFlow, which calls this skill).
---

## Customization

**Optional personal preferences:** `${AGENT_SKILLS_CONFIG:-~/.config/agent-skills}/IssueSync/PREFERENCES.md`.

If that file exists, read and apply it; otherwise proceed with skill defaults. Personal preferences only: anything
that is a fact about a repo or product belongs in that repo (its `.claude/workflow-profile.sh`
or tool configs), never here.

# IssueSync

Work tracker issues without leaving the repo, whatever the tracker. The skill is a **verb
contract** plus a **dispatcher**; each tracker is an **adapter directory** that implements the
verbs. IssueFlow calls this skill for every tracker interaction and never a tracker CLI directly.

## Entry point (always the same command)

```bash
IS="${SKILLS_HOME:-$HOME/.claude/skills}/IssueSync/Tools"
bash "$IS/issue-sync.sh" adapter            # which adapter is active, and why
bash "$IS/issue-sync.sh" <verb> KEY …
```

Adapter selection, first match wins: `$ISSUE_TRACKER` in the environment → `TRACKER=` in the
repo's `.claude/workflow-profile.sh` → auto (JIRA credentials present → `jira`, else `none`).
The root is the **main** checkout even inside a git worktree, so all worktrees share one cache.
The shell CWD does not persist between tool calls: define `IS` in the same command that uses it.

## Verbs

| Verb | Does | Implemented by |
| --- | --- | --- |
| `adapter` | name and path of the active adapter | dispatcher |
| `markup` | the comment syntax this tracker wants: `wiki` or `markdown` | adapter |
| `list` | my active issues; writes `INDEX.md` | adapter |
| `pull KEY …` | refresh the cache: `cache/KEY.json` (summary, description, status, type, comments…) | adapter |
| `show KEY` | status and available transitions, no file writes | adapter |
| `cache KEY` / `worklog KEY` | print the cache path / the worklog path (write comments there) | dispatcher |
| `comment KEY [FILE]` | post the worklog, or FILE, as a comment | adapter |
| `transitions KEY` → `transition KEY NAME` | list the exact names available now, then apply one | adapter |
| `assign KEY QUERY` | assign to the first assignable user matching a name or email | adapter |
| `count-comments KEY REGEX` | cached comments whose body matches REGEX (IssueFlow's cycle counter) | dispatcher |

Exit code 3 means "no tracker configured" and the message says what to do instead (ask the
user for acceptance criteria, put the comment in the PR body).

## Runtime (git-ignored)

`<main checkout>/.claude/local/<tracker>/{cache/KEY.json, worklog/KEY.md, INDEX.md}`, override
with `ISSUE_SYNC_DIR`. API data, so `.claude/local/` must be in the repo's `.gitignore`.

## Rules that bite, for every adapter

- **Ask the markup before writing a comment.** `issue-sync.sh markup` answers `wiki` (JIRA) or
  `markdown`. Writing Markdown into a wiki tracker renders as raw text; writing wiki into a
  Markdown tracker is just as ugly.
- **Transitions: list first, every time.** Names differ by issue type and current status.
  Never assume a path; chain steps when the target is not directly reachable.
- **Worklogs are per-issue files.** `pull` never overwrites one that exists. Rewrite the file
  for a fresh comment; append to keep a running log (IssueFlow's cycle counter depends on it).
- **Credentials never go in the profile.** Each adapter reads its own `<TRACKER>_*` variables
  from the process env, then `<root>/.env.local` (wins) and `<root>/.env`.

## Adapters

| Name | Status | Credentials | Markup | Notes |
| --- | --- | --- | --- | --- |
| `jira` | implemented ([Adapters/jira/](Adapters/jira/)) | `JIRA_CLOUD_URL` or `JIRA_BASE_URL`, `JIRA_USER_EMAIL` or `JIRA_EMAIL`, `JIRA_API_TOKEN`, optional `JIRA_PROJECT_KEY`, `JIRA_SYNC_DIR` | wiki | Python (`jira` + `python-dotenv`): the repo `.venv` if it has them, else `uv run --with`. A repo may vendor its own copy at `tools/jira-sync/jira_sync.py`, which the adapter prefers. `assign` tries every matching account (old and new SSO accounts coexist). `comment` refuses an empty or unedited worklog. |
| `none` | built in | — | markdown | every verb exits 3 with the fallback for IssueFlow |
| `linear`, `github`, `azure` | not yet | per tracker | markdown | one directory each, following the contract |

**Adding an adapter:** create `Adapters/<name>/adapter` (any language, executable), implement
the adapter-side verbs from the table with the cache JSON shape in
[Adapters/README.md](Adapters/README.md), set `TRACKER=<name>` in a repo profile, and run the
checklist at the end of that README. The dispatcher and IssueFlow do not change.
