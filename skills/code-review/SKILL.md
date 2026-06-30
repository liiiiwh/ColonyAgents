---
name: code-review
description: Use when a task needs structured code review after implementation, especially for API changes, data model updates, database migrations, cross-module edits, service-side logic, auth, middleware, async jobs, or other medium/high-risk changes.
---

# Code Review

Use this skill after implementation when review is mandatory by `AGENTS.md` or when the user explicitly asks for review.

## Read first

Before reviewing, read only what is needed:

- changed files or current diff
- related `SPEC.md`
- related docs in `docs/`
- relevant `devlogs/` entry
- available validation or test results
- available requirement/API/test docs when present

## Review scope

Focus on the changed code and directly affected modules. Expand only when side effects are likely.

## Checklists

### General

Check these first:

- implementation matches requirement and current docs
- no obvious logic regression
- edge cases and error handling are covered
- change scope is controlled and not wider than required
- docs or tests that should move with the change are updated

### Service-side

When backend or service logic is touched, also check:

- API compatibility and contract drift
- database migration safety and rollback impact
- data consistency and transaction boundaries
- idempotency for retryable paths
- middleware, auth, and permission coverage
- async job, queue, scheduler, or side-effect chain impact
- timeout, memory, query, and throughput risks
- logging, error code, and observability gaps

## Output format

Use this structure:

### Findings
- `[P1] file/module`: issue description

### 风险点
- risk description

### 建议处理项
- recommended action

### 结论
- `pass`
- `pass with risk`
- `blocked`

## Severity guide

- `P0`: critical defect or unsafe release blocker
- `P1`: high-risk issue that should be fixed before merge/release
- `P2`: medium-risk issue or likely regression gap
- `P3`: low-risk improvement or cleanup item

## Decision rules

- Use `blocked` when there is clear correctness, compatibility, security, or data safety risk.
- Use `pass with risk` when the main path is acceptable but residual risk remains.
- Use `pass` when no blocking issue is found in the reviewed scope.

Keep the output concise. Prioritize concrete findings over broad commentary.
