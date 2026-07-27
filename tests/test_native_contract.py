from __future__ import annotations

import json
import importlib.util
import os
import re
import shutil
import subprocess
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
    assert len(hot.encode("utf-8")) <= 4500
    assert "@~/" not in hot
    assert "@AGENTS.md" not in hot
    assert ".codex" not in hot.lower()
    assert "auto-push" not in hot.lower()
    assert "feedback" not in hot.lower()
    assert "простой разговор" in hot.lower()
    assert "plan mode" in hot.lower()


def test_claude_has_exact_native_agent_and_skill_catalogs():
    agents = {path.stem for path in (ROOT / "agents").glob("*.md")}
    skills = {
        path.parent.name
        for path in (ROOT / "skills").glob("*/SKILL.md")
    }
    assert agents == EXPECTED_AGENTS
    assert len(skills) == 37

    for path in sorted((ROOT / "agents").glob("*.md")):
        frontmatter = _frontmatter(path)
        description = _scalar(frontmatter, "description")
        assert len(description) <= 240, path
        assert not re.search(r"(?m)^model:", frontmatter), path

    for path in sorted((ROOT / "skills").glob("*/SKILL.md")):
        frontmatter = _frontmatter(path)
        assert _scalar(frontmatter, "name") == path.parent.name
        assert 1 <= len(_scalar(frontmatter, "description")) <= 180, path

    catalog = json.loads(
        (ROOT / "catalog" / "agents.json").read_text(encoding="utf-8")
    )
    assert all((ROOT / row["source"]).is_file() for row in catalog)


def test_claude_migration_provenance_names_every_ported_component():
    migration = json.loads(
        (ROOT / "MIGRATION-SOURCE.json").read_text(encoding="utf-8")
    )
    inventory = migration["inventory"]
    assert set(inventory["agents"]) == EXPECTED_AGENTS
    assert set(inventory["skills"]) == {
        path.parent.name
        for path in (ROOT / "skills").glob("*/SKILL.md")
    }
    assert len(inventory["cold"]) == 22
    assert all((ROOT / "cold" / path).is_file() for path in inventory["cold"])
    assert set(inventory["commands"]) == {
        path.stem for path in (ROOT / "commands").glob("*.md")
    }
    assert inventory["control_skills"] == ["sync-base"]


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
    assert release["client"]["acceptance"] == "NOT_ACCEPTED"
    assert release["client"]["supported_version"] is None
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


def test_claude_release_status_stays_fail_closed_before_canary():
    status = json.loads((ROOT / "STATUS.json").read_text(encoding="utf-8"))
    assert status["TARGET_IMPLEMENTATION"] == "IN_PROGRESS"
    assert status["CLAUDE_CANARY"] == "NOT_RUN"
    assert status["FULL_RELEASE_CLAUDE"] == "NOT_PASS"


def test_claude_static_token_budget_passes_without_claiming_live_ab():
    path = ROOT / "tools" / "token_audit.py"
    spec = importlib.util.spec_from_file_location("claude_token_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    report = module.audit_static_context(ROOT, "claude")
    assert report["results"]["STATIC_TOKEN_ACCEPTANCE"] == "PASS"
    assert report["results"]["base_controlled_startup_reduction"] >= 0.70
    assert report["results"]["MATCHED_AB"] == "NOT_RUN"
    assert report["candidate"]["cold_payload_in_startup"] is False
    assert report["candidate"]["surfaces"]["agents_discovery"]["count"] == 16
    assert report["candidate"]["surfaces"]["skills_discovery"]["count"] == 38


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
def test_claude_sync_runtime_is_native_and_blocks_before_canary(
    executable, tmp_path
):
    control = ROOT / "control-skills" / "sync-base"
    policy = json.loads(
        (control / "sync-policy.json").read_text(encoding="utf-8")
    )
    assert policy["target"] == "claude"
    assert policy["client"]["acceptance"] == "NOT_ACCEPTED"
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
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "client release contract is not accepted" in combined.lower()
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
