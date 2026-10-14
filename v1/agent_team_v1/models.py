from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class DeliveryStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNKNOWN = "unknown"
    SIMULATED = "simulated"


class AgentOutcome(StrEnum):
    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class AcceptanceResult(StrEnum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"


class TaskState(StrEnum):
    PLANNED = "planned"
    DISPATCHED = "dispatched"
    RESULT_OBSERVED = "result_observed"
    DELIVERY_UNKNOWN = "delivery_unknown"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    provider: str
    adapter: str
    workspace: str
    objective: str
    prompt: str
    acceptance_criteria: tuple[str, ...]
    attempt_id: str
    request_id: str


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    attempt_id: str
    request_id: str
    provider: str
    adapter: str
    workspace: str
    objective: str
    prompt: str
    acceptance_criteria: tuple[str, ...]
    state: TaskState
    delivery: DeliveryStatus
    agent_outcome: AgentOutcome
    caller_acceptance: AcceptanceResult
    native_ref: str | None
    response: str | None
    error: str | None
    evidence: tuple[str, ...]
    prompt_hash: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("state", "delivery", "agent_outcome", "caller_acceptance"):
            value[key] = value[key].value
        return value


@dataclass(frozen=True)
class AdapterResult:
    delivery: DeliveryStatus
    agent_outcome: AgentOutcome = AgentOutcome.UNKNOWN
    native_ref: str | None = None
    response: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class Event:
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
