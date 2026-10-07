# CLAUDE.md

Guardrails for this repo live in [`AGENTS.md`](AGENTS.md) — read that first,
it applies to you the same as any other agent. This file only holds
Claude-Code-specific notes that don't belong in the shared file.

## Claude-Code-specific

- No repo-specific slash commands or subagents are configured yet.
- If you use auto-memory or session memory features, project facts that
  are actually durable (a decided architecture, a fixed bug, a naming
  convention) belong in `AGENTS.md` or the relevant `docs/*.md` file, not
  left to persist only in a session-memory file another tool or another
  person's session won't see.
