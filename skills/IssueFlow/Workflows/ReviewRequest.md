# ReviewRequest — stakeholder QA table

Arguments: issue keys (`ABC-49 ABC-45`) or "all open PRs". Output: one table a
non-technical reviewer can work through.

```bash
IS="${SKILLS_HOME:-$HOME/.claude/skills}/IssueSync/Tools"; IF="${SKILLS_HOME:-$HOME/.claude/skills}/IssueFlow/Tools"; . "$IF/profile.sh"
```

## Input

- **"all open PRs" / empty:**
  `gh pr list --base "$INTEGRATION_BRANCH" --state open --json number,title,headRefName,url`.
  Pull the issue keys out of the branch names and titles with `$ISSUE_PATTERN` (drop the
  `^…$` anchors when you search).
- **Keys given:** validate each one with `if_require_key`.

## Gather, per issue

1. **Title:** the PR title, or the tracker summary.
2. **Type:** Story / Bug / Task / Research, from the tracker issue type or the PR labels.
3. **Reviewer:** `gh pr view <n> --json reviewRequests --jq '.reviewRequests[].login'`, else
   the tracker assignee, else `$STAKEHOLDER`, else ask.
4. **Preview:** `bash "$IF/preview-url.sh" "<headRefName>"`. Use `BRANCH_URL` and fall back
   to `COMMIT_URL`. If `PREVIEW_PROVIDER=none`, write "local / staging".
5. **How to test:** use the steps in the PR body, else derive them from the acceptance
   criteria. Write 3–5 numbered steps a non-technical person can follow, each as
   *action → what you should see*.
6. **Expected feedback:**
   - Story: "Approve if behavior matches expectations, or report specific issues."
   - Bug: "Confirm the bug no longer happens in the described scenario."
   - Research: "Feedback on quality and usefulness; closes after review."

## Output

```markdown
# QA Status Tracker — <date>

| Issue | Type | Reviewer | Preview | How to Test | Expected Feedback |
|--------|------|----------|---------|-------------|-------------------|
| KEY: Title | Story | Name | [Preview](url) | 1. … → …<br>2. … → … | … |
```

Use one row per issue, sorted by key, with `<br>` between steps and clickable preview
links.

## Delivery: ask the user

1. **Where?** Print here (default), write a scratch file, post one comment per issue
   (IssueSync, wiki markup: convert the row to `||h||` / `|c|`), or `$REVIEW_CHANNEL` via MCP
   if one is connected.
2. **Adjust?** Offer to refine the test steps before it goes to stakeholders.
