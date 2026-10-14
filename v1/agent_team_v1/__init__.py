"""Agent Team V1 control plane.

The package owns task state, idempotency, receipts, and caller acceptance.
Provider-specific execution stays behind adapters, including the existing
``agent-call`` bridges in the parent repository.
"""

__version__ = "0.1.0"

from .adapters import AdapterResult, CommandAdapter, MockAdapter
from .models import AcceptanceResult, DeliveryStatus, TaskSnapshot, TaskState
from .service import ControlPlane, ConflictError, NotFoundError, ValidationError
from .store import SQLiteStore

__all__ = [
    "AcceptanceResult",
    "AdapterResult",
    "CommandAdapter",
    "ConflictError",
    "ControlPlane",
    "DeliveryStatus",
    "MockAdapter",
    "NotFoundError",
    "SQLiteStore",
    "TaskSnapshot",
    "TaskState",
    "ValidationError",
]
