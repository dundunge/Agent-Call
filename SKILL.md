---
name: agent-call
description: Send a bounded prompt from one agent task to a separate user-visible agent task, then follow and verify its result. Use when a user wants to call another agent and inspect its work in its own task or conversation.
---

# Agent Call

Use a native task messaging tool or a configured adapter that exposes the recipient's own user-visible task. The user should be able to open that task and see its visible progress, tool activity, and final response. Internal reasoning or private logs are not part of that view.

## Call workflow

1. Identify an existing recipient task and the tool that can send it a message. Create a new visible task only when the user has requested that action and the host permits it. If no visible recipient task or transport is available, report the limitation and leave any prepared handoff marked **not sent**.
2. Write the prompt for one bounded work unit: objective, relevant context, workspace, allowed actions, expected output, and acceptance criteria. Keep the recipient's permissions within those already authorized for the task.
3. Give the call a stable `taskId` and a unique `requestId`. Send the prompt as a message visible in the recipient task once. Record the exact request, the transport receipt, and the real recipient task reference.
4. Give the user the recipient task's actual view link or host-supported task reference as soon as it is available. The recipient's visible task is the source for live progress; do not present a caller-side summary as its transcript.
5. Use native wait, status, or read operations to follow that same task. If delivery is uncertain, query the original request before any retry. Never assume a timeout means the recipient did nothing.
6. Match the final reply to the request. Inspect its artifacts and run the acceptance checks that the caller can perform. Report delivery, agent outcome, and caller verification separately.

For code changes, use an isolated workspace or one active writer per path. Do not assign another writer until the previous writer's state is known. If the recipient needs a change in scope or authority, obtain that through the normal task authorization path.

Read [the communication protocol](references/protocol.md) when implementing an adapter, formatting a handoff, reconciling an uncertain call, or interpreting a result.

For Antigravity Desktop, read [the native Sidecar route](references/antigravity.md). Its bridge can create a conversation in the configured project or send to an existing one. A configured Stop hook can collect terminal status and a response; without that hook, a dispatch receipt does not verify completion. Desktop visibility and live tool progress still require separate evidence. Do not treat a headless `agy` run as a visible native Desktop task.

For DeepSeek Harness Web, read [the native Web Session route](references/dsh-web.md). Use its current launch-token authentication and `session/create`, `session/prompt`, `session/follow`, and `session/page` to bind dispatch and result to the same user-visible Web Session. A separate headless DSH run is not proof that the currently open Web page is running that task.
