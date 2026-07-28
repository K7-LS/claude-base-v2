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

Static startup/discovery estimation is 3,582 tokens versus the 24,026-token
legacy baseline, an 85.09% reduction. The 1,714-byte HOT layer follows the
progressive context design in
[`docs/plans/2026-07-28-claude-5-context-design.md`](docs/plans/2026-07-28-claude-5-context-design.md).
These are not provider-billing results; matched A/B has not run.

Current verdict: `FULL_RELEASE_CLAUDE: NOT_PASS`.

Repository separation is not evidence for or against any prior Anthropic
account action. The policy audit found no language-based prohibition on
Russian construction documents. Employee and organization eligibility must
still be verified against Anthropic's current supported-region rules before
each release; VPN or proxy transport cannot be used to bypass a region,
account, or safeguard restriction. See
[`docs/ANTHROPIC-POLICY-AUDIT.md`](docs/ANTHROPIC-POLICY-AUDIT.md).

Claude Code `2.1.218` is pinned to the official
`win32-x64/claude.exe` binary with SHA-256
`81fcf59bb7abb558aedc6f2361f4723b3d757d28e799962d88b18b4520df66ca`,
valid Authenticode signer `Anthropic, PBC`, and zero-model
`--version`/`--help` smoke. WinGet is not part of this acceptance path. This
is only `CLIENT_BINARY_ACCEPTANCE: PASS`; employee eligibility, provider
login, model runtime, and the reversible live base canary remain required.

## Offline candidate acceptance

With an accepted exact client binary, the runner exports a clean commit,
builds the candidate twice, and runs the real pinned Foundation engine through
`plan/install/doctor/inventory/rollback` in PowerShell 7 and 5.1:

```powershell
py -3.12 .\tools\run_offline_acceptance.py `
  --foundation ..\llm-foundation-installer\.work\acceptance\engine-ps7 `
  --foundation-evidence ..\llm-foundation-installer\dist\foundation-acceptance.json `
  --candidate-version 0.1.0 `
  --output .\dist\candidate-0.1.0
```

This proves deterministic candidate packaging and fake-home preservation, but
it remains non-releasable and can never create `package-acceptance.json` or
replace the Claude live/provider canaries.

## Controlled release

All online entry points are dry-run by default. The one approved no-tools
provider marker requires PII-free eligibility evidence no older than seven
days; the live canary uses an isolated home and performs no model request.

```powershell
py -3.12 .\tools\provider_marker.py
py -3.12 .\tools\live_canary.py
```

After the explicitly approved executions pass, compose final evidence and
promote the already accepted candidate ZIP without rebuilding it:

```powershell
py -3.12 .\tools\final_evidence.py `
  --candidate-evidence .\dist\candidate-0.1.0\candidate-acceptance.json `
  --provider-marker-evidence <provider-marker.json> `
  --canary-evidence <claude-canary.json> `
  --output <claude-final-evidence.json>

py -3.12 .\tools\promote_candidate.py `
  --candidate .\dist\candidate-0.1.0 `
  --final-evidence <claude-final-evidence.json> `
  --output .\dist\stable-0.1.0
```

After immutable GitHub publication, `release_verifier.py` runs
`gh release verify` and `gh release verify-asset`. Only then may
`create_package_acceptance.py` produce the local record consumed by the
employee installer.
