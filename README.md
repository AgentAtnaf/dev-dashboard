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

### 4. (Optional) Add a `make dashboard` shortcut

Add to your `Makefile`:

```makefile
VENV_PYTHON := /home/server/odoo-17.0/.venv/bin/python

dashboard:
	@PID=$$(ss -ltnp 2>/dev/null | grep '127.0.0.1:7878 ' | grep -oP 'pid=\K[0-9]+' | head -1); \
	if [ -n "$$PID" ]; then \
		echo "Dashboard already running (PID $$PID) → http://127.0.0.1:7878"; \
	else \
		setsid $(VENV_PYTHON) /home/server/dev-dashboard/server.py > /tmp/dashboard.log 2>&1 < /dev/null & disown; \
		sleep 1.5; \
		echo "Dashboard started → http://127.0.0.1:7878"; \
	fi
```

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
```

> `cli.py` auto-detects the current Claude Code session by finding the most-recently-modified `.jsonl` in your Claude projects directory.

---

## Running

```bash
# Direct
/home/server/odoo-17.0/.venv/bin/python /home/server/dev-dashboard/server.py

# Via make (if configured)
make dashboard
```

Dashboard runs at **http://127.0.0.1:7878** — localhost only, no auth needed.

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
