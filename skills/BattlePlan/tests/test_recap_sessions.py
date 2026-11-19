"""Tests for recap_sessions.py. Run: uv run --with pytest pytest tests/

All transcripts are synthetic; nothing reads real sessions.
"""
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("recap", Path(__file__).parent.parent / "Tools" / "recap_sessions.py")
recap = importlib.util.module_from_spec(spec)
sys.modules["recap"] = recap
spec.loader.exec_module(recap)

UTC = dt.timezone.utc
SINCE = dt.datetime(2026, 1, 1, tzinfo=UTC)
UNTIL = dt.datetime(2026, 1, 3, tzinfo=UTC)
TS = "2026-01-02T10:00:00Z"
RULES = {
    "Work": {"paths": ["/dev/work/", "notes-work"], "ticket_prefixes": ["WRK"], "config_dirs": [".claude-work"]},
    "Home": {"paths": ["notes-home", "/dev/home/"], "ticket_prefixes": [], "config_dirs": []},
}


def user(text, ts=TS, cwd="/dev/work/app", **extra):
    return {"type": "user", "timestamp": ts, "cwd": cwd, "entrypoint": "claude-vscode",
            "message": {"content": text}, **extra}


def assistant(text="ok", ts=TS, tools=()):
    content = [{"type": "text", "text": text}]
    content += [{"type": "tool_use", "name": n, "input": i} for n, i in tools]
    return {"type": "assistant", "timestamp": ts, "entrypoint": "claude-vscode", "message": {"content": content}}


BASH = ("Bash", {"command": "ls"})


def write_session(config_dir: Path, sid: str, records: list[dict]) -> Path:
    proj = config_dir / "projects" / "p"
    proj.mkdir(parents=True, exist_ok=True)
    path = proj / f"{sid}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records))
    return path


def scan(config_dir: Path, **kw):
    return recap.scan_sessions([config_dir], SINCE, UNTIL, 1, **kw)


# --- config dirs ---

def test_discovers_every_profile_with_projects(tmp_path, monkeypatch):
    for name in (".claude", ".claude-work", ".claude-other"):
        (tmp_path / name / "projects").mkdir(parents=True)
    (tmp_path / ".claude-noprojects").mkdir()
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    found = {p.name for p in recap.discover_config_dirs(tmp_path)}
    assert found == {".claude", ".claude-work", ".claude-other"}


def test_includes_active_config_dir_outside_home(tmp_path, monkeypatch):
    home, elsewhere = tmp_path / "home", tmp_path / "elsewhere"
    (home / ".claude" / "projects").mkdir(parents=True)
    (elsewhere / "projects").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(elsewhere))
    assert elsewhere.resolve() in {p.resolve() for p in recap.discover_config_dirs(home)}


def test_active_config_dir_is_not_listed_twice(tmp_path, monkeypatch):
    (tmp_path / ".claude-work" / "projects").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude-work"))
    assert len(recap.discover_config_dirs(tmp_path)) == 1


# --- hook children ---

def test_skips_one_prompt_no_tool_child(tmp_path):
    write_session(tmp_path, "child", [user("CONTEXT: summarize"), assistant("summary")])
    sessions, stats = scan(tmp_path)
    assert sessions == []
    assert stats["trivial_skipped"] == 1


def test_keeps_one_prompt_with_tools(tmp_path):
    write_session(tmp_path, "real", [user("fix it"), assistant(tools=[BASH])])
    assert [s["session_id"] for s in scan(tmp_path)[0]] == ["real"]


def test_keeps_two_prompts_without_tools(tmp_path):
    write_session(tmp_path, "chat", [user("q1"), assistant(), user("q2"), assistant()])
    assert len(scan(tmp_path)[0]) == 1


def test_include_trivial_restores_children(tmp_path):
    write_session(tmp_path, "child", [user("a question"), assistant("answer")])
    assert len(scan(tmp_path, include_trivial=True)[0]) == 1


def test_collapses_sibling_clones_keeping_the_richest(tmp_path):
    write_session(tmp_path, "small", [user("same prompt"), assistant(tools=[BASH])])
    write_session(tmp_path, "big", [user("same prompt"), assistant(tools=[BASH, BASH, BASH])])
    sessions, stats = scan(tmp_path)
    assert [s["session_id"] for s in sessions] == ["big"]
    assert stats["clones_collapsed"] == 1


def test_same_prompt_later_is_not_a_clone(tmp_path):
    write_session(tmp_path, "a", [user("/BattlePlan"), assistant(tools=[BASH])])
    write_session(tmp_path, "b", [user("/BattlePlan", ts="2026-01-02T15:00:00Z"), assistant(tools=[BASH])])
    assert len(scan(tmp_path)[0]) == 2


def test_long_session_is_never_collapsed_as_a_clone(tmp_path):
    many = [r for i in range(4) for r in (user(f"step {i}" if i else "same prompt"), assistant(tools=[BASH]))]
    write_session(tmp_path, "long", many)
    write_session(tmp_path, "short", [user("same prompt"), assistant(tools=[BASH, BASH])])
    assert {s["session_id"] for s in scan(tmp_path)[0]} == {"long", "short"}


def test_skips_automation_prompt_even_with_tools(tmp_path):
    write_session(tmp_path, "bot", [user("CONTEXT: do a thing"), assistant(tools=[BASH])])
    sessions, stats = scan(tmp_path, automation_prefixes=("CONTEXT:",))
    assert sessions == []
    assert stats["automation_skipped"] == 1


def test_human_follow_up_rescues_a_session_that_starts_like_automation(tmp_path):
    write_session(tmp_path, "s", [user("CONTEXT: do a thing"), assistant(tools=[BASH]), user("now fix it"), assistant()])
    assert len(scan(tmp_path, automation_prefixes=("CONTEXT:",))[0]) == 1


def test_configured_prefixes_match_a_newline_after_context(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"automation_prompt_prefixes": ["CONTEXT:"]}))
    write_session(tmp_path, "bot", [user("CONTEXT:\nAssistant: hook text"), assistant(tools=[BASH])])
    sessions, stats = scan(tmp_path, automation_prefixes=recap.load_automation_prefixes(cfg))
    assert sessions == []
    assert stats["automation_skipped"] == 1


# --- prompt parsing ---

@pytest.mark.parametrize("raw,expected", [
    ("plain text", "plain text"),
    ("<ide_opened_file>x.py</ide_opened_file>\nfix the bug", "fix the bug"),
    ("<ide_selection>code</ide_selection> explain", "explain"),
    ("<system-reminder>noise</system-reminder>real ask", "real ask"),
    ("The user opened the file /a/b.py in the IDE.\nreal ask", "real ask"),
    ("<command-message>work-ticket</command-message>\n<command-name>/work-ticket</command-name>\n"
     "<command-args>WRK-1</command-args>", "/work-ticket WRK-1"),
    ("<command-name>/BattlePlan</command-name>", "/BattlePlan"),
    ('<pasted_content id="abc">the pasted ask</pasted_content>', "the pasted ask"),
    ("[Image #1] look at this", "look at this"),
    ("<div> is a tag I typed", "<div> is a tag I typed"),
])
def test_clean_prompt_keeps_what_the_human_said(raw, expected):
    assert recap.clean_prompt(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "<task-notification>done</task-notification>",
    "<local-command-stdout>x</local-command-stdout>", "<bash-stdout>x</bash-stdout>",
    "Caveat: local commands below", "[Request interrupted by user]", "[Image #1]",
    "This session is being continued from a previous conversation",
    "Base directory for this skill: /x", "<ide_opened_file>only this</ide_opened_file>",
])
def test_clean_prompt_rejects_what_no_human_typed(raw):
    assert recap.clean_prompt(raw) is None


def test_session_started_by_slash_command_is_kept_with_a_clean_first_prompt(tmp_path):
    write_session(tmp_path, "slash", [
        user("<command-name>/BattlePlan</command-name><command-args>--audit</command-args>"),
        assistant(tools=[BASH]),
    ])
    assert scan(tmp_path)[0][0]["first_prompt"] == "/BattlePlan --audit"


def test_compaction_summary_does_not_count_as_a_turn(tmp_path):
    write_session(tmp_path, "s", [
        user("real"), assistant(tools=[BASH]),
        user("This session is being continued from a previous conversation WRK-9"),
    ])
    s = scan(tmp_path)[0][0]
    assert s["turns_in_window"] == 1
    assert "WRK-9" not in s["tickets"]


# --- context ---

def signals(cwd=None, touched=None, tickets=(), config_dir=".claude"):
    return {"cwd": cwd, "touched": touched or {}, "tickets": list(tickets), "config_dir": config_dir}


@pytest.mark.parametrize("sig,expected", [
    (signals(cwd="/h/dev/work/app"), "Work"),
    (signals(cwd="/h/dev/repo", touched={"Home": 4}), "Home"),
    (signals(cwd="/h/dev/repo", tickets=["WRK-1"]), "Work"),
    (signals(cwd="/h/dev/repo", config_dir=".claude-work"), "Work"),
    (signals(cwd="/h/dev/repo"), None),
    (signals(cwd="/h/dev/work/app", touched={"Home": 40}), "Home"),
    (signals(cwd="/h/dev/repo", touched={"Home": 1}, config_dir=".claude-work"), "Work"),
])
def test_classify_context(sig, expected):
    assert recap.classify_context(sig, RULES) == expected


def test_tie_is_unclassified_not_a_guess():
    assert recap.classify_context(signals(touched={"Work": 3, "Home": 3}), RULES) is None


@pytest.mark.parametrize("wanted,ctx,keep", [
    ("work", "Work", True), ("WORK", "Work", True), ("home", "Work", False), ("work", None, False),
])
def test_context_filter_matches_like_pull_tasks(wanted, ctx, keep):
    assert recap.matches_context(ctx, wanted) is keep


def test_context_filter_excludes_and_reports(tmp_path):
    write_session(tmp_path, "w", [user("a", cwd="/x/dev/work/app"), assistant(tools=[BASH])])
    write_session(tmp_path, "h", [user("b", cwd="/x/dev/home/app"), assistant(tools=[BASH])])
    write_session(tmp_path, "u", [user("c", cwd="/x/other"), assistant(tools=[BASH])])
    sessions, stats = scan(tmp_path, rules=RULES, context="work")
    assert [s["session_id"] for s in sessions] == ["w"]
    assert stats["excluded_by_context"] == {"Home": 1, "unclassified": 1}


def test_tool_paths_count_toward_context(tmp_path):
    write_session(tmp_path, "s", [
        user("notes", cwd="/x/shared"),
        assistant(tools=[("Read", {"file_path": "/x/shared/notes-home/a.md"}), ("Bash", {"command": "ls /x/shared/notes-home"})]),
    ])
    assert scan(tmp_path, rules=RULES)[0][0]["context"] == "Home"


# --- host identity and handoffs (batch 2) ---

@pytest.mark.parametrize("env,system,release,expected", [
    ("laptop2", "Linux", "x", "laptop2"),
    (None, "Darwin", "23.0", "mac"),
    (None, "Linux", "6.1-microsoft-standard-WSL2", "wsl"),
    (None, "Linux", "6.1-generic", "linux"),
])
def test_host_alias_never_uses_the_hostname(monkeypatch, env, system, release, expected):
    if env:
        monkeypatch.setenv("BATTLEPLAN_HOST_ALIAS", env)
    else:
        monkeypatch.delenv("BATTLEPLAN_HOST_ALIAS", raising=False)
    assert recap.host_alias(system=system, release=release) == expected


def write_handoff(daily: Path, name: str, closed: str | None) -> Path:
    daily.mkdir(exist_ok=True)
    p = daily / name
    p.write_text((f"Closed: {closed} on x\n" if closed else "") + "# Handoff\n")
    return p


def test_handoff_time_comes_from_the_file_not_mtime(tmp_path):
    write_handoff(tmp_path, "2026-01-02-handoff-wsl.md", "2026-01-02T18:30:00-03:00")
    got = recap.last_handoff_time(tmp_path, "wsl")
    assert got == dt.datetime.fromisoformat("2026-01-02T18:30:00-03:00")


def test_other_hosts_handoff_does_not_move_this_hosts_window(tmp_path):
    write_handoff(tmp_path, "2026-01-01-handoff-wsl.md", "2026-01-01T18:00:00-03:00")
    write_handoff(tmp_path, "2026-01-02-handoff-mac.md", "2026-01-02T19:00:00-03:00")
    assert recap.last_handoff_time(tmp_path, "wsl") == dt.datetime.fromisoformat("2026-01-01T18:00:00-03:00")


def test_handoff_without_closed_line_is_ignored(tmp_path):
    write_handoff(tmp_path, "2026-01-02-handoff-wsl.md", None)
    assert recap.last_handoff_time(tmp_path, "wsl") is None


def test_newest_handoff_by_closed_time_wins(tmp_path):
    write_handoff(tmp_path, "2026-01-02-handoff-wsl.md", "2026-01-02T18:00:00-03:00")
    write_handoff(tmp_path, "2026-01-03-handoff-wsl.md", "2026-01-03T17:00:00-03:00")
    assert recap.last_handoff_time(tmp_path, "wsl").day == 3


# --- per-host default context (batch 2) ---

def test_unmatched_session_takes_the_hosts_default_for_its_profile(tmp_path):
    cfg = tmp_path / ".claude"
    write_session(cfg, "s", [user("rename some files", cwd="/x/misc"), assistant(tools=[BASH])])
    s = recap.scan_sessions([cfg], SINCE, UNTIL, 1, rules=RULES, host_defaults={".claude": "Home"})[0][0]
    assert (s["context"], s["context_basis"]) == ("Home", "host default")


def test_evidence_beats_the_host_default(tmp_path):
    cfg = tmp_path / ".claude"
    write_session(cfg, "s", [user("x", cwd="/x/dev/work/app"), assistant(tools=[BASH])])
    s = recap.scan_sessions([cfg], SINCE, UNTIL, 1, rules=RULES, host_defaults={".claude": "Home"})[0][0]
    assert (s["context"], s["context_basis"]) == ("Work", "evidence")


def test_host_defaults_are_read_per_alias(tmp_path):
    h = tmp_path / "h.json"
    h.write_text(json.dumps({"hosts": {"wsl": {"default_context_by_config_dir": {".claude": "Home"}}}}))
    assert recap.load_host_defaults("wsl", h) == {".claude": "Home"}
    assert recap.load_host_defaults("mac", h) == {}
