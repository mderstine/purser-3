# Upgrade README With Mermaid Director Guide

## Summary

Upgrade the top-level README so a director can understand how to run Purser end to end without reconstructing the workflow from prose alone. Add Mermaid charts that explain the role handoff model, the director approval gates, the single-bead and Ralph-loop execution paths, and the GitHub repo/project issue sync path into local Beads.

## Problem

The current README explains Purser’s lifecycle in text, but it still requires the director to mentally assemble the system from multiple sections. That is workable for maintainers who already know the model, but it creates unnecessary friction for a director trying to understand how work moves from idea to spec to Beads to execution, and how GitHub issue/project intake now fits into that system. Without visual workflow documentation, the most important control points, especially director approval and the boundary between intake and execution, are easy to miss.

## Goals

- Make the director workflow understandable from the README alone.
- Add Mermaid diagrams that clarify the main lifecycle and decision points.
- Show the separation of responsibilities between director, project manager, builder, GitHub, and Beads.
- Visualize where explicit director approval is required before planning or build work proceeds.
- Show how GitHub repository issues and GitHub Project items can enter the local Beads workflow through `purser sync-github`.
- Keep the README readable in plain markdown even if Mermaid is not rendered.
- Preserve the existing portable-tooling focus of the project documentation.

## Non-goals

- Rewriting the full README information architecture from scratch.
- Replacing the existing prose with diagrams only.
- Documenting every implementation detail of the GitHub sync internals in the README.
- Adding animated, interactive, or JavaScript-driven documentation assets.
- Introducing Mermaid charts into every document in the repository.

## Users / stakeholders

- Directors who need a fast, accurate understanding of how to operate Purser.
- Maintainers onboarding new users to the repository.
- Project manager and builder agents whose workflows should be explained consistently.
- Users evaluating whether GitHub issue/project intake fits their process.

## Scope

In scope:

- Update the top-level README.
- Add Mermaid charts that explain the Purser lifecycle and GitHub sync path.
- Reorganize nearby README sections as needed so the charts appear in the right narrative order.
- Add short explanatory prose around each chart so the diagrams are actionable rather than decorative.
- Clarify how the director uses `purser-add-spec`, approves specs, and decides when to run planning and build workflows.
- Clarify how `sync-github` fits into the lifecycle without implying full bidirectional sync.

Out of scope:

- Adding separate rendered image exports of the charts.
- Reworking `docs/github-sync.md` beyond any minimal cross-reference updates needed for consistency.
- Changing CLI behavior or implementation as part of this documentation-only increment.

## Functional requirements

1. The README must include a director-oriented overview section near the top that explains the lifecycle in operational terms.
2. The README must include at least one Mermaid diagram showing the end-to-end Purser flow from idea intake through spec approval, planning, and bead execution.
3. The README must include a Mermaid diagram or diagrams that make director approval gates explicit.
4. The documentation must show the role boundaries among director, project manager agent, builder agent, Beads, and GitHub.
5. The README must explain both build modes:
   - `purser-build` for one bead at a time
   - `purser-build-all` for the Ralph loop until no actionable beads remain
6. The README must include a Mermaid diagram showing how GitHub repository issues and GitHub Project items are filtered and imported into local Beads through `purser sync-github`.
7. The GitHub sync diagram must make clear that intake is explicit and selector-based rather than importing all open issues.
8. The GitHub sync documentation must clearly show that imported work enters the local Beads workflow after intake.
9. The diagrams and surrounding prose must make clear that `sync-github` is an intake workflow, not full bidirectional synchronization.
10. The README must remain understandable when viewed as raw markdown, including meaningful section headings and short prose before or after each Mermaid block.
11. The added Mermaid syntax must be compatible with common GitHub Mermaid rendering expectations and avoid advanced features that are likely to render inconsistently.
12. The README must preserve or improve discoverability of the existing command references and approval-gate guidance.

## Technical considerations

- Mermaid blocks should use simple, stable chart types such as `flowchart` unless another chart form has a clear readability advantage.
- The diagrams should be concise enough to remain readable in GitHub’s markdown renderer and in raw source form.
- The documentation should avoid visual overload. A few purposeful charts are better than many tiny ones.
- The README already contains the relevant lifecycle and GitHub sync prose, so the work should mostly restructure and visualize existing concepts rather than invent a new model.
- The charts should align with the implemented GitHub sync behavior:
  - explicit repo label selectors
  - issue-backed GitHub Project item intake
  - dry-run before import
  - import into local Beads
  - normal Beads execution after intake
- The diagrams should preserve ASCII-friendly surrounding prose even though Mermaid syntax itself uses diagram notation.
- If a chart becomes too dense, it should be split into multiple focused diagrams instead of compressing unrelated flows into one block.

## Verification strategy

- Manually review the updated README in raw markdown form to ensure the narrative remains clear even without rendered diagrams.
- Manually review the Mermaid blocks for syntax correctness and readability.
- Verify the README accurately reflects the implemented commands and current workflow, including `uv run purser prompt purser-add-spec --agent codex`, `uv run purser sync-github --dry-run`, `purser-plan`, `purser-build`, and `purser-build-all`.
- Verify the GitHub sync charts match the documented behavior in `docs/github-sync.md`.
- If any README-related tests or checks exist or are added, run `uv run --group dev ruff check`, `uv run --group dev ty check`, and `uv run --group dev pytest` for the affected scope.

## Acceptance criteria

- The README includes director-friendly Mermaid diagrams for the core Purser lifecycle.
- The README makes the approval-gate sequence visually obvious.
- The README explains the difference between planning, single-bead execution, and Ralph-loop execution.
- The README includes a clear Mermaid diagram for GitHub issue/project intake into Beads.
- The diagrams are supported by short prose that makes the system understandable to a first-time director.
- The resulting README matches the current implementation and does not over-promise unsupported GitHub sync behavior.

## Risks / unknowns

- Mermaid diagrams can become cluttered quickly if too many concepts are packed into one chart.
- GitHub markdown rendering supports Mermaid, but some alternate viewers may not, so the surrounding prose must carry the meaning as well.
- A visually improved README can still mislead if the diagrams simplify away important approval or scope boundaries.
- The director-facing view may compete with maintainers’ desire for compact reference documentation, so the section order matters.

## Suggested milestones

1. Decide the README section order for a director-first walkthrough.
2. Add a high-level Mermaid lifecycle chart showing idea, spec, approval, planning, Beads, and execution.
3. Add a focused Mermaid chart for approval gates and build-mode branching.
4. Add a Mermaid chart for GitHub repo/project issue intake into local Beads.
5. Tighten surrounding prose and command references so each chart is actionable.
6. Verify the README against the implemented GitHub sync behavior and existing lifecycle commands.

## Open questions

- Should the README include two diagrams or three: one lifecycle chart, one approval/build chart, and one GitHub sync chart?
- Should the README place the GitHub sync chart near the main lifecycle overview or keep it in a dedicated GitHub sync section?
- How much Mermaid detail is enough for directors before the charts become more confusing than the prose?
