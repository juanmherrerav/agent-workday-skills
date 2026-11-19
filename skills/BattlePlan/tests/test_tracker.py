"""Round-trip the tracker tools on the local backends. Run: uv run --with pytest --with openpyxl pytest tests/"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).parent.parent / "Tools"


def cfg_for(tmp_path, backend):
    path = tmp_path / ("tracker.xlsx" if backend == "xlsx" else "tracker")
    cfg = {
        "owner": "Alex", "owner_aliases": ["Alex", "me"],
        "tracker": {"backend": backend, "path": str(path)},
        "plans_dir": str(tmp_path / "daily"),
        "contexts": {
            "Work": {"tab": "Work", "confidential": True, "forbidden_patterns": ["acme"],
                     "sub_contexts": {"Platform": {"thread_profile": "heavy"}, "Admin": {"thread_profile": "light"}}},
            "Home": {"tab": "Home", "sub_contexts": {"General": {"thread_profile": "medium"}}},
        },
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg))
    return p


def run(cfg, tool, *args, stdin=None, ok=True):
    env = {**os.environ, "BATTLEPLAN_CONFIG": str(cfg)}
    r = subprocess.run([sys.executable, str(TOOLS / tool), *args], input=stdin, capture_output=True, text=True, env=env)
    if ok:
        assert r.returncode == 0, r.stdout + r.stderr
    return r.returncode, json.loads(r.stdout) if r.stdout.strip() else None


@pytest.mark.parametrize("backend", ["csv", "xlsx"])
def test_full_cycle(tmp_path, backend):
    cfg = cfg_for(tmp_path, backend)
    _, out = run(cfg, "setup_tracker.py", "init")
    assert {t["tab"] for t in out["tabs"]} == {"Work", "Home", "Archive"}

    run(cfg, "manage_tasks.py", "add", "ABC-1: fix login retry", "--sub-context", "Platform", "--priority", "High",
        "--deadline", "2099-01-01")
    lines = "\n".join(json.dumps(x) for x in [
        {"action": "Renew passport", "sub_context": "General", "source": "Manual"},
        {"action": "ABC-2: review PR", "sub_context": "Platform", "source": "Meeting: Standup 2099-01-01"},
    ])
    _, out = run(cfg, "manage_tasks.py", "batch-add", stdin=lines)
    assert len(out["added"]) == 2
    _, out = run(cfg, "manage_tasks.py", "batch-add", stdin=lines)  # idempotent
    assert out["added"] == [] and len(out["skipped"]) == 2

    _, pull = run(cfg, "pull_tasks.py")
    assert pull["total_open_tasks"] == 3
    task = pull["contexts"]["Work"]["sub_contexts"]["Platform"]["tasks"][0]
    assert task["tickets"] == ["ABC-1"] and task["owner_kind"] == "mine"

    _, out = run(cfg, "manage_tasks.py", "batch-done", stdin=f"Work!{task['row']}\n")
    assert out["archived"] == 1
    _, pull = run(cfg, "pull_tasks.py")
    assert pull["total_open_tasks"] == 2

    _, out = run(cfg, "manage_tasks.py", "restore", "fix login")
    assert out["source_tab"] == "Work"
    _, pull = run(cfg, "pull_tasks.py", "work")
    assert pull["total_open_tasks"] == 2 and "Home" not in pull["contexts"]


def test_confidential_context_rejects_detail(tmp_path):
    cfg = cfg_for(tmp_path, "csv")
    run(cfg, "setup_tracker.py", "init")
    code, out = run(cfg, "manage_tasks.py", "add", "call ACME about 10.0.0.12", "--sub-context", "Platform", ok=False)
    assert code == 1 and "confidential" in out["error"]
