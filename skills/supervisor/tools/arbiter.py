# arbiter.py — official canUseTool supervisor (SDK path)
# Wires rules.decide() into the SDK's can_use_tool callback.
# Hook callback signature in 0.2.110: (hook_input, session_id, context) -> dict
import asyncio, sys, io

def _configure_stdout():
    # Force UTF-8 output on Windows (avoids cp1251 UnicodeEncodeError on SDK messages).
    # Called from main(), NOT at import — importing arbiter must not mutate global stdout.
    if sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from rules import decide
from notify import escalate
from claude_agent_sdk import (
    query, ClaudeAgentOptions,
    PermissionResultAllow, PermissionResultDeny, HookMatcher,
)

async def can_use_tool(tool_name: str, input_data: dict, context) -> PermissionResultAllow | PermissionResultDeny:
    # fail-safe: any error in decide() → deny by default, never a silent allow
    try:
        d = decide(tool_name, input_data)
    except Exception as e:
        escalate(f"{tool_name} — decide() raised {e!r}")
        return PermissionResultDeny(message="supervisor: internal error — denied by default")
    if d["action"] == "allow":
        return PermissionResultAllow(updated_input=input_data)
    # deny + escalate — dangerous/unknown is NEVER silently allowed.
    # Surface the command explicitly so the human alert isn't cut off mid-command.
    _cmd = input_data.get("command") if isinstance(input_data, dict) else None
    _detail = str(_cmd) if _cmd else str(input_data)
    escalate(f"{tool_name}: {d['reason']} | {_detail[:500]}")
    return PermissionResultDeny(message=f"supervisor: {d['reason']}")

# Dummy PreToolUse hook — correct signature for SDK 0.2.110:
# (hook_input: PreToolUseHookInput, session_id: str|None, context: HookContext) -> dict
# Empirically NOT required in 0.2.110 (can_use_tool fires without it) — kept as a defensive no-op.
async def _keepalive_hook(hook_input, session_id, context):
    return {}

def _options():
    # Pin permission_mode="default" + setting_sources=[] so the arbiter's OWN worker
    # cannot route around the gate: the SDK does NOT invoke can_use_tool for calls
    # already permitted by bypassPermissions/acceptEdits or by ambient permissions.allow
    # rules in ~/.claude settings. Isolating settings ([]) + default mode keeps every
    # prompt-worthy call flowing through the arbiter. (Gating calls the SDK auto-allows
    # entirely would require a PreToolUse hook — see README "Scope & guarantee".)
    base = dict(can_use_tool=can_use_tool, permission_mode="default", setting_sources=[])
    try:
        return ClaudeAgentOptions(
            **base,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[_keepalive_hook])]},
        )
    except Exception:
        return ClaudeAgentOptions(**base)

async def _prompt_stream(text: str):
    """Wrap a plain string into the AsyncIterable[dict] streaming format
    required by can_use_tool in SDK 0.2.110."""
    yield {"type": "user", "message": {"role": "user", "content": text}}

async def main(prompt: str):
    _configure_stdout()
    async for msg in query(prompt=_prompt_stream(prompt), options=_options()):
        print(msg)

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "say hi"))
