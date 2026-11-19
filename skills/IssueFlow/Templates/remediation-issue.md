---
name: remediation-issue
description: Tracker issue body for a recurring code remediation sprint. Tiered (dead code → consolidation → consistency → structural), gated by the repo profile's unit, full e2e and CI-parity preflight commands. Cycles run with the IssueFlow Remediation workflow and are scoped with the CodeQuality Scan.
---

# Code Remediation Sprint — issue template

Copy the body below into a new issue; fill in `[N]` and trim the tiers to the sprint. The gates
are the profile's, so nothing here names a stack: `$UNIT_CMD` is whatever the repo profile says,
"full e2e" is IssueFlow `e2e.sh`, "preflight" is IssueFlow `preflight.sh`. Each cycle is run
with the IssueFlow **Remediation** workflow and scoped with the CodeQuality **Scan**.

For `$TRACKER=jira` convert the body to wiki markup before posting (`h2.`, `||header||` tables,
`*bold*`, `{{mono}}`, `#`/`*` lists); IssueSync `push` posts it. Markdown trackers take it as is.

---

## Title

`General Code Remediation Sprint [N]`

## Fields

| Field | Value |
| --- | --- |
| Type | Chore |
| Priority | Medium |
| Labels | `tech-debt`, `code-quality` |
| Estimate | Tiers 1–3: small · Tier 4 included: medium |

## Description

Reduce technical debt through targeted, behavior-preserving cleanups. The issue is a **basket**:
it stays open across cycles, each cycle is one focused PR that merges on its own with developer
approval. Work is tiered so the highest-impact, lowest-risk changes land first, every tier is
validated by the existing test safety net before merge, and each cycle ends with a Quality
Improvement Report.

## Remediation tiers

| Tier | Focus | Risk | Gate |
| --- | --- | --- | --- |
| 1 — Dead code and artifacts | unreachable code, debug scaffolding, stray prints, unused imports, discarded return values | none, no behavior change | unit (`$UNIT_CMD`) |
| 2 — Consolidation (DRY) | duplicated blocks extracted to one shared function or module | low, same behavior, fewer call sites | unit + full e2e (`e2e.sh`) |
| 3 — Consistency and lint | import hygiene, type annotations, silent error swallowing replaced by structured logging | low, cosmetic and observability | CI-parity preflight (`preflight.sh`) |
| 4 — Structural (SRP / SOLID) | extract method, reduce cognitive complexity, invert a dependency | medium, behavioral equivalence required | unit + full e2e + preflight, characterization tests first |

## Acceptance criteria

- [ ] **Scan produced** — CodeQuality Scan (tool summary and, for Tier 4, smell inventory) lists the targets with file:line references.
- [ ] **Tiered plan approved** — the implementer presents the tier breakdown for the cycle before writing code; a human approves the scope.
- [ ] **No behavioral regression** — unit (`$UNIT_CMD`) green before and after each tier.
- [ ] **Full e2e green** — IssueFlow `e2e.sh` passes with zero failures attributable to the change (Tiers 2 and 4).
- [ ] **CI-parity preflight green** — IssueFlow `preflight.sh` passes locally before push (every tier).
- [ ] **Quality Improvement Report delivered** — lines added/removed and net, issues before/after, dead-code hotspots removed, bugs found and fixed, complexity delta, deferred items.
- [ ] **No scope creep** — functions over ~100 lines and public contract changes get their own issue.

## Principles applied

1. **Boy Scout, bounded** — touched files leave cleaner; untouched files stay untouched.
2. **One category per commit** — each commit is one tier's kind of change, atomic and revertable.
3. **Characterization tests first** — an untested path gets a behavior-locking test before it is refactored.
4. **No speculation** — fix only what the scan identified; no design for hypothetical needs.
5. **Observable over silent** — swallowed exceptions become logged ones; ad-hoc prints become logger calls.
6. **Propose before structural moves** — Tier 4 changes are shown (smell, principle, move, blast radius) and confirmed before they are applied.

## Definition of done (per cycle)

- Cycle PR merged into the integration branch with developer approval (no stakeholder gate).
- Unit, full e2e and preflight green on the merged head.
- Quality Improvement Report posted as the PR body and as the issue's `Cycle <N>` comment.
- Items seen but deferred are listed in the comment for the next cycle.

## Explicitly out of scope

- Feature work or new functionality.
- Functions over ~100 lines and public API or response-shape changes (dedicated issue).
- Dependency upgrades or version bumps.
- New coverage for untested legacy code, except characterization tests required by a Tier 4 move.

## Process

1. **Scope** — CodeQuality Scan: part A for Tiers 1–3, parts B and C for Tier 4.
2. **Cycle** — IssueFlow Remediation: fresh worktree off the integration branch, CodeQuality Loop
   (tool mode for Tiers 1–3, principle mode for Tier 4), gates, developer approval, PR, merge, log.
3. **Report** — Quality Improvement Report in the PR and the cycle comment.
4. **Repeat or close** — next cycle, or transition the issue when the basket is empty.
