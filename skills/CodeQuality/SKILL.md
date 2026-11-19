---
name: CodeQuality
description: Code quality loop for any repo, seen through two lenses — a tool lens (linters, type checkers, security, dead-code and duplication scanners; fix by P0 security → P1 correctness → P2 maintainability) and a principle lens (SOLID + Clean Code smells; one principle at a time, propose → confirm → apply behind characterization tests). One manifest of free local tools, one scan, one fix loop, one mandatory Quality Improvement Report. USE WHEN improve code quality, analyze code, fix linting, reduce duplication, add types, security scan, test coverage, refactor, improve code design, apply SOLID, clean code refactor, reduce complexity, kill code smells, make code maintainable, refactor legacy code, single responsibility, dependency inversion, remediation sprint, install quality tools, quality baseline, smell report, refactoring roadmap, what should we fix first. NOT FOR the issue lifecycle, branches, PRs or merging (use IssueFlow; its Remediation workflow calls this skill to pick and scope the work).
---

## Customization

**Optional personal preferences:** `${AGENT_SKILLS_CONFIG:-~/.config/agent-skills}/CodeQuality/PREFERENCES.md`.

If that file exists, read and apply it; otherwise proceed with skill defaults. Personal preferences only: anything
that is a fact about a repo or product belongs in that repo (its `.claude/workflow-profile.sh`
or tool configs), never here.

# CodeQuality

One loop, two lenses. The loop is always detect → pick **one** item → fix behind tests → verify →
repeat. The **tool lens** fixes what scanners flag, in priority order, with existing tests as the
guard. The **principle lens** fixes what makes code hard to change (god classes, duplication,
untestable cores), one SOLID / Clean Code principle at a time, and never applies a design move
without showing it first. Both lenses read the same tool manifest, write to the same report
directory, and end with the same Quality Improvement Report.

## Two lenses

|  | Tool lens | Principle lens |
| --- | --- | --- |
| Driver | scanner output (`summary.md`) | design smells mapped to [Principles.md](Principles.md) (`smell-inventory.md`, `roadmap.md`) |
| Unit of work | one finding: one rule at one file:line | one principle on one bounded hotspot: one Extract, one class split, one dependency inversion |
| Order | P0 security → P1 correctness → P2 maintainability | leverage ladder (below), adjusted per repo |
| Autonomy | fix, then show the diff | **propose → confirm → apply**; nothing is edited before approval |
| Safety net | existing tests stay green | characterization tests written **first** when the target is untested |
| Metric | fewer findings, tool re-run clean | duplication %, cyclomatic complexity, function length, fan-in/out, "now unit-testable" |
| Pick it when | lint/type/security debt, CI red, "make the scanners happy" | code that resists change; a remediation sprint's structural tier |

## The loop

```
SCAN → SELECT → SAFETY NET → [PROPOSE → CONFIRM] → FIX → VERIFY → REPORT → REPEAT
                             └─ mandatory in principle mode, skipped in tool mode ─┘
```

## Workflow routing

| Trigger | Workflow | Produces |
| --- | --- | --- |
| "install quality tools", "set up code quality" | [Workflows/Install.md](Workflows/Install.md) | manifest tools installed and verified |
| "scan", "baseline", "analyze code quality", "smell report", "what should we fix first", "refactoring roadmap" | [Workflows/Scan.md](Workflows/Scan.md) | `summary.md` (A), `smell-inventory.md` (B), `roadmap.md` (C) |
| "improve code quality", "fix lint", "quality loop", "fix [finding]" | [Workflows/Loop.md](Workflows/Loop.md) in **tool** mode | fixes, `session-log.md`, report |
| "refactor", "apply SOLID", "clean this up", "start the loop" | [Workflows/Loop.md](Workflows/Loop.md) in **principle** mode | fixes, `session-log.md`, report |
| "clean up this repo" with no qualifier | Scan A + B + C, then Loop in principle mode | all of the above |
| "remediation sprint", "remediation cycle" | IssueFlow Remediation owns the branch, PR and merge; Scan scopes the cycle, Loop executes it | one PR per cycle |

Loop picks its mode by itself when none is given: **tool** when no `roadmap.md` exists for the
repo, **principle** when one does. The user can force either.

## The manifest

`Tools/tools.tsv` is the **only** list of tools in this skill. Tab-separated, one row per tool
and language: `language category priority tool install run notes`, with `language` in
js | python | yaml, `category` in lint | format | types | security | deadcode | duplication |
complexity | deps | coverage, `priority` in P0 | P1 | P2. Both scripts read it; the workflows
never list tools inline. To add or drop a tool, edit one row.

| Script | Reads from the manifest | Does |
| --- | --- | --- |
| `Tools/install-quality-tools.sh [--dry-run] [lang ...]` | `install` cells of the chosen languages | detects languages (package.json → js; pyproject.toml, requirements.txt or `*.py` → python; `*.yaml`/`*.yml` → yaml); installs js tools as devDependencies with the repo's package manager (lockfile → npm/pnpm/bun), python and yaml tools with `uv pip install` or `pip`; `npm:`/`pip:` prefixes override the channel, `-` installs nothing |
| `Tools/run-quality-baseline.sh [--dry-run] [lang ...]` | `run` cells | runs every tool into `reports/codequality/<YYYY-MM-DD>-<HHMMSS>/`, substituting `$OUT` (report dir), `$SRC` (`QUALITY_SRC_DIRS`, default `src` if it exists else `.`), `$PM` and `$NPX`; a tool that is not installed is MISSING, one that crashes is FAILED, neither stops the run; writes `summary.md` with per-tool status, parsed issue counts and P0/P1/P2 totals; prints the report path |

Rows whose `run` is `-` (coverage tools) are installed but not run by the baseline: coverage is
measured in the Loop, scoped to the target. Every tool is free and runs locally; `npm audit`,
`pip-audit` and `checkov` reach the network only for their vulnerability databases.

## Leverage ladder (principle lens default order)

1. **Names** — code you cannot read, you cannot safely change. Cheap, unblocks everything.
2. **DRY / duplication** — removes the most code at the lowest risk; exposes hidden abstractions.
3. **Small functions** — Long Method → Extract; one level of abstraction per function.
4. **SRP** — split classes and modules that change for more than one reason.
5. **OCP / DIP** — invert dependencies, add seams; high impact, higher risk, safety net first.
6. **ISP / LSP** — fat interfaces and broken substitutability; need the seams from step 5.

Scan part C adjusts this order to the actual inventory (leverage = impact ÷ risk; see Principles.md Part 3).

## Non-negotiables

- **One item per iteration.** One finding, or one principle on one bounded target. Small, reviewable diffs.
- **Behavior preserving.** Structure changes, behavior does not. If behavior must change, stop and flag it: that is a feature, not a fix.
- **Green to green.** Tests pass before and after. Red after a change means revert, never fix forward.
- **Characterization tests first** when the lines to be touched are untested. No net, no refactor.
- **Propose before applying** any design move (principle mode). Tool mode may fix directly, then shows the diff.
- **P0 → P1 → P2** for tool findings, across languages, never by language.
- **Never weaken a test or a lint rule** to get green. Stale tests move to the new correct behavior; rules are satisfied in code.
- **Boy Scout, bounded.** Leave touched files cleaner, but do not scope-creep past the current item.
- **Evidence, not opinion.** Name the rule or principle, and a metric where one exists.

## Output artifacts

All under `reports/codequality/` (git-ignored):

| File | Written by |
| --- | --- |
| `<YYYY-MM-DD>-<HHMMSS>/summary.md` + raw tool output | `run-quality-baseline.sh` (Scan A) |
| `<YYYY-MM-DD>/smell-inventory.md` | Scan B |
| `<YYYY-MM-DD>/roadmap.md` | Scan C |
| `<YYYY-MM-DD>/session-log.md` | Loop, one entry per iteration |
| `<YYYY-MM-DD>/quality-report.md` | Loop, at the end of the session (below) |

## Quality Improvement Report (mandatory)

Every Loop session ends with this report, in either mode. It is the deliverable alongside the
code change, and the body of the PR or tracker comment when the work ships through IssueFlow.

| Section | Content |
| --- | --- |
| Summary table | lines added / removed / net; issues before → after per priority; dead-code hotspots removed; tests before → after (count, all green) |
| Code removed | file, what, lines, risk |
| Code added or modified | file, what, lines, purpose |
| Bugs fixed | severity, description, root cause (only if any surfaced) |
| Complexity delta | max and mean cyclomatic complexity before → after, with an ASCII bar per hotspot |
| Deferred | items seen but out of scope, and why |
