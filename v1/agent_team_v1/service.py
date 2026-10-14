from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from uuid import uuid4

from .adapters import Adapter
from .models import (
    AcceptanceResult,
    AgentOutcome,
    AdapterResult,
    DeliveryStatus,
    TaskSnapshot,
    TaskSpec,
    TaskState,
)
from .store import SQLiteStore


ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class ControlPlaneError(Exception):
    pass


class ConflictError(ControlPlaneError):
    pass


class NotFoundError(ControlPlaneError):
    pass


class ValidationError(ControlPlaneError):
    pass


class ControlPlane:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def create_task(
        self,
        *,
        task_id: str,
        provider: str,
        adapter: str,
        workspace: str,
        objective: str,
        prompt: str,
        acceptance_criteria: tuple[str, ...],
        attempt_id: str | None = None,
        request_id: str | None = None,
    ) -> TaskSnapshot:
        for name, value in (("task_id", task_id), ("provider", provider), ("adapter", adapter), ("workspace", workspace), ("objective", objective), ("prompt", prompt)):
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"{name} must be non-empty")
        if not ID_RE.fullmatch(task_id):
            raise ValidationError("task_id contains unsupported characters")
        if not acceptance_criteria or any(not item.strip() for item in acceptance_criteria):
            raise ValidationError("at least one acceptance criterion is required")
        spec = TaskSpec(
            task_id=task_id,
            provider=provider,
            adapter=adapter,
            workspace=workspace,
            objective=objective,
            prompt=prompt,
            acceptance_criteria=tuple(acceptance_criteria),
            attempt_id=attempt_id or f"attempt-{uuid4().hex[:12]}",
            request_id=request_id or f"request-{uuid4().hex}",
        )
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        try:
            return self.store.create(spec, prompt_hash)
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise ConflictError("task_id or request_id already exists") from exc
            raise

    def dispatch(self, task_id: str, adapter: Adapter) -> TaskSnapshot:
        task = self._require(task_id)
        if task.state in {TaskState.ACCEPTED, TaskState.REJECTED, TaskState.RESULT_OBSERVED, TaskState.DISPATCHED}:
            return task
        if task.state == TaskState.DELIVERY_UNKNOWN:
            raise ConflictError("delivery is unknown; reconcile the original request before retrying")
        result = adapter.dispatch(task)
        return self._apply_adapter_result(task, result)

    def reconcile(self, task_id: str, *, delivery: DeliveryStatus, native_ref: str | None = None, error: str | None = None) -> TaskSnapshot:
        task = self._require(task_id)
        if task.state != TaskState.DELIVERY_UNKNOWN:
            raise ConflictError("reconcile is only valid for delivery_unknown tasks")
        if delivery == DeliveryStatus.UNKNOWN:
            raise ValidationError("reconcile requires accepted or rejected delivery")
        state = TaskState.DISPATCHED if delivery == DeliveryStatus.ACCEPTED else TaskState.FAILED
        return self.store.update(
            replace(task, state=state, delivery=delivery, native_ref=native_ref, error=error),
            "delivery_reconciled",
            {"delivery": delivery.value, "nativeRef": native_ref},
        )

    def observe(self, task_id: str, *, outcome: AgentOutcome, response: str | None = None, error: str | None = None) -> TaskSnapshot:
        task = self._require(task_id)
        if task.state not in {TaskState.DISPATCHED, TaskState.DELIVERY_UNKNOWN}:
            raise ConflictError("observe requires a dispatched task")
        state = TaskState.RESULT_OBSERVED if outcome == AgentOutcome.COMPLETED else TaskState.FAILED
        return self.store.update(
            replace(task, state=state, agent_outcome=outcome, response=response, error=error),
            "result_observed",
            {"agentOutcome": outcome.value, "hasResponse": response is not None},
        )

    def accept(self, task_id: str, *, result: AcceptanceResult, evidence: tuple[str, ...]) -> TaskSnapshot:
        task = self._require(task_id)
        if task.state != TaskState.RESULT_OBSERVED:
            raise ConflictError("caller acceptance requires an observed result")
        if not evidence or any(not item.strip() for item in evidence):
            raise ValidationError("caller acceptance requires evidence")
        state = TaskState.ACCEPTED if result == AcceptanceResult.PASSED else TaskState.REJECTED
        return self.store.update(
            replace(task, state=state, caller_acceptance=result, evidence=tuple(evidence)),
            "caller_acceptance",
            {"result": result.value, "evidenceCount": len(evidence)},
        )

    def status(self, task_id: str) -> TaskSnapshot:
        return self._require(task_id)

    def events(self, task_id: str) -> list[dict]:
        self._require(task_id)
        return self.store.events(task_id)

    def _apply_adapter_result(self, task: TaskSnapshot, result: AdapterResult) -> TaskSnapshot:
        if result.delivery == DeliveryStatus.UNKNOWN:
            state = TaskState.DELIVERY_UNKNOWN
        elif result.delivery == DeliveryStatus.REJECTED:
            state = TaskState.FAILED
        elif result.agent_outcome == AgentOutcome.COMPLETED:
            state = TaskState.RESULT_OBSERVED
        else:
            state = TaskState.DISPATCHED
        return self.store.update(
            replace(
                task,
                state=state,
                delivery=result.delivery,
                agent_outcome=result.agent_outcome,
                native_ref=result.native_ref,
                response=result.response,
                error=result.error,
            ),
            "dispatch_result",
            {"delivery": result.delivery.value, "agentOutcome": result.agent_outcome.value},
        )

    def _require(self, task_id: str) -> TaskSnapshot:
        task = self.store.get(task_id)
        if task is None:
            raise NotFoundError(f"task not found: {task_id}")
        return task
