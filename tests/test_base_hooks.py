"""Хуки базы: шаблон настроек, сверка settings.json и остатки прежней базы.

Движок Foundation не ведёт settings.json, поэтому набор хуков релиза
доставляет сама база: скрипты лежат в runtime/hooks, а runtime/hygiene.ps1
приводит к ним пользовательские настройки и перечисляет то, что осталось
от прежней базы. Тесты идут в обеих редакциях PowerShell.
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
POWERSHELLS = [
    value
    for value in (shutil.which("pwsh"), shutil.which("powershell.exe"))
    if value
]
SPEC = importlib.util.spec_from_file_location(
    "native_release_builder_hooks",
    ROOT / "tools" / "release_builder.py",
)
assert SPEC and SPEC.loader
release_builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_builder
SPEC.loader.exec_module(release_builder)

EXPECTED_HOOKS = [
    "PreToolUse:screenshot|zoom:screenshot-source-zoom",
    "SessionStart:resume:check-release",
    "SessionStart:resume:graph-staleness-check",
    "SessionStart:resume:project-memory-session-start",
    "SessionStart:resume:regen-tom-widgets",
    "SessionStart:startup:check-release",
    "SessionStart:startup:graph-staleness-check",
    "SessionStart:startup:project-memory-session-start",
    "SessionStart:startup:regen-tom-widgets",
    "UserPromptSubmit::grilling-detector",
    "UserPromptSubmit::routing-detector",
    "UserPromptSubmit::understanding-map-detector",
]
JOURNAL = "ЖУРНАЛ СЕССИЙ.md"
SETTINGS_FINDINGS = {"settings_unreadable", "hooks_not_canonical"}


def _template_hooks() -> dict[str, list[dict[str, object]]]:
    return json.loads((RUNTIME / "settings.json").read_text(encoding="utf-8"))[
        "hooks"
    ]


def _home_env(home: Path, **extra: str) -> dict[str, str]:
    drive, tail = os.path.splitdrive(str(home))
    return {
        **os.environ,
        "USERPROFILE": str(home),
        "HOMEDRIVE": drive,
        "HOMEPATH": tail,
        **extra,
    }


def _hygiene(
    executable: str, home: Path, *arguments: str, runtime: Path = RUNTIME
) -> dict[str, object]:
    result = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(runtime / "hygiene.ps1"),
            "-HomePath",
            str(home),
            *arguments,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.lstrip("\ufeff"))


def _run_hook(
    executable: str,
    script: Path,
    home: Path,
    payload: dict[str, object] | None = None,
    **extra: str,
) -> str:
    result = subprocess.run(
        [executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        input="" if payload is None else json.dumps(payload),
        env=_home_env(home, **extra),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.lstrip("\ufeff")


def _command(script: str, root: str = "scripts") -> dict[str, object]:
    return {
        "type": "command",
        "command": f'& "$HOME\\.claude\\{root}\\{script}"',
        "shell": "powershell",
        "timeout": 10,
    }


INTEROP_GROUP = {
    "matcher": "startup|resume",
    "hooks": [
        {
            "type": "command",
            "command": (
                "Start-Process -WindowStyle Hidden python -ArgumentList "
                '"$HOME\\.claude\\scripts\\interop_chat_server.py"'
            ),
            "shell": "powershell",
            "timeout": 10,
            "async": True,
        }
    ],
}
MEMORY_HOOK = {"type": "command", "command": "memory-bridge stop", "timeout": 5}
PREVIOUS_HOOKS = {
    "UserPromptSubmit": [
        {
            "hooks": [
                _command("grilling-detector.ps1"),
                _command("routing-detector.ps1"),
                _command("understanding-map-detector.ps1"),
            ]
        }
    ],
    "SessionStart": [
        {
            "matcher": "startup",
            "hooks": [
                _command("auto-pull.ps1"),
                _command("check-release-wrapper.ps1"),
                {
                    "type": "command",
                    "command": (
                        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
                        '"$env:USERPROFILE\\.claude\\base\\runtime\\hooks\\check-release.ps1"'
                    ),
                    "timeout": 40,
                },
                _command("codex-drift-check.ps1"),
                _command("graph-staleness-check.ps1"),
                _command("session_start.ps1", "skills\\project-memory\\tools\\hooks"),
                _command("regen-tom-widgets.ps1"),
            ],
        },
        {
            "matcher": "resume",
            "hooks": [_command("session_start.ps1", "scripts\\project-memory-hooks")],
        },
        INTEROP_GROUP,
    ],
    "SessionEnd": [{"matcher": "*", "hooks": [_command("auto-push.ps1")]}],
    "Stop": [
        {
            "matcher": "*",
            "hooks": [
                _command("session_end.ps1", "skills\\project-memory\\tools\\hooks"),
                MEMORY_HOOK,
            ],
        }
    ],
    "PostToolUse": [
        {"matcher": "*", "hooks": [_command("log-tool-usage.ps1")]},
        {"matcher": "Edit|Write", "hooks": [_command("codex-autosync.ps1")]},
    ],
    "PreToolUse": [
        {"matcher": "screenshot|zoom", "hooks": [_command("screenshot-source-zoom.ps1")]}
    ],
}
PREVIOUS_SCRIPTS = {
    "scripts/auto-pull.ps1",
    "scripts/auto-push.ps1",
    "scripts/check-release-wrapper.ps1",
    "scripts/codex-autosync.ps1",
    "scripts/codex-drift-check.ps1",
    "scripts/graph-staleness-check.ps1",
    "scripts/grilling-detector.ps1",
    "scripts/log-tool-usage.ps1",
    "scripts/project-memory-hooks/session_start.ps1",
    "scripts/regen-tom-widgets.ps1",
    "scripts/routing-detector.ps1",
    "scripts/screenshot-source-zoom.ps1",
    "scripts/understanding-map-detector.ps1",
    "skills/project-memory/tools/hooks/session_end.ps1",
    "skills/project-memory/tools/hooks/session_start.ps1",
}
# Нарочно неровное форматирование: сверка обязана оставить его как есть.
PREFIX = (
    "{\n"
    '  "cleanupPeriodDays": 365,\n'
    '  "note": "кавычка \\" и слэш \\\\, дата 2026-10-03T14:34:00Z, \\u0444 & <тег>",\n'
    '  "ratio": 1.50,\n'
    '  "big": 12345678901234567890,\n'
    '  "empty": {},   "list": [ ],\n'
    "  "
)
SUFFIX = (
    ",\n"
    '  "statusLine": {"type": "command", "command": "ccusage statusline"},\n'
    '  "enabledPlugins": {\n    "example@marketplace": false\n  }\n'
    "}\n"
)


def _previous_settings_text() -> str:
    return (
        PREFIX
        + '"hooks": '
        + json.dumps(PREVIOUS_HOOKS, ensure_ascii=False, indent=2)
        + SUFFIX
    )


def _write_settings(home: Path, payload: str | bytes) -> Path:
    path = home / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    path.write_bytes(payload)
    return path


def _install_runtime(home: Path) -> Path:
    """Раскладка установленного слоя: ~/.claude/base/runtime и VERSION."""
    base = home / ".claude" / "base"
    runtime = base / "runtime"
    shutil.copytree(RUNTIME, runtime)
    (runtime / "settings.json").rename(runtime / "settings.template.json")
    (base / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    return runtime


def _leftover_files(home: Path) -> list[str]:
    return sorted(
        item.name for item in (home / ".claude").glob("settings.json.hygiene-*")
    )


def test_settings_template_declares_only_base_runtime_hooks():
    settings = json.loads((RUNTIME / "settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit", "PreToolUse"}

    # Запуск через powershell.exe с Bypass не зависит от политики выполнения ПК.
    pattern = re.compile(
        r"^powershell\.exe -NoProfile -ExecutionPolicy Bypass -File "
        r'"\$HOME\\\.claude\\base\\runtime\\hooks\\([a-z-]+\.ps1)"$'
    )
    count = 0
    for groups in hooks.values():
        for group in groups:
            assert set(group) <= {"matcher", "hooks"}
            for hook in group["hooks"]:
                count += 1
                assert set(hook) == {"type", "command", "shell", "timeout"}
                assert hook["type"] == "command"
                assert hook["shell"] == "powershell"
                script = pattern.match(hook["command"])
                assert script, hook["command"]
                assert (RUNTIME / "hooks" / script.group(1)).is_file()
    assert count == len(EXPECTED_HOOKS)

    startup, resume = hooks["SessionStart"]
    assert (startup["matcher"], resume["matcher"]) == ("startup", "resume")
    assert startup["hooks"] == resume["hooks"]
    assert startup["hooks"][0]["command"].endswith('check-release.ps1"')
    assert release_builder.declared_hooks(
        ROOT, release_builder.load_release_contract(ROOT)
    ) == EXPECTED_HOOKS


def test_release_builder_rejects_hooks_outside_the_launcher_form(tmp_path):
    contract = release_builder.load_release_contract(ROOT)
    settings = json.loads((RUNTIME / "settings.json").read_text(encoding="utf-8"))
    for command in (
        '& "$HOME\\.claude\\base\\runtime\\hooks\\check-release.ps1"',
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
        '"$HOME\\.claude\\base\\runtime\\hooks\\absent.ps1"',
        "echo ok; powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
        '"$HOME\\.claude\\base\\runtime\\hooks\\check-release.ps1"',
    ):
        repo = tmp_path / str(len(list(tmp_path.iterdir())))
        shutil.copytree(RUNTIME, repo / "runtime")
        changed = json.loads(json.dumps(settings))
        changed["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = command
        (repo / "runtime" / "settings.json").write_text(
            json.dumps(changed), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="base runtime launcher"):
            release_builder.declared_hooks(repo, contract)


def test_hook_policy_names_what_the_release_replaces_and_retires():
    policy = json.loads((RUNTIME / "hooks-policy.json").read_text(encoding="utf-8"))
    superseded = policy["superseded"]
    retired = policy["retired"]
    assert superseded == sorted(set(superseded))
    assert retired == sorted(set(retired))
    assert not set(superseded) & set(retired)
    assert set(superseded) | set(retired) == PREVIOUS_SCRIPTS | {
        "scripts/project-memory-hooks/session_end.ps1"
    }
    assert policy["legacy_roots"] == [
        "scripts",
        "skills/project-memory/tools/hooks",
    ]
    for path in superseded + retired + policy["previous_sync"]:
        assert any(path.startswith(root + "/") for root in policy["legacy_roots"])
    # Выгрузка состояния и телеметрия прежней базы только снимаются.
    assert {
        "scripts/auto-pull.ps1",
        "scripts/auto-push.ps1",
        "scripts/log-tool-usage.ps1",
    } <= set(retired)
    assert "scripts/auto-pull.ps1" in policy["previous_sync"]
    shipped = {path.name for path in (RUNTIME / "hooks").glob("*.ps1")}
    assert not shipped & {Path(path).name for path in retired}


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_reconcile_replaces_previous_base_hooks_and_keeps_the_rest(
    executable, tmp_path
):
    home = tmp_path / "home"
    original = _previous_settings_text()
    path = _write_settings(home, original)

    planned = _hygiene(executable, home, "-Action", "Reconcile", "-Check")
    assert planned["hooks"]["status"] == "WOULD_UPDATE"
    assert planned["legacy"] is None
    assert path.read_bytes() == original.encode("utf-8")
    assert not (home / ".claude" / "base").exists()

    report = _hygiene(executable, home, "-Action", "Reconcile")["hooks"]
    assert report["status"] == "UPDATED"
    assert report["foreign"] == 2
    assert report["replaced"] == 16
    assert set(report["removed"]) == PREVIOUS_SCRIPTS
    backup = home / Path(report["backup"])
    assert backup.read_bytes() == original.encode("utf-8")

    updated = path.read_text(encoding="utf-8")
    assert updated.startswith(PREFIX + '"hooks": {')
    assert updated.endswith(SUFFIX)
    template = _template_hooks()
    assert json.loads(updated)["hooks"] == {
        "SessionStart": template["SessionStart"] + [INTEROP_GROUP],
        "Stop": [{"matcher": "*", "hooks": [MEMORY_HOOK]}],
        "UserPromptSubmit": template["UserPromptSubmit"],
        "PreToolUse": template["PreToolUse"],
    }

    again = _hygiene(executable, home, "-Action", "Reconcile")["hooks"]
    assert again == {
        "status": "CANONICAL",
        "reason": None,
        "replaced": 0,
        "removed": [],
        "foreign": 2,
        "backup": None,
    }
    assert path.read_text(encoding="utf-8") == updated
    assert len(list(backup.parent.iterdir())) == 1
    assert _leftover_files(home) == []


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_reconcile_owns_only_whole_launchers_under_the_user_profile(
    executable, tmp_path
):
    home = tmp_path / "home"
    literal = str(home).replace("\\", "\\\\")
    # Чужие: то же имя в проекте, на другом диске, в подпапке, в аргументе,
    # в составной команде. Исходные токены строк и чисел должны уцелеть.
    foreign = [
        '{"type": "command", "command": "echo \\u0026 a\\/b \\ud83d", "timeout": 1.50}',
        '{"type": "command", "command": "& \\"$CLAUDE_PROJECT_DIR\\\\.claude\\\\scripts\\\\session_start.ps1\\""}',
        '{"type": "command", "command": "& \\"D:\\\\work\\\\repo\\\\.claude\\\\scripts\\\\session_end.ps1\\""}',
        '{"type": "command", "command": "& \\"D:\\\\sandbox\\\\.claude\\\\base\\\\runtime\\\\hooks\\\\my-test.ps1\\""}',
        '{"type": "command", "command": "& \\"$HOME\\\\.claude\\\\scripts\\\\mine\\\\session_end.ps1\\""}',
        '{"type": "command", "command": "echo \\"$HOME\\\\.claude\\\\scripts\\\\auto-push.ps1\\""}',
        '{"type": "command", "command": "& \\"$HOME\\\\.claude\\\\my.ps1\\" \\"$HOME\\\\.claude\\\\scripts\\\\log-tool-usage.ps1\\""}',
        '{"type": "command", "command": "& \\"$HOME\\\\.claude\\\\my.ps1\\"; & \\"$HOME\\\\.claude\\\\scripts\\\\codex-autosync.ps1\\""}',
    ]
    # Свои: тот же скрипт базы при любой записи домашнего каталога.
    owned = [
        f'{{"type": "command", "command": "& \\"{literal}\\\\.claude\\\\scripts\\\\grilling-detector.ps1\\""}}',
        '{"type": "command", "command": "& \'%USERPROFILE%/.claude/scripts/routing-detector.ps1\'"}',
        '{"type": "command", "command": "pwsh -NoProfile -File \\"~\\\\.claude\\\\scripts\\\\log-tool-usage.ps1\\""}',
        '{"type": "command", "command": "& \\"${env:USERPROFILE}\\\\.claude\\\\base\\\\runtime\\\\hooks\\\\retired-by-a-later-release.ps1\\""}',
    ]
    group = (
        '{"matcher": "Bash", "hooks": [\n    '
        + ",\n    ".join(foreign + owned)
        + "\n  ]}"
    )
    path = _write_settings(home, '{"hooks": {"PreToolUse": [' + group + "]}}")

    report = _hygiene(executable, home, "-Action", "Reconcile")["hooks"]
    assert report["status"] == "UPDATED"
    assert report["foreign"] == len(foreign)
    assert report["replaced"] == len(owned)
    assert report["removed"] == [
        "scripts/grilling-detector.ps1",
        "scripts/log-tool-usage.ps1",
        "scripts/routing-detector.ps1",
    ]

    updated = path.read_text(encoding="utf-8")
    assert '"echo \\u0026 a\\/b \\ud83d"' in updated
    assert '"timeout": 1.50' in updated
    kept = json.loads(updated)["hooks"]["PreToolUse"]
    assert kept[0] == _template_hooks()["PreToolUse"][0]
    assert kept[1] == {
        "matcher": "Bash",
        "hooks": [json.loads(row) for row in foreign],
    }
    assert _hygiene(executable, home, "-Action", "Reconcile")["hooks"]["status"] == (
        "CANONICAL"
    )


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_reconcile_adds_hooks_to_any_valid_settings_shape(executable, tmp_path):
    template = _template_hooks()
    cases: dict[str, bytes | None] = {
        "missing": None,
        "zero-bytes": b"",
        "blank": b"\n",
        "bom-only": b"\xef\xbb\xbf",
        "empty": b"{}",
        "hookless": b'{\n    "model": "x",\n    "env": {"A": "1"}\n}\n',
        "minified": b'{"a":1}',
        "bom-crlf": b'\xef\xbb\xbf{\r\n  "a": 1,\r\n  "hooks": {}\r\n}\r\n',
    }
    for name, payload in cases.items():
        home = tmp_path / name
        path = home / ".claude" / "settings.json"
        if payload is not None:
            _write_settings(home, payload)

        report = _hygiene(executable, home, "-Action", "Reconcile")["hooks"]
        assert report["status"] == "UPDATED", name
        assert report["removed"] == [], name
        assert (report["backup"] is None) == (payload is None), name
        if payload is not None:
            assert (home / Path(report["backup"])).read_bytes() == payload, name

        raw = path.read_bytes()
        settings = json.loads(raw.decode("utf-8-sig"))
        assert settings.pop("hooks") == template, name
        before = "" if payload is None else payload.decode("utf-8-sig")
        previous = json.loads(before) if before.strip() else {}
        previous.pop("hooks", None)
        assert settings == previous, name
        assert _leftover_files(home) == [], name

    hookless = (tmp_path / "hookless" / ".claude" / "settings.json").read_text(
        encoding="utf-8"
    )
    assert hookless.startswith(
        '{\n    "model": "x",\n    "env": {"A": "1"},\n    "hooks": {\n'
    )
    assert hookless.endswith("\n    }\n}\n")
    for name in ("bom-only", "bom-crlf"):
        marked = (tmp_path / name / ".claude" / "settings.json").read_bytes()
        assert marked.startswith(b"\xef\xbb\xbf{"), name
    marked = (tmp_path / "bom-crlf" / ".claude" / "settings.json").read_bytes()
    assert b"\n" not in marked.replace(b"\r\n", b"")
    assert (
        _hygiene(executable, tmp_path / "bom-crlf", "-Action", "Reconcile")["hooks"][
            "status"
        ]
        == "CANONICAL"
    )


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_reconcile_never_rewrites_settings_it_cannot_read(executable, tmp_path):
    deep = b'{"deep": ' + b"[" * 80 + b"]" * 80 + b', "hooks": {}}'
    large = b'{"pad": "' + b"x" * 600000 + b'", "hooks": {}}'
    cases = {
        "broken": b'{ "hooks": [',
        "repeated": b'{ "hooks": {}, "hooks": {} }',
        "not-object": b'["hooks"]',
        "trailing": b'{ "hooks": {} } x',
        "comment": b'{ // note\n "hooks": {} }',
        "cp1251": '{ "language": "русский", "hooks": {} }'.encode("cp1251"),
        "utf16": '{ "hooks": {} }'.encode("utf-16"),
        "raw-tab": b'{ "note": "a\tb", "hooks": {} }',
        "raw-newline": b'{ "note": "a\nb", "hooks": {} }',
        "bad-escape": b'{ "note": "a\\x", "hooks": {} }',
        "nbsp": '{\u00a0"hooks": {} }'.encode("utf-8"),
        "vertical-tab": b'{\x0b"hooks": {} }',
        "leading-zero": b'{ "n": 0123, "hooks": {} }',
        "wide-digits": '{ "n": \u0661\u0662, "hooks": {} }'.encode("utf-8"),
        "too-deep": deep,
        "too-large": large,
        "array": b'{ "hooks": [] }',
    }
    for name, payload in cases.items():
        home = tmp_path / name
        path = _write_settings(home, payload)
        report = _hygiene(executable, home, "-Action", "All")
        assert report["hooks"]["status"] == "BLOCKED", name
        assert report["hooks"]["reason"], name
        assert path.read_bytes() == payload, name
        assert not (home / ".claude" / "base").exists(), name
        assert _leftover_files(home) == [], name
        ids = [finding["id"] for finding in report["legacy"]["findings"]]
        expected = "hooks_not_canonical" if name == "array" else "settings_unreadable"
        assert [value for value in ids if value in SETTINGS_FINDINGS] == [
            expected
        ], name


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_reconcile_keeps_no_copy_when_the_file_cannot_be_replaced(
    executable, tmp_path
):
    home = tmp_path / "home"
    original = _previous_settings_text().encode("utf-8")
    path = _write_settings(home, original)
    os.chmod(path, stat.S_IREAD)
    try:
        for _ in range(2):
            report = _hygiene(executable, home, "-Action", "Reconcile")["hooks"]
            assert report["status"] == "BLOCKED"
            assert report["reason"] == "settings.json could not be replaced"
            assert report["backup"] is None
        assert path.read_bytes() == original
        backups = home / ".claude" / "base" / "state" / "settings-backups"
        assert not backups.exists() or list(backups.iterdir()) == []
        assert _leftover_files(home) == []
    finally:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_backups_are_not_duplicated_and_keep_the_first_state(executable, tmp_path):
    home = tmp_path / "home"
    path = _write_settings(home, _previous_settings_text())
    backups = home / ".claude" / "base" / "state" / "settings-backups"
    first = _hygiene(executable, home, "-Action", "Reconcile")["hooks"]["backup"]
    reconciled = path.read_bytes()

    # Тот же откат к прежнему состоянию второй копии не даёт.
    for _ in range(2):
        _write_settings(home, _previous_settings_text())
        again = _hygiene(executable, home, "-Action", "Reconcile")["hooks"]
        assert again["status"] == "UPDATED"
        assert again["backup"] == first
        assert path.read_bytes() == reconciled
    assert len(list(backups.iterdir())) == 1

    # Из разных состояний остаются самое первое и девять последних.
    for index in range(12):
        _write_settings(home, json.dumps({"n": index, "hooks": {}}))
        assert (
            _hygiene(executable, home, "-Action", "Reconcile")["hooks"]["status"]
            == "UPDATED"
        )
    names = sorted(item.name for item in backups.iterdir())
    assert len(names) == 10
    assert names[0] == Path(first).name
    kept = [json.loads((backups / name).read_text(encoding="utf-8")) for name in names[1:]]
    assert [item["n"] for item in kept] == list(range(3, 12))


def _previous_sync_script(home: Path, seconds: int) -> Path:
    """Заглушка синхронизации прежней базы: ждёт и вливает прежние хуки."""
    scripts = home / ".claude" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    shared = home / ".claude" / "settings.shared.json"
    shared.write_text(_previous_settings_text(), encoding="utf-8")
    script = scripts / "auto-pull.ps1"
    script.write_text(
        f"Start-Sleep -Seconds {seconds}\n"
        f"Copy-Item -LiteralPath '{shared}' "
        f"-Destination '{home / '.claude' / 'settings.json'}' -Force\n"
        f"Set-Content -LiteralPath '{home / 'merged.txt'}' -Value 'merged'\n",
        # BOM: в пути профиля бывает кириллица, а PowerShell 5.1 без BOM
        # читает скрипт как ANSI.
        encoding="utf-8-sig",
    )
    return script


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_reconcile_waits_for_the_previous_base_sync_to_finish(executable, tmp_path):
    home = tmp_path / "home"
    path = _write_settings(home, _previous_settings_text())
    script = _previous_sync_script(home, 4)
    sync = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    )
    try:
        report = _hygiene(
            executable, home, "-Action", "Reconcile", "-WaitPreviousSyncSeconds", "40"
        )["hooks"]
        assert sync.wait(timeout=30) == 0
    finally:
        sync.kill()
    # Сверка прошла после слияния прежней базы и сняла её хук синхронизации.
    assert (home / "merged.txt").is_file()
    assert report["status"] == "UPDATED"
    assert "scripts/auto-pull.ps1" in report["removed"]
    hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]
    assert hooks["SessionStart"][:2] == _template_hooks()["SessionStart"]
    assert "auto-pull" not in path.read_text(encoding="utf-8")
    assert _hygiene(executable, home, "-Action", "Reconcile")["hooks"]["status"] == (
        "CANONICAL"
    )


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_reconcile_defers_while_the_previous_base_sync_is_running(
    executable, tmp_path
):
    home = tmp_path / "home"
    original = _previous_settings_text().encode("utf-8")
    path = _write_settings(home, original)
    script = _previous_sync_script(home, 120)
    sync = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    )
    try:
        report = _hygiene(
            executable, home, "-Action", "All", "-WaitPreviousSyncSeconds", "2"
        )
    finally:
        sync.kill()
        sync.wait(timeout=30)
    assert report["hooks"]["status"] == "DEFERRED"
    assert report["hooks"]["reason"] == "the previous base sync is still running"
    assert report["hooks"]["backup"] is None
    assert path.read_bytes() == original
    assert not (home / ".claude" / "base").exists()
    deferred = [
        finding
        for finding in report["legacy"]["findings"]
        if finding["id"] == "hooks_not_canonical"
    ]
    assert [finding["detail"] for finding in deferred] == [
        "the previous base sync is still running"
    ]


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_scan_lists_previous_base_leftovers_without_changing_them(
    executable, tmp_path
):
    home = tmp_path / "home"
    claude = home / ".claude"
    settings = json.dumps(
        {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "*",
                        "hooks": [
                            _command("interop_journal.py"),
                            _command("gone.ps1", "tools"),
                            {
                                "type": "command",
                                "command": 'python "$CLAUDE_PROJECT_DIR/.claude/hooks/format.py"',
                            },
                        ],
                    }
                ]
            }
        }
    )
    path = _write_settings(home, settings)
    (claude / "AGENTS.md").write_text("# previous rules\n", encoding="utf-8")
    (claude / ".git").mkdir()
    (claude / "scripts").mkdir()
    (claude / "scripts" / "interop_journal.py").write_text("", encoding="utf-8")
    (claude / "settings.shared.json").write_text("{}", encoding="utf-8")
    cold = claude / "base" / "cold" / "memory"
    cold.mkdir(parents=True)
    (claude / "memory").mkdir()
    (cold / "same.md").write_text("one\n", encoding="utf-8")
    (claude / "memory" / "same.md").write_bytes(b"one\r\n")
    (cold / "changed.md").write_text("new\n", encoding="utf-8")
    (claude / "memory" / "changed.md").write_text("old\n", encoding="utf-8")
    (claude / "memory" / "local-only.md").write_text("mine\n", encoding="utf-8")
    snapshot = {
        item.relative_to(home).as_posix(): item.read_bytes()
        for item in home.rglob("*")
        if item.is_file()
    }

    report = _hygiene(executable, home, "-Action", "Scan")
    assert report["hooks"] is None
    assert report["legacy"]["status"] == "FOUND"
    findings = {
        finding["id"]: finding for finding in report["legacy"]["findings"]
    }
    assert {
        (finding["id"], finding["path"]) for finding in report["legacy"]["findings"]
    } == {
        ("instruction_file", ".claude/AGENTS.md"),
        ("hook_old_location", ".claude/scripts/interop_journal.py"),
        ("hook_missing_target", ".claude/tools/gone.ps1"),
        ("old_checkout", ".claude/.git"),
        ("old_scripts", ".claude/scripts"),
        ("old_settings_template", ".claude/settings.shared.json"),
        ("memory_shadow", ".claude/memory"),
    }
    assert "changed.md" in findings["memory_shadow"]["detail"]
    assert "same.md" not in findings["memory_shadow"]["detail"]
    # Папку нельзя удалять, пока из неё запускается оставленный хук.
    assert "still run from hooks" in findings["old_scripts"]["detail"]
    assert path.read_text(encoding="utf-8") == settings
    assert snapshot == {
        item.relative_to(home).as_posix(): item.read_bytes()
        for item in home.rglob("*")
        if item.is_file()
    }


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_installed_layer_is_clean_after_one_reconcile(executable, tmp_path):
    home = tmp_path / "home"
    runtime = _install_runtime(home)
    _write_settings(home, '{\n  "language": "russian"\n}\n')

    report = _hygiene(executable, home, "-Action", "All", runtime=runtime)
    assert report["hooks"]["status"] == "UPDATED"
    assert report["legacy"] == {"status": "CLEAN", "findings": []}
    settings = json.loads(
        (home / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    assert settings == {"language": "russian", "hooks": _template_hooks()}


def _session_home(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "home"
    runtime = _install_runtime(home)
    (runtime / "update-session-tools.ps1").write_text("exit 0\n", encoding="utf-8")
    state = home / ".claude" / "base" / "state"
    state.mkdir()
    checked = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (state / "update-check.json").write_text(
        json.dumps({"checked_at": checked, "latest_tag": None}), encoding="utf-8"
    )
    return home, runtime


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_session_start_reconciles_only_from_the_installed_layer(
    executable, tmp_path
):
    home, runtime = _session_home(tmp_path)
    original = _previous_settings_text()
    path = _write_settings(home, original)

    # Хук из исходников с тем же профилем настройки не трогает.
    assert _run_hook(executable, RUNTIME / "hooks" / "check-release.ps1", home) == ""
    assert path.read_text(encoding="utf-8") == original

    installed = runtime / "hooks" / "check-release.ps1"
    message = json.loads(_run_hook(executable, installed, home))["systemMessage"]
    assert "aligned with the installed release" in message
    assert "15 hook script(s) of the previous base unhooked" in message
    assert "settings-backups" in message
    assert "hook_missing_target" in message
    assert json.loads(path.read_text(encoding="utf-8"))["hooks"]["Stop"] == [
        {"matcher": "*", "hooks": [MEMORY_HOOK]}
    ]
    updated = path.read_text(encoding="utf-8")
    state = home / ".claude" / "base" / "state" / "hygiene.json"
    assert "hook_missing_target" in json.loads(state.read_text(encoding="utf-8"))[
        "notified"
    ]

    # Тот же состав остатков второй раз не объявляется.
    assert _run_hook(executable, installed, home) == ""
    assert path.read_text(encoding="utf-8") == updated


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_session_start_survives_a_broken_hygiene_layer(executable, tmp_path):
    home, runtime = _session_home(tmp_path)
    original = _previous_settings_text()
    path = _write_settings(home, original)
    installed = runtime / "hooks" / "check-release.ps1"

    (runtime / "hooks-policy.json").write_text("{ broken", encoding="utf-8")
    message = json.loads(_run_hook(executable, installed, home))["systemMessage"]
    assert "did not align hooks in settings.json" in message
    assert "Leftovers of the previous base" not in message
    assert path.read_text(encoding="utf-8") == original

    (runtime / "hygiene.ps1").write_text("throw 'boom'\n", encoding="utf-8")
    assert _run_hook(executable, installed, home) == ""
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_sync_reports_hooks_and_leftovers_after_install(executable, tmp_path):
    control = ROOT / "control-skills" / "sync-base"
    home = tmp_path / "home"
    runtime = _install_runtime(home)
    path = _write_settings(home, _previous_settings_text())
    driver = tmp_path / "driver.ps1"
    driver.write_text(
        f". '{control / 'tools' / 'sync_base.ps1'}' -LibraryMode "
        f"-PolicyPath '{control / 'sync-policy.json'}' "
        f"-TargetHome '{home}'\n"
        "Invoke-LlmBaseHygiene\n",
        encoding="utf-8-sig",
    )

    def run() -> str:
        result = subprocess.run(
            [executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(driver)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    first = run()
    assert "Хуки базы в settings.json приведены к набору релиза." in first
    assert "Снято скриптов прежней базы: 15." in first
    assert "Прежний файл: .claude/base/state/settings-backups/settings-" in first
    assert "Остатки прежней базы (1):" in first
    assert ".claude/scripts/interop_chat_server.py" in first
    assert json.loads(path.read_text(encoding="utf-8"))["hooks"][
        "UserPromptSubmit"
    ] == _template_hooks()["UserPromptSubmit"]

    second = run()
    assert "Хуки базы в settings.json соответствуют релизу." in second
    assert "Прежний файл" not in second

    # Сбой сверки не роняет установку: одна строка и код 0.
    (runtime / "hygiene.ps1").write_text("'not json'\nexit 3\n", encoding="utf-8")
    assert "Сверка хуков и остатков прежней базы не выполнена." in run()


def _detector_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    for skill in ("domain-grilling", "understanding-map"):
        target = home / ".claude" / "skills" / skill
        target.mkdir(parents=True)
        for name in ("triggers.txt", "reminder.txt"):
            shutil.copyfile(ROOT / "skills" / skill / name, target / name)
    return home


def _first_trigger(skill: str) -> str:
    for line in (ROOT / "skills" / skill / "triggers.txt").read_text(
        encoding="utf-8"
    ).splitlines():
        if line.strip() and not line.strip().startswith("#"):
            return line.strip()
    raise AssertionError(f"{skill} has no triggers")


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_prompt_detectors_remind_only_on_their_triggers(executable, tmp_path):
    home = _detector_home(tmp_path)
    hooks = RUNTIME / "hooks"
    domain = {"prompt": "Нужно: " + _first_trigger("domain-grilling").upper()}
    mapping = {"prompt": "Задача: " + _first_trigger("understanding-map")}
    quiet = {"prompt": "hello"}

    grilling = _run_hook(executable, hooks / "grilling-detector.ps1", home, domain)
    assert grilling.strip() == (
        ROOT / "skills" / "domain-grilling" / "reminder.txt"
    ).read_text(encoding="utf-8").strip()

    routing = _run_hook(executable, hooks / "routing-detector.ps1", home, domain)
    assert routing.strip() == (hooks / "routing-reminder.txt").read_text(
        encoding="utf-8"
    ).strip()
    # Напоминание повторяет гейт HOT-слоя и не добавляет правил прежней базы.
    assert "Роутинг: <домен> → агент <имя>" in routing
    assert "модел" not in routing.lower()

    understanding = _run_hook(
        executable, hooks / "understanding-map-detector.ps1", home, mapping
    )
    assert understanding.strip() == (
        ROOT / "skills" / "understanding-map" / "reminder.txt"
    ).read_text(encoding="utf-8").strip()

    for name in (
        "grilling-detector.ps1",
        "routing-detector.ps1",
        "understanding-map-detector.ps1",
    ):
        assert _run_hook(executable, hooks / name, home, quiet) == ""
        assert _run_hook(executable, hooks / name, home) == ""
        # Без установленных навыков детектор молчит, а не падает.
        assert _run_hook(executable, hooks / name, tmp_path / "bare", domain) == ""


@pytest.mark.parametrize("executable", POWERSHELLS)
@pytest.mark.parametrize("policy", ["Restricted", "AllSigned"])
def test_template_commands_run_under_a_restrictive_execution_policy(
    executable, policy, tmp_path
):
    """Команда шаблона, запущенная так же, как её запускает клиент."""
    home = _detector_home(tmp_path)
    hooks = home / ".claude" / "base" / "runtime" / "hooks"
    shutil.copytree(RUNTIME / "hooks", hooks)
    command = next(
        hook["command"]
        for hook in _template_hooks()["UserPromptSubmit"][0]["hooks"]
        if "routing-detector" in hook["command"]
    )
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command", command],
        input=json.dumps({"prompt": _first_trigger("domain-grilling")}).encode("ascii"),
        env=_home_env(home, PSExecutionPolicyPreference=policy),
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert result.stdout.decode("utf-8").lstrip("\ufeff").strip() == (
        hooks / "routing-reminder.txt"
    ).read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_project_memory_session_start_prints_journal_top_only_in_memory_projects(
    executable, tmp_path
):
    hook = RUNTIME / "hooks" / "project-memory-session-start.ps1"
    home = tmp_path / "home"
    state = tmp_path / "state"
    project = tmp_path / "project"
    journal = project / "Claude" / JOURNAL
    journal.parent.mkdir(parents=True)
    (project / "CLAUDE.md").write_text("# project\n", encoding="utf-8")
    journal.write_text(
        "# journal\n\n"
        "## 2026-10-12 · TEST · third\n\nnewest\n\n"
        "## 2026-10-11 · TEST · second\n\nmiddle\n\n"
        "## 2026-10-10 · TEST · first\n\noldest\n",
        encoding="utf-8",
    )
    nested = project / "docs" / "deep"
    nested.mkdir(parents=True)

    output = _run_hook(
        executable,
        hook,
        home,
        {"session_id": "s1", "cwd": str(nested)},
        PROJECT_MEMORY_STATE_DIR=str(state),
    )
    assert "[project-memory] Memory project detected (root: project)." in output
    assert "newest" in output and "middle" in output
    assert "oldest" not in output
    marker = json.loads((state / "session_s1.json").read_text(encoding="utf-8-sig"))
    assert Path(marker["project_root"]) == project
    # Хук только читает проект: файлов инструкций он не создаёт.
    assert sorted(item.name for item in project.iterdir()) == [
        "CLAUDE.md",
        "Claude",
        "docs",
    ]

    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "CLAUDE.md").write_text("# plain\n", encoding="utf-8")
    assert (
        _run_hook(
            executable,
            hook,
            home,
            {"session_id": "s2", "cwd": str(plain)},
            PROJECT_MEMORY_STATE_DIR=str(state),
        )
        == ""
    )
    assert [item.name for item in plain.iterdir()] == ["CLAUDE.md"]


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_screenshot_hook_adds_context_without_blocking(executable, tmp_path):
    output = _run_hook(
        executable,
        RUNTIME / "hooks" / "screenshot-source-zoom.ps1",
        tmp_path,
        {"tool_name": "screenshot"},
    )
    payload = json.loads(output)["hookSpecificOutput"]
    assert payload["hookEventName"] == "PreToolUse"
    assert "PDF" in payload["additionalContext"]
    assert "permissionDecision" not in payload


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_graph_skeleton_is_rebuilt_once_per_installed_release(executable, tmp_path):
    hook = RUNTIME / "hooks" / "graph-staleness-check.ps1"
    home = tmp_path / "home"
    claude = home / ".claude"
    tools = claude / "skills" / "graphify" / "tools"
    tools.mkdir(parents=True)
    (tools / "skeleton_build.py").write_text(
        "import argparse, json, pathlib\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('--commit')\n"
        "commit = parser.parse_args().commit\n"
        "out = pathlib.Path('graphify-out')\n"
        "out.mkdir(exist_ok=True)\n"
        "(out / 'skeleton.json').write_text(\n"
        "    json.dumps({'built_at_commit': commit}), encoding='utf-8')\n"
        "with (out / 'runs.txt').open('a', encoding='utf-8') as handle:\n"
        "    handle.write(commit + '\\n')\n",
        encoding="utf-8",
    )
    runs = claude / "graphify-out" / "runs.txt"

    # Без установленного релиза хук молчит и ничего не строит.
    assert _run_hook(executable, hook, home) == ""
    assert not runs.exists()

    (claude / "base").mkdir()
    version = claude / "base" / "VERSION"
    version.write_text("1.2.3\n", encoding="utf-8")
    assert "[graph]" in _run_hook(executable, hook, home)
    assert _run_hook(executable, hook, home) == ""
    assert runs.read_text(encoding="utf-8").split() == ["base-1.2.3"]

    version.write_text("1.2.4\n", encoding="utf-8")
    assert "[graph]" in _run_hook(executable, hook, home)
    assert runs.read_text(encoding="utf-8").split() == ["base-1.2.3", "base-1.2.4"]
