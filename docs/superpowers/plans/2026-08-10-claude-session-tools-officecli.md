# Claude Session Tools and OfficeCLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Use superpowers:test-driven-development, superpowers:writing-skills for the imported skill contract, and superpowers:verification-before-completion.

**Goal:** подготовить распространяемый Claude Base `0.1.1` с `ru-writing-style` session auto-pull и Foundation-managed OfficeCLI, не заменяя действующий legacy auto-pull/auto-push и не обходя provider/release gates.

**Architecture:** immutable session asset and package baseline mirror Codex. `claude-managed.exe` guarantees pre-process update; Claude SessionStart calls the same updater as fallback and keeps the existing daily release check. OfficeCLI is shared Foundation state. Full distribution is promoted only after exact Claude `2.1.218` eligibility marker, zero-model lifecycle canary, immutable release and all-asset attestations.

**Tech Stack:** Python 3.12 + pytest, PowerShell 7/5.1, Claude Code `2.1.218`, Foundation protocol 1.

## Global Constraints

- Start from `origin/main` `c31138091003a1e7573420781cd22bea558168dd`.
- Commit generated `AGENTS.md` from project bootstrap; do not hand-edit it.
- Approved skill source: `C:/Users/Даниил/.claude/skills/ru-writing-style/SKILL.md`, SHA-256 `a20f25a852eaff976c9db90929c94f5658acb3a71eb264479f6d354e04a10938`, 20003 bytes.
- Require accepted Foundation `0.3.0`; OfficeCLI source/version/hash come only from that release.
- Preserve live `~/.claude/settings.json`, `~/.claude/scripts/auto-pull.ps1`, legacy auto-push, authentication, sessions, plugins, MCP and projects.
- Personal testing/owner authorization is not a substitute for `CLAUDE_PROVIDER_MARKER=PASS`, `CLAUDE_CANARY=PASS` or immutable package acceptance.
- Before provider marker, require truthful owner attestation: employee, supported physical location, supported account region, no region bypass and accepted current consumer terms.
- Do not publish automatically.

## File Map

- `AGENTS.md`, `skills/ru-writing-style/SKILL.md`, `cold/memory/reference_officecli.md`, `catalog/*.json`, `MIGRATION-SOURCE.json`.
- `tools/session_tools.py`, `tools/release_builder.py`, `release_verifier.py`, `promotion.py`.
- `runtime/update-session-tools.ps1`, `runtime/hooks/check-release.ps1`, `runtime/settings.json`, `runtime/managed-surface.json`.
- `tools/run_offline_acceptance.py`, `live_canary.py`, `final_evidence.py`, `provider_marker.py`.
- `.github/workflows/attest-release-assets.yml`.
- `tests/test_session_tools.py`, `tests/test_session_tools_updater.py`, `tests/test_release_builder.py`, `tests/test_offline_acceptance.py`, `tests/test_live_canary.py`.

---

### Task 1: Repair the date-dependent baseline tests

- [ ] Add a regression expectation that provider-marker tests use an injected/frozen `now` for age-sensitive eligibility instead of depending on the real calendar.
- [ ] Re-run the four current failures and confirm they fail only because fixtures dated `2026-07-26` are evaluated against the real current date.
- [ ] Change tests/helpers, not the seven-day production validation, so every age-sensitive case supplies deterministic `now`. Run `python -m pytest -q tests/test_provider_marker.py` to GREEN.
- [ ] Commit `test: make Claude eligibility fixtures time deterministic`.

### Task 2: Import approved skill and cold reference

- [ ] Add RED native-contract tests for 38 capability skills, 23 cold records and exact approved `ru-writing-style` SHA-256/size.
- [ ] Copy the approved bytes, add catalog/migration records and `cold/memory/reference_officecli.md`; retain Foundation-managed wording and no active OfficeCLI skill/plugin/MCP registration.
- [ ] Recompute token reports and README counts. Run focused native/token tests to GREEN. Commit `feat: add approved Russian writing skill and OfficeCLI reference` including generated `AGENTS.md`.

### Task 3: Session asset, baseline and granular ownership

- [ ] Add RED strict/deterministic session asset tests with the same limits and path/hash/collision rules as the audited design.
- [ ] Create `tools/session_tools.py`; extend `ReleaseBuild` and `release_binding_from_manifest` for `session-tools-claude-0.1.1.zip`.
- [ ] Add package baseline and granular `.claude/skills/<id>` ownership including `sync-base`, excluding `ru-writing-style`; preserve legacy broad-plus-local homes.
- [ ] Run `tests/test_session_tools.py`, `test_release_builder.py`, `test_native_contract.py` to GREEN. Commit `feat: build Claude session tool assets`.

### Task 4: Session updater while preserving legacy owner auto-pull

- [ ] Add RED updater tests for immutable `gh` chain, strict JSON, one 30-second clock, journal before staging, killed apply recovery, baseline recovery, unmanaged collision, offline/lock/missing-gh and Cyrillic.
- [ ] Implement `runtime/update-session-tools.ps1`. Update packaged `runtime/hooks/check-release.ps1` and `runtime/settings.json` so SessionStart runs the updater then keeps the daily release check with enough timeout for cleanup.
- [ ] Add explicit tests that live legacy `~/.claude/scripts/auto-pull.ps1` and current `~/.claude/settings.json` are not modified by native package build/install.
- [ ] Run updater/native tests in PowerShell 7 and 5.1. Commit `feat: update Claude session tools before launch`.

### Task 5: Shared OfficeCLI and immutable three-asset release chain

- [ ] Add RED Foundation acceptance/tamper tests for OfficeCLI payload, shim, policy and launcher.
- [ ] Extend builder/promotion/verifier to bind release manifest, main ZIP and session ZIP; add `.github/workflows/attest-release-assets.yml` and contract test requiring attestation for every asset.
- [ ] Update offline matrix for clean, legacy broad and broad-plus-local homes; assert local skill and auth/session sentinels survive install/doctor/rollback.
- [ ] Run release/offline/promotion/verifier suites to GREEN. Commit `feat: bind Claude package to Foundation shared tools`.

### Task 6: Managed canary and truthful full-release evidence

- [ ] Add RED canary/final-evidence tests requiring `claude-managed.exe`, updater evidence and `ru-writing-style` before process discovery; keep direct fallback separate.
- [ ] Update canary/final evidence, counts and package acceptance. Do not relax exact Claude Code `2.1.218`.
- [ ] Run full `python -m pytest -q` and offline candidate acceptance against Foundation `0.3.0`.
- [ ] Obtain the five explicit eligibility attestations, install/use exact Claude Code `2.1.218`, run one approved provider marker and the isolated zero-model lifecycle canary.
- [ ] If and only if all gates PASS, promote without rebuilding ZIP, publish immutable stable assets, verify every asset and attestation, then create package acceptance. Otherwise keep `FULL_RELEASE_CLAUDE=NOT_PASS` and report the exact blocker.
- [ ] Run independent whole-branch and release-evidence audit before distribution.

## Plan Self-Review

- Existing calendar failures are isolated before feature work.
- Legacy Claude owner automation stays untouched; native session updates are additive.
- Full distribution cannot be produced by owner override or personal smoke alone.
