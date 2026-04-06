from __future__ import annotations

import re
from pathlib import Path

from .templates import TEMPLATES, PromptTemplate

CANONICAL_DIR = Path(".purser") / "commands"
CLAUDE_DIR = Path(".claude") / "commands"
COPILOT_DIR = Path(".github") / "prompts"
SPECS_DIR = Path("specs")
PURSER_AGENTS_BEGIN = "<!-- BEGIN PURSER SECTION -->"
PURSER_AGENTS_END = "<!-- END PURSER SECTION -->"


def render_canonical(template: PromptTemplate) -> str:
    return (
        f"# {template.name}\n\n"
        f"Purpose: {template.purpose}\n\n"
        f"{template.body.strip()}\n"
    )


def render_agent_prompt(template: PromptTemplate, usage: str) -> str:
    return (
        f"# {template.title}\n\n"
        f"Command alias: `/{template.name}`\n\n"
        f"{usage}\n\n"
        f"{template.body.strip()}\n"
    )


def render_claude(template: PromptTemplate) -> str:
    return render_agent_prompt(
        template,
        "Use this prompt as the body of the Claude slash command in "
        f"`{CLAUDE_DIR / f'{template.name}.md'}`.",
    )


def render_copilot(template: PromptTemplate) -> str:
    return render_agent_prompt(
        template,
        "Use this prompt file in VS Code GitHub Copilot Chat. The filename "
        "preserves the same alias as the Claude slash command even though "
        "Copilot uses prompt files rather than native slash commands.",
    )


def render_codex(template: PromptTemplate) -> str:
    return render_agent_prompt(
        template,
        "Codex does not provide repo-local slash commands. Run `uv run purser "
        f"prompt {template.name} --agent codex` to print this prompt, then "
        "paste or adapt it in your Codex session.",
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


def purser_agents_section() -> str:
    return f"""{PURSER_AGENTS_BEGIN}
## Purser Workflow

Purser manages repo-local workflow prompts and operator guidance:

- Run `purser list` to see the available workflow prompts.
- Use `purser-add-spec` to create or refine a spec in `specs/`, then stop for
  director review.
- Only run `purser-plan` after the director explicitly approves the spec for
  planning.
- Use `purser-build` for one actionable bead, or `purser-build-all` for a
  sequential Ralph loop.
- Review `.purser/README.md` for the generated prompt locations and the expected
  workflow.
- If `.purser/github-sync.json` exists, start with
  `purser sync-github --dry-run` before importing GitHub work into Beads.
{PURSER_AGENTS_END}
"""


def append_section(content: str, section: str) -> str:
    stripped = content.rstrip()
    if not stripped:
        return f"# Agent Instructions\n\n{section}"
    return f"{stripped}\n\n{section}"


def ensure_purser_agents_section(path: Path) -> bool:
    section = purser_agents_section().strip()
    if path.exists():
        original = path.read_text(encoding="utf-8")
    else:
        original = ""

    pattern = re.compile(
        rf"{re.escape(PURSER_AGENTS_BEGIN)}.*?{re.escape(PURSER_AGENTS_END)}",
        re.DOTALL,
    )
    if pattern.search(original):
        updated = pattern.sub(section, original, count=1)
    else:
        updated = append_section(original, section)
    if updated == original:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{updated.rstrip()}\n", encoding="utf-8")
    return True


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

Generated outputs:
- `purser init` creates repo-local prompt artifacts and scaffolding files.
- `purser init` appends a Purser-owned section to `AGENTS.md` without
  overwriting unrelated instructions.
- This repository keeps the source templates in `src/purser/` and does not
  check the generated prompt artifacts or fresh scaffolding outputs into the
  release package.

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
