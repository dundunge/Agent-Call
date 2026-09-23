# Visible agent task communication protocol

This document specifies a call between two separate agent tasks. The caller sends a prompt into the recipient's user-visible task. The user can open that task to inspect its visible messages, progress, tool activity, and final response. A transport may accept JSON directly or carry the same fields in a structured text prompt.

```text
caller task --prompt--> task messaging tool/adapter --> recipient task
user <---------------- open recipient task via real view reference
caller task <--receipt/status/result (same requestId)--- tool/adapter
caller task --acceptance checks--> verified outcome
```

The recipient task's native timeline is the source of live progress. The caller may relay a task reference and a final summary, but must not portray its own summary as the recipient's live transcript. Private internal reasoning and private logs are outside the user-visible process.

## Request

```json
{
  "protocol": "agent-call/v1",
  "kind": "request",
  "taskId": "parser-review",
  "attemptId": "1",
  "requestId": "parser-review-1-unique-id",
  "sender": "caller",
  "recipient": "review-agent",
  "recipientTaskRef": "existing-visible-review-task-id",
  "workspace": "/absolute/path/to/project",
  "objective": "Review the parser change for regressions.",
  "contextRefs": ["src/parser.py", "tests/test_parser.py"],
  "allowedActions": ["read files", "run relevant tests"],
  "acceptance": ["Report actionable findings with file and line references", "State which tests ran"]
}
```

`taskId` groups the overall task. `attemptId` identifies one authorized attempt. `requestId` identifies one delivery and must never be reused with different content. `recipientTaskRef` addresses an existing user-visible task. If the user requests a new task, the host may create it using the prompt as its initial message and then return its real task reference. The transport may also assign a native message ID; keep that mapping locally. `workspace` and `contextRefs` identify the material the recipient may use. `allowedActions` and `acceptance` express the task scope; an adapter or host must enforce actual access limits.

Keep credentials, private URLs, and unnecessary personal data out of the request. Store any private transport identity or full native transcript only in the appropriate local state, not in a public handoff artifact.

## Receipt and result

A receipt answers whether the transport accepted the request. It does not prove that the recipient completed the task.

```json
{
  "protocol": "agent-call/v1",
  "kind": "receipt",
  "taskId": "parser-review",
  "attemptId": "1",
  "requestId": "parser-review-1-unique-id",
  "delivery": "accepted",
  "nativeRef": "transport-specific-message-id",
  "recipientTaskRef": "existing-visible-review-task-id",
  "viewRef": "host-provided-user-openable-task-reference"
}
```

`delivery` is `accepted`, `rejected`, or `unknown`. On acceptance, return the real `recipientTaskRef` and a `viewRef` that the user can open through the host. Do not invent a URL or imply a background worker has a visible task. `unknown` means the call may have been delivered; reconcile it through native status or result lookup using the original identifiers. If the transport cannot query an uncertain call, stop and report the uncertainty instead of sending a new request.

```json
{
  "protocol": "agent-call/v1",
  "kind": "result",
  "taskId": "parser-review",
  "attemptId": "1",
  "requestId": "parser-review-1-unique-id",
  "agentOutcome": "completed",
  "summary": "Reviewed the parser change.",
  "artifacts": [{ "path": "src/parser.py", "description": "One finding at line 42" }],
  "checks": [{ "name": "parser tests", "status": "passed" }],
  "openIssues": []
}
```

`agentOutcome` is `completed`, `failed`, or `unknown`. A recipient's final message can fill the result fields, but only native task status or equivalent evidence establishes that its run ended. The caller's acceptance result is separate: `passed`, `failed`, or `not_run`. Do not report the task as verified from an `accepted` receipt or from the recipient's completion claim alone.

## Adapter responsibilities

An adapter needs three operations and a user-visible destination:

1. `send(request)` adds the prompt as a user-visible message in the recipient task, returns its real `recipientTaskRef` and `viewRef`, and preserves the `requestId` to native message ID mapping.
2. `status(recipientTaskRef, requestId)` reports that task's native run state without sending another prompt.
3. `collect(recipientTaskRef, requestId)` returns the correlated result or a reason it is unavailable.

The host must also let the user open the recipient task and view the progress it actually exposes. If the native tool returns only a final response or hides the worker, this visible-task mode is unavailable. If it is asynchronous, the caller should wait on that specific native task. An adapter may add cancellation, streaming, or quotas later; those are not required for this base.

On a retry, an adapter should recognize the same `requestId` and identical content when it can. Same ID with different content is a conflict. A transport that cannot guarantee idempotency must expose that limit; the caller reconciles the original call before retrying. Start a new attempt only after the previous attempt has a known terminal state.

## Shared workspace rule

Two agents may investigate in parallel, but simultaneous writes to the same files need explicit coordination. Give writers separate workspaces or an exclusive path owner. Before moving a task to another writer, establish whether the first agent can still write and preserve its partial result. This rule applies even when delivery or completion status is unknown.
