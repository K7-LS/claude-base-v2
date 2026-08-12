from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "claude_live_canary",
    ROOT / "tools" / "live_canary.py",
)
assert SPEC and SPEC.loader
canary = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = canary
SPEC.loader.exec_module(canary)


def test_live_canary_evidence_binds_candidate_client_and_rollback():
    binding = {
        "target": "claude",
        "version": "0.1.0",
        "asset": {"sha256": "a" * 64, "bytes": 123},
    }
    evidence = canary.build_canary_evidence(
        release_binding=binding,
        client_version="2.1.218",
        lifecycle={
            "status": "PASS",
            "lifecycle": {
                "plan": "READY",
                "install": "INSTALLED",
                "doctor": "HEALTHY",
                "inventory": "INSTALLED",
                "rollback": "ROLLED_BACK",
            },
            "preserved_data": "PASS",
            "unknown_discovery_quarantine": "PASS",
            "environment_apply_and_restore": "PASS",
        },
        component_counts={"agents": 16, "skills": 38, "control_skills": 1},
    )

    assert evidence["CLAUDE_CANARY"] == "PASS"
    assert evidence["model_requests"] == 0
    assert evidence["rollback"]["byte_identical"] is True
    assert canary.evidence_body_sha256(evidence) == (
        evidence["evidence_body_sha256"]
    )


def test_live_canary_evidence_rejects_failed_preservation():
    with pytest.raises(ValueError, match="canary"):
        canary.build_canary_evidence(
            release_binding={
                "target": "claude",
                "version": "0.1.0",
                "asset": {"sha256": "a" * 64, "bytes": 123},
            },
            client_version="2.1.218",
            lifecycle={
                "status": "PASS",
                "lifecycle": {
                    "plan": "READY",
                    "install": "INSTALLED",
                    "doctor": "HEALTHY",
                    "inventory": "INSTALLED",
                    "rollback": "ROLLED_BACK",
                },
                "preserved_data": "NOT_PASS",
                "unknown_discovery_quarantine": "PASS",
                "environment_apply_and_restore": "PASS",
            },
            component_counts={
                "agents": 16,
                "skills": 38,
                "control_skills": 1,
            },
        )


def test_live_canary_workspace_is_local_to_evidence_output(tmp_path):
    output = tmp_path / "evidence" / "claude-live-canary.json"

    with canary.canary_workspace(output) as workspace:
        assert workspace.is_dir()
        assert workspace.parent == output.parent.resolve()
        assert workspace.name.startswith("claude-live-canary-")

    assert not workspace.exists()
