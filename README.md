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
account action. The policy audit found no language-based prohibition on
Russian construction documents, but Russia is absent from Anthropic's current
supported-region lists. Employee account and physical-location eligibility
must therefore be resolved before release; VPN or proxy transport cannot be
used to bypass that restriction. See
[`docs/ANTHROPIC-POLICY-AUDIT.md`](docs/ANTHROPIC-POLICY-AUDIT.md).

Claude Code `2.1.218` is pinned after an exact WinGet install, valid
Authenticode verification, and zero-model `--version`/`--help` smoke. This is
only `CLIENT_BINARY_ACCEPTANCE: PASS`; employee eligibility, provider login,
model runtime, and the reversible live base canary remain required.

## Historical offline integration acceptance

The non-releasable runner temporarily overlays client version
`0.0.0-offline` only inside an exported clean commit. Its transformation ID is
deliberately incompatible with stable release policy. It runs the real pinned
Foundation engine through `plan/install/doctor/inventory/rollback` in
PowerShell 7 and 5.1:

```powershell
py -3.12 .\tools\run_offline_acceptance.py `
  --foundation ..\llm-foundation-installer\.work\acceptance\engine-ps7 `
  --foundation-evidence ..\llm-foundation-installer\dist\foundation-acceptance.json `
  --output .\dist\offline-acceptance
```

This pre-client runner produced the existing synthetic evidence but is retired
once the real client contract is accepted. It can never create
`package-acceptance.json` or replace the Claude canary.
