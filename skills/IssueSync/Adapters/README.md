# IssueSync adapter contract

An adapter is a directory `Adapters/<name>/` containing an executable called `adapter`. Any
language. `Tools/issue-sync.sh` selects the directory by name and runs `adapter <verb> ARGS`
with three environment variables set:

| Variable | Meaning |
| --- | --- |
| `ISSUE_SYNC_ROOT` | the main checkout (never a worktree); read credentials from its `.env.local` then `.env` |
| `ISSUE_SYNC_DIR` | where to write: `cache/`, `worklog/`, `INDEX.md` (default `<root>/.claude/local/<name>/`) |
| `ISSUE_SYNC_TRACKER` | the adapter's own name |

Credentials come from the process environment first, then the root's `.env.local` (wins) and
`.env`, under variables prefixed with the tracker's name in caps (`JIRA_*`, `LINEAR_*`,
`GITHUB_*`, `AZURE_*`). They are never passed as arguments and never written to disk by the
adapter.

## Verbs the adapter must implement

| Verb | Contract | Exit |
| --- | --- | --- |
| `markup` | print `wiki` or `markdown` and nothing else | 0 |
| `list` | print my active issues; write `$ISSUE_SYNC_DIR/INDEX.md` | 0 |
| `pull KEY [KEY …]` | write `$ISSUE_SYNC_DIR/cache/KEY.json` (schema below) for each key; seed `worklog/KEY.md` **only if absent**; with no key, pull all my active issues | 0, or 1 if any key failed |
| `show KEY` | print summary, status, assignee, URL and the transition names available now; write nothing | 0 |
| `comment KEY [FILE]` | post FILE, or `$ISSUE_SYNC_DIR/worklog/KEY.md` when FILE is omitted, as a comment, verbatim; refuse an empty or template-only file | 0 / 1 |
| `transitions KEY` | print one exact transition name per line as the tracker reports them now | 0 |
| `transition KEY NAME` | apply the transition whose name equals NAME (case-insensitive); print the new status | 0 / 1 if NAME is not available |
| `assign KEY QUERY` | assign to the first assignable user matching QUERY (name or email); try every match before failing | 0 / 1 |
| anything else | print `unknown verb` to stderr | 2 |

`cache`, `worklog`, `count-comments` and `adapter` are implemented once by the dispatcher from
the files above; adapters do not implement them.

A `none` adapter answers `markup` with `markdown` and exits **3** for every other verb with a
one-line instruction of what replaces the step. IssueFlow treats exit 3 as "no tracker".

## Cache JSON schema (`cache/KEY.json`)

```json
{
  "key": "ABC-12",
  "summary": "short title",
  "type": "Story | Task | Bug | Epic | …  (the tracker's own name for the issue type)",
  "status": "In Progress",
  "status_category": "To Do | In Progress | Done   (normalized; map the tracker's states to these three)",
  "assignee": "display name or null",
  "reporter": "display name or null",
  "priority": "tracker's name or null",
  "labels": ["…"],
  "description": "full text in the tracker's markup",
  "url": "https://…/ABC-12",
  "created": "ISO-8601",
  "updated": "ISO-8601",
  "sync_timestamp": "ISO-8601",
  "comments": [
    { "id": "…", "author": "display name", "body": "text in the tracker's markup", "created": "ISO-8601", "updated": "ISO-8601" }
  ]
}
```

Extra fields are allowed. `comments[].body` is what `count-comments` searches, and
`status_category` is what IssueFlow uses to notice an issue is already done.

## Worklog file (`worklog/KEY.md`)

Seeded by `pull` with a heading, the status, the URL and a placeholder line. Written by the
user or by IssueFlow in the tracker's markup (`markup` says which). Posted verbatim by
`comment`. An adapter must refuse to post a file that still only holds the seed placeholder.

## Skeleton for a new adapter (bash shown; any language works)

```bash
#!/usr/bin/env bash
# IssueSync adapter: <name>
set -uo pipefail
ROOT="${ISSUE_SYNC_ROOT:-$PWD}"; DIR="${ISSUE_SYNC_DIR:-$ROOT/.claude/local/<name>}"
mkdir -p "$DIR/cache" "$DIR/worklog"
# credentials: env, then .env.local, then .env (parse, do not source)
tok="${<NAME>_API_TOKEN:-$(grep -hE '^(export )?<NAME>_API_TOKEN=' "$ROOT/.env.local" "$ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2-)}"
[ -n "$tok" ] || { echo "✗ <NAME>_API_TOKEN missing" >&2; exit 1; }
VERB="${1:-}"; shift || true; KEY="${1:-}"
case "$VERB" in
  markup)      echo markdown ;;
  list)        … ;;
  pull)        for k in "$@"; do …write "$DIR/cache/$k.json"…; [ -f "$DIR/worklog/$k.md" ] || …seed…; done ;;
  show)        … ;;
  comment)     f="${2:-$DIR/worklog/$KEY.md}"; …post "$(cat "$f")"… ;;
  transitions) … ;;
  transition)  … "${2:?NAME}" ;;
  assign)      … "${2:?QUERY}" ;;
  *) echo "unknown verb '$VERB'" >&2; exit 2 ;;
esac
```

## Checklist before calling an adapter done

1. `ISSUE_TRACKER=<name> bash Tools/issue-sync.sh adapter` names it.
2. `markup` prints exactly one of `wiki` / `markdown`.
3. `pull KEY` writes a cache file that validates against the schema (all top-level keys
   present, `comments` is a list) and seeds the worklog once.
4. `transitions KEY` output can be fed back to `transition KEY <line>` unchanged.
5. `comment KEY` with an unedited worklog is refused; with an edited one, the comment appears
   in the tracker with the markup intact.
6. `count-comments KEY '.'` equals the number of comments the tracker shows.
7. Run from inside a git worktree: the cache lands under the **main** checkout.
8. No credential appears in any file under `ISSUE_SYNC_DIR` or in the adapter's output.
