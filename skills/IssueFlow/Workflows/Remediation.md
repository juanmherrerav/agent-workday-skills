# Remediation — one cycle of a sprint-basket issue

Argument: `KEY`. A remediation issue is a **basket**: it stays open across many cycles, each
producing one focused PR that merges on its own. Cycles have **no stakeholder gate**, so
developer approval is enough to merge. The issue is created from
[Templates/remediation-issue.md](../Templates/remediation-issue.md); the work inside a
cycle is picked with the CodeQuality skill (tool findings or design smells).

```bash
IS="${SKILLS_HOME:-$HOME/.claude/skills}/IssueSync/Tools"; IF="${SKILLS_HOME:-$HOME/.claude/skills}/IssueFlow/Tools"; . "$IF/profile.sh"; if_require_key "$KEY"
WT="$(if_wt_path "<key-lower>-remediation")"
```

## Resume

Conventions → Resume, with the cycle branch `<branch>-cycle-<N>` as the PR head. An open
cycle PR means "merge it (Step 6) or abandon it"; uncommitted work in `$WT` means "continue
or discard".

## Step 1 — Cycle number

```bash
N=$(( $(bash "$IS/issue-sync.sh" count-comments "$KEY" '^h2\. Cycle') + 1 ))
```

With `$TRACKER=none`, count merged PRs titled `KEY (Cycle` instead.

## Step 2 — Fresh branch, reused worktree

```bash
BRANCH="$(if_branch "$KEY" remediation)-cycle-$N"
bash "$IF/provision.sh" "$(basename "$WT")" "$BRANCH" auto "$KEY remediation" --reuse
```

The first cycle provisions the worktree. Later cycles keep it and its ports, refuse
uncommitted work, point it at the new branch off the **latest** integration branch, and re-run
setup because dependencies may have moved.

## Step 3 — Scope the cycle

Ask what goes in. If the user has no preference, propose the next item from the issue's tier
list, items flagged in earlier cycle comments, or a CodeQuality Scan finding. A cycle must be:

- **Coherent:** one PR's worth of related change.
- **Bounded:** finishable in one sitting.
- **Safe:** no user-facing behavior change unless explicitly agreed.

Get agreement before implementing.

## Step 4 — Implement and validate

Loop inside `$WT`: smallest change → `bash -c "$UNIT_CMD"` → `preflight.sh --fix "$WT"`
(commit what it changes) → commit. Update stale tests to the new correct behavior and never
weaken them. Run `e2e.sh` too if the cycle touched anything user-visible.

## Step 5 — Developer gate (HARD STOP)

```
✅ CYCLE <N> READY: KEY — <summary>
Branch: <branch>   Worktree: <path>
Changes: <files / behavior>
Tests: Unit ✅ N/N · Preflight ✅ · e2e ✅ N/N (or SKIPPED: not user-visible)
👉 Approve to merge, or request changes.
```

## Step 6 — PR and land (on developer approval)

```bash
git -C "$WT" push -u "$REMOTE" "$BRANCH"
bash "$IF/pr.sh" create --head "$BRANCH" --title "KEY (Cycle <N>): <summary>" <<'EOF'
## Summary
<bullets>

## Issue
KEY — remediation cycle <N>. Developer-approved; no stakeholder review by design.

## Validation
- Unit: ✅ N/N · Preflight: ✅ · e2e: ✅ N/N or SKIPPED (not user-visible)
EOF
```

Then run **Merge** Steps 1–3 exactly as written (rebase → validation gate → land). Skip
Merge Steps 4–5: the cycle log and the close-out below replace them.

## Step 7 — Log the cycle

Append the **Cycle** comment (Conventions → Tracker comment templates) to
`$(bash "$IS/issue-sync.sh" worklog "$KEY")`, then `bash "$IS/issue-sync.sh" comment "$KEY"`.
Append, never overwrite: the `h2. Cycle` headings are the cycle counter.

## Step 8 — Close out the cycle

```bash
bash "$IF/cleanup.sh" "$WT" --keep-worktree --delete-remote
```

Stops the server, detaches the worktree onto the latest integration branch, deletes the cycle
branch locally and remotely, and keeps the worktree and its ledger row for the next cycle.

```
🔄 CYCLE <N> COMPLETE: KEY — merged into $INTEGRATION_BRANCH, logged.
👉 1. Next cycle   2. Close the issue   3. Done for now (issue stays open)
```

- **Next cycle:** back to Step 1.
- **Close:** `issue-sync.sh transitions KEY`, pick the close path from the output (Stories may
  lack "Resolved"), `issue-sync.sh transition KEY <name>`, then `bash "$IF/cleanup.sh" "$WT"`.
- **Done for now:** leave everything as it is.
