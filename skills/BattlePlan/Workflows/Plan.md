# Plan — the daily battle plan

Invocations: `/BattlePlan` (all contexts), `/BattlePlan <context>` (substring filter, e.g.
`work`), `--mine` (only tasks owned by you, shared, or unassigned), `--skip-audit`, `--launch`
(also spawn threads after confirmation), `--audit` (reconcile the tracker, then stop).

```bash
BP="${SKILLS_HOME:-$HOME/.claude/skills}/BattlePlan/Tools"
```

## Step 0 — Pull

```bash
uv run --script "$BP/pull_tasks.py" [CONTEXT] [--mine] > "${TMPDIR:-/tmp}/bp-pull.json"
```

Output shape (abridged):

```json
{"date": "YYYY-MM-DD", "total_open_tasks": 12, "urgent_tasks": 2, "overdue_tasks": 1, "stale_tasks": 3,
 "by_owner_kind": {"mine": 8, "shared": 2, "theirs": 1, "unassigned": 1},
 "contexts": {"Work": {"sub_contexts": {"Product": {"thread_profile": "heavy", "repo": "my-app", "tasks": [
   {"row": 24, "source_tab": "Work", "action": "ABC-76: retry on timeout", "owner_kind": "mine",
    "priority": "High", "priority_rank": 3, "deadline": "2026-10-16", "deadline_kind": "approx",
    "overdue_days": 5, "urgent": true, "stale": false, "blocked": false, "depends_on": [], "tickets": ["ABC-76"]}]}}}}}
```

Fields are computed deterministically. **Use them; do not re-derive from raw text.**

| Field | Meaning |
| --- | --- |
| `row` + `source_tab` | `Tab!row` targets a task exactly |
| `deadline` / `deadline_kind` | ISO date. `exact`, `approx` ("this week", "mid-November", "Q4"), `dependency` ("after X"), `none`, `unknown` (read `deadline_raw`). Relative phrases anchor to the task's own date |
| `urgent` / `overdue_days` / `due_today` | Past due or due today |
| `priority_rank` | Critical 4 > High 3 > Medium 2 > Low 1; unknown → Medium |
| `owner_kind` | `mine`, `shared` (you + others, or team), `theirs` (you are waiting on it), `unassigned` |
| `blocked` / `depends_on` | Dependency deadline, or "after / once / waiting on …" in the text |
| `stale` | Older than 14 days, no resolvable deadline, not ongoing |
| `ongoing` | A standing norm, not a one-off task |
| `tickets` | `ABC-123`-style IDs found in action, source or deadline |

Tasks arrive sorted: urgent (most overdue first) → priority → nearest due → oldest.

**Today's drafts:** if `<plans_dir>/<today>-draft-*.md` exist, read this host's first and show
its header line. Still pull (the tracker may have changed) and recap sessions after the
draft's build time, then merge. Do not redo estimates for unchanged tasks. Other hosts' drafts
are evidence for their contexts.

## Step 0b — Recap since the last plan

```bash
uv run --script "$BP/recap_sessions.py" --tasks "${TMPDIR:-/tmp}/bp-pull.json" [--since auto] [--context CONTEXT]
```

Pass the same filter as the pull to `--context`. Output:

| Field | Use |
| --- | --- |
| `sessions[]` | `context`, `title`, `cwd`, `branch`, `tickets`, `prs`, `git_actions`, `first_prompt`, `last_prompt`, `last_assistant`, `resume_cmd` |
| `git[]` | Your commits per repo since the window start, with tickets |
| `links[]` | Task `ref` ↔ sessions / commits sharing a ticket ID |
| `unlinked_sessions` | Sessions with no ticket match: match by meaning, or list as untracked work |
| `by_context`, `excluded_by_context` | `unclassified` means no evidence rule matched; check before calling a context quiet |
| `trivial_skipped`, `automation_skipped`, `clones_collapsed` | Noise filtered out |

Read the newest `*-handoff-*.md` per host when it is newer than the last plan: its "In flight"
section supplies the next step per thread.

Classify every open task, citing evidence:
- **Likely done:** a linked PR merged or opened and the session reports completion, or the handoff says done
- **In flight:** a linked session was active but the work is unfinished; keep its `resume_cmd`
- **No evidence:** nothing touched it

## Step 1 — Classify and cluster

Per sub-context: cluster related tasks by epic, app or theme (shared `tickets` go together);
start dependencies from `blocked` / `depends_on` and add only chains the script missed; surface
`stale` and `urgent`; treat `theirs` as things you are waiting on, not things you execute.

## Step 2 — Estimate

| Size | Minutes (config `size_estimates_minutes`) | Typical |
| --- | --- | --- |
| S | 30 | message, follow-up, review, admin |
| M | 60 | research, doc, small change, config |
| L | 120 | feature, multi-file change, integration |
| XL | 240 | architecture, migration, multi-PR |

`priority_rank >= 3` gets ×1.2. Flag `urgent` as **URGENT** with `overdue_days`. Estimate
`blocked` tasks but never schedule them before what they wait on. Vague tasks default to S.

## Step 3 — Plan

1. Sum hours per sub-context, context and overall.
2. Available hours: `workday.hours` (default 8), split by each context's `hours` and any
   sub-context `hours_cap`.
3. Threads: each `heavy` sub-context with 2h+ gets its own; `medium` ones share when under 2h;
   `light` ones batch into one "quick items" thread. At most `workday.max_threads` (default 4):
   human attention is the bottleneck.
4. Order inside a thread: urgent → high priority with deadlines → blockers first → quick wins →
   the rest by priority.

## Step 4 — Audit (default; skip with `--skip-audit`)

**4a.** Lead with the recap so the user confirms instead of recalling. Proposed-done items come
pre-checked:

```markdown
## Since yesterday (5 sessions, 2 commits)
**Likely done — confirm or veto:**
- [x] 3. ABC-44 open PR for the parser fix — PR #192 opened, commit af2d7da · `Work!20`
**In flight — resume:**
- 4. ABC-44 follow-up report — next: address review comments · `cd ~/dev/my-app && claude --resume acafffd1…`
**Untracked work (no task matched):** "PR review comments" (11:12) — add as task?

Reply "ok" to accept, or list vetoes / extra done items (e.g. "3 not done; 7 done").
```

Then the remaining no-evidence tasks grouped by thread, one line each:
`- [ ] N. <action> — <size> <minutes> — <URGENT/priority> · \`Tab!row\``, ending with
"Which are done, no longer relevant, or deferred?"

**4b.** Parse the answer into done, cancelled and deferred. Archive in **one** call per status
with `Tab!row` refs (exact, no extra reads):

```bash
printf 'Work!12\nPersonal!4\n' | uv run --script "$BP/manage_tasks.py" batch-done
printf 'Work!9\n' | uv run --script "$BP/manage_tasks.py" batch-done --status Cancelled
```

More than ~5 rows: run with `--dry-run` first and show `would_archive`. Lines that are
ambiguous, already closed or out of range come back under `skipped`; the rest proceed.
Deferred tasks stay open and leave today's plan.

**4c.** Recalculate estimates and threads; merge or drop threads that emptied out.
**4d.** Summarize: marked done, cancelled, deferred, remaining tasks and hours (before → after).
If nothing is left, say "No tasks for today" instead of an empty plan.

`--audit` alone: Steps 0, 0b, 1, then 4, then stop.

## Step 5 — Output

Write the plan, and save it to `<plans_dir>/YYYY-MM-DD-plan.md` (overwrite on re-plan):

```markdown
# Daily Battle Plan — YYYY-MM-DD
**Open tasks:** N | **Estimated:** Xh Ym | **Threads:** N

## URGENT (overdue or due today)
| # | Task | Context | Deadline | Est. |

## Thread 1: <Context — Sub-context> (Xh Ym)
**Profile:** heavy | **Repo:** <repo>
### Cluster: <theme>
| # | Task | Owner | Priority | Est. | Dep |
<details><summary>Thread 1 starting prompt</summary>

<prompt from Step 6>
</details>

## Thread N: Quick items (Xh Ym)

## Summary
| Context | Sub-context | Tasks | Hours | Thread |
```

## Step 6 — Thread prompts (always, one per thread)

```
You are picking up Thread N of today's plan for <Context — Sub-context>.

## Context
- Project: <description from config>
- Repo: <repo> (working directory: <repo_path>)
- Thread profile: <heavy|medium|light>

## Tasks (priority order)
1. [URGENT] <task> — <size> — Deadline: <date|none> — Tracker: <Tab!row>
2. ...

## Dependencies & notes
- <chains, stale items to triage first, source meeting if any>

## First action
<one concrete step: read the ticket, run the failing test, open the branch>
```

- **Resume over restart:** when the main task is in flight with a session on this host active
  in the last two workdays, put its `resume_cmd` first and make the prompt a short continuation
  (`Continue: <next step>. Tracker: <refs>`). Otherwise use the full prompt and cite the old
  session ID.
- **Heavy:** include the repo path; if the sub-context has `issue_skill`, start with it (e.g.
  `/IssueFlow ABC-123`) for ticket work.
- **Light:** a checklist, marking which items are messages versus admin.
- Confidential contexts: ticket IDs and generic summaries only, as in the tracker.

## Step 7 — Launch (only with `--launch` or an explicit request, after the user confirms)

- Heavy with a ticket → the sub-context's `issue_skill`, in its own session or worktree-isolated agent.
- Medium → a background agent with the thread prompt.
- Light → under 30 min total, leave them to the user; otherwise one background agent.
