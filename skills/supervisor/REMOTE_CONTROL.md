# Layer 2 — Human-Supervised Sessions via `claude remote-control`

## What Layer 2 Is

The supervised architecture has two layers:

| Layer | Mode | Approver | Use when |
|-------|------|----------|----------|
| **Layer 1 — arbiter** | Headless, automatic | Code logic (`can_use_tool`) | Background/batch runs; no human needs to watch every step |
| **Layer 2 — remote-control** | Live interactive server | **Human only** (phone / browser) | You want to watch and approve in real time from any device |

Layer 2 is the official `claude remote-control` server built into Claude Code.
It streams interactive sessions to **claude.ai/code** or the **Claude mobile app**,
where the account owner approves each action manually.

**There is no official programmatic third-party auto-approval for interactive
remote-control sessions.** Automation belongs in Layer 1.

---

## Launching a Remote-Control Server

```
claude remote-control
```

Run this in the directory where you want Claude to work.

**First-run prompt:**

```
Enable Remote Control? y
```

Type `y` once; subsequent runs skip the prompt.

The command starts a **persistent server** (process stays alive), pre-creates one
session in the current directory, and registers it on the account so it appears
on connected devices.

### Key flags (Claude Code 2.1.195)

| Flag | Default | Description |
|------|---------|-------------|
| `--name <name>` | auto | Session name shown in claude.ai/code |
| `--permission-mode <mode>` | default | Permission mode for spawned sessions: `acceptEdits`, `auto`, `bypassPermissions`, `default`, `dontAsk`, `plan` |
| `--spawn <mode>` | `same-dir` | Session isolation: `same-dir`, `worktree`, `session` |
| `--capacity <N>` | 32 | Max concurrent sessions |
| `--[no-]create-session-in-dir` | on | Pre-create a session in cwd on start |
| `--remote-control-session-name-prefix <prefix>` | hostname | Prefix for auto-generated session names (env: `CLAUDE_REMOTE_CONTROL_SESSION_NAME_PREFIX`) |
| `--debug-file <path>` | — | Write debug logs to file |
| `-v, --verbose` | — | Verbose output |

---

## Connecting from Phone or Browser

1. Open **claude.ai/code** (browser) or the **Claude mobile app**.
2. The registered session(s) appear automatically — no URL to type.
3. Tap / click a session to open the interactive terminal.
4. Every action Claude tries to take prompts **you** for approval.

> Prerequisites: you must be **logged in** with a Claude account that has a
> subscription. Run `claude` first in the target directory to accept the
> workspace trust dialog if prompted.

---

## Permission Mode for Spawned Sessions

The `--permission-mode` flag controls what Claude is allowed to do without an
explicit per-action prompt inside a spawned session:

- `default` — standard permission gates (recommended for remote use)
- `acceptEdits` — auto-accepts file edits, still prompts on commands
- `auto` — reduces prompts; human still approves from the remote UI
- `bypassPermissions` / `dontAsk` — minimizes prompts (use with care)
- `plan` — plan-only mode, no writes executed

---

## Key Facts

### Approval is HUMAN-only

In Layer 2, every sensitive action must be approved by the **human holding the
phone or browser session**. There is no official mechanism to wire a bot or
script into the interactive approval flow. If you need automated gating, that is
Layer 1 (the headless arbiter with `can_use_tool`).

### Privacy caveat — session discovery is account-wide

When a remote-control server registers a session, **all sessions associated with
the subscription OAuth token become visible** to any device connected to that
account — not only the local session you just started. Be aware that colleagues
or other devices sharing the same Claude account will see every registered
session.

### Live re-verification requires owner consent

Starting `claude remote-control` (without `--help`) immediately:

1. Creates a persistent server process.
2. Registers a new session on the account.
3. Makes it visible to all connected devices.

This is an account-touching action. **Do not start a live server to test the
command unless the account owner explicitly consents.**

---

## When to Use Layer 2 vs Layer 1

| Situation | Use |
|-----------|-----|
| Running unattended overnight batch jobs | Layer 1 (arbiter) |
| You are at a computer and actively supervising | Either — but Layer 1 is lighter |
| You are away from the workstation (phone / tablet) | **Layer 2** |
| You want a human sign-off for each file write | **Layer 2** |
| You need programmatic allow/deny logic per tool | Layer 1 |
| You need an audit trail with structured logs | Layer 1 |
| Quick interactive session from another device | **Layer 2** |

---

## Reference

- Official docs entry point: <https://claude.ai/code>
- Verified on Claude Code **2.1.195** (2026-07-01).
- Key flags above captured verbatim from `claude remote-control --help`.
