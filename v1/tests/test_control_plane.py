from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_team_v1.adapters import AdapterResult, MockAdapter
from agent_team_v1.models import AcceptanceResult, AgentOutcome, DeliveryStatus, TaskState
from agent_team_v1.service import ConflictError, ControlPlane
from agent_team_v1.store import SQLiteStore


def make_plane(root: Path) -> ControlPlane:
    return ControlPlane(SQLiteStore(root / "state.sqlite3"))


def make_task(plane: ControlPlane, task_id: str = "demo-1"):
    return plane.create_task(
        task_id=task_id,
        provider="mock",
        adapter="agent-call-v1",
        workspace="/tmp/demo",
        objective="verify lifecycle",
        prompt="read the fixture",
        acceptance_criteria=("response observed", "evidence recorded"),
        request_id=f"request-{task_id}",
    )


class UnknownAdapter:
    def __init__(self):
        self.calls = 0

    def dispatch(self, task):
        self.calls += 1
        return AdapterResult(delivery=DeliveryStatus.UNKNOWN, error="transport_timeout")


class ControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent-team-v1-")
        self.plane = make_plane(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_mock_lifecycle_separates_execution_and_acceptance(self):
        planned = make_task(self.plane)
        self.assertEqual(planned.state, TaskState.PLANNED)
        observed = self.plane.dispatch(planned.task_id, MockAdapter())
        self.assertEqual(observed.state, TaskState.RESULT_OBSERVED)
        self.assertEqual(observed.agent_outcome, AgentOutcome.COMPLETED)
        self.assertEqual(observed.caller_acceptance, AcceptanceResult.NOT_RUN)
        accepted = self.plane.accept(
            planned.task_id,
            result=AcceptanceResult.PASSED,
            evidence=("mock response observed",),
        )
        self.assertEqual(accepted.state, TaskState.ACCEPTED)

    def test_dispatch_is_idempotent_after_observed_result(self):
        task = make_task(self.plane)
        first = self.plane.dispatch(task.task_id, MockAdapter())
        second = self.plane.dispatch(task.task_id, MockAdapter())
        self.assertEqual(first.request_id, second.request_id)
        self.assertEqual(len(self.plane.events(task.task_id)), 2)

    def test_unknown_delivery_cannot_be_retried_blindly(self):
        task = make_task(self.plane)
        adapter = UnknownAdapter()
        unknown = self.plane.dispatch(task.task_id, adapter)
        self.assertEqual(unknown.state, TaskState.DELIVERY_UNKNOWN)
        with self.assertRaises(ConflictError):
            self.plane.dispatch(task.task_id, adapter)
        self.assertEqual(adapter.calls, 1)

    def test_acceptance_requires_evidence_and_observed_result(self):
        task = make_task(self.plane)
        with self.assertRaises(ConflictError):
            self.plane.accept(task.task_id, result=AcceptanceResult.PASSED, evidence=("proof",))
        self.plane.dispatch(task.task_id, MockAdapter())
        with self.assertRaises(Exception):
            self.plane.accept(task.task_id, result=AcceptanceResult.PASSED, evidence=())

    def test_duplicate_task_is_rejected(self):
        make_task(self.plane)
        with self.assertRaises(ConflictError):
            make_task(self.plane)


if __name__ == "__main__":
    unittest.main()
