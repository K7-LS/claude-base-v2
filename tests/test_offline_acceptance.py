from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_runner():
    path = ROOT / "tools" / "run_offline_acceptance.py"
    spec = importlib.util.spec_from_file_location(
        "native_offline_acceptance",
        path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_contract_overlay_is_explicit_and_fail_closed():
    runner = _load_runner()
    contract = json.loads(
        (ROOT / "runtime" / "release-contract.json").read_text(
            encoding="utf-8"
        )
    )
    original = json.loads(json.dumps(contract))
    identity = {
        "repository": contract["repository"],
        "commit": "a" * 40,
        "tree": "b" * 40,
        "transformation": contract["transformation"],
    }

    synthetic = runner.make_synthetic_contract(contract)
    synthetic_identity = runner.make_synthetic_identity(identity)
    report = runner.build_acceptance_report(
        target=contract["target"],
        source=synthetic_identity,
        foundation={"version": "0.2.0", "evidence_sha256": "c" * 64},
        asset={"sha256": "d" * 64, "bytes": 123},
        matrix={"pwsh": "PASS", "powershell": "PASS"},
    )

    assert contract == original
    assert original["client"]["acceptance"] == "PASS"
    assert original["client"]["supported_version"] == "2.1.114"
    assert synthetic["client"] == {
        "id": original["client"]["id"],
        "supported_version": "0.0.0-offline",
        "acceptance": "PASS",
    }
    assert synthetic_identity["transformation"].endswith(
        "-offline-contract-overlay"
    )
    assert report["channel"] == "InternalUnsigned"
    assert report["CLIENT_CONTRACT"] == "SYNTHETIC_ONLY"
    assert report["FOUNDATION_FAKE_HOME"] == "PASS"
    assert report["TECHNICAL_READY"] == "NOT_PASS"
    assert report["PROVIDER_LIVE"] == "BLOCKED_PROVIDER_ELIGIBILITY"
    assert "package_acceptance" not in report
    assert report["evidence_body_sha256"] == runner.evidence_body_sha256(
        report
    )


def test_offline_workspace_is_adjacent_to_evidence(tmp_path):
    runner = _load_runner()
    output = tmp_path / "dist" / "offline-acceptance"

    parent = runner.acceptance_workspace_parent(output)

    assert parent == output.parent.resolve()
    assert parent.is_dir()


def test_accepted_client_candidate_report_remains_non_stable():
    runner = _load_runner()
    report = runner.build_acceptance_report(
        target="claude",
        source={
            "repository": "https://github.com/example/claude-base-v2",
            "commit": "a" * 40,
            "tree": "b" * 40,
            "transformation": "claude-native-v2",
        },
        foundation={"version": "0.2.1", "evidence_sha256": "c" * 64},
        asset={"sha256": "d" * 64, "bytes": 123},
        matrix={"pwsh": "PASS", "powershell": "PASS"},
        synthetic=False,
        client_version="2.1.114",
    )

    assert report["CLIENT_CONTRACT"] == "ACCEPTED_BINARY"
    assert report["CLIENT_BINARY_ACCEPTANCE"] == "PASS"
    assert report["CANDIDATE_OFFLINE"] == "PASS"
    assert report["TECHNICAL_READY"] == "PASS"
    assert report["INTERNAL_UNSIGNED_RELEASE"] == "PASS"
    assert report["PROVIDER_LIVE"] == "BLOCKED_PROVIDER_ELIGIBILITY"
    assert "package_acceptance" not in report
    assert report["evidence_body_sha256"] == runner.evidence_body_sha256(
        report
    )


def test_acceptance_records_explicit_remove_decision_for_unknown_entries():
    runner = (ROOT / "tools" / "run_offline_acceptance.py").read_text(
        encoding="utf-8"
    )
    assert 'arguments.append("-ConfirmRemoveUnknown")' in runner


def test_acceptance_uses_strict_canonical_lifecycle_verdicts():
    runner = (ROOT / "tools" / "run_offline_acceptance.py").read_text(
        encoding="utf-8"
    )
    assert '"install": "CANONICAL"' in runner
    assert '"doctor": "CANONICAL"' in runner


def _engine(root: Path, version: str) -> Path:
    root.mkdir()
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    (root / "shared-tools.lock.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tools": [
                    {
                        "id": "officecli",
                        "environment": {
                            "OFFICECLI_NO_AUTO_INSTALL": "1",
                            "OFFICECLI_SKIP_UPDATE": "1",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


def test_engine_0_5_10_keeps_historical_empty_environment(tmp_path):
    runner = _load_runner()
    engine = _engine(tmp_path / "engine", "0.5.10")
    home = tmp_path / "home"
    assert runner._expected_installed_environment(engine, "claude", home) == {}
    assert runner._expected_installed_environment(engine, "opencode", home) == {
        "OPENCODE_DISABLE_CLAUDE_CODE": "1"
    }


def test_engine_0_5_12_expects_persisted_officecli_environment(tmp_path):
    runner = _load_runner()
    engine = _engine(tmp_path / "engine", "0.5.12")
    home = tmp_path / "home"
    assert runner._expected_installed_environment(engine, "claude", home) == {
        "OFFICECLI_NO_AUTO_INSTALL": "1",
        "OFFICECLI_SKIP_UPDATE": "1",
        "PATH": str(home / ".llm-foundation" / "bin"),
    }


def test_unknown_engine_has_no_environment_contract(tmp_path):
    runner = _load_runner()
    engine = _engine(tmp_path / "engine", "0.5.99")
    with pytest.raises(RuntimeError, match="0.5.99"):
        runner._expected_installed_environment(engine, "claude", tmp_path)


def test_engine_0_5_12_keeps_opencode_variable(tmp_path):
    runner = _load_runner()
    engine = _engine(tmp_path / "engine", "0.5.12")
    home = tmp_path / "home"
    assert runner._expected_installed_environment(engine, "opencode", home) == {
        "OPENCODE_DISABLE_CLAUDE_CODE": "1",
        "OFFICECLI_NO_AUTO_INSTALL": "1",
        "OFFICECLI_SKIP_UPDATE": "1",
        "PATH": str(home / ".llm-foundation" / "bin"),
    }


@pytest.mark.parametrize(
    "lock",
    [
        {"schema_version": 1, "tools": []},
        {"schema_version": 1, "tools": [{"id": "officecli"}, {"id": "other"}]},
        {"schema_version": 1, "tools": [{"id": "other", "environment": {"A": "1"}}]},
        {"schema_version": 1, "tools": [{"id": "officecli", "environment": {}}]},
    ],
)
def test_engine_0_5_12_rejects_malformed_shared_tool_lock(tmp_path, lock):
    runner = _load_runner()
    engine = _engine(tmp_path / "engine", "0.5.12")
    (engine / "shared-tools.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(RuntimeError, match="Foundation shared tool"):
        runner._expected_installed_environment(engine, "claude", tmp_path)
