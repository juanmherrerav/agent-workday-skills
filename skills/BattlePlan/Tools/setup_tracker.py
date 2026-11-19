#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["gspread>=6.2", "openpyxl>=3.1"]
# ///
"""Create and check the BattlePlan tracker described by the config.

  setup_tracker.py check   config path, backend, plans dir, and which tabs exist (no writes)
  setup_tracker.py init    create every missing context tab plus Archive, with header rows
                           (idempotent: existing tabs and rows are never touched)
"""
import argparse
import json
import sys

from tracker import (ARCHIVE_HEADERS, ARCHIVE_TAB, TASK_HEADERS, ConfigError, TabNotFound,
                     config_path, headers_of, load_config, open_store, plans_dir)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["check", "init"])
    a = ap.parse_args()
    try:
        cfg = load_config()
        store = open_store(cfg)
    except (ConfigError, ImportError, OSError) as e:
        print(json.dumps({"success": False, "config": str(config_path()), "error": str(e)}, indent=2))
        return 1

    wanted = {ctx["tab"]: TASK_HEADERS for ctx in cfg["contexts"].values()}
    wanted[ARCHIVE_TAB] = ARCHIVE_HEADERS
    report, ok = [], True
    for tab, headers in wanted.items():
        try:
            rows = store.sheet(tab).values()
            missing = [h for h in ("action", "status") if h not in headers_of(rows)] if tab != ARCHIVE_TAB else []
            report.append({"tab": tab, "exists": True, "rows": max(len(rows) - 1, 0), "missing_columns": missing})
            ok &= not missing
        except TabNotFound:
            if a.command == "init":
                store.create_sheet(tab, headers)
                report.append({"tab": tab, "exists": True, "created": True, "rows": 0})
            else:
                report.append({"tab": tab, "exists": False})
                ok = False

    pd = plans_dir(cfg)
    if a.command == "init":
        pd.mkdir(parents=True, exist_ok=True)
    print(json.dumps({
        "success": ok or a.command == "init",
        "config": str(config_path()),
        "backend": (cfg.get("tracker") or {}).get("backend", "csv"),
        "plans_dir": str(pd), "plans_dir_exists": pd.is_dir(),
        "owner": cfg["owner"], "contexts": list(cfg["contexts"]),
        "tabs": report,
    }, indent=2, ensure_ascii=False))
    return 0 if ok or a.command == "init" else 2


if __name__ == "__main__":
    sys.exit(main())
