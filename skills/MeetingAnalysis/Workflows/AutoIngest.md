# AutoIngest — unattended inbox

Recurring ingestion of every meeting in a context, from two sources:

| Source | Arrives as | Found by |
| --- | --- | --- |
| Meeting notes (`notes.provider: google-meet`) | Notes / Transcript docs | this workflow, through ImportNotes Steps 0–6 |
| Recordings (ad-hoc calls, local captures, platform recordings) | a media file dropped in `<ingest home>/Inbox/`, or copied there from `drive_recordings_dir` | `run_ingest.sh`, which transcribes before calling this workflow |

`Tools/run_ingest.sh` does the deterministic work (copy, claim, transcribe, archive, verify,
notify) and calls the judgment step:

```
/MeetingAnalysis ingest <context> --unattended [--local-only] [--dry-run-tracker]
```

## Folder contract (outside git)

```
<ingest home>/
├── Inbox/        drop recordings here (+ optional sidecar "<same basename>.md": title, attendees, context)
├── Work/<id>/    claimed: media, meta.json, transcript.txt, transcript.jsonl, transcribe.json, context.md.
│                 THIS workflow writes DONE.json here.
├── Processed/<YYYY-MM-DD-slug>/   moved here by the runner once DONE.json exists
├── Failed/       transcription failed, or 3 runs without DONE.json
└── .state/       hashes.tsv (dedupe), drive-copied.tsv, last-run.json (written by THIS workflow), lock
```

Recording and verbatim transcript stay in `Processed/`. Only the summary enters the meetings folder.

## Unattended rules

- **Never ask.** Decide, and record decisions in `last-run.json` so the user can undo them.
- **No confirmation gates:** ImportNotes' candidate confirmation and the tracker dry-run are
  skipped; `batch-add` dedupe makes re-runs safe. With `--dry-run-tracker`, run only
  `batch-add --dry-run` and put the would-add list in `last-run.json`.
- **Skip personal meetings** (HR, payroll, benefits, performance reviews, social calls): no
  summary, ledger line with `"skipped": "<reason>"`, listed in `last-run.json`.
- **Files through Write/Edit only.** Bash is limited to `uv run`, `date`, `ls`. The tracker batch
  goes to `<ingest home>/.state/tracker-batch.jsonl` (the runner deletes it).
- **No commits, pushes or messages.** The runner's allowlist enforces it.
- **Fail closed per item:** one failure never stops the others.

## Step 1 — Notes (skip with `--local-only` or when `notes.provider` is not `google-meet`)

ImportNotes Steps 0–6 under the rules above. Window start: latest ledger `meeting_date` **minus
2 days** (docs can land after a later meeting was imported; ledger ids make the overlap free).
Nothing new is normal: discovery queries only, no reads.

## Step 2 — Recordings in `Work/`

For each `Work/<id>/` with `transcript.txt` and no `DONE.json`:

1. Read `meta.json`, the sidecar if any, and `transcript.txt` (the `.jsonl` only for exact times).
2. **Date and title:** sidecar → original file name (platform recording names usually carry
   title and date; OS screen recorders carry a timestamp) → `meta.json.file_created`. Title from
   the sidecar, the file name, or the main topic.
3. **Same meeting as a notes doc** (same date, matching title, in the ledger or this run)? Append
   `## From the recording` to that summary with only what the notes missed. Never a second folder.
4. **Names:** roster, then sidecar attendees or the calendar event at that time. Low confidence → `Name (?)`.
5. **Summary** per SKILL.md, header:
   `**Source:** local recording \`<original_name>\` (transcribed locally, <model>/<device>; media and transcript archived outside the repo)`.
6. **Tracker:** your items, source `Meeting: <title> YYYY-MM-DD (recording)`, in the same single
   `batch-add` as Step 1.
7. **Ledger:** `{"file_id": "local:<sha16>", …, "source": "recording"}`.
8. **`DONE.json` last:** `{"folder": "YYYY-MM-DD-<slug>", "summary": "<path>", "tasks_added": 2, "merged_into_existing": false}`.
   An unusable recording (silence, music, wrong file) still gets `{"folder": null, "note": "<why>"}`
   so it stops being retried.

## Step 3 — Run report

Always write `<ingest home>/.state/last-run.json`:

```json
{"ran_at": "<ISO>", "headline": "2 meetings ingested · 3 tasks added",
 "notes_imported": [{"date": "…", "title": "…", "folder": "…", "tasks_added": 1}],
 "recordings": [{"id": "…", "folder": "…", "tasks_added": 2, "merged_into_existing": false}],
 "skipped": [{"title": "…", "reason": "…"}],
 "tracker": {"added": 3, "already_tracked": 1, "dry_run": false}, "errors": []}
```

`headline` becomes the desktop notification; `nothing new` keeps the runner silent. End with a
3-line answer: imported, tasks added, anything to look at.

## Operation

```bash
R="${SKILLS_HOME:-$HOME/.claude/skills}/MeetingAnalysis/Tools/run_ingest.sh"
$R --context work --check      # resolved paths, synced folder present, job installed
$R --context work --force      # one run now
$R --context work --local --force
$R --context work --status
$R --context work --install    # launchd (macOS) / systemd user timer (Linux), every ingest.interval_min in ingest.hours
$R --context work --uninstall
```

- Transcription is local; a one-hour recording holds the run lock for 30–120 min depending on
  hardware, and later runs skip until it finishes.
- `ingest.allowed_tools` lists the read-only connector tools the unattended agent may call. Add
  nothing that sends, creates, shares or deletes.
- Another agent: set `MEETING_AGENT_CMD` (takes the prompt as `$1`) and give it an equivalent
  read-only policy.
