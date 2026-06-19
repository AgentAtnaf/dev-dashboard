#!/home/server/odoo-17.0/.venv/bin/python
"""
Dev Dashboard CLI helper — called by Claude Code after commits or when saving explanations.

Usage:
  cli.py task T26-12345              # record task number for current session
  cli.py board "Title" mermaid "…"  # save mermaid/markdown to Board tab
  cli.py board "Title" markdown "…"
"""
import sys
import os
import json
import urllib.request
import urllib.error

DASHBOARD_URL = "http://127.0.0.1:7878"


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
        return {}


def _get_session_id() -> str | None:
    """Find the most-recently modified .jsonl across all Claude project dirs."""
    projects_root = os.path.expanduser("~/.claude/projects")
    all_files = []
    try:
        for project_dir in os.listdir(projects_root):
            full_dir = os.path.join(projects_root, project_dir)
            if not os.path.isdir(full_dir):
                continue
            try:
                all_files += [
                    os.path.join(full_dir, f)
                    for f in os.listdir(full_dir)
                    if f.endswith(".jsonl")
                ]
            except OSError:
                pass
    except OSError:
        pass
    if not all_files:
        return None
    latest = max(all_files, key=os.path.getmtime)
    return os.path.splitext(os.path.basename(latest))[0]


def cmd_task(args: list[str]):
    if not args:
        print("Usage: cli.py task T26-XXXXX", file=sys.stderr)
        sys.exit(1)
    task_number = args[0].strip()
    session_id = _get_session_id()
    payload = {"task_number": task_number}
    if session_id:
        payload["session_id"] = session_id
    result = _post("/api/sessions/record-task", payload)
    if result.get("ok"):
        print(f"[cli.py] Recorded task {task_number} for session {session_id or '(unknown)'}")
    else:
        print(f"[cli.py] Response: {result}")


def cmd_board(args: list[str]):
    if len(args) < 3:
        print('Usage: cli.py board "Title" mermaid|markdown "content"', file=sys.stderr)
        sys.exit(1)
    title, content_type, content = args[0], args[1], args[2]
    # decode escape sequences so \n in shell strings becomes real newlines
    content = content.replace('\\n', '\n').replace('\\t', '\t')
    if content_type not in ("mermaid", "markdown", "table"):
        print(f"[cli.py] Unknown type '{content_type}', using 'markdown'", file=sys.stderr)
        content_type = "markdown"
    session_id = _get_session_id()
    payload = {"title": title, "content": content, "content_type": content_type}
    if session_id:
        payload["session_id"] = session_id
    result = _post("/api/board", payload)
    if result.get("ok"):
        print(f"[cli.py] Saved '{title}' ({content_type}) to Board, id={result.get('id')}")
    else:
        print(f"[cli.py] Response: {result}")


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
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)
