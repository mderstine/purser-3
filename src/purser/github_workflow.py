from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .github_sync import (
    GitHubStatusMirrorConfig,
    GitHubSyncConfig,
    GitHubSyncState,
    PublishedChildIssue,
    SynthesizedSpec,
    sync_timestamp,
)

SPEC_PATH_PATTERN = re.compile(r"spec path:\s*(?P<path>\S+)", re.IGNORECASE)


@dataclass(frozen=True)
class BeadsIssue:
    bead_id: str
    title: str
    description: str
    status: str
    priority: int
    issue_type: str


@dataclass(frozen=True)
class CreatedGitHubIssue:
    repo: str
    issue_number: int
    url: str
    issue_node_id: str | None = None


@dataclass(frozen=True)
class SynthSpecResult:
    source_key: str
    spec_path: str
    refreshed: bool


@dataclass(frozen=True)
class PublishResult:
    dry_run: bool
    source_key: str
    published: tuple[str, ...]
    skipped: tuple[str, ...]


@dataclass(frozen=True)
class StatusSyncResult:
    dry_run: bool
    child_updates: tuple[str, ...]
    parent_closures: tuple[str, ...]


class SupportsGhRun(Protocol):
    def run(self, args: list[str]) -> str: ...

    def run_json(self, args: list[str]) -> Any: ...


class SupportsBeadsInspect(Protocol):
    def run(self, args: list[str]) -> str: ...


class LocalBeadsClient:
    def __init__(self, cwd: Path, runner: SupportsBeadsInspect | None = None) -> None:
        self._cwd = cwd
        self._runner = runner or _BeadsRunner(cwd)

    def exported_issues(self) -> list[BeadsIssue]:
        stdout = self._runner.run(["export", "--no-memories"])
        issues: list[BeadsIssue] = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            issues.append(
                BeadsIssue(
                    bead_id=payload["id"],
                    title=payload["title"],
                    description=payload.get("description", ""),
                    status=payload["status"],
                    priority=int(payload.get("priority", 2)),
                    issue_type=payload.get("issue_type", "task"),
                )
            )
        return issues

    def issue_by_id(self, bead_id: str) -> BeadsIssue:
        payload = json.loads(self._runner.run(["show", bead_id, "--json"]))[0]
        return BeadsIssue(
            bead_id=payload["id"],
            title=payload["title"],
            description=payload.get("description", ""),
            status=payload["status"],
            priority=int(payload.get("priority", 2)),
            issue_type=payload.get("issue_type", "task"),
        )


class GitHubMirrorClient:
    def __init__(self, runner: SupportsGhRun) -> None:
        self._runner = runner

    def create_issue(
        self,
        repo: str,
        *,
        title: str,
        body: str,
        labels: tuple[str, ...],
    ) -> CreatedGitHubIssue:
        args = ["issue", "create", "--repo", repo, "--title", title, "--body", body]
        for label in labels:
            args.extend(["--label", label])
        url = self._runner.run(args).strip().splitlines()[-1]
        payload = self._runner.run_json(
            [
                "issue",
                "view",
                url,
                "--repo",
                repo,
                "--json",
                "id,number,url",
            ]
        )
        return CreatedGitHubIssue(
            repo=repo,
            issue_number=int(payload["number"]),
            url=payload["url"],
            issue_node_id=payload.get("id"),
        )

    def add_to_project(self, owner: str, project_number: int, url: str) -> str | None:
        payload = self._runner.run_json(
            [
                "project",
                "item-add",
                str(project_number),
                "--owner",
                owner,
                "--url",
                url,
                "--format",
                "json",
            ]
        )
        return payload.get("id")

    def comment_issue(self, repo: str, issue_number: int, body: str) -> None:
        self._runner.run(
            ["issue", "comment", str(issue_number), "--repo", repo, "--body", body]
        )

    def close_issue(self, repo: str, issue_number: int, comment: str | None = None) -> None:
        args = ["issue", "close", str(issue_number), "--repo", repo, "--reason", "completed"]
        if comment:
            args.extend(["--comment", comment])
        self._runner.run(args)

    def set_project_status(
        self,
        *,
        owner: str,
        project_number: int,
        item_id: str,
        field_name: str,
        option_name: str,
    ) -> None:
        fields = self._runner.run_json(
            [
                "project",
                "field-list",
                str(project_number),
                "--owner",
                owner,
                "--format",
                "json",
            ]
        )
        field = next(field for field in fields if field.get("name") == field_name)
        option = next(
            option for option in field.get("options", []) if option.get("name") == option_name
        )
        project_id = self._project_id(owner, project_number)
        self._runner.run(
            [
                "project",
                "item-edit",
                "--id",
                item_id,
                "--project-id",
                project_id,
                "--field-id",
                field["id"],
                "--single-select-option-id",
                option["id"],
            ]
        )

    def _project_id(self, owner: str, project_number: int) -> str:
        payload = self._runner.run_json(
            [
                "api",
                "graphql",
                "-f",
                "query=query($owner: String!, $number: Int!) { "
                "organization(login: $owner) { projectV2(number: $number) { id } } "
                "user(login: $owner) { projectV2(number: $number) { id } } }",
                "-f",
                f"owner={owner}",
                "-F",
                f"number={project_number}",
            ]
        )
        data = payload["data"]
        organization = data.get("organization") or {}
        if organization.get("projectV2"):
            return organization["projectV2"]["id"]
        user = data.get("user") or {}
        if user.get("projectV2"):
            return user["projectV2"]["id"]
        raise ValueError(f"unable to resolve GitHub Project id for {owner}#{project_number}")


class _BeadsRunner:
    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd

    def run(self, args: list[str]) -> str:
        completed = subprocess.run(
            ["bd", *args],
            cwd=self._cwd,
            check=True,
            text=True,
            capture_output=True,
        )
        return completed.stdout


def synthesize_github_spec(
    state: GitHubSyncState,
    source_key: str,
    *,
    root: Path,
    refresh: bool = False,
) -> SynthSpecResult:
    imported = state.imports.get(source_key)
    if imported is None:
        raise ValueError(f"unknown source key: {source_key}")

    existing = state.synthesized_specs.get(source_key)
    if existing and not refresh:
        raise ValueError(
            f"spec already synthesized for {source_key}: {existing.spec_path}. "
            "Use --refresh to replace it."
        )

    spec_path = root / (existing.spec_path if existing else default_spec_path(imported.title))
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(render_synthesized_spec(imported), encoding="utf-8")
    state.synthesized_specs[source_key] = SynthesizedSpec(
        source_key=source_key,
        spec_path=str(spec_path.relative_to(root)),
        title=imported.title or f"Spec for {source_key}",
        source_url=imported.url,
        synthesized_at=sync_timestamp(),
    )
    return SynthSpecResult(
        source_key=source_key,
        spec_path=str(spec_path.relative_to(root)),
        refreshed=bool(existing),
    )


def publish_github_plan(
    config: GitHubSyncConfig,
    state: GitHubSyncState,
    *,
    spec_path: str,
    beads: LocalBeadsClient,
    github: GitHubMirrorClient,
    dry_run: bool,
) -> PublishResult:
    if not config.publish.enabled:
        raise ValueError("GitHub publish is disabled in .purser/github-sync.json.")
    source_key = source_key_for_spec(state, spec_path)
    publish_config = config.publish
    repo = publish_config.repo or state.imports[source_key].repo
    issues = issues_for_spec(beads.exported_issues(), spec_path)
    published: list[str] = []
    skipped: list[str] = []

    for issue in issues:
        if issue.bead_id in state.published_children:
            skipped.append(issue.bead_id)
            continue
        published.append(issue.bead_id)
        if dry_run:
            continue
        created = github.create_issue(
            repo,
            title=issue.title,
            body=render_child_issue_body(issue, state.imports[source_key].url, spec_path),
            labels=publish_config.child_labels,
        )
        project_item_id: str | None = None
        if (
            publish_config.add_to_project
            and publish_config.project_owner
            and publish_config.project_number is not None
        ):
            project_item_id = github.add_to_project(
                publish_config.project_owner,
                publish_config.project_number,
                created.url,
            )
        state.published_children[issue.bead_id] = PublishedChildIssue(
            bead_id=issue.bead_id,
            parent_source_key=source_key,
            spec_path=spec_path,
            repo=created.repo,
            issue_number=created.issue_number,
            url=created.url,
            issue_node_id=created.issue_node_id,
            project_item_id=project_item_id,
            published_at=sync_timestamp(),
        )

    if (
        not dry_run
        and published
        and config.mirror.comment_on_publish
    ):
        imported = state.imports[source_key]
        github.comment_issue(
            imported.repo,
            imported.issue_number,
            f"Purser published {len(published)} child issue(s) from `{spec_path}`.",
        )

    return PublishResult(
        dry_run=dry_run,
        source_key=source_key,
        published=tuple(published),
        skipped=tuple(skipped),
    )


def sync_github_status(
    config: GitHubSyncConfig,
    state: GitHubSyncState,
    *,
    beads: LocalBeadsClient,
    github: GitHubMirrorClient,
    dry_run: bool,
) -> StatusSyncResult:
    if not config.mirror.enabled:
        return StatusSyncResult(dry_run=dry_run, child_updates=(), parent_closures=())
    child_updates: list[str] = []
    parent_closures: list[str] = []

    for bead_id, published in sorted(state.published_children.items()):
        issue = beads.issue_by_id(bead_id)
        child_updates.append(f"{bead_id}:{issue.status}")
        if dry_run:
            continue
        mirror_child_status(config, published, issue, github)

    if not dry_run and config.publish.parent_close_on_complete:
        for source_key in sorted(parent_source_keys(state)):
            if source_key in state.closed_parent_source_keys:
                continue
            children = [
                item
                for item in state.published_children.values()
                if item.parent_source_key == source_key
            ]
            if children and all(
                beads.issue_by_id(item.bead_id).status == "closed" for item in children
            ):
                imported = state.imports[source_key]
                comment = None
                if config.mirror.comment_on_parent_closed:
                    comment = (
                        "Purser closed this parent issue after all published child work "
                        "completed in Beads."
                    )
                github.close_issue(imported.repo, imported.issue_number, comment)
                state.closed_parent_source_keys.append(source_key)
                parent_closures.append(source_key)

    return StatusSyncResult(
        dry_run=dry_run,
        child_updates=tuple(child_updates),
        parent_closures=tuple(parent_closures),
    )


def mirror_child_status(
    config: GitHubSyncConfig,
    published: PublishedChildIssue,
    issue: BeadsIssue,
    github: GitHubMirrorClient,
) -> None:
    if published.project_item_id and config.publish.project_owner and config.publish.project_number:
        github.set_project_status(
            owner=config.publish.project_owner,
            project_number=config.publish.project_number,
            item_id=published.project_item_id,
            field_name=config.mirror.status_field,
            option_name=project_status_value(config.mirror, issue.status),
        )

    if issue.status == published.last_mirrored_status:
        return

    if issue.status == "blocked" and config.mirror.comment_on_blocked:
        github.comment_issue(
            published.repo,
            published.issue_number,
            f"Purser marked linked bead `{issue.bead_id}` as blocked in local Beads.",
        )
    elif issue.status == "closed" and config.mirror.comment_on_closed:
        github.close_issue(
            published.repo,
            published.issue_number,
            f"Purser completed linked bead `{issue.bead_id}` in local Beads.",
        )

    published.last_mirrored_status = issue.status


def project_status_value(config: GitHubStatusMirrorConfig, status: str) -> str:
    mapping = {
        "open": config.open_value,
        "in_progress": config.in_progress_value,
        "blocked": config.blocked_value,
        "closed": config.closed_value,
    }
    return mapping.get(status, config.open_value)


def source_key_for_spec(state: GitHubSyncState, spec_path: str) -> str:
    normalized = spec_path.strip()
    for source_key, spec in state.synthesized_specs.items():
        if spec.spec_path == normalized:
            return source_key
    raise ValueError(f"no synthesized GitHub spec recorded for {spec_path}")


def parent_source_keys(state: GitHubSyncState) -> set[str]:
    return {entry.parent_source_key for entry in state.published_children.values()}


def issues_for_spec(issues: list[BeadsIssue], spec_path: str) -> list[BeadsIssue]:
    normalized = spec_path.strip()
    return [issue for issue in issues if linked_spec_path(issue.description) == normalized]


def linked_spec_path(description: str) -> str | None:
    match = SPEC_PATH_PATTERN.search(description)
    if not match:
        return None
    return match.group("path")


def default_spec_path(title: str) -> Path:
    slug = slugify(title or "github-spec")
    return Path("specs") / f"{datetime.now(tz=UTC).date().isoformat()}-{slug}.md"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "github-spec"


def render_synthesized_spec(imported: Any) -> str:
    body = imported.body.strip() or "No GitHub body was provided."
    title = imported.title or f"Spec for {imported.repo}#{imported.issue_number}"
    return (
        "---\n"
        f"purser_source_key: {source_key_for_issue(imported.repo, imported.issue_number)}\n"
        f"purser_source_url: {imported.url}\n"
        f"purser_issue_repo: {imported.repo}\n"
        f"purser_issue_number: {imported.issue_number}\n"
        "---\n\n"
        f"# {title}\n\n"
        "## Summary\n\n"
        f"Synthesized from GitHub issue `{imported.repo}#{imported.issue_number}`.\n\n"
        "## Problem\n\n"
        f"{body}\n\n"
        "## Goals\n\n"
        "- Preserve the intent captured in the upstream GitHub issue.\n\n"
        "## Non-goals\n\n"
        "- Do not start implementation or create Beads as part of synthesis.\n\n"
        "## Users / stakeholders\n\n"
        "- Director\n"
        "- Project manager agent\n"
        "- Builder agent\n\n"
        "## Scope\n\n"
        "- Convert the GitHub parent issue into a reviewable local spec.\n\n"
        "## Functional requirements\n\n"
        "- Review and refine the synthesized content before planning.\n\n"
        "## Technical considerations\n\n"
        f"- Upstream source: {imported.url}\n\n"
        "## Verification strategy\n\n"
        "- Director review before planning.\n\n"
        "## Acceptance criteria\n\n"
        "- A local spec exists and preserves the upstream GitHub context.\n\n"
        "## Risks / unknowns\n\n"
        "- The source issue may omit implementation details.\n\n"
        "## Suggested milestones\n\n"
        "- Review the synthesized spec.\n"
        "- Approve it for planning.\n\n"
        "## Open questions\n\n"
        "- What constraints or acceptance details still need clarification?\n"
    )


def render_child_issue_body(issue: BeadsIssue, parent_url: str, spec_path: str) -> str:
    return (
        f"Parent issue: {parent_url}\n"
        f"Spec path: {spec_path}\n"
        f"Linked Bead: {issue.bead_id}\n\n"
        "Local Beads definition:\n\n"
        f"{issue.description.strip() or '(no description)'}\n"
    )


def format_publish_result(result: PublishResult) -> str:
    lines = [
        f"Dry run: {'yes' if result.dry_run else 'no'}",
        f"Parent source: {result.source_key}",
        f"Published child issues: {len(result.published)}",
        f"Skipped existing child issues: {len(result.skipped)}",
    ]
    if result.published:
        lines.append("Published bead ids:")
        lines.extend(f"- {bead_id}" for bead_id in result.published)
    if result.skipped:
        lines.append("Skipped bead ids:")
        lines.extend(f"- {bead_id}" for bead_id in result.skipped)
    return "\n".join(lines)


def format_status_sync_result(result: StatusSyncResult) -> str:
    lines = [
        f"Dry run: {'yes' if result.dry_run else 'no'}",
        f"Child updates inspected: {len(result.child_updates)}",
        f"Parent closures: {len(result.parent_closures)}",
    ]
    if result.child_updates:
        lines.append("Child bead states:")
        lines.extend(f"- {entry}" for entry in result.child_updates)
    if result.parent_closures:
        lines.append("Closed parent source keys:")
        lines.extend(f"- {entry}" for entry in result.parent_closures)
    return "\n".join(lines)


def source_key_for_issue(repo: str, issue_number: int) -> str:
    return f"issue:{repo}#{issue_number}"
