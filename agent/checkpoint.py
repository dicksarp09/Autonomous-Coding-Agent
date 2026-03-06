"""Checkpoint persistence for AgentStateModel.

Persist state snapshots to workspace files and SQLite to enable auditability and recovery.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
from typing import Any, Optional
from .config import WORKSPACE_ROOT, DB_PATH
import sqlite3


CHECKPOINT_DIR = WORKSPACE_ROOT / "agent_checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


def save_state(state: Any, name: str | None = None) -> Path:
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    fname = (name or "state") + f"_{ts}.json"
    p = CHECKPOINT_DIR / fname
    with p.open("w", encoding="utf-8") as f:
        json.dump(state if isinstance(state, dict) else state.model_dump(), f, indent=2, default=str)
    # persist simple index in sqlite
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS checkpoints (id INTEGER PRIMARY KEY, path TEXT, timestamp TEXT)")
        cur.execute("INSERT INTO checkpoints (path, timestamp) VALUES (?, ?)", (str(p), datetime.utcnow().isoformat()))
        conn.commit()
    finally:
        conn.close()
    return p


def restore_last_checkpoint() -> Optional[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("SELECT path FROM checkpoints ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if not row:
            return None
        p = Path(row[0])
        if not p.exists():
            return None
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    finally:
        conn.close()
