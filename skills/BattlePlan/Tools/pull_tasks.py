#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["gspread>=6.2", "openpyxl>=3.1"]
# ///
"""Pull open tasks from the tracker (csv | xlsx | gsheets) and print JSON grouped by context and sub-context."""

import calendar
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from tracker import DONE_STATUSES, ConfigError, TabNotFound, load_config, open_store

EMPTY_DEADLINES = {"", "—", "-", "n/a", "none", "tbd", "tba", "ongoing", "when available", "when possible", "no deadline"}
STALE_AFTER_DAYS = 14

PRIORITY_MAP = {
    "critical": ("Critical", 4), "blocker": ("Critical", 4), "highest": ("Critical", 4), "urgent": ("Critical", 4), "p0": ("Critical", 4),
    "high": ("High", 3), "p1": ("High", 3),
    "medium": ("Medium", 2), "normal": ("Medium", 2), "med": ("Medium", 2), "p2": ("Medium", 2),
    "low": ("Low", 1), "lowest": ("Low", 1), "p3": ("Low", 1), "p4": ("Low", 1),
}
GROUP_OWNERS = {"team", "all", "everyone", "internal team", "whole team"}
OWNER_SPLIT_RE = re.compile(r"\s*(?:\+|/|,|&|\band\b)\s*")

MONTH_RE = r"(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
MONTH_NUM = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
WEEKDAY_NUM = {d.lower(): i for i, d in enumerate(calendar.day_name)}
WEEKDAY_NUM.update({d.lower(): i for i, d in enumerate(calendar.day_abbr)})

ISO_RE = re.compile(r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})")
MONTH_DAY_RE = re.compile(MONTH_RE + r"\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(?P<year>\d{4}))?\b")
MONTH_YEAR_RE = re.compile(r"^" + MONTH_RE + r"\s+(?P<year>\d{4})$")
PART_OF_MONTH_RE = re.compile(r"^(?P<part>early|mid|end of|late|eom)[\s-]*" + MONTH_RE + r"(?:\s+(?P<year>\d{4}))?$")
HALF_RE = re.compile(r"^(?P<year>\d{4})\s*h(?P<half>[12])$|^h(?P<half2>[12])\s*(?P<year2>\d{4})$")
QUARTER_RE = re.compile(r"^(?P<year>\d{4})\s*q(?P<q>[1-4])$|^q(?P<q2>[1-4])\s*(?P<year2>\d{4})$")
WEEK_OF_RE = re.compile(r"^(?:week of|w/o|wk of)\s+(?P<rest>.+)$")
DEADLINE_DEPENDENCY_RE = re.compile(r"^(?:after|with|before|once|pending|following|upon|blocked|waiting|next session)\b")
ACTION_DEPENDENCY_RE = re.compile(r"\b(?:after|once|pending|blocked by|waiting (?:for|on)|depends on)\s+([^;,.()]+)", re.IGNORECASE)
TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,6})\b")


def sub_context_info(ctx: dict, sub_name: str) -> dict:
    sub = ctx["sub_contexts"].get(sub_name)
    if not sub:
        return {"thread_profile": "light", "repo": None}
    return {"thread_profile": sub.get("thread_profile", "medium"), "repo": sub.get("repo")}


def end_of_week(d: date) -> date:
    return d + timedelta(days=(4 - d.weekday()) % 7)


def last_day_of_month(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def month_number(name: str) -> int:
    return MONTH_NUM[name.lower()[:3]]


def parse_month_day(text: str, anchor: date) -> date | None:
    m = MONTH_DAY_RE.search(text)
    if not m:
        return None
    month = month_number(m.group("month"))
    day = int(m.group("day"))
    year = int(m.group("year")) if m.group("year") else anchor.year
    try:
        resolved = date(year, month, day)
    except ValueError:
        return None
    # A bare "Jan 5" written in December means next January, not eleven months ago.
    if not m.group("year") and (resolved - anchor).days < -180:
        resolved = date(year + 1, month, day)
    return resolved


def resolve_deadline(raw: str, anchor: date) -> dict:
    """Turn free-text deadlines into a date. kind: exact | approx | dependency | none | unknown."""
    text = raw.strip()
    low = re.sub(r"\([^)]*\)", " ", text.lower())
    low = re.sub(r"[~*]", " ", low)
    low = re.sub(r"\s+", " ", low).strip()

    if low in EMPTY_DEADLINES:
        return {"kind": "none", "resolved": None, "hint": None}

    m = ISO_RE.search(low)
    if m:
        try:
            return {"kind": "exact", "resolved": date(int(m["y"]), int(m["m"]), int(m["d"])), "hint": None}
        except ValueError:
            pass

    if DEADLINE_DEPENDENCY_RE.match(low):
        return {"kind": "dependency", "resolved": None, "hint": text}

    if low in {"today", "eod", "now"}:
        return {"kind": "exact", "resolved": anchor, "hint": None}
    if low == "asap":
        return {"kind": "approx", "resolved": anchor, "hint": None}
    if low in {"tomorrow", "today/tomorrow", "tomorrow/today", "today or tomorrow"}:
        return {"kind": "exact", "resolved": anchor + timedelta(days=1), "hint": None}
    if low in {"this week", "eow", "end of week", "end of the week", "by friday"}:
        return {"kind": "approx", "resolved": end_of_week(anchor), "hint": None}
    if low == "next week":
        return {"kind": "approx", "resolved": end_of_week(anchor + timedelta(days=7)), "hint": None}
    if low in {"this sprint", "current sprint"}:
        return {"kind": "approx", "resolved": anchor + timedelta(days=14), "hint": "sprint"}
    if low == "next sprint":
        return {"kind": "approx", "resolved": anchor + timedelta(days=28), "hint": "sprint"}
    if low in {"this month", "end of month", "eom"}:
        return {"kind": "approx", "resolved": last_day_of_month(anchor.year, anchor.month), "hint": None}

    m = WEEK_OF_RE.match(low)
    if m:
        inner = resolve_deadline(m["rest"], anchor)
        if inner["resolved"]:
            return {"kind": "approx", "resolved": end_of_week(inner["resolved"]), "hint": None}

    m = PART_OF_MONTH_RE.match(low)
    if m:
        month = month_number(m["month"])
        year = int(m["year"]) if m["year"] else anchor.year
        if not m["year"] and month < anchor.month - 6:
            year += 1
        part = m["part"]
        if part == "early":
            resolved = date(year, month, 10)
        elif part == "mid":
            resolved = date(year, month, 15)
        else:
            resolved = last_day_of_month(year, month)
        return {"kind": "approx", "resolved": resolved, "hint": None}

    m = MONTH_YEAR_RE.match(low)
    if m:
        return {"kind": "approx", "resolved": last_day_of_month(int(m["year"]), month_number(m["month"])), "hint": None}

    m = HALF_RE.match(low)
    if m:
        year = int(m["year"] or m["year2"])
        half = int(m["half"] or m["half2"])
        return {"kind": "approx", "resolved": date(year, 6, 30) if half == 1 else date(year, 12, 31), "hint": None}

    m = QUARTER_RE.match(low)
    if m:
        year = int(m["year"] or m["year2"])
        q = int(m["q"] or m["q2"])
        return {"kind": "approx", "resolved": last_day_of_month(year, q * 3), "hint": None}

    resolved = parse_month_day(low, anchor)
    if resolved:
        return {"kind": "exact", "resolved": resolved, "hint": None}

    if low in WEEKDAY_NUM:
        days_ahead = (WEEKDAY_NUM[low] - anchor.weekday()) % 7
        return {"kind": "exact", "resolved": anchor + timedelta(days=days_ahead), "hint": None}

    if re.fullmatch(r"\d{4}", low):
        return {"kind": "approx", "resolved": date(int(low), 12, 31), "hint": None}

    return {"kind": "unknown", "resolved": None, "hint": text}


def normalize_priority(raw: str) -> tuple[str, int, bool]:
    low = raw.strip().lower()
    is_ongoing = low == "ongoing"
    label, rank = PRIORITY_MAP.get(low, ("Medium", 2))
    return label, rank, is_ongoing


def classify_owner(owner: str, aliases: set[str]) -> str:
    low = owner.strip().lower()
    if not low:
        return "unassigned"
    parts = [p.strip() for p in OWNER_SPLIT_RE.split(low) if p.strip()]
    has_me = any(p in aliases for p in parts)
    if any(p in GROUP_OWNERS for p in parts):
        return "shared"
    if has_me:
        return "mine" if len(parts) == 1 else "shared"
    return "theirs"


def extract_dependencies(action: str, deadline_info: dict) -> list[str]:
    deps = []
    if deadline_info["kind"] == "dependency":
        deps.append(deadline_info["hint"])
    for m in ACTION_DEPENDENCY_RE.finditer(action):
        deps.append(m.group(0).strip())
    return deps


def extract_tickets(*texts: str) -> list[str]:
    found = []
    for t in texts:
        for ticket in TICKET_RE.findall(t or ""):
            if ticket not in found:
                found.append(ticket)
    return found


def parse_tab_rows(rows: list[list[str]], tab_name: str) -> list[dict]:
    if len(rows) < 2:
        return []

    headers = [h.strip().lower() for h in rows[0]]
    tasks = []
    for row_idx, row in enumerate(rows[1:], start=2):
        cells = row + [""] * (len(headers) - len(row))
        record = {}
        for i, h in enumerate(headers):
            record[h] = cells[i].strip() if i < len(cells) else ""

        status = record.get("status", "").lower().strip()
        if status in DONE_STATUSES:
            continue

        action = record.get("action", "").strip()
        if not action:
            continue

        tasks.append({
            "date": record.get("date", ""),
            "meeting": record.get("meeting", ""),
            "number": record.get("#", ""),
            "row": row_idx,
            "action": action,
            "owner": record.get("owner", ""),
            "priority_raw": record.get("priority", ""),
            "deadline_raw": record.get("deadline", ""),
            "status": record.get("status", "") or "Open",
            "sub_context": record.get("sub-context", ""),
            "source_tab": tab_name,
        })

    return tasks


def enrich_task(task: dict, today: date, owner_aliases: set[str]) -> None:
    try:
        task_date = datetime.strptime(task["date"], "%Y-%m-%d").date()
        task["age_days"] = (today - task_date).days
    except (ValueError, TypeError):
        task_date = None
        task["age_days"] = None

    anchor = task_date or today
    dl = resolve_deadline(task["deadline_raw"], anchor)
    resolved = dl["resolved"]
    task["deadline"] = resolved.isoformat() if resolved else None
    task["deadline_kind"] = dl["kind"]

    due_in = (resolved - today).days if resolved else None
    task["due_in_days"] = due_in
    task["overdue_days"] = -due_in if due_in is not None and due_in < 0 else 0
    task["due_today"] = due_in == 0
    task["urgent"] = task["overdue_days"] > 0 or task["due_today"]

    label, rank, ongoing_priority = normalize_priority(task["priority_raw"])
    task["priority"] = label
    task["priority_rank"] = rank
    task["ongoing"] = ongoing_priority or task["deadline_raw"].strip().lower() == "ongoing"

    task["owner_kind"] = classify_owner(task["owner"], owner_aliases)
    task["depends_on"] = extract_dependencies(task["action"], dl)
    task["blocked"] = dl["kind"] == "dependency"
    task["tickets"] = extract_tickets(task["action"], task["meeting"], task["deadline_raw"])

    task["stale"] = (
        task["age_days"] is not None
        and task["age_days"] > STALE_AFTER_DAYS
        and dl["kind"] in {"none", "unknown"}
        and not task["ongoing"]
    )


def sort_key(task: dict):
    due = task["due_in_days"]
    return (
        0 if task["urgent"] else 1,
        -task["overdue_days"],
        -task["priority_rank"],
        due if due is not None else 10_000,
        -(task["age_days"] or 0),
    )


def main():
    filter_context = None
    owner_filter = False
    for arg in sys.argv[1:]:
        if arg == "--mine":
            owner_filter = True
        elif not arg.startswith("--"):
            filter_context = arg

    try:
        hierarchy = load_config()
        store = open_store(hierarchy)
    except ConfigError as e:
        print(json.dumps({"success": False, "error": str(e)}), file=sys.stderr)
        sys.exit(1)
    owner_aliases = set(a.lower() for a in hierarchy.get("owner_aliases", []))

    grouped: dict[str, dict] = {}
    counts = {"total": 0, "urgent": 0, "overdue": 0, "due_today": 0, "stale": 0, "blocked": 0, "ongoing": 0,
              "mine": 0, "shared": 0, "theirs": 0, "unassigned": 0}
    today = datetime.now().date()

    for ctx_name, ctx in hierarchy["contexts"].items():
        if filter_context and filter_context.lower() not in ctx_name.lower():
            continue
        try:
            ws = store.sheet(ctx["tab"])
        except TabNotFound:
            continue

        default_sub = next(iter(ctx["sub_contexts"]), "General")
        tasks = parse_tab_rows(ws.values(), ctx["tab"])

        for task in tasks:
            task["sub_context"] = task["sub_context"] or default_sub
            enrich_task(task, today, owner_aliases)

        if owner_filter:
            tasks = [t for t in tasks if t["owner_kind"] in {"mine", "shared", "unassigned"}]

        if not tasks:
            continue

        for task in tasks:
            counts["total"] += 1
            counts["urgent"] += task["urgent"]
            counts["overdue"] += task["overdue_days"] > 0
            counts["due_today"] += task["due_today"]
            counts["stale"] += task["stale"]
            counts["blocked"] += task["blocked"]
            counts["ongoing"] += task["ongoing"]
            counts[task["owner_kind"]] += 1

        group = grouped.setdefault(ctx_name, {"description": ctx.get("description", ""), "sub_contexts": {}})
        for task in tasks:
            sub_name = task["sub_context"]
            if sub_name not in group["sub_contexts"]:
                group["sub_contexts"][sub_name] = {**sub_context_info(ctx, sub_name), "tasks": []}
            group["sub_contexts"][sub_name]["tasks"].append(task)

        for sub in group["sub_contexts"].values():
            sub["tasks"].sort(key=sort_key)

    output = {
        "generated_at": datetime.now().isoformat(),
        "date": str(today),
        "total_open_tasks": counts["total"],
        "urgent_tasks": counts["urgent"],
        "overdue_tasks": counts["overdue"],
        "due_today_tasks": counts["due_today"],
        "stale_tasks": counts["stale"],
        "blocked_tasks": counts["blocked"],
        "ongoing_tasks": counts["ongoing"],
        "by_owner_kind": {k: counts[k] for k in ("mine", "shared", "theirs", "unassigned")},
        "filter_context": filter_context,
        "owner_filter": owner_filter,
        "contexts": grouped,
    }

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
