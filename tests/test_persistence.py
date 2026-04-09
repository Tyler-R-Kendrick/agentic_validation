"""Tests for the persistence layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_validation.persistence import (
    get_events,
    get_run,
    init_db,
    log_event,
    log_run_end,
    log_run_start,
)


@pytest.fixture
def db(tmp_path) -> Path:
    path = tmp_path / "test.db"
    init_db(path)
    return path


class TestPersistence:
    def test_init_db_creates_tables(self, db):
        import sqlite3
        conn = sqlite3.connect(str(db))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "runs" in tables
        assert "events" in tables

    def test_log_run_start(self, db):
        log_run_start("run-1", "task-1", {"goal": "test"}, db)
        run = get_run("run-1", db)
        assert run is not None
        assert run["task_id"] == "task-1"
        assert run["status"] == "running"

    def test_log_run_end(self, db):
        log_run_start("run-2", "task-2", {}, db)
        log_run_end("run-2", {"final_answer": "ok"}, "soft_verified", db)
        run = get_run("run-2", db)
        assert run["status"] == "soft_verified"
        assert "ok" in run["result_json"]

    def test_log_event(self, db):
        log_run_start("run-3", "task-3", {}, db)
        log_event("run-3", "step_critiqued", {"step_id": "s1", "labels": []}, db)
        events = get_events("run-3", db)
        assert len(events) == 1
        assert events[0]["event_type"] == "step_critiqued"

    def test_multiple_events_ordered(self, db):
        log_run_start("run-4", "task-4", {}, db)
        for i in range(5):
            log_event("run-4", f"event_{i}", {"index": i}, db)
        events = get_events("run-4", db)
        assert len(events) == 5
        for i, event in enumerate(events):
            payload = json.loads(event["payload"])
            assert payload["index"] == i

    def test_get_run_missing(self, db):
        result = get_run("does-not-exist", db)
        assert result is None

    def test_get_events_empty(self, db):
        log_run_start("run-5", "task-5", {}, db)
        events = get_events("run-5", db)
        assert events == []

    def test_pydantic_model_serialized(self, db):
        from agentic_validation.schemas import TaskInput
        task = TaskInput(task_id="t1", goal="G")
        log_run_start("run-6", "t1", task, db)
        run = get_run("run-6", db)
        payload = json.loads(run["input_json"])
        assert payload["task_id"] == "t1"
        assert payload["goal"] == "G"
