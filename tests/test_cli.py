from __future__ import annotations

from pathlib import Path

from purser.cli import build_parser, run_prompt
from purser.framework import (
    render_claude,
    render_codex,
    render_copilot,
    repository_readme,
    scaffold_repository,
)
from purser.templates import TEMPLATES


def test_parser_accepts_check_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["check"])
    assert args.command == "check"
    assert args.paths == ["src", "tests"]


def test_run_prompt_renders_codex_command(capsys) -> None:
    exit_code = run_prompt("purser-add-spec", "codex")
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Command alias: `/purser-add-spec`" in captured.out
    assert "purser-add-spec" in captured.out
    assert "Run `uv run purser prompt purser-add-spec --agent codex`" in captured.out
    assert "Do not start implementation or planning." in captured.out
    assert "hard stop after the spec file is written" in captured.out
    assert "explicit approval before `/purser-plan` is run" in captured.out


def test_run_prompt_renders_plan_approval_gate(capsys) -> None:
    exit_code = run_prompt("purser-plan", "copilot")
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Only run after the director has manually reviewed the spec" in captured.out
    assert "Do not implement code or edit product files" in captured.out


def test_scaffold_repository_writes_agent_files(tmp_path: Path) -> None:
    written = scaffold_repository(tmp_path, force=False)

    expected = {
        tmp_path / ".purser" / "README.md",
        tmp_path / ".purser" / "commands" / "purser-add-spec.md",
        tmp_path / ".claude" / "commands" / "purser-plan.md",
        tmp_path / ".github" / "prompts" / "purser-build.prompt.md",
        tmp_path / ".purser" / "codex" / "purser-build-all.md",
        tmp_path / "specs" / ".gitkeep",
    }

    assert expected.issubset(set(written))
    for path in expected:
        assert path.exists()


def test_agent_renderers_share_prompt_body() -> None:
    template = TEMPLATES["purser-plan"]

    rendered = (
        render_claude(template),
        render_copilot(template),
        render_codex(template),
    )

    for output in rendered:
        assert f"# {template.title}" in output
        assert f"Command alias: `/{template.name}`" in output
        assert template.body.strip() in output


def test_repository_readme_mentions_director_review_gate() -> None:
    readme = repository_readme()

    assert "then stop" in readme
    assert "The director manually reviews and may edit the spec." in readme
    assert "only after the director explicitly approves the spec for planning" in readme
    assert "generated prompt artifacts" in readme
