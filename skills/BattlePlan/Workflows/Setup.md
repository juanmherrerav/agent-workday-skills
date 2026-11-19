# Setup — configure the tracker, the contexts and the plans directory

Run on first use, when `setup_tracker.py check` fails, or to add a context. The output is one
file, the user's config (default `~/.config/agent-skills/BattlePlan/config.json`), plus the tabs
it describes. Ask; never guess names, people or paths.

```bash
BP="${SKILLS_HOME:-$HOME/.claude/skills}/BattlePlan"
CFG="${BATTLEPLAN_CONFIG:-${AGENT_SKILLS_CONFIG:-$HOME/.config/agent-skills}/BattlePlan/config.json}"
```

## Step 1 — Interview (one message, all questions)

1. **Who are you in the tracker?** Owner name, plus the aliases people write in meeting notes
   (initials, nickname, "me"). Tasks owned by an alias count as yours.
2. **Where should tasks live?** Offer the three backends with their trade-offs:

   | Backend | Pick it when | Needs |
   | --- | --- | --- |
   | `csv` (default) | You want plain files, version control, zero accounts | A directory. Put it in git, Dropbox, OneDrive, iCloud or Syncthing to share across machines |
   | `xlsx` | You live in Excel, or your org uses OneDrive / SharePoint | A path to a `.xlsx` file (local or in a synced folder). Close it in Excel while tools write |
   | `gsheets` | You want the tracker in a browser, editable from the phone | A Google Cloud service account with the Sheets API, its JSON key, and the sheet shared with its email as Editor |

3. **Contexts.** The big buckets of your life and work (one tab each), and inside each the
   sub-contexts (projects, teams, areas). For each sub-context: `heavy` (full dev work),
   `medium` (mixed), or `light` (messages, admin); the repo and its local path if it is code.
4. **Hours.** A normal day's hours, and the rough budget per context (e.g. Work 6, Personal 1.5).
5. **Confidentiality.** Which contexts hold an employer's or a client's material that must not
   reach a personal tracker? Those get `confidential: true` and, optionally,
   `forbidden_patterns` (customer names, internal domains) as regexes.
6. **Plans directory and sync.** Where daily plans and handoffs go. One machine: any folder.
   Several machines: a folder inside a git repo (`plans_git_sync: true`) or a synced folder.
7. **Evidence for the recap** (optional, improves the morning audit): per context, path
   fragments that identify its repos (`/dev/work/`), ticket prefixes (`ABC`), and agent config
   dirs that always mean that context.

## Step 2 — Write the config

Start from `Templates/config.example.json`; delete what does not apply rather than leaving
template values. Keys starting with `_` are comments. Show the user the final JSON before
writing it to `$CFG`.

## Step 3 — Backend prerequisites

- **csv / xlsx:** nothing beyond `uv`. The directory or workbook is created on `init`.
- **gsheets:**
  1. Google Cloud console → create a project → enable the **Google Sheets API**.
  2. IAM → Service accounts → create one → Keys → add a JSON key → save it to
     `~/.config/gspread/service_account.json` (or set `tracker.service_account`). `chmod 600` it.
  3. Create an empty Google Sheet, share it with the service account's email as **Editor**, and
     put the id from its URL (`/d/<id>/edit`) in `tracker.spreadsheet_id`.

## Step 4 — Create and verify

```bash
uv run --script "$BP/Tools/setup_tracker.py" init     # creates missing tabs + Archive, never touches rows
uv run --script "$BP/Tools/setup_tracker.py" check    # must print success: true
uv run --script "$BP/Tools/manage_tasks.py" list-tabs  # contexts → tabs as the tools resolve them
```

Tab layout (created by `init`): `Date, Meeting, #, Sub-context, Action, Owner, Priority,
Deadline, Status`. `Meeting` is the task's source. Extra columns are allowed and ignored. An
existing tracker can be adopted as long as each context tab has at least `Action` and `Status`.

## Step 5 — Optional extras

- **Morning draft:** [Draft.md](Draft.md) → `run_draft.sh --install`.
- **Meeting action items:** the MeetingAnalysis skill pushes items with `batch-add`; its setup
  maps meeting folders to sub-contexts in this config.
- **Issue work:** set `issue_skill` on a heavy sub-context (e.g. `IssueFlow`) so thread prompts
  start with that skill.

Report what was configured: backend and location, contexts and tabs, plans directory, sync
mode, and the command to run the first plan (`/BattlePlan`).
