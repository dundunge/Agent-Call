from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import (
    AcceptanceResult,
    AgentOutcome,
    DeliveryStatus,
    TaskSnapshot,
    TaskSpec,
    TaskState,
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SQLiteStore:
    """Small durable ledger for the V1 control plane.

    The store is intentionally independent from any model framework. It keeps
    task state and an append-only event trail, while adapters own provider I/O.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL,
                    request_id TEXT NOT NULL UNIQUE,
                    provider TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    acceptance_criteria TEXT NOT NULL,
                    state TEXT NOT NULL,
                    delivery TEXT NOT NULL,
                    agent_outcome TEXT NOT NULL,
                    caller_acceptance TEXT NOT NULL,
                    native_ref TEXT,
                    response TEXT,
                    error TEXT,
                    evidence TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_task_id_idx ON events(task_id, id);
                """
            )

    def create(self, spec: TaskSpec, prompt_hash: str, now: str | None = None) -> TaskSnapshot:
        timestamp = now or utc_now()
        snapshot = TaskSnapshot(
            task_id=spec.task_id,
            attempt_id=spec.attempt_id,
            request_id=spec.request_id,
            provider=spec.provider,
            adapter=spec.adapter,
            workspace=spec.workspace,
            objective=spec.objective,
            prompt=spec.prompt,
            acceptance_criteria=spec.acceptance_criteria,
            state=TaskState.PLANNED,
            delivery=DeliveryStatus.UNKNOWN,
            agent_outcome=AgentOutcome.NOT_STARTED,
            caller_acceptance=AcceptanceResult.NOT_RUN,
            native_ref=None,
            response=None,
            error=None,
            evidence=(),
            prompt_hash=prompt_hash,
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, attempt_id, request_id, provider, adapter, workspace,
                    objective, prompt, acceptance_criteria, state, delivery,
                    agent_outcome, caller_acceptance, native_ref, response, error,
                    evidence, prompt_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.task_id,
                    snapshot.attempt_id,
                    snapshot.request_id,
                    snapshot.provider,
                    snapshot.adapter,
                    snapshot.workspace,
                    snapshot.objective,
                    snapshot.prompt,
                    json_text(snapshot.acceptance_criteria),
                    snapshot.state.value,
                    snapshot.delivery.value,
                    snapshot.agent_outcome.value,
                    snapshot.caller_acceptance.value,
                    snapshot.native_ref,
                    snapshot.response,
                    snapshot.error,
                    json_text(snapshot.evidence),
                    snapshot.prompt_hash,
                    snapshot.created_at,
                    snapshot.updated_at,
                ),
            )
            self._append_event(connection, snapshot.task_id, "task_planned", {"requestId": snapshot.request_id}, timestamp)
        return snapshot

    def get(self, task_id: str) -> TaskSnapshot | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return self._row_to_snapshot(row) if row else None

    def list(self) -> list[TaskSnapshot]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM tasks ORDER BY created_at, task_id").fetchall()
        return [self._row_to_snapshot(row) for row in rows]

    def update(self, snapshot: TaskSnapshot, event_type: str, payload: dict[str, Any], now: str | None = None) -> TaskSnapshot:
        timestamp = now or utc_now()
        updated = replace(snapshot, updated_at=timestamp)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks SET state=?, delivery=?, agent_outcome=?, caller_acceptance=?,
                    native_ref=?, response=?, error=?, evidence=?, updated_at=?
                WHERE task_id=?
                """,
                (
                    updated.state.value,
                    updated.delivery.value,
                    updated.agent_outcome.value,
                    updated.caller_acceptance.value,
                    updated.native_ref,
                    updated.response,
                    updated.error,
                    json_text(updated.evidence),
                    updated.updated_at,
                    updated.task_id,
                ),
            )
            self._append_event(connection, updated.task_id, event_type, payload, timestamp)
        return updated

    def events(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_type, payload, created_at FROM events WHERE task_id=? ORDER BY id",
                (task_id,),
            ).fetchall()
        return [
            {"eventType": row["event_type"], "payload": json.loads(row["payload"]), "createdAt": row["created_at"]}
            for row in rows
        ]

    @staticmethod
    def _append_event(connection: sqlite3.Connection, task_id: str, event_type: str, payload: dict[str, Any], timestamp: str) -> None:
        connection.execute(
            "INSERT INTO events(task_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            (task_id, event_type, json_text(payload), timestamp),
        )

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> TaskSnapshot:
        return TaskSnapshot(
            task_id=row["task_id"],
            attempt_id=row["attempt_id"],
            request_id=row["request_id"],
            provider=row["provider"],
            adapter=row["adapter"],
            workspace=row["workspace"],
            objective=row["objective"],
            prompt=row["prompt"],
            acceptance_criteria=tuple(json.loads(row["acceptance_criteria"])),
            state=TaskState(row["state"]),
            delivery=DeliveryStatus(row["delivery"]),
            agent_outcome=AgentOutcome(row["agent_outcome"]),
            caller_acceptance=AcceptanceResult(row["caller_acceptance"]),
            native_ref=row["native_ref"],
            response=row["response"],
            error=row["error"],
            evidence=tuple(json.loads(row["evidence"])),
            prompt_hash=row["prompt_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
