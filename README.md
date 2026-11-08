# Dev Dashboard

A local developer dashboard for Odoo projects. Built with FastAPI + SQLite backend and a single-file SPA frontend.

**Features:**
- **Sessions** — browse Claude Code sessions linked to task numbers (T26-XXXXX)
- **AI Chat** — chat with Claude, renders Markdown tables and Mermaid diagrams inline
- **Databases** — one-click PostgreSQL database switching with Odoo restart, addons path profiles
- **Make** — run Makefile targets with a UI, streams live output
- **Board** — persistent explanations board (Mermaid diagrams, Markdown tables)

---

## Requirements

- Python 3.10+
- An Odoo installation (the dashboard auto-detects any `/home/<user>/odoo*` directory that has `odoo-bin` + `odoo/release.py`)
- PostgreSQL running locally
- `fastapi`, `uvicorn`, `httpx` pip packages

---

## Installation

### 1. Clone

```bash
git clone git@github.com:AgentAtnaf/dev-dashboard.git /home/server/dev-dashboard
```

### 2. Install Python dependencies

Use your Odoo venv or a dedicated one:

```bash
/home/server/odoo-17.0/.venv/bin/pip install fastapi uvicorn httpx
```

### 3. Adapt hardcoded paths in `server.py`

Open `server.py` and update the constants near the top to match your environment:

```python
# Line ~29 — path to your primary Odoo installation
ODOO_CONF   = "/home/server/odoo-17.0/odoo.conf"
MAKEFILE_DIR = "/home/server/odoo-17.0"

# Line ~32 — Claude Code project dirs to track sessions from
CLAUDE_PROJECTS = [
    ("/home/server/.claude/projects/-home-server-odoo-17-0", "odoo-17.0"),
    # add more if you have multiple Odoo workspaces
]

# Line ~39 — project dirs shown in the Sessions tab
PROJECT_DIRS = {
    "odoo-17.0": "/home/server/odoo-17.0",
}

# Line ~46 — default addons path profiles for the Databases tab
_BASE = "/home/server/odoo-17.0"
```

> **Odoo installs are auto-detected** by scanning `glob("/home/<user>/odoo*")` — any directory with `odoo-bin` + `odoo/release.py` is picked up automatically. No config needed for additional versions.

### 4. Run it as a systemd user service (recommended)

Do **not** start the server from a shell with `nohup`/`setsid`/`&`. Even when it
survives SIGHUP it stays inside your login session, so reloading the VS Code
window — switching workspace folder, reconnecting Remote-SSH — tears down the
pty and takes the dashboard with it. Symptom: the dashboard "randomly" closes
whenever you change project directory.

`dev-dashboard.service` in this repo runs it under `user@.service` instead,
where the editor's process tree cannot reach it, and restarts it if it crashes:

```bash
mkdir -p ~/.config/systemd/user
cp /home/server/dev-dashboard/dev-dashboard.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dev-dashboard.service
loginctl enable-linger "$USER"   # also survives logout and reboot
```

Check it landed outside the session scope — this must say `app.slice`, not
`session-N.scope`:

```bash
cat /proc/$(pgrep -f dev-dashboard/server.py)/cgroup
```

Day to day:

```bash
systemctl --user status dev-dashboard        # is it up
systemctl --user restart dev-dashboard       # after editing server.py
journalctl --user -u dev-dashboard -f        # follow the log
```

Optional `Makefile` shortcuts (`make dashboard`, `dashboard-install`,
`dashboard-stop`, `dashboard-log`) wrap exactly these commands.

### 5. (Optional) Wire `cli.py` into Claude Code

Add to your `CLAUDE.md` so Claude Code automatically records task numbers and saves diagrams:

```markdown
## Dev Dashboard Integration

After every commit, record the task number:
\`\`\`bash
/home/server/dev-dashboard/cli.py task T26-XXXXX
\`\`\`

Save diagrams/tables to the Board tab:
\`\`\`bash
/home/server/dev-dashboard/cli.py board "Title" mermaid "graph TD\n  A --> B"
/home/server/dev-dashboard/cli.py board "Title" markdown "| Col | Col |\n|---|---|\n| val | val |"
\`\`\`

Manage Odoo without hand-rolling odoo-bin commands:
\`\`\`bash
/home/server/dev-dashboard/cli.py odoo status
/home/server/dev-dashboard/cli.py odoo start            # start against current odoo.conf db_name
/home/server/dev-dashboard/cli.py odoo start --version 19
/home/server/dev-dashboard/cli.py odoo stop
/home/server/dev-dashboard/cli.py odoo restart
\`\`\`
```

> Set `ODOO_SESSION_ID` to the current caller’s session ID, or pass `--session-id`. The CLI never guesses another session from log timestamps.

---

## Running

```bash
# Direct
/home/server/odoo-17.0/.venv/bin/python /home/server/dev-dashboard/server.py

# Via make (if configured)
make dashboard
```

Dashboard runs at **http://192.168.64.3:7878** on the approved trusted LAN, with loopback **http://127.0.0.1:7878** retained for the CLI. It has no authentication. No SSH or VS Code forwarding is needed. Set `DASHBOARD_LAN_HOST` to change the private bind address, or an empty string for loopback-only access.

The SQLite database (`session_map.db`) is created automatically on first run and is gitignored.

---

## Project structure

```
dev-dashboard/
├── server.py       # FastAPI backend — all API endpoints, SQLite, Odoo process control
├── index.html      # Single-file SPA — all tabs, JS, CSS (Tailwind)
├── cli.py          # CLI helper for Claude Code hooks (task recording, board saving)
├── vendor/         # Vendored JS libs (offline-safe — no CDN dependency)
│   ├── tailwind.js
│   ├── marked.min.js
│   ├── mermaid.min.js
│   └── purify.min.js
├── session_map.db  # SQLite DB (auto-created, gitignored)
└── .gitignore
```

## Explicit task and session context

The CLI no longer chooses the newest Claude log file. Supply a session ID owned
by the current caller, either with `--session-id` or `ODOO_SESSION_ID`.
Task recording requires a session; flows and Board items can remain unassigned.
Flags override environment variables.

```bash
./cli.py task T26-12345 --session-id my-session
./cli.py flow save so-confirm /path/to/so-confirm.txt \
  --task T26-12345 --session-id my-session --db my_test_db
./cli.py board "Verification notes" markdown "Assertions passed" \
  --task T26-12345 --session-id my-session
```

Shared options: `--task` / `ODOO_TASK`, `--session-id` / `ODOO_SESSION_ID`, and
`--db` / `ODOO_DB` (database metadata applies to flows and flow visuals).
`ODOO_DASHBOARD_URL` overrides `http://127.0.0.1:7878` for the CLI and trace launcher.

The flow API stores `db_name` and returns it in list/get responses. Startup adds
this column to existing databases without changing saved flows. The read-only
`GET /api/sessions/<session-id>/context` returns that exact session's latest task,
including caller-supplied IDs without a Claude log file. Missing sessions return
an empty task. `POST /api/sessions/record-task` rejects an omitted session ID.
Restart the dashboard server after updating so the endpoint and migration load.

Run context/migration checks with the project's Python environment:

```bash
python tests/test_context.py
```

The tests use a temporary SQLite database and do not modify dashboard sessions.

## Flow run history

Start with the shared [tool guide](/home/server/odoo-17.0/TOOLS.md). The Flows tab
shows execution history with status filtering, 50-run pages, step errors and
durations, captured source, and trace/log/result downloads. Saved definitions
can still be copied, downloaded, or deleted independently of past runs.

`flow_runs` is added automatically to the existing SQLite database. The index
scans `.result.json` files and legacy ZIPs in `Record_task/` and kit `traces/`
(limited to one scan per two seconds). Override roots with `TRACE_HISTORY_DIRS`
using colon-separated absolute paths. Legacy ZIPs have unknown verdicts and no
source snapshot. Running reports older than five minutes display as stale.

APIs: `GET /api/flow-runs?flow_name=...&status=...&limit=50&offset=0`,
`GET /api/flow-runs/{run_id}`, and
`GET /api/flow-runs/{run_id}/artifacts/{trace|log|result|flow}`.
Artifacts are resolved only within configured roots; saved JSON and source
snapshots remain available if the original artifact files are removed.

Validate with `python -m unittest discover -s tests` using the project venv.

Browser check: `NODE_PATH=/home/server/odoo-trace-kit/node_modules node tests/history_ui.js`.
It starts an isolated dashboard with temporary fixtures and captures desktop/mobile screenshots.

## Browser and runtime evidence

New runs automatically capture same-origin browser JSON-RPC POST requests.
Each request has a run-scoped request ID and the ID/source line of the step active
when it started. Late responses stay linked to that step. Background traffic can
overlap: this association is timing evidence, not proof that a click caused it.

In Flows, expand an RPC below its step to see endpoint, model/method, sanitized
parameters, HTTP/RPC status, duration, and the error/actual Python traceback
returned by Odoo. HTTP 200 with a JSON-RPC error is labeled `rpc_error`. Network
failures and incomplete response capture are explicit. Older runs have no runtime
evidence. RPC errors are diagnostic evidence; existing assertion verdicts remain
unchanged, since some flows intentionally trigger errors.

Without `--python-trace`, this uses Odoo's existing response data and needs no
server restart. This default capture does not trace successful Python overrides, SQL, commits, or record changes, and does not
observe the runner's separate API login/session probes. Correlation IDs are local
to the report, not injected into Odoo logs. Match trace network entries using
endpoint, start time, JSON-RPC ID, and parameters. Successful result bodies are
omitted. Authentication parameters/details and sensitive parameter keys are
redacted; arbitrary positional values and traceback text can still contain data.
Capture is capped at 500 requests, 1 MiB per response, and bounded parameter and
traceback lengths. The runner drains responses for up to two seconds at shutdown.

## Failure summaries and opt-in Python tracing

Run details start with a deterministic failure summary: failed assertion (or
first failed step), startup error, correlated RPC errors, and earlier errors
that may be related. Timing correlation is explicitly labeled as uncertain.
A recorded RPC error does not override assertion verdicts, because some tests
intentionally exercise error paths. Summary links jump to the underlying evidence.

For deeper tracing, enable the server-wide observer for the Odoo configuration
you intend to run (no database module installation or schema change):

```bash
python3 /home/server/odoo-trace-kit/server-trace.py enable --config /path/to/odoo.conf
/home/server/dev-dashboard/cli.py odoo restart
/home/server/odoo-trace-kit/trace-local.sh example http://localhost:8069/web/login --db DATABASE --flow /path/to/flow.txt --python-trace
```

`enable` preserves existing addon/module entries and backs up the configuration;
it adds the kit's `server_addons` path and `tracekit_runtime` server-wide module.
Use `disable` with the same config and restart to unload it. `status` reports
configuration only, not whether the current process loaded the observer. Explicit
`--load`/`--addons-path` server arguments override config; include the observer
there too if used. Re-enable after switching to an addon profile that removes
the observer path. Apply separately for each Odoo installation you want to trace.

Only signed, same-origin `/web/dataset/` POSTs during recorded steps are profiled.
The report embeds the matching server trace using run/request/step IDs; the
server keeps originals under `.runtime/traces/<run-id>/`. Both processes need
access to the same kit/state directory. `TRACEKIT_STATE_DIR` can specify a shared
alternative (including its 32-byte `key`). No key or raw credentials are included
in Python call evidence. Requests without valid signatures remain unprofiled.

Expand an RPC to see actual executed addon/ORM functions, source file and line,
parent calls, model name, and inclusive duration. This proves executed Python
paths, not successful database commits. Return events also occur when exceptions
unwind; `complete` means a return event was observed, not business success.
No arguments, locals, record contents, SQL text, or record-change audit are captured.

Limits: 2,000 calls and 10 seconds per request; partial captures are labeled.
Timings include profiling overhead and nested calls. Existing profilers and
gevent workers are skipped. WSGI dispatch is covered; streaming response bodies,
cron/background workers, and C/native calls are not. Observer hooks target the
installed Odoo 14 `Root` and Odoo 17/19 `Application` WSGI entrypoints.

Summary checks: `node tests/failure_summary.js`. Observer checks are part of the trace-kit regression suite.
