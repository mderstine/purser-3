from __future__ import annotations

import json
from pathlib import Path

from purser.cli import build_parser, run_prompt, run_sync_github
from purser.framework import (
    render_claude,
    render_codex,
    render_copilot,
    repository_readme,
    scaffold_repository,
)
from purser.github_sync import (
    BeadsClient,
    GitHubRelationship,
    GitHubSourceItem,
    GitHubSyncState,
    ImportedBead,
    PendingDependency,
    ProjectSource,
    RepoSource,
    SyncOutcome,
    apply_sync,
    default_config_template,
    format_sync_outcome,
    load_config,
    load_state,
    normalize_project_items,
    resolve_pending_dependencies,
    save_state,
)
from purser.templates import TEMPLATES


def test_parser_accepts_check_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["check"])
    assert args.command == "check"
    assert args.paths == ["src", "tests"]


def test_parser_accepts_sync_github_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["sync-github", "--dry-run"])

    assert args.command == "sync-github"
    assert args.dry_run is True


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
    assert "`skills/README.md`" in captured.out


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


def test_all_templates_reference_repo_local_skills() -> None:
    for template in TEMPLATES.values():
        assert "`skills/README.md`" in template.body
        assert "`skills/<tool>/SKILL.md`" in template.body


def test_repository_readme_mentions_director_review_gate() -> None:
    readme = repository_readme()

    assert "then stop" in readme
    assert "The director manually reviews and may edit the spec." in readme
    assert "only after the director explicitly approves the spec for planning" in readme
    assert "generated prompt artifacts" in readme


def test_run_sync_github_prints_config_template(capsys) -> None:
    exit_code = run_sync_github(
        "ignored.json",
        "ignored-state.json",
        dry_run=True,
        print_config_template_only=True,
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["version"] == 1
    assert payload["sources"][0]["kind"] == "repo"
    assert payload["sources"][1]["kind"] == "project"


def test_load_config_supports_repo_and_project_sources(tmp_path: Path) -> None:
    config_path = tmp_path / "github-sync.json"
    config_path.write_text(default_config_template(), encoding="utf-8")

    config = load_config(config_path)

    assert len(config.selectors) == 2
    assert isinstance(config.selectors[0], RepoSource)
    assert isinstance(config.selectors[1], ProjectSource)
    assert config.selectors[1].issue_backed_only is True


def test_state_round_trip_preserves_imports_and_pending_dependencies(tmp_path: Path) -> None:
    state_path = tmp_path / "github-sync-state.json"
    state = GitHubSyncState(
        imports={
            "issue:owner/repo#1": ImportedBead(
                bead_id="purser-3-skills-123",
                source_kind="repo",
                repo="owner/repo",
                issue_number=1,
                url="https://example.invalid/1",
                issue_node_id="ISSUE_1",
                project_item_ids=["ITEM_1"],
                parent_keys=["issue:owner/repo#9"],
                child_keys=["issue:owner/repo#2"],
            )
        },
        pending_dependencies=[
            PendingDependency(
                bead_id="purser-3-skills-123",
                depends_on_key="issue:owner/repo#2",
                source_key="issue:owner/repo#1",
            )
        ],
        applied_dependencies=["purser-3-skills-123->purser-3-skills-456"],
    )

    save_state(state_path, state)
    restored = load_state(state_path)

    assert restored.imports["issue:owner/repo#1"].bead_id == "purser-3-skills-123"
    assert restored.pending_dependencies[0].depends_on_key == "issue:owner/repo#2"
    assert restored.applied_dependencies == ["purser-3-skills-123->purser-3-skills-456"]


def test_normalize_project_items_filters_non_matching_status_and_draft_items() -> None:
    selector = ProjectSource(
        owner="owner",
        number=7,
        status_field="Status",
        status_values=("Ready",),
        labels=("purser",),
    )

    payload = [
        {
            "id": "ITEM_1",
            "fieldValues": {"nodes": [{"name": "Ready", "field": {"name": "Status"}}]},
            "content": {
                "id": "ISSUE_1",
                "number": 10,
                "title": "Import me",
                "body": "body",
                "url": "https://example.invalid/10",
                "state": "OPEN",
                "repository": {"nameWithOwner": "owner/repo"},
                "labels": {"nodes": [{"name": "purser"}]},
            },
        },
        {
            "id": "ITEM_2",
            "fieldValues": {"nodes": [{"name": "Blocked", "field": {"name": "Status"}}]},
            "content": {
                "id": "ISSUE_2",
                "number": 11,
                "title": "Skip me",
                "body": "body",
                "url": "https://example.invalid/11",
                "state": "OPEN",
                "repository": {"nameWithOwner": "owner/repo"},
                "labels": {"nodes": [{"name": "purser"}]},
            },
        },
        {
            "id": "ITEM_3",
            "fieldValues": {"nodes": [{"name": "Ready", "field": {"name": "Status"}}]},
            "content": None,
        },
    ]

    items = normalize_project_items(payload, selector)

    assert [item.source_key for item in items] == ["issue:owner/repo#10"]


def test_normalize_project_items_extracts_parent_and_child_relationships() -> None:
    selector = ProjectSource(
        owner="owner",
        number=7,
        status_field="Status",
        status_values=("Ready",),
    )

    payload = [
        {
            "id": "ITEM_1",
            "fieldValues": {"nodes": [{"name": "Ready", "field": {"name": "Status"}}]},
            "content": {
                "id": "ISSUE_1",
                "number": 10,
                "title": "Import me",
                "body": "body",
                "url": "https://example.invalid/10",
                "state": "OPEN",
                "repository": {"nameWithOwner": "owner/repo"},
                "labels": {"nodes": []},
                "parent": {
                    "number": 9,
                    "repository": {"nameWithOwner": "owner/repo"},
                },
                "subIssues": {
                    "nodes": [
                        {
                            "number": 11,
                            "repository": {"nameWithOwner": "owner/repo"},
                        }
                    ]
                },
            },
        }
    ]

    items = normalize_project_items(payload, selector)

    assert items[0].relationships == (
        GitHubRelationship(kind="child_of", target_key="issue:owner/repo#9"),
        GitHubRelationship(kind="parent_of", target_key="issue:owner/repo#11"),
    )


class FakeBeadsRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.created = 0

    def run(self, args: list[str]) -> str:
        self.commands.append(args)
        if args[0] == "create":
            self.created += 1
            return f"✓ Created issue: purser-3-skills-{self.created}\n"
        return ""


def test_apply_sync_is_idempotent_and_resolves_dependencies() -> None:
    state = GitHubSyncState()
    runner = FakeBeadsRunner()
    beads = BeadsClient(runner=runner)
    items = [
        GitHubSourceItem(
            source_key="issue:owner/repo#1",
            source_kind="repo",
            repo="owner/repo",
            issue_number=1,
            title="First",
            body="first body",
            url="https://example.invalid/1",
            state="open",
            labels=("purser",),
            relationships=(GitHubRelationship(kind="depends_on", target_key="issue:owner/repo#2"),),
        ),
        GitHubSourceItem(
            source_key="issue:owner/repo#2",
            source_kind="repo",
            repo="owner/repo",
            issue_number=2,
            title="Second",
            body="second body",
            url="https://example.invalid/2",
            state="open",
            labels=("purser",),
        ),
    ]

    first = apply_sync(items, state, beads, dry_run=False)
    second = apply_sync(items, state, beads, dry_run=False)

    assert first.created == ("issue:owner/repo#1", "issue:owner/repo#2")
    assert "purser-3-skills-1->purser-3-skills-2" in first.dependencies_added
    assert second.created == ()
    assert second.skipped == ("issue:owner/repo#1", "issue:owner/repo#2")
    assert len([command for command in runner.commands if command[0] == "create"]) == 2
    assert len([command for command in runner.commands if command[:2] == ["dep", "add"]]) == 1


def test_apply_sync_records_parent_child_relationships_without_dependency_edges() -> None:
    state = GitHubSyncState()
    runner = FakeBeadsRunner()
    beads = BeadsClient(runner=runner)
    item = GitHubSourceItem(
        source_key="issue:owner/repo#1",
        source_kind="repo",
        repo="owner/repo",
        issue_number=1,
        title="Parent",
        body="body",
        url="https://example.invalid/1",
        state="open",
        labels=("purser",),
        relationships=(GitHubRelationship(kind="parent_of", target_key="issue:owner/repo#2"),),
    )

    outcome = apply_sync([item], state, beads, dry_run=False)

    assert outcome.recorded_hierarchy == ("parent_of:issue:owner/repo#1->issue:owner/repo#2",)
    assert not [command for command in runner.commands if command[:2] == ["dep", "add"]]


def test_resolve_pending_dependencies_waits_for_missing_import() -> None:
    state = GitHubSyncState(
        pending_dependencies=[
            PendingDependency(
                bead_id="purser-3-skills-1",
                depends_on_key="issue:owner/repo#2",
                source_key="issue:owner/repo#1",
            )
        ],
        imports={
            "issue:owner/repo#1": ImportedBead(
                bead_id="purser-3-skills-1",
                source_kind="repo",
                repo="owner/repo",
                issue_number=1,
                url="https://example.invalid/1",
            )
        },
    )
    runner = FakeBeadsRunner()
    beads = BeadsClient(runner=runner)

    unresolved = resolve_pending_dependencies(state, beads)
    assert unresolved == []
    assert len(state.pending_dependencies) == 1

    state.imports["issue:owner/repo#2"] = ImportedBead(
        bead_id="purser-3-skills-2",
        source_kind="repo",
        repo="owner/repo",
        issue_number=2,
        url="https://example.invalid/2",
    )

    resolved = resolve_pending_dependencies(state, beads)

    assert resolved == ["purser-3-skills-1->purser-3-skills-2"]
    assert state.pending_dependencies == []


def test_format_sync_outcome_summarizes_result() -> None:
    outcome = SyncOutcome(
        dry_run=True,
        created=("issue:owner/repo#1",),
        skipped=("issue:owner/repo#2",),
        dependencies_added=(),
        pending_dependencies=("issue:owner/repo#1 -> issue:owner/repo#3",),
        recorded_hierarchy=(),
    )

    summary = format_sync_outcome(outcome)

    assert "Dry run: yes" in summary
    assert "Created: 1" in summary
    assert "Skipped existing: 1" in summary
