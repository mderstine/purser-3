from __future__ import annotations

import argparse
import subprocess
from collections.abc import Callable
from pathlib import Path

from .framework import (
    get_template,
    render_canonical,
    render_claude,
    render_codex,
    render_copilot,
    scaffold_repository,
)
from .github_sync import (
    default_config_path,
    default_config_template,
    default_state_path,
    format_sync_outcome,
    run_sync,
)
from .templates import TEMPLATES, PromptTemplate

Renderer = Callable[[PromptTemplate], str]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="purser",
        description="Portable prompt framework for specs, Beads planning, and bead execution.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init",
        help="Scaffold the Purser prompt framework into a repo.",
    )
    init_parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Target repository path. Defaults to the current directory.",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite generated files.",
    )

    prompt_parser = subparsers.add_parser(
        "prompt",
        help="Print a prompt for a specific agent.",
    )
    prompt_parser.add_argument("name", choices=sorted(TEMPLATES))
    prompt_parser.add_argument(
        "--agent",
        choices=["canonical", "claude", "copilot", "codex"],
        default="codex",
        help="Prompt rendering target.",
    )

    subparsers.add_parser(
        "list",
        help="List available workflow prompt names.",
    )

    check_parser = subparsers.add_parser(
        "check",
        help="Run Ruff, Ty, pytest, and a compile pass through uv.",
    )
    check_parser.add_argument(
        "paths",
        nargs="*",
        default=["src", "tests"],
        help="Paths to verify. Defaults to `src tests`.",
    )

    sync_parser = subparsers.add_parser(
        "sync-github",
        help="Import tagged GitHub issues and project items into Beads.",
    )
    sync_parser.add_argument(
        "--config",
        default=default_config_path(),
        help="Path to the GitHub sync config JSON file.",
    )
    sync_parser.add_argument(
        "--state",
        default=default_state_path(),
        help="Path to the GitHub sync state JSON file.",
    )
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the sync result without mutating Beads or state.",
    )
    sync_parser.add_argument(
        "--print-config-template",
        action="store_true",
        help="Print a starter config template and exit.",
    )

    return parser


def run_init(target: str, force: bool) -> int:
    written = scaffold_repository(Path(target).resolve(), force=force)
    if written:
        for path in written:
            print(path)
    else:
        print("No files written.")
    return 0


def run_prompt(name: str, agent: str) -> int:
    template = get_template(name)
    renderers: dict[str, Renderer] = {
        "canonical": render_canonical,
        "claude": render_claude,
        "copilot": render_copilot,
        "codex": render_codex,
    }
    print(renderers[agent](template))
    return 0


def run_list() -> int:
    for name in sorted(TEMPLATES):
        print(name)
    return 0


def run_check(paths: list[str]) -> int:
    commands = [
        ["uv", "run", "--group", "dev", "ruff", "check", *paths],
        ["uv", "run", "--group", "dev", "ty", "check", *paths],
        ["uv", "run", "--group", "dev", "pytest"],
        ["uv", "run", "python", "-m", "compileall", *paths],
    ]
    for command in commands:
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def run_sync_github(
    config_path: str,
    state_path: str,
    *,
    dry_run: bool,
    print_config_template_only: bool,
) -> int:
    if print_config_template_only:
        print(default_config_template(), end="")
        return 0

    outcome = run_sync(Path(config_path), Path(state_path), dry_run=dry_run)
    print(format_sync_outcome(outcome))
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        return run_init(args.target, args.force)
    if args.command == "prompt":
        return run_prompt(args.name, args.agent)
    if args.command == "list":
        return run_list()
    if args.command == "check":
        return run_check(args.paths)
    if args.command == "sync-github":
        return run_sync_github(
            args.config,
            args.state,
            dry_run=args.dry_run,
            print_config_template_only=args.print_config_template,
        )

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
