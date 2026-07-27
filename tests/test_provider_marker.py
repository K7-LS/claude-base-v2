from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "claude_provider_marker",
    ROOT / "tools" / "provider_marker.py",
)
assert SPEC and SPEC.loader
marker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = marker
SPEC.loader.exec_module(marker)


def _eligibility(recorded: str) -> dict[str, object]:
    value = {
        "schema_version": 1,
        "target": "claude",
        "recorded_at_utc": recorded,
        "owner_attestation": {
            "confirmed_employee": True,
            "physical_location_supported": True,
            "account_region_supported": True,
            "no_vpn_or_proxy_region_bypass": True,
            "consumer_terms_accepted": True,
        },
        "privacy": {
            "employee_name_included": False,
            "country_included": False,
            "account_identifier_included": False,
            "credentials_included": False,
        },
    }
    value["evidence_body_sha256"] = marker.evidence_body_sha256(value)
    return value


def test_eligibility_is_pii_free_current_and_owner_attested():
    now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    evidence = _eligibility("2026-07-26T12:00:00Z")

    digest = marker.validate_eligibility(evidence, now=now)

    assert digest == evidence["evidence_body_sha256"]
    assert evidence["privacy"]["employee_name_included"] is False
    assert evidence["privacy"]["account_identifier_included"] is False
    assert "russia" not in json.dumps(evidence).lower()


def test_eligibility_older_than_seven_days_is_rejected():
    with pytest.raises(ValueError, match="seven days"):
        marker.validate_eligibility(
            _eligibility("2026-07-19T11:59:59Z"),
            now=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        )


def test_marker_command_disables_tools_and_session_persistence(tmp_path: Path):
    command = marker.build_command(
        claude="claude",
        empty_mcp_config=tmp_path / "mcp.json",
    )

    assert command[:2] == ["claude", "-p"]
    assert ["--tools", ""] == command[
        command.index("--tools") : command.index("--tools") + 2
    ]
    for flag in (
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--no-chrome",
    ):
        assert flag in command
    assert ["--model", "sonnet"] == command[
        command.index("--model") : command.index("--model") + 2
    ]
    assert ["--effort", "low"] == command[
        command.index("--effort") : command.index("--effort") + 2
    ]


def test_marker_summary_contains_hash_usage_and_no_response_or_identity():
    eligibility = _eligibility("2026-07-26T12:00:00Z")
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 1,
        "result": marker.EXPECTED_RESPONSE,
        "session_id": "must-not-be-copied",
        "usage": {
            "input_tokens": 50,
            "output_tokens": 8,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    }

    evidence = marker.summarize_marker(
        result=result,
        eligibility=eligibility,
        client_version="2.1.218",
    )

    assert evidence["CLAUDE_PROVIDER_MARKER"] == "PASS"
    assert evidence["calls_completed"] == 1
    assert "result" not in evidence
    assert "session_id" not in json.dumps(evidence)
    assert marker.EXPECTED_RESPONSE not in json.dumps(evidence)
