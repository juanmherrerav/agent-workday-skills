# Setup — contexts, folders, notes providers, tracker

Output: the config at `${MEETING_ANALYSIS_CONFIG:-~/.config/agent-skills/MeetingAnalysis/config.json}`,
an optional roster file, and the folders it names. Ask; never invent paths, accounts or people.

## Step 1 — Interview (one message)

1. **You.** Your name and the aliases people use for you in meetings (for "my items").
2. **Contexts.** Which areas have meetings (e.g. `work`, `client-x`, `personal`)? For each:
   - **Meeting folder** for summaries (any folder; usually inside a notes repo).
   - **Confidential?** Employer or client material going to a personal folder or tracker → yes.
   - **Language** (`en`, `es`, … or `auto` for mixed meetings).
   - **Notes provider:** `google-meet` (Gemini notes in a Workspace account; give the account),
     `pasted` (you paste transcripts from any notetaker), or `none` (recordings only).
   - **Tracker sub-context** for your items, plus optional regex rules (admin, HR, onboarding →
     an admin sub-context).
3. **Recordings archive.** A folder **outside every git repo** where processed recordings go
   (e.g. `~/Recordings/processed`). Optional per-context override.
4. **Unattended inbox** (optional, per context): an ingest home outside git (gets `Inbox/`,
   `Work/`, `Processed/`, `Failed/`), interval, working hours, and a cloud-synced folder where
   your meeting platform drops recordings (Google Drive for desktop `Meet Recordings`, a OneDrive
   or Dropbox folder). The runner copies from it and never deletes there.
5. **Tracker.** `BattlePlan` (must be set up, and each sub-context must exist in its config) or `none`.
6. **Transcription model.** `turbo` (default, fast) or `large-v3` (slower, slightly better).

## Step 2 — Write the files

1. Start from `Templates/config.example.json`; delete what does not apply. Show the JSON, then
   write it.
2. Roster (optional, recommended): `roster_file` with lines like
   `Dana Lee: Dana, Dena, Dana Li`. Names only; no contact details needed.
3. **Ignore media in the notes repo** as a second line of defence (the invariant is the first):

   ```gitignore
   *.mp4
   *.mov
   *.mkv
   *.webm
   *.avi
   *.wav
   *.mp3
   *.m4a
   ```

## Step 3 — Verify

```bash
MA="${SKILLS_HOME:-$HOME/.claude/skills}/MeetingAnalysis/Tools"
python3 "$MA/meeting_config.py" check                 # ok: true
uv run --script "$MA/transcribe.py" --help            # first run downloads deps; model downloads on first transcription
```

- `google-meet` contexts: confirm the agent has Google Drive and Docs connectors **signed in
  with that account** (search for one recent "Notes by Gemini" doc). Optional: Gmail and
  Calendar for fallback discovery and attendee lists.
- Inbox contexts: `bash "$MA/run_ingest.sh" --context <name> --check`, then `--install`.
- Tracker: `uv run --script "${SKILLS_HOME:-$HOME/.claude/skills}/BattlePlan/Tools/manage_tasks.py" list-tabs`
  shows every sub-context named in this config.

Report the contexts, folders, providers, and whether the inbox job is installed.
