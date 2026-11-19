---
name: MeetingAnalysis
description: Turn meetings into structured summaries and tracked action items. Transcribes recordings locally (faster-whisper on CUDA, Apple Silicon or CPU), imports Google Meet / Gemini notes through connectors, or takes pasted notetaker transcripts; writes a summary with decisions and an action table; pushes only your own items to the BattlePlan tracker. Includes an unattended inbox ingest (drop a recording, get a summary) and a hard rule that recordings never land in a git repo. USE WHEN analyze meeting, meeting summary, transcribe meeting, transcribe recording, summarize this call, what happened in the meeting, import meeting notes, Gemini notes, Google Meet notes, import meetings to tracker, auto ingest meetings, meeting inbox, process recordings folder, set up meeting analysis.
---

# MeetingAnalysis

Recordings, notes or pasted transcripts in; a short, structured summary and your action items
out. Every path, person and account comes from the user's config, never from this skill.

## Step 0 — every invocation starts here

```bash
MA="${SKILLS_HOME:-$HOME/.claude/skills}/MeetingAnalysis/Tools"
python3 "$MA/meeting_config.py" check            # ok: true, or the list of problems
python3 "$MA/meeting_config.py" show <context>   # the resolved profile for one context
```

No config, or a problem listed → run [Workflows/Setup.md](Workflows/Setup.md) first. Config
lives at `$MEETING_ANALYSIS_CONFIG`, else
`${AGENT_SKILLS_CONFIG:-~/.config/agent-skills}/MeetingAnalysis/config.json`.

## Workflows

| Trigger | Workflow |
| --- | --- |
| first use, new context, new notes provider, "set up meeting analysis" | [Setup](Workflows/Setup.md) |
| a recording path, "analyze this meeting" | [Analyze](Workflows/Analyze.md): relocate → transcribe → frames → summarize → tracker → archive → verify |
| "just transcribe" | [TranscribeOnly](Workflows/TranscribeOnly.md) |
| "import meeting notes", Gemini notes, a pasted notetaker transcript, a meeting link | [ImportNotes](Workflows/ImportNotes.md) |
| `/MeetingAnalysis ingest <context> --unattended`, "meeting inbox", scheduling | [AutoIngest](Workflows/AutoIngest.md) |

## HARD INVARIANT — no media in a repo

Meeting folders are usually inside a git repository (a notes repo, a second brain). Git keeps
every committed blob forever: one 800 MB recording costs 800 MB on every clone, permanently,
and deleting the file later does not give the space back.

| Allowed in a meeting folder | Forbidden |
| --- | --- |
| `.md`, `.txt`, `.json`, `.jsonl` | video: `.mp4 .mkv .mov .webm .avi` |
| at most 5 exceptional `.jpg` keyframes, ≤ 1 MB total (§ Frames) | audio: `.wav .mp3 .m4a`, any extracted audio |
| | `.png` frames, any file over 20 MB |

1. The source recording is **never** copied or moved into a meeting folder. The summary names it.
2. If an input recording sits inside a git work tree, **move it to `recordings_archive` first**,
   then work from the new path.
3. Scratch audio and frames go to a temp dir and are deleted at cleanup.
4. § Verification must print nothing before reporting success.

`meeting_config.py check` refuses a `recordings_archive` or ingest home inside a git work tree.

## Confidential contexts

`"confidential": true` means the meeting belongs to an employer or client and the meeting folder
or tracker is personal. Then: **no verbatim transcript or notes copied** (the summary links to
the source instead), summaries in generic terms (decisions, topics, owners, ticket IDs), no
hostnames, IPs, account IDs, credentials, customer names or customer data, and tracker items as
`TICKET-ID: short generic summary`.

## Output format

```
<meetings_dir>/YYYY-MM-DD-<slug>/
├── YYYY-MM-DD-<slug>-summary.md
├── YYYY-MM-DD-<slug>-transcript.txt     # [MM:SS] lines   (not for confidential contexts)
├── YYYY-MM-DD-<slug>-transcript.json    # segments        (not for confidential contexts)
└── frames/                              # rare; ≤ 5 jpg, ≤ 1 MB
```

`<slug>` is short kebab-case from the meeting title (`weekly-status`, `pricing-review`; add the
other person's name for 1:1s). Summary:

```markdown
# <Meeting title> — YYYY-MM-DD

**Attendees:** …
**Source:** <recording filename (archived outside the repo) | notes doc link | pasted transcript from <tool>>
**Transcript:** <filename | link | not copied>

---

## Context
## Topics Discussed
### 1. <Topic> (MM:SS–MM:SS)
## Decisions
## Immediate Action Items
| # | Action | Owner | Priority | Deadline |
|---|--------|-------|----------|----------|
## Key Takeaways
```

The action table lists **every** owner so the record is complete; only yours go to the tracker.

## Action items → tracker

`tracker: "BattlePlan"` in the config sends your items through BattlePlan's idempotent
`batch-add` (`"none"` skips the step). Yours means: owner is you or one of your
`owner_aliases`, you are one of several owners, or "we/the team" in a meeting you attended.
Sub-context: first matching `tracker_sub_context_rules` regex on the action, else the context's
`tracker_sub_context`. Resolve relative deadlines against the meeting date. Source:
`Meeting: <title> YYYY-MM-DD (recording|notes|pasted)`, stable across runs because dedupe keys
on it. Show a `--dry-run` and get a yes unless running unattended.

## Names

Speech recognition and notetakers mangle names. Correct them against the roster file
(`roster_file`: one person per line, `Name: alias, misspelling, …`) and the attendee list
(calendar event or notes header). Mark low-confidence corrections `Name (?)`; never guess.

## Frames (video only; scratch only)

Frames are analysis input, not a deliverable. Extract to a temp dir, read them, write what they
show into the summary (slides → key text; screen shares → what was shown; structure → a mermaid
diagram), then delete them.

```bash
ffmpeg -i <video> -vf "select='gt(scene,0.3)',showinfo" -vsync vfr "$TMP/frames/part1_%03d.png"   # 0.15 if < 2 frames
```

Keep a frame only if **all** hold: its content cannot be expressed as text, a table or mermaid;
it is dense (not a gallery view or title slide); the summary's conclusions depend on it; and the
summary references it by name. Save kept frames as
`ffmpeg -i in.png -vf scale=1280:-2 -q:v 4 frames/partN_MMmSSs.jpg`. When unsure, discard: the
recording and the timestamp remain.

## Verification

```bash
find "<meeting folder>" -type f \( -iname '*.mp4' -o -iname '*.mkv' -o -iname '*.mov' -o -iname '*.webm' -o \
  -iname '*.avi' -o -iname '*.wav' -o -iname '*.mp3' -o -iname '*.m4a' -o -iname '*.png' -o -size +20M \) -print
find "<meeting folder>" -path '*/frames/*' -type f | wc -l      # must be ≤ 5
```

Empty output is the only pass. Anything listed: move it out, tell the user, do not report success.

## Tools

| Tool | Does |
| --- | --- |
| `meeting_config.py check\|show\|env\|contexts` | Load and validate the config; resolve one context |
| `transcribe.py REC --out-base DIR/transcript [--lang auto\|en\|es] [--model turbo\|large-v3]` | Local transcription, writes `.txt` + `.jsonl`, prints stats JSON. Backends: CUDA → Apple MPS → CPU int8 |
| `run_ingest.sh --context NAME [--install\|--check\|--status\|--force\|--local]` | The unattended inbox runner and its scheduler |

## Dependencies

`uv` (scripts declare their own Python deps). `ffmpeg` only for frame extraction. A GPU is
optional: on CPU, a one-hour meeting takes about two hours with `turbo`. Notes import needs the
agent's Google Drive / Docs (and optionally Gmail, Calendar) connectors for the right account.
