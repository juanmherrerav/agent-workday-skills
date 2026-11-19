# Deploy workflow

`INT` = `$INTEGRATION_BRANCH`, `PROD` = `$PRODUCTION_BRANCH`, `R` = `$REMOTE`, all from
`. "$IF/profile.sh"` (SKILL.md → Configuration). Full pipeline order: **Phase 2 → Phase 1 →
Phase 3**, so the PR is built on a conflict-free branch and env validation is the last gate.

---

## Phase 1 — Release PR

1. `git fetch "$R" "$PROD" "$INT"`
2. Commits being released: `git log "$R/$PROD..$R/$INT" --oneline --no-merges`. If the list is
   empty, there's nothing to release, so stop.
3. **Group by issue.** Use `ISSUE_PREFIX` (e.g. `ABC-[0-9]+`) or else the generic
   `[A-Z][A-Z0-9]+-[0-9]+`, matching on the subject, then the branch merge message. Commits
   without a key go under **Other Changes**.
   ```
   ## Changelog
   ### ABC-40
   - abc1234 feat: new layout
   ### Other Changes
   - jkl3456 chore: bump deps
   ```
4. Create or update it (one call; `pr.sh create` updates an open PR instead of duplicating):
   ```bash
   bash "$IF/pr.sh" create --head "$INT" --base "$PROD" \
     --title "Release: $INT → $PROD ($(date +%F))" <<'EOF'
   <changelog>
   EOF
   ```
5. `bash "$IF/pr.sh" view --head "$INT" --json mergeable,mergeStateStatus,statusCheckRollup`.
   If there are conflicts, go to Phase 2.

**Exit:** the PR exists, the changelog is accurate and grouped, and checks are green or none
are configured.

---

## Phase 2 — Conflicts (integration wins)

1. Work in a clean checkout of `INT`. Use a temporary worktree if the main checkout is busy:
   `git worktree add ../release-merge "$R/$INT" && cd ../release-merge`
2. `git merge "$R/$PROD" --no-edit`. If it's clean, skip to step 6.
3. `git diff --name-only --diff-filter=U`
4. Per file, **read both sides of every hunk** and then decide:

   | Detected | Action |
   | --- | --- |
   | deleted on INT, modified on PROD | `git rm <file>` |
   | INT side is a rename / extract / restructure of PROD's code | `git checkout --ours <file>` |
   | PROD has legacy naming, INT has the new convention | `git checkout --ours <file>` |
   | both sides add genuinely new, non-overlapping code | merge both by hand; if unsure, flag it |
   | anything ambiguous | **STOP** — list file + hunk + why, wait for a human |

   `--ours` is INT here because INT is checked out. **Never apply `--ours` to a whole file
   that also contains a hotfix made only on PROD.** That silently reverts the hotfix. Check
   `git log "$R/$INT..$R/$PROD" -- <file>` first.
5. `git add <resolved>`, then run the IssueFlow **Merge → Step 2 validation gate** (unit +
   preflight + e2e) in this checkout. Same gate, same rules: never push red.
6. `git commit -m "merge: $PROD into $INT for release (integration-wins)"` and
   `git push "$R" HEAD:"$INT"`
7. Re-check `bash "$IF/pr.sh" view --head "$INT" --json mergeable,mergeStateStatus`, then
   remove the temporary worktree.

**Exit:** no conflicts, `INT` pushed, PR mergeable, and every manual decision listed with
file and reason.

---

## Phase 3 — Environment parity matrix

No `$ENV_MATRIX_FILE` → report **"Phase 3 SKIPPED — no matrix"** and stop.

1. Load the matrix (`variables[]`, `sensitive_var_handling`, `runtime_endpoints`,
   `known_dead_vars`). Provider identity comes from the profile (`PREVIEW_PROVIDER`,
   `PREVIEW_SCOPE`, `PREVIEW_TEAM_ID`, `PREVIEW_PROJECT_ID`); `PREVIEW_PROVIDER` must be
   `vercel` for the steps below, otherwise report **"Phase 3 SKIPPED — no env adapter for
   $PREVIEW_PROVIDER"**.
2. **Pull both environments into a temporary directory, never the repo:**
   ```bash
   T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
   V="vercel"; command -v vercel >/dev/null || V="bunx vercel"
   SCOPE=""; [ -n "$PREVIEW_SCOPE" ] && SCOPE="--scope $PREVIEW_SCOPE"
   $V env pull "$T/prod" --environment production --yes $SCOPE --token "$VERCEL_TOKEN"
   $V env pull "$T/prev" --environment preview    --yes $SCOPE --token "$VERCEL_TOKEN"
   ```
   **Sensitive vars come back as empty strings.** That does not mean they're missing. They
   go to Tier 2.

### Tier 1 — direct (non-empty values)

| Rule | PASS | FAIL |
| --- | --- | --- |
| SAME | values identical | values differ (report both, redacted to first 4 + last 4) |
| ENV-SPECIFIC | values differ, and patterns match if given | values identical |
| PRESENT | non-empty in every `required_in` env | missing or empty |

### Tier 2 — indirect (sensitive / empty)

- **A. API metadata.**
  `curl -s -H "Authorization: Bearer $VERCEL_TOKEN" "https://api.vercel.com/v9/projects/$PREVIEW_PROJECT_ID/env?teamId=$PREVIEW_TEAM_ID"`.
  Both IDs come from the profile; if either is empty, report Tier 2A as SKIPPED.
  The var must exist with the right `target`s. For ENV-SPECIFIC it needs separate entries
  (different `id`s) for production and preview. Check that `updatedAt` is plausible.
- **B. Runtime smoke test.** If `runtime_endpoints` is set, GET each environment's endpoint
  and check `expected_fields`. They must be present, and ENV-SPECIFIC ones must differ
  between environments. This step is definitive for config the client sees.
- **C. Dead variables.** For a var set in only one environment, `git grep -n "<VAR>"` across
  the source. No references → `[INFO] dead variable`, which doesn't block. Listed
  `known_dead_vars` are INFO too.

### Report and gate

```
ENVIRONMENT PARITY REPORT — <project> — <date>
TIER 1 — DIRECT
[PASS] API_BASE_URL      SAME: match
[FAIL] AUTH_CLIENT_ID    ENV-SPECIFIC: identical in both (copy-paste?)
TIER 2 — INDIRECT
[PASS] DB_TABLE_PREFIX   API: separate entries (prod=VlBI…, preview=thvU…) + runtime OK
[INFO] LEGACY_FLAG       preview-only, no code references
RUNTIME
[PASS] production <endpoint>   auth.domain=<prod>, enableAuth=true
SUMMARY  total N · pass N · info N · fail N
GATE: CLEARED — safe to deploy        |  GATE: BLOCKED — <n> failure(s), see remediation
```

**BLOCKED** if any Tier 1 FAIL, any var missing from the API, or any runtime check that fails
or returns unexpected values. INFO never blocks. Every FAIL gets a concrete remediation
(which env, which var, what value shape).

**Exit:** report shown, gate decision explicit, temp dir gone (`trap`), and no env files in
the repo (`git status --short` clean of `.env*`).

---

## Failure modes

| Failure | Recovery |
| --- | --- |
| `gh` not authenticated | `gh auth login` |
| project not linked | `vercel link --scope <team> --yes` |
| "token is not valid" / "scope does not exist" | token expired or personal-scoped, so mint a team-scoped one |
| "Could not retrieve Project Settings" | stale `.vercel/project.json`, so re-link |
| PR creation fails, no commits | `git log "$R/$PROD..$R/$INT"` is empty, so nothing to release |
| ambiguous conflict | stop, report it, wait for a human |
| gate BLOCKED | report it, and do **not** merge the release PR |
