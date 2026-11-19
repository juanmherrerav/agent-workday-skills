#!/usr/bin/env python3
"""MeetingAnalysis config: load, validate, and print one context's resolved profile.

Config: $MEETING_ANALYSIS_CONFIG, else ${AGENT_SKILLS_CONFIG:-~/.config/agent-skills}/MeetingAnalysis/config.json

  meeting_config.py check              validate every context; exit 1 on a problem
  meeting_config.py show CONTEXT       resolved profile as JSON
  meeting_config.py env CONTEXT        resolved profile as shell assignments (for run_ingest.sh)
  meeting_config.py contexts           context names, one per line

The hard rule this file enforces: recording folders (archive, ingest home) must sit OUTSIDE
every git work tree, and meeting folders must not be the same place as recordings.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


def config_path() -> Path:
    if os.environ.get("MEETING_ANALYSIS_CONFIG"):
        return Path(os.environ["MEETING_ANALYSIS_CONFIG"]).expanduser()
    base = Path(os.environ.get("AGENT_SKILLS_CONFIG", "~/.config/agent-skills")).expanduser()
    return base / "MeetingAnalysis" / "config.json"


def expand(p: str | None) -> str:
    return str(Path(os.path.expandvars(p)).expanduser()) if p else ""


def load() -> dict:
    p = config_path()
    if not p.is_file():
        sys.exit(f"no MeetingAnalysis config at {p}; run Workflows/Setup.md (template: Templates/config.example.json)")
    return json.loads(p.read_text())


def in_git(path: str) -> bool:
    d = Path(path)
    while not d.exists() and d != d.parent:
        d = d.parent
    r = subprocess.run(["git", "-C", str(d), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return r.returncode == 0


def resolve(cfg: dict, name: str) -> dict:
    ctxs = cfg.get("contexts", {})
    key = next((k for k in ctxs if k.lower() == name.lower()), None)
    if key is None:
        sys.exit(f"unknown context '{name}' (have: {', '.join(ctxs) or 'none'})")
    c = ctxs[key]
    ingest = c.get("ingest", {})
    notes = c.get("notes", {})
    archive = expand(c.get("recordings_archive") or cfg.get("recordings_archive") or "~/Recordings/processed")
    return {
        "context": key,
        "meetings_dir": expand(c.get("meetings_dir")),
        "recordings_archive": archive,
        "confidential": bool(c.get("confidential")),
        "language": c.get("language", "auto"),
        "owner": cfg.get("owner", ""),
        "owner_aliases": cfg.get("owner_aliases", []),
        "roster_file": expand(cfg.get("roster_file")),
        "tracker": cfg.get("tracker", "none"),
        "tracker_sub_context": c.get("tracker_sub_context", ""),
        "tracker_sub_context_rules": c.get("tracker_sub_context_rules", []),
        "transcription_model": cfg.get("transcription_model", "turbo"),
        "notes_provider": notes.get("provider", "none"),
        "notes_account": notes.get("account", ""),
        "notes_backfill_start": notes.get("backfill_start", ""),
        "ingest_home": expand(ingest.get("home")) or str(Path(archive).parent / key),
        "ingest_interval_min": int(ingest.get("interval_min", 60)),
        "ingest_hours": ingest.get("hours", "8-20"),
        "ingest_tracker": ingest.get("tracker", "add"),
        "drive_recordings_dir": expand(ingest.get("drive_recordings_dir")),
        "ingest_allowed_tools": ingest.get("allowed_tools", []),
    }


def problems(p: dict) -> list[str]:
    out = []
    if not p["meetings_dir"]:
        out.append(f"{p['context']}: meetings_dir is required")
    for k in ("recordings_archive", "ingest_home", "drive_recordings_dir"):
        if p[k] and in_git(p[k]):
            out.append(f"{p['context']}: {k}={p[k]} is inside a git work tree; recordings would be committable")
    if p["meetings_dir"] and p["recordings_archive"] and Path(p["recordings_archive"]).resolve() == Path(p["meetings_dir"]).resolve():
        out.append(f"{p['context']}: recordings_archive must differ from meetings_dir")
    if p["notes_provider"] not in {"none", "google-meet", "pasted"}:
        out.append(f"{p['context']}: notes.provider must be none | google-meet | pasted")
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    cfg = load()
    if cmd == "contexts":
        print("\n".join(cfg.get("contexts", {})))
        return 0
    if cmd == "check":
        errs = [e for name in cfg.get("contexts", {}) for e in problems(resolve(cfg, name))]
        print(json.dumps({"config": str(config_path()), "contexts": list(cfg.get("contexts", {})),
                          "ok": not errs, "problems": errs}, indent=2))
        return 0 if not errs else 1
    if len(sys.argv) < 3:
        sys.exit(f"usage: meeting_config.py {cmd} CONTEXT")
    p = resolve(cfg, sys.argv[2])
    if cmd == "show":
        print(json.dumps({**p, "problems": problems(p)}, indent=2, ensure_ascii=False))
    elif cmd == "env":
        for k, v in p.items():
            name = k.upper()
            if k == "ingest_allowed_tools":  # a bash array
                print(f"{name}=({' '.join(shlex.quote(x) for x in v)})")
            elif isinstance(v, (list, dict)):
                print(f"{name}={shlex.quote(json.dumps(v))}")
            elif isinstance(v, bool):
                print(f"{name}={'true' if v else 'false'}")
            else:
                print(f"{name}={shlex.quote(str(v))}")
    else:
        sys.exit(f"unknown command '{cmd}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
