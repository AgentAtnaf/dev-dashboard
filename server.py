#!/home/server/odoo-17.0/.venv/bin/python
"""Dev Dashboard — local Odoo 17 developer tool. Run: ./server.py  or  make dashboard"""

import asyncio
import glob
import json
import os
import re
import signal
import sqlite3
import socket
import sys
from urllib.parse import quote
from contextlib import ExitStack
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import shutil
from pathlib import Path
from run_history import RunHistory

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Constants ──────────────────────────────────────────────────────────────────
DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DASHBOARD_DIR, "session_map.db")
ODOO_CONF = "/home/server/odoo-17.0/odoo.conf"
MAKEFILE_DIR = "/home/server/odoo-17.0"
CLAUDE_PROJECTS = [
    ("/home/server/.claude/projects/-home-server-odoo-17-0", "odoo-17.0"),
    ("/home/server/.claude/projects/-home-server-odoo-19-0", "odoo-19.0"),
    ("/home/server/.claude/projects/-home-server-odoo", "odoo"),
]

# Map project name → working directory for claude --resume
PROJECT_DIRS = {
    "odoo-17.0": "/home/server/odoo-17.0",
    "odoo-19.0": "/home/server/odoo-19.0",
    "odoo": "/home/server/odoo",
}

# Addons path profiles: base paths always included + project-specific paths
_BASE = "/home/server/odoo-17.0"
_STD = f"{_BASE}/std-odoo17c"
ADDONS_PROFILES: Dict[str, List[str]] = {
    "std": [
        f"{_BASE}/addons",
        f"{_STD}/std_bs_apps",
        f"{_STD}/std_third_apps_free",
        f"{_STD}/std_third_apps_license",
    ],
    "ryt": [
        f"{_BASE}/addons",
        f"{_STD}/std_bs_apps",
        f"{_STD}/std_third_apps_free",
        f"{_STD}/std_third_apps_license",
        f"{_BASE}/ryt-odoo17c/spc_bs_apps",
        f"{_BASE}/ryt-odoo17c/spc_third_apps_free",
        f"{_BASE}/ryt-odoo17c/spc_third_apps_license",
    ],
    "dk": [
        f"{_BASE}/addons",
        f"{_STD}/std_bs_apps",
        f"{_STD}/std_third_apps_free",
        f"{_STD}/std_third_apps_license",
        f"{_BASE}/dk-odoo17c/spc_bs_apps",
        f"{_BASE}/dk-odoo17c/spc_third_apps_free",
        f"{_BASE}/dk-odoo17c/spc_third_apps_license",
    ],
    "dd": [
        f"{_BASE}/addons",
        f"{_STD}/std_bs_apps",
        f"{_STD}/std_third_apps_free",
        f"{_STD}/std_third_apps_license",
        f"{_BASE}/dd-odoo17c/std_bs_apps",
        f"{_BASE}/dd-odoo17c/std_third_apps_free",
        f"{_BASE}/dd-odoo17c/std_third_apps_license",
        f"{_BASE}/dd-odoo17c/spc_bs_apps",
        f"{_BASE}/dd-odoo17c/spc_third_apps_free",
        f"{_BASE}/dd-odoo17c/spc_third_apps_license",
    ],
    "sme": [
        f"{_BASE}/addons",
        f"{_STD}/std_bs_apps",
        f"{_STD}/std_third_apps_free",
        f"{_STD}/std_third_apps_license",
        f"{_BASE}/sme-odoo17c/spc_bs_apps",
        f"{_BASE}/sme-odoo17c/spc_third_apps_free",
        f"{_BASE}/sme-odoo17c/spc_third_apps_license",
    ],
}

MAKE_TARGETS = [
    {
        "group": "Module Dev",
        "targets": [
            {"name": "update", "description": "Upgrade module on DB", "params": [
                {"name": "MOD", "required": True, "placeholder": "bs_xyz"},
                {"name": "DB", "required": False, "placeholder": "dv_ryt", "default": "dv_ryt"},
            ]},
            {"name": "test", "description": "Run module tests", "params": [
                {"name": "MOD", "required": True, "placeholder": "bs_xyz"},
                {"name": "DB", "required": False, "placeholder": "dv_ryt", "default": "dv_ryt"},
            ]},
            {"name": "test-clean", "description": "Temp DB → install → test → drop", "params": [
                {"name": "MOD", "required": True, "placeholder": "bs_xyz"},
            ]},
            {"name": "check", "description": "py_compile all .py in module", "params": [
                {"name": "MOD", "required": True, "placeholder": "bs_xyz"},
            ]},
            {"name": "check-all", "description": "py_compile all changed .py files", "params": []},
            {"name": "lint", "description": "Validate XML syntax", "params": [
                {"name": "MOD", "required": True, "placeholder": "bs_xyz"},
            ]},
        ],
    },
    {
        "group": "Module Exploration",
        "targets": [
            {"name": "find", "description": "Find module location", "params": [
                {"name": "MOD", "required": True, "placeholder": "bs_xyz"},
            ]},
            {"name": "deps", "description": "Show module dependencies", "params": [
                {"name": "MOD", "required": True, "placeholder": "bs_xyz"},
            ]},
            {"name": "rdeps", "description": "Show reverse dependencies", "params": [
                {"name": "MOD", "required": True, "placeholder": "bs_xyz"},
            ]},
            {"name": "status", "description": "Check module install status", "params": [
                {"name": "MOD", "required": True, "placeholder": "bs_xyz"},
                {"name": "DB", "required": False, "placeholder": "dv_ryt", "default": "dv_ryt"},
            ]},
            {"name": "bump", "description": "Bump module version last digit", "params": [
                {"name": "MOD", "required": True, "placeholder": "bs_xyz"},
            ]},
        ],
    },
    {
        "group": "Code Generation",
        "targets": [
            {"name": "scaffold", "description": "Create new bs_ module skeleton", "params": [
                {"name": "MOD", "required": True, "placeholder": "bs_new_feature"},
                {"name": "PRJ", "required": True, "type": "select",
                 "options": ["ryt", "std", "dk", "dd", "sme"], "default": "ryt"},
            ]},
            {"name": "gen-model", "description": "Generate model .py + views + security", "params": [
                {"name": "MOD", "required": True, "placeholder": "bs_xyz"},
                {"name": "MODEL", "required": True, "placeholder": "bs.model.name"},
                {"name": "FIELDS", "required": False, "placeholder": "name:Char,date:Date"},
            ]},
            {"name": "gen-security", "description": "Auto-generate ir.model.access.csv", "params": [
                {"name": "MOD", "required": True, "placeholder": "bs_xyz"},
            ]},
        ],
    },
    {
        "group": "Server Tools",
        "targets": [
            {"name": "shell", "description": "Open Odoo shell (runs interactively — use terminal)", "params": [
                {"name": "DB", "required": False, "placeholder": "dv_ryt", "default": "dv_ryt"},
            ]},
            {"name": "log", "description": "Tail Odoo log (runs indefinitely — use terminal)", "params": []},
        ],
    },
    {
        "group": "Git Hooks",
        "targets": [
            {"name": "hook-install", "description": "Install pre-commit hook", "params": [
                {"name": "PRJ", "required": True, "type": "select",
                 "options": ["ryt", "std", "dk", "dd", "sme"], "default": "ryt"},
            ]},
            {"name": "hook-remove", "description": "Remove pre-commit hook", "params": [
                {"name": "PRJ", "required": True, "type": "select",
                 "options": ["ryt", "std", "dk", "dd", "sme"], "default": "ryt"},
            ]},
        ],
    },
    {
        "group": "LINE Service",
        "targets": [
            {"name": "line-start", "description": "Start LINE notify + ngrok", "params": []},
            {"name": "line-stop", "description": "Stop LINE notify + ngrok", "params": []},
            {"name": "line-restart", "description": "Restart LINE notify + ngrok", "params": []},
            {"name": "line-status", "description": "Show LINE service status", "params": []},
            {"name": "line-log", "description": "Tail LINE service log", "params": []},
        ],
    },
]

ALLOWED_TARGETS = {t["name"] for group in MAKE_TARGETS for t in group["targets"]}

LINE_LOG_PATH = "/home/server/odoo-17.0/line-notify/logs/uvicorn.out"
LINE_NGROK_LOG = "/home/server/odoo-17.0/line-notify/logs/ngrok.out"


def _detect_odoo_installs() -> Dict[str, Any]:
    """Scan /home/server/odoo* for runnable Odoo installs (release.py + odoo-bin).
    venv is optional: falls back to /usr/bin/python3.
    For -community dirs, conf is looked up in the sibling dir (e.g. odoo-19.0).
    """
    result = {}
    for d in sorted(glob.glob("/home/server/odoo*")):
        release = os.path.join(d, "odoo", "release.py")
        bin_path = os.path.join(d, "odoo-bin")
        if not (os.path.exists(release) and os.path.exists(bin_path)):
            continue
        # Prefer dedicated venv, fall back to /usr/bin/python3
        venv_python = os.path.join(d, ".venv", "bin", "python")
        python = venv_python if os.path.exists(venv_python) else "/usr/bin/python3"
        # For -community dirs (e.g. odoo-19.0-community), conf lives in the base dir
        base_dir = d[:-len("-community")] if d.endswith("-community") else d
        conf_path = os.path.join(base_dir, "odoo.conf")
        if not os.path.exists(conf_path):
            conf_path = os.path.join(d, "odoo.conf")
        try:
            with open(release) as f:
                content = f.read()
            m = re.search(r"version_info\s*=\s*\((\d+),", content)
            if m:
                major = m.group(1)
                # Keep the first-found install per major version
                result.setdefault(major, {
                    "major": major,
                    "label": f"Odoo {major}.0",
                    "dir": d,
                    "bin": bin_path,
                    "python": python,
                    "conf": conf_path,
                })
        except OSError:
            pass
    return result


ODOO_INSTALLS: Dict[str, Any] = _detect_odoo_installs()

CLAUDE_CLI: Optional[str] = (
    "/home/server/.local/bin/claude"
    if os.path.exists("/home/server/.local/bin/claude")
    else shutil.which("claude")
)

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Dev Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── SQLite helpers ─────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


history = RunHistory(get_db, [p for p in os.environ.get(
    "TRACE_HISTORY_DIRS", "/home/server/odoo-17.0/Record_task:/home/server/odoo-trace-kit/traces"
).split(os.pathsep) if p])


def _migrate_session_tasks(conn):
    """session_tasks used to be one row per session (session_id PRIMARY KEY), which meant
    every `cli.py task` call overwrote the previous task number for that session. Migrate to
    an append-only history table (one session_id can have many task rows) so past tasks
    survive."""
    cols = conn.execute("PRAGMA table_info(session_tasks)").fetchall()
    if not cols:
        return  # table doesn't exist yet; the CREATE TABLE below will make the new schema
    if any(c["name"] == "id" for c in cols):
        return  # already migrated
    conn.execute("ALTER TABLE session_tasks RENAME TO session_tasks_v1")
    conn.execute("""
        CREATE TABLE session_tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            task_number TEXT NOT NULL,
            notes       TEXT DEFAULT '',
            updated_at  TEXT
        )
    """)
    conn.execute("""
        INSERT INTO session_tasks(session_id, task_number, notes, updated_at)
        SELECT session_id, task_number, notes, updated_at FROM session_tasks_v1
        WHERE task_number != ''
    """)
    conn.execute("DROP TABLE session_tasks_v1")
    conn.commit()


def init_db():
    conn = get_db()
    _migrate_session_tasks(conn)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS session_cache (
            session_id  TEXT PRIMARY KEY,
            ai_title    TEXT,
            first_msg   TEXT,
            mtime       REAL,
            project     TEXT
        );
        CREATE TABLE IF NOT EXISTS session_tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            task_number TEXT NOT NULL,
            notes       TEXT DEFAULT '',
            updated_at  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_session_tasks_session_id ON session_tasks(session_id);
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS db_profiles (
            db_name TEXT PRIMARY KEY,
            profile TEXT
        );
        CREATE TABLE IF NOT EXISTS addons_profiles (
            profile     TEXT PRIMARY KEY,
            paths_json  TEXT
        );
        CREATE TABLE IF NOT EXISTS db_versions (
            db_name      TEXT PRIMARY KEY,
            odoo_version TEXT
        );
        CREATE TABLE IF NOT EXISTS board_items (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            title         TEXT NOT NULL,
            content       TEXT NOT NULL,
            content_type  TEXT DEFAULT 'markdown',
            session_id    TEXT DEFAULT '',
            session_title TEXT DEFAULT '',
            task_number   TEXT DEFAULT '',
            created_at    TEXT
        );
        CREATE TABLE IF NOT EXISTS flows (
            name          TEXT PRIMARY KEY,
            content       TEXT NOT NULL,
            session_id    TEXT DEFAULT '',
            session_title TEXT DEFAULT '',
            task_number   TEXT DEFAULT '',
            created_at    TEXT,
            updated_at    TEXT
        );
    """)
    if "db_name" not in {row[1] for row in conn.execute("PRAGMA table_info(flows)")}:
        conn.execute("ALTER TABLE flows ADD COLUMN db_name TEXT DEFAULT ''")
    history.init_schema(conn)
    # Seed addons_profiles from hardcoded defaults if empty
    for name, paths in ADDONS_PROFILES.items():
        conn.execute(
            "INSERT OR IGNORE INTO addons_profiles(profile, paths_json) VALUES(?,?)",
            (name, json.dumps(paths)),
        )
    conn.commit()
    conn.close()


def get_profile_paths(profile: str) -> List[str]:
    """Return paths for a profile, falling back to hardcoded defaults."""
    conn = get_db()
    row = conn.execute("SELECT paths_json FROM addons_profiles WHERE profile=?", (profile,)).fetchone()
    conn.close()
    if row:
        return json.loads(row["paths_json"])
    return ADDONS_PROFILES.get(profile, [])


def read_setting(key: str, default: str = "") -> str:
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def write_setting(key: str, value: str):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value))
    conn.commit()
    conn.close()


# ── Session helpers ────────────────────────────────────────────────────────────
def extract_session_info(jsonl_path: str):
    """Return (ai_title, first_user_message).
    Scans the first 400 lines for first_msg and an early title, then scans the
    last 16 KB for the most recent ai-title (Claude renames sessions mid-session
    by appending a new ai-title event — the last one wins).
    """
    ai_title = ""
    first_msg = ""
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 400:
                    break
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type", "")
                if t == "ai-title" and obj.get("aiTitle"):
                    ai_title = obj.get("aiTitle", "")  # keep updating (last wins)
                if not first_msg and t == "user":
                    msg = obj.get("message", {})
                    if isinstance(msg, dict):
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    first_msg = block.get("text", "")[:100]
                                    break
                        elif isinstance(content, str):
                            first_msg = content[:100]
    except OSError:
        pass
    # Scan last 16 KB for a more recent ai-title (overrides the early one if found)
    try:
        with open(jsonl_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size > 16384:
                f.seek(-16384, 2)
                tail = f.read().decode("utf-8", errors="replace")
                for line in tail.splitlines():
                    try:
                        obj = json.loads(line)
                        if obj.get("type") == "ai-title" and obj.get("aiTitle"):
                            ai_title = obj.get("aiTitle", "")
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return ai_title, first_msg


# ── Odoo conf helpers ──────────────────────────────────────────────────────────
def detect_db_version(db_name: str) -> str:
    """Look up which Odoo major version a database was installed with.

    Checks the db_versions cache first, else asks Postgres directly via
    ir_module_module.latest_version (e.g. "19.0.1.0" -> "19") and caches it.
    Used to pick a sane default install instead of hardcoding one version,
    which previously caused Odoo 17 to be launched against Odoo 19 databases.
    """
    if not db_name:
        return ""
    conn = get_db()
    row = conn.execute("SELECT odoo_version FROM db_versions WHERE db_name=?", (db_name,)).fetchone()
    conn.close()
    if row:
        return row["odoo_version"]
    result = subprocess.run(
        ["psql", "-U", "odoo", "-h", "localhost", db_name, "-t", "-A", "-c",
         "SELECT latest_version FROM ir_module_module WHERE name='base' LIMIT 1"],
        capture_output=True, text=True,
        env={**os.environ, "PGPASSWORD": "odoo"},
        timeout=5,
    )
    version = ""
    if result.returncode == 0 and result.stdout.strip():
        version = result.stdout.strip().split('.')[0]
    if version:
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO db_versions(db_name,odoo_version) VALUES(?,?)",
                     (db_name, version))
        conn.commit()
        conn.close()
    return version


def default_odoo_version() -> str:
    """Best-guess install to use when the caller doesn't specify --version."""
    return detect_db_version(get_active_db()) or "17"


def running_odoo_conf() -> str:
    """The conf the live Odoo was actually started with, if one is running.

    Without this the dashboard reads Odoo 17's conf even while Odoo 19 is the
    running server, so the Databases tab reports the wrong current database.
    """
    pid = get_odoo_pid()
    if pid:
        for arg in get_odoo_cmdline(pid):
            if arg.startswith("--config="):
                path = arg.split("=", 1)[1]
                if os.path.exists(path):
                    return path
    return ODOO_CONF


def get_active_db() -> str:
    try:
        with open(running_odoo_conf()) as f:
            text = f.read()
        m = re.search(r'^db_name\s*=\s*(.+)$', text, re.MULTILINE)
        if m:
            val = m.group(1).strip()
            return val if val else ""
    except OSError:
        pass
    return ""


def toggle_addons_paths(target_paths: List[str], conf_path: Optional[str] = None):
    """Comment/uncomment continuation lines in addons_path block — preserves unknown lines.

    conf_path selects which install's odoo.conf to edit. It defaults to the
    Odoo 17 conf only for callers that predate multi-version support; anything
    switching databases must pass the conf that owns that database.
    """
    conf_path = conf_path or ODOO_CONF
    with open(conf_path) as f:
        lines = f.readlines()

    # Build set of all paths from all known profiles (only these are safe to toggle)
    all_known: set = set()
    try:
        conn = get_db()
        for row in conn.execute("SELECT paths_json FROM addons_profiles").fetchall():
            all_known.update(json.loads(row["paths_json"]))
        conn.close()
    except Exception:
        pass
    for paths in ADDONS_PROFILES.values():
        all_known.update(paths)

    target_set = set(target_paths)
    new_lines = []
    in_block = False

    for line in lines:
        stripped = line.strip()

        # Detect block start
        if re.match(r'^addons_path\s*=', line):
            in_block = True
            new_lines.append(line)
            continue

        # Detect block end: a new key=value starting at column 0 (not a comment/space line)
        if in_block and stripped and not line[0].isspace() and not line.startswith('#'):
            in_block = False
            new_lines.append(line)
            continue

        if in_block and line[:1] in (' ', '\t', '#'):
            content = stripped.lstrip('#').strip()
            paths_in_line = {p.rstrip(',') for p in re.findall(r'(/\S+)', content)}
            known_here = paths_in_line & all_known

            if known_here:
                should_active = bool(known_here & target_set)
                is_commented = stripped.startswith('#')

                if should_active and is_commented:
                    # Uncomment: remove leading # and optional space, keep one space indent
                    line = re.sub(r'^#\s?', ' ', line)
                elif not should_active and not is_commented:
                    # Comment out: swap leading space for #
                    line = '#' + line[1:]

        new_lines.append(line)

    with open(conf_path, 'w') as f:
        f.writelines(new_lines)


def conf_for_db(db_name: str) -> str:
    """The odoo.conf belonging to the install that owns this database.

    Switching to an Odoo 19 database used to rewrite db_name and addons_path in
    the Odoo 17 conf and then launch Odoo 19 against its own, untouched conf —
    so the switch appeared to do nothing on 19 and 14 while quietly editing 17's
    config. Resolve the conf from the database's version instead.
    """
    install = ODOO_INSTALLS.get(detect_db_version(db_name) or "")
    return install["conf"] if install else ODOO_CONF


def set_active_db(db_name: str, conf_path: Optional[str] = None):
    conf_path = conf_path or ODOO_CONF
    with open(conf_path) as f:
        text = f.read()
    if re.search(r'^db_name\s*=', text, re.MULTILINE):
        text = re.sub(r'^db_name\s*=.*$', f'db_name = {db_name}', text, flags=re.MULTILINE)
    else:
        # Insert right after [options] line
        text = re.sub(r'(\[options\]\n)', r'\1db_name = ' + db_name + '\n', text, count=1)
    with open(conf_path, "w") as f:
        f.write(text)


def get_odoo_pid() -> Optional[int]:
    """Find a real odoo-bin server process.

    pgrep -f odoo-bin does a substring match against the WHOLE command line of
    every process on the box, so a shell wrapper that merely mentions the text
    "odoo-bin" (a grep, a debugpy launcher, this very pgrep call quoted back at
    itself, or another tool's --odoo-bin=<path> flag VALUE) is misidentified as
    a running Odoo server. Instead, inspect each candidate's actual argv and
    require that the SCRIPT BEING EXECUTED (argv[1], since argv[0] is the
    python interpreter) has basename "odoo-bin" — not just any argument
    anywhere on the command line, which also matches e.g. the odoo-introspect
    MCP servers' own `--odoo-bin /path/to/odoo-bin` option.
    """
    result = subprocess.run(["pgrep", "-f", "odoo-bin"], capture_output=True, text=True)
    candidates = [int(p) for p in result.stdout.strip().split() if p.strip().isdigit()]
    for pid in candidates:
        argv = get_odoo_cmdline(pid)
        if len(argv) > 1 and os.path.basename(argv[1]) == "odoo-bin":
            return pid
    return None


def get_odoo_cmdline(pid: int) -> List[str]:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            parts = f.read().split(b"\x00")
            return [p.decode("utf-8", errors="replace") for p in parts if p]
    except OSError:
        return []


def get_odoo_log_path() -> str:
    """Return Odoo log file path from conf, falling back to the dashboard restart log."""
    try:
        with open(ODOO_CONF) as f:
            text = f.read()
        m = re.search(r'^logfile\s*=\s*(.+)$', text, re.MULTILINE)
        if m:
            p = m.group(1).strip()
            if p and os.path.exists(p):
                return p
    except OSError:
        pass
    return "/tmp/odoo-dashboard-restart.log"


# ── Session endpoints ──────────────────────────────────────────────────────────
@app.get("/api/sessions")
def list_sessions():
    entries = []
    for proj_dir, proj_name in CLAUDE_PROJECTS:
        if not os.path.isdir(proj_dir):
            continue
        for path in glob.glob(os.path.join(proj_dir, "*.jsonl")):
            sid = os.path.splitext(os.path.basename(path))[0]
            entries.append({"session_id": sid, "mtime": os.path.getmtime(path),
                             "path": path, "project": proj_name})

    entries.sort(key=lambda s: s["mtime"], reverse=True)

    conn = get_db()
    cached = {r["session_id"]: r for r in conn.execute("SELECT * FROM session_cache").fetchall()}
    task_history: dict[str, list] = {}
    for r in conn.execute("SELECT session_id, task_number, notes, updated_at FROM session_tasks ORDER BY id ASC"):
        task_history.setdefault(r["session_id"], []).append(
            {"task_number": r["task_number"], "notes": r["notes"], "updated_at": r["updated_at"]}
        )

    result = []
    to_cache = []

    for e in entries:
        sid = e["session_id"]
        c = cached.get(sid)
        if c and abs(c["mtime"] - e["mtime"]) < 1.0:
            ai_title, first_msg = c["ai_title"], c["first_msg"]
        else:
            ai_title, first_msg = extract_session_info(e["path"])
            to_cache.append((sid, ai_title, first_msg, e["mtime"], e["project"]))

        # Most-recent-first history of every task this session has touched.
        history = list(reversed(task_history.get(sid, [])))
        latest = history[0] if history else None
        result.append({
            "session_id": sid,
            "ai_title": ai_title or first_msg or "(no title)",
            "has_ai_title": bool(ai_title),
            "mtime": e["mtime"],
            "date": datetime.fromtimestamp(e["mtime"]).strftime("%Y-%m-%d %H:%M"),
            "project": e["project"],
            "task_number": latest["task_number"] if latest else "",
            "notes": latest["notes"] if latest else "",
            "tasks": history,
        })

    if to_cache:
        conn.executemany(
            "INSERT OR REPLACE INTO session_cache(session_id,ai_title,first_msg,mtime,project) VALUES(?,?,?,?,?)",
            to_cache,
        )
        conn.commit()
    conn.close()
    return result


@app.get("/api/sessions/{session_id}/context")
def get_session_context(session_id: str):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT task_number FROM session_tasks WHERE session_id=? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return {"session_id": session_id, "task_number": row["task_number"] if row else ""}
    finally:
        conn.close()


class TaskUpdate(BaseModel):
    task_number: str = ""
    notes: str = ""


@app.put("/api/sessions/{session_id}/task")
def update_session_task(session_id: str, body: TaskUpdate):
    if body.task_number and not re.fullmatch(r'T\d{2}-\d{5}', body.task_number):
        raise HTTPException(400, "task_number must be T##-##### (e.g. T26-04156) or empty")
    conn = get_db()
    last = conn.execute(
        "SELECT task_number, notes FROM session_tasks WHERE session_id=? ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if not last or last["task_number"] != body.task_number or last["notes"] != body.notes:
        conn.execute(
            "INSERT INTO session_tasks(session_id,task_number,notes,updated_at) VALUES(?,?,?,?)",
            (session_id, body.task_number, body.notes, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    conn.close()
    return {"ok": True}


# ── Settings endpoints ─────────────────────────────────────────────────────────
@app.get("/api/settings")
def get_settings():
    key = read_setting("anthropic_api_key")
    model = read_setting("chat_model", "claude-sonnet-4-6")
    mode = read_setting("chat_mode", "cli" if CLAUDE_CLI else "api")
    preview = ""
    if key:
        preview = key[:8] + "..." + key[-4:] if len(key) > 12 else "set"
    return {
        "api_key_set": bool(key),
        "api_key_preview": preview,
        "chat_model": model,
        "chat_mode": mode,
        "cli_available": CLAUDE_CLI is not None,
    }


class SettingsUpdate(BaseModel):
    anthropic_api_key: Optional[str] = None
    chat_model: Optional[str] = None
    chat_mode: Optional[str] = None   # "api" or "cli"


@app.post("/api/settings")
def save_settings(body: SettingsUpdate):
    if body.anthropic_api_key is not None:
        write_setting("anthropic_api_key", body.anthropic_api_key.strip())
    if body.chat_model is not None:
        write_setting("chat_model", body.chat_model)
    if body.chat_mode is not None:
        write_setting("chat_mode", body.chat_mode)
    return {"ok": True}


# ── Session Find endpoint ──────────────────────────────────────────────────────
class FindSessionRequest(BaseModel):
    query: str


@app.post("/api/sessions/find")
async def find_sessions_by_query(body: FindSessionRequest):
    api_key = read_setting("anthropic_api_key")
    if not api_key:
        raise HTTPException(400, "No Anthropic API key configured — open Settings (gear icon)")

    model = read_setting("chat_model", "claude-haiku-4-5-20251001")

    conn = get_db()
    cached = conn.execute(
        "SELECT session_id, ai_title, mtime FROM session_cache ORDER BY mtime DESC LIMIT 150"
    ).fetchall()
    task_rows = conn.execute("SELECT session_id, task_number FROM session_tasks").fetchall()
    conn.close()

    task_map = {r["session_id"]: r["task_number"] for r in task_rows}
    sessions = []
    for row in cached:
        dt = datetime.fromtimestamp(row["mtime"]).strftime("%Y-%m-%d")
        sessions.append({
            "session_id": row["session_id"],
            "title": row["ai_title"] or "(untitled)",
            "date": dt,
            "task": task_map.get(row["session_id"], "") or "",
        })

    if not sessions:
        return []

    lines = [
        f"{i+1}. {s['title']} | {s['date']}" + (f" | {s['task']}" if s["task"] else "")
        for i, s in enumerate(sessions)
    ]
    prompt = (
        f'Search query: "{body.query}"\n\n'
        "Find the most relevant sessions from this list. Return a JSON array (max 10), most relevant first.\n\n"
        "Sessions:\n" + "\n".join(lines) +
        '\n\nReturn raw JSON only, no markdown:\n'
        '[{"index": 1, "reason": "one sentence why this matches"}]\n'
        "Only include sessions genuinely relevant to the query."
    )

    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            json={"model": model, "max_tokens": 1024,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30,
        )

    if r.status_code != 200:
        raise HTTPException(r.status_code, r.json().get("error", {}).get("message", "API error"))

    try:
        ranked = json.loads(r.json()["content"][0]["text"])
    except Exception:
        raise HTTPException(500, "Failed to parse AI response")

    results = []
    for item in ranked:
        idx = item.get("index", 0) - 1
        if 0 <= idx < len(sessions):
            s = sessions[idx]
            results.append({
                "session_id": s["session_id"],
                "ai_title": s["title"],
                "date": s["date"],
                "task_number": s["task"],
                "reason": item.get("reason", ""),
            })
    return results


# ── Database endpoints ─────────────────────────────────────────────────────────
def list_pg_databases() -> List[str]:
    result = subprocess.run(
        ["psql", "-U", "odoo", "-h", "localhost", "-lqt"],
        capture_output=True, text=True,
        env={**os.environ, "PGPASSWORD": "odoo"},
        timeout=10,
    )
    dbs = []
    for line in result.stdout.split("\n"):
        parts = line.split("|")
        if parts:
            name = parts[0].strip()
            if name.startswith("dv_"):
                dbs.append(name)
    return sorted(dbs)


@app.get("/api/databases")
def get_databases():
    return {"databases": list_pg_databases(), "active_db": get_active_db()}


class SwitchDBRequest(BaseModel):
    db_name: str
    odoo_version: Optional[str] = None  # "14" or "17" — which install to start


@app.post("/api/databases/switch")
def switch_database(body: SwitchDBRequest):
    allowed = set(list_pg_databases())
    if body.db_name not in allowed:
        raise HTTPException(400, f"Database '{body.db_name}' not found in PostgreSQL")

    pid = get_odoo_pid()

    # Edit the conf of the install that owns this database, not always Odoo 17's.
    target_conf = conf_for_db(body.db_name)

    # Update conf: db_name + toggle addons_path (if profile is assigned)
    set_active_db(body.db_name, target_conf)
    conn = get_db()
    row = conn.execute("SELECT profile FROM db_profiles WHERE db_name=?", (body.db_name,)).fetchone()
    conn.close()
    if row and row["profile"]:
        paths = get_profile_paths(row["profile"])
        if paths:
            toggle_addons_paths(paths, target_conf)

    # Kill existing Odoo
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        for _ in range(20):
            time.sleep(0.5)
            if not get_odoo_pid():
                break
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            time.sleep(1)

    # Determine which binary to start
    if body.odoo_version and body.odoo_version in ODOO_INSTALLS:
        install = ODOO_INSTALLS[body.odoo_version]
        cmdline = [install["python"], install["bin"],
                   f"--config={install['conf']}", "--dev", "xml"]
    elif pid:
        cmdline = get_odoo_cmdline(pid)
    else:
        cmdline = []

    if not cmdline:
        version = detect_db_version(body.db_name) or "17"
        inst = ODOO_INSTALLS.get(version) or next(iter(ODOO_INSTALLS.values()), None)
        if inst:
            cmdline = [inst["python"], inst["bin"], f"--config={inst['conf']}", "--dev", "xml"]
    elif target_conf not in cmdline and not any(a.startswith(f"--config={target_conf}") for a in cmdline):
        # Reusing the previous process's argv would keep pointing at the old
        # install's conf after switching to a database from another version.
        inst = ODOO_INSTALLS.get(detect_db_version(body.db_name) or "")
        if inst:
            cmdline = [inst["python"], inst["bin"], f"--config={inst['conf']}", "--dev", "xml"]

    log_path = "/tmp/odoo-dashboard-restart.log"
    with open(log_path, "w") as log:
        subprocess.Popen(
            cmdline, cwd=MAKEFILE_DIR,
            stdout=log, stderr=log,
            start_new_session=True, close_fds=True,
        )

    return {"status": "restarting", "new_db": body.db_name, "log": log_path}


@app.get("/api/db-profiles")
def get_db_profiles():
    conn = get_db()
    rows = conn.execute("SELECT db_name, profile FROM db_profiles").fetchall()
    conn.close()
    return {r["db_name"]: r["profile"] for r in rows}


class DbProfileUpdate(BaseModel):
    profile: str  # one of: ryt, std, dk, dd, sme, or "" to clear


@app.put("/api/db-profiles/{db_name}")
def set_db_profile(db_name: str, body: DbProfileUpdate):
    if body.profile:
        conn_chk = get_db()
        exists = conn_chk.execute("SELECT 1 FROM addons_profiles WHERE profile=?", (body.profile,)).fetchone()
        conn_chk.close()
        if not exists and body.profile not in ADDONS_PROFILES:
            raise HTTPException(400, f"Profile '{body.profile}' not found")
    conn = get_db()
    if body.profile:
        conn.execute("INSERT OR REPLACE INTO db_profiles(db_name,profile) VALUES(?,?)",
                     (db_name, body.profile))
    else:
        conn.execute("DELETE FROM db_profiles WHERE db_name=?", (db_name,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/addons-profiles")
def get_addons_profiles():
    conn = get_db()
    rows = conn.execute("SELECT profile, paths_json FROM addons_profiles").fetchall()
    conn.close()
    result = {r["profile"]: json.loads(r["paths_json"]) for r in rows}
    # Include any hardcoded profiles not yet in DB
    for name, paths in ADDONS_PROFILES.items():
        result.setdefault(name, paths)
    return result


class AddonsProfileUpdate(BaseModel):
    paths: List[str]


@app.put("/api/addons-profiles/{profile}")
def update_addons_profile(profile: str, body: AddonsProfileUpdate):
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,19}', profile):
        raise HTTPException(400, "Profile name must start with a letter, max 20 chars, lowercase/digits/underscore")
    # Validate paths: must be absolute paths under /home/server/
    for p in body.paths:
        if not p.startswith("/home/server/"):
            raise HTTPException(400, f"Path must be under /home/server/: {p}")
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO addons_profiles(profile, paths_json) VALUES(?,?)",
        (profile, json.dumps(body.paths)),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/addons-profiles/{profile}")
def delete_addons_profile(profile: str):
    if profile in ADDONS_PROFILES:
        raise HTTPException(400, "Cannot delete a built-in profile")
    conn = get_db()
    conn.execute("DELETE FROM addons_profiles WHERE profile=?", (profile,))
    conn.execute("DELETE FROM db_profiles WHERE profile=?", (profile,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/odoo/status")
def odoo_status():
    pid = get_odoo_pid()
    return {"running": pid is not None, "pid": pid, "db": get_active_db()}


@app.post("/api/odoo/stop")
def stop_odoo():
    pid = get_odoo_pid()
    if not pid:
        return {"status": "not_running"}
    try:
        os.kill(pid, signal.SIGTERM)
        return {"status": "stopping", "pid": pid}
    except ProcessLookupError:
        return {"status": "not_running"}


class StartOdooRequest(BaseModel):
    odoo_version: str = ""


@app.post("/api/odoo/start")
def start_odoo(body: StartOdooRequest = StartOdooRequest()):
    pid = get_odoo_pid()
    if pid:
        return {"status": "already_running", "pid": pid}
    version = body.odoo_version or default_odoo_version()
    inst = ODOO_INSTALLS.get(version) or next(iter(ODOO_INSTALLS.values()), None)
    if not inst:
        return {"status": "error", "detail": "No Odoo installation found"}
    cmdline = [inst["python"], inst["bin"], f"--config={inst['conf']}", "--dev", "xml"]
    log_path = "/tmp/odoo-dashboard-restart.log"
    with open(log_path, "w") as log:
        subprocess.Popen(cmdline, stdout=log, stderr=log, start_new_session=True, close_fds=True)
    return {"status": "starting", "log": log_path}


@app.post("/api/odoo/restart")
def restart_odoo():
    pid = get_odoo_pid()
    if not pid:
        return {"status": "not_running"}
    # Capture cmdline before killing so we can relaunch with same args
    cmdline = get_odoo_cmdline(pid)
    if not cmdline:
        inst = ODOO_INSTALLS.get(default_odoo_version()) or next(iter(ODOO_INSTALLS.values()), None)
        if inst:
            cmdline = [inst["python"], inst["bin"], f"--config={inst['conf']}", "--dev", "xml"]
    if not cmdline:
        return {"status": "error", "detail": "Could not determine Odoo command line"}

    def _do_restart(old_pid: int, cmd: list):
        try:
            os.kill(old_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        for _ in range(20):
            time.sleep(0.5)
            if not get_odoo_pid():
                break
        else:
            try:
                os.kill(old_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            time.sleep(1)
        log_path = "/tmp/odoo-dashboard-restart.log"
        with open(log_path, "w") as log:
            subprocess.Popen(cmd, stdout=log, stderr=log, start_new_session=True, close_fds=True)

    threading.Thread(target=_do_restart, args=(pid, cmdline), daemon=True).start()
    return {"status": "restarting"}


@app.get("/api/odoo/log")
async def stream_odoo_log():
    log_path = get_odoo_log_path()
    if not os.path.exists(log_path):
        async def empty():
            msg = f"Log file not found: {log_path}\n"
            yield f"data: {json.dumps({'text': msg})}\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    async def tail():
        proc = await asyncio.create_subprocess_exec(
            "tail", "-n", "150", "-f", log_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            async for line in proc.stdout:
                yield f"data: {json.dumps({'text': line.decode('utf-8', errors='replace')})}\n\n"
        finally:
            proc.kill()

    return StreamingResponse(tail(), media_type="text/event-stream")


@app.get("/api/odoo/installations")
def get_odoo_installations():
    return list(ODOO_INSTALLS.values())


@app.get("/api/databases/{db_name}/version")
def get_db_version(db_name: str):
    return {"db_name": db_name, "version": detect_db_version(db_name)}


@app.get("/api/line/log")
async def stream_line_log(source: str = "uvicorn"):
    log_path = LINE_NGROK_LOG if source == "ngrok" else LINE_LOG_PATH
    if not os.path.exists(log_path):
        async def empty():
            msg = f"Log file not found: {log_path}\n"
            yield f"data: {json.dumps({'text': msg})}\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    async def tail():
        proc = await asyncio.create_subprocess_exec(
            "tail", "-n", "200", "-f", log_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            async for line in proc.stdout:
                yield f"data: {json.dumps({'text': line.decode('utf-8', errors='replace')})}\n\n"
        finally:
            proc.kill()

    return StreamingResponse(tail(), media_type="text/event-stream")


# ── Makefile endpoints ─────────────────────────────────────────────────────────
@app.get("/api/make/targets")
def get_make_targets():
    return MAKE_TARGETS


class MakeRunRequest(BaseModel):
    target: str
    params: Dict[str, str] = {}


@app.post("/api/make/run")
async def run_make(body: MakeRunRequest):
    if body.target not in ALLOWED_TARGETS:
        raise HTTPException(400, f"Target '{body.target}' is not allowed")

    # Validate individual params
    for k, v in body.params.items():
        if not re.fullmatch(r'[A-Z_]{1,20}', k):
            raise HTTPException(400, f"Invalid param key: {k}")
        if k in ("MOD", "DB", "PRJ", "MODEL") and v:
            if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_.]{1,60}', v):
                raise HTTPException(400, f"Invalid value for {k}: {v}")

    cmd = ["make", "-C", MAKEFILE_DIR, body.target]
    for k, v in body.params.items():
        if v:
            cmd.append(f"{k}={v}")

    async def stream_make():
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=MAKEFILE_DIR,
            )
            yield f"data: {json.dumps({'type':'start','cmd':' '.join(cmd)})}\n\n"
            async for line in proc.stdout:
                text = line.decode("utf-8", errors="replace")
                yield f"data: {json.dumps({'type':'output','text':text})}\n\n"
            await proc.wait()
            yield f"data: {json.dumps({'type':'done','exit_code':proc.returncode})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type':'error','text':str(exc)})}\n\n"

    return StreamingResponse(stream_make(), media_type="text/event-stream")


# ── Record task (called by cli.py after a commit) ──────────────────────────────
class RecordTaskRequest(BaseModel):
    task_number: str
    session_id: Optional[str] = None


@app.post("/api/sessions/record-task")
def record_task(body: RecordTaskRequest):
    if not re.fullmatch(r'T\d{2}-\d{5}', body.task_number):
        return JSONResponse(status_code=422, content={"error": "Invalid task number format"})
    sid = body.session_id
    if not sid:
        return JSONResponse(status_code=422, content={"error": "Explicit session_id is required"})
    conn = get_db()
    last = conn.execute(
        "SELECT task_number FROM session_tasks WHERE session_id=? ORDER BY id DESC LIMIT 1",
        (sid,),
    ).fetchone()
    if not last or last["task_number"] != body.task_number:
        conn.execute(
            "INSERT INTO session_tasks(session_id, task_number, updated_at) VALUES(?,?,?)",
            (sid, body.task_number, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    conn.close()
    return {"ok": True, "session_id": sid, "task_number": body.task_number}


# ── Board endpoints ────────────────────────────────────────────────────────────
class BoardItemCreate(BaseModel):
    title: str
    content: str
    content_type: str = "markdown"   # "markdown", "mermaid", "table"
    session_id: Optional[str] = None
    task_number: Optional[str] = None


@app.get("/api/board")
def get_board():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, title, content, content_type, session_id, session_title, task_number, created_at "
        "FROM board_items ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/board")
def add_board_item(body: BoardItemCreate):
    session_title = ""
    task_num = body.task_number or ""
    if body.session_id:
        conn = get_db()
        cache = conn.execute("SELECT ai_title FROM session_cache WHERE session_id=?",
                             (body.session_id,)).fetchone()
        task = conn.execute("SELECT task_number FROM session_tasks WHERE session_id=? ORDER BY id DESC LIMIT 1",
                            (body.session_id,)).fetchone()
        conn.close()
        if cache:
            session_title = cache["ai_title"] or ""
        if task and not task_num:
            task_num = task["task_number"] or ""
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO board_items(title,content,content_type,session_id,session_title,task_number,created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (body.title, body.content, body.content_type, body.session_id or "",
         session_title, task_num, datetime.now().isoformat(timespec="seconds"))
    )
    item_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"ok": True, "id": item_id}


class BoardItemUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    content_type: Optional[str] = None
    task_number: Optional[str] = None


@app.put("/api/board/{item_id}")
def update_board_item(item_id: int, body: BoardItemUpdate):
    conn = get_db()
    row = conn.execute("SELECT * FROM board_items WHERE id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Board item not found")
    conn.execute(
        "UPDATE board_items SET title=?, content=?, content_type=?, task_number=? WHERE id=?",
        (
            body.title if body.title is not None else row["title"],
            body.content if body.content is not None else row["content"],
            body.content_type if body.content_type is not None else row["content_type"],
            body.task_number if body.task_number is not None else row["task_number"],
            item_id,
        ),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/board/{item_id}")
def delete_board_item(item_id: int):
    conn = get_db()
    conn.execute("DELETE FROM board_items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Flow endpoints ─────────────────────────────────────────────────────────────
class FlowSaveRequest(BaseModel):
    name: str
    content: str
    session_id: str = ""
    task_number: str = ""
    db_name: str = ""


@app.get("/api/flows")
def list_flows():
    runs = history.runs()
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT name, session_id, session_title, task_number, db_name, created_at, updated_at, "
            "length(content) as size, (length(content) - length(replace(content,char(10),''))) + 1 as lines "
            "FROM flows ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        conn.close()
    flows = {row["name"]: {**dict(row), "saved": True, "run_count": 0, "latest_run": None} for row in rows}
    for run in runs:
        flow = flows.setdefault(run["flow_name"], {
            "name": run["flow_name"], "session_id": run["session_id"], "session_title": "",
            "task_number": run["task_number"], "db_name": run["db_name"], "saved": False,
            "updated_at": run["started_at"], "run_count": 0, "latest_run": None,
        })
        flow["run_count"] += 1
        if flow["latest_run"] is None:
            flow["latest_run"] = run
    return sorted(flows.values(), key=lambda f: (f["latest_run"] or {}).get("started_at") or f.get("updated_at") or "", reverse=True)


@app.post("/api/flows")
def save_flow(body: FlowSaveRequest):
    if not re.fullmatch(r'[a-zA-Z0-9_\-]{1,80}', body.name):
        raise HTTPException(400, "Flow name must be 1-80 alphanumeric/dash/underscore chars")
    now = datetime.now(timezone.utc).isoformat()
    # Resolve session title from cache
    session_title = ""
    if body.session_id:
        conn = get_db()
        row = conn.execute("SELECT ai_title FROM session_cache WHERE session_id=?", (body.session_id,)).fetchone()
        conn.close()
        if row:
            session_title = row["ai_title"] or ""
    # Resolve task number from session if not provided
    task_number = body.task_number
    if not task_number and body.session_id:
        conn = get_db()
        row = conn.execute("SELECT task_number FROM session_tasks WHERE session_id=? ORDER BY id DESC LIMIT 1",
                           (body.session_id,)).fetchone()
        conn.close()
        if row:
            task_number = row["task_number"] or ""
    conn = get_db()
    existing = conn.execute("SELECT created_at FROM flows WHERE name=?", (body.name,)).fetchone()
    created_at = existing["created_at"] if existing else now
    conn.execute(
        "INSERT OR REPLACE INTO flows(name, content, session_id, session_title, task_number, db_name, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (body.name, body.content, body.session_id, session_title, task_number, body.db_name, created_at, now),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "name": body.name, "updated": existing is not None}


@app.get("/api/flows/{name}")
def get_flow(name: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM flows WHERE name=?", (name,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"Flow '{name}' not found")
    return dict(row)


@app.delete("/api/flows/{name}")
def delete_flow(name: str):
    conn = get_db()
    result = conn.execute("DELETE FROM flows WHERE name=?", (name,))
    conn.commit()
    conn.close()
    if result.rowcount == 0:
        raise HTTPException(404, f"Flow '{name}' not found")
    return {"ok": True}


# Local run history: results are indexed independently of mutable saved flows.
@app.get("/api/flow-runs")
def list_flow_runs(flow_name: Optional[str] = None, status: Optional[str] = None,
                   limit: int = 50, offset: int = 0):
    if status not in (None, "passed", "failed", "running", "stale", "unknown"):
        raise HTTPException(400, "Unknown run status")
    rows = history.runs(flow_name, status)
    limit, offset = max(1, min(limit, 200)), max(0, offset)
    return {"runs": rows[offset:offset + limit], "total": len(rows), "offset": offset, "limit": limit}


@app.get("/api/flow-runs/tagged")
def list_tagged_runs():
    """Runs tagged safe to delete, with how much each trace would reclaim."""
    items = history.tagged()
    pending = [i for i in items if i["bytes"] and not i["trace_purged_at"]]
    return {"runs": items,
            "reclaimable_bytes": sum(i["bytes"] for i in pending),
            "pending_count": len(pending)}


@app.post("/api/flow-runs/purge-tagged")
def purge_tagged_runs():
    """Delete the .zip of every tagged run. Reports and rows are left intact."""
    freed = 0
    removed, skipped = [], []
    for item in history.tagged():
        result = history.purge_trace(item["run_id"])
        if result.get("ok"):
            freed += result["bytes"]
            removed.append(item["run_id"])
        else:
            skipped.append({"run_id": item["run_id"], "reason": result.get("reason", "")})
    return {"removed": len(removed), "bytes_freed": freed, "skipped": skipped}


@app.get("/api/flow-runs/{run_id}")
def get_flow_run(run_id: str):
    run = history.get(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return {k: v for k, v in run.items() if not k.endswith("_path")}


class RunNoteUpdate(BaseModel):
    note: Optional[str] = None
    safe_to_delete: Optional[bool] = None


@app.post("/api/flow-runs/{run_id}/note")
def set_run_note(run_id: str, body: RunNoteUpdate):
    """Attach a note and/or the safe-to-delete tag to a run."""
    if history.get(run_id) is None:
        raise HTTPException(404, "Unknown run")
    if body.note is None and body.safe_to_delete is None:
        raise HTTPException(400, "Send note, safe_to_delete, or both")
    return history.set_note(run_id, note=body.note, safe_to_delete=body.safe_to_delete)


@app.post("/api/flow-runs/{run_id}/open-trace")
def open_run_trace(run_id: str):
    run = history.get(run_id)
    if run is None or "trace" not in run["artifacts"]:
        raise HTTPException(404, "Trace not available for this run")
    path = Path(run["trace_path"])
    if not history.allowed(path) or not path.is_file():
        raise HTTPException(404, "Trace not available for this run")
    # Use configured server identity, never a supplied URL or shell command.
    host = os.environ.get("DASHBOARD_LAN_HOST", "192.168.64.3") or "127.0.0.1"
    trace_url = f"http://{host}:7878/api/flow-runs/{quote(run_id, safe='')}/artifacts/trace"
    try:
        result = subprocess.run(
            [sys.executable, "/home/server/odoo-trace-kit/open-trace.py", trace_url],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Trace launch timed out. Check that VS Code is connected to this machine.")
    except OSError:
        raise HTTPException(503, "Trace launcher is unavailable.")
    if result.returncode:
        raise HTTPException(503, (result.stderr.strip() or "Could not open Trace Viewer.")[-1500:])
    return {"ok": True, "message": "Asked VS Code to open this trace in your browser."}


@app.get("/api/flow-runs/{run_id}/artifacts/{kind}")
def get_run_artifact(run_id: str, kind: str):
    run = history.get(run_id)
    if run is None or kind not in run["artifacts"]:
        raise HTTPException(404, "Artifact not available")
    if kind == "flow":
        return Response(run["report"]["flow"]["content"], media_type="text/plain",
                        headers={"Content-Disposition": f'attachment; filename="{run_id}.flow.txt"'})
    if kind == "result":
        return JSONResponse(run["report"])
    path = Path(run["trace_path" if kind == "trace" else "log_path"])
    # Resolve again at delivery time to reject symlinks moved outside history roots.
    if not history.allowed(path) or not path.is_file():
        raise HTTPException(404, "Artifact not available")
    return FileResponse(str(path.resolve()), media_type="application/zip" if kind == "trace" else "text/plain",
                        filename=path.name)


# ── Serve frontend ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = os.path.join(DASHBOARD_DIR, "index.html")
    with open(html_path) as f:
        return f.read()


@app.get("/failure-summary.js")
def failure_summary_script():
    return FileResponse(os.path.join(DASHBOARD_DIR, "failure-summary.js"), media_type="application/javascript")


@app.get("/flows.js")
def flow_history_script():
    return FileResponse(os.path.join(DASHBOARD_DIR, "flows.js"), media_type="application/javascript")


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


# Serve vendored JS libs (Tailwind, marked, mermaid, DOMPurify) for offline use
_VENDOR_DIR = os.path.join(DASHBOARD_DIR, "vendor")
if os.path.isdir(_VENDOR_DIR):
    app.mount("/vendor", StaticFiles(directory=_VENDOR_DIR), name="vendor")

# Our own front-end assets (styles.css, app.js, …). A mount rather than a route
# per file, because the redesign keeps adding to this directory.
_STATIC_DIR = os.path.join(DASHBOARD_DIR, "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    # Keep loopback for the CLI and expose only the approved private interface.
    lan_host = os.environ.get("DASHBOARD_LAN_HOST", "192.168.64.3")
    hosts = list(dict.fromkeys(host for host in ("127.0.0.1", lan_host) if host))
    with ExitStack() as stack:
        listeners = [stack.enter_context(socket.create_server((host, 7878), backlog=2048)) for host in hosts]
        for host in hosts:
            print(f"Dev Dashboard → http://{host}:7878", flush=True)
        uvicorn.Server(uvicorn.Config(app, reload=False)).run(sockets=listeners)
