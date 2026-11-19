#!/usr/bin/env bash
# Unattended meeting ingestion (MeetingAnalysis AutoIngest workflow). One run:
#   1. copies new recordings from a cloud-synced recordings folder into the inbox (read-only there)
#   2. claims every settled file in the inbox and transcribes it locally (transcribe.py)
#   3. runs the agent: "/MeetingAnalysis ingest <context> --unattended" imports new meeting notes
#      (if the context has a notes provider), summarizes the transcribed recordings, and pushes
#      your action items to the tracker
#   4. moves finished recordings + transcripts from Work/ into Processed/, verifies, notifies
#
#   run_ingest.sh --context NAME            scheduled run: weekdays, ingest.hours only
#   run_ingest.sh --context NAME --force    run now regardless of day/hour
#   run_ingest.sh --context NAME --local    inbox only: skip the notes import (no agent call if nothing is queued)
#   run_ingest.sh --context NAME --check    print resolved paths and settings, then exit
#   run_ingest.sh --context NAME --status   queued / in work / failed / processed, last run report
#   run_ingest.sh --context NAME --install  install the job (launchd on macOS, systemd user timer on Linux)
#   run_ingest.sh --context NAME --uninstall
#
# Everything comes from the MeetingAnalysis config (Tools/meeting_config.py show NAME).
# Env overrides: MEETINGS_HOME, INGEST_INTERVAL_MIN, INGEST_HOURS, INGEST_LANG, INGEST_TRACKER (add|dry),
#   DRIVE_RECORDINGS_DIR ("none" disables), CLAUDE_BIN, MEETING_AGENT_CMD (another agent: a command
#   that takes the prompt as $1 and enforces an equivalent allowlist).
# Nothing here commits: summaries land uncommitted in the meetings folder for review.
set -euo pipefail

LABEL="local.agent-skills.meeting.ingest"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SELF="$SKILL_DIR/Tools/$(basename "${BASH_SOURCE[0]}")"
SKILLS_ROOT="$(dirname "$SKILL_DIR")"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || echo claude)}"
OS="$(uname -s)"

MODE=""; CONTEXT=""; LOCAL_ONLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --context) CONTEXT="${2:?--context needs a value}"; shift 2 ;;
    --context=*) CONTEXT="${1#--context=}"; shift ;;
    --local) LOCAL_ONLY=1; shift ;;
    *) MODE="$1"; shift ;;
  esac
done

[[ -n "$CONTEXT" ]] || { echo "--context NAME is required (contexts: $(python3 -I "$SKILL_DIR/Tools/meeting_config.py" contexts | tr '\n' ' '))" >&2; exit 2; }
PROFILE="$(python3 -I "$SKILL_DIR/Tools/meeting_config.py" env "$CONTEXT")" || exit 2
CONTEXT_ARG_ENV_HOME="${MEETINGS_HOME:-}"
eval "$PROFILE"
MEETING_DIR="$MEETINGS_DIR"
MEETINGS_HOME="${CONTEXT_ARG_ENV_HOME:-$INGEST_HOME}"
INBOX="$MEETINGS_HOME/Inbox"; WORK="$MEETINGS_HOME/Work"
PROCESSED="$MEETINGS_HOME/Processed"; FAILED="$MEETINGS_HOME/Failed"; STATE="$MEETINGS_HOME/.state"
LANG_OPT="${INGEST_LANG:-$LANGUAGE}"
TRACKER="$INGEST_TRACKER"
INTERVAL_MIN="$INGEST_INTERVAL_MIN"
HOURS="$INGEST_HOURS"
LOG="$HOME/Library/Logs/meeting-ingest-$CONTEXT.log"
[[ "$OS" == "Darwin" ]] || LOG="${XDG_STATE_HOME:-$HOME/.local/state}/meeting-ingest/$CONTEXT.log"
PLIST="$HOME/Library/LaunchAgents/$LABEL.$CONTEXT.plist"
MEDIA_RE='\.(mp4|m4v|mov|mkv|webm|avi|m4a|mp3|wav|aac|aiff|ogg|flac)$'

DRIVE_DIR="$DRIVE_RECORDINGS_DIR"
[[ "$DRIVE_DIR" == "none" ]] && DRIVE_DIR=""

log() { echo "$(date -Iseconds) [$CONTEXT] $*"; }
notify() {
  if [[ "$OS" == "Darwin" ]]; then
    osascript -e "display notification \"${2//\"/\'}\" with title \"${1//\"/\'}\"" >/dev/null 2>&1 || true
  elif command -v notify-send >/dev/null; then notify-send "$1" "$2" >/dev/null 2>&1 || true; fi
}
age_s() { echo $(( $(date +%s) - $(stat -f %m "$1" 2>/dev/null || stat -c %Y "$1") )); }
sha16() { shasum -a 256 "$1" | cut -c1-16; }
in_git() { git -C "$1" rev-parse --show-toplevel >/dev/null 2>&1; }

# The media home must never sit inside a git work tree (MeetingAnalysis HARD INVARIANT).
guard_home() {
  mkdir -p "$INBOX" "$WORK" "$PROCESSED" "$FAILED" "$STATE"
  if in_git "$MEETINGS_HOME"; then
    echo "MEETINGS_HOME=$MEETINGS_HOME is inside a git work tree; refusing (recordings would be committable)" >&2
    exit 3
  fi
}

install_launchd() {
  guard_home
  mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
  cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL.$CONTEXT</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$SELF</string><string>--context</string><string>$CONTEXT</string></array>
  <key>StartInterval</key><integer>$((INTERVAL_MIN * 60))</integer>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>WorkingDirectory</key><string>$MEETING_DIR</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>$HOME</string>
    <key>MEETINGS_HOME</key><string>$MEETINGS_HOME</string>
    <key>INGEST_HOURS</key><string>$HOURS</string>
    <key>INGEST_TRACKER</key><string>$TRACKER</string>
  </dict>
</dict></plist>
EOF
  launchctl bootout "gui/$(id -u)/$LABEL.$CONTEXT" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "installed $PLIST (every ${INTERVAL_MIN}m, weekdays $HOURS h); inbox: $INBOX; log: $LOG"
}

install_systemd() {
  guard_home
  local unit="meeting-ingest-$CONTEXT" dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  mkdir -p "$dir" "$(dirname "$LOG")"
  cat >"$dir/$unit.service" <<UNIT
[Unit]
Description=MeetingAnalysis ingest ($CONTEXT)

[Service]
Type=oneshot
Environment=PATH=$PATH
Environment=CLAUDE_BIN=$CLAUDE_BIN
ExecStart=/usr/bin/env bash $SELF --context $CONTEXT
StandardOutput=append:$LOG
StandardError=append:$LOG
UNIT
  cat >"$dir/$unit.timer" <<UNIT
[Unit]
Description=MeetingAnalysis ingest ($CONTEXT) every ${INTERVAL_MIN} min

[Timer]
OnBootSec=5min
OnUnitActiveSec=${INTERVAL_MIN}min
Persistent=true

[Install]
WantedBy=timers.target
UNIT
  systemctl --user daemon-reload && systemctl --user enable --now "$unit.timer"
  echo "installed $unit.timer (every ${INTERVAL_MIN}m, weekdays $HOURS h); inbox: $INBOX; log: $LOG"
}

status() {
  echo "inbox:      $(find "$INBOX" -maxdepth 1 -type f 2>/dev/null | grep -Eic "$MEDIA_RE" || true) recording(s)  $INBOX"
  echo "in work:    $(find "$WORK" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')  $WORK"
  echo "failed:     $(find "$FAILED" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')  $FAILED"
  echo "processed:  $(find "$PROCESSED" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')  $PROCESSED"
  [[ -s "$STATE/last-run.json" ]] && { echo "last run:"; cat "$STATE/last-run.json"; }
  return 0
}

case "$MODE" in
  --install)
    if [[ "$OS" == "Darwin" ]]; then install_launchd; else install_systemd; fi; exit 0 ;;
  --uninstall)
    if [[ "$OS" == "Darwin" ]]; then
      launchctl bootout "gui/$(id -u)/$LABEL.$CONTEXT" 2>/dev/null || true; rm -f "$PLIST"
    else
      systemctl --user disable --now "meeting-ingest-$CONTEXT.timer" 2>/dev/null || true
      rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/meeting-ingest-$CONTEXT".service \
            "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/meeting-ingest-$CONTEXT".timer
      systemctl --user daemon-reload 2>/dev/null || true
    fi
    echo "removed ingest job for $CONTEXT"; exit 0 ;;
  --check)
    echo "context=$CONTEXT notes=$NOTES_PROVIDER lang=$LANG_OPT tracker=$TRACKER interval=${INTERVAL_MIN}m hours=$HOURS"
    echo "meetings_home=$MEETINGS_HOME meeting_dir=$MEETING_DIR"
    echo "drive_recordings=${DRIVE_DIR:-disabled} ($([[ -n "$DRIVE_DIR" && -d "$DRIVE_DIR" ]] && echo present || echo absent))"
    echo "claude=$CLAUDE_BIN log=$LOG plist=$PLIST ($([[ -f "$PLIST" ]] && echo installed || echo not installed))"
    exit 0 ;;
  --status) status; exit 0 ;;
  ""|--force) ;;
  *) echo "unknown option '$MODE'" >&2; exit 2 ;;
esac

if [[ "$MODE" != "--force" ]]; then
  [[ "$(date +%u)" -ge 6 ]] && exit 0
  h=$((10#$(date +%H))); [[ $h -ge ${HOURS%-*} && $h -le ${HOURS#*-} ]] || exit 0
fi

guard_home
mkdir -p "$(dirname "$LOG")"
# One run at a time; a lock older than 4 h is from a crashed run.
LOCK="$STATE/lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [[ $(age_s "$LOCK") -gt 14400 ]]; then rm -rf "$LOCK"; mkdir "$LOCK"; else log "previous run still active, skip"; exit 0; fi
fi
trap 'rm -rf "$LOCK"' EXIT
RUN_STAMP="$LOCK/started"; touch "$RUN_STAMP"

# --- 1. Drive-for-desktop recordings: copy new ones in, never touch the Drive original ---
if [[ -n "$DRIVE_DIR" && -d "$DRIVE_DIR" ]]; then
  touch "$STATE/drive-copied.tsv"
  while IFS= read -r -d '' f; do
    [[ "$f" =~ $MEDIA_RE ]] || continue
    [[ $(age_s "$f") -ge 600 ]] || continue          # Meet is still uploading
    key="${f#"$DRIVE_DIR"/}"$'\t'"$(stat -f %z "$f" 2>/dev/null || stat -c %s "$f")"
    grep -qxF "$key" "$STATE/drive-copied.tsv" && continue
    base="$(basename "$f")"
    cp "$f" "$INBOX/.partial-$base" && mv "$INBOX/.partial-$base" "$INBOX/$base"
    printf '%s\n' "$key" >>"$STATE/drive-copied.tsv"
    log "copied from Drive: $base"
  done < <(find "$DRIVE_DIR" -type f -print0 2>/dev/null)
fi

# --- 2. Claim and transcribe settled inbox files ---
touch "$STATE/hashes.tsv"
claimed=0
while IFS= read -r -d '' f; do
  base="$(basename "$f")"
  [[ "$base" == .* ]] && continue
  [[ "$base" =~ $MEDIA_RE ]] || continue
  [[ $(age_s "$f") -ge 120 ]] || continue            # still being copied or recorded
  h="$(sha16 "$f")"
  if prev="$(grep -m1 "^$h	" "$STATE/hashes.tsv" | cut -f2)" && [[ -n "$prev" ]]; then
    mkdir -p "$PROCESSED/_duplicates"; mv "$f" "$PROCESSED/_duplicates/"
    log "duplicate of $prev: $base moved to Processed/_duplicates"; continue
  fi
  id="$(date +%Y%m%d-%H%M%S)-$(echo "${base%.*}" | tr -cs 'A-Za-z0-9' '-' | cut -c1-50 | sed 's/-$//')"
  w="$WORK/$id"; mkdir -p "$w"
  birth="$(stat -f %SB -t %Y-%m-%dT%H:%M:%S "$f" 2>/dev/null || date -r "$f" +%Y-%m-%dT%H:%M:%S)"
  mv "$f" "$w/"
  for ext in md txt; do                               # optional sidecar: "<basename>.md" with title/attendees/context
    [[ -f "$INBOX/${base%.*}.$ext" ]] && mv "$INBOX/${base%.*}.$ext" "$w/context.$ext"
  done
  printf '{"id":"%s","original_name":"%s","sha16":"%s","file_created":"%s","claimed_at":"%s","context":"%s"}\n' \
    "$id" "${base//\"/\\\"}" "$h" "$birth" "$(date -Iseconds)" "$CONTEXT" >"$w/meta.json"
  log "transcribing $base -> Work/$id"
  if uv run --script "$SKILL_DIR/Tools/transcribe.py" "$w/$base" --out-base "$w/transcript" --lang "$LANG_OPT" --model "$TRANSCRIPTION_MODEL" \
       >"$w/transcribe.json" 2>"$w/transcribe.err"; then
    claimed=$((claimed + 1)); log "transcribed: $(cat "$w/transcribe.json")"
  else
    log "transcription failed for $base (see Failed/$id/transcribe.err)"
    mv "$w" "$FAILED/"; notify "Meeting ingest" "Transcription failed: $base"
  fi
done < <(find "$INBOX" -maxdepth 1 -type f -print0)

# Retry transcription for work dirs left without a transcript (crash mid-run)
for w in "$WORK"/*/; do
  [[ -d "$w" ]] || continue; w="${w%/}"
  [[ -s "$w/transcript.txt" ]] && continue
  m="$(find "$w" -maxdepth 1 -type f | grep -Ei "$MEDIA_RE" | head -1)"
  [[ -n "$m" ]] && uv run --script "$SKILL_DIR/Tools/transcribe.py" "$m" --out-base "$w/transcript" --lang "$LANG_OPT" --model "$TRANSCRIPTION_MODEL" \
    >"$w/transcribe.json" 2>"$w/transcribe.err" || { mv "$w" "$FAILED/"; log "retry failed: $w"; }
done

pending="$(find "$WORK" -mindepth 2 -maxdepth 2 -name transcript.txt | wc -l | tr -d ' ')"

# --- 3. Claude: Drive notes import + summaries of the transcribed recordings ---
if [[ $LOCAL_ONLY -eq 1 && "$pending" -eq 0 ]]; then
  log "local-only run, nothing queued"; exit 0
fi
flags="--unattended"; [[ $LOCAL_ONLY -eq 1 ]] && flags+=" --local-only"
[[ "$TRACKER" == "dry" ]] && flags+=" --dry-run-tracker"
rm -f "$STATE/last-run.json"
log "claude: /MeetingAnalysis ingest $CONTEXT $flags (recordings queued: $pending)"
mkdir -p "$MEETING_DIR"; cd "$MEETING_DIR"
PROMPT="/MeetingAnalysis ingest $CONTEXT $flags"
TRACKER_DIR="$SKILLS_ROOT/BattlePlan"; [[ -d "$TRACKER_DIR" ]] || TRACKER_DIR="$SKILL_DIR"
if [[ -n "${MEETING_AGENT_CMD:-}" ]]; then
  $MEETING_AGENT_CMD "$PROMPT" </dev/null || log "agent exited $?"
else
  # Allowlist only: in -p mode anything not listed is denied. Edit(...) rules also cover Write.
  # Read-only on connectors (search/read tools only, from the config), no sends, no git.
  "$CLAUDE_BIN" -p "$PROMPT" \
    --permission-mode default \
    --allowedTools "Read" "Glob" "Grep" "Skill" "ToolSearch" \
                   "Edit(/$MEETING_DIR/**)" "Edit(/$MEETINGS_HOME/**)" \
                   "Bash(uv run:*)" "Bash(date:*)" "Bash(ls:*)" \
                   ${INGEST_ALLOWED_TOOLS[@]+"${INGEST_ALLOWED_TOOLS[@]}"} \
    --disallowedTools "Agent" "Bash(git:*)" "Bash(rm:*)" \
    --add-dir "$SKILL_DIR" "$MEETINGS_HOME" "$TRACKER_DIR" \
    </dev/null || log "claude exited $?"
fi

# --- 4. Archive finished work dirs; retry or fail the rest ---
done_n=0
for w in "$WORK"/*/; do
  [[ -d "$w" ]] || continue; w="${w%/}"; id="$(basename "$w")"
  if [[ -s "$w/DONE.json" ]]; then
    folder="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("folder") or "")' "$w/DONE.json" 2>/dev/null || true)"
    [[ "$folder" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]+$ ]] || folder="$id"
    dest="$PROCESSED/$folder"; [[ -e "$dest" ]] && dest="$dest--$id"
    mv "$w" "$dest"
    python3 -I -c 'import json,sys; m=json.load(open(sys.argv[1])); print(m["sha16"]+"\t"+sys.argv[2])' "$dest/meta.json" "$folder" >>"$STATE/hashes.tsv"
    done_n=$((done_n + 1)); log "archived Work/$id -> Processed/$(basename "$dest")"
  else
    n=$(( $(cat "$w/.attempts" 2>/dev/null || echo 0) + 1 )); echo "$n" >"$w/.attempts"
    if [[ $n -ge 3 ]]; then mv "$w" "$FAILED/"; log "summary failed 3 times: $id moved to Failed/"
      notify "Meeting ingest" "Could not summarize $id (moved to Failed/)"; fi
  fi
done

# --- 5. Verify: nothing written this run is media or a transcript ---
rm -f "$STATE/tracker-batch.jsonl"
leak="$(find "$MEETING_DIR" -type f -newer "$RUN_STAMP" \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.mkv' -o -iname '*.webm' -o \
  -iname '*.m4a' -o -iname '*.mp3' -o -iname '*.wav' -o -iname '*.png' -o -iname '*-transcript.*' -o -size +20M \) -print)"
if [[ -n "$leak" ]]; then
  log "LEAK: media/transcript inside the repo:"; echo "$leak"
  notify "Meeting ingest" "STOP: media or transcript found in $MEETING_DIR, see log"
fi

msg="$(python3 -I -c 'import json,sys
try: r=json.load(open(sys.argv[1]))
except Exception: print(""); sys.exit()
print(r.get("headline",""))' "$STATE/last-run.json")"
[[ -z "$msg" ]] && msg="recordings archived: $done_n"
log "done: $msg"
[[ "$msg" == *"nothing new"* && $done_n -eq 0 ]] || notify "Meeting ingest ($CONTEXT)" "$msg"
