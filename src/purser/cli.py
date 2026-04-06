from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from .framework import (
    ensure_purser_agents_section,
    get_template,
    render_canonical,
    render_claude,
    render_codex,
    render_copilot,
    scaffold_repository,
)
from .github_sync import (
    CONFIG_VERSION,
    BeadsClient,
    BeadsRunner,
    GhRunner,
    GitHubClient,
    GitHubSyncConfig,
    ProjectSource,
    RepoSource,
    SyncAuthority,
    default_config_path,
    default_config_template,
    default_state_path,
    format_sync_outcome,
    load_config,
    load_state,
    run_sync,
    save_state,
)
from .github_workflow import (
    GitHubMirrorClient,
    LocalBeadsClient,
    format_publish_result,
    format_status_sync_result,
    publish_github_plan,
    sync_github_status,
    synthesize_github_spec,
)
from .templates import TEMPLATES, PromptTemplate

Renderer = Callable[[PromptTemplate], str]
GITHUB_REMOTE_PATTERN = re.compile(
    r"(?:git@github\.com:|https://github\.com/)(?P<repo>[^/\s]+/[^/\s]+?)(?:\.git)?$"
)


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
    init_parser.add_argument(
        "--github",
        action="store_true",
        help="Optionally create `.purser/github-sync.json` from discovered or provided settings.",
    )
    init_parser.add_argument(
        "--github-repo",
        help="GitHub repo in `owner/repo` format. Defaults to the origin remote when available.",
    )
    init_parser.add_argument(
        "--github-label",
        dest="github_labels",
        action="append",
        default=None,
        help="Label selector for repo and project issue intake. Repeat to add more labels.",
    )
    init_parser.add_argument(
        "--github-project-owner",
        help="GitHub organization or user that owns the project.",
    )
    init_parser.add_argument(
        "--github-project-number",
        type=int,
        help="GitHub Project v2 number to include in the sync config.",
    )
    init_parser.add_argument(
        "--github-project-status",
        dest="github_project_statuses",
        action="append",
        default=None,
        help="Allowed project status value. Repeat to add more values.",
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

    synth_parser = subparsers.add_parser(
        "synth-gh-spec",
        help="Generate or refresh a local spec from an imported GitHub parent issue.",
    )
    synth_parser.add_argument(
        "source_key",
        help="Imported GitHub source key, for example issue:owner/repo#123.",
    )
    synth_parser.add_argument(
        "--state",
        default=default_state_path(),
        help="Path to the GitHub sync state JSON file.",
    )
    synth_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Replace an existing synthesized spec for the same source key.",
    )

    publish_parser = subparsers.add_parser(
        "publish-github",
        help="Publish planned Beads linked to a spec as GitHub child issues.",
    )
    publish_parser.add_argument(
        "spec_path",
        help="Repo-relative spec path, for example specs/2026-04-06-foo.md.",
    )
    publish_parser.add_argument(
        "--config",
        default=default_config_path(),
        help="Path to the GitHub sync config JSON file.",
    )
    publish_parser.add_argument(
        "--state",
        default=default_state_path(),
        help="Path to the GitHub sync state JSON file.",
    )
    publish_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview GitHub child issue publication without mutating GitHub or state.",
    )

    status_parser = subparsers.add_parser(
        "sync-status",
        help="Mirror local Beads execution state outward to published GitHub issues.",
    )
    status_parser.add_argument(
        "--config",
        default=default_config_path(),
        help="Path to the GitHub sync config JSON file.",
    )
    status_parser.add_argument(
        "--state",
        default=default_state_path(),
        help="Path to the GitHub sync state JSON file.",
    )
    status_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview status mirroring without mutating GitHub or state.",
    )

    return parser


def _run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _git_repo_root(target: Path) -> Path:
    completed = _run_command(
        ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
        cwd=target,
    )
    if completed.returncode == 0:
        return Path(completed.stdout.strip()).resolve()
    return target.resolve()


def _default_issue_prefix(root: Path) -> str:
    prefix = re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-")
    return prefix or "purser"


def _ensure_beads(root: Path) -> str:
    if shutil.which("bd") is None:
        raise RuntimeError("`bd` is not installed or not on PATH.")
    if shutil.which("dolt") is None:
        raise RuntimeError("`dolt` is not installed or not on PATH.")

    if (root / ".beads").exists():
        command = ["bd", "bootstrap"]
    else:
        command = ["bd", "init", "--skip-agents", "--prefix", _default_issue_prefix(root)]

    completed = _run_command(command, cwd=root)
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        detail = stderr or stdout or "unknown error"
        raise RuntimeError(f"{' '.join(command)!r} failed: {detail}")

    return completed.stdout.strip() or "Beads setup completed."


def _discover_github_repo(root: Path) -> str | None:
    completed = _run_command(
        ["git", "-C", str(root), "config", "--get", "remote.origin.url"],
        cwd=root,
    )
    if completed.returncode != 0:
        return None
    remote = completed.stdout.strip()
    match = GITHUB_REMOTE_PATTERN.search(remote)
    if not match:
        return None
    return match.group("repo")


def _prompt(question: str) -> str:
    return input(question).strip()


def _prompt_yes_no(question: str) -> bool:
    response = _prompt(question).lower()
    return response in {"y", "yes"}


def _normalize_labels(values: list[str] | None) -> tuple[str, ...]:
    labels = values or ["purser"]
    return tuple(dict.fromkeys(label.strip() for label in labels if label.strip()))


def _prompt_for_github_config(
    root: Path,
    *,
    github_repo: str | None,
    github_labels: list[str] | None,
    project_owner: str | None,
    project_number: int | None,
    project_statuses: list[str] | None,
) -> GitHubSyncConfig | None:
    repo = github_repo or _discover_github_repo(root)
    if repo is None and sys.stdin.isatty():
        entered = _prompt("GitHub repo for Purser sync (`owner/repo`, blank to skip): ")
        repo = entered or None

    include_project = project_number is not None
    if project_number is None and sys.stdin.isatty():
        include_project = _prompt_yes_no("Configure a GitHub Project sync source? [y/N]: ")

    if not repo and not include_project:
        return None

    labels = _normalize_labels(github_labels)
    sources: list[RepoSource | ProjectSource] = []
    if repo:
        sources.append(RepoSource(repo=repo, labels=labels))

    if include_project:
        resolved_project_owner = project_owner
        if resolved_project_owner is None and repo:
            resolved_project_owner = repo.split("/", 1)[0]
        if resolved_project_owner is None and sys.stdin.isatty():
            entered_owner = _prompt("GitHub Project owner: ")
            resolved_project_owner = entered_owner or None

        resolved_project_number = project_number
        if resolved_project_number is None and sys.stdin.isatty():
            entered_number = _prompt("GitHub Project number: ")
            resolved_project_number = int(entered_number) if entered_number else None

        resolved_statuses = project_statuses
        if not resolved_statuses and sys.stdin.isatty():
            entered_statuses = _prompt(
                "GitHub Project statuses (comma-separated, default `Ready,Todo`): "
            )
            if entered_statuses:
                resolved_statuses = [value.strip() for value in entered_statuses.split(",")]

        if resolved_project_owner is None or resolved_project_number is None:
            raise RuntimeError(
                "GitHub project configuration needs both an owner and project number."
            )

        sources.append(
            ProjectSource(
                owner=resolved_project_owner,
                number=resolved_project_number,
                status_field="Status",
                status_values=tuple(resolved_statuses or ["Ready", "Todo"]),
                labels=labels,
            )
        )

    if not sources:
        return None

    return GitHubSyncConfig(
        version=CONFIG_VERSION,
        selectors=tuple(sources),
        authority=SyncAuthority(),
    )


def _write_github_sync_config(root: Path, config: GitHubSyncConfig, *, force: bool) -> Path | None:
    path = root / default_config_path()
    if path.exists() and not force:
        return None

    payload = {
        "version": config.version,
        "authority": asdict(config.authority),
        "sources": [asdict(source) for source in config.selectors],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8")
    return path


def _resolve_repo_path(root: Path, path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return root / candidate


def run_init(
    target: str,
    force: bool,
    *,
    github: bool = False,
    github_repo: str | None = None,
    github_labels: list[str] | None = None,
    github_project_owner: str | None = None,
    github_project_number: int | None = None,
    github_project_statuses: list[str] | None = None,
) -> int:
    root = _git_repo_root(Path(target).resolve())
    written = scaffold_repository(root, force=force)
    beads_result = _ensure_beads(root)
    if ensure_purser_agents_section(root / "AGENTS.md"):
        written.append(root / "AGENTS.md")

    github_config_path: Path | None = None
    if github:
        config = _prompt_for_github_config(
            root,
            github_repo=github_repo,
            github_labels=github_labels,
            project_owner=github_project_owner,
            project_number=github_project_number,
            project_statuses=github_project_statuses,
        )
        if config is not None:
            github_config_path = _write_github_sync_config(root, config, force=force)
            if github_config_path is not None:
                written.append(github_config_path)

    if written:
        for path in written:
            print(path)
    else:
        print("No files written.")
    print(f"Initialized Purser in: {root}")
    print(beads_result)
    if github and github_config_path is None:
        config_path = root / default_config_path()
        if config_path.exists():
            print(f"Kept existing GitHub sync config: {config_path}")
        else:
            print("GitHub sync config skipped.")
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
    root: Path,
    config_path: str,
    state_path: str,
    *,
    dry_run: bool,
    print_config_template_only: bool,
) -> int:
    if print_config_template_only:
        print(default_config_template(), end="")
        return 0

    config = _resolve_repo_path(root, config_path)
    state = _resolve_repo_path(root, state_path)
    outcome = run_sync(
        config,
        state,
        dry_run=dry_run,
        github=GitHubClient(runner=GhRunner(root)),
        beads=BeadsClient(runner=BeadsRunner(root)),
    )
    print(format_sync_outcome(outcome))
    return 0


def run_synth_gh_spec(root: Path, source_key: str, state_path: str, *, refresh: bool) -> int:
    state_file = _resolve_repo_path(root, state_path)
    state = load_state(state_file)
    result = synthesize_github_spec(state, source_key, root=root, refresh=refresh)
    save_state(state_file, state)
    action = "Refreshed" if result.refreshed else "Created"
    print(f"{action} spec: {result.spec_path}")
    return 0


def run_publish_github(
    root: Path,
    spec_path: str,
    config_path: str,
    state_path: str,
    *,
    dry_run: bool,
) -> int:
    config_file = _resolve_repo_path(root, config_path)
    state_file = _resolve_repo_path(root, state_path)
    config = load_config(config_file)
    state = load_state(state_file)
    result = publish_github_plan(
        config,
        state,
        spec_path=spec_path,
        beads=LocalBeadsClient(root),
        github=GitHubMirrorClient(GhRunner(root)),
        dry_run=dry_run,
    )
    if not dry_run:
        save_state(state_file, state)
    print(format_publish_result(result))
    return 0


def run_sync_status(
    root: Path,
    config_path: str,
    state_path: str,
    *,
    dry_run: bool,
) -> int:
    config_file = _resolve_repo_path(root, config_path)
    state_file = _resolve_repo_path(root, state_path)
    config = load_config(config_file)
    state = load_state(state_file)
    result = sync_github_status(
        config,
        state,
        beads=LocalBeadsClient(root),
        github=GitHubMirrorClient(GhRunner(root)),
        dry_run=dry_run,
    )
    if not dry_run:
        save_state(state_file, state)
    print(format_status_sync_result(result))
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = _git_repo_root(Path(".").resolve())

    if args.command == "init":
        return run_init(
            args.target,
            args.force,
            github=args.github,
            github_repo=args.github_repo,
            github_labels=args.github_labels,
            github_project_owner=args.github_project_owner,
            github_project_number=args.github_project_number,
            github_project_statuses=args.github_project_statuses,
        )
    if args.command == "prompt":
        return run_prompt(args.name, args.agent)
    if args.command == "list":
        return run_list()
    if args.command == "check":
        return run_check(args.paths)
    if args.command == "sync-github":
        return run_sync_github(
            root,
            args.config,
            args.state,
            dry_run=args.dry_run,
            print_config_template_only=args.print_config_template,
        )
    if args.command == "synth-gh-spec":
        return run_synth_gh_spec(root, args.source_key, args.state, refresh=args.refresh)
    if args.command == "publish-github":
        return run_publish_github(
            root,
            args.spec_path,
            args.config,
            args.state,
            dry_run=args.dry_run,
        )
    if args.command == "sync-status":
        return run_sync_status(root, args.config, args.state, dry_run=args.dry_run)

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
