# Merge — post-approval pipeline

Argument: `KEY`. Rebase → re-validate → land on `$INTEGRATION_BRANCH` → resolve the issue →
clean up.

**Precondition:** explicit stakeholder approval (or developer approval when
`$STAKEHOLDER_GATE=false`). If approval is uncertain, STOP and ask.

```bash
IS="${SKILLS_HOME:-$HOME/.claude/skills}/IssueSync/Tools"; IF="${SKILLS_HOME:-$HOME/.claude/skills}/IssueFlow/Tools"; . "$IF/profile.sh"; if_require_key "$KEY"
```

## Resolve the worktree and branch

Find the row in `$LEDGER_FILE`, or glob `$WORKTREE_DIR/<key-lower>-*`. Set `WT` and
`BRANCH="$(git -C "$WT" rev-parse --abbrev-ref HEAD)"`. If there's no worktree or branch,
STOP because there's nothing to merge.

## Step 1 — Rebase onto the latest integration branch

```bash
git -C "$IF_ROOT" fetch "$REMOTE"
git -C "$WT" rebase "$REMOTE/$INTEGRATION_BRANCH"
```

On conflicts, resolve them to preserve the issue's intended behavior, re-run Step 2, then
`git rebase --continue`. Never `--skip` a conflicted commit blindly.

## Step 2 — Validation gate (HARD pre-push gate)

This is **the** gate. Remediation Step 6 and ProductionDeployment Phase 2 run this step, not
their own copy. Pushing to the integration branch triggers CI, so it must be green first:

```bash
cd "$WT" && bash -c "$UNIT_CMD" \
  && bash "$IF/preflight.sh" "$WT" \
  && bash "$IF/e2e.sh" "$WT"
```

If preflight fails, run it with `--fix`, commit, re-rebase if needed, and repeat. **Never push a
red preflight.**

## Step 3 — Land it

`MERGE_STRATEGY=ff-only` (default):
```bash
git -C "$WT" push --force-with-lease "$REMOTE" "$BRANCH"            # PR shows the rebased commits
git -C "$WT" push "$REMOTE" "$BRANCH:$INTEGRATION_BRANCH"           # remote accepts fast-forward only
# refresh the main checkout only if it sits on the integration branch with a clean tree
if [ "$(git -C "$IF_ROOT" rev-parse --abbrev-ref HEAD)" = "$INTEGRATION_BRANCH" ] \
   && git -C "$IF_ROOT" diff --quiet HEAD; then
  git -C "$IF_ROOT" pull --ff-only "$REMOTE" "$INTEGRATION_BRANCH"
fi
```
This never checks out anything in the main checkout. If the push is rejected as non-fast-forward,
the integration branch moved during validation. Go back to Step 1, and never force.

`MERGE_STRATEGY=squash`: `bash "$IF/pr.sh" merge --head "$BRANCH" --squash`. The forge must
report checks green first.

Close the PR if landing didn't: `bash "$IF/pr.sh" close --head "$BRANCH"`.

## Step 4 — Resolution comment + transition

Write the **Resolution** comment (Conventions → Tracker comment templates) to
`$(bash "$IS/issue-sync.sh" worklog "$KEY")`, replacing the review comment, with the SHAs,
commit list and validation results from Steps 2–3. Then:

```bash
bash "$IS/issue-sync.sh" comment "$KEY"
bash "$IS/issue-sync.sh" transitions "$KEY"        # list first, then ASK the user which state
bash "$IS/issue-sync.sh" transition "$KEY" "<state>"
```

If the user declines a transition, still post the comment.

## Step 5 — Cleanup

```bash
bash "$IF/cleanup.sh" "$WT" --delete-remote
```

This stops the server, removes the folder from `$IDE_WORKSPACE_FILE` (reload the IDE window),
removes the worktree, deletes the local and remote branch, and frees the ledger row.

Report: merged into `$INTEGRATION_BRANCH` (SHA), issue state, worktree and branch removed.
