# ADR-017 · Platform agents are seeded up-front and bind the default model at runtime

Status: accepted
Date: 2026-06-16
Supersedes part of: [ADR-016](016-oss-onboarding-and-default-model.md)

## Context

ADR-016 made onboarding configure an LLM provider and pick default models, then ran a
"platform install" that seeded the Builder + workers. `seed_builder_project` resolved the
default model and **skipped seeding entirely if none was configured** (ADR-014: never
silently substitute a model). Consequences on a fresh platform:

- No agents exist until the user finishes onboarding. Entering the admin shows an empty
  Agents page with no Builder — confusing, and it couples "agents exist" to "an LLM is
  configured".
- `Agent.model_id` was a required FK, so an agent could not exist before a model did.

We want platform agents to **exist by default**, with onboarding reduced to just
"configure a provider + pick default models". Agents should use the platform default model
and simply not run while none is configured.

## Decision

1. **`agents.model_id` is nullable.** `NULL` means "use the platform default model".
2. **Platform agents seed at boot, unconditionally**, with `model_id = NULL`
   (`seed_builder_project` + `seed_worker_template_catalog` no longer gate on a model;
   `run_startup_seeds` always runs the platform bootstrap).
3. **Model resolution moves to runtime.** `build_agent_executor` resolves an agent's model
   via `_resolve_agent_model`: explicit `model_id` → else the platform default by kind
   (super → supervisor default, worker → agent default) → else raise
   `LLMNotConfiguredError`.
4. **No LLM ⇒ the agent doesn't run, gracefully.** The daemon skips the tick (logged, not
   an error); super chat returns a "configure an LLM first" message. No crash.
5. **`_is_platform_installed` now means "a default supervisor model is configured"** (i.e.
   onboarding is done), not "the Builder project exists". This still drives the onboarding
   modal — it pops until a default model is set — while agents exist regardless.

This is not silent model degradation (ADR-014 still holds): an agent with `NULL` binds the
**explicit** platform default, and refuses to run when there is none — it never quietly
swaps to a different model.

## Consequences

- Onboarding is two steps: add a provider, pick default models. No separate agent-install.
- The admin always sees the Builder + workers; they're idle until an LLM exists.
- Changing the platform default model immediately affects every `NULL`-bound agent (dynamic
  binding) instead of being frozen at seed time.
- Downgrade of the migration requires reassigning any `NULL` model_id rows first.
