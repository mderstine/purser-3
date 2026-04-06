from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

CONFIG_VERSION = 1
STATE_VERSION = 1
DEFAULT_CONFIG_PATH = Path(".purser") / "github-sync.json"
DEFAULT_STATE_PATH = Path(".purser") / "github-sync-state.json"
BEAD_ID_PATTERN = re.compile(r"Created issue: (\S+)")

PROJECT_ITEMS_QUERY = """
query($owner: String!, $number: Int!, $cursor: String) {
  organization(login: $owner) {
    projectV2(number: $number) {
      items(first: 100, after: $cursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field {
                  ... on ProjectV2FieldCommon {
                    name
                  }
                }
              }
            }
          }
          content {
            ... on Issue {
              id
              number
              title
              body
              url
              state
              parent {
                ... on Issue {
                  number
                  repository {
                    nameWithOwner
                  }
                }
              }
              subIssues(first: 20) {
                nodes {
                  number
                  repository {
                    nameWithOwner
                  }
                }
              }
              repository {
                nameWithOwner
              }
              labels(first: 20) {
                nodes {
                  name
                }
              }
            }
          }
        }
      }
    }
  }
  user(login: $owner) {
    projectV2(number: $number) {
      items(first: 100, after: $cursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field {
                  ... on ProjectV2FieldCommon {
                    name
                  }
                }
              }
            }
          }
          content {
            ... on Issue {
              id
              number
              title
              body
              url
              state
              repository {
                nameWithOwner
              }
              labels(first: 20) {
                nodes {
                  name
                }
              }
            }
          }
        }
      }
    }
  }
}
""".strip()


@dataclass(frozen=True)
class RepoSource:
    repo: str
    labels: tuple[str, ...]
    state: str = "open"
    kind: str = "repo"


@dataclass(frozen=True)
class ProjectSource:
    owner: str
    number: int
    status_field: str
    status_values: tuple[str, ...]
    labels: tuple[str, ...] = ()
    issue_backed_only: bool = True
    kind: str = "project"


@dataclass(frozen=True)
class SyncAuthority:
    github_import_fields: tuple[str, ...] = (
        "source identity",
        "source url",
        "source title snapshot",
        "source body snapshot",
        "source state snapshot",
        "project selector match",
    )
    local_bead_fields: tuple[str, ...] = (
        "bead id",
        "bead lifecycle state",
        "local dependency edges",
        "execution notes",
    )


@dataclass(frozen=True)
class GitHubSyncConfig:
    version: int
    selectors: tuple[RepoSource | ProjectSource, ...]
    authority: SyncAuthority = field(default_factory=SyncAuthority)


@dataclass(frozen=True)
class GitHubRelationship:
    kind: str
    target_key: str


@dataclass(frozen=True)
class GitHubSourceItem:
    source_key: str
    source_kind: str
    repo: str
    issue_number: int
    title: str
    body: str
    url: str
    state: str
    labels: tuple[str, ...]
    issue_node_id: str | None = None
    project_owner: str | None = None
    project_number: int | None = None
    project_item_id: str | None = None
    project_status: str | None = None
    relationships: tuple[GitHubRelationship, ...] = ()


@dataclass
class ImportedBead:
    bead_id: str
    source_kind: str
    repo: str
    issue_number: int
    url: str
    issue_node_id: str | None = None
    project_item_ids: list[str] = field(default_factory=list)
    parent_keys: list[str] = field(default_factory=list)
    child_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PendingDependency:
    bead_id: str
    depends_on_key: str
    source_key: str


@dataclass(frozen=True)
class RecordedHierarchy:
    kind: str
    source_key: str
    target_key: str


@dataclass
class GitHubSyncState:
    version: int = STATE_VERSION
    imports: dict[str, ImportedBead] = field(default_factory=dict)
    pending_dependencies: list[PendingDependency] = field(default_factory=list)
    applied_dependencies: list[str] = field(default_factory=list)
    recorded_hierarchy: list[RecordedHierarchy] = field(default_factory=list)


@dataclass(frozen=True)
class SyncOutcome:
    dry_run: bool
    created: tuple[str, ...]
    skipped: tuple[str, ...]
    dependencies_added: tuple[str, ...]
    pending_dependencies: tuple[str, ...]
    recorded_hierarchy: tuple[str, ...]


def source_key_for_issue(repo: str, issue_number: int) -> str:
    return f"issue:{repo}#{issue_number}"


def default_config_path() -> str:
    return str(DEFAULT_CONFIG_PATH)


def default_state_path() -> str:
    return str(DEFAULT_STATE_PATH)


def load_config(path: Path) -> GitHubSyncConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    version = int(raw.get("version", CONFIG_VERSION))
    selectors: list[RepoSource | ProjectSource] = []
    for source in raw.get("sources", []):
        kind = source["kind"]
        if kind == "repo":
            selectors.append(
                RepoSource(
                    repo=source["repo"],
                    labels=tuple(source.get("labels", [])),
                    state=source.get("state", "open"),
                )
            )
            continue
        if kind == "project":
            selectors.append(
                ProjectSource(
                    owner=source["owner"],
                    number=int(source["number"]),
                    status_field=source.get("status_field", "Status"),
                    status_values=tuple(source.get("status_values", [])),
                    labels=tuple(source.get("labels", [])),
                    issue_backed_only=bool(source.get("issue_backed_only", True)),
                )
            )
            continue
        raise ValueError(f"unsupported GitHub sync source kind: {kind}")

    authority = raw.get("authority", {})
    return GitHubSyncConfig(
        version=version,
        selectors=tuple(selectors),
        authority=SyncAuthority(
            github_import_fields=tuple(
                authority.get("github_import_fields", SyncAuthority().github_import_fields)
            ),
            local_bead_fields=tuple(
                authority.get("local_bead_fields", SyncAuthority().local_bead_fields)
            ),
        ),
    )


def load_state(path: Path) -> GitHubSyncState:
    if not path.exists():
        return GitHubSyncState()
    raw = json.loads(path.read_text(encoding="utf-8"))
    imports = {
        source_key: ImportedBead(**entry)
        for source_key, entry in raw.get("imports", {}).items()
    }
    pending_dependencies = [
        PendingDependency(**entry) for entry in raw.get("pending_dependencies", [])
    ]
    recorded_hierarchy = [
        RecordedHierarchy(**entry) for entry in raw.get("recorded_hierarchy", [])
    ]
    return GitHubSyncState(
        version=int(raw.get("version", STATE_VERSION)),
        imports=imports,
        pending_dependencies=pending_dependencies,
        applied_dependencies=list(raw.get("applied_dependencies", [])),
        recorded_hierarchy=recorded_hierarchy,
    )


def save_state(path: Path, state: GitHubSyncState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": state.version,
        "imports": {
            source_key: asdict(imported) for source_key, imported in sorted(state.imports.items())
        },
        "pending_dependencies": [asdict(entry) for entry in state.pending_dependencies],
        "applied_dependencies": sorted(state.applied_dependencies),
        "recorded_hierarchy": [asdict(entry) for entry in state.recorded_hierarchy],
    }
    path.write_text(f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8")


class GitHubClient:
    def __init__(self, runner: GhRunner | None = None) -> None:
        self._runner = runner or GhRunner()

    def fetch_items(self, config: GitHubSyncConfig) -> list[GitHubSourceItem]:
        normalized: dict[str, GitHubSourceItem] = {}
        for selector in config.selectors:
            if isinstance(selector, RepoSource):
                items = self._fetch_repo_source(selector)
            else:
                items = self._fetch_project_source(selector)
            for item in items:
                normalized[item.source_key] = merge_source_items(
                    normalized.get(item.source_key),
                    item,
                )
        return sorted(normalized.values(), key=lambda item: item.source_key)

    def _fetch_repo_source(self, selector: RepoSource) -> list[GitHubSourceItem]:
        args = [
            "issue",
            "list",
            "--repo",
            selector.repo,
            "--state",
            selector.state,
            "--limit",
            "100",
            "--json",
            "id,number,title,body,url,state,labels",
        ]
        if selector.labels:
            args.extend(["--label", ",".join(selector.labels)])
        payload = self._runner.run_json(args)
        return [normalize_repo_issue(issue, selector) for issue in payload]

    def _fetch_project_source(self, selector: ProjectSource) -> list[GitHubSourceItem]:
        cursor: str | None = None
        items: list[GitHubSourceItem] = []
        while True:
            payload = self._runner.run_json(
                [
                    "api",
                    "graphql",
                    "-f",
                    f"query={PROJECT_ITEMS_QUERY}",
                    "-f",
                    f"owner={selector.owner}",
                    "-F",
                    f"number={selector.number}",
                    "-f",
                    f"cursor={cursor or ''}",
                ]
            )
            project = project_payload(payload)
            item_page = project["items"]
            items.extend(normalize_project_items(item_page["nodes"], selector))
            page_info = item_page["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            cursor = page_info["endCursor"]
        return items


class GhRunner:
    def run_json(self, args: list[str]) -> Any:
        command = ["gh", *args]
        completed = subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=True,
        )
        return json.loads(completed.stdout)


class SupportsBeadsRun(Protocol):
    def run(self, args: list[str]) -> str: ...


class BeadsClient:
    def __init__(self, runner: SupportsBeadsRun | None = None) -> None:
        self._runner = runner or BeadsRunner()

    def create_issue(self, item: GitHubSourceItem) -> str:
        description = imported_issue_description(item)
        stdout = self._runner.run(
            [
                "create",
                "--title",
                item.title,
                "--description",
                description,
                "--type=task",
                "--priority=2",
            ]
        )
        match = BEAD_ID_PATTERN.search(stdout)
        if not match:
            raise ValueError(f"unable to parse bead id from bd create output: {stdout!r}")
        return match.group(1)

    def add_dependency(self, bead_id: str, depends_on_bead_id: str) -> None:
        self._runner.run(["dep", "add", bead_id, depends_on_bead_id])


class BeadsRunner:
    def run(self, args: list[str]) -> str:
        command = ["bd", *args]
        completed = subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=True,
        )
        return completed.stdout


def imported_issue_description(item: GitHubSourceItem) -> str:
    lines = [
        f"Imported from GitHub: {item.url}",
        f"Source key: {item.source_key}",
        f"Repository: {item.repo}",
        f"Issue number: {item.issue_number}",
        f"Source state: {item.state}",
    ]
    if item.project_owner and item.project_number is not None:
        lines.append(f"Project: {item.project_owner}#{item.project_number}")
    if item.project_status:
        lines.append(f"Project status: {item.project_status}")
    if item.labels:
        lines.append(f"Labels: {', '.join(item.labels)}")
    lines.extend(
        [
            "",
            "Upstream snapshot:",
            item.body.strip() or "(no body)",
        ]
    )
    return "\n".join(lines)


def merge_source_items(
    existing: GitHubSourceItem | None, incoming: GitHubSourceItem
) -> GitHubSourceItem:
    if existing is None:
        return incoming
    relationships = {entry.kind + ":" + entry.target_key: entry for entry in existing.relationships}
    relationships.update(
        {entry.kind + ":" + entry.target_key: entry for entry in incoming.relationships}
    )
    project_item_id = existing.project_item_id or incoming.project_item_id
    project_owner = existing.project_owner or incoming.project_owner
    project_number = existing.project_number or incoming.project_number
    project_status = existing.project_status or incoming.project_status
    labels = tuple(sorted(set(existing.labels) | set(incoming.labels)))
    body = existing.body if existing.body.strip() else incoming.body
    return GitHubSourceItem(
        source_key=existing.source_key,
        source_kind=(
            existing.source_kind
            if existing.source_kind == "project"
            else incoming.source_kind
        ),
        repo=existing.repo,
        issue_number=existing.issue_number,
        title=existing.title,
        body=body,
        url=existing.url,
        state=existing.state,
        labels=labels,
        issue_node_id=existing.issue_node_id or incoming.issue_node_id,
        project_owner=project_owner,
        project_number=project_number,
        project_item_id=project_item_id,
        project_status=project_status,
        relationships=tuple(
            sorted(relationships.values(), key=lambda item: (item.kind, item.target_key))
        ),
    )


def normalize_repo_issue(issue: dict[str, Any], selector: RepoSource) -> GitHubSourceItem:
    labels = tuple(sorted(label["name"] for label in issue.get("labels", [])))
    return GitHubSourceItem(
        source_key=source_key_for_issue(selector.repo, int(issue["number"])),
        source_kind="repo",
        repo=selector.repo,
        issue_number=int(issue["number"]),
        title=issue["title"],
        body=issue.get("body", ""),
        url=issue["url"],
        state=issue["state"].lower(),
        labels=labels,
        issue_node_id=issue.get("id"),
    )


def normalize_project_items(
    project_items: list[dict[str, Any]], selector: ProjectSource
) -> list[GitHubSourceItem]:
    normalized: list[GitHubSourceItem] = []
    for item in project_items:
        content = item.get("content")
        if selector.issue_backed_only and not content:
            continue
        if not content:
            continue
        labels = tuple(sorted(node["name"] for node in content.get("labels", {}).get("nodes", [])))
        if selector.labels and not set(selector.labels).issubset(set(labels)):
            continue
        status = project_status(item, selector.status_field)
        if selector.status_values and status not in selector.status_values:
            continue
        repo = content["repository"]["nameWithOwner"]
        normalized.append(
            GitHubSourceItem(
                source_key=source_key_for_issue(repo, int(content["number"])),
                source_kind="project",
                repo=repo,
                issue_number=int(content["number"]),
                title=content["title"],
                body=content.get("body", ""),
                url=content["url"],
                state=content["state"].lower(),
                labels=labels,
                issue_node_id=content.get("id"),
                project_owner=selector.owner,
                project_number=selector.number,
                project_item_id=item.get("id"),
                project_status=status,
                relationships=tuple(
                    normalize_issue_relationships(content)
                    + normalize_relationships(item.get("relationships", []))
                ),
            )
        )
    return normalized


def normalize_relationships(payload: list[dict[str, str]]) -> list[GitHubRelationship]:
    normalized: list[GitHubRelationship] = []
    for relationship in payload:
        repo = relationship.get("repo")
        issue_number = relationship.get("issue_number")
        if not repo or issue_number is None:
            continue
        normalized.append(
            GitHubRelationship(
                kind=relationship["kind"],
                target_key=source_key_for_issue(repo, int(issue_number)),
            )
        )
    return normalized


def normalize_issue_relationships(content: dict[str, Any]) -> list[GitHubRelationship]:
    normalized: list[GitHubRelationship] = []
    parent = content.get("parent")
    if parent:
        repo = parent.get("repository", {}).get("nameWithOwner")
        issue_number = parent.get("number")
        if repo and issue_number is not None:
            normalized.append(
                GitHubRelationship(
                    kind="child_of",
                    target_key=source_key_for_issue(repo, int(issue_number)),
                )
            )
    for child in content.get("subIssues", {}).get("nodes", []):
        repo = child.get("repository", {}).get("nameWithOwner")
        issue_number = child.get("number")
        if repo and issue_number is not None:
            normalized.append(
                GitHubRelationship(
                    kind="parent_of",
                    target_key=source_key_for_issue(repo, int(issue_number)),
                )
            )
    return normalized


def project_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload["data"]
    organization_project = data.get("organization", {}) or {}
    if organization_project.get("projectV2"):
        return organization_project["projectV2"]
    user_project = data.get("user", {}) or {}
    if user_project.get("projectV2"):
        return user_project["projectV2"]
    raise ValueError("GitHub project query returned neither an organization nor user project")


def project_status(item: dict[str, Any], field_name: str) -> str | None:
    for node in item.get("fieldValues", {}).get("nodes", []):
        field = node.get("field") or {}
        if field.get("name") == field_name:
            return node.get("name")
    return None


def apply_sync(
    items: list[GitHubSourceItem],
    state: GitHubSyncState,
    beads: BeadsClient,
    *,
    dry_run: bool,
) -> SyncOutcome:
    created: list[str] = []
    skipped: list[str] = []
    dependencies_added: list[str] = []
    pending_dependencies: list[str] = []
    hierarchy_entries: list[str] = []

    for item in items:
        imported = state.imports.get(item.source_key)
        if imported is None:
            if dry_run:
                created.append(item.source_key)
            else:
                bead_id = beads.create_issue(item)
                state.imports[item.source_key] = ImportedBead(
                    bead_id=bead_id,
                    source_kind=item.source_kind,
                    repo=item.repo,
                    issue_number=item.issue_number,
                    url=item.url,
                    issue_node_id=item.issue_node_id,
                    project_item_ids=[item.project_item_id] if item.project_item_id else [],
                )
                created.append(item.source_key)
                imported = state.imports[item.source_key]
        else:
            skipped.append(item.source_key)
            if item.project_item_id and item.project_item_id not in imported.project_item_ids:
                imported.project_item_ids.append(item.project_item_id)

        if imported is None:
            continue

        for relationship in item.relationships:
            if relationship.kind in {"depends_on", "blocked_by"}:
                pending = queue_dependency_relationship(
                    item.source_key,
                    imported.bead_id,
                    relationship,
                    state,
                )
                if pending:
                    pending_dependencies.append(pending)
                continue
            hierarchy_entries.append(record_hierarchy(item.source_key, relationship, state))

    if not dry_run:
        dependencies_added.extend(resolve_pending_dependencies(state, beads))
    else:
        for pending in state.pending_dependencies:
            pending_dependencies.append(f"{pending.source_key} -> {pending.depends_on_key}")

    return SyncOutcome(
        dry_run=dry_run,
        created=tuple(created),
        skipped=tuple(skipped),
        dependencies_added=tuple(dependencies_added),
        pending_dependencies=tuple(pending_dependencies),
        recorded_hierarchy=tuple(hierarchy_entries),
    )


def queue_dependency_relationship(
    source_key: str,
    bead_id: str,
    relationship: GitHubRelationship,
    state: GitHubSyncState,
) -> str | None:
    target_import = state.imports.get(relationship.target_key)
    if target_import is None or not bead_id:
        pending = PendingDependency(
            bead_id=bead_id,
            depends_on_key=relationship.target_key,
            source_key=source_key,
        )
        if pending not in state.pending_dependencies:
            state.pending_dependencies.append(pending)
        return f"{source_key} -> {relationship.target_key}"
    edge = dependency_edge_key(bead_id, target_import.bead_id)
    if edge in state.applied_dependencies:
        return None
    state.pending_dependencies.append(
        PendingDependency(
            bead_id=bead_id,
            depends_on_key=relationship.target_key,
            source_key=source_key,
        )
    )
    return f"{source_key} -> {relationship.target_key}"


def resolve_pending_dependencies(state: GitHubSyncState, beads: BeadsClient) -> list[str]:
    resolved: list[str] = []
    remaining: list[PendingDependency] = []
    seen_pending: set[str] = set()
    for pending in state.pending_dependencies:
        pending_key = f"{pending.bead_id}:{pending.depends_on_key}"
        if pending_key in seen_pending:
            continue
        seen_pending.add(pending_key)
        target = state.imports.get(pending.depends_on_key)
        if target is None or not pending.bead_id:
            remaining.append(pending)
            continue
        edge = dependency_edge_key(pending.bead_id, target.bead_id)
        if edge in state.applied_dependencies:
            continue
        beads.add_dependency(pending.bead_id, target.bead_id)
        state.applied_dependencies.append(edge)
        resolved.append(edge)
    state.pending_dependencies = remaining
    return resolved


def dependency_edge_key(bead_id: str, depends_on_bead_id: str) -> str:
    return f"{bead_id}->{depends_on_bead_id}"


def record_hierarchy(
    source_key: str, relationship: GitHubRelationship, state: GitHubSyncState
) -> str:
    entry = RecordedHierarchy(
        kind=relationship.kind,
        source_key=source_key,
        target_key=relationship.target_key,
    )
    if entry not in state.recorded_hierarchy:
        state.recorded_hierarchy.append(entry)
    imported = state.imports.get(source_key)
    if imported is not None:
        if relationship.kind == "parent_of" and relationship.target_key not in imported.child_keys:
            imported.child_keys.append(relationship.target_key)
        if relationship.kind == "child_of" and relationship.target_key not in imported.parent_keys:
            imported.parent_keys.append(relationship.target_key)
    return f"{relationship.kind}:{source_key}->{relationship.target_key}"


def format_sync_outcome(outcome: SyncOutcome) -> str:
    lines = [
        f"Dry run: {'yes' if outcome.dry_run else 'no'}",
        f"Created: {len(outcome.created)}",
        f"Skipped existing: {len(outcome.skipped)}",
        f"Dependencies added: {len(outcome.dependencies_added)}",
        f"Pending dependencies: {len(outcome.pending_dependencies)}",
        f"Recorded hierarchy links: {len(outcome.recorded_hierarchy)}",
    ]
    if outcome.created:
        lines.append("Created source keys:")
        lines.extend(f"- {key}" for key in outcome.created)
    if outcome.skipped:
        lines.append("Skipped source keys:")
        lines.extend(f"- {key}" for key in outcome.skipped)
    if outcome.pending_dependencies:
        lines.append("Pending dependency source keys:")
        lines.extend(f"- {key}" for key in outcome.pending_dependencies)
    return "\n".join(lines)


def run_sync(
    config_path: Path,
    state_path: Path,
    *,
    dry_run: bool,
    github: GitHubClient | None = None,
    beads: BeadsClient | None = None,
) -> SyncOutcome:
    config = load_config(config_path)
    state = load_state(state_path)
    github_client = github or GitHubClient()
    beads_client = beads or BeadsClient()
    items = github_client.fetch_items(config)
    outcome = apply_sync(items, state, beads_client, dry_run=dry_run)
    if not dry_run:
        save_state(state_path, state)
    return outcome


def default_config_template() -> str:
    payload = {
        "version": CONFIG_VERSION,
        "authority": {
            "github_import_fields": list(SyncAuthority().github_import_fields),
            "local_bead_fields": list(SyncAuthority().local_bead_fields),
        },
        "sources": [
            {
                "kind": "repo",
                "repo": "owner/repo",
                "labels": ["purser"],
                "state": "open",
            },
            {
                "kind": "project",
                "owner": "owner",
                "number": 7,
                "status_field": "Status",
                "status_values": ["Ready", "Todo"],
                "labels": ["purser"],
                "issue_backed_only": True,
            },
        ],
    }
    return f"{json.dumps(payload, indent=2)}\n"


def sync_timestamp() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")
