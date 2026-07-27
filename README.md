# Claude Base v2

Native, progressively loaded Claude Code base with a clean history and pinned
migration provenance.

## Runtime shape

- HOT: compact global `~/.claude/CLAUDE.md`.
- WARM: discovery metadata for 16 Claude subagents, 37 capability skills, and
  one explicit `sync-base` control skill.
- COLD: full skill instructions, scripts, templates, references, 3 named
  chains, and 3 command files loaded only when selected.

The base uses native Claude Code locations: `settings.json`, `agents/*.md`,
`skills/*/SKILL.md`, and `commands/*.md`. It does not read Codex `AGENTS.md` or
depend on a shared runtime repository. Model and effort are not fixed by the
base. Simple conversation invokes no tools, subagents, or reviewers.

## Delivery and token discipline

Updates are one-way from immutable hub releases to consumers. `$sync-base`
verifies release identity, attestations, manifests, component hashes, and the
pinned Foundation engine before `plan/install/doctor`; failed doctor triggers
rollback. Feedback, telemetry, session uploads, credentials, and local changes
never flow back to the hub.

Static startup/discovery estimation is 4,007 tokens versus the 24,026-token
legacy baseline, an 83.32% reduction. This is not provider billing; matched A/B
has not run.

Current verdict: `FULL_RELEASE_CLAUDE: NOT_PASS`.

Repository separation is not evidence for or against any prior Anthropic
account action. The exact supported Claude Code version, real Foundation
fake-home acceptance, independent policy audit, and live Claude canary remain
required before release.
