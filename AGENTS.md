# Repository Development Instructions

These instructions apply to the entire repository. Follow them for every code,
configuration, test, documentation, and maintenance change.

## Project Goals

- Build a reliable, maintainable AI service intelligence API.
- Prefer small, reviewable changes with clear behavior and explicit tests.
- Keep the service runnable locally and suitable for later production deployment.
- Do not introduce a framework, external service, or architectural layer without a
  concrete requirement.

## Before Making Changes

1. Read `README.md`, `CHANGELOG.md`, and relevant files under `docs/`.
2. Inspect the current implementation and tests before editing.
3. Preserve unrelated user changes and avoid broad mechanical rewrites.
4. Clarify only decisions that materially affect product behavior, data, security,
   compatibility, or external integrations. Make conservative assumptions otherwise.

## Architecture and Code

- Application code belongs under `src/loreal_ai_service_intelligence/`.
- Tests belong under `tests/` and should mirror the source structure where practical.
- Keep API routes thin. Put business logic in focused modules with clear interfaces.
- Use type hints for public functions and non-obvious internal functions.
- Prefer explicit data models and dependency injection over global mutable state.
- Centralize environment-backed settings in `config.py`; never hard-code credentials,
  tokens, private endpoints, or environment-specific secrets.
- Add new dependencies only when the standard library or existing dependencies are
  insufficient. Record the dependency in `pyproject.toml` with a bounded version range.
- Maintain backward compatibility for published API contracts unless the requirement
  explicitly calls for a breaking change.

## API Requirements

- Validate request and response data with typed models.
- Return consistent, actionable errors without leaking secrets or internal traces.
- Keep health endpoints lightweight and independent of optional external services.
- Document new or changed endpoints, inputs, outputs, error cases, and configuration.
- For breaking API changes, include a migration note in `docs/` and mark the entry as
  `Changed` or `Removed` in `CHANGELOG.md`.

## AI and Data Requirements

- Keep model/provider integrations behind an interface so they can be replaced or
  mocked in tests.
- Make prompts, model names, timeouts, retry limits, and sampling settings explicit.
- Do not log raw secrets, credentials, or sensitive user content.
- Treat model output as untrusted input: validate it before persistence or tool use.
- Add deterministic unit tests around parsing, routing, validation, and fallback logic.
- When behavior depends on a nondeterministic model, mock the provider in automated
  tests and document the evaluation method separately.

## Tests and Verification

- Every behavior change requires tests covering the happy path and relevant failures.
- Every bug fix requires a regression test that fails without the fix.
- Run these checks before considering work complete:

  ```bash
  .venv/bin/ruff check .
  .venv/bin/ruff format --check .
  .venv/bin/pytest
  ```

- If a check cannot run, state exactly which check was skipped and why.
- Do not weaken, delete, or skip tests merely to make a change pass.

## Documentation (`docs/`)

- Update documentation in the same change as the code it describes.
- Keep `README.md` focused on project purpose, quick start, core commands, and links.
- Put detailed architecture, API behavior, operations, integrations, decisions, and
  migration guidance under `docs/`.
- Create or update a focused Markdown document for any feature that introduces:
  - a new user-visible workflow or API;
  - a new environment variable or external dependency;
  - an architectural or operational decision;
  - a deployment, migration, privacy, or security consideration.
- Use relative links between repository documents and verify they remain valid.
- Code examples must match the current public API and should be runnable when practical.

## Changelog (`CHANGELOG.md`)

- Update `CHANGELOG.md` for every user-visible, API, configuration, dependency,
  operational, security, or compatibility change.
- Add new entries under `[Unreleased]` using Keep a Changelog categories:
  `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, or `Security`.
- Write entries from the user's perspective and state impact, not implementation trivia.
- Do not add changelog entries for formatting-only edits or internal refactors with no
  observable impact.
- When releasing, move unreleased entries into a dated semantic-version section and
  create a fresh `[Unreleased]` section.

## Security and Privacy

- Store local secrets only in `.env`; keep `.env.example` limited to safe placeholders.
- Never commit API keys, access tokens, customer data, generated credentials, or private
  model inputs/outputs.
- Validate external input and use explicit timeouts for network calls.
- Minimize data collection and retention. Document any sensitive data flow under
  `docs/` before implementation.

## Completion Criteria

A change is complete only when:

1. The requested behavior is implemented without unrelated scope expansion.
2. Tests cover the change and all required checks pass.
3. `README.md` and/or `docs/` reflect the current behavior where relevant.
4. `CHANGELOG.md` contains an `[Unreleased]` entry when the change is observable.
5. No secrets, build artifacts, caches, or unrelated workspace files are staged.
6. The final handoff summarizes behavior, verification, documentation, and any remaining
   risks or follow-up work.
