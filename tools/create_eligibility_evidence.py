from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from provider_marker import evidence_body_sha256, validate_eligibility


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create PII-free owner eligibility evidence for one Claude "
            "employee canary. Every confirmation must be explicit."
        )
    )
    parser.add_argument("--confirm-employee", action="store_true")
    parser.add_argument(
        "--confirm-physical-location-supported",
        action="store_true",
    )
    parser.add_argument(
        "--confirm-account-region-supported",
        action="store_true",
    )
    parser.add_argument("--confirm-no-region-bypass", action="store_true")
    parser.add_argument(
        "--accept-current-consumer-terms",
        action="store_true",
    )
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    confirmations = (
        arguments.confirm_employee,
        arguments.confirm_physical_location_supported,
        arguments.confirm_account_region_supported,
        arguments.confirm_no_region_bypass,
        arguments.accept_current_consumer_terms,
    )
    if not all(confirmations):
        raise SystemExit(
            "all five eligibility confirmations are required; "
            "no default or inferred approval is allowed"
        )
    output = arguments.output.resolve()
    if output.exists():
        raise SystemExit("eligibility evidence exists; refusing overwrite")
    evidence: dict[str, object] = {
        "schema_version": 1,
        "target": "claude",
        "recorded_at_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
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
    evidence["evidence_body_sha256"] = evidence_body_sha256(evidence)
    validate_eligibility(evidence)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(
        json.dumps(
            evidence,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    print(
        json.dumps(
            {
                "status": "CREATED",
                "valid_for_days": 7,
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
