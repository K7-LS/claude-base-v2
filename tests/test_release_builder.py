from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "native_release_builder",
    ROOT / "tools" / "release_builder.py",
)
assert SPEC and SPEC.loader
release_builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_builder
SPEC.loader.exec_module(release_builder)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence_body_sha256(value: dict[str, object]) -> str:
    body = dict(value)
    body.pop("evidence_body_sha256", None)
    return hashlib.sha256(
        (
            json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n"
        ).encode("utf-8")
    ).hexdigest()


def _json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _fake_foundation(root: Path) -> Path:
    root.mkdir()
    (root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    script = root / "foundation.ps1"
    script.write_text("param([string]$Command)\n", encoding="utf-8")
    _json(
        root / "engine-manifest.json",
        {
            "schema_version": 1,
            "engine_version": "0.1.0",
            "protocol_version": 1,
            "network": "offline",
            "commands": ["apply", "doctor", "install", "inventory", "plan", "rollback"],
            "supported_powershell": ["5.1", "7"],
            "foundation_ps1_sha256": _sha256(script),
        },
    )
    return root


def _accepted_source(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    source = tmp_path / "source"
    shutil.copytree(
        ROOT,
        source,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "reports"),
    )
    path = source / "runtime" / "release-contract.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    return source, contract


def test_release_builder_cli_loads_session_tools_from_repository_root():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "release_builder.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--foundation" in result.stdout


def test_release_builder_refuses_unaccepted_client_contract(tmp_path: Path):
    source, _ = _accepted_source(tmp_path)
    path = source / "runtime" / "release-contract.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    contract["client"]["supported_version"] = None
    contract["client"]["acceptance"] = "NOT_ACCEPTED"
    _json(path, contract)
    with pytest.raises(ValueError, match="binary contract"):
        release_builder.load_release_contract(source)


@pytest.mark.parametrize("tamper", ["version", "signature", "model_request"])
def test_release_builder_rejects_tampered_client_binary_evidence(
    tmp_path: Path,
    tamper: str,
):
    source, _ = _accepted_source(tmp_path)
    path = source / "runtime" / "client-acceptance.json"
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if tamper == "version":
        evidence["client"]["version"] = "9.9.9"
    elif tamper == "signature":
        evidence["binary"]["authenticode_status"] = "NotSigned"
    else:
        evidence["runtime_smoke"]["model_requests"] = 1
    _json(path, evidence)

    with pytest.raises(ValueError, match="binary acceptance evidence"):
        release_builder.load_release_contract(source)


def test_native_release_is_deterministic_complete_and_one_way(tmp_path: Path):
    source, contract = _accepted_source(tmp_path)
    foundation = _fake_foundation(tmp_path / "foundation")
    identity = {
        "repository": contract["repository"],
        "commit": "a" * 40,
        "tree": "b" * 40,
        "transformation": contract["transformation"],
    }
    first = release_builder.build_release_from_source(
        source,
        tmp_path / "one",
        "1.2.3",
        foundation,
        identity,
    )
    second = release_builder.build_release_from_source(
        source,
        tmp_path / "two",
        "1.2.3",
        foundation,
        identity,
    )
    assert _sha256(first.zip_path) == _sha256(second.zip_path)
    assert first.manifest == second.manifest
    assert first.manifest["channel"] == "candidate"
    binding = release_builder.release_binding_from_manifest(first.manifest)
    assert binding["asset"] == first.manifest["asset"]
    assert binding["source"] == identity
    assert first.manifest["client"] == {
        "id": contract["client"]["id"],
        "supported_version": "2.1.114",
    }

    root = contract["paths"]["install_root"]
    hot = contract["paths"]["hot_destination"]
    config = contract["paths"]["config_destination"]
    with zipfile.ZipFile(first.zip_path) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())
        assert hot in names
        assert config in names
        assert f"{root}/base/VERSION" in names
        assert f"{root}/base/components.lock.json" in names
        assert f"{root}/base/desired-state.json" in names
        assert f"{root}/base/foundation/0.1.0/foundation.ps1" in names
        assert f"{root}/skills/sync-base/SKILL.md" in names
        assert len(
            [
                name
                for name in names
                if name.startswith(f"{root}/agents/") and name.endswith(".md")
            ]
        ) == 16
        assert [
            name
            for name in names
            if name.startswith(f"{root}/skills/") and name.endswith("/SKILL.md")
        ] == [f"{root}/skills/sync-base/SKILL.md"]
        assert len(
            [
                name
                for name in names
                if name.startswith("session-tools-baseline/tools/")
                and name.endswith("/SKILL.md")
            ]
        ) == 39
        assert len(
            [
                name
                for name in names
                if name.startswith(f"{root}/commands/") and name.endswith(".md")
            ]
        ) == 3
        assert not any("/tests/" in name or "__pycache__" in name for name in names)

        package = json.loads(archive.read("package-manifest.json"))
        managed = json.loads(
            (source / "runtime" / "managed-surface.json").read_text(encoding="utf-8")
        )
        session_skill_ids = sorted(
            path.name
            for path in (source / "skills").iterdir()
            if path.is_dir()
        )
        assert package["managed_surface"] == {
            "exact_directories": [
                path
                for path in managed["exact_directories"]
                if path.removeprefix(".claude/skills/") not in session_skill_ids
            ],
            "replace_files": managed["replace_files"],
            "preserved_paths": managed["preserved_paths"],
        }
        assert ".claude/skills/sync-base" in (
            package["managed_surface"]["exact_directories"]
        )
        assert package["environment"] == contract["environment"]
        assert package["desired_state"] == {
            "schema_version": 1,
            "unknown_policy": "prompt-every-run",
            "local_exceptions": True,
            "strict_doctor": True,
            "inventory_roots": [
                ".claude/agents",
                ".claude/commands",
                ".claude/skills",
            ],
            "platform_owned": [],
            "toml_reconcile": [],
        }
        desired = json.loads(archive.read(f"{root}/base/desired-state.json"))
        assert desired["client"] == "claude"
        assert desired["unknown_policy"] == "prompt-every-run"
        assert "document-quality-gate" in desired["skills"]
        assert desired["plugins"] == []
        assert package["sync_policy"] == {
            "direction": "hub-to-consumer",
            "consumer_feedback_upload": False,
            "consumer_push": False,
            "consumer_session_upload": False,
            "credentials_included": False,
        }

    lock = json.loads(first.component_lock_path.read_text(encoding="utf-8"))
    assert len(lock["components"]["agents"]) == 16
    assert len(lock["components"]["skills"]) == 0
    assert len(lock["components"]["control_skills"]) == 1
    assert len(lock["components"]["commands"]) == 3
    assert len(lock["components"]["cold"]) == 23

    evidence = tmp_path / "candidate-evidence.json"
    evidence.write_text('{"CANDIDATE_OFFLINE":"PASS"}\n', encoding="utf-8")
    bound = release_builder.bind_candidate_acceptance(
        first.manifest_path,
        evidence,
    )
    assert bound["acceptance_evidence_sha256"] == _sha256(evidence)


def test_release_binds_session_asset_and_keeps_session_skill_out_of_base(
    tmp_path: Path,
):
    source, contract = _accepted_source(tmp_path)
    foundation = _fake_foundation(tmp_path / "foundation")
    identity = {
        "repository": contract["repository"],
        "commit": "a" * 40,
        "tree": "b" * 40,
        "transformation": contract["transformation"],
    }
    built = release_builder.build_release_from_source(
        source,
        tmp_path / "release",
        "0.1.1",
        foundation,
        identity,
    )
    session = built.manifest["session_tools_asset"]
    skill_ids = sorted(
        path.name
        for path in (source / "skills").iterdir()
        if path.is_dir()
    )

    assert built.session_tools_zip_path == tmp_path / "release" / session["name"]
    assert session["name"] == "session-tools-claude-0.1.1.zip"
    assert session["sha256"] == _sha256(built.session_tools_zip_path)
    assert session["tool_count"] == len(skill_ids)
    assert release_builder.release_binding_from_manifest(built.manifest)[
        "session_tools_asset"
    ] == session

    with zipfile.ZipFile(built.zip_path) as archive:
        names = archive.namelist()
        package = json.loads(archive.read("package-manifest.json"))
        baseline = package["session_tools_baseline"]
        for tool_id in skill_ids:
            assert not any(
                name.startswith(f".claude/skills/{tool_id}/")
                for name in names
            ), f"session skill {tool_id} must stay out of the base surface"
        assert baseline["manifest_path"] == (
            "session-tools-baseline/session-tools-manifest.json"
        )
        assert baseline["manifest_sha256"] == hashlib.sha256(
            archive.read(baseline["manifest_path"])
        ).hexdigest()
        assert [tool["id"] for tool in baseline["tools"]] == skill_ids
        assert session["file_count"] == sum(
            len(tool["files"]) for tool in baseline["tools"]
        )
        assert "session-tools-baseline/tools/ru-writing-style/SKILL.md" in names


def test_release_binding_rejects_session_asset_name_not_bound_to_parent_version():
    manifest = {
        "target": "claude",
        "version": "0.1.1",
        "tag": "claude-v0.1.1",
        "client": {"id": "claude-code", "supported_version": "2.1.114"},
        "asset": {"name": "claude-base-0.1.1.zip"},
        "package_manifest_sha256": "1" * 64,
        "components_lock_sha256": "2" * 64,
        "source": {"commit": "3" * 40},
        "foundation_engine_version": "0.1.0",
        "foundation_engine_manifest_sha256": "4" * 64,
        "session_tools_asset": {
            "name": "session-tools-claude-9.9.9.zip",
            "sha256": "5" * 64,
            "bytes": 1,
            "manifest_sha256": "6" * 64,
            "tool_count": 1,
            "file_count": 1,
        },
    }

    with pytest.raises(ValueError, match="asset name"):
        release_builder.release_binding_from_manifest(manifest)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("release_tag", "claude-v9.9.9", "release tag"),
        ("base_version", "9.9.9", "base version"),
    ],
)
def test_release_rejects_internal_session_manifest_not_bound_to_parent(
    tmp_path: Path,
    monkeypatch,
    field: str,
    value: str,
    error: str,
):
    source, contract = _accepted_source(tmp_path)
    foundation = _fake_foundation(tmp_path / "foundation")
    identity = {
        "repository": contract["repository"],
        "commit": "a" * 40,
        "tree": "b" * 40,
        "transformation": contract["transformation"],
    }
    original = release_builder.build_session_tools_bundle

    def mismatched(*args, **kwargs):
        bundle = original(*args, **kwargs)
        bundle.manifest[field] = value
        return bundle

    monkeypatch.setattr(release_builder, "build_session_tools_bundle", mismatched)

    with pytest.raises(ValueError, match=error):
        release_builder.build_release_from_source(
            source,
            tmp_path / "release",
            "0.1.1",
            foundation,
            identity,
        )


def test_release_rejects_tampered_session_baseline_payload(
    tmp_path: Path,
    monkeypatch,
):
    source, contract = _accepted_source(tmp_path)
    foundation = _fake_foundation(tmp_path / "foundation")
    identity = {
        "repository": contract["repository"],
        "commit": "a" * 40,
        "tree": "b" * 40,
        "transformation": contract["transformation"],
    }
    original = release_builder.session_tools_baseline_entries

    def tampered(bundle):
        entries = original(bundle)
        entries["session-tools-baseline/tools/ru-writing-style/SKILL.md"] = b"tampered"
        return entries

    monkeypatch.setattr(release_builder, "session_tools_baseline_entries", tampered)

    with pytest.raises(ValueError, match="baseline"):
        release_builder.build_release_from_source(
            source,
            tmp_path / "release",
            "0.1.1",
            foundation,
            identity,
        )


def test_release_component_lock_excludes_session_owned_skill(tmp_path: Path):
    source, contract = _accepted_source(tmp_path)
    foundation = _fake_foundation(tmp_path / "foundation")
    identity = {
        "repository": contract["repository"],
        "commit": "a" * 40,
        "tree": "b" * 40,
        "transformation": contract["transformation"],
    }
    built = release_builder.build_release_from_source(
        source,
        tmp_path / "release",
        "0.1.1",
        foundation,
        identity,
    )
    component_lock = json.loads(
        built.component_lock_path.read_text(encoding="utf-8")
    )

    assert "ru-writing-style" not in {
        component["id"] for component in component_lock["components"]["skills"]
    }


def test_release_owns_each_base_skill_without_claiming_unknown_local_skills(
    tmp_path: Path,
):
    source, contract = _accepted_source(tmp_path)
    foundation = _fake_foundation(tmp_path / "foundation")
    identity = {
        "repository": contract["repository"],
        "commit": "a" * 40,
        "tree": "b" * 40,
        "transformation": contract["transformation"],
    }
    built = release_builder.build_release_from_source(
        source,
        tmp_path / "release",
        "0.1.1",
        foundation,
        identity,
    )
    with zipfile.ZipFile(built.zip_path) as archive:
        package = json.loads(archive.read("package-manifest.json"))

    exact = package["managed_surface"]["exact_directories"]
    assert ".claude/skills" not in exact
    assert ".claude/skills/sync-base" in exact
    assert ".claude/skills/ru-writing-style" not in exact
    assert exact == sorted(exact)


def test_legacy_release_manifest_remains_readable_without_session_asset():
    legacy = {
        "target": "claude",
        "version": "0.1.0",
        "tag": "claude-v0.1.0",
        "client": {"id": "claude-code", "supported_version": "2.1.114"},
        "asset": {"name": "claude-base-0.1.0.zip"},
        "package_manifest_sha256": "1" * 64,
        "components_lock_sha256": "2" * 64,
        "source": {"commit": "3" * 40},
        "foundation_engine_version": "0.1.0",
        "foundation_engine_manifest_sha256": "4" * 64,
    }

    assert release_builder.release_binding_from_manifest(legacy) == legacy


def test_package_acceptance_requires_stable_attested_full_pass(tmp_path: Path):
    source, contract = _accepted_source(tmp_path)
    foundation = _fake_foundation(tmp_path / "foundation")
    identity = {
        "repository": contract["repository"],
        "commit": "a" * 40,
        "tree": "b" * 40,
        "transformation": contract["transformation"],
    }
    built = release_builder.build_release_from_source(
        source,
        tmp_path / "release",
        "1.2.3",
        foundation,
        identity,
    )
    stable = dict(built.manifest)
    stable["channel"] = "stable"
    _json(built.manifest_path, stable)
    binding = release_builder.release_binding_from_manifest(stable)
    evidence = {
        "schema_version": 1,
        "target": contract["target"],
        "version": stable["version"],
        "release_binding": binding,
        "verdicts": {
            release_builder.FULL_VERDICTS[contract["target"]]: "PASS",
            "RELEASE_INTEGRITY": "PENDING_PUBLICATION",
        },
        "asset_sha256": stable["asset"]["sha256"],
    }
    evidence["evidence_body_sha256"] = _evidence_body_sha256(evidence)
    evidence_path = built.manifest_path.parent / "acceptance-evidence.json"
    _json(evidence_path, evidence)
    verification = {
        "schema_version": 1,
        "repository": contract["repository"].removeprefix(
            "https://github.com/"
        ),
        "tag": stable["tag"],
        "release_state": {
            "draft": False,
            "prerelease": False,
            "immutable": True,
        },
        "release_attestation": "PASS",
        "assets": [
            {
                **stable["asset"],
                "attestation": "PASS",
            }
        ],
        "RELEASE_INTEGRITY": "PASS",
    }
    verification["evidence_body_sha256"] = _evidence_body_sha256(
        verification
    )
    verification_path = (
        built.manifest_path.parent / "release-verification.json"
    )
    _json(verification_path, verification)
    output = built.manifest_path.parent / "package-acceptance.json"

    accepted = release_builder.create_package_acceptance(
        built.manifest_path,
        evidence_path,
        verification_path,
        output,
    )
    assert accepted["package_acceptance"] == "PASS"
    assert accepted["asset"]["sha256"] == _sha256(built.zip_path)

    verification["RELEASE_INTEGRITY"] = "NOT_PASS"
    verification["evidence_body_sha256"] = _evidence_body_sha256(
        verification
    )
    _json(verification_path, verification)
    with pytest.raises(ValueError, match="incomplete"):
        release_builder.create_package_acceptance(
            built.manifest_path,
            evidence_path,
            verification_path,
            output,
        )
