# Analyze — one recording, full pipeline

Inputs: a recording path (or several parts of one meeting), the context, and optionally chat
messages, an attendee list or the meeting's purpose.

```bash
MA="${SKILLS_HOME:-$HOME/.claude/skills}/MeetingAnalysis/Tools"
eval "$(python3 "$MA/meeting_config.py" env <context>)"     # MEETINGS_DIR, RECORDINGS_ARCHIVE, CONFIDENTIAL, LANGUAGE, …
TMP="$(mktemp -d)"
```

## Step 0 — Relocate out of any repo

```bash
if git -C "$(dirname "<input>")" rev-parse --show-toplevel >/dev/null 2>&1; then
  mkdir -p "$RECORDINGS_ARCHIVE" && mv "<input>" "$RECORDINGS_ARCHIVE/"   # continue from the new path
fi
```

## Step 1 — Validate and transcribe

Confirm the file exists, get its duration (`ffprobe` if present), then:

```bash
uv run --script "$MA/transcribe.py" "<input>" --out-base "$TMP/transcript" --lang "$LANGUAGE" --model "$TRANSCRIPTION_MODEL"
```

Use a fixed `--lang` only for single-language meetings; `auto` detects. If the stats line shows
`cpu/int8` on a machine with a GPU, say so: it is roughly ten times slower.

## Step 2 — Frames (video only)

SKILL.md § Frames, into `$TMP/frames`. Default: keep none.

## Step 3 — Combine parts

Several files for one meeting → one transcript, each part's timestamps offset by the cumulative
duration before it, segments labeled `partN`.

## Step 4 — Names and summary

Correct names (SKILL.md § Names), then write the summary (SKILL.md § Output format) from the
corrected transcript plus any context given. Date from the filename or metadata. Action items
are specific and assignable, each with owner, priority (High / Medium / Low) and deadline.
Takeaways are strategic implications, not a replay.

## Step 5 — Save

Destination: the user's explicit path, else `$MEETINGS_DIR/YYYY-MM-DD-<slug>/`, else ask. Write
the summary. Unless `CONFIDENTIAL=true`, move the transcripts in as
`YYYY-MM-DD-<slug>-transcript.txt` / `.json` (from `$TMP/transcript.txt` / `.jsonl`). If the
folder exists already (for example from a notes import), append a `## From the recording`
section with only what is new instead of overwriting.

## Step 6 — Tracker

SKILL.md § Action items → tracker. Build one JSONL, `batch-add --dry-run`, show, then run it.
A tracker failure is reported but does not undo the analysis.

## Step 7 — Archive the source

Confirm the recording is in `$RECORDINGS_ARCHIVE` (move it there if it is elsewhere and the user
agrees), and write `<title> _ <date> _ PROCESSED.txt` beside it:

```
Meeting: <title>
Date: YYYY-MM-DD
Processed: YYYY-MM-DD
Original files: <names>
Summary: <absolute path to the summary>
Transcription: faster-whisper <model> (<device>)
```

Never delete an original recording.

## Step 8 — Verify and clean up

Run SKILL.md § Verification on the meeting folder and show the output (it must be empty). Then
`rm -rf "$TMP"` and report the summary path, tasks added, and the archive location.

**Quality checks:** transcript covers the full duration (within 10%); every speaker heard is in
the attendee line; no action item is vague.
