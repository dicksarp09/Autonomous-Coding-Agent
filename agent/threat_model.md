# Threat Model for Autonomous Coding Agent

## Agent Boundary

The agent's technical capabilities (enforced):

- Read: local project directory (workspace root only).
- Write: local project directory only.
- Execute: Python code in sandbox (subprocess) with time/memory limits.
- Run: pytest inside workspace only.
- Store: memory in local vector DB / SQLite metadata.
- Log: telemetry events to local telemetry/tracing.
- Retrieve: internal knowledge base (local storage).

The agent cannot (enforced):

- Access external network (network disabled via sandbox env and no network-capable tools allowed).
- Access system files outside workspace (path checks on all tools).
- Execute arbitrary shell outside sandbox (sandbox blocks subprocess calls inside executed code to the extent possible).
- Read secrets from environment unless explicitly provided (secrets are environment variables and not accessible by default tools).
- Call arbitrary external APIs (tools and LLM client require API keys and explicit env configuration).

## Primary Risk: Confused Deputy

Description:

If a user requests code changes and simultaneously asks the agent to access sensitive files (e.g., "Also print /etc/passwd"), the agent could become a confused deputy: the agent has read/write capabilities the user does not.

Why this is dangerous:

- The agent runs with the user's filesystem privileges and could expose or modify files not intended by the user.
- An LLM could be tricked into causing the agent to read or write sensitive files via prompt injection.

Mitigations implemented:

- Input filtering layer: every tool validates inputs (path checks, forbidden patterns).
- Deny list patterns: static analysis rejects dangerous imports/calls (socket, requests, subprocess, eval, exec).
- Semantic classification placeholder: `rbac.enforce_role` and input validators must be called before LLM invocation.
- Explicit validation before LLM invocation: orchestration code and tools verify requested actions are inside workspace.
- Circuit breakers and explicit stop conditions in orchestration to avoid runaway actions.

Security is enforced outside of LLM reasoning by code-level checks; LLM output cannot bypass these checks.

## Tools the agent can invoke

- write_file
- read_file
- run_tests
- execute_python
- static_analysis
- store_memory
- retrieve_memory

All tools require path validation and RBAC checks before performing privileged actions.

## Sensitive Surfaces

- File writes: must be contained to workspace; audited in `audit_logs`.
- Code execution: sandboxed with timeout and memory limits; static analysis required before execution.
- Memory storage: long-term memory stored with metadata and signatures; access is validated.
- Long-term retrieval: returned data is sanitized and validated, with RBAC enforcement.

## Attack Vectors and Mitigations

1. Prompt injection in test output

   - Risk: Malicious test output crafted to inject prompts that influence future LLM calls.
   - Mitigation: All outputs are treated as data, parsed by tool contracts; static checks and sanitization applied before storing or using outputs. Memory writes require RBAC verification.

2. Malicious code generation

   - Risk: LLM generates code that exfiltrates data or performs unauthorized operations.
   - Mitigation: Static analysis (AST checks, bandit/ruff) runs before execution and will reject dangerous constructs (eval, exec, socket, requests, subprocess). Execution only occurs in sandbox.

3. Memory poisoning / retrieval contamination

   - Risk: Adversarial content stored in long-term memory could mislead future generations.
   - Mitigation: Every memory store/read enforces RBAC; long-term entries include signatures and metadata; retrieval is limited and audited.

4. Infinite loop / cost explosion

   - Risk: Repeated LLM calls or long-running executions could incur high cost or compute use.
   - Mitigation: Orchestration enforces iteration caps, circuit breakers, and timeouts for all subprocesses; telemetry monitors token and latency usage per workflow.

## Enforcement Layers in Code

- Input validation: `tools/*` modules validate paths, types, and ranges using Pydantic v2 and explicit path checks.
- RBAC: `rbac.py` provides `enforce_role` and `require_role` to check permissions before operations.
- Static analysis: `tools/static_analysis.py` runs AST checks and optionally runs `bandit` and `ruff`.
- Sandbox: `sandbox.py` runs code with timeout and memory limits, and disables network via environment.
- Audit logging and DB: `agent/db.py` creates `audit_logs` and workflow tables for tamper-evident records.

## Notes and Operational Security

- No global writable secrets: API keys are read from environment variables.
- No global mutable state: short-term memory instances should be session-scoped; module-level state is minimized.
- Every failure is logged and returned as structured error; silent failures are disallowed.
