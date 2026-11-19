# Scan — measure, diagnose, plan (no code changes)

Three parts, each with its own output file. Part A is enough to start the Loop in tool mode.
Parts B and C are required before the Loop runs in principle mode. "Clean up this repo" with no
qualifier means all three. Nothing in this workflow edits production code.

```bash
CQ="${SKILLS_HOME:-$HOME/.claude/skills}/CodeQuality/Tools"
DAY="$(date +%Y-%m-%d)"; mkdir -p "reports/codequality/$DAY"
```

| Part | Question it answers | Output |
| --- | --- | --- |
| A — tool scan | what do the scanners flag, and how much of each priority | `reports/codequality/<day>-<time>/summary.md` |
| B — design scan | which design smells explain the pain, where, how risky | `reports/codequality/<day>/smell-inventory.md` |
| C — roadmap | which single principle to enforce first, on which hotspots | `reports/codequality/<day>/roadmap.md` |

## Part A — tool scan

### A1. Run the baseline

```bash
QUALITY_SRC_DIRS="src server"  bash "$CQ/run-quality-baseline.sh"      # SRC override; default src or .
bash "$CQ/run-quality-baseline.sh" js python                             # or force languages
```

The script runs every manifest tool for the detected languages, never stops on a failing tool,
and prints the report path last. Each tool leaves its raw output (JSON where the tool supports
it) next to `summary.md`.

### A2. Read summary.md

| Status | Meaning | Action |
| --- | --- | --- |
| OK, with a count | the tool ran; count is parsed findings | feeds the P0/P1/P2 totals |
| OK, `?` | the tool ran but its output has no parser | open the output file and count by hand |
| MISSING | binary not installed | run Install, or accept the gap and say so |
| FAILED | exit 126/127, or non-zero exit with nothing parseable | read `<tool>.stderr`; usually a missing config (tsconfig, eslint config) |
| SKIPPED | manifest row with `run = -` (coverage) | measured in the Loop, scoped to the target |

### A3. Report part A

Five to eight lines: languages, P0/P1/P2 totals, the top finding per priority with file:line,
the FAILED and MISSING rows, and the report path. Then offer tool-mode Loop ("fix the highest
finding") or continue to part B.

## Part B — design scan (the Smell Inventory)

Read [Principles.md](../Principles.md) first: it is the vocabulary, every row of the inventory
cites a principle from it.

### B1. Scope and test state

- Target: whole repo, a package, or a directory. Default: repo root.
- Languages: from part A, or from manifests and extensions when part A was skipped.
- Tests: framework, location, how to run them, current pass state. This sets the refactor risk
  later; an untested hotspot costs a characterization-test step before anything else.

### B2. Evidence: metrics as signal, not verdict

Use part A's raw output when it exists (duplication, complexity, dead code). Add the churn
signal, which no scanner gives:

```bash
git log --since="6 months ago" --name-only --pretty=format: | sort | uniq -c | sort -rn | head -20
```

Files that are **both complex and frequently changed** are the prime targets. Flag them.

### B3. Read the hotspots through the principle lens

For each top hotspot (highest complexity, most duplicated, highest churn), read the code and
classify every dominant smell:

| Column | How to fill it |
| --- | --- |
| Smell | the name from Principles.md (God Class, Long Method, Feature Envy, ...) |
| Location | `file:lines`; a glob when the smell repeats (`api/handlers/*.py`) |
| Principle | SRP / OCP / LSP / ISP / DIP, or Names / Functions / DRY / Coupling |
| Evidence | the metric or pattern: "31% clone across 6 callers", "CCN 47, 420 LOC" |
| Severity | 1 cosmetic → 5 actively dangerous |
| Blast radius | fan-in: who depends on it; public API yes/no |
| Tested? | covered / partial / none, for the exact lines |

Do not catalog every line. Find the handful of principle violations that explain most of the pain.

### B4. Score

Per Principles.md Part 3: **Impact** rises with churn, blast radius, smells unblocked and code
volume removable; **Risk** rises with missing tests, wide fan-in, framework or serialization
coupling, and public API surface. **Leverage = Impact ÷ Risk.**

### B5. Write smell-inventory.md

```markdown
# Smell Inventory — <target> — <date>

## Summary
- Languages: <…>  Files scanned: <n>  Tests: <pass/fail/none>  Baseline: <path to summary.md>
- Dominant violations: <e.g. DRY (28% dup), SRP (3 god classes), DIP (core depends on HTTP directly)>

## Inventory (sorted by leverage)
| # | Smell | Principle | Location | Evidence | Severity | Impact | Risk | Leverage | Tested? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Copy-paste validation in 6 handlers | DRY | api/handlers/*.py | jscpd 31% clone | 4 | High | Low | high | partial |
| 2 | OrderService does pricing + persistence + email | SRP | order_service.py:1-420 | 420 LOC, CCN 47 | 5 | High | High | mid | none |
| 3 | Domain calls the HTTP client directly | DIP | pricing.py:88 | untestable without network | 4 | Med | High | mid | none |

## Hotspot map (churn × complexity)
<files that are both hot and complex>

## Notes for the roadmap
<which smells unblock others; where a safety net is mandatory before touching>
```

### B6. Report part B

Three to six bullets: dominant violations and the one or two files that hurt most. Then offer
part C.

## Part C — roadmap

Input: `smell-inventory.md`. Output: one ordered plan and one ready-to-run first iteration.

### C1. Group by principle

Collapse inventory rows into principle buckets (Names, DRY, Functions, SRP, OCP, DIP, ISP, LSP,
Coupling). Per bucket: aggregate leverage (sum of its rows) and the maximum risk inside it.

### C2. Order with the leverage ladder, then adjust

Default order: Names → DRY → Small functions → SRP → OCP/DIP → ISP/LSP. Move buckets when the
inventory says so. Tie-breakers between similar leverage: lower risk first; the one that unblocks
most other smells; the one concentrated in high-churn files.

### C3. Pick the first principle and bound the first iteration

State the choice and the reasoning. Scope the first iteration to **one** bounded target for that
principle (one Extract, one class split, one dependency inversion), not the whole bucket.

> Example: First principle **DRY**. Six request handlers share a 31% duplicated validation block.
> Highest leverage (removes ~180 LOC), low risk (partial tests, narrow blast radius). First
> iteration: extract the shared validator used by the create/update/delete handlers.

### C4. Write roadmap.md

```markdown
# Refactoring Roadmap — <target> — <date>

## Sequence (one principle per phase)
| Phase | Principle | Why here | Target hotspots | Risk | Safety net | Est. iterations |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | DRY | highest leverage, low risk, unblocks SRP | api/handlers/* | Low | existing tests | 1–2 |
| 2 | Small functions | hotspots unreadable | order_service.py | Med | characterization tests first | 2–3 |
| 3 | SRP | god class, daily churn | order_service.py | High | tests from phase 2 | 3–4 |
| 4 | DIP | untestable domain | pricing.py | High | characterization tests first | 2 |

## Current phase: 1
## First iteration (ready to execute)
- Principle: DRY
- Target: <files/functions>
- Planned move: Extract Function `validate_request()`; update 6 callers
- Safety net: tests exist for create/update; write a characterization test for delete first
- Blast radius: 6 callers, no public API change
- Expected delta: duplication 31% → <10% in this module; ~180 LOC removed

## Stop conditions
<e.g. "phases 1–3 done", "user time budget", "high-leverage phases only">
```

The Loop reads `Current phase` and `First iteration`, and advances the phase marker itself.

### C5. Report part C

The sequence in three to five bullets, then: "Next: Loop in principle mode. It builds the safety
net, shows the exact move and diff scope, and applies only after you confirm."
