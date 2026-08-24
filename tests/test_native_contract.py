from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_AGENTS = {
    "audit-rd-section",
    "auditor",
    "designer",
    "excel-validator",
    "expertiza-responder",
    "id-engineer",
    "kp-writer",
    "letter-writer",
    "norm-lookup",
    "pdf-reviewer",
    "pto-engineer",
    "pyrevit-engineer",
    "rd-coordinator",
    "smetchik",
    "snabzhenets",
    "word-checker",
}


def test_project_memory_reuses_existing_codex_core(tmp_path):
    core = tmp_path / "Codex"
    core.mkdir()
    for name in ("AGENTS.md", "STATUS.md", "ЖУРНАЛ СЕССИЙ.md"):
        (core / name).write_text(f"# {name}\n", encoding="utf-8")

    script = ROOT / "skills" / "project-memory" / "tools" / "bootstrap.py"
    result = subprocess.run(
        [sys.executable, str(script), "Общее ядро", "--target", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode == 0, result.stderr
    assert "Codex/ (переиспользовано)" in result.stdout
    assert not (tmp_path / "Claude").exists()


def test_project_memory_blocks_on_conflicting_cores(tmp_path):
    for core_name, rules in (("Codex", "AGENTS.md"), ("Claude", "CLAUDE.md")):
        core = tmp_path / core_name
        core.mkdir()
        for name in (rules, "STATUS.md", "ЖУРНАЛ СЕССИЙ.md"):
            (core / name).write_text(f"# {name}\n", encoding="utf-8")

    script = ROOT / "skills" / "project-memory" / "tools" / "bootstrap.py"
    result = subprocess.run(
        [sys.executable, str(script), "Конфликт", "--target", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert result.returncode != 0
    assert "CORE_CONFLICT" in result.stdout + result.stderr


def _frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    marker = text.find("\n---\n", 4)
    assert marker > 0, path
    return text[4:marker]


def _scalar(frontmatter: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", frontmatter)
    assert match, f"missing {key}"
    return match.group(1).strip().strip("\"'")


def test_claude_hot_layer_is_native_compact_and_one_way():
    hot = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert len(hot.encode("utf-8")) <= 2000
    assert "@~/" not in hot
    assert "@AGENTS.md" not in hot
    assert ".codex" not in hot.lower()
    assert "auto-push" not in hot.lower()
    assert "feedback" not in hot.lower()
    assert "простой разговор" in hot.lower()


def test_claude_active_docs_have_no_stale_global_claude_references():
    stale_references = []
    patterns = (
        re.compile(
            r"полные формулировки.{0,160}?CLAUDE\.md",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(r"CLAUDE\.md\s+§", re.IGNORECASE),
        re.compile(r"CLAUDE\.md\s+п\.\s*\d", re.IGNORECASE),
        re.compile(r"CLAUDE\.md\s+правило\s*#?\d", re.IGNORECASE),
        re.compile(r"CLAUDE\.md\s*#\d", re.IGNORECASE),
        re.compile(
            r"(?:STOP-процедур\w*|правил\w*|токен-дисциплин\w*)"
            r"[^.\n]{0,100}CLAUDE\.md",
            re.IGNORECASE,
        ),
        re.compile(
            r"CLAUDE\.md[^.\n]{0,100}"
            r"(?:MCP-роутинг|STOP-процедур|токен-дисциплин)",
            re.IGNORECASE,
        ),
        re.compile(r"\(CLAUDE\.md\)", re.IGNORECASE),
        re.compile(r"CLAUDE-core", re.IGNORECASE),
    )
    paths = sorted(
        path
        for root in (ROOT / "agents", ROOT / "skills")
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".md", ".py", ".ps1", ".txt"}
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if any(pattern.search(text) for pattern in patterns):
            stale_references.append(path.relative_to(ROOT).as_posix())
    assert stale_references == []


def test_skill_development_uses_material_learning_not_session_ritual():
    text = (
        ROOT / "skills" / "skill-development" / "SKILL.md"
    ).read_text(encoding="utf-8")
    lowered = text.lower()
    assert "обновляй скиллы каждую сессию" not in lowered
    assert "конец сессии — спросил" not in lowered
    assert "material reusable learning" in lowered
    assert len(text.split()) <= 500


def test_claude_has_exact_native_agent_and_skill_catalogs():
    agents = {path.stem for path in (ROOT / "agents").glob("*.md")}
    skills = {
        path.parent.name
        for path in (ROOT / "skills").glob("*/SKILL.md")
    }
    assert agents == EXPECTED_AGENTS
    assert len(skills) == 39

    for path in sorted((ROOT / "agents").glob("*.md")):
        frontmatter = _frontmatter(path)
        description = _scalar(frontmatter, "description")
        assert len(description) <= 240, path
        assert not re.search(r"(?m)^model:", frontmatter), path

    for path in sorted((ROOT / "skills").glob("*/SKILL.md")):
        frontmatter = _frontmatter(path)
        assert _scalar(frontmatter, "name") == path.parent.name
        description = _scalar(frontmatter, "description")
        if path.parent.name == "ru-writing-style":
            assert description
        else:
            assert 1 <= len(description) <= 180, path

    catalog = json.loads(
        (ROOT / "catalog" / "agents.json").read_text(encoding="utf-8")
    )
    assert all((ROOT / row["source"]).is_file() for row in catalog)


def test_claude_imports_the_approved_russian_writing_skill_verbatim():
    path = ROOT / "skills" / "ru-writing-style" / "SKILL.md"
    payload = path.read_bytes()
    assert len(payload) == 20003
    assert hashlib.sha256(payload).hexdigest() == (
        "a20f25a852eaff976c9db90929c94f5658acb3a71eb264479f6d354e04a10938"
    )

    catalog = json.loads(
        (ROOT / "catalog" / "skills.json").read_text(encoding="utf-8")
    )
    record = next(row for row in catalog if row["id"] == "ru-writing-style")
    assert record["name"] == "ru-writing-style"
    assert record["source"] == "skills/ru-writing-style/SKILL.md"
    assert record["required_capabilities"] == []

    shared = json.loads(
        (ROOT / "shared-components.lock.json").read_text(encoding="utf-8")
    )
    component = next(row for row in shared["components"] if row["id"] == "ru-writing-style")
    assert component["sha256"]


def test_claude_managed_surface_owns_control_skills_only():
    managed = json.loads(
        (ROOT / "runtime" / "managed-surface.json").read_text(encoding="utf-8")
    )
    exact = managed["exact_directories"]
    session_skill_ids = {
        path.name for path in (ROOT / "skills").iterdir() if path.is_dir()
    }

    assert ".claude/skills" not in exact
    assert {
        path.removeprefix(".claude/skills/")
        for path in exact
        if path.startswith(".claude/skills/")
    } == {"sync-base"}, (
        "every portable skill is session-owned; only control skills stay base-managed"
    )
    for skill_id in session_skill_ids:
        assert f".claude/skills/{skill_id}" not in exact
    assert exact == sorted(exact)


def test_officecli_is_catalogued_only_as_a_cold_foundation_reference():
    cold_path = ROOT / "cold" / "memory" / "reference_officecli.md"
    text = cold_path.read_text(encoding="utf-8")
    assert "Foundation-managed" in text
    assert "OfficeCLI" in text
    assert "PATH" in text
    assert "plugin" in text.lower()
    assert "MCP" in text

    cold_catalog = json.loads(
        (ROOT / "catalog" / "cold.json").read_text(encoding="utf-8")
    )
    assert "memory/reference_officecli.md" in cold_catalog["memory"]

    skill_catalog = json.loads(
        (ROOT / "catalog" / "skills.json").read_text(encoding="utf-8")
    )
    assert all("officecli" not in row["id"].casefold() for row in skill_catalog)
    assert not (ROOT / "skills" / "officecli").exists()


def test_claude_repository_is_native_not_generated_from_another_base():
    assert not (ROOT / "MIGRATION-SOURCE.json").exists()
    identity = json.loads(
        (ROOT / "runtime" / "release-contract.json").read_text(encoding="utf-8")
    )
    assert identity["repository"].endswith("/claude-base-v2")


def test_claude_runtime_does_not_upload_or_overwrite_client_state():
    settings = json.loads((ROOT / "runtime" / "settings.json").read_text("utf-8"))
    assert settings["autoMemoryEnabled"] is False
    assert set(settings.get("hooks", {})) <= {"SessionStart"}
    assert "model" not in settings
    assert "effortLevel" not in settings
    assert "enabledPlugins" not in settings

    managed = json.loads(
        (ROOT / "runtime" / "managed-surface.json").read_text(encoding="utf-8")
    )
    preserved = set(managed["preserved_paths"])
    assert ".claude.json" in preserved
    assert ".claude/projects" in preserved
    assert ".claude/history.jsonl" in preserved
    assert ".claude/plugins" in preserved

    runtime_text = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in (ROOT / "runtime").rglob("*")
        if path.is_file()
    )
    for forbidden in ("auto-push", "sessionend", "feedback-pending", "invoke-webrequest -method post"):
        assert forbidden not in runtime_text

    release = json.loads(
        (ROOT / "runtime" / "release-contract.json").read_text(encoding="utf-8")
    )
    assert release["client"]["acceptance"] == "PASS"
    assert release["client"]["supported_version"] == "2.1.218"
    client_evidence = json.loads(
        (ROOT / "runtime" / "client-acceptance.json").read_text(
            encoding="utf-8"
        )
    )
    assert client_evidence["verdict"] == "PASS"
    assert client_evidence["client"] == {
        "id": "claude-code",
        "version": "2.1.218",
    }
    assert client_evidence["binary"]["authenticode_status"] == "Valid"
    assert client_evidence["distribution"] == {
        "method": "official-binary",
        "package_id": "win32-x64/claude.exe",
        "package_version": "2.1.218",
        "scope": "current-user",
        "source": "https://downloads.claude.ai/claude-code-releases/2.1.218/win32-x64/claude.exe",
    }
    assert client_evidence["binary"]["sha256"] == (
        "81fcf59bb7abb558aedc6f2361f4723b3d757d28e799962d88b18b4520df66ca"
    )
    assert client_evidence["binary"]["signer"] == "Anthropic, PBC"
    assert client_evidence["runtime_smoke"]["model_requests"] == 0
    assert release["environment"] == {"scope": "current-user", "set": []}
    connection = ROOT / "runtime" / "connection.ps1"
    assert connection.is_file()
    hook = (
        ROOT / "runtime" / "hooks" / "check-release.ps1"
    ).read_text(encoding="utf-8")
    assert "connection.ps1" in hook
    assert "Invoke-WithLlmConnection" in hook


def test_claude_managed_surface_arrays_are_foundation_canonical():
    managed = json.loads(
        (ROOT / "runtime" / "managed-surface.json").read_text(encoding="utf-8")
    )
    for name in (
        "exact_directories",
        "replace_files",
        "preserved_paths",
    ):
        values = managed[name]
        assert values == sorted(values), f"{name} is not ordinal-sorted"
        assert len(values) == len({value.casefold() for value in values})


def test_claude_release_status_records_what_was_actually_verified():
    """A release verdict may only be PASS once its own gate passed."""
    status = json.loads((ROOT / "STATUS.json").read_text(encoding="utf-8"))
    assert status["TARGET_IMPLEMENTATION"] in {"IN_PROGRESS", "PASS"}
    assert status["CLAUDE_CANARY"] in {"NOT_RUN", "PASS"}
    assert status["FULL_RELEASE_CLAUDE"] in {"NOT_PASS", "PASS"}
    if status["FULL_RELEASE_CLAUDE"] == "PASS":
        assert status["CLAUDE_CANARY"] == "PASS"
        assert status["CLIENT_BINARY_ACCEPTANCE"] == "PASS"
        assert status["OFFLINE_FOUNDATION_INTEGRATION"] == "PASS"
    assert status["unverified"], "unverified gates must stay stated, never dropped"


def test_claude_policy_audit_blocks_unsupported_region_release():
    status = json.loads((ROOT / "STATUS.json").read_text(encoding="utf-8"))
    assert status["POLICY_AUDIT"] == "BLOCKED_REGION_VERIFICATION"
    assert any(
        "supported region" in blocker.lower()
        for blocker in status["blocked_by"]
    )

    audit_path = ROOT / "docs" / "ANTHROPIC-POLICY-AUDIT.md"
    audit = audit_path.read_text(encoding="utf-8").lower()
    for official_url in (
        "https://www.anthropic.com/legal/aup",
        "https://www.anthropic.com/legal/consumer-terms",
        "https://www.anthropic.com/supported-countries",
        "https://support.claude.com/en/articles/8241253-safeguards-warnings-and-appeals",
    ):
        assert official_url in audit
    assert "russia is not listed" in audit
    assert "russian-language construction documents are not prohibited" in audit
    assert "one eligible account per employee" in audit
    assert "must not be used to bypass" in audit
    assert "exact suspension reason" in audit


def test_claude_static_token_budget_passes_without_claiming_live_ab():
    path = ROOT / "tools" / "token_audit.py"
    spec = importlib.util.spec_from_file_location("claude_token_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    report = module.audit_static_context(ROOT, "claude")
    assert report["results"]["STATIC_TOKEN_ACCEPTANCE"] == "PASS"
    assert report["results"]["base_controlled_startup_reduction"] >= 0.83
    assert report["results"]["MATCHED_AB"] == "NOT_RUN"
    assert report["candidate"]["cold_payload_in_startup"] is False
    assert report["candidate"]["surfaces"]["agents_discovery"]["count"] == 16
    skills_discovery = report["candidate"]["surfaces"]["skills_discovery"]
    assert skills_discovery["capability_skills"] == 39
    assert skills_discovery["count"] == 40

    stored = json.loads(
        (ROOT / "reports" / "static-token-audit.json").read_text(
            encoding="utf-8"
        )
    )
    assert stored == report

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "39 capability skills" in readme
    assert f"{int(report['candidate']['estimated_tokens']):,} tokens" in readme


def test_claude_llm_interop_documentation_matches_bridge_cli():
    skill = (
        ROOT / "skills" / "llm-interop" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "--task .llm-interop/task.json" in skill
    assert "references/task.schema.json" in skill
    assert "--custom agent" not in skill
    assert "custom agent.schema.json" not in skill


@pytest.mark.parametrize(
    "executable",
    [
        value
        for value in (
            shutil.which("pwsh"),
            shutil.which("powershell.exe"),
        )
        if value
    ],
)
def test_claude_sync_runtime_is_native_and_accepts_semver_client_versions(
    executable, tmp_path
):
    control = ROOT / "control-skills" / "sync-base"
    policy = json.loads(
        (control / "sync-policy.json").read_text(encoding="utf-8")
    )
    assert policy["target"] == "claude"
    assert policy["client"]["acceptance"] == "PASS"
    assert policy["client"]["version_pattern"] == (
        r"^(?<version>[0-9]+\.[0-9]+\.[0-9]+"
        r"(?:-[0-9A-Za-z.-]+)?)(?: \(Claude Code\))?$"
    )
    script = control / "tools" / "sync_base.ps1"
    assert script.is_file()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    result = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-File",
            str(script),
            "-PolicyPath",
            str(control / "sync-policy.json"),
            "-TargetHome",
            str(fake_home),
            "-LibraryMode",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "client release contract is not accepted" not in combined.lower()
    assert "github cli" not in combined.lower()


@pytest.mark.parametrize(
    "executable",
    [
        value
        for value in (
            shutil.which("pwsh"),
            shutil.which("powershell.exe"),
        )
        if value
    ],
)
def test_claude_session_hook_is_silent_without_an_installed_base(
    executable, tmp_path
):
    result = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-File",
            str(ROOT / "runtime" / "hooks" / "check-release.ps1"),
        ],
        env={**os.environ, "USERPROFILE": str(tmp_path)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode == 0
    assert not (result.stdout + result.stderr).strip()


@pytest.mark.parametrize(
    "executable",
    [
        value
        for value in (
            shutil.which("pwsh"),
            shutil.which("powershell.exe"),
        )
        if value
    ],
)
def test_project_memory_legacy_stop_hook_never_blocks_session(
    executable, tmp_path
):
    hooks = ROOT / "skills" / "project-memory" / "tools" / "hooks"
    assert not hooks.exists() or not any(hooks.iterdir())
    return
    project = tmp_path / "project"
    journal = project / "Claude" / "ЖУРНАЛ СЕССИЙ.md"
    journal.parent.mkdir(parents=True)
    journal.write_text("# journal\n", encoding="utf-8")
    start_epoch = int((time.time() - 10) * 1000)
    os.utime(journal, ((start_epoch / 1000) - 10,) * 2)
    (project / "changed.txt").write_text("changed\n", encoding="utf-8")

    state = tmp_path / "state"
    state.mkdir()
    marker = {
        "session_id": "test-session",
        "start_epoch": start_epoch,
        "project_root": str(project),
        "journal": str(journal),
        "reminded": False,
    }
    (state / "session_test-session.json").write_text(
        json.dumps(marker),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-File",
            str(
                ROOT
                / "skills"
                / "project-memory"
                / "tools"
                / "hooks"
                / "session_end.ps1"
            ),
        ],
        input=json.dumps(
            {
                "session_id": "test-session",
                "stop_hook_active": False,
            }
        ),
        env={
            **os.environ,
            "PROJECT_MEMORY_STATE_DIR": str(state),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode == 0
    assert not (result.stdout + result.stderr).strip()


@pytest.mark.parametrize(
    "executable",
    [
        value
        for value in (
            shutil.which("pwsh"),
            shutil.which("powershell.exe"),
        )
        if value
    ],
)
def test_project_memory_session_start_keeps_cache_without_forcing_log(
    executable, tmp_path
):
    hooks = ROOT / "skills" / "project-memory" / "tools" / "hooks"
    assert not hooks.exists() or not any(hooks.iterdir())
    return
    project = tmp_path / "project"
    journal = project / "Claude" / "ЖУРНАЛ СЕССИЙ.md"
    journal.parent.mkdir(parents=True)
    journal.write_text(
        "# journal\n\n## 2026-07-28 · TEST · context\n\nState changed.\n",
        encoding="utf-8",
    )

    state = tmp_path / "state"
    result = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-File",
            str(
                ROOT
                / "skills"
                / "project-memory"
                / "tools"
                / "hooks"
                / "session_start.ps1"
            ),
        ],
        input=json.dumps(
            {
                "session_id": "test-session",
                "cwd": str(project),
            }
        ),
        env={
            **os.environ,
            "PROJECT_MEMORY_STATE_DIR": str(state),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )

    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "material portable-state change" in output
    assert "at session end add your entry" not in output
    marker = json.loads(
        (state / "session_test-session.json").read_text(encoding="utf-8-sig")
    )
    assert marker == {
        "journal": str(journal),
        "project_root": str(project),
    }
