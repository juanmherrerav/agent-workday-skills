# Loop — fix one item, verify, repeat

Argument: `mode = tool | principle`. Default: **tool** when the repo has no
`reports/codequality/*/roadmap.md`, **principle** when it has one. The user can force either.

| | Tool mode | Principle mode |
| --- | --- | --- |
| Input | latest `summary.md` (Scan A) | `roadmap.md` (Scan C), its current phase |
| Item | one finding: one rule at one file:line | one bounded design move for the current principle |
| Steps 2–3 | skipped | mandatory: nothing is edited before confirmation |

```
┌────────────── ONE ITERATION ──────────────────────────────────────────────┐
│ 0 SELECT → 1 SAFETY NET → [2 PROPOSE → 3 CONFIRM] → 4 FIX → 5 VERIFY → 6 LOG │
└───────────────────────────────────────────────────────────────────────────┘
          repeat; session ends with the Quality Improvement Report
```

```bash
CQ="${SKILLS_HOME:-$HOME/.claude/skills}/CodeQuality/Tools"
DAY="$(date +%Y-%m-%d)"; LOG="reports/codequality/$DAY/session-log.md"; mkdir -p "$(dirname "$LOG")"
```

## Step 0 — SELECT

**Tool mode.** Open the latest `summary.md`. Take the highest-priority tool with findings, P0 →
P1 → P2, **across languages**, then open its raw output and take one finding: within P0,
credentials before code vulnerabilities before dependency CVEs; within P1, type errors before
lint before circular imports; within P2, the largest clone or dead-code block first. Record tool,
rule, file:line, message. If `summary.md` is older than the working tree, re-run Scan A first.

**Principle mode.** Read `roadmap.md`: the current phase's principle and the next bounded target
(one Extract, one class split, one dependency inversion — not the whole phase). Re-read the
target code now; the inventory may be stale.

## Step 1 — SAFETY NET (both modes)

Refactoring without tests is changing code and hoping. Establish green to green first.

1. **Check coverage of the exact lines you will touch**, using the repo's unit command scoped to
   the target (the manifest's coverage rows name the wrappers: `c8 <unit cmd>`, `pytest --cov=<module>`).
2. **Covered and green** → continue.
3. **Not covered, or unknown** → write **characterization tests** before touching production code:
   - The goal is not correctness but **locking current observable behavior**, bugs included.
   - Call the target with representative and edge inputs; assert exactly what it returns today.
   - For hard-to-reach code (network, DB, global state) introduce the **minimal seam** needed to
     test — one injected dependency, one extracted function. That seam is itself the first DIP
     step and is the only production edit allowed before step 4.
   - For sprawling output a golden-master snapshot is acceptable: record, then assert equality.
   - Run them. They must be **green** against current code. Red means the test is wrong, not the code.
4. No net possible (truly non-deterministic, no seam without a redesign) → say so; propose the
   seam as its own confirmed iteration, or mark the item deferred and SELECT the next one.

Tool-mode exception: a P0 credential removal, a formatting fix or a dead-code deletion flagged by
a tool needs no new tests; the existing suite is the net. Anything that changes a code path does.

## Step 2 — PROPOSE (principle mode only)

Present this block and **stop**:

```
PROPOSAL — Phase <n>: <Principle>  (iteration <k>)
SMELL      : <name> @ <file:lines>
PRINCIPLE  : <SRP/DRY/DIP/...> — <one line on why this violates it>
EVIDENCE   : <metric or pattern, e.g. "31% clone across 6 callers, CCN 47">
MOVE       : <named refactoring, e.g. Extract Function validate_request()>
STEPS      : 1. <small step>  2. <small step>  3. <update callers>
BLAST      : <files and callers affected; public API changes: yes/no>
SAFETY NET : <existing tests green | wrote N characterization tests, green>
EXPECTED   : <duplication 31% → <10%, ~180 LOC removed, CCN 47 → ~12>
BEHAVIOR   : preserved
Apply? (yes / adjust / skip)
```

## Step 3 — CONFIRM (principle mode only)

Proceed only on an explicit yes. **adjust** → revise and re-propose. **skip** → log it as skipped
and go back to SELECT. Never auto-apply a design move.

## Step 4 — FIX / APPLY

- One item. If you notice an unrelated smell or finding, note it for the inventory; do not fix it now.
- Smallest steps that keep tests green; run the scoped tests after each meaningful step so a
  break is localized. Prefer named, mechanical moves (Extract, Rename, Move, Introduce
  Parameter Object, Replace Conditional with Polymorphism, Inject Dependency).
- Tool-mode patterns: hard-coded secret → environment variable plus a startup check and an
  `.env.example` entry; type error → a real type, never `any` or a cast; duplication → one shared
  function and updated callers; dead code → delete (version control remembers); circular import →
  move the shared piece down a layer.
- Match the surrounding style. Keep the diff reviewable.

## Step 5 — VERIFY

1. **Behavior preserved:** the relevant suite (existing + characterization) is green. Red means
   this was not a refactor. **Revert** (`git restore <files>`), analyze, retry smaller. Never fix
   forward.
2. **Metric moved:** tool mode re-runs the single tool from the manifest row (same `run` cell,
   `$OUT` pointed at a scratch dir) and confirms the finding is gone and the count went down.
   Principle mode re-measures the principle's metric (duplication, CCN, function length, fan-out,
   "now unit-testable") and confirms the direction.
3. **Diff sanity:** read the diff. Is it cleaner, or only moved around?

## Step 6 — LOG, then REPEAT

Append to `$LOG` (one entry per iteration, never overwrite):

```markdown
### Iter <k> — <tool mode: P<x> <tool> <rule> | principle mode: Phase <n> <Principle>> — <time>
- Target: <file:lines>   Move/fix: <…>
- Safety net: <existing | +N characterization tests>
- Result: tests GREEN · <metric before → after> · LOC <±>
- Files: <touched>
- Noticed, not fixed: <…>
```

Then one line to the user, and the next item:

```
Iter <k> done — <one-line outcome>. Tests green. <metric before → after>.
Next: <next finding | next target for this principle | advance to Phase <n+1>>. Continue? (yes / pause / change plan)
```

Principle mode advances `Current phase` in `roadmap.md` when a phase's hotspots are clean.

## Stopping conditions

Tool mode: all P0 fixed, then all P1, or only cosmetic P2 remains. Principle mode: the targeted
phases are done, or remaining smells are low-leverage. Both: the user's time or scope budget is
reached, or the user says pause.

## Rollback

```bash
git status && git diff                      # see what the iteration touched
git restore <changed-files>                 # back to the last green state
<unit command>                              # confirm green again before retrying
```

A failed iteration still gets a log entry (what was tried, why it was reverted).

## Session end — Quality Improvement Report

Write `reports/codequality/<day>/quality-report.md` with the sections from SKILL.md: summary
table (lines added/removed/net, issues before → after per priority, dead-code hotspots removed,
tests before → after), code removed, code added or modified, bugs fixed, complexity delta with
ASCII bars, deferred items. Paste it in the reply. When the session is a IssueFlow remediation
cycle, it becomes the PR body and tracker comment.

## Example iterations

**Tool mode — P0 secret.** SELECT: `secretlint` flags `config.js:42` (`sk_live_…`). SAFETY NET:
existing unit suite green, no new tests needed. FIX: `const API_KEY = process.env.UPSTREAM_API_KEY`
plus a startup check and an `.env.example` line. VERIFY: unit suite green; re-run secretlint
→ 2 findings → 1. LOG: "Iter 1 — P0 secretlint config.js:42 — secret moved to env".

**Principle mode — DRY.** SELECT: roadmap phase 1, target "shared validation in 6 handlers".
SAFETY NET: create/update covered, delete not → 3 characterization tests, green. PROPOSE: Extract
Function `validate_request()`, 6 callers, no API change, expected 31% → <10% duplication. CONFIRM:
yes. APPLY: extract, switch callers one at a time, tests after each. VERIFY: suite green; jscpd
31% → 8%; ~180 LOC removed. LOG, then next target or phase 2.
