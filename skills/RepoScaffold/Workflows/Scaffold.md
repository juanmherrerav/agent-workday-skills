# Scaffold — make a repo agent-ready

Output: the files in the SKILL.md table, filled from this repo, plus a IssueFlow profile.
Everything is shown as a diff before it is committed. Runtime files are never committed.

```bash
ROOT="$(git rev-parse --show-toplevel)"
RS="${SKILLS_HOME:-$HOME/.claude/skills}/RepoScaffold/Templates"
IF="${SKILLS_HOME:-$HOME/.claude/skills}/IssueFlow/Tools"
```

## Step 0 — Detect, don't ask yet

Collect facts and show them as a table before writing anything. The profile facts (issue
pattern, branches, commands, env files, preview, gates) come from **IssueFlow → Setup's
detection table**; that table is the single source and is not repeated here. Scaffold adds
only what the profile does not hold:

| Fact | Where to look |
| --- | --- |
| Stack(s) | lockfiles and manifests: `pyproject.toml`/`uv.lock`, `package.json`, `go.mod`, `pom.xml`/`build.gradle*`, `*.csproj`, `Gemfile`, `Cargo.toml` |
| CI provider and its jobs | `.github/workflows/*.yml`, `.gitlab-ci.yml`, `azure-pipelines.yml`, `bitbucket-pipelines.yml`, `.circleci/` |
| Where PR templates live for this forge | GitHub `.github/`, GitLab `.gitlab/merge_request_templates/` |
| Existing `CLAUDE.md`, `.claude/`, `docs/TESTING.md`, `CONTRIBUTING.md`, PR template | `ls` |
| Coverage gate, if any | the CI coverage job or the test config |

Only people and process facts are asked: stakeholder, review channel, IDE, permission mode.

## Step 1 — The `.claude/` split

```bash
mkdir -p "$ROOT/.claude/local" "$ROOT/.claude/release"
```

- Write `.claude/README.md` from `claude-README.md.template`. Keep the permission decision
  honest: write the mode the user chose and why, dated.
- Append `gitignore.block` to `.gitignore` **once** (look for the marker line first). Then
  confirm `.env*` is already ignored, and warn if it isn't.
- Verify: `git -C "$ROOT" check-ignore -q .claude/local/x .claude/settings.local.json CLAUDE.local.md`.

## Step 2 — Per-machine permissions

Ask which mode this machine runs in, then write `.claude/settings.local.json` from the
template. `bypassPermissions` is the mode IssueFlow was designed around: edits are not the
validation surface, the gates are. If the user prefers prompts, keep `defaultMode` out and
leave the `allow` list. Add `additionalDirectories` only for paths outside the repo the
workflow must touch. **Note for the user:** when a project-level settings file exists, the
parent profile's tool permissions do not cascade into it, so this file must be complete.

## Step 3 — `CLAUDE.md` routing table

- **No `CLAUDE.md`:** write it from `CLAUDE.md.template` with every token filled from Step 0.
- **Existing `CLAUDE.md`:** insert the "Working an issue" and "Repo automation map" sections
  at the top and leave the rest alone. Show the diff.
- The commands block must contain only commands that already run in the repo, and the same
  ones that go into the profile in Step 7.

## Step 4 — PR template

GitHub: `.github/pull_request_template.md`. GitLab: `.gitlab/merge_request_templates/Default.md`.
Bitbucket/Azure: ask where PR descriptions are templated, or skip and say so. If one exists,
add the missing **Validation** and **Impact assessment** sections rather than replacing it.

## Step 5 — CI shape comparison

Read the repo's pipeline and compare it with `ci-pipeline.md`. Produce a gap table:

```
stage         present?  blocking?  notes
lint          yes       yes        ruff + eslint, no type check → add mypy/tsc
security      no        —          add dependency audit, report-only first
unit          yes       yes        single runtime version
coverage      no        —          add threshold gate (ask for the number)
e2e-fixture   no        —          suite needs a fixture mode first (see TESTING.md)
summary       no        —          add the fan-in job and make it the required check
nightly       no        —          optional
```

**Do not rewrite CI.** Report the gaps. Write YAML only when the user asks, and then one stage
at a time. Record the exact commands of the lint/type job: they become `PREFLIGHT_CHECKS`.

## Step 6 — Testing and contributing docs

- `docs/TESTING.md`: write from the template if absent. If present, add any missing section
  (tag taxonomy, API modes, coverage gate, stale-test rule) and leave the rest.
- `CONTRIBUTING.md`: same approach. The branch rule (`<KEY>` exactly, no slug) and the
  two-gate approval vocabulary must be present somewhere the team reads.

If the e2e suite has no tag taxonomy or fixture mode, say so plainly in the report. Those are
code changes the team makes; the docs describe the target state.

## Step 7 — Profile (IssueFlow Setup)

Run the IssueFlow **Setup** workflow now. The values gathered in Step 0 fill most keys. Then
prove the commands in the main checkout: `UNIT_CMD`, every `PREFLIGHT_CHECKS` entry,
`SERVE_CMD` + `curl` on `HEALTH_PATH`, and `validate-env.sh` against the main checkout.

## Step 8 — Verify and hand over

```bash
bash "$IF/profile.sh"                                    # loads, prints effective profile
bash "$IF/preflight.sh" "$ROOT"                          # same result CI would give
git -C "$ROOT" check-ignore -q .claude/local/x && echo ignored
git -C "$ROOT" status --short                            # no runtime files staged
```

Report, in this order: files written, files amended (with the diff), CI gaps, commands proven,
anything SKIPPED and why. Commit only when the user agrees, and never include
`.claude/settings.local.json`, `CLAUDE.local.md`, env files or `.claude/local/`.
