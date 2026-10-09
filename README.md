# Experience Bank

A Claude connector (MCP server) that gives Claude a persistent experience bank and application tracker.

Tools: `save_experience`, `match_to_job`, `track_application`.

## Install in Claude (first-timers)

1. Invent a **personal key**: 16+ letters/digits, e.g. `maple-orbit-4821-quartz`. It is your password. Anyone with it can read your bank. Don't share it.
2. Your connector URL is `https://experience-bank.onrender.com/u/YOUR-KEY/mcp`.
3. In Claude (claude.ai or the desktop app): **Settings → Connectors → Add custom connector**.
4. Name: `Experience Bank`. URL: the one from step 2. Leave any advanced/OAuth fields empty. Click **Add**.
5. In a new chat, click **+ → Connectors** and make sure Experience Bank is switched on.

First request after idle can take ~60s (free hosting sleeps). Retry once.

## Run locally

    python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/python -m pytest
    .venv/bin/python server.py   # SQLite file unless DATABASE_URL is set
