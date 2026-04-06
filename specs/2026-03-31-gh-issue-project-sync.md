# GitHub Issue, Project, And Beads Sync

## Summary

Add a GitHub synchronization feature that connects Beads issues with GitHub repository issues and GitHub Project items so teams can intake tagged upstream work into a local Purser-managed repository, preserve dependency and parent-child structure where possible, and begin execution through the existing Beads workflow. The first increment should focus on importing selected GitHub work into Beads with clear linkage, traceability, and idempotent sync behavior rather than full bidirectional editing.

## Problem

Purser currently assumes that work is authored or decomposed locally into Beads after a spec is approved. Many teams, however, already manage incoming work in GitHub issues and GitHub Projects, including task hierarchies, blocked work, and project-level triage. Without a bridge between those systems and Beads, teams must manually re-enter issues, relationships, and context into the local repository before builders can start. That duplicate intake step is slow, error-prone, and discourages using Purser in repositories where GitHub is the canonical intake surface.

## Goals

- Allow a local Purser-managed repository to discover GitHub issues or project items that are explicitly marked for local intake.
- Create Beads issues from eligible GitHub work with stable linkage back to the upstream GitHub source.
- Preserve meaningful structure from GitHub where available, including parent-child relationships and dependency or blocked-by relationships.
- Make sync behavior idempotent so repeated imports do not create duplicate Beads.
- Keep the imported Beads actionable for existing `bd ready`, `bd show`, and builder workflows.
- Define a clear boundary between intake/import and later synchronization responsibilities.
- Support both repository issue sources and GitHub Project-based intake views.

## Non-goals

- Full bidirectional synchronization of every field between Beads and GitHub in the first increment.
- Replacing GitHub Projects as the primary planning or dashboard system for teams that already use them.
- Importing every open GitHub issue by default without an explicit intake signal.
- Handling every GitHub issue relationship type or every custom project field in the first pass.
- Automatic conflict resolution for concurrent manual edits in both systems beyond documented precedence rules.
- Cross-platform support beyond GitHub repository issues and GitHub Projects in this feature.

## Users / stakeholders

- Directors or triage maintainers who already tag or organize work in GitHub and want to start local execution quickly.
- Project manager agents that need a structured way to convert upstream GitHub work into Beads.
- Builder agents that should be able to work from Beads without losing context about the upstream GitHub source.
- Repository maintainers who need auditability around what was imported, when, and from where.

## Scope

In scope:

- Define how Purser identifies GitHub issues or GitHub Project items that should be imported into a local repository.
- Define the source metadata that must be stored on imported Beads, such as GitHub URL, issue number, repository, project item id, sync timestamp, and source state.
- Define a mapping for parent-child relationships and dependency-like relationships from GitHub into Beads dependencies where GitHub exposes enough information.
- Define idempotent import behavior so the same GitHub item is linked to one local Bead unless a human explicitly overrides that mapping.
- Define local commands or workflows for running discovery and import.
- Define how imported items move into the normal Beads planning and execution lifecycle.
- Define the minimum documentation and operator guidance needed to use the feature safely.

Out of scope:

- Direct editing of GitHub issues from Beads close/update events in the first increment.
- Syncing comments, full issue history, reactions, or every assignee and label change continuously.
- Managing GitHub authentication UX beyond using the existing GitHub CLI or documented token prerequisites.
- Importing work from Jira, Linear, or other trackers.

## Functional requirements

1. Purser must provide a documented workflow for discovering GitHub repository issues and GitHub Project items that are eligible for local intake.
2. Eligibility for intake must require an explicit signal, such as a configured label, project status, project view, or other documented selector, so import is intentional rather than global.
3. The import workflow must create a Beads issue when an eligible GitHub item has not yet been linked locally.
4. Imported Beads must store stable source linkage sufficient to identify the original GitHub item on later sync runs.
5. Re-running the import workflow must be idempotent and must not create duplicate Beads for the same GitHub source item.
6. The system must define how repository issues and project items are deduplicated when both point to the same underlying GitHub issue.
7. Imported Beads must include enough title and description context from GitHub to be usable locally without immediately reopening the browser.
8. Imported Beads must preserve the upstream GitHub URL and any relevant repository or project identity in their notes or structured metadata.
9. When a GitHub item has a parent-child relationship that can be retrieved reliably, the import process must either:
   - create corresponding Beads with an equivalent relationship representation, or
   - record the relationship explicitly when a direct Beads equivalent is not available.
10. When GitHub exposes dependency or blocked-by relationships reliably enough for the configured source, the import process must translate them into Beads dependencies in the correct direction.
11. The workflow must define deterministic behavior when a relationship references a GitHub item that is not yet imported locally.
12. The workflow must support intake from at least:
   - GitHub repository issues in one or more configured repositories
   - GitHub Projects that surface issue-backed work items
13. The feature must define how project-only metadata is handled, including which fields are ignored, stored as notes, or used for filtering.
14. The workflow must define how state mismatches are handled, such as a GitHub issue being closed after import but before local execution is finished.
15. The implementation must provide a dry-run or preview mode so operators can inspect what would be created or updated before changing local Beads state.
16. The workflow must surface import results clearly, including created Beads, skipped items, unresolved relationships, and errors.
17. The documentation must explain the prerequisites for GitHub authentication and the expected `gh` access scope or API usage path.
18. The feature must document the initial conflict policy, including whether GitHub or local Beads metadata is authoritative for each imported field.

## Technical considerations

- The repository already includes a GitHub CLI skill under `skills/github-cli/SKILL.md`; implementation and operator workflows should reuse `gh` where practical instead of introducing an unrelated GitHub client path without justification.
- GitHub has multiple overlapping concepts for hierarchy and dependency depending on issue type, sub-issues, tracked issues, or project item relationships. The implementation should target only the relationship types that the GitHub API and `gh` can retrieve reliably in automation.
- GitHub Project items may reference draft items or non-issue items. The first increment should clarify whether only issue-backed project items are supported.
- Beads dependencies are directional, so the sync design must define an exact mapping from each supported GitHub relationship into `bd dep add <issue> <depends-on>`.
- Source linkage should be stable even if titles or labels change upstream. GitHub node ids, repository owner/name, and issue numbers are likely safer than title-based matching.
- The sync implementation should be safe to run repeatedly and should tolerate partial failure without corrupting existing Beads relationships.
- If Beads does not support arbitrary structured metadata natively, the design may need a documented notes format or companion local state file to store sync metadata.
- The feature should define whether import creates only raw intake beads or also assigns type, priority, and dependency hints derived from GitHub labels or project fields.
- Authentication and API rate limiting behavior should be documented because sync runs may query multiple repositories, projects, and related items.
- The implementation should avoid assuming every repository using Purser has GitHub Projects enabled.
- The feature should remain ASCII and repo-portable unless a stronger reason emerges.

## Verification strategy

- Add unit tests for source-item normalization, deduplication keys, and relationship mapping logic.
- Add tests for idempotent re-import so the same GitHub item does not create duplicate Beads.
- Add tests for deferred relationship resolution when one related GitHub item arrives before another.
- Add tests for dry-run output and operator-facing summaries if those paths involve code.
- Run `uv run --group dev ruff check`.
- Run `uv run --group dev ty check`.
- Run `uv run --group dev pytest`.
- If CLI workflows are added, verify representative import and dry-run commands against mocked GitHub data or stable fixtures.

## Acceptance criteria

- A documented Purser workflow exists for intentionally importing tagged GitHub repository issues or project items into local Beads.
- Imported Beads retain stable linkage back to the originating GitHub issue or project item.
- Repeated sync runs are idempotent and do not create duplicate Beads for the same source item.
- Supported parent-child and dependency relationships from GitHub are either mapped into Beads correctly or recorded explicitly with clear operator visibility when a direct mapping is not possible.
- Operators can preview intake results before mutating local state.
- Imported work can enter the normal Beads execution flow without manual re-entry of the core issue content.

## Risks / unknowns

- GitHub relationship support varies by feature set and API surface, so some desired parent-child or dependency data may be unavailable or inconsistent across repositories.
- GitHub Project items may include draft items, custom fields, or project-specific semantics that do not map cleanly to Beads.
- Beads metadata constraints may force a notes-based encoding for sync linkage, which could become brittle unless the format is explicit and tested.
- If sync later grows into bidirectional updates, early metadata and precedence choices could constrain future design.
- Teams may expect label-to-priority or project-field-to-status mapping that is too repository-specific for a portable first increment.

## Suggested milestones

1. Confirm the supported GitHub source model for the first increment, including repository issues, project items, and the exact intake selectors.
2. Design the source-linkage and deduplication model for imported Beads, including where sync metadata is stored locally.
3. Implement source discovery and dry-run preview for eligible GitHub items.
4. Implement Beads creation and idempotent re-import for eligible GitHub items.
5. Implement supported relationship mapping and unresolved-relationship reporting.
6. Document the operator workflow, authentication prerequisites, and authority/conflict rules.
7. Add automated verification for normalization, deduplication, and relationship mapping behavior.

## Open questions

- What exact intake signal should the first increment support: label-based selection, project-column/status selection, explicit project view selection, or a combination?
- Should the first increment support only issue-backed project items, or also import project draft items into Beads?
- Where should sync metadata live locally: Beads notes, a companion state file, or another documented storage mechanism?
- Which GitHub relationship types are required for v1: sub-issues, tracked issues, blocked-by/dependency, or only a smaller reliable subset?
- Should imported GitHub issues become ready/open Beads immediately, or should they land in a staged state that requires project-manager review before builder execution?
