from __future__ import annotations

from pathlib import Path

from .templates import TEMPLATES, PromptTemplate

CANONICAL_DIR = Path(".purser") / "commands"
CLAUDE_DIR = Path(".claude") / "commands"
COPILOT_DIR = Path(".github") / "prompts"
SPECS_DIR = Path("specs")


def render_canonical(template: PromptTemplate) -> str:
    return (
        f"# {template.name}\n\n"
        f"Purpose: {template.purpose}\n\n"
        f"{template.body.strip()}\n"
    )


def render_claude(template: PromptTemplate) -> str:
    return (
        f"# /{template.name}\n\n"
        "Use this Claude slash command to run the prompt below.\n\n"
        f"{template.body.strip()}\n"
    )


def render_copilot(template: PromptTemplate) -> str:
    return (
        f"# {template.title}\n\n"
        f"Command alias: `/{template.name}`\n\n"
        "Use this prompt file in VS Code GitHub Copilot Chat. The filename "
        "preserves the same alias as the Claude slash command even though "
        "Copilot uses prompt files rather than native slash commands.\n\n"
        f"{template.body.strip()}\n"
    )


def render_codex(template: PromptTemplate) -> str:
    return (
        f"# {template.title}\n\n"
        "Codex does not provide repo-local slash commands. Use `purser prompt "
        f"{template.name} --agent codex` to print this prompt, then paste or "
        "adapt it in your Codex session.\n\n"
        f"{template.body.strip()}\n"
    )


def write_file(path: Path, content: str, force: bool) -> None:
    if path.exists() and not force:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def scaffold_repository(target: Path, force: bool = False) -> list[Path]:
    written: list[Path] = []
    write_targets = [
        (
            target / ".purser" / "README.md",
            repository_readme(),
        ),
        (
            target / "specs" / ".gitkeep",
            "",
        ),
    ]

    for path, content in write_targets:
        if not path.exists() or force:
            write_file(path, content, force=force)
            written.append(path)

    for name, template in TEMPLATES.items():
        variants = {
            target / CANONICAL_DIR / f"{name}.md": render_canonical(template),
            target / CLAUDE_DIR / f"{name}.md": render_claude(template),
            target / COPILOT_DIR / f"{name}.prompt.md": render_copilot(template),
            target / ".purser" / "codex" / f"{name}.md": render_codex(template),
        }
        for path, content in variants.items():
            if not path.exists() or force:
                write_file(path, content, force=force)
                written.append(path)

    return written


def repository_readme() -> str:
    command_list = "\n".join(f"- `/{name}`" for name in TEMPLATES)
    return f"""# Purser Agent Framework

This repo uses one canonical prompt catalog and generates agent-specific entry points for:

- Claude slash commands in `.claude/commands/`
- VS Code GitHub Copilot prompt files in `.github/prompts/`
- Codex-friendly prompt files in `.purser/codex/`

Available workflows:
{command_list}

Recommended lifecycle:
1. Run `/{'purser-add-spec'}` with the director to create or refine a spec in `specs/`, then stop.
2. The director manually reviews and may edit the spec.
3. Run `/{'purser-plan'}` only after the director explicitly approves the spec for planning.
4. Run `/{'purser-build'}` for one bead at a time.
5. Run `/{'purser-build-all'}` when you want a single builder agent to keep
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
"""


def get_template(name: str) -> PromptTemplate:
    try:
        return TEMPLATES[name]
    except KeyError as exc:
        raise KeyError(f"unknown prompt: {name}") from exc
