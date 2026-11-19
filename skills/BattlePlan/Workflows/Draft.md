# Draft — unattended morning draft (`/BattlePlan --draft`)

Runs headless from a scheduler; nobody is there to answer.

- Run Plan Steps 0, 0b, 1, 2, 3, 5 and 6. **Skip the Step 4 questions:** put the pre-filled
  audit (4a format) at the top of the draft instead.
- **Never write to the tracker** (no `batch-done`, `add`, `sweep`) and never launch threads.
- Write only `<plans_dir>/YYYY-MM-DD-draft-<host>.md`, first line:
  `Draft ready: N open tasks · X likely done · Y in flight · Z untracked sessions · built HH:MM on <host>`.
- If the pull fails (auth, quota, file locked), still write the draft from the recap and say
  the tracker was unreachable.
- `/BattlePlan <context> --draft` limits both the pull and the recap's `--context`.

## Scheduling

`Tools/run_draft.sh` wraps the draft run: it skips weekends and days this host already drafted,
fast-forwards the plans repo first and commits only the draft after (when `plans_git_sync` is
on), and sends a desktop notification with the header line.

```bash
RD="${SKILLS_HOME:-$HOME/.claude/skills}/BattlePlan/Tools/run_draft.sh"
$RD --check                      # alias, context, time, paths, agent; runs nothing
$RD --install                    # weekdays at BATTLEPLAN_DRAFT_TIME (default 08:00)
$RD --install --context work     # one context only (default: hosts.<alias>.draft_context)
$RD --force                      # run once now
$RD --uninstall
```

| Platform | Scheduler | Log |
| --- | --- | --- |
| macOS | launchd agent | `~/Library/Logs/battleplan-draft.log` |
| Linux / WSL | systemd user timer, `Persistent=true` (a missed slot runs at next start) | `~/.local/state/battleplan/draft.log` |

**Agent.** By default the run is `claude -p "/BattlePlan --draft"` with a read-only allowlist:
tracker writes (`manage_tasks.py`) and sub-agents are denied, and writes are limited to
`plans_dir`. For another agent, set `BATTLEPLAN_AGENT_CMD` to a command that takes the prompt
as its first argument and enforces an equivalent read-only policy.

**Gotchas.** WSL timers only fire while WSL runs. The install captures the current `PATH` so
`uv` and the agent CLI resolve inside the unit; re-run `--install` after moving either.
