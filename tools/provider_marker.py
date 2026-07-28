from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SUPPORTED_CLIENT = "2.1.218"
PROMPT = "Ответь ровно: CLAUDE_BASE_CANARY_OK"
EXPECTED_RESPONSE = "CLAUDE_BASE_CANARY_OK"
SUPPORTED_REGIONS_URL = "https://www.anthropic.com/supported-countries"
CONSUMER_TERMS_URL = "https://www.anthropic.com/legal/consumer-terms"
SAFE_FAILURE_TYPES = {"error", "result"}
SAFE_FAILURE_SUBTYPES = {"error_during_execution", "success"}


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def evidence_body_sha256(value: dict[str, object]) -> str:
    body = dict(value)
    body.pop("evidence_body_sha256", None)
    return hashlib.sha256(_json_bytes(body)).hexdigest()


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("eligibility timestamp must be UTC")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("eligibility timestamp is invalid") from error
    return parsed.astimezone(timezone.utc)


def validate_eligibility(
    evidence: dict[str, Any],
    *,
    now: datetime | None = None,
) -> str:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    recorded = _parse_utc(evidence.get("recorded_at_utc"))
    attestation = evidence.get("owner_attestation")
    privacy = evidence.get("privacy")
    if current - recorded > timedelta(days=7):
        raise ValueError("eligibility evidence is older than seven days")
    if recorded - current > timedelta(minutes=5):
        raise ValueError("eligibility evidence timestamp is in the future")
    required_attestations = {
        "confirmed_employee": True,
        "physical_location_supported": True,
        "account_region_supported": True,
        "no_vpn_or_proxy_region_bypass": True,
        "consumer_terms_accepted": True,
    }
    required_privacy = {
        "employee_name_included": False,
        "country_included": False,
        "account_identifier_included": False,
        "credentials_included": False,
    }
    if (
        evidence.get("schema_version") != 1
        or evidence.get("target") != "claude"
        or attestation != required_attestations
        or privacy != required_privacy
        or evidence.get("evidence_body_sha256")
        != evidence_body_sha256(evidence)
    ):
        raise ValueError("Claude eligibility evidence is invalid")
    return str(evidence["evidence_body_sha256"])


def build_command(*, claude: str, empty_mcp_config: Path) -> list[str]:
    return [
        claude,
        "-p",
        PROMPT,
        "--safe-mode",
        "--output-format",
        "json",
        "--tools",
        "",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--mcp-config",
        str(empty_mcp_config.resolve()),
        "--no-session-persistence",
        "--model",
        "sonnet",
        "--effort",
        "low",
        "--no-chrome",
    ]


def summarize_marker(
    *,
    result: dict[str, Any],
    eligibility: dict[str, Any],
    client_version: str,
) -> dict[str, Any]:
    eligibility_sha256 = validate_eligibility(eligibility)
    usage = result.get("usage")
    if (
        client_version != SUPPORTED_CLIENT
        or result.get("type") != "result"
        or result.get("subtype") != "success"
        or result.get("is_error") is not False
        or result.get("num_turns") != 1
        or result.get("result") != EXPECTED_RESPONSE
        or not isinstance(usage, dict)
        or not all(
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
            for value in usage.values()
        )
    ):
        raise ValueError("Claude provider marker did not satisfy the contract")
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "target": "claude",
        "generated_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "client": {
            "id": "claude-code",
            "version": client_version,
        },
        "provider": "anthropic",
        "model": "sonnet",
        "effort": "low",
        "tools": "disabled",
        "session_persistence": False,
        "calls_authorized": 1,
        "calls_completed": 1,
        "usage": usage,
        "result_sha256": hashlib.sha256(
            EXPECTED_RESPONSE.encode("utf-8")
        ).hexdigest(),
        "eligibility": {
            "sha256": eligibility_sha256,
            "max_age_days": 7,
            "supported_regions_source": SUPPORTED_REGIONS_URL,
            "consumer_terms_source": CONSUMER_TERMS_URL,
        },
        "privacy": {
            "prompt_text_included": False,
            "response_text_included": False,
            "credentials_included": False,
            "personal_data_included": False,
            "account_identifier_included": False,
        },
        "CLAUDE_PROVIDER_MARKER": "PASS",
    }
    evidence["evidence_body_sha256"] = evidence_body_sha256(evidence)
    return evidence


def summarize_failure(
    *,
    returncode: int,
    stdout: str,
    stderr: str,
    eligibility: dict[str, Any],
    client_version: str,
) -> dict[str, Any]:
    eligibility_sha256 = validate_eligibility(eligibility)
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    result_type = payload.get("type")
    result_subtype = payload.get("subtype")
    is_error = payload.get("is_error")
    api_error_status = payload.get("api_error_status")
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "target": "claude",
        "generated_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "client": {
            "id": "claude-code",
            "version": client_version,
        },
        "provider": "anthropic",
        "model": "sonnet",
        "effort": "low",
        "tools": "disabled",
        "session_persistence": False,
        "calls_authorized": 1,
        "calls_started": 1,
        "calls_completed": 0,
        "eligibility": {
            "sha256": eligibility_sha256,
            "max_age_days": 7,
            "supported_regions_source": SUPPORTED_REGIONS_URL,
            "consumer_terms_source": CONSUMER_TERMS_URL,
        },
        "failure": {
            "exit_code": returncode,
            "result_type": (
                result_type
                if result_type in SAFE_FAILURE_TYPES
                else "unrecognized"
            ),
            "result_subtype": (
                result_subtype
                if result_subtype in SAFE_FAILURE_SUBTYPES
                else "unrecognized"
            ),
            "is_error": is_error if isinstance(is_error, bool) else None,
            "stdout_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr.encode("utf-8")).hexdigest(),
        },
        "privacy": {
            "credentials_included": False,
            "personal_data_included": False,
            "prompt_text_included": False,
            "response_text_included": False,
            "session_identifier_included": False,
            "failure_text_included": False,
        },
        "CLAUDE_PROVIDER_MARKER": "NOT_PASS",
    }
    if (
        isinstance(api_error_status, int)
        and not isinstance(api_error_status, bool)
        and 100 <= api_error_status <= 599
    ):
        evidence["failure"]["api_error_status"] = api_error_status
    evidence["evidence_body_sha256"] = evidence_body_sha256(evidence)
    return evidence


def _write_new(path: Path, value: object) -> None:
    if path.exists():
        raise RuntimeError(
            "Claude provider evidence exists; repeat requires new approval"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(_json_bytes(value))
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the one authorized Claude no-tools marker. The default is "
            "a zero-request dry-run."
        )
    )
    parser.add_argument("--execute-approved-marker", action="store_true")
    parser.add_argument("--eligibility", type=Path)
    parser.add_argument("--claude", default="claude")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/claude-provider-marker.json"),
    )
    arguments = parser.parse_args()
    plan = {
        "schema_version": 1,
        "would_execute": bool(arguments.execute_approved_marker),
        "calls_total": 1,
        "client_version": SUPPORTED_CLIENT,
        "model": "sonnet",
        "effort": "low",
        "tools": "disabled",
        "prompt_sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
        "eligibility_max_age_days": 7,
    }
    if not arguments.execute_approved_marker:
        print(json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    if arguments.eligibility is None:
        raise SystemExit("--eligibility is required for execution")
    eligibility = json.loads(
        arguments.eligibility.resolve().read_text(encoding="utf-8")
    )
    if not isinstance(eligibility, dict):
        raise SystemExit("eligibility evidence must contain an object")
    validate_eligibility(eligibility)
    version = subprocess.run(
        [arguments.claude, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=15,
    )
    if (
        version.returncode != 0
        or version.stdout.strip() != f"{SUPPORTED_CLIENT} (Claude Code)"
    ):
        raise SystemExit(f"Claude Code must be exactly {SUPPORTED_CLIENT}")
    with tempfile.TemporaryDirectory(prefix="claude-provider-marker-") as raw:
        workspace = Path(raw)
        mcp = workspace / "empty-mcp.json"
        mcp.write_text('{"mcpServers":{}}\n', encoding="utf-8")
        environment = os.environ.copy()
        environment["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        result = subprocess.run(
            build_command(
                claude=arguments.claude,
                empty_mcp_config=mcp,
            ),
            cwd=workspace,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=180,
        )
        if result.returncode != 0:
            failure = summarize_failure(
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                eligibility=eligibility,
                client_version=SUPPORTED_CLIENT,
            )
            _write_new(arguments.output.resolve(), failure)
            print(
                json.dumps(
                    {
                        "CLAUDE_PROVIDER_MARKER": "NOT_PASS",
                        "output": str(arguments.output.resolve()),
                    },
                    sort_keys=True,
                )
            )
            return 1
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                "Claude provider marker returned invalid JSON"
            ) from error
    if not isinstance(payload, dict):
        raise RuntimeError("Claude provider marker returned a non-object")
    evidence = summarize_marker(
        result=payload,
        eligibility=eligibility,
        client_version=SUPPORTED_CLIENT,
    )
    _write_new(arguments.output.resolve(), evidence)
    print(
        json.dumps(
            {
                "CLAUDE_PROVIDER_MARKER": "PASS",
                "output": str(arguments.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
