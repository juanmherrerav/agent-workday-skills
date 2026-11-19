# Tasks — add, close, restore, sweep, import

```bash
BP="${SKILLS_HOME:-$HOME/.claude/skills}/BattlePlan/Tools"
```

Every command prints one JSON object. Run tracker commands one at a time, never in parallel.

## Add (`/BattlePlan --add "…"`)

```bash
uv run --script "$BP/manage_tasks.py" add "TASK" --sub-context "Product" \
  [--source "Ticket ABC-123"] [--owner NAME] [--priority High] [--deadline 2026-10-15] [--date YYYY-MM-DD]
uv run --script "$BP/manage_tasks.py" add "TASK" --tab "Personal"     # first sub-context of that tab
```

Owner defaults to the config `owner`; `#` auto-increments per tab.

**Source conventions** (the `Meeting` column; keep them stable, since dedupe keys on them):
`Manual` (default) · `Ticket ABC-123` · `Chat #channel` · `Email` ·
`Meeting: <title> YYYY-MM-DD` · `Meeting: <title> YYYY-MM-DD (notes)` for imported meeting
notes · `Meeting: <title> YYYY-MM-DD (recording)` for transcribed recordings · `Session YYYY-MM-DD`
for untracked agent work found by the recap.

## Batch add (imports)

```bash
uv run --script "$BP/manage_tasks.py" batch-add --file tasks.jsonl [--dry-run]
# {"action": "ABC-12: review parser PR", "sub_context": "Product", "source": "Meeting: Standup 2026-10-20", "date": "2026-10-20", "priority": "High", "deadline": "2026-10-24"}
```

- **Idempotent:** a `(source, action)` pair already in the tab or the Archive is `skipped`, so
  re-running an import never duplicates.
- Any invalid line (bad JSON, unknown sub-context, no action, confidential violation) rejects
  the whole batch before anything is written.
- Prefer it over repeated `add` for more than ~3 tasks.

**From a ticket tracker:** pull the issue (the IssueSync skill: `issue-sync.sh pull KEY`, or
your tracker's CLI), then add `"KEY: <summary>"` with `--source "Ticket KEY"` and the ticket's
priority and due date. For a sprint, build one JSONL and `batch-add` it.

**From meetings:** the MeetingAnalysis skill extracts your action items and calls `batch-add`.

## Close a task

```bash
uv run --script "$BP/manage_tasks.py" mark-done "substring" [--sub-context X] [--tab T] [--dry-run]
uv run --script "$BP/manage_tasks.py" mark-done --tab "Work" --row 24
uv run --script "$BP/manage_tasks.py" mark-cancelled "substring"
printf 'Work!12\nWork!15\n' | uv run --script "$BP/manage_tasks.py" batch-done [--status Cancelled] [--dry-run]
```

- Substring search is case-insensitive on the action; an all-digit search matches `#` exactly
  (and `#` repeats across meetings, so prefer `--row`).
- Exactly one open match is required. None → exit 1. Several → exit 2 with `ambiguous: true`
  and `candidates[].ref`; show them, then re-run with `--tab --row`.
- Closing moves the row to `Archive` (with `source_tab`, `archived_at`, `sub_context`) and
  deletes it from its tab.

## Restore and sweep

```bash
uv run --script "$BP/manage_tasks.py" restore "substring" | --row N [--dry-run]   # N = row in Archive
uv run --script "$BP/manage_tasks.py" sweep [--tab T] [--sub-context X] [--dry-run]
uv run --script "$BP/manage_tasks.py" list-tabs
```

`restore` puts an archived row back in its source tab as Open. `sweep` archives every row
whose status was set to done or cancelled by hand in the tracker.
