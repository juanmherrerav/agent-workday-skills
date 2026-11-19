"""Tracker storage backends and config loading, shared by every BattlePlan tool.

A tracker is a set of named tabs. Each tab is a header row plus data rows (lists of strings).
Three backends implement the same small interface, so the planning tools never know where
the rows live:

  csv     a directory with one <tab>.csv per tab. Local, diff-friendly, works inside any
          synced folder (git, Dropbox, OneDrive, iCloud, Syncthing).
  xlsx    one Excel workbook, one sheet per tab. Local or in a synced folder (OneDrive /
          SharePoint / Google Drive for desktop). Close the file in Excel before writing.
  gsheets one Google Sheet, one worksheet per tab, through a service account (gspread).

Config: $BATTLEPLAN_CONFIG, else ${AGENT_SKILLS_CONFIG:-~/.config/agent-skills}/BattlePlan/config.json.
See Templates/config.example.json and Workflows/Setup.md.
"""
from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

TASK_HEADERS = ["Date", "Meeting", "#", "Sub-context", "Action", "Owner", "Priority", "Deadline", "Status"]
ARCHIVE_TAB = "Archive"
ARCHIVE_HEADERS = ["date", "meeting", "#", "action", "owner", "priority", "deadline", "status",
                   "source_tab", "archived_at", "sub_context"]
DONE_STATUSES = {"done", "completed", "closed", "cancelled", "canceled", "n/a", "resolved"}


class TabNotFound(KeyError):
    pass


class ConfigError(RuntimeError):
    pass


# ── config ────────────────────────────────────────────────────────────────────────────

def config_path() -> Path:
    if os.environ.get("BATTLEPLAN_CONFIG"):
        return Path(os.environ["BATTLEPLAN_CONFIG"]).expanduser()
    base = Path(os.environ.get("AGENT_SKILLS_CONFIG", "~/.config/agent-skills")).expanduser()
    return base / "BattlePlan" / "config.json"


def load_config(path: Path | None = None, required: bool = True) -> dict:
    path = path or config_path()
    if not path.is_file():
        if required:
            raise ConfigError(f"no BattlePlan config at {path}. Run the Setup workflow "
                              f"(Workflows/Setup.md) or copy Templates/config.example.json there.")
        return {}
    with path.open() as f:
        cfg = json.load(f)
    cfg.setdefault("contexts", {})
    cfg.setdefault("owner", "Me")
    cfg.setdefault("owner_aliases", [cfg["owner"], "me"])
    return cfg


def expand(p: str | None) -> Path | None:
    return Path(os.path.expandvars(p)).expanduser() if p else None


def plans_dir(cfg: dict) -> Path:
    return expand(cfg.get("plans_dir")) or (config_path().parent / "daily")


# ── backends ──────────────────────────────────────────────────────────────────────────

class Sheet:
    """One tab. Row numbers are 1-based and row 1 is the header, as in a spreadsheet UI."""

    name: str

    def values(self) -> list[list[str]]: ...
    def append_rows(self, rows: list[list[str]]) -> None: ...
    def delete_row(self, row: int) -> None: ...
    def set_cell(self, row: int, col: int, value: str) -> None: ...


class Store:
    def sheet(self, name: str) -> Sheet: ...
    def create_sheet(self, name: str, headers: list[str]) -> Sheet: ...
    def tab_names(self) -> list[str]: ...


def _safe_name(tab: str) -> str:
    return re.sub(r"[^\w .()-]+", "_", tab).strip() or "tab"


@contextmanager
def _locked(path: Path):
    """Advisory lock so two tools never rewrite the same local file at once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    try:
        import fcntl
    except ImportError:  # Windows: no advisory locks; single-writer is on the user
        yield
        return
    with lock.open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _atomic_write(path: Path, write) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            write(fh)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class CsvSheet(Sheet):
    def __init__(self, path: Path, name: str):
        self.path, self.name = path, name

    def values(self):
        with self.path.open(newline="", encoding="utf-8") as fh:
            return [row for row in csv.reader(fh)]

    def _rewrite(self, rows):
        _atomic_write(self.path, lambda fh: csv.writer(fh).writerows(rows))

    def append_rows(self, rows):
        with _locked(self.path):
            self._rewrite(self.values() + [list(map(str, r)) for r in rows])

    def delete_row(self, row):
        with _locked(self.path):
            rows = self.values()
            del rows[row - 1]
            self._rewrite(rows)

    def set_cell(self, row, col, value):
        with _locked(self.path):
            rows = self.values()
            while len(rows[row - 1]) < col:
                rows[row - 1].append("")
            rows[row - 1][col - 1] = value
            self._rewrite(rows)


class CsvStore(Store):
    def __init__(self, directory: Path):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name):
        return self.dir / f"{_safe_name(name)}.csv"

    def sheet(self, name):
        p = self._path(name)
        if not p.is_file():
            raise TabNotFound(name)
        return CsvSheet(p, name)

    def create_sheet(self, name, headers):
        p = self._path(name)
        if not p.exists():
            _atomic_write(p, lambda fh: csv.writer(fh).writerow(headers))
        return CsvSheet(p, name)

    def tab_names(self):
        return sorted(p.stem for p in self.dir.glob("*.csv"))


class XlsxStore(Store):
    """Whole workbook loaded per operation; tracker files are small, so simplicity wins."""

    def __init__(self, path: Path):
        import openpyxl  # noqa: F401  (fail early with a clear import error)
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self):
        import openpyxl
        if not self.path.exists():  # created on the first create_sheet; a workbook needs >= 1 sheet to save
            wb = openpyxl.Workbook()
            wb.remove(wb.active)
            return wb
        return openpyxl.load_workbook(self.path)

    def _save(self, wb):
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".xlsx")
        os.close(fd)
        try:
            wb.save(tmp)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def sheet(self, name):
        if name not in self._load().sheetnames:
            raise TabNotFound(name)
        return XlsxSheet(self, name)

    def create_sheet(self, name, headers):
        with _locked(self.path):
            wb = self._load()
            if name not in wb.sheetnames:
                ws = wb.create_sheet(name)
                ws.append(headers)
                self._save(wb)
        return XlsxSheet(self, name)

    def tab_names(self):
        return self._load().sheetnames


class XlsxSheet(Sheet):
    def __init__(self, store: XlsxStore, name: str):
        self.store, self.name = store, name

    def values(self):
        ws = self.store._load()[self.name]
        out = []
        for row in ws.iter_rows(values_only=True):
            cells = ["" if v is None else (v.strftime("%Y-%m-%d") if hasattr(v, "strftime") else str(v)) for v in row]
            while cells and cells[-1] == "":
                cells.pop()
            out.append(cells)
        while out and not out[-1]:
            out.pop()
        return out

    def _mutate(self, fn):
        with _locked(self.store.path):
            wb = self.store._load()
            fn(wb[self.name])
            self.store._save(wb)

    def append_rows(self, rows):
        def go(ws):
            n = 0  # last row holding any value; ws.max_row counts formatted empty rows too
            for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
                if any(v not in (None, "") for v in row):
                    n = idx
            for i, r in enumerate(rows, start=n + 1):
                for j, v in enumerate(r, start=1):
                    ws.cell(i, j, v)
        self._mutate(go)

    def delete_row(self, row):
        self._mutate(lambda ws: ws.delete_rows(row))

    def set_cell(self, row, col, value):
        self._mutate(lambda ws: ws.cell(row, col, value))


class GSheet(Sheet):
    def __init__(self, ws):
        self.ws, self.name = ws, ws.title

    def values(self):
        return self.ws.get_all_values()

    def append_rows(self, rows):
        self.ws.append_rows(rows, value_input_option="USER_ENTERED")

    def delete_row(self, row):
        self.ws.delete_rows(row)

    def set_cell(self, row, col, value):
        if col > self.ws.col_count:
            self.ws.add_cols(col - self.ws.col_count)
        self.ws.update_cell(row, col, value)


class GSheetsStore(Store):
    def __init__(self, spreadsheet_id: str, service_account: Path):
        import gspread
        self._gspread = gspread
        gc = gspread.service_account(filename=str(service_account), http_client=gspread.BackOffHTTPClient)
        self.sh = gc.open_by_key(spreadsheet_id)

    def sheet(self, name):
        try:
            return GSheet(self.sh.worksheet(name))
        except self._gspread.WorksheetNotFound:
            raise TabNotFound(name) from None

    def create_sheet(self, name, headers):
        try:
            return GSheet(self.sh.worksheet(name))
        except self._gspread.WorksheetNotFound:
            ws = self.sh.add_worksheet(title=name, rows=500, cols=len(headers))
            ws.update(values=[headers], range_name="A1", value_input_option="USER_ENTERED")
            ws.format("1:1", {"textFormat": {"bold": True}})
            return GSheet(ws)

    def tab_names(self):
        return [ws.title for ws in self.sh.worksheets()]


def open_store(cfg: dict) -> Store:
    t = cfg.get("tracker") or {}
    backend = t.get("backend", "csv")
    if backend == "csv":
        return CsvStore(expand(t.get("path")) or config_path().parent / "tracker")
    if backend == "xlsx":
        p = expand(t.get("path"))
        if not p:
            raise ConfigError("tracker.backend=xlsx needs tracker.path (the .xlsx file)")
        return XlsxStore(p)
    if backend == "gsheets":
        if not t.get("spreadsheet_id"):
            raise ConfigError("tracker.backend=gsheets needs tracker.spreadsheet_id")
        sa = expand(t.get("service_account", "~/.config/gspread/service_account.json"))
        return GSheetsStore(t["spreadsheet_id"], sa)
    raise ConfigError(f"unknown tracker.backend '{backend}' (csv | xlsx | gsheets)")


def headers_of(rows: list[list[str]]) -> list[str]:
    return [h.strip().lower() for h in rows[0]] if rows else []
