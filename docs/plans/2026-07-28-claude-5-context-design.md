# Claude 5 context design

## Source and intent

This design applies Anthropic's 2026-07-24 context-engineering guidance:
<https://claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models>.
The employee base should give Claude direction, project-specific boundaries,
and non-obvious release constraints without duplicating information already
available from code, agent descriptions, or skill metadata.

## Authoritative scope

- `CLAUDE.md`: employee HOT context installed as `~/.claude/CLAUDE.md`.
- `skills/project-memory/templates/core/{root-CLAUDE.md.tmpl,CLAUDE.md.tmpl}`:
  source templates for portable project memory.
- The current workspace's root `CLAUDE.md`, `Claude/CLAUDE.md`, and
  `этаж2/manager_station/CLAUDE.md`.
- Active references in `agents/`, `skills/`, and `README.md` that claim a
  removed section or numbered rule still lives in global `CLAUDE.md`.

Generated candidates, fake homes, fixtures, temporary worktrees, historical
handoffs, and session reports are evidence or history. They are regenerated or
left immutable instead of edited as sources.

## Context layers

1. **HOT:** a compact global `CLAUDE.md` containing language behavior, working
   principles, review boundaries, and security/privacy limits.
2. **WARM:** native agent and skill descriptions used for discovery and
   routing. The HOT layer does not repeat their catalog.
3. **COLD:** full skills, scripts, references, templates, and operational
   commands loaded only when selected.
4. **Portable project state:** project `Claude/STATUS.md` and the top of the
   session journal. This is cross-device and cross-model handoff state, not a
   duplicate of Claude's local auto-memory.

## Runtime principles

- Match the surrounding project and use judgment for ordinary implementation.
- Inspect real sources before consequential changes.
- Prefer deterministic tooling for deterministic transformations.
- Load detailed instructions progressively through matching skills.
- Use reviewers where the cost of an unchecked error is material; lack of
  access or evidence cannot be reported as PASS.
- Keep exact normative citations source-backed through `norm-lookup`.

## Non-negotiable boundary

The simplification does not weaken authentication, privacy, provider-policy,
employee-release, or irreversible-action gates. The base remains one-way
hub-to-consumer, does not upload employee state, and does not select a model or
effort level. Auto-memory settings are outside this documentation refactor and
remain unchanged.

## Acceptance

- The installed HOT file is at most 2,000 UTF-8 bytes.
- Total static startup/discovery reduction versus the pinned legacy baseline
  is at least 85%.
- Active agents and skills no longer point to removed global CLAUDE sections
  or numbered rules.
- Project-memory templates describe material-state updates instead of requiring
  a manual write after every session.
- Focused contract tests, the full repository suite, token audit, deterministic
  candidate build, and offline Foundation acceptance pass before any online
  release action.
