"""Capture SVG screenshots of the doto TUI in every layout.

Builds a DotoApp against a temp store that has a *running* (time-recorded)
task so the Feature A "active task on top" pinning is visible, then cycles
through every layout (table/list/kanban/calendar) and opens the new
filter/sort pop-up, saving each as an SVG under the given output directory.

Usage:
    python scripts/tui_screenshots.py /tmp/doto-shots
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


def _build_store(root: Path) -> Path:
    """Write a temp tasks.json with a running task + varied metadata."""
    store_path = root / "repo" / ".doto" / "tasks.json"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    started = (now - timedelta(minutes=25)).isoformat()
    today = now.date().isoformat()
    soon = (now.date() + timedelta(days=2)).isoformat()
    data = {
        "version": 5,
        "updated": "2024-01-01T00:00:00",
        "tasks": {
            "T-001": {
                "title": "Write the quarterly report",
                "status": "open",
                "priority": "high",
                "tags": ["docs", "q3"],
                "due": today,
                "worklogs": [],
            },
            "T-002": {
                "title": "Fix the login bug",
                "status": "in-progress",
                "priority": "critical",
                "tags": ["bug"],
                "due": soon,
                # Running (open worklog) -> should be pinned to the top.
                "worklogs": [{"started_at": started, "stopped_at": None}],
            },
            "T-003": {
                "title": "Review pull request",
                "status": "open",
                "priority": "medium",
                "tags": ["review"],
                "worklogs": [],
            },
            "T-004": {
                "title": "Archive old specs",
                "status": "done",
                "priority": "low",
                "tags": [],
                "worklogs": [],
            },
        },
        "series": {},
    }
    store_path.write_text(json.dumps(data))
    return store_path


async def _capture(app, pilot, out: Path, name: str) -> None:
    await pilot.pause()
    await pilot.pause()
    app.save_screenshot(str(out / f"{name}.svg"))


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/doto-shots")
    out_dir.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix="doto-shot-"))
    os.environ["XDG_CONFIG_HOME"] = str(tmp / "xdg")
    store_file = _build_store(tmp)

    from doxtr_doto.cli.config import load_config
    from doxtr_doto.cli.global_state import GlobalStateStore
    from doxtr_doto.cli.json_store import JsonTaskStore
    from doxtr_doto.cli.main import DotoContext
    from doxtr_doto.cli.output import get_formatter
    from doxtr_doto.cli.tui import nudge
    from doxtr_doto.cli.tui.app import DotoApp

    config = load_config(json_path=store_file)
    ctx = DotoContext(
        config=config,
        store=JsonTaskStore(config.get_json_path()),
        formatter=get_formatter(config),
        global_store=GlobalStateStore(),
    )
    nudge.mark_prompted(ctx, nudge.today_iso())

    app = DotoApp(ctx)

    async def body() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await _capture(app, pilot, out_dir, "01-table")
            # Cycle layouts with 'v' (table -> list -> kanban -> calendar).
            await pilot.press("v")
            await _capture(app, pilot, out_dir, "02-list")
            await pilot.press("v")
            await _capture(app, pilot, out_dir, "03-kanban")
            await pilot.press("v")
            await _capture(app, pilot, out_dir, "04-calendar")
            await pilot.press("v")  # time layout
            await _capture(app, pilot, out_dir, "05-time")
            await pilot.press("v")  # wrap back to table
            await _capture(app, pilot, out_dir, "06-table-again")
            # Open the filter/sort popup (F) over the table layout.
            await pilot.press("F")
            await _capture(app, pilot, out_dir, "07-filter-sort-popup")

    asyncio.run(body())
    print(f"Saved screenshots to {out_dir}")
    for svg in sorted(out_dir.glob("*.svg")):
        print(f"  {svg.name}  ({svg.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
