from __future__ import annotations

import json
import subprocess
from pathlib import Path

from purser.cli import (
    _discover_github_repo,
    _git_repo_root,
    _prompt_for_github_config,
    _write_github_sync_config,
    build_parser,
    run_prompt,
    run_sync_github,
)
from purser.framework import (
    PURSER_AGENTS_BEGIN,
    PURSER_AGENTS_END,
    ensure_purser_agents_section,
    render_claude,
    render_codex,
    render_copilot,
    repository_readme,
    scaffold_repository,
)
from purser.github_sync import (
    BeadsClient,
    GitHubPublishConfig,
    GitHubRelationship,
    GitHubSourceItem,
    GitHubSyncConfig,
    GitHubSyncState,
    ImportedBead,
    PendingDependency,
    ProjectSource,
    PublishedChildIssue,
    RepoSource,
    SyncAuthority,
    SyncOutcome,
    SynthesizedSpec,
    apply_sync,
    default_config_template,
    format_sync_outcome,
    load_config,
    load_state,
    normalize_project_items,
    resolve_pending_dependencies,
    save_state,
)
from purser.github_workflow import (
    BeadsIssue,
    GitHubMirrorClient,
    LocalBeadsClient,
    issues_for_spec,
    publish_github_plan,
    sync_github_status,
    synthesize_github_spec,
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


def test_parser_accepts_github_workflow_commands() -> None:
    parser = build_parser()

    synth = parser.parse_args(["synth-gh-spec", "issue:owner/repo#1", "--refresh"])
    publish = parser.parse_args(["publish-github", "specs/2026-04-06-demo.md", "--dry-run"])
    status = parser.parse_args(["sync-status", "--dry-run"])

    assert synth.command == "synth-gh-spec"
    assert synth.refresh is True
    assert publish.command == "publish-github"
    assert publish.dry_run is True
    assert status.command == "sync-status"
    assert status.dry_run is True


def test_parser_accepts_init_github_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "init",
            "--github",
            "--github-repo",
            "owner/repo",
            "--github-label",
            "purser",
            "--github-project-number",
            "7",
        ]
    )

    assert args.command == "init"
    assert args.github is True
    assert args.github_repo == "owner/repo"
    assert args.github_labels == ["purser"]
    assert args.github_project_number == 7


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


def test_ensure_purser_agents_section_appends_without_overwriting_existing_text(
    tmp_path: Path,
) -> None:
    agents_path = tmp_path / "AGENTS.md"
    agents_path.write_text("# Agent Instructions\n\nExisting text.\n", encoding="utf-8")

    changed = ensure_purser_agents_section(agents_path)

    content = agents_path.read_text(encoding="utf-8")
    assert changed is True
    assert "Existing text." in content
    assert PURSER_AGENTS_BEGIN in content
    assert PURSER_AGENTS_END in content


def test_ensure_purser_agents_section_replaces_only_purser_owned_section(tmp_path: Path) -> None:
    agents_path = tmp_path / "AGENTS.md"
    agents_path.write_text(
        "\n".join(
            [
                "# Agent Instructions",
                "",
                "Keep this.",
                "",
                PURSER_AGENTS_BEGIN,
                "Old Purser text.",
                PURSER_AGENTS_END,
                "",
            ]
        ),
        encoding="utf-8",
    )

    changed = ensure_purser_agents_section(agents_path)

    content = agents_path.read_text(encoding="utf-8")
    assert changed is True
    assert "Keep this." in content
    assert "Old Purser text." not in content
    assert content.count(PURSER_AGENTS_BEGIN) == 1


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
    assert "Purser-owned section to `AGENTS.md`" in readme


def test_git_repo_root_resolves_to_repository_toplevel(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    nested = repo_root / "nested"
    nested.mkdir(parents=True)

    def fake_run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        assert command[-1] == "--show-toplevel"
        return subprocess.CompletedProcess(command, 0, stdout=f"{repo_root}\n", stderr="")

    monkeypatch.setattr("purser.cli._run_command", fake_run_command)

    resolved = _git_repo_root(nested)

    assert resolved == repo_root.resolve()


def test_discover_github_repo_reads_origin_remote(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    def fake_run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        assert command[-2:] == ["--get", "remote.origin.url"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="git@github.com:owner/repo.git\n",
            stderr="",
        )

    monkeypatch.setattr("purser.cli._run_command", fake_run_command)

    assert _discover_github_repo(repo_root) == "owner/repo"


def test_prompt_for_github_config_autodiscovers_repo_without_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    monkeypatch.setattr("purser.cli._discover_github_repo", lambda root: "owner/repo")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    config = _prompt_for_github_config(
        repo_root,
        github_repo=None,
        github_labels=None,
        project_owner=None,
        project_number=None,
        project_statuses=None,
    )

    assert config is not None
    assert config.selectors[0].repo == "owner/repo"


def test_write_github_sync_config_respects_force(tmp_path: Path) -> None:
    config = _prompt_for_github_config(
        tmp_path,
        github_repo="owner/repo",
        github_labels=["purser"],
        project_owner="owner",
        project_number=7,
        project_statuses=["Ready"],
    )

    assert config is not None
    written_path = _write_github_sync_config(tmp_path, config, force=False)

    assert written_path == tmp_path / ".purser" / "github-sync.json"
    original = written_path.read_text(encoding="utf-8")
    written_path.write_text('{"custom": true}\n', encoding="utf-8")

    skipped = _write_github_sync_config(tmp_path, config, force=False)
    replaced = _write_github_sync_config(tmp_path, config, force=True)

    assert skipped is None
    assert replaced == written_path
    assert written_path.read_text(encoding="utf-8") == original


def test_run_sync_github_prints_config_template(capsys) -> None:
    exit_code = run_sync_github(
        Path("/tmp"),
        "ignored.json",
        "ignored-state.json",
        dry_run=True,
        print_config_template_only=True,
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["version"] == 1
    assert payload["publish"]["enabled"] is False
    assert payload["mirror"]["enabled"] is True
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
    assert config.publish.parent_close_on_complete is True


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


class FakeWorkflowBeadsRunner:
    def __init__(self, issues: list[dict[str, object]]) -> None:
        self._issues = {str(issue["id"]): issue for issue in issues}

    def run(self, args: list[str]) -> str:
        if args[:2] == ["export", "--no-memories"]:
            return "\n".join(json.dumps(issue) for issue in self._issues.values()) + "\n"
        if args[:1] == ["show"]:
            return json.dumps([self._issues[args[1]]])
        raise AssertionError(f"unexpected Beads command: {args}")


class FakeGhRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.created = 0

    def run(self, args: list[str]) -> str:
        self.commands.append(args)
        if args[:2] == ["issue", "create"]:
            self.created += 1
            return f"https://github.com/owner/repo/issues/{self.created}\n"
        if args[:2] == ["issue", "comment"]:
            return ""
        if args[:2] == ["issue", "close"]:
            return ""
        if args[:3] == ["project", "item-edit", "--id"]:
            return ""
        raise AssertionError(f"unexpected gh command: {args}")

    def run_json(self, args: list[str]) -> object:
        self.commands.append(args)
        if args[:2] == ["issue", "view"]:
            url = args[2]
            number = int(url.rsplit("/", 1)[-1])
            return {"id": f"ISSUE_{number}", "number": number, "url": url}
        if args[:2] == ["project", "item-add"]:
            return {"id": "ITEM_1"}
        if args[:2] == ["project", "field-list"]:
            return [
                {
                    "id": "FIELD_STATUS",
                    "name": "Status",
                    "options": [
                        {"id": "OPT_TODO", "name": "Todo"},
                        {"id": "OPT_IN_PROGRESS", "name": "In Progress"},
                        {"id": "OPT_BLOCKED", "name": "Blocked"},
                        {"id": "OPT_DONE", "name": "Done"},
                    ],
                }
            ]
        if args[:2] == ["api", "graphql"]:
            return {"data": {"organization": {"projectV2": {"id": "PROJECT_1"}}, "user": None}}
        raise AssertionError(f"unexpected gh json command: {args}")


def test_synthesize_github_spec_records_spec_path_and_writes_file(tmp_path: Path) -> None:
    state = GitHubSyncState(
        imports={
            "issue:owner/repo#1": ImportedBead(
                bead_id="purser-1",
                source_kind="repo",
                repo="owner/repo",
                issue_number=1,
                url="https://github.com/owner/repo/issues/1",
                title="Portable init workflow",
                body="Bootstrap Purser into existing repos.",
            )
        }
    )

    result = synthesize_github_spec(state, "issue:owner/repo#1", root=tmp_path)

    spec_path = tmp_path / result.spec_path
    assert spec_path.exists()
    assert state.synthesized_specs["issue:owner/repo#1"].spec_path == result.spec_path
    assert "Portable init workflow" in spec_path.read_text(encoding="utf-8")


def test_issues_for_spec_filters_exported_beads_by_description_path() -> None:
    issues = [
        BeadsIssue(
            bead_id="purser-1",
            title="First",
            description="Spec path: specs/demo.md",
            status="open",
            priority=2,
            issue_type="task",
        ),
        BeadsIssue(
            bead_id="purser-2",
            title="Second",
            description="Spec path: specs/other.md",
            status="open",
            priority=2,
            issue_type="task",
        ),
    ]

    filtered = issues_for_spec(issues, "specs/demo.md")

    assert [issue.bead_id for issue in filtered] == ["purser-1"]


def test_publish_github_plan_creates_child_issues_and_records_state() -> None:
    config = GitHubSyncConfig(
        version=1,
        selectors=(),
        authority=SyncAuthority(),
        publish=GitHubPublishConfig(
            enabled=True,
            repo="owner/repo",
            add_to_project=True,
            project_owner="owner",
            project_number=7,
        ),
    )
    state = GitHubSyncState(
        imports={
            "issue:owner/repo#1": ImportedBead(
                bead_id="purser-parent",
                source_kind="repo",
                repo="owner/repo",
                issue_number=1,
                url="https://github.com/owner/repo/issues/1",
                title="Parent",
            )
        },
        synthesized_specs={
            "issue:owner/repo#1": SynthesizedSpec(
                source_key="issue:owner/repo#1",
                spec_path="specs/demo.md",
                title="Demo",
                source_url="https://github.com/owner/repo/issues/1",
                synthesized_at="2026-04-06T00:00:00+00:00",
            )
        },
    )
    beads = LocalBeadsClient(
        Path("/tmp"),
        runner=FakeWorkflowBeadsRunner(
            [
                {
                    "id": "purser-1",
                    "title": "Do thing",
                    "description": "Spec path: specs/demo.md",
                    "status": "open",
                    "priority": 2,
                    "issue_type": "task",
                }
            ]
        ),
    )
    github_runner = FakeGhRunner()

    result = publish_github_plan(
        config,
        state,
        spec_path="specs/demo.md",
        beads=beads,
        github=GitHubMirrorClient(github_runner),
        dry_run=False,
    )

    assert result.published == ("purser-1",)
    assert state.published_children["purser-1"].issue_number == 1
    assert any(command[:2] == ["issue", "create"] for command in github_runner.commands)


def test_sync_github_status_closes_children_and_parent_when_complete() -> None:
    config = GitHubSyncConfig(
        version=1,
        selectors=(),
        authority=SyncAuthority(),
        publish=GitHubPublishConfig(
            enabled=True,
            repo="owner/repo",
            add_to_project=True,
            project_owner="owner",
            project_number=7,
        ),
    )
    state = GitHubSyncState(
        imports={
            "issue:owner/repo#1": ImportedBead(
                bead_id="purser-parent",
                source_kind="repo",
                repo="owner/repo",
                issue_number=1,
                url="https://github.com/owner/repo/issues/1",
                title="Parent",
            )
        },
        published_children={
            "purser-1": PublishedChildIssue(
                bead_id="purser-1",
                parent_source_key="issue:owner/repo#1",
                spec_path="specs/demo.md",
                repo="owner/repo",
                issue_number=10,
                url="https://github.com/owner/repo/issues/10",
                project_item_id="ITEM_1",
            )
        },
    )
    beads = LocalBeadsClient(
        Path("/tmp"),
        runner=FakeWorkflowBeadsRunner(
            [
                {
                    "id": "purser-1",
                    "title": "Do thing",
                    "description": "Spec path: specs/demo.md",
                    "status": "closed",
                    "priority": 2,
                    "issue_type": "task",
                }
            ]
        ),
    )
    github_runner = FakeGhRunner()

    result = sync_github_status(
        config,
        state,
        beads=beads,
        github=GitHubMirrorClient(github_runner),
        dry_run=False,
    )

    assert result.parent_closures == ("issue:owner/repo#1",)
    assert "issue:owner/repo#1" in state.closed_parent_source_keys
    assert any(command[:2] == ["issue", "close"] for command in github_runner.commands)


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
