# CI pipeline shape (provider-agnostic)

This is the pipeline the IssueFlow gates were designed against. It is a **shape**, not YAML:
compare the repo's pipeline with it, list the gaps, and let the team decide what to add.

## Triggers

- Push and pull request to the **integration** and **production** branches.
- Concurrency group per workflow + ref, cancel in progress (a new push supersedes the old run).
- Nightly workflow: scheduled on weekdays, on push to the integration branch, and manual.

## Stages

| Stage | Purpose | Blocking | Local mirror |
| --- | --- | --- | --- |
| **lint** | lint + format check + type check for **every** language in the repo, in a fixed order | yes | `PREFLIGHT_CHECKS` 1:1, same order |
| **security** | dependency vulnerability audit per package manager; upload the report | report-only at first (`continue-on-error`), graduate to blocking once clean | none |
| **unit** | unit tests across a runtime version matrix, `fail-fast: false` | yes | `UNIT_CMD` |
| **coverage** | unit tests with coverage, threshold gate, upload to the coverage service (`fail_ci_if_error: false`) | yes | none |
| **e2e-fixture** | create an env file with **placeholder secrets**, start the app in fixture mode, wait on the health route, run `not @live-api and not @wip`; upload screenshots on failure | yes | `E2E_CMD` through `e2e.sh` |
| **summary** | fan-in job that `needs` all of the above, runs `if: always()`, and fails if any blocking stage failed | the one **required status check** | none |
| **nightly** (separate workflow) | full non-`@wip` suite in fixture mode, reports + screenshots as artifacts | report | `e2e.sh` |

### Why placeholder secrets

The e2e-fixture stage writes `KEY=test-key` for every required credential so the app boots and
fixture mode replays recorded responses. The same placeholder list is `ENV_PLACEHOLDER_VALUES`
in the profile, which is why `validate-env.sh --production` rejects them.

### Why one summary job

Branch protection should require exactly one check. Adding a stage then means editing the
pipeline, not the protection rules, and `if: always()` on the summary makes partial failures
visible instead of "skipped".

## Branch protection that matches the merge strategy

| Branch | Rules |
| --- | --- |
| production | required check = summary · 1 approval · up to date before merge · no direct push |
| integration | required check = summary · up to date before merge (fast-forward only lands) |

"Up to date before merging" is what makes the IssueFlow Merge rebase mandatory rather than
optional.

## Provider mapping

| Concept | GitHub Actions | GitLab CI | Azure Pipelines |
| --- | --- | --- | --- |
| stage dependency | `needs:` | `needs:` / `stages:` | `dependsOn:` |
| run even if upstream failed | `if: always()` | `when: always` | `condition: always()` |
| non-blocking stage | `continue-on-error: true` | `allow_failure: true` | `continueOnError: true` |
| matrix | `strategy.matrix` | `parallel.matrix` | `strategy.matrix` |
| artifacts | `actions/upload-artifact` | `artifacts.paths` | `PublishPipelineArtifact` |
| schedule | `on.schedule.cron` | pipeline schedules (UI) | `schedules:` |
| cancel superseded runs | `concurrency.cancel-in-progress` | `interruptible: true` | `batch: true` on CI trigger |

## Lock-step rule

The lint stage and `PREFLIGHT_CHECKS` change in the **same commit**. A preflight that is
greener than CI is worse than no preflight, because it teaches people to trust it.
