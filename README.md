# Agent Call

[中文图解](README.zh-CN.md)

A small Codex skill for sending a bounded prompt from one agent task to another, user-visible agent task. The user can open the recipient task to follow its visible work. It is independent of model names, subscriptions, and provider APIs.

## What is included

- [`SKILL.md`](SKILL.md): instructions used when calling another agent.
- [`references/protocol.md`](references/protocol.md): message fields, delivery semantics, and an example exchange.
- [`references/antigravity.md`](references/antigravity.md): a concrete bridge for creating or messaging an Antigravity Desktop conversation.
- [`references/dsh-web.md`](references/dsh-web.md): a DSH Web bridge that creates a native visible session, sends a prompt, and collects its result.

The skill uses a task messaging tool or adapter already available to the host. The recipient must have a real task reference that the user can open. A background-only worker does not provide this experience. If no supported route is available, the skill can prepare a handoff message but must say that delivery has not occurred.

## Basic use

Place the `agent-call` folder in a Codex skills directory, then ask Codex to use `$agent-call` for a specific task and recipient. For example:

> Use `$agent-call` to send the parser review prompt to my review task. Give me its task link so I can watch its work, then report its findings and what you verified.

The caller sends the prompt to the recipient task, exposes that task's real view reference to the user, follows its status, and checks the final result against the original task. The recipient's task shows its own visible messages, tool activity, and output; it does not expose private internal reasoning.

## Scope

This is a coordination base, not a universal agent runtime. A complete adapter must implement task messaging, a user-openable task reference, status, and result collection. The Antigravity example implements conversation creation and messaging; an optional Stop hook captures terminal status and the final visible reply. The DSH Web example uses the native Web Host's session API. Codex-side live tool progress and visual confirmation in the user's open browser still need independent verification. A manual handoff remains pending until an agent actually receives it.
