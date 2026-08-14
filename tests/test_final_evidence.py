from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "claude_final_evidence",
    ROOT / "tools" / "final_evidence.py",
)
assert SPEC and SPEC.loader
finalizer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = finalizer
SPEC.loader.exec_module(finalizer)


def _binding() -> dict[str, object]:
    return {
        "target": "claude",
        "version": "0.1.0",
        "asset": {"sha256": "a" * 64, "bytes": 123},
    }


def _evidence(kind: str, binding: dict[str, object]) -> dict[str, object]:
    if kind == "candidate":
        value = {
            "schema_version": 1,
            "target": "claude",
            "CANDIDATE_OFFLINE": "PASS",
            "CLIENT_BINARY_ACCEPTANCE": "PASS",
            "release_binding": binding,
        }
    elif kind == "marker":
        value = {
            "schema_version": 1,
            "target": "claude",
            "client": {"id": "claude-code", "version": "2.1.218"},
            "provider": "anthropic",
            "model": "sonnet",
            "effort": "low",
            "CLAUDE_PROVIDER_MARKER": "PASS",
            "calls_authorized": 1,
            "calls_completed": 1,
            "tools": "disabled",
            "session_persistence": False,
            "usage": {"input_tokens": 12, "output_tokens": 3},
            "result_sha256": "b" * 64,
            "eligibility": {
                "sha256": "c" * 64,
                "max_age_days": 7,
                "supported_regions_source": "https://example.test/regions",
                "consumer_terms_source": "https://example.test/terms",
            },
            "privacy": {
                "prompt_text_included": False,
                "response_text_included": False,
                "credentials_included": False,
                "personal_data_included": False,
                "account_identifier_included": False,
            },
        }
    else:
        value = {
            "schema_version": 1,
            "target": "claude",
            "version": "0.1.0",
            "release_binding": binding,
            "client": {"id": "claude-code", "version": "2.1.218"},
            "CLAUDE_CANARY": "PASS",
            "model_requests": 0,
            "lifecycle": {
                "plan": "READY",
                "install": "CANONICAL",
                "doctor": "CANONICAL",
                "inventory": "INSTALLED",
                "rollback": "ROLLED_BACK",
            },
            "network": "offline-local-files-only",
            "credentials_included": False,
            "personal_data_included": False,
            "rollback": {
                "byte_identical": True,
                "preserved_data": "PASS",
                "unknown_discovery_restored": "PASS",
                "environment_restored": "PASS",
            },
            "discovery": {
                "agents": 16,
                "skills": 38,
                "control_skills": 1,
            },
        }
    value["evidence_body_sha256"] = finalizer.evidence_body_sha256(value)
    return value


def test_final_evidence_requires_candidate_marker_and_canary():
    binding = _binding()
    final = finalizer.compose_final_evidence(
        candidate=_evidence("candidate", binding),
        provider_marker=_evidence("marker", binding),
        canary=_evidence("canary", binding),
    )

    assert final["verdicts"]["FULL_RELEASE_CLAUDE"] == "PASS"
    assert final["verdicts"]["RELEASE_INTEGRITY"] == (
        "PENDING_PUBLICATION"
    )
    assert final["release_binding"] == binding
    assert finalizer.evidence_body_sha256(final) == (
        final["evidence_body_sha256"]
    )


def test_final_evidence_rejects_unbound_canary():
    binding = _binding()
    canary = _evidence("canary", binding)
    canary["release_binding"] = {**binding, "version": "9.9.9"}
    canary["evidence_body_sha256"] = finalizer.evidence_body_sha256(canary)
    with pytest.raises(ValueError, match="evidence"):
        finalizer.compose_final_evidence(
            candidate=_evidence("candidate", binding),
            provider_marker=_evidence("marker", binding),
            canary=canary,
        )


def test_final_evidence_rejects_marker_with_personal_data():
    binding = _binding()
    marker = _evidence("marker", binding)
    marker["privacy"]["personal_data_included"] = True
    marker["evidence_body_sha256"] = finalizer.evidence_body_sha256(marker)
    with pytest.raises(ValueError, match="evidence"):
        finalizer.compose_final_evidence(
            candidate=_evidence("candidate", binding),
            provider_marker=marker,
            canary=_evidence("canary", binding),
        )
