# Add `bd init` To `purser init`

## Summary

Extend `purser init` so it initializes the repository's Beads/Dolt state as part of the same command instead of requiring a separate `bd init` step. The command should continue to scaffold Purser prompt artifacts, then ensure the Beads repository is initialized in the same target directory.

## Problem

Today, `purser init` only writes Purser scaffolding files such as `.purser/`, `.claude/`, `.github/prompts/`, and `specs/.gitkeep`. A newly initialized repo still requires a separate `bd init` invocation before the planning and builder workflows described by Purser can actually function. That split setup is awkward because Purser's workflow assumes Beads is available and backed by Dolt. It also creates avoidable failure modes where a repo appears initialized from Purser's perspective but is still unusable for `purser-plan` or builder execution.

## Goals

- Make `purser init` perform the Beads initialization required for Purser's workflow.
- Remove the need for users to run `bd init` manually during normal repository setup.
- Preserve `purser init` as the single entry point for bootstrapping a repo that intends to use Purser's spec, planning, and execution lifecycle.
- Define clear output and failure behavior when the Purser scaffold step or Beads step fails.

## Non-goals

- Replacing or reimplementing Beads initialization logic inside Purser.
- Changing Beads CLI behavior or Dolt server configuration semantics.
- Expanding `purser init` into a general environment bootstrap command beyond Purser and Beads setup.
- Changing the prompt catalog, planning rules, or builder workflow semantics outside of initialization wording that must reflect the new behavior.

## Users / stakeholders

- Directors and project managers setting up a new Purser-managed repository.
- Builder agents that depend on Beads being available after initialization.
- Maintainers of Purser CLI and documentation.

## Scope

In scope:

- Update the `purser init` command implementation so it runs Beads initialization after Purser scaffolding in the target repository.
- Define how `purser init` behaves when Beads is already initialized.
- Update user-facing documentation and generated README text that currently describes `purser init` as only scaffolding prompt artifacts.
- Update or add tests covering the new initialization behavior.

Out of scope:

- Automatic remote Dolt provisioning or custom server-host discovery.
- Interactive configuration flows beyond what `bd init` already provides.
- Migration tooling for repositories that were partially initialized in older versions, beyond making repeated `purser init` behavior explicit.

## Functional requirements

1. `purser init` must continue to scaffold the existing Purser files into the selected target path.
2. After scaffolding, `purser init` must invoke `bd init` against the same target repository so the repo is ready for Beads-backed planning and execution.
3. The command must treat Beads initialization as part of overall success. If `bd init` fails, `purser init` must exit non-zero.
4. Output from `purser init` must make it clear that both Purser scaffolding and Beads initialization were attempted, including enough surfaced output to diagnose failures.
5. Re-running `purser init` in a repository that is already initialized should behave predictably and not corrupt existing Purser or Beads state. The exact idempotency approach may follow existing `bd init` behavior, but it must be documented and covered by tests where practical.
6. The implementation must work for non-default targets passed to `purser init <target>`, not just the current directory.
7. Documentation that lists generated outputs or setup steps must be updated so it no longer implies that `bd init` is a separate mandatory step after `purser init`.

## Technical considerations

- The current `run_init()` implementation only calls `scaffold_repository()` and prints written paths. It will need a subprocess-based integration with `bd init`.
- The implementation should run `bd init` in the resolved target directory rather than assuming the current working directory.
- The CLI should avoid partially masking Beads stderr/stdout. Users need direct enough visibility to debug Dolt or Beads configuration failures.
- Existing `--force` behavior only applies to Purser-generated files. The spec does not require mapping `--force` onto `bd init` unless that behavior is explicitly supported and justified.
- Repeated initialization needs careful handling because Purser file generation is idempotent, while `bd init` may commit files, install hooks, or report an existing setup differently.
- Tests should avoid relying on a live Beads/Dolt backend where possible by mocking subprocess invocation and asserting call shape, exit handling, and path selection.

## Verification strategy

- Add or update unit tests around `run_init()` to verify:
  - Purser scaffolding runs before `bd init`.
  - `bd init` is invoked with the correct working directory for default and explicit targets.
  - non-zero `bd init` exit status propagates out of `purser init`.
  - user-visible output still includes scaffolded paths and Beads initialization context.
- Update tests for generated README content if the documented initialization flow changes.
- Run `uv run --group dev ruff check`.
- Run `uv run --group dev ty check`.
- Run `uv run --group dev pytest`.

## Acceptance criteria

- Running `uv run purser init` in a fresh repository leaves both Purser scaffolding and Beads initialization completed without requiring a second command.
- Running `uv run purser init <target>` initializes Beads in `<target>`, not in the caller's current directory.
- If `bd init` fails, `purser init` returns a non-zero exit code and the failure is visible to the user.
- README or generated framework documentation reflects that `purser init` bootstraps the repo for Beads-backed Purser workflows rather than only writing prompt files.
- Automated tests cover the new subprocess integration and failure propagation behavior.

## Risks / unknowns

- `bd init` may have interactive or environment-specific behavior that complicates non-interactive invocation in some repositories.
- Existing repositories with partially initialized Beads state may produce edge-case outputs that need normalization or clearer messaging.
- If `bd init` writes git commits or hooks unconditionally, repeated `purser init` runs may have side effects that need explicit documentation.

## Suggested milestones

1. Update `purser init` implementation to invoke `bd init` in the target directory and propagate failures.
2. Add tests for default-target, explicit-target, and failure-path behavior.
3. Update README and generated framework documentation to describe the new single-command initialization flow.
4. Validate the full verification suite and confirm the command works in a fresh repo.

## Open questions

- Should `purser init` detect an already initialized Beads repository and short-circuit with a friendlier message, or should it delegate entirely to `bd init` and surface its native output?
- Should `purser init` stream `bd init` output directly, or should it add a small Purser-prefixed status line before handing through subprocess output?
- Are there any Beads flags that should be exposed through `purser init`, or is the initial integration intentionally limited to the default `bd init` behavior?
