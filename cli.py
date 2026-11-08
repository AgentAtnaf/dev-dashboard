#!/home/server/odoo-17.0/.venv/bin/python
"""
Dev Dashboard CLI helper — called by Claude Code after commits or when saving explanations.

Usage:
  cli.py task T26-12345              # record task number for current session
  cli.py board "Title" mermaid "…"  # save mermaid/markdown to Board tab
  cli.py board "Title" markdown "…"
  cli.py odoo status                 # show Odoo running state
  cli.py odoo start [--version 17]   # start Odoo (no-op if already running)
  cli.py odoo stop                   # SIGTERM Odoo
  cli.py odoo restart                # stop + relaunch with same config
  cli.py flow save "name" /path/to/file.txt  # save/update a Playwright flow
  cli.py flow list                           # list all saved flows
  cli.py flow get "name"                     # print flow content to stdout
  cli.py flow delete "name"                  # delete a saved flow
  cli.py runs recent [--flow NAME] [--limit N]   # recent runs with their run_id and tag state
  cli.py runs mine                               # runs from this session (needs --session-id)
  cli.py runs tag RUN_ID "why it is disposable"  # mark safe to delete (does NOT delete)
  cli.py runs untag RUN_ID                       # clear the tag
  cli.py runs tagged                             # what is tagged and how much it would free
"""
import sys
import argparse
import re
import os
import json
import urllib.parse
import urllib.request
import urllib.error

DASHBOARD_URL = os.environ.get("ODOO_DASHBOARD_URL", "http://127.0.0.1:7878")


def _get(path: str) -> dict:
    req = urllib.request.Request(DASHBOARD_URL + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        print(f"[cli.py] Dashboard unreachable: {e}", file=sys.stderr)
        raise SystemExit(1)


def _post(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        DASHBOARD_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        print(f"[cli.py] Dashboard unreachable: {e}", file=sys.stderr)
        raise SystemExit(1)


def _get_session_id() -> str | None:
    """Use caller-owned context; never infer identity from another agent's logs.

    CLAUDE_CODE_SESSION_ID is exported by Claude Code into its own tool
    environment, so it is the caller's own identity, not a guess made by reading
    someone else's logs. Without this fallback every agent had to be told to pass
    --session-id by hand, and commits silently went unlinked whenever it forgot.
    ODOO_SESSION_ID still wins, so an explicit override keeps working.
    """
    return (os.environ.get("ODOO_SESSION_ID")
            or os.environ.get("CLAUDE_CODE_SESSION_ID")
            or None)


def _context_args(args):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--task", default=os.environ.get("ODOO_TASK", ""))
    parser.add_argument("--session-id", default=_get_session_id() or "")
    parser.add_argument("--db", default=os.environ.get("ODOO_DB", ""))
    opts, rest = parser.parse_known_args(args)
    if any(arg.startswith("--") for arg in rest):
        parser.error("Unknown option: " + next(arg for arg in rest if arg.startswith("--")))
    if opts.task and not re.fullmatch(r'T\d{2}-\d{5}', opts.task):
        parser.error("Task must use T26-12345 format")
    return opts, rest


def cmd_task(args: list[str]):
    opts, args = _context_args(args)
    if not args and opts.task:
        args = [opts.task]
    if not args:
        print("Usage: cli.py task T26-XXXXX", file=sys.stderr)
        sys.exit(1)
    task_number = args[0].strip()
    session_id = opts.session_id
    if not session_id:
        print("[cli.py] task needs --session-id or ODOO_SESSION_ID; no session is inferred", file=sys.stderr)
        sys.exit(2)
    payload = {"task_number": task_number}
    if session_id:
        payload["session_id"] = session_id
    result = _post("/api/sessions/record-task", payload)
    if result.get("ok"):
        print(f"[cli.py] Recorded task {task_number} for session {session_id or '(unknown)'}")
    else:
        print(f"[cli.py] Response: {result}")
        sys.exit(1)


def cmd_board(args: list[str]):
    opts, args = _context_args(args)
    if len(args) < 3:
        print('Usage: cli.py board "Title" mermaid|markdown "content"', file=sys.stderr)
        sys.exit(1)
    title, content_type, content = args[0], args[1], args[2]
    # decode escape sequences so \n in shell strings becomes real newlines
    content = content.replace('\\n', '\n').replace('\\t', '\t')
    if content_type not in ("mermaid", "markdown", "table"):
        print(f"[cli.py] Unknown type '{content_type}', using 'markdown'", file=sys.stderr)
        content_type = "markdown"
    session_id = opts.session_id
    payload = {"title": title, "content": content, "content_type": content_type, "task_number": opts.task}
    if session_id:
        payload["session_id"] = session_id
    result = _post("/api/board", payload)
    if result.get("ok"):
        print(f"[cli.py] Saved '{title}' ({content_type}) to Board, id={result.get('id')}")
    else:
        print(f"[cli.py] Response: {result}")
        sys.exit(1)


def cmd_flow(args: list):
    opts, args = _context_args(args)
    subcommand = args[0] if args else "list"
    if subcommand == "list":
        req = urllib.request.Request(DASHBOARD_URL + "/api/flows", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                flows = json.loads(resp.read())
        except urllib.error.URLError as e:
            print(f"[cli.py] Dashboard unreachable: {e}", file=sys.stderr)
            raise SystemExit(1)
        if not flows:
            print("No flows saved yet.")
            return
        print(f"{'Name':<30} {'Saved':<5} {'Runs':>5} {'Result':<8} {'Task':<14} {'Updated':<22} Session")
        print("-" * 100)
        for f in flows:
            updated = (f.get("updated_at") or "")[:16].replace("T", " ")
            task = f.get("task_number") or "—"
            title = (f.get("session_title") or "—")[:30]
            verdict = (f.get('latest_run') or {}).get('status', '—')
            saved = 'yes' if f.get('saved', True) else 'no'
            print(f"{f['name']:<30} {saved:<5} {f.get('run_count', 0):>5} {verdict:<8} {task:<14} {updated:<22} {title}")
    elif subcommand == "save":
        if len(args) < 3:
            print("Usage: cli.py flow save \"name\" /path/to/file.txt", file=sys.stderr)
            sys.exit(1)
        name, path = args[1], args[2]
        if not os.path.exists(path):
            print(f"[cli.py] File not found: {path}", file=sys.stderr)
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
        session_id = opts.session_id
        result = _post("/api/flows", {"name": name, "content": content, "session_id": session_id, "task_number": opts.task, "db_name": opts.db})
        if result.get("ok"):
            verb = "Updated" if result.get("updated") else "Saved"
            print(f"[cli.py] {verb} flow '{name}' ({len(content.splitlines())} lines) for session {session_id or '(unknown)'}")
        else:
            print(f"[cli.py] Response: {result}")
            sys.exit(1)
    elif subcommand == "get":
        if len(args) < 2:
            print("Usage: cli.py flow get \"name\"", file=sys.stderr)
            sys.exit(1)
        name = args[1]
        url = DASHBOARD_URL + "/api/flows/" + urllib.parse.quote(name)
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            print(f"[cli.py] Not found: {e}", file=sys.stderr)
            sys.exit(1)
        except urllib.error.URLError as e:
            print(f"[cli.py] Dashboard unreachable: {e}", file=sys.stderr)
            sys.exit(1)
        print(data["content"], end="")
    elif subcommand == "delete":
        if len(args) < 2:
            print("Usage: cli.py flow delete \"name\"", file=sys.stderr)
            sys.exit(1)
        name = args[1]
        url = DASHBOARD_URL + "/api/flows/" + urllib.parse.quote(name)
        req = urllib.request.Request(url, method="DELETE")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                json.loads(resp.read())
            print(f"[cli.py] Deleted flow '{name}'")
        except urllib.error.HTTPError as e:
            print(f"[cli.py] Not found: {e}", file=sys.stderr)
            sys.exit(1)
        except urllib.error.URLError as e:
            print(f"[cli.py] Dashboard unreachable: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Unknown flow subcommand: {subcommand}  (save|list|get|delete)", file=sys.stderr)
        sys.exit(1)


def _fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _print_runs(runs):
    if not runs:
        print("No runs matched.")
        return
    print(f"{'run_id':<38} {'status':<8} {'tag':<4} {'flow':<34} {'db':<14} started")
    print("-" * 125)
    for r in runs:
        tag = "SAFE" if r.get("safe_to_delete") else ("gone" if r.get("trace_purged_at") else "")
        print(f"{r['run_id']:<38} {r['status']:<8} {tag:<4} {r['flow_name'][:34]:<34} "
              f"{(r.get('db_name') or '—')[:14]:<14} {(r.get('started_at') or '')[:19]}")


def cmd_runs(args: list):
    """Tagging only. Deleting a trace stays a human action in the dashboard UI."""
    # Consume this command's own options first: _context_args rejects anything it
    # does not recognise, so --flow/--limit must be gone before it runs.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--flow", default="")
    parser.add_argument("--limit", type=int, default=20)
    extra, rest = parser.parse_known_args(args)
    opts, args = _context_args(rest)
    sub = args[0] if args else "recent"

    if sub in ("recent", "mine"):
        query = f"?limit={max(1, min(extra.limit, 200))}"
        if extra.flow:
            query += "&flow_name=" + urllib.parse.quote(extra.flow)
        runs = _get("/api/flow-runs" + query).get("runs", [])
        if sub == "mine":
            if not opts.session_id:
                print("[cli.py] runs mine needs --session-id or ODOO_SESSION_ID", file=sys.stderr)
                sys.exit(2)
            runs = [r for r in runs if r.get("session_id") == opts.session_id]
        _print_runs(runs)

    elif sub in ("tag", "untag"):
        if len(args) < 2:
            print(f'Usage: cli.py runs {sub} RUN_ID' + (' "reason"' if sub == "tag" else ""), file=sys.stderr)
            sys.exit(1)
        run_id = args[1]
        if sub == "tag" and len(args) < 3:
            print('[cli.py] tag needs a reason, so the row says why it is disposable', file=sys.stderr)
            sys.exit(1)
        payload = {"safe_to_delete": sub == "tag"}
        if sub == "tag":
            payload["note"] = args[2]
        try:
            result = _post("/api/flow-runs/" + urllib.parse.quote(run_id) + "/note", payload)
        except SystemExit:
            raise
        print(f"[cli.py] {'Tagged' if sub == 'tag' else 'Untagged'} {run_id}"
              + (f": {result.get('note')}" if sub == "tag" else ""))

    elif sub == "tagged":
        data = _get("/api/flow-runs/tagged")
        _print_runs(data.get("runs", []))
        print(f"\n{data['pending_count']} tagged trace(s), {_fmt_bytes(data['reclaimable_bytes'])} reclaimable.")
        print("Delete them from the dashboard Flows tab -> 'Delete tagged traces'.")

    else:
        print(f"Unknown runs subcommand: {sub}  (recent|mine|tag|untag|tagged)", file=sys.stderr)
        sys.exit(1)


def cmd_odoo(args: list):
    subcommand = args[0] if args else "status"
    if subcommand == "status":
        d = _get("/api/odoo/status")
        if d.get("running"):
            print(f"Odoo: RUNNING  pid={d.get('pid')}  db={d.get('db') or '—'}")
        else:
            print("Odoo: STOPPED")
    elif subcommand == "start":
        version = ""
        if "--version" in args:
            idx = args.index("--version")
            version = args[idx + 1] if idx + 1 < len(args) else ""
        d = _post("/api/odoo/start", {"odoo_version": version})
        status = d.get("status", "")
        if status == "already_running":
            print(f"Odoo: already running (pid={d.get('pid')})")
        elif status == "starting":
            print(f"Odoo: starting — log: {d.get('log')}")
        else:
            print(f"Odoo start: {d}")
    elif subcommand == "stop":
        d = _post("/api/odoo/stop", {})
        status = d.get("status", "")
        if status == "not_running":
            print("Odoo: already stopped")
        elif status == "stopping":
            print(f"Odoo: SIGTERM sent (pid={d.get('pid')})")
        else:
            print(f"Odoo stop: {d}")
    elif subcommand == "restart":
        d = _post("/api/odoo/restart", {})
        status = d.get("status", "")
        if status == "not_running":
            print("Odoo: not running — use 'cli.py odoo start' instead")
        elif status == "restarting":
            print("Odoo: restarting…")
        else:
            print(f"Odoo restart: {d}")
    else:
        print(f"Unknown odoo subcommand: {subcommand}  (start|stop|restart|status)", file=sys.stderr)
        sys.exit(1)



if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    command = sys.argv[1]
    rest = sys.argv[2:]
    if command == "task":
        cmd_task(rest)
    elif command == "board":
        cmd_board(rest)
    elif command == "odoo":
        cmd_odoo(rest)
    elif command == "flow":
        cmd_flow(rest)
    elif command == "runs":
        cmd_runs(rest)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
