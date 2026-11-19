#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Recap what happened since the last plan: Claude Code sessions + git commits.

Feeds BattlePlan's morning audit, --close and --draft so the day does not start
from zero. Reads only local files (session transcripts, git), never the tracker.
Session transcripts are Claude Code's (~/.claude*/projects/*/*.jsonl). With another agent
there are no transcripts to read, and the recap still reports git commits.

Usage:
  recap_sessions.py [--since auto|YYYY-MM-DD|ISO] [--until ISO] [--tasks pull.json]
                    [--context NAME] [--config-dir DIR ...] [--min-turns N] [--include-trivial]

--since auto (default): `Closed:` time of this host's last handoff
(<plans_dir>/*-handoff-<alias>.md), else the start of
the previous workday (Mon looks back to Fri).
--tasks: a pull_tasks.py JSON file. Adds `links` (task ref -> sessions/commits
that share a ticket ID) and `unlinked_sessions`.
--context: keep only sessions classified into that context (same matching as
pull_tasks.py: case-insensitive substring). Rules live in the BattlePlan config
under each context's `evidence`. Dropped sessions are counted, never silent.
--config-dir: defaults to $CLAUDE_CONFIG_DIR plus every ~/.claude and ~/.claude-*
that has a projects/ dir, so a new profile needs no code change.
--include-trivial: keep one-prompt, no-tool sessions. Hook-spawned inference
inherits the parent's entrypoint, so these are almost always not human work.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
sys.path.insert(0, str(Path(__file__).parent))
from tracker import config_path, load_config, plans_dir  # noqa: E402  (stdlib-only module)

HIERARCHY_PATH = config_path()
DAILY_DIR = plans_dir(load_config(required=False))

TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,6})\b")
# Uppercase-dash-number strings that are not tickets.
TICKET_DENY = re.compile(r"^(UTF|SHA|ISO|HTTP|RFC|CVE|TLS|SSL|MD|AES|RSA|GPT|PEP|ECMA|X|COVID|IPV|HTTP2)-", re.I)
PR_RE = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
GIT_ACTION_RE = re.compile(r"\b(git commit|git push|gh pr (?:create|merge|ready|review)|git merge)\b")
SKIP_ENTRYPOINTS = {"sdk-cli", "sdk-ts", "sdk-py"}
# Editor and system wrappers around what the human typed.
WRAPPER_BLOCK = re.compile(r"<(ide_opened_file|ide_selection|ide_diagnostics|system-reminder)\b[^>]*>.*?</\1>", re.S)
IDE_HINT_LINE = re.compile(r"^The user (opened the file|has selected|selected)\b.*$", re.M)
IMAGE_TOKEN = re.compile(r"\[Image\b[^\]]*\]\s*")
COMMAND_NAME = re.compile(r"<command-name>\s*(/[^<\s]+)\s*</command-name>")
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
PASTED_TAG = re.compile(r"</?pasted_content\b[^>]*>")
NOT_TYPED = re.compile(
    r"^(<(task-notification|local-command|bash-|command-)|Caveat:|\[Request interrupted"
    r"|This session is being continued|Base directory for this skill)"
)
CLONE_WINDOW_SECONDS = 900
CLONE_MAX_PROMPTS = 2
# Classification weights: a tool touching a path is the strongest evidence in
# aggregate, a ticket is explicit, and a profile dir only breaks near-ties.
WEIGHT_CWD, WEIGHT_TICKET, WEIGHT_CONFIG_DIR = 5, 3, 2


def parse_ts(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def iso_local(ts: dt.datetime | None) -> str | None:
    return ts.astimezone().isoformat(timespec="seconds") if ts else None


def local_now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def previous_workday_start(now: dt.datetime) -> dt.datetime:
    day = now.date() - dt.timedelta(days=1)
    while day.weekday() >= 5:  # Sat/Sun -> back to Fri
        day -= dt.timedelta(days=1)
    return dt.datetime.combine(day, dt.time(0, 0), tzinfo=now.tzinfo)


def host_alias(system: str | None = None, release: str | None = None) -> str:
    """Stable, non-identifying name for this machine. Hostnames never reach shared files."""
    if os.environ.get("BATTLEPLAN_HOST_ALIAS"):
        return os.environ["BATTLEPLAN_HOST_ALIAS"]
    u = os.uname()
    system = system or u.sysname
    release = release or u.release
    if system == "Darwin":
        return "mac"
    return "wsl" if "microsoft" in release.lower() else "linux"


HANDOFF_CLOSED = re.compile(r"^Closed:\s*(\S+)", re.M)


def last_handoff_time(daily_dir: Path = DAILY_DIR, alias: str | None = None) -> dt.datetime | None:
    """When this host last closed a day, read from the handoff itself.

    File mtime is useless here: a git pull resets it. Other hosts' handoffs are
    ignored because their sessions are not on this machine.
    """
    alias = alias or host_alias()
    if not daily_dir.is_dir():
        return None
    closed = []
    for path in daily_dir.glob(f"*-handoff-{alias}.md"):
        m = HANDOFF_CLOSED.search(path.read_text(errors="replace")[:500])
        ts = parse_ts(m.group(1)) if m else None
        if ts:
            closed.append(ts if ts.tzinfo else ts.astimezone())
    return max(closed) if closed else None


def resolve_since(arg: str) -> tuple[dt.datetime, str]:
    now = local_now()
    if arg == "auto":
        h = last_handoff_time()
        floor = previous_workday_start(now)
        # A handoff only counts if it is recent; otherwise fall back to the workday floor.
        if h and h >= floor - dt.timedelta(days=3):
            return h, "last handoff"
        return floor, "previous workday start"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", arg):
        d = dt.date.fromisoformat(arg)
        return dt.datetime.combine(d, dt.time(0, 0), tzinfo=now.tzinfo), "explicit date"
    ts = parse_ts(arg)
    if not ts:
        sys.exit(f"bad --since: {arg}")
    return (ts if ts.tzinfo else ts.astimezone()), "explicit timestamp"


def tickets_in(*texts: str) -> set[str]:
    out = set()
    for t in texts:
        for m in TICKET_RE.findall(t or ""):
            if not TICKET_DENY.match(m):
                out.add(m)
    return out


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def clean_prompt(text: str | None) -> str | None:
    """What the human typed, or None if no human typed this record."""
    t = WRAPPER_BLOCK.sub("", text or "")
    t = IDE_HINT_LINE.sub("", t)
    t = IMAGE_TOKEN.sub("", t).strip()
    name = COMMAND_NAME.search(t)
    if name:
        args = COMMAND_ARGS.search(t)
        return f"{name.group(1)} {args.group(1).strip()}".strip() if args else name.group(1)
    t = PASTED_TAG.sub("", t).strip()
    if not t or NOT_TYPED.match(t) or "tool_result" in t[:40]:
        return None
    return t


def discover_config_dirs(home: Path = HOME) -> list[Path]:
    candidates = []
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        candidates.append(Path(os.environ["CLAUDE_CONFIG_DIR"]).expanduser())
    candidates.append(home / ".claude")
    candidates.extend(sorted(home.glob(".claude-*")))
    found: dict[Path, Path] = {}
    for c in candidates:
        if (c / "projects").is_dir():
            found.setdefault(c.resolve(), c)
    return list(found.values())


def load_context_rules(path: Path = HIERARCHY_PATH) -> dict:
    try:
        contexts = json.loads(path.read_text()).get("contexts", {})
    except (OSError, json.JSONDecodeError):
        return {}
    return {name: c["evidence"] for name, c in contexts.items() if c.get("evidence")}


def load_automation_prefixes(path: Path = HIERARCHY_PATH) -> tuple[str, ...]:
    try:
        return tuple(json.loads(path.read_text()).get("automation_prompt_prefixes", []))
    except (OSError, json.JSONDecodeError):
        return ()


def load_host_defaults(alias: str, path: Path = HIERARCHY_PATH) -> dict:
    try:
        hosts = json.loads(path.read_text()).get("hosts", {})
    except (OSError, json.JSONDecodeError):
        return {}
    return hosts.get(alias, {}).get("default_context_by_config_dir", {})


def count_touches(text: str, rules: dict, into: collections.Counter) -> None:
    folded = text.casefold()
    for name, rule in rules.items():
        hits = sum(folded.count(p.casefold()) for p in rule.get("paths", []))
        if hits:
            into[name] += hits


def classify_context(signals: dict, rules: dict) -> str | None:
    """Best-scoring context for a session; None when nothing matches or it is a tie."""
    scores: collections.Counter = collections.Counter(signals.get("touched") or {})
    cwd = (signals.get("cwd") or "").casefold()
    for name, rule in rules.items():
        if cwd and any(p.casefold() in cwd for p in rule.get("paths", [])):
            scores[name] += WEIGHT_CWD
        prefixes = set(rule.get("ticket_prefixes", []))
        scores[name] += WEIGHT_TICKET * sum(t.split("-")[0] in prefixes for t in signals.get("tickets", []))
        if signals.get("config_dir") in rule.get("config_dirs", []):
            scores[name] += WEIGHT_CONFIG_DIR
    top = scores.most_common(2)
    if not top or top[0][1] <= 0 or (len(top) > 1 and top[0][1] == top[1][1]):
        return None
    return top[0][0]


def matches_context(context: str | None, wanted: str) -> bool:
    return context is not None and wanted.lower() in context.lower()


def scan_session(path: Path, since: dt.datetime, until: dt.datetime, config_dir: Path, rules: dict | None = None) -> dict | None:
    sid = path.stem
    cwds = collections.Counter()
    branch = None
    title = None
    first_prompt = None
    prompts_in_window: list[str] = []
    last_prompt = None
    last_assistant = None
    first_ts = last_ts = None
    win_first = win_last = None
    entrypoint = None
    git_actions: list[str] = []
    prs: dict[str, str] = {}
    rules = rules or {}
    touched: collections.Counter = collections.Counter()
    total_prompts = 0
    tool_calls = 0

    with path.open(errors="replace") as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            typ = e.get("type")
            if typ == "ai-title":
                title = e.get("aiTitle") or title
                continue
            if typ == "custom-title":
                title = e.get("customTitle") or title
                continue
            if typ == "last-prompt":
                last_prompt = e.get("lastPrompt") or last_prompt
                continue
            if typ not in ("user", "assistant") or e.get("isSidechain"):
                continue
            ts = parse_ts(e.get("timestamp"))
            if ts:
                first_ts = first_ts or ts
                last_ts = ts
            entrypoint = entrypoint or e.get("entrypoint")
            if e.get("cwd"):
                cwds[e["cwd"]] += 1
            if e.get("gitBranch") and e["gitBranch"] != "HEAD":
                branch = e["gitBranch"]
            in_win = ts is not None and since <= ts <= until
            msg = e.get("message") or {}
            content = msg.get("content")
            if typ == "user" and not e.get("isMeta"):
                t = clean_prompt(text_of(content))
                if t:
                    total_prompts += 1
                    first_prompt = first_prompt or t
                    if in_win:
                        prompts_in_window.append(t)
                        win_first = win_first or ts
                        win_last = ts
            elif typ == "assistant":
                if in_win:
                    win_last = ts
                t = text_of(content)
                if t.strip() and in_win:
                    last_assistant = t
                for m in PR_RE.finditer(t):
                    prs[f"{m.group(1)}#{m.group(2)}"] = f"https://github.com/{m.group(1)}/pull/{m.group(2)}"
                if isinstance(content, list):
                    for c in content:
                        if not (isinstance(c, dict) and c.get("type") == "tool_use"):
                            continue
                        tool_calls += 1
                        if not in_win:
                            continue
                        tool_input = c.get("input") or {}
                        cmd = tool_input.get("command", "") if c.get("name") == "Bash" else ""
                        m = GIT_ACTION_RE.search(cmd)
                        if m:
                            git_actions.append(m.group(1))
                        for value in (cmd, tool_input.get("file_path"), tool_input.get("path"), tool_input.get("notebook_path")):
                            if isinstance(value, str) and value:
                                count_touches(value, rules, touched)

    if entrypoint in SKIP_ENTRYPOINTS or not prompts_in_window:
        return None
    cwd = cwds.most_common(1)[0][0] if cwds else None
    tix = tickets_in(title or "", branch or "", first_prompt or "", *prompts_in_window, cwd or "")
    last_typed = clean_prompt(last_prompt) or prompts_in_window[-1]
    env = "" if config_dir == HOME / ".claude" else f"CLAUDE_CONFIG_DIR={config_dir} "
    return {
        "session_id": sid,
        "config_dir": str(config_dir),
        "context": classify_context(
            {"cwd": cwd, "touched": touched, "tickets": sorted(tix), "config_dir": config_dir.name}, rules),
        "title": title,
        "cwd": cwd,
        "branch": branch,
        "entrypoint": entrypoint,
        "started": iso_local(first_ts),
        "active_from": iso_local(win_first),
        "active_to": iso_local(win_last),
        "turns_in_window": len(prompts_in_window),
        "total_prompts": total_prompts,
        "tool_calls": tool_calls,
        "first_prompt": (first_prompt or "")[:300],
        "last_prompt": last_typed[:300],
        "last_assistant": (last_assistant or "")[-600:],
        "tickets": sorted(tix),
        "prs": sorted(prs.values()),
        "git_actions": dict(collections.Counter(git_actions)),
        "resume_cmd": f"cd {cwd} && {env}claude --resume {sid}" if cwd else f"{env}claude --resume {sid}",
    }


def collapse_clones(sessions: list[dict]) -> tuple[list[dict], int]:
    """Short sessions repeating one prompt within minutes are one piece of work; keep the richest."""
    kept: list[dict] = []
    anchors: dict[str, dict] = {}
    collapsed = 0
    for s in sorted(sessions, key=lambda x: x["started"] or ""):
        key = re.sub(r"\W+", "", s["first_prompt"]).lower()[:80]
        anchor = anchors.get(key)
        same_burst = (
            anchor is not None and key and s["total_prompts"] <= CLONE_MAX_PROMPTS
            and anchor["total_prompts"] <= CLONE_MAX_PROMPTS
            and (parse_ts(s["started"]) - parse_ts(anchor["started"])).total_seconds() <= CLONE_WINDOW_SECONDS
        )
        if not same_burst:
            anchors[key] = s
            kept.append(s)
            continue
        collapsed += 1
        if s["tool_calls"] > anchor["tool_calls"]:
            kept[kept.index(anchor)] = s
            anchors[key] = s
    return kept, collapsed


def scan_sessions(config_dirs, since, until, min_turns, include_trivial=False, rules=None, context=None,
                  automation_prefixes=(), host_defaults=None):
    found = []
    trivial = 0
    automation = 0
    since_epoch = since.timestamp()
    for cd in config_dirs:
        proj = cd / "projects"
        if not proj.is_dir():
            continue
        for path in proj.glob("*/*.jsonl"):
            try:
                if path.stat().st_mtime < since_epoch:
                    continue
            except OSError:
                continue
            s = scan_session(path, since, until, cd, rules)
            if not s or s["turns_in_window"] < min_turns:
                continue
            if not include_trivial and s["tool_calls"] == 0 and s["total_prompts"] < 2:
                trivial += 1
                continue
            if automation_prefixes and s["total_prompts"] < 2 and s["first_prompt"].startswith(automation_prefixes):
                automation += 1
                continue
            s["context_basis"] = "evidence" if s["context"] else None
            if not s["context"] and (host_defaults or {}).get(cd.name):
                s["context"], s["context_basis"] = host_defaults[cd.name], "host default"
            found.append(s)
    found, collapsed = collapse_clones(found)
    excluded: collections.Counter = collections.Counter()
    if context:
        for s in found:
            if not matches_context(s["context"], context):
                excluded[s["context"] or "unclassified"] += 1
        found = [s for s in found if matches_context(s["context"], context)]
    found.sort(key=lambda s: s["active_to"] or "", reverse=True)
    return found, {"trivial_skipped": trivial, "automation_skipped": automation, "clones_collapsed": collapsed, "excluded_by_context": dict(excluded)}


def repo_root(path: str) -> str | None:
    p = Path(path)
    while p != p.parent and not p.exists():
        p = p.parent
    try:
        r = subprocess.run(["git", "-C", str(p), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def git_activity(cwds: set[str], since: dt.datetime) -> list[dict]:
    roots = {r for c in cwds if c and (r := repo_root(c))}
    out = []
    for root in sorted(roots):
        email = subprocess.run(["git", "-C", root, "config", "user.email"],
                               capture_output=True, text=True).stdout.strip()
        cmd = ["git", "-C", root, "log", "--all", "--no-merges", f"--since={since.isoformat()}",
               "--format=%h%x09%ad%x09%D%x09%s", "--date=iso-strict"]
        if email:
            cmd.append(f"--author={email}")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        commits = []
        for line in r.stdout.splitlines():
            h, date, refs, subj = (line.split("\t", 3) + ["", "", "", ""])[:4]
            commits.append({"sha": h, "date": date, "refs": refs, "subject": subj,
                            "tickets": sorted(tickets_in(subj, refs))})
        if commits:
            out.append({"repo": root, "commits": commits})
    return out


def link_tasks(tasks_json: Path, sessions: list[dict], git: list[dict]) -> tuple[list[dict], list[str]]:
    pull = json.loads(tasks_json.read_text())
    links = []
    used = set()
    for ctx, cdata in pull.get("contexts", {}).items():
        for sub, sdata in cdata.get("sub_contexts", {}).items():
            for t in sdata.get("tasks", []):
                tix = set(t.get("tickets") or [])
                if not tix:
                    continue
                ss = [s["session_id"] for s in sessions if tix & set(s["tickets"])]
                cs = [f'{g["repo"].rsplit("/", 1)[-1]}@{c["sha"]}' for g in git for c in g["commits"]
                      if tix & set(c["tickets"])]
                if ss or cs:
                    used.update(ss)
                    links.append({"ref": f'{t.get("source_tab")}!{t.get("row")}', "sub_context": sub,
                                  "action": t.get("action"), "tickets": sorted(tix),
                                  "sessions": ss, "commits": cs})
    unlinked = [s["session_id"] for s in sessions if s["session_id"] not in used]
    return links, unlinked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="auto")
    ap.add_argument("--until", default=None)
    ap.add_argument("--tasks", type=Path, default=None)
    ap.add_argument("--config-dir", action="append", type=Path, default=None)
    ap.add_argument("--min-turns", type=int, default=1)
    ap.add_argument("--context", default=None)
    ap.add_argument("--include-trivial", action="store_true")
    a = ap.parse_args()

    since, since_reason = resolve_since(a.since)
    until = parse_ts(a.until) if a.until else local_now()
    alias = host_alias()
    config_dirs = a.config_dir or discover_config_dirs()
    sessions, stats = scan_sessions(config_dirs, since, until, a.min_turns, a.include_trivial,
                                    load_context_rules(), a.context, load_automation_prefixes(),
                                    load_host_defaults(alias))
    git = git_activity({s["cwd"] for s in sessions}, since)
    result = {
        "generated_at": local_now().isoformat(timespec="seconds"),
        "host": alias,
        "since": since.isoformat(timespec="seconds"),
        "since_reason": since_reason,
        "until": until.isoformat(timespec="seconds"),
        "config_dirs": [str(c) for c in config_dirs],
        "context_filter": a.context,
        "session_count": len(sessions),
        "by_context": dict(collections.Counter(s["context"] or "unclassified" for s in sessions)),
        **stats,
        "sessions": sessions,
        "git": git,
    }
    if a.tasks:
        result["links"], result["unlinked_sessions"] = link_tasks(a.tasks, sessions, git)
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
