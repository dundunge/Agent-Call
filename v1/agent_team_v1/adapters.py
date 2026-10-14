from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from typing import Protocol, Sequence

from .models import AdapterResult, AgentOutcome, DeliveryStatus, TaskSnapshot


class Adapter(Protocol):
    def dispatch(self, task: TaskSnapshot) -> AdapterResult:
        """Dispatch once; an uncertain response must remain uncertain."""


class MockAdapter:
    """Deterministic adapter used by local deployment and CI."""

    def dispatch(self, task: TaskSnapshot) -> AdapterResult:
        return AdapterResult(
            delivery=DeliveryStatus.SIMULATED,
            agent_outcome=AgentOutcome.COMPLETED,
            native_ref=f"mock:{task.request_id}",
            response=f"Simulated completion for {task.task_id}",
        )


class CommandAdapter:
    """Run an explicitly configured adapter command without a shell.

    The command receives a JSON task snapshot on stdin and must return one JSON
    object matching AdapterResult fields. This keeps provider bridges outside
    the control plane and avoids putting credentials in this package.
    """

    def __init__(self, command: Sequence[str], timeout_seconds: float = 90.0):
        if not command:
            raise ValueError("adapter command cannot be empty")
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds

    def dispatch(self, task: TaskSnapshot) -> AdapterResult:
        try:
            completed = subprocess.run(
                self.command,
                input=json.dumps(task.to_dict(), ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return AdapterResult(delivery=DeliveryStatus.UNKNOWN, error="adapter_timeout")
        except OSError as exc:
            return AdapterResult(delivery=DeliveryStatus.REJECTED, error=f"adapter_launch_failed:{type(exc).__name__}")
        if completed.returncode != 0:
            return AdapterResult(
                delivery=DeliveryStatus.UNKNOWN,
                error=f"adapter_exit:{completed.returncode}",
            )
        try:
            payload = json.loads(completed.stdout)
            return AdapterResult(
                delivery=DeliveryStatus(payload["delivery"]),
                agent_outcome=AgentOutcome(payload.get("agent_outcome", AgentOutcome.UNKNOWN.value)),
                native_ref=payload.get("native_ref"),
                response=payload.get("response"),
                error=payload.get("error"),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return AdapterResult(delivery=DeliveryStatus.UNKNOWN, error="adapter_invalid_json")
