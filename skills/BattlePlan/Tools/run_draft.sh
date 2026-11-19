#!/usr/bin/env bash
# Build the BattlePlan morning draft unattended, then notify.
#   run_draft.sh            scheduled run: skips weekends and days this host already drafted
#   run_draft.sh --force    run now regardless
#   run_draft.sh --check    print what would run (paths, alias, scheduler) and exit
#   run_draft.sh --install  install the weekday job (launchd on macOS, systemd user timer on Linux/WSL)
#   run_draft.sh --uninstall
#   --context NAME          limit the draft to one context (any mode above); default: the
#                           host's hosts.<alias>.draft_context in the config, else all
# Config: the BattlePlan config (plans_dir, plans_git_sync, hosts). See Workflows/Setup.md.
# Env: BATTLEPLAN_CONFIG, BATTLEPLAN_HOST_ALIAS (default mac|wsl|linux), BATTLEPLAN_DRAFT_CONTEXT,
#      BATTLEPLAN_DRAFT_TIME (HH:MM, default 08:00), BATTLEPLAN_SYNC=0 to skip git even when enabled,
#      BATTLEPLAN_NOTIFY_CMD (optional; receives title and message as $1 $2 on Linux),
#      BATTLEPLAN_AGENT_CMD (optional; a command that takes the prompt as $1, for agents other
#      than Claude Code. Without it the run uses `claude -p` with a read-only tool allowlist).
set -euo pipefail

LABEL="local.agent-skills.battleplan.draft"
UNIT="battleplan-draft"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SELF="$SKILL_DIR/Tools/$(basename "${BASH_SOURCE[0]}")"
CFG_JSON="$(python3 -I -c 'import json,sys
sys.path.insert(0, sys.argv[1])
from tracker import load_config, plans_dir, config_path
c = load_config(required=False)
print(json.dumps({"config": str(config_path()), "plans_dir": str(plans_dir(c)), "git": bool(c.get("plans_git_sync")),
                  "hosts": c.get("hosts", {})}))' "$SKILL_DIR/Tools")"
cfg() { python3 -I -c 'import json,sys; d=json.loads(sys.argv[1]); v=eval(sys.argv[2], {"d": d}); print("" if v is None else v)' "$CFG_JSON" "$1"; }
DAILY="$(cfg 'd["plans_dir"]')"
GIT_SYNC="$(cfg 'd["git"]')"
DRAFT_TIME="${BATTLEPLAN_DRAFT_TIME:-08:00}"
HOUR="$((10#${DRAFT_TIME%:*}))"; MINUTE="$((10#${DRAFT_TIME#*:}))"

MODE=""
CONTEXT_ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --context) CONTEXT_ARG="${2:?--context needs a value}"; shift 2 ;;
    --context=*) CONTEXT_ARG="${1#--context=}"; shift ;;
    *) MODE="$1"; shift ;;
  esac
done
OS="$(uname -s)"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || echo claude)}"

if [[ -n "${BATTLEPLAN_HOST_ALIAS:-}" ]]; then ALIAS="$BATTLEPLAN_HOST_ALIAS"
elif [[ "$OS" == "Darwin" ]]; then ALIAS="mac"
elif uname -r | grep -qi microsoft; then ALIAS="wsl"
else ALIAS="linux"; fi
export BATTLEPLAN_HOST_ALIAS="$ALIAS"

# One context per host keeps each laptop's draft about the work that lives on it.
if [[ -n "$CONTEXT_ARG" ]]; then DRAFT_CONTEXT="$CONTEXT_ARG"
elif [[ -n "${BATTLEPLAN_DRAFT_CONTEXT+set}" ]]; then DRAFT_CONTEXT="$BATTLEPLAN_DRAFT_CONTEXT"
else
  DRAFT_CONTEXT="$(cfg "d['hosts'].get('$ALIAS', {}).get('draft_context', '')")"
fi
export BATTLEPLAN_DRAFT_CONTEXT="$DRAFT_CONTEXT"

if [[ "$OS" == "Darwin" ]]; then
  LOG="$HOME/Library/Logs/battleplan-draft.log"
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
else
  LOG="${XDG_STATE_HOME:-$HOME/.local/state}/battleplan/draft.log"
  UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
fi

notify() {
  if [[ "$OS" == "Darwin" ]]; then
    osascript -e "display notification \"$2\" with title \"$1\"" >/dev/null 2>&1 || true
  elif [[ -n "${BATTLEPLAN_NOTIFY_CMD:-}" ]]; then
    $BATTLEPLAN_NOTIFY_CMD "$1" "$2" >/dev/null 2>&1 || true
  elif command -v notify-send >/dev/null; then
    notify-send "$1" "$2" >/dev/null 2>&1 || true
  fi
}

install_launchd() {
  mkdir -p "$DAILY" "$(dirname "$PLIST")" "$(dirname "$LOG")"
  local days=""
  for d in 1 2 3 4 5; do
    days+="<dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>"
  done
  cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$SELF</string></array>
  <key>StartCalendarInterval</key><array>$days</array>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>WorkingDirectory</key><string>$DAILY</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>$HOME</string>
    <key>BATTLEPLAN_DRAFT_CONTEXT</key><string>$DRAFT_CONTEXT</string>
  </dict>
</dict></plist>
EOF
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "installed $PLIST (weekdays $DRAFT_TIME, context: ${DRAFT_CONTEXT:-all}); log: $LOG"
}

install_systemd() {
  mkdir -p "$DAILY" "$UNIT_DIR" "$(dirname "$LOG")"
  # PATH is captured now: uv and claude often live in user-local dirs a bare unit cannot see.
  cat >"$UNIT_DIR/$UNIT.service" <<EOF
[Unit]
Description=BattlePlan morning draft

[Service]
Type=oneshot
WorkingDirectory=$DAILY
Environment=PATH=$PATH
Environment=CLAUDE_BIN=$CLAUDE_BIN
Environment=BATTLEPLAN_DRAFT_CONTEXT=$DRAFT_CONTEXT
ExecStart=/usr/bin/env bash $SELF
StandardOutput=append:$LOG
StandardError=append:$LOG
EOF
  cat >"$UNIT_DIR/$UNIT.timer" <<EOF
[Unit]
Description=BattlePlan morning draft

[Timer]
OnCalendar=Mon..Fri $DRAFT_TIME
# The machine may be asleep or WSL not running: a missed slot runs at the next start.
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now "$UNIT.timer"
  echo "installed $UNIT.timer (weekdays $DRAFT_TIME, context: ${DRAFT_CONTEXT:-all}); log: $LOG"
}

# Pull without disturbing local work: fast-forward only, never stash or reset.
# Parallel sessions keep uncommitted files in this repo.
git_on() { [[ "$GIT_SYNC" == "True" && "${BATTLEPLAN_SYNC:-1}" == "1" ]] && REPO="$(git -C "$DAILY" rev-parse --show-toplevel 2>/dev/null)"; }

sync_in() {
  git_on || return 0
  local branch; branch="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
  git -C "$REPO" fetch -q origin || { echo "$(date -Iseconds) fetch failed, continuing offline"; return 0; }
  git -C "$REPO" merge -q --ff-only "origin/$branch" 2>/dev/null \
    || echo "$(date -Iseconds) cannot fast-forward (diverged or conflicting local edits); drafting on local state"
}

# Commit only the draft. A pathspec commit leaves everything else staged or not untouched.
sync_out() {
  git_on || return 0
  local rel="${1#"$REPO"/}"
  git -C "$REPO" add -- "$rel"
  git -C "$REPO" commit -q -m "chore(battleplan): morning draft $today ($ALIAS, ${DRAFT_CONTEXT:-all})" -- "$rel" >/dev/null 2>&1 \
    || { echo "$(date -Iseconds) draft unchanged, nothing to commit"; return 0; }
  sync_in
  git -C "$REPO" push -q origin HEAD 2>/dev/null \
    || echo "$(date -Iseconds) push failed; draft committed locally only"
}

case "$MODE" in
  --install)
    if [[ "$OS" == "Darwin" ]]; then install_launchd; else install_systemd; fi
    exit 0 ;;
  --uninstall)
    if [[ "$OS" == "Darwin" ]]; then
      launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
      rm -f "$PLIST"
    else
      systemctl --user disable --now "$UNIT.timer" 2>/dev/null || true
      rm -f "$UNIT_DIR/$UNIT.service" "$UNIT_DIR/$UNIT.timer"
      systemctl --user daemon-reload
    fi
    echo "removed $UNIT"; exit 0 ;;
esac

today="$(date +%F)"
draft="$DAILY/$today-draft-$ALIAS.md"

if [[ "$MODE" == "--check" ]]; then
  echo "os=$OS alias=$ALIAS context=${DRAFT_CONTEXT:-all} time=$DRAFT_TIME draft=$draft log=$LOG agent=${BATTLEPLAN_AGENT_CMD:-$CLAUDE_BIN} git_sync=$GIT_SYNC config=$(cfg 'd["config"]')"
  exit 0
fi

if [[ "$MODE" != "--force" ]]; then
  [[ "$(date +%u)" -ge 6 ]] && { echo "$(date -Iseconds) weekend, skip"; exit 0; }
  [[ -s "$draft" ]] && { echo "$(date -Iseconds) draft exists for $ALIAS, skip"; exit 0; }
fi
mkdir -p "$DAILY" "$(dirname "$LOG")"
cd "$DAILY"
sync_in
echo "$(date -Iseconds) building draft (${DRAFT_CONTEXT:-all contexts}) -> $draft"

PROMPT="/BattlePlan ${DRAFT_CONTEXT:+$DRAFT_CONTEXT }--draft"
if [[ -n "${BATTLEPLAN_AGENT_CMD:-}" ]]; then
  $BATTLEPLAN_AGENT_CMD "$PROMPT" </dev/null || echo "$(date -Iseconds) agent exited $?"
else
  # Absolute paths in permission rules need a leading "//" (hence "/$DAILY", which starts with "/").
  # Read-only toward the tracker: manage_tasks.py (the only writer) is denied outright.
  "$CLAUDE_BIN" -p "$PROMPT" \
    --permission-mode default \
    --allowedTools "Bash(uv run:*)" "Bash(date:*)" "Bash(ls:*)" "Bash(cat:*)" "Bash(jq:*)" \
                   "Read" "Glob" "Grep" "Write(/$DAILY/**)" "Edit(/$DAILY/**)" "Skill" \
    --disallowedTools "Bash(*manage_tasks.py*)" "Agent" \
    --add-dir "$SKILL_DIR" \
    </dev/null || { echo "$(date -Iseconds) claude exited $?"; }
fi

if [[ -s "$draft" ]]; then
  header="$(grep -m1 '^Draft ready' "$draft" || echo 'Draft ready')"
  sync_out "$draft"
  notify "BattlePlan" "$header"
  echo "$(date -Iseconds) done: $header"
else
  notify "BattlePlan" "Draft failed, see $LOG"
  echo "$(date -Iseconds) no draft written"
  exit 1
fi
