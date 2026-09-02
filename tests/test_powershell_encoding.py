"""Скрипты базы обязаны читаться Windows PowerShell 5.1.

Без BOM PowerShell 5.1 читает .ps1 как ANSI: кириллица рассыпается,
кавычки внутри строк разъезжаются, и скрипт падает с ParserError ещё до
первой команды. pwsh 7 читает UTF-8 сам — поэтому дефект не виден на
машине разработчика и проявляется только у пользователя без pwsh.
Наблюдалось 2026-09-02 на рабочей станции сотрудника.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Каталоги исходников, попадающие к пользователю; рабочие копии сборок
# (.work, dist) не проверяем — они пересоздаются.
SOURCE_DIRECTORIES = ("control-skills", "runtime", "skills", "scripts", "tools")


def _cyrillic(text: str) -> bool:
    return any("Ѐ" <= ch <= "ӿ" for ch in text)


def test_shipped_powershell_scripts_with_cyrillic_carry_utf8_bom() -> None:
    offenders = []
    for directory in SOURCE_DIRECTORIES:
        root = ROOT / directory
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.ps1")):
            payload = path.read_bytes()
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                offenders.append(f"{path.relative_to(ROOT)} (не UTF-8)")
                continue
            if _cyrillic(text) and not payload.startswith(b"\xef\xbb\xbf"):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], (
        "эти .ps1 содержат кириллицу без UTF-8 BOM и упадут с ParserError "
        "в Windows PowerShell 5.1: " + ", ".join(offenders)
    )
