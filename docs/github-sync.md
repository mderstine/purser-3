# GitHub Sync Workflow

`purser sync-github` imports intentionally selected GitHub work into local
Beads so a Purser-managed repository can begin execution without manually
re-entering issues.

## Prerequisites

- `gh` must be installed and authenticated for the target repositories or
  projects.
- `bd` must be installed and initialized in the repository.
- The operator should confirm GitHub access first with `gh auth status`.

## V1 source model

Purser supports two intake source kinds:

1. Repository issues
2. GitHub Project items backed by GitHub issues

V1 intentionally does not import draft project items.

## Intake selectors

Repository issues are selected by:

- repository name, for example `owner/repo`
- label set
- issue state, usually `open`

GitHub Project items are selected by:

- project owner and project number
- a named single-select status field, default `Status`
- one or more allowed status values
- optional label requirements on the underlying GitHub issue

Import is always explicit. Purser does not ingest every open GitHub issue by
default.

## Authority rules

GitHub is authoritative at import time for:

- source identity
- source URL
- title snapshot
- body snapshot
- source state snapshot
- project selector match

Local Beads is authoritative after import for:

- bead lifecycle state
- local dependency edges
- execution notes

V1 is an intake workflow, not bidirectional synchronization. Re-running sync
does not overwrite existing Bead content from GitHub.

## State and deduplication

Purser stores sync metadata in `.purser/github-sync-state.json`.

The state file tracks:

- imported source keys to local bead ids
- project item ids associated with imported issues
- unresolved dependency edges waiting for another imported item
- dependency edges already applied to Beads
- recorded hierarchy relationships

Issue-backed project items and repository issues deduplicate onto the same local
source key format:

```text
issue:owner/repo#123
```

That means a project item and its backing repository issue import into the same
Bead instead of creating duplicates.

## Relationship behavior

V1 treats dependency-like relationships conservatively:

- `depends_on` relationships become `bd dep add <issue> <depends-on>` once both
  local bead ids exist.
- unresolved dependency targets stay in sync state until a later run can apply
  them.
- parent-child relationships are recorded explicitly in sync state for operator
  visibility.

This avoids forcing hierarchy into Beads dependencies when the meaning is
ambiguous.

## Config template

Generate a starter config with:

```bash
uv run purser sync-github --print-config-template > .purser/github-sync.json
```

Or let `purser init` seed the config from the current repository:

```bash
purser init --github
purser init --github --github-project-owner owner --github-project-number 7
```

Example:

```json
{
  "version": 1,
  "authority": {
    "github_import_fields": [
      "source identity",
      "source url",
      "source title snapshot",
      "source body snapshot",
      "source state snapshot",
      "project selector match"
    ],
    "local_bead_fields": [
      "bead id",
      "bead lifecycle state",
      "local dependency edges",
      "execution notes"
    ]
  },
  "sources": [
    {
      "kind": "repo",
      "repo": "owner/repo",
      "labels": ["purser"],
      "state": "open"
    },
    {
      "kind": "project",
      "owner": "owner",
      "number": 7,
      "status_field": "Status",
      "status_values": ["Ready", "Todo"],
      "labels": ["purser"],
      "issue_backed_only": true
    }
  ]
}
```

## Commands

Preview a sync without mutating Beads or state:

```bash
uv run purser sync-github --config .purser/github-sync.json --dry-run
```

Run the sync for real:

```bash
uv run purser sync-github --config .purser/github-sync.json
```

Generate a local spec from an imported GitHub parent issue:

```bash
purser synth-gh-spec issue:owner/repo#123
```

After `purser-plan` creates local Beads that include `Spec path: specs/...` in
their descriptions, publish them outward as GitHub child issues:

```bash
purser publish-github specs/2026-04-06-demo.md
```

Mirror local Beads execution state back to the published GitHub child issues
and roll up the parent issue when all child work is complete:

```bash
purser sync-status
```

Use a custom state path if the repository wants to isolate experiments:

```bash
uv run purser sync-github \
  --config .purser/github-sync.json \
  --state .purser/github-sync-state.json
```

## Output

The command prints:

- whether the run was a dry run
- how many source keys would be or were created
- how many source keys were skipped because they already existed locally
- how many dependency edges were applied
- how many dependency edges remain pending
- how many hierarchy relationships were recorded

`publish-github` prints:

- which parent source key the spec is linked to
- how many Beads were published as GitHub child issues
- which bead ids were skipped because they were already published

`sync-status` prints:

- how many published child beads were inspected
- the current local Beads state of each linked child
- which parent source keys were closed during rollup

## Notes

- Project support relies on `gh api graphql`.
- Repository issue discovery uses `gh issue list`.
- Tests should mock GitHub responses rather than requiring live network access.
- Published child issue linking currently uses explicit parent references in the
  child issue body plus optional shared project membership; native GitHub
  sub-issue mutation support is not implemented yet.
