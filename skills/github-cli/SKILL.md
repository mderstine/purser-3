# GitHub CLI Skill

Use this skill when work in the current repository depends on GitHub operations
through `gh`.

## When To Use

- checking authentication or active account context
- inspecting repositories, pull requests, issues, and workflow runs
- triggering or watching GitHub Actions workflows
- making targeted GitHub API requests through `gh api`
- installing or using `gh` extensions

## Core Workflow

1. Confirm authentication and active account context before making changes.
2. Prefer repository-scoped `gh` commands over manual browser navigation when a
   command already exists.
3. Use `gh api` only when the built-in `gh` subcommands do not cover the task
   cleanly.
4. Treat extensions as extra code that must be audited before use.

## Authentication And Context

- Run `gh auth status` to inspect the active account and host state.
- Use `gh auth login` when the environment is not authenticated.
- Prefer environment-managed credentials when they already exist.
- Be careful with token output. `gh auth status --show-token` exposes secrets and
  should only be used when there is a clear need.
- If a task targets another repository, pass `-R owner/repo` explicitly instead
  of assuming the current checkout is the right context.

## Common Commands

- Repositories: `gh repo view`, `gh repo clone`, `gh repo fork`
- Pull requests: `gh pr view`, `gh pr status`, `gh pr checkout`, `gh pr checks`
- Issues: `gh issue view`, `gh issue list`, `gh issue create`
- Actions: `gh run list`, `gh run view`, `gh run watch`, `gh workflow run`
- General status: `gh status`

## `gh api` Guidance

- Use `gh api` for endpoints or GraphQL queries that are not covered by a
  higher-level `gh` command.
- Prefer read-only requests first when exploring unfamiliar objects.
- Use repository placeholders such as `repos/{owner}/{repo}/...` when you want
  the current repository context to fill in automatically.
- Keep mutation requests narrow and explicit.
- Avoid preview APIs unless the task specifically requires them.

## Extensions

- `gh extension` provides install, list, search, exec, and upgrade workflows.
- Extension repositories must start with `gh-`.
- Extensions cannot override core `gh` commands.
- Review an extension's source, maintenance state, and requested behavior before
  installing or running it.
- Prefer core `gh` commands when they already satisfy the task.

## Operational Notes

- `gh run list` is good for recent workflow history.
- `gh workflow run` only works for workflows that support
  `workflow_dispatch`.
- Use JSON output flags when the task needs machine-readable parsing instead of
  free-form terminal output.
- Use `--web` or `gh browse` only when a browser is genuinely the better tool
  for the task.

## Sources

- Official GitHub CLI manual: https://cli.github.com/manual/gh
- `gh auth status`: https://cli.github.com/manual/gh_auth_status
- `gh auth login`: https://cli.github.com/manual/gh_auth_login
- `gh api`: https://cli.github.com/manual/gh_api
- `gh extension`: https://cli.github.com/manual/gh_extension
- `gh run list`: https://cli.github.com/manual/gh_run_list
- `gh workflow run`: https://cli.github.com/manual/gh_workflow_run
- Design reference: https://claude-plugins.dev/skills/@lollipopkit/cc-skills/gh-cli
