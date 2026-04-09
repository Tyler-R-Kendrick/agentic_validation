"""Trace persistence layer using SQLite for reproducibility."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_DEFAULT_DB = Path("agentic_validation_traces.db")


def _get_connection(db_path: Path = _DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = _DEFAULT_DB) -> None:
    """Create the schema if it does not exist."""
    with _LOCK:
        conn = _get_connection(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id      TEXT PRIMARY KEY,
                    task_id     TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    status      TEXT,
                    input_json  TEXT,
                    result_json TEXT
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id      TEXT NOT NULL,
                    event_type  TEXT NOT NULL,
                    timestamp   TEXT NOT NULL,
                    payload     TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs(run_id)
                );
                """
            )
            conn.commit()
        finally:
            conn.close()


def log_run_start(
    run_id: str,
    task_id: str,
    task_input: Any,
    db_path: Path = _DEFAULT_DB,
) -> None:
    """Persist a new run record.

    Raises ``ValueError`` if a run with the same *run_id* already exists so
    that duplicate IDs are surfaced immediately rather than silently overwriting
    existing data.
    """
    with _LOCK:
        conn = _get_connection(db_path)
        try:
            conn.execute(
                """
                INSERT INTO runs (run_id, task_id, created_at, status, input_json)
                VALUES (?, ?, ?, 'running', ?)
                """,
                (
                    run_id,
                    task_id,
                    _now(),
                    _dump(task_input),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"A run with run_id={run_id!r} already exists.") from exc
        else:
            conn.commit()
        finally:
            conn.close()


def log_event(
    run_id: str,
    event_type: str,
    payload: Any,
    db_path: Path = _DEFAULT_DB,
) -> None:
    """Append a structured event to the events log."""
    with _LOCK:
        conn = _get_connection(db_path)
        try:
            conn.execute(
                """
                INSERT INTO events (run_id, event_type, timestamp, payload)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, event_type, _now(), _dump(payload)),
            )
            conn.commit()
        finally:
            conn.close()


def log_run_end(
    run_id: str,
    result: Any,
    status: str,
    db_path: Path = _DEFAULT_DB,
) -> None:
    """Update the run record with the final result."""
    with _LOCK:
        conn = _get_connection(db_path)
        try:
            conn.execute(
                """
                UPDATE runs SET status = ?, result_json = ? WHERE run_id = ?
                """,
                (status, _dump(result), run_id),
            )
            conn.commit()
        finally:
            conn.close()


def get_run(run_id: str, db_path: Path = _DEFAULT_DB) -> dict | None:
    """Retrieve a persisted run by ID."""
    with _LOCK:
        conn = _get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        finally:
            conn.close()
    if row is None:
        return None
    return dict(row)


def get_events(run_id: str, db_path: Path = _DEFAULT_DB) -> list[dict]:
    """Retrieve all events for a run, in order."""
    with _LOCK:
        conn = _get_connection(db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM events WHERE run_id = ? ORDER BY event_id", (run_id,)
            ).fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _dump(obj: Any) -> str:
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(), default=str)
    return json.dumps(obj, default=str)
