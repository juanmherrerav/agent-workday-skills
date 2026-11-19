#!/usr/bin/env python3
"""
jira_sync — the JIRA adapter of the IssueSync skill (local-first, usable from any git repo).

A development tool, not application code. Lives at IssueSync/Adapters/jira/ and is driven by
the sibling `adapter` script; a repo may vendor its own copy at
tools/jira-sync/jira_sync.py, which the skill prefers.

Subcommands
-----------
  list                       List active issues assigned to you (writes <runtime>/INDEX.md)
  pull [KEY ...]             Pull full JSON + comments to <runtime>/cache/ and seed worklogs.
                             No KEY → all active issues; one or more KEYs → just those.
  push KEY                   Post <runtime>/worklog/<KEY>.md as a comment on the issue.

  transition KEY [NAME]      Transition an issue. No NAME → list available transitions.
  show KEY                   Print a single issue's status + transitions (no file writes).
  assign KEY QUERY           Assign the issue to the first assignable user matching QUERY.

Runtime (git-ignored): <main checkout>/.claude/local/jira/  — override with JIRA_SYNC_DIR.
The main checkout is found through the common git dir, so running from inside a git worktree
uses the same cache as the repo root. (legacy <repo>/.jira-sync/ is honored if it exists.)

Auth: process env, then the current repo root's .env.local (wins) and .env:
  JIRA_CLOUD_URL | JIRA_BASE_URL
  JIRA_USER_EMAIL | JIRA_EMAIL
  JIRA_API_TOKEN
  JIRA_PROJECT_KEY   optional — when set, `list`/`pull` (no keys) only cover that project

Push format: the worklog is posted verbatim, so write it in Atlassian wiki markup
(h2. / *bold* / {{code}} / ||table||), not Markdown — Markdown renders as raw text.

Examples
--------
  python jira_sync.py list
  python jira_sync.py pull
  python jira_sync.py pull ABC-17
  python jira_sync.py push ABC-17
  python jira_sync.py transition ABC-17           # list transitions
  python jira_sync.py transition ABC-17 Resolved
  python jira_sync.py show ABC-20
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
    from jira import JIRA
except ImportError:
    print("❌ Required packages missing. Install with: uv pip install jira python-dotenv")
    sys.exit(1)

import os

BASE_JQL = "assignee = currentUser() AND statusCategory != Done"


def active_jql(project: str | None) -> str:
    scope = f' AND project = "{project}"' if project else ""
    return f"{BASE_JQL}{scope} ORDER BY updated DESC"


# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #
def repo_root() -> Path:
    """Root of the MAIN checkout.

    Inside a git worktree, `--show-toplevel` (or walking up to a `.git` entry) returns the
    worktree, which would split the cache per worktree. The common git dir always belongs to
    the main checkout, so its parent is the root we want. Falls back to walking up from CWD
    outside git.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if out:
            return Path(out).parent
    except (OSError, subprocess.CalledProcessError):
        pass
    here = Path.cwd()
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            return parent
    return here


def connect() -> tuple[JIRA, str, str | None]:
    """Load creds from the repo's .env(.local) and return (client, base_url, project_key)."""
    root = repo_root()
    load_dotenv(root / ".env.local", override=True)
    load_dotenv(root / ".env", override=False)

    url = os.getenv("JIRA_CLOUD_URL") or os.getenv("JIRA_BASE_URL")
    email = os.getenv("JIRA_USER_EMAIL") or os.getenv("JIRA_EMAIL")
    token = os.getenv("JIRA_API_TOKEN")
    project = os.getenv("JIRA_PROJECT_KEY") or None

    if not all([url, email, token]):
        print("❌ Missing JIRA credentials in .env / .env.local")
        print("   Need: (JIRA_CLOUD_URL|JIRA_BASE_URL), (JIRA_USER_EMAIL|JIRA_EMAIL), JIRA_API_TOKEN")
        sys.exit(1)

    assert url is not None  # guaranteed by the all() check above
    print(f"🔗 Connecting to {url} as {email}...")
    try:
        client = JIRA(server=url, basic_auth=(email, token))
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)
    return client, url, project


def sync_dir() -> Path:
    # Runtime/trace lives under the single ignored .claude/local/ folder.
    # Legacy .jira-sync/ is still honored if present (back-compat) but no longer created.
    override = os.getenv("JIRA_SYNC_DIR")
    root = repo_root()
    legacy = root / ".jira-sync"
    if override:
        d = Path(override).expanduser()
    else:
        d = legacy if (legacy / "cache").exists() else root / ".claude" / "local" / "jira"
    (d / "cache").mkdir(parents=True, exist_ok=True)
    (d / "worklog").mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #
def cmd_list(jira: JIRA, base_url: str, project: str | None) -> int:
    jql = active_jql(project)
    issues = jira.search_issues(jql, maxResults=50)
    if not issues:
        print("✅ No active issues assigned to you")
        return 0

    print(f"\n📋 {len(issues)} active issue(s):\n" + "-" * 90)
    for i in issues:
        print(f"  {i.key}: {i.fields.summary}")
        print(f"     {i.fields.status.name} | updated {i.fields.updated[:10]} | {base_url}/browse/{i.key}")
    print("-" * 90)

    index = sync_dir() / "INDEX.md"
    lines = [
        f"# Active JIRA Issues — {project or 'all projects'}\n",
        f"**Query:** `{jql}`",
        f"**Count:** {len(issues)}",
        f"**Updated:** {datetime.now().isoformat()}\n",
        "---\n",
    ]
    for i in issues:
        lines += [
            f"## [{i.key}] {i.fields.summary}\n",
            f"- **Status:** {i.fields.status.name}",
            f"- **Updated:** {i.fields.updated[:10]}",
            f"- **URL:** {base_url}/browse/{i.key}\n",
        ]
    index.write_text("\n".join(lines), encoding="utf-8")
    print(f"💾 Index → {index}")
    return 0


def _pull_one(jira: JIRA, base_url: str, key: str) -> None:
    issue = jira.issue(key)
    f = issue.fields
    data = {
        "key": issue.key,
        "id": issue.id,
        "summary": f.summary,
        "status": f.status.name,
        "status_category": f.status.statusCategory.name,
        "assignee": f.assignee.displayName if f.assignee else None,
        "reporter": f.reporter.displayName if f.reporter else None,
        "priority": f.priority.name if f.priority else None,
        "created": f.created,
        "updated": f.updated,
        "description": f.description or "",
        "labels": f.labels or [],
        "components": [c.name for c in f.components] if f.components else [],
        "url": f"{base_url}/browse/{issue.key}",
        "sync_timestamp": datetime.now().isoformat(),
    }
    try:
        data["comments"] = [
            {
                "id": c.id,
                "author": getattr(c.author, "displayName", str(c.author)),
                "body": c.body,
                "created": c.created,
                "updated": c.updated,
            }
            for c in jira.comments(issue)
        ]
    except Exception as e:  # noqa: BLE001
        data["comments"] = []
        print(f"   ⚠️  comments unavailable for {key}: {e}")

    cache = sync_dir() / "cache" / f"{key}.json"
    cache.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    worklog = sync_dir() / "worklog" / f"{key}.md"
    if not worklog.exists():
        worklog.write_text(
            f"h2. {key}: {f.summary}\n\n"
            f"*Status:* {f.status.name}\n"
            f"*URL:* {base_url}/browse/{key}\n"
            f"*Last Synced:* {datetime.now():%Y-%m-%d %H:%M:%S}\n\n"
            "----\n\nh3. Work Notes\n\n_Add your work notes here..._\n",
            encoding="utf-8",
        )
        print(f"   📝 worklog → {worklog}")
    print(f"   ✅ {key}: {f.summary}  →  {cache}")


def cmd_pull(jira: JIRA, base_url: str, project: str | None, keys: list[str]) -> int:
    if not keys:
        issues = jira.search_issues(active_jql(project), maxResults=50)
        keys = [i.key for i in issues]
        if not keys:
            print("✅ No active issues to pull")
            return 0
    print(f"📥 Pulling {len(keys)} issue(s)...\n")
    for k in keys:
        try:
            _pull_one(jira, base_url, k)
        except Exception as e:  # noqa: BLE001
            print(f"   ❌ {k}: {e}")
    return 0


def cmd_push(jira: JIRA, key: str) -> int:
    worklog = sync_dir() / "worklog" / f"{key}.md"
    if not worklog.exists():
        print(f"❌ No worklog at {worklog} — run `pull {key}` and add notes first.")
        return 1
    body = worklog.read_text(encoding="utf-8").strip()
    if not body or "_Add your work notes here..._" in body:
        print(f"❌ Worklog for {key} is empty/unedited — nothing to push.")
        return 1
    # Wiki markup, not Markdown: JIRA renders "## x" literally.
    comment = f"{body}\n\n----\n_Posted via jira_sync on {datetime.now():%Y-%m-%d %H:%M:%S}_"
    jira.add_comment(jira.issue(key), comment)
    print(f"✅ Posted worklog as a comment on {key}")
    return 0


def cmd_transition(jira: JIRA, key: str, name: str | None) -> int:
    issue = jira.issue(key)
    transitions = jira.transitions(issue)
    if not name:
        print(f"\n{key} is '{issue.fields.status.name}'. Available transitions:")
        for t in transitions:
            print(f"  - {t['name']}  (id {t['id']})")
        print(f"\nRun: jira_sync.py transition {key} <NAME>")
        return 0
    match = next((t for t in transitions if t["name"].lower() == name.lower()), None)
    if not match:
        names = ", ".join(t["name"] for t in transitions)
        print(f"❌ '{name}' not available for {key}. Options: {names}")
        return 1
    jira.transition_issue(issue, match["id"])
    new_status = jira.issue(key).fields.status.name
    print(f"✅ {key}: → {new_status}")
    return 0


def cmd_show(jira: JIRA, base_url: str, key: str) -> int:
    issue = jira.issue(key)
    f = issue.fields
    print(f"\n{key}: {f.summary}")
    print(f"  Status:    {f.status.name}")
    print(f"  Assignee:  {f.assignee.displayName if f.assignee else 'Unassigned'}")
    print(f"  Updated:   {f.updated[:10]}")
    print(f"  URL:       {base_url}/browse/{key}")
    print("  Transitions: " + ", ".join(t["name"] for t in jira.transitions(issue)))
    return 0


def cmd_assign(jira: JIRA, key: str, query: str) -> int:
    """Assign KEY to the first assignable user matching QUERY (name or email).

    The same person can exist twice (old and new SSO account); the first match may answer
    "cannot be assigned issues", so every candidate is tried in order.
    """
    try:
        users = jira.search_assignable_users_for_issues(None, issueKey=key, query=query)
    except TypeError:  # older python-jira without `query=`
        users = jira.search_assignable_users_for_issues(query, issueKey=key)
    except Exception as e:  # noqa: BLE001
        print(f"❌ user search failed: {e}")
        return 1
    if not users:
        print(f"❌ no assignable user matches '{query}' for {key}")
        return 1
    for u in users:
        account_id = getattr(u, "accountId", None)
        try:
            jira.assign_issue(key, account_id or u.name)
            print(f"✅ {key} assigned to {u.displayName}")
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"   ⚠️  {u.displayName} ({account_id}): {e}")
    print(f"❌ none of the {len(users)} matching account(s) could be assigned")
    return 1


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jira_sync", description="Local-first JIRA helper.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List active issues + write INDEX.md")
    pp = sub.add_parser("pull", help="Pull full JSON + comments to cache; seed worklogs")
    pp.add_argument("keys", nargs="*", help="Issue keys (default: all active)")
    ph = sub.add_parser("push", help="Post worklog .md as a comment")
    ph.add_argument("key")
    pt = sub.add_parser("transition", help="Transition an issue (omit name to list)")
    pt.add_argument("key")
    pt.add_argument("name", nargs="?", default=None)
    ps = sub.add_parser("show", help="Show one issue's status + transitions")
    ps.add_argument("key")
    pa = sub.add_parser("assign", help="Assign an issue to the first assignable user matching QUERY")
    pa.add_argument("key")
    pa.add_argument("query")

    args = p.parse_args(argv)
    jira, base_url, project = connect()

    if args.cmd == "list":
        return cmd_list(jira, base_url, project)
    if args.cmd == "pull":
        return cmd_pull(jira, base_url, project, args.keys)
    if args.cmd == "push":
        return cmd_push(jira, args.key)
    if args.cmd == "transition":
        return cmd_transition(jira, args.key, args.name)
    if args.cmd == "show":
        return cmd_show(jira, base_url, args.key)
    if args.cmd == "assign":
        return cmd_assign(jira, args.key, args.query)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n⚠️  interrupted")
        sys.exit(1)
