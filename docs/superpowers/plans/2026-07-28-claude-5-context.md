# Claude 5 Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace duplicated Claude hot-context instructions with a compact,
discovery-driven Claude 5 context layer while preserving release, privacy, and
verification boundaries.

**Architecture:** The installed `CLAUDE.md` is a small HOT kernel. Native agent
and skill frontmatter provides WARM discovery, while full instructions remain
COLD and are loaded only on demand. Portable project memory records material
cross-device state rather than duplicating local auto-memory.

**Tech Stack:** Markdown, Python 3.12, pytest, PowerShell 7 and 5.1, deterministic
ZIP release builder, Foundation installer acceptance harness.

## Global Constraints

- Do not edit generated candidates, fake homes, fixtures, temporary worktrees,
  historical handoffs, or session reports as source files.
- Keep authentication, privacy, provider-policy, and employee-release gates
  explicit and fail-closed.
- Do not enable auto-memory, select a model/effort, make model requests, publish,
  or touch an employee home during the documentation refactor.
- Use UTF-8 with LF in repository sources.

---

### Task 1: Add the context-budget and reference-integrity regression

**Files:**
- Modify: `tests/test_native_contract.py`

**Interfaces:**
- Consumes: `tools.token_audit.audit_static_context(Path, "claude")`.
- Produces: a failing contract for the 2,000-byte HOT budget, 85% total static
  reduction, and absence of known stale global-CLAUDE references.

- [ ] **Step 1: Write the failing test**

Add assertions that the real HOT bytes are at most `2000`, that
`base_controlled_startup_reduction >= 0.85`, and that active `agents/*.md` plus
`skills/**` do not contain references claiming full rules live in a numbered
or named global `CLAUDE.md` section.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
py -3.12 -m pytest tests/test_native_contract.py `
  -k "hot_layer or static_token or stale_global" -vv
```

Expected: failure on the current 2,988-byte HOT file, the current 83.32%
reduction, or stale section references.

### Task 2: Implement the compact runtime and repair active references

**Files:**
- Modify: `CLAUDE.md`
- Modify: active files under `agents/*.md`
- Modify: active files under `skills/**` that cite removed global sections
- Modify: `README.md`

**Interfaces:**
- Consumes: native discovery metadata in `agents/*.md` and `skills/*/SKILL.md`.
- Produces: the HOT runtime installed at `~/.claude/CLAUDE.md`.

- [ ] **Step 1: Replace routing enumeration with principles**

Keep language behavior, inspect-first, deterministic-first, progressive skill
loading, review boundaries, source-backed norms, and the security/privacy
kernel. Remove the manual catalog and procedural negations already represented
by native discovery.

- [ ] **Step 2: Point active documentation to its real canonical home**

Make `karpathy-guidelines`, `web-access`, `norm-lookup`, and other selected
skills canonical for their detailed behavior. Remove claims that full
formulations live in a removed global section or numbered rule.

- [ ] **Step 3: Run the focused tests and verify GREEN**

Run the Task 1 command. Expected: all selected tests pass.

### Task 3: Simplify every authoritative project CLAUDE source

**Files:**
- Modify: `skills/project-memory/templates/core/root-CLAUDE.md.tmpl`
- Modify: `skills/project-memory/templates/core/CLAUDE.md.tmpl`
- Modify: workspace `CLAUDE.md`
- Modify: workspace `Claude/CLAUDE.md`
- Modify: workspace `этаж2/manager_station/CLAUDE.md`
- Regenerate: workspace `AGENTS.md` project section from the two workspace
  CLAUDE sources without changing the global preference layer.

**Interfaces:**
- Consumes: portable `Claude/STATUS.md` and `Claude/ЖУРНАЛ СЕССИЙ.md`.
- Produces: concise project bootstrap instructions and matching templates.

- [ ] **Step 1: Change session logging to material-state logging**

Describe `STATUS.md` as the current portable snapshot and the journal as a
compact decision/handoff history. Update them when work materially changes
state rather than declaring every unlogged session invalid.

- [ ] **Step 2: Keep only non-obvious project gotchas**

Retain relative paths, cloud-placeholder hydration, one-device-at-a-time, and
source-of-truth boundaries. Remove generic work instructions.

- [ ] **Step 3: Verify generated project instructions**

Run the project-memory generator against the workspace and compare its project
section with both CLAUDE sources. Expected: no stale numbered global-base
reference and no unrelated global preferences overwritten.

### Task 4: Verify and rebuild exact offline evidence

**Files:**
- Update: `reports/static-token-audit.json`
- Regenerate: `dist/candidate-0.1.0/*`

**Interfaces:**
- Consumes: clean committed source and accepted Foundation engine `0.2.1`.
- Produces: deterministic candidate evidence bound to the new source commit and
  exact candidate bytes.

- [ ] **Step 1: Run focused and full tests**

```powershell
py -3.12 -m pytest tests/test_native_contract.py -vv
py -3.12 -m pytest -q
```

- [ ] **Step 2: Regenerate the static token audit**

```powershell
py -3.12 tools/token_audit.py --target claude
```

Expected: `STATIC_TOKEN_ACCEPTANCE=PASS`, reduction at least `0.85`, and
`MATCHED_AB=NOT_RUN`.

- [ ] **Step 3: Build and accept twice through both PowerShell runtimes**

Run the documented `tools/run_offline_acceptance.py` command using the already
accepted Foundation evidence. Expected: deterministic ZIP equality and PASS
for plan/install/doctor/inventory/rollback in PowerShell 7 and 5.1.

### Task 5: Resume the guarded full-release sequence

**Files:**
- Update only evidence and release artifacts produced by the existing release
  tools.

**Interfaces:**
- Consumes: reviewed commits and exact offline candidates for Foundation,
  Claude, Codex, and OpenCode.
- Produces: immutable target releases, package acceptances, employee installer,
  clean-PC pilot evidence, and final `PROGRAM_RELEASE=3/3`.

- [ ] **Step 1: Obtain the explicit online gates**

Before execution, obtain separate owner authorization for the four paid Codex
matched-A/B model calls, provider/account eligibility markers, pushes, and
immutable publication. VPN or proxy transport must not bypass provider region
or safeguard policy.

- [ ] **Step 2: Run isolated provider and client canaries**

Use isolated homes, exact accepted clients, and privacy-safe evidence. Run
Claude doctor in the isolated canary environment; do not use a working employee
profile.

- [ ] **Step 3: Publish and verify exact bytes**

Publish the already accepted assets, verify release and asset attestations, and
create the three `package-acceptance.json` records without rebuilding.

- [ ] **Step 4: Build and pilot the employee installer**

Build InternalUnsigned installer `v0.3.0`, run the full hub EXE canary, upload
the same bytes as draft, then perform a clean-PC employee pilot.

- [ ] **Step 5: Create the immutable employee release**

Only after the pilot and independent audit pass, publish the immutable employee
release and update program state to `3/3`. Public signed distribution remains a
separate release class.
