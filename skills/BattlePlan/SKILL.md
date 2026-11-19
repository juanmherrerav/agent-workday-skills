---
name: BattlePlan
description: Daily execution plan from a task tracker (local CSV, Excel workbook, or Google Sheet). Groups open tasks by context and sub-context, estimates time, finds parallel threads, and writes ready-to-paste starting prompts per thread. Starts from yesterday instead of from zero — recaps the previous day's agent sessions and git commits, pre-fills the audit, and offers resume commands. Includes an end-of-day handoff (--close), an unattended morning draft (--draft), and task management (add, done, cancel, restore, sweep, batch import). USE WHEN plan my day, daily plan, battle plan, what should I work on, close the day, end of day handoff, morning draft, task overview, standup prep, prioritize tasks, add a task, mark task done, set up battleplan, configure task tracker.
---

# BattlePlan

Reads every open task from a tracker, reconciles it with what actually happened since the last
plan, and turns it into a short list of parallel work threads, each with a starting prompt a
fresh agent session can pick up cold.

## Step 0 — every invocation starts here

```bash
BP="${SKILLS_HOME:-$HOME/.claude/skills}/BattlePlan/Tools"
uv run --script "$BP/setup_tracker.py" check
```

- **`success: false` or no config** → run [Workflows/Setup.md](Workflows/Setup.md) first. Never
  invent a tracker, a tab name or a context.
- Config lives at `$BATTLEPLAN_CONFIG`, else `${AGENT_SKILLS_CONFIG:-~/.config/agent-skills}/BattlePlan/config.json`.
  It holds the owner, the tracker backend, the plans directory and the context hierarchy.
  The skill directory never holds personal data, so it can be shared and updated freely.

## Routing

| Invocation | Workflow |
| --- | --- |
| "set up battleplan", no config, new tracker, new context | [Workflows/Setup.md](Workflows/Setup.md) |
| `/BattlePlan [context] [--mine] [--skip-audit] [--launch]`, `--audit` | [Workflows/Plan.md](Workflows/Plan.md) |
| `/BattlePlan --close` | [Workflows/Close.md](Workflows/Close.md) |
| `/BattlePlan --draft` (unattended), scheduling the draft | [Workflows/Draft.md](Workflows/Draft.md) |
| `--add`, `--done`, `--cancel`, `--restore`, `--sweep`, `batch-add`, importing tasks from tickets or meetings | [Workflows/Tasks.md](Workflows/Tasks.md) |

## The day loop

```
 evening                     scheduled (weekdays)          morning
 /BattlePlan --close  ──▶   /BattlePlan --draft   ──▶   /BattlePlan
 done, next step per        reads tracker + handoff +    opens the draft; you only
 thread, resume commands    sessions; writes a draft     confirm exceptions, then go
```

Each step works when the one before it was skipped: no handoff → the recap falls back to the
previous workday; no draft → `/BattlePlan` builds the plan live. Files live in `plans_dir`:

| File | Written by | Holds |
| --- | --- | --- |
| `YYYY-MM-DD-handoff-<host>.md` | `--close` | First line `Closed: <ISO 8601 with offset> on <host>`, then done, in flight (next step + resume command), carry-overs |
| `YYYY-MM-DD-draft-<host>.md` | `--draft` | Plan plus pre-filled audit proposals; nothing written to the tracker |
| `YYYY-MM-DD-plan.md` | `/BattlePlan` | The confirmed plan, so `--close` can compare plan with reality |

`<host>` is an alias (`mac`, `wsl`, `linux` or `$BATTLEPLAN_HOST_ALIAS`), never the hostname,
because these files may be shared across machines. Session IDs resume only on the machine that
created them: show other hosts' next steps, never their resume commands.

**Multi-machine:** set `plans_git_sync: true` and put `plans_dir` inside a git repo. Commits
touch only the file just written (`git commit -- <path>`) after `fetch` + `merge --ff-only`.
Never stash, reset or clean: other sessions may hold uncommitted work in that repo. If the
fast-forward fails, commit locally and say the push is pending.

## Tools

| Script | Does |
| --- | --- |
| `setup_tracker.py check\|init` | Validate the config and backend; `init` creates missing tabs with headers (idempotent) |
| `pull_tasks.py [context] [--mine]` | Open tasks as JSON with computed urgency, deadlines, owner kind, dependencies, tickets |
| `recap_sessions.py --tasks pull.json [--since auto] [--context X]` | Agent sessions + git commits since the last handoff, linked to tasks by ticket ID |
| `manage_tasks.py add\|batch-add\|mark-done\|mark-cancelled\|batch-done\|restore\|sweep\|list-tabs` | Every tracker write; JSON out, `--dry-run` everywhere it writes |
| `run_draft.sh --install\|--check\|--force\|--uninstall` | Schedules the unattended morning draft (launchd / systemd user timer) |
| `tracker.py` | Storage backends (`csv`, `xlsx`, `gsheets`) and config loading; imported by the others |

All scripts are `uv run --script` files with inline dependencies (PEP 723): no virtualenv to
manage. Tests: `uv run --with pytest --with openpyxl pytest tests/`.

## Non-negotiables

- **The recap proposes, the human confirms.** Nothing is marked done from evidence alone.
- **Exact row references for writes.** After a pull, archive with `Tab!row` refs in one
  `batch-done` call; never fall back to substring search when the row is known.
- **Confidential contexts** (`"confidential": true`) get ticket IDs and short generic summaries
  only, in the tracker and in handoffs. `manage_tasks.py` rejects IPs, URLs and the context's
  `forbidden_patterns`.
- **Never launch threads without explicit confirmation.**
- **Tracker commands run sequentially** — Google Sheets allows ~60 reads/minute and each
  command reads every tab.

## Dependencies

`uv` (`brew install uv`, or `curl -LsSf https://astral.sh/uv/install.sh | sh`). `git` for the
recap's commit scan. Google Sheets backend only: a service-account JSON key with editor access
to the sheet. Session recap reads Claude Code transcripts (`~/.claude*/projects`); with other
agents it reports git activity and handoffs only.
