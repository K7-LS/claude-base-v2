# rules.py
import re
import shlex

SAFE_TOOLS = {"Read", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite",
              "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "NotebookRead"}
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}

# запись в чувствительные пути (конфиг Claude, хуки, автозагрузка, ssh) — эскалация:
# перезапись settings.json/rules.py = обход надзора персистентностью, не «low risk»
SENSITIVE_WRITE = re.compile(
    r"(\.claude[/\\])|(\.git[/\\]hooks)|(\.ssh[/\\])|(\.bashrc|\.zshrc|\.profile|profile\.ps1)"
    r"|(start ?menu[/\\]programs[/\\]startup)|(\bautostart\b)", re.I)

# опасное — эскалировать (никогда не тихий allow). POSIX + Windows (харденинг 2026-07-02)
DENY_SUBSTR = ["rm -rf", "rm -fr", "mkfs", "dd if=", ":(){", "> /dev/sda",
               "format-volume", "clear-disk", "vssadmin delete", "invoke-expression"]
DENY_TOKENS = [("git", "push", "--force"), ("git", "push", "-f"),
               ("git", "reset", "--hard"), ("drop", "database"), ("drop", "table"),
               ("rm", "-r", "-f"), ("rm", "-f", "-r"), ("chmod", "777"), ("chmod", "-r", "777"),
               # Windows-эквиваленты сноса (порядок флагов не важен — проверка по вхождению)
               ("remove-item", "-recurse", "-force"), ("rd", "/s"), ("rmdir", "/s"),
               ("del", "/s"), ("reg", "delete")]
WRAPPERS = {"bash", "sh", "zsh", "python", "python3", "node", "perl", "ruby", "eval",
            "powershell", "pwsh", "cmd"}
# флаги обёрток, прячущие команду внутрь строки (не видим → эскалация).
# POSIX короткие + канонические PowerShell/cmd формы: -Command/-EncodedCommand/-File, /c, /k
WRAPPER_FLAGS = {"-c", "-e", "-ce", "-command", "-encodedcommand", "-enc", "-ec",
                 "-file", "/c", "/k"}
# пайп-в-интерпретатор: проверяем ПЕРВОЕ слово сегмента после «|» (не подстроку и не
# весь cmd — иначе ложнит на «python gen.py | tee»)
PIPE_TARGETS = {"sh", "bash", "zsh", "python", "python3", "perl", "ruby", "node",
                "pwsh", "powershell", "cmd", "iex"}

def _analyze_bash(cmd: str) -> tuple[str, str]:
    """→ (action, detail). detail называет КОНКРЕТНЫЙ сработавший паттерн для
    человекочитаемого алерта; при allow detail пустой."""
    low = cmd.lower()
    for s in DENY_SUBSTR:
        if s in low:
            return "escalate", f"dangerous substring «{s}»"
    try:
        toks = [t.lower() for t in shlex.split(cmd)]
    except ValueError:
        return "escalate", "unparseable command"  # неразбираемое — не рисковать
    # обёртки с флагом-строкой (bash -c / powershell -Command / cmd /c …) — не видим внутрь
    if toks and toks[0] in WRAPPERS and any(t in WRAPPER_FLAGS for t in toks[1:]):
        flag = next(t for t in toks[1:] if t in WRAPPER_FLAGS)
        return "escalate", f"wrapper hides command ({toks[0]} {flag})"
    # пайп-в-интерпретатор: первое слово каждого сегмента после «|»
    if "|" in cmd:
        for seg in cmd.split("|")[1:]:
            first = seg.strip().split()
            if first and first[0].lower().strip("\"'") in PIPE_TARGETS:
                return "escalate", f"pipe into interpreter ({first[0].strip(chr(34)+chr(39)).lower()})"
    for combo in DENY_TOKENS:
        if all(t in toks for t in combo):
            return "escalate", "dangerous tokens «" + " ".join(combo) + "»"
    return "allow", ""

def decide(tool_name: str, tool_input: dict) -> dict:
    if tool_name in SAFE_TOOLS:
        return {"action": "allow", "reason": "safe tool"}
    if tool_name in WRITE_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("path")
                   or tool_input.get("notebook_path") or "")
        if SENSITIVE_WRITE.search(path):
            return {"action": "escalate", "reason": f"write to sensitive path: {path[:120]}"}
        return {"action": "allow", "reason": "file write (low risk)"}
    if tool_name == "Bash":
        a, detail = _analyze_bash(str(tool_input.get("command", "")))
        reason = f"bash: {detail}" if detail else "bash: allow"
        return {"action": a, "reason": reason}
    return {"action": "escalate", "reason": "unknown tool — no rule"}
