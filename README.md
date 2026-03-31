# Purser

Purser is a portable agent-workflow scaffold for three roles:

- The director works with a project manager agent to produce spec markdown files.
- The project manager agent decomposes approved specs into atomic Beads issues/tasks.
- The builder agent executes one bead at a time or runs a full Ralph loop until no actionable beads remain.

The framework keeps one canonical prompt catalog and emits agent-specific entry points for:

- Claude slash commands
- VS Code GitHub Copilot prompt files
- Codex prompt rendering through the `purser` CLI

## Install

```bash
uv sync --group dev
uv run purser init
```

That scaffolds these repo-local files:

- `.purser/commands/*.md`
- `.purser/codex/*.md`
- `.claude/commands/*.md`
- `.github/prompts/*.prompt.md`
- `specs/.gitkeep`
- `.purser/README.md`

## Commands

```bash
uv run purser list
uv run purser prompt purser-add-spec --agent codex
uv run purser init --force
uv run purser check
uv run python -m purser.cli list
```

Available workflows:

- `purser-add-spec`: project manager prompt for creating a detailed spec in `specs/`
- `purser-plan`: project manager prompt for turning director-approved specs into Beads with dependencies
- `purser-build`: builder prompt for exactly one actionable bead
- `purser-build-all`: builder prompt for a sequential Ralph loop over all actionable beads

## Cross-agent behavior

Claude and Copilot get repo-local prompt files with the same base command names. Codex does not support repo-local slash commands, so the portable fallback is:

```bash
uv run purser prompt purser-add-spec --agent codex
```

That prints the Codex-ready version of the prompt so it can be pasted into the active session.

## Verification

This repo is intended to be managed through `uv`, and the framework treats static analysis and tests as required backpressure:

```bash
uv run purser check
```

That runs:

- `uv run --group dev ruff check`
- `uv run --group dev ty check`
- `uv run --group dev pytest`
- `uv run python -m compileall`

## Beads workflow

The generated prompts assume Steve Yegge's Beads CLI is available in the repo environment and that agents can use:

- `bd create`
- `bd update`
- `bd ready`
- `bd show`
- `bd close`

The planning prompt explicitly requires atomic beads with explicit dependencies so the builder can safely work one bead at a time.

## Director Approval Gates

The intended lifecycle is strict:

1. Run `purser-add-spec` to create or refine a spec file only.
2. Stop for director review and manual edits.
3. Run `purser-plan` only after the director explicitly approves the spec for planning.
4. Run builder workflows only after planning has produced atomic beads.
