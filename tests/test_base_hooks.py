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


def test_settings_template_declares_only_base_runtime_hooks():
    settings = json.loads((RUNTIME / "settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit", "PreToolUse"}

    pattern = re.compile(
        r'^& "\$HOME\\\.claude\\base\\runtime\\hooks\\([a-z-]+\.ps1)"$'
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


def test_hook_policy_names_what_the_release_replaces_and_retires():
    policy = json.loads((RUNTIME / "hooks-policy.json").read_text(encoding="utf-8"))
    superseded = policy["superseded"]
    retired = policy["retired"]
    assert superseded == sorted(set(superseded))
    assert retired == sorted(set(retired))
    assert not set(superseded) & set(retired)
    assert policy["legacy_roots"] == [
        "scripts",
        "skills/project-memory/tools/hooks",
    ]
    # Выгрузка состояния и телеметрия прежней базы только снимаются.
    assert {"auto-pull.ps1", "auto-push.ps1", "log-tool-usage.ps1"} <= set(retired)
    shipped = {path.name for path in (RUNTIME / "hooks").glob("*.ps1")}
    assert not shipped & set(retired)
    assert shipped - {"project-memory-session-start.ps1"} <= set(superseded)


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

    report = _hygiene(executable, home, "-Action", "Reconcile")["hooks"]
    assert report["status"] == "UPDATED"
    assert report["foreign"] == 2
    assert set(report["removed"]) == {
        "base/runtime/hooks/check-release.ps1",
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
        "removed": [],
        "foreign": 2,
        "backup": None,
    }
    assert path.read_text(encoding="utf-8") == updated
    assert len(list(backup.parent.iterdir())) == 1


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_reconcile_adds_hooks_to_any_valid_settings_shape(executable, tmp_path):
    template = _template_hooks()
    cases: dict[str, bytes | None] = {
        "missing": None,
        "blank": b"\n",
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

        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        settings = json.loads(text)
        assert settings.pop("hooks") == template, name
        previous = (
            json.loads(payload.decode("utf-8-sig"))
            if payload is not None and payload.strip()
            else {}
        )
        previous.pop("hooks", None)
        assert settings == previous, name

    hookless = (tmp_path / "hookless" / ".claude" / "settings.json").read_text(
        encoding="utf-8"
    )
    assert hookless.startswith(
        '{\n    "model": "x",\n    "env": {"A": "1"},\n    "hooks": {\n'
    )
    assert hookless.endswith("\n    }\n}\n")
    marked = (tmp_path / "bom-crlf" / ".claude" / "settings.json").read_bytes()
    assert marked.startswith(b"\xef\xbb\xbf{\r\n")
    assert b"\n" not in marked.replace(b"\r\n", b"")
    assert (
        _hygiene(executable, tmp_path / "bom-crlf", "-Action", "Reconcile")["hooks"][
            "status"
        ]
        == "CANONICAL"
    )


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_reconcile_never_rewrites_settings_it_cannot_read(executable, tmp_path):
    cases = {
        "broken": b'{ "hooks": [',
        "array": b'{ "hooks": [] }',
        "repeated": b'{ "hooks": {}, "hooks": {} }',
        "not-object": b'["hooks"]',
    }
    for name, payload in cases.items():
        home = tmp_path / name
        path = _write_settings(home, payload)
        report = _hygiene(executable, home, "-Action", "All")
        assert report["hooks"]["status"] == "BLOCKED", name
        assert report["hooks"]["reason"], name
        assert path.read_bytes() == payload, name
        assert not (home / ".claude" / "base").exists(), name
        assert "hooks_not_canonical" in {
            finding["id"] for finding in report["legacy"]["findings"]
        }, name


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
        (finding["id"], finding["path"]) for finding in report["legacy"]["findings"]
    }
    assert findings == {
        ("instruction_file", ".claude/AGENTS.md"),
        ("hook_old_location", ".claude/scripts/interop_journal.py"),
        ("hook_missing_target", ".claude/tools/gone.ps1"),
        ("old_checkout", ".claude/.git"),
        ("old_scripts", ".claude/scripts"),
        ("old_settings_template", ".claude/settings.shared.json"),
        ("memory_shadow", ".claude/memory"),
    }
    shadow = next(
        finding
        for finding in report["legacy"]["findings"]
        if finding["id"] == "memory_shadow"
    )
    assert "changed.md" in shadow["detail"]
    assert "same.md" not in shadow["detail"]
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


@pytest.mark.parametrize("executable", POWERSHELLS)
def test_session_start_reconciles_only_from_the_installed_layer(
    executable, tmp_path
):
    home = tmp_path / "home"
    runtime = _install_runtime(home)
    (runtime / "update-session-tools.ps1").write_text("exit 0\n", encoding="utf-8")
    state = home / ".claude" / "base" / "state"
    state.mkdir()
    checked = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (state / "update-check.json").write_text(
        json.dumps({"checked_at": checked, "latest_tag": None}), encoding="utf-8"
    )
    original = _previous_settings_text()
    path = _write_settings(home, original)

    # Хук из исходников с тем же профилем настройки не трогает.
    assert _run_hook(executable, RUNTIME / "hooks" / "check-release.ps1", home) == ""
    assert path.read_text(encoding="utf-8") == original

    installed = runtime / "hooks" / "check-release.ps1"
    message = json.loads(_run_hook(executable, installed, home))["systemMessage"]
    assert "aligned with the installed release" in message
    assert "hook_missing_target" in message
    assert json.loads(path.read_text(encoding="utf-8"))["hooks"]["Stop"] == [
        {"matcher": "*", "hooks": [MEMORY_HOOK]}
    ]
    updated = path.read_text(encoding="utf-8")

    # Тот же состав остатков второй раз не объявляется.
    assert _run_hook(executable, installed, home) == ""
    assert path.read_text(encoding="utf-8") == updated


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
