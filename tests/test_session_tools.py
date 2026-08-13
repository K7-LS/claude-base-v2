from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "claude_session_tools",
    ROOT / "tools" / "session_tools.py",
)
assert SPEC and SPEC.loader
session_tools = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = session_tools
SPEC.loader.exec_module(session_tools)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _manifest(
    tools: list[dict[str, object]], **overrides: object
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "target": "claude",
        "release_tag": "claude-v0.1.1",
        "base_version": "0.1.1",
        "tools": tools,
        **overrides,
    }


def _file_record(path: str, payload: bytes) -> dict[str, object]:
    return {
        "path": path,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def _write_archive(
    path: Path,
    manifest_bytes: bytes,
    payloads: dict[str, bytes],
) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("session-tools-manifest.json", manifest_bytes)
        for name, payload in payloads.items():
            archive.writestr(name, payload)


def test_builder_creates_deterministic_utf8_lf_zip_and_manifest(tmp_path: Path):
    first = session_tools.build_session_tools_bundle(ROOT, tmp_path / "one", "0.1.1")
    second = session_tools.build_session_tools_bundle(ROOT, tmp_path / "two", "0.1.1")

    assert first.zip_path.name == "session-tools-claude-0.1.1.zip"
    assert first.zip_path.read_bytes() == second.zip_path.read_bytes()
    assert first.manifest_bytes == second.manifest_bytes
    assert first.manifest_bytes.startswith(b"{")
    assert not first.manifest_bytes.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in first.manifest_bytes
    assert first.manifest_bytes.endswith(b"\n")
    assert first.manifest == session_tools.validate_session_tools_archive(first.zip_path)

    with zipfile.ZipFile(first.zip_path) as archive:
        assert archive.namelist() == [
            "session-tools-manifest.json",
            "tools/ru-writing-style/SKILL.md",
        ]
        assert all(
            info.date_time == (1980, 1, 1, 0, 0, 0)
            for info in archive.infolist()
        )


def test_manifest_parser_rejects_duplicate_json_keys():
    duplicate = (
        b'{"schema_version":1,"schema_version":1,"target":"claude",'
        b'"release_tag":"claude-v0.1.1","base_version":"0.1.1",'
        b'"tools":[]}'
    )

    with pytest.raises(ValueError, match="duplicate JSON key"):
        session_tools.validate_session_tools_manifest(duplicate)


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"schema_version": True}, "schema version"),
        ({"release_tag": "claude-v9.9.9"}, "release tag"),
    ],
)
def test_manifest_parser_rejects_bool_schema_and_mismatched_release_tag(
    overrides: dict[str, object],
    error: str,
):
    tool = {"id": "style", "files": [_file_record("SKILL.md", b"x")]}

    with pytest.raises(ValueError, match=error):
        session_tools.validate_session_tools_manifest(
            _json_bytes(_manifest([tool], **overrides))
        )


def test_manifest_parser_rejects_bool_file_size():
    tool = {
        "id": "style",
        "files": [{"path": "SKILL.md", "sha256": "0" * 64, "bytes": True}],
    }

    with pytest.raises(ValueError, match="file size"):
        session_tools.validate_session_tools_manifest(_json_bytes(_manifest([tool])))


@pytest.mark.parametrize(
    "tools",
    [
        [
            {"id": "style", "files": [_file_record("SKILL.md", b"a")]},
            {"id": "STYLE", "files": [_file_record("SKILL.md", b"b")]},
        ],
        [
            {
                "id": "style",
                "files": [
                    _file_record("SKILL.md", b"a"),
                    _file_record("skill.md", b"b"),
                ],
            }
        ],
    ],
)
def test_manifest_parser_rejects_windows_case_collisions(
    tools: list[dict[str, object]],
):
    with pytest.raises(ValueError, match="case collision"):
        session_tools.validate_session_tools_manifest(_json_bytes(_manifest(tools)))


@pytest.mark.parametrize(
    "value",
    [
        "../SKILL.md",
        "/SKILL.md",
        "C:/SKILL.md",
        "nested\\SKILL.md",
        "tool.ps1",
        "tool.exe",
    ],
)
def test_manifest_parser_rejects_unsafe_or_executable_paths(value: str):
    tool = {"id": "style", "files": [_file_record(value, b"x")]}

    with pytest.raises(ValueError):
        session_tools.validate_session_tools_manifest(_json_bytes(_manifest([tool])))


def test_archive_rejects_duplicate_members_symlinks_and_tampered_bytes(tmp_path: Path):
    payload = b"skill"
    tool = {"id": "style", "files": [_file_record("SKILL.md", payload)]}
    manifest = _json_bytes(_manifest([tool]))

    duplicate = tmp_path / "duplicate.zip"
    _write_archive(
        duplicate,
        manifest,
        {
            "tools/style/SKILL.md": payload,
            "tools/style/other.md": b"unexpected",
        },
    )
    with pytest.raises(ValueError, match="unexpected"):
        session_tools.validate_session_tools_archive(duplicate)

    symlink = tmp_path / "symlink.zip"
    with zipfile.ZipFile(symlink, "w") as archive:
        archive.writestr("session-tools-manifest.json", manifest)
        info = zipfile.ZipInfo("tools/style/SKILL.md")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, b"target")
    with pytest.raises(ValueError, match="symlink"):
        session_tools.validate_session_tools_archive(symlink)

    tampered = tmp_path / "tampered.zip"
    _write_archive(tampered, manifest, {"tools/style/SKILL.md": b"alter"})
    with pytest.raises(ValueError, match="SHA-256"):
        session_tools.validate_session_tools_archive(tampered)


def test_archive_rejects_exact_and_case_only_duplicate_members(tmp_path: Path):
    payload = b"skill"
    tool = {"id": "style", "files": [_file_record("SKILL.md", payload)]}
    manifest = _json_bytes(_manifest([tool]))

    exact = tmp_path / "exact-duplicate.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(exact, "w") as archive:
            archive.writestr("session-tools-manifest.json", manifest)
            archive.writestr("tools/style/SKILL.md", payload)
            archive.writestr("tools/style/SKILL.md", payload)
    with pytest.raises(ValueError, match="duplicate"):
        session_tools.validate_session_tools_archive(exact)

    case_only = tmp_path / "case-only-duplicate.zip"
    with zipfile.ZipFile(case_only, "w") as archive:
        archive.writestr("session-tools-manifest.json", manifest)
        archive.writestr("tools/style/SKILL.md", payload)
        archive.writestr("tools/style/skill.md", payload)
    with pytest.raises(ValueError, match="case collision"):
        session_tools.validate_session_tools_archive(case_only)


def test_archive_rejects_executable_member_and_manifest_hash_tamper(tmp_path: Path):
    payload = b"skill"
    tool = {"id": "style", "files": [_file_record("SKILL.md", payload)]}
    manifest = _json_bytes(_manifest([tool]))
    archive_path = tmp_path / "executable.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("session-tools-manifest.json", manifest)
        info = zipfile.ZipInfo("tools/style/SKILL.md")
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        archive.writestr(info, payload)

    with pytest.raises(ValueError, match="executable"):
        session_tools.validate_session_tools_archive(archive_path)
    clean_archive = tmp_path / "clean.zip"
    _write_archive(clean_archive, manifest, {"tools/style/SKILL.md": payload})
    with pytest.raises(ValueError, match="manifest SHA-256"):
        session_tools.validate_session_tools_archive(clean_archive, manifest_sha256="0" * 64)


def test_manifest_parser_enforces_design_limits():
    tools = [
        {"id": f"tool-{index:02}", "files": [_file_record("SKILL.md", b"x")]}
        for index in range(33)
    ]
    with pytest.raises(ValueError, match="tool limit"):
        session_tools.validate_session_tools_manifest(_json_bytes(_manifest(tools)))

    files = sorted(
        [_file_record(f"nested/{index}.md", b"x") for index in range(257)],
        key=lambda record: str(record["path"]),
    )
    with pytest.raises(ValueError, match="file limit"):
        session_tools.validate_session_tools_manifest(
            _json_bytes(_manifest([{"id": "style", "files": files}]))
        )

    too_large = {"path": "large.md", "sha256": "0" * 64, "bytes": 1024 * 1024 + 1}
    with pytest.raises(ValueError, match="file size limit"):
        session_tools.validate_session_tools_manifest(
            _json_bytes(_manifest([{"id": "style", "files": [too_large]}]))
        )

    expanded = [
        {"path": f"file-{index}.md", "sha256": "0" * 64, "bytes": 1024 * 1024}
        for index in range(9)
    ]
    with pytest.raises(ValueError, match="expanded size limit"):
        session_tools.validate_session_tools_manifest(
            _json_bytes(_manifest([{"id": "style", "files": expanded}]))
        )


def test_builder_rejects_source_symlink_and_executable(tmp_path: Path):
    clone = tmp_path / "clone"
    source = clone / "skills" / "ru-writing-style"
    source.mkdir(parents=True)
    skill = source / "SKILL.md"
    skill.write_text("safe\n", encoding="utf-8")
    link = source / "linked.md"
    try:
        os.symlink(skill, link)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(ValueError, match="symlink"):
        session_tools.build_session_tools_bundle(clone, tmp_path / "dist", "0.1.1")

    link.unlink()
    if os.name == "nt":
        return
    executable = source / "run.md"
    executable.write_text("not executable\n", encoding="utf-8")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(ValueError, match="executable"):
        session_tools.build_session_tools_bundle(clone, tmp_path / "dist", "0.1.1")


def test_archive_rejects_zip_size_limit(tmp_path: Path, monkeypatch):
    payload = b"skill"
    tool = {"id": "style", "files": [_file_record("SKILL.md", payload)]}
    archive_path = tmp_path / "asset.zip"
    _write_archive(
        archive_path,
        _json_bytes(_manifest([tool])),
        {"tools/style/SKILL.md": payload},
    )
    monkeypatch.setattr(session_tools, "MAX_ARCHIVE_BYTES", 1)

    with pytest.raises(ValueError, match="ZIP size limit"):
        session_tools.validate_session_tools_archive(archive_path)
