#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["gspread>=6.2", "openpyxl>=3.1"]
# ///
"""Manage tasks in the tracker (csv | xlsx | gsheets): add, batch-add, mark done/cancelled,
batch-done, restore, sweep, list-tabs. Every command prints one JSON object."""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from tracker import (ARCHIVE_HEADERS, ARCHIVE_TAB, DONE_STATUSES, ConfigError, TabNotFound,
                     headers_of, load_config, open_store)

ROW_REF_RE = re.compile(r"^(?P<tab>.+?)!(?P<row>\d+)$")
EXIT_AMBIGUOUS = 2


def fail(message, code=1, **extra):
    print(json.dumps({"success": False, "error": message, **extra}, indent=2, ensure_ascii=False))
    sys.exit(code)


# ── hierarchy helpers ─────────────────────────────────────────────────────────────────

def all_tabs(cfg) -> list[str]:
    return [ctx["tab"] for ctx in cfg["contexts"].values()]


def find_tab_for_subcontext(cfg, sub_context_name):
    """Resolve a sub-context name to (tab, context, canonical sub-context name)."""
    for ctx_name, ctx in cfg["contexts"].items():
        for sub_name in ctx.get("sub_contexts", {}):
            if sub_name.lower() == sub_context_name.lower():
                return ctx["tab"], ctx_name, sub_name
    return None, None, None


def default_sub_context(cfg, tab_name) -> str:
    for ctx in cfg["contexts"].values():
        if ctx["tab"] == tab_name:
            return next(iter(ctx.get("sub_contexts", {})), "")
    return ""


def sub_filter(args, cfg) -> str:
    if not getattr(args, "sub_context", None):
        return ""
    _, _, name = find_tab_for_subcontext(cfg, args.sub_context)
    if not name:
        fail(f"Unknown sub-context '{args.sub_context}'")
    return name.lower()


def tabs_for_scope(args, cfg) -> list[str]:
    if getattr(args, "tab", None):
        return [args.tab]
    if getattr(args, "sub_context", None):
        tab, _, _ = find_tab_for_subcontext(cfg, args.sub_context)
        if not tab:
            fail(f"Unknown sub-context '{args.sub_context}'")
        return [tab]
    return all_tabs(cfg)


# ── reading ───────────────────────────────────────────────────────────────────────────

def load_tabs(store, tab_names: list[str], pause: float = 0.0) -> dict:
    """Read each tab once. Returns {tab: {ws, headers, rows}} for tabs with action+status columns."""
    cache = {}
    for tab_name in tab_names:
        try:
            ws = store.sheet(tab_name)
        except TabNotFound:
            continue
        rows = ws.values()
        headers = headers_of(rows)
        if "action" in headers and "status" in headers:
            cache[tab_name] = {"ws": ws, "headers": headers, "rows": rows}
        if pause:
            time.sleep(pause)
    return cache


def row_record(cached: dict, row_idx: int):
    headers = cached["headers"]
    row = cached["rows"][row_idx - 1]
    cells = row + [""] * (len(headers) - len(row))
    return {h: cells[i].strip() for i, h in enumerate(headers)}, cells


def candidate_view(tab_name: str, row_idx: int, record: dict) -> dict:
    return {
        "ref": f"{tab_name}!{row_idx}", "tab": tab_name, "row": row_idx,
        "number": record.get("#", ""), "sub_context": record.get("sub-context", ""),
        "date": record.get("date", ""), "action": record.get("action", ""),
        "owner": record.get("owner", ""), "status": record.get("status", "") or "Open",
    }


def find_candidates(tab_cache, search, exclude=None, open_only=True, sub=""):
    """Numeric search matches the # column exactly; anything else is a case-insensitive substring of action."""
    exclude = exclude or set()
    term = search.strip()
    numeric = term.isdigit()
    out = []
    for tab_name, cached in tab_cache.items():
        for row_idx in range(2, len(cached["rows"]) + 1):
            if (tab_name, row_idx) in exclude:
                continue
            record, cells = row_record(cached, row_idx)
            if open_only and record.get("status", "").lower() in DONE_STATUSES:
                continue
            action = record.get("action", "")
            if not action or (sub and record.get("sub-context", "").lower() != sub):
                continue
            if (record.get("#", "") == term) if numeric else (term.lower() in action.lower()):
                out.append({**candidate_view(tab_name, row_idx, record), "cells": cells, "headers": cached["headers"]})
    return out


def resolve_row_ref(tab_cache, tab_name, row_idx):
    cached = tab_cache.get(tab_name)
    if not cached:
        fail(f"Tab '{tab_name}' not found or has no action/status columns")
    if row_idx < 2 or row_idx > len(cached["rows"]):
        fail(f"Row {row_idx} is out of range for tab '{tab_name}' (2..{len(cached['rows'])})")
    record, cells = row_record(cached, row_idx)
    if not record.get("action"):
        fail(f"{tab_name}!{row_idx} has no action text")
    if record.get("status", "").lower() in DONE_STATUSES:
        fail(f"{tab_name}!{row_idx} is already '{record['status']}'")
    return {**candidate_view(tab_name, row_idx, record), "cells": cells, "headers": cached["headers"]}


# ── archive ───────────────────────────────────────────────────────────────────────────

def archive_sheet(store):
    ws = store.create_sheet(ARCHIVE_TAB, ARCHIVE_HEADERS)
    headers = headers_of(ws.values())
    if "sub_context" not in headers:  # archives created by older versions lacked the column
        ws.set_cell(1, len(headers) + 1, "sub_context")
    return ws


def archive_row(store, source_ws, row_index, cells, headers, tab_name):
    """Copy a row to Archive, then delete it from the source tab."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cells = cells + [""] * (len(headers) - len(cells))
    out = []
    for ah in ARCHIVE_HEADERS:
        if ah == "source_tab":
            out.append(tab_name)
        elif ah == "archived_at":
            out.append(now)
        elif ah == "sub_context":
            out.append(cells[headers.index("sub-context")] if "sub-context" in headers else "")
        else:
            out.append(cells[headers.index(ah)] if ah in headers else "")
    archive_sheet(store).append_rows([out])
    source_ws.delete_row(row_index)


def apply_status_and_archive(store, tab_cache, candidate, target_status):
    cached = tab_cache[candidate["tab"]]
    cells = list(candidate["cells"])
    status_idx = cached["headers"].index("status")
    previous = cells[status_idx]
    cells[status_idx] = target_status
    archive_row(store, cached["ws"], candidate["row"], cells, cached["headers"], candidate["tab"])
    return previous


# ── commands ──────────────────────────────────────────────────────────────────────────

def next_number(rows, headers) -> int:
    if "#" not in headers:
        return 0
    i, best = headers.index("#"), 0
    for r in rows[1:]:
        try:
            best = max(best, int(r[i]))
        except (ValueError, IndexError):
            pass
    return best + 1


def build_row(headers, fields: dict) -> list[str]:
    row = [""] * len(headers)
    for field, value in fields.items():
        if field in headers:
            row[headers.index(field)] = value
    return row


def check_confidential(cfg, tab_name, text):
    """Contexts marked confidential reject task text that looks like it carries internal detail."""
    for ctx in cfg["contexts"].values():
        if ctx["tab"] == tab_name and ctx.get("confidential"):
            for pat in ctx.get("forbidden_patterns", []) + [r"\b\d{1,3}(?:\.\d{1,3}){3}\b", r"https?://"]:
                if re.search(pat, text, re.IGNORECASE):
                    return (f"'{tab_name}' is confidential: task text matches /{pat}/. "
                            f"Use a ticket ID and a short generic summary.")
    return None


def cmd_add(args, cfg, store):
    tab_name, sub_name = args.tab, ""
    if args.sub_context:
        found_tab, _, sub_name = find_tab_for_subcontext(cfg, args.sub_context)
        sub_name = sub_name or args.sub_context
        tab_name = tab_name or found_tab
    elif tab_name:
        sub_name = default_sub_context(cfg, tab_name)
    if not tab_name:
        fail("Must specify --tab or --sub-context")
    if err := check_confidential(cfg, tab_name, f"{args.action} {args.source or ''}"):
        fail(err)
    try:
        ws = store.sheet(tab_name)
    except TabNotFound:
        fail(f"Tab '{tab_name}' not found (run setup_tracker.py init)")
    rows = ws.values()
    headers = headers_of(rows)
    number = next_number(rows, headers)
    ws.append_rows([build_row(headers, {
        "date": args.date or datetime.now().strftime("%Y-%m-%d"),
        "meeting": args.source or "Manual", "#": str(number), "sub-context": sub_name,
        "action": args.action, "owner": args.owner or cfg["owner"],
        "priority": args.priority or "Medium", "deadline": args.deadline or "", "status": "Open",
    })])
    print(json.dumps({"success": True, "action": "add", "tab": tab_name, "task": args.action,
                      "row_number": str(number) if number else None}, indent=2, ensure_ascii=False))


def norm_key(meeting, action):
    squash = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
    return squash(meeting), squash(action)


def cmd_batch_add(args, cfg, store):
    """Append many tasks from JSONL, one read per tab, skipping (source, action) pairs already
    in the tab or the Archive. Re-running the same import is a no-op.

    Each line: {"action", "sub_context" | "tab", "source", "date", "owner", "priority", "deadline"}.
    """
    lines = Path(args.file).read_text().splitlines() if args.file else sys.stdin.read().splitlines()
    items, bad = [], []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as e:
            bad.append({"line": n, "error": str(e)})
            continue
        if not item.get("action"):
            bad.append({"line": n, "error": "missing action"})
            continue
        tab, sub = item.get("tab"), ""
        if item.get("sub_context"):
            found_tab, _, sub = find_tab_for_subcontext(cfg, item["sub_context"])
            if not found_tab:
                bad.append({"line": n, "error": f"unknown sub-context '{item['sub_context']}'"})
                continue
            tab = tab or found_tab
        elif tab:
            sub = default_sub_context(cfg, tab)
        if not tab:
            bad.append({"line": n, "error": "needs sub_context or tab"})
            continue
        if err := check_confidential(cfg, tab, f"{item['action']} {item.get('source', '')}"):
            bad.append({"line": n, "error": err})
            continue
        items.append({**item, "tab": tab, "sub_context": sub})
    if bad and not args.dry_run:
        fail("Invalid input lines; nothing written", invalid=bad)

    existing = set()
    try:
        arch = store.sheet(ARCHIVE_TAB).values()
        ah = headers_of(arch)
        if "meeting" in ah and "action" in ah:
            for r in arch[1:]:
                if len(r) > ah.index("action"):
                    existing.add(norm_key(r[ah.index("meeting")], r[ah.index("action")]))
    except TabNotFound:
        pass

    today = datetime.now().strftime("%Y-%m-%d")
    added, skipped = [], []
    for tab_name in dict.fromkeys(i["tab"] for i in items):
        try:
            ws = store.sheet(tab_name)
        except TabNotFound:
            fail(f"Tab '{tab_name}' not found (run setup_tracker.py init)")
        values = ws.values()
        headers = headers_of(values)
        col = lambda r, name: r[headers.index(name)] if name in headers and len(r) > headers.index(name) else ""
        seen = existing | {norm_key(col(r, "meeting"), col(r, "action")) for r in values[1:]}
        number = next_number(values, headers) - 1
        rows = []
        for item in (i for i in items if i["tab"] == tab_name):
            source = item.get("source") or "Manual"
            key = norm_key(source, item["action"])
            if key in seen:
                skipped.append({"tab": tab_name, "task": item["action"], "reason": "already tracked"})
                continue
            seen.add(key)
            number += 1
            rows.append(build_row(headers, {
                "date": item.get("date") or today, "meeting": source, "#": str(number),
                "sub-context": item["sub_context"], "action": item["action"],
                "owner": item.get("owner") or cfg["owner"], "priority": item.get("priority") or "Medium",
                "deadline": item.get("deadline") or "", "status": "Open",
            }))
            added.append({"tab": tab_name, "task": item["action"], "number": str(number)})
        if rows and not args.dry_run:
            ws.append_rows(rows)

    print(json.dumps({"success": not bad, "action": "batch-add", "dry_run": args.dry_run,
                      "would_add" if args.dry_run else "added": added, "skipped": skipped,
                      "invalid": bad}, indent=2, ensure_ascii=False))
    if bad:
        sys.exit(1)


def cmd_set_status(args, cfg, store, target_status):
    if args.row is not None and not args.tab:
        fail("--row requires --tab")
    tab_cache = load_tabs(store, tabs_for_scope(args, cfg))
    if args.row is not None:
        target = resolve_row_ref(tab_cache, args.tab, args.row)
    else:
        candidates = find_candidates(tab_cache, args.search, sub=sub_filter(args, cfg))
        if not candidates:
            fail(f"No open task matching '{args.search}'")
        if len(candidates) > 1:
            fail(f"'{args.search}' matches {len(candidates)} open tasks — re-run with --tab \"<tab>\" --row <row>",
                 code=EXIT_AMBIGUOUS, ambiguous=True,
                 candidates=[{k: c[k] for k in ("ref", "tab", "row", "number", "sub_context", "date", "owner", "action")}
                             for c in candidates])
        target = candidates[0]

    summary = {k: target[k] for k in ("ref", "tab", "row", "number", "action", "owner")}
    if args.dry_run:
        print(json.dumps({"success": True, "dry_run": True, "would": f"mark-{target_status.lower()} + archive", **summary},
                         indent=2, ensure_ascii=False))
        return
    previous = apply_status_and_archive(store, tab_cache, target, target_status)
    print(json.dumps({"success": True, "action": f"mark-{target_status.lower()}", **summary, "task": target["action"],
                      "new_status": target_status, "previous_status": previous, "archived": True},
                     indent=2, ensure_ascii=False))


def cmd_batch_done(args, cfg, store, target_status):
    """Resolve every line first (refusing ambiguous ones), then archive bottom-up per tab."""
    src = open(args.file) if args.file else sys.stdin
    lines = [line.strip() for line in src if line.strip()]
    if not lines:
        fail("No search terms provided")
    remote = (cfg.get("tracker") or {}).get("backend") == "gsheets"
    tab_cache = load_tabs(store, tabs_for_scope(args, cfg), pause=0.5 if remote else 0.0)

    matches, problems, taken = [], [], set()
    sub = sub_filter(args, cfg)
    for line in lines:
        ref = ROW_REF_RE.match(line)
        if ref:
            tab_name, row_idx = ref["tab"].strip(), int(ref["row"])
            if tab_name not in tab_cache:
                problems.append({"search": line, "error": f"tab '{tab_name}' not loaded"})
                continue
            if row_idx < 2 or row_idx > len(tab_cache[tab_name]["rows"]):
                problems.append({"search": line, "error": "row out of range"})
                continue
            record, cells = row_record(tab_cache[tab_name], row_idx)
            if not record.get("action") or record.get("status", "").lower() in DONE_STATUSES:
                problems.append({"search": line, "error": "row is empty or already closed"})
                continue
            if (tab_name, row_idx) in taken:
                problems.append({"search": line, "error": "row already claimed by an earlier line"})
                continue
            candidate = {**candidate_view(tab_name, row_idx, record), "cells": cells,
                         "headers": tab_cache[tab_name]["headers"]}
        else:
            found = find_candidates(tab_cache, line, exclude=taken, sub=sub)
            if not found:
                problems.append({"search": line, "error": "not found"})
                continue
            if len(found) > 1:
                problems.append({"search": line, "error": f"ambiguous ({len(found)} matches) — use a Tab!row reference",
                                 "candidates": [c["ref"] + "  " + c["action"][:70] for c in found]})
                continue
            candidate = found[0]
        taken.add((candidate["tab"], candidate["row"]))
        matches.append({**candidate, "search": line})

    planned = [{"search": m["search"], "ref": m["ref"], "action": m["action"]} for m in matches]
    if args.dry_run:
        print(json.dumps({"success": True, "dry_run": True, "would_archive": planned, "skipped": problems},
                         indent=2, ensure_ascii=False))
        return

    archived = []
    by_tab = {}
    for m in matches:
        by_tab.setdefault(m["tab"], []).append(m)
    for tab_matches in by_tab.values():
        for m in sorted(tab_matches, key=lambda x: x["row"], reverse=True):  # bottom-up keeps row numbers valid
            apply_status_and_archive(store, tab_cache, m, target_status)
            archived.append({"search": m["search"], "ref": m["ref"], "action": m["action"]})
            if remote:
                time.sleep(1.2)  # Sheets API write quota

    print(json.dumps({"success": True, "status": target_status, "total": len(lines), "archived": len(archived),
                      "skipped": len(problems), "details": archived, "problems": problems},
                     indent=2, ensure_ascii=False))


def cmd_restore(args, cfg, store):
    """Move a row from Archive back to its source tab as Open."""
    try:
        archive_ws = store.sheet(ARCHIVE_TAB)
    except TabNotFound:
        fail("No Archive tab exists")
    rows = archive_ws.values()
    if len(rows) < 2:
        fail("Archive is empty")
    headers = headers_of(rows)
    cache = {ARCHIVE_TAB: {"ws": archive_ws, "headers": headers, "rows": rows}}

    if args.row is not None:
        if args.row < 2 or args.row > len(rows):
            fail(f"Archive row {args.row} out of range (2..{len(rows)})")
        record, cells = row_record(cache[ARCHIVE_TAB], args.row)
        target = {**candidate_view(ARCHIVE_TAB, args.row, record), "cells": cells}
    else:
        candidates = find_candidates(cache, args.search, open_only=False)
        if not candidates:
            fail(f"Nothing in Archive matching '{args.search}'")
        if len(candidates) > 1:
            fail(f"'{args.search}' matches {len(candidates)} archived rows — re-run with --row <row>",
                 code=EXIT_AMBIGUOUS, ambiguous=True,
                 candidates=[{k: c[k] for k in ("ref", "row", "number", "date", "status", "action")} for c in candidates])
        target = candidates[0]

    record = dict(zip(headers, target["cells"]))
    source_tab = record.get("source_tab", "").strip()
    if not source_tab:
        fail(f"Archive row {target['row']} has no source_tab")
    try:
        dest_ws = store.sheet(source_tab)
    except TabNotFound:
        fail(f"Source tab '{source_tab}' no longer exists")

    dest_headers = headers_of(dest_ws.values())
    new_row = [""] * len(dest_headers)
    for i, h in enumerate(dest_headers):
        if h == "status":
            new_row[i] = "Open"
        elif h == "sub-context":
            new_row[i] = record.get("sub_context", "")
        elif h in record and h not in {"source_tab", "archived_at"}:
            new_row[i] = record[h]

    summary = {"archive_row": target["row"], "source_tab": source_tab, "action": record.get("action", ""),
               "previous_status": record.get("status", "")}
    if args.dry_run:
        print(json.dumps({"success": True, "dry_run": True, "would": "restore as Open", **summary},
                         indent=2, ensure_ascii=False))
        return
    dest_ws.append_rows([new_row])
    archive_ws.delete_row(target["row"])
    print(json.dumps({"success": True, "action": "restore", **summary, "new_status": "Open"}, indent=2, ensure_ascii=False))


def cmd_sweep(args, cfg, store):
    """Move all done/cancelled rows into the Archive tab."""
    total, details = 0, []
    sub = sub_filter(args, cfg)
    for tab_name in tabs_for_scope(args, cfg):
        try:
            ws = store.sheet(tab_name)
        except TabNotFound:
            continue
        rows = ws.values()
        headers = headers_of(rows)
        if "status" not in headers:
            continue
        status_col = headers.index("status")
        to_move = []
        for i, row in enumerate(rows[1:], start=2):
            cells = row + [""] * (len(headers) - len(row))
            if sub and "sub-context" in headers and cells[headers.index("sub-context")].strip().lower() != sub:
                continue
            if cells[status_col].strip().lower() in DONE_STATUSES:
                to_move.append((i, cells))
        if args.dry_run:
            if to_move:
                details.append({"tab": tab_name, "would_archive": len(to_move)})
            continue
        for row_idx, cells in reversed(to_move):
            archive_row(store, ws, row_idx, cells, headers, tab_name)
            total += 1
        if to_move:
            details.append({"tab": tab_name, "archived": len(to_move)})
    print(json.dumps({"success": True, "action": "sweep", "dry_run": args.dry_run, "total_archived": total,
                      "tabs": details}, indent=2, ensure_ascii=False))


def cmd_list_tabs(cfg):
    print(json.dumps([{"context": c, "sub_context": s, "tab": ctx["tab"]}
                      for c, ctx in cfg["contexts"].items() for s in ctx.get("sub_contexts", {})],
                     indent=2, ensure_ascii=False))


def add_target_args(p, search_help):
    p.add_argument("search", nargs="?", default="", help=search_help)
    p.add_argument("--tab", help="Limit search to this tab (required with --row)")
    p.add_argument("--sub-context", help="Limit search to this sub-context")
    p.add_argument("--row", type=int, help="Exact row number (1-indexed, header is row 1)")
    p.add_argument("--dry-run", action="store_true", help="Show what would change without writing")


def main():
    parser = argparse.ArgumentParser(description="Manage tasks in the BattlePlan tracker")
    sp = parser.add_subparsers(dest="command", required=True)

    a = sp.add_parser("add", help="Add a new task")
    a.add_argument("action", help="Task description")
    a.add_argument("--tab")
    a.add_argument("--sub-context")
    a.add_argument("--owner", default=None, help="default: config owner")
    a.add_argument("--priority", default="Medium")
    a.add_argument("--deadline", default="")
    a.add_argument("--date", help="Task date (default: today)")
    a.add_argument("--source", default="Manual", help="Where the task came from, e.g. 'Ticket ABC-123', 'Chat', 'Manual'")

    b = sp.add_parser("batch-add", help="Add many tasks from JSONL (stdin or --file); skips ones already tracked or archived")
    b.add_argument("--file")
    b.add_argument("--dry-run", action="store_true")

    add_target_args(sp.add_parser("mark-done", help="Mark one task done and archive it"),
                    "Task text (substring) or task # — must match exactly one open task")
    add_target_args(sp.add_parser("mark-cancelled", help="Mark one task cancelled and archive it"),
                    "Task text (substring) or task # — must match exactly one open task")

    bd = sp.add_parser("batch-done", help="Archive many tasks (stdin or --file, one per line; 'Tab!row' refs allowed)")
    bd.add_argument("--tab")
    bd.add_argument("--sub-context")
    bd.add_argument("--file")
    bd.add_argument("--status", default="Done")
    bd.add_argument("--dry-run", action="store_true")

    r = sp.add_parser("restore", help="Move an archived row back to its source tab as Open")
    r.add_argument("search", nargs="?", default="")
    r.add_argument("--row", type=int, help="Exact Archive row number")
    r.add_argument("--dry-run", action="store_true")

    s = sp.add_parser("sweep", help="Move all done/cancelled rows to Archive")
    s.add_argument("--tab")
    s.add_argument("--sub-context")
    s.add_argument("--dry-run", action="store_true")

    sp.add_parser("list-tabs", help="List known tabs and their contexts")

    args = parser.parse_args()
    try:
        cfg = load_config()
    except ConfigError as e:
        fail(str(e))
    if args.command == "list-tabs":
        cmd_list_tabs(cfg)
        return
    if args.command in {"mark-done", "mark-cancelled", "restore"} and not args.search and args.row is None:
        fail("Provide a search term or --row")
    try:
        store = open_store(cfg)
    except ConfigError as e:
        fail(str(e))

    {
        "add": lambda: cmd_add(args, cfg, store),
        "batch-add": lambda: cmd_batch_add(args, cfg, store),
        "mark-done": lambda: cmd_set_status(args, cfg, store, "Done"),
        "mark-cancelled": lambda: cmd_set_status(args, cfg, store, "Cancelled"),
        "batch-done": lambda: cmd_batch_done(args, cfg, store, args.status),
        "restore": lambda: cmd_restore(args, cfg, store),
        "sweep": lambda: cmd_sweep(args, cfg, store),
    }[args.command]()


if __name__ == "__main__":
    main()
