#!/home/server/odoo-17.0/.venv/bin/python
"""Dev Dashboard — local Odoo 17 developer tool. Run: ./server.py  or  make dashboard"""

import asyncio
import glob
import json
import os
import re
import signal
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import shutil

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
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


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS session_cache (
            session_id  TEXT PRIMARY KEY,
            ai_title    TEXT,
            first_msg   TEXT,
            mtime       REAL,
            project     TEXT
        );
        CREATE TABLE IF NOT EXISTS session_tasks (
            session_id  TEXT PRIMARY KEY,
            task_number TEXT,
            notes       TEXT DEFAULT '',
            updated_at  TEXT
        );
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
    """)
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
    """Return (ai_title, first_user_message) from first 400 lines."""
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
                if t == "ai-title" and not ai_title:
                    ai_title = obj.get("aiTitle", "")
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
                if ai_title and first_msg:
                    break
    except OSError:
        pass
    return ai_title, first_msg


# ── Odoo conf helpers ──────────────────────────────────────────────────────────
def get_active_db() -> str:
    try:
        with open(ODOO_CONF) as f:
            text = f.read()
        m = re.search(r'^db_name\s*=\s*(.+)$', text, re.MULTILINE)
        if m:
            val = m.group(1).strip()
            return val if val else ""
    except OSError:
        pass
    return ""


def toggle_addons_paths(target_paths: List[str]):
    """Comment/uncomment continuation lines in addons_path block — preserves unknown lines."""
    with open(ODOO_CONF) as f:
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

    with open(ODOO_CONF, 'w') as f:
        f.writelines(new_lines)


def set_active_db(db_name: str):
    with open(ODOO_CONF) as f:
        text = f.read()
    if re.search(r'^db_name\s*=', text, re.MULTILINE):
        text = re.sub(r'^db_name\s*=.*$', f'db_name = {db_name}', text, flags=re.MULTILINE)
    else:
        # Insert right after [options] line
        text = re.sub(r'(\[options\]\n)', r'\1db_name = ' + db_name + '\n', text, count=1)
    with open(ODOO_CONF, "w") as f:
        f.write(text)


def get_odoo_pid() -> Optional[int]:
    result = subprocess.run(["pgrep", "-f", "odoo-bin"], capture_output=True, text=True)
    pids = [int(p) for p in result.stdout.strip().split() if p.strip().isdigit()]
    return pids[0] if pids else None


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
    task_map = {r["session_id"]: r for r in conn.execute("SELECT * FROM session_tasks").fetchall()}

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

        t = task_map.get(sid)
        result.append({
            "session_id": sid,
            "ai_title": ai_title or first_msg or "(no title)",
            "has_ai_title": bool(ai_title),
            "mtime": e["mtime"],
            "date": datetime.fromtimestamp(e["mtime"]).strftime("%Y-%m-%d %H:%M"),
            "project": e["project"],
            "task_number": t["task_number"] if t else "",
            "notes": t["notes"] if t else "",
        })

    if to_cache:
        conn.executemany(
            "INSERT OR REPLACE INTO session_cache(session_id,ai_title,first_msg,mtime,project) VALUES(?,?,?,?,?)",
            to_cache,
        )
        conn.commit()
    conn.close()
    return result


class TaskUpdate(BaseModel):
    task_number: str = ""
    notes: str = ""


@app.put("/api/sessions/{session_id}/task")
def update_session_task(session_id: str, body: TaskUpdate):
    if body.task_number and not re.fullmatch(r'T\d{2}-\d{5}', body.task_number):
        raise HTTPException(400, "task_number must be T##-##### (e.g. T26-04156) or empty")
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO session_tasks(session_id,task_number,notes,updated_at) VALUES(?,?,?,?)",
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


# ── Chat endpoint ──────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]
    model: Optional[str] = None
    system: Optional[str] = None


@app.post("/api/chat")
async def chat(body: ChatRequest):
    api_key = read_setting("anthropic_api_key")
    if not api_key:
        raise HTTPException(400, "Anthropic API key not configured — open Settings (gear icon)")

    model = body.model or read_setting("chat_model", "claude-sonnet-4-6")
    payload: Dict[str, Any] = {
        "model": model,
        "max_tokens": 8096,
        "stream": True,
        "messages": body.messages,
    }
    if body.system:
        payload["system"] = body.system

    async def stream_response():
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=payload,
                    timeout=120,
                ) as resp:
                    if resp.status_code != 200:
                        err = await resp.aread()
                        yield f"data: {json.dumps({'type':'error','message':err.decode()})}\n\n"
                        return
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        except Exception as exc:
            yield f"data: {json.dumps({'type':'error','message':str(exc)})}\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")


# ── Claude CLI chat endpoints ──────────────────────────────────────────────────
@app.get("/api/chat/cli-status")
def chat_cli_status():
    return {"available": CLAUDE_CLI is not None, "path": CLAUDE_CLI}


class CliChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None   # Claude Code session UUID for --resume
    project: Optional[str] = None      # "odoo-17.0" or "odoo" — determines CWD for --resume
    model: Optional[str] = None


@app.post("/api/chat/via-cli")
async def chat_via_cli(body: CliChatRequest):
    if not CLAUDE_CLI:
        raise HTTPException(400, "Claude CLI not found — install Claude Code first")

    cmd = [CLAUDE_CLI, "-p", body.message, "--output-format", "stream-json", "--verbose"]
    if body.session_id:
        cmd += ["--resume", body.session_id]
    if body.model:
        cmd += ["--model", body.model]

    # Use the project's working directory so --resume can find the session file
    cwd = PROJECT_DIRS.get(body.project, DASHBOARD_DIR) if body.project else DASHBOARD_DIR

    async def stream():
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env={**os.environ, "HOME": os.path.expanduser("~")},
            )
            last_len = 0
            session_id = None

            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                    etype = evt.get("type")

                    # Capture session_id from any event
                    if not session_id and "session_id" in evt:
                        session_id = evt["session_id"]

                    if etype == "assistant":
                        content = evt.get("message", {}).get("content", [])
                        full_text = "".join(
                            b.get("text", "") for b in content if b.get("type") == "text"
                        )
                        delta = full_text[last_len:]
                        if delta:
                            yield f"data: {json.dumps({'type': 'text', 'text': delta})}\n\n"
                            last_len = len(full_text)

                    elif etype == "result":
                        sid = evt.get("session_id") or session_id or ""
                        yield f"data: {json.dumps({'type': 'done', 'session_id': sid})}\n\n"

                except json.JSONDecodeError:
                    pass  # Skip non-JSON lines (rare)

            await proc.wait()
            if proc.returncode != 0:
                err = (await proc.stderr.read()).decode("utf-8", errors="replace")[:600]
                yield f"data: {json.dumps({'type': 'error', 'text': err or 'CLI exited with error'})}\n\n"

        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'text': str(exc)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


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

    # Update conf: db_name + toggle addons_path (if profile is assigned)
    set_active_db(body.db_name)
    conn = get_db()
    row = conn.execute("SELECT profile FROM db_profiles WHERE db_name=?", (body.db_name,)).fetchone()
    conn.close()
    if row and row["profile"]:
        paths = get_profile_paths(row["profile"])
        if paths:
            toggle_addons_paths(paths)

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
        inst = ODOO_INSTALLS.get("17") or next(iter(ODOO_INSTALLS.values()), None)
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


@app.post("/api/odoo/restart")
def restart_odoo():
    pid = get_odoo_pid()
    if not pid:
        return {"status": "not_running"}
    # Capture cmdline before killing so we can relaunch with same args
    cmdline = get_odoo_cmdline(pid)
    if not cmdline:
        inst = ODOO_INSTALLS.get("17") or next(iter(ODOO_INSTALLS.values()), None)
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
    conn = get_db()
    row = conn.execute("SELECT odoo_version FROM db_versions WHERE db_name=?", (db_name,)).fetchone()
    conn.close()
    if row:
        return {"db_name": db_name, "version": row["odoo_version"]}
    result = subprocess.run(
        ["psql", "-U", "odoo", "-h", "localhost", db_name, "-t", "-A", "-c",
         "SELECT latest_version FROM ir_module_module WHERE name='base' LIMIT 1"],
        capture_output=True, text=True,
        env={**os.environ, "PGPASSWORD": "odoo"},
        timeout=5,
    )
    version = ""
    if result.returncode == 0 and result.stdout.strip():
        version = result.stdout.strip().split('.')[0]  # "17.0.1.3" → "17"
    if version:
        conn = get_db()
        conn.execute("INSERT OR REPLACE INTO db_versions(db_name,odoo_version) VALUES(?,?)",
                     (db_name, version))
        conn.commit()
        conn.close()
    return {"db_name": db_name, "version": version}


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
        latest_mtime, latest_sid = 0.0, None
        for proj_dir, _ in CLAUDE_PROJECTS:
            if not os.path.isdir(proj_dir):
                continue
            for fname in os.listdir(proj_dir):
                if not fname.endswith(".jsonl"):
                    continue
                fpath = os.path.join(proj_dir, fname)
                mt = os.path.getmtime(fpath)
                if mt > latest_mtime:
                    latest_mtime = mt
                    latest_sid = os.path.splitext(fname)[0]
        sid = latest_sid
    if not sid:
        return {"ok": False, "error": "No session found"}
    conn = get_db()
    conn.execute(
        "INSERT INTO session_tasks(session_id, task_number, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(session_id) DO UPDATE SET task_number=excluded.task_number, updated_at=excluded.updated_at",
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
        task = conn.execute("SELECT task_number FROM session_tasks WHERE session_id=?",
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


# ── Serve frontend ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = os.path.join(DASHBOARD_DIR, "index.html")
    with open(html_path) as f:
        return f.read()


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


# Serve vendored JS libs (Tailwind, marked, mermaid, DOMPurify) for offline use
_VENDOR_DIR = os.path.join(DASHBOARD_DIR, "vendor")
if os.path.isdir(_VENDOR_DIR):
    app.mount("/vendor", StaticFiles(directory=_VENDOR_DIR), name="vendor")


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print("Dev Dashboard → http://127.0.0.1:7878")
    uvicorn.run(app, host="127.0.0.1", port=7878, reload=False)
