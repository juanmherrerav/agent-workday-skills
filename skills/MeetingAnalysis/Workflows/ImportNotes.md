# ImportNotes — meetings that already have notes

No recording, no GPU: the meeting platform or a notetaker already transcribed it. Two providers:

| Provider | Source | Needs |
| --- | --- | --- |
| `google-meet` | "Notes by Gemini" and "Transcript" docs in a Google Workspace account | Agent connectors for Google Drive + Docs, signed in with `notes.account`; Gmail and Calendar optional |
| `pasted` | Any notetaker (Otter, Fireflies, Zoom AI, Teams Copilot, a teammate's tool) | The user pastes the transcript or summary into chat |

Invocations: `/MeetingAnalysis import <context>` (everything new since the ledger),
`--since YYYY-MM-DD`, `--dry-run` (list docs and would-add tasks, write nothing). Also
reachable as `/BattlePlan --import-meetings <context>`.

**Ledger:** `<meetings_dir>/.notes-ledger.jsonl`, one line per imported source:

```json
{"file_id": "<drive id | pasted:YYYY-MM-DD-slug | local:<sha16>>", "title": "…", "meeting_date": "YYYY-MM-DD",
 "folder": "YYYY-MM-DD-<slug>", "imported_at": "YYYY-MM-DD", "tasks_added": 3, "source": "gdoc|pasted|recording"}
```

## Step 0 — Preflight (`google-meet`)

1. Load the Drive tools (deferred tools: search "google drive"). Missing or unauthorized → stop
   and ask the user to connect Google Drive with `notes.account`. No other fallback for reading.
2. **Account check:** results must belong to the profile's account or its domain. A different
   account → stop; importing the wrong account's meetings is worse than importing nothing.
3. Window start: `--since`, else the latest `meeting_date` in the ledger, else
   `notes.backfill_start`.

## Step 1 — Discover

Drive search uses `title` and `modifiedTime` (RFC 3339, `Z`). Pass `excludeContentSnippets: true`,
follow `nextPageToken`, drop repeated ids:

```
title contains 'Notes by Gemini' and modifiedTime > '<start>T00:00:00Z'
title contains 'Transcript' and mimeType = 'application/vnd.google-apps.document' and modifiedTime > '<start>T00:00:00Z'
```

- Include docs **shared with** the user: notes are owned by the organizer.
- **Shortcuts are duplicates:** keep the `application/vnd.google-apps.document` hit, drop
  `application/vnd.google-apps.shortcut`.
- **Fallback when Drive search is unavailable:** Gmail `from:gemini-notes@google.com after:YYYY/MM/DD`
  (each email links the doc), or Calendar event attachments; read by id with Docs.
- Parse title and date: `<title> - YYYY/MM/DD HH:MM <TZ> - Notes by Gemini`, transcripts
  `<title> (YYYY-MM-DD HH:MM <TZ>) - Transcript`; fall back to the created date.
- Pair notes and transcript with the same title and date. Skip ledger ids, dates before the
  window, and empty templates.

Interactive runs: show the candidates (date, title, notes/transcript present) and confirm before
reading; a backfill can be dozens of docs and the user may drop some (HR, social calls).

**A meeting the search did not find** (ad-hoc call without an invite, so notes went only to the
room owner): search the meeting code everywhere the agent can read (Drive full text, Gmail, chat
tools, Calendar for that day) to get the real date and owner, and check the user's memory of the
date against it. No notes after a few hours → tell the user who probably has them and offer to
draft a short message asking for them. Never send it without a yes.

## Step 1 (`pasted`)

Ask for the paste if it is not in the conversation, plus title, date and attendees if the paste
lacks them. Treat the paste as the notes doc for Steps 3–6. Never save the paste itself.

## Step 2 — Read

Read the Notes doc with comments included (otherwise the tail can be cut). Read the transcript
only when the notes lack next steps or are unclear about ownership. Notes structure: Summary,
Details (topic bullets, often timestamped), Suggested next steps (`- [ ] <Name> will <action>.`).

## Step 3 — Extract action items

1. Every suggested next step, plus explicit commitments the notes missed ("can you…", "I'll take that").
2. Owner per item, corrected against the roster and attendee list.
3. Yours only for the tracker (SKILL.md § Action items → tracker); everyone's in the summary.
4. Rewrite for confidential contexts: `TICKET-ID: generic summary`, nothing internal.

## Step 4 — Summary

`<meetings_dir>/YYYY-MM-DD-<slug>/YYYY-MM-DD-<slug>-summary.md`, SKILL.md structure, with:

```markdown
**Source:** Google Meet notes, [<doc title>](<link>) (not copied)   |   Notes from <tool>, pasted (not saved)
**Transcript:** [link] | not available
```

Only the summary is written: no transcript files for imported notes. If the folder exists,
append a `## From the notes` section instead of overwriting.

## Step 5 — Tracker

One JSONL, one `batch-add` (`--dry-run` first, then a yes, unless unattended). Source:
`Meeting: <title> YYYY-MM-DD (notes)` or `(pasted)`.

## Step 6 — Ledger and verify

Append one ledger line per source (notes and transcript separately). Then confirm each folder
created by this run holds only its summary:

```bash
for d in <folders created this run>; do find "$MEETINGS_DIR/$d" -type f ! -name '*-summary.md' -print; done
```

Report meetings imported, tasks added per sub-context, tasks already tracked, and meetings with
no item for you. Do not commit: the user reviews summaries first.
