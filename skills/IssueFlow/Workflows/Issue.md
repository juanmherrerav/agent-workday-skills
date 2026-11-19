# Issue — full lifecycle for one issue

Argument: `KEY` (must match `$ISSUE_PATTERN`).

This is the **authoritative, ordered** procedure. Don't improvise, skip, or reorder steps. If
a step's preconditions aren't met, stop and report. Steps 6 and 7.5 are hard human gates.

```bash
IS="${SKILLS_HOME:-$HOME/.claude/skills}/IssueSync/Tools"; IF="${SKILLS_HOME:-$HOME/.claude/skills}/IssueFlow/Tools"
. "$IF/profile.sh"; if_require_key "$KEY"
```

---

## Resume (check FIRST)

Conventions → Resume. Run **Merge** only on explicit stakeholder approval (Conventions →
Approval vocabulary).

## Step 1 — Name the terminal tab

```bash
printf '\033]0;%s\007' "$KEY <one-line summary>"
```

Best-effort. If the terminal ignores OSC titles, tell the user. State the title.

## Step 2 — Read the issue

Refresh it, then read it (never trust a stale cache):

```bash
bash "$IS/issue-sync.sh" pull "$KEY" && cat "$(bash "$IS/issue-sync.sh" cache "$KEY")"
```

Extract acceptance criteria, scope boundaries, and linked issues. Summarize them back. If the
issue is already Resolved/Closed/Done, stop and confirm before proceeding. With
`$TRACKER=none` the tool exits 3; ask the user for the acceptance criteria.

## Step 3 — Provision the worktree

```bash
IS="${SKILLS_HOME:-$HOME/.claude/skills}/IssueSync/Tools"; IF="${SKILLS_HOME:-$HOME/.claude/skills}/IssueFlow/Tools"; . "$IF/profile.sh"
NAME="<key-lower>-<slug>"
BRANCH="$(if_branch "$KEY" "<slug>")"
bash "$IF/provision.sh" "$NAME" "$BRANCH" auto "<one-line purpose>"
```

The script creates the worktree off the latest `$REMOTE/$INTEGRATION_BRANCH`, copies the env
files, claims ports, runs setup, verifies the bootstrap, writes the ledger row, and adds the
worktree to the IDE. **Non-zero exit → surface the error and STOP.** Never work in a
half-provisioned worktree.

Tell the user the worktree path and its ports. Then check the copied env files:

```bash
bash "$IF/validate-env.sh" "$WT"
```

Missing required vars are reported now, before a test can fail for the wrong reason.
Placeholders mean live-tagged scenarios will not run on this machine. Report `ENV: SKIPPED`
as such when the profile lists no vars.

## Step 4 — Plan

From the Step 2 acceptance criteria, list the files to touch, the behavior change, and which
tests prove it. Scope it to this issue only. Present the plan before writing code.

## Step 5 — Implement and validate (iterate until green)

Work **inside the worktree** (`git -C "$WT"`, or `cd "$WT" && …` within one command). Loop:

1. Make the smallest coherent change toward the plan.
2. **Unit:** `cd "$WT" && bash -c "$UNIT_CMD"`
3. **Full e2e on a fresh server:** `bash "$IF/e2e.sh" "$WT"`. The server always gets torn down.
4. **CI-parity gate:** `bash "$IF/preflight.sh" --fix "$WT"`. It must exit 0. **Commit
   whatever `--fix` changed.** If a check still fails, fix the code and never weaken the rule.

- **5.1 Stale tests.** If a test contradicts the issue's new requirement, update the test to
  the requirement. Never weaken a test just to make it pass.
- **5.1b Stale fixtures.** If an e2e failure is an upstream contract change (new field,
  different shape) rather than a bug, re-record with `bash "$IF/e2e.sh" --record "$WT"`
  (needs real credentials), review the `$FIXTURES_DIR` diff for secrets, and commit it with
  its own message.
- **5.2 Iterate** until the requirements are met, no test is stale, and unit + e2e +
  preflight are all green (any SKIPPED gate is named as such). Commit incrementally with
  descriptive messages.

## Step 6 — Developer validation gate (HARD STOP)

Launch the app for the human (skip if `SERVE_CMD` is empty):

```bash
bash "${SKILLS_HOME:-$HOME/.claude/skills}/IssueFlow/Tools/serve.sh" "$WT"
```

Non-zero exit → surface the log path it printed and STOP. Otherwise announce and **wait**:

```
✅ READY FOR DEVELOPER VALIDATION: KEY — <summary>
Branch: <branch>   Worktree: <path>
Changes: <key files / behavior>
Tests: Unit ✅ N/N · e2e ✅ N/N · Preflight ✅      (or "SKIPPED" per gate)
👉 App is RUNNING — open: <url from serve.sh>   (stop: kill -9 $(lsof -ti:<port>))
```

**6.1** For every issue the human reports, go back to Step 5 (full validation every time),
then re-run `serve.sh` so they validate the latest build. Stay in this gate until they
explicitly approve.

## Step 7 — Push, PR, preview, tracker, message

**Trigger:** developer approval (Conventions → Approval vocabulary). This step **never** merges.

**Pre-push sync check:**
```bash
git -C "$WT" fetch "$REMOTE" "$BRANCH" 2>/dev/null
git -C "$WT" log --oneline "$REMOTE/$BRANCH"..HEAD 2>/dev/null | wc -l   # >0 → unpushed commits
```
`pr.sh create` updates an open PR instead of opening a second one, so run it on every pass:

```bash
git -C "$WT" push -u "$REMOTE" "$BRANCH"
bash "$IF/pr.sh" create --head "$BRANCH" --title "KEY: <short summary>" <<'EOF'
## Summary
<1–3 bullets>

## Issue
KEY

## Validation
- Unit: ✅ N/N
- Full e2e: ✅ N/N
- CI-parity preflight: ✅

## How to review
<Preview link once it appears, else local steps>
EOF
```

### 7.1 Preview URL
`bash "$IF/preview-url.sh" "$BRANCH" --wait 300`. Report the PR URL and the **branch** preview
URL. Verify the deploy contains the change (see Conventions → Previews).

### 7.2 Tracker comment
Write the **Review** comment (Conventions → Tracker comment templates) to
`$(bash "$IS/issue-sync.sh" worklog "$KEY")`, then `bash "$IS/issue-sync.sh" comment "$KEY"`.

### 7.3 Transition (optional)
`bash "$IS/issue-sync.sh" transitions "$KEY"`, ask the user which one, then
`bash "$IS/issue-sync.sh" transition "$KEY" "<name>"`.

### 7.4 Stakeholder message
Draft it for `$REVIEW_CHANNEL` with the Conventions template and the branch preview URL. Show
it to the user, who posts it.

## Step 7.5 — Stakeholder review gate (HARD STOP)

If `$STAKEHOLDER_GATE=false`, go straight to the **Merge** workflow. Otherwise:

```
🔄 AWAITING STAKEHOLDER REVIEW: KEY
PR: <pr-url>    Preview: <branch-preview-url>
Tracker comment posted with review instructions.
👉 Re-run IssueFlow for KEY, or say "stakeholder approved" when approval comes in.
```

This is a **session boundary**. Resume logic will pick it up.

**7.5.1 Changes requested:** go back to Step 5, fix, push (`--force-with-lease` only if you
rebased), re-fetch the preview (commit URLs go stale), and post an updated tracker comment.
Stay in this gate.

## Step 8 — Merge

Only on **explicit** stakeholder approval, run [Merge.md](Merge.md).
