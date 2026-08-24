from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import textwrap
import time
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "runtime" / "update-session-tools.ps1"
HOOK = ROOT / "runtime" / "hooks" / "check-release.ps1"
REPOSITORY = "K7-LS/claude-base-v2"
VERSION = "0.1.1"
TAG = f"claude-v{VERSION}"


def _powershells() -> list[str]:
    return [
        executable
        for executable in (shutil.which("pwsh.exe"), shutil.which("powershell.exe"))
        if executable
    ]


def _compiler() -> Path:
    candidates: list[Path] = []
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        root = os.environ.get(variable)
        if root:
            candidates.extend(
                Path(root).glob(
                    "Microsoft Visual Studio/*/*/MSBuild/Current/Bin/Roslyn/csc.exe"
                )
            )
    framework = Path("C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe")
    if framework.is_file():
        candidates.append(framework)
    assert candidates, "C# compiler is unavailable"
    return sorted(candidates)[0]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _fingerprint(path: Path) -> str:
    if not path.exists():
        return "absent"
    if path.is_file():
        return _sha256(path)
    canonical = bytearray()
    for file in sorted((item for item in path.rglob("*") if item.is_file()), key=str):
        relative = file.relative_to(path).as_posix()
        canonical.extend(f"{relative}\0{_sha256(file)}\n".encode())
    return hashlib.sha256(canonical).hexdigest()


@pytest.fixture(scope="session")
def fake_gh(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("fake-gh")
    source = root / "Program.cs"
    executable = root / "gh.exe"
    source.write_text(
        textwrap.dedent(
            r'''
            using System;
            using System.IO;
            using System.Linq;
            class Program
            {
                static int ExitCode(string name)
                {
                    int value;
                    return Int32.TryParse(Environment.GetEnvironmentVariable(name), out value) ? value : 0;
                }
                static void Log(string[] args)
                {
                    string path = Environment.GetEnvironmentVariable("FAKE_GH_LOG");
                    if (!String.IsNullOrEmpty(path))
                        File.AppendAllText(path, String.Join("\t", args) + Environment.NewLine);
                }
                static int Main(string[] args)
                {
                    Log(args);
                    if (args.Length >= 2 && args[0] == "release" && args[1] == "list")
                    {
                        Console.Write(Environment.GetEnvironmentVariable("FAKE_GH_RELEASES_JSON") ?? "[]");
                        return ExitCode("FAKE_GH_LIST_EXIT");
                    }
                    if (args.Length >= 2 && args[0] == "release" && args[1] == "verify")
                        return ExitCode("FAKE_GH_VERIFY_EXIT");
                    if (args.Length >= 2 && args[0] == "release" && args[1] == "verify-asset")
                        return ExitCode("FAKE_GH_VERIFY_ASSET_EXIT");
                    if (args.Length >= 3 && args[0] == "attestation" && args[1] == "verify")
                    {
                        int exit = ExitCode("FAKE_GH_ATTEST_EXIT");
                        if (exit != 0) return exit;
                        string match = Environment.GetEnvironmentVariable("FAKE_GH_MUTATE_AFTER_ATTEST_MATCH");
                        if (!String.IsNullOrEmpty(match) && args[2].IndexOf(match, StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            string source = Environment.GetEnvironmentVariable("FAKE_GH_MUTATE_SOURCE");
                            string target = Environment.GetEnvironmentVariable("FAKE_GH_MUTATE_TARGET");
                            try { File.Copy(source, target, true); }
                            catch (Exception) { return 93; }
                        }
                        return 0;
                    }
                    if (args.Length >= 2 && args[0] == "release" && args[1] == "download")
                    {
                        int patternIndex = Array.IndexOf(args, "--pattern");
                        int directoryIndex = Array.IndexOf(args, "--dir");
                        if (patternIndex < 0 || directoryIndex < 0) return 91;
                        string source = Path.Combine(
                            Environment.GetEnvironmentVariable("FAKE_GH_FIXTURE_ROOT"),
                            args[patternIndex + 1]
                        );
                        Directory.CreateDirectory(args[directoryIndex + 1]);
                        File.Copy(source, Path.Combine(args[directoryIndex + 1], Path.GetFileName(source)), true);
                        return ExitCode("FAKE_GH_DOWNLOAD_EXIT");
                    }
                    return 92;
                }
            }
            '''
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(_compiler()), "/nologo", "/target:exe", f"/out:{executable}", str(source)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return executable


def _write_release(
    fixture_root: Path,
    *,
    duplicate_manifest_key: bool = False,
    tool_payloads: dict[str, bytes] | None = None,
) -> dict:
    payload = "---\nname: ru-writing-style\n---\nПиши ясно и точно.\n".encode()
    if tool_payloads is None:
        tool_payloads = {"ru-writing-style": payload}
    session_manifest = {
        "schema_version": 1,
        "target": "claude",
        "release_tag": TAG,
        "base_version": VERSION,
        "tools": [
            {
                "id": tool_id,
                "files": [
                    {
                        "path": "SKILL.md",
                        "sha256": hashlib.sha256(tool_payload).hexdigest(),
                        "bytes": len(tool_payload),
                    }
                ],
            }
            for tool_id, tool_payload in sorted(tool_payloads.items())
        ],
    }
    manifest_bytes = _json_bytes(session_manifest)
    asset = fixture_root / f"session-tools-claude-{VERSION}.zip"
    with zipfile.ZipFile(asset, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("session-tools-manifest.json", manifest_bytes)
        for tool_id, tool_payload in sorted(tool_payloads.items()):
            archive.writestr(f"tools/{tool_id}/SKILL.md", tool_payload)
    main_asset = fixture_root / f"claude-base-{VERSION}.zip"
    main_asset.write_bytes(b"main-package")
    release = {
        "schema_version": 1,
        "target": "claude",
        "version": VERSION,
        "tag": TAG,
        "channel": "stable",
        "client": {"id": "claude-code", "supported_version": "2.1.218"},
        "foundation_engine_version": "0.3.0",
        "foundation_engine_manifest_sha256": "1" * 64,
        "source": {
            "repository": f"https://github.com/{REPOSITORY}",
            "commit": "2" * 40,
            "tree": "3" * 40,
            "transformation": "claude-native-v2",
        },
        "asset": {
            "name": main_asset.name,
            "sha256": _sha256(main_asset),
            "bytes": main_asset.stat().st_size,
        },
        "package_manifest_sha256": "4" * 64,
        "components_lock_sha256": "5" * 64,
        "session_tools_asset": {
            "name": asset.name,
            "sha256": _sha256(asset),
            "bytes": asset.stat().st_size,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "tool_count": len(tool_payloads),
            "file_count": len(tool_payloads),
        },
        "requires": {
            "immutable_release": True,
            "release_attestation": True,
            "verification_commands": [
                f"gh release verify {TAG} -R {REPOSITORY}",
                f"gh release verify-asset {TAG} {main_asset.name} -R {REPOSITORY}",
            ],
        },
        "acceptance_evidence_sha256": "6" * 64,
        "promoted_from_candidate_manifest_sha256": "7" * 64,
    }
    release_path = fixture_root / "release-manifest.json"
    release_bytes = _json_bytes(release)
    if duplicate_manifest_key:
        release_bytes = release_bytes.replace(
            b'"target": "claude"', b'"target": "claude",\n  "target": "claude"', 1
        )
    release_path.write_bytes(release_bytes)
    return {
        "release": release,
        "payload": payload,
        "session": session_manifest,
        "tool_payloads": tool_payloads,
    }


def _environment(
    tmp_path: Path,
    fake_gh: Path,
    *,
    tool_payloads: dict[str, bytes] | None = None,
) -> tuple[dict[str, str], Path, dict]:
    home = tmp_path / "профиль пользователя"
    fixture_root = tmp_path / "release fixtures"
    fixture_root.mkdir(parents=True)
    fixture = _write_release(fixture_root, tool_payloads=tool_payloads)
    receipt = home / ".llm-foundation" / "bin" / "claude-managed.receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_bytes(b'{"fixture":"receipt"}\n')
    gh_root = tmp_path / "bin"
    gh_root.mkdir()
    shutil.copy2(fake_gh, gh_root / "gh.exe")
    environment = {
        **os.environ,
        "USERPROFILE": str(home),
        "PATH": str(gh_root),
        "FAKE_GH_FIXTURE_ROOT": str(fixture_root),
        "FAKE_GH_LOG": str(tmp_path / "gh.log"),
        "FAKE_GH_RELEASES_JSON": json.dumps(
            [
                {
                    "tagName": TAG,
                    "isDraft": False,
                    "isPrerelease": False,
                    "isImmutable": True,
                    "publishedAt": "2026-08-10T00:00:00Z",
                }
            ]
        ),
    }
    return environment, home, fixture


def _run(host: str, environment: dict[str, str], *arguments: str, timeout: int = 40):
    return subprocess.run(
        [host, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(UPDATER), *arguments],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def _stopwatch(host: str) -> tuple[int, int]:
    result = subprocess.run(
        [
            host,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Console]::Write(('{0},{1}' -f [Diagnostics.Stopwatch]::GetTimestamp(),[Diagnostics.Stopwatch]::Frequency))",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    tick, frequency = result.stdout.split(",")
    return int(tick), int(frequency)


def _seed_killed_apply(home: Path) -> tuple[Path, Path, Path, dict]:
    state_root = home / ".llm-foundation" / "state" / "session-tools" / "claude"
    transaction_id = "12345678-1234-1234-1234-123456789abc"
    transaction_root = state_root / "transactions" / transaction_id
    previous = transaction_root / "previous"
    destination = home / ".claude" / "skills" / "ru-writing-style"
    previous.mkdir(parents=True)
    destination.mkdir(parents=True)
    (previous / "SKILL.md").write_text("старая версия\n", encoding="utf-8")
    (destination / "SKILL.md").write_text("новая версия\n", encoding="utf-8")
    receipt = home / ".llm-foundation" / "bin" / "claude-managed.receipt.json"
    frequency = 10_000_000
    start = 1
    journal = {
        "schema_version": 1,
        "target": "claude",
        "transaction_id": transaction_id,
        "phase": "move_staging_applied",
        "receipt_sha256": _sha256(receipt),
        "start_tick": start,
        "mutation_cutoff_tick": start + 22 * frequency,
        "kill_tick": start + 25 * frequency,
        "hard_deadline_tick": start + 30 * frequency,
        "stopwatch_frequency": frequency,
        "previous_destination_sha256": _fingerprint(previous),
        "previous_state_sha256": "absent",
        "expected_staging_sha256": _fingerprint(destination),
        "expected_destination_sha256": _fingerprint(destination),
        "expected_state_sha256": "absent",
        "staging_path": str(transaction_root / "staging"),
        "previous_path": str(previous),
        "destination_path": str(destination),
        "state_path": str(state_root / "state.json"),
        "operations": {
            "move_destination_to_previous": {"intent": True, "applied": True},
            "move_staging_to_destination": {"intent": True, "applied": True},
            "write_state": {"intent": False, "applied": False},
        },
    }
    state_root.mkdir(parents=True, exist_ok=True)
    return state_root, previous, destination, journal


def _seed_move_crash_window(
    home: Path, *, has_previous: bool, phase: str, actual_step: int
) -> tuple[Path, Path, Path, Path, dict]:
    state_root = home / ".llm-foundation" / "state" / "session-tools" / "claude"
    transaction_id = "12345678-1234-1234-1234-123456789abc"
    transaction_root = state_root / "transactions" / transaction_id
    staging = transaction_root / "staging"
    previous = transaction_root / "previous"
    destination = home / ".claude" / "skills" / "ru-writing-style"
    staging.mkdir(parents=True)
    destination.parent.mkdir(parents=True)
    (staging / "SKILL.md").write_text("новая версия\n", encoding="utf-8")
    new_hash = _fingerprint(staging)
    old_hash = "absent"
    if has_previous:
        destination.mkdir()
        (destination / "SKILL.md").write_text("старая версия\n", encoding="utf-8")
        old_hash = _fingerprint(destination)
    if actual_step >= 1 and has_previous:
        destination.rename(previous)
    if actual_step >= 2:
        staging.rename(destination)
    phases = [
        "created", "staged", "move_destination_intent", "move_destination_applied",
        "move_staging_intent", "move_staging_applied", "state_write_intent",
        "state_write_applied", "committed",
    ]
    transition = max(-1, phases.index(phase) - 2)
    flags = [index <= transition for index in range(6)]
    receipt = home / ".llm-foundation" / "bin" / "claude-managed.receipt.json"
    frequency = 10_000_000
    start = 1
    journal = {
        "schema_version": 1, "target": "claude", "transaction_id": transaction_id,
        "phase": phase, "receipt_sha256": _sha256(receipt),
        "start_tick": start, "mutation_cutoff_tick": start + 22 * frequency,
        "kill_tick": start + 25 * frequency, "hard_deadline_tick": start + 30 * frequency,
        "stopwatch_frequency": frequency, "previous_destination_sha256": old_hash,
        "previous_state_sha256": "absent", "expected_staging_sha256": new_hash,
        "expected_destination_sha256": new_hash, "expected_state_sha256": "absent",
        "staging_path": str(staging), "previous_path": str(previous),
        "destination_path": str(destination), "state_path": str(state_root / "state.json"),
        "operations": {
            "move_destination_to_previous": {"intent": flags[0], "applied": flags[1]},
            "move_staging_to_destination": {"intent": flags[2], "applied": flags[3]},
            "write_state": {"intent": flags[4], "applied": flags[5]},
        },
    }
    return state_root, staging, previous, destination, journal


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_verified_session_asset_is_applied_with_cyrillic_and_exact_state(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """Skipping any trust check or state field must make this integration fail."""
    environment, home, fixture = _environment(tmp_path, fake_gh)

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "TOOLS_APPLIED_NEXT_SESSION" in result.stdout
    destination = home / ".claude" / "skills" / "ru-writing-style" / "SKILL.md"
    assert destination.read_bytes() == fixture["payload"]
    state_path = home / ".llm-foundation" / "state" / "session-tools" / "claude" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(state) == {
        "schema_version", "target", "release_tag", "release_version",
        "release_manifest_sha256", "session_manifest_sha256", "verified_at",
        "tools", "complete",
    }
    assert state["schema_version"] == 2
    assert state["complete"] is True
    assert state["target"] == "claude"
    assert state["release_tag"] == TAG
    assert state["release_version"] == VERSION
    assert state["release_manifest_sha256"] == _sha256(
        Path(environment["FAKE_GH_FIXTURE_ROOT"]) / "release-manifest.json"
    )
    assert state["tools"] == [
        {
            "id": "ru-writing-style",
            "destination": str(home / ".claude" / "skills" / "ru-writing-style"),
            "ownership_marker": "session-tools-v1:claude:ru-writing-style",
            "files": fixture["session"]["tools"][0]["files"],
        }
    ]
    assert not (
        home / ".llm-foundation" / "state" / "session-tools" / "claude" / "active-transaction.json"
    ).exists()
    calls = (tmp_path / "gh.log").read_text(encoding="utf-8").splitlines()
    assert calls == [
        f"release\tlist\t--repo\t{REPOSITORY}\t--limit\t20\t--json\ttagName,isDraft,isPrerelease,isImmutable,publishedAt",
        f"release\tverify\t{TAG}\t--repo\t{REPOSITORY}",
        f"release\tdownload\t{TAG}\t--repo\t{REPOSITORY}\t--pattern\trelease-manifest.json\t--dir\t{home / '.llm-foundation' / 'state' / 'session-tools' / 'claude' / 'downloads'}",
        f"release\tverify-asset\t{TAG}\trelease-manifest.json\t--repo\t{REPOSITORY}",
        f"attestation\tverify\t{home / '.llm-foundation' / 'state' / 'session-tools' / 'claude' / 'downloads' / 'release-manifest.json'}\t--repo\t{REPOSITORY}",
        f"release\tdownload\t{TAG}\t--repo\t{REPOSITORY}\t--pattern\tsession-tools-claude-{VERSION}.zip\t--dir\t{home / '.llm-foundation' / 'state' / 'session-tools' / 'claude' / 'downloads'}",
        f"release\tverify-asset\t{TAG}\tsession-tools-claude-{VERSION}.zip\t--repo\t{REPOSITORY}",
        f"attestation\tverify\t{home / '.llm-foundation' / 'state' / 'session-tools' / 'claude' / 'downloads' / f'session-tools-claude-{VERSION}.zip'}\t--repo\t{REPOSITORY}",
    ]


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_mutable_stable_release_is_rejected_before_verification(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """A stable tag is trusted only when GitHub reports exact immutable state."""
    environment, home, _ = _environment(tmp_path, fake_gh)
    releases = json.loads(environment["FAKE_GH_RELEASES_JSON"])
    releases[0]["isImmutable"] = False
    environment["FAKE_GH_RELEASES_JSON"] = json.dumps(releases)

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (home / ".claude" / "skills").exists()
    assert "REJECTED_RELEASE_LIST" in (
        home / ".llm-foundation" / "state" / "session-tools" / "claude" / "events.log"
    ).read_text(encoding="utf-8")
    calls = (tmp_path / "gh.log").read_text(encoding="utf-8").splitlines()
    assert calls == [
        f"release\tlist\t--repo\t{REPOSITORY}\t--limit\t20\t--json\t"
        "tagName,isDraft,isPrerelease,isImmutable,publishedAt"
    ]


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_release_list_rejects_non_rfc_json_whitespace(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """Only JSON whitespace from RFC 8259 may occur outside strings."""
    environment, home, _ = _environment(tmp_path, fake_gh)
    environment["FAKE_GH_RELEASES_JSON"] = environment["FAKE_GH_RELEASES_JSON"].replace(
        "[", "[\u00a0", 1
    )

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (home / ".claude" / "skills").exists()
    assert "REJECTED_RELEASE_LIST" in (
        home / ".llm-foundation" / "state" / "session-tools" / "claude" / "events.log"
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_verified_manifest_handle_detects_late_external_replacement(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """Later gh processes cannot replace bytes that already passed attestation."""
    environment, home, fixture = _environment(tmp_path, fake_gh)
    fixture_root = Path(environment["FAKE_GH_FIXTURE_ROOT"])
    mutated = json.loads(json.dumps(fixture["release"]))
    mutated["acceptance_evidence_sha256"] = "8" * 64
    mutation_source = fixture_root / "mutated-release-manifest.json"
    mutation_source.write_bytes(_json_bytes(mutated))
    downloaded_manifest = (
        home
        / ".llm-foundation"
        / "state"
        / "session-tools"
        / "claude"
        / "downloads"
        / "release-manifest.json"
    )
    environment.update(
        {
            "FAKE_GH_MUTATE_AFTER_ATTEST_MATCH": f"session-tools-claude-{VERSION}.zip",
            "FAKE_GH_MUTATE_SOURCE": str(mutation_source),
            "FAKE_GH_MUTATE_TARGET": str(downloaded_manifest),
        }
    )

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (home / ".claude" / "skills").exists()
    assert "REJECTED_VERIFICATION" in (
        home / ".llm-foundation" / "state" / "session-tools" / "claude" / "events.log"
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_malformed_managed_ticks_are_rejected_before_filesystem_mutation(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """Accepting caller ticks that are not exact 22/25/30 intervals is unsafe."""
    environment, home, _ = _environment(tmp_path, fake_gh)
    result = _run(
        host,
        environment,
        "-ManagedPreflight",
        "-TransactionId", "12345678-1234-1234-1234-123456789abc",
        "-StartTick", "100",
        "-MutationCutoffTick", "122",
        "-KillTick", "125",
        "-HardDeadlineTick", "131",
        "-StopwatchFrequency", "1",
    )
    assert result.returncode != 0
    assert "BLOCKED_INVALID_PREFLIGHT" in result.stderr
    assert not (home / ".llm-foundation" / "state" / "session-tools").exists()
    assert not (tmp_path / "gh.log").exists()


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_duplicate_manifest_key_rejects_whole_snapshot_and_preserves_local_skill(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """A duplicate JSON property must not be normalized by ConvertFrom-Json."""
    environment, home, _ = _environment(tmp_path, fake_gh)
    _write_release(Path(environment["FAKE_GH_FIXTURE_ROOT"]), duplicate_manifest_key=True)
    destination = home / ".claude" / "skills" / "ru-writing-style"
    destination.mkdir(parents=True)
    marker = destination / "SKILL.md"
    marker.write_text("локальная версия\n", encoding="utf-8")

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text(encoding="utf-8") == "локальная версия\n"
    assert "TOOLS_APPLIED_NEXT_SESSION" not in result.stdout
    log = home / ".llm-foundation" / "state" / "session-tools" / "claude" / "events.log"
    assert "REJECTED_MANIFEST" in log.read_text(encoding="utf-8")


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_unmanaged_collision_is_never_overwritten(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """Missing state plus differing destination bytes must stay user-owned."""
    environment, home, _ = _environment(tmp_path, fake_gh)
    destination = home / ".claude" / "skills" / "ru-writing-style"
    destination.mkdir(parents=True)
    marker = destination / "SKILL.md"
    marker.write_text("моя локальная версия\n", encoding="utf-8")

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text(encoding="utf-8") == "моя локальная версия\n"
    assert not (home / ".llm-foundation" / "state" / "session-tools" / "claude" / "state.json").exists()
    log = home / ".llm-foundation" / "state" / "session-tools" / "claude" / "events.log"
    assert "BLOCKED_UNMANAGED_COLLISION" in log.read_text(encoding="utf-8")


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_same_tag_state_drift_is_not_silently_accepted(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """A matching tag cannot bypass exact ownership and destination verification."""
    environment, home, fixture = _environment(tmp_path, fake_gh)
    destination = home / ".claude" / "skills" / "ru-writing-style"
    destination.mkdir(parents=True)
    (destination / "SKILL.md").write_text("изменённая локально версия\n", encoding="utf-8")
    state_path = home / ".llm-foundation" / "state" / "session-tools" / "claude" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_bytes(_json_bytes({
        "schema_version": 1,
        "target": "claude",
        "release_tag": TAG,
        "release_version": VERSION,
        "release_manifest_sha256": "1" * 64,
        "session_manifest_sha256": "2" * 64,
        "verified_at": "2026-08-10T00:00:00.0000000+00:00",
        "tools": [{
            "id": "ru-writing-style",
            "destination": str(destination),
            "ownership_marker": "session-tools-v1:claude:ru-writing-style",
            "files": fixture["session"]["tools"][0]["files"],
        }],
    }))

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (destination / "SKILL.md").read_text(encoding="utf-8") == "изменённая локально версия\n"
    log = state_path.parent / "events.log"
    assert "BLOCKED_STATE_DRIFT" in log.read_text(encoding="utf-8")
    assert "NO_UPDATE" not in log.read_text(encoding="utf-8")


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_exact_package_baseline_recovers_missing_ownership_state(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """An exact verified package baseline is managed, while arbitrary bytes are not."""
    environment, home, fixture = _environment(tmp_path, fake_gh)
    destination = home / ".claude" / "skills" / "ru-writing-style"
    destination.mkdir(parents=True)
    (destination / "SKILL.md").write_bytes(fixture["payload"])
    baseline = home / ".claude" / "base" / "runtime" / "session-tools-baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_bytes(_json_bytes(fixture["session"]))

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "TOOLS_APPLIED_NEXT_SESSION" in result.stdout
    assert (destination / "SKILL.md").read_bytes() == fixture["payload"]
    state = json.loads(
        (home / ".llm-foundation" / "state" / "session-tools" / "claude" / "state.json")
        .read_text(encoding="utf-8")
    )
    assert state["tools"][0]["ownership_marker"] == "session-tools-v1:claude:ru-writing-style"


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_newer_package_baseline_blocks_session_channel_downgrade(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """Missing state must not let an older remote release replace a newer baseline."""
    environment, home, fixture = _environment(tmp_path, fake_gh)
    destination = home / ".claude" / "skills" / "ru-writing-style"
    destination.mkdir(parents=True)
    (destination / "SKILL.md").write_bytes(fixture["payload"])
    baseline_value = json.loads(json.dumps(fixture["session"]))
    baseline_value["base_version"] = "0.2.0"
    baseline_value["release_tag"] = "claude-v0.2.0"
    baseline = home / ".claude" / "base" / "runtime" / "session-tools-baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_bytes(_json_bytes(baseline_value))

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (destination / "SKILL.md").read_bytes() == fixture["payload"]
    state_root = home / ".llm-foundation" / "state" / "session-tools" / "claude"
    assert not (state_root / "state.json").exists()
    assert "BLOCKED_NO_DOWNGRADE" in (state_root / "events.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_busy_target_lock_is_bounded_and_does_not_contact_network(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """A competing Foundation install owns the target lock without being bypassed."""
    environment, home, _ = _environment(tmp_path, fake_gh)
    lock_path = home / ".llm-foundation" / "state" / "session-tools" / "claude" / "update.lock"
    lock_path.parent.mkdir(parents=True)
    ready = tmp_path / "lock-ready.txt"
    holder_script = tmp_path / "hold-lock.ps1"
    holder_script.write_text(
        "param([string]$LockPath, [string]$ReadyPath)\n"
        "$stream = [IO.File]::Open($LockPath, 'OpenOrCreate', 'ReadWrite', 'None')\n"
        "try { [IO.File]::WriteAllText($ReadyPath, 'held'); Start-Sleep -Seconds 15 }\n"
        "finally { $stream.Dispose() }\n",
        encoding="utf-8",
    )
    holder = subprocess.Popen(
        [host, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(holder_script), str(lock_path), str(ready)],
        env=environment,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), "lock holder did not start"
        started = time.monotonic()
        result = _run(host, environment, "-HookFallback")
        elapsed = time.monotonic() - started
    finally:
        holder.terminate()
        holder.wait(timeout=5)

    assert result.returncode == 0, result.stdout + result.stderr
    assert elapsed < 4
    assert not (tmp_path / "gh.log").exists()
    assert not (home / ".claude" / "skills" / "ru-writing-style").exists()
    log = home / ".llm-foundation" / "state" / "session-tools" / "claude" / "events.log"
    assert "SKIPPED_LOCK_BUSY" in log.read_text(encoding="utf-8")


@pytest.mark.parametrize("declared_tool_count", (0, 2, 65))
@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_declared_tool_count_must_match_archive_before_mutation(
    host: str, declared_tool_count: int, tmp_path: Path, fake_gh: Path
) -> None:
    """The declared tool_count must equal the verified archive contents and
    stay within 1..64; zero, out-of-range, and mismatching declarations all
    block before any filesystem mutation."""
    environment, home, _ = _environment(tmp_path, fake_gh)
    manifest_path = Path(environment["FAKE_GH_FIXTURE_ROOT"]) / "release-manifest.json"
    release = json.loads(manifest_path.read_text(encoding="utf-8"))
    release["session_tools_asset"]["tool_count"] = declared_tool_count
    manifest_path.write_bytes(_json_bytes(release))

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (home / ".claude" / "skills").exists()
    assert not (home / ".llm-foundation" / "state" / "session-tools" / "claude" / "active-transaction.json").exists()
    log = home / ".llm-foundation" / "state" / "session-tools" / "claude" / "events.log"
    assert "BLOCKED_MULTI_TOOL_ASSET" in log.read_text(encoding="utf-8")


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_multi_tool_asset_is_applied_transactionally_with_complete_state(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """A verified asset with several tools installs every destination and
    finishes with a complete schema-2 state describing all of them."""
    payloads = {
        "alpha-notes": "---\nname: alpha-notes\n---\nАльфа.\n".encode(),
        "beta-notes": "---\nname: beta-notes\n---\nБета.\n".encode(),
        "ru-writing-style": "---\nname: ru-writing-style\n---\nПиши ясно.\n".encode(),
    }
    environment, home, fixture = _environment(
        tmp_path, fake_gh, tool_payloads=payloads
    )

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "TOOLS_APPLIED_NEXT_SESSION" in result.stdout
    for tool_id, payload in payloads.items():
        destination = home / ".claude" / "skills" / tool_id / "SKILL.md"
        assert destination.read_bytes() == payload
    state_path = home / ".llm-foundation" / "state" / "session-tools" / "claude" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["schema_version"] == 2
    assert state["complete"] is True
    assert [tool["id"] for tool in state["tools"]] == sorted(payloads)
    assert not (
        home / ".llm-foundation" / "state" / "session-tools" / "claude" / "active-transaction.json"
    ).exists()
    log = home / ".llm-foundation" / "state" / "session-tools" / "claude" / "events.log"
    assert "APPLIED" in log.read_text(encoding="utf-8")


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_incomplete_schema_two_state_resumes_on_same_tag(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """A same-tag state marked incomplete must not answer NO_UPDATE; the
    updater finishes the snapshot and marks the state complete."""
    payloads = {
        "alpha-notes": "---\nname: alpha-notes\n---\nАльфа.\n".encode(),
        "beta-notes": "---\nname: beta-notes\n---\nБета.\n".encode(),
    }
    environment, home, _ = _environment(tmp_path, fake_gh, tool_payloads=payloads)
    first = _run(host, environment, "-HookFallback")
    assert first.returncode == 0, first.stdout + first.stderr
    state_path = home / ".llm-foundation" / "state" / "session-tools" / "claude" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["complete"] is True
    state["complete"] = False
    state_path.write_bytes(_json_bytes(state))

    second = _run(host, environment, "-HookFallback")

    assert second.returncode == 0, second.stdout + second.stderr
    resumed = json.loads(state_path.read_text(encoding="utf-8"))
    assert resumed["complete"] is True
    assert [tool["id"] for tool in resumed["tools"]] == sorted(payloads)


@pytest.mark.parametrize("mode", ("missing-gh", "offline"))
@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_missing_gh_and_offline_are_fail_open_without_mutation(
    host: str, mode: str, tmp_path: Path, fake_gh: Path
) -> None:
    """A trust dependency or network failure must preserve the verified local copy."""
    environment, home, _ = _environment(tmp_path, fake_gh)
    if mode == "missing-gh":
        environment["PATH"] = str(tmp_path / "empty-path")
    else:
        environment["FAKE_GH_LIST_EXIT"] = "7"
    result = _run(host, environment, "-HookFallback")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (home / ".claude" / "skills" / "ru-writing-style").exists()
    log = home / ".llm-foundation" / "state" / "session-tools" / "claude" / "events.log"
    expected = "BLOCKED_GH_REQUIRED" if mode == "missing-gh" else "SKIPPED_OFFLINE"
    assert expected in log.read_text(encoding="utf-8")


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_killed_apply_journal_is_recovered_before_network_check(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """A new run must restore old bytes from an applied move before contacting GitHub."""
    environment, home, _ = _environment(tmp_path, fake_gh)
    environment["PATH"] = str(tmp_path / "empty-path")
    state_root, previous, destination, journal = _seed_killed_apply(home)
    (state_root / "active-transaction.json").write_bytes(_json_bytes(journal))

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (destination / "SKILL.md").read_text(encoding="utf-8") == "старая версия\n"
    assert not previous.exists()
    assert not (state_root / "active-transaction.json").exists()


@pytest.mark.parametrize("has_previous", (False, True))
@pytest.mark.parametrize("partial_staging", (False, True))
@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_created_journal_recovers_absent_or_partial_staging(
    host: str, partial_staging: bool, has_previous: bool, tmp_path: Path, fake_gh: Path
) -> None:
    """Created owns absent or partial pre-mutation staging and can safely clean either."""
    environment, home, _ = _environment(tmp_path, fake_gh)
    environment["PATH"] = str(tmp_path / "empty-path")
    state_root = home / ".llm-foundation" / "state" / "session-tools" / "claude"
    transaction_id = "12345678-1234-1234-1234-123456789abc"
    transaction_root = state_root / "transactions" / transaction_id
    staging = transaction_root / "staging"
    previous = transaction_root / "previous"
    destination = home / ".claude" / "skills" / "ru-writing-style"
    destination.parent.mkdir(parents=True)
    old_hash = "absent"
    if has_previous:
        destination.mkdir()
        (destination / "SKILL.md").write_text("старая версия\n", encoding="utf-8")
        old_hash = _fingerprint(destination)
    expected_template = tmp_path / "expected-template"
    expected_template.mkdir()
    (expected_template / "SKILL.md").write_text("новая версия\n", encoding="utf-8")
    new_hash = _fingerprint(expected_template)
    receipt = home / ".llm-foundation" / "bin" / "claude-managed.receipt.json"
    frequency = 10_000_000
    start = 1
    journal = {
        "schema_version": 1, "target": "claude", "transaction_id": transaction_id,
        "phase": "created", "receipt_sha256": _sha256(receipt),
        "start_tick": start, "mutation_cutoff_tick": start + 22 * frequency,
        "kill_tick": start + 25 * frequency, "hard_deadline_tick": start + 30 * frequency,
        "stopwatch_frequency": frequency, "previous_destination_sha256": old_hash,
        "previous_state_sha256": "absent", "expected_staging_sha256": new_hash,
        "expected_destination_sha256": new_hash, "expected_state_sha256": "3" * 64,
        "staging_path": str(staging), "previous_path": str(previous),
        "destination_path": str(destination), "state_path": str(state_root / "state.json"),
        "operations": {
            "move_destination_to_previous": {"intent": False, "applied": False},
            "move_staging_to_destination": {"intent": False, "applied": False},
            "write_state": {"intent": False, "applied": False},
        },
    }
    state_root.mkdir(parents=True)
    if partial_staging:
        staging.mkdir(parents=True)
        (staging / "partial.tmp").write_text("неполный payload\n", encoding="utf-8")
    journal_path = state_root / "active-transaction.json"
    journal_path.write_bytes(_json_bytes(journal))

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _fingerprint(destination) == old_hash
    assert not staging.exists()
    assert not previous.exists()
    assert not journal_path.exists()


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_created_partial_staging_with_nested_reparse_is_preserved_and_blocked(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """Recovery must not recursively delete through a nested link in partial staging."""
    environment, home, _ = _environment(tmp_path, fake_gh)
    environment["PATH"] = str(tmp_path / "empty-path")
    state_root, staging, previous, destination, journal = _seed_move_crash_window(
        home, has_previous=False, phase="created", actual_step=0
    )
    neighbor = tmp_path / "neighbor"
    neighbor.mkdir()
    marker = neighbor / "keep.txt"
    marker.write_text("сохранить\n", encoding="utf-8")
    redirect = staging / "redirect"
    try:
        os.symlink(neighbor, redirect, target_is_directory=True)
    except OSError:
        junction = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(redirect), str(neighbor)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if junction.returncode != 0:
            pytest.skip("directory link creation is unavailable")
    journal_path = state_root / "active-transaction.json"
    journal_path.write_bytes(_json_bytes(journal))

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text(encoding="utf-8") == "сохранить\n"
    assert redirect.exists()
    assert staging.exists()
    assert not previous.exists()
    assert not destination.exists()
    assert journal_path.exists()
    assert "BLOCKED_SESSION_RECOVERY" in (state_root / "events.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_created_regular_file_staging_is_preserved_and_blocked(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """The exact staging leaf must be a real directory, never a regular file."""
    environment, home, _ = _environment(tmp_path, fake_gh)
    environment["PATH"] = str(tmp_path / "empty-path")
    state_root, staging, previous, destination, journal = _seed_move_crash_window(
        home, has_previous=False, phase="created", actual_step=0
    )
    shutil.rmtree(staging)
    staging_bytes = b"regular-file-staging\n"
    staging.write_bytes(staging_bytes)
    journal_path = state_root / "active-transaction.json"
    journal_path.write_bytes(_json_bytes(journal))

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert staging.is_file()
    assert staging.read_bytes() == staging_bytes
    assert not previous.exists()
    assert not destination.exists()
    assert journal_path.exists()
    assert "BLOCKED_SESSION_RECOVERY" in (state_root / "events.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_expired_hard_deadline_preserves_recovery_journal_and_blocks_managed_launch(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """Recovery and cleanup cannot continue after the launcher's 30-second deadline."""
    environment, home, _ = _environment(tmp_path, fake_gh)
    environment["PATH"] = str(tmp_path / "empty-path")
    state_root, staging, previous, destination, journal = _seed_move_crash_window(
        home, has_previous=False, phase="created", actual_step=0
    )
    now, frequency = _stopwatch(host)
    start = now - 31 * frequency
    journal.update(
        {
            "start_tick": start,
            "mutation_cutoff_tick": start + 22 * frequency,
            "kill_tick": start + 25 * frequency,
            "hard_deadline_tick": start + 30 * frequency,
            "stopwatch_frequency": frequency,
        }
    )
    journal_path = state_root / "active-transaction.json"
    journal_path.write_bytes(_json_bytes(journal))

    result = _run(
        host,
        environment,
        "-ManagedPreflight",
        "-TransactionId",
        journal["transaction_id"],
        "-StartTick",
        str(start),
        "-MutationCutoffTick",
        str(start + 22 * frequency),
        "-KillTick",
        str(start + 25 * frequency),
        "-HardDeadlineTick",
        str(start + 30 * frequency),
        "-StopwatchFrequency",
        str(frequency),
    )

    assert result.returncode == 65, result.stdout + result.stderr
    assert "BLOCKED_SESSION_RECOVERY" in result.stderr
    assert staging.exists()
    assert not previous.exists()
    assert not destination.exists()
    assert journal_path.exists()
    assert not (tmp_path / "gh.log").exists()


@pytest.mark.parametrize(
    ("has_previous", "phase", "actual_step"),
    [
        (False, "move_destination_applied", 1),
        (False, "move_staging_intent", 2),
        (True, "move_destination_intent", 1),
        (True, "move_staging_intent", 2),
    ],
)
@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_recovery_reconciles_move_before_applied_is_durable(
    host: str,
    has_previous: bool,
    phase: str,
    actual_step: int,
    tmp_path: Path,
    fake_gh: Path,
) -> None:
    """Updater and compiled launcher recover the same intent-to-applied crash windows."""
    environment, home, _ = _environment(tmp_path, fake_gh)
    environment["PATH"] = str(tmp_path / "empty-path")
    state_root, staging, previous, destination, journal = _seed_move_crash_window(
        home, has_previous=has_previous, phase=phase, actual_step=actual_step
    )
    journal_path = state_root / "active-transaction.json"
    journal_path.write_bytes(_json_bytes(journal))

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    if has_previous:
        assert (destination / "SKILL.md").read_text(encoding="utf-8") == "старая версия\n"
    else:
        assert not destination.exists()
    assert not staging.exists()
    assert not previous.exists()
    assert not journal_path.exists()


@pytest.mark.parametrize("host", _powershells(), ids=lambda value: Path(value).stem)
def test_malformed_journal_operation_map_blocks_without_cleanup(
    host: str, tmp_path: Path, fake_gh: Path
) -> None:
    """Updater recovery must reject the same non-canonical journal that launcher rejects."""
    environment, home, _ = _environment(tmp_path, fake_gh)
    environment["PATH"] = str(tmp_path / "empty-path")
    state_root, previous, destination, journal = _seed_killed_apply(home)
    journal["operations"]["unexpected"] = {"intent": False, "applied": False}
    journal_path = state_root / "active-transaction.json"
    journal_path.write_bytes(_json_bytes(journal))

    result = _run(host, environment, "-HookFallback")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (destination / "SKILL.md").read_text(encoding="utf-8") == "новая версия\n"
    assert (previous / "SKILL.md").read_text(encoding="utf-8") == "старая версия\n"
    assert journal_path.exists()
    log = state_root / "events.log"
    assert "BLOCKED_SESSION_RECOVERY" in log.read_text(encoding="utf-8")


def test_packaged_session_start_runs_updater_before_daily_check_and_has_cleanup_budget(
    tmp_path: Path,
) -> None:
    """Removing the fallback invocation or shortening its hook budget must fail."""
    runtime = tmp_path / "runtime"
    shutil.copytree(ROOT / "runtime", runtime)
    marker = tmp_path / "updater-ran.txt"
    (runtime / "update-session-tools.ps1").write_text(
        f"[IO.File]::WriteAllText('{str(marker).replace(chr(39), chr(39) * 2)}', 'ran')\n"
        "'TOOLS_APPLIED_NEXT_SESSION'\nexit 0\n",
        encoding="utf-8",
    )
    home = tmp_path / "home"
    result = subprocess.run(
        [_powershells()[0], "-NoProfile", "-File", str(runtime / "hooks" / "check-release.ps1")],
        env={**os.environ, "USERPROFILE": str(home)},
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text(encoding="utf-8") == "ran"
    settings = json.loads((runtime / "settings.json").read_text(encoding="utf-8"))
    hook = settings["hooks"]["SessionStart"][0]["hooks"][0]
    assert hook["timeout"] >= 38


def test_journal_is_durable_before_staging_and_uses_launcher_clock() -> None:
    """The source contract keeps mutation behind the durable singular journal."""
    source = UPDATER.read_text(encoding="utf-8")
    apply_start = source.index("function Apply-VerifiedTool")
    apply_end = source.index("$Lock = $null", apply_start)
    apply_source = source[apply_start:apply_end]
    assert apply_source.index("Write-DurableJson $JournalPath $Journal") < apply_source.index(
        "[IO.Directory]::CreateDirectory($Staging)"
    )
    assert "start_tick = $StartTick" in apply_source
    assert "mutation_cutoff_tick = $MutationCutoffTick" in apply_source
    assert "kill_tick = $KillTick" in apply_source
    assert "hard_deadline_tick = $HardDeadlineTick" in apply_source
    assert "stopwatch_frequency = $StopwatchFrequency" in apply_source
    assert (
        "expected_staging_sha256 = $ExpectedDirectory; "
        "expected_destination_sha256 = $ExpectedDirectory"
    ) in apply_source
    assert "$Journal.expected_staging_sha256" not in apply_source


def test_success_cleanup_reuses_reparse_scanning_helper_and_hard_deadline() -> None:
    """Committed cleanup must rescan previous and stay inside the 30-second contract."""
    source = UPDATER.read_text(encoding="utf-8")
    apply_source = source.split("function Apply-VerifiedTool", 1)[1].split("$Lock = $null", 1)[0]
    assert "Remove-JournalEntry $Previous" in apply_source
    assert "Remove-Item -LiteralPath $Previous -Recurse -Force" not in apply_source
    assert "Assert-BeforeHardDeadline" in apply_source


def test_native_runtime_does_not_modify_live_legacy_owner_automation(
    tmp_path: Path, fake_gh: Path
) -> None:
    """Native updater execution in an isolated home must leave legacy owner bytes untouched."""
    live = [
        Path.home() / ".claude" / "scripts" / "auto-pull.ps1",
        Path.home() / ".claude" / "settings.json",
    ]
    existing = [path for path in live if path.is_file()]
    if not existing:
        pytest.skip("live legacy Claude files are unavailable on this host")
    before = {path: path.read_bytes() for path in existing}
    environment, _, _ = _environment(tmp_path, fake_gh)
    result = _run(_powershells()[0], environment, "-HookFallback")
    assert result.returncode == 0, result.stdout + result.stderr
    assert {path: path.read_bytes() for path in existing} == before
