# Close — end-of-day handoff (`/BattlePlan --close`)

Two minutes at the end of the day so tomorrow starts warm.

```bash
BP="${SKILLS_HOME:-$HOME/.claude/skills}/BattlePlan/Tools"
uv run --script "$BP/pull_tasks.py" > "${TMPDIR:-/tmp}/bp-pull.json"
uv run --script "$BP/recap_sessions.py" --tasks "${TMPDIR:-/tmp}/bp-pull.json" --since "$(date +%F)"
```

1. **Read** today's `<plans_dir>/YYYY-MM-DD-plan.md` if it exists.
2. **Propose, in one message:** planned tasks that look done (with evidence), in-flight tasks
   with a one-line next step each (from the session's `last_assistant` / `last_prompt`),
   untracked work worth adding, and planned tasks nobody touched.
3. **One confirmation** ("ok" or corrections). Then archive done rows with one `batch-done`
   call (`Tab!row` refs), and add confirmed untracked work with `batch-add`
   (`"source": "Session YYYY-MM-DD"`).
4. **Write** `<plans_dir>/YYYY-MM-DD-handoff-<host>.md` (host = the recap's `host` field). With
   `plans_git_sync`, commit and push only that file (SKILL.md § The day loop).

```markdown
Closed: 2026-11-05T18:40:00-03:00 on <host>
# Handoff — YYYY-MM-DD (host: <host>)
## Done today
- ABC-44 PR #192 opened · Work!20 (archived)
## In flight
### Product — ABC-44 follow-up report
- Next step: address review comments on PR #192, then re-run the suite
- Resume: `cd ~/dev/my-app && claude --resume acafffd1-…`
- Tracker: Work!24
## Carry over (untouched)
- Work!23 — reason if known
## Notes for tomorrow
- Waiting on: <person or team> for <thing>
```

The `Closed:` line must be first: the next recap's `--since auto` reads it, because file
modification times are meaningless after a sync. Confidential contexts: ticket IDs and generic
summaries only, no hostnames, customer names or internal URLs.
