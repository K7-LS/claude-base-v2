# -*- coding: utf-8 -*-
"""Плоский AGENTS.md проекта из CLAUDE.md (П9, Эпик 1 мульти-LLM).
Запуск: python gen_project_agents.py <project_root>. Чужой AGENTS.md (без маркера) не трогает."""
import re
import os
import sys
import tempfile
from pathlib import Path

MARKER = "generated-by: gen_project_agents"
OWNERSHIP_LINE = f"<!-- {MARKER} -->"
SOURCES = ("CLAUDE.md", "Claude/CLAUDE.md")

def render_project_agents(root: Path):
    parts = []
    for rel in SOURCES:
        p = root / rel
        if not p.exists():
            continue
        t = p.read_text(encoding="utf-8")
        t = re.sub(r"^@.*$", "", t, flags=re.M)              # @import — Claude-специфика, в плоском файле не работает
        t = t.replace("Claude Code", "агентная среда")        # vendor-нейтрализация
        parts.append(f"<!-- источник: {rel} -->\n\n" + t.strip())
    if not parts:
        return None
    head = (f"{OWNERSHIP_LINE}\n"
            "<!-- НЕ править руками: источник — CLAUDE.md проекта; перегенерация:\n"
            "     python ~/.claude/skills/project-memory/tools/gen_project_agents.py . -->\n\n")
    return head + "\n\n---\n\n".join(parts) + "\n"

def project_agents_status(root: Path, rendered=None) -> str:
    """Определи состояние AGENTS.md по происхождению и ожидаемому содержимому."""
    if rendered is None:
        rendered = render_project_agents(root)
    if rendered is None:
        return "no-source"
    dst = root / "AGENTS.md"
    if dst.is_symlink():
        return "foreign"
    if not dst.exists():
        return "missing"
    if not dst.is_file():
        return "foreign"
    actual = dst.read_text(encoding="utf-8")
    first = next(iter(actual.splitlines()), "")
    if first != OWNERSHIP_LINE:
        return "foreign"
    return "current" if actual == rendered else "stale"


def main(root: Path, quiet_current: bool = False) -> int:
    out = render_project_agents(root)
    state = project_agents_status(root, out)
    if state == "no-source":
        print("[gen_project_agents] CLAUDE.md не найден — проект без ядра, выходим")
        return 1
    dst = root / "AGENTS.md"
    if state == "foreign":
        print(f"[gen_project_agents] foreign: {dst} создан не нами — не трогаю "
              "(считай его каноном проекта; расхождение с CLAUDE.md согласуй отдельно)")
        return 2
    if state == "current":
        if not quiet_current:
            print(f"[gen_project_agents] current: {dst} актуален — без изменений")
        return 0
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dst.name}.", suffix=".tmp", dir=dst.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as tmp:
            tmp.write(out)
        os.replace(tmp_name, dst)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
    action = "создан" if state == "missing" else "обновлён"
    print(f"[gen_project_agents] {state}: {action} {dst}")
    return 0

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    args = sys.argv[1:]
    quiet_current = "--quiet-current" in args
    args = [arg for arg in args if arg != "--quiet-current"]
    sys.exit(main(Path(args[0]).resolve() if args else Path.cwd(), quiet_current))
