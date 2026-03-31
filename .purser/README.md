# Purser Agent Framework

This repo uses one canonical prompt catalog and generates agent-specific entry points for:

- Claude slash commands in `.claude/commands/`
- VS Code GitHub Copilot prompt files in `.github/prompts/`
- Codex-friendly prompt files in `.purser/codex/`

Available workflows:
- `/purser-add-spec`
- `/purser-plan`
- `/purser-build`
- `/purser-build-all`

Recommended lifecycle:
1. Run `/purser-add-spec` with the director to create or refine a spec in `specs/`, then stop.
2. The director manually reviews and may edit the spec.
3. Run `/purser-plan` only after the director explicitly approves the spec for planning.
4. Run `/purser-build` for one bead at a time.
5. Run `/purser-build-all` when you want a single builder agent to keep
   looping until nothing actionable remains.

Verification backpressure:
- Use `uv run purser check` as the default verification path for framework changes.
- For Python work, expect `uv run --group dev ruff check`,
  `uv run --group dev ty check`, and `uv run --group dev pytest`
  before a bead is closed.

Canonical source of truth:
- Edit `.purser/commands/` if you want to customize the prompts for this repo.
- Re-run `purser init --force` to regenerate Claude, Copilot, and Codex
  variants from the bundled defaults.

Beads expectations:
- Use `bd create`, `bd update`, `bd ready`, `bd show`, and `bd close`.
- Keep dependencies explicit.
- Keep tasks atomic so a builder agent can safely execute one bead at a time.
